"""Native desktop integration: run AgentOS as an app window, install launcher + service.

Cross-platform:
  Linux   — .desktop launcher + systemd user service + XDG autostart
  macOS   — app bundle in ~/Applications + LaunchAgents (server at login, app at login)
  Windows — Start Menu shortcut + Startup-folder entries

`agentos app`      — open the UI in its own window (no browser chrome). Starts the
                     server in-process if one isn't already running.
`agentos install`  — launcher + background service so the server starts on boot/login.
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
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

# --- Linux artifacts ---------------------------------------------------------------
DESKTOP_FILE = Path.home() / ".local/share/applications" / f"{APP_ID}.desktop"
ICON_FILE = Path.home() / ".local/share/icons/hicolor/scalable/apps" / f"{APP_ID}.svg"
SERVICE_FILE = Path.home() / ".config/systemd/user" / f"{APP_ID}.service"
AUTOSTART_FILE = Path.home() / ".config/autostart" / f"{APP_ID}-app.desktop"

# --- macOS artifacts ---------------------------------------------------------------
MAC_SERVER_LABEL = f"com.{APP_ID}.server"
MAC_APP_LABEL = f"com.{APP_ID}.app"
MAC_SERVER_PLIST = Path.home() / "Library/LaunchAgents" / f"{MAC_SERVER_LABEL}.plist"
MAC_APP_PLIST = Path.home() / "Library/LaunchAgents" / f"{MAC_APP_LABEL}.plist"
MAC_APP_BUNDLE = Path.home() / "Applications" / "AgentOS.app"

# --- Windows artifacts --------------------------------------------------------------
_WIN_APPDATA = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
WIN_STARTUP_DIR = _WIN_APPDATA / "Microsoft/Windows/Start Menu/Programs/Startup"
WIN_STARTMENU_DIR = _WIN_APPDATA / "Microsoft/Windows/Start Menu/Programs"
WIN_SERVER_VBS = WIN_STARTUP_DIR / f"{APP_ID}-server.vbs"
WIN_APP_VBS = WIN_STARTUP_DIR / f"{APP_ID}-app.vbs"
WIN_SHORTCUT = WIN_STARTMENU_DIR / "AgentOS.lnk"

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

MAC_BROWSER_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
]

WIN_BROWSER_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
]


def find_browser() -> str | None:
    """Path to a chromium-based browser for app-window mode, or None."""
    candidates: list[str] = []
    if IS_MAC:
        home_apps = [str(Path.home() / p.lstrip("/")) for p in MAC_BROWSER_PATHS]
        candidates += MAC_BROWSER_PATHS + home_apps
    if IS_WIN:
        candidates += WIN_BROWSER_PATHS
    for c in candidates:
        if Path(c).exists():
            return c
    return next((shutil.which(b) for b in BROWSERS if shutil.which(b)), None)


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

    browser = find_browser()
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


# --- cross-platform host helpers -----------------------------------------------------

def open_path(target: str) -> str | None:
    """Open a file/URL with the host OS default handler. Returns an error string or None."""
    try:
        if IS_WIN:
            os.startfile(target)  # noqa: S606 — the whole point is host handoff
            return None
        if IS_MAC:
            opener, cmd = "open", ["open", target]
        else:
            opener = shutil.which("xdg-open") or shutil.which("gio")
            if not opener:
                return "no host opener (xdg-open/gio) available"
            cmd = [opener, "open", target] if opener.endswith("gio") else [opener, target]
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return None
    except Exception as e:
        return str(e)


def send_notification(title: str, message: str = "") -> bool:
    """Show a native desktop notification. Best-effort; False when no mechanism exists."""
    try:
        if IS_MAC:
            def q(s: str) -> str:
                return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
            subprocess.Popen(["osascript", "-e",
                              f"display notification {q(message)} with title {q(title)}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if IS_WIN:
            def pq(s: str) -> str:
                return "'" + s.replace("'", "''") + "'"
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                "ContentType = WindowsRuntime] > $null;"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                f"$t.GetElementsByTagName('text').Item(0).AppendChild($t.CreateTextNode({pq(title)}))>$null;"
                f"$t.GetElementsByTagName('text').Item(1).AppendChild($t.CreateTextNode({pq(message)}))>$null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AgentOS')"
                ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, message],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        pass
    return False


def restart_service() -> str:
    """Restart the AgentOS server: via the platform service manager when installed and
    running, otherwise by re-exec'ing this process. Returns a short description."""
    if IS_MAC and MAC_SERVER_PLIST.exists():
        ok, _ = _run(["launchctl", "kickstart", "-k",
                      f"gui/{os.getuid()}/{MAC_SERVER_LABEL}"])
        if ok:
            return "restarting the AgentOS LaunchAgent"
    elif not IS_MAC and not IS_WIN and SERVICE_FILE.exists():
        active, _ = _run(["systemctl", "--user", "is-active", f"{APP_ID}.service"])
        if active:
            _run(["systemctl", "--user", "restart", f"{APP_ID}.service"])
            return "restarting the AgentOS systemd service"
    # not running under a service manager (dev run, `agentos serve` in a terminal,
    # Windows) — re-exec this process after the HTTP response has flushed
    def _reexec():
        time.sleep(1.0)
        os.execv(sys.executable, [sys.executable, "-m", "agentos", "serve", "--no-browser"])
    threading.Thread(target=_reexec, daemon=True).start()
    return "restarting the AgentOS process"


