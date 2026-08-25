"""Remote access: reaching this desktop from your phone, safely.

AgentOS is a browser desktop with a real shell behind it. Serving that to
anything beyond loopback is a decision with consequences, so this module exists
to make the decision explicit and then hold the line:

  * It is OFF until a human turns it on AND there is a lock on the door. There
    is no code path that enables it without both — not the agent's
    configure_agentos tool, not an app, not a config file push
    (`sanitize_remote` re-checks on load).
  * The lock is one of two things. On a single-user machine it is a shared
    passphrase. On a machine with accounts it is the ACCOUNTS: the phone in
    somebody's pocket signs in with the same username and password as the
    desktop, and no second shared secret is invented in front of them. A door
    only some people have the key to is a door that gets propped open.
  * Loopback stays trusted, so turning it on changes nothing about using AgentOS
    on the machine it runs on. A LAN client cannot forge a loopback source
    address to the kernel, so this is a real boundary rather than a header check.
  * Everything else needs a signed session cookie: passphrase -> PBKDF2 ->
    HMAC-signed token. The passphrase itself is never stored.
  * Failed attempts back off per source address, so a weak passphrase cannot be
    brute-forced at network speed.

The threat model is honest about what it is not. With a passphrase this is one
shared secret protecting one machine; with accounts it is real per-person auth,
but still one process, one host and one kernel — a signed-in executor is not
sandboxed from the machine, only from other people's data. Either way it expects
to be behind your home network or a VPN rather than on the open internet.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time

COOKIE = "agentos_session"
PBKDF2_ROUNDS = 210_000          # OWASP's 2023 floor for PBKDF2-HMAC-SHA256
MIN_PASSPHRASE = 8
LOCKOUT_AFTER = 5                # failures from one address before it waits
LOCKOUT_SECS = 60                # ...and how long it waits, doubling to a cap
LOCKOUT_MAX = 3600

# in-process, deliberately: a restart clearing the backoff is fine, and it keeps
# a brute-force attempt from writing unbounded rows to the store
_fails: dict[str, list] = {}     # addr -> [count, unlock_at]


# ---------------------------------------------------------------------------
# passphrase
# ---------------------------------------------------------------------------

def hash_passphrase(passphrase: str, salt: str = "") -> tuple[str, str]:
    """(hash, salt), both hex. A fresh salt is generated when none is given."""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return dk.hex(), salt


def check_passphrase(cfg: dict, passphrase: str) -> bool:
    r = cfg.get("remote") or {}
    if not r.get("pass_hash") or not r.get("pass_salt"):
        return False
    try:
        got, _ = hash_passphrase(passphrase, r["pass_salt"])
    except ValueError:
        return False
    return hmac.compare_digest(got, r["pass_hash"])


def passphrase_problem(passphrase: str) -> str:
    """Empty string when it's acceptable, else why not — shown to the user."""
    if len(passphrase or "") < MIN_PASSPHRASE:
        return f"use at least {MIN_PASSPHRASE} characters"
    if passphrase.lower() in ("password", "agentos", "12345678", "changeme", "letmein"):
        return "that passphrase is on every guessing list"
    return ""


# ---------------------------------------------------------------------------
# session tokens
# ---------------------------------------------------------------------------

def _machine_key() -> bytes:
    """A random per-machine signing key, on disk at 0600.

    There has to be one. The passphrase hash below is a fine secret when remote
    access is on, but a multi-user machine on a private LAN may never turn remote
    access on at all — and a cookie signed with a constant is a cookie anybody can
    write, including the `uid` field that decides whose directory gets opened.

    On disk rather than in the config because the config gets exported, copied
    into bug reports and read by every surface; this is only ever read here.
    """
    from . import config as cfgmod
    p = cfgmod.AGENTOS_HOME / "session.key"
    try:
        if p.exists():
            got = p.read_bytes().strip()
            if len(got) >= 32:
                return got
    except OSError:
        pass
    key = secrets.token_hex(32).encode()
    try:
        cfgmod.AGENTOS_HOME.mkdir(parents=True, exist_ok=True)
        p.write_bytes(key)
        os.chmod(p, 0o600)
    except OSError:
        pass                    # read-only home: still better than a constant
    return key


