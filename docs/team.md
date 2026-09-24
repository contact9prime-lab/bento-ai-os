# The team: agents on different AI providers, talking to each other

Your agent is not alone. Every specialist in **Missions → Build → Agents** (the researcher,
the validator, the writer, and any you or your agent make) is its own agent with its own
character, its own tools and **its own brain**. This page covers two things: choosing which AI
provider each one answers on, and getting them to talk a question through with each other.

![A huddle in Chat: the researcher on OpenRouter, the validator on OpenAI and the writer on a custom local server answering each other by name](screenshots/team-huddle-chat.png)

## Each agent on its own provider

Any agent can be pinned to a model on any provider this machine has: Anthropic, OpenAI, Google
Gemini, OpenRouter, a local Ollama model, or a custom OpenAI-compatible server. A researcher on a
free local model, a validator on Claude and a writer on GPT is a normal setup: the cheap agent
does the reading, and the expensive one gets the judgement calls.

- **Settings → AI providers → Team** lists every agent with a model picker. A change applies
  immediately.
- **Missions → Build → Agents** shows each agent's provider on its card, and so does the Crew
  stage. Under each figure is the provider it answers on, and while it works the light above its
  head becomes a tag naming the provider.
- **Ask your agent**, e.g. "put the validator on Claude". Its `set_agent_brain` tool can only
  choose models on providers that exist here, and it asks first, because the move changes who is
  billed.
- **From a terminal**, `bento team` lists everyone, `bento team set writer openai/gpt-4o` pins
  one, and `bento team own on|off` is the switch below. It works with the server down.

![Settings → AI providers → Team: the switch, then one row per agent with its face, a model picker and the provider it is answering on now](screenshots/team-settings.png)

**The badge always shows what is actually answering, not what the agent was pinned to.** Those
can differ. If an agent is pinned to a provider that is switched off, or has no key yet, the pin
is kept, the agent uses this machine's brain until the provider is on, and the row says so in
words. The **Agents answer on their own providers** switch turns all of this off (one bill, one
provider). Every agent then uses the brain chosen at the top of the page.

This holds when your agent runs on another installed agent too. With Claude Code as the
machine's brain, a specialist pinned to OpenAI still answers on OpenAI, through AgentOS's own
loop and permission gate. Unpinned specialists run where the machine's brain runs.

