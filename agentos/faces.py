"""Faces for this machine's own screen: layouts you switch between, with widgets in them.

Asked for from a Raspberry Pi's kiosk: "the Pi should have different faces, think of these as
different faces and widgets so I can add or build", "some widgets, cool ones, and build". A face
is a LAYOUT and the widgets in it:

  * chat     the Office with the chat column (the kiosk as it was)
  * office   the Office, the whole screen, with the band along the bottom
  * clock    a big clock, the date, and your agent's line
  * board    a grid of widgets
  * ambient  the scene, and a small clock

Widgets are a closed set the page draws itself (cheap on a Pi: one timer for all of them), plus
any of your apps that has a widget view, built in App Studio (`app:<id>`), drawn in the same
sandboxed frame the desktop's widgets use. Five built-in faces, and your own (`custom`), are the
MACHINE's like the rest of `face` (a screen belongs to the box it's plugged into). Read field by
field: an unknown widget or layout is dropped and named, never drawn.

Free of HTTP and asyncio: `bento face faces` uses the same functions with the server down.
"""
from __future__ import annotations

import re

LAYOUTS = ("chat", "office", "clock", "board", "ambient")
MAX_WIDGETS = 8
MAX_CUSTOM = 12

# the widgets this page draws itself: id -> (name, what it shows)
WIDGETS = {
    "clock": ("Clock", "the time, big"),
    "date": ("Date", "the day and the date"),
    "agent": ("Your agent", "its face, and what it's doing or last said"),
    "machine": ("This machine", "processor, memory, temperature and how long it has been up"),
    "network": ("Network", "the Wi-Fi it's on, and whether its hub answers"),
    "timer": ("Timer", "tap to add minutes, tap again to start; it rings when done"),
    "brief": ("Your Brief", "how many things need you today"),
    "quote": ("Your agent says", "the last thing your agent said here, large"),
}

BUILTIN = [
    {"id": "chat", "name": "Chat", "layout": "chat", "widgets": []},
    {"id": "office", "name": "Office", "layout": "office", "widgets": []},
    {"id": "clock", "name": "Clock", "layout": "clock", "widgets": ["clock", "date", "agent"]},
    {"id": "board", "name": "Dashboard", "layout": "board",
     "widgets": ["clock", "agent", "machine", "network", "timer", "brief"]},
    {"id": "ambient", "name": "Ambient", "layout": "ambient", "widgets": ["clock"]},
]
BUILTIN_IDS = {f["id"] for f in BUILTIN}


def _store(cfg: dict) -> dict:
    # `cfg` itself, never `cfg or {}`: an empty config is falsy, and the write went nowhere
    f = cfg.setdefault("face", {})
    if not isinstance(f, dict):
        f = cfg["face"] = {}
    s = f.get("faces")
    if not isinstance(s, dict):
        s = f["faces"] = {}
    return s


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(s or "").lower()).strip("-")[:32]


def clean_face(d: dict, app_ids=()) -> tuple[dict, list[str]]:
    """A face as stored, and what was dropped (named). Raises ValueError on no name."""
    from . import teamlink
    if not isinstance(d, dict):
        raise ValueError("a face is a name, a layout and its widgets")
    name = teamlink.plain(d.get("name"), 24, newlines=False).strip()
    if not name:
        raise ValueError("give the face a name")
    layout = str(d.get("layout") or "board")
    dropped = []
    if layout not in LAYOUTS:
        dropped.append(f"layout '{layout}'")
        layout = "board"
    ws, seen = [], set()
    apps = set(app_ids or ())
    for w in list(d.get("widgets") or [])[:MAX_WIDGETS * 2]:
        w = str(w or "")
        ok = w in WIDGETS or (w.startswith("app:") and w[4:] in apps)
        if not ok:
            dropped.append(f"widget '{w[:40]}'")
            continue
        if w in seen:
            continue
        seen.add(w)
        ws.append(w)
    if len(ws) > MAX_WIDGETS:
        dropped.append(f"{len(ws) - MAX_WIDGETS} widget(s) past {MAX_WIDGETS}")
        ws = ws[:MAX_WIDGETS]
    fid = _slug(d.get("id") or name) or "face"
    if fid in BUILTIN_IDS:
        fid = f"my-{fid}"
    return {"id": fid, "name": name, "layout": layout, "widgets": ws}, dropped


def faces(cfg: dict) -> list[dict]:
    custom = [f for f in (_store(cfg).get("custom") or []) if isinstance(f, dict) and f.get("id")]
    return [{**f, "builtin": True} for f in BUILTIN] + [{**f, "builtin": False} for f in custom]


def current(cfg: dict) -> str:
    c = str(_store(cfg).get("current") or "chat")
    return c if any(f["id"] == c for f in faces(cfg)) else "chat"


def state(cfg: dict) -> dict:
    return {"current": current(cfg), "faces": faces(cfg), "layouts": list(LAYOUTS),
            "widgets": [{"id": k, "name": v[0], "what": v[1]} for k, v in WIDGETS.items()],
            "max_widgets": MAX_WIDGETS}


def use(cfg: dict, fid: str) -> str:
    if not any(f["id"] == fid for f in faces(cfg)):
        raise ValueError(f"no face called '{fid}'")
    _store(cfg)["current"] = fid
    return fid


def save(cfg: dict, d: dict, app_ids=()) -> tuple[dict, list[str]]:
    """Add or replace one of your own faces (by id). A built-in one is never overwritten."""
    face, dropped = clean_face(d, app_ids)
    s = _store(cfg)
    custom = [f for f in (s.get("custom") or []) if isinstance(f, dict) and f.get("id") != face["id"]]
    if len(custom) >= MAX_CUSTOM:
        raise ValueError(f"this screen keeps {MAX_CUSTOM} faces of your own: remove one first")
    custom.append(face)
    s["custom"] = custom
    return face, dropped


def delete(cfg: dict, fid: str) -> bool:
    s = _store(cfg)
    before = len(s.get("custom") or [])
    s["custom"] = [f for f in (s.get("custom") or []) if f.get("id") != fid]
    if s.get("current") == fid:
        s["current"] = "chat"
    return len(s["custom"]) < before
