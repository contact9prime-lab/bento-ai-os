"""Active sync for the cloud standby: the cloud a few seconds behind, not ten minutes.

Without it the standby holds whole sealed copies of the home, sent at most every ten
minutes (standby.PUSH_S). With it, your machine also sends small sealed UPDATES as things
happen: every row any database wrote, every file that changed in the home or the
workspace, and a few facts about the machine itself (its version, its brain, which agent
CLIs are installed). The standby keeps them beside the copy they build on, and a
takeover replays them over that copy, so the cloud carries on from the last change
rather than from the last full copy.

How a change is caught, and why that way:

  * Rows, through SQLite triggers. Every table gets three AFTER triggers that write
    (table, rowid, insert/update/delete) into one journal table, `_bento_sync`. That is
    the only way to see every write the program makes without threading a hook through
    the ~250 places that write; a timestamp column would miss deletes and the tables
    that have none. The triggers exist only while active sync is on (`ensure`), on the
    main machine; every other side drops them at start, so a backup restored elsewhere
    never keeps journaling for nobody.
  * An update carries each changed row's CURRENT value, read at send time, never the
    value at the moment of the change. So applying updates in order is idempotent and
    converges, and a row changed three times is sent once.
  * The journal's AUTOINCREMENT high-water mark travels inside every full copy (it is in
    the database), and a takeover skips journal entries at or below it. That is what
    makes a full copy and the updates around it fit together without a lock between the
    copy and the writer.
  * Files by size and modification time, against what the standby was last given.

What it deliberately does NOT do:

  * Merge. One side acts at a time (standby.py); updates only ever flow from the side
    that is working to the side that stands by, and a hand-back is a whole copy.
  * Carry a new vault. A vault's key travels only inside a full copy, so a new vault
    (a new account's) makes the next send a full copy instead of an update.
  * Carry the machine's software. An agent CLI installed on your machine is not
    installed on the cloud by any of this; the update says it was, and the standby's
    page says what the cloud would be missing.

Kept free of HTTP and asyncio, like standby.py: the server's loop calls `pending` and
`build` in a thread, standby.py sends, and `replay` runs inside `standby.takeover`.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import sqlite3
import tarfile
import threading
import time
from pathlib import Path

JOURNAL = "_bento_sync"
TRIGGER = "_bento_sync_"
POLL_S = 2                    # how often the main machine looks for a change
FILES_S = 6                   # the home's files are walked this often
WORKSPACE_S = 10              # and the workspace, which can be large, this often
SNAP_EVERY = 3600             # a full copy at most this often while updates flow
FILE_CAP = 50 << 20           # a file larger than this waits for the next full copy
MAX_ROWS = 20000              # an update larger than this is a full copy instead
FEED = 20                     # what the standby remembers of what changed
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

#: How a table's changes read to a person. Tables not named here are counted under
#: "other data"; the noisy bookkeeping ones (logs, usage, the ledger) are not mentioned.
WORDS = {
    "messages": ("chat message", "chat messages"),
    "conversations": ("chat", "chats"),
    "memories": ("memory", "memories"),
    "kg_nodes": ("knowledge entry", "knowledge entries"),
    "kg_edges": ("knowledge link", "knowledge links"),
    "flows": ("mission", "missions"),
    "flow_triggers": ("mission trigger", "mission triggers"),
    "tasks": ("schedule", "schedules"),
    "grants": ("permission", "permissions"),
    "subagents": ("agent", "agents"),
    "executor_profiles": ("executor profile", "executor profiles"),
    "skills": ("skill", "skills"),
    "brief_items": ("Brief item", "Brief items"),
    "user_apps": ("app", "apps"),
    "app_data": ("app's data", "apps' data"),
    "automations": ("automation", "automations"),
    "spaces": ("space", "spaces"),
    "avatars": ("character", "characters"),
    "themes": ("theme", "themes"),
    "fabric_runs": ("run", "runs"),
    "team_messages": ("team message", "team messages"),
    "assets": ("picture or file", "pictures and files"),
}
QUIET = {"logs", "usage", "audit", "fabric_events", "timeline_events", "task_runs",
         "app_versions", "quarantine", "proactive_items", "flow_artifacts", "fabric_parked",
         "telegram_chats", "whatsapp_chats", "mcp_registry", "worlds"}
FILE_WORDS = {"config.json": "settings", "vault.json": "saved passwords", "soul.md": "your agent's soul",
              "users.json": "accounts"}

_CONS: dict[str, sqlite3.Connection] = {}
_LOCK = threading.RLock()


class SyncError(Exception):
    """A sentence the person can act on."""


# ---- the journal ---------------------------------------------------------------------

def _home(home=None) -> Path:
    from . import backup as bk
    return bk._home(home)


def databases(home=None) -> list[tuple[str, Path]]:
    """Every database a full copy would hold, as (relative path, path)."""
    from . import backup as bk
    home = _home(home)
    return [(rel, p) for rel, p in bk._walk(home) if rel.endswith(".db")]


def _con(path: Path) -> sqlite3.Connection:
    key = str(path)
    with _LOCK:
        c = _CONS.get(key)
        if c is None:
            c = sqlite3.connect(key, timeout=30, check_same_thread=False, isolation_level=None)
            _CONS[key] = c
        return c


def forget_connections() -> None:
    with _LOCK:
        for c in _CONS.values():
            try:
                c.close()
            except Exception:
                pass
        _CONS.clear()


def _tables(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name != ? ORDER BY name", (JOURNAL,))]


def _covered(con) -> set[str]:
    return {r[0][len(TRIGGER) + 2:] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE ?", (TRIGGER + "i_%",))}


def install(path: Path) -> list[str]:
    """Journal every table of one database. Idempotent; returns the tables it newly
    covered. A table newly covered that already holds rows gets a FULL marker, so the next
    update carries all of it (a table created after the last full copy, or a new account's
    database)."""
    with _LOCK:
        con = _con(path)
        con.execute(f"CREATE TABLE IF NOT EXISTS {JOURNAL} (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "tbl TEXT NOT NULL, rid INTEGER, op TEXT NOT NULL)")
        have = _covered(con)
        new = []
        for t in _tables(con):
            if t in have or not _NAME.match(t):
                continue
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(f'CREATE TRIGGER IF NOT EXISTS "{TRIGGER}i_{t}" AFTER INSERT ON "{t}" BEGIN '
                            f"INSERT INTO {JOURNAL}(tbl,rid,op) VALUES('{t}',NEW.rowid,'u'); END")
                con.execute(f'CREATE TRIGGER IF NOT EXISTS "{TRIGGER}u_{t}" AFTER UPDATE ON "{t}" BEGIN '
                            f"INSERT INTO {JOURNAL}(tbl,rid,op) SELECT '{t}',OLD.rowid,'d' WHERE OLD.rowid<>NEW.rowid; "
                            f"INSERT INTO {JOURNAL}(tbl,rid,op) VALUES('{t}',NEW.rowid,'u'); END")
                con.execute(f'CREATE TRIGGER IF NOT EXISTS "{TRIGGER}d_{t}" AFTER DELETE ON "{t}" BEGIN '
                            f"INSERT INTO {JOURNAL}(tbl,rid,op) VALUES('{t}',OLD.rowid,'d'); END")
                if con.execute(f'SELECT 1 FROM "{t}" LIMIT 1').fetchone():
                    con.execute(f"INSERT INTO {JOURNAL}(tbl,rid,op) VALUES(?,NULL,'f')", (t,))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
            new.append(t)
        return new


def remove(path: Path, con: sqlite3.Connection | None = None) -> bool:
    """Drop the triggers and the journal from one database. Returns whether there was
    anything to drop."""
    own = con is None
    with _LOCK:
        c = con or _con(path)
        names = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE ?", (TRIGGER + "%",))]
        had = bool(names) or bool(c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (JOURNAL,)).fetchone())
        if not had:
            return False
        c.execute("BEGIN IMMEDIATE")
        try:
            for n in names:
                c.execute(f'DROP TRIGGER IF EXISTS "{n}"')
            c.execute(f"DROP TABLE IF EXISTS {JOURNAL}")
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        if own:
            with _LOCK:
                _CONS.pop(str(path), None)
            c.close()
        return True


def ensure(home=None, on: bool = False) -> dict:
    """Journal every database while active sync is on; drop every trace of it otherwise.
    Called at start and on every look, so a new account's database is picked up and a
    home restored from a copy never keeps journaling for nobody."""
    out = {"covered": [], "removed": 0}
    for rel, p in databases(home):
        try:
            if on:
                for t in install(p):
                    out["covered"].append(f"{rel}:{t}")
            elif remove(p):
                out["removed"] += 1
        except sqlite3.Error:
            continue
    return out


def high_water(con) -> int:
    try:
        r = con.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (JOURNAL,)).fetchone()
    except sqlite3.Error:
        return 0
    return int(r[0]) if r and r[0] is not None else 0


def marks(home=None) -> dict[str, int]:
    """Each database's journal high-water mark, now."""
    out = {}
    for rel, p in databases(home):
        try:
            out[rel] = high_water(_con(p))
        except sqlite3.Error:
            out[rel] = 0
    return out


