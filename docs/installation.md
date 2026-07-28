# Installation

AgentOS is a Python application that serves a desktop environment to your browser (or its own
window). You can run it from source, install it as a system package, or use the
**guided installers** below on Linux, macOS and Windows.

---

## Guided installers (recommended)

One downloadable file per OS, each with a wizard. The installer wizards decide **where AgentOS
goes and how it starts** — and they also *offer what your system doesn't have yet* (Python,
a browser to draw the shell, the sway session stack, Ollama for local models), installing each
missing piece only if you pick it. Product setup — your agent's name, model provider, autonomy —
happens on **first launch**, in AgentOS's own setup wizard.

| OS | File | Build with | The wizard asks |
|---|---|---|---|
| Linux | `AgentOS-Setup-<ver>-linux-x86_64.run` | `./packaging/build-linux-installer.sh` | licence → **system** (.deb, sudo) or **user** (`~/.local`, no root) → components: launcher & open-at-login, background server, **AgentOS at the login screen**, **boot straight into AgentOS** → what's missing (chromium, sway stack, Ollama, bubblewrap, git, node, …) → summary |
| macOS | `AgentOS-Installer-<ver>.command` | `./packaging/build-macos-command.sh` | native dialogs: licence → open at login → `agentos` command in `/usr/local/bin` → Ollama. Missing Python routes through Apple's own Command Line Tools prompt. A full `.pkg` with the Installer-app choices wizard builds on a Mac with `packaging/macos/build-macos-pkg.sh` |
| Windows | `AgentOS-Setup-<ver>-windows-x64.exe` | `./packaging/build-windows-installer.sh` (cross-built with NSIS: `sudo apt install nsis`) | classic setup wizard: licence → components (Start Menu, desktop shortcut, **start server at sign-in**, Ollama) → folder → install. Finds Python 3.10+ or installs it (winget / python.org) automatically |

`./packaging/build-all.sh` builds everything the current machine can.

