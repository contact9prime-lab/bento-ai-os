"""The vault: where a secret lives, and the only door to it.

A password to somebody's whole mailbox, or the refresh token a sign-in with
Google handed over, used to sit in `config.json` in clear — masked on the one
route that shows config, and nowhere else: not in a backup, not in a bundle
somebody exports, not in `bento config`, not in the model's context if a tool
ever printed its own settings. Masking a value on the way out is a promise the
next code path has to remember to keep. Storing it somewhere else is not.

So config now holds a REFERENCE — `vault:mail.password` — and the bytes live
here, encrypted (AES-256-GCM) in a 0600 file in the person's own home, under a
key that is the OS keyring's when there is one and a 0600 key file when there
is not. Three properties, and what each one is for:

- **Only the user or the system reads it, and every read is written down.**
  There is no tool, no route and no verb that returns a secret. `get()` is
  called by the code that needs the secret to do its job (open the mailbox,
  refresh the token) and says who it is for; the operator diary gets one line
  per read. The model sees the mail, never the password.
- **The key is not next to the lock when it can be elsewhere.** With a Secret
  Service (`secret-tool`, a Linux desktop) or the macOS keychain (`security`),
  the key sits there and the file on disk is bytes nobody can read without the
  session. A headless Pi has neither, so the key is a 0600 file beside the
  vault — and `status()` SAYS so, in the sentence the card shows: "protected by
  file permissions on this machine". A vault that claimed more than that would
  be worse than the clear-text file it replaced, because somebody would believe
  it.
- **A vault never swaps its key.** The mechanism that keyed it is recorded in
  the file; if that keyring is unreachable later, the vault is LOCKED and says
  so, rather than minting a fresh key and quietly failing to decrypt everything.

Per user, like the config it serves: `~/.agentos/users/<id>/vault.json`, the
machine's when there are no accounts. Kept free of HTTP and asyncio, so `bento
vault` works with the server down.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

REF = "vault:"
VAULT_FILE = "vault.json"
KEY_FILE = "vault.key"
SERVICE = "bento-box-ai"

_on_read = None      # fn(name, actor) -> None — the operator diary, wired by the server
_probe_cache: dict = {}


def set_reader_log(fn) -> None:
    global _on_read
    _on_read = fn


# ---- where -----------------------------------------------------------------------

def _home() -> Path:
    from . import users as usersmod
    return usersmod.home_for(usersmod.current())


def path() -> Path:
    return _home() / VAULT_FILE


def _key_path() -> Path:
    return _home() / KEY_FILE


def _scope() -> str:
    """The keyring entry's name: one per person, one for the machine."""
    from . import users as usersmod
    return f"vault-{usersmod.current() or 'machine'}"


def is_ref(value) -> bool:
    return isinstance(value, str) and value.startswith(REF)


# ---- the key ---------------------------------------------------------------------
#
# Two mechanisms, decided ONCE per vault and recorded in it. `keyring` when a
# secret store answers on this machine; `file` otherwise. Tests and a headless
# box set AGENTOS_VAULT_KEYRING=0 to skip probing a D-Bus that is not there.

def _keyring_tool() -> str:
    if os.environ.get("AGENTOS_VAULT_KEYRING", "1") == "0":
        return ""
    if shutil.which("secret-tool"):
        return "secret-tool"
    if shutil.which("security") and os.uname().sysname == "Darwin":
        return "security"
    return ""


def _keyring_get(scope: str) -> str:
    tool = _keyring_tool()
    try:
        if tool == "secret-tool":
            r = subprocess.run(["secret-tool", "lookup", "service", SERVICE, "key", scope],
                               capture_output=True, text=True, timeout=10)
        elif tool == "security":
            r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", scope, "-w"],
                               capture_output=True, text=True, timeout=10)
        else:
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _keyring_set(scope: str, key_b64: str) -> bool:
    tool = _keyring_tool()
    try:
        if tool == "secret-tool":
            r = subprocess.run(["secret-tool", "store", f"--label=Bento Box AI vault ({scope})",
                                "service", SERVICE, "key", scope],
                               input=key_b64, capture_output=True, text=True, timeout=10)
        elif tool == "security":
            r = subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", scope,
                                "-w", key_b64], capture_output=True, text=True, timeout=10)
        else:
            return False
        return r.returncode == 0 and _keyring_get(scope) == key_b64
    except (OSError, subprocess.SubprocessError):
        return False


def _read_file() -> dict:
    try:
        return json.loads(path().read_text())
    except Exception:
        return {}


