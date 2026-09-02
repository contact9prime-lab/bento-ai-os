# Bento Box AI — a local-first agentic operating system

<p align="right"><sub>
<b>English</b> ·
<a href="docs/i18n/README.zh-CN.md">简体中文</a> ·
<a href="docs/i18n/README.zh-TW.md">繁體中文</a> ·
<a href="docs/i18n/README.ja.md">日本語</a> ·
<a href="docs/i18n/README.ko.md">한국어</a> ·
<a href="docs/i18n/README.es.md">Español</a> ·
<a href="docs/i18n/README.pt-BR.md">Português&nbsp;(BR)</a> ·
<a href="docs/i18n/README.fr.md">Français</a> ·
<a href="docs/i18n/README.de.md">Deutsch</a> ·
<a href="docs/i18n/README.ru.md">Русский</a> ·
<a href="docs/i18n/README.hi.md">हिन्दी</a> ·
<a href="docs/i18n/README.ar.md">العربية</a>
</sub></p>

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

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

![The Bento Box AI desktop — AI agent chat, file manager, and quick settings in a browser-based desktop environment](docs/screenshots/desktop.png)

**Full documentation is in [`docs/`](docs/README.md)** — installation, a user guide to the desktop
and every app, the agent and its tools, building apps, integrations, the API reference, and
troubleshooting.

---

## Setup is eleven steps, and each one leaves something behind

Not a settings form with a progress bar. Every step **produces something real** — a model
that answers, an agent that exists, a flow that runs, a schedule that fires — and says what
you will end up with before it asks you for anything.

![The first-run setup screen: a rail of eleven steps down the left, and on the right "Name your agent" with the line "You will end up with: the name on the menu bar and in every reply"](docs/screenshots/onboarding-1-name.png)

Every step is **probed, never remembered**: it is ticked because the machine has the thing.
Delete the agent and the step goes back to todo. That is what makes it safe to re-run — and
re-running is a normal thing to do here, because **Setup is also an app**. Open it any time to
see what a step does, on a machine you set up months ago.

![The Setup app in a window: the eleven-step rail on the left, and the "Build a specialist" step open on the right](docs/screenshots/setup-app.png)

Same catalogue, same probe, same panes — including in a terminal, where `bento setup` over
SSH picks up exactly where the browser left off.

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

## Day one is lighter than week four

The desktop used to open onto 43 tiles on a machine that could not yet answer a question. Now:

![The desktop on day one: three groups open, three folded to one line with a count, and a "No brain yet · give it one" chip in the menu bar](docs/design/ux-review/after/a-desktop.jpg)

- **The deck folds what you have not used.** Intelligence, System and Library start as one line
  with a count and a peek of their icons; they unfold on a click, or the first time you open one of
  their apps. A deck you have arranged is left exactly as you left it.
- **The menu bar says what state the machine is in.** With nothing set to answer it reads
  *No brain yet · give it one →*, and clicking it opens that step of setup.
- **A failed turn is a sentence with a door.** No model, Ollama not running, a refused key, a rate
  limit, a model not pulled — each is one sentence and one button (*Give it a brain*, *Open AI
  providers*, *Open Model Manager*), in Chat, in the prompt bar's card and in every copilot panel.
  The exception's name goes to Logs, where it belongs.
- **One rule for every popover.** The launcher, the menus, notifications, power and Quick Settings
  open one at a time, close on Escape and on a click outside, and the launcher fits the screen it is on.
- **On a phone, one composer.** A sheet with its own input hides the prompt bar; list/detail apps
  push one pane at a time with a way back; the setup wizard keeps its exit.

![The first message on a fresh install: "Nothing can answer yet — this machine has no brain" with a Give it a brain button, instead of a Python exception](docs/design/ux-review/after/a-chat-sent.jpg)

