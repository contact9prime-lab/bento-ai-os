# Missions — what this machine does for you every day

A mission is a standing job you give the machine once: *write my standup every
morning*, *watch my competitors' pricing pages*, *draft the client report every
Friday*. It runs without you, inside exactly the permissions it printed when you
set it up, and the Missions app shows what it did.

Under the hood **a mission is a flow** (see `docs/design/flows.md`). The Missions
catalogue (`agentos/jobs.py`) is a list of recipes; a recipe plus two or three
answers becomes a flow definition and goes through the same save, the same
permission gate and the same scheduler as a flow you wrote by hand. There is no
mission engine, and there is nothing a mission can do that a flow cannot.

![The Missions app for a coder: the value line, one installed mission with its
last outcome, the persona chips, and the coder's five missions first](design/ux-review/after/missions-coder.jpg)

## Who is asking

The first question on every mission surface is who you are:

| Persona | Missions written for it |
|---|---|
| **Founder** | Triage my inbox · Brief me before today's meetings · Tell me who I owe a reply to · Watch my competitors · Tell me when someone is in the news · Draft my investor update · Brief me every morning |
| **Coder** | Triage my inbox · Write my standup · Review what I pushed today · Keep my tests green · Tell me when a dependency ships |
| **Consultant** | Triage my inbox · Brief me before today's meetings · Tell me who I owe a reply to · Keep up with a client's folder · Draft the weekly client report · Tell me when someone is in the news |
| **Just me** | Triage my inbox · Show me the week ahead · Watch a folder · Tell me when a page changes · Tell me what I worked on this week |

The persona is a **filter over one catalogue, never a subset**: yours come first,
then everybody's, then the rest. A consultant who also writes code can reach the
coder's missions. The choice is saved per person (`persona` is a user key) and
also decides the three suggestion chips on the home scene.

## What a mission may do

Every mission is honest about its reach, and prints it before it exists:

- **A folder mission reads that folder and nothing above it.** `Write my
  standup` on `~/code` is granted `fs.read` on `~/code/*`. The coder missions
  never get `fs.write`: they run git and the tests, and they report — they do
  not commit, push or edit.
- **A web mission reaches exactly the addresses it was given.** `Watch my
  competitors` with three pages is granted those three URLs. `Tell me when
  someone is in the news` is granted the news feed and nothing else. Only
  `Brief me every morning` is granted the open web, and the card says so.
- **A mission that remembers runs with a memory it may write.** The first
  page-watch recipe granted `remember` under a read-only memory scope, so every
  write was refused and "compare with last time" compared against nothing.
  `tests/test_jobs.py` now checks that a recipe's specialists can actually call
  the tools the flow grants them.

![The consent block: runs every day at 09:00, reads /home/user/* and nothing else,
delivers to Reports, 11 permissions](design/ux-review/after/missions-consent.jpg)

## What it did

The app is a value surface, not a schedule. For each mission: the last run's
status and when, the first sentence of what it said, this week's runs and
tokens, and how many permissions it holds. The header sums the rows. Tokens are
counted here; what they cost is priced per model in Usage, so there is one
number for that and it is there.

A failed run says so in the row, in the words the run recorded — `error ·
ConnectError` — not softened.

## Can it run here?

A mission's consent block is a promise about every step, so a mission only runs
where every step passes the permission gate. Two ways do:

- **The built-in loop on a provider model** (Ollama, Anthropic, OpenAI…), which
  is what the gate was written for.
- **Claude Code through the run bridge.** When your brain is Claude Code, the
  mission's master and specialists run on it — started with its own tools
  switched off and exactly one MCP server allowed: this OS's tools, bound to
  that one run. Every call Claude Code makes is one of ours, checked against the
  mission's permissions and written to the ledger; the model is Claude Code's,
  the hands are this OS's. Nothing to configure: the Missions app says
  "Missions run on Claude Code" when it applies.

An executor that cannot take this OS's tools over MCP (Hermes, OpenClaw today)
can answer chats but not run a mission, and the Missions app, the wizard and
`bento job list` say so before the Run button, with the fix.

## Schedules

Daily at a time, weekly on a day at a time, every N minutes, or when a folder
changes. `weekly` is new with this catalogue and is a flow trigger like any
other: `{"kind":"cron","config":{"type":"weekly","day":"friday","at":"16:00"}}`.

## From a terminal

The same catalogue, the same install, no wizard — which is where a standing
mission earns its keep:

```
bento job persona coder                      # open on a coder's missions from now on
bento job recipes                            # the catalogue, yours first
bento job add standup --folder ~/code --at 09:00
bento job add competitor-watch --urls 'https://acme.com/pricing,https://acme.com/changelog'
bento job add client-report --client Acme --folder ~/Clients/Acme --day friday --at 15:00
bento job list                               # what runs, what it last said, what it holds
bento job run standup-code                   # now, while you watch
```

## Missions that read your mail and calendar

Four missions need an account (`docs/accounts.md`): triage my inbox, brief me
before today's meetings, show me the week ahead, tell me who I owe a reply to.
Until the account is set up and its sign-in has succeeded, the card is greyed
with the sentence that would fix it and the save refuses — a mission that can
never run must not look armed. A mission that would only *use* an account
(meeting prep with mail) runs without it and says so in its own instructions.

## Build: the editor behind every mission

A mission is a flow with a recipe behind it, and the *Build* tab of the Missions app
is the editor for flows: the flows themselves, the specialist agents on their rosters,
and every run. It is where a mission a recipe made is changed, and where a flow is
written from scratch — by hand, or drafted from a sentence. A draft names the tools
and agents it would use and, when the request's own words match a first-party MCP
server in the catalogue, offers it as a part with a Connect button. Offered, never
granted: the draft's permissions never gain a server you did not add yourself.

## How a mission delivers

Not as a message. Every recipe ends with the same instruction: put each
finding into the person's **Brief** with `brief_item` — something that needs
you, a decision with its choices, an FYI, or a thing done for you — then save
the long form as a report. The Brief is one living page a day with hands on
every item, and a decision made there comes back to the agent as its next
turn. It is its own guide: [brief.md](brief.md).

## What is deliberately not here

No mission sends mail. `mail_send` exists as a tool for the person's own agent,
always asks, and is never granted by a recipe: a drafted reply is a draft on
the Brief item, and *Send draft…* sends it as you, through the gate that asks.