Scripting/CI: the Linux and macOS installers take `--unattended`
(`--user|--system --prefix DIR --with-session --autologin --with-deps --no-symlink …`).
Uninstall keeps `~/.agentos` (your agent's memory and config) — removing the app never deletes
what it learned.

---

## Requirements

**Required**
- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or `pip`
- **A model provider** — either [Ollama](https://ollama.com) running locally (recommended: a
  tool-capable model such as `qwen3.5:9b`), or an API key for a cloud provider.

**Optional** — each unlocks extra capabilities when present:

| Tool | Enables |
|---|---|
| `bubblewrap` (`bwrap`) | the folder **sandbox** that confines the agent & terminal to one directory |
| `xdg-utils` (`xdg-open`) | opening files and links in your **host** browser and apps |
| Node/`npx` and/or `uvx` | running **MCP tool servers** (browser automation, filesystem, git, …) |
| `git` | installing **skills** from repositories |
| `gtk-launch`, `wpctl`, `upower`, `nmcli`, `gnome-control-center` | launching native apps and the **Quick Settings** (sound, battery, network, settings) |

Missing optional tools degrade gracefully — the related feature simply isn't offered.

### Architecture

Nothing in AgentOS is x86-only. Every runtime dependency is pure Python or ships `aarch64`
wheels, so it installs and runs on **arm64** — Apple Silicon, ARM servers, and a **Raspberry Pi**
— exactly as it does on x86. `./packaging/build-deb.sh` takes its architecture from the build
machine (`dpkg --print-architecture`), so running it on a Pi produces a real `arm64` package;
building on a PC and installing on a Pi will not work, because the `.deb` bundles a venv.

---

## Raspberry Pi

AgentOS runs on a Pi. What that's like depends entirely on where the model lives.

**Recommended: Pi 4 or Pi 5, 4GB+, 64-bit Raspberry Pi OS (Bookworm or newer).**

```bash
sudo apt install python3 python3-venv git
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone <your fork> agentic-os && cd agentic-os
uv sync && uv run agentos
```

**Reaching it from another machine.** A Pi is usually headless, and the obvious move — binding
the server to the network — is the wrong one: AgentOS has no authentication and the agent has a
real shell, so `--host 0.0.0.0` hands your Pi to anyone on the LAN. Forward the loopback port
over SSH instead, and the [loopback-only guarantee](security.md) still holds:

```bash
ssh -L 8321:127.0.0.1:8321 pi@raspberrypi.local     # then open http://127.0.0.1:8321 locally
```

**The model is the constraint, not the OS.** The server, the desktop, the scheduler and the agent
loop are light — the Pi is a fine *host*. Local inference is a different story: a Pi has no
usable GPU for Ollama, so models run on CPU. A 3B model is slow but usable; 7B and up is
painful. Two setups that work well:

- **Cloud models** — the Pi is the always-on machine, inference happens elsewhere. The whole OS
  stays responsive.
- **Ollama on another box** — point `providers.ollama.base_url` at a desktop on your LAN. You keep
  local-only inference and the Pi keeps being the thing that's always on.

**Drawing the desktop.** Chromium on the Pi renders the shell fine, but the heavy-blur themes
(Liquid Glass, Spatial) lean on `backdrop-filter`, which is expensive without GPU compositing.
If the desktop feels sluggish on the Pi's own display, pick **Bento** or **Minimalism** — both are
deliberately blur-free — or drive the Pi headless and open the desktop from a laptop or phone,
which is where the [responsive layout](desktop.md#phone-tablet-desktop) pays off. The built-in
wallpapers are SVG with no blur filters, so they cost nothing either way.

**What won't be there.** The Train app (LoRA fine-tuning) needs an NVIDIA GPU and is simply not
offered. Anything else that depends on a missing tool degrades the same way it does everywhere
else — the feature isn't offered rather than failing.

Boot-to-AgentOS (the sway session) has **not** been tested on a Pi; the source install above has
the fewest moving parts and is what to use there.

---

## Run from source

```bash
cd agentic-os
uv sync                 # install dependencies (or: pip install -e .)
uv run agentos          # start the server and open the desktop in your browser
```

That's it. The desktop opens at **http://127.0.0.1:8321**. If Ollama is running, your models are
detected automatically.

### Make it permanent

```bash
uv run agentos install
```

This:
- adds an **AgentOS** entry to your application menu (with an icon),
- installs a **systemd user service** that runs the server, enabled and started, with **linger** on
  so it starts at boot — even before you log in,
- adds a **login autostart** entry so the AgentOS window opens automatically each time you log in.

Flags:
- `--no-service` — install the launcher only; skip the boot service.
- `--no-login` — don't open AgentOS automatically at login.

To remove everything (your data in `~/.agentos` is preserved):

```bash
uv run agentos uninstall
```

---

## Install the Debian/Ubuntu package (`.deb`)

A self-contained package bundles the app **and** a Python environment with all dependencies — no
network is needed at install time.

**Build it:**
```bash
./packaging/build-deb.sh          # → packaging/dist/agentos_<version>_<arch>.deb  (arm64 on a Pi)
```

**Install it:**
```bash
sudo dpkg -i packaging/dist/agentos_0.1.0_amd64.deb
systemctl --user enable --now agentos      # start it, and start at login
agentos app                                # open the window (or find "AgentOS" in your menu)
```

`apt`/`dpkg` manages updates and removal (`sudo apt remove agentos`). The package **recommends**
`bubblewrap` and `xdg-utils`, and **suggests** `ollama`, `nodejs`, and `git` for optional features.

> The prebuilt package targets the Python version it was built against. For a different distribution
> or Python version, rebuild it on that machine with `./packaging/build-deb.sh`.

### The desktop-environment package (`agentos-desktop`)

A second, tiny package makes AgentOS selectable as a **login session** — a full Wayland desktop
where AgentOS is the shell. It is purely additive: your current desktop and default session are
untouched.

```bash
./packaging/build-desktop-deb.sh    # → packaging/dist/agentos-desktop_<version>_all.deb
sudo apt install ./packaging/dist/agentos-desktop_0.1.0_all.deb
```

Then log out and pick **AgentOS** at the login screen. Every hard dependency it pulls in
(sway, swaylock, grim, pipewire, …) is permissively licensed — enforced by
`packaging/audit-licenses.sh` at build time. See
**[AgentOS as your desktop environment](desktop-environment.md)** for the full story, including
boot-to-AgentOS.

---

## Launch modes

| Command | What it does |
|---|---|
| `agentos` | start the server **and** open the desktop in your browser |
| `agentos serve --no-browser --port 8321` | run the server headless (used by the boot service) |
| `agentos app` | open the desktop as its own fullscreen window |
| `agentos install` / `uninstall` | install / remove the launcher, service, and autostart |
| `agentos autostart` / `autostart --off` | open at login / stop opening at login |
| `agentos ask "…"` | run a single agent task from the terminal |

---

## Managing the service

Once installed, AgentOS runs as a systemd **user** service:

```bash
systemctl --user status agentos      # is it running?
systemctl --user restart agentos     # restart (e.g. after changing settings on disk)
systemctl --user stop agentos        # stop
journalctl --user -u agentos -f      # follow logs
```

---

## Where data lives

| Location | Contents |
|---|---|
| `~/.agentos/config.json` | all settings |
| `~/.agentos/agentos.db` | conversations, memory, tasks, apps, logs, knowledge graph |
| `~/.agentos/soul.md` | the agent's persistent identity |
| `~/.agentos/wallpapers/` | generated wallpapers |
| `~/.agentos/snapshots/` | restore points |
| `~/AgentOS/` | the agent's working directory (reports land in `~/AgentOS/reports/`) |

See [Configuration](configuration.md) for details.
