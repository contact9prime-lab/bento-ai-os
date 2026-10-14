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

Four rules keep it safe:

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

import hashlib
import json
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


# ---- the journal -----------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS _tt_undo (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  tbl TEXT NOT NULL, op TEXT NOT NULL, rid INTEGER NOT NULL, old TEXT);
CREATE TABLE IF NOT EXISTS _tt_points (id TEXT PRIMARY KEY, ts REAL NOT NULL, seq INTEGER NOT NULL,
  conversation_id TEXT DEFAULT '', run_id TEXT DEFAULT '', step INTEGER DEFAULT 0, tool TEXT DEFAULT '',
  detail TEXT DEFAULT '', files TEXT DEFAULT '[]', unseen INTEGER DEFAULT 0, state TEXT DEFAULT 'live');
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
    return (home_dir(home) / "blobs" / h[:2] / h).read_bytes()


def capture(home: Path, path: Path) -> dict:
    """The file as it is now: its bytes kept by content, or the fact it was not there."""
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "existed": False}
    if not path.is_file():
        return {"path": str(path), "existed": True, "skipped": "not a file"}
    size = path.stat().st_size
    if size > FILE_CAP:
        return {"path": str(path), "existed": True, "skipped": f"over {FILE_CAP // (1024 * 1024)} MB", "size": size}
    return {"path": str(path), "existed": True, "blob": _blob(home, path.read_bytes()), "size": size}


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
    db.execute("INSERT INTO _tt_points(id, ts, seq, conversation_id, run_id, step, tool, detail, files, unseen, state)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (pid, row["ts"], row["seq"], row["conversation_id"], row["run_id"], row["step"], tool,
                row["detail"], json.dumps(caps), row["unseen"], "live"))
    db.commit()
    return row


def _point(r) -> dict:
    d = dict(r)
    d["files"] = json.loads(d.get("files") or "[]")
    return d


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
    return [_point(r) for r in db.execute(q, args)][::-1]


def get(db, pid: str) -> dict | None:
    r = db.execute("SELECT * FROM _tt_points WHERE id=?", (pid,)).fetchone()
    return _point(r) if r else None


# ---- what going back would undo ------------------------------------------------------

_LABEL = {"memories": "memory", "kg_nodes": "graph entity", "kg_edges": "graph fact", "skills": "skill"}


def plan(db, home: Path, pid: str) -> dict:
    """Going back to just before checkpoint `pid`: every row change since it, every file
    a later step changed (with the earliest copy, which is how it was then), and the steps
    whose changes cannot be undone. The scrubber shows this; `rewind` does exactly this."""
    p = get(db, pid)
    if not p:
        raise KeyError(pid)
    later = [x for x in points(db, limit=KEEP_POINTS * 2, live_only=True) if x["ts"] >= p["ts"]]
    rows = db.execute("SELECT seq, tbl, op FROM _tt_undo WHERE seq > ? ORDER BY seq", (p["seq"],)).fetchall()
    counts: dict[str, dict] = {}
    for _, tbl, op in rows:
        c = counts.setdefault(tbl, {"added": 0, "changed": 0, "removed": 0})
        c[{"i": "added", "u": "changed", "d": "removed"}[op]] += 1
    files: dict[str, dict] = {}
    for x in later:
        for f in x["files"]:
            files.setdefault(f["path"], f)       # the earliest copy is the state back then
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
            "skipped": [{"path": f["path"], "why": f["skipped"]} for f in skipped],
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
    later = [x for x in points(db, limit=KEEP_POINTS * 2) if x["ts"] >= p["ts"]]
    seen: dict[str, dict] = {}
    for x in later:
        for f in x["files"]:
            seen.setdefault(f["path"], f)
    for path, f in seen.items():
        if f.get("skipped"):
            continue
        cur = Path(path)
        if cur.exists():
            rel = str(cur).lstrip("/")
            dest = aside / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(cur), str(dest))
            moved.append(str(dest))
        if f.get("existed") and f.get("blob"):
            cur.parent.mkdir(parents=True, exist_ok=True)
            cur.write_bytes(_read_blob(home, f["blob"]))
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
