"""The AgentOS login session — Linux only.

`agentos install-session` makes AgentOS selectable at the login screen. Two
variants:

    --wayland (default)  sway (MIT) as the compositor engine, AgentOS as the
                         shell. This is the real DE mode.
    --x11                the older openbox/kiosk session, kept for machines
                         still on X11.

Everything here is additive and reversible: installing writes one session file
under /usr/share/{wayland-sessions,xsessions} plus scripts in the user's own
home — the display manager, GNOME, and the default session are never touched.
Switching back is logging out and picking Ubuntu.

`--autologin` is the sole exception, and it is opt-in: it disables the display
manager and boots tty1 straight into the AgentOS session. It refuses to run
over SSH without --force, prints the escape hatch before doing anything, and
`--remove --autologin` restores the display manager.

Start order matters in the Wayland session: sway starts FIRST, then the shell
launcher (run by sway) starts the AgentOS server. The server therefore inherits
$SWAYSOCK and $AGENTOS_SESSION, which is what makes runmode.detect() report
`de` and lets the server drive the compositor over IPC. If a server is already
running (e.g. a leftover from a hosted session), the launcher reuses it — the
desktop works, but that server was started without $SWAYSOCK and will report
hosted mode; `agentos doctor` calls this out.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import config as cfgmod

APP_ID = "agentos"
IS_LINUX = sys.platform.startswith("linux")

# --- user-owned files (no root needed) --------------------------------------
# Naming note: `agentos-session` has meant the X11 kiosk script since the first
# install-session shipped, and machines exist where /usr/share/xsessions points
# at it. It keeps that meaning; the Wayland launcher gets its own name so
# installing the new session can never silently repoint an old entry at sway.
BIN_DIR = Path.home() / ".local/bin"
SESSION_SCRIPT = BIN_DIR / f"{APP_ID}-session-wayland"    # Exec target of the Wayland entry
SHELL_SCRIPT = BIN_DIR / f"{APP_ID}-shell"                # run inside sway: server + renderer
IDLE_SCRIPT = BIN_DIR / f"{APP_ID}-idle"                  # swayidle: lock, blank, and wake back up
X11_SESSION_SCRIPT = BIN_DIR / f"{APP_ID}-session"        # legacy name, still X11
SWAY_CONF = Path.home() / ".config" / APP_ID / "sway.conf"
SWAY_DROPIN_DIR = Path.home() / ".config" / APP_ID / "sway.d"
# XDG_CURRENT_DESKTOP is a colon-separated list. Ours names AgentOS first and
# then the desktops we genuinely behave like, so portals can pick a backend and
# secret-storage libraries recognise the session instead of falling back to
# plain text. See session_script_text() for the full reasoning.
DESKTOP_ID = "AgentOS:sway:wlroots:GNOME"

# --- staged copies of the root-owned files ----------------------------------
WL_STAGE = cfgmod.AGENTOS_HOME / f"{APP_ID}-wayland-session.desktop"
X11_STAGE = cfgmod.AGENTOS_HOME / f"{APP_ID}-session.desktop"

# --- root-owned targets ------------------------------------------------------
WL_SESSIONS = Path("/usr/share/wayland-sessions")
XSESSIONS = Path("/usr/share/xsessions")
AUTOLOGIN_DROPIN = Path("/etc/systemd/system/getty@tty1.service.d/agentos-autologin.conf")

PROFILE_MARK_BEGIN = "# >>> agentos autologin (agentos install-session --autologin) >>>"
PROFILE_MARK_END = "# <<< agentos autologin <<<"

# Chromium-family binaries able to render the shell, best first. Mirrors
# desktop.BROWSERS; duplicated into generated shell scripts because those run
# without Python.
RENDERERS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
             "brave-browser", "microsoft-edge", "vivaldi")

DISPLAY_MANAGERS = ("gdm3", "gdm", "sddm", "lightdm", "lxdm")


def _run(cmd: list[str]) -> tuple[bool, str]:
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _sudo_ok() -> bool:
    return _run(["sudo", "-n", "true"])[0]


def _port() -> int:
    try:
        return int(cfgmod.load_config().get("port", 8321))
    except Exception:
        return 8321


# =============================================================================
# generated files
# =============================================================================

def lock_cmd_text(wallpaper: str = "") -> str:
    """Branded swaylock invocation: AgentOS teal ring over the wallpaper (or the
    shell's base color), instead of swaylock's stock look. Plain-swaylock flags
    only — no swaylock-effects dependency."""
    style = ("--indicator-radius 84 --indicator-thickness 8 "
             "--ring-color 5eead4cc --ring-ver-color 22d3eecc --ring-wrong-color f87171cc "
             "--key-hl-color 22d3ee --bs-hl-color f87171 "
             "--inside-color 0b0d10b8 --inside-ver-color 0b0d10b8 --inside-wrong-color 0b0d10b8 "
             "--line-uses-inside --text-color e6ebf2 --text-ver-color e6ebf2 --text-wrong-color f87171 "
             "--separator-color 00000000")
    if wallpaper:
        return f"swaylock -f -i '{wallpaper}' -s fill {style}"
    return f"swaylock -f -c 0b0d10 {style}"


def nightlight_cmd_text(nl: dict | None) -> str:
    """The wlsunset invocation for the user's night-light setting, or a no-op.

    Screens that stay blue-white at midnight are the one display setting people
    notice by feeling tired, so it belongs in the session rather than in an app
    the user has to remember to start."""
    nl = nl or {}
    if not nl.get("enabled"):
        return ":"
    day = int(nl.get("day_temp", 6500))
    night = int(nl.get("night_temp", 4000))
    lat, lon = nl.get("lat"), nl.get("lon")
    where = f" -l {float(lat):.2f} -L {float(lon):.2f}" if lat is not None and lon is not None else \
            f" -S {nl.get('from', '20:00')} -s {nl.get('to', '06:30')}"
    return f"command -v wlsunset >/dev/null && wlsunset -t {night} -T {day}{where} >/dev/null 2>&1 &"


def idle_script_text(port: int, idle_lock: int = 600, idle_off: int = 900,
                     wallpaper: str = "") -> str:
    """swayidle in its own script.

    It lives here rather than inline in the sway config because the lock command
    is already full of quotes; nesting it inside `sh -c '…'` breaks on the first
    apostrophe in the wallpaper path. A script also means `swaymsg reload` can
    genuinely restart it — with `exec` the old daemon kept running with the old
    arguments and an idle-timeout change silently did nothing.

    after-resume and unlock are the important part: without them, coming back
    from suspend or from the lock screen left the outputs powered off and the
    shell unfocused, which is a black screen with no way back to the desktop.
    """
    lock = lock_cmd_text(wallpaper)
    wake = (f'swaymsg "output * power on"; '
            f'curl -sf -m 3 -X POST http://127.0.0.1:{port}/api/shell/wake >/dev/null 2>&1')
    args = []
    if idle_lock > 0:
        args.append(f'  timeout {int(idle_lock)} "{lock}" \\')
    if idle_off > 0:
        args.append(f'  timeout {int(idle_off)} \'swaymsg "output * power off"\' '
                    f'resume \'swaymsg "output * power on"\' \\')
    body = "\n".join(args)
    return f"""\
#!/bin/sh
# AgentOS idle & lock — generated by `agentos install-session`. Do not edit.
# One instance only, so a reload replaces it instead of stacking daemons.
pkill -u "$USER" -x swayidle >/dev/null 2>&1
exec swayidle -w \\
{body}
  before-sleep "{lock}" \\
  lock "{lock}" \\
  after-resume '{wake}' \\
  unlock '{wake}'
"""


def sway_config_text(port: int, idle_lock: int = 600, idle_off: int = 900,
                     wallpaper: str = "") -> str:
    """The generated compositor config. Deliberately small: sway is an invisible
    engine here — no bar, no tiling keymap — and live window/output management
    arrives over IPC, not from this file."""
    lock_cmd = lock_cmd_text(wallpaper)
    idle_lines = []
    if idle_lock > 0:
        idle_lines.append(f"timeout {int(idle_lock)} \"{lock_cmd}\"")
    if idle_off > 0:
        idle_lines.append(f"timeout {int(idle_off)} 'swaymsg \"output * power off\"' "
                          "resume 'swaymsg \"output * power on\"'")
    idle = " ".join(idle_lines)
    return f"""\
# AgentOS session — generated by `agentos install-session`. Do not edit;
# put overrides in {SWAY_DROPIN_DIR}/*.conf instead.

xwayland enable
# Native windows get a title bar: something to read, something to grab, and
# middle-click to close. The AgentOS shell is stripped back to borderless when
# it is anchored, because it is the desktop, not a window.
#
# NOTE on the buttons an app draws itself: sway does not implement
# xdg_toplevel.set_minimized at all — no Wayland compositor here can make an
# app's own minimize button work. AgentOS provides minimize from the taskbar
# tile, the Window menu and Super+H instead.
default_border normal 2
default_floating_border normal 2
title_align center
focus_follows_mouse no

# One pointer everywhere (compositor + XWayland), sized for modern displays.
seat * xcursor_theme Adwaita 24

# ---------------------------------------------------------------------------
# Session environment. Without this, ANYTHING started outside sway — the
# AgentOS server when systemd launches it at login, and every D-Bus activated
# service (portals, the file chooser, screen sharing) — has no WAYLAND_DISPLAY
# and cannot open a window. That is what makes "launch Chrome" say launching
# and then do nothing.
exec_always systemctl --user import-environment WAYLAND_DISPLAY DISPLAY SWAYSOCK XDG_CURRENT_DESKTOP XDG_SESSION_DESKTOP XDG_SESSION_TYPE XCURSOR_THEME XCURSOR_SIZE SSH_AUTH_SOCK GNOME_KEYRING_CONTROL
exec_always dbus-update-activation-environment --systemd WAYLAND_DISPLAY DISPLAY SWAYSOCK XDG_CURRENT_DESKTOP XDG_SESSION_DESKTOP XDG_SESSION_TYPE

# The pieces a desktop session is expected to provide. Each is started only if
# it is installed — a missing one degrades that feature, never the session.
# polkit agent: without it, anything asking for authorisation (installing a
# package, mounting a disk, changing the network) fails silently.
exec_always sh -c 'pgrep -u "$USER" -f polkit-.*-authentication-agent >/dev/null && exit; \
  for a in /usr/libexec/polkit-gnome-authentication-agent-1 \
           /usr/lib/policykit-1-gnome/polkit-gnome-authentication-agent-1 \
           /usr/libexec/polkit-kde-authentication-agent-1 /usr/bin/lxpolkit; do \
    [ -x "$a" ] && exec "$a"; done'
# secret service: started by the session script (so apps inherit its env); here
# we only make sure D-Bus-activated services and systemd user units see it too,
# and start it as a fallback if the session was entered some other way.
exec_always sh -c 'command -v gnome-keyring-daemon >/dev/null || exit 0; \
  [ -n "$GNOME_KEYRING_CONTROL" ] || eval "$(gnome-keyring-daemon --start --components=secrets,pkcs11,ssh 2>/dev/null)"; \
  systemctl --user set-environment SSH_AUTH_SOCK="$SSH_AUTH_SOCK" GNOME_KEYRING_CONTROL="$GNOME_KEYRING_CONTROL" 2>/dev/null; \
  dbus-update-activation-environment --systemd SSH_AUTH_SOCK GNOME_KEYRING_CONTROL 2>/dev/null'
# the user's own autostart entries (~/.config/autostart), like any other session.
exec_always sh -c 'command -v dex >/dev/null && dex -a -s "$HOME/.config/autostart" >/dev/null 2>&1'
# desktop portals: what makes "Share your screen" in a browser, and the native
# file chooser a Flatpak or snap opens, actually work. Without them the button
# is there and nothing happens.
exec_always sh -c 'command -v /usr/libexec/xdg-desktop-portal >/dev/null || \
  command -v /usr/lib/xdg-desktop-portal >/dev/null || exit 0; \
  systemctl --user restart xdg-desktop-portal-wlr.service xdg-desktop-portal.service 2>/dev/null'
# removable media: plug in a USB stick and it mounts, the way it does everywhere
# else. Nothing happens at all without a mount agent.
exec_always sh -c 'command -v udiskie >/dev/null && \
  (pgrep -u "$USER" -x udiskie >/dev/null || udiskie --no-automount-notify >/dev/null 2>&1 &)'

# Hardware keys, answered by AgentOS itself so the on-screen feedback matches.
bindsym --locked XF86AudioRaiseVolume exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"volume_step":5}}' http://127.0.0.1:{port}/api/control
bindsym --locked XF86AudioLowerVolume exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"volume_step":-5}}' http://127.0.0.1:{port}/api/control
bindsym --locked XF86AudioMute exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"mute_toggle":true}}' http://127.0.0.1:{port}/api/control
bindsym --locked XF86MonBrightnessUp exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"step":10}}' http://127.0.0.1:{port}/api/brightness
bindsym --locked XF86MonBrightnessDown exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"step":-10}}' http://127.0.0.1:{port}/api/brightness
# Media keys, answered by whatever is playing (MPRIS), like any other desktop.
bindsym --locked XF86AudioPlay exec playerctl play-pause
bindsym --locked XF86AudioNext exec playerctl next
bindsym --locked XF86AudioPrev exec playerctl previous
bindsym --locked XF86AudioStop exec playerctl stop
bindsym Print exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"area":"full"}}' http://127.0.0.1:{port}/api/screenshot
bindsym Shift+Print exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"area":"select"}}' http://127.0.0.1:{port}/api/screenshot

