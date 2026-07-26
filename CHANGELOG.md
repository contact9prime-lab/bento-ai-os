# Changelog

## Unreleased — the living-desktop release (2026-07-26)

The theme: **truly agentic, and it moves like a Mac.** Two gaps closed at once —
the desktop finally behaves like a physical place (motion, materials, real window
management), and the agent finally has hands on the whole machine (every UI
capability is now also a PDP-gated tool, the launcher routes language to actions,
and the OS can start turns of its own).

### The experience (Mac-class motion & materials)
- **UI modularized**: `ui/index.html` is now assembled from `ui/src/` (14 CSS + 32 JS
  modules) by a zero-dependency build step (`python -m agentos.ui.build`); the shipped
  artifact is unchanged in kind — one file, served as before. A test keeps it fresh.
- **Design tokens**: type ramp, spacing, radii, a 5-step elevation ladder, motion
  durations/curves, mode-flipping hairlines/scrims — and the old 27 ad-hoc font sizes /
  17 radii / 43 shadows normalized onto them. Inter (OFL) ships as the UI typeface.
  `prefers-reduced-motion` honored globally; `:focus-visible` ring; light mode
  systematized.
- **Windows are things now**: they zoom out of their dock icon on open, back into it on
  minimize/close, FLIP-animate between maximize states, lift while dragged, and snap to
  edges (halves/quarters, top = maximize) with a live preview ghost. 8-way resize handles
  replace the browser's corner grip. Files & Terminal are multi-instance ("New window"
  in the dock menu). z-order renormalizes; the switcher stays macOS-style (icons).
- **The dock magnifies** — continuous neighbor falloff under the pointer — and bounces
  on launch. It auto-hides under a focused maximized window (bottom-edge peek restores).
- **Exposé** (F3 / Ctrl+↑): every window on the desktop, live, FLIP-scaled into a grid.
  Virtual desktops slide instead of teleporting; themes crossfade via View Transitions.
- **Every popover animates from its anchor** (context menus, power menu, notification
  center, Control Center) and **`window.confirm`/`alert`/`prompt` are gone** — replaced
  by AgentOS sheets (`osConfirm`/`osAlert`/`osPrompt`) everywhere, including power
  actions and factory reset. Toasts stack properly. Quick Settings became a real
  **Control Center popover** on the tray (the app window remains available).
- The menu bar shows the **focused app's name**; power menu drops emoji for clean labels.

### Boot & identity continuity
- **The 30-second void is dead**: the session launches the renderer immediately on a
  local branded splash (`~/.agentos/boot.html`) that probes the server with an image
  beacon and hands off the moment it answers — with live status text and a named
  failure state after 90s. The in-page splash now dismisses on actual readiness
  (config + platform + setup loaded), not a 900ms timer.
- **Wallpaper continuity**: changing the wallpaper now updates the compositor
  background *and* the swaylock image live (`session.apply_wallpaper_live`) — no more
  drift until the next `install-session`.
- **swaylock is branded** (teal ring, wallpaper fill, correct error colors);
  the cursor theme is pinned (compositor + XWayland); an optional **AgentOS plymouth
  boot theme** ships as a consent-gated component (`plymouth-theme`, script install).

### Agent hands (the parity law)
- Every capability the UI has is now a tool: `desktop_state`, `control_desktop`
  (open/close/focus AgentOS apps, switch desktops, apply themes — via a new
  server↔shell command channel), `manage_window`, `list_themes`, `wifi`, `bluetooth`,
  `set_brightness`, `audio`, `power_profile`, `lock_screen`, `power_action`
  (**always asks**, even at full autonomy), `take_screenshot` (the image goes to the
  model — the agent can *see* the screen), `list_notifications`, `search_files`,
  `create_trigger`. 75 tools total, all PDP-gated.
- The system prompt now carries a live **machine-state line** (focused window, battery,
  network, volume, unread notifications) — cached, time-boxed, prompt-cache-friendly.

### Language as the primary input
- **Palette v2**: a local intent grammar turns "open terminal", "volume 30",
  "brightness 60", "make it dark", "theme nord", "lock", "screenshot", "wallpaper of a
  quiet harbor", "desktop 2", "dnd off", arithmetic — into direct actions with inline
  rows (still one keystroke from "Ask {agent}"). Misses fall through to `POST
  /api/intent` (model-classified, 6s cap) which appends a suggested action.
