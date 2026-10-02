"""Backup and restore: the whole machine in one file you can carry.

Asked for as "what is missing from a portability point of view", and the answer was
that nothing could move a machine. Snapshots copied three files of the machine's own
home into a folder on the same disk: every signed-in account, the workspace, the
vault, the linked-team certificates and the WhatsApp session were left behind, and
the backups died with the disk they described.

A backup here is ONE file (`*.bento`) holding everything that makes this machine
yours:

- every home: the machine's and each account's (`users/<id>/…`), with every SQLite
  database copied through SQLite's own backup API, so a server that is running while
  it is taken still yields a consistent copy;
- the workspace folder the config points at, when it lives outside the home
  (`--no-workspace` leaves it out);
- the vault KEYS. A vault whose key is in this machine's keyring would arrive locked
  on any other machine, so the key travels inside the encrypted file and restore puts
  it in the new keyring, or in a 0600 key file when the new machine has none, and
  says which.

Four rules keep it safe to hand somebody, and to restore from:

- **Always encrypted, with a passphrase the person chooses.** It carries every
  account's memory, mail sign-ins and vault keys; an unencrypted mode would be a
  file that must never be lost, which is not a backup. AES-256-GCM in 1 MiB records
  under a scrypt key: a Raspberry Pi can make and read one without holding it in
  memory, and every record is bound to its position and to whether it is the LAST
  one, so a file cut short, reordered or edited is refused rather than restored in
  part. A wrong passphrase fails on the first record, before anything is written.
- **Restore checks everything before it touches anything.** The whole file is
  decrypted into a staging folder first; only when the last record has been
  verified is the current home moved aside (`.before-restore-<time>`, never
  deleted) and the staged one moved in.
- **Nothing in the file can land outside the home.** Every member name is checked:
  no absolute paths, no `..`, no links, only regular files and folders.
- **Folders follow the machine.** Paths recorded under the old home or the old user
  folder (`/home/ada/…` → `/Users/ada/…`) are rewritten in every config and in every
  agent's folder rules, because a hard-coded path that no longer exists fails
  silently.

Kept free of HTTP and asyncio, like jobs.py and brief.py: `bento backup` and `bento
restore` work with the server stopped, which is exactly when a restore must run.
The desktop stages a restore and the server applies it on its next start
(`apply_pending`), because swapping a home under a running server would leave it
answering from a database that is no longer there.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import io
import json
import os
import platform
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

FORMAT = "bento-backup/1"
MAGIC = b"BENTOBK1\n"
SUFFIX = ".bento"
CHUNK = 1 << 20
SCRYPT = {"n": 1 << 15, "r": 8, "p": 1}      # ~32 MiB and well under a second on a Pi 4
MIN_PASSPHRASE = 8
MAX_HEADER = 4096

#: Regenerated, cached or diagnostic: nothing a person would miss, and some of it large
#: (the MCP catalogue is 12 MB, the speech cache is capped at hundreds of files).
SKIP_TOP = {"snapshots", "speech-cache", "mcp_index.json", "logs", "boot.html",
            "layer-shell-failed", "git-askpass.sh", "agentos-autologin.conf", "appwindow"}
SKIP_NAMES = {"__pycache__", "node_modules", ".DS_Store"}
SKIP_SUFFIX = (".db-wal", ".db-shm", ".db-journal", ".pyc", ".tmp", ".part")
#: This module's own working names inside the home, never backed up and never moved.
PRIVATE = (".restoring-", ".before-restore-", ".restore-ready", ".backup-out-",
           ".restore-upload-", ".backup-tmp",
           # the cloud standby's pairing, copies and state (standby.py): this machine's own
           ".standby")
READY = ".restore-ready"
LAST = "last-restore.json"


class BackupError(Exception):
    """Something the person can act on, in a sentence."""


# ---- where -------------------------------------------------------------------------

def _home(home=None) -> Path:
    if home:
        return Path(home)
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME)


def _private(name: str) -> bool:
    return any(name.startswith(p) for p in PRIVATE)


def _inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def default_name() -> str:
    host = "".join(c for c in platform.node().split(".")[0] if c.isalnum() or c in "-_") or "machine"
    return f"bento-{host}-{time.strftime('%Y-%m-%d')}{SUFFIX}"


def check_passphrase(pw: str) -> None:
    if len(pw or "") < MIN_PASSPHRASE:
        raise BackupError(f"Choose a passphrase of at least {MIN_PASSPHRASE} characters. "
                          "It is the only way to open the backup, so keep it somewhere safe.")


# ---- the sealed stream -----------------------------------------------------------
#
# MAGIC, a 4-byte header length, the header (JSON: format, scrypt parameters, salt,
# nonce prefix, record size), then records: 4-byte length + AES-GCM ciphertext. The
# nonce is the header's 8-byte prefix plus the record's counter; the associated data
# is the header, the counter and a final flag. The header is therefore authenticated
# by every record, the order by the counter, and the end by the one record whose flag
# says so.

@functools.lru_cache(maxsize=8)
def _kdf(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # cached: the standby's active sync seals and opens an update every few seconds
    # with one salt per process (standbysync._salt), and scrypt is meant to be slow
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=n, r=r, p=p,
                          maxmem=256 * 1024 * 1024, dklen=32)


def _check(key: bytes) -> str:
    """A value derived from the key and stored in the header, so a wrong passphrase is
    told apart from a damaged file even when the whole backup is one record."""
    return base64.b64encode(hmac.new(key, b"bento-backup-passphrase-check", hashlib.sha256)
                            .digest()[:16]).decode()


def _aead(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


class _Sealer(io.RawIOBase):
    """A write-only file that encrypts what tarfile streams into it."""

    def __init__(self, out, passphrase: str, salt: bytes | None = None):
        super().__init__()
        salt, self.prefix = salt or os.urandom(16), os.urandom(8)
        cost = dict(SCRYPT)
        key = _kdf(passphrase, salt, **cost)
        head = json.dumps({"format": FORMAT, "kdf": "scrypt", **cost,
                           "salt": base64.b64encode(salt).decode(),
                           "nonce": base64.b64encode(self.prefix).decode(),
                           "check": _check(key), "chunk": CHUNK}, sort_keys=True).encode()
        out.write(MAGIC + len(head).to_bytes(4, "big") + head)
        self.out, self.ad, self.i, self.buf = out, MAGIC + head, 0, bytearray()
        self.box = _aead(key)
        self.sealed = False

    def writable(self):
        return True

    def write(self, b) -> int:
        self.buf += b
        while len(self.buf) >= CHUNK:
            self._record(bytes(self.buf[:CHUNK]), False)
            del self.buf[:CHUNK]
        return len(b)

    def _record(self, data: bytes, final: bool) -> None:
        nonce = self.prefix + self.i.to_bytes(4, "big")
        ct = self.box.encrypt(nonce, data, self.ad + self.i.to_bytes(8, "big") + (b"\1" if final else b"\0"))
        self.out.write(len(ct).to_bytes(4, "big") + ct)
        self.i += 1

    def seal(self) -> None:
        if not self.sealed:
            self._record(bytes(self.buf), True)
            self.buf.clear()
            self.sealed = True


class _Opener(io.RawIOBase):
    """A read-only file that decrypts and checks a sealed stream as tarfile reads it."""

    def __init__(self, inp, passphrase: str):
        super().__init__()
        self.inp = inp
        if inp.read(len(MAGIC)) != MAGIC:
            raise BackupError("This is not a Bento backup (it does not start like one).")
        n = int.from_bytes(inp.read(4) or b"\0", "big")
        if not 0 < n <= MAX_HEADER:
            raise BackupError("This backup's header is damaged.")
        head = inp.read(n)
        try:
            h = json.loads(head)
        except ValueError:
            raise BackupError("This backup's header is damaged.")
        if h.get("format") != FORMAT:
            raise BackupError(f"This backup is in a format this version cannot read ({h.get('format')!r}). "
                              "Update Bento and try again.")
        try:
            n_, r_, p_ = int(h["n"]), int(h["r"]), int(h["p"])
            if not (2 <= n_ <= 1 << 20 and n_ & (n_ - 1) == 0 and 1 <= r_ <= 32 and 1 <= p_ <= 16):
                raise BackupError("This backup's header asks for a key setting this version will not use.")
            key = _kdf(passphrase, base64.b64decode(h["salt"]), n_, r_, p_)
            self.prefix = base64.b64decode(h["nonce"])
        except (KeyError, ValueError, TypeError):
            raise BackupError("This backup's header is damaged.")
        if not hmac.compare_digest(str(h.get("check") or ""), _check(key)):
            raise BackupError("The passphrase is wrong. It is the one chosen when the backup was made.")
        self.box, self.ad, self.i = _aead(key), MAGIC + head, 0
        self.chunk = int(h.get("chunk") or CHUNK)
        self.buf, self.done = bytearray(), False

    def readable(self):
        return True

    def _next(self) -> None:
        from cryptography.exceptions import InvalidTag
        lb = self.inp.read(4)
        if len(lb) < 4:
            raise BackupError("The backup is cut short: it ends before its last part. "
                              "It may not have finished copying or downloading.")
        n = int.from_bytes(lb, "big")
        if n > self.chunk + 16:
            raise BackupError(f"The backup is damaged (part {self.i + 1} has an impossible size).")
        ct = self.inp.read(n)
        if len(ct) < n:
            raise BackupError("The backup is cut short: it ends before its last part. "
                              "It may not have finished copying or downloading.")
        nonce = self.prefix + self.i.to_bytes(4, "big")
        for final in (b"\0", b"\1"):
            try:
                self.buf += self.box.decrypt(nonce, ct, self.ad + self.i.to_bytes(8, "big") + final)
                self.done = final == b"\1"
                break
            except InvalidTag:
                continue
        else:
            # the passphrase was proved by the header's check, so this is the file
            raise BackupError(f"The backup has been changed or damaged since it was made "
                              f"(part {self.i + 1} does not match).")
        self.i += 1
        if self.done and self.inp.read(1):
            raise BackupError("The backup has extra data after its last part; it was changed after it was made.")

    def readinto(self, b) -> int:
        while not self.buf and not self.done:
            self._next()
        n = min(len(b), len(self.buf))
        b[:n] = self.buf[:n]
        del self.buf[:n]
        return n

    def drain(self) -> None:
        """Read to the last record, so a file cut short is caught even when the tar
        stream inside happens to end before it."""
        while not self.done:
            self._next()
        self.buf.clear()


class _Exact(io.RawIOBase):
    """A file read at exactly the size tar was told, padded if it shrank while being
    read: a config written mid-backup must not break the archive around it."""

    def __init__(self, f, size: int):
        super().__init__()
        self.f, self.left, self.short = f, size, False

    def readable(self):
        return True

    def readinto(self, b) -> int:
        if self.left <= 0:
            return 0
        want = min(len(b), self.left)
        got = self.f.readinto(memoryview(b)[:want]) or 0
        if got == 0:
            self.short = True
            got = want
            b[:got] = b"\0" * got
        self.left -= got
        return got


# ---- what goes in ------------------------------------------------------------------

def _copy_db(src: Path, dst: Path) -> None:
    """A consistent copy of a live database, through SQLite's own backup API: a plain
    file copy of a WAL database taken mid-write restores as a corrupt one."""
    s = sqlite3.connect(str(src), timeout=30)
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def _walk(home: Path):
    """(relative posix path, absolute path) for every file worth keeping."""
    for root, dirs, files in os.walk(home):
        r = Path(root)
        rel_root = r.relative_to(home)
        keep = []
        for d in sorted(dirs):
            if d in SKIP_NAMES or (not rel_root.parts and (d in SKIP_TOP or _private(d))):
                continue
            if (r / d).is_symlink():
                continue
            keep.append(d)
        dirs[:] = keep
        for f in sorted(files):
            if not rel_root.parts and (f in SKIP_TOP or _private(f)):
                continue
            if f in SKIP_NAMES or f.endswith(SKIP_SUFFIX):
                continue
            p = r / f
            if p.is_symlink() or not p.is_file():
                continue
            yield (rel_root / f).as_posix(), p


def _users(home: Path) -> list[dict]:
    try:
        data = json.loads((home / "users.json").read_text())
        return [{"id": u.get("id", ""), "name": u.get("name", ""), "admin": bool(u.get("admin"))}
                for u in data.get("users", [])]
    except Exception:
        return []


def _vault_scope(rel: str) -> str:
    """The keyring entry a vault's key lives under (vault._scope, from its place)."""
    parts = PurePosixPath(rel).parts
    if len(parts) == 3 and parts[0] == "users":
        return f"vault-{parts[1]}"
    return "vault-machine"


