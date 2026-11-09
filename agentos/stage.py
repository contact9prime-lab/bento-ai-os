"""The Stage: an answer shown, not only written.

Asked for as "if I ask what are the hottest places on earth it shows them on the map in
front of me … every answer becomes a story of images in front of me". While the agent
answers it may call `show_scene`, and each scene appears on the person's screen as it
arrives: a chart, a world map with places and countries, key numbers, a timeline, a chain
of steps, a table. A forwarded brain is silent until its last word (fifty seconds, measured
in chat), and these arrive DURING that silence, so the screen is telling the story while
the text is still being written.

Four rules keep it honest, each pinned by tests/test_stage.py:

- **A scene is a closed set, read field by field** (`clean`), the avatars/office argument:
  the page draws exactly these kinds and fields, an unknown field is dropped and NAMED, and
  every list is capped, because a scene is drawn on a phone too.
- **Numbers say where they came from.** A chart, a map with values, key numbers and a table
  need a `source`, or `illustrative: true`, which the page prints on the scene as
  "Illustrative, not data". A plausible chart of numbers nobody measured is the most
  convincing kind of wrong this OS could put on a screen.
- **The scene belongs to the chat, never the model's choice of chat.** `_conv` is injected
  by the agent loop (like `create_app`'s), and a scene is filed under the question it
  answers (`answer_to`, the conversation's last message from the person), so a reopened
  chat replays each answer's own story. A call with no conversation is refused in words.
- **Everything is text on the page.** The page builds every label with textContent and SVG
  text nodes, never markup, because a scene's words are often a web page's.

Kept free of HTTP and asyncio, like brief.py: `bento story` reads the same rows with the
server down, and `text()` is the terminal's face of a scene.
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid

KINDS = ("chart", "map", "numbers", "timeline", "steps", "table", "image", "video", "film",
         "blueprint")
CHART_TYPES = ("line", "area", "bar", "scatter", "pie")
NEEDS_SOURCE = ("chart", "map", "numbers", "table")   # the kinds that carry measurements

MAX_PER_ANSWER = 8       # a story, not a slideshow
MAX_SERIES = 8
MAX_POINTS = 1500        # per series; a year of daily closes fits
MAX_MARKERS = 300
MAX_ITEMS = 12
MAX_EVENTS = 40
MAX_COLS = 8
MAX_ROWS = 60
TEXT = 300               # a caption or a note
LABEL = 80

COMMON = ("kind", "title", "caption", "say", "source", "illustrative")
FIELDS = {
    "chart": ("chart_type", "series", "x_label", "y_label", "unit", "marks"),
    "map": ("points", "regions", "view", "unit"),
    "numbers": ("items",),
    "timeline": ("events",),
    "steps": ("items", "ordered"),
    "table": ("columns", "rows"),
    "image": ("url", "asset", "alt", "credit"),
    "video": ("url", "start"),
    "film": ("shots", "look"),
    "blueprint": ("subject", "form", "unit", "parts", "links", "unknowns", "facts"),
}

# A blueprint takes a thing apart instead of presenting it: its parts, how they connect,
# the real numbers and how sure anyone is of each, and what nobody can tell from outside.
# Asked for as "give me a fine blueprint of Burj Khalifa … opens the building inside out and
# I can literally drill into anything". The parts nest, so the person drills on the page
# without waiting on a model; past the last level, Go deeper asks for that part's own.
# `form` is how a level is laid out: tower (built in layers along a height, bottom first),
# exploded (a thing made of parts round a core) or flow (a process, in order).
BP_FORMS = ("tower", "exploded", "flow")
BP_CERTAINTY = ("known", "estimated", "unclear")
# a state is never colour alone: the page draws each with its icon and its word
BP_STATUS = ("ok", "refused", "asked", "waiting", "failed", "stopped", "running")
BP_DEPTH = 4             # levels of parts under the subject
BP_CHILDREN = 12         # parts at one level: more than that is a list, not a drawing
BP_NODES = 160           # parts in all; a blueprint is drawn on a phone too
BP_FACTS = 6
BP_LINKS = 160
BP_UNKNOWNS = 6
BP_HEADLINE = 8          # the whole's own key numbers, the spec table
# what a part carries besides its parts: what it does (role), HOW it works, what it is made
# of, its limits or how it fails. A blueprint that only names parts is a list with lines.
BP_PART = ("name", "id", "role", "detail", "how", "made_of", "limits", "facts", "from", "to",
           "width", "certainty", "status", "source", "evidence", "form", "parts", "unknowns")
# what flows along a link. Each is drawn with its own line and a word, never colour alone.
BP_FLOWS = ("load", "power", "fluid", "heat", "air", "data", "signal", "control", "material",
            "money", "people")
# a part with fewer facts than this and no how is THIN: the page says so rather than letting
# a name with a line under it pass for a part that was taken apart
BP_THIN_FACTS = 2

# A film is a short 3D animation the page plays from a shot list, asked for as "stage
# generation should have video generation too … the AI should decide the level". The model
# never writes code for it: it picks each shot's subject and camera from these closed sets,
# and the page's own three.js painter (24l-stage.js `stageFilm`) builds and moves the scene.
# A picture somebody can believe is drawn from what the model said, and nothing it wrote runs.
FILM_SUBJECTS = ("city", "tower", "bars", "rocket", "factory", "solar", "road", "conveyor",
                 "crowd", "globe")
FILM_CAMERAS = ("orbit", "push", "rise", "fly", "top")
FILM_LOOKS = ("day", "dusk", "night")
MAX_SHOTS = 6
SHOT_S = (2, 8)          # seconds a shot may last; a film is under half a minute
VIEWS = ("world", "africa", "asia", "europe", "north america", "south america", "oceania",
         "middle east", "india")
# lon_min, lat_min, lon_max, lat_max
VIEW_BOX = {
    "world": (-180, -58, 180, 84), "africa": (-20, -36, 53, 38), "asia": (25, -12, 150, 60),
    "europe": (-25, 34, 45, 72), "north america": (-170, 7, -50, 75),
    "south america": (-85, -57, -32, 14), "oceania": (110, -50, 180, 5),
    "middle east": (25, 10, 65, 42), "india": (66, 5, 98, 37),
}


# C0/C1 controls (a terminal escape retitles windows) and bidi overrides, the
# teamlink.plain rule: a scene's words are often a web page's.
_CONTROLS = re.compile("[\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def _s(v, n: int = LABEL) -> str:
    """A label: one line of plain text, no controls, cut at a word."""
    t = " ".join(_CONTROLS.sub(" ", str(v if v is not None else "")).split())
    if len(t) <= n:
        return t
    cut = t[:n - 1].rsplit(" ", 1)[0] if " " in t[:n - 1] else t[:n - 1]
    return cut + "…"


def _num(v):
    """A finite number, or None. Strings like '1,234.5' and '12%' are numbers too:
    a model copying a table off a page writes them that way."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        t = v.strip().replace(",", "").rstrip("%").strip()
        try:
            f = float(t)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def _x(v):
    """An x value keeps its kind: a number, or a label (a date, a category)."""
    n = _num(v) if not isinstance(v, str) else None
    return n if n is not None else _s(v, 40)


def _list(v) -> list:
    return v if isinstance(v, list) else []