![The roster: each agent's card shows the provider and model it answers on](screenshots/team-roster.png)

## Huddles: agents talking to each other

A **huddle** is two to four agents talking a question through in turns. Each one reads what the
others said, answers them by name, and speaks on its own model. That is how an OpenAI agent and a
Claude agent can disagree with each other, and how you can get a second or third opinion.

Start one from any chat surface (the desktop, the TUI) by naming two or more agents at the
start of a message:

```
@researcher @validator @writer should we price the new plan per seat?
```

Or ask your agent to do it ("get the researcher and the validator to argue this out"). It has a
`huddle` tool, summarises the conversation for you afterwards, and can create a specialist first
if nobody on the team fits (`create_subagent`). The new agent gets its own character and walks
onto the Crew stage.

What you see:

- **In Chat**, each turn arrives as it lands, with the speaker's face, name and the provider it
  answered on. A reloaded conversation shows the same card.
- **On the Crew stage**, the one talking lights up with the start of what it said over its head.
  One speaker at a time, the way a conversation goes.
- **In the TUI**, one line per turn: `@validator (OpenAI)  Two of those pages are a year old.`

![The Crew stage during a huddle: provider tags over the working agents, and the researcher's words over its head](screenshots/team-huddle-stage.png)

### What keeps it honest

- **Agents never call each other.** A specialist may not start another agent (that is what keeps
  the tree of agents two deep), and a huddle does not need it to. AgentOS moderates: every turn
  is an ordinary run of that agent, with the transcript so far in its task. Each turn appears
  in Observability, gets its own budget and model, and every tool call passes the same gate and
  lands in the same ledger as any other.
- **It is its own permission.** Convening a huddle is the `agent.huddle` action, apart from
  "may delegate to the researcher". Below full autonomy your agent asks first. The approval card
  names who is in the room and what each one runs on, because a huddle costs several models at
  once. Only your own agent can convene one: specialists, flows, apps and peers are refused.
  Typing the names yourself is your consent, the same as addressing one agent directly.
- **It is bounded.** At most four agents, three rounds and about 120 words a turn. A round in
  which everybody passes ends the huddle early.

## Agents messaging each other: the matrix, and swarm

A huddle is you (or your agent) putting agents in a room. A **message** is one specialist
deciding, mid-task, to ask another: the researcher checking a figure with the validator before
it reports back. Each specialist has an `ask_agent` tool. The colleague answers as itself, on
its own model and with its own permissions, and the answer comes back to the one who asked.

![A researcher on OpenRouter asks the validator on OpenAI, and uses the answer](screenshots/team-message-chat.png)

**Who may ask whom is a permission matrix.** Every pair of agents is a cell: rows ask, columns
answer. You set it in **Settings → AI providers → Team → Who may ask whom** (tap a cell to cycle
*ask → allow → block*), with `bento team allow|block|ask ASKER ANSWERER`, or by answering the
card the first time a pair talks:

![The approval card: researcher wants to ask validator; Allow, Deny, or Allow & remember](screenshots/team-message-approval.png)

**Allow & remember** fills that cell, so the matrix builds itself from your answers. Cells are
ordinary permissions, so the **Permissions** app lists and revokes the same rows.

![The matrix in Settings: four agents, one allowed pair and one blocked pair](screenshots/team-matrix.png)

**The mode switch** (Settings, or `bento team talk`) has three settings:

| | An empty cell | A cell you allowed | A cell you blocked |
|---|---|---|---|
| **Ask me** (the default) | asks you; nobody there = no | talks | refused |
| **Swarm** | talks, without asking | talks | refused |
| **Off** | refused | refused | refused |

Swarm is the matrix switched wide open. It is not a second system: every limit below still
holds, every message is still a run and a ledger row, and a cell you blocked stays blocked.

### The shape of a conversation, and the limits you set

- **Asking back is a clarification, not a loop.** The validator, asked by the researcher, may
  ask the researcher back ("which plan, Pro or Team?"). The question goes *up* to the
  researcher that asked, which still holds everything it knew, and it asks again with the
  answer. No fresh copy of the researcher is started, because a copy would know nothing. How
  many times a colleague may ask back is a limit (default 2, 0 turns it off).
- **A real cycle is refused.** In A → B → C, if C asks A, A is not C's asker; it is waiting on B.
  AgentOS records who is in the conversation, and the model cannot edit that record.
- **Limits are settings.** Settings → AI providers → Team → Limits, or `bento team limits
  hops=3 budget=20`:

| Limit | Default | Range | What it bounds |
|---|---|---|---|
| `hops` | 2 | 1–6 | how far one question may travel (A → B → C is 2) |
| `budget` | 6 | 1–100 | questions one task may send in total |
| `clarify` | 2 | 0–5 | times a colleague may ask its asker back |
| `huddle_agents` | 4 | 2–8 | agents in one huddle |
| `huddle_rounds` | 3 | 1–6 | rounds in one huddle |

  The budget is **per task**, so several swarms running at once each get their own. The
  ceilings are fixed because every one of these multiplies model calls, and a typo of 600
  should not become a bill. Every change to a limit is an audit row.

### What holds in every mode

- **Untrusted content stays marked.** If the validator read a web page to answer, its reply
  arrives marked, and the researcher's turn is held to the same care as if it had read the page
  itself. The asker's own untrusted content travels with the question.
- **In a mission, when the mission says so.** A mission's editor has **Specialists may
  consult each other**. Turned on, every agent on its roster may ask every other one *inside
  that mission*, and its consent screen says so before you enable it. Turned off (the
  default), they work through the orchestrator only. The two worlds don't leak into each
  other: a cell you allowed at the desk does not open a mission, swarm does not reach into
  one, and a mission's consent does not open the desk.
- **Only specialists.** Apps, a flow's master and peers cannot message an agent. Your own agent
  has `delegate` and `huddle` instead.

### Does full autonomy open the matrix? No.

Autonomy (*balanced*, *full*) is how much an agent may **do** without asking: run a command,
write a file. Who may **recruit whom** is a different question, and only the matrix answers it.
An empty cell asks at every autonomy level, including full. On a run nobody is watching (a
schedule, a webhook), an empty cell is refused rather than answered on nobody's behalf. Only
**Swarm** opens empty cells. A huddle is different: your own agent convening one follows
autonomy, because you asked your agent, not a specialist.

### Everything is in the audit ledger

The hash-chained audit ledger (the Audit app, `audit_verify`) records:

- **every decision**: each message asked, allowed, refused or blocked (`agent.message`), each
  huddle (`agent.huddle`), each model pin by the agent (`agent.write`);
- **every change to a permission, from any door**: a cell set in Settings or with the CLI,
  "Allow & remember", the Permissions app, a flow's own permissions, a revoke, and a deleted app
  taking its permissions with it (`grant.write`, `grant.change`, `grant.revoke`). A change you
  made is recorded as yours; one the system made (a flow reconciling its permissions) is
  recorded as the system's, with the flow named;
- **every team switch**: the talk mode, the own-providers switch and a model pinned from
  Settings or the CLI (`team.write`, `agent.write`).

## Where it lives

| | |
|---|---|
| Which brain an agent answers on | `fabric.agent_brain` — one answer for the run, the badge, Settings and the CLI |
| Pinning a model | `fabric.set_agent_model` — `PUT /api/subagents/{name}/brain`, `set_agent_brain`, `bento team set` |
| The switch | `team.own_brains` in config (a machine setting: it decides spend) |
| A huddle | `ControlPlane.huddle` — the `huddle` tool, a `@a @b …` chat message, `agent_say` events |
| A message | `ask_agent` → `agent.message` (the gate) → `ControlPlane.message` (loops, hops, budget, taint) — `agent_msg` events |
| The matrix | `fabric.matrix` / `fabric.set_cell` (grant rows) — `GET/PUT /api/team/matrix`, `bento team matrix/allow/block/ask` |
| The mode | `team.talk` = `matrix` \| `swarm` \| `off` — `policy.team_talk`, Settings, `bento team talk` |
| The limits | `team.limits` — `fabric.LIMITS` / `team_limits` / `set_limits`, `GET /api/team/limits`, `bento team limits` |
| In a mission | `permissions.talk` — `flows.declared_grants` writes the roster's pairs; the gate counts only that mission's rows |
| Tests | `tests/test_team.py`, `tests/test_agent_messages.py` |
