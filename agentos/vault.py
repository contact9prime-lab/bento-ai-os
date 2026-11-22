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
machine's when there are no accounts.

**An account's vault is SEALED** (`key: "sealed"`, seal.py): an item is locked to that
account's public key, so writing needs nothing secret, and reading needs the account's
private key, which only that person's signed-in browser can lend. Not an admin, not another
account. Each item also carries the person's choice for while they're away (away.py): unless it
is "only while signed in", a second copy is locked with the machine's service key, and that is
what a mission reads with nobody signed in. An account's vault moves to the seal at its first
sign-in after the update (`reseal`); until then it keeps the key it had. The machine's own
vault (no accounts, the device passwords) has nobody to sign in and keeps its key. Kept free of HTTP and asyncio, so `bento
vault` works with the server down.
"""

from __future__ import annotations

import base64
import contextvars
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

_TENANT: contextvars.ContextVar = contextvars.ContextVar("agentos_vault_tenant", default="")


def _home() -> Path:
    from . import users as usersmod
    t = _TENANT.get()
    if t:
        return usersmod.tenant_home(t)
    return usersmod.home_for(usersmod.current())


class in_tenant:
    """Read and write an Isolated Tenant's vault (users.py): its provider and voice keys, locked
    with the service key like the machine's own. Nobody signs in as a tenant, so it is never
    sealed to a person."""

    def __init__(self, tid: str):
        self.tid = tid

    def __enter__(self):
        self._tok = _TENANT.set(str(self.tid or ""))
        return self

    def __exit__(self, *a):
        _TENANT.reset(self._tok)
        return False


def adopt_tenant(tid: str, tcfg: dict) -> bool:
    """A tenant's keys into its own vault. Names carry the tenant, so `machine_value` knows which
    vault a reference opens in."""
    moved = False
    with in_tenant(tid):
        for sec, key, name in list(_machine_places(tcfg)):
            v = sec.get(key)
            if _clear(v):
                sec[key] = put(f"tenant.{_clean(tid)}.{name}", v)
                moved = True
    return moved


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
    if mech == "service":
        k = _away()._load(create=False)
        if k:
            return k, "service", ""
        return b"", "service", ("This machine's service key can't be found, so the secrets in its "
                                "vault stay locked until it is back.")
    if not create:
        return b"", "", ""
    if not _uid():
        # the machine's own vault is locked with the service key (away.py): the one key Bento's
        # service has from the moment it starts, so provider keys open after a restart
        key = _away()._load(create=True)
        if key:
            data["key"] = "service"
            data.setdefault("v", 1)
            data.setdefault("items", {})
            _write_file(data)
            return key, "service", ""
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


def _uid() -> str:
    """Whose vault this is: '' for the machine's and for a tenant's (nobody signs in as those)."""
    if _TENANT.get():
        return ""
    from . import users as usersmod
    return usersmod.current() or ""


def sealed() -> bool:
    """Is the vault in front of us an account's sealed one?"""
    return _read_file().get("key") == "sealed"


def put(name: str, secret: str) -> str:
    """Store a secret under a name and return the reference config keeps."""
    name = _clean(name)
    _CACHE.pop((_uid(), _TENANT.get(), REF + name), None)
    data = _read_file()
    uid = _uid()
    if data.get("key") == "sealed" or (uid and not data.get("key") and _seal().exists(uid)):
        # locked to the account's public key: nothing secret is needed to put one away
        data["key"] = "sealed"
        data.setdefault("v", 1)
        items = data.setdefault("items", {})
        plain = str(secret).encode()
        item = {"s": _seal().seal_bytes(uid, plain, "vault/" + name), "at": time.time()}
        # the plaintext is in hand, so this is when a copy for while you're away can be made
        meta = _carry_away(uid, name, (items.get(name) or {}).get("away"), plain)
        if meta:
            item["away"] = meta
        items[name] = item
        _write_file(data)
        return REF + name
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
    if data.get("key") == "sealed":
        uid = _uid()
        out = _open_sealed(uid, name, data, item)
        if out is None:
            return ""
        if _on_read is not None:
            with _quiet():
                _on_read(name, actor)
        return out
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
    if mech == "sealed":
        st = _seal().status(_uid())
        aw = _away()
        n_away = sum(1 for it in items.values() if aw.usable(it.get("away")))
        detail = st["detail"]
        if n_away:
            detail = (f"Sealed with your password. {n_away} of {len(items)} also work while you're "
                      "away: those are kept locked with this machine's key too, so missions can use "
                      "them with nobody signed in, and root on this machine could open them.")
        return {"mechanism": "sealed", "locked": not st.get("open"), "count": len(items),
                "names": sorted(items), "detail": detail, "path": str(path()),
                "away": away_list()}
    if not mech:
        would = "the keyring" if _keyring_tool() else "a key file beside it"
        return {"mechanism": "", "locked": False, "count": 0, "names": [],
                "detail": f"Empty. The first secret creates it, keyed by {would}."}
    key, _m, problem = _load_key(create=False)
    if mech == "service":
        detail = ("Encrypted with this machine's service key, so Bento opens it with nobody signed "
                  "in. That protects copies of config.json and anything that prints config. Root, "
                  "and the user Bento runs as, can still open it.")
        return {"mechanism": mech, "locked": bool(problem), "count": len(items),
                "names": sorted(items), "detail": problem or detail, "path": str(path())}
    if mech == "keyring":
        detail = ("Encrypted; the key is in this machine's keyring (Secret Service / keychain), "
                  "so the file on disk is unreadable without your session.")
    else:
        detail = ("Encrypted; the key is a 0600 file beside it — protected by file permissions "
                  "on this machine, which is all a headless box can offer.")
    return {"mechanism": mech, "locked": bool(problem), "count": len(items), "names": sorted(items),
            "detail": problem or detail, "path": str(path())}


