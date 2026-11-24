"""Every Bento database is encrypted at rest with this machine's key.

Asked for as "is the database encrypted at rest too? This should be decrypted by machine key".
Memory, the knowledge graph, conversations, the ledger, usage, readings: all of it was plain
SQLite that anyone who copied the file could read. The vault, the sealed browser profile, the
backup file and the cloud copy were already encrypted; the databases were not.

How it works:
  * SQLCipher (the `sqlcipher3` package: SQLCipher Community Edition with OpenSSL, built into
    a wheel). Every page of the file is AES-256 encrypted with an HMAC, so a copied file, an
    old SD card or a disk taken out of the machine reads as noise.
  * The key is derived from the machine's service key (away.py), the one key Bento's service
    has from the moment it starts: HMAC-SHA256(service key, "bento database v1"), handed to
    SQLCipher as a raw key, so no password stretching runs on every open. One key for every
    database on the machine, the accounts' included. It is never written anywhere itself.
  * `connect()` is the ONE way any Bento code opens one of its databases. It reads the file's
    first 16 bytes: a plain SQLite header opens unkeyed (a home not yet converted, or a 32-bit
    Pi), anything else, a new file included, opens with the key.
  * `encrypt_home()` converts a plain database once, at server start, before anything opens
    it (migrate.everyone). It refuses a file another process has open, because that process
    would keep writing to the plain file it already holds. The copy is checked table by
    table before it replaces the original.

What it does NOT do, and every face says so (`status()`):
  * Where the service key is a file beside the database (a headless Pi, no keyring), a stolen
    disk carries both. Then it protects a copied database file and nothing more. With the key
    in the keyring (a Mac, a Linux desktop) the disk alone opens nothing.
  * While Bento runs, the key is in its memory, and root on the machine can read memory.
  * Removing the plain file after conversion can't be guaranteed on an SSD or SD card: the
    old blocks may still be on the flash until they are reused.
  * Files that are not databases (the workspace, logs, soul.md) are not covered. Full-disk
    encryption covers everything; `diskcrypt.py` says whether this disk has it.

Kept free of HTTP and asyncio, like vault.py.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import weakref
import sqlite3 as _plain
import time
from pathlib import Path

try:
    from sqlcipher3 import dbapi2 as sql
    AVAILABLE = True
except Exception:          # no wheel here (a 32-bit Pi), or it failed to load
    sql = _plain
    AVAILABLE = False

# the module every caller uses for errors and rows, so a `except dbcrypt.sql.OperationalError`
# catches what the connection it opened raises (sqlcipher3's classes are not sqlite3's)
Row = sql.Row
Error = sql.Error
DatabaseError = sql.DatabaseError
OperationalError = sql.OperationalError
IntegrityError = sql.IntegrityError

class _Conn(sql.Connection):
    """A connection this process holds, weakly listed (`_HELD`), so `open_elsewhere` knows its
    own without reading its every file handle: late in a long-lived process that was tens of
    thousands of readlinks, twice per database (measured: a test 0.2 s alone, 93 s in the suite)."""


_HELD: "weakref.WeakSet" = weakref.WeakSet()
OPEN_SCAN_S = 2.0          # how long open_elsewhere may read /proc before it says "can't tell"

HEADER = b"SQLite format 3\x00"
INFO = b"bento database v1"
# the databases Bento keeps, relative to the machine's home; each account's is users/<id>/agentos.db
MACHINE_DBS = ("agentos.db", "pool.db", "telemetry.db")

_KEY: dict = {}            # (stamp of the service key's files) -> hex key
LAST: list = []            # what the last encrypt_home did, for the server's diary line


def _path_of(database) -> Path | None:
    """The file a connect string names, or None (":memory:", a bare URI with no file)."""
    s = str(database)
    if s in ("", ":memory:"):
        return None
    if s.startswith("file:"):
        s = s[5:].split("?", 1)[0]
        if not s or s == ":memory:":
            return None
    return Path(s)


def is_plain(path) -> bool | None:
    """True for a plain SQLite file, False for an encrypted one, None when it is absent or empty
    (a new database, which is created encrypted)."""
    p = _path_of(path) if not isinstance(path, Path) else path
    if p is None:
        return None
    try:
        with open(p, "rb") as f:
            head = f.read(16)
    except OSError:
        return None
    if not head:
        return None
    return head == HEADER


def home_of(path) -> Path:
    """The machine home a database belongs to, whose key opens it: the folder it is in, or for
    an account's (`users/<id>/agentos.db`) the machine home above it."""
    p = Path(os.path.abspath(str(path)))
    parent = p.parent
    if parent.parent.name == "users":
        return parent.parent.parent
    return parent


