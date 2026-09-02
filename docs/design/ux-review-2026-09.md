# UX review, September 2026 — what a new person meets, measured

This is a review of the product as it is experienced, not as it is described.
It was produced by running the shipped code against a **fresh home** (no
model, no key, no accounts — the state every new install is in), driving it
with a real browser, and measuring what happened. Every claim below has a
number, a screenshot, or a `file:line` behind it. Where something could not be
measured here, the review says so rather than guessing.

The short version: the thinking behind this product is unusually good, and the
honesty rules in `CLAUDE.md` are visible on almost every screen. What lets it
down is a small number of mechanical defects on the paths a new person walks
first, and a desktop that shows everything on day one. Both are fixable in
days, not months, and both are worth more than any new feature.

---

## How this was done

| | |
|---|---|
| Build | branch `master` at `abd285f`, served with `AGENTOS_HOME` pointing at an empty directory |
| Desktop face | headless Chromium, 1440×900 (the commonest laptop size), mouse |
| Phone face | iPhone 13 emulation, 390×844, touch events, DPR 2 |
| Walked | the setup wizard, the empty desktop, launcher, prompt bar, Chat, all 43 built-in apps, the tray panels, the command palette, Exposé, a light theme, the sign-in page |
| Measured with | `getBoundingClientRect`, `getComputedStyle`, timed event sequences — not by reading the CSS |
| **Not tested** | the session UI (no compositor here), the TUI, and a turn with a working model (no key, no Ollama). The last is deliberate: "no brain yet" is the first state every install is in, and it is where the worst finding lives |

The evidence screenshots are in [`ux-review/`](ux-review/).

---

## What is already strong

Say this first, because the plan below should protect it.

