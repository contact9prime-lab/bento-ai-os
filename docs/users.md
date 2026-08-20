# Users

Several people on one machine, isolated by **directory**, not by query.

AgentOS ships single-user and stays that way until somebody adds an account.
Nothing about this document applies to a machine that never does: it keeps using
exactly the files it always used, there is no login screen, and there is nothing
to migrate.

The offer is the last step of setup, and it says what it costs before the button:

![The last onboarding step, "Add the people who will use it": a bordered note listing the three things that happen the moment you add the first account, the line "It is the same sign-in from anywhere", and username / display name / password fields](screenshots/onboarding-4-account.png)

Creating the first one is a decision with a confirmation on it, because it changes
how this machine behaves for everybody at it:

![A confirmation dialog: "Turn on accounts for this machine? Everything you have just set up becomes your account. From now on this desktop asks who you are — at the keyboard as well as from a phone."](screenshots/onboarding-5-account-consent.png)

Afterwards you are signed in as that account — bouncing somebody to a sign-in page
they had just created would be theatre:

![The account step, now ticked, with the message "signed in as ada — this is your machine now"](screenshots/onboarding-6-account-done.png)

---

## The layout

```
~/.agentos/
  config.json          the machine: providers and their keys, image provider,
                       executors, sandbox, remote access, updates, components
  users.json           the registry: id, name, display, role, password hash (0600)
  session.key          the cookie signing key (0600)
  shared/              agents and apps crossing between accounts, as copies
                       (the other crossing is a safe folder, shared live —
                       an admin setting, per account, see below)
  users/<id>/          0700 — somebody's whole private world
    agentos.db         memory, KG, conversations, grants, flows, tasks, apps, audit
    config.json        their channels, MCP, credentials, look, spaces (0600)
    workspace/         their files
    assets/            their gallery
    soul.md            their agent's identity
```

## Why directories, and not a `user_id` column

`space_id` is already a column, and its rule is deliberately leaky —
`space_id IN ('', :active)`, so a space sees its own rows *and* the global ones.
A space is a project you are working on, not a wall.

Users are the opposite claim. One forgotten `WHERE` clause among ~250 query sites
is somebody reading a colleague's memory, and no amount of review makes that
failure mode acceptable. Two files cannot leak into each other. That is the whole
argument.

## The seam

`state["store"]` and `state["cfg"]` are read in about 250 places, and not one of
them was changed. Instead the **lookup** resolves:

- `users.current()` is a contextvar, set by the request middleware from the
  **signed session cookie only** — never a header or a query parameter, because
  those are things a caller chooses and this decides which private directory is
  opened.
- `server._State` is a `dict` subclass whose `__getitem__` routes `store` and
  `cfg` (and the three per-user services) through that contextvar.
- `users.Scoped` is a two-descriptor mixin that does the same for the long-lived
  services built once at startup — the scheduler, the toolbox, the PDP, the
  control plane, the bridges. `self.cfg = cfg` in their existing `__init__`
  keeps working unchanged; it stores the machine's copy as the fallback.
- Background work enters `users.as_user(uid)`. A scheduled job belongs to whoever
  created it, and `asyncio.create_task` copies the current context — so a run
  launched at 08:00 still reads the right person's memory. That inheritance is
  why the seam is a contextvar and not a parameter.

Three services genuinely cannot be shared and get one instance per person: a
**Telegram** bridge polls with one bot token, a **WhatsApp** bridge holds one
linked device, an **MCP manager** owns live subprocesses started with somebody's
own credentials. They are built the first time anything reaches for them, not at
startup — most accounts have configured none of it, and an idle bridge nobody
asked for is a poll loop for nothing.

## Two roles

| | can |
|---|---|
| **executor** | everything inside their own home: agents, flows, jobs, apps, channels, MCP, credentials, their own permissions |
| **admin** | all of that, plus the machine: accounts, providers and models, components, remote access |

![The Users app: two accounts, Ada Lovelace marked admin and "this is you", Bob Kahn with a role dropdown set to Executor, and Password / Remove buttons](screenshots/users-two-accounts.png)

Two roles, and the form says what each one means rather than offering a grid of
checkboxes:

![The "add somebody" form: username, display name, password, and two role cards — Executor ("everything inside their own home") and Admin ("all of that, plus the machine")](screenshots/users-add.png)

There is deliberately no per-user grid of capabilities. **Grants** already answer
*what may this principal do* in far more detail than a role could, and they are
per user because the `grants` table is per user. The role answers only the one
question grants cannot: *may you change things that affect everybody?*

