"""Users: several people on one machine, isolated by directory rather than by query.

Everything personal in this OS already lives in one SQLite file and one directory
tree. So a user is not a column — a user is **their own home**:

    ~/.agentos/                     the machine
      config.json                   machine settings: providers, keys, models, remote,
                                    components. Admins change these; everyone reads them.
      users.json                    the registry: id, name, role, password hash
      shared/                       the one place data crosses between people
      users/<id>/
        agentos.db                  memory, KG, conversations, grants, flows, tasks, audit
        config.json                 their channels, their MCP, their look, their spaces
        workspace/                  their files
        assets/                     their gallery
        soul.md                     their agent's identity

WHY DIRECTORIES AND NOT A `user_id` COLUMN
==========================================
`space_id` is already a column, and its rule is deliberately leaky: `space_id IN
('', :active)` — a space sees its own rows AND the global ones, because a space is
a project you are working on, not a wall. Users are the opposite claim. One
forgotten WHERE clause in 200 query sites is somebody reading a colleague's
memory, and no amount of review makes that failure mode acceptable.

Two files cannot leak into each other. That is the whole argument.

THE SEAM
========
`current()` is a contextvar the request middleware sets. `store_for()` and
`cfg_for()` cache one Store and one config per user, so every existing
`state["store"]` call site keeps working unchanged and resolves to the right
person's data. Background work (the scheduler, a channel) runs inside
`as_user(uid)`, because a job belongs to whoever created it — a nightly briefing
must read its owner's memory, not whoever happened to log in last.

TWO ROLES, AND THEY ARE ABOUT THE MACHINE
=========================================
    executor   everything inside their own home: agents, flows, jobs, apps,
               channels, MCP, credentials, their own permissions.
    admin      all of that, plus the machine: add and remove users, change
               providers and models, install components, remote access.

There is deliberately no per-user grid of capabilities. Grants already answer
"what may this principal do" in far more detail than a role ever could, and they
are per-user because the `grants` table is per-user. The role answers only the one
question grants cannot: may you change things that affect everybody?

SHARING
=======
`shared/` is the single crossing point, and it is opt-in in one direction: you
publish a copy, and somebody else installs a copy. Nothing is live-linked, because
a shared app that changes under you is a supply-chain problem in a filesystem.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from . import config as cfgmod

ROLES = ("admin", "executor")

#: The id of whoever this request/turn belongs to. '' means the single-user
#: machine that has never added anybody — see `enabled()`.
_current: contextvars.ContextVar[str] = contextvars.ContextVar("agentos_user", default="")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,30}$")


# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------

def registry_path() -> Path:
    return cfgmod.AGENTOS_HOME / "users.json"


def users_root() -> Path:
    return cfgmod.AGENTOS_HOME / "users"


def shared_root() -> Path:
    return cfgmod.AGENTOS_HOME / "shared"


def home_for(uid: str) -> Path:
    """A user's own directory, or the machine home for the single-user case.

    Falling back to AGENTOS_HOME is what makes this whole module invisible until
    somebody adds a second person: an install that never does keeps using exactly
    the files it always used, and nothing needs migrating.
    """
    return users_root() / uid if uid else cfgmod.AGENTOS_HOME


def db_for(uid: str) -> Path:
    return home_for(uid) / "agentos.db"


def cfg_path_for(uid: str) -> Path:
    return home_for(uid) / "config.json"


def soul_path_for(uid: str) -> Path:
    return home_for(uid) / "soul.md"


def assets_root_for(uid: str) -> Path:
    return home_for(uid) / "assets"


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def _read() -> dict:
    p = registry_path()
    if not p.exists():
        return {"users": []}
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) and isinstance(d.get("users"), list) else {"users": []}
    except Exception:
        return {"users": []}


def _write(d: dict) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    os.replace(tmp, p)
    os.chmod(p, 0o600)          # it holds password hashes


def enabled() -> bool:
    """Is this a multi-user machine?

    False until somebody actually adds a user. Every route that asks "who is this"
    gets '' and behaves exactly as it did before — one person, one home, no login
    screen. Multi-user is a thing you turn on by needing it.
    """
    return bool(_read()["users"])


def list_users(safe: bool = True) -> list[dict]:
    out = []
    for u in _read()["users"]:
        d = dict(u)
        if safe:
            d.pop("pass_hash", None)
            d.pop("salt", None)
        out.append(d)
    return sorted(out, key=lambda u: (u.get("role") != "admin", u.get("name", "")))


def get(uid: str) -> dict | None:
    for u in _read()["users"]:
        if u["id"] == uid:
            return dict(u)
    return None


def by_name(name: str) -> dict | None:
    n = (name or "").strip().lower()
    for u in _read()["users"]:
        if u["name"] == n:
            return dict(u)
    return None


def is_admin(uid: str) -> bool:
    """A machine with no users has no one to refuse: the single user IS the admin.

    Getting this backwards would lock somebody out of their own laptop the moment
    the module shipped.
    """
    if not enabled():
        return True
    u = get(uid)
    return bool(u and u.get("role") == "admin")


def admin_count() -> int:
    return sum(1 for u in _read()["users"] if u.get("role") == "admin")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: str = "") -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256, the same shape `remote.py` already uses for the remote
    passphrase — one hashing story on this machine rather than two."""
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return h.hex(), salt


