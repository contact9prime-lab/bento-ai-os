"""Time travel: rewind what an agent changed, step by step, and fork from there.

Every developer has watched an agent wreck a working folder halfway through a task. This
module keeps enough of the past to undo it: before each step that changes something, a
CHECKPOINT; under it, the files that step was about to change and every row the agent's
memory and knowledge graph changed since. The desktop's scrubber (`00j-timetravel.js`)
slides along the checkpoints, shows what going back would undo, and rewinds; a fork then
starts a new conversation from that step on another brain.

What it holds, and how:

- **Memory, the graph and skills** are journalled by SQLite triggers into `_tt_undo`
  (the old row as JSON, or a mark that a row was added), so a rewind is exact and nothing
  has to remember to call this module. The triggers are rebuilt from the live columns at
  every start, so a migration that adds a column is journalled from then on.
- **Files** are copied before the file tools change them (`before_tool`): the agent's
  writes, its reports, the soul. Content-addressed under `.timetravel/blobs`, one copy per
  content, and a file over `FILE_CAP` is noted as too big rather than half kept.
- **A shell command cannot be captured.** What `run_command` changed is not in the
  timeline, and every surface says so at that checkpoint instead of promising a rewind it
  cannot make. Nor can an agent CLI's own native edits; only its calls to this OS's tools.

Five rules keep it safe:

- **A rewind writes files as the server, so a row is never trusted because it is there.** Each
  checkpoint is signed with a key in the machine's home, out of every jail's reach, and bound to
  the home it belongs to; a blob must hash to its name; and every path is checked again at the
  moment of the rewind (`refusal`). A forged row in an account's own database made the server
  write attacker bytes over the machine's users.json, and its author admin.

- **Preview and rewind are one computation** (`plan`), the jobs rule: what the scrubber
  shows is what `rewind` does.
- **Nothing is deleted by a rewind.** A file it replaces or removes is moved to
  `.timetravel/rewound/<time>/` first, so a rewind can itself be undone by hand.
- **Checkpoints are the person's.** Per account, in their own database and home (so
  they travel only in that person's own backup), pruned to `KEEP_DAYS` / `KEEP_POINTS`.
- **It never touches the ledger.** `audit` is hash-chained and is history, not state.

Stdlib only, no HTTP and no asyncio, like jobs.py: `bento timetravel` reads and rewinds
with the server down.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

TABLES = ("memories", "kg_nodes", "kg_edges", "skills")
KEEP_DAYS = 7
KEEP_POINTS = 500
FILE_CAP = 5 * 1024 * 1024
#: Tools whose step can change a file, and how to find which one.
FILE_TOOLS = ("write_file", "save_report", "update_soul")
#: Tools that change the agent's memory, graph or skills (journalled by the triggers).
MEMORY_TOOLS = ("remember", "forget", "kg_add", "save_skill", "update_memory")
#: A step that changes things this module cannot see.
UNSEEN_TOOLS = ("run_command", "run_python", "git_commit", "git_pull", "git_clone", "git_init")
STATE = ("live", "rewound")


def _now() -> float:
    return time.time()


class Forged(ValueError):
    """A checkpoint this machine did not sign. Nothing it names is touched."""


KEY_FILE = "timetravel.key"
_SIGNED = ("id", "ts", "seq", "conversation_id", "run_id", "step", "tool", "detail", "files", "unseen")


def _key(make: bool = True) -> bytes:
    """The machine's signing key, read at call time because tests and a restore move the home.
    It sits in the machine's home, never an account's, so an account's shell has no way to it."""
    from . import config as cfgmod
    p = Path(cfgmod.AGENTOS_HOME) / KEY_FILE
    try:
        return p.read_bytes()
    except OSError:
        if not make:
            return b""
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    return p.read_bytes()


