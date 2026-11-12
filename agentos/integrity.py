"""The watcher: if this OS's code or a locked file changes, a person hears and the agents stop.

Asked for as "there should be a watcher if the file has been changed by the AI". The honest
constraint decides the shape: the server and any unjailed process run as the same Unix user, so
nothing in this file can stop that user rewriting a file, a manifest or this module. So it is
layers, and each one says what it does not do (docs/security.md has the table):

1. **Memory.** At start the server hashes the code tree and watches it. A process that is not the
   server cannot reach what the server holds in memory, so a change while it runs is always seen.
2. **The record** (`integrity.json`), written by a person (`seal`) or by the update path. It is
   what catches a change made while the server was stopped. Unsigned, a same-user process can
   forge it, and every surface says "unsigned". Signed with a key whose private half is off this
   machine (`trust` + `seal --key`) it cannot be forged, and `accept` needs that key too.
3. **The hold.** A change stops the agents: `policy.PDP` refuses every step and `Agent.run` /
   `executors.forward` refuse every turn, with a sentence. No tool, route or model lifts it. Only
   `bento integrity accept`, typed by a person at a terminal, does.
4. **The lock** (`bento integrity lock`): the code tree owned by root. The server's user cannot
   write its own gate at all. This is the only layer that is a real boundary.

Rules that keep it honest:

- **A `.git` folder exempts nothing.** A checkout holds like any other machine until a person says
  otherwise with `bento integrity dev on`, which is recorded in the record and only warns from then
  on. An agent making a `.git` directory changes nothing here.
- **Re-baselining is one path, the OS's own**: `rebaseline`, called by `updates.apply` and
  `updates.rollback` after they finish, and it adopts nothing git calls dirty. `restart_agentos`
  never reaches it. A restart re-reads the record, and a change is still a change.
- **A signature that fails is worse than none**: it holds, it does not read as "unsigned".

Stdlib only and free of HTTP and asyncio (cryptography is imported when a signature is touched, as
in appregistry), so the terminal verbs work with the server down. Off by default in a process:
`serve()` calls `arm()`. The suite shares a checkout it must not trip on.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import shlex
import stat as statmod
import subprocess
import threading
import time
from pathlib import Path

from . import secevents

FORMAT = "bento-integrity/1"
RECORD = "integrity.json"           # the manifest, per code tree
KEYS = "integrity.keys"             # public keys a person trusts on this machine
HELD = "integrity.held"             # why the agents are stopped, so a restart keeps it
WRITES = "integrity.writes"         # what the OS itself last wrote to each locked home file
UPDATING = "integrity.updating"     # an update is moving the code right now

WATCH_S = 30                        # seconds between looks. A look is one stat per file.
REHASH_S = 24 * 3600                # the whole tree re-read, in case stat was fooled
UPDATE_MAX_S = 900                  # updates.APPLY_TIMEOUT: a marker older than this means nothing

SCOPE_DIRS = ("agentos",)
SCOPE_FILES = ("install.sh", "pyproject.toml")
SKIP_PARTS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"})
SKIP_SUFFIX = (".pyc", ".pyo", ".tmp", ".swp")

# Home files, in the machine's home and each account's. FIXED never change once made, whoever
# asks: replacing one is replacing the identity it stands for. TRACKED change through the OS's
# own save (`noted`), so a change that was not noted came from somewhere else. STRICT is watched
# from nothing as well: a trust list appearing by itself is the attack.
HOME_FIXED = ("session.key", "vault.key", "ledger.key", "pki/ca.key", "pki/ca.crt")
HOME_TRACKED = ("config.json", "users.json")
HOME_STRICT = (KEYS,)
# What in config.json can open a door. The rest is preferences and window state, written by many
# hands, and a watcher that fires on those is one somebody switches off.
CONFIG_VIEW = ("autonomy", "sandbox", "security", "remote", "updates", "mcp_servers", "policies")

ACCEPT_PHRASE = "accept"
SEAL_PHRASE = "seal"

_lock = threading.Lock()
_hold: dict | None = None
_armed = False
_cache: tuple[float, dict | None] = (0.0, None)     # another process's view of the hold file
_on_hold: list = []
WATCHER: "Watcher | None" = None


# ------------------------------------------------------------------------------------- paths

def _home() -> Path:
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME)


def code_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    """None when absent. A file that is there and cannot be read is `{"_broken": True}`, which
    nothing accepts, so damaging a record never reads the same as never having sealed."""
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"_broken": True}
    return got if isinstance(got, dict) else {"_broken": True}


# -------------------------------------------------------------------------------- the tree

def _in_scope(root: Path):
    for name in SCOPE_FILES:
        p = root / name
        if p.is_file():
            yield name, p
    for d in SCOPE_DIRS:
        base = root / d
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(x for x in dirnames if x not in SKIP_PARTS)
            for f in sorted(filenames):
                if f.endswith(SKIP_SUFFIX):
                    continue
                p = Path(dirpath) / f
                yield p.relative_to(root).as_posix(), p


def _stamp(st: os.stat_result) -> tuple:
    # ctime can't be set from userspace, so `touch -r` doesn't hide an edit
    return (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)


def stat_tree(root: Path) -> dict[str, tuple]:
    """Plain strings and scandir, because this is the whole cost of an idle look: scandir's
    entries cost one lstat each, where a Path per file cost five times the look."""
    out = {}
    base = str(root)
    for name in SCOPE_FILES:
        with contextlib.suppress(OSError):
            st = os.lstat(f"{base}/{name}")
            if statmod.S_ISREG(st.st_mode):
                out[name] = _stamp(st)
    stack = list(SCOPE_DIRS)
    while stack:
        rel = stack.pop()
        with contextlib.suppress(OSError), os.scandir(f"{base}/{rel}") as it:
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    if e.name not in SKIP_PARTS:
                        stack.append(f"{rel}/{e.name}")
                elif not e.name.endswith(SKIP_SUFFIX):
                    out[f"{rel}/{e.name}"] = _stamp(e.stat(follow_symlinks=False))
    return out


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: Path | None = None) -> dict[str, str]:
    """{relative path: sha256}. Measured: 348 files, 13 MB, 11 ms here; a Pi 3 with no SHA
    instructions and an SD card is about a second. Read once at start, on a thread."""
    root = Path(root or code_root())
    out = {}
    for rel, p in _in_scope(root):
        with contextlib.suppress(OSError):
            out[rel] = sha_file(p)
    return out


def digest_of(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(f"{rel}\0{files[rel]}\n".encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def diff(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """Paths that differ, security modules first: those are what a person should read first."""
    from . import protected
    gone = [k for k in set(old) | set(new) if old.get(k) != new.get(k)]
    return sorted(gone, key=lambda k: (not protected.is_security_module(k), k))


# ------------------------------------------------------------------------------------ signing

def key_id_of(pub_b64: str) -> str:
    return "bento-" + hashlib.sha256(base64.b64decode(pub_b64)).hexdigest()[:8]


def keygen(path) -> tuple[Path, str, str]:
    """Mint a keypair, private half at `path`, 0600. Never ran for anybody but the person
    asking: nothing in this repository holds a private key, and the public list ships empty."""
    from . import appregistry
    p, _, pub = appregistry.keygen(Path(path))
    return p, key_id_of(pub), pub


def sign_bytes(key_path, msg: bytes) -> tuple[str, str]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(Path(key_path).read_bytes()))
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return key_id_of(base64.b64encode(pub).decode()), base64.b64encode(priv.sign(msg)).decode()


def verify_bytes(pub_b64: str, msg: bytes, sig_b64: str) -> bool:
    """False on anything it cannot check, a missing library included: fail closed."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64)).verify(
            base64.b64decode(sig_b64), msg)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def personal_keys() -> dict[str, str]:
    """Keys a person added here with `bento integrity trust`. Once there is one, every record
    must be signed: that is what the person asked for by adding it."""
    d = _read_json(_home() / KEYS) or {}
    keys = d.get("keys") if isinstance(d.get("keys"), dict) else {}
    return {str(k): str(v) for k, v in keys.items()}


