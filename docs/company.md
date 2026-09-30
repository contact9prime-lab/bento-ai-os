# Your company: departments of agents

Say what your business does and Bento sets it up as a company: departments like Admin,
HR, Finance, Supply, Sales, Tech and Marketing, each with a head and two or three staff.
Every person has a job title and a persona written for your business. They sit in their
department's room in the Office, and each department can be given work.

## Set it up

**In the Office:** press **▦ Company**, write a sentence about the business, and press
**Draft my company**. You can also tick the departments you want. With none ticked, your
AI picks the ones your business needs. The setup wizard's crew step has a **Set up a
whole company** button that opens the same panel.

The draft shows everything before anything is made: every department, what it does for
your business, every person with their title, their persona and the tools they would
have. Untick a person or a whole department, or open a persona and change it. The button
counts what will be made, and the count changes as you untick.

![The drafted company: each department with its head and staff, a persona open for editing](screenshots/company-draft.png)

**In a terminal:**

```
bento company setup "a dental scheduling startup, fifteen people, selling to clinic chains"
bento company setup "..." --departments admin,finance,sales    # exactly these
bento company setup "..." --words      # skip the AI, use the catalogue as it is
bento company templates                # the departments to choose from
```

It shows the same plan and asks before making anything (`--yes` skips the question).

With no AI set up, the catalogue fills the plan in as it is, with your company's name
and description in every persona. The panel says when that happened.

## What it makes

Nothing new. A company is things this OS already has:

- **Agents.** Each person is an ordinary specialist, in Missions → Build → Agents and
  Settings → Agents, and editable there like any other. An agent that already exists
  with the same name joins its department as it is. Nothing about it is rewritten.
- **Departments.** They are the Office's rooms. A department's head wears a ★ on the
  desk, and its people wear the department's colour.
- **A desk for each department.** This is a mission (a flow) whose team is that
  department. It starts **switched off**, so it holds no permissions. You can still give
  a department work: any step that needs permission asks you first. Switch the desk on in
  Missions when you trust it with its tools.
- **Who may ask whom**, if you leave that ticked. People in a department can ask each
  other, and the heads can ask each other. These are ordinary rows in Permissions and you
  can remove any of them. Swarm mode opens everything anyway.

Mail and calendar tools are given only when those accounts are set up in Settings →
Accounts. Otherwise the plan says who would read them once they are.

A drafted department can only have tools from a short list: reading files, memory, the
Brief, reports, the web, reading mail and calendar, reading code and running tests, and
images. It can't get a shell, a way to send mail or messages, a git push, or anything that
changes the machine. You can add those to an agent later in the agent editor, one by one.

## Give a department work

Tap a department's card in the Office, or pick it in the ▦ Company panel, write the task
and press **Send**. The head plans it and hands the pieces to the staff, and you watch it
happen in the Office: papers fly to desks and people walk over to ask each other.

```
bento company task Finance "summarise what we spend each month from the files in my workspace"
```

Your own agent knows the departments too. Ask it for something in chat and it hands the
work to the right head.

## What the cards and the task board count

![The company panel: each department's line and the task board](screenshots/company-tasks.png)

The card over each room shows how many agents it has, how many tasks it is **doing**,
how many are scheduled **next**, how many it has **done** this week, and a ⚠ when one is
waiting for you. Every number is counted from the runs, approvals and schedules on this
machine. Nothing is estimated, and a department that has done nothing shows zeros.

The **Tasks** list in the panel shows every department's work, newest first:

- **working**, **waiting for you**, **done**, **failed**, **stopped**, **scheduled**;
- who is on it and how many hand-overs it took;
- the first line of what came back.

A waiting task has **Review what it asks**, which brings up the approval card, or
**Answer it in the Brief** when the mission has paused for your answer there. Tap a task
to open it in the Run Inspector.

`bento company` prints the same numbers in a terminal.

![The Office with a company: each department's room, its head, and its card](screenshots/company-office.png)

## In every scene

The desktop's scenes (Settings → Appearance → Scene) show the company too. Each reads
the same answer about who is in which department, so they never disagree.

- **Crew:** one figure per department, drawn as its head in the department's colour,
  with the department's name and size under it. When anybody in the department works,
  its figure steps forward and says who. Anybody in no department stands beside them.

  ![The Crew stage with a company: one figure per department](screenshots/company-crew.png)

- **Mind:** each department is one cluster in its colour, with its people as the brighter
  points in it and their runs around them. Tap a department for its head, its people and
  a button to give it a task. Two people in one department talking stays inside the
  cluster; departments talking to each other is a strand between them.

  ![The Mind with a company: a cluster per department, and one department's card](screenshots/company-mind.png)

- **World:** a department stands as its head, with a tag like "★ Finance · 3". Tap the
  head to see how everybody in the department feels. Drawing twenty people at once made a
  crowd, so the rest of the department is on that card instead.

  ![The World with a company: the heads, their departments, and a head's card](screenshots/company-world.png)

- **Office:** the rooms, as above.

`bento mind` groups by department in a terminal as well.

## Changing it later

- **Add departments:** ▦ Company → **＋ Add departments**. Existing departments and
  agents stay as they are.
- **Rename, recolour or move people:** Office → ✎ Design, as before. The head, the
  mandate and the desk stay with the department.
- **Change a person:** Missions → Build → Agents, or Settings → Agents.
- **Remove a department:** Design → ✕ next to it. Its people move to the open floor; the
  agents and the desk are not deleted.

## The three faces

- **GUI:** the Office's ▦ Company panel and the cards over the rooms. On a phone the
  panel is a sheet and the cards shrink to fit the room.
- **TUI:** `bento company` shows, `setup` plans and makes, `task` hands out work. A task
  needs the server running, because that is where the work runs.
- **SUI:** the same page. The desktop scenes (Office, Crew, Mind, World) show the
  departments. The Office scene shows no cards, because nothing under the windows can be
  tapped; the Mind's and the World's tags can be.