- **Semantic search everywhere it counts**: a lazy mtime-aware embedding index over the
  workspace + docs (`agentos/search.py`, Ollama embeddings, substring fallback) behind
  `GET /api/search`, the `search_files` tool, and a meaning-search box in Files.

### The OS initiates (proactivity)
- **Event triggers** join the scheduler: `notification` (substring/regex),
  `file_change` (mtime polling), `login`, `idle` — each with a cooldown, created by
  the user or the agent (`create_trigger`), running headless turns tagged by origin.
- **Notification intelligence**: AgentOS *is* the notification daemon in de mode, and
  now the agent reads what it hears — a gated idle-time triage pass scores importance,
  groups, and writes a **"For you" digest** pinned atop the notification center.
- **"While you were away"**: a briefing composed on login/unlock when there's material,
  delivered as a desktop card. The knowledge loop may float **at most one suggestion**
  (24h quiet after dismissal), also as a card.
- **The metric exists now**: `/api/lifecycle` reports `initiative` — % of turns
  initiated by the OS over 7 days.

### First-run & apps are agentic
- **The wizard is a conversation**: two minimal screens (name, brain), then the *named
  agent takes over* — streaming in-character lines (`POST /api/setup/say`, canned
  offline fallback) with inline choice chips for autonomy, autostart (replaced in de
  mode by "this is your desktop now"), wallpaper presets and voice. Fully offline-safe.
