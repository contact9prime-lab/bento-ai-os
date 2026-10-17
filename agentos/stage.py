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

KINDS = ("chart", "map", "numbers", "timeline", "steps", "table")
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
    "steps": ("items",),
    "table": ("columns", "rows"),
}
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
    measured = kind in NEEDS_SOURCE and not (kind == "map" and not any(
        r.get("value") is not None for r in sc.get("regions", []) + sc.get("points", [])))
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
        sc.update(points=pts, regions=regions, view=view or "", unit=_s(spec.get("unit"), 12))

    @staticmethod
    def numbers(spec, sc, dropped):
        items = []
        for it in _list(spec.get("items"))[:MAX_ITEMS]:
            if not isinstance(it, dict) or it.get("value") in (None, ""):
                continue
            items.append({"label": _s(it.get("label"), 48), "value": _s(it.get("value"), 24),
                          "unit": _s(it.get("unit"), 12), "delta": _s(it.get("delta"), 24),
                          "note": _s(it.get("note"), 120)})
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
                items.append({"title": _s(it.get("title"), 80), "text": _s(it.get("text"), 200)})
        if not items:
            raise ValueError("steps needs items: [{title, text?}], in order")
        sc["items"] = items

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


# -- kept with the chat ------------------------------------------------------------------

def _ensure(store) -> None:
    """The tables are in memory.SCHEMA; this covers a Store opened by older code."""
    if getattr(store, "_stage_ready", False):
        return
    names = {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "stage_scenes" not in names or "stage_boards" not in names:
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
    sid = uuid.uuid4().hex[:12]
    now = time.time()
    store.db.execute("INSERT INTO stage_scenes (id, conversation_id, answer_to, seq, scene, created_at) "
                     "VALUES (?,?,?,?,?,?)",
                     (sid, conversation_id, answer_to, n + 1, json.dumps(scene), now))
    store.db.commit()
    return {"id": sid, "conversation_id": conversation_id, "answer_to": answer_to,
            "seq": n + 1, "scene": scene, "created_at": now}


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


BIG_LINE = ("Answer BIG: this person sees your answers on the Stage. When an answer has numbers, "
            "places, a trend, a comparison, a sequence or a cause and its effects, SHOW it with "
            "show_scene as you go (a chart, a map, key numbers, a timeline, steps or a table), "
            "two to five scenes that tell the story in order, then write the answer. Use real "
            "figures you looked up and name the source; if a picture is only an example, set "
            "illustrative: true. A plain question gets a plain answer and no scenes.")
ASKED_LINE = ("show_scene puts a chart, a map, key numbers, a timeline, steps or a table on the "
              "person's screen. Use it when they ask to see something; name the source of any "
              "numbers, or set illustrative: true.")


def note(cfg: dict, tool: str = "show_scene") -> str:
    """What the lead is told, built-in or forwarded (`tool` is the name it calls it by)."""
    line = BIG_LINE if settings(cfg)["big"] else ASKED_LINE
    return "THE STAGE. " + line.replace("show_scene", tool)


# -- the story as one file: what a phone channel sends ------------------------------------

_UI = __import__("pathlib").Path(__file__).parent / "ui"
REPORT_TOKENS = """:root{--bg:#0b0d1a;--bg2:#13162a;--bg3:#1b1f38;--bg4:#242a4a;--txt:#eef0ff;--dim:#a3a8c9;
--dim2:#7c82a8;--line:#2b3157;--acc:#8b7cff;--acc-grad:linear-gradient(135deg,#6d7cff,#a77bff);
--on-acc:#fff;--warn:#fbbf24;--err:#f87171;--r-sm:8px;--r-md:12px;--r-lg:18px;--tap:36px;
--fs-2xs:11px;--fs-xs:12px;--fs-sm:14px;--fs-md:16px;--fs-base:15px;--fs-lg:21px;
--sans:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;--ease-out:cubic-bezier(.2,.8,.2,1);--el-4:0 10px 30px #0008}
@media (prefers-color-scheme: light){:root{--bg:#f6f6fb;--bg2:#ffffff;--bg3:#eef0f7;--bg4:#e3e6f1;--txt:#14162b;
--dim:#555b7d;--dim2:#7a809f;--line:#dadff0;--acc:#5b4dff;--warn:#b45309}}
body{margin:0;background:var(--bg);color:var(--txt);font:16px/1.5 var(--sans)}
.rp{max-width:980px;margin:0 auto;padding:22px 16px 60px}
.rp-h{font-size:13px;color:var(--dim);letter-spacing:.04em;text-transform:uppercase}
.rp-q{font-size:26px;font-weight:800;line-height:1.25;margin:8px 0 22px}
.rp .st-card{margin:0 0 18px;min-height:0}.rp .st-art{min-height:240px;overflow:visible}
.rp .st-svg{height:auto;min-height:0}
.rp-a{background:var(--bg2);border:1px solid var(--line);border-radius:var(--r-lg);padding:16px 18px;white-space:pre-wrap;line-height:1.55}
.rp-f{color:var(--dim2);font-size:12px;margin-top:22px;text-align:center}
.st-card:not(.seen) .st-art{visibility:hidden}"""


def report_html(store, conversation_id: str, answer_to: str, answer: str = "",
                agent: str = "") -> str:
    """One self-contained page: the question, every scene drawn by the Stage's own code
    (24l-stage.js, so there is one painter), the written answer, and the map inline. It
    is what Telegram sends: opened on a phone it plays the story without this machine."""
    import html as _html
    scenes = [s["scene"] for s in story(store, conversation_id, answer_to)]
    row = store.db.execute("SELECT content FROM messages WHERE id=?", (answer_to,)).fetchone()
    question = _question(row[0] if row else "")
    js = (_UI / "src/js/24l-stage.js").read_text(encoding="utf-8")
    css = (_UI / "src/css/31-stage.css").read_text(encoding="utf-8")
    world = (_UI / "assets/world-110m.json").read_text(encoding="utf-8") \
        if any(s["kind"] == "map" for s in scenes) else "null"
    data = json.dumps({"scenes": scenes}).replace("</", "<\\/")
    world = world.replace("</", "<\\/")
    when = time.strftime("%d %b %Y, %H:%M")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html.escape(_s(question or 'The story', 70))}</title>
