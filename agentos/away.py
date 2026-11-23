"""A secret usable while you're away: the copy a mission reads when nobody is signed in.

Asked for as "Bento starts as a service for everyone; once the user has accepted to store the
password for future missions, it should work unless they revoke it or set a time limit; allowed
once, it works the next time and then resets, whether they're signed in or not".

An account's secrets are sealed to that person's key (seal.py), which only their signed-in
browser can lend. A mission at 3 am has no browser to ask. So each secret carries a choice:

- `off`: only while you're signed in, the strict rule. Nothing but your key opens it.
- `always`: until you revoke it (the default when you save one).
- `until`: until a date you chose.
- `once`: the next run that needs it, then it is gone (`ONCE_S` after its first use).

For anything but `off`, the secret is also kept as a SECOND copy locked with this machine's
service key, the one Bento's service has from the moment it starts. That copy is what work
nobody is watching reads. It is made only while the plaintext is in hand (when you save the
secret, or when you switch it on while signed in), revoking deletes it, and it is deleted when
its time is up. Nothing in this module can make one from the sealed copy alone.

What it costs, and the docs and Settings say so: anything the service can open on its own, root
on this machine can open too. Another account and an admin still can't read it, because no
route, verb or tool returns a secret and each account's files are its own. A secret set to `off`
keeps the strict rule.

The service key is decided once and recorded (`away.json`): the keyring when one answers, a 0600
file otherwise, and a key that can't be found is LOCKED, never re-minted, as vault.py's rule.
Kept free of HTTP and asyncio.
"""

from __future__ import annotations

import base64
import json
import math
import os
import time
from pathlib import Path

MODES = ("off", "always", "until", "once")
DEFAULT = "always"
ONCE_S = 3600.0                  # "once" is one run: usable for an hour after its first use
MAX_DAYS = 3650
FILE = "away.json"
KEY_FILE = "away.key"
SCOPE = "away-service"

COST_WORDS = ("A secret that works while you're away is also kept locked with this machine's own "
              "key, so missions can open it with nobody signed in. No other account or admin can "
              "read it through Bento, but root on this machine could.")


def _home() -> Path:
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME)


def _meta_path(home: Path | None = None) -> Path:
    return (Path(home) if home else _home()) / FILE


def _key_path(home: Path | None = None) -> Path:
    return (Path(home) if home else _home()) / KEY_FILE


def _vault():
    from . import vault
    return vault


def _load(create: bool, home: Path | None = None) -> bytes:
    """The service key, or b'' when there is none (and create is False) or it can't be found.
    `home` is another machine home than this process's (dbcrypt: a database's key is its home's)."""
    try:
        meta = json.loads(_meta_path(home).read_text())
    except Exception:
        meta = {}
    mech = meta.get("key") or ""
    v = _vault()
    if mech == "keyring":
        k = v._keyring_get(SCOPE)
        return base64.b64decode(k) if k else b""
    if mech == "file":
        try:
            return base64.b64decode(_key_path(home).read_text().strip())
        except Exception:
            return b""
    if not create:
        return b""
    key = os.urandom(32)
    kb = base64.b64encode(key).decode()
    (Path(home) if home else _home()).mkdir(parents=True, exist_ok=True)
    # the keyring entry has ONE name per OS user: only this process's own home may use it, or
    # making a key for another home (a staged restore, a test's) would overwrite the real one
    if home is None and v._keyring_tool() and v._keyring_set(SCOPE, kb):
        mech = "keyring"
    else:
        fd = os.open(_key_path(home), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(kb)
        mech = "file"
    fd = os.open(_meta_path(home), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"key": mech, "at": time.time()}, f)
    return key


def _aad(uid: str, what: str) -> bytes:
    return f"bento-away/{uid}/{what}".encode()