- **appLLM v2**: user apps get `appLLM.stream`, `appChat(.stream)`, `appAgent` (a
  5-step tool loop under the app's own principal), and `appContext()` — all app-token
  authed and PDP-enforced. The builder persona teaches the new floor: stream anything
  user-visible; Quick Notes reference app updated to match.

Tests: 221 passing (build freshness, tool parity, proactivity gates, semantic search,
setup/appLLM v2, plus the whole existing suite).

## Boot-to-AgentOS release (2026-07-25)

The theme: goodbye GNOME. AgentOS installs as a real **Wayland login session** — its own
compositor engine, window management, settings, notifications and lock screen — while
staying 100% non-destructive: your existing desktop is one logout away, and hosted mode
is unchanged.

### The platform layer (one UI, four backends)
- New `agentos/platform/` — a capability contract (`windows.manage`, `net.wifi.join`,
  `brightness.set`, …) with four backends: `linux_de` (AgentOS **is** the session),
  `linux_hosted` (today's guest mode, behaviour-identical), `macos`, `windows`.
  `host.py` is now a thin facade; every existing endpoint keeps its exact shape.
- The UI never asks "what OS?" — it loads **`GET /api/platform`** once and renders per
  capability. Unavailable controls grey out with a sentence explaining why and, where an
  optional component would fix it, an Install… button.
- Run modes `de` / `hosted` / `kiosk`, auto-detected from how the session was started
  (`AGENTOS_SESSION` + `SWAYSOCK`), pinnable via `desktop.mode` / `agentos session mode`.

### The Wayland session
- `agentos install-session` now installs a **Wayland session** (sway as the invisible
  compositor engine — no bar, no keybinds, MIT-licensed) selectable at the login screen;
  `--x11` keeps the legacy kiosk; `--remove` uninstalls. The generated session starts the
  server *inside* sway so it inherits `$SWAYSOCK` and knows it owns the desktop.
- `agentos install-session --autologin`: true boot-to-AgentOS — display manager disabled,
  tty1 auto-login into the session. Prints the escape hatch (Ctrl+Alt+F3 →
  `--remove --autologin`) before touching anything; refuses over SSH without `--force`.
- Idle & lock: swaylock themed with your wallpaper; swayidle locks after
  `desktop.idle_lock_secs`, blanks outputs, locks before sleep, answers the ⏻ menu.

### Real window management on Wayland
- New `agentos/compositor.py` — sway/i3 IPC client: list/focus/close/float windows, move
  between workspaces, configure displays (mode/scale/rotation/enable), subscribe to
  events. Replaces the wmctrl dead-end that Wayland killed.
- The taskbar switches from 3-second polling to **compositor events**; right-click a
  native window for focus/float/move-to-desktop/close.
- New endpoints: `/api/windows/move`, `/api/windows/floating`, `/api/wm/workspaces`,
  `/api/wm/outputs`.

### System controls without gnome-control-center
- New `agentos/hostctl/` speaking **D-Bus** (dbus-fast, MIT — new dependency) to the
  distro's own daemons: NetworkManager (wifi **scan/join/forget**, airplane), BlueZ
  (**pair/connect/trust/remove**, device battery), UPower + power-profiles-daemon,
  logind (lock/suspend/brightness — no sudo, no prompts), PipeWire (`pw-dump`/`wpctl`:
  output/input switching, per-app volume), sysfs+logind+ddcutil brightness.
  Wifi passphrases travel over the bus, never a command line.
- New **System Settings** app: Network, Bluetooth, Displays, Sound, Power, Session &
  Mode, Components. Quick Settings rebuilt around capabilities (brightness sliders,
  output picker, power profiles, DND). All new control endpoints are app-blocked via the
  privilege guard.

### Notifications
- New `agentos/notifications.py` claims `org.freedesktop.Notifications` **in DE mode
  only** (DO_NOT_QUEUE — it can never fight GNOME for the name in hosted mode): native
  apps' notifications arrive as toasts + a new bell/notification center with
  do-not-disturb (critical urgency cuts through).
- Screenshots: `POST /api/screenshot` (grim/slurp, full or region) → `<workspace>/Screenshots`.

### Packaging with a licence gate
- New `packaging/audit-licenses.sh`: build-time assertion that everything shipped is
  permissive (MIT/BSD/Apache/ISC). It caught real ones: wl-clipboard is GPL-3 (dropped
  from Depends), xdg-desktop-portal is LGPL (demoted to interface-only). Generates the
  apt-dependency table in `THIRD_PARTY_NOTICES.md`.
- New `packaging/build-desktop-deb.sh` → **`agentos-desktop`**, a 4KB additive
  metapackage: Depends strictly permissive (sway stack), Recommends the distro's GPL
  daemons, Suggests the rest. postinst changes nothing about the default session.
- New `agentos/components.py` + Store-style consent flow (`/api/components`): what we
  can't ship (chromium is snap-only; ddcutil, wl-clipboard, power-profiles-daemon are
  copyleft) is offered with its licence shown, installed only on an explicit yes
  (sudo -n → pkexec → hand you the exact command).

### Guided installers for Linux, macOS and Windows
- One downloadable installer per OS, each a wizard that decides where AgentOS goes and
  how it starts — and that **offers what the system doesn't have yet** (Python, a shell
  renderer, the sway session stack, Ollama, bubblewrap, git, node…), installing each
  missing piece only when picked:
  - **Linux** `AgentOS-Setup-<ver>-linux-x86_64.run` — self-extracting (no makeself
    needed), whiptail wizard with plain-prompt and `--unattended` fallbacks; system
    (.deb) or user (`~/.local`) install; components include the login-screen session
    and boot-to-AgentOS (with the double-confirm + escape hatch).
  - **macOS** `AgentOS-Installer-<ver>.command` — double-clickable, native osascript
    dialogs; missing Python routes through Apple's Command Line Tools prompt; plus
    `packaging/macos/build-macos-pkg.sh` for the real `.pkg` choices wizard (runs on a
    Mac; core + open-at-login choices, repair.sh for the no-Python case).
  - **Windows** `packaging/windows/agentos.nsi` — NSIS MUI2 wizard (licence,
    components: Start Menu / desktop shortcut / start-at-sign-in / Ollama, directory,
    finish-and-launch), cross-built from Linux with `makensis`; `bootstrap.ps1` finds
    Python 3.10+ or installs it via winget / python.org, builds the venv, writes
    console-free launchers; per-user install, no UAC; uninstaller keeps `~/.agentos`.
- `packaging/build-all.sh` builds everything the current machine can and says exactly
  what was skipped and why. Install-time wizards own placement/startup choices; the
  existing first-launch wizard keeps owning product setup (name, model, autonomy).

### Doctor, docs, tests
- `agentos doctor` gained a desktop section: run mode, session entries, sway +
  `$SWAYSOCK`, renderer, NVIDIA `nvidia-drm.modeset`, and each D-Bus backend.