def clean(spec: dict) -> tuple[dict, list[str]]:
    """The scene the page will draw, and the names of what was dropped. Raises ValueError
    with a sentence the model can act on when the scene cannot be drawn at all."""
    if not isinstance(spec, dict):
        raise ValueError("a scene is an object with a kind")
    kind = str(spec.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    dropped = [k for k in spec if k not in COMMON + FIELDS[kind] and not k.startswith("_")]
    sc: dict = {"kind": kind, "title": _s(spec.get("title"), 120),
                "caption": _s(spec.get("caption"), TEXT),
                "say": _s(spec.get("say") or "", TEXT),
                "source": _s(spec.get("source"), 200),
                "illustrative": bool(spec.get("illustrative"))}
    getattr(_KIND, kind)(spec, sc, dropped)
    measured = (kind in NEEDS_SOURCE and not (kind == "map" and not any(
        r.get("value") is not None for r in sc.get("regions", []) + sc.get("points", [])))) or (
        kind == "film" and any(sh.get("value") is not None or sh.get("items")
                               for sh in sc.get("shots", []))) or (
        kind == "blueprint" and (bool(sc.get("facts")) or _bp_measured(sc.get("parts", []))))
    if measured and not sc["source"] and not sc["illustrative"]:
        raise ValueError("say where these numbers came from (source: a site, a dataset or "
                         "a URL), or set illustrative: true when they are an example")
    return sc, dropped


class _KIND:
    @staticmethod
    def chart(spec, sc, dropped):
        ct = str(spec.get("chart_type") or "line").lower()
        if ct not in CHART_TYPES:
            dropped.append(f"chart_type {ct!r}")
            ct = "line"
        series = []
        for s in _list(spec.get("series"))[:MAX_SERIES]:
            if not isinstance(s, dict):
                continue
            pts = []
            for p in _list(s.get("points"))[:MAX_POINTS]:
                if isinstance(p, dict):
                    p = [p.get("x"), p.get("y")]
                if not isinstance(p, (list, tuple)) or len(p) < 2:
                    continue
                y = _num(p[1])
                if y is None:
                    continue
                pts.append([_x(p[0]), y])
            if pts:
                series.append({"name": _s(s.get("name"), 40), "points": pts})
        if not series:
            raise ValueError("a chart needs series: [{name, points: [[x, y], …]}] with numbers for y")
        if ct == "pie":
            series = series[:1]
            series[0]["points"] = [p for p in series[0]["points"] if p[1] > 0][:MAX_ITEMS]
        marks = []
        for m in _list(spec.get("marks"))[:12]:
            if not isinstance(m, dict):
                continue
            y = _num(m.get("y"))
            x = m.get("x")
            if y is None and x is None:
                continue
            marks.append({**({"y": y} if y is not None else {}),
                          **({"x": _x(x)} if x is not None else {}), "text": _s(m.get("text"), 60)})
        sc.update(chart_type=ct, series=series, marks=marks, x_label=_s(spec.get("x_label"), 40),
                  y_label=_s(spec.get("y_label"), 40), unit=_s(spec.get("unit"), 12))

    @staticmethod
    def map(spec, sc, dropped):
        pts = []
        for p in _list(spec.get("points"))[:MAX_MARKERS]:
            if not isinstance(p, dict):
                continue
            lat, lon = _num(p.get("lat")), _num(p.get("lon"))
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            pts.append({"lat": round(lat, 4), "lon": round(lon, 4), "label": _s(p.get("label"), 48),
                        "value": _num(p.get("value")), "note": _s(p.get("note"), 120)})
        regions = []
        for r in _list(spec.get("regions"))[:200]:
            if not isinstance(r, dict) or not str(r.get("country") or "").strip():
                continue
            regions.append({"country": _s(r.get("country"), 60), "value": _num(r.get("value")),
                            "label": _s(r.get("label"), 60)})
        if not pts and not regions:
            raise ValueError("a map needs points: [{lat, lon, label, value?}] or "
                             "regions: [{country, value?}]")
        view = str(spec.get("view") or "").strip().lower()
        if view and view not in VIEWS:
            dropped.append(f"view {view!r}")
            view = ""
        # lines join the places only when they are a journey (route: true); a set of places
        # that are each their own story is pins with notes, never a route nobody took
        sc.update(points=pts, regions=regions, view=view or "", unit=_s(spec.get("unit"), 12),
                  route=bool(spec.get("route")))

    @staticmethod
    def numbers(spec, sc, dropped):
        items = []
        for it in _list(spec.get("items"))[:MAX_ITEMS]:
            if not isinstance(it, dict) or it.get("value") in (None, ""):
                continue
            items.append({"label": _s(it.get("label"), 48), "value": _s(it.get("value"), 24),
                          "unit": _s(it.get("unit"), 12), "delta": _s(it.get("delta"), 24),
                          "note": _s(it.get("note"), 120), "open": _open(it.get("open"))})
        if not items:
            raise ValueError("numbers needs items: [{label, value, unit?, delta?, note?}]")
        sc["items"] = items

    @staticmethod
    def timeline(spec, sc, dropped):
        ev = []
        for e in _list(spec.get("events"))[:MAX_EVENTS]:
            if isinstance(e, dict) and (e.get("when") or e.get("label")):
                ev.append({"when": _s(e.get("when"), 32), "label": _s(e.get("label"), 80),
                           "note": _s(e.get("note"), 160)})
        if not ev:
            raise ValueError("a timeline needs events: [{when, label, note?}]")
        sc["events"] = ev

    @staticmethod
    def steps(spec, sc, dropped):
        items = []
        for it in _list(spec.get("items"))[:MAX_ITEMS]:
            if isinstance(it, str):
                it = {"title": it}
            if isinstance(it, dict) and (it.get("title") or it.get("text")):
                items.append({"title": _s(it.get("title"), 100), "text": _s(it.get("text"), 200),
                              "note": _s(it.get("note"), 120), "open": _open(it.get("open"))})
        if not items:
            raise ValueError("steps needs items: [{title, text?}], in order")
        sc["items"] = items
        # ordered: false is a list (things waiting, not a sequence): no numbers, no arrows
        sc["ordered"] = spec.get("ordered") is not False

    @staticmethod
    def image(spec, sc, dropped):
        """A picture: an https address on the web, or an asset this machine made or keeps
        (generate_image, save_asset), drawn from /api/assets/<id>/file."""
        url, asset = str(spec.get("url") or "").strip(), str(spec.get("asset") or "").strip()
        if asset and not _ASSET.match(asset):
            raise ValueError("asset must be the id of one of your assets (list_assets shows them)")
        if not asset and not (url.startswith("https://") and len(url) <= 2000 and " " not in url):
            raise ValueError("an image needs url: an https address, or asset: one of your assets' ids")
        sc.update(url="" if asset else url, asset=asset, alt=_s(spec.get("alt") or sc["title"], 160),
                  credit=_s(spec.get("credit"), 120))

    @staticmethod
    def video(spec, sc, dropped):
        """A YouTube video, played from youtube-nocookie.com: a tutorial, a talk, a clip."""
        vid = youtube_id(str(spec.get("url") or ""))
        if not vid:
            raise ValueError("a video needs url: a YouTube address (watch, youtu.be, shorts or embed)")
        start = _num(spec.get("start"))
        sc.update(video=vid, start=int(start) if start and start > 0 else 0,
                  url=f"https://www.youtube.com/watch?v={vid}")

    @staticmethod
    def film(spec, sc, dropped):
        """A short 3D animation, as a shot list: each shot a subject and a camera move from
        the closed sets, a few seconds, and the line said over it. Numbers in a shot (a bar
        each, a tower's height, a crowd's size) need a source like any chart."""
        look = str(spec.get("look") or "day").strip().lower()
        if look not in FILM_LOOKS:
            dropped.append(f"look {look!r}")
            look = "day"
        shots = []
        for sh in _list(spec.get("shots"))[:MAX_SHOTS]:
            if not isinstance(sh, dict):
                continue
            subj = str(sh.get("subject") or "").strip().lower()
            if subj not in FILM_SUBJECTS:
                dropped.append(f"subject {subj!r}")
                continue
            cam = str(sh.get("camera") or "orbit").strip().lower()
            if cam not in FILM_CAMERAS:
                dropped.append(f"camera {cam!r}")
                cam = "orbit"
            secs = _num(sh.get("seconds"))
            secs = int(min(SHOT_S[1], max(SHOT_S[0], secs))) if secs is not None else 4
            out = {"subject": subj, "camera": cam, "seconds": secs,
                   "text": _s(sh.get("text"), 120), "unit": _s(sh.get("unit"), 12),
                   "value": _num(sh.get("value"))}
            if subj == "bars":
                out["items"] = [{"label": _s(it.get("label"), 24), "value": v}
                                for it in _list(sh.get("items"))[:8]
                                if isinstance(it, dict) and (v := _num(it.get("value"))) is not None]
                if not out["items"]:
                    dropped.append("a bars shot with no items")
                    continue
            if subj == "globe":
                out["points"] = [{"lat": round(la, 3), "lon": round(lo, 3), "label": _s(pt.get("label"), 32)}
                                 for pt in _list(sh.get("points"))[:12] if isinstance(pt, dict)
                                 and (la := _num(pt.get("lat"))) is not None and (lo := _num(pt.get("lon"))) is not None
                                 and -90 <= la <= 90 and -180 <= lo <= 180]
            shots.append(out)
        if not shots:
            raise ValueError("a film needs shots: [{subject, camera, seconds, text}], subject one of "
                             + ", ".join(FILM_SUBJECTS) + "; camera one of " + ", ".join(FILM_CAMERAS))
        sc.update(shots=shots, look=look)

    @staticmethod
    def blueprint(spec, sc, dropped):
        """A thing taken apart: parts that nest, each with what it does, its numbers, how sure
        anyone is, and its own parts. Read field by field at every level; what is dropped is
        named with where it was (parts[2].colour), so the model can correct itself."""
        form = str(spec.get("form") or "").strip().lower()
        if form and form not in BP_FORMS:
            dropped.append(f"form {form!r}")
            form = ""
        seen: set[str] = set()
        count = [0]
        parts = _bp_parts(spec.get("parts"), 1, "parts", seen, count, dropped)
        if len(parts) < 2:
            raise ValueError("a blueprint needs parts: at least two [{name, role, parts?: […]}], "
                             "each part what it is and what it does")
        if count[0] > BP_NODES:
            dropped.append(f"{count[0] - BP_NODES} parts past the limit of {BP_NODES}")
        links = []
        for i, ln in enumerate(_list(spec.get("links"))[:BP_LINKS]):
            if not isinstance(ln, dict):
                continue
            a, b = _bp_ref(ln.get("from"), seen), _bp_ref(ln.get("to"), seen)
            if not a or not b or a == b:
                dropped.append(f"links[{i}] (names a part that is not there)")
                continue
            links.append(_bp_link(ln, a, b, f"links[{i}]", dropped))
        sc.update(subject=_s(spec.get("subject") or sc["title"], 80) or "The whole",
                  form=form or _bp_form_of(parts), unit=_s(spec.get("unit"), 12), parts=parts,
                  links=links, facts=_bp_facts(spec.get("facts"), BP_HEADLINE),
                  unknowns=[_s(u, 160) for u in _list(spec.get("unknowns"))[:BP_UNKNOWNS]
                            if str(u or "").strip()])
        if not sc["title"]:
            sc["title"] = sc["subject"]

    @staticmethod
    def table(spec, sc, dropped):
        cols = [_s(c, 40) for c in _list(spec.get("columns"))[:MAX_COLS]]
        rows = []
        for r in _list(spec.get("rows"))[:MAX_ROWS]:
            if isinstance(r, dict):
                r = [r.get(c) for c in cols]
            if isinstance(r, (list, tuple)) and r:
                rows.append([_s(c, 60) for c in list(r)[:len(cols) or MAX_COLS]])
        if not cols or not rows:
            raise ValueError("a table needs columns: [...] and rows: [[...], …]")
        sc.update(columns=cols, rows=rows)


def _bp_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "part"


def _bp_ref(v, seen: set) -> str:
    """A link end: a part's id, or its name as the model wrote it."""
    v = str(v or "").strip()
    if v in seen:
        return v
    sl = _bp_slug(v)
    return sl if sl in seen else ""


def _bp_link(ln: dict, a: str, b: str, at: str, dropped: list) -> dict:
    kind = str(ln.get("kind") or "").strip().lower()
    if kind and kind not in BP_FLOWS:
        dropped.append(f"{at}.kind {kind!r}")
        kind = ""
    return {"from": a, "to": b, "verb": _s(ln.get("verb"), 40), "kind": kind}


# what a model writes in a unit when there is none
_NO_UNIT = {"n/a", "na", "none", "-", "—", "null"}


def _bp_facts(raw, cap: int = BP_FACTS) -> list:
    out = []
    for f in _list(raw)[:cap]:
        if isinstance(f, dict) and str(f.get("value") if f.get("value") is not None else "").strip():
            unit = _s(f.get("unit"), 12)
            out.append({"label": _s(f.get("label"), 40), "value": _s(f.get("value"), 28),
                        "unit": "" if unit.lower() in _NO_UNIT else unit})
    return out


def bp_thin(p: dict) -> bool:
    """A part that names a thing and says almost nothing about it."""
    return len(p.get("facts") or []) < BP_THIN_FACTS and not p.get("how") and not p.get("detail")


def _bp_form_of(parts: list) -> str:
    """The layout a level gets when the model named none: heights mean a tower."""
    return "tower" if any(p.get("from") is not None or p.get("to") is not None for p in parts) \
        else "exploded"


def _bp_parts(raw, depth: int, where: str, seen: set, count: list, dropped: list) -> list:
    out = []
    items = _list(raw)
    if len(items) > BP_CHILDREN:
        dropped.append(f"{where}: {len(items) - BP_CHILDREN} past {BP_CHILDREN} at one level")
    for i, p in enumerate(items[:BP_CHILDREN]):
        at = f"{where}[{i}]"
        if isinstance(p, str):
            p = {"name": p}
        if not isinstance(p, dict) or not str(p.get("name") or "").strip():
            dropped.append(f"{at} (a part needs a name)")
            continue
        count[0] += 1
        if count[0] > BP_NODES:
            continue
        dropped += [f"{at}.{k}" for k in p if k not in BP_PART and not str(k).startswith("_")]
        name = _s(p.get("name"), 60)
        pid = _bp_slug(str(p.get("id") or name))
        base, n = pid, 2
        while pid in seen:
            pid, n = f"{base}-{n}", n + 1
        seen.add(pid)
        cert = str(p.get("certainty") or "known").strip().lower()
        if cert not in BP_CERTAINTY:
            dropped.append(f"{at}.certainty {cert!r}")
            cert = "known"
        status = str(p.get("status") or "").strip().lower()
        if status and status not in BP_STATUS:
            dropped.append(f"{at}.status {status!r}")
            status = ""
        form = str(p.get("form") or "").strip().lower()
        if form and form not in BP_FORMS:
            dropped.append(f"{at}.form {form!r}")
            form = ""
        facts = _bp_facts(p.get("facts"))
        lo, hi = _num(p.get("from")), _num(p.get("to"))
        if lo is not None and hi is not None and hi < lo:
            lo, hi = hi, lo
        w = _num(p.get("width"))
        node = {"id": pid, "name": name, "role": _s(p.get("role"), 160),
                "detail": _s(p.get("detail"), 600), "how": _s(p.get("how"), 600),
                "made_of": _s(p.get("made_of"), 200), "limits": _s(p.get("limits"), 300),
                "facts": facts, "certainty": cert,
                "status": status, "source": _s(p.get("source"), 200),
                "evidence": _s(p.get("evidence"), 240),
                "unknowns": [_s(u, 160) for u in _list(p.get("unknowns"))[:4] if str(u or "").strip()],
                "from": lo, "to": hi,
                # 0 to 1 is a share of the widest; over 1 is the real width in the scene's unit
                "width": (round(max(0.02, w), 3) if w <= 1 else round(min(w, 1e7), 3))
                if w is not None and w > 0 else None}
        kids = []
        if p.get("parts"):
            if depth >= BP_DEPTH:
                dropped.append(f"{at}.parts (deeper than {BP_DEPTH} levels; Go deeper asks for them)")
            else:
                kids = _bp_parts(p.get("parts"), depth + 1, f"{at}.parts", seen, count, dropped)
        node["parts"] = kids
        node["form"] = (form or _bp_form_of(kids)) if kids else ""
        out.append(node)
    return out


def _bp_measured(parts: list, covered: bool = False) -> bool:
    """True when a part carries numbers (facts, heights) that nothing says the source of.
    A part's own source covers it and everything inside it."""
    for p in parts:
        mine = covered or bool(p.get("source"))
        if not mine and (p.get("facts") or p.get("from") is not None or p.get("to") is not None):
            return True
        if _bp_measured(p.get("parts") or [], mine):
            return True
    return False


def bp_walk(parts: list, depth: int = 1):
    """Every part with its depth, parents before children: the terminal's and the tests' view."""
    for p in parts:
        yield p, depth
        yield from bp_walk(p.get("parts") or [], depth + 1)


_ASSET = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
# A card that opens something on this machine: only a Brief item or a Brief group, so a
# story the Brief built can be acted on. Nothing a model writes can name another door.
_OPEN = re.compile(r"^brief:(needs_you|decide|fyi|done|[0-9a-f]{6,32})$")


def _open(v) -> str:
    v = str(v or "").strip()
    return v if _OPEN.match(v) else ""
_YT = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def youtube_id(url: str) -> str:
    """The 11-character id of a YouTube address, or ''. Nothing but YouTube is played."""
    from urllib.parse import urlparse
    u = (url or "").strip()
    host = (urlparse(u if "://" in u else "https://" + u).hostname or "").lower()
    if host not in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
                    "www.youtube-nocookie.com", "youtube-nocookie.com", "music.youtube.com"):
        return ""
    m = _YT.search(u)
    return m.group(1) if m else ""