def release_keys() -> dict[str, str]:
    """The keys an update is checked against: pinned in source, plus a person's own."""
    from . import updates
    return {**personal_keys(), **dict(getattr(updates, "SIGNING_KEYS", {}) or {})}


def _canonical(entry: dict) -> bytes:
    clean = {k: v for k, v in entry.items() if k != "sig"}
    return json.dumps(clean, sort_keys=True, separators=(",", ":")).encode()


def release_message(commit: str, digest: str) -> bytes:
    return f"bento-release-1\n{commit}\n{digest}\n".encode()


def signature_state(entry: dict) -> str:
    """signed (a person's key), release (a verified update), none, or bad. Bad means somebody
    claimed a signature that does not check, or a digest that does not match its files."""
    if not isinstance(entry.get("files"), dict) or entry.get("digest") != digest_of(entry["files"]):
        return "bad"
    sig = entry.get("sig")
    if sig:
        pub = personal_keys().get(str((sig or {}).get("key_id") if isinstance(sig, dict) else ""))
        if not pub or not verify_bytes(pub, _canonical(entry), str(sig.get("sig") or "")):
            return "bad"
        return "signed"
    up = entry.get("update") if isinstance(entry.get("update"), dict) else {}
    if up.get("state") == "verified":
        pub = release_keys().get(str(up.get("key_id") or ""))
        if not pub or up.get("digest") != entry.get("digest") or not verify_bytes(
                pub, release_message(str(up.get("commit") or ""), str(up.get("digest") or "")),
                str(up.get("sig") or "")):
            return "bad"
        return "release"
    return "none"


# ---------------------------------------------------------------------------------- the record

def load_records() -> dict:
    d = _read_json(_home() / RECORD)
    if d is None:
        return {}
    return d


def record_for(root: Path | None = None) -> dict | None:
    """This tree's entry. A record for another copy says nothing about this one: on the owner's
    machine the `bento` on the PATH and the service run from two checkouts."""
    d = load_records()
    if d.get("_broken"):
        return {"_broken": True}
    trees = d.get("trees") if isinstance(d.get("trees"), dict) else {}
    got = trees.get(str(Path(root or code_root()).resolve()))
    return got if isinstance(got, dict) else None