<style>{REPORT_TOKENS}
{css}</style></head><body><div class="rp">
<div class="rp-h">{_html.escape(agent or 'Your agent')} · {when} · {len(scenes)} scene{'s' if len(scenes) != 1 else ''}</div>
<div class="rp-q">{_html.escape(question)}</div>
<div id="scenes"></div>
{f'<div class="rp-a">{_html.escape(answer)}</div>' if answer.strip() else ''}
<div class="rp-f">Made by Bento Box AI. Numbers carry their source; scenes marked illustrative are examples, not data.</div>
</div>
<script>{js}
(function(){{
  var D={data}, W={world};
  if(W)stageWorldIndex(W);
  var host=document.getElementById('scenes');
  var cards=D.scenes.map(function(sc){{
    var card=sEl('div','st-card k-'+sc.kind);card.append(sEl('div','st-title',sc.title||''));
    var art=sEl('div','st-art');card.append(art);
    if(sc.caption)card.append(sEl('div','st-cap',sc.caption));
    if(sc.illustrative)card.append(sEl('div','st-src st-illus','Illustrative, not data'));
    else if(sc.source)card.append(stageSource(sc.source));
    host.append(card);return [card,art,sc];
  }});
  // each scene draws as it scrolls into view, so its motion is seen
  var io=('IntersectionObserver' in window)?new IntersectionObserver(function(es){{es.forEach(function(e){{
    if(!e.isIntersecting)return;var c=cards.find(function(x){{return x[0]===e.target}});io.unobserve(e.target);
    c[0].classList.add('seen');try{{stageDraw(c[1],c[2])}}catch(err){{c[1].textContent='Could not draw this scene.'}}
  }})}},{{threshold:.25}}):null;
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


def last_question(store, conversation_id: str) -> str:
    row = store.db.execute("SELECT id FROM messages WHERE conversation_id=? AND role='user' "
                           "ORDER BY created_at DESC LIMIT 1", (conversation_id,)).fetchone()
    return row[0] if row else ""
