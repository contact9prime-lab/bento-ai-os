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
    It is only ever given to a real loopback peer: with a Host this machine answers
    to (a rebinding page has its own), no proxy's headers, and not a process this
    server started (peercheck.py). Remote off means the network gets nothing, never
    that there is nothing to gate.
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
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time

# Cookies ignore ports. A second Bento on 127.0.0.1 (the warehouse demo's four) would overwrite this
# machine's own sign-in with its cookie unless each has a name of its own.
COOKIE = os.environ.get("AGENTOS_SESSION_COOKIE") or "agentos_session"
PBKDF2_ROUNDS = 210_000          # OWASP's 2023 floor for PBKDF2-HMAC-SHA256
MIN_PASSPHRASE = 8
LOCKOUT_AFTER = 5                # failures from one address before it waits
LOCKOUT_SECS = 60                # ...and how long it waits, doubling to a cap
LOCKOUT_MAX = 3600
TARGET_AFTER = 10                # failures against one account, from anywhere, before it waits
TARGET_KEEP = 2048               # names counted; every name counts, or a lock would say which exist

# in-process, deliberately: a restart clearing the backoff is fine, and it keeps
# a brute-force attempt from writing unbounded rows to the store
_fails: dict[str, list] = {}     # addr -> [count, unlock_at]
_target_fails: dict[str, list] = {}  # account -> [count, unlock_at]


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
        # 0600 from its first byte, and EXCL so two processes starting together agree on one key
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    except FileExistsError:
        with contextlib.suppress(OSError):
            got = p.read_bytes().strip()
            if len(got) >= 32:
                return got
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
    gen = session_gen(cfg, uid)
    if gen:
        claims["g"] = gen             # absent, not 0, so a cookie from before this reads the same
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
    return _verify(cfg, token)[0]


def _verify(cfg: dict, token: str) -> tuple[dict | None, str]:
    """(claims, '') for a good cookie, else (None, why): none, forged, expired, ended."""
    if not token:
        return None, "none"
    if "." not in token:
        return None, "forged"
    body, _, sig = token.rpartition(".")
    want = hmac.new(_secret(cfg), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig.encode(), want.encode()):
        return None, "forged"
    try:
        pad = "=" * (-len(body) % 4)
        d = json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception:
        return None, "forged"
    if not isinstance(d, dict):
        return None, "forged"
    if d.get("exp", 0) <= time.time():
        return None, "expired"
    # Signature and expiry alone meant a copied cookie worked for 30 days after a password change.
    try:
        if int(d.get("g") or 0) != session_gen(cfg, str(d.get("uid") or "")):
            return None, "ended"
    except (TypeError, ValueError):
        return None, "forged"
    if str(d.get("jti") or "") in _denied():
        return None, "ended"
    return d, ""


def cookie_forged(cfg: dict, token: str) -> bool:
    """Did somebody present a cookie this machine did not sign? An expired or ended one is an honest
    browser, and is not news. A passphrase change makes old cookies read as forged, because the signature
    covers its hash: `quiet_forgeries` holds the alarm for the time those browsers take to come back."""
    return _verify(cfg, token)[1] == "forged" and time.time() >= _forgery_quiet[0]


_forgery_quiet = [0.0]


def quiet_forgeries(seconds: int = 3600) -> None:
    _forgery_quiet[0] = time.time() + seconds


def session_gen(cfg: dict, uid: str) -> int:
    """The generation a session of this account must carry. On a machine with no accounts it is the
    machine's, under `remote`."""
    if uid:
        from . import users as usersmod
        return usersmod.session_gen(uid)
    with contextlib.suppress(TypeError, ValueError):
        return int((cfg.get("remote") or {}).get("sgen") or 0)
    return 0


def _denied_path():
    from . import config as cfgmod
    return cfgmod.AGENTOS_HOME / "session-denied.json"


_denied_cache: dict = {"path": "", "mtime": -1, "ids": {}}