def _save_entry(root: Path, entry: dict) -> None:
    with _map_lock():
        d = load_records()
        if d.get("_broken"):
            d = {}
        d["format"] = FORMAT
        d.setdefault("trees", {})[str(Path(root).resolve())] = entry
        _atomic(_home() / RECORD, json.dumps(d, indent=1, sort_keys=True))


def _entry(root: Path, files: dict, by: str, **extra) -> dict:
    return {"format": FORMAT, "root": str(Path(root).resolve()), "files": files,
            "digest": digest_of(files), "at": time.time(), "by": by, **extra}


def judge(entry: dict | None, files: dict) -> dict:
    """What the record says about these files, in one word.

    none: nothing recorded. match. changed: files differ. forged: the record can't be believed.
    unsigned: a person added a key and this record isn't signed by it."""
    if entry is None:
        return {"state": "none", "signed": "none", "changed": []}
    if entry.get("_broken"):
        return {"state": "forged", "signed": "bad", "changed": [],
                "why": "the integrity record can't be read"}
    signed = signature_state(entry)
    if signed == "bad":
        return {"state": "forged", "signed": "bad", "changed": [],
                "why": "the integrity record's signature does not check"}
    if signed == "none" and personal_keys():
        return {"state": "unsigned", "signed": "none", "changed": [],
                "why": "the integrity record isn't signed by the key you trust"}
    changed = diff(entry.get("files") or {}, files)
    return {"state": "changed" if changed else "match", "signed": signed, "changed": changed}


# ----------------------------------------------------------------------------- locked home files

def _map_lock():
    """Across processes: the server and a `bento` verb both note what they write."""
    class _L:
        def __enter__(self):
            self.f = None
            _lock_thread.acquire()
            with contextlib.suppress(Exception):
                import fcntl
                _home().mkdir(parents=True, exist_ok=True)
                self.f = open(_home() / "integrity.lock", "a")
                fcntl.flock(self.f, fcntl.LOCK_EX)
            return self

        def __exit__(self, *a):
            if self.f:
                with contextlib.suppress(Exception):
                    self.f.close()
            _lock_thread.release()
    return _L()


_lock_thread = threading.RLock()


def _view_hash(path: Path) -> str | None:
    """The hash that stands for this file, or None when it is not there."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if path.name == "config.json":
        try:
            d = json.loads(raw)
            raw = json.dumps({k: d.get(k) for k in CONFIG_VIEW}, sort_keys=True).encode()
        except (ValueError, AttributeError):
            pass
    return hashlib.sha256(raw).hexdigest()


def home_paths() -> list[tuple[Path, str]]:
    """Every locked file that could exist, with its kind."""
    home = _home()
    homes = [home]
    with contextlib.suppress(OSError):
        homes += [p for p in sorted((home / "users").iterdir()) if p.is_dir()]
    out: list[tuple[Path, str]] = []
    for h in homes:
        out += [(h / n, "fixed") for n in HOME_FIXED]
        out += [(h / n, "tracked") for n in HOME_TRACKED]
    out += [(home / n, "strict") for n in HOME_STRICT]
    return out


def _load_writes() -> dict:
    d = _read_json(_home() / WRITES) or {}
    return d.get("files") if isinstance(d.get("files"), dict) else {}


def noted(path) -> None:
    """The OS itself just wrote this locked file. Called by the writers (config.save_config,
    users' registry). Never raises: a save must not fail because a note could not be kept, and
    the cost of a missed note is a false alert, which says what happened."""
    try:
        path = Path(path)
        h = _view_hash(path)
        key = str(path)
        with _map_lock():
            files = _load_writes()
            if files.get(key) == h:
                return
            if h is None:
                files.pop(key, None)
            else:
                files[key] = h
            _atomic(_home() / WRITES, json.dumps({"files": files}, indent=0))
    except Exception:  # noqa: BLE001
        return


def rebaseline_home() -> None:
    """Every locked file, as it is now. For the OS's own wholesale moves (a restore, a factory
    reset) and for a person's accept. Never for anything an agent can start."""
    with contextlib.suppress(Exception), _map_lock():
        files = {}
        for p, _ in home_paths():
            h = _view_hash(p)
            if h is not None:
                files[str(p)] = h
        _atomic(_home() / WRITES, json.dumps({"files": files}, indent=0))


_home_stamps: tuple | None = None


def _stamp_home() -> tuple:
    out = []
    for p, _ in home_paths():
        try:
            out.append(_stamp(p.stat()))
        except OSError:
            out.append(None)
    try:
        out.append(_stamp((_home() / WRITES).stat()))
    except OSError:
        out.append(None)
    return tuple(out)