Every one of these was measured in a real browser before and after. The review that found them,
with the numbers, is [docs/design/ux-review-2026-09.md](docs/design/ux-review-2026-09.md).

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
| ![Chat with the AI agent — streaming replies, tool calls, and approvals](docs/screenshots/chat.png) **Agent Chat** — talk to your machine; streaming replies, tool cards, approvals, voice. Paste, drop or snap a screenshot on any agent surface — Chat, the prompt bar, the ✦ panel in every app — so it can see the problem | ![Team app — subagents, workflows, and observability](docs/screenshots/team.png) **Team** — specialist subagents and visual workflows, with per-step model mixing |
| ![Built-in documentation app rendering the full manual](docs/screenshots/docs.png) **Docs** — the full manual lives inside the OS | ![App store — one-click apps, skills, and MCP channels](docs/screenshots/store.png) **Store** — one-click apps, skills, and MCP tool channels |

### Several people, one machine

Add an account and each person gets **their own home** — their own database, memory, agents,
channels, MCP servers and credentials. Not a `user_id` column that one forgotten `WHERE`
clause leaks: their own directory, because two files cannot leak into each other.

![The Users app: two accounts, Ada Lovelace marked admin and "this is you", Bob Kahn with a role dropdown set to Executor](docs/screenshots/users-two-accounts.png)

Two roles — **executor** (everything inside their own home) and **admin** (that, plus the
machine). Settings stay shared, so there is one provider key for the machine rather than one
per person. Agents and apps cross deliberately, as copies, through a shared library.

And it is **one sign-in, here and from anywhere**: a machine with accounts is locked by
them, so the phone in somebody's pocket uses the same username and password as the desktop
and lands in their own home. No second shared passphrase to invent, share or forget.

![The Remote access panel reading "Locked by this machine's accounts — everyone signs in from their phone with the same username and password they use here"](docs/screenshots/remote-locked-by-accounts.png)

### You can see what it is doing

![A turn in flight: the finished Read call kept its duration, the running Bash call ages in place, and the row underneath says which step and how long the turn has taken](docs/screenshots/agent-working.png)

A turn is mostly waiting, and "working…" for four minutes tells you nothing — a model thinking
and a run that has silently died look identical under it. Every waiting surface says **what it is
on and for how long**: the running call ages in place (`running · 2m 14s`), finished calls keep
their duration, and the row underneath carries the step and the turn total. The same sentence
appears on the presence bubble and the omnibar, so it is answerable from the desktop without
opening the chat.

### It can build its own team — and asks before it does

![Approving a delegation: the card names the agent, the model, the step and time budget, and the exact tools and skills it would hold](docs/screenshots/agent-approval.png)

When no existing specialist fits, the agent **builds one** and delegates to it. Defining an agent
grants it nothing; the first time it is actually used you get a card naming the model it runs on,
its budget, and the exact tools and skills its definition gives it — because consent to an actor
you cannot picture is consent in name only. Approving `researcher` is not approving `deploy-bot`,
and the grant is revocable in Permissions like any other. [How it works →](docs/security.md)

### It answers questions about itself from its own manual

![The Docs app answering a question about this OS, grounded in the manual](docs/screenshots/docs-ask.png)

The manual is in the retrieval index, so "how do I stop an app reaching the internet but keep it
working?" is answered from **these pages**, not from a model's memory of a different project — and
the reply names the page it used. It is agentic retrieval rather than a one-shot lookup: the agent
searches, reads, and searches again when the first pass misses.

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

WhatsApp has **two transports**, and they fail in opposite directions. Meta's Cloud API is
official but needs a developer account and a public webhook, and outside 24 hours from your last
message it will not carry a free-form reply at all — the card says whether that window is open, a
send that cannot go through says so and how to fix it, and a scheduled job saves its report first
so nothing is lost. The WhatsApp Web link needs only a QR scan and has no 24-hour window, but it is
**unofficial** and Bento says so on the install card before anything downloads. [Setup →](docs/whatsapp.md)

Telegram is also an **admin console**: `/agents`, `/run`, `/flows`, `/model`, `/logs`, `/perms` —
owner only, and every command that *does* something goes through the same permission gate and the
same approval buttons as the desktop, so it is never a cheaper way in. [Commands →](docs/integrations.md)

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
- **A landing place, not a walled garden** — coming from an OpenClaw-class assistant? Bento
  [installs its plugins through a scan and a consent screen](docs/openclaw-plugins.md), can run
  them behind its own permission engine, or has the agent **rebuild one natively** from the
  plugin's own manifest — ending in a signed-off report of what carried over, what did not, and
  what each gap costs you.