# -- the terminal's face -----------------------------------------------------------------

_BARS = "▁▂▃▄▅▆▇█"


def _spark(ys: list[float]) -> str:
    if not ys:
        return ""
    if len(ys) > 48:
        step = len(ys) / 48
        ys = [ys[int(i * step)] for i in range(48)]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1
    return "".join(_BARS[min(7, int((y - lo) / span * 7.999))] for y in ys)


def _fmt(n) -> str:
    if n is None:
        return ""
    return f"{n:,.0f}" if abs(n) >= 100 else f"{n:,.2f}".rstrip("0").rstrip(".")


def text(sc: dict) -> str:
    """A scene in plain lines, for `bento story` and the terminal chat."""
    head = f"▶ {sc.get('title') or sc['kind']}"
    out = [head]
    if sc.get("caption"):
        out.append(f"  {sc['caption']}")
    k = sc["kind"]
    if k == "chart":
        u = sc.get("unit") or ""
        for s in sc["series"]:
            ys = [p[1] for p in s["points"]]
            if sc["chart_type"] in ("bar", "pie") and len(ys) <= MAX_ITEMS * 2:
                top = max(abs(y) for y in ys) or 1
                out.append(f"  {s['name']}" if s["name"] else "")
                for x, y in s["points"]:
                    out.append(f"  {str(x)[:18]:<18} {'█' * max(1, round(abs(y) / top * 24))} {_fmt(y)}{u}")
            else:
                out.append(f"  {s['name'] or 'series'}: {_spark(ys)}  "
                           f"{_fmt(ys[0])}{u} → {_fmt(ys[-1])}{u} (low {_fmt(min(ys))}, high {_fmt(max(ys))})")
        for m in sc.get("marks", []):
            out.append(f"  ┄ {m['text']}" + (f" at {_fmt(m['y'])}{u}" if "y" in m else f" at {m.get('x')}"))
    elif k == "map":
        u = sc.get("unit") or ""
        for p in sc["points"]:
            v = f" {_fmt(p['value'])}{u}" if p["value"] is not None else ""
            out.append(f"  ● {p['label'] or '·'}{v}  ({p['lat']:.1f}, {p['lon']:.1f})"
                       + (f" — {p['note']}" if p["note"] else ""))
        for r in sc["regions"]:
            v = f" {_fmt(r['value'])}{u}" if r["value"] is not None else ""
            out.append(f"  ▧ {r['country']}{v}" + (f" — {r['label']}" if r["label"] else ""))
    elif k == "numbers":
        for it in sc["items"]:
            out.append(f"  {it['label']}: {it['value']}{it['unit']}"
                       + (f" ({it['delta']})" if it["delta"] else "")
                       + (f" — {it['note']}" if it["note"] else ""))
    elif k == "timeline":
        for e in sc["events"]:
            out.append(f"  {e['when']:>10} │ {e['label']}" + (f" — {e['note']}" if e["note"] else ""))
    elif k == "steps":
        for i, it in enumerate(sc["items"], 1):
            out.append(f"  {i}. {it['title']}" + (f" — {it['text']}" if it["text"] else ""))
    elif k == "image":
        out.append(f"  🖼 {sc.get('alt') or 'a picture'}  {sc.get('url') or '(one of your assets: ' + sc.get('asset', '') + ')'}")
    elif k == "video":
        out.append(f"  ▶ https://youtu.be/{sc['video']}" + (f"?t={sc['start']}" if sc.get("start") else ""))
    elif k == "film":
        for i, sh in enumerate(sc["shots"], 1):
            v = f" {_fmt(sh['value'])}{sh['unit']}" if sh.get("value") is not None else ""
            out.append(f"  {i}. [{sh['seconds']}s {sh['camera']} · {sh['subject']}]{v}"
                       + (f" {sh['text']}" if sh["text"] else ""))
            for it in sh.get("items") or []:
                out.append(f"       {it['label']}: {_fmt(it['value'])}{sh['unit']}")
            if sh.get("points"):
                out.append("       " + ", ".join(p["label"] or f"{p['lat']:.1f}, {p['lon']:.1f}"
                                                for p in sh["points"]))
    elif k == "blueprint":
        u = sc.get("unit") or ""
        out.append(f"  ⌖ {sc['form']} · {sum(1 for _ in bp_walk(sc['parts']))} parts")
        if sc.get("facts"):
            out.append("  " + " · ".join(f"{f['label']} {bp_value(f)}".strip() for f in sc["facts"]))
        out += _bp_lines(sc["parts"], "  ", u)
        for x in sc.get("unknowns") or []:
            out.append(f"  ? {x}")
    elif k == "table":
        w = [max(len(c), *(len(r[i]) if i < len(r) else 0 for r in sc["rows"])) for i, c in enumerate(sc["columns"])]
        w = [min(x, 24) for x in w]
        out.append("  " + "  ".join(c[:w[i]].ljust(w[i]) for i, c in enumerate(sc["columns"])))
        for r in sc["rows"][:20]:
            out.append("  " + "  ".join((r[i] if i < len(r) else "")[:w[i]].ljust(w[i]) for i in range(len(w))))
    if sc.get("illustrative"):
        out.append("  (illustrative, not data)")
    elif sc.get("source"):
        out.append(f"  source: {sc['source']}")
    return "\n".join(x for x in out if x != "")


