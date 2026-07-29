"""Remote access: reaching this desktop from your phone, safely.

AgentOS is a browser desktop with a real shell behind it. Serving that to
anything beyond loopback is a decision with consequences, so this module exists
to make the decision explicit and then hold the line:

  * It is OFF until a human turns it on AND sets a passphrase. There is no code
    path that enables it without both — not the agent's configure_agentos tool,
    not an app, not a config file push (`sanitize_remote` re-checks on load).
  * Loopback stays trusted, so turning it on changes nothing about using AgentOS
    on the machine it runs on. A LAN client cannot forge a loopback source
    address to the kernel, so this is a real boundary rather than a header check.
  * Everything else needs a signed session cookie: passphrase -> PBKDF2 ->
    HMAC-signed token. The passphrase itself is never stored.
  * Failed attempts back off per source address, so a weak passphrase cannot be
    brute-forced at network speed.

The threat model is honest about what it is not: this is one shared passphrase
protecting one machine, not multi-user auth. It is the lock on your front door,
and it expects to be behind your home network or a VPN rather than on the open
internet.
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

def _secret(cfg: dict) -> bytes:
    """Sessions are signed with the passphrase hash, so changing the passphrase
    invalidates every device that was signed in with the old one."""
    r = cfg.get("remote") or {}
    return (r.get("pass_hash", "") + r.get("pass_salt", "")).encode() or b"agentos-unset"


def issue_session(cfg: dict) -> str:
    days = int((cfg.get("remote") or {}).get("session_days") or 30)
    payload = json.dumps({"exp": int(time.time()) + days * 86400,
                          "jti": secrets.token_hex(8)}, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(_secret(cfg), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def valid_session(cfg: dict, token: str) -> bool:
    if not token or "." not in token:
        return False
    body, _, sig = token.rpartition(".")
    want = hmac.new(_secret(cfg), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, want):
        return False
    try:
        pad = "=" * (-len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(body + pad))["exp"] > time.time()
    except Exception:
        return False


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


def enabled(cfg: dict) -> bool:
    """Remote access counts as on only when it is BOTH switched on and locked."""
    r = cfg.get("remote") or {}
    return bool(r.get("enabled")) and bool(r.get("pass_hash"))


def sanitize_remote(cfg: dict) -> dict:
    """Re-assert the invariant every time config is loaded or written: enabled
    without a passphrase is not a state this system has."""
    r = cfg.setdefault("remote", {})
    if r.get("enabled") and not r.get("pass_hash"):
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
        "configured": bool(r.get("pass_hash")),
        "bind": r.get("bind") or "0.0.0.0",
        "port": port,
        "session_days": int(r.get("session_days") or 30),
        "trust_loopback": bool(r.get("trust_loopback", True)),
        "addresses": lan_addresses(port) if enabled(cfg) else [],
        "listening_on": os.environ.get("AGENTOS_BOUND_HOST", ""),
    }