- **The wizard's framing is the best thing in the product.** "You will end up
  with: a model this machine can actually reach" before any control, steps that
  are *probed* rather than remembered, greyed steps that say *why* ("needs
  model"). Nothing else in this category does this.
  ![Name your agent](ux-review/01-firstload.jpg)
- **Jobs** is the model for every other app: three recipes, each with what it
  does *and* a sample of what you will actually receive ("A page headed
  'Tuesday' with four or five paragraphs…"). It reads like a person talking.
- **The honesty rule is real.** Quick Settings on a hosted desktop says "Your
  desktop environment owns this" instead of showing a dead slider; the brain
  step lists Hermes and OpenClaw as *not installed* with the reason, rather than
  hiding them.
- **Empty states teach.** Memory, Skills, MCP, Scheduler, Gallery each explain
  what fills them and end on "✦ Ask Aria".
- **Keyboard and window management** are a cut above: Ctrl+/ overlay, Exposé
  with the desktop pager, snapping, focus ring on the active window, cascade.
- **The phone layout exists and mostly works**: sheets, a bottom dock, a
  38px close, the Settings rail turned sideways, safe areas. The touch-target
  work recorded in `tests/test_ui_touch.py` shows.
- The **light theme** holds up (chat and Settings read cleanly on Ubuntu light).

---

## The defects, measured

Ordered by how early a new person hits them. "Fix" is an estimate of the size
of the change, not of its importance.

### D1 — The first message ever sent is answered with a Python exception

Type anything into the prompt bar or Chat on a fresh install. The reply is
`ConnectError: All connection attempts failed`, in red, from "▲ ARIA", and a
toast says **"Aria replied"**.

![The first answer](ux-review/12-chat-sent.jpg)

What happened: no brain is set, so the provider layer defaults to Ollama on
`localhost:11434`, which is not running, and `run_chat` forwards the exception
name verbatim (`agentos/server.py:9228`, `f"{type(e).__name__}: {e}"`). The
turn is also logged as an error and counted (Token Analytics shows "2 turns").

Nothing on that screen says *there is no model* or offers the door to fix it.
The brain picker in the Chat header reads "— nothing set —" / "— no model —"
as two disabled dropdowns, and the wizard step that would fix it is three
clicks away with no link. This is the one moment where the honesty rule
("a missing capability reports why, plus the component that would fix it") is
not applied, and it is the first moment.

**Fix (small).** In `run_chat`, before constructing the agent: if no brain
resolves, emit an `error` event with a sentence and a door ("Nothing can answer
yet — give it a brain") that opens the setup step, and do not log or bill the
turn. Map the three failures every install meets (no brain, Ollama down, bad
key / 401) to sentences; keep the exception name in Logs only. The "Aria
replied" toast should not fire on an error turn. Pin it in
`tests/test_empty_turn.py`: a turn with no brain never emits a message
containing `Error:`.

### D2 — The launcher is off the top of the screen

Click the ▲ Launcher on a 1440×900 screen with the deck open (the default):
the menu's top edge is at **y = −419px**. The header, the search box and the
first four rows of apps are above the screen; only the last two rows are
visible. The same arithmetic puts it at −239px on a 1920×1080 screen when the
deck wraps to two rows.

![Launcher](ux-review/08-startmenu.jpg)

Cause: `agentos/ui/src/css/14-omnibar.css:292` —
`body.deck-open #startmenu{bottom:calc(var(--tbh) + var(--deckh) + 16px)}`
lifts the launcher above the deck, and the deck is 564px tall here. The two
launchers compete for the same vertical space and the older one loses.

**Fix (small).** Clamp: `max-height:calc(100vh - var(--mbh) - var(--tbh) - 32px)`
on `#startmenu`, with `#smapps` taking the remainder, and drop the deck offset
when there is no room. Better: the deck *is* the launcher on the desktop; the
▲ button could open the deck's search (`#deck-q`) instead of a second menu.

### D3 — The menu bar's menus cannot be opened by clicking

Every window gets File · Edit · View · Window · Help. Clicking a title
highlights it and shows nothing. Measured sequence: `mousedown` → nothing;
`mouseup` → `#ctxmenu` is shown by `paintMenuBar` (`04b-appmenu.js:169`) and
**closed in the same event** by the document-level click listener at
`06-icon-layout.js:187` (`if(!e.target.closest('#ctxmenu')) …remove('show')`).
At +30ms and +430ms the dropdown is `display:none` and the title is still
`.on`.

Because the title keeps `.on`, the `mouseenter` path (`04b-appmenu.js:176`,
"slide across like a real menu bar") re-opens the dropdown the next time the
pointer passes over it, with no click — and that dropdown then survives
Escape, a theme change and opening another window (visible in
[`28-light-settings.jpg`](ux-review/28-light-settings.jpg): File's menu is
still open over a Settings window that was opened afterwards). The
Help → Keyboard shortcuts and Help → manual entries are therefore unreachable
by click, and every later screenshot shows "Window" or "Help" stuck highlighted.

**Fix (tiny).** `e.stopPropagation()` in the title's `onclick`, or teach the
document listener to ignore `#mbmenus`. Then Escape must close it (see D4).

### D4 — Popovers are not exclusive, and Escape does not close them

Open Notifications, press Escape: still open. Click ⏻: the power menu opens
*under* the still-open notification panel and its first entries (Lock screen,
Restart AgentOS) are hidden. Open Quick Settings, press Ctrl+Space: the
palette opens beside it. Each popover has its own document-click closer
(`22-quicksettings.js:39`, `06-icon-layout.js:185`, the menus above) and
Escape is handled only for Exposé, the switcher, the shortcuts overlay and
fullscreen (`29-keyboard-palette.js:455`).

![Two popovers](ux-review/16-power.jpg)

**Fix (small, structural).** One popover manager: `popOpen(el)` closes any
other open popover, Escape closes the top-most, a click outside closes it.
Start menu, notifications, power, quick settings, the context menu, the
palette and the omni list all register with it. This is the same shape as the
existing `osDialog` and would replace five ad-hoc closers.

### D5 — The prompt bar's answer card covers whatever window is focused

An omnibar answer lingers for 30 seconds (`28a-omnibar.js:231`) at a z-index
above windows. Ask something, open Chat: the card sits over Chat's composer.
Open Settings: it covers the Ollama URL field. It is the first thing a new
person does (ask from the bar) followed by the second (open the app the card
suggests), and the card hides the app.

**Fix (small).** Dock cards to the bar rather than floating them over the
desktop: when a window is focused, lower `#omnicards` below `.win` or slide the
card to the side; end the linger on the next interaction instead of a fixed
30s.

### D6 — On a phone, the wizard has no way out

At ≤760px `.ob-head, .ob-leave {display:none}` (`18-onboarding.css:95`). The
"Finish later" button is the only exit from the first-run screen, and a phone
user who cannot supply an API key from where they are (which is the case for
the person who installed on a Pi and opened it from their phone, the exact
person `install.sh` now asks about) is inside the wizard with no door. Blocked
steps are `disabled`, so they cannot even be looked at.

![Phone wizard](ux-review/p01-firstload.jpg)

**Fix (tiny).** Keep `#ob-leave` in the horizontal rail (it already handles
"Open it full screen" / "Close" in the windowed variant). Blocked steps should
open read-only with the reason in the pane rather than refuse the tap.

### D7 — On a phone, Chat shows two prompt boxes

Chat's composer ("Ask, tell it what to do, paste an ima…") sits 60px above the
desktop prompt bar ("Ask Aria anything — or pre…"). Above the empty chat are
five controls in two rows ("— nothing set —", "— no model —", Balanced, Voice
off, Clear session) before any content. The two inputs answer the same
question in slightly different words.

![Phone chat](ux-review/p04-chat.jpg)

**Fix (medium).** On a phone, a sheet with its own composer should hide the
prompt bar (`body.dev-mobile.win-open #omnibar{display:none}`), or the sheet
should *use* the bar as its composer. The header controls belong behind one
"⋯" on a phone; the brain picker is a Settings decision, not a per-message one.

### D8 — On a phone, the launcher is 33 icons with no names

Every `.smapp .n` label measures **0px tall** inside a 58px tile whose icon is
48px; the label is there in the DOM and clipped to nothing. Thirty-three
unlabeled squares is a memory test, and eleven of them are shades of grey.
(On the desktop the last row loses its labels the same way under the
`max-height:52vh` clip.)

![Phone launcher](ux-review/p03-startmenu.jpg)

**Fix (small).** Give `.smapp` a `min-height` that fits icon + gap + label and
let `.n` be `flex:none`; on a phone the tile should be 84×96 or so. Then D2's
clamp stops the desktop row clipping too.

### D9 — On a phone, Workflows keeps its two-pane desktop layout

The flow list and the flow detail share 390px: the detail column is ~300px of
wrapped prose, and the "STARTS / GRANTED (10)" pair wraps word-by-word ("no /
triggers / — runs / when you / say so"). Settings solved exactly this by
turning its rail sideways; Workflows did not get the same treatment. App
Studio's three-column builder has the same shape.

![Phone workflows](ux-review/p06-workflows.jpg)

**Fix (medium).** A `.two-pane` convention for phones: list first, tapping a
row pushes the detail as a sheet with a back control. Applied once as a CSS
class + a small helper, every list/detail app inherits it.

### D10 — Keyboard hints on a touch screen, and a legend that says "ask" twice

The prompt bar's result list shows `⇧↵ ask · alt+1…9 quick launch · ↑↓ pick`
on a phone with no keyboard. On the desktop the legend reads
`↵ ask  ⇧↵ ask` when the query is a question — two keys with the same label,
which is the case where the distinction actually matters (Enter *launches* for
a one-word query).

![Phone prompt bar](ux-review/p08-omni.jpg)

**Fix (tiny).** Hide `.omni-hint` under `body.dev-touch`; label the desktop
legend by what differs ("↵ ask · ⇧↵ always ask" or "↵ launch · ⇧↵ ask").

### D11 — On a phone, toasts paint over the clock

`toast()` uses `bottom:calc(var(--tbh) + 12px)`, but measured on the phone the
toast's box is at **y = −18…20px** — over the 34px menu bar, covering the
clock and the status dot ("configuration updated" in
[`p03-startmenu.jpg`](ux-review/p03-startmenu.jpg)). Something in the phone
layout gives `#toasts` a different containing block; the rule for
`body.dev-mobile #toasts` is missing from `15-responsive.css`.

**Fix (tiny).** `body.dev-mobile #toasts{top:auto;bottom:calc(var(--chrome-b) + 8px)}`.

### D12 — One sentence, four times

Quick Settings on a hosted desktop shows "Your desktop environment owns this.
Open its settings, or run the AgentOS session." under Sound, Brightness,
Network and Power — four times in one 380px panel, then a fifth variant under
Notifications, and again in System Settings → Network. The sentence is right;
repeating it turns an honest answer into noise.

![Quick settings](ux-review/17-palette.jpg)

**Fix (tiny).** One banner at the top of the panel when the platform is hosted,
and the individual cards show their read-only value or nothing.

### D13 — The sign-in page is a different product

`/login` says **AgentOS** (everything else says Bento Box AI) and "This desktop
is **locked**. Sign in to continue." — for a first sign-in it reads like a
lock-out. The About window and the CLI banner also still say AgentOS. The
CLAUDE.md note explains why `agentos` stays as the *command*; the *name on
screen* should be one name.

**Fix (tiny).** `login.html` wording and mark; the lock sentence only when
`session_locked` is actually true.

### D14 — Smaller things seen on the way

- The README and Getting Started say "**nine** steps"; the wizard has **11**.
- `F1` does nothing; Ctrl+/ opens the shortcuts overlay, and Help → Keyboard
  shortcuts is unreachable by click (D3). A newcomer has no discoverable way to
  the shortcut list.
- The Exposé hint at the bottom ("click a space to … window to open it") is
  behind the dock.
- The running-apps dock on a phone grows with every sheet opened and rests
  with the left-most icon half-clipped (`p07-jobs.jpg`); the snap rule fixed the
  right edge but not the left.
- "Model Manager" inside Settings → AI providers is a default blue underlined
  browser link in the light theme (`28-light-settings.jpg`).
- The brain step's "Or bring a cloud model" heading sits with no space under
  the Ollama card (`02-wiz-brain.jpg`).
- The chat window opens at the top-left of the screen (y=45) rather than
  where a cascade would put it; every other first window is centred.

---

## The structural issues

These are the levers that change how the product *feels*, as opposed to
whether it works. Each one is a design decision, so this section argues rather
than measures.

### S1 — The first five minutes end on a wall of 43 apps

After "Finish later" the desktop is six groups and 43 tiles, plus the
machine's own apps, on a machine that cannot yet answer a question. Nothing on
the screen says so. Quarantine, Audit, Policies, Permissions, Snapshots, Token
Analytics, Mission Control, Train and Evals are all offered with the same
weight as Chat.

![The desktop after setup](ux-review/07-desktop.jpg)

The roadmap's own pitch is "week 4 looks different from week 1". Day one should
look like day one. Two concrete moves, both using machinery that exists:

- **The deck should be probed the way the wizard is.** The wizard already
  knows what exists on this machine (model, agent, flow, job, channel, users).
  Groups whose apps have nothing in them yet — Intelligence with an empty
  memory, System with zero grants, Library — start **collapsed** with a count,
  and open as things appear. Essentials, Create and Automation stay open. That
  is 16 tiles on day one, not 43, and the tile count itself becomes a progress
  meter.
- **The desktop should carry one line of state.** A strip under the menu bar
  or a first deck tile: "No brain yet — give it one →", later "Running on
  Claude Code · 2 jobs standing · last run 08:00". The menu bar has a hidden
  `#fwdchip` for the executor already; make it the machine's one-line status,
  and make "nothing set" a link rather than a label.

### S2 — Four ways to do one thing

A person who wants the machine to do something without them meets **Jobs,
Scheduler, Automations and Workflows** (and triggers inside flows). Someone
who wants to know what it is allowed to do meets **Policies, Permissions,
Quarantine, Audit** and Settings → Agent → autonomy. Someone who wants to see
what it knows meets **Memory, Profile, Knowledge Graph, Soul, Spaces,
Timeline**. Settings comes in three: **Settings, System Settings, Quick
Settings**.

Each of these exists for a real reason in the code, and the code should stay.
The *apps* should merge, because an app is a promise about a concept and a
newcomer cannot tell four concepts apart. Concretely:

| Today | Proposal | Why it is safe |
|---|---|---|
| Scheduler | a tab of **Jobs** | jobs are already flows; a bare scheduled prompt is a job with no recipe |
| Automations | a tab of **Workflows** | "name a sequence once" is a flow without a model |
| Policies, Audit | tabs of **Permissions** | Permissions already has Quarantine as a tab; Audit is its ledger |
| Memory, Knowledge Graph, Soul | tabs of **Profile** | Profile is already the roll-up of the other three |
| Quick Settings | the tray popover only | it is a popover pretending to be an app |

That takes the deck from 43 to about 31 without deleting a screen — every
former app becomes a tab, with its route and its TUI face unchanged. This is
pillar H of the roadmap ("look like one OS, not twenty utilities") done by
subtraction first.

### S3 — Two agents on one screen

The prompt bar is "the ever-present agent" and Chat is the agent's app, and
they are visibly two things: two composers on a phone (D7), a card that covers
the chat window it offers to open (D5), a separate "Desktop" thread in the
sidebar. The stitching in `10a-handoff.js` is good; the visual model is not
yet one agent.

Proposal: the bar is the only composer on a phone, and on the desktop a card
is a *preview of the Desktop thread* that docks to the bar and never covers a
window. "Open in Chat" then reads as "expand", which is what it is.

### S4 — Errors are exceptions, not sentences

D1 is the worst case, but the pattern is general: the WebSocket `error` event
carries whatever string the server made (`09-websocket.js:360`), and the
server makes it from the exception (`server.py:9228`). The product has a
vocabulary for capabilities ("why, plus the component that would fix it") and
none for turns. A table of the six failures every install meets — no brain,
Ollama not running, model not pulled, bad key, rate limit, network — each with
one sentence and one door, would apply the existing rule to the one place it
matters most.

### S5 — One overlay model

D2, D3, D4, D5 and D11 are one problem wearing five hats: launcher, menus,
tray panels, cards and toasts each own their own position, z-index and closing
rules, and they collide. A single layer with an ordering (toast > dialog >
popover > card > window), one manager that keeps at most one popover open, and
Escape/outside-click handled in one place would fix all five and prevent the
sixth.

### S6 — The phone is a first-class face and needs three conventions, not fixes

The sheet model is right. What is missing is three rules the desktop apps can
follow without knowing about phones: a **list→detail push** (D9), a **header
overflow** ("⋯" for anything past two controls, D7), and **one composer**
(S3). Settings already demonstrates the first; write the other two once as
classes and every app inherits them.

### S7 — One name, one copy

Bento Box AI / AgentOS / Aria appear on the same screen. "AgentOS" is fine as
history and as the command, but the sign-in page, About, the CLI banner and
the wizard's "Set up Aria" should agree on what the *product* is called and
what the *agent* is called. The nine-versus-eleven steps is the same kind of
drift, smaller.

---

## What to do, in order

Each item names the test that would pin it, in the style of
`tests/test_ui_touch.py` — the guarantee is a convention, and the moment a
rule is dropped nothing else notices.

**P0 — this week, all small, all measurable.**

| Item | Test |
|---|---|
| D1 no-brain turn → sentence + door, never an exception name, never billed | `test_empty_turn.py`: no `Error:` in any event of a turn with no brain |
| D3 menu titles open on click; D4 one popover at a time, Escape closes it | `test_ui_windows.py`: `#mbmenus` click is not closed by the document listener; every `.show` popover is in the manager's list |
| D2 launcher clamped to the viewport | `test_ui_build.py`: `#startmenu` has a `max-height` in `vh` |
| D6 phone wizard keeps its exit; D8 launcher tiles keep their labels; D10 no key hints on touch; D11 toasts below the chrome | `test_ui_touch.py`: `#ob-leave` not `display:none` under mobile; `.smapp` has a `min-height`; `.omni-hint` hidden under `dev-touch`; `#toasts` has a mobile rule |
| D12 one ownership banner; D13 one product name; the "nine steps" copy | a `grep` in `test_i18n_readme.py` for the step count against `onboarding.STEPS` |

**P1 — the next two weeks.**

- S1: probed deck groups (collapsed until they have something) and the
  one-line machine status in the menu bar.
- S3 / D5 / D7: one composer on a phone; cards dock to the bar on the desktop.
- S6 / D9: the list→detail push for Workflows, App Studio and Permissions.
- S4: the six-failure table for turns.
- S5: the popover manager, which P0's D3/D4 fixes should be written against
  rather than around.

**P2 — a release.**

- S2: merge the four automation apps into two, the four trust apps into one,
  the four memory apps into one. Routes, TUI panes and tests unchanged; only
  the app registry and the deck's seed change.
- Pillar H's UI kit, built from the pieces that already look right (the Jobs
  recipe card, the wizard pane, the Permissions card) rather than designed
  fresh.

**What this review does not cover.** The session UI on a real compositor, the
TUI, and any turn with a working model — including tool cards, approvals and
the copilot panel, which are the heart of the product once it is set up. A
second pass with a key and Ollama installed should start there, and should
measure the same way: a fresh home, a real browser, numbers.
