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

> **The interpreter is pinned in `.python-version`.** `requires-python` has no upper bound, so left
> to itself `uv` provisions the newest CPython — and the newest release is where prebuilt wheels
> have not caught up: `cryptography`, `pydantic-core` and friends have wheels for 3.11–3.13 but not
> a just-released 3.14, so `uv` would compile them from source (and `cryptography` needs Rust). On a
> 64-bit Pi that turns a seconds-long wheel download into a Rust build that fails — for a reason that
> has nothing to do with ARM. The pin keeps `uv` on a version with full wheel coverage; delete
> `.venv` and re-sync if an earlier run already built the environment on a newer Python.

> **Use 64-bit Pi OS.** On **arm64** every dependency ships a prebuilt wheel, so nothing is
> compiled and the install is quick. On **32-bit** Pi OS (armv7 — and especially an old image like
> Buster, or a Pi Zero / 1) some packages may have to build from source: minutes of 100% CPU that
> looks like the installer has hung, and on a small Pi can thrash into an out-of-memory kill.
>
> `install.sh` helps in two ways. It points `uv` at [piwheels](https://www.piwheels.org) — the
> Raspberry Pi project's own wheelhouse of these packages built for ARM — so what piwheels carries
> **downloads instead of compiling** (uv, unlike pip on Pi OS, does not use piwheels by default).
> And it prints a heartbeat while `uv` works, so a genuine compile reads as *working*, not *stuck*.
> Anything piwheels does not carry still compiles, and for the C ones it names and offers to install
> the build toolchain: `build-essential python3-dev libffi-dev libssl-dev pkg-config`.
>
> **`cryptography` deserves its own note, and the real variable is glibc — not 32-bit.** It arrives
> via `pyjwt[crypto]` (the MCP SDK needs it), and it *does* ship a prebuilt 32-bit ARM wheel. But
> that wheel is tagged `manylinux_2_31_armv7l`, so it needs **glibc ≥ 2.31**:
>
> | Raspberry Pi OS | Debian | glibc | 32-bit `cryptography` |
> |---|---|---|---|
> | **Buster** | 10 | 2.28 | ❌ too old → source build → fails (no OpenSSL 3.0) |
> | **Bullseye** | 11 | 2.31 | ✅ prebuilt wheel — no compile, no Rust |
> | **Bookworm** | 12 | 2.36 | ✅ prebuilt wheel — no compile, no Rust |
>
> So on **Bullseye or Bookworm, 32-bit is completely fine** — the wheel installs in seconds and
> bundles its own OpenSSL 3, so the system's OpenSSL version is irrelevant. The only real problem is
> **Buster**: its glibc 2.28 is below the wheel's floor, so `uv` falls back to a source build, which
> then fails because Buster's OpenSSL is 1.1.1 and cryptography 49 requires 3.0. The fix for a Buster
> Pi is simply to move to Bullseye or Bookworm — **you do not need 64-bit and you do not need Rust.**
> The installer measures glibc and says exactly this.
>
> Two genuine exceptions still need a compile (Rust via [rustup](https://rustup.rs) + ≥1 GB swap, on
> Bookworm for its OpenSSL 3.0): an **armv6** Pi (Zero / 1), which has no ARM wheel at all, and any
> case where you deliberately stay on Buster. **64-bit Bookworm** remains the smoothest option of all —
> prebuilt `aarch64` wheels for everything — if reflashing is on the table.

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

**Drawing the desktop.** Chromium on the Pi renders the shell fine. The thing that hurts a Pi is
`backdrop-filter` — the heavy-blur themes (Liquid Glass, Spatial) lean on it, and its cost
compounds with every window you open, because each translucent surface makes the compositor
re-blur everything beneath it.

You do not have to manage that by hand: **Themes → Effects** defaults to *Automatic*, which
measures real frame times with real windows open and turns glass down if this machine cannot keep
up — first to *Reduced* (only the focused window is glass, so the cost stops growing with the
number of windows), then to *Off*. You can pin any level yourself; on a Pi's own display, **Off**
is a reasonable thing to just choose. See
[Effects](desktop.md#effects-what-glass-costs-and-the-knob-for-it).

Everything else is already cheap: the flat themes (**Bento**, **Claymorphism**, **Minimalism**)
never blur, the built-in wallpapers are SVG with no blur filters, and windows you cannot see
[stop doing background work entirely](desktop.md#windows-sleep-when-you-stop-looking-at-them).
Or drive the Pi headless and open the desktop from a laptop or phone, which is where the
[responsive layout](desktop.md#phone-tablet-desktop) pays off.

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

## The address it answers on

By default AgentOS listens on `127.0.0.1:8321`. Both halves are changeable, and both
are saved to the config so the boot service uses them too:

```bash
bento remote --port 8080                                   # the port
bento remote --on --passphrase '<long>' --bind 0.0.0.0     # every interface
bento remote --on --passphrase '<long>' --bind 192.168.1.20  # one interface
bento remote                                               # show what it is now
```

Or through the settings file directly — `~/.agentos/config.json`, under `$AGENTOS_HOME`
if you set one:

```bash
bento config port 8080             # same validation and the same service warning
bento config remote.bind 0.0.0.0   # dotted paths reach nested settings
bento config                       # the whole file, secrets masked (--raw shows them)
bento config --path                # where it lives
bento config --edit                # $EDITOR, with a rollback if you leave invalid JSON
```

At install time, in one go:

```bash
curl -fsSL <url> | sh -s -- --passphrase='<long>' --bind=0.0.0.0 --port=8080
```

The `-s --` matters: `curl … | sh --port=8080` gives the flag to `sh`, not to the
script, and `sh` rejects it.

Three things this will not do quietly:

- **Binding off loopback needs a passphrase.** `--bind` alone is refused, and so is
  `bento serve --host 0.0.0.0` with remote access off. The agent has a real shell, so
  an open port is an open shell — the lock is not optional.
- **A port change does not reach the installed service by itself.** The unit and the
  LaunchAgent bake the port into `ExecStart`, so re-run `bento service install` after
  changing it. The CLI reminds you when a service is installed.
- **A port the kernel refuses is reported, with the fix.** Below 1024 needs privilege
  on Linux; the message prints the `sysctl` line, the redirect, and the proxy option.
  It is decided by attempting the bind, not by the port number — macOS allows
  `0.0.0.0:80` to any process and refuses `127.0.0.1:80`, so the rule of thumb is
  wrong there in both directions.

After a bind or port change, restart: `bento service restart`.

## Already running?

`bento` and `bento serve` check before starting, and — in a terminal — ask what you
want instead of refusing:

```
  [o] open it in a browser        [r] restart it
  [p] a second one on port 8322   [q] quit
```

`--if-running open|port|restart|fail` picks without asking. Without a terminal it
always behaves as `fail`, so a unit or a CI step never blocks on a prompt.

A second instance shares `~/.agentos` — one database, two schedulers, two Telegram
pollers. Use `AGENTOS_HOME=~/.agentos-test bento serve --port 8322` for a real one.

## Small machines (Raspberry Pi and friends)

A standing agent earns its keep on a Pi, so the footprint is measured rather than
assumed. On a warm install with no browser attached:

| | |
|---|---|
| idle RSS | ~70 MB, flat |
| idle CPU | ~0.6% of one core |
| a turn | ~0.13 s of CPU, ~1.6 kB of database |
| after 1,300 turns | RSS settles at ~120 MB and stays there |

### Light mode

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh -s -- --lite
bento profile            # what this machine is doing, and what it is keeping
bento profile lite       # switch later; the MCP cache is deleted on the spot
```

`--lite` is the Pi profile. The one behaviour it changes is the expensive one: the
MCP catalogue is **fetched while you search and deleted when you stop**, so
nothing is kept at rest — a search costs a download instead of 12 MB of card and
35 MB of RAM. Telemetry is kept 7 days rather than 30. Nothing else changes: same
features, same tools, same agent.

Left alone, the profile is `auto`: the server decides from the machine on first
run (≤ 2 GB of RAM → lite) and **writes down what it decided**, so it shows up as
an ordinary `profile` key in `config.json` and in `bento doctor` rather than as
behaviour you cannot see. Settings → System → Footprint is the same switch.

Three standing costs are deliberately **not** paid unless you use the thing:

- **The MCP catalogue** is 21,811 servers — 11.9 MB of JSON, +35 MB of RSS once
  parsed. It is synced when you first open the MCP Store, not at boot, and it is
  released from memory again after 15 idle minutes (the file stays; the next
  search reads it back). While it syncs, the file is written every few seconds
  rather than after every page — page-by-page writes cost ~1.3 GB of SD-card
  writes per sync, daily.
- **Executor probes** (`claude --version` and friends) are cached for five
  minutes and dropped the moment something is installed. Uncached, they cost
  1.2 s per `/api/executors` call, and every Settings repaint asked.
- **Telemetry is pruned.** Logs and flow-run events older than 30 days and token
  accounting older than a year are deleted on the maintenance pass, and the WAL
  is checkpointed so the disk is actually given back. The audit ledger and your
  own work — messages, memories, assets, apps — are never touched. Change or
  switch it off under `retention` in `config.json`; `bento doctor` prints the
  database size.

If a Pi feels slow, `bento doctor` is the first stop: it reports the database
size, what answers turns here, and which optional components are missing.

## Updating

```bash
bento update           # is there a newer version? changes nothing
bento update --apply   # fast-forward, sync deps, run the tests, restart
```

`--apply` refuses on a checkout with uncommitted changes to tracked files, or on the
wrong branch, and says which. It runs the test suite before keeping the new code and
**rolls back** if it fails — `--no-tests` skips that gate, which is also what makes a
bad update recoverable. `--no-restart` leaves loading it to you.

A bare `bento update` never pulls. The same machinery backs Settings → Updates, the
About panel and the background check, so all four agree about what is waiting.

**Two sources, because they answer for different installs.** `agentos/VERSION` is
published at a release and is the only thing a pip/wheel copy can compare against.
The checkout's own git is the only thing that knows about commits BETWEEN releases —
and that is most of the time. So a report looks like one of:

```
▲ 0.4.0 is available (you have 0.3.0)              # a release
▲ 8 changes waiting on origin/master — same version (0.3.0), newer code
✓ up to date with origin/master (published version 0.3.0)
```

If a push of yours never seems to arrive, the first line of `bento update` is the
usual answer: it prints the branch this checkout is **on** and the branch updates
**track**. Commits pushed to any other branch will never show up here, and your own
unpushed commits are reported as `ahead`.

## Managing the service

Use `bento service`. It talks to whichever supervisor this machine actually has —
a systemd **user** unit on Linux, a **LaunchAgent** on macOS, a Startup entry on
Windows — so the same commands work everywhere:

```bash
bento service status       # running? at boot? is the port answering?
bento service start
bento service stop
bento service restart      # e.g. after changing settings on disk
bento service logs -f      # follow logs
bento service uninstall    # remove the service only; launcher and ~/.agentos stay
```

`status` reports the supervisor's opinion and the port separately, because they can
disagree: a unit that is `active` while nothing answers is a crash loop inside
`RestartSec`, and one boolean would call that healthy.

On a machine where nothing is installed as a service, `start`/`stop` fall back to
plain process control and say so — "started, unsupervised" is a different promise
from "started" and you should be able to tell which you got.

The underlying systemd commands still work, if you prefer them:

```bash
systemctl --user status agentos
systemctl --user restart agentos
journalctl --user -u agentos -f
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