def check_password(uid: str, password: str) -> bool:
    u = get(uid)
    if not u or not u.get("pass_hash"):
        return False
    got, _ = hash_password(password or "", u.get("salt", ""))
    return hmac.compare_digest(got, u["pass_hash"])


def password_problem(password: str) -> str:
    if len(password or "") < 8:
        return "a password needs at least 8 characters"
    return ""


# ---------------------------------------------------------------------------
# Adding and removing people
# ---------------------------------------------------------------------------

def name_problem(name: str) -> str:
    n = (name or "").strip().lower()
    if not _NAME_RE.match(n):
        return ("a username is 2-31 characters of lowercase letters, digits, "
                "'.', '_' or '-'")
    if by_name(n):
        return f"there is already a user called '{n}'"
    return ""


def create(name: str, password: str, role: str = "executor",
           display: str = "") -> dict:
    """Add a person, and build them a home.

    The directory is made here rather than lazily on first login, because a user
    who exists in the registry but has no home is a user whose first request 500s
    — and that request is the first thing they ever do on the machine.
    """
    n = (name or "").strip().lower()
    problem = name_problem(n) or password_problem(password)
    if problem:
        raise ValueError(problem)
    if role not in ROLES:
        raise ValueError(f"a role is one of {', '.join(ROLES)}")
    pw, salt = hash_password(password)
    uid = secrets.token_hex(8)
    first = not _read()["users"]
    # The first person to be added must be an admin, whatever was asked for: a
    # machine whose only account cannot administer it is a machine nobody can
    # administer, and there is no second account to fix it from.
    if first:
        role = "admin"
    d = _read()
    d["users"].append({"id": uid, "name": n, "display": (display or n).strip()[:60],
                       "role": role, "pass_hash": pw, "salt": salt,
                       "created_at": time.time()})
    _write(d)
    if first:
        adopt(uid)
    provision(uid)
    reset_caches()   # `enabled()` has just flipped: every cached view is now wrong
    return {k: v for k, v in (get(uid) or {}).items() if k not in ("pass_hash", "salt")}


def adopt(uid: str) -> None:
    """Hand the machine's existing single-user world to the first account.

    Somebody has been using this machine — there are agents, conversations, a
    memory, a linked phone. Adding the first user must not look like a fresh
    install to the person who was already here, so their home IS the machine home,
    moved: the database, the soul, the assets and the per-user half of the config.

    The machine config is then stripped of those keys. It has to be: every user
    created afterwards layers their own config over the machine's, so leaving a
    Telegram token there would hand it to the next person who signs up.
    """
    h = home_for(uid)
    h.mkdir(parents=True, exist_ok=True)
    src_db = cfgmod.AGENTOS_HOME / "agentos.db"
    for suffix in ("", "-wal", "-shm"):
        s = src_db.with_name(src_db.name + suffix)
        if s.exists():
            shutil.move(str(s), str(h / s.name))
    for name in ("soul.md", "assets", "whatsapp"):
        s = cfgmod.AGENTOS_HOME / name
        if s.exists():
            shutil.move(str(s), str(h / name))
    machine = cfgmod.load_config()
    own = {k: machine[k] for k in USER_KEYS if k in machine}
    own.setdefault("setup_complete", bool(machine.get("setup_complete")))
    cfg_path_for(uid).write_text(json.dumps(own, indent=2))
    os.chmod(cfg_path_for(uid), 0o600)
    cfgmod.save_config(machine_view(machine))


def provision(uid: str) -> Path:
    """Make the directory tree, 0700. It is somebody's whole private world."""
    h = home_for(uid)
    for sub in ("", "workspace", "assets"):
        (h / sub).mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(h, 0o700)
    except OSError:
        pass
    if not cfg_path_for(uid).exists():
        cfg_path_for(uid).write_text(json.dumps(_fresh_user_cfg(uid), indent=2))
        os.chmod(cfg_path_for(uid), 0o600)
    return h


