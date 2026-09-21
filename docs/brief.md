# The Brief

What your missions produced, as things to act on — not a message to read.

Every other agent delivers a standing job the same way: a wall of prose lands
in a chat or a file, once, and tomorrow's run lands another one under it.
Nothing in that wall can be tapped, nothing in it remembers that you dealt
with it, and by the third morning you have stopped reading. The Brief is the
other answer, and it is the only way a mission delivers here.

## What a mission delivers

A mission does not write a report at you. Its specialists write **items**, one
per thing, with a tool called `brief_item`:

| Kind | What it is | Its hands |
|---|---|---|
| **Needs you** | Something you must do — a signature, a reply, a payment — with who, by when, and a drafted reply if one made sense | Done · Later · Send draft… · Open mail |
| **Decide** | An ask with two to four possible answers, offered as buttons | The choices |
| **FYI** | Worth one line, nothing to do | Done · Later |
| **Done for you** | Something the mission did on your behalf | — |

The narrative still exists — a mission's `finish` is saved as a report — but it
is the long form, behind a button. What reaches you is the items.

## One living page

There is one Brief per day. It is the same page everywhere:

- **The desktop** — the Brief app, grouped: needs you, decide, FYI, done for
  you. The home scene's line under the prompt bar reads `Your Brief: 2 need
  you · 1 decision` and opens it.
- **The phone** — one item per screen, the hands at a fingertip's size, ‹ › to
  step through.
- **Telegram** — a mission that delivers there sends the digest with the
  buttons under it: `✓ 1 done`, `⏸ 1 later`, and a decision's choices.
- **Out loud** — *Read it* speaks the headline and the items that need you.
- **A terminal** — `bento brief`, with the server down if need be, and `bento
  brief done <id>`, `later`, `reopen`, `decide <id> <choice>`.

Three rules make it a page rather than a feed:

- **A mission's next run updates its items instead of adding twins.** Every
  item carries a key — the mail uid, the event uid — and a re-run with the same
  key changes the item in place. A thing you marked Done stays done, whatever
  the next run says about it.
- **A thing that needs you does not stop needing you at midnight.** Open items
  carry over onto tomorrow's page. *Later* only says you saw it.
- **A decision stays in view after you make it**, with what you decided and,
  when it lands, the reply. Only Done goes under "handled".

## Every item has hands

Done and Later are one tap. A draft can be sent — through the same gate, as
you, so `mail_send` asks first; no mission can send. *Open mail* reads the
message the item came from.

A decision's choices are buttons, and the answer is **handed back to the
agent as a turn**: "the user decided: counter at $20 — do the next step", with
the item as its whole context. The tap returns at once — the item reads
*decided: Counter at $20 · Aria is writing the reply…* — and the reply arrives
where the question was, a minute later, as *The reply*: a conversation you can
carry on. That loop — mission → decision inbox → your one word → the next
step — is the thing a message cannot do.

## What was measured

Inbox triage on a real Claude Code brain against a five-message mailbox,
three runs: 77s, 81s and 74s, one delegation each, 56k–80k tokens in. The
third run wrote two needs-you items, one decision with four choices and no
FYI, keyed on the mail uids, with the source recorded so *Open mail* works.
Tapping a choice recorded the decision at once; the agent's reply landed
6 seconds later as a drafted acceptance. On a 390px phone every hand measured
40px tall, the page did not scroll sideways, and a real touch on *Done* hit
*Done*.

## What is deliberately not here

- A mission cannot mark its own items done, and cannot decide. Those are the
  person's, and `brief_item` only adds or updates.
- The mission and run stamped on an item come from the agent that wrote it,
  never from an argument — a model cannot file something under another
  mission's name.
- No item is deleted by a run. Prune keeps the Brief with everything else
  that grows; a person's Done is a fact about the person, not about the run.
