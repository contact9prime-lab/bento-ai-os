# Changelog

## Unreleased

**Your agent is now something you can share — and fork.** `bento agent share`
(GUI: Settings → Agent) packages the agent you shaped — skills, teammates, flows,
the apps you tick, MCP server shapes — into one `bento.agent.json` anybody can
fork; publish it in a repo under the GitHub topic `bento-agent` and it resolves
as `owner/repo[@ref]` across two CDNs, like apps. The vital rule is structural:
the bundle is built by whitelist (memory, conversations and the knowledge graph
are never even read), MCP credentials become `<YOUR_KEY>` placeholders, webhook
secrets are stripped — and then a leak scan runs over the finished bytes anyway,
and anything key-shaped REFUSES the export with no override flag, because a
shared credential cannot be unshared. The soul is opt-in and its full text is
shown before you publish; shipping each app is a per-app checkbox. A fork is the
flows rule applied to a whole agent: everything lands disabled, ZERO permission
rows are written (`grants_written_now: 0` on the consent screen is the design),
nothing of yours is overwritten, and the bundle's permission list is disclosure
— the ceiling enabling everything would reach — computed by the same
`flows.declared_grants` the editor uses. Integrity and identity ride the app
registry's rails: SHA-256 checksum, optional Ed25519 signature from the same
`bento registry keygen` key, and first-fork TOFU pins where `changed-key` is
the loudest alarm. (`agentos/agentbundle.py`, `docs/agent-sharing.md`.)

**And sharing has a second intention: hosted, not published.** A published file
is a copy the taker owns forever; `bento agent host --on` is the other
arrangement — "it stays with me, take it". The machine serves its share through
an authenticated MCP door (`POST /api/agent/mcp`, two tools: `agent_card`,
`fetch_agent`), so a peer — another Bento with `bento agent fork http://host
--key …`, or any agent that speaks MCP — always takes the CURRENT agent, built
fresh with the leak scan running on every single take. Minting a key (`bento
agent peers --add`, shown once) writes a real `peer:<name> may agent.share`
grant; every take is a PDP decision in the ledger, and the arrangement ends two
ways that both work: revoke the key, or revoke the grant in Permissions. A peer
principal is denied everything else by default at the policy layer. Three
refusals carry three sentences — unknown key, revoked, and expired ("rotate it
— this is not a leak") — and a guess flood is held in memory before any work
happens, the webhook's rule.

**A fork now ends on an arrival, and the wizard offers forking on day one.**
Every import closes with the same two answers on every surface — WHAT CHANGED
(by name, with each kind's caveat: flows disabled, MCP off with placeholders)
and WHAT DID NOT (your memory, your keys, your brain, your identity, 0
permissions written, collisions kept) — plus a "Test it — start chatting"
door that prefills a first question in Chat without sending it. One
computation (`fork()["arrival"]`) feeds Settings, the CLI and the new
first-run step **Start from a shared agent** (browser wizard and `bento
setup`), where a fork can tick several later steps at once because what it
brings satisfies their probes. Fixed alongside: a forked app now appears in
App Studio and the launcher immediately — the fork route broadcast an event
the desktop never listened for, so the app existed in the store while every
pane showed stale until a full reload.

**OpenClaw plugins install through this OS's review.** OpenClaw has been an
executor here for a while; it could not be extended. Its plugins — tools,
providers, channels, hooks and MCP servers — now install through `bento openclaw`,
Settings → Executors, or the agent, all reading one module (`agentos/ocplugins.py`)
so there is one scan, one consent screen and one set of permissions however you
arrive. An install lands DISABLED and holds nothing; enabling is the act of
granting, and it is confirmed every time, at full autonomy included. The agent may
install and may not enable, exactly as with flows.

What that adds: a deterministic scan of the plugin's own `openclaw.plugin.json`,
which names the tiers whose point is to sit in front of something — host-trusted
pre-tool policies, tool-result middleware, in-process Gateway dispatch, a claimed
`memory` slot, conversation hooks; real `grants` rows, where revoking the
enablement makes AgentOS disable the plugin; trust on first use, so a plugin that
changes origin or grows capabilities is held rather than upgraded — measured
against the verdict you consented to, because `openclaw plugins update` run in a
terminal never passes this screen; and the ordinary quarantine list, with the
ordinary once/forever/deleted release.

What it does not add, said plainly: an enabled plugin runs inside OpenClaw's own
process, and nothing here can refuse an individual call it makes. AgentOS gates
the lifecycle and enforces enablement; that is the whole boundary.
`docs/openclaw-plugins.md` says the same thing to a user, and AgentOS still ships
no OpenClaw installer — a machine without the CLI gets one honest sentence rather
than a pane of dead buttons.

**A compatibility gap is now a fork, not a dead end.** Every install and enable
screen — CLI, desktop, agent — first states what will NOT work on this machine,
from one computation so the sentences never differ by surface, and then offers the
other road: have AgentOS rebuild what the plugin declares out of its own parts —
MCP servers, flows, skills — where every call is already behind the permission
engine. A disclaimer whose only way forward is Proceed is a formality people learn
to click through, so there are always two.

The plugin's manifest is the specification, and three rules keep the port honest.
The brief is DERIVED, never invented: everything traces to something the manifest
declares, and a manifest that declares nothing produces no brief and says so
rather than guessing what the plugin probably does. A port is a proposal —
everything it writes lands disabled, so porting cannot become a way to acquire
permissions without being asked. And the agent checks its own work against the
same brief it was built from (`bento openclaw verify`), item by item, reporting
reachability and saying plainly that reachability is not behaviour.

`ocnative.MAPPING` is the table of OpenClaw concept → Bento primitive, and its
most important rows are the ones with no target: trusted tool policies, tool-result
middleware, providers, channels, the memory slot and in-turn hooks are reported as
not portable rather than approximated onto the nearest thing that compiles.

**`bento openclaw report` is the document you sign off on, and it has ONE name.**
The same report is printed by the CLI, by `GET /api/openclaw/plugins/{id}/report`
and by the agent's `openclaw_report` — a second name for it would be how two
surfaces end up describing one thing differently. Four parts: what was ported and
is reachable, what is still to build, what cannot be carried at all *and what
losing each of those costs you*, and three ways forward. A list of names with no
consequence attached is a list people skim, so every unportable row says what it
means — "any budget rule it enforced is gone; write it as a grant in Permissions
instead, where it applies to everything and not just this plugin". It ends in a
proposal, never a verdict: build the rest, continue as it is, or keep the original
running. Continuing as it is is offered unconditionally, because a partial port
covering what somebody actually uses is a fine place to stop.

**Licensing asks twice, and the answers differ.** Installing a plugin is RUNNING
it, which is what a licence is for and needs nobody's permission — only a missing
or proprietary one stops you. Porting has the agent write new code doing the same
job, which for copyleft raises a derivative-work question, so that path demands an
acknowledgement (`--accept-licence`) the install path does not. Conflating them
would either nag on every install or stay silent on the one that matters. The
classifier is a table rather than a regex, because AGPL is not GPL is not LGPL;
`OR` takes the best branch and `AND` the worst; and no declared licence is never
softened into "probably fine" — with no grant the default is no rights. AgentOS
states the licence and what a port actually reads, and says out loud that it is
not legal advice.

### 0.3.0 — several people, more places to work, and one brain to choose (2026-08-17)

**Several people on one machine.** Accounts are isolated by DIRECTORY, not by a
WHERE clause: each has its own `~/.agentos/users/<id>/` with its own database,
config, workspace and assets. Two files cannot leak into each other, which is the
whole argument — one forgotten filter among ~250 query sites would be somebody
reading a colleague's memory. Sign-in is one signed cookie everywhere (desktop,
phone, API), the tools refuse another account's home, and `run_command` and the
Terminal run in a per-account jail that fails closed if it cannot be built. A
machine with no accounts keeps using exactly the files it always used.

**The agent can work in more places, and an admin decides which.** Safe folders
are shares: a path, who it is for, and whether it carries read or read/write. They
are allocated in the Users app, and adding a root as writable says what that
means before you agree to it. `bento folders` is the same thing over SSH.

**A stranger reaching a channel is recorded, and can be let in.** An unregistered
Telegram or WhatsApp sender is logged with who they were and what they wanted
rather than silently dropped, and an allow-list lets specific people talk to the
bot without making the channel public.

**The brain is one choice.** Which executor answers and which of ITS models it
runs on, in one control and one write — local providers, cloud providers, Claude
Code, Hermes, OpenClaw, each carrying the models it can actually wake up. The top
bar states the pair at all times. An executor that is not installed is listed with
its licence and, where AgentOS knows a truthful command, an offer to install it.
`bento brain` is the headless face; `bento doctor` reports the pair.

**The surfaces are stitched.** The prompt bar's thread is a real conversation from
the moment you press Enter — visible in Chat, openable, and honest about waiting
its turn. A turn that builds an app or writes a workflow offers the door to it in
App Studio or Workflows, and the button selects the thing rather than dropping you
in an empty app.

**Updates tell the truth.** "Up to date" used to be a claim about a version file
somebody edits at a release, so a machine could sit twenty commits behind the
branch it tracks and be told there was nothing new. The check now asks git as
well: how far behind, which commits, which branch this copy is actually on. The
ledger of what arrived comes from the commits themselves.

**Everything a principal does is in the ledger, and the ledger can be
fail-closed.** Audit rows are hash-chained with the acting account, `audit_verify()`
finds the first edit or deletion, and nothing user-reachable deletes them. Apps run
in opaque-origin iframes so an app's `fetch` cannot forge the desktop's origin, and
a rate ceiling now catches a patient loop as well as a tight one.

**Findable failures.** `bento log` prints the OS-level log for the Bento process
with its errors, and the desktop bundle is parse-checked in CI — one syntax error
used to take the whole desktop out while the server and the tests looked healthy.

### 0.2.0 — it tells you what it is doing, and it keeps up to date (2026-08-10)

**You can see what it is waiting on.** Every surface that showed a turn in
flight said the same three words for however long it took, so a model thinking
and a run that had died looked identical. One shared record now drives all of
them — the chat row, the copilot panels, the omnibar, the presence bubble, the
voice overlay — with the live step and its age. Open tool calls age in place
(`running · 2m 14s`) and keep their duration when they finish. Sending from a
copilot panel is acknowledged immediately instead of at the server's reply.

**Agents that build agents, with consent.** The chat can now define a specialist
(`create_subagent`) when none fits, and starting one asks once per agent — the
card names the model, the budget and the exact tools and skills it would hold.
Defining grants nothing; the first use is what asks. Nothing but your own agent
may define one, and an agent may never start or define another.

**Telegram is an admin console.** `/agents`, `/run`, `/flows`, `/flow`,
`/model`, `/tools`, `/logs`, `/perms` — owner only, published as Telegram's own
command menu, and every command that acts goes through the same permission gate
and approval buttons as the desktop.

**It answers questions about itself.** The manual is in the retrieval index and
the Docs app has an ask box; the reply cites the page it came from.

**Providers are asked what they can run.** Model lists were static config, so a
working OpenAI-compatible endpoint appeared to have none. They are fetched now,
`llama.cpp`'s bare host URL resolves, and models that cannot chat (embedders,
image, speech) are no longer offered as choices that fail on first use. Choosing
a model in Settings or the Model Manager takes effect immediately.

