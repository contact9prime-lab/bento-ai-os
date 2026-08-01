# AgentOS — working notes

Read this before changing anything. It records decisions that are expensive to
rediscover, not style preferences.

---

## THE THREE FACES: GUI, TUI, SUI

**Every feature must be considered in all three, every time. This is the first
question to ask about any change, not the last.**

| | What it is | How it is drawn |
|---|---|---|
| **GUI** | AgentOS as an app on someone else's desktop — macOS, Windows, Linux, or just a browser tab | `agentos/ui/index.html` in a browser window |
| **TUI** | AgentOS on a machine with no screen — over SSH, on a server, on a headless Pi | `agentos/tui_app.py`, `agentos/clitui.py` |
| **SUI** | AgentOS **is** the Linux session: it owns the whole machine | `agentos/shellhost.py` — the same HTML, drawn as a **wlr-layer-shell surface** |

They are one codebase and one server. A feature is not finished when it works in
one of them.

For each change, answer these three and write the answer down:

- **GUI** — does it work in a plain browser with no compositor, no `.desktop`
  files and no root? Capabilities must degrade to an honest sentence, never a
  dead button. `/api/platform` is how the UI finds out; branch on capability,
  never on operating system.
- **TUI** — is the thing reachable without a pointer? If it is a new server
  capability, it belongs in the TUI or in a CLI verb. If it genuinely cannot
  exist there (window snapping), say so rather than leaving a silent gap.
- **SUI** — does it hold up when AgentOS is the desktop? The traps here are real
  and they are listed under "The session UI" below: the desktop is not a window,
  native app windows exist and are above it, the chrome bands are reserved with
  the compositor, and a phone may be looking at all of it from another room.

When something is deliberately not in one of the three, say why in the code
comment. "Not applicable" is a fine answer; silence is not.

---

## The session UI (SUI) — the part most likely to be got wrong

The desktop is **not a window**. It is a layer surface on the **BACKGROUND**
layer, which is below every ordinary window by definition. This is why native
apps stack above it correctly with nothing being raised or lowered.

Consequences that have each caused a bug:

- **There is no shell window to find.** `compositor.find_shell()` returns `''`
  in SUI. Anything that shuffles "the shell window" must check
  `compositor.SUI_HOST[0]` first; `anchor_shell` and `raise_shell` already do,
  and return success by doing nothing.
- **Coming to the front is a layer change**, done by the page through
  `suiRaise()` → `window.suiCall('raise')`. Do not add HTTP round trips or
  compositor commands to that path.
- **The menu bar and dock bands are reserved** as layer-shell exclusive zones by
  two empty, click-through strut surfaces. The page measures its own chrome and
  tells the host (`00-sui.js`). Never hardcode a chrome height: use
  `compositor.work_area()`, which reads the compositor's usable area.
- **Native windows are real.** They are not in the page, they never travel over
  HTTP, and a remote browser cannot see them — see `docs/remote-access.md`.
- **The Chromium fallback still exists** for machines without WebKitGTK, and it
  *does* have a shell window with all the old trade-offs. Both paths must work.

### Testing SUI

Do not reason about it — run it. `packaging/dev/sui-testbed.sh up` brings up a
complete session on a headless compositor (sway + server + layer-shell host) and
`shot` captures the screen. Two things it documents, learned the hard way:

- `WEBKIT_DISABLE_COMPOSITING_MODE` and `WEBKIT_DISABLE_DMABUF_RENDERER` are the
  folklore fix for WebKitGTK on software rendering, and they are what **crash**
  it. WebKit's own defaults work. Do not "fix" this back.
- sway only re-renders **damaged** regions, so a headless screenshot can show
  stale black where the desktop has not changed. Force a full repaint first
  (`shot` does). A missing region in a capture is usually the capture, not a bug —
  verify before chasing it.

---

## Spaces: one visibility rule, written once

A space is a thing the user is working on. Memory, KG assertions, conversations, assets,
runs, tasks, logs and audit rows all carry `space_id`, and `''` is the global scope.

