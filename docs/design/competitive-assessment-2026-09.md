# Competitive assessment — a multi-agent desktop harness (September 2026)

*What a recently trending open-source "team of coding agents" desktop app is, how far it
is from this OS, and what it teaches us. The project is deliberately not named here or in
any commit: this is a working note about our own roadmap, not a comparison for publication.*

---

## What was assessed

An MIT-licensed Electron desktop app (TypeScript, React, a 2D canvas, a terminal emulator,
a PTY library) at version 0.4.x, ~70k lines, one primary author with a growing contributor
base (13 community contributors in its last release), signed and notarized builds for three
platforms, an in-app auto-updater, a 60-post SEO blog, a Discord, a Product Hunt launch, a
GitHub-trending badge and a paid tier announced for its next minor version.

Its shape, in its own terms:

- **Every agent is a real terminal process.** It wraps twelve coding-agent CLIs (Claude
  Code, Codex, Gemini CLI and nine others) as pseudo-terminals. The CLI is the runtime; the
  app is a viewer, a controller and a coordinator. "Bring the subscription you already pay
  for" is the pitch.
- **Coordination is files in a git repo.** Each agent has a directory with `identity.md`,
  `memory.md`, an `inbox/` and an `outbox/`. A router in the main process moves messages
  between them and is the single git committer. A shared markdown blackboard and a JSON
  task ledger (a kanban with dependencies) sit beside them. Messages carry a speech act
  (request / inform / propose / query / agree / refuse / done) and a hop count.
- **An orchestrator agent you talk to.** One privileged agent reads every request, routes
  work to specialists, is the sole scribe of the blackboard, and escalates "critical" items
  (spend, destructive ops, scope changes) to the human. Its escalation policy lives in its
  system prompt: "tune the prompt, not the code."
- **Control rides the CLI's hook protocol.** Pause and per-tool gating return a deny from
  `PreToolUse`; steering injects `additionalContext`; halt returns `continue: false`; the
  autonomous loop is a `Stop` hook that blocks the exit while the inbox has mail. "Auto
  mode" is the CLI's own bypass-permissions flag, with the CLI's OS sandbox kept on where
  the CLI has one (Claude Code, Codex) and not otherwise.
- **A circuit breaker** watches each agent for repeated identical tool calls, error storms,
  token velocity and no-progress, and escalates steer → constrain → stop, de-escalating on
  healthy beats. Hard stop is off by default.
- **Memory** is markdown per agent, mined into a sidecar semantic index, condensed on a
  timer into pinned facts + rolling summary + recent tail behind a backup-first,
  verify-don't-trust gate. A separate file-backed "enterprise knowledge graph" ingests
  documents for keyword search.
- **Getting work in and out:** Slack (Events API over a public tunnel), secret-gated
  webhooks with per-caller status tokens, scheduled missions with weekday schedules, a
  GitHub CI watcher, shareable "hire" manifests behind a deep link (import only pre-fills
  a form; a human still spawns), a browsable catalogue of 227 third-party skills.
- **Surfaces:** one desktop window with a pixel-art floor where avatars walk to
  stations as their tool calls fire, a built-in code editor with git rails, a command
  centre (kanban, triggers, memory search, activity, tool waterfall), voice control through
  a cloud realtime model, a UI translated into two more languages with right-to-left.
- **Observability:** real token and cost figures read from the CLIs' own transcript files,
  a durable SQLite cost ledger, OTel-style spans, per-agent token caps.
- **Telemetry:** anonymous, allow-listed, documented event by event, three opt-outs.

## The thesis: a harness over other people's agents, versus an OS that is the agent

The two projects look alike from ten metres (local-first, multi-agent, a desktop, an
orchestrator, memory, missions, sharing) and are opposites at the load-bearing joint.

