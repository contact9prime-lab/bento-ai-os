# AgentOS — Product Vision & Roadmap

*Why this exists, what makes it different, and what to build next. (July 2026)*

---

## Positioning

Every personal-agent product on the market today — OpenClaw-class assistants, the
wave of "Claude in your terminal" wrappers — is **chat-first**: a bot you message, with tools
bolted on. They live in a message thread. Everything they know, do, and produce is trapped in
scrollback.

AgentOS's bet is different: **the agent doesn't live in a chat window — it lives in an
operating system it builds around you.** The OS metaphor is not skin; it is the product:

| OS concept | What it does for the agent |
|---|---|
| Desktop & windows | you *see* what the agent knows and does — nothing hides in scrollback |
| Apps | recurring needs become software the agent writes, not answers it repeats |
| Widgets | ambient state, always on screen, updated by background jobs |
| Files & reports | deliverables persist as artifacts, not messages |
| Permissions & policies | OS-grade trust model instead of "YOLO mode" |
| Snapshots | restore points that make self-modification safe |
| The store | an ecosystem: everything above is shareable and installable |

**One-line pitch:** *Chat-first assistants answer you. AgentOS builds you an operating
system — apps, automations, memory, and a knowledge graph that compound the longer you use it.*

---

## Why chat-first assistants can't easily follow

1. **No visual surface.** Their output medium is text in a thread. AgentOS renders live apps,
   graphs, dashboards, and a desktop the agent itself restyles (`create_theme`,
   `create_app`, `pin_widget`).
2. **Flat memory.** Markdown-file memory with no structure, no scoping, no lifecycle.
   AgentOS scopes memory on two axes — user/session *and* which space (project) it belongs
   to — with automatic extraction after every turn, semantic recall, contradiction
   supersede, session rollup, and a deduplicated knowledge graph whose assertions carry
   the scope while entities stay shared. All visible and editable in the UI (◈ Memory,
   Graph, Profile, Spaces, Timeline).
3. **Trust came last.** The OpenClaw wave normalized agents on personal machines — and also
   normalized exposed gateways, unvetted community skills, and prompt-injection horror
   stories. AgentOS ships autonomy levels, approval gates, allow/deny policies, a bubblewrap
   sandbox, full audit logs, and snapshots as *first-class product*, not disclaimers.
4. **A bot, not a place.** Nothing accumulates. In AgentOS, week 4 looks different from
   week 1: more apps, more automations, richer memory. Switching cost grows with use —
   that's the moat.

---

## Pillars & feature roadmap

### A. An OS that knows you — memory & identity  *(largely shipped)*
- Two-tier memory (user/session), injected every turn; pin / edit / promote / delete in UI
- Auto-learn: background extraction of memories + KG facts after every chat turn
- Semantic recall (local embeddings, auto-detected model), keyword fallback
- Contradiction handling: corrections supersede, retractions delete (pinned are immune)
- Session rollup: idle conversations distill into durable memory
- KG entity dedup; Profile app ("what do you know about me?")
- **Two axes, not one**: scope (user/session) × space (this project / everywhere). See
  pillar J — memory and facts are filed where they are true, and a space always sees
  the global scope alongside its own
- Timeline of milestones — what was run, made, learned and changed (pillar J)
- ▢ Memory provenance — click a memory → the conversation that taught it
- ▢ Portable brain — export/import the whole memory+KG+soul as one encrypted `.brain` file.
  *Your agent's mind is yours; take it to another machine (or another model) in one file.*

### B. Personal software factory — apps & widgets
- `create_app` / App Studio (agent-built UI apps), desktop widgets, app data store
- ▢ **App Studio → IDE** *(requested, next up)* — versioned apps: every build/refine saves an
  `app_versions` row; a diff view between versions; one-click rollback; a code pane (editable
  source next to the live preview); **Export** — push an app to a git repo / download as a
  signed `.aos` bundle; **Publish to the store** — PR into the community index straight from
  the Studio. The store's install button already exists; this closes the loop: build → version
  → export → share → install
- ▢ **App packs** — one installable bundle = app + skill + scheduled job (e.g. "Meal Planner"
  = UI + recipe skill + weekly grocery-list job)
- ▢ **App gardener** — a nightly job where the agent reviews its own apps' usage/errors and
  improves them; changelog shown in the app
- ▢ Desktop modes — agent-curated layouts ("work", "evening", "travel") that swap widgets,
  wallpaper, and pinned apps by context

### C. The proactive OS — triggers & automations  *(largely shipped via flows)*
- **Triggers**: cron/interval/daily, an inbound **webhook** per flow (own secret, own
  cooldown, payload treated as untrusted), a **message pattern** on Telegram or chat, and the
  existing OS events (desktop notification / file change / login / idle) — all of which now
  bind to a flow, not only to a bare prompt. See pillar E and
  [design/flows.md](design/flows.md)