def _mac(home: Path, row: dict, key: bytes) -> str:
    """Over the row's words and the home it belongs to, so a row copied from one account's
    database to another's reads as forged there."""
    body = json.dumps([os.path.realpath(str(home))] + [row.get(k) for k in _SIGNED],
                      ensure_ascii=False, sort_keys=True, default=str)
    return hmac.new(key, body.encode("utf-8"), hashlib.sha256).hexdigest()


def signed(home: Path, row: dict) -> bool:
    """`row` as it is in the table (`files` still its JSON text)."""
    key, mac = _key(make=False), str(row.get("mac") or "")
    return bool(key and mac) and hmac.compare_digest(_mac(home, row, key), mac)


# ---- the journal -----------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS _tt_undo (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  tbl TEXT NOT NULL, op TEXT NOT NULL, rid INTEGER NOT NULL, old TEXT);
CREATE TABLE IF NOT EXISTS _tt_points (id TEXT PRIMARY KEY, ts REAL NOT NULL, seq INTEGER NOT NULL,
  conversation_id TEXT DEFAULT '', run_id TEXT DEFAULT '', step INTEGER DEFAULT 0, tool TEXT DEFAULT '',
  detail TEXT DEFAULT '', files TEXT DEFAULT '[]', unseen INTEGER DEFAULT 0, state TEXT DEFAULT 'live',
  mac TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS _tt_state (k TEXT PRIMARY KEY, v TEXT);
INSERT OR IGNORE INTO _tt_state(k, v) VALUES ('paused', '0');
CREATE INDEX IF NOT EXISTS idx_tt_points_ts ON _tt_points(ts);
"""
_WHEN = "WHEN (SELECT v FROM _tt_state WHERE k='paused')='0'"
_TS = "((julianday('now') - 2440587.5) * 86400.0)"


def install(db) -> None:
    """The journal and its triggers, rebuilt from the live columns. Called by Store at
    every open, after its migrations."""
    db.executescript(DDL)
    if "mac" not in {r[1] for r in db.execute('PRAGMA table_info("_tt_points")')}:
        db.execute("ALTER TABLE _tt_points ADD COLUMN mac TEXT DEFAULT ''")
    have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in TABLES:
        for kind in ("i", "u", "d"):
            db.execute(f'DROP TRIGGER IF EXISTS "_tt_{kind}_{t}"')
        if t not in have:
            continue
        cols = [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]
        old = "json_object(" + ", ".join(f"'{c}', OLD.\"{c}\"" for c in cols) + ")"
        db.execute(f'CREATE TRIGGER "_tt_i_{t}" AFTER INSERT ON "{t}" {_WHEN} BEGIN '
                   f"INSERT INTO _tt_undo(ts, tbl, op, rid, old) VALUES ({_TS}, '{t}', 'i', NEW.rowid, NULL); END")
        db.execute(f'CREATE TRIGGER "_tt_u_{t}" AFTER UPDATE ON "{t}" {_WHEN} BEGIN '
                   f"INSERT INTO _tt_undo(ts, tbl, op, rid, old) VALUES ({_TS}, '{t}', 'u', OLD.rowid, {old}); END")
        db.execute(f'CREATE TRIGGER "_tt_d_{t}" AFTER DELETE ON "{t}" {_WHEN} BEGIN '
                   f"INSERT INTO _tt_undo(ts, tbl, op, rid, old) VALUES ({_TS}, '{t}', 'd', OLD.rowid, {old}); END")
    db.commit()


def _seq(db) -> int:
    row = db.execute("SELECT seq FROM sqlite_sequence WHERE name='_tt_undo'").fetchone()
    return int(row[0]) if row else 0


# ---- files -------------------------------------------------------------------------

def home_dir(home: Path) -> Path:
    return Path(home) / ".timetravel"


def _blob(home: Path, data: bytes) -> str:
    h = hashlib.sha256(data).hexdigest()
    p = home_dir(home) / "blobs" / h[:2] / h
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(p)
    return h


def _read_blob(home: Path, h: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", str(h)):
        raise Forged("that is not a blob's name")
    data = (home_dir(home) / "blobs" / h[:2] / h).read_bytes()
    if hashlib.sha256(data).hexdigest() != h:
        raise Forged("a kept copy does not match its name")
    return data


def refusal(path: str, home: Path) -> str:
    """Why a rewind may not write this path now, or ''. The same lines the file tools hold: a
    rewind runs as the server, so without this it is the widest write on the machine."""
    from . import protected
    from . import users as usersmod
    real = os.path.realpath(path)
    if real != path:
        return "a link now sits on the way to that path"
    if real == os.path.realpath(str(Path(home) / "soul.md")):
        return ""                                      # the agent's own soul, named by this OS
    try:
        cfg = usersmod.cfg_for()
    except Exception:  # noqa: BLE001 - no settings to read means nothing extra is allowed
        cfg = {}
    why = protected.write_refused(real) or protected.outside_agent_area(real, True, [cfg.get("workspace") or ""])
    if why:
        return why
    if usersmod.enabled():
        from .tools import _under_any, safe_folders
        if not _under_any(real, [os.path.realpath(str(home)), *safe_folders(cfg, write=True)]):
            return "that path belongs to another account"
    return ""


def capture(home: Path, path: Path) -> dict:
    """The file as it is now: its bytes kept by content, or the fact it was not there. Opened
    link by link at its real path, and a security file is never copied into the blobs at all."""
    from . import protected, safeopen
    real = os.path.realpath(str(path))
    if protected.secret(real):
        return {"path": real, "existed": True, "skipped": "a security file"}
    try:
        fd = safeopen.open_file(real)
    except FileNotFoundError:
        return {"path": real, "existed": False}
    except OSError:
        return {"path": real, "existed": True, "skipped": "not a file"}
    with os.fdopen(fd, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size > FILE_CAP:
            return {"path": real, "existed": True, "skipped": f"over {FILE_CAP // (1024 * 1024)} MB", "size": size}
        return {"path": real, "existed": True, "blob": _blob(home, f.read()), "size": size}


def targets(tool: str, args: dict, resolve, soul_path=None, workspace: str = "") -> list[Path]:
    """The files a step is about to change, read from its own arguments the way the tool
    reads them (`resolve` is the toolbox's own path rule)."""
    args = args or {}
    if tool == "write_file" and args.get("path"):
        return [resolve(str(args["path"]))]
    if tool == "save_report" and args.get("title"):
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", str(args["title"]).lower()).strip("-")[:50] or "report"
        return [Path(workspace).expanduser() / "reports" / f"{time.strftime('%Y-%m-%d')}-{slug}.html"]
    if tool == "update_soul" and soul_path:
        return [Path(soul_path)]
    return []


# ---- checkpoints -------------------------------------------------------------------

def changes_things(tool: str) -> bool:
    return tool in FILE_TOOLS or tool in MEMORY_TOOLS or tool in UNSEEN_TOOLS


def checkpoint(db, home: Path, tool: str, detail: str = "", files: list[Path] = (),
               conversation_id: str = "", run_id: str = "", step: int = 0) -> dict:
    """Before a step that changes something: what it is about to change, kept."""
    caps = [capture(home, f) for f in files]
    pid = f"{int(_now() * 1000):x}{secrets.token_hex(2)}"
    row = {"id": pid, "ts": _now(), "seq": _seq(db), "conversation_id": conversation_id or "",
           "run_id": run_id or "", "step": int(step or 0), "tool": tool, "detail": str(detail or "")[:200],
           "files": caps, "unseen": int(tool in UNSEEN_TOOLS), "state": "live"}
    files_json = json.dumps(caps)
    mac = ""
    with contextlib.suppress(OSError):
        mac = _mac(home, {**row, "files": files_json}, _key())
    db.execute("INSERT INTO _tt_points(id, ts, seq, conversation_id, run_id, step, tool, detail, files, unseen, state, mac)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (pid, row["ts"], row["seq"], row["conversation_id"], row["run_id"], row["step"], tool,
                row["detail"], files_json, row["unseen"], "live", mac))
    db.commit()
    return row


def _point(r) -> dict:
    d = dict(r) if not isinstance(r, dict) else r
    d["raw_files"] = d.get("files") or "[]"
    try:
        d["files"] = json.loads(d["raw_files"])
    except ValueError:
        d["files"] = []
    return d


def _rows(db, q: str, args=()) -> list[dict]:
    """Rows as dicts whatever row factory this connection has."""
    cur = db.execute(q, args)
    cols = [c[0] for c in cur.description]
    return [_point(dict(zip(cols, tuple(r)))) for r in cur.fetchall()]


def _public(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("raw_files", "mac")}


def _genuine(home: Path, d: dict) -> bool:
    return signed(home, {**d, "files": d.get("raw_files", "[]")})


def _trusted_files(home: Path, d: dict) -> list[dict]:
    """A row's files if this machine signed them. A row with none has nothing to lie about."""
    if not d["files"]:
        return []
    return d["files"] if _genuine(home, d) else []


def points(db, conversation_id: str = "", limit: int = 200, live_only: bool = False) -> list[dict]:
    q, args = "SELECT * FROM _tt_points", []
    where = []
    if conversation_id:
        where.append("conversation_id=?")
        args.append(conversation_id)
    if live_only:
        where.append("state='live'")
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(int(limit))
    return [_public(r) for r in _rows(db, q, args)][::-1]


def get(db, pid: str) -> dict | None:
    rows = _rows(db, "SELECT * FROM _tt_points WHERE id=?", (pid,))
    return _public(rows[0]) if rows else None


def _since(db, ts: float, live_only: bool) -> list[dict]:
    q = "SELECT * FROM _tt_points WHERE ts >= ?" + (" AND state='live'" if live_only else "")
    return _rows(db, q + " ORDER BY ts LIMIT ?", (ts, KEEP_POINTS * 2))


# ---- what going back would undo ------------------------------------------------------

_LABEL = {"memories": "memory", "kg_nodes": "graph entity", "kg_edges": "graph fact", "skills": "skill"}


def _flag_forged(pid: str) -> None:
    from . import secevents
    from . import users as usersmod
    secevents.flag("timetravel.forged", str(pid)[:40], source="rewind", uid=usersmod.current() or "")


def _files_of(home: Path, rows: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """The files these checkpoints would put back, the earliest copy of each, and what is refused
    with why. Preview and rewind both read this, so neither can promise what the other refuses."""
    files: dict[str, dict] = {}
    refused: list[dict] = []
    for x in rows:
        if x["files"] and not _genuine(home, x):
            _flag_forged(x["id"])
            refused.append({"path": "(a checkpoint)", "why": "not signed by this machine"})
            continue
        for f in x["files"]:
            path = str(f.get("path") or "")
            if not path or path in files:
                continue
            why = refusal(path, home)
            if why:
                refused.append({"path": path, "why": why})
            else:
                files[path] = f                  # the earliest copy is the state back then
    return files, refused


def plan(db, home: Path, pid: str) -> dict:
    """Going back to just before checkpoint `pid`: every row change since it, every file
    a later step changed (with the earliest copy, which is how it was then), and the steps
    whose changes cannot be undone. The scrubber shows this; `rewind` does exactly this."""
    found = _rows(db, "SELECT * FROM _tt_points WHERE id=?", (pid,))
    if not found:
        raise KeyError(pid)
    # A forged row chooses `seq` and `ts`, which decide how much gets undone, so it stops here. A
    # row from before signing is refused the same way when it names files.
    if not _genuine(home, found[0]) and (found[0]["files"] or found[0].get("mac")):
        _flag_forged(pid)
        raise Forged("That checkpoint was not signed by this machine, so nothing was changed.")
    p = _public(found[0])
    later = _since(db, p["ts"], live_only=True)
    rows = db.execute("SELECT seq, tbl, op FROM _tt_undo WHERE seq > ? ORDER BY seq", (p["seq"],)).fetchall()
    counts: dict[str, dict] = {}
    for _, tbl, op in rows:
        c = counts.setdefault(tbl, {"added": 0, "changed": 0, "removed": 0})
        c[{"i": "added", "u": "changed", "d": "removed"}[op]] += 1
    files, refused = _files_of(home, later)
    words = []
    for tbl, c in counts.items():
        lab = _LABEL.get(tbl, tbl)
        for k, verb in (("added", "remove"), ("changed", "restore"), ("removed", "bring back")):
            if c[k]:
                words.append(f"{verb} {c[k]} {lab}{'s' if c[k] != 1 else ''}")
    restore = [f for f in files.values() if f.get("existed") and f.get("blob")]
    drop = [f for f in files.values() if not f.get("existed")]
    skipped = [f for f in files.values() if f.get("skipped")]
    if restore:
        words.append(f"put back {len(restore)} file{'s' if len(restore) != 1 else ''}")
    if drop:
        words.append(f"set aside {len(drop)} new file{'s' if len(drop) != 1 else ''}")
    unseen = [x for x in later if x["unseen"]]
    return {"point": p, "steps": len(later), "rows": len(rows), "counts": counts,
            "restore": [f["path"] for f in restore], "remove": [f["path"] for f in drop],
            "skipped": [{"path": f["path"], "why": f["skipped"]} for f in skipped] + refused,
            "unseen": [{"tool": x["tool"], "detail": x["detail"]} for x in unseen],
            "words": words or ["nothing to undo since then"],
            "warning": (f"{len(unseen)} step{'s' if len(unseen) != 1 else ''} ran a shell command or git; "
                        "what those changed is not in the timeline") if unseen else ""}


def rewind(db, home: Path, pid: str) -> dict:
    """Go back to just before checkpoint `pid`. Rows are put back in reverse order with the
    journal paused (a rewind is not itself journalled); files are put back or set aside,
    and whatever they replace is moved to .timetravel/rewound/<time>/ first."""
    pl = plan(db, home, pid)
    p = pl["point"]
    aside = home_dir(home) / "rewound" / time.strftime("%Y%m%d-%H%M%S")
    moved = []
    db.execute("UPDATE _tt_state SET v='1' WHERE k='paused'")
    try:
        rows = db.execute("SELECT seq, tbl, op, rid, old FROM _tt_undo WHERE seq > ? ORDER BY seq DESC",
                          (p["seq"],)).fetchall()
        for seq, tbl, op, rid, old in rows:
            if tbl not in TABLES:
                continue
            if op == "i":
                db.execute(f'DELETE FROM "{tbl}" WHERE rowid=?', (rid,))
            else:
                vals = json.loads(old or "{}")
                cols = list(vals)
                # these become SQL, so only a column the table really has
                if not set(cols) <= {r[1] for r in db.execute(f'PRAGMA table_info("{tbl}")')}:
                    raise Forged("A journal row names a column that does not exist.")
                if op == "u":
                    db.execute(f'UPDATE "{tbl}" SET ' + ", ".join(f'"{c}"=?' for c in cols) + " WHERE rowid=?",
                               [vals[c] for c in cols] + [rid])
                else:
                    db.execute(f'INSERT OR REPLACE INTO "{tbl}"(rowid, ' + ", ".join(f'"{c}"' for c in cols)
                               + ") VALUES (?" + ",?" * len(cols) + ")", [rid] + [vals[c] for c in cols])
        db.execute("DELETE FROM _tt_undo WHERE seq > ?", (p["seq"],))
        db.execute("UPDATE _tt_points SET state='rewound' WHERE ts >= ? AND state='live'", (p["ts"],))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("UPDATE _tt_state SET v='0' WHERE k='paused'")
        db.commit()
    from . import safeopen
    seen, _ = _files_of(home, _since(db, p["ts"], live_only=False))
    for path, f in seen.items():
        if f.get("skipped"):
            continue
        # read before anything moves: a blob that fails its check leaves the file where it is
        data = _read_blob(home, f["blob"]) if f.get("existed") and f.get("blob") else None
        cur = Path(path)
        if cur.exists():
            rel = str(cur).lstrip("/")
            dest = aside / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(cur), str(dest))
            moved.append(str(dest))
        if data is not None:
            safeopen.write_bytes(path, data)
    return {**pl, "aside": str(aside) if moved else "", "moved": moved}


def fork_history(db, messages: list[dict], pid: str) -> dict:
    """What a fork from checkpoint `pid` starts with: the conversation before the turn the
    step belonged to, the question that started that turn, and the steps of it that had
    already run (so the new brain carries on from there rather than starting over)."""
    p = get(db, pid)
    if not p:
        raise KeyError(pid)
    before = [m for m in messages if (m.get("created_at") or 0) < p["ts"]]
    ask_i = max((i for i, m in enumerate(before) if m.get("role") == "user"), default=-1)
    if ask_i < 0:
        raise ValueError("that step has no question before it to fork from")
    done = [x for x in points(db, conversation_id=p["conversation_id"], limit=KEEP_POINTS)
            if before[ask_i].get("created_at", 0) <= x["ts"] < p["ts"]]
    return {"history": before[:ask_i], "ask": before[ask_i].get("content") or "",
            "already": [f"{x['tool']}: {x['detail']}" for x in done]}


def prune(db, home: Path, now: float | None = None) -> int:
    """Keep KEEP_DAYS and at most KEEP_POINTS; drop the journal rows older than the oldest
    point kept, and the blobs nothing points at any more."""
    now = now or _now()
    cut = now - KEEP_DAYS * 86400
    n = db.execute("SELECT COUNT(*) FROM _tt_points").fetchone()[0]
    if n > KEEP_POINTS:
        row = db.execute("SELECT ts FROM _tt_points ORDER BY ts DESC LIMIT 1 OFFSET ?", (KEEP_POINTS - 1,)).fetchone()
        cut = max(cut, row[0])
    gone = db.execute("DELETE FROM _tt_points WHERE ts < ?", (cut,)).rowcount
    oldest = db.execute("SELECT MIN(seq) FROM _tt_points").fetchone()[0]
    if oldest is None:
        db.execute("DELETE FROM _tt_undo WHERE ts < ?", (cut,))
    else:
        db.execute("DELETE FROM _tt_undo WHERE seq <= ? AND ts < ?", (oldest, cut))
    db.commit()
    keep = set()
    for (files,) in db.execute("SELECT files FROM _tt_points"):
        for f in json.loads(files or "[]"):
            if f.get("blob"):
                keep.add(f["blob"])
    root = home_dir(home) / "blobs"
    if root.is_dir():
        for b in root.rglob("*"):
            if b.is_file() and b.name not in keep:
                b.unlink(missing_ok=True)
    return gone


def text(db, conversation_id: str = "", limit: int = 30) -> str:
    rows = points(db, conversation_id, limit)
    if not rows:
        return "No checkpoints yet. One is kept before each step that changes a file, the memory or the graph."
    out = []
    for x in rows:
        when = time.strftime("%H:%M:%S", time.localtime(x["ts"]))
        flag = " (shell: not undoable)" if x["unseen"] else ""
        files = f" · {len(x['files'])} file" + ("s" if len(x["files"]) != 1 else "") if x["files"] else ""
        state = "" if x["state"] == "live" else " [rewound]"
        out.append(f"  {x['id']}  {when}  {x['tool']:<12} {x['detail'][:60]}{files}{flag}{state}")
    return "\n".join(out)
