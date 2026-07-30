"""Optional components — what AgentOS can't ship but the user can add.

The desktop package deliberately bundles only permissive (MIT/Apache/BSD)
software; see packaging/audit-licenses.sh. Some genuinely useful pieces are
GPL, snap-only, or simply optional — those live here as a catalog the UI can
offer: each entry says what it unlocks, what licence it carries, and how it
would be installed. Nothing installs without the user saying yes to exactly
that, licence in view.

Capabilities link back here: when a control is greyed out, its `component`
field names the catalog entry whose installation would light it up.

Installation itself needs root. In order of least friction:
  1. passwordless sudo (developer machines)         → run it
  2. pkexec (polkit prompt, hosted desktop)         → run it, user authenticates
  3. neither                                        → hand back the exact command
The command is always returned too, so the UI can show what was (or should be)
run — no invisible system changes.
"""

from __future__ import annotations

import asyncio
import shutil

# id → what it is. `licence` is shown in the consent dialog. `method` is apt or
# snap. `detect` returns True when the component is already present.
CATALOG: dict[str, dict] = {
    "wl-clipboard": {
        "package": "wl-clipboard", "method": "apt", "licence": "GPL-3.0+",
        "title": "Clipboard bridge",
        "unlocks": "Copy and paste between AgentOS and native Wayland apps.",
        "detect": lambda: bool(shutil.which("wl-copy")),
    },
    "wayvnc": {
        "package": "wayvnc", "method": "apt", "licence": "ISC",
        "title": "Interactive remote control",
        "unlocks": "Use native apps from another device — a real VNC server for "
                   "the AgentOS compositor, streaming the screen and sending your "
                   "clicks and keys back. AgentOS starts it on loopback only, "
                   "because wayvnc ships with no password.",
        "detect": lambda: bool(shutil.which("wayvnc")),
    },
    "novnc": {
        "package": "novnc", "method": "apt", "licence": "MPL-2.0",
        "title": "Remote Desktop in a browser",
        "unlocks": "Use the real screen — native apps included — from a phone or "
                   "any browser, with no VNC app to install. AgentOS relays it "
                   "over its own authenticated connection, so the VNC port stays "
                   "on 127.0.0.1 and nothing new is exposed to the network.",
        "detect": lambda: _novnc_present(),
    },
    "ddcutil": {
        "package": "ddcutil", "method": "apt", "licence": "GPL-2.0+",
        "title": "External monitor brightness",
        "unlocks": "Brightness control for desktop monitors over DDC/CI "
                   "(machines without an internal backlight).",
        "detect": lambda: bool(shutil.which("ddcutil")),
    },
    "chromium": {
        "package": "chromium", "method": "snap", "licence": "BSD-3-Clause and others",
        "title": "Desktop shell renderer",
        "unlocks": "Draws the AgentOS desktop in the AgentOS session. Any "
                   "chromium-family browser works; this is the open-source one.",
        "detect": lambda: _has_renderer(),
    },
    "power-profiles-daemon": {
        "package": "power-profiles-daemon", "method": "apt", "licence": "GPL-3.0+",
        "title": "Power profiles",
        "unlocks": "Switch between power-saver, balanced and performance modes.",
        "detect": lambda: bool(shutil.which("powerprofilesctl")),
    },
    "session-ui": {
        "package": ("python3-gi gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 "
                    "gir1.2-webkit2-4.1"),
        "method": "apt", "licence": "MIT (gtk-layer-shell), LGPL-2.1+ (GTK, WebKitGTK)",
        "title": "Native desktop surface (session UI)",
        "unlocks": "Draws the AgentOS desktop as a real Wayland layer-shell "
                   "surface instead of a browser window, so application windows "
                   "stack above it normally and the menu bar and dock cannot be "
                   "covered. Without it the session falls back to a Chromium "
                   "window, which works but has to fake the stacking order.",
        "detect": lambda: _sui_available(),
    },
    "wmctrl": {
        "package": "wmctrl", "method": "apt", "licence": "GPL-2.0+",
        "title": "X11 window control",
        "unlocks": "See and control native windows when running hosted on an "
                   "X11 desktop.",
        "detect": lambda: bool(shutil.which("wmctrl")),
    },
    "grim": {
        "package": "grim slurp", "method": "apt", "licence": "MIT",
        "title": "Screenshots",
        "unlocks": "Screen and region capture in the AgentOS session.",
        "detect": lambda: bool(shutil.which("grim")),
    },
    "swaylock": {
        "package": "swaylock swayidle", "method": "apt", "licence": "MIT",
        "title": "Screen lock",
        "unlocks": "Locking and idle timeout in the AgentOS session.",
        "detect": lambda: bool(shutil.which("swaylock")),
    },
    "network-manager": {
        "package": "network-manager", "method": "apt", "licence": "GPL-2.0+",
        "title": "Network management",
        "unlocks": "Wifi scanning and joining, connection management.",
        "detect": lambda: bool(shutil.which("nmcli")),
    },
    "upower": {
        "package": "upower", "method": "apt", "licence": "GPL-2.0+",
        "title": "Battery status",
        "unlocks": "Battery level and charging state.",
        "detect": lambda: bool(shutil.which("upower")),
    },
    "portals": {
        "package": "xdg-desktop-portal xdg-desktop-portal-wlr xdg-desktop-portal-gtk",
        "method": "apt", "licence": "MIT and LGPL-2.1+",
        "title": "Screen sharing & native file dialogs",
        "unlocks": "\"Share your screen\" in a browser call, and the system file "
                   "picker that snaps and Flatpaks open. Without these the "
                   "button is there and nothing happens.",
        "detect": lambda: _portal_present(),
    },
    "udiskie": {
        "package": "udiskie", "method": "apt", "licence": "MIT",
        "title": "Removable media",
        "unlocks": "Plug in a USB stick or SD card and it mounts by itself, "
                   "the way it does on every other desktop.",
        "detect": lambda: bool(shutil.which("udiskie")),
    },
    "wlsunset": {
        "package": "wlsunset", "method": "apt", "licence": "MIT",
        "title": "Night light",
        "unlocks": "Warms the screen after dark (System Settings \u2192 Displays).",
        "detect": lambda: bool(shutil.which("wlsunset")),
    },
    "playerctl": {
        "package": "playerctl", "method": "apt", "licence": "LGPL-3.0+",
        "title": "Media keys",
        "unlocks": "Play/pause, next and previous keys control whatever is "
                   "playing, in any app.",
        "detect": lambda: bool(shutil.which("playerctl")),
    },
    "printing": {
        "package": "cups system-config-printer", "method": "apt", "licence": "Apache-2.0",
        "title": "Printers",
        "unlocks": "Discovering and printing to network and USB printers.",
        "detect": lambda: bool(shutil.which("lpstat")),
    },
    "plymouth-theme": {
        "package": "agentos boot theme", "method": "script", "licence": "MIT (AgentOS)",
        "title": "Branded boot splash",
        "unlocks": "The AgentOS mark from the first frame of boot — no distro "
                   "splash between power-on and the desktop. Rebuilds the "
                   "initramfs (takes a minute).",
        "detect": lambda: _plymouth_theme_installed(),
    },
}