# Input and outputs the user configured in AgentOS Settings live in the
# drop-in directory, so changing them never rewrites this file.

# Watching something full screen must not trigger the idle lock.
for_window [title=".*"] inhibit_idle fullscreen

# Window controls on a native window's OWN title bar. An app's minimize button
# cannot be made to work — sway does not implement xdg_toplevel.set_minimized,
# so the request never arrives — but the title bar is ours, and these do the
# real thing: right-click minimizes (to the scratchpad, still in the taskbar),
# middle-click closes. Super-drag moves the window from anywhere.
floating_modifier Mod4
bindsym --border --release button3 move scratchpad
bindsym --border --release button2 kill

# Wallpaper behind everything (visible if the shell ever drops fullscreen).
{f"exec swaybg -i '{wallpaper}' -m fill" if wallpaper else "exec swaybg -c '#0b0d10'"}

# The lock screen is enforced by swaylock. swayidle locks after idling, blanks
# the outputs a bit later, locks before sleep, and answers loginctl
# lock-session — which is what the ⏻ menu's Lock calls.
#
# after-resume and unlock are NOT optional. Without them, coming back from
# suspend or from the lock screen left the outputs powered off and the shell
# unfocused — a black screen with no way back to the desktop. Both now power the
# outputs on and tell the server to wake the shell (re-anchor, focus, repaint).
exec_always "{IDLE_SCRIPT}"

