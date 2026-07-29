# Changelog

## Unreleased — the ever-present agent (2026-07-26, second drop)

### You can keep talking while it works (2026-07-29)

Typing into a busy chat used to be refused outright: *"This conversation already has a turn
running — stop it, or continue in another chat."* Your next thought was worth less than the
agent's convenience. Now it is **queued**, and the running turn has to decide what it is.

- **A queue per conversation.** Whatever you send while a turn is running lands in the *Up
  next* strip above the composer — this chat's visible to-do list, with a `✕` on each row.
  It survives a reload (it rides `state_sync` like running turns do).
- **The turn triages it, at a step boundary.** Between steps — never mid-tool — the agent
  decides whether each queued message belongs to what it is doing *right now*. "Actually make
  it a bullet list", "put it in Documents instead" gets **folded into the live run**, marked in
  the transcript with `↩ took in: …`, and the rest of the turn accounts for it. "Also tell me a
  joke afterwards" **waits**, and starts as its own turn the moment this one ends. A turn that
  is about to end checks once more, so a message that lands during the final reply still counts.
- **The decision does not cost you time.** It starts the instant you hit send and runs alongside
  the reply already streaming, on `memory.model` if you have a small model set for that. If no
  model answers within `steer_triage_timeout`, the wording decides — and the default is to wait,
  because waiting is recoverable and hijacking a task in flight is not. `steer_queued_messages:
  false` turns the judgement off entirely and makes everything wait its turn.
- **The send button learned a second job.** While a turn runs, with something typed it queues
  (`➤`); empty, it is the stop button it always was (`◼`). Stopping drops the backlog with the
  turn — stop means stop.

### Window controls you can actually reach, and a session that feels immediate (2026-07-29)

- **The minimize button was being drawn and then clipped away.** The per-window controls
  lived inside `#tbnative`, which is `overflow-x:auto` — so the popup was rendered and
  silently cut off by the scroll container. That is what "minimize doesn't work" was: not
  a missing feature, an invisible one. The controls (minimize · maximize · full screen ·
  close) now live in a fixed-position element on the desktop, verified on screen and
  hit-tested so a click lands on the button rather than on whatever is over it.
- **Minimize from the window's own title bar.** Right-click a native title bar to minimize,
  middle-click to close. An app's *own* minimize button still cannot work — sway does not
  implement `xdg_toplevel.set_minimized`, so the request never arrives — but the title bar
  is ours to bind, and this is the real thing.
- **Window controls respond immediately.** The server answers in about two milliseconds;
  the sluggishness was a hard-coded 150 ms wait before redrawing, plus no optimistic
  update, so the tile sat unchanged through the whole round trip. State is applied to the
  tile first and the request goes out behind it; the compositor event that follows
  reconciles anything guessed wrong.
- **Apps launch straight from their `Exec` line.** We already parsed the .desktop file, so
  spawning `gtk-launch` to read the same file again was latency for nothing. Measured
  launch-to-window is now ~97 ms. Terminal and DBusActivatable entries still go through
  `gtk-launch`, which they need.

### Getting the machine back, and desktops that mean something (2026-07-29)

- **Lock and suspend no longer strand you.** swayidle was told what to do when the screen
  goes away but nothing about coming back: it had `before-sleep` and `lock` hooks and
  neither `after-resume` nor `unlock`. So a resume left the outputs powered off and the
  shell unfocused — a black screen with no way to the desktop. Both hooks now power the
  outputs on and call `/api/shell/wake`, which re-anchors the desktop, focuses it and
  repaints the things that go stale after hours asleep. swayidle also moved into its own
  script (`~/.local/bin/agentos-idle`): `swaymsg reload` can now actually restart it —
  with `exec` the old daemon kept running with the old arguments and an idle-timeout
  change silently did nothing — and the lock command's quotes can no longer break it.
- **Desktops move external windows.** An AgentOS desktop is now a real sway workspace, so
  switching carries the desktop with you and leaves the apps where you put them. They
  used to appear on every desktop because the two ideas of "desktop" were unrelated.
- **Alt-Tab shows you something.** It was a single keypress that just switched. It is now
  a compositor *mode*: hold Alt and the desktop comes forward with a switcher — the
  AgentOS desktop plus every window, real icons — Tab moves the selection, releasing Alt
  commits, Escape cancels. That is the only way to show an overlay while a native window
  is on top.
- **Ctrl+Space actually comes forward now.** Two bugs on top of each other: `anchor_shell`
  runs on every window event and does `floating disable`, so it dropped the desktop back
  behind the apps the instant it was raised; and the raise was four separate sway commands,
  which let the client ack its remembered floating size before the resize landed — the
  desktop came forward at half width. It is one chained command now, and anchoring stands
  aside while the desktop is deliberately summoned.
- **No more "press and hold Esc".** Raising by full screen made Chromium believe the *page*
  had gone full screen, so it flashed that bubble on every summon. Floating the desktop and
  sizing it to the output looks identical and says nothing.
- **The menu bar follows the compositor, not the page.** It said "Task Manager" while you
  were typing in VS Code. A focused external window now owns the bar.
- **AgentOS refuses to open inside AgentOS.** It is not a window, it is a second session
  fighting this one for the screen, the notification bus and the port — so it says that
  instead of launching.
- **Native windows have title bars** (middle-click to close). Worth being straight about
  the limit: sway does not implement `xdg_toplevel.set_minimized` at all, so an app's own
  minimize button cannot work under any wlroots compositor. AgentOS provides minimize from
  the taskbar tile, the Window menu and Super+H.

### External apps are windows on this desktop (2026-07-29)

The session treated native windows as second-class: they could not be minimised, they
had no icons, Alt-Tab did nothing, and one of them covering the screen left nowhere to go.

- **The shell was being mistaken for an app.** Chromium applies `--class` only to
  XWayland, so under Wayland the AgentOS desktop arrived looking like the browser and
  matched no rule written for `agentos`. It was therefore listed in its own taskbar, and
  "Alt-Tab back to the desktop" — which searched for `app_id="agentos"` — never matched.
  The shell is now identified by its command line (the process serving our port), which
  is the one honest signal. This was the root of several of the symptoms below.
