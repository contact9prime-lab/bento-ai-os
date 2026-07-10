# ▲ AgentOS

**Your machine, with a brain.** A local-first *agentic operating system* — a full desktop
environment in the browser, driven by an AI agent that takes **real actions** on your computer.
Local (Ollama) or cloud (Anthropic, OpenAI, OpenRouter, or any OpenAI-compatible endpoint), with
your approval. It can even build apps for itself, extend its own code, and reach you on Telegram.

Runs at `http://127.0.0.1:8321` — private by default, and installable as a boot-time service.

📖 **Full documentation is in [`docs/`](docs/README.md)** — installation, a user guide to the
desktop and every app, the agent and its tools, building apps, integrations, the API reference, and
troubleshooting.

---

## Quickstart

```bash
cd agentic-os
uv sync                 # install dependencies (or: pip install -e .)
uv run agentos          # start the server and open the desktop in your browser
```

If **Ollama** is running, your local models are picked up automatically. Add cloud API keys under
**⚙ Settings** if you want them. That's the whole setup.

> **Tip:** builds, tool-calling, and multi-step tasks are far more reliable with a **tool-capable
> model** (any `qwen*` model, or a cloud model). Weaker local models like `gemma` won't reliably
> call tools.

---

## Install as a Debian/Ubuntu package (.deb)

A self-contained `.deb` (bundles the app **and** a Python venv with all dependencies — no network
needed at install) can be built and installed:

```bash
./packaging/build-deb.sh                                   # → packaging/dist/agentos_<ver>_amd64.deb
sudo dpkg -i packaging/dist/agentos_0.1.0_amd64.deb        # installs to /opt/agentos + app launcher + service
systemctl --user enable --now agentos                      # start at login (per user)
agentos app                                                # or launch "AgentOS" from your menu
```

`apt`/`dpkg` handles updates and removal (`sudo apt remove agentos`). The package targets the build
machine's Python (currently 3.13 / Ubuntu 25.10) — rebuild on the target's Python for other versions.
It **Recommends** `bubblewrap` (sandbox) and `xdg-utils` (host-open), and **Suggests** `ollama`,
`nodejs`, and `git` for the optional features.

## Install as a real app (auto-start on boot) — from source

```bash
uv run agentos install      # adds an app-launcher entry + a systemd user service (starts at boot)
```

This gives you:
- an **AgentOS** entry in your application menu (search "AgentOS"),
- a **systemd user service** (`agentos.service`) that's enabled and started, with **linger** on so
  it comes up at boot — even before you log in.

Manage it like any service:

```bash
systemctl --user status agentos      # is it running?
systemctl --user restart agentos     # restart (e.g. after config/source changes)
uv run agentos uninstall             # remove launcher + service (your data in ~/.agentos stays)
```

Open it as a chromeless desktop window any time:

```bash
uv run agentos app          # opens in its own window (chromium --app, or pywebview fallback)
```

---

## Launch modes

| Command | What it does |
|---|---|
| `uv run agentos` | start the server **and** open the desktop in your browser |
| `uv run agentos serve --no-browser --port 8321` | headless server (used by the boot service) |
| `uv run agentos app` | open the desktop as a native-feel window |
| `uv run agentos install` / `uninstall` | install/remove the launcher + boot service |
| `uv run agentos ask "…"` | one-shot agent run in the terminal |
| `uv run agentos ask --full "…"` | …with no approval prompts (full autonomy) |
| `uv run agentos ask --model ollama/qwen3.5:9b "…"` | …with a specific model |

---

## Requirements

