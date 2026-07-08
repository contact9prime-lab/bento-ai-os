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

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="#5eead4"/><stop offset="1" stop-color="#22d3ee"/>
</linearGradient></defs>
<rect width="128" height="128" rx="28" fill="#0b0d10"/>
<rect x="4" y="4" width="120" height="120" rx="24" fill="none" stroke="url(#g)" stroke-width="2" opacity=".35"/>
<path d="M64 26 L102 96 L26 96 Z" fill="url(#g)"/>
<path d="M64 47 L86 88 L42 88 Z" fill="#0b0d10"/>
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
        proc = subprocess.Popen(
            [browser, f"--app={url}", f"--user-data-dir={profile}",
             "--window-size=1500,900", f"--class={APP_ID}", "--no-first-run"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


def install(autostart: bool = True):
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

    for cmd in (["update-desktop-database", str(DESKTOP_FILE.parent)],
                ["gtk-update-icon-cache", str(Path.home() / ".local/share/icons/hicolor")]):
        if shutil.which(cmd[0]):
            _run(cmd)

    print("\n▲ AgentOS installed. Find it in your app launcher, or run `agentos app`.")


def uninstall():
    _run(["systemctl", "--user", "disable", "--now", f"{APP_ID}.service"])
    for f in (SERVICE_FILE, DESKTOP_FILE, ICON_FILE):
        if f.exists():
            f.unlink()
            print(f"✓ removed {f}")
    _run(["systemctl", "--user", "daemon-reload"])
    print("▲ AgentOS uninstalled (config and data in ~/.agentos are untouched).")