**Updates.** `agentos/VERSION` is the one place a version is written. AgentOS
checks for a newer one on its own and asks; installing pulls, verifies against
the test suite, rolls back on failure, restarts the service and reloads the page.

**A reload no longer costs you the desktop.** Which windows were open, where,
minimised or maximised, and any unsent message come back after a refresh — which
is what makes an update safe to accept while you are working.

### Scroll the tiles and the deck becomes the wall (2026-08-08)

The app deck was a strip you could only ever see all of by making the window
bigger. It is now the near edge of a stack of three surfaces, and one gesture
moves between them:

        All apps        ← push up
        the desktop
        Widgets         ← push down

A wheel, two fingers or a swipe **up** over the tiles — or over bare wallpaper —
opens **All apps**: every group on one grid of equal columns, bigger icons, the
machine's own applications no longer capped at fourteen but laid out in full
across the width, and **the caret already in a search box**. Typing filters the
whole wall in place — the omnibar's own ranking, so a name typed here and the
same name typed in the prompt bar cannot disagree — Enter opens the top hit, Esc
clears the query before it closes the wall, and a search that matches nothing
offers to ask the agent instead of showing an empty screen.

Pushing **down** instead opens **Widgets**: every widget you have, wherever it is
pinned and whichever desktop it is on, as live cards with the app's own widget
page inside. Tabs cross between the two faces without going back through the
desktop. `Ctrl+Shift+↑` / `Ctrl+Shift+↓`, and either as a hot corner, for people
who would rather not gesture.

Four details are the whole feel of it:

- **The strip scrolls itself first.** The gesture only fires once the deck is
  already at the end it is being pushed past, and only for a push that adds up —
  otherwise one stray trackpad notch would flip the desktop inside out.
- **Tiles arrive rather than appear**: a single capped left-to-right sweep, so a
  hundred and thirty apps still land in under half a second, and nothing at all
  moves under `prefers-reduced-motion`.
- **Filtering hides tiles in place rather than re-rendering**, because
  re-rendering takes the caret out of the box on every keystroke.
- **The wall is not chrome.** It is deliberately not persisted and deliberately
  not measured into `--deckh` — an overview you log back into is a screen in the
  way, and measuring it would push every toast and card off the bottom. The
  widgets face mounts its iframes on open and throws them away on close: a
  glance surface showing what it showed ten minutes ago is worse than one that
  takes a moment, and a hidden iframe left running is a timer nobody can see.

In the session UI the desktop is the BACKGROUND layer, so the wall raises the
surface for exactly as long as it is up; otherwise "all apps" would open behind
the very windows you are trying to get away from.

### WhatsApp by scanning a QR, with no Meta account at all (2026-08-08)

The Cloud API path works and stays, but its cost before the first "hello" is a Meta
developer app, business verification, a publicly reachable HTTPS webhook and a
24-hour window that silently refuses free-form messages. On a laptop behind NAT that
is a lot of ceremony.

**The linked-device transport** (`agentos/wa_baileys.py` + `agentos/wa_bridge/`) is the
other route: Baileys (MIT) speaks the WhatsApp Web multi-device protocol, so pairing is
a QR code scanned from the phone that already has WhatsApp on it. No Meta account, no
webhook, no tunnel — and no 24-hour window, because a linked device may message whenever
it likes. `window_open()` now asks the transport before answering, so that limit is not
invented where it does not apply.

**One agent path, two transports.** Inbound messages are reshaped into the exact dict
shape the Cloud API webhook produces and handed to the same `WhatsAppBridge._one`, so
owner pairing, the allow-list, `/clear`, flow triggers, approvals, taint and the ledger
are the code that already ran and was already tested. The Node process decides nothing —
a bridge that started making decisions would be a second agent, which is the thing that
was just removed.

**Offered, never shipped.** Node plus ~60 MB for one channel does not belong on every
machine, so it is a `components.py` entry with the licence and the honest warning in
view: this is **unofficial**, it emulates a linked WhatsApp Web session, WhatsApp does
not support it, and accounts have been banned for automating on it. Nothing downloads
until somebody reads that and says yes. `unavailable_reason()` gained a per-component
hook so a machine without Node is told "needs Node.js" rather than "no debian-family
package name is known for this component".

Three faces: the QR renders as SVG in the WhatsApp card and as block art in
`bento channels whatsapp --pair`, both encoded once in the Node process rather than
twice in two languages. The card follows the bridge's events because the code rotates
every ~20 seconds and a stale QR is one that silently will not scan.

**A bug worth recording**, found by writing the doc before believing the code: the first
version mapped numbered replies to button ids like `"deny"`, but `_answer` parses
`ap:<aid>:<value>`. Every approval on this transport would have hung until it timed out.
Digits now resolve against the approval that is actually pending — and a digit with
nothing pending stays an ordinary message, so texting "2" to your own agent reaches it.

### Hermes is removed, and the gateway hub with it (2026-08-08)

The Hermes integration is gone: the chat engine, the `hermes_*` tools, the companion
app, the `/api/hermes/*` endpoints, the twelve carried channels, and `agentos/hermes.py`
itself. The planned **gateway hub** (`openclaw.py` behind a shared `Gateway` interface)
and **carriers become channels** roadmap items are dropped with it. `openclaw.py` was
never written, which made that half free.

**The reason is not that it failed.** It worked, and it gave AgentOS twelve messaging
platforms for the cost of shelling out to a CLI. The problem was that we could not judge
what we had:

- a carried channel could only deliver **out** — a reply arriving there was answered by
  a different agent, with a different memory, and the user had to be told so on every card
- nothing Hermes did reached this OS's grants, ledger or budgets, so `hermes_ask` was a
  hole in the one rule the audit design rests on
- as a chat engine it was worse than it looked: `hermes -z` is one-shot, so **turn 2 never
  knew about turn 1**, `tokens` were hardcoded to `0` and `steps` to `[]`

Abstracting a dependency we could not measure behind a `Gateway` interface would have made
it permanent rather than understood. Removing it costs real capability — Slack, Signal,
Discord and the rest are not available from AgentOS today, and that is the honest price.

**What replaces it is a bar, not a plan.** A channel is offered only if AgentOS owns it
end to end: it brings a conversation to *this* agent, through this policy, with every call
in this ledger. Telegram and the native WhatsApp meet it. `tests/test_channels.py` enforces
that on every channel, and separately asserts the carrier surface is really gone rather
than half-removed — the failure mode of a removal this wide is one module attribute left
behind for a surface to call.

Upgrades are handled rather than assumed: a config pinned to `engine: "hermes"` is repaired
to `aria` on load (a machine pinned to a removed engine must still answer with something),
and the dead `hermes` config block is pruned, because a setting for something that no longer
exists reads as a feature merely switched off. Your own Hermes install is untouched —
this removes AgentOS's integration, not the program.

### Quarantine is a place you can get to (2026-08-08)

It shipped as a tab inside the policy console, which is the wrong home. Permissions is
where you go to *think about rules*; quarantine is where you go when something has
already stopped working and you want to know why. Nobody whose app just went quiet
thinks "I should check the policy console".

- **Quarantine is now an app** — its own icon in the launcher, the deck and the bento
  layout. Same renderer as the tab, which stays as a deep link: a second copy of the
  list would drift, and the drift would be in the screen that explains why the OS
  stopped something.
- **`bento quarantine list | history | release <id> --mode …`** — until now the hold
  existed on a headless box and the way out did not, so an app stopped over SSH could
  be seen in the logs and never released. A hold you cannot lift is worse than no hold.
- **A test over the app registry**, because adding an app means agreeing four lists
  across three files and nothing checked they matched. An id with no entry, or an entry
  whose render function was never written, is an icon that opens nothing — the dead
  control the honesty rules exist to prevent, in the place a user is most likely to
  click. It found nothing broken today; it exists so the next one is caught.

Existing installs pick the app up automatically: `deckReconcile()` gives every new
built-in a home, so it appears under **More** on a deck that was already customised.

### The popular servers were never findable, and could not have connected anyway (2026-08-08)

"Canva and Higgsfield aren't in the MCP" turned out to be two separate faults stacked on
each other, and fixing either alone would have produced something that looked fixed.