- **Team → Flows** is the automations app: trigger → mission → deliverable (report / telegram
  / notification / desktop), with the live run graph, the board and the control-plane log
- **Daily briefing** ships as the seeded built-in flow — deliberately with no trigger, so a
  fresh install does not start doing things at 08:00 because it was installed
- ▢ Remaining trigger sources: email/calendar events (via MCP), system thresholds
  (disk > 90 %, process died, battery low), RSS/price/website change
- ▢ A dry-run button: "show me what this flow would do" without spending anything
- ▢ Heartbeat: a periodic "look around, anything need doing?" turn with a strict token budget

### D. Trust is the product — security & control
- Autonomy levels, approval gates, policies, bwrap sandbox, audit log, snapshots
- ▢ **Secrets vault** — agent *uses* credentials (templated into commands/requests) without
  ever seeing them; per-secret allowed-tools list
- ▢ **Privacy ledger** — a UI page answering "what left this machine today?": every outbound
  request grouped by provider/destination, with payload sizes
- ▢ Dry-run mode — "show me exactly what you would do" before granting full autonomy
- ▢ Signed packages + permission manifests for store items (see G) — the answer to the
  malicious-skill problem the OpenClaw ecosystem keeps hitting

### E. A staff, not a bot — subagents & the execution fabric
*Full design: [design/subagents.md](design/subagents.md) — status: **F0 shipped**, L1+ on the radar.
Flows (an agent as the control plane) shipped on top: [design/flows.md](design/flows.md).*
- **Flows** — a standing mission with a roster, declared permissions, triggers and delivery
  sinks. A **master orchestrator** picks the agents and the order while it runs, aggregates
  their work on a run-scoped blackboard of full artefacts, and finishes. The graph you watch
  is a trace, not a plan. Two deep, and it is the permission gate that says so: the master is
  a `flow` principal whose only route to `agent.invoke` is a grant its own definition wrote,
  and its agents are `subagent`s, which may never delegate
- **Permissions defined with the definition** — declared once, materialised as real grants,
  reconciled on every save without touching anything a person wrote by hand
- **Pause, don't fail** — an unattended run that hits an ungranted action asks (Telegram
  inline buttons where it came from, else every open window) and resumes; `max_seconds` means
  working seconds, so waiting for a person costs a run nothing
- **Subagent definitions** — named specialists with their own soul, model, tool allow-list,
  bound skills, autonomy cap, and budgets; built-ins seeded (researcher / writer / validator)
- **Control plane / data plane split** — the control plane owns definitions, model
  resolution (step → subagent → default: "smartness flows down"), start/cancel, and
  telemetry; every run is a data plane with a sidecar heartbeat and two-way event traffic
- **Heterogeneous smartness** — per-step model override: generate on Ollama, validate on
  Claude (or run everything on one LLM via inherit). Data planes never hold provider keys;
  `/api/plane/llm` is the control-plane model surface L1+ workers will call over mTLS
- **Visual workflows** — DAG of subagent steps rendered as a live SVG flow in the Team app
  (); parallel layers, per-step status animation, run/cancel from the UI
- **Observability per data plane** — faults / performance / tokens per subagent & workflow,
  live heartbeat ages with STALE flags, and the main agent (L0 current setup) reported
  through the same pane; `delegate` + `run_workflow` tools for the main agent
- ▢ **L1–L3 execution** — task-envelope wire protocol, `agentos serve --worker`,
  **mTLS-based creation** (parent-as-CA, one-time-token enrollment, docker workers
  born-enrolled, rotation/revocation), remote nodes