def prune(home, upto: dict[str, int]) -> None:
    """Forget journal entries the standby has: they are in its copy or its updates."""
    for rel, p in databases(home):
        n = int(upto.get(rel, 0) or 0)
        if not n:
            continue
        try:
            _con(p).execute(f"DELETE FROM {JOURNAL} WHERE seq <= ?", (n,))
        except sqlite3.Error:
            continue


# ---- files -----------------------------------------------------------------------------

def file_state(home=None, ws: bool = True) -> dict[str, list[int]]:
    """{"home/<rel>" | "ws/<rel>": [size, mtime_ns]} for every file a copy would hold
    that is not a database (those travel as rows)."""
    from . import backup as bk
    home = _home(home)
    out: dict[str, list[int]] = {}
    for rel, p in bk._walk(home):
        if rel.endswith(".db"):
            continue
        try:
            s = p.stat()
        except OSError:
            continue
        out["home/" + rel] = [s.st_size, s.st_mtime_ns]
    root = bk._workspace(home) if ws else None
    if root:
        for rel, p in bk._walk_plain(root):
            try:
                s = p.stat()
            except OSError:
                continue
            out["ws/" + rel] = [s.st_size, s.st_mtime_ns]
    return out


def _file_path(home: Path, key: str) -> Path | None:
    from . import backup as bk
    kind, _, rel = key.partition("/")
    if kind == "home":
        return home / rel
    root = bk._workspace(home)
    return root / rel if root else None