- **Discover could not find them.** It searches the public MCP registry, which is a
  *publishing* registry: a vendor is in it only if that vendor published there. Measured
  against the live API, `higgsfield` returns zero results and `canva` returns third-party
  imitations plus Canvas-LMS courseware — the official servers are announced on the
  vendors' own domains and are simply not in the index. No better query finds them.
- **And a URL alone would not have worked.** Every first-party remote server answers an
  unauthenticated `initialize` with `401` + `WWW-Authenticate`, and the HTTP transport only
  ever sent static headers. Adding one by URL produced a server permanently in `error` —
  the dead control the honesty rules forbid. This is why the catalogue and OAuth shipped
  together rather than one at a time.

**Native OAuth 2.1** (`agentos/mcp_oauth.py`) — AgentOS now discovers the authorisation
server from the 401, registers itself by DCR, does code+PKCE and refreshes the token. No
Node, no `mcp-remote` subprocess, no bridge. Tokens sit in `~/.agentos/oauth/<name>.json`
at `0600` (opened with that mode, not chmod'd after — the gap is the exposure), and Sign
out deletes the client registration too, because keeping it would silently reuse an
authorisation the user just ended.

**A curated catalogue** (`agentos/mcp_catalog.py`) — Higgsfield, Canva, Replicate, fal,
Figma, Notion and Linear, merged *ahead of* registry results so the official server outranks
imitations of it. Two entry rules: probed live before inclusion, and DCR required, since
that is what makes it one click. `mcp.stripe.com` is real, works, and is deliberately
excluded because it has no DCR — it stays an API-key preset. `packaging/dev/probe-catalog.sh`
re-probes all seven; the unit tests stay offline, because a suite that failed during a Canva
outage would be reporting on Canva, not on this code.

Three faces: the MCP app grows a curated section plus Sign in / Sign out per server; the
callback is a page a human reads; and `bento mcp catalog|add|list|connect|disconnect` covers
the headless case, where it **prints** the URL instead of assuming a browser exists — a
consent page must not open in a room the user is not in. That is also why the redirect base
is configurable rather than a hardcoded `localhost`, and why the server only auto-opens a
tab when no UI is connected to do it better.

### Quarantine: the OS stops what will not stop itself (2026-08-07)

A stock-ticker app was firing bursts of `fetch_url` on every refresh, and nothing in the OS
had an opinion about it. Grants answer *may it?* and budgets answer *how long?* — neither
answers *how often?*. A subagent is bounded by `max_steps` and a flow by its delegation
budget, but an app runs in a browser tab and can loop for as long as the tab is open.

- **A rate ceiling, checked before grants** — beside the channel and taint ceilings, for the
  same reason: a grant of `fetch_url` is consent to fetch pages, not consent to fetch six
  hundred a minute. Apps, subagents and flows are all metered; the user never is.
- **Model calls and tool calls have separate budgets.** Six model calls a minute is money
  leaving at a rate nobody asked for; six fetches is a page refreshing. The numbers are
  calibrated against what this machine actually does — its busiest legitimate app burst was
  25 fetches in 10s — so a real dashboard passes and a runaway misses by an order of
  magnitude. There is a test that asserts exactly that, because the worst version of this
  feature is one that breaks working apps.
- **Quarantine is a state you can see.** Permissions → Quarantine lists what is held, why,
  and the evidence: *"7 model calls in 60s, over its limit of 6 — it was calling
  llm_generate in a loop"*. It arrives as a notification too — something that just stops
  working is a bug report; something that says why is a decision you can disagree with.
- **Three ways out, all recorded**: let it run once (still watched), allow forever (an
  exemption, so the row is kept rather than cleared), or delete it. The choice and who made
  it go in the log.
- **A privilege escalation, found by testing this.** Silencing a rogue app by revoking its
  runtime token doesn't silence it — `_principal_of` maps an unknown token to the user, so
  the app's next call ran *as you*, with your permissions. A server restart alone was enough
  to reach it. A presented-but-unknown app token is now refused outright, and quarantine
  leaves identity alone: suspension is what stops an app, not amnesia about who it is.

### The Team app is now Workflows, and half its tabs are gone (2026-08-07)

Five tabs had accumulated, two of them answering the same question from different endpoints.

- **Three tabs: Flows · Agents · Runs.** "Executions" and "Observability" were both "what
  happened" — they are one **Runs** view now, with the per-agent totals as a fold-out strip
  instead of a tab of their own.
- **Flows is master/detail.** A one-line row per flow on the left, the selected one in full on
  the right — chart, mission, what starts it, what it grants, Run. Adding a tenth flow now
  costs a row instead of another screenful, and the live graph/board/log that used to sit
  below the cards is gone: the Run Inspector already owns that, and having it twice meant two
  places showing the same state.
- **The static-DAG workflow tab is gone**, and its two built-ins are no longer seeded. The
  engine, `/api/workflows` and the `run_workflow` tool all still work for anything already
  using them. The reason is in the numbers: on this machine, across every run ever recorded —
  9 delegations, 3 flows, **0 workflows**. Every new install was being furnished with two
  examples nobody ran. 69 lines of unreachable UI deleted rather than hidden.
- **Named for the word people arrive with.** The app is *Workflows*; the code underneath still
  says `flows` everywhere (`flows` table, `/api/flows`, `flow.write`). That divergence is
  deliberate and written down in CLAUDE.md — it is safe precisely because the older thing
  actually called a workflow no longer appears in the UI, so the two meanings never share a
  screen.

### Flows: the master agent is the control plane (2026-08-06)

The fabric could already run a team. What it could not do was decide anything: a workflow was
a DAG somebody drew before it ran. A **flow** is a standing mission — what you want, who may
work on it, what it may touch, and what starts it — and a master orchestrator picks the agents
and the order while it runs. Full design: [docs/design/flows.md](docs/design/flows.md).

- **The graph is a trace, not a plan.** Team → Flows draws the master, then each agent as it is
  delegated to, with solid edges for delegations and dashed edges for the data handed forward.
  Beside it: the board (every artefact, click to open) and the control-plane log — what worked,
  what didn't, and what it cost. The client's state is built from the *same* events that replay
  from the runs API, so a window that was closed while a flow ran opens showing the truth rather
  than a replay of what it missed.
- **A blackboard instead of string substitution.** Steps used to pass
  `prompt.replace("{step}", output[:5000])`. Every output is now stored whole under a short
  handle; the master sees an index and passes handles forward. Its four tools are built per run
  and close over the run id — a global `delegate(run_id=…)` would take the run id as an
  argument, and an argument is something a model can invent.
- **Two deep, enforced by the gate.** The master runs as a new `flow` principal that may invoke
  its roster and nothing else — `delegate` is not in `risk_of`'s table, so it arrives as "safe"
  and the roster deny is load-bearing, not belt-and-braces. Its agents run as `subagent`, which
  already may never delegate. No depth counter exists to forget to increment.
- **Permissions are part of the definition.** What a flow's roster may do is declared with the
  flow and materialised as real grants in the same table the Permissions app shows. Editing
  reconciles only the rows that definition wrote: a grant you added by hand, or tapped
  *Always* on, is never revoked by someone re-saving a flow. `add_grant` now keys on provenance
  as well as the tuple, because the two can read identically.
- **Four ways to start one.** Cron and OS events materialise a real scheduler row (so flows
  appear in the Tasks app, the TUI and the CLI for free); a message pattern starts one from
  Telegram or chat — an explicit `@subagent` still wins; and each flow can mint a webhook with
  its own secret. A webhook body is content from outside this machine, so the run it starts is
  tainted and the existing ceiling does the rest.
- **It asks instead of failing.** An unattended run that hits something it was not granted now
  pauses and asks — Telegram inline buttons when that is where it came from (Allow once /
  Always / Deny), otherwise every open window, including the session desktop. Which forced a
  real fix: `max_seconds` now means *working* seconds. A run waiting for you to tap Allow was
  being killed at 300s having done 20s of work, so asking a human was a reliable way to end a
  run. An unanswered question denies and the run carries on; only the budget stops it.
- **It answers where you asked.** A flow triggered from a Telegram chat replies in that chat —
  `telegram_send` grew a `chat_id`, which it always could have had.
- **Two ways to make one.** The roster picker has a **＋ New agent** button that borrows the
  subagent wizard — it opens over the flow editor, your half-filled flow survives, and the new
  specialist lands on the roster. Agents can also arrive with a flow and are created in the
  same save; an existing name is never overwritten.
- **✦ Draft a flow** takes a sentence: Aria writes the mission, proposes the specialists it
  needs, and scopes the permissions. The result lands **in the list as a disabled card**, not
  a modal you have to answer — something you can read beside your other flows, compare, come
  back to, or discard.
- **Aria can build flows now — from chat or from Telegram.** `create_flow`, `enable_flow`,
  `list_flows` and `run_flow` are ordinary tools, and Telegram is not a special admin channel:
  it acts as *you*, so "make me a flow that…" works from a phone. Defining one is its own
  capability, `flow.write`, because a flow definition **is** a set of standing permissions.
  Two rules make that safe: apps, subagents, workflows and flows are refused `flow.write`
  outright (anything that could write a flow could grant itself whatever it liked by writing
  one that says so), and a tool-made flow is **always born disabled** with `enable_flow` in
  ALWAYS_ASK — so the agent writes the definition and tells you what it would grant, and the
  granting is still a tap you make, wherever you are.
- **See the flow before it runs.** There are no steps to draw, so the chart draws what there
  is: the master and everyone it *may* call, ghosted. It is on every flow card and in the
  editor, and it redraws as you change the roster — so a flow is visible while you are still
  writing it.
- **Change it with AI, and see what changed.** The editor is two columns now: the form, and
  on the right the chart, an ask-for-a-change box and what saving would grant. A revision
  comes back as a **diff** — `tools: system_info → system_info, fetch_url` — with the model's
  own note, and nothing is written until you press Save. The Run Inspector has the same box,
  because watching a flow go wrong is the best moment to fix it; editing there is for the
  next run and never touches the one in flight. The subagent wizard got the same pane: draft
  a specialist from a sentence, or ask for a change to the one on screen.
- A revision returns the *whole* definition and models fill untouched fields with `null` —
  merged naively that silently reset a `max_delegations` somebody had tuned. Nulls are
  dropped and the revision is layered over what you already had; the name is always kept, so
  an edit can never fork into a second flow.
- **Executions.** A tab listing every flow run — when, which flow, status, how many
  delegations, which agents, which steps failed, duration, tokens, and what started it —
  filterable by flow, and clicking one replays it in the Run Inspector. Observability still
  mixes flows, workflows and one-off delegations; this is the flow-shaped view of it.
- **Test run, and a Run Inspector to watch it in.** Triggering a flow by hand is nearly
  always debugging, so the log comes to you instead of being somewhere to go and look: Run
  opens a window with the live graph, the control-plane log, the board, and **step detail** —
  what each agent was asked, every tool it called and whether it worked, and what it returned.
  Clicking any node in any graph opens it too. A flow you have not enabled says **Test run**:
  you can try it with you watching, which is what the disabled state is *for* rather than a
  limitation of it.
- That needed one more distinction in the gate, because a disabled flow has no `agent.invoke`
  grant and its delegations were being denied outright — so a test run could never call
  anyone. The roster branch now separates "not on the roster" (deny) from "on the roster but
  the flow is not enabled" (**ask**, with a grant offer). It escalates down the same path as
  any other ungranted capability, so unattended runs still end in a denial when nobody
  answers, and answering once grants nothing: after a test run the flow is still disabled and
  still holds zero permissions.
- **"Could not reach the model" was a lie.** That catch-all fired for any exception — a 404, a
  non-JSON body, a stale server — and sent you looking at Ollama when the real answer was that
  the server was running older code than the page it had just served. Errors now say what
  actually happened, and a 404/405 names the route and tells you to restart.
- **A disabled flow now holds nothing**, which is what makes creating a draft you did not
  explicitly approve safe: no permissions, no armed triggers, and Run refuses it. The card
  says what enabling *would* grant, and **Enable is the act of granting**. This is not a
  special draft state — it applies to any flow you turn off, and it closes a hole: until now
  a disabled flow kept its standing permissions, which is precisely what turning something off
  should stop. Enabling restores exactly what you wrote, webhook secret included, so callers
  never have to be told a new URL. **Discard** takes the agents the draft brought with it,
  unless another flow is using them.
- Three things the composer needed to be usable rather than a demo: the prompt carries the
  machine's real inventory and drops anything invented (saying so in `warnings` rather than
  silently); a worked example, without which small models write a lovely mission and leave the
  roster empty; and `{"type":"cron","at":"06:30"}` — the shape models actually write — is
  lifted into the wrapper shape instead of failing the draft.