def set_role(uid: str, role: str) -> dict:
    if role not in ROLES:
        raise ValueError(f"a role is one of {', '.join(ROLES)}")
    u = get(uid)
    if not u:
        raise ValueError("no such user")
    # A machine with no admin cannot be administered, and nothing in the UI can
    # rescue it — the only way back would be editing JSON by hand.
    if u.get("role") == "admin" and role != "admin" and admin_count() <= 1:
        raise ValueError("this is the last admin — promote somebody else first")
    d = _read()
    for x in d["users"]:
        if x["id"] == uid:
            x["role"] = role
    _write(d)
    return {"ok": True, "role": role}


def set_password(uid: str, password: str) -> dict:
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    pw, salt = hash_password(password)
    d = _read()
    found = False
    for x in d["users"]:
        if x["id"] == uid:
            x["pass_hash"], x["salt"] = pw, salt
            found = True
    if not found:
        raise ValueError("no such user")
    _write(d)
    return {"ok": True}


def delete(uid: str, wipe: bool = False) -> dict:
    """Remove a user. Their home is KEPT unless `wipe` is asked for explicitly.

    Deleting an account and destroying everything that person made are two
    different decisions, and conflating them means one mis-click costs work that
    was never the admin's to throw away.
    """
    u = get(uid)
    if not u:
        raise ValueError("no such user")
    if u.get("role") == "admin" and admin_count() <= 1:
        raise ValueError("this is the last admin — promote somebody else first")
    d = _read()
    d["users"] = [x for x in d["users"] if x["id"] != uid]
    _write(d)
    if wipe:
        shutil.rmtree(home_for(uid), ignore_errors=True)
    _forget(uid)
    return {"ok": True, "wiped": bool(wipe), "home": str(home_for(uid))}


def _fresh_user_cfg(uid: str = "") -> dict:
    """What a new person's config starts as: nothing but the per-user sections.

    Machine settings are deliberately absent rather than copied — a copy would be
    a second source of truth for the provider key, and the one that drifted would
    be whichever user last opened Settings.

    `setup_complete: False` is the interesting one. Onboarding is a per-user arc —
    name your agent, say hello to it, build one, pick a look — so a new person
    lands in the wizard rather than in somebody else's finished desktop.
    """
    return {"channels": {}, "mcp_servers": [], "desktop": {}, "spaces": {},
            "credentials": {}, "setup_complete": False,
            "workspace": str(home_for(uid) / "workspace") if uid else ""}


# ---------------------------------------------------------------------------
# The seam: who is this request, and what data do they see
# ---------------------------------------------------------------------------

def current() -> str:
    return _current.get()


def set_current(uid: str) -> None:
    _current.set(uid or "")


class as_user:
    """Run a block as somebody, and put it back afterwards.

    Background work needs this: a scheduled job belongs to whoever created it, so
    the scheduler enters the owner's context before running it. Without that, a
    nightly briefing would read whichever user's memory happened to be current —
    which is both wrong and a leak.
    """

    def __init__(self, uid: str):
        self.uid = uid or ""
        self._token = None

    def __enter__(self):
        self._token = _current.set(self.uid)
        return self.uid

    def __exit__(self, *_exc):
        if self._token is not None:
            _current.reset(self._token)
        return False


_stores: dict[str, object] = {}
_cfgs: dict[str, dict] = {}


def store_for(uid: str | None = None):
    """One Store per user, cached. SQLite connections are not free and the object
    holds live state (grants_version, the FTS index), so handing out a new one per
    request would be both slow and subtly wrong."""
    from .memory import Store
    uid = current() if uid is None else (uid or "")
    st = _stores.get(uid)
    if st is None:
        fresh = bool(uid) and not db_for(uid).exists()
        if uid:
            provision(uid)
        st = Store(db_for(uid))
        _stores[uid] = st
        if fresh:
            _seed(st)
    return st


def _seed(store) -> None:
    """What a brand-new account's database starts with.

    The same specialists and the same example flow a fresh single-user install
    gets. Without this a new person opens Workflows to an empty list and has no
    example of what a subagent even is — while the machine they are sitting at
    demonstrably has some, belonging to somebody else.

    Imported here rather than at module scope: `fabric` reaches `policy`, which
    imports this module.
    """
    try:
        from . import fabric as fabricmod
        from . import flows as flowsmod
        fabricmod.seed_builtins(cfgmod.load_config(), store)
        flowsmod.seed_builtin(store)
    except Exception:
        pass                # a seed is a courtesy; it must never block an account


