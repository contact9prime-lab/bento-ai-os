# Ethics: should a step happen at all

Asked for in November 2026 after the OpenAI and Hugging Face incident, where an agent in a
security test reached another company's infrastructure:

> One of the things it doesn't do today is enforceability. The problem is not shooting rm -rf
> and then the user rejecting it. The problem is whether that should be executed, ethically.
> Ethics is the most important evaluator, and it has to be calculated by the system in the most
> deterministic way, so the AI doesn't circumvent it. The user may authorize rm -rf *, but the
> AI might say its ethics filter picked it up as a cautionary command. Or asking how to hack a
> third party site: the vision of the operator is skewed.

The gate (`policy.py`) answered one question: may this agent do it, and did somebody say yes?
That question has no answer for harm that lands on somebody who was never asked. A person could
approve it with a tap, and an agent at full autonomy needed nobody.

## The rule

**Only the party who would be hurt can consent.**

| Who is hurt | What happens | Can it be switched? |
|---|---|---|
| Someone else (a machine nobody here has shown is theirs) | Refused | No. Nobody's yes covers somebody else |
| Everyone on this machine (the system, a disk, a whole home) | Refused | No |
| Others who share a history (a force push) | Typed confirmation | No |
| You, when Bento can't read what would go (`rm -rf $(…)`) | Typed confirmation | No |
| You (over 200 files or 200 MB, or outside your workspace) | Typed confirmation | Yes, it's yours |

So the answer to "should ethics be something people enable or disable?" is: **partly.** The part
that protects you from yourself is yours to turn off. The part that protects other people has no
switch, because a switch would be you consenting on their behalf, which is exactly what this
layer exists to stop. And there's no setting an AI can reach, because a model that could switch
its own ethics off would be talked into it by the first page that asked.

## Deterministic, so a model can't argue with it

`agentos/ethics.py` is plain code over facts it works out itself:

- **The command, parsed.** Each shell segment is split as a shell would and unwrapped (`sudo`,
  `env`, `timeout`, `bash -c`). A line the reader can't be sure of is treated as one you'd want to
  see, never as safe.
- **Real paths, measured.** Globs are expanded, links are not followed, files and bytes are
  counted (stopping at 200,000 entries or 1.5 s, and then saying "at least").
- **Who owns each target.** This machine (loopback, its own addresses and name), a machine Bento
  set up, linked or logs into (the Network inventory), or a site that served the proof file. A
  model saying "this is an authorized test" counts for nothing; that's the hole the rule closes.

No model is asked, and the test checks the module imports none of the brain's code. Its
verdict can only be made stricter by the rest of the gate: a later deny still refuses, and nothing
lowers an ethics refusal. It's in `protected.SECURITY_MODULES`, so no agent may write it, and the
integrity watcher holds the machine if the file changes.

## Where it sits

It's step 1b of `PDP._decide`, right after the hard blocks and before grants, autonomy and the
built-in denies:

- **A refusal** returns `deny` with `rule="ethics"` at once.
- **A caution** is carried to the end of the gate. Every later step still has its say (a deny
  stands), and whatever they allowed or asked becomes an `ask` with `rule="ethics"`, no grant
  offer, and the verdict on `Decision.ethics`. `person_rule` marks it as a person's.

## The typed confirmation, and why it fails closed

The agent loop opens a confirmation token (`ethics.ask`) around its approver and requires
`ethics.consume(token)` after a yes. Only a screen that had the phrase typed confirms the token:

- the desktop card (`apEthics` in `09-websocket.js`), whose Go ahead stays off until the words
  match, and the server checks them again in `resolve_approval`;
- the TUI's card, the terminal chat, `bento flow allow <id> --type "…"`, and the one-shot REPL.

Every other approver (a phone tap, the scheduler, a flow's headless approver, an older page)
returns a yes that never confirmed the token, so the step is refused with a sentence telling the
agent to explain itself. That's deliberate: a new approver added next year is safe by default.
Phones aren't asked at all; they're told the card is waiting at a screen. A Brief answer to a
parked run types nothing, so it never answers an ethics caution either.

The confirmation is never remembered. There's no Remember on the card, and the token is
single use.

## Faces

- **GUI and SUI:** the chat card, Settings → Permissions → Ethics (the switch, what has no switch,
  your proved sites, Try a command), and the Ethics step in Permissions → Flow.
- **TUI:** `bento ethics` (show, check, own on|off, prove, proved, forget), the approval card in
  `bento tui` and the terminal chat, `bento flow approvals`.

## What it can't do

- It reads what a step names. The sandbox keeps the network, so a program an agent writes can open
  its own connections. Python is read for attack libraries it imports and attack programs it
  names, not every socket. Closing that properly needs a network jail with an allow-list per host.
- It can't judge intent. Asking how an attack works is conversation; this decides what Bento
  actually does.
- An agent CLI's own native tools, when a chat turns them on, never reach this gate (missions turn
  them off).
- A person at a terminal can still run anything themselves.

These are said in `docs/security.md`, not hidden.

## Next steps that would make it stronger

- A network jail with per-host egress, so ownership is checked at the socket and not only in the
  command.
- DNS TXT proof alongside the file, for sites with no web server.
- More programs in the attack list, and reading `run_python`'s deletes the way shell deletes are
  read.
