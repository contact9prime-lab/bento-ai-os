# Bento Box AI — a local-first agentic operating system

**Your machine, with a brain.** Bento Box AI is a self-hosted **AI desktop environment**: a full
desktop — windows, apps, files, terminal — driven by an **autonomous AI agent** that takes **real
actions** on your computer. Use local models via [Ollama](https://ollama.com) for total privacy, or
cloud models (Anthropic Claude, OpenAI, OpenRouter, or any OpenAI-compatible endpoint) — always with
your approval. The agent can browse, build its own apps, schedule jobs, remember what it learns,
extend its own source code, and reach you on Telegram or WhatsApp.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platforms](https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20Windows-lightgrey)
![Local-first](https://img.shields.io/badge/AI-local--first%20·%20Ollama%20·%20cloud%20optional-5eead4)

Runs at `http://127.0.0.1:8321` — private by default, installable as a boot-time service.

![The Bento Box AI desktop — AI agent chat, file manager, and quick settings in a browser-based desktop environment](docs/screenshots/desktop.png)

**Full documentation is in [`docs/`](docs/README.md)** — installation, a user guide to the desktop
and every app, the agent and its tools, building apps, integrations, the API reference, and
troubleshooting.

---

## The first thing it asks you is what job to do

Setup ends on a question, not a door: **give me a job.** Pick one of three, answer two questions,
and this machine is doing something for you before you have opened a single app.

![The Jobs screen: three recipes — brief me every morning, watch a folder, tell me when a page changes — with the chosen one's questions and exactly what it will be allowed to do](docs/screenshots/jobs.png)

| | |
|---|---|
| **Brief me every morning** | reads up on the things you follow overnight and leaves one page waiting |
| **Watch a folder for me** | notices what lands in a folder *you choose*, works out what it is, tells you |
| **Tell me when a page changes** | checks a page and speaks up only when something real has changed |

Two things it will not do. It will not grant itself anything you have not seen: the panel prints
the exact permissions before you press the button, computed by the same code that writes them —
"reads `~/Downloads/*`, and nothing else". And it will not offer a way of reaching you that does not
work: an unpaired Telegram is shown greyed with the sentence that would fix it, never hidden and
never quietly substituted.

The last button is **"Run it now, so I can see it work"** — because a schedule you have not seen
fire is a promise, and a new user has no reason to believe one.

A job is a *flow*, not a new kind of thing: same scheduler, same permission gate, same audit
ledger. On a headless box: `bento job recipes`, then `bento job add morning-brief --topics "…"`.

---

## Three faces, one program

Bento runs in three places, and **every feature is built for all three**. This is the first
question asked of any change, not the last.

| | What it is | Start it with |
|---|---|---|
| **GUI** | a window (or tab) on macOS, Windows or Linux. Nothing extra to install | `bento` |
| **TUI** | the whole OS in a terminal — for a server, or a headless Pi over SSH | `bento tui` |
| **SUI** | Bento **is** your Linux session: it owns the machine | `bento installer` |

> The command is `bento`. `agentos` still works and always will — it is in people's shell history,
> systemd units and scripts, and a rename we chose should not cost them that.

---

## See it in action

| | |
|---|---|
| ![Chat with the AI agent — streaming replies, tool calls, and approvals](docs/screenshots/chat.png) **Agent Chat** — talk to your machine; streaming replies, tool cards, approvals, voice | ![Team app — subagents, workflows, and observability](docs/screenshots/team.png) **Team** — specialist subagents and visual workflows, with per-step model mixing |
| ![Built-in documentation app rendering the full manual](docs/screenshots/docs.png) **Docs** — the full manual lives inside the OS | ![App store — one-click apps, skills, and MCP channels](docs/screenshots/store.png) **Store** — one-click apps, skills, and MCP tool channels |

### Windows that behave like windows

![Four Bento windows stacked on the desktop: the focused one carries an accent ring and the full shadow, the rest recede](docs/screenshots/windows.png)

A window opens **where you left it** — position and size are remembered per app — and a window
opening for the first time cascades by more than a title bar, so the one underneath is still
readable. The focused window carries an accent ring and the full shadow; the others recede. The ✦
in the title bar is the agent *inside that app*: ask it about what is on screen without leaving it.

### Five design languages, not five palettes

![The five built-in design-language themes: Bento, Liquid Glass, Spatial, Claymorphism, Minimalism](docs/screenshots/themes.png)

**Bento · Liquid Glass · Spatial · Claymorphism · Minimalism.** Each re-cuts the whole shell —
surfaces, radii, elevation, blur, type — and brings its own wallpaper. The wallpapers ship as SVG:
a few KB each, sharp from a phone to a 4K panel. [More →](docs/desktop.md#themes)

Glass is the most expensive thing a desktop can draw, and the cost compounds with every window you
open. **Themes → Effects** measures your machine and turns it down only if it has to — five windows
in Liquid Glass went from 6.5fps to 27 (reduced) or 60 (off).

### It reaches you where you already are

![The WhatsApp channel in Settings: the four Cloud API fields, the callback URL to paste into Meta's console, the paired number, and whether the 24-hour window is open](docs/screenshots/channels-whatsapp.png)

**Telegram and WhatsApp are native channels** — the same conversation, the same memory, the same
tools and the same approval buttons as at the desk. Not a notification bridge: a reply from your
phone continues the thread you started this morning.

WhatsApp uses Meta's Cloud API, and Bento is honest about its one real limit: outside 24 hours from
your last message, WhatsApp will not carry a free-form reply at all. The card says whether that
window is open, a send that cannot go through says so and how to fix it, and a scheduled job that
delivers to WhatsApp saves its report first so nothing is lost. [Setup →](docs/whatsapp.md)

### One desktop, every screen

![Bento Box AI on a phone: the lock screen, the desktop laid out for a phone, and an app as a full-bleed sheet](docs/screenshots/mobile.png)

Phone, tablet, workstation — the same desktop, adapting. Windows become full-bleed sheets, the dock
spans the bottom edge, popovers become sheets. Turn on **Remote access** and reach it from your phone
over your network, behind a passphrase; *Add to Home Screen* makes it a full-screen app.
[Remote access →](docs/remote-access.md) · [Responsive layout →](docs/desktop.md#phone-tablet-desktop)

### It can *be* the desktop, not just live on one

![A native Wayland application above the Bento desktop, with the menu bar reserved above it and the dock reserved below it](docs/screenshots/session-native-window.png)

Log in and get Bento as your Linux session. The desktop is drawn as a **Wayland layer surface on the
background layer**, so native application windows are above it in normal stacking order — not because
anything gets raised or lowered, but because that is what "background" means. The menu bar and dock
sit in bands **reserved with the compositor**, the same mechanism a GNOME or KDE panel uses, so a
full-screen app stops at their edges instead of swallowing them.

![Two native terminals snapped to the left and right halves of the Bento desktop](docs/screenshots/session-snapped.png)

Full window management for native apps: snap to halves and quarters, tile, float, layouts, keyboard
resize, workspaces, minimise, and an Alt-Tab switcher — with the taskbar and menu bar tracking
whichever app has focus. [The session UI →](docs/session-ui.md)

### Install applications, from inside Bento

![The Applications app searching the machine's package catalogue, with install buttons per result](docs/screenshots/app-store.png)

A desktop you cannot install software on is a demo. *Applications → Get apps…* searches the machine's
own catalogue — AppStream, Flatpak or apt — and shows you the exact command before it runs. Flatpak
is preferred where it exists because a per-user install needs no password at all. Bento mirrors
nothing and bundles nothing; it asks the package manager you already have.

### Your real screen, on your phone, in the browser

![Bento's Remote Desktop open in a phone browser, showing the machine's real screen with a native app on it and a toolbar of keys a phone keyboard lacks](docs/screenshots/phone-remote-desktop.png)

**Remote access** sends you the Bento shell, which is HTML and travels perfectly — but a native app
is pixels on the machine's own display and was never part of the page. **Remote Desktop** closes
that: Bento relays the screen over its *own* authenticated connection, so you get the real desktop,
clickable, with no VNC app to install on the phone.

The shape is the point — the VNC server stays on `127.0.0.1` and never goes near the network; what
protects it is the passphrase you already use. [Remote access →](docs/remote-access.md)

### Automations & hot corners

![The Automations app with saved routines and the hot-corner map, and the step builder](docs/screenshots/automations.png)

Name a sequence once — open these apps, switch theme, run this Python, call that MCP tool, put the
agent on a task — and run it forever after from the prompt bar, a hot corner, a schedule, or by
asking for it by name. [More →](docs/desktop.md#automations)

---

## Why Bento Box AI

- **A real desktop, not a chat box** — draggable windows, taskbar, virtual desktops, widgets,
  themes, a command palette, and 25+ built-in apps.
- **An agent with hands** — shell commands, file management, web research, desktop notifications,
  scheduled jobs, HTML reports, and app-building, all from plain language.
- **Local-first and private** — everything can run on your hardware with Ollama; nothing leaves your
  machine unless you add a cloud key. Binds to localhost only, until you deliberately turn on
  passphrase-protected [remote access](docs/remote-access.md).
- **The whole lifecycle under one roof** — **Train · Test · Operate · Build · Ship · Manage**, live
  on one screen (Mission Control): fine-tune your own models on your GPU, test-gate every
  self-modification, run scheduled jobs, build apps, and ship them to GitHub.
- **Self-extending** — the agent builds new UI apps for itself (App Studio), installs skills and MCP
  tool servers, and can modify Bento's own source code (with auto-snapshots and a test suite that
  must pass before a restart).
- **Memory that compounds** — two-tier memory, a live knowledge graph, and a persistent "soul",
  learned automatically after every conversation.
- **Safe by design** — autonomy levels, approval prompts, allow/deny policies, a bubblewrap folder
  sandbox, hard-blocked destructive commands, and one-click restore points.

---

## Quickstart

```bash
uv sync                 # install dependencies (or: pip install -e .)
uv run bento            # start the server and open the desktop in your browser
```

If **Ollama** is running, your local models are picked up automatically. Add cloud API keys under
**Settings** if you want them. That's the whole setup.

> **Tip:** builds, tool-calling, and multi-step tasks are far more reliable with a **tool-capable
> model** (any `qwen*` model, or a cloud model). Weaker local models like `gemma` won't reliably
> call tools.

---

## Run it as your Linux desktop (SUI)

```bash
uv run bento installer      # detects your distro, installs what's missing, adds it to the login screen
```

Then log out and pick **Bento Box AI** at the login screen. Your existing desktop is untouched —
switching back is logging out and picking Ubuntu again.

The installer detects the distribution, names every package it wants and why, and asks before
installing anything. Two groups: the compositor engine (sway and friends, MIT), and the native
desktop surface (`python3-gi`, `python3-gi-cairo`, gtk-layer-shell, WebKitGTK) that lets the desktop
be a real Wayland surface rather than a browser window.

**Bento ships and redistributes none of them.** gtk-layer-shell is MIT, but GTK, PyGObject and
WebKitGTK are LGPL, and what this project *depends* on stays permissive — so they are asked for, with
the licences in view. Without them the session still runs, drawing the desktop in a Chromium window.
[Licensing →](docs/licensing.md) · [The session UI →](docs/session-ui.md)

If anything about the desktop misbehaves, one command tells you why:

```bash
uv run bento doctor --session   # probes what can actually draw on THIS machine, and says so
```

It checks the interpreter, GTK's display, the compositor's layer-shell support, and whether WebKit
can render *and keep rendering* — in a window and on a layer surface — then gives a verdict. Probes
run in subprocesses, because the failures it looks for are aborts and segfaults, and a probe that
crashes the doctor cannot report that it crashed.

---

## Install as a Debian/Ubuntu package (.deb)

A self-contained `.deb` (bundles the app **and** a Python venv with all dependencies — no network
needed at install):

```bash
./packaging/build-deb.sh                                   # → packaging/dist/agentos_<ver>_<arch>.deb
sudo dpkg -i packaging/dist/agentos_0.1.0_amd64.deb        # installs to /opt/agentos + launcher + service
systemctl --user enable --now agentos                      # start at login (per user)
bento app                                                  # or launch it from your menu
```

`apt`/`dpkg` handles updates and removal. It **Recommends** `bubblewrap` (sandbox) and `xdg-utils`,
and **Suggests** `ollama`, `nodejs`, and `git`. The desktop package additionally **Suggests** the
session-UI stack and `wayvnc`/`novnc` — suggested rather than depended on, because apt installs
Recommends by default and that would be bundling with a softer name.

## Install as a real app (auto-start on boot) — from source

```bash
uv run bento install      # app launcher + a background service that starts at login/boot
```

The right native mechanism is used automatically: a `.desktop` launcher plus a **systemd user
service** on Linux (with linger, so it starts at boot), an app bundle plus **LaunchAgents** on
macOS, a Start Menu shortcut plus **Startup entries** on Windows.

```bash
systemctl --user status agentos      # is it running?
uv run bento uninstall               # remove launcher + service (your data stays)
uv run bento app                     # open as a chromeless desktop window any time
```

---

## Launch modes

| Command | What it does |
|---|---|
| `uv run bento` | start the server **and** open the desktop in your browser |
| `uv run bento serve --no-browser --port 8321` | headless server (used by the boot service) |
| `uv run bento app` | open the desktop as a native-feel window |
| `uv run bento tui` | the whole OS in a terminal (**TUI**) |
| `uv run bento installer` | detect this distro and set up the Linux session (**SUI**) |
| `uv run bento doctor` / `doctor --session` | environment check / what can draw the desktop here |
| `uv run bento apps search \| install \| remove` | native applications, from a terminal |
| `uv run bento remote --on --passphrase '…'` | reach this desktop from your phone |
| `uv run bento remote-desktop --on` | the browser remote desktop (real screen, native apps) |
| `uv run bento ask "…"` | one-shot agent run in the terminal (`--full`, `--model …`) |

---

## Requirements

- **Python ≥ 3.10** and [**uv**](https://docs.astral.sh/uv/) (or pip).
- **A model provider** — either [Ollama](https://ollama.com) locally (recommended: a tool-capable
  model such as `qwen3.5:9b`), or a cloud API key.

Optional, unlock extra features when present — `bento installer` offers each with its licence:

- **The Linux session (SUI)** — `sway` and friends, plus `python3-gi`, `python3-gi-cairo`,
  `gir1.2-gtklayershell-0.1` and `gir1.2-webkit2-4.1`. [Details →](docs/session-ui.md)
- **wayvnc + novnc** — Remote Desktop from a phone browser, relayed on loopback.
- **bubblewrap** (`bwrap`) — the folder **sandbox** that jails the agent and terminal to one folder.
- **Node/npx** and/or **uvx** — to run **MCP servers** (Playwright, filesystem, git, …).
- **git** — to install **skills** from repositories.

---

## The desktop

- **Windows** — every app opens in a draggable, resizable window with minimize/maximize/close and
  z-ordering. A **taskbar** tracks open windows; a **Start menu** launches everything.
- **Windows that sleep** — a window you cannot see stops doing periodic work and refreshes the
  moment it comes back. Six apps open and all minimised went from 25 requests per 10s to 2.
- **Virtual desktops** — a taskbar pager; `Ctrl+1..6` to switch, right-click to move a window there.
  Widgets are per-desktop, so each is its own space.
- **Widgets** — pin any app as a frameless live tile; drag, resize, and it restores on startup.
- **Command palette** — `Ctrl+Space` (or `Ctrl+K`) for fuzzy launch of any app or action, or
  "Ask Aria …" to send straight to the agent. `Ctrl+Alt+T` opens a terminal.
- **Look & feel** — AI-generated wallpapers with a local gallery, a thinking animation while the
  agent works, and optional voice. Paste images straight into chat for vision-capable models.

### Built-in apps

| App | What it is |
|---|---|
| **Agent Chat** | talk to the agent; streaming, tool cards, approvals, voice, image paste |
| **Applications** | every installed desktop app — launch them, or install new ones |
| **Remote Desktop** | the machine's real screen, clickable, from here or from a phone |
| **Host Screen** | a refreshing still of the real display, including native app windows |
| **Web** | opens URLs in your **real system browser** (full sites, logins, extensions) |
| **Files** | browse the workspace; click a file to open it in your host browser/app |
| **Terminal** | a real host shell (xterm.js over a PTY), jailed to the sandbox folder |
| **App Studio** | describe an app in plain language and the agent **builds it live** |
| **Task Manager** | live CPU/memory/disk, processes, open windows (and which are sleeping) |
| **Knowledge Graph** | what the agent knows, as a live force-directed graph |
| **Soul** | the agent's persistent identity/personality (injected every turn) |
| **Memory** | user & session memory with auto-learn + semantic recall |
| **Profile** | everything the agent knows about you, in one place |
| **Team** | subagents & visual workflows (mix models per step) + observability |
| **Docs** | this manual, inside the OS |
| **Automations** | named routines, hot corners, and the step builder |
| **Skills** | reusable procedures; install from a git repo or a raw `.md` URL |
| **MCP Servers** | connect external tool servers from a catalog |
| **Telegram** | control the agent from your phone; per-chat allow-list |
| **Policies** | always-allow / always-deny rules for tools & commands |
| **Logs** | everything the system did (turns, tools, MCP, telegram, jobs) |
| **Scheduler** | recurring background **jobs** |
| **Snapshots** | restore points for the whole OS (config, data, and source) |
| **Settings** | providers, model, autonomy, voice, sandbox, agent name |

---

## What the agent can do

The agent (default name **Aria**) has a large toolset and can drive the whole OS from chat or
Telegram:

- **Act on the machine** — run shell commands, read/write files, fetch the web, open apps/files on
  the host, desktop notifications.
- **Deliver results** — `save_report` writes a styled HTML report that shows in Files and opens in
  your browser, and can ship a summary to Telegram. The agent is told to **finish the job** — turn
  research into an actual deliverable, not stop after a search.
- **Build the OS** — `create_app` makes new UI apps with a desktop icon; `pin_widget` puts them on
  the desktop; `add_mcp_server` connects new tool channels.
- **Grow** — two-tier memory, a knowledge graph, `update_soul` — plus **auto-learn**: a background
  pass after every turn extracts memories and facts on its own.
- **Automate** — `schedule_task` creates headless **jobs** that deliver to a report and/or Telegram.
- **Extend itself** — `read_source` / `develop_agentos` let it modify Bento's **own source code**;
  it auto-snapshots first and syntax-checks before writing.

Ask in plain language: *"add the github MCP channel", "build me a habit tracker and pin it to desktop
2", "every morning report social-media trends to my Telegram", "install inkscape".*

---

## Models & providers

- **Ollama** (local) — auto-discovered; nothing leaves your machine.
- **Anthropic**, **OpenAI**, **OpenRouter**, or any **OpenAI-compatible** endpoint (LM Studio, vLLM,
  Groq, …).
- **Image generation** — Google Gemini or OpenAI image models when a key is set, free fallback
  otherwise.

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` and `GOOGLE_API_KEY` are picked up
automatically. Switch models mid-flight from the chat window's dropdown.

---

## Safety

- **Autonomy levels** — Paranoid / Balanced auto-run read-only actions and ask before anything that
  modifies the system; Full runs everything. Destructive commands are **hard-blocked** at every level.
- **Policies** — always-allow / always-deny rules (with `*` wildcards) matched against
  `<tool> <command>`.
- **Folder sandbox** — with bubblewrap, the agent's shell/file tools and the Terminal are jailed to
  one folder; the rest of the filesystem is read-only.
- **Snapshots** — restore points; the agent auto-snapshots before editing its own code.
- **Private by default** — binds to `127.0.0.1`. Remote access is off until you turn it on with a
  passphrase, and installing software is refused from anywhere but the machine itself.

---

## Telegram · MCP · Programmable

**Telegram** — message @BotFather, paste the token in the Telegram app, and the first private chat
becomes the owner. The agent has all its tools there; risky actions send inline Allow/Deny buttons.

**MCP servers** — add external tool servers from the catalog (Playwright, filesystem, fetch, git,
GitHub, Postgres, Slack, search, …) or a custom `stdio`/`http` server. Their tools appear to the
agent as `mcp_<server>_<tool>`, and to built apps via `POST /api/tool`.

**Programmable** — `bento ask "…"` for one-shot runs; a REST API (`POST /api/chat`, `GET /api/system`,
`POST /api/tool`, …); WebSockets at `/ws` (streaming chat + approvals) and `/ws/terminal` (host PTY).
Apps you build run in a same-origin iframe and can call all of it.

---

## Architecture

```
agentos/                 # the Python package keeps its original name; see "On the name" below
├── __main__.py    # CLI entry: serve · app · installer · doctor · apps · remote-desktop · ask
├── agent.py       # the kernel: plan → act (tools) → observe loop, approval gates, personas
├── providers.py   # unified streaming chat: Ollama / Anthropic / OpenAI / OpenRouter / custom
├── tools.py       # the hands: shell, files, web, apps, reports, memory, KG, soul, skills, MCP
├── shellhost.py   # the SUI: the desktop as a wlr-layer-shell surface (GTK + WebKitGTK)
├── sessiondoctor.py # what can actually draw the desktop on this machine
├── compositor.py  # sway/wlroots IPC: windows, workspaces, outputs, live events
├── appstore.py    # installing native applications via appstream / flatpak / apt
├── remotedesktop.py # the browser remote desktop, relayed over the authenticated connection
├── installer.py   # OS-aware setup: detect the distro, install what is missing, ask first
├── memory.py      # SQLite: conversations, memories, tasks, logs, KG, skills, apps
├── server.py      # FastAPI: desktop UI, REST API, WebSocket streams, file serving
└── ui/
    ├── src/       # the desktop's source — edit here
    └── index.html # generated by `python -m agentos.ui.build` (do not edit)
```

**State lives in `~/.agentos/`:** `config.json`, the SQLite database, `soul.md`, `wallpapers/`,
`snapshots/`. The agent's working directory is `~/AgentOS/`.

### On the name

The product is **Bento Box AI**. The Python package, the data directory and the systemd unit are
still `agentos` — deliberately. Renaming those breaks every existing install's service, config and
scripts, and buys the user nothing they can see. They will move when there is a migration worth
running, not before. The name and mark are ours in the way Ubuntu's are Canonical's: fork the code
freely under MIT, ship it under your own name. [Licensing and trademarks →](docs/licensing.md)

---

*Bento Box AI is an open, local-first alternative to cloud AI assistants: an agentic OS, AI desktop,
and automation platform you run yourself — on Linux, macOS, or Windows.*