def _seal():
    from . import seal
    return seal


# ---- while you're away (away.py) -------------------------------------------------------
#
# A sealed item may carry `away`: the person's choice (off / always / until / once) and, unless
# it is off, `box`, the same secret locked with the machine's service key. Work nobody is
# watching reads the box; revoking deletes it; a box whose time is up is deleted on the next
# read. `BROWSER` is the signed-in browser profile, whose box is a file beside the profile
# (cdpbrowser.py), so its choice lives in `data["away"]` rather than under an item.

BROWSER = "browser"
LABELS = {BROWSER: "Websites you're signed in to", "mail.password": "Mail password",
          "calendar.password": "Calendar password", "oauth.mail": "Mail sign-in",
          "oauth.calendar": "Calendar sign-in", "telegram.bot_token": "Telegram bot",
          "channels.telegram.bot_token": "Telegram bot",
          "whatsapp.access_token": "WhatsApp access token", "whatsapp.app_secret": "WhatsApp app secret",
          "channels.whatsapp.access_token": "WhatsApp access token",
          "channels.whatsapp.app_secret": "WhatsApp app secret"}


def label(name: str) -> str:
    """A vault name in the words Settings shows."""
    if name in LABELS:
        return LABELS[name]
    if name.startswith("mcp.oauth."):
        return f"MCP {name[10:].rsplit('-', 1)[0]}: sign-in"
    if name.startswith("mcp."):
        parts = name.split(".")
        if len(parts) >= 4:
            return f"MCP {parts[1]}: {'.'.join(parts[3:])}"
    if name.startswith("esp."):
        return f"ESP32 {name[4:]}"
    return name


def _away():
    from . import away
    return away


def _carry_away(uid: str, name: str, old: dict | None, plain: bytes) -> dict | None:
    """The choice an item keeps when its value is written again (a refreshed token keeps what
    the person chose), with a fresh box. A new secret gets the default: works while you're
    away, until you revoke it."""
    aw = _away()
    if old is None:
        meta = aw.choice(aw.DEFAULT)
    else:
        meta = {k: v for k, v in old.items() if k != "box"}
        if old.get("box") and aw.spent(old):
            return aw.ended(old)
    if meta.get("mode") in (None, "", "off"):
        return meta
    try:
        meta["box"] = aw.lock(uid, "vault/" + name, plain)
    except RuntimeError:
        meta.pop("box", None)
    return meta


def _open_sealed(uid: str, name: str, data: dict, item: dict) -> str | None:
    """A sealed item's value. Your own key first when this request carries it; then the copy you
    allowed for while you're away; then a page of yours that can lend the key. With none of
    those, seal.Sealed says what to do. "Once" is not spent while a page of yours could lend."""
    seal, aw = _seal(), _away()
    meta = item.get("away")
    priv = seal.key_here(uid)
    if not priv and aw.usable(meta) and (meta.get("mode") != "once" or not seal.open_here(uid)):
        out = _from_away(uid, name, data, item)
        if out is not None:
            return out
        meta = None                    # the service key is gone: only your own key opens it now
    if not priv:
        if isinstance(meta, dict) and aw.spent(meta):
            item["away"] = aw.ended(meta)
            _write_file(data)
        try:
            priv = seal.borrow_blocking(uid, f"open {name} from your vault")
        except seal.Sealed:
            if meta is not None and aw.usable(item.get("away")):
                out = _from_away(uid, name, data, item)
                if out is not None:
                    return out
            out = _wait_for_phone(uid, name)
            if out is not None:
                return out
            raise seal.Sealed(away_refusal(name)) from None
    try:
        return seal.open_bytes(uid, priv, item["s"], "vault/" + name).decode()
    except Exception:
        return None
    finally:
        priv = None


