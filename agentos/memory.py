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
    rolled_up INTEGER DEFAULT 0, -- session memories already distilled into user memory
    origin TEXT DEFAULT 'user',  -- who started it: user | schedule | trigger | briefing | suggestion
    space_id TEXT DEFAULT '',    -- the space this conversation belongs to ('' = global)
    summary TEXT DEFAULT '',     -- rolling summary of the turns that no longer fit (history.py)
    summary_upto TEXT DEFAULT '',-- id of the last message the summary covers
    summary_msgs INTEGER DEFAULT 0
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
    space_id TEXT DEFAULT '',    -- '' = true everywhere; else true inside one space
    updated_at REAL,             -- bumped when edited or re-confirmed; drives recency ranking
    created_at REAL
);
CREATE TABLE IF NOT EXISTS logs (
    id TEXT PRIMARY KEY,
    kind TEXT,                   -- turn | tool | approval | task | telegram | mcp | error | system
    message TEXT,
    meta TEXT,
    conversation_id TEXT DEFAULT '',  -- was buried in meta JSON, so unfilterable
    space_id TEXT DEFAULT '',
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(created_at);
CREATE TABLE IF NOT EXISTS kg_nodes (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    type TEXT,
    created_at REAL
);
-- The graph is scoped on its EDGES, never on its nodes. A node is an entity and
-- an entity is the same entity everywhere: the person "Ana" does not become a
-- different person because you switched to the launch space. An edge is an
-- ASSERTION, and assertions are what belong to a project — "Ana reviews the
-- launch copy" is true here and nowhere else.
--
-- This also keeps the migration non-destructive: kg_nodes.name is UNIQUE, and
-- making it unique-per-space would mean rebuilding the table.
CREATE TABLE IF NOT EXISTS kg_edges (
    id TEXT PRIMARY KEY,
    src TEXT,
    dst TEXT,
    relation TEXT,
    space_id TEXT DEFAULT '',
    created_at REAL
);
-- (its indexes are created in _migrate, after space_id is guaranteed to exist)
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
-- WhatsApp chats paired to this machine. Separate from telegram_chats rather than a
-- shared "channel_chats" table because the keys are genuinely different kinds: a
-- Telegram chat_id is an integer Telegram owns, a wa_id is an E.164 phone number.
-- `last_inbound` is the one column with real behaviour behind it: Meta refuses
-- free-form messages more than 24 hours after it, so this is what `window_open`
-- reads before promising a delivery it cannot make.
CREATE TABLE IF NOT EXISTS whatsapp_chats (
    wa_id TEXT PRIMARY KEY,      -- E.164 without '+', as Meta sends it
    name TEXT,                   -- WhatsApp profile name, as given
    allowed INTEGER DEFAULT 0,
    conversation_id TEXT,
    msg_count INTEGER DEFAULT 0,
    last_inbound REAL,           -- the 24-hour customer-service window starts here
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
-- A named, repeatable sequence of desktop steps. Unlike `workflows` (a DAG of
-- subagent steps in the fabric control plane) an automation drives the DESKTOP:
-- open these apps, switch to that theme, put the agent on this prompt. It is what
-- a hot corner, the palette, or "run my morning routine" fires.
CREATE TABLE IF NOT EXISTS automations (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    icon TEXT DEFAULT '',
    steps TEXT,                  -- JSON: [{kind:'app'|'action'|'theme'|'desktop'|'agent'|'wait', ...}]
    created_at REAL,
    updated_at REAL,
    last_run REAL,
    runs INTEGER DEFAULT 0
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
    space_id TEXT DEFAULT '',
    conversation_id TEXT DEFAULT '',
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
-- A FLOW is a standing mission with a master orchestrator in front of it. Unlike a
-- `workflow` (a DAG somebody drew ahead of time) a flow says only what it wants, who
-- it may ask, and what it may touch — the master picks the agents and the order while
-- it runs. That is why there are no steps here: the graph is a trace, not a plan.
CREATE TABLE IF NOT EXISTS flows (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    description TEXT DEFAULT '',
    mission TEXT,                      -- the brief the master orchestrator is given
    roster TEXT DEFAULT '[]',          -- JSON [{"subagent":"researcher","why":"…"}]
    model TEXT DEFAULT '',             -- the orchestrator's own model ('' = inherit)
    permissions TEXT DEFAULT '{}',     -- JSON declaration — materialised as grants on save
    sinks TEXT DEFAULT '[]',           -- JSON delivery sinks ([] = reply where it came from)
    autonomy_cap TEXT DEFAULT 'balanced',
    max_delegations INTEGER DEFAULT 12,
    max_steps INTEGER DEFAULT 24,
    max_seconds INTEGER DEFAULT 1800,  -- WORKING seconds: time spent waiting for you is free
    space_id TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    builtin INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL
);
-- What starts a flow. The declaration lives here; the CLOCK is still the `tasks`
-- table — cron and OS-event triggers materialise a real task row (task_id below) so
-- the scheduler's due-polling, claim-on-fire and cooldowns are reused rather than
-- reimplemented. Message and webhook triggers have no time dimension and get no row.
CREATE TABLE IF NOT EXISTS flow_triggers (
    id TEXT PRIMARY KEY,
    flow TEXT,                   -- flows.name
    kind TEXT,                   -- cron | message | webhook | os_event
    config TEXT DEFAULT '{}',    -- JSON, per kind
    task_id TEXT DEFAULT '',     -- cron/os_event: the tasks row that actually fires it
    secret TEXT DEFAULT '',      -- webhook only
    enabled INTEGER DEFAULT 1,
    cooldown_secs INTEGER DEFAULT 60,
    last_fired REAL,
    fires INTEGER DEFAULT 0,
    dropped INTEGER DEFAULT 0,   -- fires refused by the cooldown — shown, never silent
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_flow_triggers_kind ON flow_triggers(kind, enabled);
-- The blackboard: what a flow's agents actually produced, in full. `fabric_runs.output`
-- is a truncated summary for the runs list; this is the artefact the next agent is
-- handed. Handles ('a1', 'a2') are what the orchestrator says out loud, so they are
-- short and per-run, never global — a model cannot name another run's work because the
-- handle does not resolve outside the run whose tools it is holding.
CREATE TABLE IF NOT EXISTS flow_artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT,                 -- the orchestrator run (fabric_runs.id, kind='flow')
    handle TEXT,                 -- 'in1' | 'a1' | 'a2' … unique within run_id
    kind TEXT DEFAULT 'output',  -- input | output | note | error
    agent TEXT DEFAULT '',       -- subagent that produced it ('' = trigger input)
    child_run TEXT DEFAULT '',   -- fabric_runs.id of the producing child
    task TEXT DEFAULT '',        -- what that agent was asked for
    content TEXT,                -- FULL text. Never truncated here.
    preview TEXT DEFAULT '',     -- first ~240 chars; what the index shows
    bytes INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ok',
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    tainted INTEGER DEFAULT 0,   -- came from outside this machine (webhook, fetched page)
    deps TEXT DEFAULT '[]',      -- JSON handles fed in — these ARE the graph's data edges
    space_id TEXT DEFAULT '',
    created_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_flow_artifact_handle ON flow_artifacts(run_id, handle);
-- Things the OS stopped because they would not stop themselves.
--
-- One table for apps, subagents and flows alike: what went rogue is a property of the
-- PRINCIPAL, and putting a column on three tables would mean three places to forget.
-- A row here is a held thing plus the evidence for holding it, so the user is answering
-- "6 llm calls in 41s, here they are" rather than "something went wrong".
--
-- Release is a decision with three shapes and all of them are recorded: `once` lets it run
-- again and stays watching, `forever` stops it being held for this again (an exemption the
-- user made, which must be visible later), `deleted` means it is gone.
CREATE TABLE IF NOT EXISTS quarantine (
    id TEXT PRIMARY KEY,
    principal_kind TEXT,          -- app | subagent | flow
    principal_id TEXT,
    label TEXT DEFAULT '',        -- the human name at the time it was held
    reason TEXT,                  -- one sentence, shown to the user
    kind TEXT DEFAULT 'rate',     -- rate | llm | tool  — what class of call tripped it
    evidence TEXT DEFAULT '{}',   -- JSON: counts, window, the tools it was calling
    created_at REAL,
    released_at REAL,             -- NULL = still held
    release_mode TEXT DEFAULT '', -- once | forever | deleted
    released_by TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_quarantine_live
    ON quarantine(principal_kind, principal_id, released_at);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY,
    principal_kind TEXT,          -- app | subagent | workflow | user | system | '*'
    principal_id TEXT,            -- app id / subagent name / '' / '*'
    action TEXT,                  -- fnmatch: 'tool.use', 'mcp.use', 'app.data.*', '*'
    resource TEXT,                -- fnmatch: 'mcp:github/*', 'tool:run_command git *', '*'
    effect TEXT DEFAULT 'allow',  -- allow | deny (deny wins)
    source TEXT,                  -- manifest | user | legacy | auto
    note TEXT DEFAULT '',         -- human-readable reason shown in the Permissions app
    surfaces TEXT DEFAULT '*',    -- IO gates: '*' or csv of gui,tui,telegram,api,task —
                                  -- the grant only applies to calls arriving via these
    expires_at REAL,              -- NULL = never
    created_at REAL,
    revoked_at REAL               -- soft revoke: the row stays as an audit trail
);
CREATE INDEX IF NOT EXISTS idx_grants_principal ON grants(principal_kind, principal_id);
CREATE TABLE IF NOT EXISTS mcp_registry (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,             -- the local config key (cfg["mcp_servers"] entry)
    title TEXT,                   -- display name
    description TEXT,
    source TEXT,                  -- discovery | manual | package
    origin TEXT,                  -- public-registry id / URL the server came from
    package TEXT,                 -- JSON: how to run it (registry_type, identifier, transport…)
    homepage TEXT,
    status TEXT DEFAULT 'installed',  -- discovered | installed
    doc_file TEXT DEFAULT '',     -- generated doc, relative to the user docs dir
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    prompt TEXT,
    schedule_type TEXT,          -- 'once' | 'interval' | 'daily' | 'trigger'
    interval_seconds INTEGER,    -- for 'interval'
    at_time TEXT,                -- 'HH:MM' for 'daily'
    next_run REAL,               -- NULL for 'trigger' (event-driven, never time-due)
    last_run REAL,
    last_result TEXT,
    enabled INTEGER DEFAULT 1,
    created_at REAL,
    "trigger" TEXT DEFAULT '',   -- for 'trigger': notification | file_change | login | idle
    trigger_config TEXT DEFAULT '{}',  -- JSON: {match} | {path,glob} | {minutes}
    cooldown_secs INTEGER DEFAULT 300, -- a trigger fires at most once per cooldown
    last_fired REAL,
    space_id TEXT DEFAULT ''     -- the space a scheduled turn runs inside
);
CREATE TABLE IF NOT EXISTS proactive_items (
    id TEXT PRIMARY KEY,
    kind TEXT,                   -- 'digest' (notification triage) | 'suggestion' (knowledge loop)
    text TEXT,
    data TEXT,                   -- JSON: digest {top_ids} / suggestion {action_prompt}
    dismissed_at REAL,           -- NULL = still live
    created_at REAL
);
-- A space is a thing the user is working on: a launch, a client, a channel, a
-- side project. Conversations, assets, memories, KG assertions, runs and tasks
-- all belong to one — or to the GLOBAL scope, which is spelled '' everywhere.
--
-- '' is deliberately not NULL. Every read is `space_id IN ('', :active)`, and
-- three-valued logic in that clause is how this would rot: `space_id != 'x'` is
-- false for NULL, so one forgotten COALESCE silently hides every pre-existing
-- row. Rows written before spaces existed are global, which is the correct
-- reading of "we did not know about projects when this was recorded".
CREATE TABLE IF NOT EXISTS spaces (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    icon TEXT DEFAULT '',
    colour TEXT DEFAULT '',
    description TEXT DEFAULT '',  -- shown to the extraction model: what this space IS
    workspace TEXT DEFAULT '',    -- optional filesystem dir this space maps to
    archived INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL
);
-- The timeline is a materialised index of MILESTONES, not of messages. A
-- timeline containing every message is the message list, and the sources it
-- draws from (logs, fabric_runs, assets, app_versions) share no key and no
-- index — a five-way UNION view could never be ordered cheaply.
CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    space_id TEXT DEFAULT '',
    ts REAL,
    kind TEXT,                   -- run | asset | memory | app_version | conversation | task | space
    ref_table TEXT DEFAULT '',   -- where the full record lives
    ref_id TEXT DEFAULT '',
    title TEXT DEFAULT '',
    meta TEXT DEFAULT '{}',
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_timeline_space ON timeline_events(space_id, ts);
CREATE INDEX IF NOT EXISTS idx_timeline_kind ON timeline_events(kind, ts);
-- Everything the agent made or was given: generated images, video an MCP server
-- returned, uploads, rendered cuts, reports. Content-addressed, so storing the
-- same bytes twice costs one row and one file.
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    sha256 TEXT,                 -- content address; the file name on disk
    path TEXT,                   -- absolute, always under the assets root
    kind TEXT,                   -- image | video | audio | doc | data | other
    mime TEXT DEFAULT '',
    bytes INTEGER DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    duration REAL DEFAULT 0,     -- seconds; 0 = unknown (nothing probed it)
    title TEXT DEFAULT '',
    prompt TEXT DEFAULT '',      -- what was asked for, when this was generated
    source TEXT DEFAULT '',      -- mcp:<server>/<tool> | tool:<name> | upload | url
    origin_url TEXT DEFAULT '',
    conversation_id TEXT DEFAULT '',
    run_id TEXT DEFAULT '',      -- fabric_runs.id when a subagent made it
    space_id TEXT DEFAULT '',
    thumb TEXT DEFAULT '',       -- '' = nothing could make one; the UI says why
    meta TEXT DEFAULT '{}',
    created_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_sha ON assets(sha256);
CREATE INDEX IF NOT EXISTS idx_assets_time ON assets(created_at);
CREATE INDEX IF NOT EXISTS idx_assets_space ON assets(space_id, created_at);
CREATE INDEX IF NOT EXISTS idx_assets_conv ON assets(conversation_id);
CREATE INDEX IF NOT EXISTS idx_assets_run ON assets(run_id);
-- The access ledger. `logs` is the operator's diary — free text, one `kind`
-- column, meta as a JSON blob you have to grep. That is fine for "what happened"
-- and useless for "who was allowed to do what, on which way in, and why".
--
-- Every PDP decision writes exactly one row here, structured in the same
-- vocabulary grants are written in, so a question like "everything a subagent
-- was denied over Telegram last week" is an index scan rather than a grep
-- through JSON. Rows are never updated after the outcome is stamped.
CREATE TABLE IF NOT EXISTS audit (
    id TEXT PRIMARY KEY,
    ts REAL,
    principal_kind TEXT DEFAULT '',   -- user | app | subagent | workflow | system
    principal_id TEXT DEFAULT '',
    surface TEXT DEFAULT '',          -- the IO gate: gui | tui | telegram | api | task
    space_id TEXT DEFAULT '',
    conversation_id TEXT DEFAULT '',
    run_id TEXT DEFAULT '',
    action TEXT DEFAULT '',           -- tool.use | mcp.use | fs.write | media.generate | …
    resource TEXT DEFAULT '',         -- mcp:github/create_issue | fs:/home/… | media:image
    effect TEXT DEFAULT '',           -- allow | deny | ask
    rule TEXT DEFAULT '',             -- grant id | hard-block | builtin-deny | io-gate | default
    risk TEXT DEFAULT '',             -- safe | risky | blocked
    reason TEXT DEFAULT '',
    outcome TEXT DEFAULT '',          -- '' (decision only) | ok | error | denied | timeout
    detail TEXT DEFAULT '',           -- error text, or a short result note
    duration_ms INTEGER DEFAULT 0,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
CREATE INDEX IF NOT EXISTS idx_audit_principal ON audit(principal_kind, principal_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit(action, ts);
CREATE INDEX IF NOT EXISTS idx_audit_effect ON audit(effect, ts);
CREATE INDEX IF NOT EXISTS idx_audit_space ON audit(space_id, ts);
-- What each turn cost. Tokens are always known; money only when the model is
-- priced (see usage.py) — an unpriced row is honest about being unpriced rather
-- than reporting a confident zero.
CREATE TABLE IF NOT EXISTS usage (
    id TEXT PRIMARY KEY,
    ts REAL,
    model TEXT DEFAULT '',
    surface TEXT DEFAULT '',          -- gui | tui | telegram | api | task | copilot | omni
    principal TEXT DEFAULT 'user',
    conversation_id TEXT DEFAULT '',
    space_id TEXT DEFAULT '',
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd REAL,                    -- NULL = this model has no price configured
    kind TEXT DEFAULT 'chat'          -- chat | build | subagent | extract | eval
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
CREATE INDEX IF NOT EXISTS idx_usage_model ON usage(model, ts);
CREATE INDEX IF NOT EXISTS idx_usage_conv ON usage(conversation_id, ts);
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
        self.quarantine_version = 0  # ditto for holds — consulted on every capability call

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
        if "origin" not in ccols:  # who initiated it — the OS-initiative metric reads this
            self.db.execute("ALTER TABLE conversations ADD COLUMN origin TEXT DEFAULT 'user'")
        # the rolling summary of what no longer fits the context window (history.py)
        for col, ddl in (("summary", "TEXT DEFAULT ''"),
                         ("summary_upto", "TEXT DEFAULT ''"),   # last message id it covers
                         ("summary_msgs", "INTEGER DEFAULT 0")):
            if col not in ccols:
                self.db.execute(f"ALTER TABLE conversations ADD COLUMN {col} {ddl}")
        tcols = {r["name"] for r in self.db.execute("PRAGMA table_info(tasks)").fetchall()}
        for col, ddl in (('"trigger"', "TEXT DEFAULT ''"),
                         ("trigger_config", "TEXT DEFAULT '{}'"),
                         ("cooldown_secs", "INTEGER DEFAULT 300"),
                         ("last_fired", "REAL")):
            if col.strip('"') not in tcols:
                self.db.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
        acols = {r["name"] for r in self.db.execute("PRAGMA table_info(user_apps)").fetchall()}
        for col, ddl in (("suspended_at", "REAL"),                    # stopped for going rogue
                         ("suspended_reason", "TEXT DEFAULT ''"),
                         ("manifest", "TEXT DEFAULT ''"),            # JSON permission manifest
                         ("manifest_status", "TEXT DEFAULT 'none'"),   # none | proposed | approved
                         ("widget_size", "TEXT DEFAULT 'm'")):         # s | m | l — the app's widget mode
            if col not in acols:
                self.db.execute(f"ALTER TABLE user_apps ADD COLUMN {col} {ddl}")
        gcols = {r["name"] for r in self.db.execute("PRAGMA table_info(grants)").fetchall()}
        if "surfaces" not in gcols:  # IO gates: pre-surface grants apply everywhere
            self.db.execute("ALTER TABLE grants ADD COLUMN surfaces TEXT DEFAULT '*'")
        # Spaces. Purely additive: every existing row defaults to '' (global), so an
        # untouched install reads back exactly as it did before — every memory and
        # every fact stays visible from every space. Nothing is moved, nothing is
        # hidden, and no index is rebuilt.
        for table, columns in (
            ("memories", (("space_id", "TEXT DEFAULT ''"),)),
            ("kg_edges", (("space_id", "TEXT DEFAULT ''"),)),
            ("conversations", (("space_id", "TEXT DEFAULT ''"),)),
            ("logs", (("space_id", "TEXT DEFAULT ''"),
                      ("conversation_id", "TEXT DEFAULT ''"))),
            ("fabric_runs", (("space_id", "TEXT DEFAULT ''"),
                             ("conversation_id", "TEXT DEFAULT ''"))),
            ("tasks", (("space_id", "TEXT DEFAULT ''"),)),
            # Flows. `origin_*` is how a run knows where it came from, which is what
            # lets a flow started from a Telegram message answer in THAT chat instead
            # of the owner's. `grants.source_ref` is provenance: which definition wrote
            # a grant, so re-saving a flow can revoke its own rows and nobody else's.
            ("fabric_runs", (("origin_surface", "TEXT DEFAULT ''"),
                             ("origin_ref", "TEXT DEFAULT ''"),
                             ("flow", "TEXT DEFAULT ''"))),
            ("tasks", (("flow", "TEXT DEFAULT ''"),)),
            ("grants", (("source_ref", "TEXT DEFAULT ''"),)),
            ("subagents", (("memory_scope", "TEXT DEFAULT 'inherit'"),
                           ("skills_locked", "INTEGER DEFAULT 1"))),
            # provenance for a flow the model drafted: which model, what it assumed, what
            # it had to drop, and which agents came with it (so Discard can clean up)
            # `job` is the recipe a flow came out of (agentos/jobs.py), or '' for one
            # written by hand. Kept on the row rather than guessed from the description,
            # because "which of my jobs are still running?" has to survive somebody
            # renaming one.
            ("flows", (("draft", "TEXT DEFAULT '{}'"), ("job", "TEXT DEFAULT ''"))),
        ):
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, ddl in columns:
                if col not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        # Indexes that only exist once the columns above do (executescript ran the
        # CREATE INDEX statements before these ALTERs on a pre-spaces database).
        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_memories_space ON memories(space_id, scope)",
            "CREATE INDEX IF NOT EXISTS idx_kg_edges_src ON kg_edges(src)",
            "CREATE INDEX IF NOT EXISTS idx_kg_edges_dst ON kg_edges(dst)",
            "CREATE INDEX IF NOT EXISTS idx_kg_edges_space ON kg_edges(space_id)",
            "CREATE INDEX IF NOT EXISTS idx_logs_space ON logs(space_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_logs_conv ON logs(conversation_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_fabric_runs_space ON fabric_runs(space_id, started_at)",
        ):
            self.db.execute(ddl)

    def factory_reset(self):
        """Wipe every table (profile, memory, apps, logs, fabric, …) but keep the schema.
        Used by the first-run wizard's 'start fresh' flow."""
        tables = [r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for t in tables:
            self.db.execute(f"DELETE FROM {t}")
        self.db.commit()

    # -- conversations ------------------------------------------------------

    def create_conversation(self, title: str = "New chat", origin: str = "user",
                            space_id: str = "") -> str:
        cid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at, origin, space_id) "
            "VALUES (?,?,?,?,?,?)",
            (cid, title, now, now, origin or "user", space_id or ""),
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

    def get_conversation(self, cid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        return dict(row) if row else None

    def set_summary(self, cid: str, summary: str, upto: str, added: int = 0):
        """Persist the rolling summary of turns that fell out of the context
        budget. `summary_msgs` accumulates because it counts how much of the
        thread the summary now stands for, not how much the last pass ate."""
        self.db.execute(
            "UPDATE conversations SET summary=?, summary_upto=?, "
            "summary_msgs=COALESCE(summary_msgs,0)+? WHERE id=?",
            (summary or "", upto or "", int(added or 0), cid))
        self.db.commit()

    def set_conversation_space(self, cid: str, space_id: str):
        """Move a conversation into a space. Its session memories move with it —
        they were learned in that thread, so leaving them behind would split one
        conversation's knowledge across two scopes."""
        self.db.execute("UPDATE conversations SET space_id=? WHERE id=?", (space_id or "", cid))
        self.db.execute(
            "UPDATE memories SET space_id=? WHERE scope='session' AND conversation_id=?",
            (space_id or "", cid))
        self.db.commit()

    def list_conversations(self, limit: int = 100, space: str = "") -> list[dict]:
        sql, params = "SELECT * FROM conversations WHERE 1=1", []
        clause, sp = self._space_clause(space)
        sql += clause
        params += sp
        rows = self.db.execute(
            sql + " ORDER BY updated_at DESC LIMIT ?", (*params, limit)).fetchall()
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
                   pinned: int = 0, space_id: str = "") -> str:
        content = (content or "").strip()
        if not content:
            return ""
        if scope not in ("user", "session"):
            scope = "user"
        if scope != "session":
            conversation_id = None
        space_id = space_id or ""
        # exact-duplicate guard (case-insensitive, same scope/conversation/space);
        # re-seeing a fact counts as confirmation, so refresh its recency.
        # The same sentence can be true globally AND inside a space with a
        # different meaning ("the deadline is Friday"), so the space is part of
        # the identity rather than something to collapse.
        row = self.db.execute(
            "SELECT id FROM memories WHERE lower(content)=lower(?) AND scope=? "
            "AND (conversation_id IS ? OR conversation_id=?) AND COALESCE(space_id,'')=?",
            (content, scope, conversation_id, conversation_id or "", space_id)).fetchone()
        if row:
            self.db.execute("UPDATE memories SET updated_at=? WHERE id=?", (time.time(), row["id"]))
            self.db.commit()
            return row["id"]
        mid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO memories (id, content, scope, conversation_id, pinned, source, "
            "space_id, updated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, content, scope, conversation_id, pinned, source, space_id, now, now),
        )
        self.db.commit()
        return mid

    #: ask for global-only memories (the Profile app's "regardless of project" view)
    GLOBAL_ONLY = "__global__"

    def search_memories(self, query: str = "", limit: int = 20, scope: str = "",
                        conversation_id: str = "", space: str = "") -> list[dict]:
        """Search memory. `space` widens nothing and hides nothing global: passing a
        space means "what is true here", which is this space's memories UNION the
        ones true everywhere. Pass Store.GLOBAL_ONLY for global alone."""
        where, params = [], []
        if scope:
            where.append("scope=?")
            params.append(scope)
        if conversation_id:
            where.append("conversation_id=?")
            params.append(conversation_id)
        if space == self.GLOBAL_ONLY:
            where.append("COALESCE(space_id,'')=''")
        elif space:
            where.append("COALESCE(space_id,'') IN ('', ?)")
            params.append(space)
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
                      pinned: int | None = None, scope: str | None = None,
                      space_id: str | None = None):
        """Edit a memory in place. scope='user' also clears conversation_id (promote).
        space_id='' promotes it out of its space to true-everywhere, which is the
        other half of the same gesture. A content change resets the embedding so
        semantic recall re-indexes it."""
        sets, params = [], []
        if space_id is not None:
            sets.append("space_id=?")
            params.append(space_id)
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

    def log(self, kind: str, message: str, meta: dict | None = None,
            conversation_id: str = "", space_id: str = ""):
        meta = meta or {}
        # Callers have always passed the conversation inside meta. It is a real
        # column now, so accept it from either place rather than making every
        # call site change at once.
        conversation_id = conversation_id or str(meta.get("conversation_id") or "")
        space_id = space_id or str(meta.get("space_id") or "")
        self.db.execute(
            "INSERT INTO logs (id, kind, message, meta, conversation_id, space_id, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex[:12], kind, message[:2000], json.dumps(meta)[:4000],
             conversation_id, space_id, time.time()),
        )
        self.db.commit()

    def list_logs(self, kind: str = "", limit: int = 300, q: str = "",
                  space: str = "", conversation_id: str = "") -> list[dict]:
        sql, params = "SELECT * FROM logs WHERE 1=1", []
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if conversation_id:
            sql += " AND conversation_id=?"
            params.append(conversation_id)
        if space == self.GLOBAL_ONLY:
            sql += " AND COALESCE(space_id,'')=''"
        elif space:
            sql += " AND COALESCE(space_id,'') IN ('', ?)"
            params.append(space)
        if q:
            sql += " AND (message LIKE ? OR meta LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]
        rows = self.db.execute(sql + " ORDER BY created_at DESC LIMIT ?",
                               (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def clear_logs(self):
        self.db.execute("DELETE FROM logs")
        self.db.commit()

    # -- the access ledger ----------------------------------------------------

    def usage_add(self, model: str, tokens_in: int, tokens_out: int,
                  cost_usd: float | None = None, surface: str = "", principal: str = "user",
                  conversation_id: str = "", space_id: str = "", kind: str = "chat") -> str:
        """Record what one turn spent. Never raises — a bookkeeping failure must
        not cost the user the answer they were waiting for."""
        uid = uuid.uuid4().hex[:12]
        try:
            self.db.execute(
                "INSERT INTO usage (id, ts, model, surface, principal, conversation_id, "
                "space_id, tokens_in, tokens_out, cost_usd, kind) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (uid, time.time(), model or "", surface or "", principal or "user",
                 conversation_id or "", space_id or "", int(tokens_in or 0),
                 int(tokens_out or 0), cost_usd, kind or "chat"))
            self.db.commit()
        except Exception:  # pragma: no cover - defensive
            return ""
        return uid

    def usage_summary(self, since: float = 0, group: str = "model",
                      space: str = "", limit: int = 50) -> list[dict]:
        """Spend grouped by model, day, surface, kind or conversation.

        `priced` and `unpriced` are reported separately on purpose: a total that
        silently treats an unpriced local model as $0.00 reads as "this cost
        nothing", which is true for Ollama and false for anything else.
        """
        col = {"model": "model", "surface": "surface", "kind": "kind",
               "conversation": "conversation_id", "space": "space_id",
               "day": "CAST(ts/86400 AS INTEGER)"}.get(group, "model")
        sql = (f"SELECT {col} AS bucket, COUNT(*) n, SUM(tokens_in) tin, SUM(tokens_out) tout, "
               "SUM(COALESCE(cost_usd,0)) cost, SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) "
               "unpriced FROM usage WHERE ts > ?")
        params: list = [since]
        clause, sp = self._space_clause(space)
        sql += clause
        params += sp
        rows = self.db.execute(sql + f" GROUP BY {col} ORDER BY cost DESC, tin DESC LIMIT ?",
                               (*params, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["priced"] = d["n"] - d["unpriced"]
            if group == "day":
                d["bucket"] = time.strftime("%Y-%m-%d", time.gmtime(float(d["bucket"] or 0) * 86400))
            out.append(d)
        return out

    def audit_add(self, principal_kind: str = "", principal_id: str = "", surface: str = "",
                  action: str = "", resource: str = "", effect: str = "", rule: str = "",
                  risk: str = "", reason: str = "", space_id: str = "",
                  conversation_id: str = "", run_id: str = "", outcome: str = "",
                  detail: str = "", duration_ms: int = 0) -> str:
        """Record one access decision. Never raises: an audit write that fails must
        not take a turn down with it, but it must also never fail silently, so the
        failure goes to the operator log instead."""
        aid = uuid.uuid4().hex[:12]
        now = time.time()
        try:
            self.db.execute(
                "INSERT INTO audit (id, ts, principal_kind, principal_id, surface, space_id, "
                "conversation_id, run_id, action, resource, effect, rule, risk, reason, "
                "outcome, detail, duration_ms, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, now, principal_kind, principal_id, surface, space_id or "",
                 conversation_id or "", run_id or "", action, resource[:500], effect, rule,
                 risk, reason[:500], outcome, detail[:1000], int(duration_ms), now))
            self.db.commit()
        except Exception as e:  # pragma: no cover - defensive
            try:
                self.db.execute(
                    "INSERT INTO logs (id, kind, message, meta, created_at) VALUES (?,?,?,?,?)",
                    (uuid.uuid4().hex[:12], "error", f"audit write failed: {e}", "{}", now))
                self.db.commit()
            except Exception:
                pass
            return ""
        return aid

    def audit_finish(self, aid: str, outcome: str, detail: str = "", duration_ms: int = 0):
        """Stamp the result onto a decision already recorded. The decision itself is
        never rewritten — only the outcome columns, which were empty until now."""
        if not aid:
            return
        self.db.execute(
            "UPDATE audit SET outcome=?, detail=?, duration_ms=? WHERE id=?",
            (outcome, (detail or "")[:1000], int(duration_ms), aid))
        self.db.commit()

    def audit_list(self, limit: int = 300, effect: str = "", action: str = "",
                   principal_kind: str = "", surface: str = "", space: str = "",
                   since: float = 0.0, q: str = "") -> list[dict]:
        sql, params = "SELECT * FROM audit WHERE 1=1", []
        for col, val in (("effect", effect), ("action", action),
                         ("principal_kind", principal_kind), ("surface", surface)):
            if val:
                sql += f" AND {col}=?"
                params.append(val)
        if since:
            sql += " AND ts>=?"
            params.append(since)
        if space == self.GLOBAL_ONLY:
            sql += " AND COALESCE(space_id,'')=''"
        elif space:
            sql += " AND COALESCE(space_id,'') IN ('', ?)"
            params.append(space)
        if q:
            sql += " AND (resource LIKE ? OR reason LIKE ? OR detail LIKE ?)"
            params += [f"%{q}%"] * 3
        rows = self.db.execute(sql + " ORDER BY ts DESC LIMIT ?", (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def audit_summary(self, since: float = 0.0) -> dict:
        """Counts for the Audit app's header: what was allowed, denied and asked,
        and which resources were refused most. Cheap enough to poll."""
        where, params = ("WHERE ts>=?", [since]) if since else ("", [])
        effects = {r["effect"]: r["n"] for r in self.db.execute(
            f"SELECT effect, COUNT(*) n FROM audit {where} GROUP BY effect", params).fetchall()}
        top_denied = [dict(r) for r in self.db.execute(
            f"SELECT resource, action, COUNT(*) n FROM audit "
            f"{where + (' AND' if where else 'WHERE')} effect='deny' "
            f"GROUP BY resource, action ORDER BY n DESC LIMIT 10", params).fetchall()]
        by_surface = {r["surface"] or "unknown": r["n"] for r in self.db.execute(
            f"SELECT surface, COUNT(*) n FROM audit {where} GROUP BY surface", params).fetchall()}
        return {"effects": effects, "top_denied": top_denied, "by_surface": by_surface,
                "total": sum(effects.values())}

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
               subject_type: str = "", object_type: str = "", space_id: str = "") -> str:
        src = self._kg_node(subject, subject_type)
        dst = self._kg_node(obj, object_type)
        space_id = space_id or ""
        row = self.db.execute(
            "SELECT id FROM kg_edges WHERE src=? AND dst=? AND relation=? COLLATE NOCASE "
            "AND COALESCE(space_id,'')=?",
            (src, dst, relation.strip(), space_id)).fetchone()
        if row:
            return row["id"]
        eid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO kg_edges (id, src, dst, relation, space_id, created_at) VALUES (?,?,?,?,?,?)",
            (eid, src, dst, relation.strip(), space_id, time.time()))
        self.db.commit()
        return eid

    def _space_clause(self, space: str, col: str = "space_id") -> tuple[str, list]:
        """The one visibility rule, in one place: a space sees its own rows and the
        global ones. Returns ('', []) when no space was asked for."""
        if space == self.GLOBAL_ONLY:
            return f" AND COALESCE({col},'')=''", []
        if space:
            return f" AND COALESCE({col},'') IN ('', ?)", [space]
        return "", []

    def kg_graph(self, space: str = "") -> dict:
        """The graph as seen from `space`. Edges carry the scope; a node is present
        when a visible edge touches it, so entities are never duplicated per space.
        Orphan nodes (no edges at all) are always included — they are usually a
        just-added entity waiting for its first assertion."""
        clause, params = self._space_clause(space, "e.space_id")
        edges = [dict(r) for r in self.db.execute(
            f"SELECT e.* FROM kg_edges e WHERE 1=1{clause}", params).fetchall()]
        if not space:
            nodes = [dict(r) for r in self.db.execute("SELECT * FROM kg_nodes").fetchall()]
            return {"nodes": nodes, "edges": edges}
        touched = {e["src"] for e in edges} | {e["dst"] for e in edges}
        nodes = []
        for r in self.db.execute("SELECT * FROM kg_nodes").fetchall():
            n = dict(r)
            attached = self.db.execute(
                "SELECT 1 FROM kg_edges WHERE src=? OR dst=? LIMIT 1", (n["id"], n["id"])).fetchone()
            if n["id"] in touched or not attached:
                nodes.append(n)
        return {"nodes": nodes, "edges": edges}

    def kg_query(self, query: str, limit: int = 40, space: str = "") -> list[str]:
        """Return 'subject —relation→ object' lines whose endpoints or relation match
        the query words.

        This used to load the entire graph into Python and substring-match every
        rendered line, which is O(graph) for every recall on every turn. It is a
        join now, which is what made scoping cheap enough to add at all.
        """
        clause, params = self._space_clause(space, "e.space_id")
        words = [w for w in (query or "").split() if w]
        if words:
            ors, wp = [], []
            for w in words:
                ors.append("(s.name LIKE ? OR d.name LIKE ? OR e.relation LIKE ?)")
                wp += [f"%{w}%"] * 3
            clause += " AND (" + " OR ".join(ors) + ")"
            params = params + wp
        rows = self.db.execute(
            "SELECT s.name AS s, e.relation AS r, d.name AS o FROM kg_edges e "
            "JOIN kg_nodes s ON s.id = e.src JOIN kg_nodes d ON d.id = e.dst "
            f"WHERE 1=1{clause} ORDER BY e.created_at DESC LIMIT ?",
            (*params, limit)).fetchall()
        return [f"{r['s']} —{r['r']}→ {r['o']}" for r in rows]

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

    def kg_clear(self, space: str = ""):
        """Clear the graph. Clearing one space drops only its assertions and then
        the entities nothing points at any more — global facts survive."""
        if space:
            self.db.execute("DELETE FROM kg_edges WHERE COALESCE(space_id,'')=?", (space,))
            self.db.execute(
                "DELETE FROM kg_nodes WHERE id NOT IN "
                "(SELECT src FROM kg_edges UNION SELECT dst FROM kg_edges)")
        else:
            self.db.execute("DELETE FROM kg_edges")
            self.db.execute("DELETE FROM kg_nodes")
        self.db.commit()

    # -- spaces ---------------------------------------------------------------

    def create_space(self, name: str, description: str = "", icon: str = "",
                     colour: str = "", workspace: str = "") -> str:
        name = (name or "").strip()
        if not name:
            return ""
        row = self.db.execute("SELECT id FROM spaces WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if row:
            return row["id"]
        sid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO spaces (id, name, icon, colour, description, workspace, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (sid, name, icon, colour, description, workspace, now, now))
        self.db.commit()
        self.timeline_add("space", title=f"Space '{name}' created", space_id=sid,
                          ref_table="spaces", ref_id=sid)
        return sid

    def list_spaces(self, include_archived: bool = False) -> list[dict]:
        sql = "SELECT * FROM spaces"
        if not include_archived:
            sql += " WHERE COALESCE(archived,0)=0"
        return [dict(r) for r in self.db.execute(sql + " ORDER BY updated_at DESC").fetchall()]

    def get_space(self, sid_or_name: str) -> dict | None:
        if not sid_or_name:
            return None
        row = self.db.execute(
            "SELECT * FROM spaces WHERE id=? OR name=? COLLATE NOCASE",
            (sid_or_name, sid_or_name)).fetchone()
        return dict(row) if row else None

    def update_space(self, sid: str, **fields) -> None:
        allowed = ("name", "icon", "colour", "description", "workspace", "archived")
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed and v is not None:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return
        sets.append("updated_at=?")
        params.append(time.time())
        self.db.execute(f"UPDATE spaces SET {', '.join(sets)} WHERE id=?", (*params, sid))
        self.db.commit()

    #: what to do with a space's contents when it is deleted
    SPACE_CONTENTS = ("archive", "global", "delete")
    #: every table that carries a space_id, so no disposition can silently miss one
    _SPACED = ("memories", "kg_edges", "conversations", "logs", "fabric_runs",
               "tasks", "assets", "timeline_events", "audit")

    def delete_space(self, sid: str, contents: str = "archive") -> dict:
        """Deleting a space must never silently orphan what is in it, so the caller
        has to say what happens to the contents:
          archive — nothing moves, the space just stops being offered (default)
          global  — its memories, facts and assets become true everywhere
          delete  — everything scoped to it goes too
        Returns a per-table count of what was touched, so the UI can say it out loud.
        """
        if contents not in self.SPACE_CONTENTS:
            contents = "archive"
        counts: dict[str, int] = {}
        if contents == "archive":
            self.update_space(sid, archived=1)
            return {"archived": 1}
        for table in self._SPACED:
            n = self.db.execute(
                f"SELECT COUNT(*) c FROM {table} WHERE COALESCE(space_id,'')=?", (sid,)).fetchone()["c"]
            if not n:
                continue
            counts[table] = n
            if contents == "global":
                self.db.execute(f"UPDATE {table} SET space_id='' WHERE COALESCE(space_id,'')=?", (sid,))
            else:
                self.db.execute(f"DELETE FROM {table} WHERE COALESCE(space_id,'')=?", (sid,))
        if contents == "delete":
            # entities left pointing at nothing after their assertions went
            self.db.execute(
                "DELETE FROM kg_nodes WHERE id NOT IN "
                "(SELECT src FROM kg_edges UNION SELECT dst FROM kg_edges)")
        self.db.execute("DELETE FROM spaces WHERE id=?", (sid,))
        self.db.commit()
        return counts

    def space_stats(self, sid: str) -> dict:
        """What is actually in a space — shown before deleting it, so 'delete' is
        never a guess."""
        out = {}
        for table in self._SPACED:
            out[table] = self.db.execute(
                f"SELECT COUNT(*) c FROM {table} WHERE COALESCE(space_id,'')=?",
                (sid,)).fetchone()["c"]
        return out

    # -- timeline -------------------------------------------------------------

    def timeline_add(self, kind: str, title: str, space_id: str = "", ref_table: str = "",
                     ref_id: str = "", meta: dict | None = None, ts: float | None = None) -> str:
        tid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO timeline_events (id, space_id, ts, kind, ref_table, ref_id, title, "
            "meta, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, space_id or "", ts if ts is not None else now, kind, ref_table, ref_id,
             (title or "")[:400], json.dumps(meta or {})[:2000], now))
        self.db.commit()
        return tid

    def timeline(self, space: str = "", kind: str = "", since: float = 0.0,
                 limit: int = 200) -> list[dict]:
        sql, params = "SELECT * FROM timeline_events WHERE 1=1", []
        clause, sp = self._space_clause(space)
        sql += clause
        params += sp
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if since:
            sql += " AND ts>=?"
            params.append(since)
        rows = self.db.execute(sql + " ORDER BY ts DESC LIMIT ?", (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    # -- assets ---------------------------------------------------------------

    def asset_add(self, sha256: str, path: str, kind: str, mime: str = "", size: int = 0,
                  title: str = "", prompt: str = "", source: str = "", origin_url: str = "",
                  conversation_id: str = "", run_id: str = "", space_id: str = "",
                  thumb: str = "", width: int = 0, height: int = 0, duration: float = 0.0,
                  meta: dict | None = None) -> str:
        """Record an asset. Content-addressed: the same bytes seen twice return the
        existing row rather than a second one, so a re-download costs nothing."""
        row = self.db.execute("SELECT * FROM assets WHERE sha256=?", (sha256,)).fetchone()
        if row:
            return row["id"]
        aid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO assets (id, sha256, path, kind, mime, bytes, width, height, duration, "
            "title, prompt, source, origin_url, conversation_id, run_id, space_id, thumb, meta, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, sha256, path, kind, mime, int(size), int(width), int(height), float(duration),
             title[:200], prompt[:1000], source, origin_url[:500], conversation_id, run_id,
             space_id or "", thumb, json.dumps(meta or {})[:2000], time.time()))
        self.db.commit()
        self.timeline_add("asset", title or f"{kind} from {source or 'unknown'}",
                          space_id=space_id, ref_table="assets", ref_id=aid,
                          meta={"kind": kind, "mime": mime})
        return aid

    def asset_get(self, aid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
        return dict(row) if row else None

    def asset_by_sha(self, sha256: str) -> dict | None:
        row = self.db.execute("SELECT * FROM assets WHERE sha256=?", (sha256,)).fetchone()
        return dict(row) if row else None

    def asset_list(self, kind: str = "", q: str = "", space: str = "",
                   conversation_id: str = "", run_id: str = "",
                   limit: int = 100, offset: int = 0) -> list[dict]:
        sql, params = "SELECT * FROM assets WHERE 1=1", []
        clause, sp = self._space_clause(space)
        sql += clause
        params += sp
        for col, val in (("kind", kind), ("conversation_id", conversation_id), ("run_id", run_id)):
            if val:
                sql += f" AND {col}=?"
                params.append(val)
        if q:
            sql += " AND (title LIKE ? OR prompt LIKE ? OR source LIKE ?)"
            params += [f"%{q}%"] * 3
        rows = self.db.execute(sql + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                               (*params, limit, offset)).fetchall()
        return [dict(r) for r in rows]

    def asset_update(self, aid: str, **fields) -> None:
        allowed = ("title", "thumb", "width", "height", "duration", "space_id", "meta")
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed and v is not None:
                sets.append(f"{k}=?")
                params.append(json.dumps(v) if k == "meta" and isinstance(v, dict) else v)
        if not sets:
            return
        self.db.execute(f"UPDATE assets SET {', '.join(sets)} WHERE id=?", (*params, aid))
        self.db.commit()

    def asset_delete(self, aid: str) -> dict | None:
        """Drop the row and hand the caller what it needs to unlink the files. The
        Store does not touch the filesystem — assets.py owns that."""
        row = self.asset_get(aid)
        if not row:
            return None
        self.db.execute("DELETE FROM assets WHERE id=?", (aid,))
        self.db.execute("DELETE FROM timeline_events WHERE ref_table='assets' AND ref_id=?", (aid,))
        self.db.commit()
        return row

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

    def rename_app(self, aid: str, name: str = "", icon: str | None = None,
                   description: str | None = None,
                   widget_size: str | None = None) -> str | None:
        """Rename/redecorate an app in place (id, data, versions and grants all key on
        the id, so nothing else moves). Returns an error string, or None on success."""
        app = self.get_app(aid)
        if not app:
            return "app not found"
        sets, params = [], []
        if name and name.strip() and name.strip() != app["name"]:
            name = name.strip()[:60]
            clash = self.db.execute(
                "SELECT id FROM user_apps WHERE name=? COLLATE NOCASE AND id!=?",
                (name, aid)).fetchone()
            if clash:
                return f"an app named '{name}' already exists"
            sets.append("name=?")
            params.append(name)
        if icon is not None:
            sets.append("icon=?")
            params.append(icon)
        if description is not None:
            sets.append("description=?")
            params.append(description)
        if widget_size is not None:
            # every app has a widget mode; the size is the user's, not the model's
            sets.append("widget_size=?")
            params.append(widget_size if widget_size in ("s", "m", "l") else "m")
        if not sets:
            return None
        sets.append("updated_at=?")
        params.append(time.time())
        self.db.execute(f"UPDATE user_apps SET {', '.join(sets)} WHERE id=?", (*params, aid))
        self.db.commit()
        return None

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

    # -- quarantine: what the OS stopped, and why ----------------------------

    def quarantine_add(self, principal_kind: str, principal_id: str, reason: str,
                       label: str = "", kind: str = "rate", evidence: dict | None = None) -> str:
        """Hold a principal. Returns '' if it is already held — a runaway calls many times
        a second, and one incident must not become two hundred rows."""
        if self.quarantined(principal_kind, principal_id):
            return ""
        qid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO quarantine (id, principal_kind, principal_id, label, reason, kind, "
            "evidence, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (qid, principal_kind, principal_id, label[:120], reason[:400], kind,
             json.dumps(evidence or {})[:2000], time.time()))
        self.db.commit()
        self.quarantine_version = getattr(self, "quarantine_version", 0) + 1
        return qid

    def quarantined(self, principal_kind: str, principal_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM quarantine WHERE principal_kind=? AND principal_id=? "
            "AND released_at IS NULL ORDER BY created_at DESC LIMIT 1",
            (principal_kind, principal_id)).fetchone()
        return dict(row) if row else None

    def quarantine_exempt(self, principal_kind: str, principal_id: str) -> bool:
        """Did the user say 'allow this forever'? That decision outlives the incident, which
        is the point of recording the mode rather than just deleting the row."""
        row = self.db.execute(
            "SELECT 1 FROM quarantine WHERE principal_kind=? AND principal_id=? "
            "AND release_mode='forever' LIMIT 1", (principal_kind, principal_id)).fetchone()
        return bool(row)

    def quarantine_list(self, include_released: bool = False, limit: int = 100) -> list[dict]:
        q = "SELECT * FROM quarantine"
        if not include_released:
            q += " WHERE released_at IS NULL"
        rows = self.db.execute(q + " ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["evidence"] = json.loads(d.get("evidence") or "{}")
            except Exception:
                d["evidence"] = {}
            out.append(d)
        return out

    def quarantine_release(self, qid: str, mode: str, by: str = "user") -> dict | None:
        row = self.db.execute("SELECT * FROM quarantine WHERE id=?", (qid,)).fetchone()
        if not row:
            return None
        self.db.execute(
            "UPDATE quarantine SET released_at=?, release_mode=?, released_by=? WHERE id=?",
            (time.time(), mode, by, qid))
        self.db.commit()
        self.quarantine_version = getattr(self, "quarantine_version", 0) + 1
        return dict(row)

    def suspend_app(self, aid: str, reason: str) -> bool:
        """Stop an app without deleting it or touching what it was granted.

        Suspension is a pause, not a punishment: the app, its data, its versions and its
        permissions all survive, so resuming is one click and loses nothing. What stops is
        its ability to call anything."""
        cur = self.db.execute(
            "UPDATE user_apps SET suspended_at=?, suspended_reason=? WHERE id=? "
            "AND suspended_at IS NULL", (time.time(), reason[:400], aid))
        self.db.commit()
        return bool(cur.rowcount)

    def resume_app(self, aid: str) -> bool:
        cur = self.db.execute(
            "UPDATE user_apps SET suspended_at=NULL, suspended_reason='' WHERE id=?", (aid,))
        self.db.commit()
        return bool(cur.rowcount)

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

    # -- automations: named, repeatable desktop sequences ---------------------

    def save_automation(self, name: str, steps: str, icon: str = "", aid: str = "") -> str:
        """Upsert by name — saving 'Morning' twice edits it rather than forking it."""
        name = (name or "").strip()
        now = time.time()
        row = self.db.execute("SELECT id FROM automations WHERE name=?", (name,)).fetchone()
        aid = row["id"] if row else (aid or uuid.uuid4().hex[:12])
        self.db.execute(
            "INSERT INTO automations (id, name, icon, steps, created_at, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, icon=excluded.icon, "
            "steps=excluded.steps, updated_at=excluded.updated_at",
            (aid, name, icon or "", steps, now, now))
        self.db.commit()
        return aid

    def list_automations(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, name, icon, steps, created_at, updated_at, last_run, runs "
            "FROM automations ORDER BY name COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["steps"] = json.loads(r["steps"] or "[]")
            except Exception:
                d["steps"] = []
            out.append(d)
        return out

    def get_automation(self, key: str) -> dict | None:
        """By id or by name — callers say 'run Morning', not 'run 3f9a…'."""
        row = self.db.execute(
            "SELECT * FROM automations WHERE id=? OR name=? COLLATE NOCASE", (key, key)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["steps"] = json.loads(row["steps"] or "[]")
        except Exception:
            d["steps"] = []
        return d

    def delete_automation(self, key: str):
        self.db.execute("DELETE FROM automations WHERE id=? OR name=? COLLATE NOCASE", (key, key))
        self.db.commit()

    def mark_automation_run(self, aid: str):
        self.db.execute("UPDATE automations SET last_run=?, runs=COALESCE(runs,0)+1 WHERE id=?",
                        (time.time(), aid))
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

    # -- whatsapp chats -------------------------------------------------------

    def wa_upsert_chat(self, wa_id: str, name: str) -> dict:
        """Record an INBOUND message. `last_inbound` moves only here, because that is
        exactly what Meta's 24-hour window measures — a message we sent does not
        reopen it, and a row touched for any other reason must not pretend it did."""
        now = time.time()
        row = self.db.execute("SELECT 1 FROM whatsapp_chats WHERE wa_id=?", (wa_id,)).fetchone()
        if row:
            self.db.execute(
                "UPDATE whatsapp_chats SET name=?, msg_count=msg_count+1, last_inbound=?, "
                "last_seen=? WHERE wa_id=?", (name, now, now, wa_id))
        else:
            self.db.execute(
                "INSERT INTO whatsapp_chats (wa_id, name, allowed, msg_count, last_inbound, "
                "first_seen, last_seen) VALUES (?,?,0,1,?,?,?)", (wa_id, name, now, now, now))
        self.db.commit()
        return self.wa_get_chat(wa_id) or {}

    def wa_get_chat(self, wa_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM whatsapp_chats WHERE wa_id=?",
                              (wa_id or "",)).fetchone()
        return dict(row) if row else None

    def wa_list_chats(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM whatsapp_chats ORDER BY last_seen DESC").fetchall()
        return [dict(r) for r in rows]

    def wa_set_allowed(self, wa_id: str, allowed: int):
        self.db.execute("UPDATE whatsapp_chats SET allowed=? WHERE wa_id=?", (allowed, wa_id))
        self.db.commit()

    def wa_set_conversation(self, wa_id: str, cid: str):
        self.db.execute("UPDATE whatsapp_chats SET conversation_id=? WHERE wa_id=?",
                        (cid, wa_id))
        self.db.commit()

    def wa_delete_chat(self, wa_id: str):
        self.db.execute("DELETE FROM whatsapp_chats WHERE wa_id=?", (wa_id,))
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
                  expires_at: float | None = None, surfaces: str = "*",
                  source_ref: str = "") -> str:
        """Write one consent rule. Identical live rules dedupe to the existing row.
        `surfaces` scopes the rule to IO gates ('*' or csv of gui,tui,telegram,api,task).

        `source_ref` names the definition that asked for this rule ('flow:nightly-digest').
        It is part of the dedupe key on purpose: a grant a person wrote by hand and one a
        flow definition implies can read identically, and collapsing them would mean the
        next save of that flow silently revokes somebody's deliberate decision."""
        surfaces = (surfaces or "*").strip() or "*"
        row = self.db.execute(
            "SELECT id, surfaces FROM grants WHERE principal_kind=? AND principal_id=? AND action=? "
            "AND resource=? AND effect=? AND COALESCE(source_ref,'')=? AND revoked_at IS NULL",
            (principal_kind, principal_id, action, resource, effect, source_ref or "")).fetchone()
        if row:
            if (row["surfaces"] or "*") != surfaces:
                self.db.execute("UPDATE grants SET surfaces=? WHERE id=?", (surfaces, row["id"]))
                self.db.commit()
                self.grants_version += 1
            return row["id"]
        gid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO grants (id, principal_kind, principal_id, action, resource, effect, "
            "source, note, surfaces, expires_at, created_at, source_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (gid, principal_kind, principal_id, action, resource, effect,
             source, note[:300], surfaces, expires_at, time.time(), source_ref or ""))
        self.db.commit()
        self.grants_version += 1
        return gid

    def set_grant_surfaces(self, gid: str, surfaces: str) -> bool:
        """Rescope a live grant's IO gates ('*' or csv of gui,tui,telegram,api,task)."""
        surfaces = (surfaces or "*").strip() or "*"
        cur = self.db.execute("UPDATE grants SET surfaces=? WHERE id=? AND revoked_at IS NULL",
                              (surfaces, gid))
        self.db.commit()
        if cur.rowcount:
            self.grants_version += 1
        return bool(cur.rowcount)

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

    # -- MCP registry: first-class records of discovered/installed MCP servers ----

    def mcp_reg_upsert(self, name: str, title: str = "", description: str = "",
                       source: str = "", origin: str = "", package: dict | None = None,
                       homepage: str = "", status: str = "", doc_file: str = "") -> str:
        """Upsert one registry row. On update, only the fields passed with real values
        are overwritten; defaults (source=manual, status=installed) apply on insert only."""
        name = (name or "").strip()
        now = time.time()
        row = self.db.execute("SELECT id FROM mcp_registry WHERE name=? COLLATE NOCASE",
                              (name,)).fetchone()
        if row:
            sets, params = ["updated_at=?"], [now]
            for col, val in (("title", title), ("description", description),
                             ("source", source), ("origin", origin),
                             ("package", json.dumps(package) if package else ""),
                             ("homepage", homepage), ("status", status),
                             ("doc_file", doc_file)):
                if val:  # only overwrite with real values — partial updates keep the rest
                    sets.append(f"{col}=?")
                    params.append(val)
            self.db.execute(f"UPDATE mcp_registry SET {', '.join(sets)} WHERE id=?",
                            (*params, row["id"]))
            self.db.commit()
            return row["id"]
        rid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO mcp_registry (id, name, title, description, source, origin, package, "
            "homepage, status, doc_file, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, name, title or name, description, source or "manual", origin,
             json.dumps(package) if package else "", homepage, status or "installed",
             doc_file, now, now))
        self.db.commit()
        return rid

    def mcp_reg_list(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM mcp_registry ORDER BY name COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["package"] = json.loads(d.get("package") or "{}")
            except Exception:
                d["package"] = {}
            out.append(d)
        return out

    def mcp_reg_get(self, name: str) -> dict | None:
        row = self.db.execute("SELECT * FROM mcp_registry WHERE name=? COLLATE NOCASE",
                              ((name or "").strip(),)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["package"] = json.loads(d.get("package") or "{}")
        except Exception:
            d["package"] = {}
        return d

    def mcp_reg_delete(self, name: str):
        self.db.execute("DELETE FROM mcp_registry WHERE name=? COLLATE NOCASE",
                        ((name or "").strip(),))
        self.db.commit()

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
                int(d.get("builtin", 0)), d.get("memory_scope", "inherit"),
                int(d.get("skills_locked", 1)), now)
        if row:
            self.db.execute(
                "UPDATE subagents SET name=?, soul=?, model=?, tools=?, skills=?, autonomy_cap=?, "
                "target=?, max_steps=?, max_seconds=?, builtin=?, memory_scope=?, skills_locked=?, "
                "updated_at=? WHERE id=?", (*vals, sid))
        else:
            self.db.execute(
                "INSERT INTO subagents (name, soul, model, tools, skills, autonomy_cap, target, "
                "max_steps, max_seconds, builtin, memory_scope, skills_locked, updated_at, id, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                         parent_run: str = "", model: str = "", space_id: str = "",
                         conversation_id: str = "", flow: str = "",
                         origin_surface: str = "", origin_ref: str = "") -> str:
        rid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO fabric_runs (id, kind, ref, parent_run, status, input, model, "
            "space_id, conversation_id, started_at, flow, origin_surface, origin_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, kind, ref, parent_run, "running", input_text[:4000], model,
             space_id or "", conversation_id or "", time.time(),
             flow or "", origin_surface or "", origin_ref or ""))
        self.db.commit()
        return rid

    def fabric_run_finish(self, rid: str, status: str, output: str = "", fault: str = "",
                          tokens_in: int = 0, tokens_out: int = 0, steps: int = 0):
        self.db.execute(
            "UPDATE fabric_runs SET status=?, output=?, fault=?, tokens_in=?, tokens_out=?, "
            "steps=?, finished_at=? WHERE id=?",
            (status, output[:8000], fault[:2000], tokens_in, tokens_out, steps, time.time(), rid))
        # A finished run is a milestone: it is what "what did my agents do while I
        # was away?" is actually asking about.
        row = self.db.execute(
            "SELECT kind, ref, space_id FROM fabric_runs WHERE id=?", (rid,)).fetchone()
        if row:
            self.timeline_add("run", f"{row['ref']} ({row['kind']}) — {status}",
                              space_id=row["space_id"] or "", ref_table="fabric_runs",
                              ref_id=rid, meta={"status": status, "steps": steps})
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

    # -- flows: standing missions with a master orchestrator -----------------

    _FLOW_JSON = ("roster", "permissions", "sinks", "draft")

    @classmethod
    def _flow_row(cls, r) -> dict:
        d = dict(r)
        for k in cls._FLOW_JSON:
            try:
                d[k] = json.loads(d.get(k) or ("{}" if k in ("permissions", "draft") else "[]"))
            except Exception:
                d[k] = {} if k in ("permissions", "draft") else []
        return d

    def save_flow(self, d: dict) -> str:
        name = (d.get("name") or "").strip()
        now = time.time()
        row = self.db.execute("SELECT id FROM flows WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        fid = row["id"] if row else uuid.uuid4().hex[:12]
        vals = (name, d.get("description", ""), d.get("mission", ""),
                json.dumps(d.get("roster") or []), d.get("model", ""),
                json.dumps(d.get("permissions") or {}), json.dumps(d.get("sinks") or []),
                d.get("autonomy_cap", "balanced"), int(d.get("max_delegations", 12)),
                int(d.get("max_steps", 24)), int(d.get("max_seconds", 1800)),
                d.get("space_id", "") or "", int(d.get("enabled", 1)), int(d.get("builtin", 0)),
                json.dumps(d.get("draft") or {}), str(d.get("job") or "")[:48], now)
        if row:
            self.db.execute(
                "UPDATE flows SET name=?, description=?, mission=?, roster=?, model=?, "
                "permissions=?, sinks=?, autonomy_cap=?, max_delegations=?, max_steps=?, "
                "max_seconds=?, space_id=?, enabled=?, builtin=?, draft=?, job=?, "
                "updated_at=? WHERE id=?", (*vals, fid))
        else:
            self.db.execute(
                "INSERT INTO flows (name, description, mission, roster, model, permissions, "
                "sinks, autonomy_cap, max_delegations, max_steps, max_seconds, space_id, "
                "enabled, builtin, draft, job, updated_at, id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*vals, fid, now))
        self.db.commit()
        return fid

    def list_flows(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM flows ORDER BY name COLLATE NOCASE").fetchall()
        return [self._flow_row(r) for r in rows]

    def get_flow(self, name: str) -> dict | None:
        row = self.db.execute("SELECT * FROM flows WHERE name=? COLLATE NOCASE",
                              ((name or "").strip(),)).fetchone()
        return self._flow_row(row) if row else None

    def delete_flow(self, fid: str):
        self.db.execute("DELETE FROM flows WHERE id=?", (fid,))
        self.db.commit()

    # -- flow triggers ------------------------------------------------------

    @staticmethod
    def _trigger_row(r) -> dict:
        d = dict(r)
        try:
            d["config"] = json.loads(d.get("config") or "{}")
        except Exception:
            d["config"] = {}
        return d

    def add_flow_trigger(self, flow: str, kind: str, config: dict | None = None,
                         task_id: str = "", secret: str = "", cooldown_secs: int = 60,
                         enabled: int = 1) -> str:
        tid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO flow_triggers (id, flow, kind, config, task_id, secret, enabled, "
            "cooldown_secs, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, flow, kind, json.dumps(config or {}), task_id, secret, int(enabled),
             int(cooldown_secs), time.time()))
        self.db.commit()
        return tid

    def flow_triggers(self, flow: str = "", kind: str = "", enabled_only: bool = False) -> list[dict]:
        q, params = "SELECT * FROM flow_triggers WHERE 1=1", []
        if flow:
            q += " AND flow=? COLLATE NOCASE"
            params.append(flow)
        if kind:
            q += " AND kind=?"
            params.append(kind)
        if enabled_only:
            q += " AND enabled=1"
        rows = self.db.execute(q + " ORDER BY created_at", params).fetchall()
        return [self._trigger_row(r) for r in rows]

    def flow_trigger(self, tid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM flow_triggers WHERE id=?", (tid,)).fetchone()
        return self._trigger_row(row) if row else None

    def update_flow_trigger(self, tid: str, **fields):
        if not fields:
            return
        if isinstance(fields.get("config"), dict):
            fields["config"] = json.dumps(fields["config"])
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE flow_triggers SET {cols} WHERE id=?", (*fields.values(), tid))
        self.db.commit()

    def flow_trigger_fired(self, tid: str, dropped: bool = False):
        """One firing (or one refused by the cooldown). Dropped fires are counted, not
        discarded — 'it never ran' and 'it ran less often than you think' look identical
        otherwise, and only one of them is a bug in the cooldown."""
        if dropped:
            self.db.execute("UPDATE flow_triggers SET dropped=dropped+1 WHERE id=?", (tid,))
        else:
            self.db.execute("UPDATE flow_triggers SET fires=fires+1, last_fired=? WHERE id=?",
                            (time.time(), tid))
        self.db.commit()

    def delete_flow_trigger(self, tid: str):
        self.db.execute("DELETE FROM flow_triggers WHERE id=?", (tid,))
        self.db.commit()

    # -- the blackboard -----------------------------------------------------

    def artifact_add(self, run_id: str, handle: str, content: str, kind: str = "output",
                     agent: str = "", child_run: str = "", task: str = "", status: str = "ok",
                     tokens_in: int = 0, tokens_out: int = 0, tainted: int = 0,
                     deps: list | None = None, space_id: str = "") -> str:
        content = content or ""
        aid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO flow_artifacts (id, run_id, handle, kind, agent, child_run, task, "
            "content, preview, bytes, status, tokens_in, tokens_out, tainted, deps, space_id, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, run_id, handle, kind, agent, child_run, task[:400], content,
             " ".join(content.split())[:240], len(content), status, tokens_in, tokens_out,
             int(tainted), json.dumps(deps or []), space_id or "", time.time()))
        self.db.commit()
        return aid

    def artifact_get(self, run_id: str, handle: str) -> dict | None:
        row = self.db.execute("SELECT * FROM flow_artifacts WHERE run_id=? AND handle=?",
                              (run_id, handle)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["deps"] = json.loads(d.get("deps") or "[]")
        return d

    def artifact_index(self, run_id: str) -> list[dict]:
        """Every column EXCEPT `content`. The index is what goes into a prompt, and a
        query that *could* return 400 KB is how it eventually does."""
        rows = self.db.execute(
            "SELECT id, run_id, handle, kind, agent, child_run, task, preview, bytes, status, "
            "tokens_in, tokens_out, tainted, deps, space_id, created_at "
            "FROM flow_artifacts WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["deps"] = json.loads(d.get("deps") or "[]")
            out.append(d)
        return out

    def next_handle(self, run_id: str, prefix: str = "a") -> str:
        row = self.db.execute(
            "SELECT COUNT(*) n FROM flow_artifacts WHERE run_id=? AND handle LIKE ?",
            (run_id, prefix + "%")).fetchone()
        return f"{prefix}{(row['n'] if row else 0) + 1}"

    # -- scheduled tasks ----------------------------------------------------

    def add_task(self, prompt: str, schedule_type: str, interval_seconds: int | None,
                 at_time: str | None, next_run: float | None, trigger: str = "",
                 trigger_config: str = "{}", cooldown_secs: int = 300,
                 flow: str = "", space_id: str = "") -> str:
        tid = uuid.uuid4().hex[:12]
        self.db.execute(
            'INSERT INTO tasks (id, prompt, schedule_type, interval_seconds, at_time, next_run, '
            'created_at, "trigger", trigger_config, cooldown_secs, flow, space_id) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, prompt, schedule_type, interval_seconds, at_time, next_run, time.time(),
             trigger, trigger_config or "{}", int(cooldown_secs), flow or "", space_id or ""),
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

    # -- proactive items (digests & suggestions) -----------------------------

    def add_proactive(self, kind: str, text: str, data: dict | None = None) -> str:
        pid = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO proactive_items (id, kind, text, data, created_at) VALUES (?,?,?,?,?)",
            (pid, kind, (text or "").strip()[:4000], json.dumps(data or {}), time.time()),
        )
        self.db.commit()
        return pid

    def latest_proactive(self, kind: str) -> dict | None:
        """The newest live (undismissed) item of a kind, with its JSON data parsed."""
        row = self.db.execute(
            "SELECT * FROM proactive_items WHERE kind=? AND dismissed_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1", (kind,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["data"] = json.loads(d.get("data") or "{}")
        except Exception:
            d["data"] = {}
        return d

    def dismiss_proactive(self, pid: str = "", kind: str = ""):
        """Dismiss one item by id, or every live item of a kind."""
        now = time.time()
        if pid:
            self.db.execute("UPDATE proactive_items SET dismissed_at=? WHERE id=? "
                            "AND dismissed_at IS NULL", (now, pid))
        elif kind:
            self.db.execute("UPDATE proactive_items SET dismissed_at=? WHERE kind=? "
                            "AND dismissed_at IS NULL", (now, kind))
        self.db.commit()

    def proactive_dismissed_since(self, kind: str, since: float) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM proactive_items WHERE kind=? AND dismissed_at>? LIMIT 1",
            (kind, since)).fetchone()
        return row is not None

    # -- the OS-initiative metric --------------------------------------------

    def initiative_stats(self, since: float = 0.0) -> dict:
        """Turns split by who initiated them. Turn logs carry meta.origin
        (user | schedule | trigger | briefing | suggestion); missing = user."""
        os_t = user_t = 0
        for r in self.db.execute(
                "SELECT meta FROM logs WHERE kind='turn' AND created_at>?", (since,)).fetchall():
            try:
                origin = json.loads(r["meta"] or "{}").get("origin") or "user"
            except Exception:
                origin = "user"
            if origin == "user":
                user_t += 1
            else:
                os_t += 1
        total = os_t + user_t
        return {"os_turns": os_t, "user_turns": user_t,
                "pct_os": round(100.0 * os_t / total, 1) if total else 0.0}
