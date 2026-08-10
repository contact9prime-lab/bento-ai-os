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

### What it remembers of the conversation itself

A turn is replayed the whole thread, and two things about that are easy to get wrong.

**Tool traces travel.** What the agent *did* on an earlier turn — which file it read, what
came back, what failed — is replayed compactly alongside what it said. Without that, "now do
the same for the other one" either re-runs everything or gets answered from a file the model
can no longer see.

**Long threads are compacted, not killed.** The desktop's persistent thread grows forever;
once it outgrows the model's window, the oldest turns are distilled into a rolling summary
that is generated once and stored on the conversation. You are told in the conversation when
it happens — a thread that has been summarised behaves differently from one that has not, and
you are the only one who can say the summary lost something. Tune it under `history` in
config (`budget_tokens`, `tool_trace`, `trace_chars`, `compact`, `model`), or turn compaction
off in Settings → Agent, in which case old turns are dropped and you are told that instead.

---

## Talking while it works

You never have to wait for a turn to finish before typing the next thing. Send it and the message is
**queued** — it appears in the *Up next* strip above the composer, this chat's visible to-do list.
(With the composer empty, the same button is still the stop button.)

Between steps — never in the middle of a tool call — the running turn decides what each queued
message is:

- **It changes what's happening now** ("actually make it a bullet list", "put it in Documents
  instead") → it is folded into the run in flight. A `↩ took in: …` line marks the moment in the
  transcript, and the rest of the turn accounts for it.
- **It's a separate ask** ("also tell me a joke afterwards") → it waits, and starts as its own turn
  the moment this one ends. Queued messages run in the order you typed them.

The decision is made by a small model call that starts the instant you hit send, so it runs
alongside the reply already streaming rather than holding it up. It uses `memory.model` if you have
a small model configured for that, and falls back to the message's wording — defaulting to *wait* —
if no model answers in time. Set `steer_queued_messages: false` in the config to skip the judgement
entirely and have every queued message simply wait its turn.

Stopping a turn (`◼`, `Ctrl+.`) drops its backlog too — stop means stop. You can also drop a single
queued message with the `✕` beside it.

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

### How many of them the model sees at once

There are ~90 built-in tools and their JSON schemas are ~11,600 tokens. Sent on every call,
against a model configured at `ollama_num_ctx: 24576`, that is 47% of the context window gone
before the system prompt or a word of your conversation.

That is the argument for narrowing the list, and AgentOS can do it — but **it ships off**,
because the argument lost to the measurement. `agentos eval` on this machine's local model,
same cases, only the setting different:

| `tools.scope` | passed | median case |
|---|---|---|
| `all` (default) | 21/22 | 9.9s |
| `always` | 19/22 | 8.0s |

Narrowing made each step cheaper and the agent slightly worse, twice running. Small sample,
but nothing in it justifies turning this on for everyone. Set `tools.scope: "auto"` to narrow
only when the schemas would eat a real share of the window (the decision reads the configured
window, never the model's name — a 128k local model is treated as the large model it is), and
check it against your own model with the harness.

When narrowing is on, the model always sees a core set (files, shell, memory, reports),
anything the request itself points at, and anything this turn has already used. It is *told*
what it cannot see, and `find_tools("send a telegram message")` puts the matches on the table
for its next step — tool sets are rebuilt each step, so a miss costs one step, not the turn.

| setting | meaning |
|---|---|
| `tools.scope` | `all` (default, never narrow) · `auto` (narrow on a tight window) · `always` |
| `tools.budget` | how many tools to offer when narrowing (default 30) |
| `tools.window_share` | narrow once schemas exceed this share of the window (default 0.20) |
| `tools.cloud_context` | assumed window when the provider does not tell us (default 128000) |

`find_tools` is offered either way: a model that cannot spot the right tool in a list of
ninety can now ask for it in plain words instead of telling you the OS cannot do it.

---

## Asking the OS about itself

The manual you are reading is in the agent's retrieval index, so a question about how *this
build* behaves is answered from these pages rather than from the model's memory of some other
project. The Docs app has an ask box on top of every page:

![The Docs app answering a question about this OS, with the answer grounded in the manual](screenshots/docs-ask.png)

It is **agentic retrieval, not a one-shot lookup**: the agent calls `search_docs`, reads what
comes back, and searches again with better words when the first pass misses — because a real
question ("why did my scheduled flow stop delegating?") is usually answered by two or three
pages that no single similarity search returns together. The reply names the page it used, so
the answer is checkable against the thing it came from.

`search_docs` is an ordinary tool, so the agent reaches for it in any conversation, not only
in the Docs app. If the manual genuinely does not cover something, it says so rather than
filling the gap from memory.

> One limitation, stated plainly: when the machine is set to **forward turns to an executor**
> (Settings → Executors), the executor answers with *its* tools, and `search_docs` is not
> among them. The Docs ask box is grounded only when the built-in agent is answering.

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