**The rule is `space_id IN ('', :active)` — a space sees its own rows AND the global
ones** — and it lives in `memory.Store._space_clause`. Do not re-implement it inline.

Three things that have to stay true:

- **`''`, never NULL.** Three-valued logic in that clause is how this rots: one forgotten
  COALESCE and every pre-existing row disappears from every view.
- **The graph is scoped on its EDGES.** An entity is the same entity everywhere; an
  assertion belongs to a project. `kg_nodes.name` is UNIQUE and must stay that way.
- **The conversation decides the turn's space**, not whatever the user last clicked. The
  per-surface `cfg["spaces"]["active"][surface]` only seeds *new* conversations.

`space_id` is injected into tool args by the agent loop (`SPACE_SCOPED_TOOLS`), never
declared in a tool schema — a model must not be able to reach into another project by
naming one. `everywhere: true` is the one declared way out, so the gate can see it.

## Everything a principal does goes in the ledger

`PDP.decide()` writes one `audit` row per decision. That is the only place it happens, and
it is why every capability call in the OS must keep funnelling through the PDP rather than
checking autonomy inline. `logs` remains the free-text operator diary; `audit` is the
structured record (principal, surface, action, resource, effect, rule, outcome).

New capabilities get their own **action**, not another `tool.use` string — `media.read`,
`media.generate` and `space.write` exist because "may look at the gallery but may not bill
my image provider" has to be expressible as one grant.

## Licensing: permissive only, and ask rather than ship

What AgentOS **depends on**, it is effectively distributing, and that set must be
permissively licensed (MIT/Apache/BSD/ISC). `packaging/audit-licenses.sh` gates
it and must stay green.

Anything copyleft that is genuinely useful is **asked for, not shipped**:

- `agentos/components.py` — the catalogue. Each entry states what it unlocks, its
  licence, and the exact command. Nothing installs without the user agreeing to
  that specific thing with the licence in view.
- `Suggests:` in the packaging, never `Depends:` and never `Recommends:` — apt
  installs Recommends by default, which is the same thing with a softer name.
- The privilege ladder is always: passwordless sudo → polkit prompt → hand back
  the exact command. Never a silent system change.

This is why the native desktop surface (GTK, PyGObject, WebKitGTK — all LGPL) is
a Suggests plus three separate offers, even though it is what makes AgentOS a
desktop.

---

## The UI is built, not edited

`agentos/ui/index.html` is **generated**. Edit `agentos/ui/src/` and run
`python -m agentos.ui.build`. `tests/test_ui_build.py` fails if the shipped file
is stale.

The bundle is one concatenated `<script>`, in filename order. Two rules follow:

- **`let`/`const` at the top level are a trap.** Anything earlier in file order
  that calls into your file sees them in the temporal dead zone and throws. Use
  `var`, or name the file so it loads first. (`00-sui.js` is named that way for
  exactly this reason, after `00c-` threw on every session start.)
- Function declarations hoist across the whole bundle, so cross-file calls are
  fine; module *state* is not.

---

## Performance rules that are load-bearing

- **Windows sleep.** Periodic work belongs in `winTick(w, fn, ms)`, not
  `setInterval`, so it stops when the window is minimised, on another desktop, or
  covered. A bare `w.timer = setInterval(...)` is a regression and
  `tests/test_ui_lifecycle.py` will fail.
- **`backdrop-filter` compounds.** Every translucent surface makes the compositor
  re-blur everything beneath it, so cost grows with window count. The base `.win`
  rule must never blur (its background is opaque — it cost 8fps for nothing).
  Glass themes declare their own, and `Themes → Effects` turns it down.

---

## Honesty rules

- A capability that is missing reports **why**, in a sentence, plus the component
  that would fix it. Never a dead control.
- A remote browser is told when something happened somewhere else ("opened on
  `<host>`"), because a native app launched from a phone really did start — in
  another room.
- Generated files (`SWAY_CONF`, the session scripts) go stale across upgrades.
  `session.config_is_stale()` and `refresh_config()` exist because every window
  fix shipped for months never reached machines that had already installed.
- Fix the cause. Measure before and after, and put the numbers in the commit
  message.
