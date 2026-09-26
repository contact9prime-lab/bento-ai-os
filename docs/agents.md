# Agents: a brain, hands, permissions and skills

Every agent on this machine is built from the same four parts. Settings has one place for
each:

| Part | What it is | Where you set it |
|---|---|---|
| **Brain** | What the agent thinks with: a cloud model with a key, a model running locally, or another AI agent installed here (Claude Code, Hermes, OpenClaw) | **Settings → AI providers** |
| **Hands** | What it can reach: which tools, which folders (read-only or read-write), which web addresses and which MCP servers. This is an *executor*. | **Settings → Executors** |
| **Permissions** | What it is *allowed* to do with those hands, and how far it may go without asking | its card in **Settings → Agents**, and the Permissions app |
| **Skills** | Procedures it knows: which steps to follow, which tool to use for what | its card in **Settings → Agents** (Edit) |

There is always one **lead agent**, which you name (Aria by default). It is the agent you
talk to, and it hands work to the others: your **specialists**. Each specialist has its own
soul and its own brain, hands, permissions and skills. Specialists can ask each other
questions, talk a problem through in a huddle, and work with agents on a linked team (see
[team.md](team.md)), but only where a permission says they may.

**Everything is recorded.** Every step any agent takes, every refusal and every change to a
brain, hands or permission is a row in the ledger (Logs, or `bento audit`).

## AI providers: the brains

