"""Host desktop integration: launch native desktop apps, control volume/battery/network,
open native settings panels. Best-effort — degrades gracefully when a tool is missing.

This is what makes AgentOS a shell *over* the host rather than a sandboxed island:
every installed .desktop app is visible & launchable, and the system controls are wired
to the real host (PipeWire/wpctl, upower, nmcli, gnome-control-center).
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

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
    }


def list_apps() -> list[dict]:
    seen: dict[str, dict] = {}
    for d in APP_DIRS:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in p.glob("*.desktop"):
            e = _parse_desktop(f)
            if e:
                seen[e["id"]] = e  # later dirs (user) override system
    apps = sorted(seen.values(), key=lambda a: a["name"].lower())
    return apps


def resolve_icon(name: str) -> str | None:
    """Return a filesystem path for a .desktop Icon= (a name or an absolute path), best-effort."""
    if not name:
        return None
    if os.path.isabs(name) and os.path.isfile(name):
        return name
    for ext in (".png", ".svg", ".xpm"):
        # pixmaps (flat)
        cand = Path("/usr/share/pixmaps") / (name + ext)
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


def launch_app(app_id: str) -> tuple[bool, str]:
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+", app_id or ""):
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


# --- system controls -------------------------------------------------------------

def _run(cmd: list[str], timeout: float = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def get_volume() -> dict:
    if shutil.which("wpctl"):
        out = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])  # "Volume: 0.55 [MUTED]"
        m = re.search(r"([\d.]+)", out)
        vol = int(round(float(m.group(1)) * 100)) if m else None
        return {"volume": vol, "muted": "MUTED" in out}
    if shutil.which("amixer"):
        out = _run(["amixer", "get", "Master"])
        m = re.search(r"\[(\d+)%\]", out)
        return {"volume": int(m.group(1)) if m else None, "muted": "[off]" in out}
    return {"volume": None, "muted": False}


def set_volume(percent: int | None = None, mute: bool | None = None) -> bool:
    if not shutil.which("wpctl"):
        if shutil.which("amixer"):
            if mute is not None:
                _run(["amixer", "set", "Master", "mute" if mute else "unmute"])
            if percent is not None:
                _run(["amixer", "set", "Master", f"{max(0, min(100, percent))}%"])
            return True
        return False
    if mute is not None:
        _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if mute else "0"])
    if percent is not None:
        _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{max(0, min(150, percent))}%"])
    return True


def get_battery() -> dict:
    if not shutil.which("upower"):
        return {}
    dev = ""
    for line in _run(["upower", "-e"]).splitlines():
        if "battery" in line.lower():
            dev = line.strip()
            break
    if not dev:
        return {}
    info = _run(["upower", "-i", dev])
    pct = re.search(r"percentage:\s*(\d+)", info)
    state = re.search(r"state:\s*(\w+)", info)
    return {"percent": int(pct.group(1)) if pct else None,
            "state": state.group(1) if state else ""}


def get_network() -> dict:
    if not shutil.which("nmcli"):
        return {}
    out = _run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device", "status"])
    conns = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "connected" and parts[0] in ("wifi", "ethernet"):
            conns.append({"type": parts[0], "name": parts[2]})
    return {"connections": conns, "online": bool(conns)}


SETTINGS_PANELS = {
    "sound": "sound", "audio": "sound", "network": "network", "wifi": "wifi",
    "bluetooth": "bluetooth", "display": "display", "power": "power",
    "background": "background", "settings": "", "": "",
}


def open_settings(panel: str = "") -> tuple[bool, str]:
    exe = shutil.which("gnome-control-center")
    if not exe:
        return False, "gnome-control-center not available"
    p = SETTINGS_PANELS.get(panel.lower().strip(), panel.strip())
    try:
        subprocess.Popen([exe] + ([p] if p else []), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return False, str(e)
    return True, f"opened settings{': ' + p if p else ''}"


def control_state() -> dict:
    return {"audio": get_volume(), "battery": get_battery(), "network": get_network()}


# --- native window management (needs wmctrl; works on X11 / XWayland) -------------

def list_windows() -> dict:
    """Open windows on the host desktop. Requires wmctrl. Wayland-native windows can't be
    enumerated (the session forbids it) — only X11/XWayland windows appear."""
    exe = shutil.which("wmctrl")
    wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland"
    if not exe:
        reason = ("Window control needs `wmctrl` — install it with `sudo apt install wmctrl`."
                  + (" You're on a Wayland session; log into an X11 session for full support."
                     if wayland else ""))
        return {"available": False, "reason": reason, "windows": []}
    out = _run([exe, "-lpx"])
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


def _wmctrl_win(action: str, win_id: str) -> tuple[bool, str]:
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


def focus_window(win_id: str) -> tuple[bool, str]:
    return _wmctrl_win("-a", win_id)   # activate/raise


def close_window(win_id: str) -> tuple[bool, str]:
    return _wmctrl_win("-c", win_id)   # graceful close