# Layering: the AgentOS shell is the ONLY tiled window, so it fills the screen
# as the base layer; every native app floats ABOVE it. (The old fullscreen
# approach was wrong — sway keeps fullscreen on top, so launched apps appeared
# to do nothing while sitting invisible underneath the shell.)
for_window [title=".*"] floating enable
for_window [app_id="^{APP_ID}$"] floating disable, fullscreen disable
for_window [class="^{APP_ID}$"] floating disable, fullscreen disable

# Window switching, answered by the server (which tracks focus over compositor
# IPC) so it works no matter which window has the keyboard. Alt+Tab and
# Super+Tab both cycle. Ctrl+Tab is deliberately NOT bound here — browsers and
# editors need it for their own tabs; it switches windows only while the
# AgentOS shell itself has the keyboard, where the shell handles it.
# Alt-Tab is a MODE, not a single keypress — that is the only way to keep the
# switcher on screen while Alt is held and commit when it is let go. Without it
# the desktop just jumped between windows with nothing to look at.
set $sw curl -sf -m 2 -X POST -H "Content-Type: application/json" http://127.0.0.1:{port}/api/windows/switcher -d
bindsym Mod1+Tab mode "switcher"; exec $sw '{{"action":"open","direction":"next"}}'
bindsym Mod1+Shift+Tab mode "switcher"; exec $sw '{{"action":"open","direction":"prev"}}'
bindsym Mod4+Tab mode "switcher"; exec $sw '{{"action":"open","direction":"next"}}'
bindsym Mod4+Shift+Tab mode "switcher"; exec $sw '{{"action":"open","direction":"prev"}}'
mode "switcher" {{
  bindsym Tab exec $sw '{{"action":"step","direction":"next"}}'
  bindsym Shift+Tab exec $sw '{{"action":"step","direction":"prev"}}'
  bindsym Right exec $sw '{{"action":"step","direction":"next"}}'
  bindsym Left exec $sw '{{"action":"step","direction":"prev"}}'
  bindsym Escape mode "default"; exec $sw '{{"action":"cancel"}}'
  bindsym Return mode "default"; exec $sw '{{"action":"commit"}}'
  bindsym --release Alt_L mode "default"; exec $sw '{{"action":"commit"}}'
  bindsym --release Alt_R mode "default"; exec $sw '{{"action":"commit"}}'
  bindsym --release Super_L mode "default"; exec $sw '{{"action":"commit"}}'
  bindsym --release Super_R mode "default"; exec $sw '{{"action":"commit"}}'
}}

# Window controls for NATIVE apps, so they behave like windows anywhere else.
# sway has no minimise; the server parks the window in the scratchpad and keeps
# it in the taskbar, which is what minimise actually means to a person.
bindsym Mod4+h exec curl -sf -m 2 -X POST http://127.0.0.1:{port}/api/windows/minimize -H "Content-Type: application/json" -d "{{\"id\":\"focused\"}}"
bindsym Mod4+d exec curl -sf -m 2 -X POST http://127.0.0.1:{port}/api/windows/showdesktop
bindsym Mod4+f exec curl -sf -m 2 -X POST http://127.0.0.1:{port}/api/windows/fullscreen -H "Content-Type: application/json" -d "{{\"id\":\"focused\"}}"
bindsym F11 fullscreen toggle
bindsym Mod4+q kill
bindsym Mod4+Up fullscreen enable
bindsym Mod4+Down fullscreen disable