def cfg_for(uid: str | None = None, machine: dict | None = None) -> dict:
    """The machine config with this user's own sections layered over it.

    A live dict, cached and mutated in place, because that is what every caller in
    the OS already assumes about `state["cfg"]`. `save_user_cfg` writes back only
    the per-user keys — the machine ones stay in the machine file, so a user
    saving their theme cannot rewrite everybody's provider key.
    """
    uid = current() if uid is None else (uid or "")
    if not uid:
        return machine if machine is not None else cfgmod.load_config()
    c = _cfgs.get(uid)
    if c is None:
        base = dict(machine if machine is not None else cfgmod.load_config())
        try:
            own = json.loads(cfg_path_for(uid).read_text())
        except Exception:
            own = _fresh_user_cfg()
        for k, v in own.items():
            base[k] = v
        base["_uid"] = uid
        _cfgs[uid] = c = base
    return c


#: The keys a user owns. Everything else in the config is the machine's, and only
#: an admin may change it. Kept as one list so "what is mine" is answerable in one
#: place rather than inferred from whichever route happened to write it.
#:
#: The line is drawn at cost and blast radius, not at how personal something feels.
#: Anything that spends money or reconfigures the machine — providers and their
#: keys, the image provider, executors, the sandbox, remote access, updates,
#: components, the taint policy — is the machine's. Everything that shapes one
#: person's own working day is theirs, INCLUDING `default_model`: which model you
#: talk to is a preference, while which providers exist and what their keys are is
#: not, and a user picking a different model reaches nothing they could not
#: already reach.
USER_KEYS = ("channels", "telegram", "whatsapp", "mcp_servers", "credentials",
             "desktop", "widgets", "shortcuts", "spaces",
             "agent_name", "soul", "onboarding", "setup_complete",
             "autonomy", "default_model", "max_steps", "workspace",
             "memory", "history", "tools", "steer_queued_messages",
             # whom I trust: added registry publisher keys and the first-install
             # pins of apps I installed. Personal by the USER_KEYS test — trusting
             # a publisher costs nothing machine-wide and reconfigures nothing;
             # it decides only what MY install screen alarms about.
             "registry",
             # whom I share MY agent with: the hosted-share toggle and its minted
             # peer keys. Personal by the same test — a share serves MY skills and
             # flows out of MY store, spends nothing and reconfigures nothing
             # machine-wide. The share route finds a key's owner by searching
             # accounts, the same way a flow webhook finds its trigger's.
             "agent_share")


def machine_view(cfg: dict) -> dict:
    """What an admin's save is allowed to write to the MACHINE file.

    Their own channels and their own theme are theirs; if they went into the
    machine file, every user created afterwards would start life with the first
    admin's Telegram token layered under their config as a default.
    """
    return {k: v for k, v in cfg.items() if k not in USER_KEYS and k != "_uid"}


def save_user_cfg(uid: str, cfg: dict) -> None:
    if not uid:
        cfgmod.save_config(cfg)
        return
    own = {k: cfg[k] for k in USER_KEYS if k in cfg}
    p = cfg_path_for(uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(own, indent=2))
    os.replace(tmp, p)
    os.chmod(p, 0o600)          # it holds their channel tokens and credentials


def machine_changed(machine: dict) -> None:
    """An admin changed something machine-wide — push it into the live views.

    Every user's config is a cached dict that was built by layering their own keys
    over the machine's. Without this, an admin adding a provider key would reach
    nobody else until the next restart, and the bug would read as "the model does
    not work for me".
    """
    for uid, c in _cfgs.items():
        for k, v in machine.items():
            if k not in USER_KEYS:
                c[k] = v


def _forget(uid: str) -> None:
    _stores.pop(uid, None)
    _cfgs.pop(uid, None)
    _services.pop(uid, None)


def reset_caches() -> None:
    """Tests and factory reset: drop every cached Store and config."""
    _stores.clear()
    _cfgs.clear()
    _services.clear()


# ---------------------------------------------------------------------------
# Two descriptors, and they are what make this module small
# ---------------------------------------------------------------------------
#
# Every long-lived service in this OS — the scheduler, the toolbox, the PDP, the
# control plane, the bridges — is built once at startup and handed the machine's
# cfg and store. On a multi-user machine that pair is wrong for every request but
# one. Threading a user through every method would be a hundred signatures and one
# forgotten; so instead the ATTRIBUTE resolves, exactly as `state["store"]` does.
#
# `self.cfg = cfg` in an existing `__init__` keeps working unchanged — it goes
# through `__set__` and stores the machine's copy as the fallback.

class _ScopedCfg:
    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        m = getattr(obj, "_machine_cfg", None)
        return cfg_for(machine=m) if enabled() else m

    def __set__(self, obj, value):
        obj._machine_cfg = value