def check_home() -> list[str]:
    """Locked files that are not what the OS last wrote. A file it never saw is taken as it is,
    so the first start after this code arrives doesn't accuse anybody, except a strict one.
    Nothing is read when no stat moved: this runs on every look."""
    global _home_stamps
    stamps = _stamp_home()
    if stamps == _home_stamps:
        return []
    files = _load_writes()
    known = bool(files)
    changed, adopt = [], {}
    for p, kind in home_paths():
        key = str(p)
        h = _view_hash(p)
        was = files.get(key)
        if was == h:
            continue
        if was is None:
            if kind == "strict" and known:
                changed.append(_rel_home(p))
            else:
                adopt[key] = h
            continue
        changed.append(_rel_home(p))
    if adopt:
        with contextlib.suppress(Exception), _map_lock():
            cur = _load_writes()
            cur.update(adopt)
            _atomic(_home() / WRITES, json.dumps({"files": cur}, indent=0))
        stamps = _stamp_home()
    if not changed:
        _home_stamps = stamps
    return changed


def _rel_home(p: Path) -> str:
    try:
        return "~/" + p.relative_to(_home()).as_posix()
    except ValueError:
        return str(p)


# ------------------------------------------------------------------------------------ the hold

def on_hold(listener) -> None:
    if listener not in _on_hold:
        _on_hold.append(listener)


def arm() -> None:
    """serve() says this process is the server. The hold's truth is then in memory."""
    global _armed
    _armed = True


def armed() -> bool:
    return _armed


def held() -> dict | None:
    """Are the agents stopped? Read on every gate decision: a dict lookup in the server, and a
    stat a second elsewhere, because a terminal verb has no watcher of its own."""
    global _cache
    if _hold is not None:
        return _hold
    if _armed:
        return None
    now = time.monotonic()
    if now - _cache[0] < 1.0:
        return _cache[1]
    got = _read_json(_home() / HELD)
    _cache = (now, got if got is None or got.get("reason") else {"reason": "held", "files": []})
    return _cache[1]


REFUSAL = ("This OS's security files changed and agents are stopped. Nothing can run until a "
           "person checks it and clears it at this machine's terminal with bento integrity accept.")


def refusal() -> str:
    """What a turn or a step gets. The same words whatever changed: a file's name is whatever
    somebody called it, and this sentence goes to a model."""
    return REFUSAL if held() else ""


def hold(reason: str, files: list[str] | None = None) -> dict:
    """Stop the agents. Idempotent. The file is what survives a restart."""
    global _hold, _cache
    with _lock:
        fresh = _hold is None
        kept = list(_hold.get("files") or []) if _hold else []
        names = kept + [secevents.plain(f, 200) for f in (files or []) if f not in kept]
        _hold = {"reason": secevents.plain(reason, 200), "files": names[:50],
                 "at": (_hold or {}).get("at") or time.time()}
        with contextlib.suppress(OSError):
            _atomic(_home() / HELD, json.dumps(_hold))
        _cache = (0.0, None)
        cur = dict(_hold)
    if fresh:
        for fn in list(_on_hold):
            with contextlib.suppress(Exception):
                fn(cur)
    return cur


def _release() -> None:
    global _hold, _cache
    with _lock:
        _hold = None
        _cache = (0.0, None)
        with contextlib.suppress(OSError):
            (_home() / HELD).unlink()


def forget_for_tests() -> None:
    global _hold, _armed, _cache, WATCHER, _home_stamps
    _hold, _armed, _cache, WATCHER, _home_stamps = None, False, (0.0, None), None, None
    _on_hold.clear()
    _seen_heads.clear()
    _broken_said.clear()


# --------------------------------------------------------------------------------- the watcher

def _updating_now() -> bool:
    """An update is moving the code (`updating()`). Bounded, and only while its process lives:
    a marker left by a crash, or written to buy time, stops counting."""
    d = _read_json(_home() / UPDATING)
    if not d or d.get("_broken"):
        return False
    if time.time() - float(d.get("at") or 0) > UPDATE_MAX_S:
        return False
    try:
        os.kill(int(d.get("pid") or 0), 0)
    except (OSError, ValueError):
        return False
    return int(d.get("pid") or 0) > 0


class updating:
    """`with integrity.updating():` around the code moving. The watcher waits, then compares
    against what `rebaseline` wrote, so a change made during the window that the update did not
    make is still a change."""
    def __enter__(self):
        with contextlib.suppress(OSError):
            _atomic(_home() / UPDATING, json.dumps({"pid": os.getpid(), "at": time.time()}))
        return self

    def __exit__(self, *a):
        with contextlib.suppress(OSError):
            (_home() / UPDATING).unlink()


