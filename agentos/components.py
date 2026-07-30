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
  1. passwordless sudo (developer machines)         -> run it
  2. pkexec (polkit prompt, hosted desktop)         -> run it, user authenticates
  3. neither                                        -> hand back the exact command
The command is always returned too, so the UI can show what was (or should be)
run — no invisible system changes.

PACKAGE NAMES ARE PER DISTRO, AND THAT IS NOT OPTIONAL
======================================================
This catalogue used to hold one spelling per component — the Debian one — and
`install_command` prefixed it with `apt-get install -y` unconditionally. On
Fedora or Arch that produced a command that cannot run, shown in a consent
dialog as though it were the truth, and `install.sh` skipped its whole
dependency step behind `command -v apt-get` so those users were offered nothing
at all. Every entry now carries a `packages` map keyed by distro family (see
osdetect.py), and a component with no spelling for the running family says so
instead of inventing one.

The non-Debian names are best effort, and the design accounts for that: what
decides whether a component is present is always its own `detect()` probe, never
the package name. A wrong name therefore fails loudly at install time with the
package manager's own error, and can never report success it did not achieve.
"""

from __future__ import annotations

import asyncio
import shutil

from . import osdetect

#: Distro families this catalogue has package names for. Anything else is told
#: plainly that it has none — see `catalog()`.
FAMILIES = ("debian", "rhel", "arch", "suse")


def _same(name: str) -> dict:
    """Shorthand for the common case: identical package name everywhere."""
    return {f: name for f in FAMILIES}


# id -> what it is. `licence` is shown in the consent dialog. `method` is
# "system" (the distro's own package manager), "snap" or "script". `detect`
# returns True when the component is already present. `group` is how the
# installer sorts it: "required" for the session to work at all, "recommended"
# for a desktop that behaves like one, "optional" for the rest.
CATALOG: dict[str, dict] = {
    # ---- the session cannot exist without these -----------------------------
    "compositor": {
        "packages": _same("sway swaybg foot"),
        "method": "system", "licence": "MIT",
        "group": "required", "for_session": True,
        "title": "Compositor engine (sway)",
        "unlocks": "The Wayland compositor AgentOS drives when it IS the desktop, "
                   "the wallpaper layer, and a terminal to fall back to. Without "
                   "this there is no AgentOS session to log into at all.",
        "detect": lambda: bool(shutil.which("sway")),
    },
    "session-ui": {
        "packages": {
            # python3-gi-cairo is the PyGObject<->cairo foreign-type bridge, and
            # python3-gi does NOT pull it in. Leaving it out is what made the
            # shell host start, die on its first strut, and take the login with
            # it — a black screen with no greeter.
            "debian": ("python3-gi python3-gi-cairo gir1.2-gtk-3.0 "
                       "gir1.2-gtklayershell-0.1 gir1.2-webkit2-4.1"),
            "rhel": "python3-gobject python3-cairo gtk3 gtk-layer-shell webkit2gtk4.1",
            "arch": "python-gobject python-cairo gtk3 gtk-layer-shell webkit2gtk-4.1",
            "suse": ("python3-gobject python3-gobject-cairo python3-cairo gtk3 "
                     "gtk-layer-shell typelib-1_0-WebKit2-4_1"),
        },
        "method": "system",
        "licence": "MIT (gtk-layer-shell), LGPL-2.1+ (GTK, WebKitGTK)",
        "group": "required", "for_session": True,
        "title": "Native desktop surface (session UI)",
        "unlocks": "Draws the AgentOS desktop as a real Wayland layer-shell "
                   "surface instead of a browser window, so application windows "
                   "stack above it normally and the menu bar and dock cannot be "
                   "covered. Without it the session falls back to a Chromium "
                   "window, which works but has to fake the stacking order.",
        "detect": lambda: _sui_available(),
    },
    "chromium": {
        "packages": _same("chromium"),
        "method": "snap", "licence": "BSD-3-Clause and others",
        "group": "required", "for_session": True,
        "title": "Desktop shell renderer (fallback)",
        "unlocks": "Draws the AgentOS desktop when the native surface above is "
                   "unavailable. Any chromium-family browser works; this is the "
                   "open-source one.",
        "detect": lambda: _has_renderer(),
    },

    # ---- a desktop that behaves like a desktop ------------------------------
    "swaylock": {
        "packages": _same("swaylock swayidle"),
        "method": "system", "licence": "MIT",
        "group": "recommended", "for_session": True,
        "title": "Screen lock",
        "unlocks": "Locking and idle timeout in the AgentOS session.",
        "detect": lambda: bool(shutil.which("swaylock")),
    },
    "grim": {
        "packages": _same("grim slurp"),
        "method": "system", "licence": "MIT",
        "group": "recommended", "for_session": True,
        "title": "Screenshots",
        "unlocks": "Screen and region capture in the AgentOS session.",
        "detect": lambda: bool(shutil.which("grim")),
    },
    "portals": {
        "packages": _same("xdg-desktop-portal xdg-desktop-portal-wlr "
                          "xdg-desktop-portal-gtk"),
        "method": "system", "licence": "MIT and LGPL-2.1+",
        "group": "recommended", "for_session": True,
        "title": "Screen sharing & native file dialogs",
        "unlocks": "\"Share your screen\" in a browser call, and the system file "
                   "picker that snaps and Flatpaks open. Without these the "
                   "button is there and nothing happens.",
        "detect": lambda: _portal_present(),
    },
    "wl-clipboard": {
        "packages": _same("wl-clipboard"),
        "method": "system", "licence": "GPL-3.0+",
        "group": "recommended", "for_session": True,
        "title": "Clipboard bridge",
        "unlocks": "Copy and paste between AgentOS and native Wayland apps.",
        "detect": lambda: bool(shutil.which("wl-copy")),
    },
    "network-manager": {
        "packages": {"debian": "network-manager", "rhel": "NetworkManager",
                     "arch": "networkmanager", "suse": "NetworkManager"},
        "method": "system", "licence": "GPL-2.0+",
        "group": "recommended", "for_session": False,
        "title": "Network management",
        "unlocks": "Wifi scanning and joining, connection management.",
        "detect": lambda: bool(shutil.which("nmcli")),
    },
    "udiskie": {
        "packages": _same("udiskie"),
        "method": "system", "licence": "MIT",
        "group": "recommended", "for_session": True,
        "title": "Removable media",
        "unlocks": "Plug in a USB stick or SD card and it mounts by itself, "
                   "the way it does on every other desktop.",
        "detect": lambda: bool(shutil.which("udiskie")),
    },

    # ---- everything else ----------------------------------------------------
    "wayvnc": {
        "packages": _same("wayvnc"),
        "method": "system", "licence": "ISC",
        "group": "optional", "for_session": True,
        "title": "Interactive remote control",
        "unlocks": "Use native apps from another device — a real VNC server for "
                   "the AgentOS compositor, streaming the screen and sending your "
                   "clicks and keys back. AgentOS starts it on loopback only, "
                   "because wayvnc ships with no password.",
        "detect": lambda: bool(shutil.which("wayvnc")),
    },
    "novnc": {
        "packages": _same("novnc"),
        "method": "system", "licence": "MPL-2.0",
        "group": "optional", "for_session": True,
        "title": "Remote Desktop in a browser",
        "unlocks": "Use the real screen — native apps included — from a phone or "
                   "any browser, with no VNC app to install. AgentOS relays it "
                   "over its own authenticated connection, so the VNC port stays "
                   "on 127.0.0.1 and nothing new is exposed to the network.",
        "detect": lambda: _novnc_present(),
    },
    "ddcutil": {
        "packages": _same("ddcutil"),
        "method": "system", "licence": "GPL-2.0+",
        "group": "optional", "for_session": False,
        "title": "External monitor brightness",
        "unlocks": "Brightness control for desktop monitors over DDC/CI "
                   "(machines without an internal backlight).",
        "detect": lambda: bool(shutil.which("ddcutil")),
    },
    "power-profiles-daemon": {
        "packages": _same("power-profiles-daemon"),
        "method": "system", "licence": "GPL-3.0+",
        "group": "optional", "for_session": False,
        "title": "Power profiles",
        "unlocks": "Switch between power-saver, balanced and performance modes.",
        "detect": lambda: bool(shutil.which("powerprofilesctl")),
    },
    "wmctrl": {
        "packages": _same("wmctrl"),
        "method": "system", "licence": "GPL-2.0+",
        "group": "optional", "for_session": False,
        "title": "X11 window control",
        "unlocks": "See and control native windows when running hosted on an "
                   "X11 desktop.",
        "detect": lambda: bool(shutil.which("wmctrl")),
    },
    "upower": {
        "packages": _same("upower"),
        "method": "system", "licence": "GPL-2.0+",
        "group": "optional", "for_session": False,
        "title": "Battery status",
        "unlocks": "Battery level and charging state.",
        "detect": lambda: bool(shutil.which("upower")),
    },
    "wlsunset": {
        "packages": _same("wlsunset"),
        "method": "system", "licence": "MIT",
        "group": "optional", "for_session": True,
        "title": "Night light",
        "unlocks": "Warms the screen after dark (System Settings → Displays).",
        "detect": lambda: bool(shutil.which("wlsunset")),
    },
    "playerctl": {
        "packages": _same("playerctl"),
        "method": "system", "licence": "LGPL-3.0+",
        "group": "optional", "for_session": False,
        "title": "Media keys",
        "unlocks": "Play/pause, next and previous keys control whatever is "
                   "playing, in any app.",
        "detect": lambda: bool(shutil.which("playerctl")),
    },
    "printing": {
        "packages": {"debian": "cups system-config-printer",
                     "rhel": "cups system-config-printer",
                     "arch": "cups system-config-printer",
                     "suse": "cups"},
        "method": "system", "licence": "Apache-2.0",
        "group": "optional", "for_session": False,
        "title": "Printers",
        "unlocks": "Discovering and printing to network and USB printers.",
        "detect": lambda: bool(shutil.which("lpstat")),
    },
    "plymouth-theme": {
        "packages": {}, "method": "script", "licence": "MIT (AgentOS)",
        "group": "optional", "for_session": True,
        "title": "Branded boot splash",
        "unlocks": "The AgentOS mark from the first frame of boot — no distro "
                   "splash between power-on and the desktop. Rebuilds the "
                   "initramfs (takes a minute).",
        "detect": lambda: _plymouth_theme_installed(),
    },
}

#: Order the installer and the settings panel present groups in.
GROUPS = ("required", "recommended", "optional")


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


def packages_for(comp: dict, family: str = "") -> str:
    """The package names for this family, or '' when none are known."""
    family = family or osdetect.family()
    return (comp.get("packages") or {}).get(family, "")


def install_argv(comp: dict) -> list[str]:
    """Exact argv that installs this component here, or [] if we cannot say.

    argv, not a string, so nothing is ever assembled by shell concatenation.
    """
    if comp["method"] == "script":
        return ["sh", _plymouth_script()]
    if comp["method"] == "snap" and shutil.which("snap"):
        pkg = packages_for(comp) or (comp.get("packages") or {}).get("debian", "")
        return ["snap", "install", pkg] if pkg else []
    pkgs = packages_for(comp)
    return osdetect.install_argv(pkgs) if pkgs else []


def install_command(comp: dict) -> str:
    """The same thing as a copy-pasteable string, or '' when unavailable."""
    return " ".join(install_argv(comp))


def unavailable_reason(comp: dict) -> str:
    """Why this component cannot be installed here — an honest sentence, or ''.

    A missing capability must report why plus what would fix it, never a dead
    control. That rule applies to the installer itself.
    """
    if install_argv(comp):
        return ""
    d = osdetect.detect()
    # The OS-level reason outranks every package-level one. Telling a macOS user
    # "no macos-family package name is known for this component" is technically
    # true and useless; the fact that matters is that the session is Linux-only.
    if d["os"] != "linux":
        return d["why"] or f"not available on {d['pretty']}"
    if comp["method"] == "snap" and not shutil.which("snap") and not packages_for(comp):
        return "needs snapd, which is not installed"
    if not d["family"]:
        return d["why"] or f"AgentOS has no package name for {d['pretty']}"
    if not packages_for(comp):
        return f"no {d['family']}-family package name is known for this component"
    if not d["manager"]:
        return d["why"] or "no usable package manager was found"
    return "cannot be installed automatically here"


def catalog(session_only: bool = False) -> list[dict]:
    """Every entry, resolved for THIS machine.

    `package` and `command` are what would actually run here — not a Debian
    command shown to a Fedora user. `available` is False with a `reason` when
    this machine has no way to install the thing, so the UI can say why rather
    than offering a button that cannot work.
    """
    d = osdetect.detect()
    out = []
    for cid, c in CATALOG.items():
        if session_only and not c.get("for_session"):
            continue
        argv = install_argv(c)
        out.append({
            "id": cid, "title": c["title"],
            "package": packages_for(c) or c.get("packages", {}).get("debian", ""),
            "method": c["method"],
            "manager": ("snap" if argv[:1] == ["snap"] else
                        "script" if c["method"] == "script" else d["manager"]),
            "licence": c["licence"], "unlocks": c["unlocks"],
            "group": c.get("group", "optional"),
            "for_session": bool(c.get("for_session")),
            "installed": bool(c["detect"]()),
            "available": bool(argv),
            "reason": unavailable_reason(c),
            "command": f"sudo {' '.join(argv)}" if argv else "",
        })
    order = {g: i for i, g in enumerate(GROUPS)}
    out.sort(key=lambda r: (order.get(r["group"], 9), r["title"]))
    return out


def missing(session_only: bool = True, groups: tuple = ("required",)) -> list[dict]:
    """What is not installed yet — the installer's worklist."""
    return [r for r in catalog(session_only=session_only)
            if not r["installed"] and r["group"] in groups]