def _portal_present() -> bool:
    """The portal binaries live in libexec, not on $PATH."""
    from pathlib import Path
    return any(Path(p).exists() for p in (
        "/usr/libexec/xdg-desktop-portal", "/usr/lib/xdg-desktop-portal",
        "/usr/libexec/xdg-desktop-portal-wlr", "/usr/lib/xdg-desktop-portal-wlr"))


def _plymouth_theme_installed() -> bool:
    from pathlib import Path
    return Path("/usr/share/plymouth/themes/agentos/agentos.plymouth").exists()


def _plymouth_script() -> str:
    from pathlib import Path
    return str(Path(__file__).resolve().parent / "de_assets" / "plymouth" / "install.sh")


def _novnc_present() -> bool:
    from . import remotedesktop
    return bool(remotedesktop.novnc_dir())


def _sui_available() -> bool:
    from . import shellhost
    return shellhost.available()


def _has_renderer() -> bool:
    from . import desktop
    return bool(desktop.find_browser())


def install_command(comp: dict) -> str:
    if comp["method"] == "snap":
        return f"snap install {comp['package']}"
    if comp["method"] == "script":
        return f"sh {_plymouth_script()}"
    return f"apt-get install -y {comp['package']}"


def catalog() -> list[dict]:
    out = []
    for cid, c in CATALOG.items():
        out.append({
            "id": cid, "title": c["title"], "package": c["package"],
            "method": c["method"], "licence": c["licence"], "unlocks": c["unlocks"],
            "installed": bool(c["detect"]()),
            "command": f"sudo {install_command(c)}",
        })
    return out


async def install(component_id: str) -> dict:
    """Install one catalog entry. Only ever called after explicit user consent.

    Returns {ok, message, command, needs_terminal} — `command` is always the
    exact thing run or to run, so nothing changes invisibly.
    """
    comp = CATALOG.get(component_id)
    if not comp:
        return {"ok": False, "message": f"unknown component '{component_id}'",
                "command": "", "needs_terminal": False}
    if comp["detect"]():
        return {"ok": True, "message": "already installed", "command": "",
                "needs_terminal": False}

    cmd = install_command(comp)
    manual = {"ok": False, "needs_terminal": True, "command": f"sudo {cmd}",
              "message": "Root access is needed — run this in the Terminal:"}

    async def run(argv: list[str], timeout: float) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return 1, "timed out"
        return proc.returncode or 0, out.decode(errors="replace")

    # 1) passwordless sudo
    rc, _ = await run(["sudo", "-n", "true"], 10)
    if rc == 0:
        rc, out = await run(["sudo", "-n"] + cmd.split(), 600)
        if rc == 0 and comp["detect"]():
            _refresh_platform()
            return {"ok": True, "message": f"{comp['title']} installed.",
                    "command": f"sudo {cmd}", "needs_terminal": False}
        return {**manual, "message": out[-400:] or manual["message"]}

    # 2) polkit prompt (hosted desktops have an auth agent)
    if shutil.which("pkexec"):
        rc, out = await run(["pkexec"] + cmd.split(), 600)
        if rc == 0 and comp["detect"]():
            _refresh_platform()
            return {"ok": True, "message": f"{comp['title']} installed.",
                    "command": f"pkexec {cmd}", "needs_terminal": False}
        if rc in (126, 127):     # dismissed the prompt / no agent
            return manual
        return {**manual, "message": out[-400:] or manual["message"]}

    # 3) hand the command back
    return manual


def _refresh_platform():
    """A new binary can flip capabilities — re-probe so the UI un-greys."""
    try:
        from .platform import get_platform
        get_platform(refresh=True)
    except Exception:
        pass