class Watcher:
    """One per server. Started on a thread, ticked on a thread, never on the loop.

    Measured idle: see docs/security.md. A look is a stat per file and reads nothing."""

    def __init__(self, root: Path | None = None, passive=None):
        self.root = Path(root or code_root()).resolve()
        self.passive = passive or (lambda: False)
        self.files: dict[str, str] = {}
        self.stats: dict[str, tuple] = {}
        self.record_stamp: tuple | None = None
        self.had_record = False
        self.started = 0.0
        self.last_tick = 0.0
        self.last_rehash = 0.0
        self.dev_changes: list[str] = []

    # ---- start
    def start(self) -> dict:
        """The baseline, then the question for a change made while nobody was watching."""
        global _hold
        self.stats = stat_tree(self.root)
        self.files = hash_tree(self.root)
        self.started = self.last_rehash = time.time()
        prior = _read_json(_home() / HELD)
        if prior and not prior.get("_broken") and prior.get("reason"):
            with _lock:
                _hold = {"reason": str(prior["reason"])[:200], "files": list(prior.get("files") or [])[:50],
                         "at": float(prior.get("at") or time.time())}
        entry = record_for(self.root)
        self.had_record = entry is not None
        self.record_stamp = self._record_stamp()
        verdict = judge(entry, self.files)
        self._act_on(verdict, entry, "while the server was stopped")
        self._home_check()
        self._try_release()
        return verdict

    def _record_stamp(self) -> tuple | None:
        try:
            return _stamp((_home() / RECORD).stat())
        except OSError:
            return None

    # ---- a look
    def tick(self) -> list[str]:
        """Returns the paths that changed and were not adopted. Never hashes what didn't move."""
        self.last_tick = time.time()
        if _updating_now():
            return []
        now_stats = stat_tree(self.root)
        moved = [k for k in set(now_stats) | set(self.stats) if now_stats.get(k) != self.stats.get(k)]
        rehash = self.last_tick - self.last_rehash > REHASH_S
        if moved or rehash:
            self._rescan(now_stats, moved, rehash)
        stamp = self._record_stamp()
        if stamp != self.record_stamp:
            self.record_stamp = stamp
            self._record_moved()
        self._home_check()
        self._try_release()
        return list(self.dev_changes)

    def _rescan(self, now_stats: dict, moved: list[str], rehash: bool) -> None:
        new = dict(self.files)
        if rehash:
            new = hash_tree(self.root)
            self.last_rehash = self.last_tick
        else:
            for rel in moved:
                p = self.root / rel
                if rel not in now_stats:
                    new.pop(rel, None)
                else:
                    with contextlib.suppress(OSError):
                        new[rel] = sha_file(p)
        self.stats = now_stats
        changed = diff(self.files, new)
        if not changed:
            self.files = new
            return
        entry = record_for(self.root)
        verdict = judge(entry, new)
        # The update path wrote the record first, or the same process did: the code is what was
        # recorded, by the one path allowed to record it.
        if entry and verdict["state"] == "match" and entry.get("by") in ("update", "rollback", "seal", "accept") \
                and float(entry.get("at") or 0) >= self.started:
            self.files = new
            return
        if entry and entry.get("dev") and verdict["state"] != "forged":
            self._dev(changed)
            self.files = new
            return
        self._trip(changed, "changed while the server was running")
        self.files = new

    def _record_moved(self) -> None:
        entry = record_for(self.root)
        if entry is None:
            if self.had_record:
                self.had_record = False
                self._trip(["integrity.json"], "the integrity record was removed")
            return
        self.had_record = True
        verdict = judge(entry, self.files)
        if verdict["state"] in ("forged", "unsigned"):
            self._trip(["integrity.json"], verdict.get("why") or "the integrity record can't be believed")

    def _home_check(self) -> None:
        changed = check_home()
        if not changed:
            return
        if self.passive():
            # a standby's home is written by the copies it receives
            rebaseline_home()
            return
        entry = record_for(self.root)
        if entry and entry.get("dev"):
            self._dev(changed)
            for p in changed:
                self._note_rel(p)
            return
        self._trip(changed, "a locked file changed outside this OS")
        for p in changed:
            self._note_rel(p)      # one alert per change: the hold stays until a person clears it

    def _note_rel(self, rel: str) -> None:
        if rel.startswith("~/"):
            noted(_home() / rel[2:])

    def _act_on(self, verdict: dict, entry: dict | None, when: str) -> None:
        state = verdict["state"]
        if state in ("none", "match"):
            return
        if state in ("forged", "unsigned"):
            self._trip(["integrity.json"], verdict.get("why") or state)
        elif entry and entry.get("dev"):
            self._dev(verdict["changed"])
        else:
            self._trip(verdict["changed"], when)

    def _dev(self, changed: list[str]) -> None:
        """A person said this checkout is theirs: a warning and no hold."""
        for rel in changed:
            if rel not in self.dev_changes:
                self.dev_changes.append(secevents.plain(rel, 200))
        del self.dev_changes[:-50]
        secevents.flag("integrity.dev", ", ".join(changed[:5]))

    def _trip(self, changed: list[str], reason: str) -> None:
        shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
        secevents.flag("integrity.changed", f"{shown}: {reason}")
        hold(reason, changed)

    def _try_release(self) -> None:
        """Only a person's accept or seal, newer than the hold, for what is on disk right now."""
        if _hold is None:
            return
        entry = record_for(self.root)
        if not entry or entry.get("by") not in ("accept", "seal"):
            return
        if float(entry.get("at") or 0) < float(_hold.get("at") or 0):
            return
        files = hash_tree(self.root)
        if judge(entry, files)["state"] != "match" or check_home():
            return
        self.files, self.stats = files, stat_tree(self.root)
        _release()


def start_watching(root: Path | None = None, passive=None) -> Watcher:
    global WATCHER
    w = Watcher(root, passive)
    w.start()
    WATCHER = w
    return w


# --------------------------------------------------------------- what the OS's own paths call

