# AgentOS as your desktop (the session UI)

There are three ways to run AgentOS, and they are the same program:

| | |
|---|---|
| **In a browser** | a window on macOS, Windows or Linux. Nothing extra to install. |
| **In a terminal** | `agentos tui` — for a server or a headless Pi. |
| **As your Linux session** | AgentOS *is* the desktop. This page. |

---

## What changed, in one picture

The desktop used to be drawn in a Chromium **window**. A window is a peer of
every other window, so "the desktop is behind the apps" had to be faked — the
shell was pinned as the only tiled window, apps were forced to float above it,
and bringing the desktop forward meant resizing it to the whole screen and
putting it back afterwards. Every one of those is a trade, and while a trade is
in flight the stacking order is wrong. That is what *"it launched the app behind
the desktop"* and *"it's always on top"* both were.

Wayland already has the right answer, and it is not a trick. A **layer surface**
is not a window; the **background layer** is below every ordinary window by
definition. So the desktop goes there:

```
┌──────────────────────────────────────────────┐
│  AgentOS menu bar        ← reserved band     │  no app can cover this
├──────────────────────────────────────────────┤
│                                              │
│   native app windows                         │  ← ordinary windows,
│   ┌───────────────┐                          │    above the desktop
│   │ LibreOffice   │   AgentOS windows        │    because that is what
│   └───────────────┘                          │    "above" means here
│                                              │
│   the AgentOS desktop  ← BACKGROUND layer    │
├──────────────────────────────────────────────┤
│  prompt bar + dock       ← reserved band     │  no app can cover this
└──────────────────────────────────────────────┘
```

Nothing is raised or lowered, ever. A maximised app stops at the edges of the two
reserved bands, exactly as it stops above the panel in GNOME or KDE — because it
is the same mechanism (layer-shell *exclusive zones*).

Measured on a 1600×900 screen: a full-screen native window occupies y=30 to
y=770. The 30px above it is the AgentOS menu bar; the 130px below is the prompt
bar and dock. Both stay visible and clickable.

---

## Turning it on

```bash
sudo apt install sway swaybg swayidle swaylock grim slurp        # the compositor engine
sudo apt install python3-gi gir1.2-gtk-3.0 \
                 gir1.2-gtklayershell-0.1 gir1.2-webkit2-4.1     # the desktop surface
agentos install-session                                          # add it to the login screen
```

Then log out and pick **AgentOS** at the login screen. Your existing desktop is
untouched — switching back is logging out and picking Ubuntu again.

`agentos install-session` tells you which of the two desktops you are going to
get before it writes anything, and prints that second apt line if it is missing.
`agentos doctor` says the same at any time. The one-command installer offers both
groups (and checks you are online first, because all of it downloads).

**Why these are separate installs.** AgentOS ships and redistributes none of them.
gtk-layer-shell is MIT, but GTK, PyGObject and WebKitGTK are LGPL, and the rule
here is that what AgentOS *depends* on stays permissive. So they are asked for —
in the installer, in `install-session`, and in **System Settings → Components** —
with the licences in view. See [security & licensing](security.md).

**Without them it still works.** The session falls back to drawing the desktop in
a Chromium window, which is what it did before. Everything functions; the
stacking order is arranged rather than true. `agentos doctor` tells you which one
you are on.

---

## What you get that a browser window cannot give you

**Native apps are normal windows.** Launch LibreOffice or a terminal from the
deck's *System apps* group; it appears above the desktop, with a title bar, in
the AgentOS taskbar, and the menu bar follows its focus.

**Window management, all of it.** Move, resize, minimise (the compositor has no
minimise of its own — AgentOS parks the window and keeps it in the taskbar),
maximise, full screen, move between desktops, and snap:

| | |
|---|---|
| Snap halves / quarters | Window menu → *Snap left half*, *top right*, … |
| Tile, float, layouts | `Super`+`T` float, `Super`+`E`/`W`/`S` split/tabbed/stacked |
| Resize by keyboard | `Super`+`R`, then the arrows |
| Workspaces | `Super`+`1`…`6`, `Super`+`Shift`+`n` to carry a window |
| Minimise / desktop / full screen | `Super`+`H` / `Super`+`D` / `Super`+`F` |
| **Session menu** | `Ctrl`+`Alt`+`Delete` — lock, log out, restart, shut down |
| Switch windows | `Alt`+`Tab` (held, with an on-screen switcher) |
| End the session | `Ctrl`+`Alt`+`Backspace` |

Snapping uses the compositor's *usable* area, so a snapped window lands between
the menu bar and the dock rather than underneath them.

**Installing applications.** *Applications → Get apps…* searches the machine's
own catalogue — `appstreamcli` for real applications with summaries, flatpak,
or apt — and installs with the command shown to you first. Flatpak is preferred
where available because `--user` needs no password at all. AgentOS mirrors
nothing and bundles nothing; it asks the package manager you already have.

Installing is **only allowed from the machine itself**, even with a valid remote
session. A phone connected to your desktop is a viewer of it, not its
administrator.

**The rest of a session.** Screen lock and idle blanking (swaylock/swayidle),
night light, screenshots, display and input settings, removable media, desktop
portals for screen sharing and native file dialogs, media and brightness keys,
notifications, and the user's own autostart entries.

---

## Multiple monitors

The desktop surface is created on the output the compositor gives it, and the
reserved bands are per-output. A second monitor shows native windows and the
wallpaper but not a second copy of the desktop chrome. Being honest about this
rather than pretending: it is a known limitation, not a design.

---

## If something looks wrong

| | |
|---|---|
| `agentos doctor` | says which desktop you are on, what is missing, and the exact line to fix it |
| Desktop in a Chromium window | the layer-shell stack is not installed — see *Turning it on* |
| Apps have no title bar or controls | the compositor config predates your AgentOS build; `agentos doctor --fix` |
| `Ctrl`+`Alt`+`Delete` | the session menu. It is **bound on purpose**: left unbound, the kernel's own handler answers it and `ctrl-alt-del.target` is an alias for `reboot.target`, so the machine reboots instantly with nothing saved and nothing asked. If the desktop is not responding, the compositor puts the same choices on screen itself |
| `Ctrl`+`Alt`+`Backspace` | ends the session immediately, without asking — the emergency hatch, for when nothing can ask |
| `Ctrl`+`Alt`+`F3` | a raw terminal, always, from the kernel — the escape hatch |

Developing on it without a monitor: `packaging/dev/sui-testbed.sh up` runs a
complete session on a headless compositor, and `shot` captures it. That is how
the numbers on this page were measured.