# --- install / autostart --------------------------------------------------------------

def _mac_load_agent(plist: Path):
    uid = os.getuid()
    _run(["launchctl", "bootout", f"gui/{uid}", str(plist)])          # ignore failures
    ok, out = _run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)])
    if not ok:                                                        # older macOS
        ok, out = _run(["launchctl", "load", "-w", str(plist)])
    return ok, out


def _install_mac(autostart: bool, open_at_login: bool):
    python = sys.executable
    port = _port()

    # minimal app bundle so AgentOS shows up in Launchpad / Spotlight
    macos_dir = MAC_APP_BUNDLE / "Contents/MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)
    (MAC_APP_BUNDLE / "Contents/Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>AgentOS</string>
  <key>CFBundleIdentifier</key><string>com.{APP_ID}.app</string>
  <key>CFBundleExecutable</key><string>AgentOS</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><false/>
</dict></plist>
""")
    launcher = macos_dir / "AgentOS"
    launcher.write_text(f"""#!/bin/sh
exec "{python}" -m agentos app
""")
    launcher.chmod(0o755)
    print(f"✓ app bundle     {MAC_APP_BUNDLE}")

    if autostart:
        MAC_SERVER_PLIST.parent.mkdir(parents=True, exist_ok=True)
        MAC_SERVER_PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{MAC_SERVER_LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{python}</string><string>-m</string><string>agentos</string>
    <string>serve</string><string>--no-browser</string><string>--port</string><string>{port}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
</dict></plist>
""")
        ok, out = _mac_load_agent(MAC_SERVER_PLIST)
        print(f"✓ LaunchAgent    {MAC_SERVER_PLIST} — server starts at login"
              if ok else f"! LaunchAgent written but not loaded: {out}")

    if open_at_login:
        enable_login_app(True)

    print("\n▲ AgentOS installed. It will start automatically at login, or run `agentos app`.")


def _install_windows(autostart: bool, open_at_login: bool):
    python = sys.executable
    port = _port()

    # Start Menu shortcut
    WIN_STARTMENU_DIR.mkdir(parents=True, exist_ok=True)
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{WIN_SHORTCUT}');"
          f"$s.TargetPath='{python}';$s.Arguments='-m agentos app';"
          f"$s.Description='AgentOS — your machine, with a brain';$s.Save()")
    ok, out = _run(["powershell", "-NoProfile", "-Command", ps])
    print(f"✓ start menu     {WIN_SHORTCUT}" if ok else f"! shortcut failed: {out}")

    if autostart:
        WIN_STARTUP_DIR.mkdir(parents=True, exist_ok=True)
        WIN_SERVER_VBS.write_text(
            f'CreateObject("WScript.Shell").Run """{python}"" -m agentos serve '
            f'--no-browser --port {port}", 0, False\n')
        print(f"✓ startup entry  {WIN_SERVER_VBS} — server starts at login")

    if open_at_login:
        enable_login_app(True)

    print("\n▲ AgentOS installed. It will start automatically at login, or run `agentos app`.")


def _install_linux(autostart: bool, open_at_login: bool):
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
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
ExecStart={python} -m agentos serve --no-browser --port {port}
Restart=on-failure
RestartSec=10

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


