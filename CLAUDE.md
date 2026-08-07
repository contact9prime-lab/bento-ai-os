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

## One deliberate name divergence: the app is "Workflows", the code says `flows`

The app in the dock is **Workflows**, because that is the word people arrive with. Every
identifier underneath is `flow`: the `flows` table, `/api/flows`, the `flow.write` action,
`Principal("flow", …)`, `create_flow`. This is a decision, not drift — do not "fix" it by
renaming either side.

What makes it safe is that the older thing genuinely called a workflow — the fixed DAG in
`workflows`, `run_workflow`, `/api/workflows` — no longer has a UI. Its engine still works
for anything already using it, but it is not offered, not seeded, and not a tab, so the two
meanings never appear on screen together. If you ever put static DAGs back in front of a
user, this divergence stops being safe and one of the two has to be renamed.

## Flows: the master orchestrator is an agent, and that has three consequences

A flow is a mission, a roster and declared permissions; the master picks the agents while it
runs (`agentos/flows.py` defines, `ControlPlane.run_flow` executes). Full reasoning in
`docs/design/flows.md`. Three things will bite whoever touches this next:

- **The depth cap is the permission gate, not a counter.** The master is a `flow` principal
  with NO default for `agent.invoke` (`rule="roster"`), so only a grant its own definition
  wrote lets it delegate; its children are `subagent`s, which `BUILTIN_DENY` already refuses.
  `delegate` is absent from `risk_of`'s table and therefore arrives as *safe* — remove the
  roster deny and every flow can reach every subagent.
- **The orchestrator's four tools close over the run id on purpose.** They are built per run
  in `fabric.py` and are deliberately not in `tools.py`/`TOOL_SCHEMAS`. A global
  `delegate(run_id=…)` would take the run id as an argument, and an argument is something a
  model can invent.
- **`max_seconds` is working seconds.** Time spent paused for an approval is not charged
  (`fabric.Budget`). Do not "simplify" this back to a bare `asyncio.wait_for`: that is what
  made asking a human a reliable way to kill a run. The outer `wait_for` at
  `budget + approval_timeout + 60` must stay — a hung run holds `knowledge.turn_started()`
  and degrades the whole OS.

**A disabled flow holds nothing** — `reconcile_grants` returns no grants and
`reconcile_triggers` removes the `tasks` rows while keeping the declarations. That is what
makes it safe for the model to draft a flow into the list without asking: Enable is the act
of granting. Do not "fix" a disabled flow's missing permissions by writing them anyway.

Definition-time permissions become real `grants` rows with `source='definition'` and
`source_ref='flow:<name>'`. `add_grant` keys its dedupe on `source_ref` too, because a
hand-written grant and a definition one can read identically and reconciliation must never
revoke somebody's deliberate decision.

## Quarantine: the ceiling that answers "how often?"

Grants answer *may it?*, budgets answer *how long?* — neither answers *how often?*. A
subagent is bounded by `max_steps` and a flow by its delegation budget, but a user app runs
in a browser tab and can loop for as long as the tab is open.

The rate ceiling sits in `PDP._decide` **before grants**, beside the channel and taint
ceilings and for the same reason: a grant of `fetch_url` is consent to fetch pages, not
consent to fetch six hundred a minute. Three things about it are load-bearing:

- **Calls are metered in classes** (`policy.call_class`): model calls and tool calls have
  separate budgets. Six model calls a minute is money leaving; six fetches is a page
  refreshing. Counting them together either holds every working app or catches no runaway.
  The defaults are calibrated against real measurements on this machine — the busiest
  legitimate app burst was 25 fetches in 10s. Do not tighten them without measuring again.
- **The PDP writes the hold itself**, then calls `on_rate_trip` for the side effects. If the
  callback owned the write, an unwired embedding would refuse one call, re-meter the next,
  and let the loop straight through.
- **Never revoke an app's token to silence it.** `_principal_of` maps an unknown token to
  `MAIN`, so revoking identity *promotes* the app to the user's permissions. Suspension is
  what stops it; `_stale_app_token` refuses a presented-but-unknown token outright, which a
  server restart alone can otherwise reach.

Release is a user decision with three shapes, all recorded in `quarantine.release_mode`:
`once` (still watched), `forever` (an exemption, which is why the row is kept rather than
deleted), `deleted`.

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
