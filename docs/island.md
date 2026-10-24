# The island

Your office, on an island in the sea. Every department is a district of houses in its colour, your
agent's office has the lighthouse, the Brain is a fountain in the middle, and a little railway runs
round it with a station at every district.

![The island at ten in the morning](screenshots/island-day.png)

It is the same office as the 3D look, with the same people at the same desks. The rooms are open
terraces instead of boxes with walls, and the island grows round them. When your agents work, you
see it here: the desks light up, people walk over to ask each other things, and huddles gather at
the meeting table.

## Where to find it

- **As your desktop:** Settings → Appearance → Scene → Island. It fills the screen behind your
  windows, like Office HQ.
- **In the Office app:** ✎ Design → Look → "An island, a district for each department".
- **From a terminal:** `bento office look island`.

## What moves, and why

Nothing on the island moves for show.

- **The train runs because work was handed over.** When one room hands work to another (your agent
  delegating, a department's desk giving a job to one of its people, the answer coming back), the
  train sets off from the first room's station and stops at the other's. With nothing handed over,
  it waits at your agent's station.
- **Windows light up while somebody in that district is working.** At night they all glow, and so
  do the street lamps and the lighthouse.
- **The sea ripples and the boats rock.** That is scenery, like the office pet.

![A job handed to Research: the camera follows it, and the train carries it](screenshots/island-handover.png)

## Time of day

The island is lit for the real time where you are. The clock in the bottom corner lets you drag it
to any hour, and **Now** takes it back to the real one. This is kept in your browser only, so it
changes nothing for anybody else and nothing your agents do.

![The same island at night, with windows, lamps and the lighthouse lit](screenshots/island-night.png)

## Build it your way

In the Office, open ✎ Design. With the island look on, the Island section has:

- **Houses for each district.** Tap − or + to shrink or grow it, up to 12. Until you choose, a
  district has four houses and two more for each person in the department, so a bigger team is a
  bigger district.
- **Railway on or off.**
- **Trees:** few, some or lots.

Houses are scenery. Who works where is still decided by the departments' people, which you set in
the same panel or in the Company panel.

![The island builder in the Office's Design panel](screenshots/island-builder.png)

Your agent can build it too ("give Sales a bigger district and plant lots of trees"), through the
same settings. Every change is a line in Permissions → Ledger, whoever made it.

## From a terminal

```
bento office island                        # the districts and their houses
bento office island houses Sales 9         # grow a district (0 to 12)
bento office island train off              # no railway
bento office island trees lots             # few, some or lots
```

![bento office island in a terminal, listing each district and its houses](screenshots/island-terminal.png)

A terminal shows the plan, not the picture.

## On a phone

The island fits a phone held upright, and every control is big enough for a finger: zoom, the whole
island, the clock, and the builder's − and + buttons.

![The island on a phone held upright, with the clock and zoom buttons](screenshots/island-phone.png)

## What it costs

The island is one mesh for all the land, houses, trees and railway, two more for the windows, and
one plane for the sea. It draws from the Office's own loop: at most 30 frames a second while
something moves, and none while it is covered or the tab is hidden. At rest the sea ripples at
12 frames a second on a real graphics card and 6 on software rendering. Software rendering
and phones get no shadows, as in the 3D office.