- **Minimize works.** sway has no minimise; AgentOS parks the window in the scratchpad —
  hidden but alive — and *keeps it in the taskbar*, so it can be brought back. Click a
  focused tile to put it away, click a hidden one to bring it back, exactly like an
  AgentOS window. **Super+H** minimises the focused window.
- **Alt-Tab, Super-Tab.** One ring: the AgentOS desktop, then every native window in a
  stable order (sorted by window id, because sway reshuffles tree order under you and
  that made Alt-Tab ping-pong between two windows). Ctrl+Tab switches windows while the
  desktop has the keyboard, and is deliberately left to the app otherwise — browsers and
  editors need it for their own tabs.
- **Show the desktop.** **Super+D**, the desktop right-click menu, or any native
  window's menu hides every native window and puts the keyboard back on AgentOS. This is
  the escape hatch that was missing.
- **Maximize and full screen are different things, and you get both.** Maximize fills the
  desk but leaves the menu bar reachable; full screen covers everything. Minimize,
  maximize and close also sit right on the window's taskbar tile, so they are one click
  away rather than a menu hunt.
- **Real icons.** A running window's app_id is matched against the installed desktop
  entries (including `StartupWMClass`, which is what makes "org.gnome.Nautilus",
  "nautilus" and "Nautilus" the same program) and the app's own icon is shown instead of
  its first letter.
- **External apps get a menu bar.** The focused native window puts its real name and a
  Window menu in the top bar — minimise, full screen, tile/float, move to desktop,
  close, show desktop — plus Help. We do not fake the app's own File and Edit; what is
  offered is what the window manager genuinely owns.
- **Ctrl+Space works over a native window.** The shell is the tiled base layer and sway
  paints floating windows above tiled ones, so no z-index inside the page could help:
  summoning now brings the whole desktop forward (full screen, the one state that
  outranks floating) and releasing puts it straight back underneath.
- **Screenshots from the desktop right-click** — whole screen or a region.
- **The keyring error at login.** `XDG_CURRENT_DESKTOP` was set to `AgentOS`, a name no
  other software recognises — which is why apps reported *"OS keyring couldn't be
  identified for storing the encryption related data in your current desktop
  environment"* and fell back to plain text, and why portals could not pick a backend.
  It is a colon-separated list, and it now reads `AgentOS:sway:wlroots:GNOME`. The secret
  service is also started *before* sway, so every app the session launches inherits
  `SSH_AUTH_SOCK` and `GNOME_KEYRING_CONTROL` rather than only D-Bus-activated ones.

### Every app has a widget mode (2026-07-28)

- **Two surfaces, one app.** Every built app now has a desktop surface (the whole application) and
  a **widget** surface (the one glanceable fact). Mark them `.desktop-only` and `.widget-only` and
  the OS shows exactly one — before the app's own code runs, so there is no flash of the wrong
  view. `window.appSurface` = `{mode, size, widget, desktop}` for anything that needs to branch in
  JS, and both views read the same `appData` state.
- **S · M · L, chosen while editing.** App Studio gains a size picker beside *Pin to Desktop*:
  Small (260×170), Medium (340×240) or Large (460×340). The size belongs to the *app*, not to a
  placement, so it looks the same wherever it is pinned; changing it resizes every pinned copy.
  *Preview widget* renders the widget surface at exactly that size, so "does it still read at S?"
  is answered before pinning. A widget's own right-click menu offers the three sizes too.
- **The builder builds both.** Generated apps are now required to ship a widget view — a KPI tile
  or two short lines, never a table or a form — readable and complete at S.

### A session that behaves like a session (2026-07-28)

- **External apps launch again in session mode.** "Launching…" and then nothing: the
  server is started by systemd at login, so its environment has no `WAYLAND_DISPLAY`,
  `DISPLAY` or session bus — every GUI app it spawned died the instant it tried to open
  a window. Launches now go through the compositor (`swaymsg exec`), which hands the
  child the session's own environment, and sway itself imports that environment into
  systemd and D-Bus so activated services (portals, file choosers) can open windows too.
- **The desktop fills the screen.** Chromium only applies `--class` to XWayland, so under
  native Wayland the shell arrived with the browser's own app_id and missed every rule
  written for `agentos` — leaving it floating at a default size. The shell is now found
  by its command line (the process pointed at our port) and anchored as the tiled,
  borderless base layer, with every native window floating above it.
- **Display settings.** System Settings → Displays sets resolution, refresh, scale,
  rotation and on/off per output — and the layout is written to a compositor drop-in, so
  it survives logout instead of lasting until you close the lid. (The persistence block
  was there but sat after the `return`; it never ran.)
- **Keyboard & Mouse.** A new settings tab for keyboard layout and variant, repeat delay
  and rate, tap-to-click, natural scrolling, disable-while-typing and pointer speed —
  applied to the live session immediately and kept for the next one.
- **The pieces a Wayland session is expected to have.** The generated sway config now
  starts the desktop portals (screen sharing, native file dialogs), a polkit agent, the
  secret service, your `~/.config/autostart` entries, and a removable-media agent so a
  USB stick mounts by itself. Play/pause, next and previous keys drive whatever is
  playing, volume and brightness keys are answered by AgentOS itself so the on-screen
  feedback matches, Print takes a screenshot — and a full-screen window inhibits the idle
  lock, so a film no longer gets interrupted.
- **Night light.** System Settings → Displays warms the screen between hours you choose.
  Off unless you ask for it, and it survives reinstalling the session.
- **Every window has menus.** File · Edit · View · Window · Help sit in the menu bar for
  the focused window — new window, find, screenshot, close; undo/cut/copy/paste/select
  all against whatever holds the caret; full screen, maximize, the agent panel, Spaces;
  tiling, move-to-desktop and every other open window; shortcuts, the manual, about.
  Apps add their own entries (Files: go to root, go up, copy path; Terminal: clear, copy
  selection) and they merge into the standard menus rather than replacing them. Menus are
  rebuilt when focus changes and recomputed when opened, so they always describe the app
  as it is right now.


The theme: **the agent stops being an app.** Until now the AI lived in a Chat
window; every other surface was point-and-click. Now there is always somewhere
to talk — on the desktop and inside every single application.