- **`at: 730` no longer runs at nine o'clock.** `_next_daily` silently falls back to 09:00 on
  anything it cannot split on a colon, so a mistyped or model-written time became a job that
  ran at the wrong hour and never said why. Times are normalised (`730`, `7.30`, `7` → `07:30`)
  and anything unreadable is refused where somebody can see it.

### App Studio: a build you can watch, name, and consent to (2026-08-06)

A build that ran for twelve minutes and produced a working app reported that it had produced
nothing. Everything here comes out of that one screen.

- **A successful executor build said it failed.** The Claude Code path finished by broadcasting
  `{"app": …}`; the Studio branches on `app_id`. So the app was installed, versioned and sitting
  in the sidebar while the log said *"no app was produced — try rephrasing"*, the preview stayed
  empty, and the permission consent never ran. That path now closes out exactly like the one-shot
  builder — same terminal event, same lint warnings, same manifest. It was also reaching for
  `list_apps()[0]` to mean "the app just built", which sorts by **name**: correct on an empty
  machine, wrong on every machine after that.
- **Silence is not progress.** The log named tools without saying what they were on, so `Bash`
  for four minutes and `Bash` for four seconds looked identical, and the gaps between calls
  looked like a crash. Every call now shows the file, command or URL it is on, with its own
  clock; failures turn red in place with the reason; and a heartbeat reports what the run is
  doing between calls (`Bash · npm test · 2m 10s · $1.20`). Assistant text is one block per
  message with markdown rendered, instead of one slab with the sentences fused at the full stop.
- **The app's name and icon are the user's.** Left to itself the builder named an app after the
  sentence that asked for it — *"build an application that runs every 5 m"* — and made a second
  one next time the sentence differed. Name and icon are now fields above the prompt: applied to
  an existing app before the build so `create_app` updates in place, and forced onto a new one
  after. Renaming keeps the id, so data, versions, grants and pinned widgets follow. The icon
  picker offers the OS's own glyph tiles (`glyph:<key>`), an emoji, or the monogram default.
- **An app asks before it runs.** The consent screen was a link in a log line that had usually
  scrolled away, and executor-built apps never got one at all. A finished build now reads what
  the app actually calls and raises the consent screen as part of finishing. Versions and
  permissions live in tabs under the builder log, next to the thing that asked for them.
- **A 44KB app killed the build that wrote it.** `stream-json` puts one whole event on one
  line, and an event carries whole tool payloads — the app file the executor just wrote, read
  back to check its own work. asyncio's StreamReader defaults to a **64KiB line limit**, and
  crossing it does not truncate: `readline()` raises *"Separator is found, but chunk is longer
  than limit"*. So the size of a perfectly normal app was the thing that failed the build, with
  a finished `app.html` sitting on disk. The ceiling is now in app territory (32MB, a cap on one
  line and not an allocation), one line past even that costs the event rather than the run, and
  — the part that matters — **a lost stream no longer discards a finished app**. The file is the
  deliverable, `build_task` says so to the executor, and the build now goes and looks for it
  before reporting failure.
- **The AI runtime is documented.** `appLLM` / `appLLM.stream` / `appChat` / `appAgent` /
  `appCopilot` have been in every built app for a while and were in no document, so apps got
  built without the one capability that makes them more than a form.

### The agent, measured: what it remembers, what it trusts, what it costs (2026-08-04)

Four things the OS was doing without measuring, telling you, or bounding.

- **A conversation now remembers what it did, not just what it said.** Tool calls and their
  results lived in `messages.meta` — right for the chat window, wrong for the next turn: the
  model that read a file on Monday had no record of it on Tuesday beyond whatever it happened
  to write in prose. "Now do the same for the other one" then re-ran everything, or worse got
  answered from a file it could no longer see. Earlier turns' tool activity is replayed as a
  compact fenced digest, not as reconstructed `role:"tool"` messages — those need call ids
  that must match a live turn, and Gemini needs its own signature replayed against each one.
  Rebuilding that from storage would be a forgery some providers reject.
- **And a long thread stops dying.** History was unbounded, so the desktop's permanent
  conversation grew until the prompt filled the context window and every turn failed with
  "hit its token limit" — a thread that worked yesterday simply stopped, with no way back but
  deleting it. Turns that no longer fit are now distilled into a rolling summary, generated
  once and stored on the conversation, and **you are told in the conversation when it
  happens**: a summarised thread behaves differently from a whole one, and you are the only
  one who can say the summary lost something that mattered. Telegram used its own hand-rolled
  last-30-messages window; it uses the same rebuild now, because one conversation should not
  have two different memories of itself depending on which surface you answer from.
- **A fetched page can no longer spend a permission.** Grants answer *who is asking*; nothing
  answered *on whose say-so*. Output from `fetch_url`, `hermes_ask` and any `mcp_*` tool is
  fenced before the model sees it, and a turn that has read untrusted content holds its risky
  steps for a human — **at full autonomy too**, because full autonomy is trust placed in your
  instructions, not a stranger's. The ceiling sits *before* grants, exactly like the read-only
  channel ceiling: "allow fetch_url everywhere" is consent for the agent to fetch pages, not
  consent for a page to spend the grant on something else. For the same reason that approval
  card offers no "allow & remember" — remembering it would hand the next page the same key.
  Safe steps are never escalated, so reading and research stay as quick as they were. This
  does not stop a model being fooled; it stops a fooled model being *able* to act. Off,
  `ask` or `strict` in Settings → Agent, the TUI, or `security.taint`.
- **The Test pillar was only testing half of what it claimed.** `tests/` proves the OS works.
  Nothing proved the *agent* works — and every quality fix in this changelog's history (the
  empty turn, the announce-and-stop, the invented API key, the loop guard) was found by a
  person noticing it in a live conversation, with nothing to stop it coming back. `agentos
  eval` runs behavioural cases: one turn each, in a throwaway home with its own database,
  workspace and sandbox root, asserting deterministically which tools were called with what
  arguments and what the answer says. No LLM judge — a harness that disagrees with itself is
  one people learn to ignore. Also in the Evals app, the `run_evals` tool, and Mission
  Control. Deliberately **not** in the restart gate: evals need a live model, and blocking
  every self-modification on minutes of inference would stop the agent improving itself.
- It earned its keep immediately. It found that **`read_file("notes.txt")` was denied by the
  sandbox** — relative paths resolved against the server's working directory, which under
  systemd is nowhere near your workspace, so a model asked to read a file by name burned its
  whole step budget shelling out to find one it was standing next to. Relative paths now
  belong to the workspace. It also caught three of its own assertions being wrong, including
  one that scored a model *refusing* a destructive request as a failure.
