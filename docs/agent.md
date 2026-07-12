# The Agent

The agent is the intelligence at the center of AgentOS. It plans, uses tools to take real actions,
observes the results, and continues until the task is done — with your approval on anything risky.

By default the agent is named **Aria** (change it in Settings).

---

## How it works

Each turn, the agent runs a loop: think → call tools → read the results → adapt → respond. It streams
its progress to the chat window, including its reasoning, each tool call and its output, and any
approval requests. It's instructed to **finish the job** — to produce the concrete result you asked
for (a file, a report, a created project, a scheduled job), not to stop after a single step.

The agent also chooses the right *shape* for a request:
- a one-off result → do it now (and save a report if it's research/analysis),
- a recurring need → a scheduled **job**,
- something interactive you'll click → a built **app**.

---

## The tool set

Everything the agent can do is a tool. The built-in tools:

**System & files**
- `run_command` — run a shell command and return its output
- `read_file`, `write_file`, `list_dir` — work with files
- `system_info` — a snapshot of the machine
- `open_app` — open a file, app, or URL on the host
- `notify` — desktop notification

**Web & reports**
- `fetch_url` — fetch a web page or API as text
- `save_report` — write a formatted report to your workspace (optionally deliver to Telegram)

**Memory & knowledge**
- `remember`, `recall`, `forget` — memory, with two scopes: `user` (durable, all conversations)
  and `session` (this conversation only)
- `kg_add`, `kg_query` — structured knowledge graph
- `update_soul` — evolve the agent's persistent identity
- `read_app_data` — read the data stored inside a built app

**Team & delegation**
- **@mentions** — in any chat surface (Agent Chat, Telegram, TUI) type `@name your task` to
  address a subagent directly; it runs inside the chat, streaming its steps, and the run is
  tracked in the Team app's Observability tab
- `delegate` — hand a focused subtask to a specialist subagent (own model, tools, budget)
- `run_workflow` — run a multi-subagent DAG (e.g. draft on a local model, validate on a
  stronger one); manage both in the Team app ()

**Building & configuring the OS**
- `create_app` — build a UI app that appears on the desktop
- `pin_widget` — pin an app to the desktop as a live widget
- `configure_agentos` — change settings (autonomy, model, policies, integrations, name)
- `add_mcp_server` — connect an external tool "channel"
- `manage_models` — list, download, or remove local Ollama models

**Skills & automation**
- `use_skill`, `save_skill`, `delete_skill` — reusable procedures
- `schedule_task` — recurring background jobs

**Host desktop**
- `launch_native_app` — launch any installed application
- `system_control` — volume, mute, and open native settings panels

**Communication**
- `telegram_send` — message your paired Telegram chat

**Self-extension**
- `read_source`, `develop_agentos`, `restart_agentos` — read and modify AgentOS's own source code
- `snapshot_os` — save a restore point of the whole system

Plus every tool from any connected **MCP server**, which appears as `mcp_<server>_<tool>`.

You can drive all of these from plain chat: *"add the github channel," "pull qwen2.5:14b," "set volume
to 30," "save a skill for our release process," "build me a habit tracker."*

---

## Safety

AgentOS is designed to give the agent real power without letting it surprise you.

### Autonomy levels
| Level | Behavior |
|---|---|
| Paranoid / Balanced | read-only actions run automatically; anything that modifies the system asks for one-click approval |
| Full | everything runs without prompting |

Destructive commands (wiping the disk, `mkfs`, `shutdown`, fork bombs, …) are **hard-blocked at every
level**, including Full.

### Policies
The **Policies** app lets you set standing rules matched against `<tool> <command>`:
- **allow** rules run matching actions without asking,
- **deny** rules block them outright (deny always wins over allow).

Patterns use `*` wildcards, e.g. `run_command git *`. Every approval prompt also has an **"Always
allow"** button that writes a policy for you.

### Folder sandbox
With `bubblewrap` installed, the agent's shell and file tools — and the Terminal — are confined to a
single folder (default `~/AgentOS`). The rest of the filesystem is read-only and other home files are
hidden. Toggle it in **Settings → Sandbox**.

### Snapshots
Take a restore point before risky changes from the **Snapshots** app. The agent also snapshots
automatically before modifying its own code. Restoring rolls back settings, data, and source, then
restarts.

---

## Memory, knowledge & soul

- **Memory (◈)** — two tiers, both injected into every turn and fully manageable in the Memory app:
  - **User memory** — durable facts about you and your machine, shared across all conversations.
    Pin () the ones that must always be injected first; edit (✎) or delete (✕) any of them.
  - **Session memory** — the working context of one conversation (goals, decisions, constraints).
    It is injected only into that conversation and deleted with it. Promote (⤴) a session memory
    to user memory to keep it forever.
- **Auto-learn ()** — after every chat turn a background pass mines the exchange for user
  memories, session memories, and knowledge-graph facts, so memory and the knowledge base
  populate themselves — no `remember` call needed. It also applies **corrections**: a fact you
  contradict gets rewritten, a fact you withdraw gets deleted (pinned memories are immune).
  Toggle it in the Memory app, or point it at a small fast model via `memory.model` in config.
- **Semantic recall** — memories are embedded with a local Ollama embedding model
  (auto-detected; install one with `ollama pull nomic-embed-text`). When memory outgrows the
  injection budget, the most *relevant* memories for the current message are injected, and
  `recall` finds facts by meaning, not just keywords.
- **Housekeeping** — a background maintenance loop (and the Tidy button) embeds new
  memories, rolls idle conversations' session memory up into durable user memory, and merges
  duplicate knowledge-graph entities ("Piyush" / "piyush chandra").
- **Profile ()** — one page showing everything the agent knows about you: stats, user
  memories, graph facts, and soul, with links to manage each.
- **Knowledge Graph ()** — structured relationships (people, projects, tools) shown as a live
  graph; recent facts are also injected into the agent's context.
- **Soul ()** — a persistent identity/personality file injected into every conversation. You can
  edit it directly, and the agent can refine it over time as it learns about you.

Clearing a conversation (the button, or "clear session") wipes just that conversation; your
user memory, graph, and soul persist. Deleting a conversation also deletes its session memories.

---

## Skills

Skills are reusable procedures — house rules, runbooks, how-tos. The agent sees the list of skills
and loads one when relevant. Manage them in the **Skills** app: write one directly, or install from
a git repository or a raw Markdown URL. The agent can also save skills itself when you teach it a
process.

---

## Scheduler & jobs

The **Scheduler** runs recurring background **jobs** — a prompt executed on a schedule (interval,
daily, or once). A job runs headless and is told to deliver its result: save a report and/or message
you on Telegram. Create one from the app, or just ask: *"every morning at 9, summarize my calendar
and send it to Telegram."*

At **Balanced** autonomy, jobs stay read-only unless you approve; run **Full** (or add a policy) for
jobs that need to write files or take other actions unattended.
