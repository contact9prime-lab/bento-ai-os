# AgentOS as your desktop environment

AgentOS can be more than an app on your desktop — it can *be* the desktop. This
page covers the AgentOS login session: what it is, how to install and leave it,
how it's put together, and the licence rules that shape what it ships.

---

## The three run modes

AgentOS always knows which of three ways it is running (`agentos session` shows it):

| Mode | What it means | How you get there |
|---|---|---|
| **hosted** | AgentOS is a window on your existing desktop (GNOME, KDE, macOS, Windows). The original behaviour, still the default. | `agentos serve` / `agentos app` |
| **de** | AgentOS **is** the session: its own Wayland compositor, window management, settings, notifications and lock screen. | pick **AgentOS** at the login screen |
| **kiosk** | The older fullscreen X11 session (openbox + kiosk browser). Kept for machines still on X11. | `agentos install-session --x11` |

The mode is detected from how the session was started, and everything above it —
the API, the UI, the agent tools — adapts through one capability layer
(`/api/platform`). A control that can't work in the current mode is greyed out
with a sentence saying why, never hidden and never broken. `desktop.mode` in
config can pin a mode for testing; `agentos session mode <auto|de|hosted|kiosk>`
sets it.

**Nothing is ever migrated.** Installing the session only *adds* an entry to
the login screen. GNOME, your display manager and your default session stay
exactly as they are; switching back is logging out and picking Ubuntu.

---

## Install

The quick way, on a machine that has the sway compositor available:

```bash
sudo apt install sway swaylock swayidle swaybg grim slurp xdg-desktop-portal-wlr
agentos install-session          # stages user files, installs the session entry
```

Or install the packaged version, which pulls that stack in automatically:

```bash
./packaging/build-desktop-deb.sh
sudo apt install ./packaging/dist/agentos-desktop_<version>_all.deb
```