# ---- the machine itself ----------------------------------------------------------------

def meta(home=None) -> dict:
    """A few facts about this machine that a person would want the cloud to know changed:
    the version, the brain, the agent CLIs installed here. Cheap: the CLI probes are
    cached for five minutes (executors.probe)."""
    from . import backup as bk
    home = _home(home)
    cfg = bk._config(home)
    out = {"version": bk._version(), "engine": str(cfg.get("engine") or "aria"),
           "model": str(cfg.get("default_model") or ""), "clis": {}}
    try:
        from . import executors as ex
        for eid in ex.DRIVEN:
            try:
                out["clis"][eid] = bool(ex.probe(eid).get("installed"))
            except Exception:
                out["clis"][eid] = False
    except Exception:
        pass
    ws = bk._workspace(home)
    out["workspace"] = str(ws) if ws else ""
    return out


def meta_changes(before: dict, after: dict) -> list[str]:
    """What changed about the machine, in words."""
    if not before:
        return []
    out = []
    if before.get("version") and after.get("version") != before.get("version"):
        out.append(f"Bento updated from {before.get('version')} to {after.get('version')}")
    if (before.get("engine"), before.get("model")) != (after.get("engine"), after.get("model")):
        what = after.get("engine") if after.get("engine") != "aria" else (after.get("model") or "the built-in loop")
        out.append(f"the brain changed to {what}")
    titles = {"claude-code": "Claude Code", "gemini-cli": "Gemini CLI", "codex": "Codex"}
    for eid, now in (after.get("clis") or {}).items():
        was = (before.get("clis") or {}).get(eid)
        if was is None or was == now:
            continue
        out.append(f"{titles.get(eid, eid)} {'installed' if now else 'removed'}")
    if before.get("workspace") != after.get("workspace") and after.get("workspace"):
        out.append("the workspace folder moved")
    return out


def summary(rows: dict[str, int], files: list[str], deleted: list[str], ws_prefix: str = "") -> list[str]:
    """What an update holds, in words: '2 chat messages', 'settings'. `ws_prefix` is the
    workspace's place inside the home, when it lives there."""
    out, other = [], 0
    for t, n in sorted(rows.items(), key=lambda kv: (-kv[1], kv[0])):
        if t in WORDS:
            one, many = WORDS[t]
            out.append(f"{n} {one if n == 1 else many}")
        elif t not in QUIET:
            other += n
    names = set()
    ws = 0
    for key in list(files) + list(deleted):
        kind, _, rel = key.partition("/")
        if kind == "ws" or (ws_prefix and key.startswith(ws_prefix)):
            ws += 1
            continue
        base = rel.rsplit("/", 1)[-1]
        names.add(FILE_WORDS.get(base, "other files"))
    if ws:
        out.append(f"{ws} workspace file{'' if ws == 1 else 's'}")
    out += sorted(names - {"other files"})
    if "other files" in names or other:
        out.append("other data")
    return out


