"""The Bento Registry at bentoboxos.com: browse freely, publish signed in.

The registry is a Supabase project; its server (migrations, the publish and
download functions) lives in the website repo, bento-box-os-com, under
supabase/. This module is only the client. Reading is open:
the catalogue and the files are public, and a Bento that never signs in can
still find and install things. Publishing needs three things, each checked by
the registry's own `publish` function and never only here:

- **a person**, signed in with a code sent to their email (Supabase Auth, OTP);
- **this machine**, registered to that person with an Ed25519 key whose private
  half never leaves this home (`<home>/registry/machine.key`, 0600);
- **a signature** over the exact bytes being published.

Before anything is sent, `report()` reads the package for credentials (which
refuse, with no override: agentbundle's tripwire) and for things that are
merely personal (emails, phone numbers, home folders, private addresses), which
are shown to the person. `publish()` takes an `ack`: the hash of the bytes the
person was shown the report for, so what was read is what goes.

An installing Bento checks the file's hash and the publisher's signature itself,
pins the publisher's key on first install (appregistry's SSH model), and then
hands the package to the same import doors a file from anywhere goes through.

Stdlib and `cryptography` only, no HTTP framework and no asyncio, so `bento
registry` does all of it with the server down. The refresh token is in the vault.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

#: The registry. Both values are public: the key is Supabase's publishable key,
#: which can only do what row-level security lets an anonymous caller do.
HUB_URL = "https://oaculfexvasryxvopbgw.supabase.co"
HUB_KEY = "sb_publishable_AtJAikkezFxL1lZQKZUUBQ_WJ-WXn5R"
SITE = "https://bentoboxos.com/registry/"

KINDS = {
    "app": "agentos-app/1",
    "agent": "agentos-agent/1",
    "skill": "bento-skill/1",
    "soul": "bento-soul/1",
    "tool": "bento-tool/1",
}
KIND_WORDS = {"app": "App", "agent": "Agent", "skill": "Skill", "soul": "Soul", "tool": "Tool"}
MAX_BYTES = 2 * 1024 * 1024
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
HANDLE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")
VERSION = re.compile(r"^[0-9]{1,6}(\.[0-9]{1,6}){0,2}$")
VAULT_NAME = "registry.session"
PINS_KEY = "hub"
TIMEOUT = 25

_ACCESS: dict[str, tuple[str, float]] = {}      # account -> (access token, expiry); memory only


class HubError(RuntimeError):
    """A refusal in words, from here or from the registry."""

    def __init__(self, msg: str, status: int = 0, extra: dict | None = None):
        super().__init__(msg)
        self.status = status
        self.extra = extra or {}


# ---------------------------------------------------------------------------
# Where things are kept
# ---------------------------------------------------------------------------

def _uid() -> str:
    from . import users as usersmod
    return (usersmod.current() or "") if usersmod.enabled() else ""


def home() -> Path:
    from . import users as usersmod
    return usersmod.home_for(_uid())


def _dir(create: bool = True) -> Path:
    d = home() / "registry"
    if create and not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    return d


def _state_path(create: bool = True) -> Path:
    return _dir(create) / "hub.json"


def _read_state() -> dict:
    try:
        return json.loads(_state_path(create=False).read_text())
    except (OSError, ValueError):
        return {}


def _write_state(st: dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _key_path() -> Path:
    return _dir() / "machine.key"


# ---------------------------------------------------------------------------
# HTTP: one small client, the registry's address only
# ---------------------------------------------------------------------------

def _call(method: str, path: str, body=None, token: str = "", headers: dict | None = None,
          raw: bool = False):
    url = HUB_URL + path
    h = {"apikey": HUB_KEY, "Accept": "application/json", "User-Agent": "bento-registry/1"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            out = r.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        try:
            j = json.loads(text)
        except ValueError:
            j = {}
        msg = (j.get("error") if isinstance(j.get("error"), str) else "") or j.get("msg") \
            or j.get("message") or j.get("error_description") or text[:200] or f"HTTP {e.code}"
        raise HubError(str(msg), e.code, j if isinstance(j, dict) else {}) from None
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise HubError(f"couldn't reach the Bento registry ({getattr(e, 'reason', e)})") from None
    if raw:
        return out
    return json.loads(out or b"null")


def _fetch_bytes(url: str) -> bytes:
    """A package file. Only from the registry's own storage, never an address a row names."""
    if not url.startswith(HUB_URL + "/storage/v1/object/public/packages/"):
        raise HubError("the registry gave a file address outside its own storage")
    req = urllib.request.Request(url, headers={"User-Agent": "bento-registry/1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read(MAX_BYTES + 1)
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise HubError(f"couldn't download the package ({getattr(e, 'reason', e)})") from None
    if len(data) > MAX_BYTES:
        raise HubError("the package is over 2 MB")
    return data


# ---------------------------------------------------------------------------
# Signing in: a code by email
# ---------------------------------------------------------------------------

def _clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}", email):
        raise HubError("that doesn't look like an email address")
    return email


def masked(email: str) -> str:
    if "@" not in (email or ""):
        return ""
    user, dom = email.split("@", 1)
    return (user[:2] + "…" if len(user) > 2 else user[:1] + "…") + "@" + dom


def start_login(email: str) -> dict:
    """Send a sign-in code to this address. A new address becomes an account."""
    email = _clean_email(email)
    _call("POST", "/auth/v1/otp", {"email": email, "create_user": True})
    st = _read_state()
    st["pending_email"] = email
    _write_state(st)
    return {"sent": True, "to": masked(email)}


def finish_login(code: str, email: str = "") -> dict:
    """Trade the emailed code for a session. The refresh token goes in the vault."""
    st = _read_state()
    email = _clean_email(email or st.get("pending_email") or "")
    code = re.sub(r"\s+", "", code or "")
    if not re.fullmatch(r"[0-9]{6,10}", code):
        raise HubError("the code is the 6 to 10 digits in the email")
    tok = _call("POST", "/auth/v1/verify", {"type": "email", "email": email, "token": code})
    _keep_session(tok)
    st = _read_state()
    st.pop("pending_email", None)
    st.update(email=email, user_id=((tok.get("user") or {}).get("id") or ""), signed_in_at=time.time())
    _write_state(st)
    prof = _profile(tok["access_token"], st["user_id"])
    if prof:
        st["handle"] = prof.get("handle") or ""
        _write_state(st)
    return status()


def _keep_session(tok: dict) -> None:
    from . import vault
    if not tok.get("access_token") or not tok.get("refresh_token"):
        raise HubError("the registry didn't return a session")
    vault.put(VAULT_NAME, tok["refresh_token"])
    _ACCESS[_uid()] = (tok["access_token"], time.time() + int(tok.get("expires_in") or 3600) - 60)


def _token() -> str:
    """A live access token, refreshed from the vault when it has run out."""
    from . import vault
    hit = _ACCESS.get(_uid())
    if hit and hit[1] > time.time():
        return hit[0]
    refresh = vault.get(VAULT_NAME, actor="registry")
    if not refresh:
        raise HubError("sign in to the Bento registry first", 401)
    try:
        tok = _call("POST", "/auth/v1/token?grant_type=refresh_token", {"refresh_token": refresh})
    except HubError as e:
        if e.status in (400, 401, 403):
            raise HubError("your registry session has ended; sign in again", 401) from None
        raise
    _keep_session(tok)
    return tok["access_token"]


def logout() -> dict:
    from . import vault
    try:
        _call("POST", "/auth/v1/logout", {}, token=_token())
    except HubError:
        pass
    _ACCESS.pop(_uid(), None)
    try:
        vault.forget(VAULT_NAME)
    except Exception:                                             # noqa: BLE001
        pass
    st = _read_state()
    for k in ("email", "user_id", "handle", "signed_in_at", "pending_email"):
        st.pop(k, None)
    _write_state(st)
    return status()


def _profile(token: str, user_id: str) -> dict | None:
    rows = _call("GET", "/rest/v1/profiles?select=handle&id=eq." + urllib.parse.quote(user_id),
                 token=token)
    return rows[0] if rows else None


# Names that read as Bento itself, kept for the registry's admins by the project's
# migration 003 (the same list; a test compares them). A listing under one of these
# is Bento's own, which is what the Store's mark says.
RESERVED = ("bento", "bentobox", "bentoboxos", "bento-ai", "bentoai", "bento-os",
            "bento-team", "official", "registry", "admin", "support")
OFFICIAL = "bento"


def set_handle(handle: str) -> dict:
    """The publisher name shown on every listing. The email is never shown."""
    handle = (handle or "").strip().lower()
    if not HANDLE.fullmatch(handle):
        raise HubError("a publisher name is 3 to 32 lower case letters, digits and dashes")
    # a reserved name is tried anyway: the registry decides, and lets its admins have it
    st = _read_state()
    tok = _token()
    try:
        if _profile(tok, st.get("user_id", "")):
            _call("PATCH", "/rest/v1/profiles?id=eq." + st["user_id"], {"handle": handle}, token=tok)
        else:
            _call("POST", "/rest/v1/profiles", {"id": st["user_id"], "handle": handle}, token=tok)
    except HubError as e:
        if "duplicate" in str(e) or e.status == 409:
            raise HubError(f"'{handle}' is taken; try another") from None
        if "kept for Bento" in str(e):
            raise HubError(f"'{handle}' is kept for Bento's own listings; choose another name") from None
        raise
    st["handle"] = handle
    _write_state(st)
    return status()


# ---------------------------------------------------------------------------
# This machine's key
# ---------------------------------------------------------------------------

def _ensure_key() -> tuple[str, str]:
    """(key_id, public_b64). Made once; the private half stays in this home."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption,
                                                              PrivateFormat, PublicFormat)
    p = _key_path()
    if p.exists():
        priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(p.read_bytes()))
    else:
        priv = Ed25519PrivateKey.generate()
        raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        tmp = p.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64encode(raw))
        os.replace(tmp, p)
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return key_id_of(pub), base64.b64encode(pub).decode()


def key_id_of(raw_pub: bytes) -> str:
    return "bm-" + hashlib.sha256(raw_pub).hexdigest()[:16]


def _sign(data: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(_key_path().read_bytes()))
    return base64.b64encode(priv.sign(("sha256:" + hashlib.sha256(data).hexdigest()).encode())).decode()


def register_machine(name: str = "") -> dict:
    """Tie this Bento to the signed-in person, so it may publish for them."""
    from . import config as cfgmod
    st = _read_state()
    tok = _token()
    key_id, pub = _ensure_key()
    name = re.sub(r"[\x00-\x1f\x7f]", "", (name or socket.gethostname() or "bento").strip())[:60] or "bento"
    rows = _call("GET", "/rest/v1/machines?select=key_id,revoked_at&key_id=eq." + key_id, token=tok)
    if rows and not rows[0].get("revoked_at"):
        st.update(key_id=key_id, machine=name)
        _write_state(st)
        return status()
    if rows:
        raise HubError("this machine's key was revoked; `bento registry register --new-key` makes a new one")
    _call("POST", "/rest/v1/machines",
          {"owner": st.get("user_id"), "name": name, "key_id": key_id, "public_key": pub,
           "version": _version(cfgmod)}, token=tok, headers={"Prefer": "return=minimal"})
    st.update(key_id=key_id, machine=name, registered_at=time.time())
    _write_state(st)
    return status()


def new_key() -> None:
    """Throw this machine's key away (after a revoke) so the next register makes another."""
    p = _key_path()
    if p.exists():
        p.rename(p.with_suffix(f".retired-{int(time.time())}"))
    st = _read_state()
    st.pop("key_id", None)
    _write_state(st)


def revoke_machine() -> dict:
    """Stop this machine publishing. What it already published stays signed by it."""
    st = _read_state()
    if not st.get("key_id"):
        raise HubError("this machine isn't registered")
    _call("PATCH", "/rest/v1/machines?key_id=eq." + st["key_id"],
          {"revoked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, token=_token(),
          headers={"Prefer": "return=minimal"})
    st.pop("key_id", None)
    st["revoked"] = True
    _write_state(st)
    return status()


def _version(cfgmod=None) -> str:
    try:
        return (Path(__file__).parent / "VERSION").read_text().strip()[:40]
    except OSError:
        return ""


def status() -> dict:
    """What this face shows: signed in or not, as whom, and whether this machine may publish."""
    from . import vault
    st = _read_state()
    have = bool(st.get("user_id")) and bool(_has_session(vault))
    return {
        "hub": HUB_URL, "site": SITE,
        "signed_in": have,
        "email": masked(st.get("email", "")) if have else "",
        "handle": st.get("handle", "") if have else "",
        "registered": have and bool(st.get("key_id")),
        "key_id": st.get("key_id", "") if have else "",
        "machine": st.get("machine", "") if have else "",
        "pending": masked(st.get("pending_email", "")),
        "can_publish": have and bool(st.get("key_id")) and bool(st.get("handle")),
        "next": _next_step(have, st),
    }


def _has_session(vault) -> bool:
    try:
        return vault.has(VAULT_NAME)
    except Exception:                                             # noqa: BLE001
        return False


def _next_step(have: bool, st: dict) -> str:
    if not have:
        return "sign in with your email to publish; browsing needs no account"
    if not st.get("handle"):
        return "choose the publisher name shown on your listings"
    if not st.get("key_id"):
        return "register this machine so it can sign what you publish"
    return ""


# ---------------------------------------------------------------------------
# What gets published
# ---------------------------------------------------------------------------

def package(kind: str, store, cfg: dict, name: str = "", **kw) -> dict:
    """Build the package for an agent, a skill, a soul or a tool. An app comes
    from the server's export, which owns its manifest."""
    from . import agentbundle
    if kind == "agent":
        try:
            bundle, _report = agentbundle.export(store, cfg, name=name or "", description=kw.get("description", ""),
                                                 apps=kw.get("apps", "none"), with_soul=bool(kw.get("with_soul")),
                                                 mcp=kw.get("mcp", "used"))
        except agentbundle.LeakRefusal as e:
            raise HubError(str(e), extra={"leaks": e.findings}) from None
        return bundle
    if kind == "skill":
        s = store.get_skill(name)
        if not s:
            raise HubError(f"there is no skill called '{name}' here")
        return {"format": KINDS["skill"], "name": s["name"], "description": s.get("description") or "",
                "content": s.get("content") or ""}
    if kind == "soul":
        from . import config as cfgmod
        text = cfgmod.load_soul()
        if not text.strip():
            raise HubError("this agent's soul is empty")
        return {"format": KINDS["soul"], "name": name or "soul", "content": text}
    if kind == "tool":
        conf = (cfg.get("mcp_servers") or {}).get(name)
        if not conf:
            raise HubError(f"there is no MCP server called '{name}' here")
        return {"format": KINDS["tool"], "name": name, "mcp": agentbundle.sanitize_mcp_conf(name, conf)}
    raise HubError(f"kind must be one of {', '.join(KINDS)}")


def text_of(pkg: dict) -> str:
    """The exact bytes that are reported on, signed and stored."""
    return json.dumps(pkg, indent=1, ensure_ascii=False, sort_keys=True)


# Personal, not secret: shown to the person, never a refusal on its own.
_PERSONAL = (
    ("an email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("a phone number", re.compile(r"(?<![\w.])\+?\d[\d ()-]{8,}\d(?![\w.])")),
    ("a home folder", re.compile(r"(/home/[A-Za-z0-9._-]+|/Users/[A-Za-z0-9._-]+|[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9._-]+)")),
    ("a private network address", re.compile(
        r"\b(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01])|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7]))\.\d{1,3}\.\d{1,3}\b")),
    ("a local machine name", re.compile(r"\b[A-Za-z0-9-]{2,}\.(local|lan|internal|home\.arpa)\b")),
    ("a web address carrying a key", re.compile(r"https?://[^\s\"']*[?&](key|token|sig|signature|secret|auth|code)=[^\s\"'&]{6,}", re.I)),
)
# What the phone rule matches that is not a phone number: a bare run of digits (every app
# package's scan time is ten of them, and so is any timestamp) and a date written
# 2026-12-04. A number someone would ring has a + or a space, dash, dot or bracket in it.
_NOT_A_PHONE = re.compile(r"\d+|\d{4}-\d{2}-\d{2}")
_HARMLESS_EMAIL = re.compile(r"@(example\.(com|org|net)|users\.noreply\.github\.com|anthropic\.com)$|^(noreply|no-reply)@", re.I)


def _mask(s: str) -> str:
    s = s.strip()
    return s[:4] + "…" + s[-2:] if len(s) > 8 else s[:2] + "…"


def report(kind: str, text: str, pkg: dict | None = None) -> dict:
    """What this package carries that someone should look at before it is public.

    ``blocking`` (credentials, and an app this machine can't read as clean) stops
    the publish with no override. ``warnings`` (personal details) are the person's
    call. ``ack`` is the hash of these bytes; publish wants it back.
    """
    from . import agentbundle, appregistry
    pkg = pkg if pkg is not None else json.loads(text)
    blocking = [{"what": f["looks_like"], "line": f["line"], "excerpt": f["excerpt"]}
                for f in agentbundle.leak_scan(text)]
    warnings: list[dict] = []
    mine = _own_words()
    lines = text.split("\n")
    for label, rx in _PERSONAL:
        for i, ln in enumerate(lines, 1):
            for m in rx.finditer(ln):
                hit = m.group(0)
                if label == "an email address" and _HARMLESS_EMAIL.search(hit):
                    continue
                if label == "a phone number" and _NOT_A_PHONE.fullmatch(hit.strip()):
                    continue
                warnings.append({"what": label, "line": i, "excerpt": _mask(hit)})
                break
            if len([w for w in warnings if w["what"] == label]) >= 5:
                break
    for word, label in mine:
        for i, ln in enumerate(lines, 1):
            if word in ln.lower():
                warnings.append({"what": label, "line": i, "excerpt": _mask(word)})
                break
    security: dict = {}
    perms: list[str] = []
    if kind == "app":
        html = pkg.get("html") or ""
        security = appregistry.scan_block(html)
        man = pkg.get("manifest") or {}
        perms = sorted({f"{p.get('action')} {p.get('resource')}".strip()
                        for p in (man.get("permissions") or []) if isinstance(p, dict)})
        if pkg.get("checksum") != appregistry.package_checksum(man, html):
            blocking.append({"what": "the app's checksum doesn't match its contents", "line": 0, "excerpt": ""})
        prob = appregistry.author_problem(man)
        if prob:
            warnings.append({"what": prob, "line": 0, "excerpt": ""})
    elif kind == "agent":
        perms = sorted({f"{p.get('action')} {p.get('resource')}".strip()
                        for p in (pkg.get("permissions") or []) if isinstance(p, dict)})[:60]
    elif kind == "tool":
        mcp = pkg.get("mcp") or {}
        if mcp.get("command"):
            warnings.append({"what": "this tool starts a program on the machine that installs it",
                             "line": 0, "excerpt": str(mcp.get("command"))[:40]})
    verdict = "blocked" if blocking else (security.get("verdict") or "pass")
    if verdict == "pass" and warnings:
        verdict = "review"
    return {"kind": kind, "bytes": len(text.encode()), "ack": hashlib.sha256(text.encode()).hexdigest(),
            "blocking": blocking, "warnings": warnings, "verdict": verdict,
            "security": {k: security[k] for k in ("verdict", "scanner", "findings") if k in security},
            "permissions": perms, "ok": not blocking}


def _own_words() -> list[tuple[str, str]]:
    """This person's and this machine's own names, which shouldn't travel by accident."""
    out: list[tuple[str, str]] = []
    st = _read_state()
    em = (st.get("email") or "").lower()
    if em:
        out.append((em, "your registry email"))
    try:
        host = socket.gethostname().lower()
        if len(host) >= 4 and host not in ("localhost", "bento", "raspberrypi", "ubuntu"):
            out.append((host, "this machine's name"))
    except OSError:
        pass
    try:
        user = os.environ.get("USER", "").lower()
        if len(user) >= 4 and user not in ("root", "user", "admin", "pi"):
            out.append((user, "your login name"))
    except Exception:                                             # noqa: BLE001
        pass
    return out


def publish(kind: str, slug: str, version: str, text: str, *, ack: str, name: str = "",
            summary: str = "", icon: str = "", notes: str = "") -> dict:
    """Send a package. Refuses before the network when the report blocks, when the
    person hasn't seen the report for these bytes, or when this machine can't sign."""
    if kind not in KINDS:
        raise HubError(f"kind must be one of {', '.join(KINDS)}")
    slug = (slug or "").strip().lower()
    if not SLUG.fullmatch(slug):
        raise HubError("the address name is lower case letters, digits and dashes, 2 to 64 long")
    if not VERSION.fullmatch(version or ""):
        raise HubError("a version is numbers with dots, like 1.2.0")
    data = text.encode()
    if not data or len(data) > MAX_BYTES:
        raise HubError("the package is empty or over 2 MB")
    rep = report(kind, text)
    if not rep["ok"]:
        raise HubError("this won't be published: " + "; ".join(
            f"{b['what']}" + (f" on line {b['line']}" if b["line"] else "") for b in rep["blocking"]),
            extra={"report": rep})
    if ack != rep["ack"]:
        raise HubError("look at the report for this exact package first", extra={"report": rep})
    st = status()
    if not st["signed_in"]:
        raise HubError("sign in to the Bento registry first", 401)
    if not st["handle"]:
        raise HubError("choose a publisher name first")
    if not st["registered"]:
        raise HubError("register this machine first")
    body = {
        "kind": kind, "slug": slug, "version": version, "package": text,
        "key_id": st["key_id"], "signature": _sign(data),
        "name": name, "summary": summary, "icon": icon, "notes": notes,
        "permissions": rep["permissions"],
        "report": {"verdict": rep["verdict"], "warnings": len(rep["warnings"]),
                   "warned": sorted({w["what"] for w in rep["warnings"]}),
                   "security": rep["security"].get("verdict", ""),
                   "checked_by": "bento " + _version()},
    }
    return _call("POST", "/functions/v1/publish", body, token=_token())


# ---------------------------------------------------------------------------
# Reading the registry: open to everyone
# ---------------------------------------------------------------------------

def search(q: str = "", kind: str = "", limit: int = 50) -> list[dict]:
    params = {"select": "kind,slug,name,summary,icon,downloads,publisher,latest,verdict,version_count,updated_at",
              "order": "downloads.desc,updated_at.desc", "limit": str(max(1, min(int(limit), 200)))}
    if kind:
        if kind not in KINDS:
            raise HubError(f"kind must be one of {', '.join(KINDS)}")
        params["kind"] = "eq." + kind
    q = re.sub(r"[^\w\s-]", " ", (q or "")).strip()[:60]
    if q:
        params["or"] = f"(name.ilike.*{q}*,summary.ilike.*{q}*,slug.ilike.*{q}*)"
    return _call("GET", "/rest/v1/catalog?" + urllib.parse.urlencode(params))


def versions(kind: str, slug: str) -> list[dict]:
    rows = _call("GET", "/rest/v1/listings?select=id&kind=eq.{}&slug=eq.{}".format(
        urllib.parse.quote(kind), urllib.parse.quote(slug)))
    if not rows:
        return []
    return _call("GET", "/rest/v1/versions?select=version,notes,downloads,created_at,yanked,permissions,report"
                 "&order=created_at.desc&listing_id=eq." + rows[0]["id"])


def parse_ref(ref: str) -> tuple[str, str, str]:
    """`kind/slug[@version]` → (kind, slug, version)."""
    ref = (ref or "").strip()
    m = re.fullmatch(r"(app|agent|skill|soul|tool)/([a-z0-9][a-z0-9-]{0,62}[a-z0-9])(?:@([0-9.]+))?", ref)
    if not m:
        raise HubError("name it as kind/name, like app/hello-notes or skill/pdf-tables@1.2")
    return m.group(1), m.group(2), m.group(3) or ""


def fetch(kind: str, slug: str, version: str = "", cfg: dict | None = None) -> dict:
    """Download one version and check it here: the hash, the publisher's signature,
    a revoked key, and whether this publisher is the one seen last time."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from . import appregistry
    q = {"kind": kind, "slug": slug}
    if version:
        q["version"] = version
    meta = _call("GET", "/functions/v1/download?" + urllib.parse.urlencode(q))
    data = _fetch_bytes(meta.get("url") or "")
    digest = hashlib.sha256(data).hexdigest()
    if digest != meta.get("sha256"):
        raise HubError("the downloaded file doesn't match the registry's record of it; it wasn't installed")
    pub = meta.get("publisher_key") or ""
    if not pub or key_id_of(base64.b64decode(pub)) != meta.get("key_id"):
        raise HubError("the publisher's key doesn't match the one that signed this")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(
            base64.b64decode(meta.get("signature") or ""), ("sha256:" + digest).encode())
    except (InvalidSignature, ValueError):
        raise HubError("the publisher's signature doesn't match the file; it wasn't installed") from None
    text = data.decode()
    pkg = json.loads(text)
    if pkg.get("format") != KINDS.get(kind):
        raise HubError(f"the file isn't a {kind} package")
    pins = (((cfg or {}).get("registry") or {}).get(PINS_KEY)) or {}
    pin_status, pin_note = appregistry.tofu_check(pins, f"{kind}/{slug}", "bento-registry", meta["key_id"])
    return {"kind": kind, "slug": slug, "version": meta.get("version"), "name": meta.get("name"),
            "publisher": meta.get("publisher"), "revoked": bool(meta.get("revoked")),
            "key_id": meta["key_id"], "sha256": digest, "notes": meta.get("notes") or "",
            "report": meta.get("report") or {}, "permissions": meta.get("permissions") or [],
            "pin_status": pin_status, "pin_note": pin_note, "package": pkg, "text": text,
            "local": report(kind, text, pkg)}


def pin(cfg: dict, got: dict) -> dict:
    """Record the publisher's key for this listing after the person installed it."""
    from . import appregistry
    reg = cfg.setdefault("registry", {})
    pins = reg.setdefault(PINS_KEY, {})
    reg[PINS_KEY] = appregistry.tofu_record(pins, f"{got['kind']}/{got['slug']}", "bento-registry",
                                            got["key_id"], "sha256:" + got["sha256"])
    return cfg


def slug_of(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:64].strip("-")
    return s if len(s) >= 2 else (s + "-x" if s else "")
