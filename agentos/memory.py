"""SQLite persistence: conversations, messages, long-term memories, scheduled tasks."""

import json
import sqlite3
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    role TEXT,
    content TEXT,
    meta TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS logs (
    id TEXT PRIMARY KEY,
    kind TEXT,                   -- turn | tool | approval | task | telegram | mcp | error | system
    message TEXT,
    meta TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(created_at);
CREATE TABLE IF NOT EXISTS kg_nodes (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    type TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS kg_edges (
    id TEXT PRIMARY KEY,
    src TEXT,
    dst TEXT,
    relation TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS user_apps (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    icon TEXT,
    description TEXT,
    html TEXT,
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS telegram_chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    username TEXT,
    type TEXT,                   -- private | group | supergroup | channel
    allowed INTEGER DEFAULT 0,
    conversation_id TEXT,
    msg_count INTEGER DEFAULT 0,
    first_seen REAL,
    last_seen REAL
);
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    description TEXT,
    content TEXT,
    source TEXT,                 -- '' for hand-written, else the git/URL origin
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    prompt TEXT,
    schedule_type TEXT,          -- 'once' | 'interval' | 'daily'
    interval_seconds INTEGER,    -- for 'interval'
    at_time TEXT,                -- 'HH:MM' for 'daily'
    next_run REAL,
    last_run REAL,
    last_result TEXT,
    enabled INTEGER DEFAULT 1,
    created_at REAL
);
"""


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # -- conversations ------------------------------------------------------

    def create_conversation(self, title: str = "New chat") -> str:
        cid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (cid, title, now, now),
        )
        self.db.commit()
        return cid

    def touch_conversation(self, cid: str, title: str | None = None):
        if title:
            self.db.execute(
                "UPDATE conversations SET updated_at=?, title=? WHERE id=?",
                (time.time(), title, cid),
            )
        else:
            self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), cid))
        self.db.commit()

    def list_conversations(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_conversation(self, cid: str):
        self.db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        self.db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        self.db.commit()

    # -- messages -----------------------------------------------------------

    def add_message(self, cid: str, role: str, content: str, meta: dict | None = None) -> str:
        mid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, meta, created_at) VALUES (?,?,?,?,?,?)",
            (mid, cid, role, content, json.dumps(meta or {}), time.time()),
        )
        self.db.commit()
        return mid

    def get_messages(self, cid: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (cid,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta"] = json.loads(d.get("meta") or "{}")
            out.append(d)
        return out

    # -- long-term memory ---------------------------------------------------

    def add_memory(self, content: str) -> str:
        mid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO memories (id, content, created_at) VALUES (?,?,?)",
            (mid, content, time.time()),
        )
        self.db.commit()
        return mid

    def search_memories(self, query: str = "", limit: int = 20) -> list[dict]:
        if query:
            words = [w for w in query.split() if w]
            clause = " OR ".join("content LIKE ?" for _ in words)
            params = [f"%{w}%" for w in words]
            rows = self.db.execute(
                f"SELECT * FROM memories WHERE {clause} ORDER BY created_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_memory(self, mid: str):
        self.db.execute("DELETE FROM memories WHERE id=?", (mid,))
        self.db.commit()

    def clear_messages(self, cid: str):
        self.db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        self.db.commit()

    # -- logs ----------------------------------------------------------------

    def log(self, kind: str, message: str, meta: dict | None = None):
        self.db.execute(
            "INSERT INTO logs (id, kind, message, meta, created_at) VALUES (?,?,?,?,?)",
            (uuid.uuid4().hex[:12], kind, message[:2000], json.dumps(meta or {})[:4000], time.time()),
        )
        self.db.commit()

    def list_logs(self, kind: str = "", limit: int = 300) -> list[dict]:
        if kind:
            rows = self.db.execute(
                "SELECT * FROM logs WHERE kind=? ORDER BY created_at DESC LIMIT ?", (kind, limit)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_logs(self):
        self.db.execute("DELETE FROM logs")
        self.db.commit()

    # -- knowledge graph ------------------------------------------------------

    def _kg_node(self, name: str, ntype: str = "") -> str:
        name = name.strip()
        row = self.db.execute("SELECT id, type FROM kg_nodes WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if row:
            if ntype and not row["type"]:
                self.db.execute("UPDATE kg_nodes SET type=? WHERE id=?", (ntype, row["id"]))
            return row["id"]
        nid = uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO kg_nodes (id, name, type, created_at) VALUES (?,?,?,?)",
                        (nid, name, ntype, time.time()))
        self.db.commit()
        return nid

    def kg_add(self, subject: str, relation: str, obj: str,
               subject_type: str = "", object_type: str = "") -> str:
        src = self._kg_node(subject, subject_type)
        dst = self._kg_node(obj, object_type)
        row = self.db.execute(
            "SELECT id FROM kg_edges WHERE src=? AND dst=? AND relation=? COLLATE NOCASE",
            (src, dst, relation.strip())).fetchone()
        if row:
            return row["id"]
        eid = uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO kg_edges (id, src, dst, relation, created_at) VALUES (?,?,?,?,?)",
                        (eid, src, dst, relation.strip(), time.time()))
        self.db.commit()
        return eid

    def kg_graph(self) -> dict:
        nodes = [dict(r) for r in self.db.execute("SELECT * FROM kg_nodes").fetchall()]
        edges = [dict(r) for r in self.db.execute("SELECT * FROM kg_edges").fetchall()]
        return {"nodes": nodes, "edges": edges}

    def kg_query(self, query: str, limit: int = 40) -> list[str]:
        """Return 'subject —relation→ object' lines whose endpoints or relation match the query words."""
        g = self.kg_graph()
        byid = {n["id"]: n for n in g["nodes"]}
        words = [w.lower() for w in query.split() if w]
        out = []
        for e in g["edges"]:
            s = byid.get(e["src"], {}).get("name", "?")
            o = byid.get(e["dst"], {}).get("name", "?")
            line = f"{s} —{e['relation']}→ {o}"
            if not words or any(w in line.lower() for w in words):
                out.append(line)
        return out[:limit]

    def kg_delete_node(self, nid: str):
        self.db.execute("DELETE FROM kg_edges WHERE src=? OR dst=?", (nid, nid))
        self.db.execute("DELETE FROM kg_nodes WHERE id=?", (nid,))
        self.db.commit()

    def kg_clear(self):
        self.db.execute("DELETE FROM kg_edges")
        self.db.execute("DELETE FROM kg_nodes")
        self.db.commit()

    # -- user apps (AI-built UI tools) ------------------------------------------

    def save_app(self, name: str, icon: str, description: str, html: str) -> str:
        name = name.strip()
        now = time.time()
        row = self.db.execute("SELECT id FROM user_apps WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if row:
            self.db.execute("UPDATE user_apps SET icon=?, description=?, html=?, updated_at=? WHERE id=?",
                            (icon, description, html, now, row["id"]))
            self.db.commit()
            return row["id"]
        aid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO user_apps (id, name, icon, description, html, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)", (aid, name, icon or "🧰", description, html, now, now))
        self.db.commit()
        return aid

    def list_apps(self, with_html: bool = False) -> list[dict]:
        rows = self.db.execute("SELECT * FROM user_apps ORDER BY name COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if not with_html:
                d.pop("html", None)
            out.append(d)
        return out

    def get_app(self, aid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM user_apps WHERE id=?", (aid,)).fetchone()
        return dict(row) if row else None

    def delete_app(self, aid: str):
        self.db.execute("DELETE FROM user_apps WHERE id=?", (aid,))
        self.db.commit()

    # -- telegram chats --------------------------------------------------------

    def tg_upsert_chat(self, chat_id: int, title: str, username: str, ctype: str) -> dict:
        now = time.time()
        row = self.db.execute("SELECT * FROM telegram_chats WHERE chat_id=?", (chat_id,)).fetchone()
        if row:
            self.db.execute(
                "UPDATE telegram_chats SET title=?, username=?, type=?, msg_count=msg_count+1, last_seen=? "
                "WHERE chat_id=?", (title, username, ctype, now, chat_id))
        else:
            self.db.execute(
                "INSERT INTO telegram_chats (chat_id, title, username, type, allowed, msg_count, first_seen, last_seen) "
                "VALUES (?,?,?,?,0,1,?,?)", (chat_id, title, username, ctype, now, now))
        self.db.commit()
        return dict(self.db.execute("SELECT * FROM telegram_chats WHERE chat_id=?", (chat_id,)).fetchone())

    def tg_list_chats(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM telegram_chats ORDER BY last_seen DESC").fetchall()
        return [dict(r) for r in rows]

    def tg_set_allowed(self, chat_id: int, allowed: int):
        self.db.execute("UPDATE telegram_chats SET allowed=? WHERE chat_id=?", (allowed, chat_id))
        self.db.commit()

    def tg_set_conversation(self, chat_id: int, cid: str):
        self.db.execute("UPDATE telegram_chats SET conversation_id=? WHERE chat_id=?", (cid, chat_id))
        self.db.commit()

    def tg_delete_chat(self, chat_id: int):
        self.db.execute("DELETE FROM telegram_chats WHERE chat_id=?", (chat_id,))
        self.db.commit()

    # -- skills ---------------------------------------------------------------

    def save_skill(self, name: str, description: str, content: str, source: str = "") -> str:
        name = name.strip()
        now = time.time()
        row = self.db.execute("SELECT id FROM skills WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if row:
            self.db.execute(
                "UPDATE skills SET description=?, content=?, source=?, updated_at=? WHERE id=?",
                (description, content, source, now, row["id"]))
            self.db.commit()
            return row["id"]
        sid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO skills (id, name, description, content, source, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)", (sid, name, description, content, source, now, now))
        self.db.commit()
        return sid

    def list_skills(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM skills ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def get_skill(self, name: str) -> dict | None:
        row = self.db.execute("SELECT * FROM skills WHERE name=? COLLATE NOCASE", (name.strip(),)).fetchone()
        return dict(row) if row else None

    def delete_skill(self, sid: str):
        self.db.execute("DELETE FROM skills WHERE id=?", (sid,))
        self.db.commit()

    # -- scheduled tasks ----------------------------------------------------

    def add_task(self, prompt: str, schedule_type: str, interval_seconds: int | None,
                 at_time: str | None, next_run: float) -> str:
        tid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO tasks (id, prompt, schedule_type, interval_seconds, at_time, next_run, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (tid, prompt, schedule_type, interval_seconds, at_time, next_run, time.time()),
        )
        self.db.commit()
        return tid

    def list_tasks(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def due_tasks(self, now: float) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM tasks WHERE enabled=1 AND next_run IS NOT NULL AND next_run<=?", (now,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_task(self, tid: str, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), tid))
        self.db.commit()

    def delete_task(self, tid: str):
        self.db.execute("DELETE FROM tasks WHERE id=?", (tid,))
        self.db.commit()