# ---- building an update (the main machine) -------------------------------------------

def _enc(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(v)).decode()}
    return v


def _dec(v):
    if isinstance(v, dict) and "$b" in v:
        return base64.b64decode(v["$b"])
    return v


def _db_changes(con, since: int) -> tuple[dict, int, int]:
    """One database's changes after journal entry `since`, read in one transaction:
    ({"tables": {t: {"sql", "cols"}}, "ops": [[seq, t, rid, values|None] | [seq, t, "F", rows]]},
    high-water, row count)."""
    try:
        con.execute("BEGIN")
    except sqlite3.OperationalError:
        pass
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (JOURNAL,)).fetchone():
            return {}, since, 0
        entries = con.execute(f"SELECT seq, tbl, rid, op FROM {JOURNAL} WHERE seq > ? ORDER BY seq",
                              (since,)).fetchall()
        if not entries:
            return {}, since, 0
        hw = entries[-1][0]
        last: dict[tuple, int] = {}
        full: dict[str, int] = {}
        for seq, t, rid, op in entries:
            if op == "f":
                full[t] = seq
            else:
                last[(t, rid)] = seq
        # rows of a table being sent whole need not be sent one by one as well
        last = {k: s for k, s in last.items() if not (k[0] in full and s <= full[k[0]])}
        tables: dict[str, dict] = {}
        ops: list = []
        count = 0

        def table(t):
            if t not in tables:
                r = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
                if not r:
                    return None
                cols = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
                tables[t] = {"sql": r[0], "cols": cols}
            return tables[t]

        for t, seq in full.items():
            info = table(t)
            if info is None:
                continue
            cols = ",".join(f'"{c}"' for c in info["cols"])
            rows = [[r[0], [_enc(v) for v in r[1:]]]
                    for r in con.execute(f'SELECT rowid, {cols} FROM "{t}"')]
            count += len(rows)
            ops.append([seq, t, "F", rows])
        by_table: dict[str, dict[int, int]] = {}
        for (t, rid), seq in last.items():
            by_table.setdefault(t, {})[rid] = seq
        for t, rids in by_table.items():
            info = table(t)
            ids = list(rids)
            found: dict[int, list] = {}
            if info is not None:
                cols = ",".join(f'"{c}"' for c in info["cols"])
                for i in range(0, len(ids), 500):
                    part = ids[i:i + 500]
                    q = f'SELECT rowid, {cols} FROM "{t}" WHERE rowid IN ({",".join("?" * len(part))})'
                    for r in con.execute(q, part):
                        found[r[0]] = [_enc(v) for v in r[1:]]
            for rid, seq in rids.items():
                ops.append([seq, t, rid, found.get(rid)])
                count += 1
        ops.sort(key=lambda o: o[0])
        return {"tables": tables, "ops": ops}, hw, count
    finally:
        try:
            con.execute("COMMIT")
        except sqlite3.OperationalError:
            pass


def pending(home, base: dict, files_known: dict | None, check_files: bool, ws: bool) -> dict:
    """Is there anything to send? Cheap: one indexed read per database, and a walk of the
    files only when `check_files`."""
    out = {"rows": False, "files": False}
    hw = base.get("hw") or {}
    for rel, p in databases(home):
        try:
            if high_water(_con(p)) > int(hw.get(rel, 0) or 0):
                out["rows"] = True
                break
        except sqlite3.Error:
            continue
    if check_files and files_known is not None:
        now = file_state(home, ws)
        out["files"] = now != files_known
        out["file_state"] = now
    return out