- **The build model is your choice, not a ranking.** App Studio used to rank models by a
  hardcoded list of names — which had no `gemini` in it, so a machine with a Gemini key
  built with a local 9B instead. That ladder is gone. Authority now runs: the model picked
  for this build → **Settings → Agent → Build model** → your default model. AgentOS never
  substitutes another model on its own, and when a build produces nothing it *asks* —
  "gemma4:12b did not produce an app. Run it again with: [model] [Retry]" — instead of
  silently switching. A model you pick also stays picked when the provider list is
  momentarily missing it ("unavailable right now" rather than a quiet reset).
- **A build no longer throws away work.** If the model writes the finished app in a
  ```html block without calling `create_app`, AgentOS builds it from that block instead
  of failing.
- **Stop the agent from anywhere.** **Ctrl+.** halts every running turn and any build,
  from any app, any window, even mid-sentence in a text field. Every surface that can
  start a turn can now stop one: the AI bubble grows a ◼ while it works, a copilot
  panel's send button becomes ◼, and an omnibar answer card shows Stop while it thinks.
  Anything queued behind the stopped turn is dropped too.
- **The agent notices its own loops.** The same tool called with identical arguments four
  times in one turn ends it: "that is a loop, not progress" — instead of quietly burning
  the whole step budget.
- **The prompt bar sits behind your windows.** It lived on top of everything, covering a
  maximized app. It now belongs to the desktop layer — a window covers it — and
  **Ctrl+Space, Ctrl+K, or a double-tap of Ctrl** summons it to the front (over full
  screen too). Esc or a click elsewhere drops it back behind your work; an answer card
  stays up until you dismiss it.
- **Arrow keys drive the desktop.** Ctrl+← / Ctrl+→ walk the desktops (wrapping),
  Ctrl+Shift+← / → carry the focused window across and follow it there, Ctrl+↑ opens
  Spaces, and Ctrl+↓ organises what's in front of you: tile → cascade → exactly back
  where they were. All seven are rows in the editable shortcut table, and they stand
  aside while you're typing — though an *empty* prompt bar no longer counts as typing,
  so the shortcuts work on a fresh desktop where the bar holds the caret.
- **Each desktop decides for itself whether it carries the deck.** Desktop 1 is the
  launcher; every other space starts clear, so windows get the whole canvas to be moved
  and arranged in. Ctrl+Shift+D (or the ▾ handle, which stays reachable on a cleared
  space) toggles the deck for the desktop you are on, and the choice is remembered
  per desktop.
- **The copilot is silent until you ask for it.** A window no longer opens with a chat
  panel attached: the ✦ fades in only on the focused/hovered window, and the panel opens
  on demand — click it, or press Ctrl+Shift+Space, which works in full screen too.
- **The prompt bar takes pictures.** Paste or drop an image into the bar, or press the ▣
  button to capture the screen, and the shot rides along with your question (thumbnails
  above the bar, up to four, downscaled so a turn stays light). Asking with no text but
  an image just asks "What do you see here?".
- **Wallpaper generation survives a rate limit.** Pinning a provider (Settings → Image
  generation) meant a Google 429 was fatal and surfaced as a bare "google429". The pinned
  provider is still tried first — now with one retry — but a rate limit or outage falls
  through to the remaining providers and the result says so ("came from the free service").
  Errors carry the API's own explanation instead of a status code, Imagen models are
  supported (`:predict`, aspect ratio) alongside Gemini's `:generateContent`, and
  Personalize shows failures in a readable dialog rather than a vanishing toast.
- **Gemini tool calls work again.** Google signs every function call with a
  `thought_signature` and rejects the *next* request with HTTP 400 if it isn't replayed
  ("Function call is missing a thought_signature… position 4"). Provider baggage on a
  tool call is now captured while streaming and echoed back verbatim with the history.
- **A saved API key is never shown again.** Keys were masked server-side but the mask
  was rendered back into an editable field. A stored secret is now a locked chip
  ("saved ••••4MNQ") with a Replace button — nothing sensitive sits in the DOM, and a
  mask can never be echoed back over the real key.
- **Desktops are spaces you can organise.** F3 (or Ctrl+↑) opens Spaces: every desktop
  as a live mini-map card at the top, the current desktop's windows scaled below.
  Drag a window onto a card — or onto a pager button — to move it; click a card to
  switch; ＋ adds a desktop and ✕ removes one (its windows move, never vanish).
- **Real window control.** Right-click any title bar for Full screen · Maximize ·
  Minimize · Tile left/right/centre · Move to Desktop N · New window · Close. Per-window
  full screen covers the menu bar and dock (Esc or F exits), and the pager now shows
  which desktops have windows, with the app names in the tooltip.
- **Settings is a real preferences app.** The endless scroll of full-width inputs is
  gone: a category rail (AI providers · Agent · Locale · Shortcuts · Voice · Appearance ·
  System), preference GROUPS as cards, and rows that read label + description on the
  left, control on the right — with proper toggle switches instead of bare checkboxes.
  Search still spans every category. Two reusable primitives (`pGroup`/`pRow`) back it,
  so other panels can adopt the same grammar.
- **App windows are opaque again.** Window bodies were translucent glass, which made a
  settings form sit unreadably on top of the wallpaper. Glass now belongs to chrome
  (bar, dock, popovers, deck); content windows are solid.
- **External apps show up in session mode.** The server is normally started by systemd
  at login, so it never inherited `$SWAYSOCK` — and the AgentOS session reuses that
  server, which therefore reported `hosted` forever and listed no native windows. It now
  discovers the compositor socket for its own user, verifies the compositor really is
  the AgentOS session (reading its environment), attaches **late** when the session
  appears, and tells the shell to re-read its capabilities. Verified against a real
  nested sway: the same server flipped hosted → de without restarting and listed a
  launched app.
- **One glass material across the shell.** The deck groups, widgets, answer cards,
  the prompt bar, the launcher list and the AI bubble all draw from a single recipe
  (`--glass-tint` / `--glass-blur` / `--glass-edge`): a translucent tint over a 30px
  saturated blur with a hairline of light along the top edge — and a matching light-mode
  variant. Desktop widgets are glass now too: an app pinned as a widget renders with a
  transparent page (`?surface=widget`), so the wallpaper reads through its content
  instead of a flat slab sitting on it.
- **AgentOS knows where and when you are.** A new Locale record (country, timezone,
  language, city, units, 12/24h) is detected from the machine — timezone decides the
  country, so an en_US locale in India no longer reads as "United States" — confirmed
  by the agent during first run, editable in Settings → Locale. It reaches the agent's
  system prompt ("localise news, weather, prices, holidays, units… never assume the
  US"), renders the prompt's clock in your timezone, drives the menu-bar clock, and is
  exported into the AgentOS session (TZ/LANG/LC_*) so native apps agree with it.
- **The desktop is wallpaper again — apps live in the deck.** Bento groups of app
  tiles sit above the prompt bar and **claim the desktop space they need**: groups wrap
  into rows and grow upward from the bar (scrolling only once they hit the menu bar), so
  nothing is clipped off-screen at any window size. Rename, reorder, create ("＋ New
  group") and move apps between groups by right-click. It shows on a bare desktop and
  steps aside the moment you're working in a window; Ctrl+Shift+D or the ▾ handle
  collapses it entirely and pins that choice.
- **Widgets choose where they live**: free on the desktop, as a card in the deck,
  in the strip beside the prompt bar, or shrunk into the menu bar — right-click a
  widget's header to move it.
- **An AI presence bubble sits bottom-right** whenever a turn is running anywhere
  (a copilot panel, the omnibar, a background task) and after a reply you haven't
  read; one click opens that conversation in Agent Chat.
- **Shortcuts are a table you can edit** (Settings → Shortcuts): click a binding,
  press the keys. Session-marked shortcuts are also written into the compositor,
  so they keep working while a native window holds the keyboard — Alt+Tab included.
- **Turns finish the job.** The agent no longer ends by announcing work it never did
  ("Let me fetch some top stories:") — a dangling lead-in, or a tool that failed while
  the reply stayed silent about it, gets one push for the actual deliverable. And the
  system prompt now forbids inventing credentials: a fabricated API key only ever
  returns 401, so keyless sources (RSS, public endpoints) or a connected MCP server
  come first, and a missing key is stated plainly instead of guessed.
- **Empty replies are gone.** A thinking model (qwen3.5:9b here) can spend an entire
  reply in its thinking channel and return no text and no tool call — the turn used to
  end with a silent blank bubble. The agent now retries once with thinking off and, if
  it is still empty, says so instead of showing nothing. A queued ask can also stop the
  turn ahead of it ("Stop current & send") so a wedged turn can never trap the bar.
- **Asks queue instead of being dropped.** A second question while the agent is
  busy now waits its turn (and says so) rather than bouncing off a toast.
- Agent Chat no longer opens itself at login — the prompt bar is the way in, and
  answer cards no longer dump the model's raw reasoning.
- **The omnibar is the launcher too** — the old command-palette overlay is gone,
  so there is exactly one prompt surface. Ctrl+Space / Ctrl+K / Alt+Space pops
  the bar itself (it grows, focuses, selects) with results above it; typing
  anywhere on the desktop lands in it. **Enter launches** what you named —
  asking is the default only for question-shaped input — **⇧Enter** always asks,
  and **Alt+1…9** quick-launches a result row (or the Nth dock app when the list
  is closed). Ranking is name-first, so scattered-letter noise no longer buries
  the app you typed.
- **The omnibar.** A slim glass bar floats above the dock, always. Its orb
  breathes while idle and pulses while any turn runs. Start typing anywhere on
  the desktop and the keys land in it. The intent grammar reads as you type
  (a ghost row offers "Open Terminal" / "Volume 30" — Tab accepts); Enter sends
  to the agent and the answer streams into a card that rises above the bar —
  markdown, live tool cards, inline approvals — with one-click escalation to
  the full Chat window. All omnibar turns share one persistent **Desktop
  thread**. Quick asks from the palette now route here instead of opening Chat.
- **Every app has its agent.** A ✦ button in every window's title bar slides
  open a copilot panel: a compact conversation scoped to THAT app. It knows
  what the app is showing (a per-app `context()` line — current folder, active
  settings tab, selected Studio app, live CPU numbers…), speaks with the app's
  starter prompts ("Fix my wifi", "What's eating my RAM?", "Clean up outdated
  memories"), acts through the full tool set, and the app **refreshes itself as
  the agent's tools run**. Each app keeps ONE persistent thread
  (`origin=copilot:<app>`), grouped under **Copilots** in Chat's sidebar — the
  Files agent remembers last week's conversation about your files.
- **Visible hands.** When the agent touches an app — opens it, closes it,
  generates a wallpaper, edits an app in Studio — that window and its dock icon
  glow. You watch the OS being operated.
- **Agentic empty states.** Empty panels now invite action: "No memories yet →
  ✦ Ask Aria", "Nothing scheduled → ✦ set up a useful daily schedule".
- **User-built apps get the same.** The injected runtime ships
  `appCopilot.mount({starters})` — a one-call resident agent widget (corner ✦,
  conversation panel, acts via appAgent under the app's own grants) — and the
  builder persona mounts it in every generated app by default.
- Plumbing: chat-event **sinks** let any surface render any conversation's live
  stream (Chat, omnibar cards, copilot panels — simultaneously); `run_chat`
  accepts per-surface context (sanitized, capped) appended to the system
  prompt; conversations carry an origin end-to-end; the menu-bar spinner now
  reflects every running turn, not just the visible chat.

Tests: 230 passing.

## The living-desktop release (2026-07-26)

The theme: **truly agentic, and it moves like a Mac.** Two gaps closed at once —
the desktop finally behaves like a physical place (motion, materials, real window
management), and the agent finally has hands on the whole machine (every UI
capability is now also a PDP-gated tool, the launcher routes language to actions,
and the OS can start turns of its own).

### The experience (Mac-class motion & materials)
- **UI modularized**: `ui/index.html` is now assembled from `ui/src/` (14 CSS + 32 JS
  modules) by a zero-dependency build step (`python -m agentos.ui.build`); the shipped
  artifact is unchanged in kind — one file, served as before. A test keeps it fresh.
- **Design tokens**: type ramp, spacing, radii, a 5-step elevation ladder, motion
  durations/curves, mode-flipping hairlines/scrims — and the old 27 ad-hoc font sizes /
  17 radii / 43 shadows normalized onto them. Inter (OFL) ships as the UI typeface.
  `prefers-reduced-motion` honored globally; `:focus-visible` ring; light mode
  systematized.
- **Windows are things now**: they zoom out of their dock icon on open, back into it on
  minimize/close, FLIP-animate between maximize states, lift while dragged, and snap to
  edges (halves/quarters, top = maximize) with a live preview ghost. 8-way resize handles
  replace the browser's corner grip. Files & Terminal are multi-instance ("New window"
  in the dock menu). z-order renormalizes; the switcher stays macOS-style (icons).
- **The dock magnifies** — continuous neighbor falloff under the pointer — and bounces
  on launch. It auto-hides under a focused maximized window (bottom-edge peek restores).
- **Exposé** (F3 / Ctrl+↑): every window on the desktop, live, FLIP-scaled into a grid.
  Virtual desktops slide instead of teleporting; themes crossfade via View Transitions.
- **Every popover animates from its anchor** (context menus, power menu, notification
  center, Control Center) and **`window.confirm`/`alert`/`prompt` are gone** — replaced
  by AgentOS sheets (`osConfirm`/`osAlert`/`osPrompt`) everywhere, including power
  actions and factory reset. Toasts stack properly. Quick Settings became a real
  **Control Center popover** on the tray (the app window remains available).
- The menu bar shows the **focused app's name**; power menu drops emoji for clean labels.

### Boot & identity continuity
- **The 30-second void is dead**: the session launches the renderer immediately on a
  local branded splash (`~/.agentos/boot.html`) that probes the server with an image
  beacon and hands off the moment it answers — with live status text and a named
  failure state after 90s. The in-page splash now dismisses on actual readiness
  (config + platform + setup loaded), not a 900ms timer.
- **Wallpaper continuity**: changing the wallpaper now updates the compositor
  background *and* the swaylock image live (`session.apply_wallpaper_live`) — no more
  drift until the next `install-session`.
- **swaylock is branded** (teal ring, wallpaper fill, correct error colors);
  the cursor theme is pinned (compositor + XWayland); an optional **AgentOS plymouth
  boot theme** ships as a consent-gated component (`plymouth-theme`, script install).

### Agent hands (the parity law)
- Every capability the UI has is now a tool: `desktop_state`, `control_desktop`
  (open/close/focus AgentOS apps, switch desktops, apply themes — via a new
  server↔shell command channel), `manage_window`, `list_themes`, `wifi`, `bluetooth`,
  `set_brightness`, `audio`, `power_profile`, `lock_screen`, `power_action`
  (**always asks**, even at full autonomy), `take_screenshot` (the image goes to the
  model — the agent can *see* the screen), `list_notifications`, `search_files`,
  `create_trigger`. 75 tools total, all PDP-gated.
- The system prompt now carries a live **machine-state line** (focused window, battery,
  network, volume, unread notifications) — cached, time-boxed, prompt-cache-friendly.

### Language as the primary input
- **Palette v2**: a local intent grammar turns "open terminal", "volume 30",
  "brightness 60", "make it dark", "theme nord", "lock", "screenshot", "wallpaper of a
  quiet harbor", "desktop 2", "dnd off", arithmetic — into direct actions with inline
  rows (still one keystroke from "Ask {agent}"). Misses fall through to `POST
  /api/intent` (model-classified, 6s cap) which appends a suggested action.
- **Semantic search everywhere it counts**: a lazy mtime-aware embedding index over the
  workspace + docs (`agentos/search.py`, Ollama embeddings, substring fallback) behind
  `GET /api/search`, the `search_files` tool, and a meaning-search box in Files.

### The OS initiates (proactivity)
- **Event triggers** join the scheduler: `notification` (substring/regex),
  `file_change` (mtime polling), `login`, `idle` — each with a cooldown, created by
  the user or the agent (`create_trigger`), running headless turns tagged by origin.
- **Notification intelligence**: AgentOS *is* the notification daemon in de mode, and
  now the agent reads what it hears — a gated idle-time triage pass scores importance,
  groups, and writes a **"For you" digest** pinned atop the notification center.
- **"While you were away"**: a briefing composed on login/unlock when there's material,
  delivered as a desktop card. The knowledge loop may float **at most one suggestion**
  (24h quiet after dismissal), also as a card.
- **The metric exists now**: `/api/lifecycle` reports `initiative` — % of turns
  initiated by the OS over 7 days.

### First-run & apps are agentic
- **The wizard is a conversation**: two minimal screens (name, brain), then the *named
  agent takes over* — streaming in-character lines (`POST /api/setup/say`, canned
  offline fallback) with inline choice chips for autonomy, autostart (replaced in de
  mode by "this is your desktop now"), wallpaper presets and voice. Fully offline-safe.
- **appLLM v2**: user apps get `appLLM.stream`, `appChat(.stream)`, `appAgent` (a
  5-step tool loop under the app's own principal), and `appContext()` — all app-token
  authed and PDP-enforced. The builder persona teaches the new floor: stream anything
  user-visible; Quick Notes reference app updated to match.

Tests: 221 passing (build freshness, tool parity, proactivity gates, semantic search,
setup/appLLM v2, plus the whole existing suite).

## Boot-to-AgentOS release (2026-07-25)

The theme: goodbye GNOME. AgentOS installs as a real **Wayland login session** — its own
compositor engine, window management, settings, notifications and lock screen — while
staying 100% non-destructive: your existing desktop is one logout away, and hosted mode
is unchanged.

### The platform layer (one UI, four backends)
- New `agentos/platform/` — a capability contract (`windows.manage`, `net.wifi.join`,
  `brightness.set`, …) with four backends: `linux_de` (AgentOS **is** the session),
  `linux_hosted` (today's guest mode, behaviour-identical), `macos`, `windows`.
  `host.py` is now a thin facade; every existing endpoint keeps its exact shape.
- The UI never asks "what OS?" — it loads **`GET /api/platform`** once and renders per
  capability. Unavailable controls grey out with a sentence explaining why and, where an
  optional component would fix it, an Install… button.
- Run modes `de` / `hosted` / `kiosk`, auto-detected from how the session was started
  (`AGENTOS_SESSION` + `SWAYSOCK`), pinnable via `desktop.mode` / `agentos session mode`.

### The Wayland session
- `agentos install-session` now installs a **Wayland session** (sway as the invisible
  compositor engine — no bar, no keybinds, MIT-licensed) selectable at the login screen;
  `--x11` keeps the legacy kiosk; `--remove` uninstalls. The generated session starts the
  server *inside* sway so it inherits `$SWAYSOCK` and knows it owns the desktop.
- `agentos install-session --autologin`: true boot-to-AgentOS — display manager disabled,
  tty1 auto-login into the session. Prints the escape hatch (Ctrl+Alt+F3 →
  `--remove --autologin`) before touching anything; refuses over SSH without `--force`.
- Idle & lock: swaylock themed with your wallpaper; swayidle locks after
  `desktop.idle_lock_secs`, blanks outputs, locks before sleep, answers the ⏻ menu.

### Real window management on Wayland
- New `agentos/compositor.py` — sway/i3 IPC client: list/focus/close/float windows, move
  between workspaces, configure displays (mode/scale/rotation/enable), subscribe to
  events. Replaces the wmctrl dead-end that Wayland killed.
- The taskbar switches from 3-second polling to **compositor events**; right-click a
  native window for focus/float/move-to-desktop/close.
- New endpoints: `/api/windows/move`, `/api/windows/floating`, `/api/wm/workspaces`,
  `/api/wm/outputs`.

### System controls without gnome-control-center
- New `agentos/hostctl/` speaking **D-Bus** (dbus-fast, MIT — new dependency) to the
  distro's own daemons: NetworkManager (wifi **scan/join/forget**, airplane), BlueZ
  (**pair/connect/trust/remove**, device battery), UPower + power-profiles-daemon,
  logind (lock/suspend/brightness — no sudo, no prompts), PipeWire (`pw-dump`/`wpctl`:
  output/input switching, per-app volume), sysfs+logind+ddcutil brightness.
  Wifi passphrases travel over the bus, never a command line.
- New **System Settings** app: Network, Bluetooth, Displays, Sound, Power, Session &
  Mode, Components. Quick Settings rebuilt around capabilities (brightness sliders,
  output picker, power profiles, DND). All new control endpoints are app-blocked via the
  privilege guard.

### Notifications
- New `agentos/notifications.py` claims `org.freedesktop.Notifications` **in DE mode
  only** (DO_NOT_QUEUE — it can never fight GNOME for the name in hosted mode): native
  apps' notifications arrive as toasts + a new bell/notification center with
  do-not-disturb (critical urgency cuts through).
- Screenshots: `POST /api/screenshot` (grim/slurp, full or region) → `<workspace>/Screenshots`.

### Packaging with a licence gate
- New `packaging/audit-licenses.sh`: build-time assertion that everything shipped is
  permissive (MIT/BSD/Apache/ISC). It caught real ones: wl-clipboard is GPL-3 (dropped
  from Depends), xdg-desktop-portal is LGPL (demoted to interface-only). Generates the
  apt-dependency table in `THIRD_PARTY_NOTICES.md`.
- New `packaging/build-desktop-deb.sh` → **`agentos-desktop`**, a 4KB additive
  metapackage: Depends strictly permissive (sway stack), Recommends the distro's GPL
  daemons, Suggests the rest. postinst changes nothing about the default session.
- New `agentos/components.py` + Store-style consent flow (`/api/components`): what we
  can't ship (chromium is snap-only; ddcutil, wl-clipboard, power-profiles-daemon are
  copyleft) is offered with its licence shown, installed only on an explicit yes
  (sudo -n → pkexec → hand you the exact command).

### Guided installers for Linux, macOS and Windows
- One downloadable installer per OS, each a wizard that decides where AgentOS goes and
  how it starts — and that **offers what the system doesn't have yet** (Python, a shell
  renderer, the sway session stack, Ollama, bubblewrap, git, node…), installing each
  missing piece only when picked:
  - **Linux** `AgentOS-Setup-<ver>-linux-x86_64.run` — self-extracting (no makeself
    needed), whiptail wizard with plain-prompt and `--unattended` fallbacks; system
    (.deb) or user (`~/.local`) install; components include the login-screen session
    and boot-to-AgentOS (with the double-confirm + escape hatch).
  - **macOS** `AgentOS-Installer-<ver>.command` — double-clickable, native osascript
    dialogs; missing Python routes through Apple's Command Line Tools prompt; plus
    `packaging/macos/build-macos-pkg.sh` for the real `.pkg` choices wizard (runs on a
    Mac; core + open-at-login choices, repair.sh for the no-Python case).
  - **Windows** `packaging/windows/agentos.nsi` — NSIS MUI2 wizard (licence,
    components: Start Menu / desktop shortcut / start-at-sign-in / Ollama, directory,
    finish-and-launch), cross-built from Linux with `makensis`; `bootstrap.ps1` finds
    Python 3.10+ or installs it via winget / python.org, builds the venv, writes
    console-free launchers; per-user install, no UAC; uninstaller keeps `~/.agentos`.
- `packaging/build-all.sh` builds everything the current machine can and says exactly
  what was skipped and why. Install-time wizards own placement/startup choices; the
  existing first-launch wizard keeps owning product setup (name, model, autonomy).

### Doctor, docs, tests
- `agentos doctor` gained a desktop section: run mode, session entries, sway +
  `$SWAYSOCK`, renderer, NVIDIA `nvidia-drm.modeset`, and each D-Bus backend.
- New `docs/desktop-environment.md` (modes, install, autologin + escape hatch,
  architecture, licence policy, honest limits); updates across installation/desktop/
  troubleshooting docs.
- 60 new tests: platform contract (every backend answers every capability, with a reason
  when unavailable), session generation + autologin safety rails, compositor IPC against
  a fake sway serving the real wire protocol, hostctl parsers, the notification daemon
  over a real private D-Bus (which caught the request_name queueing bug), and the
  component consent mechanics.

Deferred, honestly: an on-screen keyboard for native apps (needs an MIT
`zwp_virtual_keyboard_v1` client), PIN-confirmation bluetooth pairing (needs a pairing
agent), and the AgentOS-rendered lock screen (`ext-session-lock-v1` — the natural first
piece of an in-house compositor).

## Unreleased — the app-store & IO-gates release (2026-07-24)

The theme: the store discovers the world's MCP ecosystem, and permissions learn *where*
a call comes from — plus the desktop grows real session controls.

### App Store = MCP discovery
- **Store → Discover** searches the public MCP registry (registry.modelcontextprotocol.io):
  thousands of community servers, normalized into one-click installs (npm→`npx`,
  PyPI→`uvx`, remote→`http` incl. header templates like `Bearer {key}`; results deduped
  across published versions). Nothing installs silently — every install goes through a
  "discovered X, build around it?" consent step; servers whose required keys aren't
  supplied are written **disabled** with placeholders.
- **Search is as-you-type and instant**: the upstream registry API takes 15-25s per
  request, so the whole catalog (`version=latest`) is synced into a local index in the
  background — saved page-by-page to `~/.agentos/mcp_index.json`, refreshed daily — and
  searches run against it in ~1ms. While the first sync runs, the Discover tab shows
  results growing ("indexing the registry — N servers so far…") and re-queries on a
  timer; stale keystroke requests are aborted.
- Agent tools to match: `discover_mcp_servers(query)` (read-only) and the approval-gated
  `install_mcp_server(registry_name, env)` — the agent proposes, the user disposes.
- **MCP Registry** (`mcp_registry` table, `GET /api/mcp/registry`): every installed server —
  discovered, manual (`add_mcp_server`), or app-package prerequisite — becomes a first-class
  record: origin, package info, status, doc.
- **Auto-generated documentation**: each registry entry gets a manual page under
  `~/.agentos/docs/mcp/<name>.md`, served into the **Docs** app alongside the built-in
  manual and refreshed with the live tool list when the server connects. 📖 buttons in the
  MCP app jump straight to it.
- After a Discover install, the Store offers to **build an AI-native app around the new
  server** in App Studio, permission manifest pre-scoped to `mcp.use · mcp:<name>/*`.

- **Deep discovery — when the registry isn't enough, the system widens the net**:
  sparse results auto-trigger a parallel sweep of npm and GitHub (deduped against the
  registry). npm finds install like any other server (`npm:<package>`, verified against
  the npm registry at install time); GitHub-only repos get a **🤖 Set up with AI**
  button — the agent reads the repo, derives the run command and keys, and connects it
  via `add_mcp_server`, approval-gated end to end. The `discover_mcp_servers` tool does
  the same widening on its own.
- **Apps are renameable**: `PUT /api/apps/{id}` (name/icon/description; id — and with
  it data, versions, grants, widgets — stays put), a ✏️ on every App Studio row, and a
  right-click menu on user-app desktop icons (Open · Rename · Edit in Studio · Delete).
- Store-triggered wrapper builds now ask for a **compact single-screen MVP** (local
  models were streaming multi-hundred-line suites for minutes, which read as hung).

- **Professional builds — a design system every app gets for free**: an OS-matched
  stylesheet (cards, rows, responsive grids, KPIs, tables, buttons, empty states,
  spinner) is injected into every app page (top of `<head>`, so an app's own CSS still
  wins). The App Builder now composes with those classes instead of inventing layout
  CSS — the thing weak local models are worst at — under hard rules (no absolute/fixed
  layout, no rotated text, no stretched buttons, labels on every input), and the build
  linter flags violations into the repair pass.
- MCP stdio noise fix: servers that print banners/console.table to stdout no longer
  spam a traceback per line ("Failed to parse JSONRPC message") — the stream
  self-recovers and that specific noise is filtered.

### Permissions: IO gates (surface scoping)
- Every turn/tool call now carries its **surface** — `gui`, `tui`, `telegram`, `api`,
  `task` — wired through the web desktop, TUI, Telegram bridge, scheduler and `/api/tool`.
- Grants gain a `surfaces` scope (default `*`): a rule permitted on all surfaces flows
  everywhere; a scoped rule only applies on its gates. Consent that exists only for other
  surfaces ⇒ the call is **denied with rule `io-gate`** and logged (policy + error entries).
- Permissions app: ⛩ gate badges on every rule (click to rescope) and an IO-gates picker in
  the Attach composer; `POST/PUT /api/grants` accept `surfaces`.

### Telegram channels
- The bridge now receives **channel posts** (`channel_post` updates): add the bot to a
  group or as a channel admin and the chat registers in the Telegram app — blocked until
  you permit it there, like every other chat. Telegram is a first-class IO gate.

### Desktop as the DE
- **Power menu (⏻) in the menu bar**: lock, restart AgentOS, suspend, log out, restart,
  power off — confirmed in the UI, executed via `loginctl`/`systemctl` (macOS: `pmset`/
  System Events) through `POST /api/power`. Apps are hard-blocked from it; the agent's
  shell still cannot shutdown/reboot. First step toward booting straight into AgentOS.
- **AI-native by default**: the App Builder persona now requires a real `appLLM` feature in
  every app it ships, and store templates lead by example (Quick Notes gained AI
  summarize/tidy on the natively selected model).

## Unreleased — the lifecycle release (2026-07-14)

The theme: from prototype to product. Chat and builds are now *reliable*, the full
Train · Test · Operate · Build · Ship · Manage lifecycle lives under one roof, and the OS
can check its own environment.

### Reliability (the "it hangs" class is gone)
- Chat turns and App Studio builds are **global and reconnect-safe**: events broadcast to
  every client, a `state_sync` on (re)connect re-attaches a reloaded page to running work,
  and every turn/build is guaranteed a terminal event on every exit path.
- **Real cancellation**: Stop first asks nicely, then cancels the task — which closes the
  provider's HTTP stream, the only thing that interrupts a model still evaluating a prompt.
- **First-token watchdog + heartbeats**: while a local model loads/evaluates, the UI shows
  "waiting for the model — Ns" instead of dead air; after a configurable timeout it fails
  loudly (`first_token_timeout`, default 180s).
- **Prompt-cache fix**: the timestamp moved from the first line of the system prompt to the
  last — local models no longer re-evaluate the entire (large) prompt every turn.
- **Ollama options**: explicit `num_ctx` (default 24576) instead of the silent 2–4k default;
  per-request `keep_alive` (default 30m) so a server-wide `OLLAMA_KEEP_ALIVE=-1` can't pin
  models into VRAM forever; optional thinking-channel switch.
- SQLite hardened: WAL + busy_timeout. Pre-bind port check: a second instance exits cleanly
  *before* spawning services (no more crash-loop wars); systemd units get restart backoff.

### App Studio v2
- **Truncation detected and handled**: providers surface finish reasons; text output cut at
  the token limit auto-continues (bounded); truncated tool-call JSON returns actionable
  guidance instead of a silent retry loop; Anthropic `max_tokens` is configurable (32k for
  builds) instead of hardcoded 8k.
- **Completeness validation before install**: structural checks (unclosed tags/scripts,
  content after `</html>`, JS leaking as visible text) gate every generated app, feed one
  repair pass, and anything unfixed ships as an explicit warning — never a silent success.
- **Local-model build mode**: Ollama models build without tool-calling (several local
  templates silently swallow large tool payloads) — output contract + `​```html` extraction +
  validation; announcement-only replies get one direct nudge; failure-retry only ever
  escalates to a *cloud* model (never a bigger local one).
- Timeouts are reported as timeouts (not "cancelled"); failed tool calls are visible in the
  build log; builds survive reloads via `GET /api/build/status`.

### The lifecycle
- **Mission Control** app: all six pillars — Train, Test, Operate, Build, Ship, Manage — one
  live screen with deep links (`GET /api/lifecycle`).
- **Train**: TrainForge integrated as a managed loopback service + the **Train** desktop app
  (datasets, LoRA fine-tuning, live metrics, model endpoints, HF publishing) + five `train_*`
  agent tools incl. Autopilot.
- **Test**: a real pytest suite (`tests/`), a `run_tests` agent tool, and a **test gate on
  self-modification** — the OS refuses to restart onto source that fails its own tests.
- **Ship**: structured git tools (`git_status/log/diff/init/commit/branch/remote/push/pull/
  clone`), GitHub PAT integration (Settings → GitHub; token env-injected, never logged),
  `export_app_to_git` (app → project folder → repo → GitHub), and `git` removed from the
  blanket-safe shell list (read-only subcommands stay free; pushes/resets ask).
- **`agentos doctor`**: port conflicts, duplicate instances, crash-looping units, Ollama
  reachability/VRAM pinning/network exposure, DB integrity, companion checks.

### Companion agents, self-healing, auto-fetch
- **Hermes integration** — AgentOS interoperates with a local Hermes install: `hermes_status`,
  `hermes_ask` (delegate a task to Hermes like a cross-product subagent), and `hermes_send`
  (deliver through any platform Hermes is paired with — WhatsApp/Slack/Discord/Signal),
  surfaced in Mission Control's Operate lane.
- **Hermes as a wrapped engine** — AgentOS is now a control surface over Hermes, not just an
  interop layer:
  - **Engine selector in chat** — the model dropdown offers "🜁 Hermes agent"; picking it routes
    that conversation's turns to Hermes (with AgentOS's working indicator, cancellation, and
    persistence) instead of the built-in Aria agent. It's a per-turn choice, never persisted as
    the global default (background tasks keep their real model).
  - **Download from inside AgentOS** — the new **Hermes app** downloads Hermes (MIT, from
    `hermes.repo`), provisions its venv, and symlinks the CLI, streaming progress.
  - **Config editor** — read/edit/save `~/.hermes/config.yaml` in the Hermes app (models,
    providers, toolsets, personalities), YAML-validated before save with a `.bak` kept; API keys
    in `.env` are never shown or touched. Gateway start/stop and update controls too.
  - Added PyYAML as a dependency so config edits are validated, not silently accepted.
- **TrainForge auto-fetch** — if the training service isn't on disk, the Train app (and the
  agent) clones it from `trainforge.repo` and provisions it via `run.sh` (venv + deps + GPU
  stack), with live download/install progress in the UI. Configured path that's gone empty
  falls back to detection/fetch instead of erroring.
- **`agentos doctor --fix`** — auto-remediates the safe items: stops a crash-looping unit,
  releases VRAM-pinned Ollama models, sets the DB to WAL; prints exact sudo steps for the
  rest (Ollama `0.0.0.0` exposure). Doctor now also reports Hermes and the fetchable Train
  service, and suggests `--fix` when it finds something.

### macOS
- **Folder sandbox on macOS** — `run_command` is now jailed on macOS too, via `sandbox-exec`
  (writes confined to the workspace + tmp/caches; parity with bubblewrap's guarantee that the
  agent's shell can't modify files outside the workspace). Previously macOS had no bwrap so
  commands ran unjailed.
- **Chat liveness** — a running turn always shows motion: an elapsed-time "working" indicator
  between and after tool calls, and streamed text forces a compositor repaint — fixing the
  macOS symptom where a reply only appeared after switching chats/tabs. Model heartbeats now
  render even once the assistant bubble exists.
- `/api/system` (Task Manager, TUI System tab) is now cross-platform: sysctl/vm_stat/`ps -r`
  on macOS instead of `/proc/stat`/`/proc/meminfo`/GNU ps — the TUI no longer crashes with
  "no such file or directory /proc/stat" on Mac.
- MCP servers now spawn reliably from GUI-launched instances (macOS LaunchAgents, Linux
  systemd): `npx`/`uvx` are resolved over an extended PATH (Homebrew, nvm, ~/.local/bin,
  pnpm, bun, cargo) and child processes inherit it; a missing runtime produces a clear
  "install node/uv" error instead of a silent failure.

### Docs & TUI
- New guides: lifecycle, training, git & shipping, TUI, security/threat model.
- TUI chat now streams (line-by-line), shows model heartbeats and failed tool calls, and
  filters the broadcast stream correctly.