- New `docs/desktop-environment.md` (modes, install, autologin + escape hatch,
  architecture, licence policy, honest limits); updates across installation/desktop/
  troubleshooting docs.
- 60 new tests: platform contract (every backend answers every capability, with a reason
  when unavailable), session generation + autologin safety rails, compositor IPC against
  a fake sway serving the real wire protocol, hostctl parsers, the notification daemon
  over a real private D-Bus (which caught the request_name queueing bug), and the
  component consent mechanics.

Deferred, honestly: an on-screen keyboard for native apps (needs an MIT
`zwp_virtual_keyboard_v1` client), PIN-confirmation bluetooth pairing (needs a pairing
agent), and the AgentOS-rendered lock screen (`ext-session-lock-v1` — the natural first
piece of an in-house compositor).

## Unreleased — the app-store & IO-gates release (2026-07-24)

The theme: the store discovers the world's MCP ecosystem, and permissions learn *where*
a call comes from — plus the desktop grows real session controls.

### App Store = MCP discovery
- **Store → Discover** searches the public MCP registry (registry.modelcontextprotocol.io):
  thousands of community servers, normalized into one-click installs (npm→`npx`,
  PyPI→`uvx`, remote→`http` incl. header templates like `Bearer {key}`; results deduped
  across published versions). Nothing installs silently — every install goes through a
  "discovered X, build around it?" consent step; servers whose required keys aren't
  supplied are written **disabled** with placeholders.
- **Search is as-you-type and instant**: the upstream registry API takes 15-25s per
  request, so the whole catalog (`version=latest`) is synced into a local index in the
  background — saved page-by-page to `~/.agentos/mcp_index.json`, refreshed daily — and
  searches run against it in ~1ms. While the first sync runs, the Discover tab shows
  results growing ("indexing the registry — N servers so far…") and re-queries on a
  timer; stale keystroke requests are aborted.
- Agent tools to match: `discover_mcp_servers(query)` (read-only) and the approval-gated
  `install_mcp_server(registry_name, env)` — the agent proposes, the user disposes.
- **MCP Registry** (`mcp_registry` table, `GET /api/mcp/registry`): every installed server —
  discovered, manual (`add_mcp_server`), or app-package prerequisite — becomes a first-class
  record: origin, package info, status, doc.
- **Auto-generated documentation**: each registry entry gets a manual page under
  `~/.agentos/docs/mcp/<name>.md`, served into the **Docs** app alongside the built-in
  manual and refreshed with the live tool list when the server connects. 📖 buttons in the
  MCP app jump straight to it.
- After a Discover install, the Store offers to **build an AI-native app around the new
  server** in App Studio, permission manifest pre-scoped to `mcp.use · mcp:<name>/*`.

- **Deep discovery — when the registry isn't enough, the system widens the net**:
  sparse results auto-trigger a parallel sweep of npm and GitHub (deduped against the
  registry). npm finds install like any other server (`npm:<package>`, verified against
  the npm registry at install time); GitHub-only repos get a **🤖 Set up with AI**
  button — the agent reads the repo, derives the run command and keys, and connects it
  via `add_mcp_server`, approval-gated end to end. The `discover_mcp_servers` tool does
  the same widening on its own.
- **Apps are renameable**: `PUT /api/apps/{id}` (name/icon/description; id — and with
  it data, versions, grants, widgets — stays put), a ✏️ on every App Studio row, and a
  right-click menu on user-app desktop icons (Open · Rename · Edit in Studio · Delete).
- Store-triggered wrapper builds now ask for a **compact single-screen MVP** (local
  models were streaming multi-hundred-line suites for minutes, which read as hung).

- **Professional builds — a design system every app gets for free**: an OS-matched
  stylesheet (cards, rows, responsive grids, KPIs, tables, buttons, empty states,
  spinner) is injected into every app page (top of `<head>`, so an app's own CSS still
  wins). The App Builder now composes with those classes instead of inventing layout
  CSS — the thing weak local models are worst at — under hard rules (no absolute/fixed
  layout, no rotated text, no stretched buttons, labels on every input), and the build
  linter flags violations into the repair pass.
- MCP stdio noise fix: servers that print banners/console.table to stdout no longer
  spam a traceback per line ("Failed to parse JSONRPC message") — the stream
  self-recovers and that specific noise is filtered.

