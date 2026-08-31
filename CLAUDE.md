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

## A phone is a face too, and a fingertip is 9mm

The GUI face is not "a browser": it is a browser on a 390px screen held in one
hand, which is how remote access is actually used. `15-responsive.css` had that
layout — sheets, a bottom dock, safe areas, sheet popovers — and every control
INSIDE an app still had the size a mouse gave it. Measured in Chrome with touch
emulation, signed in over the LAN as a phone: a 10x16 ✕ in Flows, a 98x23 button
in Chat, a 26x26 window close, Settings' 188px rail leaving a 202px pane whose
rows ran to x=571 on a 390px screen, and a ✦ whose panel is `display:none` here.
Every one of those was reported as "the buttons don't work", and every one of
them was true.

- **`--tap` is the floor and it is real size, not a halo.** An invisible enlarged
  hit area is the tempting fix because nothing reflows — and two adjacent 16px
  buttons with 40px halos overlap, so whichever paints last silently eats the
  other's taps. Reflowing a dense row on a phone is the correct outcome: on a
  phone that row was too dense.
- **A row that cannot fit must scroll, and must not rest half-way.** `.seg`,
  `.prefs-side` and the dock all overflowed a phone. Scroll-snap is not polish
  here: a scroller resting mid-item puts the centre of a button outside its own
  box, where the tap lands on whatever is behind it.
- **A control whose target cannot exist here is removed, not left.** The ✦
  copilot button answered a tap by doing nothing, which is the dead control the
  honesty rules forbid — and is indistinguishable from the OS being broken.
- **Measure it in a browser with real touch emulation.** Every number above came
  from CDP `Input.dispatchTouchEvent` and `elementFromPoint`, not from reading
  the CSS; synthetic clicks land dead centre every time and prove nothing about a
  finger. `tests/test_ui_touch.py` pins the rules that came out of it.

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

## Users are isolated by DIRECTORY, and that is the opposite claim to spaces

`space_id` is a column and its rule is deliberately leaky. A user is not a column —
a user is **their own home**: `~/.agentos/users/<id>/{agentos.db,config.json,workspace,
assets,soul.md}`. One forgotten WHERE clause among ~250 query sites is somebody reading
a colleague's memory, and no amount of review makes that failure mode acceptable. Two
files cannot leak into each other; that is the whole argument. Full reasoning in
`docs/users.md`.

`users.enabled()` is False until somebody is added, and everything below is invisible
until then — an install that never adds a user keeps using exactly the files it always
used. `is_admin('')` is True for the same reason: a machine with no accounts has nobody
to refuse.

**Nothing threads a user through a signature. The LOOKUP resolves.** `users.current()`
is a contextvar set by the request middleware from the SIGNED COOKIE ONLY — never a
header or a query parameter, because those are things a caller chooses and this decides
which private directory gets opened. Three mechanisms read it and there should never be
a fourth:

- `server._State.__getitem__` — routes `state["store"]`, `state["cfg"]` and the three
  per-user services. ~250 call sites unchanged.
- `users.Scoped` — a two-descriptor mixin on every long-lived service. `self.cfg = cfg`
  in an existing `__init__` keeps working; it stores the machine's copy as the fallback.
- `users.as_user(uid)` for background work. `asyncio.create_task` copies the context, so
  a job launched at 08:00 still reads its owner's memory hours later. **That inheritance
  is why this is a contextvar and not a parameter** — do not "simplify" it to an argument.

Three things will bite whoever touches this next:

- **In-memory caches must be keyed on the user, not only on a name or a version.** A
  version counter is per-database, so two people can both be at `grants_version` 3 —
  without the prefix the second is decided against the first one's grants. `PDP._who()`
  exists for this; the rate meter and the skills cache collide the same way, because two
  users may each own an app called `notes`.
- **`users.USER_KEYS` is the whole definition of "mine".** The line is cost and blast
  radius, not how personal something feels: anything that spends money or reconfigures
  the machine stays the machine's. A key missing from that tuple silently never saves.
- **The machine config is the seed for every account created later.** `machine_view()`
  strips the personal keys before an admin's save reaches it — leaving a Telegram token
  there hands it to the next person who signs up.

**A passphrase is not a user, and the two locks are alternatives.** `remote.lock_kind`
is the whole rule: accounts win, and a shared passphrase in front of them is one more
secret held in common by people this OS otherwise keeps in separate directories. Every
part of the system knew that except the one command a headless machine is driven with —
`bento remote --on` demanded a passphrase on a machine that already had accounts, then
stored one `lock_kind` would never read. When you change either lock, check all four
places that decide it: `enabled()`, `sanitize_remote()`, `_remote_cli` and the sign-in
page's `/api/users/who`. And say WHICH lock is on: "where is the user?" is the first
question anybody asks of a machine they have just made reachable, and on a machine with
no accounts the honest answer is that there isn't one — you are the machine.

**A locked screen is a third refusal, and it sits in front of both.** `remote.session_locked`
reads a lock out of the SIGNED cookie, and `_authed` / `_ws_authed` refuse it BEFORE loopback
trust and before the account check — otherwise the page would be behind a lock screen while its
socket kept streaming a turn. Two rules keep the two locks apart: the HOST lock
(`/api/power {"action":"lock"}`) is the only correct one in SUI, where native windows sit above
the BACKGROUND-layer desktop and nothing the page does can cover them; the SESSION lock
(`/api/session/lock`) is offered only outside SUI, where the host's would lock the screen of the
*server* while the person's desktop stays open in their hand. A locked cookie still RESOLVES to
its owner in `resolve_user` — that is what makes unlocking one password instead of a sign-in, and
it is the whole difference from Sign out. A machine with no key (`remote.lock_kind` == `''`)
refuses to lock rather than shipping a door that never opens again. Full reasoning in
`docs/users.md`.

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

