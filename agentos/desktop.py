"""Native desktop integration: run AgentOS as an app window, install launcher + service.

`agentos app`      — open the UI in its own window (no browser chrome). Starts the
                     server in-process if one isn't already running.
`agentos install`  — desktop launcher (app grid) + systemd user service so the
                     server starts on boot/login.
`agentos uninstall`— remove both.
"""

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config as cfgmod

APP_ID = "agentos"
DESKTOP_FILE = Path.home() / ".local/share/applications" / f"{APP_ID}.desktop"
ICON_FILE = Path.home() / ".local/share/icons/hicolor/scalable/apps" / f"{APP_ID}.svg"
SERVICE_FILE = Path.home() / ".config/systemd/user" / f"{APP_ID}.service"
AUTOSTART_FILE = Path.home() / ".config/autostart" / f"{APP_ID}-app.desktop"

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#5eead4"/><stop offset="1" stop-color="#22d3ee"/>
  </linearGradient>
  <linearGradient id="tri" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0a2c26"/><stop offset="1" stop-color="#04211c"/>
  </linearGradient>
</defs>
<rect width="128" height="128" rx="30" fill="url(#g)"/>
<rect x="3" y="3" width="122" height="122" rx="28" fill="none" stroke="rgba(255,255,255,.25)" stroke-width="1.5"/>
<path d="M64 24 L104 98 Q107 103 101 103 L27 103 Q21 103 24 98 Z" fill="url(#tri)"/>
<path d="M64 55 L85 94 L43 94 Z" fill="rgba(255,255,255,.16)"/>
<circle cx="64" cy="47" r="7.5" fill="#04211c"/>
<circle cx="64" cy="47" r="3" fill="#5eead4"/>
</svg>
"""

BROWSERS = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
            "brave-browser", "microsoft-edge", "vivaldi"]


def _port() -> int:
    return cfgmod.load_config().get("port", 8321)


def _server_up(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def _start_server_thread(port: int):
    import uvicorn
    config = uvicorn.Config("agentos.server:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(60):
        if _server_up(port):
            return
        time.sleep(0.25)
    print("warning: server did not come up within 15s", file=sys.stderr)


def app_mode():
    """Open AgentOS as its own desktop window."""
    port = _port()
    started_here = False
    if not _server_up(port):
        print("▲ starting AgentOS server…")
        _start_server_thread(port)
        started_here = True
    url = f"http://127.0.0.1:{port}"

    browser = next((b for b in BROWSERS if shutil.which(b)), None)
    if browser:
        profile = cfgmod.AGENTOS_HOME / "appwindow"
        profile.mkdir(parents=True, exist_ok=True)
        # true fullscreen (hides the host top bar / taskbar). --start-maximized would keep them,
        # so it must NOT be combined with --start-fullscreen.
        args = [browser, f"--app={url}", f"--user-data-dir={profile}",
                "--start-fullscreen", f"--class={APP_ID}", "--no-first-run",
                "--no-default-browser-check"]
        if os.environ.get("AGENTOS_KIOSK") == "1":
            args = [browser, f"--app={url}", f"--user-data-dir={profile}",
                    "--kiosk", f"--class={APP_ID}", "--no-first-run"]
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait()   # keep the in-process server alive while the window is open
        return

    try:
        import webview  # pywebview, optional
        window_kwargs = dict(width=1500, height=900, background_color="#0b0d10")
        webview.create_window("AgentOS", url, **window_kwargs)
        webview.start()
        return
    except ImportError:
        pass

    print(f"No chromium-based browser or pywebview found — opening {url} in the default browser.")
    import webbrowser
    webbrowser.open(url)
    if started_here:
        print("Server keeps running; Ctrl-C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def install(autostart: bool = True, open_at_login: bool = True):
    python = sys.executable
    port = _port()

    ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
    ICON_FILE.write_text(ICON_SVG)

    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(f"""[Desktop Entry]
Type=Application
Name=AgentOS
GenericName=Agentic OS
Comment=Your machine, with a brain
Exec={python} -m agentos app
Icon={APP_ID}
Terminal=false
Categories=Utility;System;
StartupWMClass={APP_ID}
Keywords=agent;ai;assistant;
""")
    print(f"✓ app launcher   {DESKTOP_FILE}")

    if autostart:
        SERVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SERVICE_FILE.write_text(f"""[Unit]
Description=AgentOS server (your machine, with a brain)
After=network-online.target