def _wait_for_phone(uid: str, name: str) -> str | None:
    """Nobody is signed in and this secret needs them: their own phone chat gets a link to sign
    in through remote access (unlock.py), and this step waits a few minutes for them to open it
    there, for the next run or longer. None when it wasn't opened in time."""
    from . import unlock
    seal, aw = _seal(), _away()
    if not unlock.closed(uid, name) and not unlock.sent_lately(uid):
        return None

    def ready():
        it = (_read_file().get("items") or {}).get(name) or {}
        return aw.usable(it.get("away")) or seal.open_here(uid)

    if not unlock.wait(uid, ready):
        return None
    data = _read_file()
    item = (data.get("items") or {}).get(name)
    if not item:
        return None
    if aw.usable(item.get("away")):
        return _from_away(uid, name, data, item)
    try:
        priv = seal.borrow_blocking(uid, f"open {name} from your vault")
    except seal.Sealed:
        return None
    try:
        return seal.open_bytes(uid, priv, item["s"], "vault/" + name).decode()
    except Exception:
        return None
    finally:
        priv = None


def _from_away(uid: str, name: str, data: dict, item: dict) -> str | None:
    meta = item["away"]
    out = _away().unlock(uid, "vault/" + name, meta.get("box") or {})
    if out is None:
        return None
    if meta.get("mode") == "once" and not meta.get("used"):
        meta["used"] = time.time()
        _write_file(data)
    return out.decode()


def away_refusal(name: str) -> str:
    """What a step nobody is watching is told when it can't open a secret."""
    return (f"{label(name)} is set to work only while you're signed in, so it's closed now. Sign in, or "
            "after a restart enter your password once, in Settings → Accounts → Your secrets, where you "
            "can also let it work while you're away.")


def away_meta(name: str) -> dict | None:
    data = _read_file()
    if name == BROWSER:
        return (data.get("away") or {}).get(BROWSER)
    return ((data.get("items") or {}).get(_clean(name)) or {}).get("away")


def note_away(name: str, meta: dict | None) -> None:
    """Record a choice as it now stands (the browser's, written by cdpbrowser as it seals)."""
    data = _read_file()
    if name == BROWSER:
        data.setdefault("away", {})[BROWSER] = meta
    else:
        it = (data.get("items") or {}).get(_clean(name))
        if not it:
            return
        it["away"] = meta
    _write_file(data)


def set_away(name: str, mode: str, days: float | None = None, priv: bytes | None = None) -> dict:
    """The person's choice for one secret. Switching one ON needs the plaintext, so it needs
    their key (`priv`, from their signed-in request) unless a copy is still there to reuse.
    Revoking needs nothing. Raises ValueError for a bad choice, seal.Sealed when the key is
    needed and missing, KeyError for a name that isn't there."""
    aw, seal = _away(), _seal()
    uid = _uid()
    meta = aw.choice(mode, days)
    if name == BROWSER:
        from . import cdpbrowser
        return cdpbrowser.away_switch(uid, meta, priv)
    name = _clean(name)
    data = _read_file()
    item = (data.get("items") or {}).get(name)
    if not item or data.get("key") != "sealed":
        raise KeyError(name)
    old = item.get("away") or {}
    if meta["mode"] != "off":
        if old.get("box"):
            meta["box"] = old["box"]          # the same secret; only the choice changes
        else:
            if not priv:
                raise seal.Sealed("Sign in to switch this on: Bento needs your key once to make "
                                  "the copy that works while you're away.")
            plain = seal.open_bytes(uid, priv, item["s"], "vault/" + name)
            meta["box"] = aw.lock(uid, "vault/" + name, plain)
            plain = None
    item["away"] = meta
    _write_file(data)
    return meta


