# Installation

AgentOS runs on Linux. It's a Python application that serves a desktop environment to your browser
(or its own window). You can run it from source, or install it as a system package.

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
| `gtk-launch`, `wpctl`, `upower`, `nmcli`, `gnome-control-center` | launching native apps and the **Control Center** (sound, battery, network, settings) |

Missing optional tools degrade gracefully — the related feature simply isn't offered.

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
./packaging/build-deb.sh          # → packaging/dist/agentos_<version>_amd64.deb
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