**Triggers are the event side, and three rules keep them honest.** A flow starts on `cron`,
`message`, `webhook`, `os_event` or `flow_done` — only the first is time-driven, and the rest
are why "event-driven" is not a missing feature.

- **A trigger this machine cannot fire is never offered.** `notification` needs AgentOS to own
  the session and `login` needs DE/KIOSK; `file_change` and `idle` are polled and work headless.
  `flows.os_event_problem()` is the one answer, carried on `/api/platform` as `os_events`, and
  the save refuses what the editor greys. A stored trigger that can never fire reads as armed
  forever, which is the dead control this file's honesty rules forbid.
- **A webhook is the one door with no cookie**, so the trigger row records its owner and the
  route enters `users.as_user(uid)` before reading anything. Without that the fire resolves to
  the machine — and since accounts are isolated by directory, the trigger is not even in the
  machine's database. `bento flow rotate` revokes a leaked URL without re-saving the flow.
- **Chaining is `flow_done`, not one flow POSTing another's webhook.** That was an HTTP round
  trip and a shared secret to say something local, and it made the second run look like it came
  from the internet. A flow naming itself is refused at the save; `MAX_CHAIN_DEPTH` stops the
  A→B→A cycle a self-check cannot see.

**A hook's key is minted, rotatable, and only expires if you say so.** AgentOS mints the
secret (`token_urlsafe(24)`) rather than letting a caller choose one, because a token
somebody picks is a token somebody reuses. It does NOT expire by default — a key that dies
on its own silently stops a standing job — but `bento flow rotate --days N` sets a lifetime,
and the refusal after that date says *expired*, not *bad secret*: the difference between
"rotate it" and hunting a leak that never happened.

**Being ASKED too often is its own overflow, and it quarantines.** Grants answer *may it?*,
the cooldown answers *how often may it run?*, and neither bounds how often a URL may be
POSTed — a retry loop or somebody who found it costs a lookup and a compare every time.
`_hook_overflowing` is the ceiling, in memory for the same reason `RateMeter` is (a gate
that costs a write is one a flood turns into a disk problem), and the outcome is the one
this OS already uses everywhere: held until a person releases it, ONE row per incident, with
`forever` kept as an exemption so the next burst does not re-hold what was already judged.

**A flow can be authored from a terminal.** `bento flow add/trigger/rotate/enable/disable` go
through `flows.save` — the same door the editor uses — because a second authoring path would be
a second permission model. `add` creates missing roster agents (`new_agents`, as the editor
does) and leaves the flow DISABLED, since enabling is the act of granting.

**And observed from one.** `bento flow runs` / `events <run-id>` read `fabric_runs` and
`fabric_events` directly, so a headless box can see how its flows went with the server down.
`bento flow doctor` is the one command that answers "is any of this actually working?": every
trigger says whether it can fire HERE and why not — an OS event this mode cannot deliver, a
`flow_done` following a flow that no longer exists, a quarantined or expired webhook — which
is the honesty rule applied to a surface that had no way to state it.

**A disabled flow holds nothing** — `reconcile_grants` returns no grants and
`reconcile_triggers` removes the `tasks` rows while keeping the declarations. That is what
makes it safe for the model to draft a flow into the list without asking: Enable is the act
of granting. Do not "fix" a disabled flow's missing permissions by writing them anyway.

Definition-time permissions become real `grants` rows with `source='definition'` and
`source_ref='flow:<name>'`. `add_grant` keys its dedupe on `source_ref` too, because a
hand-written grant and a definition one can read identically and reconciliation must never
revoke somebody's deliberate decision.

## Jobs are flows, and that is the whole design

`agentos/jobs.py` is a recipe catalogue and nothing else. It turns a recipe plus two or
three answers into a flow definition and hands it to `flows.save`. There is no job
engine, no job scheduler and no job permission model — a job that could do something a
flow cannot would be a second set of bugs in each of those.

It exists because the gap between "installed" and "useful" is where this OS is lost. The
first-run wizard used to end on a door onto an empty desktop; it now ends on "give me a
job", and the last button is "run it now, so I can see it work" — a schedule nobody has
watched fire is a promise, and a new user has no reason to believe one.

Three things must stay true:

- **The consent screen and the save are one computation.** `/api/jobs/preview` runs
  `flows.declared_grants` (pure) over the definition that will be saved. Describing the
  permissions separately is how the sentence somebody agreed to stops matching the
  permission they got.
- **Delivery is probed, never declared.** `deliveries()` asks the machine what works
  right now. A way out that is not set up is shown greyed with the sentence that would
  fix it — hidden reads as "this OS cannot", offered teaches people it lies.
- **`flows.job` is a column, not a heuristic.** Renaming a job in the editor must not
  orphan it from the list of what this machine is doing for you.

Keep `jobs.py` free of HTTP and asyncio. That is what lets `bento job` be the same
catalogue and the same install on a headless Pi, which is where a standing job earns its
keep and where there is no wizard.

## A channel is one AgentOS owns end to end