def _own(home: Path | None) -> Path | None:
    """None when `home` is this process's own home (away.py's default, the keyring allowed)."""
    from . import config as cfgmod
    if home is None:
        return None
    try:
        if Path(home).resolve() == Path(cfgmod.AGENTOS_HOME).resolve():
            return None
    except OSError:
        pass
    return Path(home)


def _stamp(home: Path | None = None) -> tuple:
    from . import away
    out = [str(home or "")]
    for p in (away._meta_path(home), away._key_path(home)):
        try:
            st = p.stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((str(p), 0, 0))
    return tuple(out)


def key_hex(create: bool = True, home: Path | None = None) -> str:
    """The database key of a machine home (this process's when None), as 64 hex digits, or ''
    when its service key can't be found. Kept for the life of the process, keyed on the service
    key's files, so a restore that brings another machine's key back is seen at once."""
    home = _own(home)
    stamp = _stamp(home)
    k = _KEY.get(stamp)
    if k:
        return k
    from . import away
    try:
        service = away._load(create=create, home=home)
    except Exception:
        service = b""
    if not service:
        return ""
    k = hmac.new(service, INFO, hashlib.sha256).hexdigest()
    if len(_KEY) > 16:
        _KEY.clear()
    _KEY[_stamp(home)] = k       # the stamp again: _load(create=True) may have just made the files
    return k


def _key_sql(k: str) -> str:
    return f"PRAGMA key = \"x'{k}'\""


def connect(database, *args, plain: bool | None = None, key: str = "", **kw):
    """Open a Bento database, keyed when it is (or will be) encrypted.

    `plain=True` opens without the key whatever the file holds (the backup copy of a plain
    database must stay plain: SQLCipher won't copy pages between a plain and an encrypted one).
    `key` opens it with that key (hex) instead of its home's: a private copy of another file.
    """
    kw.setdefault("factory", _Conn)
    con = sql.connect(database, *args, **kw)
    if isinstance(con, _Conn):
        p0 = _path_of(database)
        con._bento_path = os.path.abspath(str(p0)) if p0 is not None else ""
        _HELD.add(con)
    if not AVAILABLE:
        return con
    if key and not plain:
        con.execute(_key_sql(key))
        return con
    fresh = False
    path = _path_of(database)
    if plain is None:
        state = None if path is None else is_plain(path)
        plain = path is None or state is True
        fresh = state is None
    if plain:
        return con
    # only a NEW database may make the machine's key: an existing encrypted one whose key is
    # gone stays unreadable, never re-keyed (the vault's rule), and says why when it is read
    k = key_hex(create=fresh, home=home_of(path)) if path is not None else ""
    if k:
        con.execute(_key_sql(k))
    return con


def attach(con, path, alias: str) -> None:
    """ATTACH another database, keyed by what IT is. A bare ATTACH borrows the main file's key,
    so a plain main could not read an encrypted file beside it, and the other way round."""
    path = Path(path)
    if not AVAILABLE:
        con.execute(f"ATTACH DATABASE ? AS {alias}", (str(path),))
        return
    if is_plain(path) is True:
        con.execute(f"ATTACH DATABASE ? AS {alias} KEY ''", (str(path),))
        return
    k = key_hex(create=False, home=home_of(path))
    con.execute(f"ATTACH DATABASE ? AS {alias} KEY \"x'{k}'\"", (str(path),))


