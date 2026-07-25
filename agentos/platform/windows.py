"""Windows — AgentOS as an app on the Windows desktop.

Moved verbatim from host.py. Like macOS, there is no AgentOS-as-the-session mode
here; this backend keeps the shared UI honest about what Windows will and won't
let us drive.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import caps as C
from .base import Capability, Platform, missing, ok, run

WIN_APP_DIRS = [
    str(Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"),
    str(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs"),
]

WIN_SETTINGS_PAGES = {
    "sound": "ms-settings:sound", "audio": "ms-settings:sound",
    "network": "ms-settings:network", "wifi": "ms-settings:network-wifi",
    "bluetooth": "ms-settings:bluetooth", "display": "ms-settings:display",
    "power": "ms-settings:powersleep", "background": "ms-settings:personalization-background",
}


class Windows(Platform):
    name = "Windows"

    def __init__(self, mode: str = "hosted"):
        super().__init__(mode=mode, name="Windows")

    def _probe(self) -> dict[str, Capability]:
        caps: dict[str, Capability] = {
            C.APPS_LIST: ok(C.APPS_LIST),
            C.APPS_LAUNCH: ok(C.APPS_LAUNCH),
            C.POWER_BATTERY: ok(C.POWER_BATTERY),
            C.NET_STATUS: ok(C.NET_STATUS),
            C.NOTIFY_SEND: ok(C.NOTIFY_SEND),
            C.SETTINGS_OPEN: ok(C.SETTINGS_OPEN),
            C.WALLPAPER_GET: ok(C.WALLPAPER_GET),
            # host.set_volume() has always returned False here — no backend.
            C.AUDIO_VOLUME: missing(C.AUDIO_VOLUME,
                                    "Volume control isn't wired up on Windows yet."),
        }
        owned = "Windows owns this. Use Settings."
        for cap_id in (C.WINDOWS_LIST, C.WINDOWS_MANAGE, C.WINDOWS_ARRANGE, C.WORKSPACES,
                       C.DISPLAY_LIST, C.DISPLAY_CONFIGURE, C.AUDIO_DEVICES, C.AUDIO_PER_APP,
                       C.NET_WIFI_SCAN, C.NET_WIFI_JOIN, C.NET_AIRPLANE, C.BT_STATUS,
                       C.BT_MANAGE, C.BRIGHTNESS_GET, C.BRIGHTNESS_SET, C.POWER_PROFILE,
                       C.POWER_SESSION, C.SESSION_LOCK, C.SESSION_LOGOUT,
                       C.NOTIFY_DAEMON, C.SCREEN_CAPTURE, C.WALLPAPER_SET, C.SETTINGS_NATIVE):
            caps[cap_id] = Capability(cap_id, False, False, owned)
        return caps

    # --- native applications ----------------------------------------------

    def list_apps(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for d in WIN_APP_DIRS:
            p = Path(d)
            if not p.is_dir():
                continue
            for f in p.rglob("*.lnk"):
                name = f.stem
                if name.lower().startswith("uninstall"):
                    continue
                seen.setdefault(name, {"id": name, "name": name, "comment": "", "icon": "",
                                       "categories": [], "terminal": False})
        return sorted(seen.values(), key=lambda a: a["name"].lower())

    def launch_app(self, app_id: str) -> tuple[bool, str]:
        if not re.fullmatch(r"[\w .+()&,'-]+", app_id or ""):
            return False, "invalid app id"
        lnk = None
        for d in WIN_APP_DIRS:
            if Path(d).is_dir():
                lnk = next(iter(Path(d).rglob(f"{app_id}.lnk")), None)
                if lnk:
                    break
        if not lnk:
            return False, "app not found"
        try:
            os.startfile(str(lnk))   # noqa: S606 - Windows-only API
            return True, "launched"
        except Exception as e:
            return False, str(e)

    # --- system controls ---------------------------------------------------

    def get_volume(self) -> dict:
        return {"volume": None, "muted": False}

    def set_volume(self, percent: int | None = None, mute: bool | None = None) -> bool:
        return False

    def get_battery(self) -> dict:
        out = run(["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance Win32_Battery).EstimatedChargeRemaining"], timeout=10)
        return {"percent": int(out), "state": ""} if out.strip().isdigit() else {}

    def get_network(self) -> dict:
        out = run(["powershell", "-NoProfile", "-Command",
                   "(Get-NetConnectionProfile | Select-Object -ExpandProperty Name) -join ','"],
                  timeout=10)
        conns = [{"type": "network", "name": n.strip()} for n in out.split(",") if n.strip()]
        return {"connections": conns, "online": bool(conns)}

    def open_settings(self, panel: str = "") -> tuple[bool, str]:
        key = panel.lower().strip()
        try:
            os.startfile(WIN_SETTINGS_PAGES.get(key, "ms-settings:"))   # noqa: S606
            return True, f"opened settings{': ' + key if key in WIN_SETTINGS_PAGES else ''}"
        except Exception as e:
            return False, str(e)

    # --- windows -----------------------------------------------------------

    def list_windows(self) -> dict:
        return {"available": False, "windows": [],
                "reason": "Native window control is currently available on Linux (X11) only."}