There used to be a second tier: platforms "carried" by the Hermes gateway — Slack,
Signal, Discord and the rest — delivered by shelling out to another agent installed on
the machine. It was removed, along with the rest of the Hermes integration.

The reason was not that the bridges failed. It was that we could not judge them: a
carried channel delivered OUT only, a reply arriving there was answered by a different
agent with a different memory, and nothing that agent did reached this OS's grants,
ledger or budgets. Depending on a surface you cannot evaluate is worse than having
fewer surfaces.

So the rule is now one line: **a channel is offered only if it brings a conversation to
THIS agent, through this policy, with every call in this ledger.** Telegram and
`agentos/whatsapp.py` qualify. When Slack or Signal earn a place they will be built to
that bar — not proxied to something that cannot meet it.
`tests/test_channels.py` enforces it, and also asserts the removed carrier surface is
really gone rather than half-removed.

## Executors: another agent may answer, and that is not the Hermes that was removed

`engine` decides who runs a turn. `aria` is the built-in loop; anything else in
`executors.ENGINES` hands the turn to an agent already installed on this machine
— Claude Code, Hermes, OpenClaw. `executors.roster()` is the list and every
surface reads it: the model picker, AI Providers, the onboarding brain step,
`bento doctor`. None of them names an executor, so adding one is a catalogue
entry rather than an edit in five places.

**This is deliberately not the Hermes that was removed, and the difference is the
same one the channel rule is built on.** The removed thing was a GATEWAY that
carried messages out to another agent with its own memory, whose replies never
reached this OS's grants, ledger or budgets. An executor answers *this* OS's
turns, through this PDP, into this ledger — the bar the carrier failed. The old
`hermes` config block (`repo`, `engine_enabled`) is still dropped on load,
because that shape configured the gateway and nothing else.

Three things that will bite whoever touches this next:

- **An engine that is not installed must never be returned.** `resolve_engine`
  probes before answering and falls back to `aria`. The setting outlives the
  binary in more ways than a load-time migration can catch — uninstalled later,
  edited by hand, a backup restored onto a machine that never had it — and a
  machine answering with nothing fails on every surface at once.
- **An executor is offered only if AgentOS can state its install truthfully.**
  Claude Code and Hermes have entries in `components.py` with a real command and
  their licence. OpenClaw is detected and used if present and has NO installer,
  because a fabricated command is a dead button, which every honesty rule here
  forbids. Say "you install it, I will use it" rather than guessing.
- **An executor OWNS its models.** See the next section: one picker, and the model
  list belongs to whatever is answering.

## OpenClaw plugins: the lifecycle is ours, the runtime is not

`agentos/ocplugins.py` installs OpenClaw's plugins through this OS's review — scan,
consent, grants, quarantine — by shelling out to the real `openclaw plugins ...` verbs
rather than reimplementing any of them. Full reasoning in `docs/openclaw-plugins.md`.
It exists because every other way code arrives here goes past a lock, and third-party
code running beside the agent this machine answers with should not be the exception
just because somebody else's CLI owns the door.

**The boundary is stated, not implied, and it is the first thing to keep true.** An
enabled plugin runs inside OpenClaw's process; its calls do not reach this PDP and
nothing here can refuse one. What AgentOS gates is the LIFECYCLE (`plugin.install`,
`plugin.enable` — their own actions, in `BUILTIN_DENY` for every non-user principal),
and what it enforces afterwards is ENABLEMENT, through the one lever OpenClaw
documents as absolute: `plugins.deny` wins over allow and over per-plugin enablement.
Claiming more than that would be worse than the feature not existing.

- **Install lands it DISABLED, and that is the design.** Scanning before the bytes
  exist means re-implementing OpenClaw's resolver for npm, ClawHub, git, archives and
  marketplaces — five ways to be subtly wrong about what is arriving. So the bytes
  land first and the scan reads the real `openclaw.plugin.json` on disk. It is the
  flows rule again ("a disabled flow holds nothing — Enable is the act of granting"),
  which is the strongest argument for it: one idea twice, not two half-ideas. The
  agent may install and may NOT enable, exactly as with `create_flow`.
- **The `plugin.run` grant is load-bearing, not a receipt.** `reconcile()` reads it
  back and turns a revoked grant into a real `openclaw plugins disable`. Remove that
  binding and the Permissions app becomes a list of things it cannot actually do.
  Reconciliation only ever turns things OFF — a reconciler that could enable is a way
  to grant without being asked.
- **Drift is measured against the PIN, not against the update.** AgentOS does not own
  the `openclaw` CLI: somebody running `openclaw plugins update` in a terminal, or
  editing a linked plugin's source, changes what it reaches without passing any screen
  here. `record_pin` therefore stores the verdict that was CONSENTED to, and both
  `update_plugin` and `reconcile` compare a fresh scan against that. Comparing across
  our own update call only — which is what it did first — misses every change that
  did not go through us. Only an ESCALATION holds; a plugin that got quieter is left
  alone, because a hold that fires on every update is one people click through.
- **`--force` is the person, never the caller.** It answers OpenClaw's own provenance
  question about an untrusted source. `bento openclaw install` demands `--yes`, the
  GUI asks, and the agent's tool cannot supply it at all. Defaulting it anywhere
  silently answers for somebody.
- **`--runtime` is never passed.** It imports the plugin's module to list what it
  registers — running the code to decide whether to run the code. The manifest is the
  static answer, and `contracts.tools` must match what the runtime registers anyway.
- **One verdict function.** `verdict_of` is imported from `appregistry`, not copied.
  Two definitions of "is this alarming?" is how one of them stops being read.