def _git(root: Path, *args: str, timeout: int = 60) -> tuple[bool, str]:
    # safe.directory: on a locked tree the checkout belongs to root and git refuses it otherwise
    try:
        r = subprocess.run(["git", "-c", f"safe.directory={root}", *args], cwd=str(root),
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout if r.returncode == 0 else r.stderr)


def dirty_in_scope(root: Path) -> list[str]:
    """What git says differs from the commit, inside the watched scope. A path git can't vouch for
    is not adopted by an update."""
    ok, out = _git(root, "status", "--porcelain", "--no-renames", "--", *SCOPE_DIRS, *SCOPE_FILES)
    if not ok:
        return ["(git could not say)"]
    return [ln[3:].strip().strip('"') for ln in out.splitlines() if len(ln) > 3]


def rebaseline(root: Path | None = None, by: str = "update", update: dict | None = None) -> dict:
    """The one way code changes without a hold: updates.apply and updates.rollback, when they
    finish. Dirty files keep their old hash, so an edit made during the update is still a change.
    A personal signature can't survive this (the key is off the machine), so a machine with a
    personal key holds after an unsigned update until a person signs it, as they asked for."""
    root = Path(root or code_root()).resolve()
    files = hash_tree(root)
    old = record_for(root) or {}
    prev = old.get("files") if isinstance(old.get("files"), dict) else {}
    dirty = dirty_in_scope(root)
    for rel in dirty:
        if rel in prev:
            files[rel] = prev[rel]
        else:
            files.pop(rel, None)
    extra = {"update": update} if update else {}
    if old.get("dev"):
        extra["dev"] = True
    entry = _entry(root, files, by, **extra)
    if dirty:
        entry["dirty"] = [secevents.plain(x, 200) for x in dirty[:50]]
    _save_entry(root, entry)
    return entry


TAG_PREFIX = "bento-"
# Asked for by name: `git fetch origin master` carries no tags with it, and only this namespace
# comes in, so a repository full of tags can't fill a Pi. Forced, because a tag is only a place a
# signature sits: a moved tag proves nothing, whatever it says is checked against the commit.
TAG_REFSPEC = f"+refs/tags/{TAG_PREFIX}*:refs/tags/{TAG_PREFIX}*"


def release_state(root: Path, commit: str, keys: dict[str, str] | None = None) -> dict:
    """Is this commit a signed release? {state: verified|unsigned|bad-signature, ...}.

    A signature is one line in an annotated tag's message, so it needs git and nothing else on
    the machine: `bento-signature: <key id> <signature> <tree digest>`. It signs the commit and
    the sha256 digest of the code at that commit, so the check doesn't rest on git's SHA-1."""
    keys = release_keys() if keys is None else keys
    ok, out = _git(Path(root), "tag", "--points-at", commit, "--list", f"{TAG_PREFIX}*")
    bad = ""
    for tag in (out.split() if ok else []):
        got, body = _git(Path(root), "cat-file", "tag", tag)
        if not got or f"object {commit}" not in body.splitlines()[:1]:
            continue
        for line in body.splitlines():
            if not line.startswith("bento-signature: "):
                continue
            parts = line.split()
            if len(parts) != 4:
                bad = bad or tag
                continue
            _, key_id, sig, digest = parts
            pub = keys.get(key_id)
            if not pub:
                continue                    # somebody else's key says nothing here
            if verify_bytes(pub, release_message(commit, digest), sig):
                return {"state": "verified", "key_id": key_id, "tag": tag, "sig": sig,
                        "digest": digest, "commit": commit}
            bad = bad or tag
    if bad:
        return {"state": "bad-signature", "tag": bad, "commit": commit}
    return {"state": "unsigned", "commit": commit, "pinned": bool(keys)}


def sign_release(key_path, root: Path | None = None, tag: str = "") -> dict:
    """`bento integrity sign-release`: on the owner's machine, at a clean release commit."""
    root = Path(root or code_root()).resolve()
    if dirty_in_scope(root):
        return {"ok": False, "error": "The checkout has uncommitted changes. Commit them first, "
                                      "because a signature vouches for one exact commit."}
    ok, commit = _git(root, "rev-parse", "HEAD")
    if not ok:
        return {"ok": False, "error": "This folder is not a git checkout."}
    commit = commit.strip()
    digest = digest_of(hash_tree(root))
    key_id, sig = sign_bytes(key_path, release_message(commit, digest))
    tag = tag or (root / "agentos" / "VERSION").read_text().strip()
    tag = tag if tag.startswith(TAG_PREFIX) else TAG_PREFIX + tag
    msg = f"Bento release {tag}\n\nbento-signature: {key_id} {sig} {digest}\n"
    ok, out = _git(root, "tag", "-a", tag, "-m", msg, commit)
    if not ok:
        return {"ok": False, "error": f"git could not make the tag: {out.strip()[:200]}"}
    return {"ok": True, "tag": tag, "commit": commit, "key_id": key_id, "digest": digest}


# --------------------------------------------------------------------- what only a person does