### Permissions: IO gates (surface scoping)
- Every turn/tool call now carries its **surface** — `gui`, `tui`, `telegram`, `api`,
  `task` — wired through the web desktop, TUI, Telegram bridge, scheduler and `/api/tool`.
- Grants gain a `surfaces` scope (default `*`): a rule permitted on all surfaces flows
  everywhere; a scoped rule only applies on its gates. Consent that exists only for other
  surfaces ⇒ the call is **denied with rule `io-gate`** and logged (policy + error entries).
- Permissions app: ⛩ gate badges on every rule (click to rescope) and an IO-gates picker in
  the Attach composer; `POST/PUT /api/grants` accept `surfaces`.

### Telegram channels
- The bridge now receives **channel posts** (`channel_post` updates): add the bot to a
  group or as a channel admin and the chat registers in the Telegram app — blocked until
  you permit it there, like every other chat. Telegram is a first-class IO gate.

### Desktop as the DE
- **Power menu (⏻) in the menu bar**: lock, restart AgentOS, suspend, log out, restart,
  power off — confirmed in the UI, executed via `loginctl`/`systemctl` (macOS: `pmset`/
  System Events) through `POST /api/power`. Apps are hard-blocked from it; the agent's
  shell still cannot shutdown/reboot. First step toward booting straight into AgentOS.
- **AI-native by default**: the App Builder persona now requires a real `appLLM` feature in
  every app it ships, and store templates lead by example (Quick Notes gained AI
  summarize/tidy on the natively selected model).

## Unreleased — the lifecycle release (2026-07-14)

The theme: from prototype to product. Chat and builds are now *reliable*, the full
Train · Test · Operate · Build · Ship · Manage lifecycle lives under one roof, and the OS
can check its own environment.

### Reliability (the "it hangs" class is gone)
- Chat turns and App Studio builds are **global and reconnect-safe**: events broadcast to
  every client, a `state_sync` on (re)connect re-attaches a reloaded page to running work,
  and every turn/build is guaranteed a terminal event on every exit path.
- **Real cancellation**: Stop first asks nicely, then cancels the task — which closes the
  provider's HTTP stream, the only thing that interrupts a model still evaluating a prompt.
- **First-token watchdog + heartbeats**: while a local model loads/evaluates, the UI shows
  "waiting for the model — Ns" instead of dead air; after a configurable timeout it fails
  loudly (`first_token_timeout`, default 180s).
- **Prompt-cache fix**: the timestamp moved from the first line of the system prompt to the
  last — local models no longer re-evaluate the entire (large) prompt every turn.
- **Ollama options**: explicit `num_ctx` (default 24576) instead of the silent 2–4k default;
  per-request `keep_alive` (default 30m) so a server-wide `OLLAMA_KEEP_ALIVE=-1` can't pin
  models into VRAM forever; optional thinking-channel switch.
- SQLite hardened: WAL + busy_timeout. Pre-bind port check: a second instance exits cleanly
  *before* spawning services (no more crash-loop wars); systemd units get restart backoff.

### App Studio v2
- **Truncation detected and handled**: providers surface finish reasons; text output cut at
  the token limit auto-continues (bounded); truncated tool-call JSON returns actionable
  guidance instead of a silent retry loop; Anthropic `max_tokens` is configurable (32k for
  builds) instead of hardcoded 8k.
- **Completeness validation before install**: structural checks (unclosed tags/scripts,
  content after `</html>`, JS leaking as visible text) gate every generated app, feed one
  repair pass, and anything unfixed ships as an explicit warning — never a silent success.