Plugins are the MACHINE's, not a per-user preference — they install into OpenClaw's
state directory and edit OpenClaw's config, both shared — so the routes are admin-only.
The PINS are personal and live under the existing `registry` USER_KEY: whom I trust
costs nothing machine-wide. Faces: GUI in Settings → Executors (`11b-openclaw.js`,
inert with one sentence when the CLI is absent), TUI as `bento openclaw` (as `bento
mcp` is the MCP pane's terminal face), SUI identical to GUI — a page, no native
process, nothing touching the compositor.

## Hosting a plugin ourselves: the second bargain, and why it is a different one

`ocplugins.py` governs a plugin that runs in OpenClaw's gateway, and can honestly
claim only the lifecycle. `agentos/ochost.py` + `ocp_host/host.js` change who runs the
plugin: AgentOS starts the Node process, hands the plugin its `api` object, and the
tools it registers arrive in the agent loop as `ocp_<plugin>_<tool>` — so every call is
a `PDP.decide`, an audit row and something quarantine can stop. Their ecosystem's reach,
inside this OS's permissions. **Both integrations are kept**: one is interop with a
machine that already runs OpenClaw, the other is absorption. They are not alternatives
and must not be collapsed.

The load-bearing parts, each of which was MEASURED rather than assumed:

- **The api shim IS the sandbox.** Node's permission model (`--permission`) denies the
  plugin filesystem and subprocess access — verified: `fs.readFileSync` and
  `child_process.execSync` both raise `ERR_ACCESS_DENIED`. What a plugin cannot take, it
  must ask for (`api.host.fetch`), and an ask is a round trip into Python and through the
  PDP. That inversion is the whole design: a capability taken is invisible, one requested
  is governable. An unwired `host_call` refuses everything, because an unwired embedding
  must be a closed door.
- **Network is NOT contained by Node and the report must keep saying so.** There is no
  `--allow-net`; `fetch()` works inside a permission-restricted process. Only an OS jail
  (`bwrap --unshare-net`, sandbox-exec) closes it, and on a machine with neither,
  `sandbox_report()["network_note"]` says `CANNOT CONTAIN` in those words. A consent
  screen claiming "sandboxed" where the network is open would be worse than no sandbox,
  because somebody would believe it. `tests/test_ochost.py` pins the report to
  `sandbox_mechanism()` so it cannot drift optimistic.
- **A refused API is named out loud.** `registerHook`, `registerChannel`,
  `registerTrustedToolPolicy` and the rest are defined as functions that REFUSE and
  record, never left undefined — an undefined property throws a TypeError deep inside
  the plugin with no explanation, while this reaches the user. The failure mode of every
  compatibility layer is a plugin that installs, reports healthy and silently does most
  of its job.
- **The manifest audits the shim.** OpenClaw requires runtime `registerTool` calls to
  match `contracts.tools`, so `discrepancy()` compares what the host caught against what
  the plugin promised. A registration the shim missed becomes a visible gap instead of a
  tool that quietly does not exist. This is what makes a compatibility layer auditable
  rather than hopeful — do not remove it to make the report cleaner.
- **stdout is the wire, so console is rebound before any plugin code runs.** A plugin's
  `console.log` would desynchronise every frame after it. Same rule as `wa_bridge.js`.
- **`plugin.tool` is its own action.** "May use the tools this plugin brought" has to be
  grantable apart from the OS's built-in tools, or installing a plugin would silently
  widen every grant somebody had already written.

`HostSet` deliberately has the same seams as `mcp_client.MCP` (`tool_schemas` +
`resolve`), because a hosted plugin tool and an MCP tool are the same KIND of thing — a
third party's tool behind a gate — and giving them one shape means the tool loop, the PDP
and the ledger need no new special case.

## A gap is a fork, not a dead end: `ocnative.py`

Both plugin integrations have gaps — the gateway one cannot gate a call, the hosted one
refuses part of OpenClaw's API and cannot contain the network without a jail. Saying so
was already the rule. What `ocnative.py` adds is the second answer: **build it natively
instead**, out of parts this OS already governs (MCP for tools, a flow for standing work,
a skill for know-how), where there is no shim and no ungoverned reach.

The plugin's manifest is a specification — it names the tools, the MCP servers, the events
and the config — so it is enough to brief the agent with. Three rules keep that from
becoming a machine for confident nonsense:

- **The brief is DERIVED, never invented.** Everything traces to something the manifest
  declares; a manifest that says nothing yields `buildable: False` and a sentence saying
  so. Guessing what a plugin called `voice-call` probably does would produce a plausible
  implementation of something nobody asked for, and nothing downstream could tell.
- **The same brief is the acceptance test.** `verify()` checks item by item against the
  document the build was given, which is what stops "done" meaning "the agent said done" —
  the same argument `preview()`/`enable_plugin()` share one computation. It checks
  REACHABILITY and says so: it can prove a flow exists and an MCP tool is offered, not
  that the tool does the right thing. Claiming more would make "verified" the most
  dangerous word on the screen.
- **A port is a proposal.** Everything it writes lands DISABLED. Porting must not be a way
  to acquire permissions without being asked.

Two traps found by building it. An in-turn hook (`llm_output`) has no equivalent, so it
must leave the buildable steps AND appear in `not_portable` — left as a step it becomes a
demand for a flow named `llm_output` that fails its own check forever, which is how a
verification step stops being believed. And a declined config setting is never a
failure: failing it would push the agent to invent a credential, the exact thing the
brief forbids.

`MAPPING` is the table of OpenClaw concept → Bento primitive, and its most important rows
are the ones whose target is `None`. A concept with no equivalent must be reported as
unportable, not quietly mapped onto the nearest thing that compiles.

The disclaimer is one computation shown by every surface (`preview()["compatibility"]`),
because a warning that differs between the terminal and the desktop is one somebody has
already got wrong — and it always names both roads. A disclaimer whose only way forward
is Proceed is a formality people learn to click through.

## The brain is one choice: an executor and one of ITS models

`executors.brains(cfg, models)` is the whole list — local providers, cloud
providers and other installed agents, each carrying the models it can actually
wake up — and `set_brain(cfg, executor, model, models)` is the only way to
change it. `/api/brains` and `PUT /api/brain` are those two functions over HTTP;
the chat header, the menu-bar chip, Settings → AI providers, the wizard's brain
step and the `set_engine` verb all read and write through them, so there is one
answer to "what is this machine running on" and one place it is decided.

It was two questions for a long time, and they disagreed on screen: `engine`
lived in this module, `default_model` lived in providers, and the picker showed
both in one dropdown. With Claude Code as the engine and a Gemini model still in
config, TWO options carried `selected` and the browser kept the last one — so
the control read "gemini" while the machine forwarded to Claude Code.

Four things that have to stay true:

- **One write, not two.** `set_brain` sets `engine` AND the model in the same
  call. Choosing a provider also sets `engine="aria"`, because otherwise picking
  a model changes nothing while a forwarder is on — the original bug.
- **Each executor remembers its own model.** A provider's is `default_model`; an
  agent's is `cfg["executors"][<id with _>]["model"]`. Switching away and back
  must not lose the choice already made.
- **The model list is validated against the executor.** `Claude Code does not
  offer 'google/gemini-3.1-pro'` is refused at the write as well as in the
  picker, so no config edit or verb can recreate the mismatch.
- **`brains()` is pure** — it is handed the model list. That is what lets the
  TUI, `bento doctor` and the wizard read the same catalogue without HTTP, and
  keeps one route from probing providers twice.

An agent executor's model list is the aliases its CLI documents plus the honest
empty choice ("whatever it is set to"). AgentOS does not fetch or invent a
catalogue for it; what the run actually woke up on comes back from the run
itself (`engine_info`) and that is what the chip shows.

## The three surfaces are stitched: bar → chat → Studio / Workflows

The prompt bar asks, the chat answers, and what the answer BUILT lives in
another app. Those seams are code, and each one was reported as "this makes no
sense" when it was missing:

- **The bar's thread exists before the send.** `omniThread()` creates the
  `origin:'omni'` conversation (POST `/api/conversations`) rather than waiting
  for the server to name one. A turn can sit queued for half a minute, and until
  it existed the sidebar showed nothing and "Open in Chat" landed elsewhere.
- **A queued turn says queued.** `miniFeed.queued()` marks the row, and
  `mfPaint` skips it: the activity record belongs to the turn running AHEAD of
  it, so painting it there made a waiting card claim another turn's step.
- **A turn that MAKES something offers the door to it.** `10a-handoff.js` maps
  the creating tools (`create_app`, `create_flow`, `enable_flow`,
  `save_automation`, `schedule_task`) to the app that owns the result, and the
  button selects the thing rather than just opening the app. It is derived from
  `tool_end` in the stream, so every live surface — Chat, the omnibar card, a
  copilot panel — gets it from one place. A tool that is not in that map
  deliberately gets NO handoff: an invented door is worse than no door.

## WhatsApp is one channel with two transports

`conf(cfg)["mode"]` decides which is live, and they fail in opposite directions:

- **`baileys`** (`wa_baileys.py` + the `wa_bridge/` Node sidecar) — a linked
  WhatsApp Web device. No Meta account, no webhook, no 24-hour window.
  **Unofficial**, and every surface that offers it says so in those words, because
  WhatsApp has banned accounts for automating on it.
- **`cloud`** (`whatsapp.py`, the default) — Meta's Cloud API. Official, and the
  right answer for an unattended machine, but it needs a developer account and a
  public HTTPS webhook.

Both reach `WhatsAppBridge.incoming()`. Pairing, the allow-list, the commands and
the turn are properties of the CHANNEL, not of how the bytes arrived — two copies
would drift, and the half that drifted would be whichever one was not being
demoed. `configured()` asks only about the live transport: holding the channel off
because four Cloud API boxes it will never read are empty is refusing to switch on
for a reason that does not apply.

Starting a link IS choosing the transport — `/api/whatsapp/link` sets the mode
itself rather than making the user find a dropdown first, and it is loopback-only
because a linked device is a credential.

### The link transport

- **stdio, never a port.** WhatsApp credentials behind an unauthenticated loopback port
  would be a full account takeover for anything else on the machine, and a bridge that
  outlives a crashed AgentOS keeps a live session nobody is reading.
- **The session directory is the phone.** `~/.agentos/whatsapp/session`, 0700,
  deleted on unlink and on factory reset. "Disconnected"
  with the keys still on disk is still a linked device.
- **A logout is never retried.** Exit code 2 means the credentials are void; retrying
  reads as "it keeps failing" rather than "you need to scan again".
- **Both sides need a deadline.** A socket that never opens produces no event at all,
  so the Node side has its own 25s timer. Without it the bridge exited 0 in silence and
  the card called that "off" — found by running it behind a proxy that blocks
  `web.whatsapp.com`.

### The cloud transport

Four things about it that a port of the Telegram bridge gets wrong for free:

- **It is a webhook, not a poll.** Meta calls this machine, so it needs a public HTTPS
  address. A webhook channel that is "on" but unreachable receives nothing, forever, with
  no error anywhere — `reachability()` exists so that state is stated, not discovered.
- **Verify the signature over the RAW bytes**, before anything parses them. Re-serialising
  the body changes key order and whitespace, so a check written against the parsed JSON
  fails on every legitimate message and then gets deleted rather than fixed. No app
  secret means refuse, not trust: it is a public URL.
- **The 24-hour window is real.** Outside it Meta will not carry a free-form message at
  all, so an unattended job cannot rely on it. `wa_upsert_chat` moves `last_inbound`
  only on an INBOUND message, because that is exactly what the rule measures. It does
  NOT apply to a linked device, and `window_open` must keep saying so — that exemption
  is the entire reason the link transport is worth its unofficial status.
- **Reply buttons are three, at 20 characters.** Over the limit Meta truncates
  server-side and the user approves something whose label was cut off.

Meta retries and redelivers, so message ids are remembered — otherwise one sentence
becomes several agent runs and the user pays for each.

## App distribution is FEDERATED; the registry is optional curation on top

Nobody hosts the commons. An author's app lives in the author's own repo at
`bento.agentapp.json` (see `appregistry.WELL_KNOWN`), discovery is the GitHub topic
`bento-app` (`/api/store/federated`, `bento registry search`), and `owner/repo[@ref]`
resolves across TWO CDNs (raw.githubusercontent + jsDelivr) so one outage does not take
the commons down. `owner/repo@commit` is the chain, literally: a git hash is a Merkle
root, so a pinned source names immutable bytes. Validity is decided by the RECEIVING
machine — it re-scans the code (a recorded verdict that disagrees with a fresh scan is
flagged: `scan_drift`), and pins source+signer on first install (`tofu_check`, the SSH
model: `changed-key` is the loudest alarm because that is what a hijacked author account
looks like). Pins live under the `registry` USER_KEY — whom I trust is personal.

The commons is HYBRID: agents contribute on the same terms as people. Authorship is
DERIVED from the app's version notes ("agent build" is what `create_app` has always
written) and stamped as `manifest.author.kind` (human/agent/hybrid) at export — never
declared, so it cannot be faked cheaply — and the consent screen says it. The registry's
CI refuses a package without it; the product only warns (an old package is
underdocumented, not hostile). The covenant (registry COVENANT.md) binds every author
kind equally, and its checkable clauses are checked, not asked for.