BP_MARK = {"ok": "✓", "refused": "✕", "asked": "?", "waiting": "⏸", "failed": "⚠",
           "stopped": "■", "running": "●"}


def bp_value(f: dict) -> str:
    """A fact's value with its unit: '828 m', '$1.69', '12%'. A word unit gets a space."""
    v, u = str(f.get("value") or ""), str(f.get("unit") or "")
    if not u or u in v:          # "$1.69" with unit "$" already says it
        return v
    return f"{v} {u}" if u[:1].isalpha() else v + u


def _bp_lines(parts: list, pad: str, unit: str) -> list[str]:
    out = []
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        span = ""
        if p.get("from") is not None or p.get("to") is not None:
            span = f" [{_fmt(p.get('from'))} → {_fmt(p.get('to'))}{(' ' + unit) if unit else ''}]"
        mark = f"{BP_MARK[p['status']]} " if p.get("status") else ""
        cert = "" if p.get("certainty", "known") == "known" else f" ({p['certainty']})"
        facts = "; ".join(f"{f['label']} {bp_value(f)}".strip() for f in p.get("facts") or [])
        out.append(f"{pad}{'└─' if last else '├─'} {mark}{p['name']}{span}{cert}"
                   + (f" — {p['role']}" if p.get("role") else "") + (f"  · {facts}" if facts else ""))
        more = pad + ("   " if last else "│  ")
        if p.get("how"):
            out.append(f"{more}  how: {p['how'][:160]}")
        if p.get("evidence"):
            out.append(f"{more}  ↳ {p['evidence']}")
        out += _bp_lines(p.get("parts") or [], pad + ("   " if last else "│  "), unit)
    return out