| | The harness | This OS |
|---|---|---|
| **What runs a turn** | Somebody else's CLI, in a PTY | Our own loop (`agent.py`), or an executor driven through the MCP bridge with every native tool off |
| **What decides whether a tool call may happen** | The CLI's own permission prompt, or its bypass flag; a hook can deny by name | `PDP.decide()` — one gate, one `audit` row per decision, hash-chained |
| **Where "may it?" is written** | The orchestrator's system prompt | `grants` rows, computed from the definition by `flows.declared_grants`, shown on the consent screen by the same code |
| **How agents talk** | JSON files in inboxes, delivered by a router, LLM-adjudicated | `delegate`/`finish` closures bound to one run; roster deny; depth cap is a permission |
| **Memory** | Per-agent markdown + sidecar vector index | Scoped SQLite: `space_id IN ('', :active)`, KG scoped on edges, extraction and supersede after every turn |
| **Users** | One | Directory-isolated accounts, signed cookie, `bwrap` jail per account |
| **Faces** | One Electron window (macOS-first) | GUI in any browser and on a phone, TUI over SSH, SUI as the Linux session |
| **Channels** | Slack in, webhook in, replies out to a thread | Telegram and WhatsApp owned end to end: same conversation, same memory, same approval buttons |
| **Untrusted content** | Not modelled | `UNTRUSTED_TOOLS` + taint ceiling for the rest of the turn |
| **Sharing** | Hire manifest = a form pre-fill | Signed packages, TOFU pins, leak scan with no override, forks that write zero grants |
| **Third-party code** | Skills catalogue (browse only), plugins are the CLI's problem | App iframe sandbox, plugin lifecycle review, hosted-plugin shim with a stated network gap |
| **Telemetry** | Anonymous, opt-out | None |
| **Proof the agent still behaves** | Typecheck + 110 unit test files | 1,755 tests + `evals.py` behavioural cases against a live model |

Three consequences follow, and they are the reason this OS should not become a harness:

1. **Their ledger is a message log; ours is a decision log.** The harness can tell you
   which agent messaged which; it cannot tell you which tool call was allowed by which
   rule, because the calls happen inside a process it does not own. The hook deny is a
   veto on a name, not a policy over an action on a resource. Everything in our security
   story (quarantine, taint, `audit_verify`, definition grants applying only inside their
   own run) is impossible in that architecture, and it is exactly what an operator will
   ask for the first time an agent does something expensive.
2. **Their autonomy is the CLI's bypass flag.** The "leash" is real (per-tool gates,
   pause, steer, a breaker) but it sits beside a process that was started with permissions
   off, and on nine of the twelve engines there is no OS sandbox under it. Our missions
   run through the gate or not at all, and the consent screen is computed by the code that
   writes the grants.
3. **Their coordination cost scales with the number of processes.** Twelve PTYs, twelve
   contexts, twelve subscriptions' hourly limits, a git commit per message. Our fabric runs
   specialists in one process with one budget accounted in working seconds. This is also
   why their footprint story is "your subscription", and ours is "a Raspberry Pi".

## What they do better, and what we should take from it

Ordered by how much of the machinery we already have. Each item names the face it touches.

### 1. A durable human-ask queue — we have the pieces and have not joined them

Their strongest product idea is small: a question from an agent becomes an item on a task
card, with a markdown ask, an answer trail, and a board that shows every open ask at once.
The agent moves on and picks the answer up when it arrives.

Ours: an unattended run that hits an ungranted action waits in memory for
`fabric.approval_timeout` (900 s) and is then denied. The roadmap's "persistent approval
queue" (J3) is still open. But the Brief already **is** this queue: `brief_item` with
`decide`, choices, a reply that runs as a turn, one page a day, buttons on Telegram,
`bento brief` with the server down.

- **Do:** when a flow's approval wait would expire, file a Brief `decide` item keyed on
  the run and the action, park the run (`fabric.Budget` already stops the clock), and
  resume it when the item is answered — from the desk, the phone, Telegram or the CLI.
  A restart must find the parked run and its item.
- **Faces:** GUI Brief app; phone stack; TUI `bento brief`; SUI identical. Nothing new
  to draw.

### 2. A steer rung before the hold

Their breaker escalates steer → constrain → stop and *de-escalates* on a healthy beat. Its
inputs are worth copying: repeated identical tool calls (we have this per turn, >3, in
`agent.py`), error storms, token velocity as a diff of cumulative samples, and
no-progress on both coordination and the agent's own workspace, with a two-beat debounce
and a compaction grace so a context compaction is never mistaken for a runaway.