## The app registry is a Git repo of the packages the OS already speaks

`agentos/appregistry.py` + `registry/` (the seed of `bento-app-registry`), full story in
`docs/app-registry.md`. The load-bearing decisions:

- **No second format.** The registry stores `.agentapp.json` exactly as export writes it
  and Import reads it; propagation is a GitHub raw URL into the Import door that already
  verified checksums and staged grants. A registry format of its own would mean a second
  install path with a second review screen, and drift between them.
- **The verdict lives INSIDE the manifest** so the checksum covers it, and the signature
  (Ed25519 over the checksum) covers both. Editing code, permissions or the scan verdict
  of a verified package fails verification; recomputing the checksum turns that into
  `bad-signature`. `tests/test_appregistry.py` is mostly these attacks.
- **One implementation everywhere.** server.py imports the checksum from appregistry, and
  the registry's CI pip-installs this repo and imports the same module. Two definitions of
  "what bytes does the signature cover?" is how valid packages become checksum-mismatches.
- **`BUILTIN_KEYS` ships empty until the owner mints theirs** (`bento registry keygen`,
  private key 0600 in their home, public half pinned in source). A trust root whose
  private half ever existed on a build machine would make "verified" meaningless. Config
  may ADD keys, never shadow a built-in.
- **`unsigned` is not hostile** — your own exports are unsigned. Only `bad-signature` and
  `checksum-mismatch` say do-not-install, and the consent banner colours them so.

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