- **Fork my agent** — [share the agent you shaped as one file](docs/agent-sharing.md) — skills,
  teammates, flows, the apps you choose — and fork anybody else's. Your data and credentials
  **never travel** (a leak scan refuses the export, with no override), and a fork lands with
  everything disabled and **zero permissions granted**: you read the ceiling first, then enabling
  each piece is the act of granting. Or **host** your share instead of publishing it: peers take
  the live version through an authenticated MCP door with a key you minted — and can revoke.

---

## Quickstart

**One command, on macOS or Linux.** It installs everything — including Python, via `uv` — starts
Bento, and then *proves it works* by asking the running server a question before it says "done".

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
```

Then open **http://127.0.0.1:8321**, or run `bento setup` for the same eleven steps in a terminal.

If there is a terminal to ask on, the installer asks two things before it finishes: whether this
machine should be reachable from your other devices, and — if so — whether you sign in with a
**passphrase** or an **account**. On a machine with no screen that first question is the
difference between an install you can look at and one you cannot. `--yes` deliberately does not
answer it: an open port here is an open shell.

It leaves a `bento` command on your `PATH` (in `~/.local/bin`, added to your shell profile if it
was not there — open a new terminal afterwards). `bento --help` shows the ten commands a new
machine needs; `bento help --all` is the rest.

### Installing it on a chosen address and port

On a server you reach over SSH, `127.0.0.1:8321` means "reachable by nothing". Give the
installer a passphrase and an address and it comes up ready, with the boot service already
pointed at the right port:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=0.0.0.0 --port=8080
```

That machine now answers on **every** interface at port 8080, and asks for that passphrase
before it will do anything. Local use through `127.0.0.1:8080` is unchanged.

The installer says which of the two it left you with — `AgentOS is running` only when something
is genuinely listening. On a box with no service manager to hand (a container, a non-systemd
distro, SSH with no user D-Bus) it says so instead, and `bento service start` finishes the job.

One interface rather than all of them — a private VLAN, a Tailscale address:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --passphrase='something long and unguessable' --bind=192.168.1.20 --port=8080
```

Just a different port, still loopback-only:

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh \
  | sh -s -- --port=8080
```

> **`-s --` is not optional.** `curl … | sh --port=8080` hands the flag to `sh`, which rejects
> it — a piped script gets no arguments of its own. `-s --` means "the rest is for the script".
> This is the single most common way these flags get lost, and the error names `sh`, so it
> reads as a broken installer.

**All the flags:**

| flag | what it does |
|---|---|
| `--passphrase=SECRET` | require this to sign in, and allow binding off loopback — given here, the installer does not ask |
| `--bind=ADDR` | which interface to listen on (default `0.0.0.0`); needs `--passphrase` |
| `--port=N` | which port (default `8321`); saved to the config, so the boot service uses it |
| `--yes` | answer yes to every optional component — **not** to opening the port |
| `--no-service` | no launcher and no boot service (containers, CI) |
| `--no-verify` | skip the "prove it works" step |

### Changing it afterwards

Everything above lives in **`~/.agentos/config.json`** (or under `$AGENTOS_HOME`), and
`bento config` reads and writes it without you having to find it:

```bash
bento config                       # the whole file, secrets masked
bento config port                  # one setting
bento config port 8080             # change it
bento config remote.bind 0.0.0.0   # dotted paths for nested settings
bento config --path                # where the file is
bento config --edit                # open it in $EDITOR — refuses to save invalid JSON
```

`bento remote` is the same settings with the reachability ones grouped together:

```bash
bento remote --on --passphrase 'something long' --bind 0.0.0.0   # one shared secret
bento user add alice && bento remote --on --bind 0.0.0.0          # or an account each
bento remote --port 8080                                          # the port
bento remote                                                      # what it is now, and who signs in
```

**A port change does not reach an installed boot service by itself** — the systemd unit
and the LaunchAgent bake it into `ExecStart`. Both commands tell you when that applies:

```bash
bento service install && bento service restart
```