def _denied() -> dict:
    """The one-browser half of revoking: this cookie, not the account's other devices. A sign-out or a
    lock ends the cookie it replaces, and the id is kept until the cookie would have expired anyway,
    which is what keeps this file small. It is read back on a restart: a lock a restart forgot would be
    undone by copying the cookie from before it."""
    p = _denied_path()
    try:
        m = p.stat().st_mtime_ns
    except OSError:
        return {}
    if _denied_cache["path"] == str(p) and _denied_cache["mtime"] == m:
        return _denied_cache["ids"]
    ids = {}
    with contextlib.suppress(OSError, ValueError):
        got = json.loads(p.read_text())
        ids = got if isinstance(got, dict) else {}
    _denied_cache.update(path=str(p), mtime=m, ids=ids)
    return ids


def end_session(claims: dict | None) -> None:
    """This one cookie stops working, here and in any copy of it."""
    jti, exp = str((claims or {}).get("jti") or ""), (claims or {}).get("exp", 0)
    if not jti:
        return
    from . import config as cfgmod
    now = time.time()
    ids = {k: v for k, v in _denied().items() if isinstance(v, (int, float)) and v > now}
    ids[jti] = exp
    with contextlib.suppress(OSError):
        cfgmod.write_private(_denied_path(), json.dumps(ids))


def _desk_flag():
    from . import config as cfgmod
    return cfgmod.AGENTOS_HOME / "session.locked"


def desk_locked(cfg: dict) -> bool:
    """On a single-user machine a lock in the cookie covers one browser, and loopback trust let a private
    window straight past it. This flag switches that trust off until somebody proves they hold the key.
    A machine with no key cannot be flagged, because nothing could ever clear it."""
    return bool(lock_kind(cfg)) and _desk_flag().exists()


def set_desk_locked(on: bool) -> None:
    from . import config as cfgmod
    with contextlib.suppress(OSError):
        if on:
            cfgmod.write_private(_desk_flag(), "1")
        else:
            _desk_flag().unlink(missing_ok=True)


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


# Headers a proxy adds. A tunnel or nginx arrives from 127.0.0.1, so the socket alone would call everybody
# behind it local. A browser never sends these on its own, and a local process that does only makes
# itself less trusted.
FORWARDED = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host", "x-forwarded-proto",
             "cf-connecting-ip", "true-client-ip", "tailscale-user-login")


def client_addr(peer: str, headers) -> str:
    """Who to treat this request as coming from: the socket, unless the socket is loopback and a proxy
    says it is carrying somebody else. Then the address the nearest proxy appended (the last one; earlier
    ones are whatever the client sent), so each visitor has a backoff of their own, and `forwarded` when
    that says nothing usable. Never loopback: the person behind a tunnel is not at this machine."""
    if not is_loopback(peer) or not any(headers.get(h) for h in FORWARDED):
        return peer
    last = str(headers.get("x-forwarded-for") or "").split(",")[-1].strip()
    with contextlib.suppress(ValueError):
        if not ipaddress.ip_address(last).is_loopback:
            return last
    return "forwarded"


# The Host names this machine answers to. A DNS rebinding page reaches 127.0.0.1 with its own name in Host
# and a matching Origin, so comparing those two proves nothing: the only thing it cannot fake is a name
# this list has. An IP literal is always fine. Rebinding needs a NAME to re-point, and an address behind
# NAT or a container's port map is not one of this machine's own, so a list of addresses would only lock
# out a phone. The suffixes are the ones a home router or mDNS hands out and nobody can register.
_LOCAL_SUFFIXES = ("local", "lan", "home", "internal", "intranet", "localdomain", "home.arpa", "fritz.box")
_learned_names: set[str] = set()


def parse_host(value: str) -> str | None:
    """The name in a Host header, lower case, with no port. None when it is not a well-formed one."""
    v = (value or "").strip().lower()
    if v.startswith("["):
        end = v.find("]")
        if end < 0 or v[end + 1:] not in ("",) and not v[end + 1:].startswith(":"):
            return None
        return v[1:end]
    name, _, port = v.partition(":")
    if port and not port.isdigit():
        return None
    name = name.rstrip(".")
    if not name or any(not (c.isalnum() or c in "-._") for c in name):
        return None
    return name