def ours(home: Path) -> list[Path]:
    """Every database Bento keeps under a machine home: its own, and each account's."""
    home = Path(home)
    out = [home / n for n in MACHINE_DBS]
    users = home / "users"
    if users.is_dir():
        out += sorted(p / "agentos.db" for p in users.iterdir() if p.is_dir())
    return [p for p in out if p.exists()]


def open_elsewhere(path: Path) -> list[int]:
    """Processes holding the file (or its WAL) open, read from /proc. [] when none, or when
    this system has no /proc to read (macOS, Windows): there the conversion runs only at the
    server's own start, before anything here opens it."""
    base = os.path.abspath(str(path))
    targets = {base, base + "-wal", base + "-shm", str(path), str(path) + "-wal", str(path) + "-shm"}
    try:
        targets |= {os.path.realpath(t) for t in list(targets)}
    except OSError:
        pass
    pids = []
    me = os.getpid()
    # this process: the connections dbcrypt.connect opened and that are still open (every Bento
    # module opens through it; the test refuses a sqlite3.connect anywhere else)
    for c in list(_HELD):
        if getattr(c, "_bento_path", "") in targets:
            try:
                c.total_changes                    # raises on a closed connection
            except Exception:
                continue
            pids.append(me)
            break
    proc = Path("/proc")
    if not proc.is_dir():
        return pids
    deadline = time.monotonic() + OPEN_SCAN_S
    uid = os.getuid() if hasattr(os, "getuid") else None
    for d in proc.iterdir():
        if not d.name.isdigit() or int(d.name) == me:
            continue
        if time.monotonic() > deadline:
            # couldn't look at everything in time: say "can't tell", which leaves the file plain
            # until the next start, rather than replace a file something may still hold
            pids.append(-1)
            break
        try:
            if uid is not None and d.stat().st_uid != uid:
                continue                   # another user's process can't hold this user's file
        except OSError:
            continue
        try:
            for fd in (d / "fd").iterdir():
                try:
                    if os.readlink(fd) in targets:
                        pids.append(int(d.name))
                        break
                except OSError:
                    continue
        except OSError:
            continue
    return pids


def _counts(con) -> dict:
    names = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {n: con.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}