- **What a turn costs is now recorded — in money, not just tokens.** Token totals already
  existed, re-derived by `/api/analytics/tokens` from the JSON meta of the last 1000 turn-log
  rows. That shape cannot carry a price, silently truncates history at 1000 rows, and has no
  answer for "which surface is expensive" or "what has this space cost". Spend gets its own
  table: `agentos usage` (and `/api/usage`, and Mission Control) reports by model, day,
  surface, kind, space or conversation. Tokens are a fact and money is an estimate, so they
  are kept apart — an unpriced model records no cost rather than a confident `$0.00`, prices
  live in `config.pricing` where you can correct them, and local models are priced at zero
  *explicitly*, because "free" and "unknown" are different answers. The old endpoint stays;
  it still answers for conversations that happened before the ledger existed.
- **Tool scoping: built, measured, and shipped OFF.** The 90 built-in tools are ~11,600 tokens
  of schema on every call — 47% of a 24,576-token local window before the system prompt or a
  word of your conversation. Narrowing that per step is the obvious fix, so it exists, with a
  core set that is never hidden, request-matched additions, per-turn pinning, and `find_tools`
  as the way back. Then `agentos eval` was pointed at it: on `ollama/qwen3.5:9b`, 11 cases ×
  2 rounds, **21/22 passed with all 90 tools and 19/22 with 30** — faster per step, slightly
  worse at the job, twice running. Small sample, and the individual failures look like
  ordinary 9B variance, but nothing in it justifies turning this on for everyone. So the
  default is `all`, the measurement is written down in `toolscope.py`, and anyone with a
  tighter window can enable it and check on their own model. Building the harness first is
  what made it possible to find that out instead of shipping a plausible regression.
- Two smaller things found along the way: filtering the tool catalogue for a subagent was
  writing **one access-ledger row per tool per turn** — ninety rows for one question nobody
  asked; it is a `could I?` probe now and the ledger keeps recording what was *done*. And a
  usage-ledger write can no longer take a turn down with it.

### Channels: every way in, and how far each is trusted (2026-08-01)

- **A channel is a way in, not a messenger.** Settings → Channels lists all of them
  together — this window, the session desktop, a terminal over SSH, a remote browser,
  the HTTP API, the schedule, Telegram, WhatsApp — because they are the same thing:
  a conversation arriving at the same agent, with the same memory and the same tools.
  What differs is who can speak through it and how far it is trusted, so those are the
  two things each card states. The GUI, TUI and SUI appear in the list as channels
  rather than as special cases, which is the point of modelling it this way.
- **Per-channel permissions, enforced by the machinery that was already there.**
  AgentOS has had surface-scoped IO gates and per-grant surface scoping for a while;
  this release gives them a front door. A channel's posture — inherit, look-don't-touch,
  ask-me-first, act-without-asking — sets the ceiling for its gate. "Act freely at the
  desk, ask over Telegram" and its reverse are both things people mean, so both
  directions are allowed.
- **Read-only refuses rather than queues, and outranks a grant.** A channel nobody is
  watching cannot answer an approval prompt, so on a read-only channel a risky step is
  denied outright. The check runs *before* grants on purpose: a ceiling that an
  allow-everywhere grant could punch through would not be a ceiling, and narrowing a way
  in should not be silently undone by consent given at the desk. Both are tested.
- **No dead controls.** The session desktop and a remote browser arrive through the same
  gate as this window, so a posture of their own would never be read — they say whose
  they follow instead of offering a select that does nothing, and the API refuses to set
  one with that explanation. Built-in channels have no off switch, because switching off
  the window you are reading this in is a lockout, not a setting. WhatsApp accepts its
  credentials and says plainly that the transport is not built yet.
- **Saved secrets are never handed back**, and a blank secret means "leave it alone"
  rather than "erase it" — otherwise saving an unrelated change on the same card would
  quietly wipe the token.
- **WhatsApp, Slack and Signal are carried by Hermes, not rebuilt here.** Hermes already
  runs a messaging gateway with those bridges, so a second Meta Cloud API integration
  beside a working one would be a worse copy of something already installed. These
  channels are *discovered* from `hermes send --list --json` rather than declared: a
  static list would have claimed Signal works on this machine because it appears in
  Hermes' config, when its gateway has in fact been failing to reach signal-cli every
  five minutes. Carried channels state their direction — AgentOS delivers out through
  them, and a reply arriving there is answered by Hermes' own agent, not by Aria in your
  AgentOS conversation. Without that sentence, "WhatsApp: on" reads as a promise the
  machine does not keep.
- **Delegated runs go to the Claude Code you already pay for, and now cannot drift.**
  The executor shells out to the local CLI, which bills against the Claude subscription
  it is signed in to — but the CLI prefers `ANTHROPIC_API_KEY` when it finds one, so a
  key sitting in a shell profile from years ago would silently turn every delegated turn
  into a metered API call. The child process no longer sees those variables at all, and
  the Executors panel states which account pays before the switch that starts a run.
- **Fixed: the allowed-tools list ran off the right edge**, so `Edit` and `Bash` could
  not be seen or ticked. A stacked-row rule meant for text fields was also stretching
  each checkbox to fill its grid cell, which pushed the labels away and forced every
  column past its minimum. Measured against the panel edge after the fix, not eyeballed.
- **Reaching this machine from anywhere, and the address that was already there.**
  `remote.py` answers "may someone else use this"; it could never answer "and how do
  they get here", which on a laptop behind NAT is the harder half. New `tunnel.py`
  reports every address that works *right now* and what could publish a better one.
  The first finding was that this machine was **already reachable from anywhere** over a
  connected tailnet — AgentOS just never showed it, listing only LAN addresses, so a
  desktop usable from a phone on mobile data looked like it only worked in the same
  room. Each address now says where it reaches from: "Tailscale · your devices, from
  anywhere" versus "This network · devices on this Wi-Fi".
- **The passphrase gate covers tunnels too, and that is the point.** A tunnel proxies to
  127.0.0.1, so without an explicit check it would sail straight past the rule that
  AgentOS must not be reachable off-loopback without a passphrase — a hole around our own
  front door. Publishing is refused until remote access is configured, and publishing to
  the whole internet (`funnel`) is a separate, clearly-labelled choice from publishing to
  your own devices (`serve`).
- **`tailscale serve` is refused with the fix instead of hanging.** It blocks
  indefinitely trying to provision an HTTPS certificate when the tailnet has none — 45
  seconds of nothing, here. The precondition is now detected up front and reported as
  the one-time switch that fixes it, alongside the note that the existing Tailscale
  address works meanwhile. `agentos tunnel` is the TUI face, which matters most on the
  headless box you cannot walk over to and read an address off.
- **Fixed: a delegated turn had no idea what it was looking at.** The built-in agent
  receives the copilot/omnibar context as `extra_system`; the executor was handed the
  bare sentence and nothing else, so "make the button in the top right bigger" arrived
  with no app, no state and no screen. It now travels via `--append-system-prompt`, and
  every forwarded surface gets it — a forwarded Telegram or scheduled turn otherwise
  arrived believing it owned the desktop.
- **Claude Code can now actually edit an AgentOS app.** Explaining that apps are
  database rows was honest but useless — the answer was always "ask somebody else". A
  copilot turn now checks the app OUT to a real file inside the workspace the executor
  already has, it is edited there, and AgentOS writes it back as a new version. Safe
  because it goes through `save_app`, which records a version on every change and keeps
  the last 30, so a bad edit is one Restore away. An emptied, deleted or absurdly large
  file is refused rather than saved, and a read-only envelope says it cannot edit
  instead of failing. Verified end to end against a real app: read → edit → version 2
  in the database, the rest of the app untouched, version 1 still restorable.
- **Fixed: an executor granted Write and Edit silently could not write.** The
  permission mode was a hardcoded `dontAsk`, chosen so a headless run would not block on
  a prompt nobody can answer. Tested against a real edit it turned out to *deny*: the
  run read the file, tried one Edit, was refused, and reported "the tool call was
  denied". The mode now follows the envelope — nothing to approve stays `dontAsk`,
  Write/Edit gets `acceptEdits`, Bash gets `bypassPermissions` — because the envelope is
  the approval. Only reachable when someone ticked those tools, and still bounded by
  `--tools` and `--add-dir`. Found by running it, not by reasoning about it.
- **It can also work on AgentOS itself.** An opt-in switch adds this OS's own source to
  the run, so the executor can fix AgentOS's tools and windows, and it is told the two
  load-bearing rules — the UI is built from `ui/src`, and a change that breaks the suite
  is not finished. Off by default and stated in the envelope sentence: the OS rewriting
  itself is its own decision, not a side effect of enabling an executor.
- **"Not installed" is no longer a dead end.** Claude Code missing now offers the exact
  install command with its output streamed into the panel, and installed-but-signed-out
  says to run `claude` once — a different problem with a different fix.
- **The OS offers to set remote access up rather than waiting to be asked.** When
  nothing reaches past the local Wi-Fi, Remote access says so and offers the fix in
  place, with the exact install command in view and a button that runs it — installed
  and verified through that endpoint here. Publishing to the public internet is
  confirmed separately, because "reachable from anywhere" and "reachable by anyone" are
  different promises.
- **A public address, set up for you.** Cloudflare quick tunnels give this machine an
  `https://…trycloudflare.com` name with no account, no DNS to configure and nothing
  opened on the router, since the connection is made outbound. Offered with its exact
  install command like everything else optional. The passphrase gate is checked before
  the provider, so no provider can route around it.
- **Fixed: it blamed the database for a built-in app.** Asked to fix the theme dropdown
  in Settings, the executor answered that "AgentOS apps live in the database, use App
  Studio" — false, and a dead end, since App Studio cannot edit Settings either. AgentOS
  has two kinds of app and they are opposites: a *user* app is a database row, a
  *built-in* app (Settings, Files, Chat) is the OS's own source. The blanket claim is
  gone from the preamble; the kind is now resolved where it is actually known, and a
  built-in app without source access names the switch that would grant it rather than
  sending anyone to a tool that cannot help. With the switch on, Claude Code found the
  real cause of that dropdown — no `color-scheme` declared, so the browser painted the
  native popup light while light text inherited in — fixed it in `ui/src`, rebuilt the
  bundle and left the suite green.