def install(autostart: bool = True, open_at_login: bool = True):
    if IS_MAC:
        _install_mac(autostart, open_at_login)
    elif IS_WIN:
        _install_windows(autostart, open_at_login)
    else:
        _install_linux(autostart, open_at_login)


def enable_login_app(on: bool = True):
    """Open the AgentOS window automatically at every login."""
    python = sys.executable
    if IS_MAC:
        if on:
            MAC_APP_PLIST.parent.mkdir(parents=True, exist_ok=True)
            MAC_APP_PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{MAC_APP_LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{python}</string><string>-m</string><string>agentos</string><string>app</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict></plist>
""")
            _mac_load_agent(MAC_APP_PLIST)
            print(f"✓ autostart      {MAC_APP_PLIST} — AgentOS opens at login")
        else:
            if MAC_APP_PLIST.exists():
                _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(MAC_APP_PLIST)])
                MAC_APP_PLIST.unlink()
                print("✓ autostart disabled")
            else:
                print("· autostart was not enabled")
        return

    if IS_WIN:
        if on:
            WIN_STARTUP_DIR.mkdir(parents=True, exist_ok=True)
            WIN_APP_VBS.write_text(
                f'CreateObject("WScript.Shell").Run """{python}"" -m agentos app", 0, False\n')
            print(f"✓ autostart      {WIN_APP_VBS} — AgentOS opens at login")
        else:
            if WIN_APP_VBS.exists():
                WIN_APP_VBS.unlink()
                print("✓ autostart disabled")
            else:
                print("· autostart was not enabled")
        return

    if on:
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


def autostart_installed() -> bool:
    """Is the boot/login server service installed on this platform?"""
    if IS_MAC:
        return MAC_SERVER_PLIST.exists()
    if IS_WIN:
        return WIN_SERVER_VBS.exists()
    return SERVICE_FILE.exists()


def autostart_report() -> tuple[str | None, str | None]:
    """(autostart status line, boot status line) for the setup wizard, per platform."""
    if IS_MAC:
        if not MAC_SERVER_PLIST.exists():
            return "LaunchAgent not installed", None
        ok, _ = _run(["launchctl", "print", f"gui/{os.getuid()}/{MAC_SERVER_LABEL}"])
        return ("LaunchAgent loaded — starts automatically" if ok
                else "LaunchAgent written; loads at next login"), "starts at login"
    if IS_WIN:
        return (("startup entry installed — starts at login" if WIN_SERVER_VBS.exists()
                 else "startup entry not installed"), "starts at login")
    ok, _ = _run(["systemctl", "--user", "is-enabled", f"{APP_ID}.service"])
    auto = ("service enabled — starts automatically" if ok
            else "service written; enable failed (see server log)")
    lok, lout = _run(["loginctl", "show-user", os.environ.get("USER", ""),
                      "--property=Linger"])
    boot = ("starts at boot (linger on)" if lok and "yes" in lout
            else "starts at login (boot-time start needs `loginctl enable-linger $USER`)")
    return auto, boot


def install_session():
    """Superseded by agentos/session.py (which adds the Wayland/sway session and
    keeps this X11 one as the kiosk fallback). Kept as a delegate so old callers
    keep working."""
    from . import session
    session.install(wayland=False)


def uninstall_session():
    from . import session
    session.remove()


def uninstall():
    if IS_MAC:
        uid = os.getuid()
        for plist in (MAC_SERVER_PLIST, MAC_APP_PLIST):
            if plist.exists():
                _run(["launchctl", "bootout", f"gui/{uid}", str(plist)])
                plist.unlink()
                print(f"✓ removed {plist}")
        if MAC_APP_BUNDLE.exists():
            shutil.rmtree(MAC_APP_BUNDLE)
            print(f"✓ removed {MAC_APP_BUNDLE}")
    elif IS_WIN:
        for f in (WIN_SERVER_VBS, WIN_APP_VBS, WIN_SHORTCUT):
            if f.exists():
                f.unlink()
                print(f"✓ removed {f}")
    else:
        _run(["systemctl", "--user", "disable", "--now", f"{APP_ID}.service"])
        for f in (SERVICE_FILE, DESKTOP_FILE, ICON_FILE, AUTOSTART_FILE):
            if f.exists():
                f.unlink()
                print(f"✓ removed {f}")
        _run(["systemctl", "--user", "daemon-reload"])
    print("▲ AgentOS uninstalled (config and data in ~/.agentos are untouched).")