def build(dest: Path, secret: str, *, home=None, base: dict, files_known: dict,
          files_now: dict | None, last_meta: dict, n: int) -> dict:
    """Write one sealed update to `dest`. Returns what it holds, or {"empty": True}, or
    {"want_copy": why} when only a full copy will do."""
    from . import backup as bk
    home = _home(home)
    hw0 = base.get("hw") or {}
    dbs, hw, rows_by_table, total = {}, dict(hw0), {}, 0
    for rel, p in databases(home):
        try:
            ch, top, count = _db_changes(_con(p), int(hw0.get(rel, 0) or 0))
        except sqlite3.Error:
            continue
        if not ch:
            continue
        dbs[rel] = ch
        hw[rel] = top
        total += count
        for op in ch["ops"]:
            rows_by_table[op[1]] = rows_by_table.get(op[1], 0) + (len(op[3]) if op[2] == "F" else 1)
        if total > MAX_ROWS:
            return {"want_copy": f"more than {MAX_ROWS} rows changed at once"}
    changed, deleted, skipped = [], [], []
    known = dict(files_known or {})
    if files_now is not None:
        for key, sig in files_now.items():
            if known.get(key) == sig:
                continue
            if key.endswith("/vault.json") or key == "home/vault.json":
                if key not in known:
                    return {"want_copy": "a new vault, whose key travels only in a full copy"}
            if sig[0] > FILE_CAP:
                skipped.append(key)
                continue
            changed.append(key)
        deleted = [k for k in known if k not in files_now]
    now_meta = meta(home)
    sys_changes = meta_changes(last_meta, now_meta)
    if not dbs and not changed and not deleted and not sys_changes:
        return {"empty": True}
    ws_prefix = ""
    w = str(bk._config(home).get("workspace") or "")
    if w:
        try:
            ws_prefix = "home/" + Path(w).expanduser().resolve().relative_to(home.resolve()).as_posix() + "/"
        except (ValueError, OSError):
            ws_prefix = ""
    words = summary(rows_by_table, changed, deleted, ws_prefix) + sys_changes
    head = {"format": "bento-sync/1", "copy_id": base.get("copy_id", ""), "n": n, "created": time.time(),
            "meta": now_meta, "changes": words, "dbs": dbs, "deleted": deleted,
            "workspace": now_meta.get("workspace", "")}
    sent_files = {}
    part = dest.with_name(dest.name + ".part")
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            sealer = bk._Sealer(out, secret, salt=_salt(secret))
            with tarfile.open(fileobj=sealer, mode="w|gz") as tar:
                bk._add_bytes(tar, "delta.json", json.dumps(head).encode())
                for key in changed:
                    p = _file_path(home, key)
                    if p is None:
                        continue
                    kind, _, rel = key.partition("/")
                    arc = ("home/" if kind == "home" else "outside/workspace/") + rel
                    try:
                        bk._add(tar, arc, p, [])
                        sent_files[key] = files_now[key]
                    except FileNotFoundError:
                        continue
            sealer.seal()
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    new_known = dict(known)
    new_known.update(sent_files)
    for k in deleted:
        new_known.pop(k, None)
    return {"path": str(dest), "bytes": dest.stat().st_size, "hw": hw, "files": new_known,
            "meta": now_meta, "changes": words, "rows": sum(rows_by_table.values()),
            "skipped": skipped, "n": n}


_SALTS: dict[str, bytes] = {}


def _salt(secret: str) -> bytes:
    """One salt per secret per process: the scrypt cost (~32 MiB, a fraction of a second)
    is paid once, not every two seconds. Every update still has its own random nonce
    prefix, which is what AES-GCM needs."""
    import hashlib
    k = hashlib.sha256(secret.encode()).hexdigest()
    if k not in _SALTS:
        _SALTS[k] = os.urandom(16)
    return _SALTS[k]


# ---- reading an update (the standby) -------------------------------------------------

def read_head(path: Path, secret: str) -> dict:
    """Check every record of an update and return its header."""
    from . import backup as bk
    head = None
    with open(path, "rb") as f:
        op = bk._Opener(f, secret)
        with tarfile.open(fileobj=io.BufferedReader(op, bk.CHUNK), mode="r|gz") as tar:
            for m in tar:
                if m.name == "delta.json":
                    head = json.loads(tar.extractfile(m).read())
                    continue
                rel = bk._safe(m.name)
                if rel.parts[0] not in ("home", "outside") or (
                        rel.parts[0] == "outside" and rel.parts[1:2] != ("workspace",)):
                    raise bk.BackupError(f"The update holds something this version does not know ({m.name!r}).")
        op.drain()
    if not head or head.get("format") != "bento-sync/1":
        raise bk.BackupError("This is not a Bento update.")
    return head


def _ensure_table(con, t: str, info: dict) -> list[str]:
    if not _NAME.match(t):
        raise SyncError(f"refused a table named {t!r}")
    have = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
    if not have:
        sql = str(info.get("sql") or "")
        if not sql.upper().startswith("CREATE TABLE"):
            raise SyncError(f"no way to create table {t}")
        con.execute(sql)
        have = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
    for c in info.get("cols") or []:
        if c not in have and _NAME.match(c):
            con.execute(f'ALTER TABLE "{t}" ADD COLUMN "{c}"')
            have.append(c)
    return have