- **Fixed: real work stopped half-finished at a limit that was protecting nothing.**
  A build died mid-`python -m venv` reporting "stopped at the $2.40 spend ceiling". On a
  Claude subscription **nothing is billed per token** — the CLI reports a *notional*
  cost — so that ceiling controlled no spending at all and only truncated the work. The
  default now follows how the CLI is signed in: a tight guard on an API key, a much
  larger runaway backstop on a subscription. `budget_usd: 0` means "decide it from the
  billing mode", the message no longer talks about money when no money was spent, and it
  says the session resumes so nobody starts over. Settings labels it "Work limit" rather
  than "Spend limit" on a subscription.
- **App Studio can build with Claude Code, and builds got room to finish.** An executor
  now appears in the build picker and builds the app as a FILE — write it, read it back,
  fix it, keep going — instead of the built-in builder's single turn to emit an entire
  app in one fenced block, which is why an ambitious brief came back as a sketch. Builds
  also get a bigger step ceiling (10 was set for one-shot local models and left nothing
  for finishing) and a build floor on the limit. Refining keeps the app's own name, so it
  updates in place rather than leaving a duplicate.
- **The engine and model are chosen in Settings, and nowhere else.** The per-chat picker
  meant the same machine answered as different agents depending on which window you were
  in, and background work — tasks, Telegram, the API — could never see that choice at
  all, so "what is this machine running on" had no single answer. Chat now shows a chip
  that states it and opens the one place to change it.
- **A machine with no local runtime is offered one, at first run.** Setup used to detect
  no Ollama models and fall straight through to "give me a cloud API key" — a poor first
  run for someone installing a private, self-hosted OS, and it never said running models
  locally was even possible. Ollama is now a catalogue entry (MIT, llama.cpp underneath)
  offered by the GUI wizard, the CLI wizard and Settings → Components, with the exact
  command in view. No separate llama.cpp entry: it is packaged on Arch alone, and an
  entry absent on three of the four families we support is the silent gap the catalogue
  guard test exists to catch.
- **The context is translated, not forwarded verbatim.** The copilot preamble ends by
  naming `control_desktop`, `read_file` and `write_file`, which only the built-in agent
  has; handed to a filesystem agent it is worse than no context, because it sends it
  reaching for tools that do not exist. That line is dropped and replaced with what is
  actually true of an executor: no screen, no AgentOS tools, one directory — and the
  fact that decides whether the request is even possible, that **an AgentOS app is a
  single HTML document in the database, not a file on disk**. Verified live: asked to
  edit an app, Claude Code now names the app, explains it cannot reach it, and points at
  App Studio, instead of searching the filesystem and improvising.
- **Fixed: onboarding offered "? · ? detected" as the recommended location.** The chip
  was drawn before the locale fetch resolved, and if that fetch failed it stayed that
  way — the very first screen a new user sees, recommending a place nobody had detected.
  It now has three states: reading, detected, and could-not-read, and the last one asks
  where you are instead of pretending to an answer. Detection itself was never broken.
- **All three faces.** `agentos channels` prints the same table and
  `agentos channels <id> --posture …` sets it, because a headless box reached only over
  SSH is exactly where "who can talk to this, and how far do I trust it" most needs
  answering and has no settings window to answer it in.

### Executors, and this machine as a forwarder (2026-07-31)

- **AgentOS can hand work to another agent already on this machine.** Claude Code is
  the first executor: it appears as an engine in the chat model picker, and a delegated
  turn stays a normal AgentOS turn — working indicator, Ctrl+. to stop, persistence,
  sidebar, live tool chips — because its `stream-json` events are translated into the
  same events the built-in agent emits. Its session is kept per chat, so a follow-up
  continues rather than starting over. AgentOS keeps the desktop; an executor has no
  screen or keyboard.
- **Forward everything.** One setting turns the machine into a front end: every turn a
  *person* starts is answered by Claude Code or Hermes instead — chat, the prompt bar,
  copilot panels, Telegram, the headless API, and scheduled turns. Apps and App Studio
  are deliberately excluded and the UI says so, because an app calls the agent expecting
  AgentOS's tools and its own data store, and App Studio already has an explicit
  build-model choice. Verified end to end: a chat turn with no model in the payload, and
  a `POST /api/chat`, both reached Claude Code; the same call from an app did not.
- **Forwarding is never silent.** A machine answering as somebody else says so in the
  menu bar on every surface, with what is and isn't forwarded in the tooltip, and the
  chip opens the setting that turns it off. Over SSH, `agentos forward` prints the same
  thing.
- **The envelope is the safety story.** This build of the Claude Code CLI has no
  per-call permission hook, so tools are not approved one at a time — each run is bounded
  before it starts (folder, tools, model, spend), the bound is stated in one sentence
  wherever it can be granted, and the server clamps it: granting `Sudo` and $9999 comes
  back as the known tools at the $50 cap. Off by default, read-only when first enabled.
- **Failures say why, once.** An early run reported "the executor failed" twice with no
  reason; it had hit the spend ceiling — the one fact that made it fixable — and the
  non-zero exit was the same failure counted again. A test also caught a real widening:
  `budget_usd or DEFAULT` turned "spend nothing" into $2, because 0 is falsy.
- `agentos delegate` and `agentos forward` give the same capabilities a terminal.

## Unreleased — the ever-present agent (2026-07-26, second drop)

### You can keep talking while it works (2026-07-29)

Typing into a busy chat used to be refused outright: *"This conversation already has a turn
running — stop it, or continue in another chat."* Your next thought was worth less than the
agent's convenience. Now it is **queued**, and the running turn has to decide what it is.

- **A queue per conversation.** Whatever you send while a turn is running lands in the *Up
  next* strip above the composer — this chat's visible to-do list, with a `✕` on each row.
  It survives a reload (it rides `state_sync` like running turns do).
- **The turn triages it, at a step boundary.** Between steps — never mid-tool — the agent
  decides whether each queued message belongs to what it is doing *right now*. "Actually make
  it a bullet list", "put it in Documents instead" gets **folded into the live run**, marked in
  the transcript with `↩ took in: …`, and the rest of the turn accounts for it. "Also tell me a
  joke afterwards" **waits**, and starts as its own turn the moment this one ends. A turn that
  is about to end checks once more, so a message that lands during the final reply still counts.
- **The decision does not cost you time.** It starts the instant you hit send and runs alongside
  the reply already streaming, on `memory.model` if you have a small model set for that. If no
  model answers within `steer_triage_timeout`, the wording decides — and the default is to wait,
  because waiting is recoverable and hijacking a task in flight is not. `steer_queued_messages:
  false` turns the judgement off entirely and makes everything wait its turn.
- **The send button learned a second job.** While a turn runs, with something typed it queues
  (`➤`); empty, it is the stop button it always was (`◼`). Stopping drops the backlog with the
  turn — stop means stop.

### Window controls you can actually reach, and a session that feels immediate (2026-07-29)

- **The minimize button was being drawn and then clipped away.** The per-window controls
  lived inside `#tbnative`, which is `overflow-x:auto` — so the popup was rendered and
  silently cut off by the scroll container. That is what "minimize doesn't work" was: not
  a missing feature, an invisible one. The controls (minimize · maximize · full screen ·
  close) now live in a fixed-position element on the desktop, verified on screen and
  hit-tested so a click lands on the button rather than on whatever is over it.
- **Minimize from the window's own title bar.** Right-click a native title bar to minimize,
  middle-click to close. An app's *own* minimize button still cannot work — sway does not
  implement `xdg_toplevel.set_minimized`, so the request never arrives — but the title bar
  is ours to bind, and this is the real thing.
- **Window controls respond immediately.** The server answers in about two milliseconds;
  the sluggishness was a hard-coded 150 ms wait before redrawing, plus no optimistic
  update, so the tile sat unchanged through the whole round trip. State is applied to the
  tile first and the request goes out behind it; the compositor event that follows
  reconciles anything guessed wrong.
- **Apps launch straight from their `Exec` line.** We already parsed the .desktop file, so
  spawning `gtk-launch` to read the same file again was latency for nothing. Measured
  launch-to-window is now ~97 ms. Terminal and DBusActivatable entries still go through
  `gtk-launch`, which they need.

### Getting the machine back, and desktops that mean something (2026-07-29)

- **Lock and suspend no longer strand you.** swayidle was told what to do when the screen
  goes away but nothing about coming back: it had `before-sleep` and `lock` hooks and
  neither `after-resume` nor `unlock`. So a resume left the outputs powered off and the
  shell unfocused — a black screen with no way to the desktop. Both hooks now power the
  outputs on and call `/api/shell/wake`, which re-anchors the desktop, focuses it and
  repaints the things that go stale after hours asleep. swayidle also moved into its own
  script (`~/.local/bin/agentos-idle`): `swaymsg reload` can now actually restart it —
  with `exec` the old daemon kept running with the old arguments and an idle-timeout
  change silently did nothing — and the lock command's quotes can no longer break it.
- **Desktops move external windows.** An AgentOS desktop is now a real sway workspace, so
  switching carries the desktop with you and leaves the apps where you put them. They
  used to appear on every desktop because the two ideas of "desktop" were unrelated.
- **Alt-Tab shows you something.** It was a single keypress that just switched. It is now
  a compositor *mode*: hold Alt and the desktop comes forward with a switcher — the
  AgentOS desktop plus every window, real icons — Tab moves the selection, releasing Alt
  commits, Escape cancels. That is the only way to show an overlay while a native window
  is on top.