# -- kept with the chat ------------------------------------------------------------------

def _ensure(store) -> None:
    """The tables are in memory.SCHEMA; this covers a Store opened by older code."""
    if getattr(store, "_stage_ready", False):
        return
    names = {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"stage_scenes", "stage_boards", "stage_links"} <= names:
        from .memory import SCHEMA
        store.db.executescript(SCHEMA)
    store._stage_ready = True


def add(store, conversation_id: str, scene: dict) -> dict:
    """File a cleaned scene under the question it answers. Returns the row the page gets."""
    if not conversation_id:
        raise ValueError("this run has no chat to show it in, so put it in words instead")
    _ensure(store)
    row = store.db.execute("SELECT id FROM messages WHERE conversation_id=? AND role='user' "
                           "ORDER BY created_at DESC LIMIT 1", (conversation_id,)).fetchone()
    answer_to = row[0] if row else ""
    n = store.db.execute("SELECT COUNT(*) FROM stage_scenes WHERE conversation_id=? AND answer_to=?",
                         (conversation_id, answer_to)).fetchone()[0]
    if n >= MAX_PER_ANSWER:
        raise ValueError(f"this answer already has {MAX_PER_ANSWER} scenes; say the rest in words")
    if n == 0:
        # the first scene of a new story: was it asked for by "Go deeper" on a scene?
        ask = _DEEPER.pop((_who(), conversation_id), None)
        if ask and time.time() - ask[2] < DEEPER_S and ask[0] != answer_to:
            store.db.execute("INSERT OR REPLACE INTO stage_links (conversation_id, answer_to, "
                             "parent_answer_to, parent_seq, created_at) VALUES (?,?,?,?,?)",
                             (conversation_id, answer_to, ask[0], ask[1], time.time()))
    sid = uuid.uuid4().hex[:12]
    now = time.time()
    store.db.execute("INSERT INTO stage_scenes (id, conversation_id, answer_to, seq, scene, created_at) "
                     "VALUES (?,?,?,?,?,?)",
                     (sid, conversation_id, answer_to, n + 1, json.dumps(scene), now))
    store.db.commit()
    return {"id": sid, "conversation_id": conversation_id, "answer_to": answer_to,
            "seq": n + 1, "scene": scene, "created_at": now}


# "Go deeper" on a scene: the page asks for it, then sends the question as an ordinary chat
# message. The story that answers it is linked to the scene when its first scene arrives,
# whichever brain answers (Claude Code saves its messages in another place than the
# built-in loop). Kept in memory per person and chat, for DEEPER_S.
DEEPER_S = 1800
_DEEPER: dict = {}


def _who() -> str:
    try:
        from . import users
        return users.current() or ""
    except Exception:
        return ""


def ask_deeper(store, conversation_id: str, answer_to: str, seq: int, part: str = "") -> str:
    """Remember that the next story in this chat goes deeper on that scene, and return
    the question to send. Refused for a scene that is not there. `part` is a blueprint
    part's id: the question asks for that part taken apart, named with where it sits."""
    scenes = story(store, conversation_id, answer_to)
    hit = next((s for s in scenes if s["seq"] == int(seq)), None)
    if not hit:
        raise ValueError("that scene is not there")
    sc = hit["scene"]
    path = []
    if part:      # checked before it is remembered: a refusal must not move the link
        if sc.get("kind") != "blueprint":
            raise ValueError("only a blueprint has parts")
        path = _bp_path(sc.get("parts") or [], str(part))
        if not path:
            raise ValueError("that part is not in this blueprint")
    _DEEPER[(_who(), conversation_id)] = (answer_to, int(seq), time.time())
    if path:
        p, within = path[-1], [x["name"] for x in path[:-1]]
        where = " › ".join([sc.get("subject") or sc.get("title") or "it"] + within)
        return (f"Go deeper on \"{p['name']}\" in {where}"
                + (f" ({p['role']})" if p.get("role") else "")
                + ". Take it apart as its own blueprint on the Stage: what it is made of, how the "
                  "pieces work together, the real numbers with their source, and what is unclear.")
    about = sc.get("title") or sc["kind"]
    return (f"Go deeper on \"{about}\"" + (f" ({sc['caption']})" if sc.get("caption") else "")
            + ". Explain it properly and show it as its own story on the Stage: what is behind it, "
              "the numbers, places, pictures or videos that make it clear.")


def _bp_path(parts: list, pid: str) -> list:
    """The parts from the top down to the one with this id, or []."""
    for p in parts:
        if p.get("id") == pid:
            return [p]
        sub = _bp_path(p.get("parts") or [], pid)
        if sub:
            return [p] + sub
    return []


def links(store, conversation_id: str) -> dict:
    _ensure(store)
    rows = store.db.execute("SELECT answer_to, parent_answer_to, parent_seq FROM stage_links "
                            "WHERE conversation_id=?", (conversation_id,)).fetchall()
    return {a: {"answer_to": p, "seq": q} for a, p, q in rows}


def stories(store, conversation_id: str) -> list[dict]:
    """Each answer's scenes, oldest answer first: [{answer_to, scenes: [...]}]."""
    _ensure(store)
    rows = store.db.execute("SELECT id, answer_to, seq, scene, created_at FROM stage_scenes "
                            "WHERE conversation_id=? ORDER BY created_at", (conversation_id,)).fetchall()
    out: dict[str, dict] = {}
    for sid, ans, seq, scene, at in rows:
        try:
            sc = json.loads(scene)
        except ValueError:
            continue
        st = out.setdefault(ans or "", {"answer_to": ans or "", "scenes": []})
        st["scenes"].append({"id": sid, "seq": seq, "scene": sc, "created_at": at})
    ln = links(store, conversation_id)
    for a, st in out.items():
        st["parent"] = ln.get(a)
        # which of its scenes others went deeper on: {seq: [answer_to, …]}
        st["deeper"] = {}
    for a, p in ln.items():
        if p["answer_to"] in out:
            out[p["answer_to"]]["deeper"].setdefault(str(p["seq"]), []).append(a)
    return list(out.values())


def latest_conversation(store) -> str:
    _ensure(store)
    row = store.db.execute("SELECT conversation_id FROM stage_scenes ORDER BY created_at DESC LIMIT 1").fetchone()
    return row[0] if row else ""


def story(store, conversation_id: str, answer_to: str) -> list[dict]:
    for st in stories(store, conversation_id):
        if st["answer_to"] == (answer_to or ""):
            return st["scenes"]
    return []


def library(store, limit: int = 200) -> list[dict]:
    """Every story this person has been shown, newest first: the visual memory. Each
    carries the question it answered, so the list reads as what was asked."""
    _ensure(store)
    rows = store.db.execute(
        "SELECT s.conversation_id, s.answer_to, COUNT(*), MIN(s.created_at), MAX(s.created_at), "
        "m.content, c.title FROM stage_scenes s "
        "LEFT JOIN messages m ON m.id = s.answer_to "
        "LEFT JOIN conversations c ON c.id = s.conversation_id "
        "GROUP BY s.conversation_id, s.answer_to ORDER BY MAX(s.created_at) DESC LIMIT ?",
        (int(limit),)).fetchall()
    out = []
    for cid, ans, n, first, last, question, title in rows:
        top = store.db.execute("SELECT scene FROM stage_scenes WHERE conversation_id=? AND answer_to=? "
                               "ORDER BY seq LIMIT 4", (cid, ans)).fetchall()
        kinds, titles = [], []
        for (raw,) in top:
            try:
                sc = json.loads(raw)
            except ValueError:
                continue
            kinds.append(sc.get("kind", ""))
            titles.append(sc.get("title", ""))
        out.append({"conversation_id": cid, "answer_to": ans or "", "scenes": n,
                    "question": _s(_question(question or ""), 160), "chat": title or "",
                    "kinds": kinds, "titles": [t for t in titles if t],
                    "first_at": first, "last_at": last})
    return out