def learn_names() -> None:
    """The fully qualified name can take a DNS timeout to find, so the server asks once, off to the side."""
    import socket
    with contextlib.suppress(Exception):
        n = socket.getfqdn().strip().lower().rstrip(".")
        if n and n != "localhost" and not n.startswith("localhost."):
            _learned_names.add(n)


def declared_hosts(cfg: dict) -> list[str]:
    """What the owner and the hosting platform have said this machine is called."""
    from urllib.parse import urlsplit
    out = [str(h).strip().lower() for h in ((cfg.get("remote") or {}).get("allowed_hosts") or []) if h]
    out += [h.strip().lower() for h in (os.environ.get("AGENTOS_ALLOWED_HOSTS") or "").split(",") if h.strip()]
    # what a hosting platform tells its service. A name set by the host's own environment
    with contextlib.suppress(ValueError):
        h = urlsplit(os.environ.get("RENDER_EXTERNAL_URL") or "").hostname
        if h:
            out.append(h.lower())
    if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        out.append(os.environ["RENDER_EXTERNAL_HOSTNAME"].strip().lower())
    if os.environ.get("FLY_APP_NAME"):
        out.append(f"{os.environ['FLY_APP_NAME'].strip().lower()}.fly.dev")
    with contextlib.suppress(Exception):
        from . import tunnel
        h = urlsplit(tunnel.cloudflared_url()).hostname
        if h:
            out.append(h.lower())
    for key in (((cfg.get("mcp_oauth") or {}).get("redirect_base")),):
        with contextlib.suppress(ValueError):
            h = urlsplit(str(key or "")).hostname
            if h:
                out.append(h.lower())
    return out


def host_allowed(cfg: dict, host_header: str) -> bool:
    """May a request naming this Host be answered? Checked before anything decides who it is."""
    import socket
    if not (host_header or "").strip():
        return True             # HTTP/1.0: no browser sends this, so it cannot be a rebinding page
    name = parse_host(host_header)
    if name is None:
        return False
    with contextlib.suppress(ValueError):
        ipaddress.ip_address(name.split("%")[0])
        return True
    if name == "localhost" or name.endswith(".localhost"):
        return True             # browsers resolve these to loopback themselves, whatever DNS says
    if name.endswith((".ts.net", ".tailscale.net")):
        return True             # Tailscale serves these records. A stranger's page cannot re-point one
    own = {(socket.gethostname() or "").strip().lower().rstrip(".")}
    own.add(str((cfg.get("team") or {}).get("machine_name") or "").strip().lower())
    own |= _learned_names
    for o in list(own):
        if o.endswith(".local"):
            own.add(o[: -len(".local")])
    own.discard("")
    if name in own:
        return True
    first, _, rest = name.partition(".")
    # avahi renames a machine that finds its name taken: pi.local becomes pi-2.local
    base = first.rsplit("-", 1)[0] if first.rsplit("-", 1)[-1].isdigit() else first
    if (first in own or base in own) and rest in _LOCAL_SUFFIXES:
        return True
    for h in declared_hosts(cfg):
        if h == "*" or h == name or (h.startswith("*.") and name.endswith(h[1:])):
            return True
    return False


# A per-run key on a Bento nobody should reach by being on loopback (the warehouse demo's servers, which
# are on this machine's loopback with no accounts). It is a file in that home, so the machine's own jail
# (which blanks /home) cannot read it, and an environment variable would be readable in /proc by anything
# else the server starts.
ENTRY_FILE = "entry.token"
_entry_cache: dict = {}