Ours goes from "fine" to "held" in one step (`PDP` rate ceiling → quarantine). A hold is
the right end state, but a specialist that has used the same tool eight times often
needs one sentence, not a stop, and a held mission at 03:00 is a mission that did nothing.

- **Do:** add a `steer` action to the quarantine path for flow principals: on the first
  trip, inject a corrective message into the run (the orchestrator tools already close
  over the run id) and record the trip; on the second, hold as today. Add error-storm
  and no-progress inputs alongside the rate meter. Keep the release modes.
- **Faces:** the Permissions / quarantine list gains a "steered" state; TUI shows it in
  `bento flow doctor`; SUI identical.

### 3. Real cost from the executor's own records

They read each CLI's transcript files for real token and cost figures, reconcile them
into a durable ledger, and fold lifetime cost in the UI. We record cost per model call in
`usage` when the loop is ours, and `engine_info` comes back from an executor run — but a
forwarded chat turn's cost is only as good as what the CLI's `result` event says, and
nothing reconciles it later.

- **Do:** a reconciler that reads Claude Code's project transcripts for turns this OS
  started (keyed on the session id we already have) and corrects the `usage` row. Their
  note that the transcript directory key changed spelling and silently matched nothing
  for months is the trap to test for.
- **Faces:** Usage app; `bento usage`; SUI identical.

### 4. Per-specialist git worktrees for coding missions

They isolate each parallel worker in its own git worktree so agents never collide on a
branch. We have no notion of it. For a mission whose specialists edit code (increasingly
the case with an executor brain), two specialists in one checkout is a race.

- **Do:** an `isolate: worktree` option on a flow's roster entry; the run creates the
  worktree in the space's workspace, the specialist's file tools are rooted there, and
  `finish` reports the branch. The tenant deny already knows how to root a tool.
- **Faces:** Workflows editor (a checkbox); `bento flow add --isolate`; SUI identical.

### 5. Twelve engines against our three

Their roster is Claude Code, Codex, Gemini CLI, Cursor, Copilot CLI and seven more, each
with its documented auto flag and its sandbox stance recorded in one table. Ours is
`ENGINES = ("aria", "claude-code", "hermes", "openclaw")`, and the run bridge drives only
Claude Code. The people they are winning are people who already pay for one of those
subscriptions and want it to do more.