def _config(home: Path) -> dict:
    try:
        return json.loads((home / "config.json").read_text())
    except Exception:
        return {}


def plan(home=None, workspace: bool = True) -> dict:
    """What a backup would hold, without making one: the Settings row's line."""
    home = _home(home)
    files = list(_walk(home))
    ws = _workspace(home) if workspace else None
    ws_files = list(_walk_plain(ws)) if ws else []
    return {"home": str(home), "files": len(files), "bytes": sum(p.stat().st_size for _, p in files),
            "workspace": str(ws) if ws else "", "workspace_files": len(ws_files),
            "workspace_bytes": sum(p.stat().st_size for _, p in ws_files),
            "accounts": len(_users(home))}


def _workspace(home: Path):
    """The configured workspace, when it is a real folder OUTSIDE the home (inside it,
    it is already in)."""
    w = str(_config(home).get("workspace") or "")
    if not w:
        return None
    p = Path(w).expanduser()
    if not p.is_dir() or _inside(p, home):
        return None
    return p


def _walk_plain(root: Path):
    for r, dirs, files in os.walk(root):
        rp = Path(r)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_NAMES and not (rp / d).is_symlink())
        for f in sorted(files):
            p = rp / f
            if f in SKIP_NAMES or p.is_symlink() or not p.is_file():
                continue
            yield (p.relative_to(root)).as_posix(), p


