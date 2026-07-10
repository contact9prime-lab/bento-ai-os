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
- `remember`, `recall` — long-term facts
- `kg_add`, `kg_query` — structured knowledge graph
- `update_soul` — evolve the agent's persistent identity
- `read_app_data` — read the data stored inside a built app

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
| 🛡 Paranoid / ⚖ Balanced | read-only actions run automatically; anything that modifies the system asks for one-click approval |
| ⚡ Full | everything runs without prompting |

Destructive commands (wiping the disk, `mkfs`, `shutdown`, fork bombs, …) are **hard-blocked at every
level**, including Full.

### Policies
The **🛡 Policies** app lets you set standing rules matched against `<tool> <command>`:
- **allow** rules run matching actions without asking,
- **deny** rules block them outright (deny always wins over allow).

Patterns use `*` wildcards, e.g. `run_command git *`. Every approval prompt also has an **"Always
allow"** button that writes a policy for you.

### Folder sandbox
With `bubblewrap` installed, the agent's shell and file tools — and the Terminal — are confined to a
single folder (default `~/AgentOS`). The rest of the filesystem is read-only and other home files are
hidden. Toggle it in **Settings → Sandbox**.

### Snapshots
Take a restore point before risky changes from the **🕰 Snapshots** app. The agent also snapshots
automatically before modifying its own code. Restoring rolls back settings, data, and source, then
restarts.

---

## Memory, knowledge & soul

- **Memory (◈)** — durable facts the agent keeps across conversations.
- **Knowledge Graph (🕸)** — structured relationships (people, projects, tools) shown as a live graph.
- **Soul (☯)** — a persistent identity/personality file injected into every conversation. You can
  edit it directly, and the agent can refine it over time as it learns about you.

Clearing a conversation (the 🧹 button, or "clear session") wipes just that conversation; your
memory, graph, and soul persist.

---

## Skills

Skills are reusable procedures — house rules, runbooks, how-tos. The agent sees the list of skills
and loads one when relevant. Manage them in the **🧩 Skills** app: write one directly, or install from
a git repository or a raw Markdown URL. The agent can also save skills itself when you teach it a
process.

---

## Scheduler & jobs

The **⏱ Scheduler** runs recurring background **jobs** — a prompt executed on a schedule (interval,
daily, or once). A job runs headless and is told to deliver its result: save a report and/or message
you on Telegram. Create one from the app, or just ask: *"every morning at 9, summarize my calendar
and send it to Telegram."*

At **Balanced** autonomy, jobs stay read-only unless you approve; run **Full** (or add a policy) for
jobs that need to write files or take other actions unattended.