Log out, click the gear on the login screen, pick **AgentOS**. The shell needs
a chromium-family browser to draw itself; if none is present the session says
so on a fallback screen (`sudo snap install chromium` fixes it — see
[Optional components](#optional-components) for why it isn't bundled).

What actually got installed:

- `/usr/share/wayland-sessions/agentos.desktop` — the login-screen entry (the
  only root-owned file).
- `~/.local/bin/agentos-session-wayland` — marks the session
  (`AGENTOS_SESSION=1`) and execs sway.
- `~/.config/agentos/sway.conf` — generated compositor config: no bar, no
  tiling keymap, XWayland on, idle/lock timers, one escape keybinding. Put
  overrides in `~/.config/agentos/sway.d/*.conf`; the generated file is
  rewritten on every install.
- `~/.local/bin/agentos-shell` — runs *inside* sway: starts the AgentOS server
  (which thereby inherits `$SWAYSOCK` — that's how it knows it owns the
  desktop) and execs the renderer in kiosk mode. When the renderer exits, the
  session ends; you land back at the login screen, never on a dead compositor.

`agentos install-session --remove` deletes all of it.

## Boot straight into AgentOS

```bash
agentos install-session --autologin
```

This is the one deliberately invasive option: it disables the display manager,
auto-logs your user into tty1, and starts the AgentOS session at boot — the
machine turns on into AgentOS. Before changing anything it prints what it will
do and the escape hatch. It refuses to run over SSH unless you add `--force`.

**The escape hatch, worth memorising:** `Ctrl+Alt+F3` always gives a raw
terminal. Log in and run:

```bash
agentos install-session --remove --autologin   # restores the login screen
```

Test autologin in a VM before using it on a machine you depend on.

---

## What works in DE mode

| Area | How |
|---|---|
| Native window management | sway IPC (`$SWAYSOCK`) — list, focus, close, float, move between workspaces; the taskbar updates from compositor events, not polling. Right-click a native window's taskbar icon for the menu. |
| Displays | resolution / refresh / scale / rotation / on-off per output, live, in **System Settings → Displays** |
| Wifi | scan, join (WPA2/WPA3/open), forget, airplane mode — NetworkManager over D-Bus; passphrases travel over the bus, never a command line |
| Bluetooth | power, discovery, pair/connect/trust/remove, device battery — BlueZ over D-Bus |
| Audio | output/input device switching and per-app volume — PipeWire (`pw-dump`/`wpctl`) |
| Brightness | internal panels via logind (no root); external monitors via the optional `ddcutil` component |
| Battery & power profiles | UPower + power-profiles-daemon over D-Bus |
| Notifications | AgentOS claims `org.freedesktop.Notifications` — native apps' notifications appear as toasts and in the bell menu, with do-not-disturb. (In hosted mode your desktop keeps this job; AgentOS never fights it for the bus name.) |
| Lock & idle | swaylock, themed with your wallpaper; swayidle locks after `desktop.idle_lock_secs` (default 600), blanks outputs after `desktop.idle_screen_off_secs` (900), locks before sleep, and answers the ⏻ menu's Lock |
| Screenshots | grim/slurp — full screen or region, saved to `<workspace>/Screenshots` |
| Power menu | the ⏻ menu (lock / suspend / logout / restart / power off) via logind — no sudo, no polkit prompts |

Everything in that table is driven by capabilities: on a Mac, or hosted on
GNOME, the same UI renders and the DE-only controls grey out with the reason.

## Architecture

```
login screen (GDM)
  └─ agentos-session-wayland        AGENTOS_SESSION=1, exec sway
       └─ sway (MIT, wlroots)       invisible engine: no bar, no keybinds
            ├─ agentos-shell        starts the server, execs the renderer
            │    ├─ agentos serve   inherits $SWAYSOCK → runmode = de
            │    │    ├─ agentos/compositor.py   sway IPC: windows, outputs, events
            │    │    ├─ agentos/hostctl/*       D-Bus: NM, BlueZ, UPower, logind
            │    │    └─ agentos/notifications.py  org.freedesktop.Notifications
            │    └─ chromium --kiosk http://127.0.0.1:<port>   the shell
            ├─ swayidle / swaylock  idle + lock
            └─ swaybg               wallpaper behind everything
```

sway is an implementation detail, deliberately: everything above it talks to
`agentos/compositor.py`, so a future in-house wlroots compositor replaces one
module, not the desktop.

## Licences: what ships and what doesn't

The rule: **everything `agentos-desktop` hard-depends on is permissively
licensed** (MIT/BSD/Apache) — enforced at build time by
`packaging/audit-licenses.sh`, which fails the build if a dependency's licence
changes. Verified set: sway, xwayland, seatd, swaylock, swayidle, swaybg,
grim, slurp, xdg-desktop-portal-wlr, pipewire, wireplumber.

The GPL system daemons AgentOS *talks to* over D-Bus — NetworkManager, BlueZ,
UPower — are `Recommends:`, installed by the distro, never bundled. Speaking
D-Bus to a separate program is an interface, not linkage.

### Optional components

Useful pieces that can't be in `Depends:` (copyleft, or snap-only) are offered
in **System Settings → Components**: each shows its licence and what it
unlocks, and installs only after you say yes to exactly that. Currently:
`chromium` (snap-only on modern Ubuntu — this is why the renderer isn't
bundled), `wl-clipboard` (GPL-3), `ddcutil` (GPL-2), `power-profiles-daemon`
(GPL-3), `wmctrl` (GPL-2). A greyed-out control whose fix is a component links
straight to it.

## Troubleshooting

- **`agentos doctor`** has a desktop section: run mode, session entry, sway,
  compositor socket, renderer, and each D-Bus backend.
- **Black screen on NVIDIA:** wlroots needs `nvidia-drm.modeset=1` on the
  kernel command line. On dual-GPU machines the AMD/Intel iGPU is the smoother
  choice for the session.
- **Stale server:** if a server started under GNOME is still holding the port
  when you log into AgentOS, the session reuses it — but it will report
  `hosted` mode and window management stays off. `agentos doctor` flags this;
  restart AgentOS from the ⏻ menu to fix it.
- **Escape hatches:** `Ctrl+Alt+BackSpace` ends the session from inside;
  `Ctrl+Alt+F3` is a raw TTY regardless of what the compositor is doing.

## Known limits (honest list)

- An on-screen keyboard for **native** apps needs a `zwp_virtual_keyboard_v1`
  client we haven't written yet (the permissive-licence rule excludes the
  existing GPL ones). AgentOS's own surfaces can use the browser's input.
- Pairing bluetooth devices that demand a PIN confirmation needs a pairing
  agent — "just works" devices (headphones, mice, speakers) pair fine.
- The lock screen is swaylock's, themed with your wallpaper — a fully
  AgentOS-rendered lock UI is the first milestone of the in-house compositor.
- Screen sharing works through xdg-desktop-portal-wlr; per-window sharing
  depends on the app supporting the portal.