def _secret(cfg: dict) -> bytes:
    """Sessions are signed with the passphrase hash, so changing the passphrase
    invalidates every device that was signed in with the old one — and with the
    machine key underneath it, so a machine with no passphrase still signs with
    something nobody else can guess."""
    r = cfg.get("remote") or {}
    return _machine_key() + (r.get("pass_hash", "") + r.get("pass_salt", "")).encode()


def issue_session(cfg: dict, uid: str = "", locked: bool = False) -> str:
    """A signed cookie.

    `uid` rides inside it because on a multi-user machine the cookie has to say
    WHO, not merely that somebody proved something once.

    `locked` rides inside it for the same kind of reason. A locked screen has to
    survive a reload, a second tab, a restored browser session and a server
    restart, and no script running in the page may clear it — so it cannot be a
    flag in the desktop, a class on the body, or a row in memory. It is part of
    what the cookie SAYS, under the same signature as the identity.
    """
    days = int((cfg.get("remote") or {}).get("session_days") or 30)
    claims = {"exp": int(time.time()) + days * 86400,
              "uid": uid or "",
              "jti": secrets.token_hex(8)}
    if locked:
        claims["lk"] = 1              # absent, not 0, so an old cookie reads as open
    payload = json.dumps(claims, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(_secret(cfg), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def session_claims(cfg: dict, token: str) -> dict | None:
    """The verified contents of a session cookie, or None if it is not one.

    ONE verify path on purpose. The signature check, the expiry, the identity and
    the lock are the same operation, and asking them in four places is how a route
    ends up trusting half a cookie — a uid it never verified, or a lock it never
    looked for.
    """
    if not token or "." not in token:
        return None
    body, _, sig = token.rpartition(".")
    want = hmac.new(_secret(cfg), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, want):
        return None
    try:
        pad = "=" * (-len(body) % 4)
        d = json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception:
        return None
    if not isinstance(d, dict) or d.get("exp", 0) <= time.time():
        return None
    return d


def session_user(cfg: dict, token: str) -> str | None:
    """The user id inside a valid session cookie, or None if it does not verify."""
    d = session_claims(cfg, token)
    return None if d is None else str(d.get("uid") or "")


def valid_session(cfg: dict, token: str) -> bool:
    return session_claims(cfg, token) is not None


def session_locked(cfg: dict, token: str) -> bool:
    """Has whoever holds this cookie locked their screen?

    A cookie that does not verify is not locked — it is nobody, which every gate
    refuses for a different reason. Keeping those two answers apart is what lets
    the lock screen say "enter your password" to one and "sign in" to the other.
    """
    d = session_claims(cfg, token)
    return bool(d and d.get("lk"))


# ---------------------------------------------------------------------------
# who is allowed through
# ---------------------------------------------------------------------------

def is_loopback(host: str) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return host in ("localhost", "testclient")   # starlette's TestClient


def accounts_lock() -> bool:
    """Do this machine's user accounts serve as the lock?

    Once there are accounts they ARE the credentials, and a second shared
    passphrase in front of them is worse than none: it is one more secret, held
    in common by people who are otherwise isolated from each other, and it makes
    "sign in" mean two different things depending on where you are standing. So a
    multi-user machine is locked by definition, and the phone in somebody's
    pocket signs in with the same username and password as the desktop.
    """
    from . import users as usersmod
    return usersmod.enabled()


def lock_kind(cfg: dict) -> str:
    """Which lock is on the door: 'accounts', 'passphrase', or '' for neither.

    Accounts win when both exist — the passphrase becomes dead config rather than
    a second door, because a door only some people have the key to is a door that
    will be propped open.
    """
    if accounts_lock():
        return "accounts"
    return "passphrase" if (cfg.get("remote") or {}).get("pass_hash") else ""


def enabled(cfg: dict) -> bool:
    """Remote access counts as on only when it is BOTH switched on and locked."""
    r = cfg.get("remote") or {}
    return bool(r.get("enabled")) and bool(lock_kind(cfg))


def sanitize_remote(cfg: dict) -> dict:
    """Re-assert the invariant every time config is loaded or written: enabled
    without a lock is not a state this system has.

    `enabled` is left alone rather than forced off when there is no lock — the
    stored intent survives, and `enabled()` above refuses until a lock exists.
    Zeroing it would mean that adding the first account silently un-remembered a
    machine that was deliberately reachable before.
    """
    r = cfg.setdefault("remote", {})
    if r.get("enabled") and not r.get("pass_hash") and not accounts_lock():
        r["enabled"] = False
    return cfg


def bind_host(cfg: dict) -> str:
    """The interface the server should listen on — loopback unless remote access
    is genuinely on. This is the single place that decision is made."""
    if not enabled(cfg):
        return "127.0.0.1"
    return (cfg.get("remote") or {}).get("bind") or "0.0.0.0"


# ---------------------------------------------------------------------------
# brute-force backoff
# ---------------------------------------------------------------------------

def locked_for(addr: str) -> int:
    """Seconds this address must wait, 0 if it may try now."""
    ent = _fails.get(addr)
    if not ent:
        return 0
    return max(0, int(ent[1] - time.time()))


def note_failure(addr: str) -> int:
    ent = _fails.setdefault(addr, [0, 0.0])
    ent[0] += 1
    if ent[0] >= LOCKOUT_AFTER:
        # double the wait for each failure past the threshold, up to the cap
        wait = min(LOCKOUT_MAX, LOCKOUT_SECS * (2 ** (ent[0] - LOCKOUT_AFTER)))
        ent[1] = time.time() + wait
        return wait
    return 0


def note_success(addr: str):
    _fails.pop(addr, None)


def reset_failures():
    _fails.clear()


# ---------------------------------------------------------------------------
# what to tell the user
# ---------------------------------------------------------------------------

def lan_addresses(port: int) -> list[str]:
    """Best-effort list of URLs this machine is reachable at, for the QR/copy UI.
    A UDP socket to a public address never sends a packet; it just asks the
    routing table which local interface would be used."""
    import socket
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        out.append(f"http://{s.getsockname()[0]}:{port}")
        s.close()
    except Exception:
        pass
    try:
        host = socket.gethostname()
        # `.local` is APPENDED, so a hostname that already carries it must not get a
        # second one. macOS's gethostname() returns the mDNS name in full — this
        # produced `http://Someones-MacBook-Pro.local.local:8321`, an address that
        # resolves nowhere, printed as the way to reach the machine from a phone.
        # Strip any trailing dot too: a fully-qualified name may end in one.
        host = (host or "").rstrip(".")
        if host.endswith(".local"):
            host = host[: -len(".local")]
        if host and not host.startswith("localhost"):
            out.append(f"http://{host}.local:{port}")
    except Exception:
        pass
    return out


def status(cfg: dict) -> dict:
    r = cfg.get("remote") or {}
    port = int(cfg.get("port") or 8321)
    return {
        "enabled": enabled(cfg),
        "configured": bool(lock_kind(cfg)),
        "lock": lock_kind(cfg),
        "bind": r.get("bind") or "0.0.0.0",
        "port": port,
        "session_days": int(r.get("session_days") or 30),
        "trust_loopback": bool(r.get("trust_loopback", True)),
        "addresses": lan_addresses(port) if enabled(cfg) else [],
        "listening_on": os.environ.get("AGENTOS_BOUND_HOST", ""),
    }