def _add(tar: tarfile.TarFile, arc: str, path: Path, changed: list) -> None:
    st = path.stat()
    ti = tarfile.TarInfo(arc)
    ti.size, ti.mtime, ti.mode = st.st_size, int(st.st_mtime), st.st_mode & 0o777
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    with open(path, "rb") as f:
        ex = _Exact(f, st.st_size)
        tar.addfile(ti, io.BufferedReader(ex, CHUNK))
        if ex.short:
            changed.append(arc)


def _add_bytes(tar: tarfile.TarFile, arc: str, data: bytes, mode: int = 0o600) -> None:
    ti = tarfile.TarInfo(arc)
    ti.size, ti.mtime, ti.mode = len(data), int(time.time()), mode
    tar.addfile(ti, io.BytesIO(data))


def create(dest, passphrase: str, *, home=None, workspace: bool = True, version: str = "") -> dict:
    """Write an encrypted backup of the whole home to `dest`. Returns the manifest with
    the file's path and size added. The file is 0600 and written beside itself first,
    so an interrupted backup never leaves a file that looks finished."""
    check_passphrase(passphrase)
    home = _home(home)
    if not home.is_dir():
        raise BackupError(f"There is nothing to back up: {home} does not exist.")
    dest = Path(dest).expanduser()
    if dest.is_dir():
        dest = dest / default_name()
    if _inside(dest, home) and not _private(dest.name):
        raise BackupError("Save the backup outside the Bento folder it is backing up "
                          f"({home}); a copy kept inside it is lost with it.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    ws = _workspace(home) if workspace else None
    cfg = _config(home)
    manifest = {
        "format": FORMAT, "created": time.time(), "version": version or _version(),
        "host": platform.node(), "os": platform.system(), "machine": platform.machine(),
        "home": str(home), "user_home": str(Path.home()),
        "workspace": str(ws) if ws else "", "workspace_included": bool(ws),
        "workspace_setting": str(cfg.get("workspace") or ""),
        "accounts": _users(home), "files": 0, "bytes": 0, "databases": [], "vaults": [],
        "telegram": bool((cfg.get("telegram") or {}).get("enabled") and (cfg.get("telegram") or {}).get("bot_token")),
        "whatsapp_linked": (home / "whatsapp" / "session").is_dir(),
        "linked_teams": _count_links(home), "engine": str(cfg.get("engine") or "aria"),
        "default_model": str(cfg.get("default_model") or ""), "changed_while_reading": [],
    }
    keys: dict[str, str] = {}
    part = dest.with_name(dest.name + ".part")
    tmp_root = home / f".backup-tmp-{os.getpid()}-{time.time_ns()}"
    tmp_root.mkdir(mode=0o700)
    try:
        with tempfile.TemporaryDirectory(dir=tmp_root) as tmp:
            items = []
            for rel, p in _walk(home):
                if rel.endswith(".db"):
                    copy = Path(tmp) / f"{len(items)}.db"
                    try:
                        _copy_db(p, copy)
                    except sqlite3.Error:
                        continue            # not a database after all; the file itself is kept below
                    manifest["databases"].append(rel)
                    items.append(("home/" + rel, copy))
                    continue
                if PurePosixPath(rel).name == "vault.json":
                    manifest["vaults"].append(_vault_entry(rel, p, keys))
                items.append(("home/" + rel, p))
            if ws:
                items += [("outside/workspace/" + rel, p) for rel, p in _walk_plain(ws)]
            manifest["files"] = len(items)
            manifest["bytes"] = sum(p.stat().st_size for _, p in items)
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as out:
                sealer = _Sealer(out, passphrase)
                changed: list = []
                # manifest first, so `inspect` reads one member and stops
                with tarfile.open(fileobj=sealer, mode="w|gz") as tar:
                    _add_bytes(tar, "manifest.json", json.dumps(manifest, indent=1).encode(), 0o644)
                    _add_bytes(tar, "keys.json", json.dumps(keys).encode())
                    for arc, p in items:
                        try:
                            _add(tar, arc, p, changed)
                        except FileNotFoundError:
                            changed.append(arc)      # gone between the walk and the read
                    # the list of what changed underneath goes last; the manifest is sealed
                    _add_bytes(tar, "changed.json", json.dumps(changed).encode(), 0o644)
                sealer.seal()
                manifest["changed_while_reading"] = changed
        os.replace(part, dest)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    manifest["path"] = str(dest)
    manifest["size"] = dest.stat().st_size
    return manifest


def _vault_entry(rel: str, p: Path, keys: dict) -> dict:
    """A vault's key, carried when it lives in the keyring (a key FILE is in the home
    and travels as a file)."""
    from . import vault as vaultmod
    try:
        mech = json.loads(p.read_text()).get("key") or ""
    except Exception:
        mech = ""
    carried = mech == "file"
    if mech == "keyring":
        k = vaultmod._keyring_get(_vault_scope(rel))
        if k:
            keys[rel] = k
            carried = True
    return {"path": rel, "mechanism": mech, "carried": carried}


def _count_links(home: Path) -> int:
    try:
        data = json.loads((home / "links.json").read_text())
        return len(data.get("links", data) if isinstance(data, dict) else data)
    except Exception:
        return 0


def _version() -> str:
    try:
        return (Path(__file__).resolve().parent / "VERSION").read_text().strip()
    except OSError:
        return ""


# ---- what comes out ----------------------------------------------------------------

def inspect(path, passphrase: str) -> dict:
    """The manifest, read from the first member without unpacking the rest. It proves
    the passphrase; it does not prove the whole file (restore does, before it moves
    anything)."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise BackupError(f"There is no file at {path}.")
    with open(path, "rb") as f:
        op = _Opener(f, passphrase)
        with tarfile.open(fileobj=io.BufferedReader(op, CHUNK), mode="r|gz") as tar:
            m = tar.next()
            if m is None or m.name != "manifest.json":
                raise BackupError("This backup has no manifest where it should be.")
            return json.loads(tar.extractfile(m).read())


def verify(path, passphrase: str) -> dict:
    """Read a backup to its last record without writing anything: every record's seal
    checked, every name checked. Returns the manifest. Cheaper than `stage` in disk, the
    same in trust: the cloud standby checks each copy it is sent with this."""
    path = Path(path).expanduser()
    manifest = None
    with open(path, "rb") as f:
        op = _Opener(f, passphrase)
        with tarfile.open(fileobj=io.BufferedReader(op, CHUNK), mode="r|gz") as tar:
            for m in tar:
                _safe(m.name)
                if m.name == "manifest.json":
                    manifest = json.loads(tar.extractfile(m).read())
        op.drain()
    if not manifest or manifest.get("format") != FORMAT:
        raise BackupError("This backup has no manifest; it cannot be restored.")
    return manifest


def _safe(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in name or "\0" in name:
        raise BackupError(f"The backup names a file outside where it may go ({name!r}); refused.")
    return p


def _mkdirs(d: Path, root: Path) -> None:
    """Folders a restore creates are the owner's only, like the homes they rebuild."""
    missing = []
    while not d.exists() and d != root:
        missing.append(d)
        d = d.parent
    for m in reversed(missing):
        m.mkdir(mode=0o700)


def stage(path, passphrase: str, *, home=None) -> dict:
    """Decrypt and unpack a backup into a staging folder inside the home, checking
    every record and every name. Nothing outside the staging folder is touched; on any
    problem it is removed and the error says what went wrong. Returns the manifest,
    with `staging` set."""
    home = _home(home)
    home.mkdir(parents=True, exist_ok=True)
    path = Path(path).expanduser()
    if not path.is_file():
        raise BackupError(f"There is no file at {path}.")
    staging = home / f".restoring-{_stamp()}"
    staging.mkdir(mode=0o700)
    try:
        manifest, keys = None, {}
        with open(path, "rb") as f:
            op = _Opener(f, passphrase)
            with tarfile.open(fileobj=io.BufferedReader(op, CHUNK), mode="r|gz") as tar:
                for m in tar:
                    rel = _safe(m.name)
                    if m.name == "manifest.json":
                        manifest = json.loads(tar.extractfile(m).read())
                        continue
                    if m.name == "keys.json":
                        keys = json.loads(tar.extractfile(m).read())
                        continue
                    if m.name == "changed.json":
                        if manifest is not None:
                            manifest["changed_while_reading"] = json.loads(tar.extractfile(m).read())
                        continue
                    if rel.parts[0] not in ("home", "outside") or (
                            rel.parts[0] == "outside" and rel.parts[1:2] != ("workspace",)):
                        raise BackupError(f"The backup holds something this version does not know "
                                          f"({m.name!r}); refused.")
                    if m.isdir():
                        continue
                    if not m.isfile():
                        continue            # links and devices never travel
                    out = staging.joinpath(*rel.parts)
                    _mkdirs(out.parent, staging)
                    src = tar.extractfile(m)
                    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, (m.mode & 0o777) or 0o600)
                    with os.fdopen(fd, "wb") as w:
                        shutil.copyfileobj(src, w, CHUNK)
                    os.utime(out, (m.mtime, m.mtime))
            op.drain()
        if not manifest or manifest.get("format") != FORMAT:
            raise BackupError("This backup has no manifest; it cannot be restored.")
        (staging / "home").mkdir(exist_ok=True)
        fd = os.open(staging / "keys.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as w:
            json.dump(keys, w)
        (staging / "manifest.json").write_text(json.dumps(manifest))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    manifest["staging"] = str(staging)
    return manifest


def apply(staging, *, home=None, keyring: bool = True) -> dict:
    """Swap a staged backup in: the current home's contents move aside into
    `.before-restore-<time>` (kept, never deleted), the staged ones move in, vault keys
    go back where they can live, and folder paths follow the new machine. Returns the
    report the CLI prints and the desktop shows once."""
    home = _home(home)
    staging = Path(staging)
    manifest = json.loads((staging / "manifest.json").read_text())
    keys = json.loads((staging / "keys.json").read_text() or "{}")
    stamp = _stamp()
    aside = home / f".before-restore-{stamp}"
    moved = 0
    for e in sorted(home.iterdir()):
        if _private(e.name) or e.name == staging.name:
            continue
        aside.mkdir(mode=0o700, exist_ok=True)
        os.replace(e, aside / e.name)
        moved += 1
    for e in sorted((staging / "home").iterdir()):
        os.replace(e, home / e.name)
    report = {"from_host": manifest.get("host", ""), "created": manifest.get("created", 0),
              "version": manifest.get("version", ""), "restored_at": time.time(),
              "accounts": [u.get("name", "") for u in manifest.get("accounts", [])],
              "previous": str(aside) if moved else "", "workspace": "", "workspace_previous": "",
              "attention": []}
    # the workspace, where this machine keeps it
    ws_src = staging / "outside" / "workspace"
    if ws_src.is_dir():
        target = Path(_remap(manifest.get("workspace", ""), manifest, home) or
                      (Path.home() / "AgentOS"))
        if target.exists() and any(target.iterdir()):
            prev = target.with_name(f"{target.name}.before-restore-{stamp}")
            try:
                os.replace(target, prev)
                report["workspace_previous"] = str(prev)
            except OSError:
                target = target.with_name(f"{target.name}.restored-{stamp}")
                report["attention"].append(f"Your workspace was restored to {target}, because the "
                                           "folder already there could not be moved aside.")
        target.parent.mkdir(parents=True, exist_ok=True)
        # An EMPTY folder already there (a fresh install makes ~/AgentOS on its first
        # start) is filled, never nested into: shutil.move into an existing folder puts
        # the source INSIDE it, and the workspace landed at ~/AgentOS/workspace while the
        # config pointed at ~/AgentOS. Found moving a laptop to a fresh cloud container.
        if target.is_dir() and not any(target.iterdir()):
            try:
                target.rmdir()
            except OSError:
                pass                     # a mount point: it stays, and is filled below
        if target.is_dir():
            for e in sorted(ws_src.iterdir()):
                shutil.move(str(e), str(target / e.name))
        else:
            shutil.move(str(ws_src), str(target))
        report["workspace"] = str(target)
    if report["workspace_previous"]:
        report["attention"].append(f"Your workspace is back in {report['workspace']}. The folder "
                                   f"that was there is kept in {report['workspace_previous']}.")
    report["attention"] += _vaults_back(home, manifest, keys, keyring)
    report["paths_rewritten"] = _remap_everywhere(home, manifest)
    report["attention"] += _attention(manifest)
    if report["previous"]:
        report["attention"].append(f"What was here before is kept in {report['previous']}. "
                                   "Delete it once you are happy.")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        (home / LAST).write_text(json.dumps(report, indent=1))
    except OSError:
        pass
    return report


def restore(path, passphrase: str, *, home=None, keyring: bool = True) -> dict:
    """Stage, then apply: the whole restore, for the CLI. Nothing moves unless every
    record of the file checked out."""
    m = stage(path, passphrase, home=home)
    return apply(m["staging"], home=home, keyring=keyring)


# ---- the desktop's two-step restore ------------------------------------------------

def mark_ready(staging, home=None) -> None:
    """Stage from the desktop, apply on the next start: a running server must not have
    its home swapped from under it."""
    (_home(home) / READY).write_text(json.dumps({"staging": Path(staging).name, "at": time.time()}))


def pending(home=None) -> dict:
    home = _home(home)
    try:
        d = json.loads((home / READY).read_text())
        st = home / d["staging"]
        if st.is_dir() and _inside(st, home):
            m = json.loads((st / "manifest.json").read_text())
            return {"staging": str(st), "at": d.get("at", 0), "host": m.get("host", ""),
                    "created": m.get("created", 0), "accounts": len(m.get("accounts", []))}
    except Exception:
        pass
    return {}


def cancel_pending(home=None) -> bool:
    home = _home(home)
    p = pending(home)
    try:
        (home / READY).unlink()
    except OSError:
        pass
    if p:
        shutil.rmtree(p["staging"], ignore_errors=True)
    return bool(p)


def apply_pending(home=None, echo=print) -> dict:
    """Called by `serve` before anything opens the home. Applies a restore the desktop
    staged, once."""
    home = _home(home)
    p = pending(home)
    if not p:
        try:
            (home / READY).unlink()
        except OSError:
            pass
        return {}
    try:
        (home / READY).unlink()
    except OSError:
        pass
    report = apply(p["staging"], home=home)
    if echo:
        echo(f"  Restored the backup from {report['from_host'] or 'another machine'}.")
        for line in report["attention"]:
            echo(f"  · {line}")
    return report


def last_restore(home=None, forget: bool = False) -> dict:
    p = _home(home) / LAST
    try:
        d = json.loads(p.read_text())
    except Exception:
        return {}
    if forget:
        try:
            p.unlink()
        except OSError:
            pass
    return d


# ---- after the swap ------------------------------------------------------------------

def _remap(value: str, manifest: dict, home: Path) -> str:
    """A path recorded on the old machine, where it lives on this one."""
    if not isinstance(value, str) or not value.startswith("/") and not value[1:3] == ":\\":
        return value
    old_home, old_user = manifest.get("home") or "", manifest.get("user_home") or ""
    for old, new in ((old_home, str(home)), (old_user, str(Path.home()))):
        sep = "/" if "/" in old else "\\"
        if old and old != new and (value == old or value.startswith(old.rstrip("/\\") + sep)):
            rest = value[len(old.rstrip("/\\")):]
            if sep != os.sep:            # a Windows path arriving on Linux, or back
                rest = rest.replace(sep, os.sep)
            return new + rest
    return value


def _remap_json(obj, manifest: dict, home: Path, count: list):
    if isinstance(obj, dict):
        return {k: _remap_json(v, manifest, home, count) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_remap_json(v, manifest, home, count) for v in obj]
    if isinstance(obj, str):
        new = _remap(obj, manifest, home)
        if new != obj:
            count[0] += 1
        return new
    return obj


#: Database columns that hold a folder the machine will use: a mission's watched folder
#: (its trigger, the task it made and the text it runs with) and the folder grant that
#: lets it read there. Missed at first: after a move, a folder-watch mission kept
#: watching the old machine's path and was silently dead. Never `audit` (hash-chained
#: history) and never messages or memories (what was said, not where things are).
DB_PATH_COLUMNS = (("flows", "mission"), ("flows", "permissions"), ("flow_triggers", "config"),
                   ("grants", "resource"), ("tasks", "prompt"), ("tasks", "trigger_config"))


def _remap_text(value: str, manifest: dict, home: Path) -> str:
    """Every old folder inside a piece of text, where it lives on this machine. One pass,
    longest prefix first, and only a whole folder (followed by a separator, a quote, a
    space, a glob or the end), so a path already rewritten is never rewritten again."""
    if not isinstance(value, str) or not value:
        return value
    pairs = []
    for old, new in ((manifest.get("home") or "", str(home)), (manifest.get("user_home") or "", str(Path.home()))):
        old = old.rstrip("/\\")
        if old and old != new.rstrip("/\\") and old in value:
            pairs.append((old, new.rstrip("/\\")))
    if not pairs:
        return value
    pairs.sort(key=lambda p: -len(p[0]))
    table = dict(pairs)
    pat = re.compile("(" + "|".join(re.escape(o) for o, _ in pairs) + r")(?=[/\\\s\"'*,;)\]}]|$)")
    return pat.sub(lambda m: table[m.group(1)], value)


def _remap_databases(con, manifest: dict, home: Path, count: list) -> None:
    for table, col in DB_PATH_COLUMNS:
        try:
            rows = con.execute(f'SELECT rowid, "{col}" FROM "{table}"').fetchall()
        except sqlite3.Error:
            continue
        for rid, val in rows:
            nv = _remap_text(val, manifest, home)
            if nv != val:
                con.execute(f'UPDATE "{table}" SET "{col}"=? WHERE rowid=?', (nv, rid))
                count[0] += 1


def _remap_everywhere(home: Path, manifest: dict) -> int:
    """Every config and every agent's folder rules, in every home."""
    count = [0]
    homes = [home] + sorted(p for p in (home / "users").glob("*") if p.is_dir())
    for h in homes:
        cp = h / "config.json"
        if cp.is_file():
            try:
                data = json.loads(cp.read_text())
                new = _remap_json(data, manifest, home, count)
                if new != data:
                    cp.write_text(json.dumps(new, indent=2))
            except (OSError, ValueError):
                pass
        db = h / "agentos.db"
        if db.is_file():
            try:
                con = sqlite3.connect(str(db))
                try:
                    rows = con.execute("SELECT name, spec FROM executor_profiles").fetchall()
                except sqlite3.Error:
                    rows = []
                for name, spec in rows:
                    try:
                        s = json.loads(spec or "{}")
                    except ValueError:
                        continue
                    ns = _remap_json(s, manifest, home, count)
                    if ns != s:
                        con.execute("UPDATE executor_profiles SET spec=? WHERE name=?",
                                    (json.dumps(ns), name))
                _remap_databases(con, manifest, home, count)
                con.commit()
                con.close()
            except sqlite3.Error:
                pass
    return count[0]


def _vaults_back(home: Path, manifest: dict, keys: dict, keyring: bool) -> list[str]:
    """Each carried keyring key goes into this machine's keyring, or into a 0600 key
    file beside its vault when there is none. The key is the SAME key, so everything
    in the vault still opens; only where it is kept changes, and the report says so."""
    from . import vault as vaultmod
    out = []
    for v in manifest.get("vaults", []):
        rel, mech = v.get("path", ""), v.get("mechanism", "")
        vf = home / rel
        if mech != "keyring" or not vf.is_file():
            continue
        k = keys.get(rel)
        who = "your" if rel == "vault.json" else f"account {PurePosixPath(rel).parts[1]}'s"
        if not k:
            out.append(f"The passwords in {who} vault could not be carried (its key was in a keyring "
                       "the backup could not reach). Sign in to mail and calendar again.")
            continue
        if keyring and vaultmod._keyring_tool() and vaultmod._keyring_set(_vault_scope(rel), k):
            continue
        kp = vf.parent / vaultmod.KEY_FILE
        fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(k)
        data = json.loads(vf.read_text())
        data["key"] = "file"
        fd = os.open(vf.with_suffix(".tmp"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(vf.with_suffix(".tmp"), vf)
        out.append(f"This machine has no keyring, so {who} vault's key is now kept in a file "
                   "only you can read. That is weaker than a keyring.")
    return out


def _attention(m: dict) -> list[str]:
    """What a move cannot carry by itself, in the person's words."""
    out = []
    if m.get("telegram"):
        out.append("Telegram: only one machine can answer your bot. Switch the old machine off, "
                   "or turn Telegram off there.")
    if m.get("whatsapp_linked"):
        out.append("WhatsApp: the linked device came along. Switch the old machine off; if it "
                   "stops answering, link it again in Settings → Channels.")
    if m.get("linked_teams"):
        out.append(f"Linked teams ({m['linked_teams']}): they still know this machine, but they "
                   "reach it at its old address. If the address changed, link them again.")
    eng = m.get("engine") or "aria"
    if eng != "aria":
        out.append(f"Your brain was {eng}. Install it on this machine too, or choose another in "
                   "Settings → AI providers.")
    dm = m.get("default_model") or ""
    if dm.startswith("ollama/"):
        out.append(f"Local models are not in the backup. Pull {dm[7:]} again in Ollama.")
    ws, home = m.get("workspace_setting") or "", (m.get("home") or "").rstrip("/\\")
    inside = bool(home) and (ws == home or ws.startswith(home + "/") or ws.startswith(home + "\\"))
    if ws and not m.get("workspace_included") and not inside:
        out.append("Your workspace folder was not in this backup; copy it across yourself.")
    if m.get("changed_while_reading"):
        out.append(f"{len(m['changed_while_reading'])} file(s) changed while the backup was being "
                   "made and may be incomplete.")
    return out
