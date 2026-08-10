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
| **Config** | Providers, autonomy, agent name |

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

## Notes

- Chat streams incrementally and shows model heartbeats ("waiting for the model — 20s…")
  while a local model loads or evaluates a long prompt, plus failed tool calls in red.
- Approvals raised anywhere (including Telegram or the browser) can be answered from the TUI.
- The TUI auto-starts the server if it isn't already running — and respects an existing one
  (the port-conflict guard means it never fights another instance).