## The security boundaries, and the two that are enforcement not architecture

The PDP is the gate for *what a principal may do*. Three other boundaries decide *who a
principal is* and *what it can reach outside the PDP*, and they are the ones a change is
most likely to quietly break. Full audit and rationale in `docs/design/tenant-isolation.md`.

- **An app is an opaque-origin iframe, and that is the whole app sandbox.** Apps are
  served with `sandbox="allow-scripts allow-forms"` — deliberately WITHOUT
  `allow-same-origin`. That makes their `fetch` carry `Origin: null` (a header the browser
  sets and no script can forge) and stops them reading `window.parent`. `csrf_origin_guard`
  refuses any cross-origin mutation of a normal `/api/*` route, so an app cannot POST
  `/api/grants` or `/api/config`; it reaches the OS ONLY through the token-bearing runtime
  (`/api/tool`, `/api/apps/*/data`, `/api/apps/context`, `/api/apps/llm/*`), which the PDP
  then gates. **Putting `allow-same-origin` back on an app iframe silently removes the whole
  boundary** — `tests/test_app_origin.py` fails if you do. Do not "simplify" the guard to a
  token plumbed through the desktop's fetches: the point is that no desktop call has to
  remember anything, because the browser stamps Origin for free.

- **A WebSocket has no HTTP middleware, so it resolves the user by hand.** `resolve_user`
  never runs for a socket; `_ws_user` reads the account from the signed cookie and every
  turn/build enters `users.as_user(uid)` before the first `state["store"]` read. A turn that
  read the store first and set the user second would act as the machine, not the person.

