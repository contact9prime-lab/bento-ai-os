"""Each account's secrets, sealed so only that person, signed in, can open them.

Asked for as "per account, not cross-pollinated even from root; the user has to be signed in to
Bento to read it, period", then "do not keep in memory something that might unlock something".

The shape, and what each part is for:

- **A key pair per account.** Sealing needs only the PUBLIC half (`seal_bytes`), so a refreshed
  sign-in token, a vault write from a mission or the browser profile put away at idle can be
  locked at any time with nothing secret in memory. Opening needs the PRIVATE half.
- **The private half is wrapped twice and stored nowhere in clear**: by a key stretched from the
  account's password (scrypt, its own salt per account) and by one stretched from a recovery
  code shown to the person once. An admin reset cannot re-wrap it; the old wrap is marked
  stale and the person's next sign-in asks for their recovery code, or starts fresh.
- **While signed in, the private half is split** (`lend_cookie`): a random pad stays in this
  process for that one session, and the private half XOR the pad goes to the person's browser
  as an HttpOnly cookie. Neither half alone opens anything, so this process's memory holds
  nothing that unlocks. A request from that browser carries its half (`from_request`), the two
  are combined for one use (`key_here`) and dropped.
- **Work nobody is watching borrows** (`borrow`): it asks a page this person has open to lend its
  half for one step, over the socket (`seal_need` → `POST /api/seal/lend`). No page open, and
  the step is refused in a sentence that says to open Bento signed in. A restart forgets every
  pad, so after one the person types their password once to open their secrets again.

What this does NOT defend, and the docs say: while a secret is in use (a step reading the mail,
a browser that is running) it is in this process or in RAM, and root can read RAM. At rest, and
whenever that person is signed out, nothing on this machine opens it. A machine with no accounts
has nobody to sign in, and keeps the vault's own key (vault.py says which).

Kept free of HTTP and asyncio at import, like vault.py; `borrow` is the one async door.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import json
import os
import secrets
import threading
import time
from pathlib import Path

SEAL_FILE = "seal.json"
COOKIE = "bento_k"
SCRYPT_N = 2 ** 15                 # ~100 ms and 32 MB, once per sign-in
BORROW_WAIT = 25.0                 # a page that is open answers in about a second
CODE_GROUPS = 5                    # 5 groups of 5 base32 characters: 125 bits

LOCKED_WORDS = ("Your secrets are sealed while you're signed out. Open Bento and sign in, "
                "then run this again.")
RESTART_WORDS = ("Bento restarted, so your secrets are sealed until you enter your password "
                 "once (Settings → Accounts → Your secrets).")


class Sealed(RuntimeError):
    """Nothing here can open this account's secrets right now; the message says why."""


# ---- where ---------------------------------------------------------------------------

def _home(uid: str) -> Path:
    from . import users as usersmod
    return usersmod.home_for(uid)


def _path(uid: str) -> Path:
    return _home(uid) / SEAL_FILE


