# Changelog

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