> **Reachable from other machines is a deliberate choice, not a default.** Bento listens on
> `127.0.0.1` only until it has a lock — a passphrase, or an account somebody signs in as —
> because the agent has a real shell, and an open port here is an open shell. `--bind` on its
> own is refused for that reason, and so is `bento serve --host 0.0.0.0` with remote access off.
> The two locks are alternatives, not layers: once an account exists it *is* the lock, and a
> passphrase in front of it is config nothing reads.

**About ports below 1024.** They are refused to a non-root process on Linux, and on macOS the
refusal is per-address — it grants `0.0.0.0:80` and denies `127.0.0.1:80`. So nothing here
guesses from the number: `--port` attempts the real bind and, if the kernel says no, prints the
`sysctl` line, the redirect rule, or the proxy option that fixes it. On Linux, port 80 usually
means one command:

```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/50-agentos.conf
sudo sysctl --system
```

Running the server as root is not advised — the agent has a real shell.

<details>
<summary><b>From a git checkout instead</b></summary>

```bash
uv sync                 # install dependencies (or: pip install -e .)
uv run bento            # start the server and open the desktop in your browser
```
</details>

<details>
<summary><b>In Docker</b></summary>

```bash
docker build -t bento .
docker run -d --name bento -p 8321:8321 -v bento-data:/data \
  -e AGENTOS_PASSPHRASE='something long and unguessable' bento
```

A container has to bind `0.0.0.0` to be reachable at all, so the passphrase is required rather
than optional — the entrypoint refuses to start unreachable *or* insecure and tells you which.
Everything that would be lost lives in the `/data` volume. Build a specific branch with
`--build-arg SOURCE=git --build-arg REF=my-branch`.
</details>

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

One set of commands drives all three — you should not have to know whether this box
uses systemd or launchd to control your own agent:

```bash
bento service status       # is it running, will it come back at boot, is the port answering
bento service start        # …stop, restart
bento service logs -f      # journalctl or the log file, whichever this machine uses
bento service uninstall    # remove the background service only — launcher and data stay
bento uninstall            # remove launcher + service (your data stays)
bento app                  # open as a chromeless desktop window any time
```

`bento service status` reports what the supervisor believes **and** whether the port
answers, separately: a unit that is "active" while nothing is listening is a crash
loop, and that is the state worth being able to see.

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
| `uv run bento service status \| start \| stop \| restart \| logs \| uninstall` | the background server, on whatever supervisor this OS has |
| `uv run bento update` / `update --apply` | check for a newer version / pull, sync, test and restart — `--repo you/fork --branch x` follows a fork, `--official` goes back |
| `uv run bento config [key] [value]` | read or change `~/.agentos/config.json` (`--edit`, `--path`) |
| `uv run bento remote --port 8080 --bind 0.0.0.0` | the address it answers on, saved to the config |
| `uv run bento serve --if-running open\|port\|restart\|fail` | what to do when one is already running (default: ask) |
| `uv run bento apps search \| install \| remove` | native applications, from a terminal |
| `uv run bento remote --on --passphrase '…'` | reach this desktop from your phone |
| `uv run bento remote-desktop --on` | the browser remote desktop (real screen, native apps) |
| `uv run bento ask "…"` | one-shot agent run in the terminal (`--full`, `--model …`) |
| `uv run bento user add <name>` | accounts — the first one adopts this machine and is an admin |
| `uv run bento help --all` | every command; `bento --help` shows the ten a new machine needs |

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
- **Absorb other ecosystems** — it can install an [OpenClaw plugin](docs/openclaw-plugins.md)
  (always landing **disabled** — enabling stays your decision), or take the plugin's manifest as a
  brief and rebuild the same capability out of Bento's own parts, then check its own work item by
  item and hand you the report.

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
- **Every extension goes past a lock** — apps, MCP servers, flows,
  [OpenClaw plugins](docs/openclaw-plugins.md) and [forked agents](docs/agent-sharing.md) all
  arrive through a scan, a consent screen that
  states the licence, real permission rows you can revoke, and a quarantine that can hold a
  misbehaving one. What a boundary *cannot* enforce is said in a sentence, never implied away.
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