- **Do:** extend `executors.py` with Codex and Gemini CLI first — both support MCP and a
  native-tools-off configuration, so the bridge shape (`--tools ""`, one MCP server, the
  Agent's own tool list) generalises. Keep the honesty rules: an entry only where the
  install command and the licence can be stated, and `resolve_engine` must keep probing.
- **Faces:** the brain picker, `bento doctor`, the wizard's brain step — all read the
  roster, so this is a catalogue change.

### 6. The UI in more than one language

Their interface ships in three languages with right-to-left layout and fonts bundled so a
blocked network never leaves a blank window. We translated the README eleven times and
the desktop is English only. `localeinfo` already knows the machine's language.

- **Do:** a string table in the UI build (`agentos/ui/src`) for the wizard, the menu bar,
  the dock and Chat first, selected by `localeinfo` and overridable in Settings. Pin the
  same rule the README test pins: every key present in every language, or the build
  fails. The TUI reads the same table.
- **Faces:** all three; the TUI is the one most likely to be forgotten.

### 7. Distribution and community — the largest gap, and it is not code

This is where the other project is ahead by a distance, and none of it is architecture:

- Signed and notarized macOS builds, Windows and Linux builds on every release, and an
  updater that downloads and restarts into the new version. We build a `.pkg`, a `.deb`,
  an NSIS installer and a `.run`, and `updates.py` has a verify gate they do not have —
  but the README leads with `curl | sh`, which is the right door for a server and the
  wrong one for someone on a Mac who has never opened a terminal.
- Sixty blog posts, each a search query someone types ("why does Claude Code keep asking
  for permission", "how to run multiple agents"), plus `llms.txt` so answer engines cite
  them. We have thirty pages of manual and no page a stranger lands on.
- A Discord, a contributor list generated from merged PRs, a Discord role granted by CI on
  merge, a "good first issue" shelf kept stocked, and a **before/after evidence check**
  that fails a PR without screenshots under `### Before` and `### After`. Our CLAUDE.md
  says "measure before and after and put the numbers in the commit message"; theirs makes
  the reviewer's eye do it and refuses the PR otherwise.
- A gallery of shareable roles with a validator and a deep link. We have the stronger
  mechanism (signed bundles, TOFU, leak scan) and no gallery page to browse.

- **Do, in this order:** a landing page that is the README's first screen; a community
  channel named in the README; the PR evidence check ported to `ci.yml` (it is one
  workflow file and it pays for itself on the first UI regression); a static gallery page
  generated from the `bento-app` and `bento-agent` GitHub topics that `appregistry` and
  `agentbundle` already search; then a blog built from `docs/` rather than beside it.

### Smaller things worth a line each

- **A model catalogue fetched at runtime** from a file on the default branch, cached six
  hours, compiled-in copy as the floor. Ours probes providers; for executors we hardcode
  aliases. Cheap to adopt for executor model lists.
- **Closing time.** Before quitting, the orchestrator broadcasts shutdown, every worker
  parks work and appends state to memory, and the app waits for the acknowledgements.
  Our flows keep state in the database so the need is smaller, but `bento service stop`
  during a run still loses the partial artefact. A `finish(partial=True)` on stop is
  enough.
- **A memory condensation gate**: backup first, then a verify pass that refuses the
  rewrite if the summary lost pinned facts, then an atomic swap. Our session rollup and
  supersede do the work; check that `memory.Store.prune()` and rollup have a size ceiling
  on the injected memory, and that a bad rollup cannot delete a pinned row.
- **The task ledger merge rule**: a UI writer holding a partial model of a card must not
  delete the fields it does not know. We have the same shape in `flows.save` and the
  Brief upsert; worth a test that a re-save from an older editor keeps unknown keys.
- **Voice as a control plane.** Theirs needs a cloud realtime key; the roadmap's provider
  layer (local Whisper + local TTS first) is the local-first version and should stay so.

## What not to chase

- **The animated floor.** It is their demo and their brand, and their own spec admits the
  risk: "if walking to the shelf doesn't convey 'is reading a file' faster than a text
  label, we built a toy." Our `01c-movement.js` dial answers the same question — is it
  working, on what, for how long — at 20 fps with no per-agent sprite. Do not build a
  second scene.
- **A built-in code editor.** It is a fine feature in a coding harness. Ours is a desktop
  with a Terminal, Files and App Studio, and the roadmap's "Studio → IDE" (versions, diff,
  rollback, export) is the right scope: version what the agent built, do not become an
  editor.
- **Twelve PTYs.** The executor model already answers "use the agent I already have";
  the bridge keeps the gate. A PTY-per-agent design would put our tools outside the PDP,
  which is the one thing this OS must not do.
- **Telemetry.** Theirs is done well (allow-listed, documented, three opt-outs) and it
  buys them an activation funnel. "No telemetry" is a sentence in our README that people
  install for. The roadmap's privacy ledger ("what left this machine today?") is the
  local-first answer to the same question and is still open.
- **Slack.** The channel rule stands: a channel is offered only if it brings a
  conversation to this agent, through this policy, with every call in this ledger.
  Theirs is inbound over a public tunnel with replies to a thread, which is exactly the
  carrier shape we removed.

## Where we are ahead, so it is written down

The gate and the ledger; users isolated by directory; three faces plus a phone; channels
owned end to end; scoped memory and a scoped graph; the app iframe sandbox; a federated,
signed registry with TOFU pins; agent sharing with a leak scan that has no override;
missions whose consent screen and grants are one computation; a hosted-plugin shim that
says `CANNOT CONTAIN` where it cannot; behavioural evals; and a working-notes file that
records why. None of that shows on a landing page, and item 7 above is how it starts to.

---

## What has been built since, and what has not

Four of the items above are in. Each is listed with what it does NOT do, because a
half-built thing described as finished is the failure this document was written about.

- **The steer rung (item 2).** `PDP._steer_first` in `agentos/policy.py`. The first time
  a flow or a subagent crosses a rate ceiling the offending call is refused and the
  refusal text tells it what to do instead — which reaches the model as the tool's own
  result, so there is no second channel and nothing to look up. The meter is cleared with
  the steer, so it is a real second chance; a second trip inside ten minutes holds it as
  before. An app is still held outright: a browser tab running somebody's JavaScript does
  not read a correction. A steer writes no quarantine row (that list is what is
  *stopped*), carries `rule="steered"` in the ledger, and releasing a hold resets the
  ladder. Ten tests in `tests/test_quarantine.py`. *Not done:* the middle "constrain"
  rung, which would need a notion of a read-only principal this OS does not have.
- **An unanswered approval reaches a person (part of item 1).** `_unanswered_to_brief` in
  `agentos/server.py`, wired through both the desktop broker and the Telegram bridge. A
  question nobody answered is now distinguished from a person pressing Deny, and files a
  Brief `decide` item keyed on the mission and the action, so a nightly mission asking the
  same thing every night is one standing question rather than thirty. *Not done, and the
  item says so in as many words:* the run is **not** parked and **not** resumed. Nothing
  about an in-flight run survives the process — `fabric_runs` has no paused state, the
  `Budget` and the agent's history are in RAM, and there is no startup sweep of orphaned
  rows — so the durable queue in the roadmap's J3 is still open, and an item claiming a
  run was waiting would be a promise this OS cannot keep. Four tests in `tests/test_brief.py`.
- **The evidence check (part of item 7).** `.github/workflows/pr-evidence.yml` plus the
  two new template sections. It reads only the PR body, through the environment rather
  than interpolated into a shell, and checks out no code from the pull request. It catches
  the section left holding the template's own comment, which is the likeliest way past it.
  Deliberately **not** a required check: making it blocking is a branch-protection setting
  and the repository owner's decision, not something a workflow should take by arriving.
- **A third scene, Crew** (`agentos/ui/src/js/01d-crew.js`), which is not on the list
  above and is the one thing here taken from the other project's *look* rather than its
  engineering. It is their office floor with the parts removed that this project's own
  rules forbid: the cast is `/api/subagents` and nothing else, so an empty roster draws
  the agent alone and says so; the figures are drawn rather than loaded from a tileset, so
  there is no asset licence to carve out and nothing added to the wheel; and it rides the
  Movement scene's loop, so it inherits the whole cost argument (measured on this machine:
  17.3 fps against a ceiling of 20, 0.4 ms a frame, zero frames under a maximised window
  or a hidden tab, one still frame under reduced motion). Thirteen tests in
  `tests/test_immersive.py`.

  The first cut of it is worth recording, because it is the lesson the whole scene turns
  on. Reusing the dial's single brass for everything produced outlined wire bodies,
  identical in colour, frozen between events, each with one red dot where a face would be
  — and the report on it was one word: *scary*. Nothing about it was wrong as
  instrumentation; every mark still meant something real. It was simply a drawing of
  principals rather than of people, and a desktop full of those is one somebody switches
  off. The fix was four things, each now pinned by a test: a FILLED body (an outline is a
  ghost), a colour per specialist that no two on stage share (a bare hash collides like
  birthdays — two of four came out the same green), a face with TWO eyes (a single centred
  mark is a cyclops, so the running indicator moved above the head), and idle life, since
  a row of motionless figures staring out of a dark room is a waxwork. The cost of all
  four together was 0.2 ms a frame.

  A third pass turned them into CARTOONS, which is a different fix again and worth
  separating from the second. The flat-vector version that came out of the "scary" work
  was friendly and read as an infographic — correct, and nobody's colleague. What a
  drawing needs to read as *drawn* is an outline on every shape, and with one holding the
  form the fill can be flat and bright, which is exactly why cartoons look like that. The
  useful lesson was the part that had to be taken back OUT: the first cartoon attempt also
  added a light sclera, a dark rim and an eyebrow to each eye, which is correct anatomy at
  poster size and a compound eye at forty pixels — a row of them read as insects. At this
  scale the face wants FEWER marks, not more. It ended on one solid eye and a catchlight,
  plus mitts, shoes and a squash at the bottom of each bounce, at 0.5 ms a frame.

Still open from the list, untouched: cost reconciliation from executor transcripts (3),
per-specialist git worktrees (4), more executors through the run bridge (5), the UI string
table (6), and everything in item 7 that is not the evidence check — the landing page, the
community channel, the gallery, the blog.