- **Python ≥ 3.10** and [**uv**](https://docs.astral.sh/uv/) (or pip).
- **A model provider** — either [Ollama](https://ollama.com) running locally (recommended: a
  tool-capable model such as `qwen3.5:9b`), or a cloud API key.

Optional, unlock extra features when present:

- **bubblewrap** (`bwrap`) — the folder **sandbox** that jails the agent & terminal to one directory.
- **xdg-open** — opens files/URLs in your **host** browser and apps (standard on Linux desktops).
- **Node/npx** and/or **uvx** — to run **MCP servers** (Playwright, filesystem, git, …).
- **git** — to install **skills** from repositories.

---

## The desktop

AgentOS presents a real desktop environment, not a chat box:

- **Windows** — every app opens in a draggable, resizable window with minimize/maximize/close and
  z-ordering. A **taskbar** tracks open windows; a **Start menu** launches everything.
- **Virtual desktops** — a taskbar pager (`1 2 +`); `Ctrl+1..6` to switch, right-click a pager
  number to move the active window there. Widgets are per-desktop, so each is its own space.
- **Widgets** — pin any app as a frameless live tile on the desktop; drag, resize, and it restores
  on startup. Widgets are full apps, so they can poll, call the API, run tools, and react to clicks.
- **Command palette** — `Ctrl+Space` (or `Ctrl+K`) for Quicksilver-style fuzzy launch of any app or
  action, or "Ask Aria …" to send straight to the agent. `Ctrl+Alt+T` opens a terminal.
- **Look & feel** — AI-generated wallpapers with a local gallery, a thinking animation while the
  agent works, and optional voice (speak replies + mic dictation).

### Built-in apps

| App | What it is |
|---|---|
| 💬 **Agent Chat** | talk to the agent; streaming, tool cards, approvals, voice |
| 🌐 **Web** | opens URLs in your **real system browser** (full sites, logins, extensions) |
| 🗂 **Files** | browse the workspace; click a file to open it in your host browser/app |
| 🖥 **Terminal** | a real host shell (xterm.js over a PTY), jailed to the sandbox folder |
| 🧰 **App Studio** | describe an app in plain language and the agent **builds it live** |
| 📊 **Task Manager** | live CPU/memory/disk, processes, open windows |
| 🕸 **Knowledge Graph** | what the agent knows, as a live force-directed graph |
| ☯ **Soul** | the agent's persistent identity/personality (injected every turn) |
| ◈ **Memory** | long-term facts the agent remembers |
| 🧩 **Skills** | reusable procedures; install from a git repo or a raw `.md` URL |
| 🔌 **MCP Servers** | connect external tool servers from a catalog (Playwright, git, …) |
| ✈️ **Telegram** | control the agent from your phone; per-chat allow-list |
| 🛡 **Policies** | always-allow / always-deny rules for tools & commands |
| 📜 **Logs** | everything the system did (turns, tools, MCP, telegram, jobs) |
| 📈 **Token Analytics** | token usage over time, by model |
| ⏱ **Scheduler** | recurring background **jobs** |
| 🖼 **Personalize** | AI wallpapers + gallery |
| 🕰 **Snapshots** | restore points for the whole OS (config, data, and source) |
| ⚙ **Settings** | providers, model, autonomy, voice, sandbox, agent name |

---

## What the agent can do

The agent (default name **Aria**) has a large toolset and can drive the whole OS from chat or
Telegram. Highlights:

- **Act on the machine** — run shell commands, read/write files, fetch the web, open apps/files on
  the host, desktop notifications.
- **Deliver results** — `save_report` writes a styled HTML report into `~/AgentOS/reports/` (shows
  in Files, opens in your browser) and can ship a summary to Telegram. The agent is told to
  **finish the job** — turn research into an actual deliverable, not stop after a search.
- **Build the OS** — `create_app` makes new UI apps that get a desktop icon; `pin_widget` puts them
  on the desktop; `configure_agentos` changes settings; `add_mcp_server` connects new tool channels.
- **Grow** — `remember`/`recall`, knowledge graph (`kg_add`/`kg_query`), and `update_soul`.
- **Automate** — `schedule_task` creates headless **jobs** that run on a schedule and deliver to a
  report and/or Telegram. The agent picks the right shape: one-off → do it now; recurring → a job;
  interactive → a UI app.
- **Extend itself** — `read_source` / `develop_agentos` let it modify AgentOS's **own source code**
  (e.g. add a WhatsApp integration); it auto-snapshots first and syntax-checks before writing.

Ask in plain language: *"add the github MCP channel", "save a skill for our release process", "build
me a habit tracker and pin it to desktop 2", "every morning report social-media trends to my
Telegram", "change my wallpaper to a snowy forest".*

---

## Models & providers

Configure under **⚙ Settings**:

- **Ollama** (local) — auto-discovered; nothing leaves your machine.
- **Anthropic**, **OpenAI**, **OpenRouter** (one key → hundreds of models), or any **OpenAI-
  compatible** endpoint (LM Studio, vLLM, Groq, …).

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `OPENROUTER_API_KEY` env vars are picked up automatically.
Switch models mid-flight from the chat window's model dropdown.

---

## Safety

- **Autonomy levels** — 🛡 Paranoid / ⚖ Balanced auto-run read-only actions and ask before anything
  that modifies the system; ⚡ Full runs everything. Destructive commands (`rm -rf /`, `mkfs`,
  `shutdown`, …) are **hard-blocked** at every level.
- **Policies** — add always-allow / always-deny rules (with `*` wildcards) matched against
  `<tool> <command>`. "Always allow" is one click on any approval prompt.
- **Folder sandbox** — with bubblewrap, the agent's shell/file tools and the Terminal are jailed to
  one folder (default `~/AgentOS`): the rest of the filesystem is read-only and other home files are
  hidden. Toggle it in Settings.
- **Snapshots** — take a restore point before risky changes; the agent auto-snapshots before editing
  its own code. Restoring rolls back config, data, and source, then restarts.
- **Private by default** — binds to `127.0.0.1`. The host-open endpoint only opens `http(s)` URLs or
  files **inside the workspace**.

---

## Telegram

1. Message **@BotFather** → `/newbot` → copy the token.
2. Paste it in the **Telegram** app and enable the bridge.
3. Send **any** message to your bot — the first private chat becomes the owner; others are listed and
   can be enabled/disabled per chat.

The agent has all its tools over Telegram, so you can build apps, change themes, run jobs, etc. from
your phone. Risky actions send inline **Allow / Deny** buttons and wait for your tap. `/clear` resets
the session, `/status` pings.

---

## MCP servers (tool "channels")

Add external tool servers from the **MCP Servers** catalog (Playwright browser automation,
filesystem, fetch, git, GitHub, Postgres, Slack, Brave/DuckDuckGo search, and more) or a custom
`stdio`/`http` server. Their tools appear to the agent as `mcp_<server>_<tool>`, and to built apps
via `POST /api/tool`. You can also just ask the agent: *"add the playwright channel."*

---

## Programmable

- **CLI** — `agentos ask "…"` for one-shot runs.
- **REST** — e.g. `POST /api/chat {text}`, `GET /api/system`, `GET /api/files`, `POST /api/tool
  {name,args}`, `GET /api/analytics/tokens`, plus endpoints for apps, widgets, skills, snapshots,
  wallpapers, MCP, and Telegram.
- **WebSocket** — `/ws` (streaming chat + approvals + build events), `/ws/terminal` (host PTY).
- **Apps** you build run in a same-origin iframe and can call all of the above.

---

## Architecture

```
agentos/
├── __main__.py    # CLI entry: serve · app · install · uninstall · ask
├── agent.py       # the kernel: plan → act (tools) → observe loop, approval gates, personas
├── providers.py   # unified streaming chat: Ollama / Anthropic / OpenAI / OpenRouter / custom
├── tools.py       # the hands: shell, files, web, apps, reports, memory, KG, soul, skills,
│                  #   widgets, wallpaper, MCP dispatch, self-modification, sandbox jail
├── mcp_client.py  # Model Context Protocol client (stdio + http servers)
├── telegram.py    # Telegram bridge: chat registry, approval keyboard, headless turns
├── memory.py      # SQLite: conversations, memories, tasks, logs, KG, skills, apps, chats
├── scheduler.py   # background job runner
├── desktop.py     # native app window + installer (.desktop launcher, systemd service)
├── server.py      # FastAPI: desktop UI, REST API, WebSocket streams, host-open, file serving
└── ui/
    ├── index.html # the entire desktop environment — zero build step, single file
    └── assets/    # vendored xterm.js (terminal)
```

**State lives in `~/.agentos/`:** `config.json`, `agentos.db` (SQLite), `soul.md`, `wallpapers/`,
`snapshots/`. The agent's working directory / sandbox root is `~/AgentOS/` (reports land in
`~/AgentOS/reports/`).