`is_admin('')` is **True** — a machine with no accounts has nobody to refuse.
Getting that backwards would lock somebody out of their own laptop.

## What is shared, and what is not

**Shared:** the machine settings. One set of provider keys for the machine, not
one per person who would each have to go and get their own. `users.USER_KEYS` is
the whole list of what is personal, in one place, so *"what is mine"* is
answerable without reading whichever route happened to write it. The line is
drawn at cost and blast radius: anything that spends money or reconfigures the
machine is the machine's. `default_model` is personal — which model you talk to
is a preference; which providers exist and what their keys are is not.

**Not shared:** everything else. Memory, conversations, the knowledge graph,
grants, flows, jobs, tasks, apps, the gallery, the soul, channels, MCP servers,
credentials, the audit ledger.

**Crossing over:** two things cross, and they cross in opposite ways on purpose.

The first is `shared/` — only agents and apps, and only as a **copy**. A shared app
that changed under the people using it would be a supply-chain problem living in a
filesystem, and the publisher would not know they had shipped a change. Taking a
copy renames on collision, so installing one never overwrites something of yours
with the same name.

The second is a **safe folder**, and it is deliberately the other way round: it is
shared *live*, not copied. That is the difference between code and data. A copy of
an app is a safe version of it; a copy of the quarter's invoices is a stale second
copy of the quarter's invoices, which is the problem rather than the fix. See
[Safe folders](#safe-folders-the-agent-working-outside-its-own-home) below.

Share from where the thing lives — an agent in Workflows, an app in App Studio:

![The Agents tab in Workflows, each agent row carrying a Share button next to Test in chat](screenshots/sharing-agent-share-button.png)

![A confirmation: "Share market-watcher with everybody on this machine? They get a COPY. Changing yours afterwards does not change theirs, and nothing else of yours becomes visible."](screenshots/sharing-consent.png)

It lands in the shared library at the bottom of the Users app, where anybody can
install a copy:

![The shared library showing market-watcher — "agent · shared by ada" — with Install a copy and Remove buttons](screenshots/sharing-library.png)

## Adding the first account

This is the consequential moment, and the UI says so before the button:

1. **Everything already on the machine becomes that account's** — the database,
   the soul, the assets, the linked phone, and the personal half of the config.
   The machine config is then stripped of those keys, because everything left in
   it becomes the starting point for the next person created.
2. **Loopback trust ends.** "Whoever is sitting here" has to stop being an
   identity once there is more than one identity, so the desktop starts asking —
   at the keyboard as well as from a phone.
3. **The first account is an admin**, whatever was asked for. A machine whose only
   account cannot administer it is a machine nobody can administer, and there is
   no second account to fix it from.

The person who creates the first account is signed in by the same request. They
proved they were the machine's owner by being able to make it; bouncing them to a
sign-in page they had just created would be theatre.

From then on the power menu names who is signed in, and offers a way out. Neither
appears on a machine without accounts — a "sign out" there would lock somebody out
of their own laptop with nothing to sign back in as.

![The power menu with "Bob" at the top, then "Sign out…", above Lock screen and the rest](screenshots/power-menu-signed-in.png)

![The sign-in page, asking for a username and a password](screenshots/login.png)

A new account gets its own arc on a machine somebody else already set up, rather
than landing in a stranger's finished desktop:

![The setup arc, freshly at 0 of 9, for the second account](screenshots/second-user-onboarding.png)

An executor sees their own account and the shared library, and is told plainly what
is and is not theirs:

![The Users app as Bob: both accounts listed but no role dropdown, no Remove, no "add somebody" — and the line "Only an admin can add or remove accounts. Everything inside your own home — agents, flows, channels, credentials — is yours."](screenshots/users-executor-view.png)

And the isolation is visible: Ada's `market-watcher` is not in Bob's Workflows.

![Bob's Agents tab, showing only the three built-in specialists — researcher, validator and writer — and none of Ada's](screenshots/isolation-second-user-agents.png)

## Safe folders: the agent working outside its own home

Everything above is about what each account keeps to itself. This is the one
deliberate hole in it, and it exists because the alternative was worse: the
agent's file tools are jailed to the workspace, and nobody's data lives in the
workspace, so "summarise last quarter's invoices" began with copying them in.

A **safe folder** is an admin naming a directory the agent may work in, who it is
for, and how much it carries:

```
bento folders                                             # who has what
bento folders add /data/finance --mode rw --users ada
bento folders add /srv/legal    --mode ro --users bob
bento folders add /srv/common   --mode rw               # everyone
```

or in **Settings → Sandbox → Safe folders**, one share per line as `mode who path`.

**It is the AI's access, not just yours.** These folders are what the agent itself
reads and writes — `read_file`, `write_file`, `list_dir`, the git tools — and what
`run_command` and the Terminal can reach. All of them, or none: a folder the agent
can read but the Terminal cannot would be a difference nobody could explain, and
a `ro` share the shell could write to would make the setting a lie.

**And it is scoped per account.** A share names the accounts it is for, and the
agent gets exactly the acting account's list — resolved from the same
`users.current()` contextvar as everything else on this page, so a scheduled job
running at 08:00 sees its owner's folders and not the machine's. Given the three
shares above:

| acting as | `/data/finance` | `/srv/legal` | `/srv/common` |
|---|---|---|---|
| **ada** | read + write | denied | read + write |
| **bob** | denied | read only | read + write |

An empty account list means everyone, which is also what a single-user machine
always sees — there is nobody to distinguish there.

**Only an admin can share one.** `sandbox` is a machine setting, so `/api/config`
refuses a non-admin the whole key. That is the point rather than an accident:
"which folders may I reach" is not a question you should be able to answer for
yourself from your own account.

**No share can ever be a way into another account.** The accounts root, a home
inside it, or *any directory above it* is refused outright, with that reason — so
naming `~/.agentos` or `/` cannot hand one account another's memory and
credentials. The per-account boundary is still checked first and still wins:
naming somebody's home directly does not open it. `bento doctor` lists every
share, its mode and who it is for, plus any entry that was refused and why.

This is the honest summary: **accounts are private by default, and a safe folder
is the admin deciding, explicitly and per person, that one directory is not.**

## One sign-in, here and from anywhere

Remote access needs a lock on the door. On a single-user machine that is a shared
passphrase. **On a machine with accounts it is the accounts** — the phone in
somebody's pocket signs in with the same username and password as the desktop, and
lands in their own home.

![The Remote access panel: "Locked by this machine's accounts. Everyone signs in from their phone with the same username and password they use here, and lands in their own desktop — their memory, their agents, their channels. No separate remote passphrase to invent, share or forget." with a Manage accounts button, and Turn remote access on enabled](screenshots/remote-locked-by-accounts.png)

Headless, that is two commands and no passphrase at all — the account is the lock:

```bash
bento user add alice          # the first account adopts this machine and is an admin
bento remote --on --bind 0.0.0.0
```

`bento remote` then reports which lock is in force and who signs in with it. Offer it
a `--passphrase` on a machine that has accounts and it declines, out loud, rather than
storing a secret nothing would ever read.

A second shared passphrase in front of per-person credentials would be worse than
none: one more secret, held in common by people who are otherwise isolated from
each other, and "sign in" would mean two different things depending on where you
were standing. `/api/remote/login` accepts the account password too, because a
phone that added AgentOS to its home screen months ago has that URL cached and a
404 there reads as "remote access broke".

What signing in gets somebody is their own **data**, kept private from the other
accounts. Through AgentOS's own surfaces that boundary holds even at the shell: the
agent's file tools refuse another account's home, and `run_command` and the
Terminal run inside a per-account `bwrap` jail — rooted at that account's home with
every other account's home blanked out — or refuse to run if no jail is available
(no jail cannot mean no walls). An executor cannot `cat` another account's memory
through AgentOS. The one exception is a folder an admin has deliberately shared
with them, which is the whole subject of [Safe
folders](#safe-folders-the-agent-working-outside-its-own-home) above — and no
share may be another account's home, so it never widens this.

What that does **not** buy, and should not be claimed, is protection against an
account that is actively hostile *and* has more than AgentOS gives it — a
`bwrap`-escape exploit, or root / physical access to the disk. That is a
deployment decision (a real per-user OS uid, or containers), laid out in
`docs/design/tenant-isolation.md`. So: accounts are a real boundary for the tools
this OS exposes; hardening the box underneath them against a resourceful insider
is a deployment choice on top.

## Locking the screen, which is not signing out

The lock this OS started with is the **host's**: `loginctl lock-session`, or sleeping
the display on a Mac. In SUI that is the right lock and still the only correct one —
AgentOS draws the desktop on the compositor's BACKGROUND layer with native windows
above it, so nothing the page can do would cover a running Firefox. In a browser it
is the wrong lock, or none at all: from a phone it locks the screen of the *server*,
in a room the person may not be in, while their AgentOS desktop stays open in their
hand.

So there is a second lock, offered exactly where the first cannot answer — a tab, a
window, a phone — and hidden in SUI, where the compositor's lock is stronger:

    Power menu → Lock desktop        (⌘/Ctrl palette: "lock desktop")

It locks the **session**, not the pixels. `POST /api/session/lock` re-issues the same
signed cookie with a lock inside it, and three things follow from where it lives:

- a reload, a second tab, a restored browser session and a server restart all still
  find it locked, and no script in the page can clear it;
- `_authed` refuses a locked cookie **before** loopback trust and before the account
  check, so the API and every WebSocket — the terminal included — go quiet with the
  page. A desktop that kept streaming a turn behind the lock screen would be a lock
  over the pixels only;
- it keeps **who** you are. `resolve_user` still resolves a locked cookie's owner, so
  coming back asks for one password and not a username. That is the entire difference
  from Sign out, and the lock screen says whose desktop it is guarding.

`/login` is both doors and the server decides which: `/api/users/who` answers `locked`,
and the page then asks for a password, offers "Sign in as someone else" for whoever is
not that person, and otherwise stays the sign-in page it was.

A machine with **no key** refuses to lock, in a sentence naming both ways to get one
(add an account, or set a remote passphrase). A lock with nothing to open it would
shut somebody out of their own desktop for good, so it is the one thing this must not
quietly become. `POST /api/session/lock` is in `SENSITIVE_FOR_APPS` for the mirror
reason: an app that could lock the desktop could hold its owner out on a loop.

There is nothing to lock from the **TUI**. The lock is a property of a browser
session, and the terminal client has no cookie — a headless machine's lock is the one
on the shell you reached it through.

## From a terminal

A headless machine has no desktop to add the first account from, and the
alternative would be editing `users.json` by hand — which is also the only way
back from a machine with no admin, so it must not be the normal way in.

```
bento user                          # who can use this machine
bento user add ada --role admin     # prompts for a password
bento user role bob --role admin
bento user passwd bob
bento user remove bob               # their home is KEPT
bento user remove bob --wipe        # and this destroys it — a separate decision

bento --user ada job list           # every data verb needs to know whose
AGENTOS_USER=ada bento flow list    # or say it once, for a cron line or a unit
```

A verb that reads data refuses rather than guessing when the machine has accounts
and none was named: a `bento job add` that silently landed in the wrong person's
database would be discovered weeks later by whoever did not get their briefing.

## Things that were nearly bugs

- **The PDP's caches are keyed on the user as well as the name.** A version
  counter is per-database, so two people can both be at `grants_version` 3 —
  without the prefix the second is decided against the first one's grants. The
  rate meter and the declared-skills cache collide the same way: two users may
  each own a subagent called `researcher` or an app called `notes`. Releasing a
  quarantine hold goes through `PDP.forget_rate()` for the same reason — a key
  built by hand at a call site is a key that gets built without the user, and the
  release then silently does nothing.
- **Session cookies used to be signed with a constant** when remote access had
  never been turned on. A multi-user machine on a private LAN may never turn it
  on, and a cookie signed with a public string is a forgeable `uid`.
  `~/.agentos/session.key` is now underneath every signature.
- **Deleting an account keeps their home.** Removing somebody's access and
  destroying what they made are two decisions, and one mis-click must not make
  them the same one. `--wipe` is the second decision, asked separately.
- **A factory reset removes the accounts too.** "Back to day one" that left three
  private databases on the machine — and left it demanding a sign-in nobody has
  the password for — would be the most misleading button in the OS.

## The three faces

- **GUI** — the Users app: the offer, the roster, roles, passwords, the shared
  library. The power menu names who is signed in and offers Sign out, and shows
  neither on a machine without accounts.
- **TUI** — `bento user`, plus `--user` / `AGENTOS_USER` on every data verb. No
  lock: see [Locking the screen](#locking-the-screen-which-is-not-signing-out).
- **SUI** — the same page, so the same app. Two things are genuinely different and
  are stated rather than hidden. Signing out returns this **AgentOS session** to
  the sign-in page; it is not a Linux logout, and the compositor, the native
  windows and anything already running are unaffected. And "Lock desktop" is not
  offered at all, because native windows sit above the desktop where only the
  compositor's own lock reaches them — the menu's "Lock screen" is that lock. Two people cannot use one
  physical screen at once, so the session-shell case is one account at a time —
  the others reach the machine from their own browsers.