- **Local-model build mode**: Ollama models build without tool-calling (several local
  templates silently swallow large tool payloads) — output contract + `​```html` extraction +
  validation; announcement-only replies get one direct nudge; failure-retry only ever
  escalates to a *cloud* model (never a bigger local one).
- Timeouts are reported as timeouts (not "cancelled"); failed tool calls are visible in the
  build log; builds survive reloads via `GET /api/build/status`.

### The lifecycle
- **Mission Control** app: all six pillars — Train, Test, Operate, Build, Ship, Manage — one
  live screen with deep links (`GET /api/lifecycle`).
- **Train**: TrainForge integrated as a managed loopback service + the **Train** desktop app
  (datasets, LoRA fine-tuning, live metrics, model endpoints, HF publishing) + five `train_*`
  agent tools incl. Autopilot.
- **Test**: a real pytest suite (`tests/`), a `run_tests` agent tool, and a **test gate on
  self-modification** — the OS refuses to restart onto source that fails its own tests.
- **Ship**: structured git tools (`git_status/log/diff/init/commit/branch/remote/push/pull/
  clone`), GitHub PAT integration (Settings → GitHub; token env-injected, never logged),
  `export_app_to_git` (app → project folder → repo → GitHub), and `git` removed from the
  blanket-safe shell list (read-only subcommands stay free; pushes/resets ask).
- **`agentos doctor`**: port conflicts, duplicate instances, crash-looping units, Ollama
  reachability/VRAM pinning/network exposure, DB integrity, companion checks.

### Companion agents, self-healing, auto-fetch
- **Hermes integration** — AgentOS interoperates with a local Hermes install: `hermes_status`,
  `hermes_ask` (delegate a task to Hermes like a cross-product subagent), and `hermes_send`
  (deliver through any platform Hermes is paired with — WhatsApp/Slack/Discord/Signal),
  surfaced in Mission Control's Operate lane.
- **Hermes as a wrapped engine** — AgentOS is now a control surface over Hermes, not just an
  interop layer:
  - **Engine selector in chat** — the model dropdown offers "🜁 Hermes agent"; picking it routes
    that conversation's turns to Hermes (with AgentOS's working indicator, cancellation, and
    persistence) instead of the built-in Aria agent. It's a per-turn choice, never persisted as
    the global default (background tasks keep their real model).
  - **Download from inside AgentOS** — the new **Hermes app** downloads Hermes (MIT, from
    `hermes.repo`), provisions its venv, and symlinks the CLI, streaming progress.
  - **Config editor** — read/edit/save `~/.hermes/config.yaml` in the Hermes app (models,
    providers, toolsets, personalities), YAML-validated before save with a `.bak` kept; API keys
    in `.env` are never shown or touched. Gateway start/stop and update controls too.
  - Added PyYAML as a dependency so config edits are validated, not silently accepted.
- **TrainForge auto-fetch** — if the training service isn't on disk, the Train app (and the
  agent) clones it from `trainforge.repo` and provisions it via `run.sh` (venv + deps + GPU
  stack), with live download/install progress in the UI. Configured path that's gone empty
  falls back to detection/fetch instead of erroring.
- **`agentos doctor --fix`** — auto-remediates the safe items: stops a crash-looping unit,
  releases VRAM-pinned Ollama models, sets the DB to WAL; prints exact sudo steps for the
  rest (Ollama `0.0.0.0` exposure). Doctor now also reports Hermes and the fetchable Train
  service, and suggests `--fix` when it finds something.

### macOS
- **Folder sandbox on macOS** — `run_command` is now jailed on macOS too, via `sandbox-exec`
  (writes confined to the workspace + tmp/caches; parity with bubblewrap's guarantee that the
  agent's shell can't modify files outside the workspace). Previously macOS had no bwrap so
  commands ran unjailed.
- **Chat liveness** — a running turn always shows motion: an elapsed-time "working" indicator
  between and after tool calls, and streamed text forces a compositor repaint — fixing the
  macOS symptom where a reply only appeared after switching chats/tabs. Model heartbeats now
  render even once the assistant bubble exists.
- `/api/system` (Task Manager, TUI System tab) is now cross-platform: sysctl/vm_stat/`ps -r`
  on macOS instead of `/proc/stat`/`/proc/meminfo`/GNU ps — the TUI no longer crashes with
  "no such file or directory /proc/stat" on Mac.
- MCP servers now spawn reliably from GUI-launched instances (macOS LaunchAgents, Linux
  systemd): `npx`/`uvx` are resolved over an extended PATH (Homebrew, nvm, ~/.local/bin,
  pnpm, bun, cargo) and child processes inherit it; a missing runtime produces a clear
  "install node/uv" error instead of a silent failure.

### Docs & TUI
- New guides: lifecycle, training, git & shipping, TUI, security/threat model.
- TUI chat now streams (line-by-line), shows model heartbeats and failed tool calls, and
  filters the broadcast stream correctly.