- **Ctrl+Space actually comes forward now.** Two bugs on top of each other: `anchor_shell`
  runs on every window event and does `floating disable`, so it dropped the desktop back
  behind the apps the instant it was raised; and the raise was four separate sway commands,
  which let the client ack its remembered floating size before the resize landed — the
  desktop came forward at half width. It is one chained command now, and anchoring stands
  aside while the desktop is deliberately summoned.
- **No more "press and hold Esc".** Raising by full screen made Chromium believe the *page*
  had gone full screen, so it flashed that bubble on every summon. Floating the desktop and
  sizing it to the output looks identical and says nothing.
- **The menu bar follows the compositor, not the page.** It said "Task Manager" while you
  were typing in VS Code. A focused external window now owns the bar.
- **AgentOS refuses to open inside AgentOS.** It is not a window, it is a second session
  fighting this one for the screen, the notification bus and the port — so it says that
  instead of launching.
- **Native windows have title bars** (middle-click to close). Worth being straight about
  the limit: sway does not implement `xdg_toplevel.set_minimized` at all, so an app's own
  minimize button cannot work under any wlroots compositor. AgentOS provides minimize from
  the taskbar tile, the Window menu and Super+H.

### External apps are windows on this desktop (2026-07-29)

The session treated native windows as second-class: they could not be minimised, they
had no icons, Alt-Tab did nothing, and one of them covering the screen left nowhere to go.

- **The shell was being mistaken for an app.** Chromium applies `--class` only to
  XWayland, so under Wayland the AgentOS desktop arrived looking like the browser and
  matched no rule written for `agentos`. It was therefore listed in its own taskbar, and
  "Alt-Tab back to the desktop" — which searched for `app_id="agentos"` — never matched.
  The shell is now identified by its command line (the process serving our port), which
  is the one honest signal. This was the root of several of the symptoms below.
- **Minimize works.** sway has no minimise; AgentOS parks the window in the scratchpad —
  hidden but alive — and *keeps it in the taskbar*, so it can be brought back. Click a
  focused tile to put it away, click a hidden one to bring it back, exactly like an
  AgentOS window. **Super+H** minimises the focused window.
- **Alt-Tab, Super-Tab.** One ring: the AgentOS desktop, then every native window in a
  stable order (sorted by window id, because sway reshuffles tree order under you and
  that made Alt-Tab ping-pong between two windows). Ctrl+Tab switches windows while the
  desktop has the keyboard, and is deliberately left to the app otherwise — browsers and
  editors need it for their own tabs.
- **Show the desktop.** **Super+D**, the desktop right-click menu, or any native
  window's menu hides every native window and puts the keyboard back on AgentOS. This is
  the escape hatch that was missing.
- **Maximize and full screen are different things, and you get both.** Maximize fills the
  desk but leaves the menu bar reachable; full screen covers everything. Minimize,
  maximize and close also sit right on the window's taskbar tile, so they are one click
  away rather than a menu hunt.
- **Real icons.** A running window's app_id is matched against the installed desktop
  entries (including `StartupWMClass`, which is what makes "org.gnome.Nautilus",
  "nautilus" and "Nautilus" the same program) and the app's own icon is shown instead of
  its first letter.
- **External apps get a menu bar.** The focused native window puts its real name and a
  Window menu in the top bar — minimise, full screen, tile/float, move to desktop,
  close, show desktop — plus Help. We do not fake the app's own File and Edit; what is
  offered is what the window manager genuinely owns.
- **Ctrl+Space works over a native window.** The shell is the tiled base layer and sway
  paints floating windows above tiled ones, so no z-index inside the page could help:
  summoning now brings the whole desktop forward (full screen, the one state that
  outranks floating) and releasing puts it straight back underneath.
- **Screenshots from the desktop right-click** — whole screen or a region.
- **The keyring error at login.** `XDG_CURRENT_DESKTOP` was set to `AgentOS`, a name no
  other software recognises — which is why apps reported *"OS keyring couldn't be
  identified for storing the encryption related data in your current desktop
  environment"* and fell back to plain text, and why portals could not pick a backend.
  It is a colon-separated list, and it now reads `AgentOS:sway:wlroots:GNOME`. The secret
  service is also started *before* sway, so every app the session launches inherits
  `SSH_AUTH_SOCK` and `GNOME_KEYRING_CONTROL` rather than only D-Bus-activated ones.

### Every app has a widget mode (2026-07-28)

- **Two surfaces, one app.** Every built app now has a desktop surface (the whole application) and
  a **widget** surface (the one glanceable fact). Mark them `.desktop-only` and `.widget-only` and
  the OS shows exactly one — before the app's own code runs, so there is no flash of the wrong
  view. `window.appSurface` = `{mode, size, widget, desktop}` for anything that needs to branch in
  JS, and both views read the same `appData` state.
- **S · M · L, chosen while editing.** App Studio gains a size picker beside *Pin to Desktop*:
  Small (260×170), Medium (340×240) or Large (460×340). The size belongs to the *app*, not to a
  placement, so it looks the same wherever it is pinned; changing it resizes every pinned copy.
  *Preview widget* renders the widget surface at exactly that size, so "does it still read at S?"
  is answered before pinning. A widget's own right-click menu offers the three sizes too.
- **The builder builds both.** Generated apps are now required to ship a widget view — a KPI tile
  or two short lines, never a table or a form — readable and complete at S.

### A session that behaves like a session (2026-07-28)

- **External apps launch again in session mode.** "Launching…" and then nothing: the
  server is started by systemd at login, so its environment has no `WAYLAND_DISPLAY`,
  `DISPLAY` or session bus — every GUI app it spawned died the instant it tried to open
  a window. Launches now go through the compositor (`swaymsg exec`), which hands the
  child the session's own environment, and sway itself imports that environment into
  systemd and D-Bus so activated services (portals, file choosers) can open windows too.
- **The desktop fills the screen.** Chromium only applies `--class` to XWayland, so under
  native Wayland the shell arrived with the browser's own app_id and missed every rule
  written for `agentos` — leaving it floating at a default size. The shell is now found
  by its command line (the process pointed at our port) and anchored as the tiled,
  borderless base layer, with every native window floating above it.
- **Display settings.** System Settings → Displays sets resolution, refresh, scale,
  rotation and on/off per output — and the layout is written to a compositor drop-in, so
  it survives logout instead of lasting until you close the lid. (The persistence block
  was there but sat after the `return`; it never ran.)
- **Keyboard & Mouse.** A new settings tab for keyboard layout and variant, repeat delay
  and rate, tap-to-click, natural scrolling, disable-while-typing and pointer speed —
  applied to the live session immediately and kept for the next one.
- **The pieces a Wayland session is expected to have.** The generated sway config now
  starts the desktop portals (screen sharing, native file dialogs), a polkit agent, the
  secret service, your `~/.config/autostart` entries, and a removable-media agent so a
  USB stick mounts by itself. Play/pause, next and previous keys drive whatever is
  playing, volume and brightness keys are answered by AgentOS itself so the on-screen
  feedback matches, Print takes a screenshot — and a full-screen window inhibits the idle
  lock, so a film no longer gets interrupted.
- **Night light.** System Settings → Displays warms the screen between hours you choose.
  Off unless you ask for it, and it survives reinstalling the session.
- **Every window has menus.** File · Edit · View · Window · Help sit in the menu bar for
  the focused window — new window, find, screenshot, close; undo/cut/copy/paste/select
  all against whatever holds the caret; full screen, maximize, the agent panel, Spaces;
  tiling, move-to-desktop and every other open window; shortcuts, the manual, about.
  Apps add their own entries (Files: go to root, go up, copy path; Terminal: clear, copy
  selection) and they merge into the standard menus rather than replacing them. Menus are
  rebuilt when focus changes and recomputed when opened, so they always describe the app
  as it is right now.


The theme: **the agent stops being an app.** Until now the AI lived in a Chat
window; every other surface was point-and-click. Now there is always somewhere
to talk — on the desktop and inside every single application.

- **The build model is your choice, not a ranking.** App Studio used to rank models by a
  hardcoded list of names — which had no `gemini` in it, so a machine with a Gemini key
  built with a local 9B instead. That ladder is gone. Authority now runs: the model picked
  for this build → **Settings → Agent → Build model** → your default model. AgentOS never
  substitutes another model on its own, and when a build produces nothing it *asks* —
  "gemma4:12b did not produce an app. Run it again with: [model] [Retry]" — instead of
  silently switching. A model you pick also stays picked when the provider list is
  momentarily missing it ("unavailable right now" rather than a quiet reset).