def _ancestors() -> list[list[str]]:
    """Arguments of this process's parents, nearest first. Split as the kernel holds them: a
    shell whose one `-c` argument merely mentions `agentos serve` isn't the server."""
    out, pid = [], os.getppid()
    for _ in range(64):
        if pid <= 1:
            break
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                out.append(f.read().decode("utf-8", "replace").split("\0"))
            with open(f"/proc/{pid}/stat", "rb") as f:
                pid = int(f.read().rsplit(b")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def person_problem() -> str:
    """Why this process can't be taken for a person typing, or ''. It stops every agent tool
    that runs a program with pipes, and every child of the server. A same-user process that
    detaches and fakes a terminal gets past it: the limit of this door, and why a signing key
    and `bento integrity lock` exist."""
    import sys
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return "This needs a person at a terminal, and this isn't a terminal."
    except (ValueError, OSError):
        return "This needs a person at a terminal, and this isn't a terminal."
    for argv in _ancestors():
        if "serve" in argv and any(w == "agentos" or w.endswith(("/bento", "/agentos")) or w == "bento"
                                   for w in argv):
            return ("This terminal was started by Bento, so an agent could be typing here. "
                    "Use a terminal outside it: SSH or the machine's own console.")
    return ""


def _sign_entry(entry: dict, key_path) -> dict:
    key_id, sig = sign_bytes(key_path, _canonical(entry))
    if key_id not in personal_keys():
        raise ValueError(f"{key_id} isn't a key you trust here. Add it with bento integrity trust.")
    entry["sig"] = {"key_id": key_id, "sig": sig}
    return entry


def needs_key() -> bool:
    return bool(personal_keys())


def seal(root: Path | None = None, key_path=None, by: str = "seal", dev: bool | None = None) -> dict:
    """Write the record for the code as it is now, and take the locked files as they are.
    A person's act: `bento integrity seal` and `accept` check `person_problem` first, and on a
    machine with a key this can't be done without it. Clears the hold."""
    root = Path(root or code_root()).resolve()
    if needs_key() and not key_path:
        raise ValueError("You added a signing key, so this needs it. Pass --key with its path.")
    old = record_for(root) or {}
    extra = {}
    keep_dev = old.get("dev") if dev is None else dev
    if keep_dev:
        extra["dev"] = True
    entry = _entry(root, hash_tree(root), by, **extra)
    if key_path:
        entry = _sign_entry(entry, key_path)
    _save_entry(root, entry)
    rebaseline_home()
    with contextlib.suppress(OSError):
        (_home() / HELD).unlink()
    if not _armed:
        _release()
    return entry


def trust(pub_b64: str) -> str:
    """A person adds a key. Everything sealed from now on must be signed by one of these."""
    key_id = key_id_of(pub_b64)
    if len(base64.b64decode(pub_b64)) != 32:
        raise ValueError("That isn't an Ed25519 public key.")
    with _map_lock():
        d = _read_json(_home() / KEYS) or {}
        keys = d.get("keys") if isinstance(d.get("keys"), dict) else {}
        keys[key_id] = pub_b64
        _atomic(_home() / KEYS, json.dumps({"keys": keys}, indent=1))
    noted(_home() / KEYS)
    return key_id


# ------------------------------------------------------------------------------------ the lock

def is_locked(root: Path | None = None) -> bool:
    """Measured: can this user write the gate? Only a real answer counts, so root never reads
    as locked and neither does a checkout with a surprising owner it can still write."""
    root = Path(root or code_root())
    p = root / "agentos" / "policy.py"
    try:
        return p.stat().st_uid != os.getuid() and not os.access(p, os.W_OK) \
            and not os.access(root / "agentos", os.W_OK)
    except OSError:
        return False


def open_parents(root: Path | None = None) -> list[str]:
    """Folders above the code this user can still write. Whoever can write a folder can rename
    what's in it and put another program in its place."""
    root = Path(root or code_root()).resolve()
    return [str(p) for p in root.parents if os.access(p, os.W_OK)]


def lock_script(root: Path | None = None) -> str:
    """What runs as root. Shown first, then run, as harden.plan does. Bytecode is compiled here,
    because the server can't write it afterwards. chattr stops a same-folder rename where the
    filesystem has it, and its failure is reported, not hidden."""
    root = Path(root or code_root()).resolve()
    q = shlex.quote(str(root))
    py = root / ".venv" / "bin" / "python"
    python = shlex.quote(str(py if py.exists() else "python3"))
    return (f"{python} -m compileall -q {q}/agentos; "
            f"chown -R root:root {q} && chmod -R u+rwX,go+rX,go-w {q} && "
            f"(chattr +i {q} 2>/dev/null || echo 'chattr is not available here')")


def unlock_script(root: Path | None = None) -> str:
    root = Path(root or code_root()).resolve()
    q = shlex.quote(str(root))
    return (f"chattr -i {q} 2>/dev/null; chown -R {os.getuid()}:{os.getgid()} {q}")


def run_as_root(script: str, why: str, runner=None) -> tuple[bool, str]:
    """The privilege ladder: passwordless sudo, a prompt, a polkit prompt, then the exact command
    handed back. All of it is session._run_root."""
    if runner is None:
        from . import session
        runner = session._run_root
    return runner(["sh", "-c", script], why)


def hand_back(script: str) -> str:
    return f"sudo sh -c {shlex.quote(script)}"


# ----------------------------------------------------------------------------------- the ledgers

_seen_heads: dict[str, tuple[int, str]] = {}
# The break each ledger was last flagged for. A break stays broken, and the check runs every few
# minutes, so flagging it each time sent the same Telegram alert every 20 minutes all night. One
# break is one alert: it is flagged again only when it changes (another row, another reason), or
# after it verified clean and broke again. The card and `bento integrity status` still show it on
# every check. A restart forgets this and says it once more.
_broken_said: dict[str, tuple[str, int]] = {}


def _databases() -> list[Path]:
    home = _home()
    out = [home / "agentos.db"]
    with contextlib.suppress(OSError):
        out += [p / "agentos.db" for p in sorted((home / "users").iterdir()) if p.is_dir()]
    return [p for p in out if p.exists()]


def verify_ledgers(full: bool = False) -> list[dict]:
    """Every home's ledger. `full` walks every row (at start and once a day); otherwise only rows
    newer than the last walk, plus the one it stopped on, so a timer costs what the new rows cost.
    A break is one flag per database. A head that moved backwards is a break too."""
    import sqlite3

    from . import memory
    out = []
    for db_path in _databases():
        key = str(db_path)
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            continue
        try:
            con.row_factory = sqlite3.Row
            after = None if full else _seen_heads.get(key)
            v = memory.verify_chain(con, db_path, after=after)
        except sqlite3.Error as e:
            v = {"ok": True, "checked": 0, "skipped": str(e)[:200]}  # busy or locked: look next time
        finally:
            con.close()
        v["db"] = key
        if v.get("ok"):
            if v.get("head_seq") or key not in _seen_heads:
                _seen_heads[key] = (int(v.get("head_seq") or 0), str(v.get("head_hash") or ""))
            if not v.get("skipped"):
                _broken_said.pop(key, None)
        else:
            _seen_heads.pop(key, None)
            who = db_path.parent.name if db_path.parent != _home() else "machine"
            brk = (str(v.get("reason") or ""), int(v.get("at_seq") or 0))
            if _broken_said.get(key) != brk:
                _broken_said[key] = brk
                secevents.flag("ledger.broken", f"{who}: {v.get('reason')} at row {v.get('at_seq')}",
                               source=who)
        out.append(v)
    return out


# ------------------------------------------------------------------------------------- the status

def status(root: Path | None = None, ledgers: list[dict] | None = None) -> dict:
    """One answer for the card, `bento integrity status`, `bento security` and `bento doctor`."""
    root = Path(root or code_root()).resolve()
    w = WATCHER if WATCHER and WATCHER.root == root else None
    files = dict(w.files) if w else hash_tree(root)
    entry = record_for(root)
    verdict = judge(entry, files)
    hold_now = held()
    signed = verdict.get("signed", "none")
    sealed = "none" if entry is None else ("bad" if verdict["state"] == "forged" else
                                           ("signed" if signed in ("signed", "release") else "unsigned"))
    locked = is_locked(root)
    from . import updates
    out = {
        "root": str(root), "watching": bool(w), "files": len(files),
        "last_look": w.last_tick if w else 0, "held": hold_now,
        "sealed": sealed, "signed": signed, "by": (entry or {}).get("by", ""),
        "at": (entry or {}).get("at", 0), "changed": verdict["changed"][:20],
        "state": verdict["state"], "dev": bool((entry or {}).get("dev")),
        "dev_changes": list(w.dev_changes) if w else [], "locked": locked,
        "open_parents": open_parents(root)[:3] if locked else [],
        "personal_keys": len(personal_keys()),
        "release_keys": len(dict(getattr(updates, "SIGNING_KEYS", {}) or {})),
        "update": (entry or {}).get("update") or {},
    }
    if ledgers is not None:
        out["ledgers"] = [{"ok": bool(v.get("ok")), "checked": v.get("checked", 0),
                           "reason": v.get("reason", ""), "at_seq": v.get("at_seq", 0)} for v in ledgers]
    out["line"] = line(out)
    return out


def line(s: dict) -> str:
    """The one sentence. Nothing wrong reads as one quiet line."""
    if s.get("held"):
        names = s["held"].get("files") or []
        what = ", ".join(names[:3]) or "a security file"
        return (f"Agents are stopped because {what} changed. If that was you, run "
                "bento integrity accept at this machine's terminal.")
    if s.get("sealed") == "bad":
        return "The integrity record doesn't check out. Run bento integrity seal at this machine's terminal."
    how = {"signed": "sealed and signed by your key", "release": "a signed release",
           "none": "not sealed yet"}.get(s.get("signed"), "not sealed yet")
    if s.get("sealed") == "unsigned":
        how = "sealed, unsigned"
    head = f"Watching {s.get('files', 0)} files" if s.get("watching") else f"{s.get('files', 0)} files"
    bits = [f"{head}, {how}"]
    if s.get("dev"):
        bits.append("development checkout, changes only warn")
    if s.get("locked"):
        bits.append("locked by root")
    return "; ".join(bits) + "."