# The one escape keybinding: end the session if the shell is ever unreachable.
# (Ctrl+Alt+F3 for a raw TTY is handled by the kernel, not by us.)
bindsym Ctrl+Alt+BackSpace exec swaymsg exit

# Shell launcher: starts the AgentOS server (inheriting $SWAYSOCK, which is how
# the server knows it IS the desktop), then the renderer. When it exits, the
# session ends — never strand the user on an empty compositor.
exec sh -c '"{SHELL_SCRIPT}" ; swaymsg exit'

include {SWAY_DROPIN_DIR}/*.conf
"""


def boot_html_text(port: int) -> str:
    """The pre-shell splash. The renderer opens this local file IMMEDIATELY —
    no blank wallpaper while the server cold-starts. It mirrors the in-app
    #boot splash exactly (same colors, mark, shimmer), probes the server with
    an image beacon (file:// pages can't fetch() localhost, but image loads
    are exempt from CORS), and replaces itself with the shell the moment the
    server answers. After 90s it names the problem instead of spinning."""
    return f"""\
<!DOCTYPE html><html><head><meta charset="utf-8"><title>AgentOS</title><style>
html,body{{height:100%;margin:0}}
body{{background:#0b0d10;color:#e6ebf2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Roboto,sans-serif;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;cursor:none}}
.mark{{width:74px;height:74px;border-radius:20px;background:linear-gradient(135deg,#5eead4,#22d3ee);
  display:flex;align-items:center;justify-content:center;color:#04211c;font-size:32px;font-weight:900;
  box-shadow:0 0 60px rgba(94,234,212,.3)}}
h1{{font-size:24px;letter-spacing:.5px;margin:0;font-weight:700}}
.bbar{{width:180px;height:3px;border-radius:3px;background:#1e242e;overflow:hidden}}
.bbar i{{display:block;height:100%;width:35%;border-radius:3px;background:linear-gradient(90deg,#5eead4,#22d3ee);
  animation:boot 1s ease-in-out infinite}}
@keyframes boot{{0%{{transform:translateX(-120%)}}100%{{transform:translateX(520%)}}}}
#st{{font-size:12px;color:#5c6577;min-height:16px;transition:color .3s}}
#st.err{{color:#f87171;cursor:auto}}
</style></head><body>
<div class="mark">▲</div><h1>AgentOS</h1><div class="bbar"><i></i></div><div id="st">starting…</div>
<script>
const URL_='http://127.0.0.1:{port}';
const t0=Date.now();let tries=0;
function probe(){{
  const i=new Image();
  i.onload=()=>location.replace(URL_);
  i.onerror=()=>{{
    tries++;
    const s=Math.round((Date.now()-t0)/1000);
    const st=document.getElementById('st');
    if(s>90){{st.textContent='the AgentOS server did not start — check ~/.agentos/session.log (Ctrl+Alt+BackSpace ends the session)';st.className='err';document.body.style.cursor='auto';return}}
    if(s>6)st.textContent='starting the AgentOS server… '+s+'s';
    setTimeout(probe,tries<20?250:1000);
  }};
  i.src=URL_+'/assets/ping.png?'+Date.now();
}}
probe();
</script></body></html>
"""


def shell_script_text(port: int) -> str:
    renderer_loop = "\n".join(
        f'  command -v {b} >/dev/null 2>&1 && {{ RENDERER=$(command -v {b}); break; }}'
        for b in RENDERERS)
    return f"""\
#!/bin/sh
# AgentOS shell launcher — runs INSIDE sway (started from sway.conf), so the
# server and renderer both inherit $SWAYSOCK and $WAYLAND_DISPLAY.
PORT="${{AGENTOS_PORT:-{port}}}"
LOG="$HOME/.agentos/session.log"

# XWayland apps (VS Code and friends) need $DISPLAY; sway normally exports it
# but a race at startup leaves it unset — and every app the server launches
# inherits THIS environment.
[ -z "$DISPLAY" ] && export DISPLAY=:0

# 1) the server. It must run INSIDE this session: a server started at login by
#    systemd holds the port but has no $SWAYSOCK, no $DISPLAY — it can neither
#    manage windows nor launch apps. Reusing it silently is how "nothing works"
#    happens, so a non-DE server on our port gets stopped and replaced.
if curl -sf -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  if ! curl -sf "http://127.0.0.1:$PORT/api/platform" 2>/dev/null | grep -q '"mode":"de"'; then
    echo "found a non-session server on port $PORT — replacing it" >> "$LOG"
    systemctl --user stop agentos 2>/dev/null
    i=0
    while [ $i -lt 40 ] && curl -sf -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; do
      i=$((i+1)); sleep 0.25
    done
  fi
fi
if ! curl -sf -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  "{sys.executable}" -m agentos serve --no-browser --port "$PORT" >> "$LOG" 2>&1 &
fi

# 2) the renderer: first chromium-family browser found.
RENDERER=""
while true; do
{renderer_loop}
  break
done
if [ -z "$RENDERER" ]; then
  swaynag -t error \\
    -m "AgentOS needs a chromium-family browser to draw the desktop. Install one (e.g. 'sudo snap install chromium'), then log in again." \\
    -Z "End session" "swaymsg exit"
  exit 1
fi

prof="$HOME/.agentos/appwindow"; mkdir -p "$prof"
echo "renderer: $RENDERER" >> "$LOG"
# Boot continuity: open the local splash instantly; it hands off to the shell
# by itself the moment the server answers.
START_URL="http://127.0.0.1:$PORT"
[ -f "$HOME/.agentos/boot.html" ] && START_URL="file://$HOME/.agentos/boot.html"
# --ozone-platform-hint=auto: native Wayland when it works, XWayland when it
# doesn't (NVIDIA setups) — both render inside our compositor either way.
# NOT --kiosk: chrome's kiosk mode forces a fullscreen surface, which sway
# keeps above everything — hiding every native app. The shell is a plain app
# window; sway tiles it alone, which IS edge-to-edge, with floats above it.
# --class names the XWayland window, --wayland-app-id the Wayland one.
exec "$RENDERER" --app="$START_URL" \\
  --user-data-dir="$prof" --class={APP_ID} --wayland-app-id={APP_ID} \\
  --ozone-platform-hint=auto --no-first-run --no-default-browser-check >> "$LOG" 2>&1
"""


def session_script_text() -> str:
    return f"""\
#!/bin/sh
# AgentOS Wayland session — Exec target of {WL_SESSIONS / (APP_ID + '.desktop')}.
# Marks the session so AgentOS knows it owns the desktop, then hands the seat
# to sway. Everything else (server, shell) is started from inside sway so it
# inherits the compositor's environment.
export AGENTOS_SESSION=1
# XDG_CURRENT_DESKTOP is a colon-separated LIST, and other software reads it to
# decide what it is talking to. "AgentOS" alone is a name nothing recognises:
# xdg-desktop-portal cannot pick a backend, and libsecret/Electron apps report
# "OS keyring couldn't be identified for your current desktop environment" and
# fall back to storing secrets in plain text. Naming the compatible desktops we
# actually behave like fixes both, and is honest — we run wlroots and provide
# the GNOME Secret Service below.
export XDG_CURRENT_DESKTOP={DESKTOP_ID}
export XDG_SESSION_DESKTOP={APP_ID}
export XDG_SESSION_TYPE=wayland
export XCURSOR_THEME=Adwaita
export XCURSOR_SIZE=24
# The secret service, started BEFORE sway so every app the session launches
# inherits SSH_AUTH_SOCK and GNOME_KEYRING_CONTROL. Started from inside sway it
# would only reach D-Bus-activated services, and browsers would still complain.
if command -v gnome-keyring-daemon >/dev/null 2>&1; then
  eval "$(gnome-keyring-daemon --start --components=secrets,pkcs11,ssh 2>/dev/null)"
  export SSH_AUTH_SOCK GNOME_KEYRING_CONTROL
fi
# Locale (Settings → Locale): timezone + language for the whole session
[ -f "$HOME/.config/agentos/locale.env" ] && . "$HOME/.config/agentos/locale.env"
LOG="$HOME/.agentos/session.log"
mkdir -p "$HOME/.agentos"
echo "=== AgentOS session $(date) ===" >> "$LOG"
# The proprietary NVIDIA driver needs two accommodations, or sway refuses to
# start and the session bounces straight back to the login screen:
SWAY_FLAGS=""
if [ -d /sys/module/nvidia ]; then
  SWAY_FLAGS="--unsupported-gpu"
  export WLR_NO_HARDWARE_CURSORS=1
  echo "nvidia driver detected: sway $SWAY_FLAGS, software cursors" >> "$LOG"
fi
exec sway $SWAY_FLAGS -c "{SWAY_CONF}" >> "$LOG" 2>&1
"""


def x11_session_script_text(port: int) -> str:
    """The legacy X11 kiosk session (runmode `kiosk`), port-aware — the old
    generator in desktop.py hardcoded 8321."""
    return f"""\
#!/bin/sh
# AgentOS desktop session (X11 kiosk) — runs AgentOS as the shell.
export AGENTOS_SESSION=1
PORT="${{AGENTOS_PORT:-{port}}}"
# 1) make sure the server is up (start one only if nothing is already listening)
if ! curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  "{sys.executable}" -m agentos serve --no-browser --port "$PORT" >/dev/null 2>&1 &
fi
for i in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null && break
  sleep 0.25
done
# 2) a minimal window manager so any native apps AgentOS launches are movable/closable
for wm in openbox matchbox-window-manager icewm; do
  if command -v "$wm" >/dev/null 2>&1; then "$wm" & break; fi
done
# 3) launch AgentOS fullscreen kiosk (this blocks; when it exits, the session ends)
prof="$HOME/.agentos/appwindow"; mkdir -p "$prof"
for b in {' '.join(RENDERERS)}; do
  if command -v "$b" >/dev/null 2>&1; then
    exec "$b" --app="http://127.0.0.1:$PORT" --kiosk --user-data-dir="$prof" \\
         --no-first-run --no-default-browser-check --class={APP_ID}
  fi
done
command -v xmessage >/dev/null 2>&1 && xmessage "AgentOS session: no chromium-based browser found."
sleep 5
"""


def session_entry_text(script: Path, wayland: bool) -> str:
    kind = "Wayland" if wayland else "X11"
    return f"""\
[Desktop Entry]
Name=AgentOS
Comment=AgentOS — your machine, with a brain ({kind})
Exec={script}
Type=Application
DesktopNames=AgentOS
Keywords=agent;ai;
"""


#: shell shortcut names the compositor can carry, mapped to sway modifiers.
#: Only these reach sway — window-management keys stay with the shell.
SESSION_ACTIONS = ("omnibar.focus", "omnibar.focus2", "chat.open", "terminal",
                   "voice", "expose")


def _sway_binding(keys: str) -> str:
    """'Ctrl+Shift+A' → 'Ctrl+Shift+a' in sway's spelling (Mod1 = Alt, Mod4 = Super)."""
    parts = [p.strip() for p in str(keys or "").split("+") if p.strip()]
    if not parts:
        return ""
    out = []
    for p in parts[:-1]:
        low = p.lower()
        out.append({"ctrl": "Ctrl", "control": "Ctrl", "alt": "Mod1", "option": "Mod1",
                    "shift": "Shift", "meta": "Mod4", "cmd": "Mod4", "super": "Mod4",
                    "win": "Mod4"}.get(low, p))
    key = parts[-1]
    key = {"space": "space", "enter": "Return", "tab": "Tab", "escape": "Escape"}.get(
        key.lower(), key.lower() if len(key) == 1 else key)
    out.append(key)
    return "+".join(out)


def write_shortcut_bindings(shortcuts: dict, port: int) -> int:
    """Generate the session keybinding drop-in and reload sway. Returns the count.

    Each binding curls /api/shell/action, which the server relays to the shell —
    so one editable table drives both the browser shell and the compositor."""
    SWAY_DROPIN_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by AgentOS (Settings → Shortcuts). Do not edit by hand.",
             "# Each binding asks the running shell to perform a named action."]
    n = 0
    for action in SESSION_ACTIONS:
        keys = shortcuts.get(action)
        if not keys:
            continue
        binding = _sway_binding(keys)
        if not binding:
            continue
        lines.append(
            f"bindsym {binding} exec curl -sf -m 2 -X POST "
            f"-H 'Content-Type: application/json' -d '{{\"action\":\"{action}\"}}' "
            f"http://127.0.0.1:{port}/api/shell/action")
        n += 1
    (SWAY_DROPIN_DIR / "shortcuts.conf").write_text("\n".join(lines) + "\n")
    _run(["swaymsg", "reload"])
    return n


LOCALE_ENV = Path.home() / ".config" / APP_ID / "locale.env"


def write_locale_env(env: dict) -> Path:
    """Persist the session locale as a sourceable env file. The session script
    sources it before exec'ing sway, so the compositor and every app launched
    from AgentOS inherit the user's timezone and language."""
    LOCALE_ENV.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by AgentOS (Settings → Locale). Do not edit by hand."]
    lines += [f'export {k}="{v}"' for k, v in sorted(env.items())]
    LOCALE_ENV.write_text("\n".join(lines) + "\n")
    return LOCALE_ENV


def apply_session_env(env: dict) -> bool:
    """Update the live session: sway's env (for apps started from now on) and
    this process (so the server's own clock agrees immediately)."""
    if not os.environ.get("SWAYSOCK"):
        return False
    ok = True
    for k, v in env.items():
        os.environ[k] = v
        good, _ = _run(["swaymsg", "exec", f"systemctl --user set-environment {k}={v}"])
        ok = ok and good
    if env.get("TZ"):
        import time as _t
        _t.tzset()
    return ok


def write_output_config(outputs: list) -> Path:
    """Persist display layout to a compositor drop-in.

    Applying a mode over IPC lasts until logout; a display setting the user made
    must survive it, exactly as it would in GNOME's Displays panel."""
    SWAY_DROPIN_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by AgentOS (System Settings → Displays). Do not edit by hand."]
    for o in outputs or []:
        name = str(o.get("name") or "").strip()
        if not name:
            continue
        parts = [f'output "{name}"']
        if o.get("enabled") is False:
            parts.append("disable")
        else:
            if o.get("mode"):
                parts.append(f"mode {o['mode']}")
            if o.get("scale"):
                parts.append(f"scale {o['scale']}")
            if o.get("transform"):
                parts.append(f"transform {o['transform']}")
            if o.get("position"):
                parts.append(f"position {o['position']}")
            parts.append("enable")
        lines.append(" ".join(parts))
    path = SWAY_DROPIN_DIR / "outputs.conf"
    path.write_text("\n".join(lines) + "\n")
    return path


def input_config_text(inp: dict) -> str:
    """Keyboard and pointer preferences — the other half of "display settings"
    that a session is expected to own."""
    inp = inp or {}
    kb, tp = inp.get("keyboard") or {}, inp.get("touchpad") or {}
    lines = ["# Generated by AgentOS (System Settings → Keyboard & Mouse)."]
    k = []
    if kb.get("layout"):
        k.append(f'    xkb_layout "{kb["layout"]}"')
    if kb.get("variant"):
        k.append(f'    xkb_variant "{kb["variant"]}"')
    if kb.get("options"):
        k.append(f'    xkb_options "{kb["options"]}"')
    if kb.get("repeat_delay"):
        k.append(f'    repeat_delay {int(kb["repeat_delay"])}')
    if kb.get("repeat_rate"):
        k.append(f'    repeat_rate {int(kb["repeat_rate"])}')
    if k:
        lines += ["input type:keyboard {"] + k + ["}"]
    t = []
    if tp.get("tap") is not None:
        t.append(f'    tap {"enabled" if tp["tap"] else "disabled"}')
    if tp.get("natural_scroll") is not None:
        t.append(f'    natural_scroll {"enabled" if tp["natural_scroll"] else "disabled"}')
    if tp.get("dwt") is not None:
        t.append(f'    dwt {"enabled" if tp["dwt"] else "disabled"}')
    if tp.get("accel") is not None:
        t.append(f'    pointer_accel {float(tp["accel"]):.2f}')
    if t:
        lines += ["input type:touchpad {"] + t + ["}"]
    return "\n".join(lines) + "\n"


def write_idle_script(port: int, idle_lock: int = 600, idle_off: int = 900,
                      wallpaper: str = "") -> Path:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    IDLE_SCRIPT.write_text(idle_script_text(port, idle_lock, idle_off, wallpaper))
    IDLE_SCRIPT.chmod(0o755)
    return IDLE_SCRIPT


def stage_nightlight(nl: dict | None) -> Path:
    """Put the night-light launcher in a drop-in so it survives the next login.

    The main config is regenerated by `install-session`; a preference the user
    set from Settings must not depend on that ever being run again."""
    SWAY_DROPIN_DIR.mkdir(parents=True, exist_ok=True)
    path = SWAY_DROPIN_DIR / "nightlight.conf"
    cmd = nightlight_cmd_text(nl)
    path.write_text("# Generated by AgentOS (System Settings \u2192 Displays).\n"
                    f"exec_always sh -c 'pkill -u \"$USER\" -x wlsunset >/dev/null 2>&1; {cmd}'\n")
    return path


def write_input_config(inp: dict) -> Path:
    SWAY_DROPIN_DIR.mkdir(parents=True, exist_ok=True)
    path = SWAY_DROPIN_DIR / "input.conf"
    path.write_text(input_config_text(inp))
    return path


def apply_dropins() -> bool:
    """Reload the compositor so freshly written drop-ins take effect now."""
    if not os.environ.get("SWAYSOCK"):
        return False
    ok, _ = _run(["swaymsg", "reload"])
    return ok


def apply_wallpaper_live(wallpaper: str | None) -> bool:
    """Propagate a wallpaper change to the live compositor + lock screen.

    The shell repaints itself over the websocket, but the compositor background
    (visible if the shell drops fullscreen) and swaylock's -i were baked in at
    install-session time — without this, the desktop and its lock screen drift
    apart until the next `agentos session install`. Called by the server on
    every wallpaper change while in de mode; silently a no-op elsewhere."""
    import subprocess
    if not os.environ.get("SWAYSOCK"):
        return False
    bg = ["swaymsg", "output", "*", "bg"]
    bg += ([wallpaper, "fill"] if wallpaper else ["#0b0d10", "solid_color"])
    ok, _ = _run(bg)
    # swayidle holds the old lock command; respawn it with the new one so the
    # NEXT lock shows the new wallpaper. Config on disk is refreshed too.
    try:
        _cfg = cfgmod.load_config()
        desk = _cfg.get("desktop", {})
        idle_lock = int(desk.get("idle_lock_secs", 600))
        idle_off = int(desk.get("idle_screen_off_secs", 900))
        SWAY_CONF.write_text(sway_config_text(
            _port(), idle_lock=idle_lock, idle_off=idle_off, wallpaper=wallpaper or ""))
        stage_nightlight(_cfg.get("nightlight"))
        # Rewrite and respawn the idle daemon from the SAME script the session
        # uses, so a live wallpaper change can never drift from what a fresh
        # login would produce — and so the wake hooks are never lost.
        write_idle_script(_port(), idle_lock, idle_off, wallpaper or "")
        subprocess.Popen([str(IDLE_SCRIPT)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        pass
    return bool(ok)


# =============================================================================
# install / remove
# =============================================================================

def stage(wayland: bool = True, port: int | None = None) -> list[Path]:
    """Write every user-owned file. Root is not needed for any of this."""
    port = port or _port()
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    cfgmod.AGENTOS_HOME.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if wayland:
        try:
            _cfg = cfgmod.load_config()
        except Exception:
            _cfg = {}
        desk = _cfg.get("desktop", {})
        wallpaper = cfgmod.AGENTOS_HOME / "wallpaper.png"
        SWAY_CONF.parent.mkdir(parents=True, exist_ok=True)
        SWAY_DROPIN_DIR.mkdir(parents=True, exist_ok=True)
        SWAY_CONF.write_text(sway_config_text(
            port,
            idle_lock=int(desk.get("idle_lock_secs", 600)),
            idle_off=int(desk.get("idle_screen_off_secs", 900)),
            wallpaper=str(wallpaper) if wallpaper.exists() else ""))
        written.append(SWAY_CONF)
        written.append(stage_nightlight(_cfg.get("nightlight")))
        written.append(write_idle_script(
            port,
            idle_lock=int(desk.get("idle_lock_secs", 600)),
            idle_off=int(desk.get("idle_screen_off_secs", 900)),
            wallpaper=str(wallpaper) if wallpaper.exists() else ""))
        SHELL_SCRIPT.write_text(shell_script_text(port))
        SHELL_SCRIPT.chmod(0o755)
        written.append(SHELL_SCRIPT)
        boot_html = cfgmod.AGENTOS_HOME / "boot.html"
        boot_html.write_text(boot_html_text(port))
        written.append(boot_html)
        SESSION_SCRIPT.write_text(session_script_text())
        SESSION_SCRIPT.chmod(0o755)
        written.append(SESSION_SCRIPT)
        WL_STAGE.write_text(session_entry_text(SESSION_SCRIPT, wayland=True))
        written.append(WL_STAGE)
    else:
        X11_SESSION_SCRIPT.write_text(x11_session_script_text(port))
        X11_SESSION_SCRIPT.chmod(0o755)
        written.append(X11_SESSION_SCRIPT)
        X11_STAGE.write_text(session_entry_text(X11_SESSION_SCRIPT, wayland=False))
        written.append(X11_STAGE)
    return written


def _install_entry(staged: Path, target: Path) -> bool:
    """Copy the staged session entry to its root-owned home, or print how."""
    if _sudo_ok():
        _run(["sudo", "mkdir", "-p", str(target.parent)])
        ok, out = _run(["sudo", "cp", str(staged), str(target)])
        if ok:
            print(f"✓ session entry   {target}")
            return True
        print(f"! could not copy the session file: {out}")
    print(f"✓ session entry   staged at {staged}")
    print("\nOne step needs root. Run this, then log out and pick 'AgentOS' at the login screen:\n")
    print(f"  sudo mkdir -p '{target.parent}' && sudo cp '{staged}' '{target}'")
    return False


def _detect_display_manager() -> str:
    for dm in DISPLAY_MANAGERS:
        ok, out = _run(["systemctl", "is-enabled", f"{dm}.service"])
        if ok and "enabled" in out:
            return dm
    return ""


def _autologin_dropin_text(user: str) -> str:
    return f"""\
# Generated by `agentos install-session --autologin`.
# Remove with `agentos install-session --remove --autologin`.
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin {user} --noclear %I $TERM
"""


def _profile_snippet() -> str:
    return f"""{PROFILE_MARK_BEGIN}
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ] \\
   && [ -x "{SESSION_SCRIPT}" ]; then
  exec "{SESSION_SCRIPT}"
fi
{PROFILE_MARK_END}"""


def _profile_has_snippet(profile: Path) -> bool:
    try:
        return PROFILE_MARK_BEGIN in profile.read_text()
    except OSError:
        return False


def _strip_profile_snippet(profile: Path):
    try:
        text = profile.read_text()
    except OSError:
        return
    if PROFILE_MARK_BEGIN not in text:
        return
    head, _, rest = text.partition(PROFILE_MARK_BEGIN)
    _, _, tail = rest.partition(PROFILE_MARK_END)
    profile.write_text(head.rstrip("\n") + ("\n" + tail.lstrip("\n") if tail.strip() else "\n"))


def _over_ssh() -> bool:
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))


def install_autologin(force: bool = False) -> bool:
    """Boot straight into AgentOS: getty autologin on tty1 + no display manager.

    This is the one deliberately invasive step in the whole feature, so it
    narrates exactly what it changes and how to get out before touching
    anything.
    """
    if _over_ssh() and not force:
        print("! You appear to be connected over SSH. Autologin changes how this machine's\n"
              "  console boots — run it at the machine, or add --force if you're sure.")
        return False
    user = os.environ.get("USER", "")
    if not user:
        print("! Could not determine the user for autologin.")
        return False
    dm = _detect_display_manager()

    print("This will make the machine boot straight into AgentOS:")
    print(f"  • tty1 logs in as '{user}' automatically and starts the AgentOS session")
    if dm:
        print(f"  • the display manager ({dm}) is disabled — the usual login screen goes away")
    print("\nEscape hatch — memorise this before rebooting:")
    print("  Ctrl+Alt+F3 opens a raw terminal. Log in and run:")
    print("    agentos install-session --remove --autologin")
    print(f"  to restore {dm or 'the login screen'}.\n")

    profile = Path.home() / ".profile"
    if not _profile_has_snippet(profile):
        with profile.open("a") as f:
            f.write("\n" + _profile_snippet() + "\n")
    print(f"✓ tty1 hook       {profile}")

    dropin_cmds = [
        f"sudo mkdir -p '{AUTOLOGIN_DROPIN.parent}'",
        f"sudo tee '{AUTOLOGIN_DROPIN}' >/dev/null <<'EOF'\n{_autologin_dropin_text(user)}EOF",
        "sudo systemctl daemon-reload",
    ] + ([f"sudo systemctl disable {dm}"] if dm else [])

    if _sudo_ok():
        _run(["sudo", "mkdir", "-p", str(AUTOLOGIN_DROPIN.parent)])
        stage_file = cfgmod.AGENTOS_HOME / "agentos-autologin.conf"
        stage_file.write_text(_autologin_dropin_text(user))
        ok, out = _run(["sudo", "cp", str(stage_file), str(AUTOLOGIN_DROPIN)])
        if not ok:
            print(f"! could not write the getty drop-in: {out}")
            return False
        _run(["sudo", "systemctl", "daemon-reload"])
        if dm:
            _run(["sudo", "systemctl", "disable", dm])
        print(f"✓ getty drop-in   {AUTOLOGIN_DROPIN}")
        if dm:
            print(f"✓ display manager {dm} disabled (re-enable: sudo systemctl enable {dm})")
        print("\n▲ Reboot to land in AgentOS.")
        return True

    print("Root is needed for the getty drop-in. Run:\n")
    for c in dropin_cmds:
        print(f"  {c}")
    return False


def remove_autologin():
    _strip_profile_snippet(Path.home() / ".profile")
    print("✓ removed tty1 hook from ~/.profile")
    dm = ""
    for cand in DISPLAY_MANAGERS:
        ok, out = _run(["systemctl", "is-enabled", f"{cand}.service"])
        if ok or "disabled" in out:
            dm = dm or (cand if "disabled" in out else "")
    if _sudo_ok():
        _run(["sudo", "rm", "-f", str(AUTOLOGIN_DROPIN)])
        _run(["sudo", "systemctl", "daemon-reload"])
        print(f"✓ removed {AUTOLOGIN_DROPIN}")
        if dm:
            _run(["sudo", "systemctl", "enable", dm])
            print(f"✓ re-enabled {dm}")
        else:
            print("! no disabled display manager found — if the login screen is missing,\n"
                  "  run: sudo systemctl enable gdm3   (or your display manager)")
    else:
        print("Root is needed to finish. Run:\n")
        print(f"  sudo rm -f '{AUTOLOGIN_DROPIN}' && sudo systemctl daemon-reload")
        print("  sudo systemctl enable gdm3   # or your display manager")


def install(wayland: bool = True, autologin: bool = False, force: bool = False):
    if not IS_LINUX:
        print("Login-screen sessions are a Linux feature. On this OS use `agentos install` "
              "for autostart, or AGENTOS_KIOSK=1 `agentos app` for a fullscreen window.")
        return
    if wayland and not shutil.which("sway"):
        print("! sway is not installed — the AgentOS Wayland session needs it.\n"
              "  Install it first:  sudo apt install sway\n"
              "  (or install the agentos-desktop package, which depends on it)")
        return

    port = _port()
    for p in stage(wayland=wayland, port=port):
        print(f"✓ wrote           {p}")
    if wayland:
        installed = _install_entry(WL_STAGE, WL_SESSIONS / f"{APP_ID}.desktop")
    else:
        installed = _install_entry(X11_STAGE, XSESSIONS / f"{APP_ID}.desktop")
    _run(["loginctl", "enable-linger", os.environ.get("USER", "")])

    if installed and not autologin:
        print("\n▲ AgentOS session installed. Log out, then pick 'AgentOS' (gear icon) at "
              "the login screen.\n  Your current desktop is untouched — switch back the same way.")
    if autologin:
        install_autologin(force=force)


def run_session():
    """Become the AgentOS Wayland session, now. This is the Exec path used by
    the packaged /usr/share/wayland-sessions entry: it (re)generates this
    user's session files — so any user on the machine can pick AgentOS at the
    login screen with zero prior setup — then replaces itself with sway."""
    if not IS_LINUX:
        print("The AgentOS session is Linux-only.")
        return
    if not shutil.which("sway"):
        print("sway is not installed — cannot start the AgentOS session.")
        sys.exit(1)
    stage(wayland=True)
    os.environ["AGENTOS_SESSION"] = "1"
    os.environ["XDG_CURRENT_DESKTOP"] = DESKTOP_ID
    os.environ["XDG_SESSION_DESKTOP"] = APP_ID
    os.execvp("sway", ["sway", "-c", str(SWAY_CONF)])


def remove(autologin: bool = False):
    if not IS_LINUX:
        print("Login-screen sessions are a Linux feature — nothing to remove on this OS.")
        return
    for p in (SESSION_SCRIPT, SHELL_SCRIPT, X11_SESSION_SCRIPT, SWAY_CONF):
        if p.exists():
            p.unlink()
            print(f"✓ removed {p}")
    targets = [WL_SESSIONS / f"{APP_ID}.desktop", XSESSIONS / f"{APP_ID}.desktop"]
    if _sudo_ok():
        for t in targets:
            _run(["sudo", "rm", "-f", str(t)])
        print(f"✓ removed {' and '.join(str(t) for t in targets)}")
    else:
        print("To finish removing the session entries, run:")
        for t in targets:
            print(f"  sudo rm -f '{t}'")
    if autologin:
        remove_autologin()