def _question(text: str) -> str:
    """The person's words, without a schedule's or a refresh's bracketed preamble."""
    t = (text or "").strip()
    while t.startswith("["):
        end = t.find("]")
        if end < 0:
            break
        t = t[end + 1:].strip()
    return t


# -- boards: a saved story that can keep itself fresh -------------------------------------

EVERY = {"": 0, "hour": 3600, "day": 86400, "week": 7 * 86400}
EVERY_WORDS = {"": "kept as it is", "hour": "refreshed every hour", "day": "refreshed every day",
               "week": "refreshed every week"}
REFRESH_LINE = ("[Refreshing a saved Stage board. Nobody is waiting on this answer, so do not ask "
                "questions. Look the facts up again now and show the answer with show_scene, as "
                "you did before: the board replaces its old scenes with these.]")


def save_board(store, conversation_id: str, answer_to: str, title: str = "", every: str = "") -> dict:
    _ensure(store)
    if every not in EVERY:
        raise ValueError("every must be one of: never, hour, day, week")
    scenes = story(store, conversation_id, answer_to)
    if not scenes:
        raise ValueError("there is no story there to save")
    row = store.db.execute("SELECT content FROM messages WHERE id=?", (answer_to,)).fetchone()
    question = _question(row[0] if row else "")
    if every and not question:
        raise ValueError("this story has no question to ask again, so it can only be kept as it is")
    now = time.time()
    hit = store.db.execute("SELECT id FROM stage_boards WHERE conversation_id=? AND answer_to=?",
                           (conversation_id, answer_to)).fetchone()
    bid = hit[0] if hit else uuid.uuid4().hex[:12]
    title = _s(title or scenes[0]["scene"].get("title") or question, 80)
    nxt = now + EVERY[every] if every else None
    if hit:
        store.db.execute("UPDATE stage_boards SET title=?, every=?, next_run=? WHERE id=?",
                         (title, every, nxt, bid))
    else:
        store.db.execute("INSERT INTO stage_boards (id, title, question, conversation_id, answer_to, every, "
                         "next_run, last_run, last_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (bid, title, question, conversation_id, answer_to, every, nxt, None, "", now))
    store.db.commit()
    return board(store, bid)


def _board_row(r) -> dict:
    keys = ("id", "title", "question", "conversation_id", "answer_to", "every", "next_run",
            "last_run", "last_status", "created_at")
    d = dict(zip(keys, r))
    d["when"] = EVERY_WORDS.get(d["every"] or "", "")
    return d


def board(store, bid: str) -> dict | None:
    _ensure(store)
    r = store.db.execute("SELECT id, title, question, conversation_id, answer_to, every, next_run, "
                         "last_run, last_status, created_at FROM stage_boards WHERE id=?", (bid,)).fetchone()
    return _board_row(r) if r else None


def boards(store) -> list[dict]:
    _ensure(store)
    rows = store.db.execute("SELECT id, title, question, conversation_id, answer_to, every, next_run, "
                            "last_run, last_status, created_at FROM stage_boards "
                            "ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        b = _board_row(r)
        b["scenes"] = story(store, b["conversation_id"], b["answer_to"])
        out.append(b)
    return out


def due_boards(store, now: float | None = None) -> list[dict]:
    _ensure(store)
    now = time.time() if now is None else now
    rows = store.db.execute("SELECT id FROM stage_boards WHERE every != '' AND next_run IS NOT NULL "
                            "AND next_run <= ?", (now,)).fetchall()
    return [board(store, r[0]) for r in rows]


def claim(store, bid: str) -> None:
    """Taken before the refresh runs, so a slow one is not started twice."""
    store.db.execute("UPDATE stage_boards SET next_run=NULL, last_status='refreshing' WHERE id=?", (bid,))
    store.db.commit()


def refreshed(store, bid: str, conversation_id: str, answer_to: str, ok: bool, note: str = "") -> dict | None:
    """Point the board at the new story when the refresh showed one; otherwise keep the
    old story and say why. A board that silently went blank would be worse than stale."""
    b = board(store, bid)
    if not b:
        return None
    now = time.time()
    nxt = now + EVERY[b["every"]] if b["every"] else None
    if ok and story(store, conversation_id, answer_to):
        store.db.execute("UPDATE stage_boards SET conversation_id=?, answer_to=?, last_run=?, "
                         "last_status='ok', next_run=? WHERE id=?",
                         (conversation_id, answer_to, now, nxt, bid))
    else:
        store.db.execute("UPDATE stage_boards SET last_run=?, last_status=?, next_run=? WHERE id=?",
                         (now, _s(note or "the refresh showed nothing new, so the last story stays", 200),
                          nxt, bid))
    store.db.commit()
    return board(store, bid)


def drop_board(store, bid: str) -> bool:
    _ensure(store)
    cur = store.db.execute("DELETE FROM stage_boards WHERE id=?", (bid,))
    store.db.commit()
    return cur.rowcount > 0


# -- the person's settings ---------------------------------------------------------------

DEFAULTS = {"big": True, "app": ""}


def settings(cfg: dict) -> dict:
    """`big`: show answers on the Stage without being asked. `app`: '' is the Stage,
    otherwise the id of one of the person's own apps that is handed each scene."""
    st = cfg.get("stage") if isinstance(cfg.get("stage"), dict) else {}
    return {"big": bool(st.get("big", DEFAULTS["big"])), "app": str(st.get("app") or "")}


BP_LINE = ("Asked what is inside something, how a building, a machine, a body, an organisation or a "
           "system is built, or for a blueprint, show ONE blueprint scene, and make it the main scene: it "
           "takes the thing apart so the person can open any part on their screen. form is tower for "
           "something built in layers along a height (a building, a rocket, the earth; parts bottom "
           "first, with from and to as heights in unit, and width as how wide each part really is in the "
           "same unit, so the outline is drawn to scale; only when you cannot know it, 0 to 1 as a share "
           "of the widest), exploded for a thing made of parts round a core (an engine, "
           "a watch, a cell, a company) or flow for a process in order. Show the OUTLINE quickly: six to "
           "ten parts, each with its role, how it works (how), two or three facts, and the names of the "
           "parts inside it; the whole's own key numbers in facts; links between parts (from, to, a "
           "verb, and kind: what flows along it, one of " + ", ".join(BP_FLOWS) + "); what nobody "
           "outside can know in unknowns. The Stage then fills in every part on its own, looked up and "
           "three levels deep, so show it once and do not show it again while it fills. Each part may "
           "say what it is made of (made_of), its limits or how it fails (limits), and how sure anyone "
           "is (certainty known, estimated or unclear). A child part may take another form (a tower's "
           "foundation drawn exploded).")
BIG_LINE = ("Answer BIG: the person watches your answers on the Stage, so anything worth seeing is "
            "SHOWN with show_scene before you write the text: three to six scenes, in story order. "
            "Tell a story, not a slide: open on what matters most (the headline numbers, or a "
            "picture of the main thing), then the detail, and END on what it means for this person "
            "(what to do, what to watch, how it touches what they told you about themselves). Every "
            "caption is the takeaway as a sentence with a verb ('A stampede in Kolkata and a red "
            "alert in Chennai lead the day'), never a label ('Stories by location'). On a map, give "
            "every point a note saying what happened there, in a few words; set route: true only when "
            "the places are a journey. News: the top stories' key numbers, a map with a note on each "
            "place, a picture of the biggest story, and what it means for them. "
            "A how-to or a tutorial: the steps, a picture, and a YouTube video (search the web for "
            "the best tutorial on it and pass its youtube.com address as a video scene). A place: "
            "a map, and a picture of it. Numbers or a trend: a chart or key numbers. A process or a "
            "cause: steps or a timeline. "
            "Choose how big each answer is yourself: a fact gets none, a comparison a chart, and "
            "something that moves, grows or gets built (a launch, a factory, a city growing, a "
            "supply chain, a startup's first year) earns a film: a short 3D animation you write "
            "as three to six shots, each a subject and a camera move with the line said over "
            "it. Open or close a big story with one; never more than one film per answer. "
            "A picture is an https image address you found (a photo "
            "on Wikipedia or the maker's site) or one you made with generate_image. Use real "
            "figures you looked up and name the source; if a picture is only an example, set "
            "illustrative: true. A plain question (a fact, a yes or no, small talk) gets no scenes. "
            + BP_LINE + " "
            "When the person asks to change what is on the Stage (add a place, another chart, "
            "newer figures), show the whole story again with the change: it is kept as a new "
            "version beside the old one.")
ASKED_LINE = ("show_scene puts a chart, a map, key numbers, a timeline, steps, a table, a picture, a "
              "YouTube video, a film (a short 3D animation from a shot list) or a blueprint (a thing "
              "taken apart into parts the person can open, level by level) on the "
              "person's screen. Use it when they ask to see something; name the source of any "
              "numbers, or set illustrative: true. Asked to change what is on the Stage, show the "
              "whole story again with the change; the old version is kept.")


PHONE_LINE = ("This person is on their phone ({surface}). They do not see the Stage live: every scene "
              "you show is sent to them as one page right after your reply, which plays the whole "
              "story on the phone. So show it exactly as you would at the desk; it is how they see "
              "charts, maps, pictures and videos there.")


def note(cfg: dict, tool: str = "show_scene", surface: str = "") -> str:
    """What the lead is told, built-in or forwarded (`tool` is the name it calls it by). On a
    phone channel the Stage line said "the person watches your answers on the Stage", which
    was not true there, and Claude Code answered a Nifty question in words: the phone line
    says where the scenes go instead."""
    # asking for a blueprint is asking to see one, so its guidance goes with Answer BIG off too
    line = BIG_LINE if settings(cfg)["big"] else ASKED_LINE + " " + BP_LINE
    out = "THE STAGE. " + line.replace("show_scene", tool)
    if surface in ("telegram", "whatsapp"):
        out += " " + PHONE_LINE.format(surface={"telegram": "Telegram", "whatsapp": "WhatsApp"}[surface])
    return out


# -- the story as one file: what a phone channel sends ------------------------------------

_UI = __import__("pathlib").Path(__file__).parent / "ui"
REPORT_TOKENS = """:root{--bg:#0b0d1a;--bg2:#13162a;--bg3:#1b1f38;--bg4:#242a4a;--txt:#eef0ff;--dim:#a3a8c9;
--dim2:#7c82a8;--line:#2b3157;--acc:#8b7cff;--acc-grad:linear-gradient(135deg,#6d7cff,#a77bff);
--on-acc:#fff;--warn:#fbbf24;--err:#f87171;--r-sm:8px;--r-md:12px;--r-lg:18px;--tap:36px;
--fs-2xs:11px;--fs-xs:12px;--fs-sm:14px;--fs-md:16px;--fs-base:15px;--fs-lg:21px;
--sans:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;--ease-out:cubic-bezier(.2,.8,.2,1);--el-4:0 10px 30px #0008}
@media (prefers-color-scheme: light){:root{--bg:#f6f6fb;--bg2:#ffffff;--bg3:#eef0f7;--bg4:#e3e6f1;--txt:#14162b;
--dim:#555b7d;--dim2:#7a809f;--line:#dadff0;--acc:#5b4dff;--warn:#b45309}}
body{margin:0;background:#05060e;color:#eef1ff;font:16px/1.5 var(--sans)}
.rp{max-width:980px;margin:0 auto;padding:22px 16px 60px}
.rp-h{font-size:13px;color:rgba(238,241,255,.6);letter-spacing:.04em;text-transform:uppercase}
.rp-q{font-size:26px;font-weight:800;line-height:1.25;margin:8px 0 22px}
.rp .stg.rp-sc{display:block;container-type:normal;border-radius:22px;margin:0 0 18px;padding:18px 0 16px;contain:none;transform:none}
.rp .stg-scene{display:block;padding:0 18px}
.rp .stg-art{height:min(62vh,520px);min-height:260px}
.rp .stg-scene.k-chart .stg-art,.rp .stg-scene.k-map .stg-art,.rp .stg-scene.k-video .stg-art,.rp .stg-scene.k-steps .stg-art,.rp .stg-scene.k-numbers .stg-art,.rp .stg-scene.k-timeline .stg-art,.rp .stg-scene.k-table .stg-art{height:auto}
.rp .stg-foot{margin-top:10px}
.rp .stg-cap span{opacity:1;animation:none}
.rp .st-svg{height:auto}
.rp .stg-vid{display:block}.rp .stg-vid-link{width:100%;height:auto}
.rp-a{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:var(--r-lg);padding:16px 18px;white-space:pre-wrap;line-height:1.55}
.rp-f{color:rgba(238,241,255,.45);font-size:12px;margin-top:22px;text-align:center}
.st-card:not(.seen) .st-art{visibility:hidden}"""


def still_caption(sc: dict, i: int, n: int) -> str:
    """The words under a scene's picture in Telegram: where it is in the story, its title,
    its caption, and where the numbers came from (the picture shows them too, but a caption
    is what a phone reads aloud and searches)."""
    head = f"{i + 1}/{n} · {sc.get('title') or STILL_KIND.get(sc.get('kind'), 'Scene')}" if n > 1 \
        else (sc.get("title") or "")
    out = [head]
    if sc.get("caption"):
        out.append(sc["caption"])
    if sc.get("kind") == "map":
        # the notes the picture lists, so a caption read aloud says them too
        out += [f"{k}. {p['label']}: {p['note']}" for k, p in
                enumerate([p for p in sc.get("points") or [] if p.get("note")], 1)][:8]
    if sc.get("illustrative"):
        out.append("Illustrative, not data.")
    elif sc.get("source"):
        out.append(f"Source: {sc['source']}")
    if sc.get("kind") == "video" and sc.get("video"):
        out.append(f"https://www.youtube.com/watch?v={sc['video']}")
    if sc.get("kind") == "blueprint":
        # a picture cannot be drilled: the caption says what is inside each part
        out += [f"{k}. {p['name']}" + (f": {p['role']}" if p.get("role") else "")
                + (f" ({len(p['parts'])} part{'s' if len(p['parts']) != 1 else ''} inside)" if p.get("parts") else "")
                for k, p in enumerate(sc.get("parts") or [], 1)][:12]
    if sc.get("kind") == "film":
        # the picture is the storyboard; the caption says each shot, so it reads aloud
        out += [f"{k}. {sh['text']}" for k, sh in enumerate(sc.get("shots") or [], 1) if sh.get("text")]
    return "\n".join(x for x in out if x)[:1024]


STILL_KIND = {"chart": "Chart", "map": "Map", "numbers": "Numbers", "timeline": "Timeline",
              "steps": "How it works", "table": "Table", "image": "Picture", "video": "Video",
              "film": "Film", "blueprint": "Blueprint"}


# A photograph per scene (stagestill.py): the page's chrome goes, each card stands alone with
# the question over it, and nothing moves.
STILL_CSS = """
body.still{background:#05060e}
body.still .rp{padding:0;max-width:none}
body.still .rp-h,body.still .rp-q,body.still .rp-f{display:none}
.still-card{padding:22px 18px 16px;background:radial-gradient(120% 80% at 0 0,#141a3a,#05060e 70%)}
.still-q{font:700 17px/1.3 var(--sans);color:rgba(238,241,255,.78);margin:0 2px 14px}
.still-f{font:600 11px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:rgba(238,241,255,.4);
  margin:12px 2px 0;text-align:right}
body.still .stg.rp-sc{margin:0}
body.still .rp .stg-art{height:420px}
/* a picture has no scrolling: a map's notes are a grid under it, and the card grows to hold them */
body.still .stg .st-mapnotes{display:grid;overflow:visible;grid-template-columns:1fr 1fr}
body.still .stg .st-mapnotes li{flex:none}
body.still .rp .stg-art:has(.st-mapnotes){height:auto;min-height:420px}
body.still *,body.still *::before,body.still *::after{animation:none!important;transition:none!important}
"""


def _inline_asset(store, sc: dict) -> dict:
    """A picture this machine keeps travels inside the page (a phone cannot reach it here);
    one over REPORT_IMG_CAP stays out, and the page says the picture is on the machine."""
    if sc.get("kind") != "image" or not sc.get("asset"):
        return sc
    import base64
    try:
        from . import assets as assetmod
        row = store.asset_get(sc["asset"])
        path = assetmod.path_of(row) if row else None
        data = open(path, "rb").read() if path else b""
    except Exception:
        data, row = b"", None
    if data and len(data) <= REPORT_IMG_CAP:
        sc["url"] = f"data:{(row or {}).get('mime') or 'image/png'};base64," + base64.b64encode(data).decode()
    else:
        sc["url"], sc["credit"] = "", "The picture is on your machine, in Assets"
    sc["asset"] = ""
    return sc


REPORT_IMG_CAP = 3 * 1024 * 1024
# the Stage's painters, which the phone's page embeds as they are: one painter, two places
PAINTER_JS = ("24l-stage.js", "24v-blueprint.js")
PAINTER_CSS = ("31-stage.css", "40-blueprint.css")


def report_html(store, conversation_id: str, answer_to: str, answer: str = "",
                agent: str = "", still: bool = False) -> str:
    """One self-contained page: the question, every scene drawn by the Stage's own code
    (24l-stage.js, so there is one painter), the written answer, and the map inline. It
    is what Telegram sends when it cannot send pictures: opened on a phone it plays the
    story without this machine.

    `still` is the same page laid out for photographs (stagestill.py): each scene a card of
    its own with the question over it, drawn at once, and `STAGE_STILL_DONE` set when it is."""
    import html as _html
    from . import tgformat
    scenes = [_inline_asset(store, dict(s["scene"])) for s in story(store, conversation_id, answer_to)]
    row = store.db.execute("SELECT content FROM messages WHERE id=?", (answer_to,)).fetchone()
    question = _question(row[0] if row else "")
    js = "\n".join((_UI / f"src/js/{f}").read_text(encoding="utf-8") for f in PAINTER_JS)
    css = "\n".join((_UI / f"src/css/{f}").read_text(encoding="utf-8") for f in PAINTER_CSS)
    world = (_UI / "assets/world-110m.json").read_text(encoding="utf-8") \
        if any(s["kind"] == "map" for s in scenes) else "null"
    data = json.dumps({"scenes": scenes}).replace("</", "<\\/")
    world = world.replace("</", "<\\/")
    when = time.strftime("%d %b %Y, %H:%M")
    # outside the f-string: Python 3.10 refuses a backslash inside an f-string expression
    lt = "\\u003c"
    still_q = json.dumps(_s(question, 140)).replace("<", lt)
    still_f = json.dumps((agent or "Your agent") + " · Bento Box AI").replace("<", lt)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html.escape(_s(question or 'The story', 70))}</title>
<style>{REPORT_TOKENS}
{css}{STILL_CSS if still else ''}</style></head><body class="{'still' if still else ''}"><div class="rp">
<div class="rp-h">{_html.escape(agent or 'Your agent')} · {when} · {len(scenes)} scene{'s' if len(scenes) != 1 else ''}</div>
<div class="rp-q">{_html.escape(question)}</div>
<div id="scenes"></div>
{f'<div class="rp-a">{tgformat.to_html(answer)}</div>' if answer.strip() and not still else ''}
<div class="rp-f">Made by Bento Box AI. Numbers carry their source; scenes marked illustrative are examples, not data.</div>
</div>
<script>window.STAGE_REPORT=true;window.STAGE_STILL={'true' if still else 'false'};
{js}
(function(){{
  var D={data}, W={world};
  if(W)stageWorldIndex(W);
  var host=document.getElementById('scenes');
  // each scene is a room of its own, lit by its kind, as on the Stage
  var cards=D.scenes.map(function(sc,i){{
    var card=sEl('section','stg rp-sc');card.style.setProperty('--hue',STAGE_HUE[sc.kind]||250);
    card.append(sEl('div','stg-bg'));
    if(window.STAGE_STILL){{var wrap=sEl('div','still-card');
      wrap.append(sEl('div','still-q',{still_q}));wrap.append(card);
      wrap.append(sEl('div','still-f',{still_f}));host.append(wrap)}}
    var box=sEl('div','stg-scene k-'+sc.kind);
    box.append(sEl('div','stg-kicker',(i+1)+' of '+D.scenes.length+' · '+(STAGE_KIND[sc.kind]||sc.kind)));
    box.append(sEl('div','stg-title',sc.title||''));
    var art=sEl('div','stg-art st-art');box.append(art);
    var foot=sEl('div','stg-foot');
    if(sc.caption)foot.append(sEl('div','stg-cap',sc.caption));
    if(sc.illustrative)foot.append(sEl('div','st-src st-illus','Illustrative, not data'));
    else if(sc.source)foot.append(stageSource(sc.source));
    box.append(foot);card.append(box);
    if(!window.STAGE_STILL)host.append(card);return [card,art,sc];
  }});
  // each scene draws as it scrolls into view, so its motion is seen
  var io=('IntersectionObserver' in window)?new IntersectionObserver(function(es){{es.forEach(function(e){{
    if(!e.isIntersecting)return;var c=cards.find(function(x){{return x[0]===e.target}});io.unobserve(e.target);
    c[0].classList.add('seen');try{{stageDraw(c[1],c[2])}}catch(err){{c[1].textContent='Could not draw this scene.'}}
  }})}},{{threshold:.25}}):null;
  if(window.STAGE_STILL){{cards.forEach(function(c){{c[0].classList.add('seen');
    try{{stageDraw(c[1],c[2])}}catch(err){{c[1].textContent='Could not draw this scene.'}}}});
    window.STAGE_STILL_DONE=true;return}}
  cards.forEach(function(c){{if(io)io.observe(c[0]);else{{c[0].classList.add('seen');stageDraw(c[1],c[2])}}}});
}})();
</script></body></html>"""


def write_report(store, folder, conversation_id: str, answer_to: str, answer: str = "",
                 agent: str = "") -> "Path | None":
    """The report on disk under the person's workspace (stage/), or None with no story."""
    from pathlib import Path
    if not story(store, conversation_id, answer_to):
        return None
    d = Path(folder) / "stage"
    d.mkdir(parents=True, exist_ok=True)
    name = (_s(_question(store.db.execute("SELECT content FROM messages WHERE id=?",
                                          (answer_to,)).fetchone()[0] if answer_to else ""), 40)
            or "story")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "story"
    p = d / f"{slug}-{(answer_to or conversation_id)[:6]}.html"
    p.write_text(report_html(store, conversation_id, answer_to, answer, agent), encoding="utf-8")
    return p


def question_of(store, answer_to: str) -> str:
    """The person's question a story answers, in their words (without channel notes)."""
    row = store.db.execute("SELECT content FROM messages WHERE id=?", (answer_to,)).fetchone() if answer_to else None
    return _s(_question(row[0] if row else ""), 200)


def last_question(store, conversation_id: str) -> str:
    row = store.db.execute("SELECT id FROM messages WHERE conversation_id=? AND role='user' "
                           "ORDER BY created_at DESC LIMIT 1", (conversation_id,)).fetchone()
    return row[0] if row else ""
