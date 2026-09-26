# The TUI — AgentOS in a terminal

`agentos tui` runs a full-screen terminal UI (Textual) — the same OS, over SSH or on a
machine without a browser. If Textual isn't installed it falls back to a plain REPL
(`clitui`) with the same chat + approval flow.

```bash
uv run agentos tui        # or just: agentos tui (installed package)
```

The TUI talks to the same server and the same WebSocket event stream as the browser desktop,
so conversations, memory, approvals, and running turns are shared across every surface — a
turn you start in the TUI streams into the browser too, and vice versa.

## Signing in

On a machine with accounts (see [Users](users.md)) the TUI starts with a sign-in: your
name and password, the same ones as the desktop and the phone. The server refuses every
call from anybody who has not signed in, the terminal included, so until then there is
nothing to show. After signing in, the title bar names **your** agent and its brain, not
the machine's, and every tab reads your own home. **Ctrl+O** signs out and asks again.
The key only appears on a machine with accounts, because with none there is nobody to
sign out as. The session lasts until you quit; nothing is saved to disk.

The plain REPL fallback asks the same two questions before its first prompt.

## Tabs

| Tab | What it does |
|---|---|
| **Chat** | Talk to the agent — replies stream live (line by line), tool calls and failures shown inline, approval prompts pop as modals |
| **System** | Live CPU/RAM bars and processes |
| **Models** | Installed Ollama models, GPU state, switch the active model |
| **Apps** | Launch native desktop applications |
| **Tasks** | Scheduled jobs and their last results |
| **Team** | Subagents & workflow observability |
| **Logs** | The system log, live |
| **Docs** | This manual, rendered in the terminal |
| **Office** (`o`) | The office plan and who is at work right now (the same roll call as the phone's picture), your linked teams, **Snap to my phone**, and a *Describe it* box that redesigns it |
| **Config** | Providers, autonomy, agent name — and **Start over**: *Walk me through it* (every setup step again, nothing deleted) and *Factory reset…* (type `reset everything` to confirm) |

## Finding your way around the CLI

`bento --help` shows **ten commands** — the ones a machine that was installed ten
minutes ago needs, with `setup` first. It is not the whole list, and it says so:

```bash
bento help            # the same short page
bento help --all      # every command, in two groups
bento help remote     # one command in full
```

Nothing is hidden in the sense of removed. Every verb `--all` lists is a real command
with its own `--help`; the short page exists because thirty-nine of them in one flat
list reads as "you have to understand all of this first", when on a fresh machine the
answer is one word long.

## Starting over

```bash
bento setup --again     # every step offered again, skipped ones included — nothing is deleted
bento reset             # factory reset: wipes everything on this machine, then setup starts again
```

`bento reset` is the desktop's Settings → System → Danger zone → Factory reset. It
removes memory, conversations, apps, specialists, flows, the soul and every setting, and
on a machine with accounts every account and its home. It refuses in three cases, and
says which:

- **The server is running.** A running server keeps the settings in memory and would
  write them back over the reset. Stop it first (`bento service stop`), or use the
  desktop's button, which resets the running server itself.
- **The phrase is not typed.** You type `reset everything`. There is no `--yes`, on
  purpose, and with no terminal to type into (a pipe, a script) it refuses.
- **You are not an admin.** On a machine with accounts it asks for an admin's name and
  password first.

## Setting the machine up from a terminal

`bento setup` walks the **same nine-step arc** as the desktop wizard, from the same
catalogue and the same probe. Set up half of it in a browser and finish it over SSH; the
right steps are already ticked, because a step is ticked when the machine has the thing —
not when a page remembers a click.

```
$ bento setup

▲ Set up Bento — 4 of 9 done

  ✓  1  Name your agent                   Bento
  ✓  2  Give it a brain                   ollama/qwen2.5
  ✓  3  Watch it answer                   2 conversations
  ✓  4  Build a specialist                researcher-plus
  ○  5  Give the specialist a mission
  ○  6  Let it run without you            needs flow
  –  7  Reach it from your phone
  ○  8  Make it yours
  ○  9  Add the people who will use it

  next: 5. Give the specialist a mission
  a number to do a step · s<n> to skip one · q to finish
  Step [5]:
```

Every step in the catalogue works here, including the ones that create things — the agent,
the flow, the job and the account are made by the same functions the browser calls. The one
honest gap is stated rather than hidden: a terminal can pick a theme but cannot show you a
wallpaper, so that step sets what it can and points at the app that does the rest.

`bento setup` is also the way in on a machine with no screen at all, which is where a
standing job earns its keep and where there has never been a wizard.

## Accounts from a terminal

```bash
bento user                          # who can use this machine
bento user add ada --role admin     # prompts for a password
bento user role bob --role admin
bento user passwd bob
bento user remove bob               # their home is KEPT
bento user remove bob --wipe        # and this destroys it — a separate decision
```

Once a machine has accounts, every verb that reads data has to know whose:

```bash
bento --user ada job list
AGENTOS_USER=ada bento flow list    # or say it once, for a cron line or a unit
```

It refuses rather than guessing. A `bento job add` that silently landed in the wrong
person's database would be discovered weeks later by whoever did not get their briefing.
The same username and password is the sign-in from a phone — see [Users](users.md).

## Characters in a terminal

The pixel-art characters the desktop shows beside messages are drawn here too, in
half blocks from the same pixel grid — so the researcher on an SSH session is the
same person as on the desktop and the phone:

```bash
bento avatar                                   # everybody's face, side by side
bento avatar show writer                       # one, full height
bento avatar set me hair=blue style=bob        # the same choices as the editor
bento avatar reroll researcher                 # a new look, same shirt colour
bento avatar design agent "a calm lead with a grey bun, in a violet blazer"   # the machine's model designs it
```

It reads and writes the rows directly, so it works with the server down. Without
colour (a pipe, `NO_COLOR`) it describes each character in words instead.

## The team from a terminal

```bash
bento team                                     # each agent and the provider it answers on
bento team set validator anthropic/claude-sonnet-5
bento team own off                             # every agent on this machine's brain
bento team matrix                              # who may ask whom
bento team allow researcher validator          # one cell (also: block, ask)
bento team talk swarm                          # matrix | swarm | off
bento team limits hops=3 budget=20             # the limits, within their ranges
```

Linked teams — another Bento, or another account here — have their own verb:

```bash
bento link                                     # this machine's certificate and every link
bento link request office.local                # ask; shows six digits and waits for the answer
bento link request ada@office.local            # …addressed to Ada's account there
bento link requests                            # requests waiting here, with their digits
bento link approve 7a89ed8e                    # …check the digits match, then say yes (or deny)
bento link request account bob                 # another account here: Bob approves as himself
bento link listen on                           # let other machines ask (mTLS, port 8322)
bento link allow office analyst                # their agents may ask your analyst
bento link mine office on                      # yours may ask theirs without asking you
bento link let office analyst fs.write ~/shared/reports --days 30
                                               # their questions may have analyst write there, unasked
bento link standing office                     # what they may have your agents change · unlet ID
bento link missions office                     # their missions that use your agents, as recorded here
bento link stop office weekly-report           # refuse that mission's questions here · resume undoes it
bento link say office "Is the Q3 deck ready?"   # write to the people on that team
bento link chat office                         # the conversation (pulls anything waiting)
bento link remove office                       # ends it, and revokes its cells
bento link invite machine                      # headless: a one-time bento://link/… line
bento link join 'bento://link/…' office        # …redeemed on the other machine
```

In the TUI's chat, `@researcher @validator should we…` starts a huddle, and each turn prints as
one line with the speaker and its provider. See [the team](team.md).

## Notes

- Chat streams incrementally and shows model heartbeats ("waiting for the model — 20s…")
  while a local model loads or evaluates a long prompt, plus failed tool calls in red.
- Approvals raised anywhere (including Telegram or the browser) can be answered from the TUI.
- The TUI auto-starts the server if it isn't already running — and respects an existing one
  (the port-conflict guard means it never fights another instance).