def away_list() -> list[dict]:
    """Every secret in this account's vault with its choice, in the words Settings shows."""
    aw = _away()
    data = _read_file()
    if data.get("key") != "sealed" and not (_uid() and _seal().exists(_uid())):
        return []
    out = []
    for name, it in sorted((data.get("items") or {}).items()):
        m = it.get("away")
        out.append({"name": name, "label": label(name),
                    "mode": (m or {}).get("mode") or "off", "until": (m or {}).get("until"),
                    "away": aw.usable(m), "words": aw.words(m)})
    m = (data.get("away") or {}).get(BROWSER)
    from . import cdpbrowser
    if m or cdpbrowser.has_profile(_uid()):
        out.append({"name": BROWSER, "label": LABELS[BROWSER], "mode": (m or {}).get("mode") or "off",
                    "until": (m or {}).get("until"), "away": aw.usable(m), "words": aw.words(m)})
    return out


class _quiet:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return True


def reseal(uid: str) -> int:
    """At an account's first sign-in after the update: every item moves from the vault's old key
    to the account's seal, and the old key is deleted. Run inside `users.as_user(uid)`. Returns
    how many moved. A vault whose old key can't be read is left as it is, and says so."""
    data = _read_file()
    if not uid or data.get("key") in ("sealed",):
        return 0
    items = data.get("items") or {}
    if not data.get("key"):
        data.update(key="sealed", v=1, items={})
        _write_file(data)
        return 0
    key, mech, problem = _load_key(create=False)
    if problem or not key:
        return 0
    moved = {}
    for name, it in items.items():
        try:
            plain = _aead(key).decrypt(base64.b64decode(it["n"]), base64.b64decode(it["c"]), name.encode())
        except Exception:
            continue
        moved[name] = {"s": _seal().seal_bytes(uid, plain, "vault/" + name), "at": it.get("at") or time.time()}
        # it worked with nobody signed in before the update, so it keeps doing so until revoked
        meta = _carry_away(uid, name, None, plain)
        if meta:
            moved[name]["away"] = meta
    data.update(key="sealed", items=moved)
    _write_file(data)
    if mech == "file":
        with _quiet():
            _key_path().unlink()
    elif mech == "keyring" and _keyring_tool() == "secret-tool":
        with _quiet():
            subprocess.run(["secret-tool", "clear", "service", SERVICE, "key", _scope()],
                           capture_output=True, timeout=10)
    return len(moved)


def drop_sealed(uid: str) -> int:
    """Start fresh with no recovery code: the sealed items can never be opened again."""
    from . import users as usersmod
    with usersmod.as_user(uid):
        data = _read_file()
        if data.get("key") != "sealed":
            return 0
        n = len(data.get("items") or {})
        data["items"] = {}
        data.pop("away", None)
        _write_file(data)
        return n


def _clear(v) -> bool:
    return isinstance(v, str) and bool(v) and not is_ref(v) and not v.startswith("•••")


def _secret_places(cfg: dict):
    """Every (dict, key, vault name) in a config that holds a secret: SECRET_KEYS, each
    channel field marked secret (channels.py), and the MCP servers' env and headers whose name
    reads as a secret (trace.SECRET, the one rule for that). A value that is a path or a flag
    stays where the person can read and edit it."""
    for section, key, name in SECRET_KEYS:
        sec = cfg.get(section)
        if isinstance(sec, dict):
            yield sec, key, name
    from . import channels as chmod
    chans = cfg.get("channels") if isinstance(cfg.get("channels"), dict) else {}
    for ch in chmod.CATALOGUE:
        sec = chans.get(ch.id)
        if isinstance(sec, dict):
            for f in ch.fields:
                if f.secret:
                    yield sec, f.key, f"channels.{ch.id}.{f.key}"
    from .trace import SECRET
    for srv in cfg.get("mcp_servers") or []:
        if not isinstance(srv, dict):
            continue
        sname = _clean(srv.get("name") or "server")
        for part in ("env", "headers"):
            d = srv.get(part)
            if isinstance(d, dict):
                for k in list(d):
                    if SECRET.search(str(k)):
                        yield d, k, f"mcp.{sname}.{part}.{_clean(k)}"


def _machine_places(cfg: dict):
    """The machine's own secrets in a config: provider API keys and the voice engines' keys.
    They go into the MACHINE's vault whoever is saving, and only a machine save moves them (an
    account's file never holds them: they aren't USER_KEYS)."""
    for pid, conf in (cfg.get("providers") or {}).items():
        if isinstance(conf, dict):
            yield conf, "api_key", f"provider.{_clean(pid)}.api_key"
    for eng, conf in ((cfg.get("speech") or {}) if isinstance(cfg.get("speech"), dict) else {}).items():
        if isinstance(conf, dict) and "api_key" in conf:
            yield conf, "api_key", f"speech.{_clean(eng)}.api_key"