def lock(uid: str, what: str, data: bytes) -> dict:
    """The away copy of one secret, locked with the service key."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _load(create=True)
    if not key:
        raise RuntimeError("This machine's service key can't be found, so nothing can be kept "
                           "for while you're away.")
    n = os.urandom(12)
    c = AESGCM(key).encrypt(n, data, _aad(uid, what))
    return {"n": base64.b64encode(n).decode(), "c": base64.b64encode(c).decode()}


def unlock(uid: str, what: str, box: dict) -> bytes | None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _load(create=False)
    if not key or not isinstance(box, dict):
        return None
    try:
        return AESGCM(key).decrypt(base64.b64decode(box["n"]), base64.b64decode(box["c"]),
                                   _aad(uid, what))
    except Exception:
        return None


# ---- the choice ----------------------------------------------------------------------

def choice(mode: str = DEFAULT, days: float | None = None, until: float | None = None) -> dict:
    """A closed set: one of MODES, and a time for `until`. Anything else is refused in words."""
    mode = str(mode or "").strip().lower()
    if mode in ("revoke", "never", "signed-in", "signed_in"):
        mode = "off"
    if mode in ("on", "forever", "yes"):
        mode = "always"
    if mode == "days":
        mode = "until"
    if mode not in MODES:
        raise ValueError(f"'{mode}' isn't a choice. Use one of: only while signed in (off), "
                         "until I revoke it (always), for a number of days (until), once.")
    out = {"mode": mode, "set": time.time()}
    if mode == "until":
        if until is None:
            try:
                d = float(days or 0)
            except (TypeError, ValueError):
                d = 0
            if not 0 < d <= MAX_DAYS:
                raise ValueError(f"Say how many days, from 1 to {MAX_DAYS}.")
            until = time.time() + d * 86400
        out["until"] = float(until)
    return out


def usable(meta: dict | None, now: float | None = None) -> bool:
    """Can work nobody is watching use this copy right now?"""
    if not isinstance(meta, dict) or not meta.get("box"):
        return False
    now = time.time() if now is None else now
    mode = meta.get("mode")
    if mode == "always":
        return True
    if mode == "until":
        return now < float(meta.get("until") or 0)
    if mode == "once":
        used = meta.get("used")
        return not used or now - float(used) < ONCE_S
    return False


def spent(meta: dict | None, now: float | None = None) -> bool:
    """A copy whose time is up, to be deleted."""
    if not isinstance(meta, dict) or not meta.get("box"):
        return False
    return not usable(meta, now)


def ended(meta: dict) -> dict:
    """What a spent copy becomes: off, saying why. "Allowed once" resets to signed-in only."""
    return {"mode": "off", "set": time.time(), "ended": meta.get("mode")}


def words(meta: dict | None, now: float | None = None) -> str:
    """The one line Settings and `bento vault` show for a secret."""
    now = time.time() if now is None else now
    if not isinstance(meta, dict) or meta.get("mode") in (None, "", "off"):
        ended = (meta or {}).get("ended") if isinstance(meta, dict) else None
        if ended == "once":
            return "Used once. Now only while you're signed in"
        if ended == "until":
            return "Its time ran out. Now only while you're signed in"
        return "Only while you're signed in"
    mode = meta["mode"]
    if not meta.get("box"):
        return "Needs you signed in once to switch on"
    if mode == "always":
        return "Works while you're away, until you revoke it"
    if mode == "until":
        left = float(meta.get("until") or 0) - now
        days = max(0, math.ceil(left / 86400))
        when = time.strftime("%d %b %Y", time.localtime(float(meta.get("until") or 0)))
        return f"Works while you're away until {when}" + (f" ({days} days left)" if days else "")
    if mode == "once":
        return ("Being used by a run now" if meta.get("used")
                else "Works once while you're away, for the next run that needs it")
    return "Only while you're signed in"


def forget_key() -> None:
    """A factory reset: the service key goes with everything it locked."""
    for p in (_key_path(), _meta_path()):
        try:
            p.unlink()
        except OSError:
            pass
