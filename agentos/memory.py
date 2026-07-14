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
    updated_at REAL,
    rolled_up INTEGER DEFAULT 0  -- session memories already distilled into user memory
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
    scope TEXT DEFAULT 'user',   -- 'user' (durable, all conversations) | 'session' (one conversation)
    conversation_id TEXT,        -- set for scope='session'
    pinned INTEGER DEFAULT 0,    -- pinned memories are always injected first
    source TEXT DEFAULT '',      -- 'agent' | 'auto' | 'ui'
    embedding TEXT,              -- JSON float vector for semantic recall (NULL = not embedded yet)
    updated_at REAL,             -- bumped when edited or re-confirmed; drives recency ranking
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
CREATE TABLE IF NOT EXISTS app_data (
    app_id TEXT PRIMARY KEY,
    data TEXT,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS app_versions (
    id TEXT PRIMARY KEY,
    app_id TEXT,
    version INTEGER,             -- 1, 2, 3… per app
    html TEXT,
    note TEXT DEFAULT '',        -- what changed (builder prompt, "restored v2", …)
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_app_versions ON app_versions(app_id, version);
CREATE TABLE IF NOT EXISTS themes (
    name TEXT PRIMARY KEY,
    data TEXT,
    created_at REAL
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
CREATE TABLE IF NOT EXISTS subagents (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    soul TEXT,                   -- the subagent's own persona (never the parent's)
    model TEXT DEFAULT '',       -- '' = inherit the control plane's default_model
    tools TEXT DEFAULT '[]',     -- JSON allow-list; empty list = safe read-only defaults
    skills TEXT DEFAULT '[]',    -- JSON list of skill names shipped into its prompt
    autonomy_cap TEXT DEFAULT 'balanced',  -- effective autonomy = min(parent, cap)
    target TEXT DEFAULT 'local', -- local (L0) | subprocess | docker | node:<id>  (L1+ later)
    max_steps INTEGER DEFAULT 12,
    max_seconds INTEGER DEFAULT 300,
    builtin INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    description TEXT,
    steps TEXT,                  -- JSON DAG: [{id,name,subagent,model?,prompt,depends_on:[...]}]
    builtin INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS fabric_runs (
    id TEXT PRIMARY KEY,
    kind TEXT,                   -- 'delegate' | 'workflow' | 'step'
    ref TEXT,                    -- subagent or workflow name
    parent_run TEXT,             -- for kind='step': the workflow run it belongs to
    status TEXT,                 -- running | ok | error | timeout | cancelled | denied
    input TEXT,
    output TEXT,
    fault TEXT,
    model TEXT DEFAULT '',       -- the model the control plane actually resolved
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    steps INTEGER DEFAULT 0,
    started_at REAL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS fabric_events (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    ts REAL,
    type TEXT,                   -- status | step | log | fault | heartbeat
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_fabric_events_run ON fabric_events(run_id, ts);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY,
    principal_kind TEXT,          -- app | subagent | workflow | user | system | '*'
    principal_id TEXT,            -- app id / subagent name / '' / '*'
    action TEXT,                  -- fnmatch: 'tool.use', 'mcp.use', 'app.data.*', '*'
    resource TEXT,                -- fnmatch: 'mcp:github/*', 'tool:run_command git *', '*'
    effect TEXT DEFAULT 'allow',  -- allow | deny (deny wins)
    source TEXT,                  -- manifest | user | legacy | auto
    note TEXT DEFAULT '',         -- human-readable reason shown in the Permissions app
    expires_at REAL,              -- NULL = never
    created_at REAL,
    revoked_at REAL               -- soft revoke: the row stays as an audit trail
);
CREATE INDEX IF NOT EXISTS idx_grants_principal ON grants(principal_kind, principal_id);
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
        # WAL + busy timeout: readers never block the writer, and a second process
        # (installer, doctor, a stray instance) can't turn writes into hard
        # "database is locked" errors that kill a turn mid-flight.
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()
        self.grants_version = 0  # bumped on every grant write so the PDP cache invalidates

    def _migrate(self):
        """Add columns introduced after the first release to existing databases."""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(memories)").fetchall()}
        for col, ddl in (("scope", "TEXT DEFAULT 'user'"),
                         ("conversation_id", "TEXT"),
                         ("pinned", "INTEGER DEFAULT 0"),
                         ("source", "TEXT DEFAULT ''"),
                         ("embedding", "TEXT"),
                         ("updated_at", "REAL")):
            if col not in cols:
                self.db.execute(f"ALTER TABLE memories ADD COLUMN {col} {ddl}")
        ccols = {r["name"] for r in self.db.execute("PRAGMA table_info(conversations)").fetchall()}
        if "rolled_up" not in ccols:
            self.db.execute("ALTER TABLE conversations ADD COLUMN rolled_up INTEGER DEFAULT 0")
        acols = {r["name"] for r in self.db.execute("PRAGMA table_info(user_apps)").fetchall()}
        for col, ddl in (("manifest", "TEXT DEFAULT ''"),            # JSON permission manifest
                         ("manifest_status", "TEXT DEFAULT 'none'")):  # none | proposed | approved
            if col not in acols:
                self.db.execute(f"ALTER TABLE user_apps ADD COLUMN {col} {ddl}")

    def factory_reset(self):
        """Wipe every table (profile, memory, apps, logs, fabric, …) but keep the schema.
        Used by the first-run wizard's 'start fresh' flow."""
        tables = [r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for t in tables:
            self.db.execute(f"DELETE FROM {t}")
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
        # new activity re-arms the session-memory rollup for this conversation
        if title:
            self.db.execute(
                "UPDATE conversations SET updated_at=?, rolled_up=0, title=? WHERE id=?",
                (time.time(), title, cid),
            )
        else:
            self.db.execute("UPDATE conversations SET updated_at=?, rolled_up=0 WHERE id=?",
                            (time.time(), cid))
        self.db.commit()

    def list_conversations(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_conversation(self, cid: str):
        self.db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        self.db.execute("DELETE FROM memories WHERE scope='session' AND conversation_id=?", (cid,))
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

    def add_memory(self, content: str, scope: str = "user",
                   conversation_id: str | None = None, source: str = "agent",
                   pinned: int = 0) -> str:
        content = (content or "").strip()
        if not content:
            return ""
        if scope not in ("user", "session"):
            scope = "user"
        if scope != "session":
            conversation_id = None
        # exact-duplicate guard (case-insensitive, same scope/conversation);
        # re-seeing a fact counts as confirmation, so refresh its recency
        row = self.db.execute(
            "SELECT id FROM memories WHERE lower(content)=lower(?) AND scope=? "
            "AND (conversation_id IS ? OR conversation_id=?)",
            (content, scope, conversation_id, conversation_id or "")).fetchone()
        if row:
            self.db.execute("UPDATE memories SET updated_at=? WHERE id=?", (time.time(), row["id"]))
            self.db.commit()
            return row["id"]
        mid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO memories (id, content, scope, conversation_id, pinned, source, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (mid, content, scope, conversation_id, pinned, source, now, now),
        )
        self.db.commit()
        return mid

    def search_memories(self, query: str = "", limit: int = 20, scope: str = "",
                        conversation_id: str = "") -> list[dict]:
        where, params = [], []
        if scope:
            where.append("scope=?")
            params.append(scope)
        if conversation_id:
            where.append("conversation_id=?")
            params.append(conversation_id)
        if query:
            words = [w for w in query.split() if w]
            where.append("(" + " OR ".join("content LIKE ?" for _ in words) + ")")
            params.extend(f"%{w}%" for w in words)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        rows = self.db.execute(
            f"SELECT * FROM memories {clause} "
            f"ORDER BY pinned DESC, COALESCE(updated_at, created_at) DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_memory(self, content: str, scope: str = "user") -> dict | None:
        """Exact (case-insensitive) content match — used to apply supersedes/retractions."""
        row = self.db.execute(
            "SELECT * FROM memories WHERE lower(content)=lower(?) AND scope=?",
            ((content or "").strip(), scope)).fetchone()
        return dict(row) if row else None

    def update_memory(self, mid: str, content: str | None = None,
                      pinned: int | None = None, scope: str | None = None):
        """Edit a memory in place. scope='user' also clears conversation_id (promote).
        A content change resets the embedding so semantic recall re-indexes it."""
        sets, params = [], []
        if content is not None:
            sets.append("content=?")
            params.append(content.strip())
            sets.append("embedding=NULL")
        if pinned is not None:
            sets.append("pinned=?")
            params.append(1 if pinned else 0)
        if scope in ("user", "session"):
            sets.append("scope=?")
            params.append(scope)
            if scope == "user":
                sets.append("conversation_id=NULL")
        if not sets:
            return
        sets.append("updated_at=?")
        params.append(time.time())
        self.db.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", (*params, mid))
        self.db.commit()

    def memories_missing_embedding(self, limit: int = 64) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, content FROM memories WHERE embedding IS NULL LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def set_memory_embedding(self, mid: str, vector_json: str):
        self.db.execute("UPDATE memories SET embedding=? WHERE id=?", (vector_json, mid))
        self.db.commit()

    def delete_memory(self, mid: str):
        self.db.execute("DELETE FROM memories WHERE id=?", (mid,))
        self.db.commit()

    def clear_messages(self, cid: str):
        self.db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        self.db.commit()

    # -- session rollup -------------------------------------------------------

    def rollup_candidates(self, idle_before: float) -> list[dict]:
        """Conversations idle since `idle_before` that still hold un-distilled session memories."""
        rows = self.db.execute(
            "SELECT c.* FROM conversations c WHERE COALESCE(c.rolled_up,0)=0 AND c.updated_at<? "
            "AND EXISTS (SELECT 1 FROM memories m WHERE m.scope='session' AND m.conversation_id=c.id)",
            (idle_before,)).fetchall()
        return [dict(r) for r in rows]

    def mark_rolled_up(self, cid: str):
        self.db.execute("UPDATE conversations SET rolled_up=1 WHERE id=?", (cid,))
        self.db.commit()

    # -- logs ----------------------------------------------------------------

    def log(self, kind: str, message: str, meta: dict | None = None):
        self.db.execute(
            "INSERT INTO logs (id, kind, message, meta, created_at) VALUES (?,?,?,?,?)",
            (uuid.uuid4().hex[:12], kind, message[:2000], json.dumps(meta or {})[:4000], time.time()),
        )
        self.db.commit()

    def list_logs(self, kind: str = "", limit: int = 300, q: str = "") -> list[dict]:
        sql, params = "SELECT * FROM logs WHERE 1=1", []
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if q:
            sql += " AND (message LIKE ? OR meta LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]
        rows = self.db.execute(sql + " ORDER BY created_at DESC LIMIT ?",
                               (*params, limit)).fetchall()
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

    def kg_merge_nodes(self, keep_name: str, merge_names: list[str]) -> int:
        """Merge duplicate entities: repoint every edge from the merged nodes onto the kept
        node, drop the merged nodes, then remove self-loops and duplicate edges. Returns the
        number of nodes merged away."""
        keep = self.db.execute(
            "SELECT id FROM kg_nodes WHERE name=? COLLATE NOCASE", (keep_name.strip(),)).fetchone()
        if not keep:
            return 0
        kid, merged = keep["id"], 0
        for name in merge_names:
            row = self.db.execute(
                "SELECT id FROM kg_nodes WHERE name=? COLLATE NOCASE", ((name or "").strip(),)).fetchone()
            if not row or row["id"] == kid:
                continue
            self.db.execute("UPDATE kg_edges SET src=? WHERE src=?", (kid, row["id"]))
            self.db.execute("UPDATE kg_edges SET dst=? WHERE dst=?", (kid, row["id"]))
            self.db.execute("DELETE FROM kg_nodes WHERE id=?", (row["id"],))
            merged += 1
        if merged:
            self.db.execute("DELETE FROM kg_edges WHERE src=? AND dst=?", (kid, kid))
            self.db.execute(
                "DELETE FROM kg_edges WHERE id NOT IN "
                "(SELECT MIN(id) FROM kg_edges GROUP BY src, dst, lower(relation))")
        self.db.commit()
        return merged

    def kg_delete_node(self, nid: str):
        self.db.execute("DELETE FROM kg_edges WHERE src=? OR dst=?", (nid, nid))
        self.db.execute("DELETE FROM kg_nodes WHERE id=?", (nid,))
        self.db.commit()

    def kg_clear(self):
        self.db.execute("DELETE FROM kg_edges")
        self.db.execute("DELETE FROM kg_nodes")
        self.db.commit()

    # -- user apps (AI-built UI tools) ------------------------------------------

    def save_app(self, name: str, icon: str, description: str, html: str,
                 note: str = "") -> str:
        name = name.strip()
        now = time.time()
        row = self.db.execute("SELECT id, html FROM user_apps WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if row:
            changed = (row["html"] or "") != html
            self.db.execute("UPDATE user_apps SET icon=?, description=?, html=?, updated_at=? WHERE id=?",
                            (icon, description, html, now, row["id"]))
            if changed:
                self._record_app_version(row["id"], html, note)
            self.db.commit()
            return row["id"]
        aid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO user_apps (id, name, icon, description, html, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)", (aid, name, icon or "", description, html, now, now))
        self._record_app_version(aid, html, note or "initial version")
        self.db.commit()
        return aid

    def set_app_manifest(self, aid: str, manifest: str, status: str):
        """status: none | proposed (awaiting user review) | approved (grants written)."""
        self.db.execute("UPDATE user_apps SET manifest=?, manifest_status=? WHERE id=?",
                        (manifest, status, aid))
        self.db.commit()

    # -- app versions (every save with changed html = a new restorable version) --

    def _record_app_version(self, aid: str, html: str, note: str = ""):
        last = self.db.execute(
            "SELECT MAX(version) v FROM app_versions WHERE app_id=?", (aid,)).fetchone()
        self.db.execute(
            "INSERT INTO app_versions (id, app_id, version, html, note, created_at) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex[:12], aid, (last["v"] or 0) + 1, html, note[:300], time.time()))
        # keep history bounded: the newest 30 versions per app
        self.db.execute(
            "DELETE FROM app_versions WHERE app_id=? AND version <= "
            "(SELECT MAX(version) FROM app_versions WHERE app_id=?) - 30", (aid, aid))

    def app_versions(self, aid: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, app_id, version, note, created_at, length(html) AS size "
            "FROM app_versions WHERE app_id=? ORDER BY version DESC", (aid,)).fetchall()
        return [dict(r) for r in rows]

    def get_app_version(self, aid: str, version: int) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM app_versions WHERE app_id=? AND version=?", (aid, version)).fetchone()
        return dict(row) if row else None

    def restore_app_version(self, aid: str, version: int) -> bool:
        v = self.get_app_version(aid, version)
        app = self.get_app(aid)
        if not v or not app:
            return False
        self.save_app(app["name"], app["icon"], app["description"], v["html"],
                      note=f"restored v{version}")
        return True

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
        self.db.execute("DELETE FROM app_data WHERE app_id=?", (aid,))
        self.db.execute("DELETE FROM app_versions WHERE app_id=?", (aid,))
        cur = self.db.execute(
            "UPDATE grants SET revoked_at=? WHERE principal_kind='app' AND principal_id=? "
            "AND revoked_at IS NULL", (time.time(), aid))
        self.db.commit()
        if cur.rowcount:
            self.grants_version += 1

    # -- themes ---------------------------------------------------------------

    def save_theme(self, name: str, data: str):
        self.db.execute(
            "INSERT INTO themes (name, data, created_at) VALUES (?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET data=excluded.data",
            (name.strip(), data, time.time()))
        self.db.commit()

    def list_themes(self) -> list[dict]:
        rows = self.db.execute("SELECT name, data FROM themes ORDER BY name COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            try:
                d = json.loads(r["data"])
            except Exception:
                d = {}
            d["name"] = r["name"]
            out.append(d)
        return out

    def delete_theme(self, name: str):
        self.db.execute("DELETE FROM themes WHERE name=?", (name,))
        self.db.commit()

    def get_app_data(self, aid: str) -> str:
        row = self.db.execute("SELECT data FROM app_data WHERE app_id=?", (aid,)).fetchone()
        return row["data"] if row else "{}"

    def set_app_data(self, aid: str, data: str):
        self.db.execute(
            "INSERT INTO app_data (app_id, data, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(app_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (aid, data, time.time()))
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

    # -- grants (the permission framework's single source of truth) ----------

    def add_grant(self, principal_kind: str, principal_id: str, action: str, resource: str,
                  effect: str = "allow", source: str = "user", note: str = "",
                  expires_at: float | None = None) -> str:
        """Write one consent rule. Identical live rules dedupe to the existing row."""
        row = self.db.execute(
            "SELECT id FROM grants WHERE principal_kind=? AND principal_id=? AND action=? "
            "AND resource=? AND effect=? AND revoked_at IS NULL",
            (principal_kind, principal_id, action, resource, effect)).fetchone()
        if row:
            return row["id"]
        gid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO grants (id, principal_kind, principal_id, action, resource, effect, "
            "source, note, expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (gid, principal_kind, principal_id, action, resource, effect,
             source, note[:300], expires_at, time.time()))
        self.db.commit()
        self.grants_version += 1
        return gid

    def grants_live(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM grants WHERE revoked_at IS NULL "
                               "ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def list_grants(self, principal_kind: str = "", principal_id: str = "",
                    include_revoked: bool = False) -> list[dict]:
        q, params = "SELECT * FROM grants WHERE 1=1", []
        if not include_revoked:
            q += " AND revoked_at IS NULL"
        if principal_kind:
            q += " AND principal_kind=?"
            params.append(principal_kind)
        if principal_id:
            q += " AND principal_id=?"
            params.append(principal_id)
        rows = self.db.execute(q + " ORDER BY principal_kind, principal_id, created_at",
                               params).fetchall()
        return [dict(r) for r in rows]

    def update_grant(self, gid: str, effect: str) -> bool:
        """Flip a live grant between allow and deny (the Permissions map toggle)."""
        if effect not in ("allow", "deny"):
            return False
        cur = self.db.execute("UPDATE grants SET effect=? WHERE id=? AND revoked_at IS NULL",
                              (effect, gid))
        self.db.commit()
        if cur.rowcount:
            self.grants_version += 1
        return bool(cur.rowcount)

    def revoke_grant(self, gid: str) -> bool:
        cur = self.db.execute("UPDATE grants SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                              (time.time(), gid))
        self.db.commit()
        if cur.rowcount:
            self.grants_version += 1
        return bool(cur.rowcount)

    def revoke_grants_for(self, principal_kind: str, principal_id: str, source: str = "") -> int:
        """Revoke every live grant of one principal (optionally only one source),
        e.g. swapping an app's legacy full-access grant for its approved manifest."""
        q, params = ("UPDATE grants SET revoked_at=? WHERE principal_kind=? AND principal_id=? "
                     "AND revoked_at IS NULL"), [time.time(), principal_kind, principal_id]
        if source:
            q += " AND source=?"
            params.append(source)
        cur = self.db.execute(q, params)
        self.db.commit()
        if cur.rowcount:
            self.grants_version += 1
        return cur.rowcount

    # -- fabric: subagents, workflows, runs (control-plane state) ------------

    def save_subagent(self, d: dict) -> str:
        name = (d.get("name") or "").strip()
        now = time.time()
        row = self.db.execute("SELECT id FROM subagents WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        sid = row["id"] if row else uuid.uuid4().hex[:12]
        vals = (name, d.get("soul", ""), d.get("model", ""),
                json.dumps(d.get("tools") or []), json.dumps(d.get("skills") or []),
                d.get("autonomy_cap", "balanced"), d.get("target", "local"),
                int(d.get("max_steps", 12)), int(d.get("max_seconds", 300)),
                int(d.get("builtin", 0)), now)
        if row:
            self.db.execute(
                "UPDATE subagents SET name=?, soul=?, model=?, tools=?, skills=?, autonomy_cap=?, "
                "target=?, max_steps=?, max_seconds=?, builtin=?, updated_at=? WHERE id=?", (*vals, sid))
        else:
            self.db.execute(
                "INSERT INTO subagents (name, soul, model, tools, skills, autonomy_cap, target, "
                "max_steps, max_seconds, builtin, updated_at, id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*vals, sid, now))
        self.db.commit()
        return sid

    @staticmethod
    def _subagent_row(r) -> dict:
        d = dict(r)
        d["tools"] = json.loads(d.get("tools") or "[]")
        d["skills"] = json.loads(d.get("skills") or "[]")
        return d

    def list_subagents(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM subagents ORDER BY name COLLATE NOCASE").fetchall()
        return [self._subagent_row(r) for r in rows]

    def get_subagent(self, name: str) -> dict | None:
        row = self.db.execute("SELECT * FROM subagents WHERE name=? COLLATE NOCASE",
                              ((name or "").strip(),)).fetchone()
        return self._subagent_row(row) if row else None

    def delete_subagent(self, sid: str):
        self.db.execute("DELETE FROM subagents WHERE id=?", (sid,))
        self.db.commit()

    def save_workflow(self, d: dict) -> str:
        name = (d.get("name") or "").strip()
        now = time.time()
        row = self.db.execute("SELECT id FROM workflows WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        wid = row["id"] if row else uuid.uuid4().hex[:12]
        vals = (name, d.get("description", ""), json.dumps(d.get("steps") or []),
                int(d.get("builtin", 0)), now)
        if row:
            self.db.execute("UPDATE workflows SET name=?, description=?, steps=?, builtin=?, "
                            "updated_at=? WHERE id=?", (*vals, wid))
        else:
            self.db.execute("INSERT INTO workflows (name, description, steps, builtin, updated_at, "
                            "id, created_at) VALUES (?,?,?,?,?,?,?)", (*vals, wid, now))
        self.db.commit()
        return wid

    def list_workflows(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM workflows ORDER BY name COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["steps"] = json.loads(d.get("steps") or "[]")
            out.append(d)
        return out

    def get_workflow(self, name: str) -> dict | None:
        row = self.db.execute("SELECT * FROM workflows WHERE name=? COLLATE NOCASE",
                              ((name or "").strip(),)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["steps"] = json.loads(d.get("steps") or "[]")
        return d

    def delete_workflow(self, wid: str):
        self.db.execute("DELETE FROM workflows WHERE id=?", (wid,))
        self.db.commit()

    def fabric_run_start(self, kind: str, ref: str, input_text: str,
                         parent_run: str = "", model: str = "") -> str:
        rid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO fabric_runs (id, kind, ref, parent_run, status, input, model, started_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (rid, kind, ref, parent_run, "running", input_text[:4000], model, time.time()))
        self.db.commit()
        return rid

    def fabric_run_finish(self, rid: str, status: str, output: str = "", fault: str = "",
                          tokens_in: int = 0, tokens_out: int = 0, steps: int = 0):
        self.db.execute(
            "UPDATE fabric_runs SET status=?, output=?, fault=?, tokens_in=?, tokens_out=?, "
            "steps=?, finished_at=? WHERE id=?",
            (status, output[:8000], fault[:2000], tokens_in, tokens_out, steps, time.time(), rid))
        self.db.commit()

    def fabric_runs(self, limit: int = 100, parent_run: str = "") -> list[dict]:
        if parent_run:
            rows = self.db.execute("SELECT * FROM fabric_runs WHERE parent_run=? "
                                   "ORDER BY started_at", (parent_run,)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM fabric_runs WHERE kind!='step' "
                                   "ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def fabric_run(self, rid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM fabric_runs WHERE id=?", (rid,)).fetchone()
        return dict(row) if row else None

    def fabric_event(self, run_id: str, etype: str, payload: dict | None = None):
        self.db.execute(
            "INSERT INTO fabric_events (id, run_id, ts, type, payload) VALUES (?,?,?,?,?)",
            (uuid.uuid4().hex[:12], run_id, time.time(), etype,
             json.dumps(payload or {})[:4000]))
        self.db.commit()

    def fabric_events_for(self, run_id: str, limit: int = 500) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM fabric_events WHERE run_id=? ORDER BY ts LIMIT ?",
            (run_id, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except Exception:
                d["payload"] = {}
            out.append(d)
        return out

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
