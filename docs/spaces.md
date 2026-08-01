# Spaces, the Gallery, the Timeline and the Audit ledger

Four things that arrived together, because each was blocked on the others.

---

## Spaces — the things you are working on

A **space** is a launch, a client, a channel, a side project. Conversations, memory,
knowledge-graph facts, assets, agent runs, scheduled jobs and audit entries each belong to
one — or to the **global scope**, which the UI calls *Everywhere*.

The rule, and it is the same rule in every read path in the OS:

> **A space sees its own rows AND the global ones.**

Not "only its own" — you would lose your own name the moment you switched to a project.
Not "everything" — that is what it did before, and it is why three clients' deadlines
competed to answer one question. In SQL it is `space_id IN ('', :active)`, written once in
`memory.Store._space_clause`.

### Where the active space comes from

Two answers, deliberately:

- **The conversation is authoritative for a turn.** A conversation started inside a space
  stays in it forever, including when you reopen it next month from your phone. Scrollback
  that changes meaning depending on what you clicked last would be worse than no spaces.
- **The surface default decides where the *next* new conversation starts**, and it is
  per-surface. One global "current space" would have the desktop, the TUI and Telegram
  fighting over one value — you would switch to a client at your desk and silently move
  what your phone does next.

API callers pass `X-AgentOS-Space` (or `?space=`) and get neither default: a script has no
"current" anything.

### What the agent does with it

After every turn the memory pass classifies what it learned, with one test:

> If the fact would still be true after this project ends, it is a **user memory** (global).
> If it stops being true when the project does, it is a **space memory**.

"Piyush works at Accacia" is global. "This project deploys on Fridays" is not. Session
rollup follows the same logic: an idle conversation's context distils into its *space*, not
into your global memory, because promoting it further is a judgement worth a human.

The agent can override explicitly — `remember(..., everywhere=true)` and
`kg_add(..., everywhere=true)` — and that choice is visible to the permission gate, which
is why it is a flag rather than a hidden id.

### The knowledge graph is scoped on its edges

An **entity** is the same entity everywhere: the person "Ana" does not fork because you
switched project. An **assertion** is what belongs to a project: "Ana reviews the launch
copy" is true here and nowhere else. So `kg_edges` carries `space_id` and `kg_nodes` does
not — which also means the migration never had to rebuild the `UNIQUE(name)` index.

### Removing a space

Never silently. `DELETE /api/spaces/{id}` requires `?contents=`:

| disposition | what happens |
|---|---|
| `archive` *(default)* | nothing moves or is deleted; the space stops being offered |
| `global` | its memories, facts and assets become true everywhere; the space goes |
| `delete` | everything scoped to it is removed, plus entities nothing points at any more |

The UI shows what is actually in the space (`GET /api/spaces/{id}/stats`) before asking.

---

## The Gallery — everything the agent made or was handed

Until now the only picture AgentOS could keep was a wallpaper, and **anything a media MCP
returned was thrown away**: `MCPManager.call()` rendered every non-text content block as
the literal string `[image]`, so Higgsfield, Canva, ElevenLabs — anything that draws,
speaks or renders — reported success and handed back nothing.

Now non-text content is stored. Images, video, audio and blobs become **assets** with
provenance: which server and tool made them, from which prompt, in which conversation and
space.

- **Content-addressed** under `~/.agentos/assets` — the same bytes twice cost one row and
  one file, so re-running a generation is free. The path is never caller-supplied: an asset
  is addressed by id, so there is no path to traverse.
- **Images are attached for vision** using the shape the agent already understood.
  **Video and audio are not** — no provider path can carry them, and attaching them would
  be a silent no-op dressed up as sight. They travel as asset ids the agent can act on.
- **No new dependencies.** Dimensions, durations and thumbnails come from ffmpeg *if you
  chose to install it*. Without it those fields stay zero, thumbnails are absent, and the
  UI says which component would fix it — see below.
- **Uploads stream.** `PUT /api/assets/raw` takes a raw body, so a 200 MB video is never
  base64-inflated into a JSON string. Small pasted images still go through
  `POST /api/assets` as a data URL.

### ffmpeg is offered, never shipped

The distro `ffmpeg` binary is GPL. AgentOS ships permissively, so it lives in
`agentos/components.py` as an offer with its licence in view, and never as a dependency.
Without it AgentOS still receives, keeps and plays media a service generated — it just
cannot measure, thumbnail or cut it locally. `GET /api/media/capability` returns that
sentence, and the Gallery renders it rather than greying a control out in silence.

---

## The Timeline

A materialised index of **milestones** — runs that finished, assets produced, memory
learned, apps changed — not a second copy of the message log. A timeline containing every
message *is* the message list, and there is already one of those.

It is a table rather than a five-way UNION view because the sources share no key and none
of them were indexed for this question.

---

## The Audit ledger

`logs` is the operator's diary: free text, one `kind` column, metadata as a JSON blob you
have to grep. Fine for "what happened", useless for "who was allowed to do what, arriving
on which way in, and under which rule".

Every decision the policy engine makes now writes one structured row — and because every
capability call in the OS funnels through `PDP.decide()`, that is genuinely every one:
tool calls, MCP calls, file writes, model choices, memory writes.

| column | what it records |
|---|---|
| `principal_kind` / `principal_id` | user, app, subagent, workflow, system |
| `surface` | the IO gate: gui, tui, telegram, api, task |
| `action` / `resource` | the same vocabulary grants are written in |
| `effect` / `rule` | allow, deny, ask — and which rule decided (grant id, `builtin-deny`, `io-gate`, `channel-read-only`, `default`) |
| `outcome` / `detail` / `duration_ms` | stamped when the call returns, so a permission that was granted and then failed does not look like one that worked |
| `space_id` / `conversation_id` / `run_id` | where it happened |

Because the vocabulary matches, a filter in the Audit app and a grant in the Permissions
app describe the same thing. `media.*` and `space.*` are first-class actions, and memory
and KG resources are space-qualified (`memory:user@<space>`, `kg:<space>`), so *"this
subagent may write memory in the marketing space and nowhere else"* is one grant.

The ledger never blocks a decision: if the write fails, the decision still stands and the
failure goes to the operator log.

---

## The three faces

| | |
|---|---|
| **GUI** | A space chip in the menu bar (only once you have a space — until then *Everywhere* is the only scope and the control would be decoration), the Spaces, Timeline, Gallery and Audit apps. The Gallery detail pane opts out of glass explicitly: a translucent surface above a playing video makes the compositor re-blur it *every frame*. |
| **TUI** | `agentos space` / `space <name>` / `space --none` / `space --new`, `agentos timeline --since 7d`, `agentos assets [list\|path\|open\|rm]`, `agentos audit --since 24h --effect deny`, plus Spaces and Audit tabs. A chronological list and an access log are *native* to a terminal — this is where the TUI is the better face, and a headless server is exactly where you audit what ran overnight. |
| **SUI** | Identical to GUI. The space chip is inline inside the existing menu bar band and height-neutral on purpose: the band is a layer-shell exclusive zone whose height the page measures and reports to the host, so a chip that grew the bar would silently change the reserved strut. The Gallery cannot show a genuinely fullscreen video above native windows — there is no shell window in SUI — so fullscreen means maximise-within-page. |

The CLI verbs talk to the database directly rather than to the HTTP API, so they work when
the server is not running — which is when you most want to read an audit log.