- **A build no longer throws away work.** If the model writes the finished app in a
  ```html block without calling `create_app`, AgentOS builds it from that block instead
  of failing.
- **Stop the agent from anywhere.** **Ctrl+.** halts every running turn and any build,
  from any app, any window, even mid-sentence in a text field. Every surface that can
  start a turn can now stop one: the AI bubble grows a ◼ while it works, a copilot
  panel's send button becomes ◼, and an omnibar answer card shows Stop while it thinks.
  Anything queued behind the stopped turn is dropped too.
- **The agent notices its own loops.** The same tool called with identical arguments four
  times in one turn ends it: "that is a loop, not progress" — instead of quietly burning
  the whole step budget.
- **The prompt bar sits behind your windows.** It lived on top of everything, covering a
  maximized app. It now belongs to the desktop layer — a window covers it — and
  **Ctrl+Space, Ctrl+K, or a double-tap of Ctrl** summons it to the front (over full
  screen too). Esc or a click elsewhere drops it back behind your work; an answer card
  stays up until you dismiss it.
- **Arrow keys drive the desktop.** Ctrl+← / Ctrl+→ walk the desktops (wrapping),
  Ctrl+Shift+← / → carry the focused window across and follow it there, Ctrl+↑ opens
  Spaces, and Ctrl+↓ organises what's in front of you: tile → cascade → exactly back
  where they were. All seven are rows in the editable shortcut table, and they stand
  aside while you're typing — though an *empty* prompt bar no longer counts as typing,
  so the shortcuts work on a fresh desktop where the bar holds the caret.
- **Each desktop decides for itself whether it carries the deck.** Desktop 1 is the
  launcher; every other space starts clear, so windows get the whole canvas to be moved
  and arranged in. Ctrl+Shift+D (or the ▾ handle, which stays reachable on a cleared
  space) toggles the deck for the desktop you are on, and the choice is remembered
  per desktop.
- **The copilot is silent until you ask for it.** A window no longer opens with a chat
  panel attached: the ✦ fades in only on the focused/hovered window, and the panel opens
  on demand — click it, or press Ctrl+Shift+Space, which works in full screen too.
- **The prompt bar takes pictures.** Paste or drop an image into the bar, or press the ▣
  button to capture the screen, and the shot rides along with your question (thumbnails
  above the bar, up to four, downscaled so a turn stays light). Asking with no text but
  an image just asks "What do you see here?".
- **Wallpaper generation survives a rate limit.** Pinning a provider (Settings → Image
  generation) meant a Google 429 was fatal and surfaced as a bare "google429". The pinned
  provider is still tried first — now with one retry — but a rate limit or outage falls
  through to the remaining providers and the result says so ("came from the free service").
  Errors carry the API's own explanation instead of a status code, Imagen models are
  supported (`:predict`, aspect ratio) alongside Gemini's `:generateContent`, and
  Personalize shows failures in a readable dialog rather than a vanishing toast.
- **Gemini tool calls work again.** Google signs every function call with a
  `thought_signature` and rejects the *next* request with HTTP 400 if it isn't replayed
  ("Function call is missing a thought_signature… position 4"). Provider baggage on a
  tool call is now captured while streaming and echoed back verbatim with the history.
- **A saved API key is never shown again.** Keys were masked server-side but the mask
  was rendered back into an editable field. A stored secret is now a locked chip
  ("saved ••••4MNQ") with a Replace button — nothing sensitive sits in the DOM, and a
  mask can never be echoed back over the real key.
- **Desktops are spaces you can organise.** F3 (or Ctrl+↑) opens Spaces: every desktop
  as a live mini-map card at the top, the current desktop's windows scaled below.
  Drag a window onto a card — or onto a pager button — to move it; click a card to
  switch; ＋ adds a desktop and ✕ removes one (its windows move, never vanish).
- **Real window control.** Right-click any title bar for Full screen · Maximize ·
  Minimize · Tile left/right/centre · Move to Desktop N · New window · Close. Per-window
  full screen covers the menu bar and dock (Esc or F exits), and the pager now shows
  which desktops have windows, with the app names in the tooltip.
- **Settings is a real preferences app.** The endless scroll of full-width inputs is
  gone: a category rail (AI providers · Agent · Locale · Shortcuts · Voice · Appearance ·
  System), preference GROUPS as cards, and rows that read label + description on the
  left, control on the right — with proper toggle switches instead of bare checkboxes.
  Search still spans every category. Two reusable primitives (`pGroup`/`pRow`) back it,
  so other panels can adopt the same grammar.
- **App windows are opaque again.** Window bodies were translucent glass, which made a
  settings form sit unreadably on top of the wallpaper. Glass now belongs to chrome
  (bar, dock, popovers, deck); content windows are solid.
- **External apps show up in session mode.** The server is normally started by systemd
  at login, so it never inherited `$SWAYSOCK` — and the AgentOS session reuses that
  server, which therefore reported `hosted` forever and listed no native windows. It now
  discovers the compositor socket for its own user, verifies the compositor really is
  the AgentOS session (reading its environment), attaches **late** when the session
  appears, and tells the shell to re-read its capabilities. Verified against a real
  nested sway: the same server flipped hosted → de without restarting and listed a
  launched app.
- **One glass material across the shell.** The deck groups, widgets, answer cards,
  the prompt bar, the launcher list and the AI bubble all draw from a single recipe
  (`--glass-tint` / `--glass-blur` / `--glass-edge`): a translucent tint over a 30px
  saturated blur with a hairline of light along the top edge — and a matching light-mode
  variant. Desktop widgets are glass now too: an app pinned as a widget renders with a
  transparent page (`?surface=widget`), so the wallpaper reads through its content
  instead of a flat slab sitting on it.
- **AgentOS knows where and when you are.** A new Locale record (country, timezone,
  language, city, units, 12/24h) is detected from the machine — timezone decides the
  country, so an en_US locale in India no longer reads as "United States" — confirmed
  by the agent during first run, editable in Settings → Locale. It reaches the agent's
  system prompt ("localise news, weather, prices, holidays, units… never assume the
  US"), renders the prompt's clock in your timezone, drives the menu-bar clock, and is
  exported into the AgentOS session (TZ/LANG/LC_*) so native apps agree with it.
- **The desktop is wallpaper again — apps live in the deck.** Bento groups of app
  tiles sit above the prompt bar and **claim the desktop space they need**: groups wrap
  into rows and grow upward from the bar (scrolling only once they hit the menu bar), so
  nothing is clipped off-screen at any window size. Rename, reorder, create ("＋ New
  group") and move apps between groups by right-click. It shows on a bare desktop and
  steps aside the moment you're working in a window; Ctrl+Shift+D or the ▾ handle
  collapses it entirely and pins that choice.
- **Widgets choose where they live**: free on the desktop, as a card in the deck,
  in the strip beside the prompt bar, or shrunk into the menu bar — right-click a
  widget's header to move it.
- **An AI presence bubble sits bottom-right** whenever a turn is running anywhere
  (a copilot panel, the omnibar, a background task) and after a reply you haven't
  read; one click opens that conversation in Agent Chat.
- **Shortcuts are a table you can edit** (Settings → Shortcuts): click a binding,
  press the keys. Session-marked shortcuts are also written into the compositor,
  so they keep working while a native window holds the keyboard — Alt+Tab included.
- **Turns finish the job.** The agent no longer ends by announcing work it never did
  ("Let me fetch some top stories:") — a dangling lead-in, or a tool that failed while
  the reply stayed silent about it, gets one push for the actual deliverable. And the
  system prompt now forbids inventing credentials: a fabricated API key only ever
  returns 401, so keyless sources (RSS, public endpoints) or a connected MCP server
  come first, and a missing key is stated plainly instead of guessed.
- **Empty replies are gone.** A thinking model (qwen3.5:9b here) can spend an entire
  reply in its thinking channel and return no text and no tool call — the turn used to
  end with a silent blank bubble. The agent now retries once with thinking off and, if
  it is still empty, says so instead of showing nothing. A queued ask can also stop the
  turn ahead of it ("Stop current & send") so a wedged turn can never trap the bar.
- **Asks queue instead of being dropped.** A second question while the agent is
  busy now waits its turn (and says so) rather than bouncing off a toast.
- Agent Chat no longer opens itself at login — the prompt bar is the way in, and
  answer cards no longer dump the model's raw reasoning.
- **The omnibar is the launcher too** — the old command-palette overlay is gone,
  so there is exactly one prompt surface. Ctrl+Space / Ctrl+K / Alt+Space pops
  the bar itself (it grows, focuses, selects) with results above it; typing
  anywhere on the desktop lands in it. **Enter launches** what you named —
  asking is the default only for question-shaped input — **⇧Enter** always asks,
  and **Alt+1…9** quick-launches a result row (or the Nth dock app when the list
  is closed). Ranking is name-first, so scattered-letter noise no longer buries
  the app you typed.
- **The omnibar.** A slim glass bar floats above the dock, always. Its orb
  breathes while idle and pulses while any turn runs. Start typing anywhere on
  the desktop and the keys land in it. The intent grammar reads as you type
  (a ghost row offers "Open Terminal" / "Volume 30" — Tab accepts); Enter sends
  to the agent and the answer streams into a card that rises above the bar —
  markdown, live tool cards, inline approvals — with one-click escalation to
  the full Chat window. All omnibar turns share one persistent **Desktop
  thread**. Quick asks from the palette now route here instead of opening Chat.
- **Every app has its agent.** A ✦ button in every window's title bar slides
  open a copilot panel: a compact conversation scoped to THAT app. It knows
  what the app is showing (a per-app `context()` line — current folder, active
  settings tab, selected Studio app, live CPU numbers…), speaks with the app's
  starter prompts ("Fix my wifi", "What's eating my RAM?", "Clean up outdated
  memories"), acts through the full tool set, and the app **refreshes itself as
  the agent's tools run**. Each app keeps ONE persistent thread
  (`origin=copilot:<app>`), grouped under **Copilots** in Chat's sidebar — the
  Files agent remembers last week's conversation about your files.
- **Visible hands.** When the agent touches an app — opens it, closes it,
  generates a wallpaper, edits an app in Studio — that window and its dock icon
  glow. You watch the OS being operated.
- **Agentic empty states.** Empty panels now invite action: "No memories yet →
  ✦ Ask Aria", "Nothing scheduled → ✦ set up a useful daily schedule".
- **User-built apps get the same.** The injected runtime ships
  `appCopilot.mount({starters})` — a one-call resident agent widget (corner ✦,
  conversation panel, acts via appAgent under the app's own grants) — and the
  builder persona mounts it in every generated app by default.
- Plumbing: chat-event **sinks** let any surface render any conversation's live
  stream (Chat, omnibar cards, copilot panels — simultaneously); `run_chat`
  accepts per-surface context (sanitized, capped) appended to the system
  prompt; conversations carry an origin end-to-end; the menu-bar spinner now
  reflects every running turn, not just the visible chat.

Tests: 230 passing.

## The living-desktop release (2026-07-26)

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