def _read(uid: str) -> dict:
    try:
        d = json.loads(_path(uid).read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write(uid: str, d: dict) -> None:
    p = _path(uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.replace(tmp, p)


def exists(uid: str) -> bool:
    """Is this account sealed? Never for the machine (uid '')."""
    return bool(uid) and bool(_read(uid).get("pub"))


def needs_recovery(uid: str) -> bool:
    """An admin reset the password: the password's wrap no longer opens anything."""
    return exists(uid) and bool(_read(uid).get("pw_stale"))


# ---- the crypto ------------------------------------------------------------------------

def _b(x: bytes) -> str:
    return base64.b64encode(x).decode()


def _u(s: str) -> bytes:
    return base64.b64decode(s)


def _stretch(secret: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=SCRYPT_N, r=8, p=1).derive(secret.encode())


def _aead(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def _wrap(kek: bytes, data: bytes, aad: bytes) -> dict:
    n = os.urandom(12)
    return {"n": _b(n), "c": _b(_aead(kek).encrypt(n, data, aad))}


def _unwrap(kek: bytes, w: dict, aad: bytes) -> bytes:
    return _aead(kek).decrypt(_u(w["n"]), _u(w["c"]), aad)


def _aad(uid: str, what: str) -> bytes:
    return f"bento-seal/{uid}/{what}".encode()


def new_code() -> str:
    """A recovery code: five groups of five, from an alphabet with no 0/O or 1/I to misread."""
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alpha) for _ in range(5 * CODE_GROUPS))
    return "-".join(raw[i:i + 5] for i in range(0, len(raw), 5))


def _norm_code(code: str) -> str:
    c = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return c.replace("0", "O").replace("1", "I")


def _pub_of(priv: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization as ser
    return X25519PrivateKey.from_private_bytes(priv).public_key().public_bytes(
        ser.Encoding.Raw, ser.PublicFormat.Raw)


def _shared(priv: bytes, peer_pub: bytes, what: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    s = X25519PrivateKey.from_private_bytes(priv).exchange(X25519PublicKey.from_public_bytes(peer_pub))
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"bento-seal/" + what).derive(s)


def seal_bytes(uid: str, data: bytes, what: str) -> dict:
    """Lock `data` to this account with its PUBLIC key: needs nothing secret, so anything may
    put a secret away at any time. `what` binds the box to its use (a vault name, the profile)."""
    pub = _u(_read(uid).get("pub") or "")
    if len(pub) != 32:
        raise Sealed("this account has no seal yet")
    eph = os.urandom(32)
    k = _shared(eph, pub, what.encode())
    n = os.urandom(12)
    return {"e": _b(_pub_of(eph)), "n": _b(n), "c": _b(_aead(k).encrypt(n, data, _aad(uid, what)))}


def open_bytes(uid: str, priv: bytes, box: dict, what: str) -> bytes:
    k = _shared(priv, _u(box["e"]), what.encode())
    return _aead(k).decrypt(_u(box["n"]), _u(box["c"]), _aad(uid, what))


# ---- setting up, signing in, recovering --------------------------------------------------

def establish(uid: str, password: str) -> tuple[bytes, str]:
    """Seal an account for the first time. Returns (private key, recovery code). The code is
    shown once and never stored: only a key stretched from it is."""
    if not uid:
        raise ValueError("the machine has no account to seal")
    priv = os.urandom(32)
    code = new_code()
    ps, rs = os.urandom(16), os.urandom(16)
    _write(uid, {
        "v": 1, "pub": _b(_pub_of(priv)), "at": time.time(),
        "pw": {"salt": _b(ps), **_wrap(_stretch(password, ps), priv, _aad(uid, "pw"))},
        "rc": {"salt": _b(rs), **_wrap(_stretch(_norm_code(code), rs), priv, _aad(uid, "rc"))},
    })
    return priv, code


def open_with_password(uid: str, password: str) -> bytes:
    d = _read(uid)
    if d.get("pw_stale"):
        raise Sealed("Your password was reset by an admin. Enter your recovery code to open "
                     "your secrets, or start fresh.")
    w = d.get("pw") or {}
    try:
        return _unwrap(_stretch(password, _u(w["salt"])), w, _aad(uid, "pw"))
    except Exception:
        raise Sealed("that password does not open this account's seal") from None


def open_with_code(uid: str, code: str) -> bytes:
    w = _read(uid).get("rc") or {}
    try:
        return _unwrap(_stretch(_norm_code(code), _u(w["salt"])), w, _aad(uid, "rc"))
    except Exception:
        raise Sealed("that recovery code does not match") from None


def rewrap(uid: str, priv: bytes, password: str) -> None:
    """The password changed (or was recovered): wrap the same private key under the new one."""
    d = _read(uid)
    ps = os.urandom(16)
    d["pw"] = {"salt": _b(ps), **_wrap(_stretch(password, ps), priv, _aad(uid, "pw"))}
    d.pop("pw_stale", None)
    _write(uid, d)


def new_recovery(uid: str, priv: bytes) -> str:
    """A fresh recovery code; the old one stops working."""
    d = _read(uid)
    code, rs = new_code(), os.urandom(16)
    d["rc"] = {"salt": _b(rs), **_wrap(_stretch(_norm_code(code), rs), priv, _aad(uid, "rc"))}
    d["rc_at"] = time.time()
    _write(uid, d)
    return code


def mark_password_reset(uid: str) -> None:
    """An admin set somebody else's password. The old wrap can't be redone without the old
    password, so it is marked stale: the person's recovery code is what opens it now."""
    if exists(uid):
        d = _read(uid)
        d["pw_stale"] = True
        _write(uid, d)
    drop_user(uid)


def start_fresh(uid: str) -> list[str]:
    """No recovery code: what was sealed can never be opened, so it goes, and the account is
    sealed again from nothing at its next sign-in. Returns what was removed, in words."""
    gone = []
    home = _home(uid)
    try:
        from . import vault
        n = vault.drop_sealed(uid)
        if n:
            gone.append(f"{n} saved password{'s' if n != 1 else ''} in the vault")
    except Exception:
        pass
    prof = home / "browser" / "profile.sealed"
    if prof.exists():
        prof.unlink()
        gone.append("your website sign-ins")
    with contextlib.suppress(OSError):
        _path(uid).unlink()
    drop_user(uid)
    return gone


# ---- the split: half in the browser, half here, for one session ---------------------------

_PADS: dict[str, tuple[str, bytes]] = {}          # session id -> (uid, pad)
_LOCK = threading.Lock()


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def lend_cookie(uid: str, sid: str, priv: bytes) -> str:
    """Split the private key for one session: the pad stays here, the other half is returned
    for the browser's cookie. Neither opens anything alone."""
    pad = os.urandom(32)
    with _LOCK:
        _PADS[sid] = (uid, pad)
    return base64.urlsafe_b64encode(_xor(priv, pad)).decode()


def move(old_sid: str, new_sid: str) -> None:
    """A lock or a fresh cookie keeps the same session's half (the person chose that a lock
    keeps their missions working)."""
    with _LOCK:
        if old_sid in _PADS and new_sid:
            _PADS[new_sid] = _PADS.pop(old_sid)


def drop(sid: str) -> None:
    with _LOCK:
        _PADS.pop(sid, None)


def drop_user(uid: str) -> None:
    with _LOCK:
        for k in [k for k, (u, _p) in _PADS.items() if u == uid]:
            _PADS.pop(k, None)


def open_here(uid: str) -> bool:
    """Does any session of this person hold a pad here (so a page of theirs could lend)?"""
    with _LOCK:
        return any(u == uid for u, _p in _PADS.values())


_SHARE: contextvars.ContextVar = contextvars.ContextVar("bento_seal_share", default=None)


class _Held:
    """This request's half, in a holder emptied when the request ends. A task started from the
    request copies the context and so the holder; emptying it is what stops that task keeping
    the browser's half after the request has answered."""
    __slots__ = ("uid", "sid", "share")

    def __init__(self, uid, sid, share):
        self.uid, self.sid, self.share = uid, sid, share


def from_request(uid: str, sid: str, cookie_value: str):
    """Set by the request middleware: this request's browser half, for this request only."""
    held = None
    if uid and sid and cookie_value:
        try:
            share = base64.urlsafe_b64decode(cookie_value.encode())
        except Exception:
            share = b""
        if len(share) == 32:
            held = _Held(uid, sid, share)
    return (_SHARE.set(held), held)


def reset_request(token) -> None:
    tok, held = token
    if held is not None:
        held.share = None
    _SHARE.reset(tok)


def key_here(uid: str) -> bytes | None:
    """The private key, combined from this request's half and this session's pad, for one use.
    None when this request is not that person's signed-in browser."""
    got = _SHARE.get()
    if got is None or got.uid != uid or not got.share:
        return None
    sid, share = got.sid, got.share
    with _LOCK:
        pad = _PADS.get(sid)
    if not pad or pad[0] != uid:
        return None
    priv = _xor(share, pad[1])
    try:
        if _pub_of(priv) != _u(_read(uid).get("pub") or ""):
            return None
    except Exception:
        return None
    return priv


# ---- borrowing, for work nobody is watching -------------------------------------------------

LOOP: list = [None]                  # the server's event loop, set at start
_ASK: list = [None]                  # async fn(uid, ticket, why) -> bool: a page of theirs was asked
_WAIT: dict[str, tuple[str, asyncio.Future]] = {}
_WANTS: dict[str, dict[str, str]] = {}       # uid -> {ticket: why}: steps waiting for a page
_POLLED: dict[str, float] = {}               # uid -> when a locked page last asked
POLL_FRESH = 12.0


def wants(uid: str) -> list[dict]:
    """What a locked page of this person's is asked to lend, and why (it shows the why)."""
    _POLLED[uid] = time.time()
    return [{"ticket": t, "why": w} for t, w in (_WANTS.get(uid) or {}).items()]


def bind(loop, ask) -> None:
    LOOP[0], _ASK[0] = loop, ask


async def borrow(uid: str, why: str) -> bytes:
    """The private key for one step, from a page this person has open. Raises Sealed with the
    sentence to show when nobody signed in as them can lend it."""
    k = key_here(uid)
    if k:
        return k
    if not open_here(uid):
        raise Sealed(LOCKED_WORDS if not _restarted_since_sign_in(uid) else RESTART_WORDS)
    ask = _ASK[0]
    if ask is None:
        raise Sealed(LOCKED_WORDS)
    ticket = secrets.token_urlsafe(12)
    fut = asyncio.get_running_loop().create_future()
    _WAIT[ticket] = (uid, fut)
    _WANTS.setdefault(uid, {})[ticket] = why[:160]
    try:
        asked = await ask(uid, ticket, why)
        if not asked and time.time() - _POLLED.get(uid, 0) > POLL_FRESH:
            # a locked screen has no socket; it asks every few seconds instead (`wants`)
            raise Sealed("Your secrets open only from a page where you're signed in, and none is "
                         "open now. Open Bento, then run this again.")
        return await asyncio.wait_for(fut, BORROW_WAIT)
    except asyncio.TimeoutError:
        raise Sealed("Your open Bento page didn't answer in time, so your secrets stayed sealed. "
                     "Try again with the page open.") from None
    finally:
        _WAIT.pop(ticket, None)
        _WANTS.get(uid, {}).pop(ticket, None)


def borrow_blocking(uid: str, why: str) -> bytes:
    """`borrow` for code running in a worker thread (mail, calendar, a sign-in refresh). On the
    loop's own thread it cannot wait, so it only uses this request's half."""
    k = key_here(uid)
    if k:
        return k
    loop = LOOP[0]
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if loop is None or running is loop or not loop.is_running():
        raise Sealed(LOCKED_WORDS)
    return asyncio.run_coroutine_threadsafe(borrow(uid, why), loop).result(BORROW_WAIT + 5)


def lent(ticket: str, uid: str) -> bool:
    """`POST /api/seal/lend`: this request is the person's browser; hand the key to the step
    that asked, once."""
    w = _WAIT.get(ticket)
    if not w or w[0] != uid or w[1].done():
        return False
    k = key_here(uid)
    if not k:
        return False
    w[1].set_result(k)
    return True


_SIGNED_IN_AT: dict[str, float] = {}
_STARTED = time.time()


def note_sign_in(uid: str) -> None:
    _SIGNED_IN_AT[uid] = time.time()


def _restarted_since_sign_in(uid: str) -> bool:
    """A cookie that still says signed in, on a server that has no pad for it: a restart."""
    return uid not in _SIGNED_IN_AT


def status(uid: str) -> dict:
    """What the Settings card and `bento vault` say about this account's seal."""
    if not uid:
        return {"sealed": False, "detail": "This machine has no accounts, so there is nobody to "
                                           "sign in and the vault keeps its own key."}
    d = _read(uid)
    if not d.get("pub"):
        return {"sealed": False, "detail": "Not sealed yet. It's sealed with your password the "
                                           "next time you sign in."}
    return {"sealed": True, "open": key_here(uid) is not None, "here": open_here(uid),
            "needs_recovery": bool(d.get("pw_stale")), "since": d.get("at"),
            "code_at": d.get("rc_at") or d.get("at"),
            "detail": "Sealed with your password. Only you, signed in, can open it. Not an admin, "
                      "not another account, not root while you're signed out."}