def _write_file(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    # 0600 before any content: a refresh token is a standing credential, and the
    # window between create and chmod is the one an attacker gets (mcp_oauth's rule)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, p)


def _new_key() -> bytes:
    return os.urandom(32)


def _load_key(create: bool) -> tuple[bytes, str, str]:
    """(key, mechanism, problem). mechanism is 'keyring' | 'file' | ''; problem is
    the sentence when the vault cannot be opened — never a freshly minted key."""
    data = _read_file()
    mech = data.get("key") or ""
    scope = _scope()
    if mech == "keyring":
        k = _keyring_get(scope)
        if k:
            return base64.b64decode(k), "keyring", ""
        return b"", "keyring", ("The vault's key is in this machine's keyring, which is not "
                                "reachable from here (no desktop session) — the secrets stay "
                                "locked until it is.")
    if mech == "file":
        try:
            return base64.b64decode(_key_path().read_text().strip()), "file", ""
        except Exception:
            return b"", "file", (f"The vault's key file {_key_path()} is missing — the secrets "
                                 "in it cannot be read. Sign in again to replace them.")
    if not create:
        return b"", "", ""
    # a new vault: decide the mechanism once
    key = _new_key()
    kb = base64.b64encode(key).decode()
    if _keyring_tool() and _keyring_set(scope, kb):
        data["key"] = "keyring"
    else:
        kp = _key_path()
        kp.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(kb)
        data["key"] = "file"
    data.setdefault("v", 1)
    data.setdefault("items", {})
    _write_file(data)
    return key, data["key"], ""


# ---- the door --------------------------------------------------------------------

def _aead(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def put(name: str, secret: str) -> str:
    """Store a secret under a name and return the reference config keeps."""
    name = _clean(name)
    key, mech, problem = _load_key(create=True)
    if problem:
        raise RuntimeError(problem)
    data = _read_file()
    items = data.setdefault("items", {})
    nonce = os.urandom(12)
    ct = _aead(key).encrypt(nonce, str(secret).encode(), name.encode())
    items[name] = {"n": base64.b64encode(nonce).decode(), "c": base64.b64encode(ct).decode(),
                   "at": time.time()}
    _write_file(data)
    return REF + name


def get(ref_or_name: str, actor: str = "") -> str:
    """The secret, or '' when there is none or the vault is locked. Every hit is
    one line in the operator diary, with who it was for."""
    name = _clean(ref_or_name[len(REF):] if is_ref(ref_or_name) else ref_or_name)
    data = _read_file()
    item = (data.get("items") or {}).get(name)
    if not item:
        return ""
    key, mech, problem = _load_key(create=False)
    if problem or not key:
        return ""
    try:
        out = _aead(key).decrypt(base64.b64decode(item["n"]), base64.b64decode(item["c"]),
                                 name.encode()).decode()
    except Exception:
        return ""
    if _on_read is not None:
        try:
            _on_read(name, actor)
        except Exception:
            pass
    return out


def resolve(value, actor: str = "") -> str:
    """A config value as the code that needs it wants it: a reference is looked up,
    anything else passes through (an install that has not adopted yet)."""
    if is_ref(value):
        return get(value, actor)
    return str(value or "")


def forget(name: str) -> bool:
    name = _clean(name[len(REF):] if is_ref(name) else name)
    data = _read_file()
    items = data.get("items") or {}
    if name not in items:
        return False
    del items[name]
    _write_file(data)
    return True


def names() -> list[str]:
    return sorted((_read_file().get("items") or {}).keys())


def has(ref_or_name: str) -> bool:
    name = _clean(ref_or_name[len(REF):] if is_ref(ref_or_name) else ref_or_name)
    return name in (_read_file().get("items") or {})


def status() -> dict:
    """What protects the vault, in a sentence the card can show — decided by
    what is actually on this machine, never by what would be nice."""
    data = _read_file()
    mech = data.get("key") or ""
    items = data.get("items") or {}
    if not mech:
        would = "the keyring" if _keyring_tool() else "a key file beside it"
        return {"mechanism": "", "locked": False, "count": 0, "names": [],
                "detail": f"Empty. The first secret creates it, keyed by {would}."}
    key, _m, problem = _load_key(create=False)
    if mech == "keyring":
        detail = ("Encrypted; the key is in this machine's keyring (Secret Service / keychain), "
                  "so the file on disk is unreadable without your session.")
    else:
        detail = ("Encrypted; the key is a 0600 file beside it — protected by file permissions "
                  "on this machine, which is all a headless box can offer.")
    return {"mechanism": mech, "locked": bool(problem), "count": len(items), "names": sorted(items),
            "detail": problem or detail, "path": str(path())}


def adopt(cfg: dict) -> bool:
    """Move the secrets config still holds in clear into the vault, leaving
    references. Returns True when something moved (and config should be saved).
    Never runs when the vault is locked: a migration that cannot store must not
    blank the value it was moving."""
    moved = False
    for section, key, name in SECRET_KEYS:
        sec = cfg.get(section)
        if not isinstance(sec, dict):
            continue
        v = sec.get(key)
        if isinstance(v, str) and v and not is_ref(v) and not v.startswith("•••"):
            try:
                sec[key] = put(name, v)
                moved = True
            except RuntimeError:
                return moved
    return moved


#: (config section, key, vault name) — what `adopt` moves. The rule for what goes
#: here: a value that opens somebody's account. Provider API keys and the
#: Telegram token are the MACHINE's (USER_KEYS says why) and stay where they are.
SECRET_KEYS = (
    ("mail", "password", "mail.password"),
    ("calendar", "password", "calendar.password"),
    ("mail", "oauth", "oauth.mail"),
    ("calendar", "oauth", "oauth.calendar"),
)


def _clean(name: str) -> str:
    return "".join(c for c in str(name or "") if c.isalnum() or c in "._-")[:80]