- **A WebSocket has no HTTP middleware, so it checks its ORIGIN by hand too.** The same
  reason `csrf_origin_guard` cannot see it. A browser attaches the site's cookies to a
  cross-origin WS handshake and the same-origin policy does not stop a foreign page opening
  one — so without a check, a page on the open web could open `ws://localhost/ws/terminal`
  and, because `_ws_authed` trusts loopback on a default single-user box, be handed a shell.
  That is Cross-Site WebSocket Hijacking, and on this OS it is RCE. Every socket now passes
  ONE gate, `_ws_reject`, which refuses a cross-origin (or `null`) Origin *before* auth;
  an absent Origin is a non-browser client with no cookie jar and is allowed, mirroring
  `_same_origin`. Having one gate is the point — a new socket must not be able to forget
  the check, and one of these sockets is a shell. `tests/test_ws_origin.py` pins it.

- **Accounts are a data boundary through the tools, enforced, not an OS boundary.** On a
  machine with accounts, the file tools refuse another account's home (via `_tenant_deny`,
  independent of the sandbox toggle) and `run_command`/the Terminal run in a per-account
  `bwrap` jail with sibling homes tmpfs-blanked — failing CLOSED if no jail exists, because
  a shell that can read another home is the whole isolation gone. What this does NOT defend
  is a `bwrap` escape or an account with root/physical disk access; that is the deployment
  choice (per-user uid / containers) in the design doc, and the docs say so rather than
  overclaiming.

- **The ledger is tamper-evident and can be fail-closed.** Every `audit` row carries the
  acting `uid`, a `seq` and a `row_hash` chaining it to the previous row; `audit_verify()`
  finds the first edit or deletion. `security.audit_fail_closed` refuses an ALLOW whose
  ledger write failed. Nothing user-reachable may delete audit rows — a space-delete keeps
  them, and factory-reset is loopback + admin only.

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

## Window chrome: the rules that keep a stack readable

- **A window opens where you left it.** Geometry is remembered per app and clamped into
  the current screen. A maximised or snapped window never overwrites it — otherwise
  maximising once loses the shape somebody chose.
- **The cascade step must exceed the title bar height**, or a cascaded window buries the
  name of the one underneath, which is the only thing a cascade is for. The wrap point is
  a property of the screen; deriving it from the window being placed gives every app a
  different one.
- **Focus has to be visible at a glance.** `--el-5` against `--el-4` is not. Inactive
  windows sit at `--el-2`; the active one takes the full shadow plus an accent ring, as a
  second `box-shadow` layer so it costs no layout and does not clip at the radius.
- **A panel must not repeat its own window title.** `panelShell` reads the title bar above
  it and drops the label when they match — and keeps it where there is no title bar.

## The footprint is a feature: this may be a Raspberry Pi

Measured, on a warm install with no browser attached: ~70 MB idle RSS, ~0.6% of
one core, ~0.13s of CPU and ~1.6 kB of database per turn, settling at ~120 MB
after 1,300 turns and staying there. There is no unbounded leak; what there WAS
is three standing costs paid by machines that were not using the feature.

- **Nothing large is fetched, parsed or held for a feature nobody opened.** The
  MCP catalogue is 21,811 servers: 11.9 MB of JSON, +35 MB of RSS parsed. It used
  to be synced at boot and held forever; it is now synced on first use and
  released after 15 idle minutes (`mcp_store.release_if_idle`). `ensure_index(
  only_refresh=True)` decides staleness from the FILE's mtime, because parsing it
  to find out is the cost being avoided.
- **A file that accumulates must not be rewritten per item.** The index was saved
  after every page, with the whole list — 219 pages of a file growing to 11.9 MB
  is ~1.3 GB written per sync, daily, to storage that wears out. Publish in
  memory every page; write every few seconds.
- **A probe is a process.** `executors.probe()` caches for five minutes and
  `forget_probes()` is called on the way out of any install. Uncached it cost
  1.2s per `/api/executors` call, and the chat header, Settings and the wizard
  all ask.
- **Light mode is a PROFILE, and a profile writes settings rather than hiding
  them.** `profile.apply()` puts the retention numbers into config where
  `bento config` can argue with them; the one thing it owns live is whether the
  MCP catalogue survives a search (`mcp_store.housekeeping`). `auto` resolves
  from RAM on first run and then records what it chose — a machine that behaves
  differently after a RAM upgrade, with nothing on screen saying why, is the
  thing this shape exists to avoid.
- **Everything that grows needs a ceiling.** `memory.Store.prune()` drops logs
  and flow events past 30 days and usage past a year, then checkpoints the WAL so
  the disk comes back. It must never touch `audit` (hash-chained — deleting rows
  is what `audit_verify()` exists to detect) or the user's own work. The same
  rule applies in the page: `TOOL_ARGS` is capped, because a tool call whose turn
  died never gets its `tool_end`.

Measure before and after, and put the numbers in the commit message. Every claim
in this section came from `/proc/<pid>/status` on a running server, not from
reading the code.

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

## "Up to date" is a claim about the CODE, not about a file

