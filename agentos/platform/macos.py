"""macOS — AgentOS as an app on the Mac desktop.

Moved verbatim from host.py. macOS has no AgentOS-as-the-session mode and never
will: the compositor isn't ours to replace. This backend exists so the same UI
renders correctly on a Mac, with the controls Apple doesn't expose greyed out
and explained rather than broken.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import caps as C
from .base import Capability, Platform, ok, run

MAC_APP_DIRS = ["/Applications", "/System/Applications",
                "/System/Applications/Utilities", str(Path.home() / "Applications")]

MAC_SETTINGS_PANES = {
    "sound": "com.apple.preference.sound", "audio": "com.apple.preference.sound",
    "network": "com.apple.preference.network", "wifi": "com.apple.preference.network",
    "bluetooth": "com.apple.preferences.Bluetooth",
    "display": "com.apple.preference.displays", "power": "com.apple.preference.battery",
    "background": "com.apple.preference.desktopscreeneffect",
}


class MacOS(Platform):
    name = "macOS"

    def __init__(self, mode: str = "hosted"):
        super().__init__(mode=mode, name="macOS")

    def _probe(self) -> dict[str, Capability]:
        caps: dict[str, Capability] = {
            C.APPS_LIST: ok(C.APPS_LIST),
            C.APPS_LAUNCH: ok(C.APPS_LAUNCH),
            C.AUDIO_VOLUME: ok(C.AUDIO_VOLUME),
            C.POWER_BATTERY: ok(C.POWER_BATTERY),
            C.NET_STATUS: ok(C.NET_STATUS),
            C.POWER_SESSION: ok(C.POWER_SESSION),
            C.SESSION_LOCK: ok(C.SESSION_LOCK),
            C.SESSION_LOGOUT: ok(C.SESSION_LOGOUT),
            C.NOTIFY_SEND: ok(C.NOTIFY_SEND),
            C.SETTINGS_OPEN: ok(C.SETTINGS_OPEN),
            C.WALLPAPER_GET: ok(C.WALLPAPER_GET),
        }
        owned = "macOS owns this. Use System Settings."
        for cap_id in (C.WINDOWS_LIST, C.WINDOWS_MANAGE, C.WINDOWS_ARRANGE, C.WORKSPACES,
                       C.DISPLAY_LIST, C.DISPLAY_CONFIGURE, C.AUDIO_DEVICES, C.AUDIO_PER_APP,
                       C.NET_WIFI_SCAN, C.NET_WIFI_JOIN, C.NET_AIRPLANE, C.BT_STATUS,
                       C.BT_MANAGE, C.BRIGHTNESS_GET, C.BRIGHTNESS_SET, C.POWER_PROFILE,
                       C.NOTIFY_DAEMON, C.SCREEN_CAPTURE, C.WALLPAPER_SET, C.SETTINGS_NATIVE):
            caps[cap_id] = Capability(cap_id, False, False, owned)
        return caps

    # --- native applications ----------------------------------------------

    def list_apps(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for d in MAC_APP_DIRS:
            p = Path(d)
            if not p.is_dir():
                continue
            for f in p.glob("*.app"):
                name = f.stem
                seen[name] = {"id": name, "name": name, "comment": "", "icon": "",
                              "categories": [], "terminal": False}
        return sorted(seen.values(), key=lambda a: a["name"].lower())

    def launch_app(self, app_id: str) -> tuple[bool, str]:
        # names may contain spaces; still no path separators or shell metachars
        if not re.fullmatch(r"[\w .+()&,'-]+", app_id or ""):
            return False, "invalid app id"
        try:
            subprocess.Popen(["open", "-a", app_id], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "launched"
        except Exception as e:
            return False, str(e)

    # --- system controls ---------------------------------------------------

    def get_volume(self) -> dict:
        out = run(["osascript", "-e",
                   "output volume of (get volume settings) & \",\" & "
                   "output muted of (get volume settings)"])
        parts = out.split(",")
        vol = int(parts[0]) if parts and parts[0].strip().isdigit() else None
        return {"volume": vol, "muted": len(parts) > 1 and "true" in parts[1].lower()}

    def set_volume(self, percent: int | None = None, mute: bool | None = None) -> bool:
        if mute is not None:
            run(["osascript", "-e", f"set volume output muted {'true' if mute else 'false'}"])
        if percent is not None:
            run(["osascript", "-e", f"set volume output volume {max(0, min(100, percent))}"])
        return True

    def get_battery(self) -> dict:
        out = run(["pmset", "-g", "batt"])   # "… 85%; charging; …"
        pct = re.search(r"(\d+)%", out)
        st = re.search(r"%;\s*([\w ]+?);", out)
        if not pct:
            return {}
        return {"percent": int(pct.group(1)), "state": (st.group(1).strip() if st else "")}

    def get_network(self) -> dict:
        out = run(["scutil", "--nwi"])       # lists reachable interfaces, e.g. "en0"
        conns = []
        for m in set(re.findall(r"Network interfaces:\s*([\w ,]+)", out)):
            for iface in m.replace(",", " ").split():
                conns.append({"type": "wifi" if iface.startswith("en0") else "ethernet",
                              "name": iface})
        return {"connections": conns, "online": bool(conns)}

    def open_settings(self, panel: str = "") -> tuple[bool, str]:
        key = panel.lower().strip()
        try:
            pane = MAC_SETTINGS_PANES.get(key)
            cmd = (["open", f"x-apple.systempreferences:{pane}"] if pane
                   else ["open", "-b", "com.apple.systempreferences"])
            subprocess.Popen(cmd, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"opened settings{': ' + key if pane else ''}"
        except Exception as e:
            return False, str(e)

    # --- windows -----------------------------------------------------------

    def list_windows(self) -> dict:
        return {"available": False, "windows": [],
                "reason": "Native window control is currently available on Linux (X11) only."}
