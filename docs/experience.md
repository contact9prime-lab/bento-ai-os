# The living desktop — motion, language, initiative

> **Second drop — the ever-present agent.** The agent is no longer an app:
> the **omnibar** floats above the dock always (start typing anywhere on the
> desktop; Tab accepts the intent ghost; Enter streams an answer card; one
> click escalates to Chat — all on the persistent Desktop thread), and every
> window's **✦ button** opens that app's copilot — a scoped conversation that
> sees the app's live state (`APPS[id].context(w)`), acts through tools, and
> keeps one persistent thread per app (the "Copilots" group in Chat's sidebar).
> Apps refresh as the agent's tools run, and touched windows/dock icons glow.
> User-built apps get the same via `appCopilot.mount({starters})` in the app
> runtime — mounted by default in every generated app. Under the hood:
> chat-event sinks (`sinkOn/sinkOff` in the websocket module) let any surface
> render any conversation, and `run_chat` accepts capped per-surface context
> appended to the system prompt.

The 2026-07-26 release closes the two gaps between "a chat app with an OS around
it" and a truly agentic OS: the desktop now *behaves* like a physical place, and
the agent has hands on every part of the machine. This page is the map.

## The three principles

1. **Motion is object permanence.** Windows zoom out of their dock icon, minimize
   back into it, FLIP between sizes, snap to edges with a preview, and lift while
   dragged. If something appears or disappears without animating, it's a bug.
2. **Language is the primary input.** The command palette (`Ctrl+Space` / `Ctrl+K`)
   routes natural language to *direct actions* first, fuzzy app matches second, and
   "Ask your agent" always last. The agent has the same verbs as tools.
3. **The OS initiates.** Triggers, notification triage, briefings and suggestions
   let the machine start useful turns — always rate-limited, always attributable
   (`/api/lifecycle` → `operate.initiative` reports the % of OS-initiated turns).

## Working on the UI

`agentos/ui/index.html` is generated. Edit the modules under `agentos/ui/src/`
(`css/*.css`, `shell.html`, `js/*.js` — concatenated in filename order), then:

```sh
python -m agentos.ui.build          # writes index.html
python -m agentos.ui.build --check  # CI freshness check (also a pytest)
```

Design tokens live in `src/css/00-tokens-base.css`: the type ramp (`--fs-*`),
spacing (`--sp-*`), radii (`--r-*`), elevation (`--el-1..5`), motion
(`--d-*`, `--ease-*`), and mode-aware hairlines/scrims. New UI must use tokens —
the drift they replaced (27 font sizes, 43 shadow variants) is not coming back.
Motion helpers are global (`src/js/04-motion.js`): `Motion.run` (WAAPI +
reduced-motion in one place), `zoomWin`, `flipWin`, `popIn/popOut`, `ctxShow`,
and the dialog sheets `osConfirm` / `osAlert` / `osPrompt` — native
`confirm()`/`alert()`/`prompt()` are banned.

## Window management

Drag to an edge for halves/quarters (top = maximize); 8-way resize handles;
`F3` or `Ctrl+↑` for Exposé (live windows in a grid); `Ctrl+Tab` to switch;
Files and Terminal open multiple windows (dock right-click → New window).
The dock magnifies under the pointer, bounces on launch, and hides beneath a
maximized window (touch the bottom edge to peek).

## The agent's hands

Everything the UI can do is a PDP-gated tool. Highlights: `desktop_state` (one
snapshot of windows/battery/network/volume/notifications — also injected into
the system prompt as a live machine-state line), `control_desktop` (open/close/
focus apps, switch desktops, apply themes via the server↔shell command channel),
`wifi` / `bluetooth` / `audio` / `set_brightness` / `power_profile`,
`take_screenshot` (the agent sees the screen), `power_action` (**always asks**,
even at full autonomy), `search_files` (semantic), `create_trigger`.

## Proactivity

- **Triggers** (`Scheduler`): `notification` (substring/regex), `file_change`,
  `login`, `idle` — each with a cooldown, each running a headless turn tagged
  with its origin.
- **Notification triage** runs only when the pile is worth a model call and the
  machine is idle; it scores importance and pins a "For you" digest in the
  notification center.
- **Briefings** ("while you were away") and **suggestions** (max one live, 24h
  quiet after a dismissal) arrive as dismissible desktop cards.

## First-run

Two minimal screens (name, brain) and then the named agent speaks for itself —
streamed via `POST /api/setup/say` with canned offline fallbacks, choice chips
for autonomy/autostart/wallpaper/voice, and de-mode-aware copy. `agentos setup`
remains the TTY equivalent.

## Boot chain (de mode)

plymouth (optional `plymouth-theme` component) → sway (base color matches the
shell) → renderer opens `~/.agentos/boot.html` instantly (branded splash that
probes the server and hands off when it answers) → the in-page splash leaves on
readiness, not a timer. Wallpaper changes propagate live to the compositor and
swaylock.