class _ScopedStore:
    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        return store_for() if enabled() else getattr(obj, "_machine_store", None)

    def __set__(self, obj, value):
        obj._machine_store = value


class Scoped:
    """Mix in to make `.cfg` and `.store` answer for whoever the turn belongs to."""

    cfg = _ScopedCfg()
    store = _ScopedStore()


def resolve(cfg: dict, store):
    """The (cfg, store) pair for whoever is current, given the machine's as a
    fallback. For the background loops, which take theirs as plain arguments and
    so cannot be helped by `Scoped`."""
    uid = current() if enabled() else ""
    if not uid:
        return cfg, store
    return cfg_for(uid, machine=cfg), store_for(uid)


def sweep() -> list[str]:
    """Every user id to visit in a background pass, or [''] for a single-user
    machine. One place, so a loop that forgets somebody forgets them everywhere
    rather than in one subsystem nobody thinks to check."""
    return [u["id"] for u in list_users()] if enabled() else [""]


# ---------------------------------------------------------------------------
# Services that genuinely cannot be shared
# ---------------------------------------------------------------------------
#
# Most services are stateless about WHO and only need the right cfg and store —
# `Scoped` is enough for them. Three are not: a Telegram bridge polls with one bot
# token, a WhatsApp bridge holds one linked device, an MCP manager owns live
# subprocesses. Those are one per person, built on demand.

_services: dict[str, dict] = {}
_factory = None


def set_service_factory(fn) -> None:
    """The server registers how to build a user's bridges. Kept as a callback so
    this module stays free of asyncio and HTTP — `bento job` and the TUI import it
    on a headless Pi."""
    global _factory
    _factory = fn


def services(uid: str | None = None) -> dict:
    uid = current() if uid is None else (uid or "")
    bag = _services.get(uid)
    if bag is None:
        _services[uid] = bag = (_factory(uid) if _factory else {})
    return bag


class PerUser:
    """An attribute that is this user's instance when there are users, and the one
    assigned at startup when there are not."""

    def __init__(self, name: str):
        self.name = name
        self.attr = "_" + name

    def __set_name__(self, owner, attr):
        self.attr = "_" + attr

    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        if enabled():
            got = services().get(self.name)
            if got is not None:
                return got
        return getattr(obj, self.attr, None)

    def __set__(self, obj, value):
        setattr(obj, self.attr, value)


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------

SHAREABLE = ("app", "agent")


def _share_dir(kind: str) -> Path:
    d = shared_root() / (kind + "s")
    d.mkdir(parents=True, exist_ok=True)
    return d


def publish(kind: str, name: str, payload: dict, by: str) -> dict:
    """Put a COPY in the shared library.

    A copy, never a link. A shared app that changes under the people using it is a
    supply-chain problem living in a filesystem — and the person who published it
    would have no idea they had shipped a change.
    """
    if kind not in SHAREABLE:
        raise ValueError(f"only {', '.join(SHAREABLE)} can be shared")
    if not (name or "").strip():
        raise ValueError("it needs a name")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:60] or "shared"
    rec = {"kind": kind, "name": name, "slug": slug, "by": by,
           "published_at": time.time(), "payload": payload}
    (_share_dir(kind) / f"{slug}.json").write_text(json.dumps(rec, indent=2))
    return {k: v for k, v in rec.items() if k != "payload"}


def shared(kind: str = "") -> list[dict]:
    out = []
    for k in ([kind] if kind else list(SHAREABLE)):
        for f in sorted(_share_dir(k).glob("*.json")):
            try:
                rec = json.loads(f.read_text())
            except Exception:
                continue
            out.append({x: rec[x] for x in ("kind", "name", "slug", "by",
                                            "published_at") if x in rec})
    return sorted(out, key=lambda r: -(r.get("published_at") or 0))


def take(kind: str, slug: str) -> dict:
    """The payload, for the caller to install into their own store."""
    f = _share_dir(kind) / f"{slug}.json"
    if not f.exists():
        raise ValueError(f"nothing shared called '{slug}'")
    return json.loads(f.read_text()).get("payload") or {}


def unpublish(kind: str, slug: str, by: str, admin: bool = False) -> dict:
    """Only the person who shared it, or an admin, can take it back down."""
    f = _share_dir(kind) / f"{slug}.json"
    if not f.exists():
        return {"ok": False}
    try:
        rec = json.loads(f.read_text())
    except Exception:
        rec = {}
    if not admin and rec.get("by") and rec["by"] != by:
        raise ValueError("only whoever shared it, or an admin, can remove it")
    f.unlink()
    return {"ok": True}