![Settings → AI providers: the lead agent's brain, then every provider with its key and models, and the AI agents installed on this machine](screenshots/settings-brains.png)

The first row is the lead agent's brain. Below it are all the brains this machine has:

- **Cloud providers**, each with its key: Anthropic, OpenAI, OpenRouter, Google (Gemini)
  and any OpenAI-compatible server.
- **Local models** through Ollama.
- **AI agents installed here**: Claude Code, Hermes and OpenClaw, each with its install
  offer and what it can do. Pick one as the lead agent's brain, or give it to a
  specialist.

A specialist can have its own brain: pick a model on its card in **Agents**. If that
provider is switched off or has no key, the agent uses the lead agent's brain, and the card
says why.

![The same page on a 390px phone](screenshots/settings-brains-phone.png)

## Executors: the hands

![Settings → Executors: the default, read-only and a custom "reports" executor, each saying what it reaches and which agents use it](screenshots/settings-hands.png)

An executor is a set of hands. It says what an agent **can reach**:

- **Tools**: every tool, or only the ones ticked, grouped as Files, Web, Shell & code, Git,
  Memory, Mail & calendar, Messages, Desktop and so on.
- **Folders**: each one read-only or read-write. `@workspace` means the workspace;
  *anywhere the machine allows* means no extra limit beyond the machine's own folder jail.
- **Web**: any address, none, or only the addresses you list (`https://api.github.com/*`).
- **MCP servers**: every server, none, or the ones you tick.

Two executors are built in:

- **default**: every tool, anywhere the machine allows, the web and every MCP server. It is
  what agents had before executors existed, so nothing changes until you narrow one.
- **read-only**: reading tools only, the workspace read-only, the web, no MCP servers.

You can change a built-in executor, but not delete it. Delete one of your own and its
agents go back to **default**, never to an executor that no longer exists.

**Reaching is not permission.** An executor is a ceiling, not a grant. The permission gate
checks it before anything else, and no permission reaches past it: a read-only agent that
has been granted "write files everywhere" still cannot write. Inside its hands, the agent
still needs its permissions to act. A refusal names the executor and what it did not reach
("analyst's hands do not reach this: /srv/x is outside this executor's folders").

**A shell is a tool, and the page says so.** A command line reaches whatever the machine's
folder jail allows, not only the executor's folders. The editor says this beside any
executor that includes a shell tool. Leave shell tools out to make the folder list a real
limit, or turn on the folder jail (**Executors → The machine's own limit**).

Folders are checked against the path a write would **really** land on: `~` expanded, a
relative path taken from the workspace, and `..` and symlinks resolved. A folder rule for
`~/reports` does not cover `~/reports/../.bashrc`.

![The same page on a 390px phone](screenshots/settings-hands-phone.png)

## Agents: who has what

![Settings → Agents: each specialist with its brain, hands, permissions, skills, who it may ask and its missions](screenshots/settings-agents.png)

The **Lead agent** group names your agent, sets its **look** and its hands; its brain is
chosen in AI providers. Below it, **Your agents** shows each specialist on one card:

- **Look**: its character, the same one in Chat, the Office and the Crew stage. **Change…**
  opens the editor, **✦ Describe it** opens it on the box where you say what you want in
  words. Tapping the face on the card does the same. (From a terminal: `bento avatar`.)
- **Brain**: what it answers on right now, and why when that is not its own pick.
- **Hands**: which executor it has. Changing it applies at once and is recorded.
- **Permissions**: its autonomy and what it has been allowed or refused, by kind (files,
  web, agents, …). "Inside missions" counts the permissions a mission gives it only while
  that mission runs. **Open** goes to the Permissions app.
- **Skills**, **who it may ask** (and who is blocked), its **missions**, and any linked
  team that may ask it.

**Edit** opens the agent editor (soul, tools, skills, autonomy). **＋ New agent** creates
one. **Working together** holds the team settings: each agent's own provider, whether agents
may message each other (ask me / swarm / off), the limits, who may ask whom, and linked
teams.

![The same page on a 390px phone](screenshots/settings-agents-phone.png)

### Your lead hands work to them, whatever its brain

Your lead is told who its specialists are: each one's name and the first sentence of its
soul, which is how you described the job. When you ask for one of those jobs ("build me a
tool" with a toolsmith on the roster), it hands the work over with `delegate` and reports
what they did, instead of doing it itself.

This holds when the lead's brain is Claude Code. A chat turn forwarded to Claude Code keeps
its own tools and also gets exactly two of this OS's: `delegate` and `huddle`, over the same
bridge missions use. Every hand-over passes this OS's permission check, asks you when a
built-in turn would, and is in the audit log. The same applies to a message sent from
Telegram or WhatsApp. A scheduled turn does not get it; a mission is how a schedule gets a
team.

Addressing someone directly always wins: `@toolsmith build a VCP scanner` goes to the
toolsmith, `@researcher @validator is this right?` starts a huddle, whatever the brain.
Before this, with Claude Code as the brain, even an `@toolsmith` message was answered by
Claude Code itself.

## The map

![The map: brains, teams and missions on the left; agents in the middle; their hands, then skills on the right, with a line for every relationship](screenshots/settings-agents-map.png)

At the bottom of **Agents**, the map draws every agent and everything it is connected to,
with one line per relationship:

- *thinks with* (its brain), *works with* (its hands) and *knows* (a skill);
- *may ask* / *may not ask* (the matrix), and *delegates* (the lead agent to each
  specialist);
- *mission roster* (a mission that puts it to work), and *linked team* (another team that
  may ask it, including their missions and standing permissions).

Tap an agent to see only its lines:

![The map with the analyst selected: its brain, its "reports" hands, and who may and may not ask it](screenshots/settings-agents-map-focus.png)

On a phone the map scrolls sideways instead of squeezing four columns into the screen:

![The map on a 390px phone, scrolling sideways](screenshots/settings-agents-map-phone.png)

The map, the cards and `bento agents` come from one computation (`agentos/agentmap.py`),
drawn from the same rows the permission gate checks. They cannot disagree about who
reaches what.

## From a terminal

```
bento agents                          # every agent: brain, hands, permissions, skills, company
bento agents map                      # the map as lines: "analyst ─works with→ reports"
bento agents hands analyst read-only  # give an agent hands (@agent is the lead agent)

bento hands                           # the executors, and what each reaches
bento hands show reports
bento hands set reports --tools read_file,write_file,save_report \
    --folder ~/reports:rw --folder @workspace:ro --web none --mcp ""
bento hands rm reports                # its agents go back to default
```

All of these work with the server down, and every write is recorded.

## Where it lives

| | |
|---|---|
| Executors (hands) | `agentos/hands.py` (profiles, the built-ins, `refusal()`, `assign`) · `executor_profiles` table · `subagents.profile` · `agent_profile` in config for the lead agent |
| The ceiling | `policy.PDP._decide` step 2a (rule `reach`), `PDP.reach_of`; `Agent._tools` hides what the hands cannot hold |
| The map | `agentos/agentmap.py` (`overview`, `graph`, `text`) |
| Routes | `GET /api/hands`, `PUT/DELETE /api/hands/{name}`, `GET /api/agents`, `GET /api/agents/graph`, `PUT /api/agents/{key}/hands` |
| Pages | Settings → AI providers / Executors / Agents (`11-settings.js`, `11e-hands.js`) |
| Tests | `tests/test_hands.py` |
