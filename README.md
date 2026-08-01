# ▲ AgentOS — a local-first agentic operating system

**Your machine, with a brain.** AgentOS is a self-hosted **AI desktop environment** that runs in
your browser: a full desktop — windows, apps, files, terminal — driven by an **autonomous AI
agent** that takes **real actions** on your computer. Use local models via
[Ollama](https://ollama.com) for total privacy, or cloud models (Anthropic Claude, OpenAI,
OpenRouter, or any OpenAI-compatible endpoint) — always with your approval. The agent can browse,
build its own apps, schedule jobs, remember what it learns, extend its own source code, and reach
you on Telegram.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platforms](https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20Windows-lightgrey)
![Local-first](https://img.shields.io/badge/AI-local--first%20·%20Ollama%20·%20cloud%20optional-5eead4)

Runs at `http://127.0.0.1:8321` — private by default, installable as a boot-time service.

![AgentOS desktop — AI agent chat, file manager, and quick settings in a browser-based desktop environment](docs/screenshots/desktop.png)

**Full documentation is in [`docs/`](docs/README.md)** — installation, a user guide to the
desktop and every app, the agent and its tools, building apps, integrations, the API reference, and
troubleshooting.

---

## See it in action

| | |
|---|---|
| ![Chat with the AI agent — streaming replies, tool calls, and approvals](docs/screenshots/chat.png) **Agent Chat** — talk to your machine; streaming replies, tool cards, approvals, voice | ![Team app — subagents, workflows, and observability](docs/screenshots/team.png) **Team** — specialist subagents and visual workflows, with per-step model mixing |
| ![Built-in documentation app rendering the full manual](docs/screenshots/docs.png) **Docs** — the full manual lives inside the OS | ![App store — one-click apps, skills, and MCP channels](docs/screenshots/store.png) **Store** — one-click apps, skills, and MCP tool channels |

### Five design languages, not five palettes

![The five built-in design-language themes: Bento, Liquid Glass, Spatial, Claymorphism, Minimalism](docs/screenshots/themes.png)

**Bento · Liquid Glass · Spatial · Claymorphism · Minimalism.** Each re-cuts the whole shell —
surfaces, radii, elevation, blur, type — and brings its own wallpaper. The wallpapers ship with
AgentOS as SVG: a few KB each, sharp from a phone to a 4K panel.
[More →](docs/desktop.md#themes)

### One desktop, every screen

![AgentOS on a phone: the lock screen, the desktop laid out for a phone, and an app as a full-bleed sheet](docs/screenshots/mobile.png)

Phone, tablet, workstation — the same desktop, adapting. Windows become full-bleed sheets, the
dock spans the bottom edge, popovers become sheets. Turn on **Remote access** and reach it from
your phone over your network, behind a passphrase; *Add to Home Screen* makes it a full-screen
app. [Remote access →](docs/remote-access.md) · [Responsive layout →](docs/desktop.md#phone-tablet-desktop)

### It can *be* the desktop, not just live on one

![A native Wayland application above the AgentOS desktop, with the AgentOS menu bar reserved above it and the dock reserved below it](docs/screenshots/session-native-window.png)

Log in and get AgentOS as your Linux session. The desktop is drawn as a **Wayland layer surface on
the background layer**, so native application windows are above it in normal stacking order — not
because anything gets raised or lowered, but because that is what "background" means. The menu bar
and dock sit in bands **reserved with the compositor**, the same mechanism a GNOME or KDE panel
uses, so a full-screen app stops at their edges instead of swallowing them.

![Two native terminals snapped to the left and right halves of the AgentOS desktop](docs/screenshots/session-snapped.png)

Full window management for native apps: snap to halves and quarters, tile, float, layouts,
keyboard resize, workspaces, minimise, and an Alt-Tab switcher — with the AgentOS taskbar and menu
bar tracking whichever app has focus. [The session UI →](docs/session-ui.md)

### Install applications, from AgentOS

![The Applications app searching the machine's package catalogue, with install buttons per result](docs/screenshots/app-store.png)

A desktop you cannot install software on is a demo. *Applications → Get apps…* searches the
machine's own catalogue — AppStream, Flatpak or apt — and shows you the exact command before it
runs. Flatpak is preferred where it exists because a per-user install needs no password at all.
AgentOS mirrors nothing and bundles nothing; it asks the package manager you already have.

### Your real screen, on your phone, in the browser

![The AgentOS Remote Desktop open in a phone browser, showing the machine's real screen with a native app on it and a toolbar of keys a phone keyboard lacks](docs/screenshots/phone-remote-desktop.png)

**Remote access** sends you the AgentOS shell, which is HTML and travels perfectly — but a native
app is pixels on the machine's own display and was never part of the page. **Remote Desktop**
closes that: AgentOS relays the screen over its *own* authenticated connection, so you get the
real desktop, clickable, with no VNC app to install on the phone.

The shape is the point — the VNC server stays on `127.0.0.1` and never goes near the network; what
protects it is the AgentOS passphrase you already use. [Remote access →](docs/remote-access.md)

### Automations & hot corners

![The Automations app with saved routines and the hot-corner map, and the step builder](docs/screenshots/automations.png)

Name a sequence once — open these apps, switch theme, run this Python, call that MCP tool, put the
agent on a task — and run it forever after from the prompt bar, a hot corner, a schedule, or by
asking for it by name. [More →](docs/desktop.md#automations)

---

## Why AgentOS

- **A real desktop, not a chat box** — draggable windows, taskbar, virtual desktops, widgets,
  themes, a command palette, and 25+ built-in apps.
- **An agent with hands** — shell commands, file management, web research, desktop notifications,
  scheduled jobs, HTML reports, and app-building, all from plain language.
- **Local-first and private** — everything can run on your hardware with Ollama; nothing leaves
  your machine unless you add a cloud key. Binds to localhost only, until you deliberately turn on
  passphrase-protected [remote access](docs/remote-access.md) to reach it from your phone.
- **The whole lifecycle under one roof** — **Train · Test · Operate · Build · Ship · Manage**,
  live on one screen (Mission Control): fine-tune your own models on your GPU (the Train app,
  LoRA included), test-gate every self-modification, run scheduled jobs, build apps, and ship
  them to GitHub with first-class git tools.
- **Self-extending** — the agent builds new UI apps for itself (App Studio), installs skills and
  MCP tool servers, and can even modify AgentOS's own source code (with auto-snapshots and a
  test suite that must pass before a restart).
- **Memory that compounds** — two-tier memory, a live knowledge graph, and a persistent "soul",
  learned automatically after every conversation.
- **Safe by design** — autonomy levels, approval prompts, allow/deny policies, a bubblewrap folder
  sandbox, hard-blocked destructive commands, and one-click restore points.

---

## Quickstart

```bash
cd agentic-os
uv sync                 # install dependencies (or: pip install -e .)
uv run agentos          # start the server and open the desktop in your browser
```

If **Ollama** is running, your local models are picked up automatically. Add cloud API keys under
**Settings** if you want them. That's the whole setup.

> **Tip:** builds, tool-calling, and multi-step tasks are far more reliable with a **tool-capable
> model** (any `qwen*` model, or a cloud model). Weaker local models like `gemma` won't reliably
> call tools.

---

## Install as a Debian/Ubuntu package (.deb)

A self-contained `.deb` (bundles the app **and** a Python venv with all dependencies — no network
needed at install) can be built and installed:

```bash
./packaging/build-deb.sh                                   # → packaging/dist/agentos_<ver>_<arch>.deb
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
uv run agentos install      # app launcher + a background service that starts at login/boot
```

Works on every OS — the right native mechanism is used automatically:

- **Linux** — a `.desktop` launcher + a **systemd user service** (with linger, so it starts at
  boot even before you log in).
- **macOS** — an `AgentOS.app` in `~/Applications` (Launchpad/Spotlight) + **LaunchAgents** that
  start the server and open the window at login.
- **Windows** — a Start Menu shortcut + **Startup entries**.

Manage it like any service (Linux shown; macOS uses `launchctl`):

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
| `uv run agentos tui` | the whole OS in a terminal (**TUI**) — for a server or a headless Pi |
| `uv run agentos installer` | detect this distro, install what's missing, add AgentOS to the login screen (**SUI**) — [details](docs/session-ui.md) |

The same program has three faces, and every feature is built for all three: a **GUI** window on
another desktop, a **TUI** for machines with no screen, and the **SUI** where AgentOS *is* the
Linux session.

---

## Requirements

- **Python ≥ 3.10** and [**uv**](https://docs.astral.sh/uv/) (or pip).
- **A model provider** — either [Ollama](https://ollama.com) running locally (recommended: a
  tool-capable model such as `qwen3.5:9b`), or a cloud API key.

Optional, unlock extra features when present:

- **The Linux session (SUI)** — `sway` and friends for the compositor engine, plus `python3-gi`,
  `gir1.2-gtklayershell-0.1` and `gir1.2-webkit2-4.1` for the native desktop surface. AgentOS
  bundles none of them: the installer offers them, `agentos install-session` prints the exact line,
  and System Settings → Components lists them with their licences. Without them the session still
  runs, drawing the desktop in a Chromium window. [Details →](docs/session-ui.md)
- **wayvnc + novnc** — Remote Desktop from a phone browser, relayed through AgentOS on loopback.
- **bubblewrap** (`bwrap`) — the folder **sandbox** that jails the agent & terminal to one directory (Linux).
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
  agent works, and optional voice (speak replies + mic dictation). Paste images straight from the
  clipboard into chat for vision-capable models.

### Built-in apps

| App | What it is |
|---|---|
| **Agent Chat** | talk to the agent; streaming, tool cards, approvals, voice, image paste |
| **Web** | opens URLs in your **real system browser** (full sites, logins, extensions) |
| **Files** | browse the workspace; click a file to open it in your host browser/app |
| **Terminal** | a real host shell (xterm.js over a PTY), jailed to the sandbox folder |
| **App Studio** | describe an app in plain language and the agent **builds it live** |
| **Task Manager** | live CPU/memory/disk, processes, open windows |
| **Knowledge Graph** | what the agent knows, as a live force-directed graph |
| **Soul** | the agent's persistent identity/personality (injected every turn) |
| ◈ **Memory** | user & session memory with auto-learn + semantic recall; pin, edit, promote, delete |
| **Profile** | everything the agent knows about you, in one place |
| **Team** | subagents & visual workflows (mix models per step) + data-plane observability |
| **Docs** | this manual, inside the OS (also tab 8 in the TUI) |
| **Skills** | reusable procedures; install from a git repo or a raw `.md` URL |
| **MCP Servers** | connect external tool servers from a catalog (Playwright, git, …) |
| **Telegram** | control the agent from your phone; per-chat allow-list |
| **Policies** | always-allow / always-deny rules for tools & commands |
| **Logs** | everything the system did (turns, tools, MCP, telegram, jobs) |
| **Token Analytics** | token usage over time, by model |
| **Scheduler** | recurring background **jobs** |
| **Personalize** | AI wallpapers + gallery (Gemini / OpenAI / free fallback) |
| **Snapshots** | restore points for the whole OS (config, data, and source) |
| **Settings** | providers, model, autonomy, voice, sandbox, agent name |

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
- **Grow** — two-tier memory (`remember`/`recall`/`forget`, user- and session-scoped), a knowledge
  graph (`kg_add`/`kg_query`), `update_soul` — plus **auto-learn**: a background pass after every
  chat turn extracts memories and graph facts on its own, so nothing depends on the model
  remembering to call `remember`.
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

Configure under **Settings**:

- **Ollama** (local) — auto-discovered; nothing leaves your machine.
- **Anthropic**, **OpenAI**, **OpenRouter** (one key → hundreds of models), or any **OpenAI-
  compatible** endpoint (LM Studio, vLLM, Groq, …).
- **Image generation** — Google Gemini or OpenAI image models when a key is set, with a free
  fallback service otherwise.

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, and `GOOGLE_API_KEY` env vars are
picked up automatically. Switch models mid-flight from the chat window's model dropdown.

---

## Safety

- **Autonomy levels** — Paranoid / Balanced auto-run read-only actions and ask before anything
  that modifies the system; Full runs everything. Destructive commands (`rm -rf /`, `mkfs`,
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
`stdio`/`http` server — AgentOS speaks the **Model Context Protocol**. Their tools appear to the
agent as `mcp_<server>_<tool>`, and to built apps via `POST /api/tool`. You can also just ask the
agent: *"add the playwright channel."*

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
├── host.py        # host integration: native apps, volume/battery/network, settings panels
├── desktop.py     # native window + installers (Linux systemd / macOS LaunchAgents / Windows)
├── server.py      # FastAPI: desktop UI, REST API, WebSocket streams, host-open, file serving
└── ui/
    ├── index.html # the entire desktop environment — zero build step, single file
    └── assets/    # vendored xterm.js (terminal)
```

**State lives in `~/.agentos/`:** `config.json`, `agentos.db` (SQLite), `soul.md`, `wallpapers/`,
`snapshots/`. The agent's working directory / sandbox root is `~/AgentOS/` (reports land in
`~/AgentOS/reports/`).

---

*AgentOS is an open, local-first alternative to cloud AI assistants: an agentic OS, AI desktop,
and automation platform you run yourself — on Linux, macOS, or Windows.*