def machine_value(value, actor: str = "provider") -> str:
    """A machine secret (a provider's API key) as the code that calls the provider wants it:
    a reference is opened in the MACHINE's vault, whoever is asking, once an hour (`held`). A
    value that isn't a reference passes through (an environment variable, an old config)."""
    if not is_ref(value):
        return str(value or "")
    name = value[len(REF):]
    if name.startswith("tenant."):
        # an Isolated Tenant's own key, in its own vault (users.TENANT_KEYS)
        with in_tenant(name.split(".", 2)[1]):
            return held(value, actor)
    from . import users as usersmod
    with usersmod.as_user(""):
        return held(value, actor)


def to_service() -> int:
    """The machine's vault moves from its own key to the service key, once: one key the service
    holds for every secret it opens by itself. Run as the machine (users.as_user("")). Returns
    how many items moved; a vault whose old key can't be read is left as it is."""
    data = _read_file()
    if _uid() or data.get("key") not in ("file", "keyring"):
        return 0
    key, mech, problem = _load_key(create=False)
    if problem or not key:
        return 0
    new = _away()._load(create=True)
    if not new:
        return 0
    items = {}
    for name, it in (data.get("items") or {}).items():
        try:
            plain = _aead(key).decrypt(base64.b64decode(it["n"]), base64.b64decode(it["c"]), name.encode())
        except Exception:
            return 0                       # never half-move a vault
        nonce = os.urandom(12)
        items[name] = {"n": base64.b64encode(nonce).decode(),
                       "c": base64.b64encode(_aead(new).encrypt(nonce, plain, name.encode())).decode(),
                       "at": it.get("at") or time.time()}
    data.update(key="service", items=items)
    _write_file(data)
    if mech == "file":
        with _quiet():
            _key_path().unlink()
    elif mech == "keyring" and _keyring_tool() == "secret-tool":
        with _quiet():
            subprocess.run(["secret-tool", "clear", "service", SERVICE, "key", _scope()],
                           capture_output=True, timeout=10)
    return len(items)


def adopt(cfg: dict) -> bool:
    """Move the secrets config still holds in clear into the vault, leaving
    references. Returns True when something moved (and config should be saved).
    Never runs when the vault is locked: a migration that cannot store must not
    blank the value it was moving. Called on load AND before every save (config.py), so a
    token typed into Settings is in the vault before the file is written."""
    moved = False
    same: dict = {}            # one value in two places (Telegram's two blocks) is one secret
    for sec, key, name in list(_secret_places(cfg)):
        v = sec.get(key)
        if _clear(v):
            try:
                sec[key] = same.get(v) or put(name, v)
                same[v] = sec[key]
                moved = True
            except RuntimeError:
                return moved
    if not _uid():
        for sec, key, name in list(_machine_places(cfg)):
            v = sec.get(key)
            if _clear(v):
                try:
                    sec[key] = put(name, v)
                    moved = True
                except RuntimeError:
                    return moved
    return moved


#: (config section, key, vault name) — what `adopt` moves, beside the channel fields and MCP
#: keys `_secret_places` finds. The rule: a value that opens somebody's account or bot.
#: Provider API keys are the MACHINE's (USER_KEYS says why) and stay where they are.
SECRET_KEYS = (
    ("mail", "password", "mail.password"),
    ("calendar", "password", "calendar.password"),
    ("mail", "oauth", "oauth.mail"),
    ("calendar", "oauth", "oauth.calendar"),
    ("telegram", "bot_token", "telegram.bot_token"),
    ("whatsapp", "access_token", "whatsapp.access_token"),
    ("whatsapp", "app_secret", "whatsapp.app_secret"),
)


_CACHE: dict = {}
CACHE_S = 3600.0


def held(value, actor: str) -> str:
    """`resolve` for a value used over and over by a running service (a bot's token on every
    poll): read from the vault once an hour per account, so the diary gets a line an hour and
    not one per request. A value that isn't a reference passes through."""
    if not is_ref(value):
        return str(value or "")
    k = (_uid(), _TENANT.get(), value)
    hit = _CACHE.get(k)
    if hit and time.time() - hit[1] < CACHE_S:
        return hit[0]
    try:
        out = get(value, actor)
    except Exception:
        out = ""
    # kept in memory only when it may be used with nobody signed in anyway: a secret set to
    # "only while you're signed in" is read each time, so signing out still closes it
    name = _clean(value[len(REF):])
    if out and (not sealed() or _away().usable(away_meta(name))):
        _CACHE[k] = (out, time.time())
    return out


def forget_held() -> None:
    _CACHE.clear()


def _clean(name: str) -> str:
    return "".join(c for c in str(name or "") if c.isalnum() or c in "._-")[:120]