async def _run(argv: list[str], timeout: float) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "timed out"
    return proc.returncode or 0, out.decode(errors="replace")


async def refresh_index() -> tuple[bool, str]:
    """Refresh the package index where the family needs it before installing.

    On Debian this is the single most common cause of "package not found" on a
    machine that has been switched off for a while. Best effort: a failure here
    is reported but never blocks the install attempt itself.
    """
    argv = osdetect.detect()["refresh_argv"]
    if not argv:
        return True, ""
    rc, _ = await _run(["sudo", "-n", "true"], 10)
    prefix = ["sudo", "-n"] if rc == 0 else (["pkexec"] if shutil.which("pkexec") else [])
    if not prefix:
        return False, "no root access to refresh the package index"
    rc, out = await _run(prefix + argv, 300)
    return rc == 0, ("" if rc == 0 else out[-300:])


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

    argv = install_argv(comp)
    if not argv:
        # Nothing to run, and saying "failed" would be a lie — this machine
        # simply has no route to it. Say which, and stop.
        return {"ok": False, "needs_terminal": False, "command": "",
                "message": f"{comp['title']} cannot be installed here: "
                           f"{unavailable_reason(comp)}."}

    cmd = " ".join(argv)
    manual = {"ok": False, "needs_terminal": True, "command": f"sudo {cmd}",
              "message": "Root access is needed — run this in the Terminal:"}

    # 1) passwordless sudo
    rc, _ = await _run(["sudo", "-n", "true"], 10)
    if rc == 0:
        rc, out = await _run(["sudo", "-n"] + argv, 900)
        if rc == 0 and comp["detect"]():
            _refresh_platform()
            return {"ok": True, "message": f"{comp['title']} installed.",
                    "command": f"sudo {cmd}", "needs_terminal": False}
        return {**manual, "message": out[-400:] or manual["message"]}

    # 2) polkit prompt (hosted desktops have an auth agent)
    if shutil.which("pkexec"):
        rc, out = await _run(["pkexec"] + argv, 900)
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
    try:
        from . import shellhost
        shellhost.python_with_gi(refresh=True)
    except Exception:
        pass