def encrypt_file(path: Path) -> str:
    """Convert one plain database to an encrypted one in place. Returns '' when it was done or
    there was nothing to do, otherwise why it was left plain (in words)."""
    path = Path(path)
    if not AVAILABLE:
        return "SQLCipher isn't installed here"
    if is_plain(path) is not True:
        return ""
    k = key_hex(create=True, home=home_of(path))
    if not k:
        return "this machine's key can't be found"
    busy = [p for p in open_elsewhere(path)]
    if busy == [-1] or -1 in busy:
        return "Bento couldn't check in time whether another program has it open"
    if busy:
        return f"it is open in another process ({', '.join(map(str, busy[:3]))})"
    tmp = path.with_name(path.name + ".encrypting")
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm"), Path(str(tmp) + "-journal")):
        p.unlink(missing_ok=True)
    src = sql.connect(str(path), timeout=30)
    try:
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        version = int(src.execute("PRAGMA user_version").fetchone()[0])
        before = _counts(src)
        quoted = str(tmp).replace("'", "''")
        src.execute(f"ATTACH DATABASE '{quoted}' AS enc KEY \"x'{k}'\"")
        src.execute("SELECT sqlcipher_export('enc')")
        src.execute(f"PRAGMA enc.user_version = {version}")
        src.execute("DETACH DATABASE enc")
    except Exception as e:
        src.close()
        tmp.unlink(missing_ok=True)
        return f"the conversion failed ({type(e).__name__}: {e})"
    src.close()
    # check the copy before it replaces anything: it opens with the key, it is whole, and
    # every table holds what the original held
    try:
        chk = sql.connect(str(tmp))
        chk.execute(_key_sql(k))
        ok = chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        after = _counts(chk)
        chk.close()
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return f"the encrypted copy couldn't be read back ({type(e).__name__})"
    if not ok or after != before:
        tmp.unlink(missing_ok=True)
        return "the encrypted copy didn't match the original, so the original was kept"
    if open_elsewhere(path):
        tmp.unlink(missing_ok=True)
        return "another process opened it while it was being converted"
    os.replace(tmp, path)
    for p in (Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        p.unlink(missing_ok=True)
    return ""


def plain_copy(src: Path, dst: Path) -> None:
    """A plain copy of a database, for inside a backup (backup.py): the backup file is sealed
    with its own passphrase, and a plain copy restores on any machine, which encrypts it with
    ITS key at its next start. The live file is read through SQLite's backup API into an
    encrypted copy first (a consistent snapshot of a database that may be mid-write), and only
    that private copy is exported plain."""
    src, dst = Path(src), Path(dst)
    s = connect(str(src), timeout=30)
    if not AVAILABLE or is_plain(src) is not False:
        d = connect(str(dst), plain=True)
        try:
            s.backup(d)
        finally:
            d.close()
            s.close()
        return
    mid = dst.with_name(dst.name + ".sealed")
    k = key_hex(create=False, home=home_of(src))
    d = connect(str(mid), key=k)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    try:
        m = connect(str(mid), key=k)
        quoted = str(dst).replace("'", "''")
        version = int(m.execute("PRAGMA user_version").fetchone()[0])
        m.execute(f"ATTACH DATABASE '{quoted}' AS plain KEY ''")
        m.execute("SELECT sqlcipher_export('plain')")
        m.execute(f"PRAGMA plain.user_version = {version}")
        m.execute("DETACH DATABASE plain")
        m.close()
    finally:
        mid.unlink(missing_ok=True)


def encrypt_home(home: Path, say=None) -> list[dict]:
    """Convert every plain database under a machine home. One row per database converted or
    left plain: {path, ok, why}. Already-encrypted ones are not listed."""
    say = say or (lambda m: None)
    out = []
    for p in ours(home):
        if is_plain(p) is not True:
            continue
        t0 = time.monotonic()
        why = encrypt_file(p)
        row = {"path": str(p), "ok": not why, "why": why, "ms": round((time.monotonic() - t0) * 1000)}
        out.append(row)
        rel = p.relative_to(home) if p.is_relative_to(home) else p
        say(f"✓ {rel} is encrypted with this machine's key" if not why
            else f"! {rel} stays unencrypted for now: {why}")
    return out


def status(home: Path | None = None) -> dict:
    """The one answer every face reads: are the databases encrypted, with what, and what that
    protects. {state: encrypted|partly|plain|unavailable, key: keyring|file|'', counts, line, detail}"""
    from . import away
    from . import config as cfgmod
    home = Path(home or cfgmod.AGENTOS_HOME)
    dbs = ours(home)
    enc = [p for p in dbs if is_plain(p) is False]
    plain = [p for p in dbs if is_plain(p) is True]
    try:
        import json
        mech = json.loads(away._meta_path().read_text()).get("key") or ""
    except Exception:
        mech = ""
    if not AVAILABLE:
        state = "unavailable"
        line = ("The databases aren't encrypted: SQLCipher has no build for this machine "
                "(a 32-bit Pi). Full-disk encryption is the way to protect them here.")
    elif plain and not enc:
        state = "plain"
        line = "The databases aren't encrypted yet. Bento encrypts them at its next start."
    elif plain:
        state = "partly"
        line = (f"{len(enc)} of {len(dbs)} databases are encrypted. The rest are encrypted at "
                "Bento's next start.")
    else:
        state = "encrypted"
        line = "Your memory, conversations, ledger and readings are encrypted with this machine's key."
    if mech == "keyring":
        detail = ("The key is in the system keyring, so a copied file or a disk taken out of "
                  "this machine can't be read.")
    elif mech == "file":
        detail = ("The key is a file in Bento's home, beside the databases. A copied database "
                  "can't be read, but a stolen disk carries both. Full-disk encryption covers that.")
    else:
        detail = ""
    return {"state": state, "available": AVAILABLE, "key": mech, "encrypted": len(enc),
            "plain": len(plain), "total": len(dbs), "line": line, "detail": detail,
            "plain_files": [str(p.relative_to(home)) for p in plain]}
