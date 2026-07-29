"""Linux, running on somebody else's desktop (GNOME, KDE, Xfce…).

This is what AgentOS has always done and remains the default: we are a guest.
The host desktop owns the session, the notification bus, wifi, bluetooth and the
wallpaper; we read what we can, hand off to its settings app for the rest, and
manage X11 windows through wmctrl when it's there.

Every implementation here was moved verbatim from host.py — this backend must be
behaviour-identical to what shipped before the platform layer existed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import caps as C
from .base import Capability, Platform, missing, ok, run, unsupported

APP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    str(Path.home() / ".local/share/applications"),
    str(Path.home() / ".local/share/flatpak/exports/share/applications"),
]
ICON_THEME_DIRS = [
    Path.home() / ".local/share/icons",
    Path("/usr/share/icons/hicolor"),
    Path("/usr/share/icons/Adwaita"),
    Path("/usr/share/icons/Yaru"),
    Path("/usr/share/pixmaps"),
]

SETTINGS_PANELS = {
    "sound": "sound", "audio": "sound", "network": "network", "wifi": "wifi",
    "bluetooth": "bluetooth", "display": "display", "power": "power",
    "background": "background", "settings": "", "": "",
}


def _clean_exec(cmd: str) -> str:
    """A .desktop Exec= line with the field codes removed.

    %f %F %u %U %i %c %k are placeholders the launcher is supposed to substitute;
    run verbatim they become literal arguments and confuse the app. We launch
    without documents, so dropping them is exactly right.
    """
    import re as _re
    cmd = _re.sub(r"%[fFuUdDnNickvm]", "", cmd or "")
    return " ".join(cmd.split())


def _parse_desktop(path: Path) -> dict | None:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    entry = {}
    in_entry = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k not in entry:  # first (unlocalized) wins
            entry[k.strip()] = v.strip()
    if entry.get("Type") not in (None, "Application"):
        return None
    if entry.get("NoDisplay", "").lower() == "true" or entry.get("Hidden", "").lower() == "true":
        return None
    if not entry.get("Name") or not entry.get("Exec"):
        return None
    return {
        "id": path.stem,
        "name": entry["Name"],
        "comment": entry.get("Comment", ""),
        "icon": entry.get("Icon", ""),
        "categories": [c for c in entry.get("Categories", "").split(";") if c],
        "terminal": entry.get("Terminal", "").lower() == "true",
        # How a RUNNING window identifies itself. Toolkits disagree with the
        # .desktop file name often enough that without this the taskbar shows a
        # letter instead of the app's icon.
        "wmclass": entry.get("StartupWMClass", ""),
        # The command itself, so a launch does not have to pay for gtk-launch
        # re-reading and re-parsing this same file in another process.
        "exec": _clean_exec(entry.get("Exec", "")),
        "dbus": entry.get("DBusActivatable", "").lower() == "true",
    }


class LinuxHosted(Platform):
    name = "Linux"

    def __init__(self, mode: str = "hosted"):
        super().__init__(mode=mode, name="Linux")

    # --- capabilities ------------------------------------------------------

    def _session_is_wayland(self) -> bool:
        return os.environ.get("XDG_SESSION_TYPE") == "wayland"

    def _probe(self) -> dict[str, Capability]:
        has = shutil.which
        caps: dict[str, Capability] = {C.APPS_LIST: ok(C.APPS_LIST)}

        caps[C.APPS_LAUNCH] = (
            ok(C.APPS_LAUNCH) if (has("gtk-launch") or has("gio"))
            else missing(C.APPS_LAUNCH,
                         "Needs gtk-launch or gio to start desktop applications.")
        )

        # Window control: wmctrl is X11-only by nature, and Wayland forbids one
        # app from enumerating another's windows. Neither is a bug we can fix
        # from here — the AgentOS session is the answer, which is the whole
        # point of the DE work.
        if self._session_is_wayland():
            why = ("Wayland stops applications from controlling each other's windows. "
                   "Log into the AgentOS session to manage native windows here.")
            caps[C.WINDOWS_LIST] = Capability(C.WINDOWS_LIST, True, False, why)
            caps[C.WINDOWS_MANAGE] = Capability(C.WINDOWS_MANAGE, True, False, why)
        elif has("wmctrl"):
            caps[C.WINDOWS_LIST] = ok(C.WINDOWS_LIST)
            caps[C.WINDOWS_MANAGE] = ok(C.WINDOWS_MANAGE)
        else:
            why = "Needs wmctrl to see and control native windows on X11."
            caps[C.WINDOWS_LIST] = missing(C.WINDOWS_LIST, why, "wmctrl")
            caps[C.WINDOWS_MANAGE] = missing(C.WINDOWS_MANAGE, why, "wmctrl")

        caps[C.AUDIO_VOLUME] = (
            ok(C.AUDIO_VOLUME) if (has("wpctl") or has("amixer"))
            else missing(C.AUDIO_VOLUME, "Needs PipeWire (wpctl) or ALSA (amixer).")
        )
        caps[C.POWER_BATTERY] = (
            ok(C.POWER_BATTERY) if has("upower")
            else missing(C.POWER_BATTERY, "Needs upower to read battery status.", "upower")
        )
        caps[C.NET_STATUS] = (
            ok(C.NET_STATUS) if has("nmcli")
            else missing(C.NET_STATUS, "Needs NetworkManager to report connections.",
                         "network-manager")
        )
        for cap_id in (C.POWER_SESSION, C.SESSION_LOCK, C.SESSION_LOGOUT):
            caps[cap_id] = (
                ok(cap_id) if has("systemctl") and has("loginctl")
                else missing(cap_id, "Needs systemd (systemctl/loginctl) for session control.")
            )
        caps[C.NOTIFY_SEND] = (
            ok(C.NOTIFY_SEND) if has("notify-send")
            else missing(C.NOTIFY_SEND, "Needs notify-send (libnotify) to raise notifications.")
        )
        caps[C.SETTINGS_OPEN] = (
            ok(C.SETTINGS_OPEN) if has("gnome-control-center")
            else missing(C.SETTINGS_OPEN,
                         "Needs your desktop's own settings app to hand off to.")
        )
        caps[C.WALLPAPER_GET] = (
            ok(C.WALLPAPER_GET) if has("gsettings")
            else missing(C.WALLPAPER_GET, "Needs gsettings to read the desktop wallpaper.")
        )

        # Owned by the host desktop while we are its guest. Not a missing
        # package — a deliberate boundary, so say so plainly.
        guest = "Your desktop environment owns this. Open its settings, or run the AgentOS session."
        for cap_id in (C.NET_WIFI_SCAN, C.NET_WIFI_JOIN, C.NET_AIRPLANE, C.BT_STATUS,
                       C.BT_MANAGE, C.BRIGHTNESS_GET, C.BRIGHTNESS_SET, C.POWER_PROFILE,
                       C.DISPLAY_LIST, C.DISPLAY_CONFIGURE, C.WORKSPACES,
                       C.WINDOWS_ARRANGE, C.AUDIO_DEVICES, C.AUDIO_PER_APP,
                       C.WALLPAPER_SET, C.SCREEN_CAPTURE, C.SETTINGS_NATIVE):
            caps[cap_id] = Capability(cap_id, True, False, guest)

        # Claiming org.freedesktop.Notifications as a guest would fight the host
        # desktop for the bus name and silently break its notifications.
        caps[C.NOTIFY_DAEMON] = Capability(
            C.NOTIFY_DAEMON, True, False,
            "Your desktop environment is the notification daemon. "
            "Run the AgentOS session to collect app notifications here.")
        return caps

    # --- native applications ----------------------------------------------

    def list_apps(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for d in APP_DIRS:
            p = Path(d)
            if not p.is_dir():
                continue
            for f in p.glob("*.desktop"):
                e = _parse_desktop(f)
                if e:
                    seen[e["id"]] = e  # later dirs (user) override system
        return sorted(seen.values(), key=lambda a: a["name"].lower())

    def resolve_icon(self, name: str) -> str | None:
        """Return a filesystem path for a .desktop Icon= (a name or an absolute path)."""
        if not name:
            return None
        if os.path.isabs(name) and os.path.isfile(name):
            return name
        for ext in (".png", ".svg", ".xpm"):
            cand = Path("/usr/share/pixmaps") / (name + ext)   # pixmaps (flat)
            if cand.is_file():
                return str(cand)
        # themed icons: <theme>/<size>/apps/<name>.(png|svg)
        for theme in ICON_THEME_DIRS:
            if not theme.is_dir():
                continue
            for sub in ("scalable/apps", "512x512/apps", "256x256/apps", "128x128/apps",
                        "96x96/apps", "64x64/apps", "48x48/apps"):
                for ext in (".svg", ".png"):
                    cand = theme / sub / (name + ext)
                    if cand.is_file():
                        return str(cand)
            # some themes nest size dirs differently; do a shallow glob fallback
            for ext in (".svg", ".png"):
                hits = list(theme.glob(f"*/apps/{name}{ext}"))
                if hits:
                    return str(hits[0])
        return None

    def launch_app(self, app_id: str) -> tuple[bool, str]:
        # no path separators or shell metachars
        if not re.fullmatch(r"[\w .+()&,'-]+", app_id or ""):
            return False, "invalid app id"
        launcher = shutil.which("gtk-launch")
        try:
            if launcher:
                subprocess.Popen([launcher, app_id], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which("gio"):
                # find the .desktop path and launch it
                path = next((str(Path(d) / f"{app_id}.desktop") for d in APP_DIRS
                             if (Path(d) / f"{app_id}.desktop").is_file()), None)
                if not path:
                    return False, "app not found"
                subprocess.Popen(["gio", "launch", path], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                return False, "no launcher (gtk-launch/gio) available"
        except Exception as e:
            return False, str(e)
        return True, "launched"

    # --- system controls ---------------------------------------------------

    def get_volume(self) -> dict:
        if shutil.which("wpctl"):
            out = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])  # "Volume: 0.55 [MUTED]"
            m = re.search(r"([\d.]+)", out)
            vol = int(round(float(m.group(1)) * 100)) if m else None
            return {"volume": vol, "muted": "MUTED" in out}
        if shutil.which("amixer"):
            out = run(["amixer", "get", "Master"])
            m = re.search(r"\[(\d+)%\]", out)
            return {"volume": int(m.group(1)) if m else None, "muted": "[off]" in out}
        return {"volume": None, "muted": False}

    def set_volume(self, percent: int | None = None, mute: bool | None = None) -> bool:
        if not shutil.which("wpctl"):
            if shutil.which("amixer"):
                if mute is not None:
                    run(["amixer", "set", "Master", "mute" if mute else "unmute"])
                if percent is not None:
                    run(["amixer", "set", "Master", f"{max(0, min(100, percent))}%"])
                return True
            return False
        if mute is not None:
            run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if mute else "0"])
        if percent is not None:
            run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{max(0, min(150, percent))}%"])
        return True

    def get_battery(self) -> dict:
        if not shutil.which("upower"):
            return {}
        dev = ""
        for line in run(["upower", "-e"]).splitlines():
            if "battery" in line.lower():
                dev = line.strip()
                break
        if not dev:
            return {}
        info = run(["upower", "-i", dev])
        pct = re.search(r"percentage:\s*(\d+)", info)
        state = re.search(r"state:\s*(\w+)", info)
        return {"percent": int(pct.group(1)) if pct else None,
                "state": state.group(1) if state else ""}

    def get_network(self) -> dict:
        if not shutil.which("nmcli"):
            return {}
        out = run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device", "status"])
        conns = []
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "connected" and parts[0] in ("wifi", "ethernet"):
                conns.append({"type": parts[0], "name": parts[2]})
        return {"connections": conns, "online": bool(conns)}

    def open_settings(self, panel: str = "") -> tuple[bool, str]:
        key = panel.lower().strip()
        try:
            exe = shutil.which("gnome-control-center")
            if not exe:
                return False, "gnome-control-center not available"
            p = SETTINGS_PANELS.get(key, panel.strip())
            subprocess.Popen([exe] + ([p] if p else []), start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"opened settings{': ' + p if p else ''}"
        except Exception as e:
            return False, str(e)

    # --- native window management (needs wmctrl; X11 / XWayland only) ------

    def list_windows(self) -> dict:
        exe = shutil.which("wmctrl")
        wayland = self._session_is_wayland()
        if not exe:
            reason = ("Window control needs `wmctrl` — install it with `sudo apt install wmctrl`."
                      + (" You're on a Wayland session; log into an X11 session for full support."
                         if wayland else ""))
            return {"available": False, "reason": reason, "windows": []}
        out = run([exe, "-lpx"])
        wins = []
        for line in out.splitlines():
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            winid, desk, pid, wmclass, _host, title = parts
            if desk == "-1":               # panels / sticky / docks
                continue
            cls = (wmclass or "").lower()
            if "agentos" in cls or title.strip() == "AgentOS":   # don't list ourselves
                continue
            wins.append({"id": winid, "pid": int(pid) if pid.isdigit() else 0,
                         "app": wmclass.split(".")[-1] if wmclass else "", "title": title})
        if not wins and wayland:
            return {"available": False, "windows": [],
                    "reason": "No controllable windows — Wayland restricts window control. "
                              "Log into an X11 session to manage and switch native windows here."}
        return {"available": True, "windows": wins}

    def _wmctrl_win(self, action: str, win_id: str) -> tuple[bool, str]:
        exe = shutil.which("wmctrl")
        if not exe:
            return False, "wmctrl not installed"
        if not re.fullmatch(r"0x[0-9a-fA-F]+", win_id or ""):
            return False, "invalid window id"
        try:
            subprocess.run([exe, "-i", action, win_id], timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            return False, str(e)
        return True, "ok"

    def focus_window(self, win_id: str) -> tuple[bool, str]:
        return self._wmctrl_win("-a", win_id)   # activate/raise

    def close_window(self, win_id: str) -> tuple[bool, str]:
        return self._wmctrl_win("-c", win_id)   # graceful close