def entry_token() -> str:
    """This home's entry key, '' on an ordinary machine. Written before the server starts."""
    from . import config as cfgmod
    key = str(cfgmod.AGENTOS_HOME)
    if key not in _entry_cache:
        got = ""
        with contextlib.suppress(OSError):
            got = (cfgmod.AGENTOS_HOME / ENTRY_FILE).read_text().strip()
        _entry_cache[key] = got
    return _entry_cache[key]


def entry_matches(presented: str) -> bool:
    want = entry_token()
    return bool(want) and bool(presented) and hmac.compare_digest(str(presented).encode(), want.encode())


# A browser this server starts for the person is its descendant, so peercheck would refuse it as it refuses
# a jailed shell. It arrives with a ticket instead and leaves with a cookie. Signed with the machine key, so
# `bento app` can mint one for a server in another process; good once and for TICKET_S, because argv is
# readable by other processes of this user for as long as that browser runs.
TICKET_S = 120
_tickets_used: dict[str, float] = {}


def mint_ticket() -> str:
    exp = str(int(time.time()) + TICKET_S)
    nonce = secrets.token_hex(8)
    sig = hmac.new(_machine_key(), f"desk|{exp}|{nonce}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{nonce}.{sig}"


def spend_ticket(ticket: str) -> bool:
    try:
        exp, nonce, sig = str(ticket).split(".")
        if int(exp) <= time.time():
            return False
    except ValueError:
        return False
    want = hmac.new(_machine_key(), f"desk|{exp}|{nonce}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig.encode(), want.encode()) or nonce in _tickets_used:
        return False
    now = time.time()
    for k, v in list(_tickets_used.items()):
        if v <= now:
            _tickets_used.pop(k, None)
    _tickets_used[nonce] = int(exp)
    return True


def ticket_url(url: str) -> str:
    """This URL with a ticket, for a browser about to be started from this process. A machine with
    accounts signs in as usual, so it gets none."""
    from urllib.parse import urlsplit, urlunsplit
    if accounts_lock():
        return url
    with contextlib.suppress(Exception):
        u = urlsplit(url)
        return urlunsplit((u.scheme, u.netloc, u.path or "/", f"desk={mint_ticket()}", u.fragment))
    return url


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
        wait = min(LOCKOUT_MAX, LOCKOUT_SECS * (2 ** min(ent[0] - LOCKOUT_AFTER, 16)))
        ent[1] = time.time() + wait
        return wait
    return 0


def note_success(addr: str):
    _fails.pop(addr, None)


def reset_failures():
    _fails.clear()
    _target_fails.clear()


def target_locked_for(name: str) -> int:
    """Seconds anybody must wait before guessing at this account again, wherever they are."""
    ent = _target_fails.get(str(name or "").lower())
    return max(0, int(ent[1] - time.time())) if ent else 0


def note_target_failure(name: str) -> int:
    """One account, counted apart from the source. Per source alone, four guesses at the admin and one
    good sign-in to your own account reset the count for ever. Any name counts, so that being locked says
    nothing about whether a name exists, and the table is bounded because the names are the attacker's."""
    key = str(name or "").lower()[:64]
    if key not in _target_fails and len(_target_fails) >= TARGET_KEEP:
        for k in sorted(_target_fails, key=lambda k: _target_fails[k][1])[:TARGET_KEEP // 4]:
            _target_fails.pop(k, None)
    ent = _target_fails.setdefault(key, [0, 0.0])
    ent[0] += 1
    if ent[0] >= TARGET_AFTER:
        wait = min(LOCKOUT_MAX, LOCKOUT_SECS * (2 ** min(ent[0] - TARGET_AFTER, 16)))
        ent[1] = time.time() + wait
        return wait
    return 0


def note_target_success(name: str) -> None:
    """Only this account's own password clears its count."""
    _target_fails.pop(str(name or "").lower()[:64], None)


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
        "allowed_hosts": list(r.get("allowed_hosts") or []),
        "addresses": lan_addresses(port) if enabled(cfg) else [],
        "listening_on": os.environ.get("AGENTOS_BOUND_HOST", ""),
    }