- ▢ Memory proposals from remote children (parent's dedup pipeline decides); scheduler jobs
  targeting a subagent so heavy recurring work runs off-box

### J. Spaces, media & the enterprise hub  *(foundation shipped — the rest is sequenced below)*

Two use cases drove this pillar, and the foundation both were blocked on is now in:
a creator running a social/content operation, and an operator running several agents
at once. Neither could work while the knowledge graph was global-only and everything
a media MCP returned was thrown away.

**Shipped (the foundation):**
- **Spaces** — a first-class container for a thing you are working on. Conversations,
  memory, KG assertions, assets, runs, scheduled jobs and audit entries each belong to
  one, or to the global scope. The rule everywhere is `space ∪ global`: a space sees its
  own rows *and* what is true everywhere, so switching project never loses your name.
  Per-surface active space (the desk and the phone do not fight), authoritative on the
  conversation (reopening a thread never moves it)
- **Scoped knowledge graph** — assertions carry the scope, entities do not: a person is
  the same person in every space. `kg_query` became a join instead of loading the whole
  graph into Python, which is what made scoping affordable
- **Space-aware extraction** — the post-turn memory pass classifies global vs space with
  one testable rule ("would this still be true after the project ends?"), and session
  rollup lands in the space rather than in your global memory
- **Timeline** — a materialised index of milestones (runs finished, assets produced,
  memory learned, apps changed), not a second copy of the message log
- **MCP media bridge** — non-text content a server returns is stored instead of
  discarded. Images, video, audio and blobs become assets with provenance; images are
  attached for vision, video and audio travel as asset ids because no provider path can
  carry them and pretending otherwise would be a silent no-op
- **Asset store** — content-addressed under `~/.agentos/assets`, zero new dependencies,
  a raw-body streaming upload, a Gallery with real `<video>`/`<audio>`, and honest
  degradation when ffmpeg is absent (offered via `components.py`, never shipped — it
  is GPL)
- **The access ledger** — every PDP decision writes one structured row: who, what
  resource, which surface, which rule, what outcome. `logs` stays the operator's diary;
  this is the queryable record an enterprise actually needs. `media.*` and `space.*` are
  grantable actions, and memory/KG resources are space-qualified so "this subagent may
  write memory in one space only" is one grant

**Next, one at a time:**
- ▢ **Creator suite** — local rendering (trim/concat/caption/reframe) behind the offered
  ffmpeg component, a storyboard the agent fills with `storyboard_add_shot`, and a
  **Media & creative** category in the MCP catalogue (Higgsfield, Canva, Replicate, fal;
  ElevenLabs moves into it). Publishing goes **through MCP servers** — no bespoke
  TikTok/Instagram API clients to own and no platform review to chase — with
  `publish.post` as a risky, grantable action per carrier and target
- ▢ **Multi-agent for an operator** — `delegate(wait=false)` with a durable run registry,
  concurrency caps and token budgets per subagent and per space, scheduler jobs that
  target a subagent, artifacts and a run-scoped blackboard for handoff, and an
  org-chart surface in the GUI *and* the TUI. Recursive delegation stays denied; a
  separate `agent.handoff` action with a framework-enforced depth cap is the way in
- ▢ **A persistent approval queue** — today an unattended run either has full autonomy or
  is auto-denied after a 300s in-memory wait. A parked decision should survive a restart
  and be answerable in the morning from a phone, over SSH, or at the desk
- ▢ **The gateway hub** — `agentos/openclaw.py` behind one `Gateway`
  interface (install, status, config, lifecycle, live target probe). AgentOS owns a
  *named subset* of `~/.openclaw/openclaw.json`, applied through `openclaw config set`
  and picked up by the gateway's hot reload — never by writing the JSON5 file, which
  would destroy comments and bake `${VAR}` substitutions into literals. Secrets stay
  with the gateway, and never touching its `.env`
- ▢ **Carriers become channels, and AgentOS becomes the hub** — today a message arriving
  at a gateway is answered by that gateway's own agent, which is why every carried channel is
  stamped `direction: out`. Pointing a gateway's agent endpoint at AgentOS makes the
  conversation land *here*, with this memory, this policy and this ledger. That is the
  step that turns the gateways into transport and AgentOS into the permission and
  audit hub in front of them — and it is opt-in, because it changes who answers

### F. Everywhere — surfaces
- Web desktop, desktop app, Telegram, CLI, TUI
- ▢ WhatsApp / Discord / Slack bridges (same conversation + memory model as Telegram)
- ▢ Mobile PWA of the desktop (the OS in your pocket, approvals as push notifications)
- ▢ **Voice as a provider layer**, mirroring the LLM provider design: pluggable **TTS**
  (ElevenLabs, OpenAI, local Piper/Kokoro) and pluggable **realtime STT** (local Whisper,
  Deepgram, OpenAI Realtime) behind one interface —

  ```jsonc
  "voice": {
    "tts":  {"provider": "elevenlabs", "api_key": "", "voice_id": "", "model": ""},
    "stt":  {"provider": "whisper-local", "model": "base", "realtime": true},
    "wake_word": "aria"
  }
  ```
  Per-subagent voices later (the Research agent literally sounds different). Streaming both
  ways: mic → realtime STT → agent → sentence-streamed TTS, barge-in supported. Local
  providers keep the privacy story intact; cloud ones are opt-in like any other provider

### G. The ecosystem — store & sharing  *(the network-effect engine)*
- Store templates, skill install from git/raw URL, themes
- ▢ **One registry for everything shareable**: apps, skills, themes, souls, automations, app
  packs — published as signed `.aos` bundles with permission manifests, indexed in a public
  git repo (zero-infra, PR-reviewed like Homebrew)
- ▢ **Publish from inside the OS**: right-click an app → "Share to store" → the agent writes
  the manifest, strips secrets, opens the PR
- ▢ Agents browse the store too: "you asked about meal planning — there's a pack for that,
  install it?"
- ▢ Soul market: personalities/personas as installable identity files

### H. Interface quality — a design system for the OS
*The built-in apps grew tool-by-tool and it shows: inconsistent layouts, cramped forms, raw
lists, no empty states. For a product whose pitch is "you can SEE your agent," the apps must
look like one OS, not twenty utilities.*
- ▢ **OS UI kit** — one small component layer every app renders through: page header,
  toolbar, list row, card, stat tile, form row, empty state, confirm dialog (kill
  `prompt()`/`confirm()`), toast, tab bar. Defined once as CSS classes + tiny JS helpers,
  themable via the existing CSS-variable system
- ▢ **Density & hierarchy pass** — consistent spacing scale, type scale, and icon language
  across all built-in apps; every list gets search/sort when it can grow; every destructive
  action gets a proper confirm
- ▢ **Empty states that teach** — each app's zero-state explains what fills it and offers the
  one-click action ("Ask the agent to…")
- ▢ **App-by-app polish order**: Chat (tool cards, approvals) → Settings → Memory/Profile →
  Store → Scheduler/Automations → the rest
- ▢ The UI kit ships to **user-built apps too**: `create_app` system prompt teaches the kit's
  classes, so agent-built apps automatically match the OS look
- ▢ Later: replace the monolithic `index.html` (180 KB) with per-app modules + the kit as a
  shared asset, enabling app-level hot reload

### I. The self-evolving OS
- `develop_agentos` (self-modification) + auto-snapshot + syntax check
- ▢ **Weekly self-improvement job**: agent reviews its own error logs and failed turns,
  proposes patches, applies them behind a snapshot, writes a changelog entry
- ▢ "What's new in your OS" app — the agent narrates its own release notes
- *An OS that upgrades itself while you sleep is a story chat-first products cannot tell —
  snapshots are what make it safe to tell.*

---

## Suggested sequencing

| Horizon | Ship |
|---|---|
| **Now** *(done)* | Memory v2: two-tier + auto-learn + semantic recall + rollup + supersede + KG dedup + Profile · **fabric F0**: subagents + visual workflows + control/data-plane split + heartbeats + observability + heterogeneous models ([design/subagents.md](design/subagents.md)) · **spaces foundation** (pillar J): spaces + scoped KG + timeline + MCP media bridge + asset store + Gallery + the access ledger |
| **Next — one at a time** | **J1 creator suite** (ffmpeg component + storyboard + Media MCP category + publish via MCP) · **J2 multi-agent for an operator** (async delegate, run registry, budgets, scheduler→subagent, handoff, org chart in GUI *and* TUI) · **J3 approval queue** (durable, answerable in the morning) · **J4 gateway hub** (`openclaw.py` + one `Gateway` interface + reconciled config) · **J5 carriers as channels** (inbound handoff into AgentOS — opt-in, it changes who answers) |
| **Then (2–6 wks)** | Automations app with event triggers · morning briefing · **UI kit + density pass (Chat, Settings, Memory first)** · **fabric F1: task-envelope wire protocol + mTLS PKI + worker mode** · secrets vault · privacy ledger · registry v0 (git index + signed bundles + publish flow) |
| **Later** | Fabric F2–F3 (docker workers → remote nodes) · **voice provider layer (ElevenLabs/OpenAI/local TTS + realtime STT)** · mobile PWA · app gardener · self-improvement loop · desktop modes · portable brain · per-app UI modules |

**North-star metrics** — depth over chats: apps + automations per active user; % of turns
*initiated by the OS* (proactivity); % of sessions where injected memory changed the answer.

---

## The moat, restated

Chat-first agents compete on model quality and skill count — both commoditize. AgentOS
competes on **accumulation**: every conversation leaves behind memory, graph, apps, and
automations that make the next one better. The desktop makes that accumulation *visible*,
the trust stack makes it *safe*, and the store makes it *shared*. That's the ecosystem play.


##### otherthings - pc 
 Plus the app studio should be able to use the MCPs as well for the connection to get more information that
  permission should be taken in the app and installed as a manifest for the appllication and it can be added to
  pre-requsite if its install on the third party os to install that as well (Distribution made easy). Once the
  permissionsa re give it can be revoked as well by the user too. This is important to be in control. The Apps
  permission should flow through the policy framework. The policy framework has to be made more robust to support such
  service mesh permissions. Permission to Interact, Permission between apps, Permissions between Agents, Permissions
  between Services etc. Permissions to use the skills, Permissions to use the MCP, Permissions to use the LLMs. All
  should be defined in the manifest of the Permission framework. That is single source of gate of the control plane.
  Also the subagents should be able to be use this framework for the controls etc. Policy is most important for things
  to work.