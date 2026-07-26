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
X11_SESSION_SCRIPT = BIN_DIR / f"{APP_ID}-session"        # legacy name, still X11
SWAY_CONF = Path.home() / ".config" / APP_ID / "sway.conf"
SWAY_DROPIN_DIR = Path.home() / ".config" / APP_ID / "sway.d"

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
default_border none
default_floating_border none
focus_follows_mouse no

# One pointer everywhere (compositor + XWayland), sized for modern displays.
seat * xcursor_theme Adwaita 24

# Drag native windows with Super held down.
floating_modifier Mod4

# Wallpaper behind everything (visible if the shell ever drops fullscreen).
{f"exec swaybg -i '{wallpaper}' -m fill" if wallpaper else "exec swaybg -c '#0b0d10'"}

# The lock screen is enforced by swaylock. swayidle locks after idling, blanks
# the outputs a bit later, locks before sleep, and answers loginctl
# lock-session — which is what the ⏻ menu's Lock calls.
exec swayidle -w {idle} \\
  before-sleep "{lock_cmd}" lock "{lock_cmd}"

# Layering: the AgentOS shell is the ONLY tiled window, so it fills the screen
# as the base layer; every native app floats ABOVE it. (The old fullscreen
# approach was wrong — sway keeps fullscreen on top, so launched apps appeared
# to do nothing while sitting invisible underneath the shell.)
for_window [title=".*"] floating enable
for_window [app_id="^{APP_ID}$"] floating disable, fullscreen disable
for_window [class="^{APP_ID}$"] floating disable, fullscreen disable

# Alt+Tab cycles shell → each native window → shell, via the server (which
# tracks focus over compositor IPC). Works no matter which window has the keys.
bindsym Mod1+Tab exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"direction":"next"}}' http://127.0.0.1:{port}/api/windows/cycle
bindsym Mod1+Shift+Tab exec curl -sf -m 2 -X POST -H "Content-Type: application/json" -d '{{"direction":"prev"}}' http://127.0.0.1:{port}/api/windows/cycle

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
export XDG_CURRENT_DESKTOP=AgentOS
export XDG_SESSION_DESKTOP={APP_ID}
export XCURSOR_THEME=Adwaita
export XCURSOR_SIZE=24
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
        desk = cfgmod.load_config().get("desktop", {})
        idle_lock = int(desk.get("idle_lock_secs", 600))
        idle_off = int(desk.get("idle_screen_off_secs", 900))
        SWAY_CONF.write_text(sway_config_text(
            _port(), idle_lock=idle_lock, idle_off=idle_off, wallpaper=wallpaper or ""))
        lock = lock_cmd_text(wallpaper or "")
        idle_args = []
        if idle_lock > 0:
            idle_args += ["timeout", str(idle_lock), lock]
        if idle_off > 0:
            idle_args += ["timeout", str(idle_off), 'swaymsg "output * power off"',
                          "resume", 'swaymsg "output * power on"']
        subprocess.run(["pkill", "-u", os.environ.get("USER", ""), "-x", "swayidle"],
                       capture_output=True, timeout=5)
        subprocess.Popen(["swayidle", "-w", *idle_args,
                          "before-sleep", lock, "lock", lock],
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
            desk = cfgmod.load_config().get("desktop", {})
        except Exception:
            desk = {}
        wallpaper = cfgmod.AGENTOS_HOME / "wallpaper.png"
        SWAY_CONF.parent.mkdir(parents=True, exist_ok=True)
        SWAY_DROPIN_DIR.mkdir(parents=True, exist_ok=True)
        SWAY_CONF.write_text(sway_config_text(
            port,
            idle_lock=int(desk.get("idle_lock_secs", 600)),
            idle_off=int(desk.get("idle_screen_off_secs", 900)),
            wallpaper=str(wallpaper) if wallpaper.exists() else ""))
        written.append(SWAY_CONF)
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
    os.environ["XDG_CURRENT_DESKTOP"] = "AgentOS"
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