def _apply_db(path: Path, ch: dict, skip_upto: int) -> int:
    """Apply one database's part of an update inside one transaction. Entries at or
    below `skip_upto` are already in the copy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    applied = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            tables = ch.get("tables") or {}
            for seq, t, rid, val in ch.get("ops") or []:
                if seq <= skip_upto:
                    continue
                info = tables.get(t)
                if info is None:
                    if rid == "F" or val is not None:
                        continue
                    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                        con.execute(f'DELETE FROM "{t}" WHERE rowid=?', (rid,))
                        applied += 1
                    continue
                _ensure_table(con, t, info)
                cols = info["cols"]
                names = ",".join(["rowid"] + [f'"{c}"' for c in cols])
                marks_ = ",".join("?" * (len(cols) + 1))
                if rid == "F":
                    con.execute(f'DELETE FROM "{t}"')
                    for r, vals in val:
                        con.execute(f'INSERT OR REPLACE INTO "{t}" ({names}) VALUES ({marks_})',
                                    [r] + [_dec(v) for v in vals])
                    applied += len(val)
                elif val is None:
                    con.execute(f'DELETE FROM "{t}" WHERE rowid=?', (rid,))
                    applied += 1
                else:
                    con.execute(f'INSERT OR REPLACE INTO "{t}" ({names}) VALUES ({marks_})',
                                [rid] + [_dec(v) for v in val])
                    applied += 1
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    return applied


def replay(staging, updates: list[Path], secret: str) -> dict:
    """Apply updates, in order, over a staged copy (backup.stage's layout). The journal is
    dropped from every staged database first: the side that takes over works, it does not
    journal. Stops at the first update that does not apply and says so; what came before
    it stays applied."""
    from . import backup as bk
    staging = Path(staging)
    root = staging / "home"
    skip: dict[str, int] = {}
    for p in sorted(root.rglob("*.db")):
        rel = p.relative_to(root).as_posix()
        try:
            c = sqlite3.connect(str(p), timeout=30, isolation_level=None)
            try:
                skip[rel] = high_water(c)
                remove(p, c)
            finally:
                c.close()
        except sqlite3.Error:
            skip[rel] = 0
    report = {"applied": 0, "rows": 0, "last_at": 0.0, "error": "", "workspace": ""}
    for path in updates:
        try:
            head = None
            with open(path, "rb") as f:
                op = bk._Opener(f, secret)
                with tarfile.open(fileobj=io.BufferedReader(op, bk.CHUNK), mode="r|gz") as tar:
                    for m in tar:
                        if m.name == "delta.json":
                            head = json.loads(tar.extractfile(m).read())
                            continue
                        if not m.isfile():
                            continue
                        rel = bk._safe(m.name)
                        out = staging.joinpath(*rel.parts)
                        bk._mkdirs(out.parent, staging)
                        src = tar.extractfile(m)
                        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, (m.mode & 0o777) or 0o600)
                        with os.fdopen(fd, "wb") as w:
                            shutil.copyfileobj(src, w, bk.CHUNK)
                        os.utime(out, (m.mtime, m.mtime))
                op.drain()
            if not head:
                raise SyncError("an update had no header")
            for rel, ch in (head.get("dbs") or {}).items():
                target = root.joinpath(*bk._safe(rel).parts)
                report["rows"] += _apply_db(target, ch, skip.get(rel, 0))
                skip[rel] = max(skip.get(rel, 0), max((o[0] for o in ch.get("ops") or []), default=0))
            for key in head.get("deleted") or []:
                kind, _, rel = key.partition("/")
                base = root if kind == "home" else staging / "outside" / "workspace"
                try:
                    (base.joinpath(*bk._safe(rel).parts)).unlink()
                except (OSError, bk.BackupError):
                    pass
            if head.get("workspace"):
                report["workspace"] = head["workspace"]
            report["applied"] += 1
            report["last_at"] = float(head.get("created") or 0)
        except Exception as e:                       # noqa: BLE001
            report["error"] = f"{type(e).__name__}: {e}"
            break
    if report["workspace"] and (staging / "outside" / "workspace").is_dir():
        try:
            mp = staging / "manifest.json"
            m = json.loads(mp.read_text())
            if not m.get("workspace"):
                m["workspace"], m["workspace_included"] = report["workspace"], True
                mp.write_text(json.dumps(m))
        except (OSError, ValueError):
            pass
    return report
