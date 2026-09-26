# The Office

The **Office** app is a playground where you watch your agents work. It is drawn as a
comic-strip office:

- your agent sits in the corner office, behind the mission board;
- each specialist has a desk in a department;
- huddles happen in the meeting room;
- there is a lounge with a sofa, a coffee machine and an office cat.

The chat is the column on the right, so you ask for something there and see it happen
on the left.

![The Office in the Pop comic style: the analyst has walked to the writer's desk and asked a question, the writer answers in a balloon, the researcher's monitor is lit with a burst naming the tool it just called, and the chat is on the right](screenshots/office.png)

Open it from the dock, the app deck (Essentials), or ask your agent to "open the office".

## What moves, and why

Everything in the office moves because something really happened on this machine.

| You see | Because |
|---|---|
| A **paper flies** from the mission board to a desk, and a **!** pops over the specialist | A mission handed that specialist work, or your agent delegated to it |
| The **monitor lights** in the department's colour and the specialist **types** | Its run started; a tag above its head names the AI provider it is answering on |
| A **comic burst** ("FETCH!", "SCRIBBLE!") with the real tool name under it | It called that tool |
| One agent **gets up and walks** across the office to another's desk, asks in a speech balloon, waits for the answer, says thanks and walks back | It asked that colleague something (the team's permission matrix let it) |
| Agents **gather round the meeting table**, the one talking in a balloon | A huddle started |
| A **"? needs you"** shout and a raised hand | It is waiting for you to allow a step |
| **"done ✓"**, and the paper flies back to the board | Its run finished |

When nothing is happening, everyone sits at their desk, breathing and blinking. **They do
not wander about for show.** An office where everybody strolls around would look busy
when nothing is running, and this OS never shows activity that is not real. The pet
wanders. It is decoration, and it is clearly not an agent.

Under the picture, a four-line log says the same things in words ("analyst asked writer:
…"). A screen reader reads that log. It is also the quickest way to catch up after
looking away.

![A huddle in the meeting room: the validator and the engineer stand behind the table, the validator speaking, while the researcher walks in along the corridor](screenshots/office-huddle.png)

This is a real run, not a replay. You type into the chat, "redesign my office as a
space station". The agent calls `set_office` and the office repaints. Then you ask
`@researcher` about prices. It walks to the validator's desk in Build, asks, and gets
the answer.

![A live run in the Space station style: the researcher standing at the validator's desk in Build, its question and the validator's answer in balloons, and the same turns in the chat on the right](screenshots/office-live.png)

## Make it your office

Press **✎ Design**:

- **Describe it** in words. The text goes to your agent in the chat, and it designs the
  office with `set_office`.
- **Style**: *Pop comic* (the default), *Startup loft*, *Glass tower*, *Cozy studio*,
  *Space station*, *Greenhouse* or *Night shift*.
- **Name on the door.**
- **Departments**: up to six, each with a name and one of eight colours.
- **Who sits where**: pick a department for each specialist. A specialist you do not
  place sits on the **Open floor**.
- **Shared rooms**: the meeting room (where huddles gather) and the lounge, each on or
  off.
- **Decor**: plants, coffee, a whiteboard (the mission board), a bookshelf, an arcade
  cabinet, posters.
- **Office pet**: a cat, a dog, a robot, or none.

Changes show at once. The office is yours alone: on a machine with accounts, every
person has their own office. Every change you make is a row in the Audit log
(`office.write`).

![The designer open over the office: describe it, seven styles, the name on the door, two departments with colours, and who sits where](screenshots/office-design.png)

Only real specialists can be seated. Put in a name that nobody on this machine has and
it is left out, and the office tells you which names it dropped. A specialist that is
deleted leaves its department. Its empty chair has no name on it.

## Your agent can redesign it

"Make the office a cosy greenhouse and put the researcher and analyst in a Research wing"
is enough. The agent's `set_office` tool picks from the same fixed set of styles,
colours, decor and pets as the designer. If you ask for something outside that set, it
is refused with the list of choices.

`set_office` has its own permission (`office.write`), separate from the permissions for
real work. You can allow your agent to redecorate and still refuse it everything else,
or the other way round.

## From a terminal

There is nothing to animate in a terminal, but the office is a plan too, and
`bento office` shows it and edits it:

```
$ bento office
HQ — Pop comic (bright halftone floors, bold ink, primary colours)

  Aria's office            your agent
  Research                 researcher, analyst  [sky]
  Writing                  writer  [rose]
  Open floor               engineer, validator

  also: meeting room, lounge · decor: plants, coffee, whiteboard · pet: cat

$ bento office styles
$ bento office style space
$ bento office move analyst Research
$ bento office move analyst            # back to the open floor
$ bento office dept-rm Writing
$ bento office meeting off
$ bento office decor plants arcade
$ bento office pet robot
```

It works with the server stopped. The desktop shows the change the next time it loads
the office. To follow live work in a terminal, use `bento flow runs` and the chat TUI.

## On a phone

The rooms stack one per row and the office scrolls. The chat is a sheet behind the
**Chat** button. Tap a person to start a message to them (`@name`) in that sheet.
Every control in the designer meets the touch-size floor.

![The Office on a 390px phone: the rooms stacked, the analyst standing at the writer's desk with the answer in a balloon](screenshots/office-phone.png)

## What it costs

The Office draws on one canvas. The rooms are painted once into a hidden layer and
copied each frame, so a frame costs about a millisecond. Measured in Chromium with six
agents:

| State | Frames per second | Time per frame |
|---|---|---|
| At rest | about 5 | 1.1 ms |
| Five agents working, one walking | 15 (at most 30) | 1.35 ms |
| Window minimised, on another desktop, or covered | 0 | — |

With reduced motion turned on, the office draws one still frame per event: people appear
where they are going instead of walking there.