[Service]
ExecStart={python} -m agentos serve --no-browser --port {port}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
""")
        print(f"✓ systemd unit   {SERVICE_FILE}")
        ok, out = _run(["systemctl", "--user", "daemon-reload"])
        ok2, out2 = _run(["systemctl", "--user", "enable", "--now", f"{APP_ID}.service"])
        if ok and ok2:
            print(f"✓ service        enabled + started (http://127.0.0.1:{port})")
        else:
            print(f"! service setup incomplete: {out or out2}")
        # user services normally start at login; linger makes them start at boot
        lok, _ = _run(["loginctl", "enable-linger", os.environ.get("USER", "")])
        print("✓ boot start     linger enabled — server starts at boot, even before login"
              if lok else "· starts at login (run `loginctl enable-linger $USER` for boot-time start)")

    if open_at_login:
        enable_login_app(True)

    for cmd in (["update-desktop-database", str(DESKTOP_FILE.parent)],
                ["gtk-update-icon-cache", str(Path.home() / ".local/share/icons/hicolor")]):
        if shutil.which(cmd[0]):
            _run(cmd)

    print("\n▲ AgentOS installed. It will open automatically at login, or run `agentos app`.")


def enable_login_app(on: bool = True):
    """Open the AgentOS window fullscreen automatically at every login."""
    if on:
        python = sys.executable
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(f"""[Desktop Entry]
Type=Application
Name=AgentOS
Comment=Open AgentOS at login
Exec={python} -m agentos app
Icon={APP_ID}
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=2
""")
        print(f"✓ autostart      {AUTOSTART_FILE} — AgentOS opens at login")
    else:
        if AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink()
            print("✓ autostart disabled")
        else:
            print("· autostart was not enabled")


SESSION_SCRIPT = Path.home() / ".local/bin" / f"{APP_ID}-session"
SESSION_DESKTOP_STAGE = cfgmod.AGENTOS_HOME / f"{APP_ID}-session.desktop"
XSESSIONS = Path("/usr/share/xsessions")


def install_session():
    """Make AgentOS a desktop session you can choose at the login screen — it boots straight
    into AgentOS in kiosk mode, replacing the normal desktop shell.

    The session file must go in /usr/share/xsessions (root-owned), so this stages everything and
    either installs it with sudo (if available non-interactively) or prints the exact commands.
    """
    python = sys.executable
    SESSION_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
    SESSION_SCRIPT.write_text(f"""#!/bin/sh
# AgentOS desktop session — runs AgentOS as the shell (kiosk).
export AGENTOS_SESSION=1
# 1) make sure the server is up (start one only if nothing is already listening)
if ! curl -s -o /dev/null http://127.0.0.1:8321/ 2>/dev/null; then
  "{python}" -m agentos serve --no-browser >/dev/null 2>&1 &
fi
for i in $(seq 1 60); do
  curl -s -o /dev/null http://127.0.0.1:8321/ 2>/dev/null && break
  sleep 0.25
done
# 2) a minimal window manager so any native apps AgentOS launches are movable/closable (optional)
for wm in openbox matchbox-window-manager icewm; do
  if command -v "$wm" >/dev/null 2>&1; then "$wm" & break; fi
done
# 3) launch AgentOS fullscreen kiosk (this blocks; when it exits, the session ends → logout)
prof="$HOME/.agentos/appwindow"; mkdir -p "$prof"
for b in chromium chromium-browser google-chrome google-chrome-stable brave-browser microsoft-edge vivaldi; do
  if command -v "$b" >/dev/null 2>&1; then
    exec "$b" --app=http://127.0.0.1:8321 --kiosk --user-data-dir="$prof" \\
         --no-first-run --no-default-browser-check --class={APP_ID}
  fi
done
command -v xmessage >/dev/null 2>&1 && xmessage "AgentOS session: no chromium-based browser found."
sleep 5
""")
    SESSION_SCRIPT.chmod(0o755)
    print(f"✓ session script  {SESSION_SCRIPT}")

    desktop = f"""[Desktop Entry]
Name=AgentOS
Comment=AgentOS — your machine, with a brain
Exec={SESSION_SCRIPT}
Type=Application
DesktopNames=AgentOS
Keywords=agent;ai;
"""
    SESSION_DESKTOP_STAGE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_DESKTOP_STAGE.write_text(desktop)

    target = XSESSIONS / f"{APP_ID}.desktop"
    # try to install it system-wide without prompting; otherwise hand the user the commands
    if _run(["sudo", "-n", "true"])[0]:
        _run(["sudo", "mkdir", "-p", str(XSESSIONS)])
        ok, out = _run(["sudo", "cp", str(SESSION_DESKTOP_STAGE), str(target)])
        _run(["loginctl", "enable-linger", os.environ.get("USER", "")])
        if ok:
            print(f"✓ session entry   {target}")
            print("\n▲ AgentOS session installed. Log out, then pick 'AgentOS' (gear icon) at the login screen.")
            return
        print(f"! could not copy the session file: {out}")

    print(f"✓ session entry   staged at {SESSION_DESKTOP_STAGE}")
    print("\nOne step needs root. Run these, then log out and pick 'AgentOS' at the login screen:\n")
    print(f"  sudo cp '{SESSION_DESKTOP_STAGE}' '{target}'")
    print(f"  loginctl enable-linger \"$USER\"")
    print("\n  (Optional, for movable native app windows in the session:  sudo apt install openbox )")


def uninstall_session():
    if SESSION_SCRIPT.exists():
        SESSION_SCRIPT.unlink()
        print(f"✓ removed {SESSION_SCRIPT}")
    target = XSESSIONS / f"{APP_ID}.desktop"
    if _run(["sudo", "-n", "true"])[0]:
        _run(["sudo", "rm", "-f", str(target)])
        print(f"✓ removed {target}")
    else:
        print(f"To finish removing the session, run:  sudo rm -f '{target}'")


def uninstall():
    _run(["systemctl", "--user", "disable", "--now", f"{APP_ID}.service"])
    for f in (SERVICE_FILE, DESKTOP_FILE, ICON_FILE, AUTOSTART_FILE):
        if f.exists():
            f.unlink()
            print(f"✓ removed {f}")
    _run(["systemctl", "--user", "daemon-reload"])
    print("▲ AgentOS uninstalled (config and data in ~/.agentos are untouched).")