`updates.check()` has two sources and needs both. `agentos/VERSION` is written by
hand at a release, so between releases it does not move — a machine could be
twenty commits behind the branch it tracks and be told, truthfully about the file
and uselessly about the code, that there was nothing new. That is exactly what was
reported. `updates.git_state()` asks git: which branch this copy is on, which one
updates track, how far behind, and which commits.

Four things that have to stay true:

- **Either source may say yes.** The version file is all a pip/wheel install has;
  git is the only thing that knows about commits between releases. `behind > 0` is
  an update even when the version is identical.
- **Both halves report even when one fails.** An unreachable version file and an
  unfetchable remote are different sentences, and either alone still leaves a
  usable answer — bailing on the first one is how a network blip became "up to
  date".
- **The count and the list must agree.** `commits()` drops merges, so a checkout
  two merge commits behind said "2 changes waiting" above an empty list; it now
  falls back to showing the merges. A number with nothing under it reads as the
  updater being broken.
- **Announce-once is keyed on the MARK, not the version** (`version@newest-hash`),
  and so is Skip. Keyed on the version, a version announced or skipped once
  silenced every commit that ever landed under it — a decline that quietly became
  "never update this machine again".

Say what it is up to date WITH. A checkout sitting on another branch is the
commonest reason a push looks like it did nothing, and every surface now names it.

**The verify gate refuses REGRESSIONS, not a fragile machine.** `apply()` runs the
suite on the new code, and if anything fails, runs those same tests on the OLD
code before deciding. A test already red on this machine — pytest's temp dir
under `/private/var` on a Mac, a cloud-provider test with no network — is an
environment fact, not the update's fault, and must not strand the machine on old
code. Only a test the update turns from green to red rolls it back. Two traps
this hides: each pytest run needs its own `PYTHONPYCACHEPREFIX` (two checkouts in
the same second let Python reuse the new code's `.pyc` while running the old, so
the old run "fails" a test it passes), and a test whose FILE is new to the update
never passed before it, so it is not a regression. `tests/test_update_gate.py`
pins all of it. The blunt `-x` gate this replaced bricked updates on a Mac —
`test_safe_folders` cannot pass when the temp dir resolves under a system
directory, so the machine could never self-update.

## The first five minutes: a short front page and one question

The install and `--help` are the same surface as everything else here, and both were
failing the same way — by telling the truth at a volume nobody can read.

- **`bento --help` lists ten verbs, not thirty-nine.** The mechanism is `verb()` in
  `__main__.py`: argparse has no hidden subcommand, but a parser registered WITHOUT
  `help=` is left out of the listing while staying in `sub.choices`. So nothing is
  removed — `bento help --all` prints the whole catalogue from `VERBS`, which is why
  the text is recorded there rather than only handed to argparse. `metavar` matters
  as much as the list: without it the usage line is a forty-word wall that scrolls
  the help off an 80-column SSH window. `tests/test_cli_help.py` pins all three.

- **install.sh ASKS how the machine will be reached, and `--yes` cannot answer.**
  Loopback-only is still the default and still right — but the desktop is a browser
  page, so on a Pi over SSH that default means "an install nobody can open", and the
  only thing that ever said so was one line at the end of a long log. `ask_deliberate`
  exists to be the one prompt `--yes` does not reach: yes to every optional install
  is consent to install THINGS, and opening this port hands a real shell to whatever
  can reach the machine. There is deliberately no `--remote` flag; the only way in is
  `--passphrase`, where the person choosing the secret is the person deciding.

- **`[ -t 0 ]` is the wrong interactivity test for a script installed by a pipe.**
  The documented install is `curl … | sh`, so stdin is never a terminal and every
  question in that script was answered "no" without being asked. The terminal is
  /dev/tty, and `INTERACTIVE` tests for it — while still resolving to "nobody" when
  there is no controlling terminal, because a systemd unit or a container build must
  never block on a prompt.

- **A machine that has not been set up says so where it is looked at.** `serve()`
  prints the arc's terminal entry point on every start until `setup_complete`, next
  to the URL rather than after it. The browser wizard already opens itself
  (`14-docs-setup.js`); the headless half had nothing, and "it is set up when you
  open it" is not true on a machine nobody is sitting in front of.

## The README is eleven files now

`docs/i18n/README.<lang>.md` — eleven hand-written translations of the front page,
each with a switcher to the other ten and back to English. Two things follow, and
the first one is a real cost to accept before editing:

- **Editing the English README puts eleven files out of date**, and nothing makes
  them follow — they are prose, not generated. `tests/test_i18n_readme.py` pins
  what can be pinned mechanically: the set is complete, every switcher resolves,
  and the heading COUNT matches, which catches a section added on one side only.
  It cannot catch a paragraph that changed meaning. If a change is small and you
  cannot make it in all eleven, prefer leaving the English narrower over leaving
  ten translations wrong — a sentence nobody on the team can proofread is worse
  than a sentence that says less.
- **They ship inside the product.** `docs/` is force-included into the wheel and
  `/api/docs` globs `**/*.md`, so the Docs app and TUI tab 8 list them too. They
  are titled by LANGUAGE there (`README — 日本語`) rather than by their own
  heading, and this machine's language sorts first among them — eleven entries all
  called "Bento Box AI — …" in scripts a reader cannot tell apart is how shipping
  translations makes the docs worse. `localeinfo.DOC_LANGUAGES` is that table and
  must stay equal to what is on disk.

The guides under `docs/` are **English only**, deliberately for now: nothing has
translated them, and a half-translated manual is worse than an honest English one.
`docs/README.md` says so where somebody would go looking.

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
