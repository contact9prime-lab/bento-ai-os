"""The office: the playground where the crew is seen at work.

The Office app draws this machine's agents as a comic-strip office — your agent in
the corner office, each specialist at a desk in a department, a meeting room where
huddles happen — and moves them when something REALLY happens: a paper flies to the
desk of the specialist a mission just handed work to, one agent walks across the
floor to ask another, a huddle gathers round the meeting table. This module is what
the person can change about that office, and the one place it is decided.

Four rules, the same ones the Crew scene and the characters live by:

- **The cast is the real one.** Departments hold agents that exist
  (`store.list_subagents()`); a name that is not there is dropped and NAMED, never
  drawn. A specialist nobody placed sits on the open floor rather than vanishing, and
  an office with no specialists says so instead of filling desks with extras.
- **A closed set, validated here.** A style, a department colour, a decor item and a
  pet are names from the tables below; a refusal names the choices so the model can
  correct itself. The editor, `bento office` and the agent's `set_office` tool can
  choose from the set and nothing else — no string reaches the painter unchecked.
- **One definition of the place.** The page draws from `view()`: the styles' colours
  travel in it, so the terminal's description and the canvas cannot disagree about
  what "space station" means. The page lays the rooms out; it decides nothing about
  who sits where.
- **Personal.** `office` is a USER_KEY: how my office looks costs nothing machine-wide
  and reconfigures nothing — it is the character editor's argument, for a room.

The colours in STYLES are the ROOM's, like skin tones are a person's: a greenhouse is
green on every theme. The desktop's theme still owns everything around the canvas.

Kept free of HTTP and asyncio, like avatars.py and jobs.py: `bento office` reads and
edits the same config with the server down.
"""
from __future__ import annotations

import json
import re

#: The look of the whole floor. `floor` is two tones of one pattern, `wall` the band at
#: the top of every room, `accent` the trim and the lamps. Order is the picker's order.
STYLES: dict[str, dict] = {
    "pop": {"label": "Pop comic", "blurb": "bright halftone floors, bold ink, primary colours",
            "floor": ["#ffe27a", "#ffd23f"], "wall": "#5ab0f0", "accent": "#ff4d4d", "pattern": "dots"},
    "loft": {"label": "Startup loft", "blurb": "wooden planks, brick walls, warm lamps",
             "floor": ["#d9a066", "#c98f55"], "wall": "#b8573f", "accent": "#f59e0b", "pattern": "planks"},
    "tower": {"label": "Glass tower", "blurb": "carpet tiles, pale walls, blue trim",
              "floor": ["#a9b4c2", "#9ba7b6"], "wall": "#e3eaf2", "accent": "#2563eb", "pattern": "tiles"},
    "cozy": {"label": "Cozy studio", "blurb": "soft rugs, sage walls, terracotta",
             "floor": ["#ecd3b0", "#e2c49c"], "wall": "#8fb996", "accent": "#e76f51", "pattern": "rug"},
    "space": {"label": "Space station", "blurb": "metal deck plates, dark hull, cyan lights",
              "floor": ["#4a5468", "#424b5e"], "wall": "#1b2233", "accent": "#22d3ee", "pattern": "grid"},
    "garden": {"label": "Greenhouse", "blurb": "stone paths, glass walls, plants everywhere",
               "floor": ["#b5d197", "#a7c587"], "wall": "#e7f4dc", "accent": "#65a30d", "pattern": "stone"},
    "night": {"label": "Night shift", "blurb": "dark wood, violet dusk, desk lamps on",
              "floor": ["#473a57", "#3e3250"], "wall": "#261e36", "accent": "#c084fc", "pattern": "planks"},
}
DEFAULT_STYLE = "pop"

#: A department's colour: its door sign, its carpet edge and its people's desk lamps.
COLORS: dict[str, str] = {
    "teal": "#14b8a6", "violet": "#8b5cf6", "amber": "#f59e0b", "rose": "#f43f5e",
    "sky": "#0ea5e9", "lime": "#84cc16", "orange": "#f97316", "slate": "#64748b",
}
DECOR = ("plants", "coffee", "whiteboard", "bookshelf", "arcade", "posters")
PETS = ("none", "cat", "dog", "robot")

MAX_DEPTS = 6          # a floor plan, not an org chart: six rooms plus the fixed ones
NAME_MAX = 24
FLOOR = "Open floor"   # where a specialist nobody placed sits

DEFAULT: dict = {
    "name": "HQ",
    "style": DEFAULT_STYLE,
    "departments": [],
    "meeting": True,
    "lounge": True,
    "decor": ["plants", "coffee", "whiteboard"],
    "pet": "cat",
}


def _plain(text, limit: int = NAME_MAX) -> str:
    """A name somebody typed: printable, one line, trimmed. Control and bidi characters
    are what make a label lie on screen (the teamlink.plain rule), so they never reach
    the canvas or a terminal."""
    s = re.sub(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]", "", str(text or ""))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def _choice(value, table, what: str) -> str:
    v = str(value or "").strip().lower()
    names = list(table)
    if v in names:
        return v
    # the picker's own words: "space station" → space, "Startup loft" → loft
    if table is STYLES:
        for k, s in STYLES.items():
            if v and (v == s["label"].lower() or v in s["label"].lower().split()):
                return k
    raise ValueError(f"'{value}' is not a {what} — choose one of: {', '.join(names)}")


def agents(store) -> list[str]:
    """The specialists that exist, in the order the Team app lists them."""
    try:
        return [s["name"] for s in store.list_subagents() if s.get("name") and s.get("enabled", 1) not in (0, False)]
    except Exception:
        return []


def current(cfg: dict) -> dict:
    """The stored office, with every missing field at its default. Never raises: a
    hand-edited config with a bad value draws the default for that field."""
    raw = (cfg or {}).get("office") or {}
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT.items()}
    if not isinstance(raw, dict):
        return out
    try:
        out.update(clean(raw, known=None)[0])
    except ValueError:
        pass
    return out


def clean(spec: dict, known: list[str] | None) -> tuple[dict, list[str]]:
    """The only way a change reaches the office. Returns (clean fields, dropped names).

    Only the fields given are returned, so a patch touches nothing else. `known` is the
    roster to check members against; None skips that check (reading a stored office,
    where stale members are dropped at view time instead)."""
    out: dict = {}
    dropped: list[str] = []
    if "name" in spec:
        out["name"] = _plain(spec["name"]) or DEFAULT["name"]
    if "style" in spec:
        out["style"] = _choice(spec["style"], STYLES, "style")
    for flag in ("meeting", "lounge"):
        if flag in spec:
            out[flag] = bool(spec[flag]) and str(spec[flag]).lower() not in ("false", "no", "off", "0")
    if "pet" in spec:
        out["pet"] = _choice(spec["pet"] or "none", PETS, "pet")
    if "decor" in spec:
        items = spec["decor"] if isinstance(spec["decor"], list) else str(spec["decor"] or "").split(",")
        out["decor"] = []
        for it in items:
            if str(it).strip():
                d = _choice(it, DECOR, "decor item")
                if d not in out["decor"]:
                    out["decor"].append(d)
    if "departments" in spec:
        depts, seen_names, placed = [], set(), set()
        known_l = {k.lower(): k for k in (known or [])}
        for i, d in enumerate(spec["departments"] or []):
            if not isinstance(d, dict):
                continue
            name = _plain(d.get("name"))
            if not name or name.lower() in seen_names or name.lower() == FLOOR.lower():
                continue
            if len(depts) >= MAX_DEPTS:
                raise ValueError(f"an office has room for {MAX_DEPTS} departments — merge some first")
            seen_names.add(name.lower())
            color = _choice(d.get("color") or list(COLORS)[i % len(COLORS)], COLORS, "colour")
            members = []
            for m in d.get("members") or []:
                m = str(m).strip().lstrip("@")
                if not m:
                    continue
                if known is not None:
                    real = known_l.get(m.lower())
                    if not real:
                        dropped.append(m)
                        continue
                    m = real
                if m.lower() in placed:        # one desk each: the first department wins
                    continue
                placed.add(m.lower())
                members.append(m)
            depts.append({"name": name, "color": color, "members": members})
        out["departments"] = depts
    return out, dropped


def save(cfg: dict, store, patch: dict) -> tuple[dict, list[str]]:
    """Apply a patch to the stored office. The caller saves config and says what changed."""
    fields, dropped = clean(patch, known=agents(store))
    office = current(cfg)
    office.update(fields)
    cfg["office"] = office
    return office, dropped


def place(cfg: dict, store, agent: str, department: str, color: str = "") -> dict:
    """Move one specialist to a department, creating the department if it is new.
    `department` of '' or the open floor's name takes it out of every department."""
    known = {k.lower(): k for k in agents(store)}
    real = known.get(str(agent or "").strip().lstrip("@").lower())
    if not real:
        raise ValueError(f"no specialist called '{agent}' — choose one of: {', '.join(known.values()) or 'none yet'}")
    office = current(cfg)
    depts = [dict(d, members=[m for m in d["members"] if m.lower() != real.lower()]) for d in office["departments"]]
    target = _plain(department)
    if target and target.lower() != FLOOR.lower():
        hit = next((d for d in depts if d["name"].lower() == target.lower()), None)
        if not hit:
            hit = {"name": target, "color": color or list(COLORS)[len(depts) % len(COLORS)], "members": []}
            depts.append(hit)
        hit["members"].append(real)
    office, _ = save(cfg, store, {"departments": depts})
    return office


def view(cfg: dict, store) -> dict:
    """Everything the page draws, and nothing it has to decide: the office, its rooms
    in order with the people really in them, and the tables for the editor."""
    office = current(cfg)
    roster = agents(store)
    live = {r.lower(): r for r in roster}
    rooms = [{"kind": "lead", "name": f"{(cfg or {}).get('agent_name') or 'Aria'}'s office",
              "color": "teal", "members": ["@agent"]}]
    placed: set[str] = set()
    for d in office["departments"]:
        members = [live[m.lower()] for m in d["members"] if m.lower() in live and m.lower() not in placed]
        placed.update(m.lower() for m in members)
        rooms.append({"kind": "dept", "name": d["name"], "color": d["color"], "members": members})
    loose = [r for r in roster if r.lower() not in placed]
    if loose or not office["departments"]:
        rooms.append({"kind": "floor", "name": FLOOR, "color": "slate", "members": loose})
    if office["meeting"]:
        rooms.append({"kind": "meeting", "name": "Meeting room", "color": "amber", "members": []})
    if office["lounge"]:
        rooms.append({"kind": "lounge", "name": "Lounge", "color": "lime", "members": []})
    return {"office": office, "rooms": rooms, "agents": roster,
            "style": STYLES[office["style"]], "styles": STYLES, "colors": COLORS,
            "decor": list(DECOR), "pets": list(PETS), "max_departments": MAX_DEPTS}


def describe(v: dict) -> str:
    """One sentence: what the agent says back after a change."""
    o = v["office"]
    depts = [r for r in v["rooms"] if r["kind"] in ("dept", "floor")]
    parts = [f"{r['name']} ({', '.join(r['members']) or 'empty'})" for r in depts]
    extra = [x for x, on in (("a meeting room", o["meeting"]), ("a lounge", o["lounge"])) if on]
    pet = f", and a {o['pet']}" if o["pet"] != "none" else ""
    return (f"{o['name']} is a {STYLES[o['style']]['label'].lower()} office: "
            f"{'; '.join(parts) or 'no departments yet'}"
            f"{' — with ' + ' and '.join(extra) if extra else ''}{pet}.")


def text(v: dict) -> str:
    """The office for a terminal: the TUI face of a place that is otherwise a picture."""
    o = v["office"]
    st = STYLES[o["style"]]
    lines = [f"{o['name']} — {st['label']} ({st['blurb']})", ""]
    for r in v["rooms"]:
        if r["kind"] in ("meeting", "lounge"):
            continue
        who = ", ".join("your agent" if m == "@agent" else m for m in r["members"]) or "nobody yet"
        tag = "" if r["kind"] != "dept" else f"  [{r['color']}]"
        lines.append(f"  {r['name']:<24} {who}{tag}")
    shared = [r["name"].lower() for r in v["rooms"] if r["kind"] in ("meeting", "lounge")]
    lines.append("")
    lines.append(f"  also: {', '.join(shared) or 'no shared rooms'}"
                 f" · decor: {', '.join(o['decor']) or 'none'} · pet: {o['pet']}")
    if not v["agents"]:
        lines.append("  No specialists yet — ask your agent for one and they take a desk here.")
    return "\n".join(lines)


def record(store, detail: str) -> None:
    """A change the PERSON made (the editor or `bento office`) is a ledger row like every
    other change on this machine; the agent's `set_office` gets its row from the gate."""
    try:
        from . import users as _users
        uid = _users.current() or ""
    except Exception:
        uid = ""
    try:
        store.audit_add(uid=uid, principal_kind="user", principal_id="", action="office.write",
                        resource="office", effect="allow", rule="person", outcome="ok",
                        detail=str(detail)[:1000])
    except Exception:
        pass


# ---- designing it from a description -------------------------------------------------
#
# "A cosy space station with a research wing" -> an office. The machine's brain picks
# (executors.ask_once — the executor or the provider model, whichever answers turns);
# the closed set decides: every field goes through clean() on its own, so one wrong
# value is dropped and NAMED rather than failing the whole design. With no brain to
# ask, the style names, pets and decor in the words are matched — and the answer
# says which happened, the character designer's rule.

def design_prompt(description: str, v: dict) -> tuple[str, str]:
    system = ("You design an office for a person's AI agents. Answer with ONE JSON object "
              "and nothing else — no prose, no code fence.")
    agents = ", ".join(v["agents"]) or "(none yet)"
    prompt = (
        f'The person asked for: "{description}"\n\n'
        "Fields and their ONLY allowed values:\n"
        f'- "style": one of {", ".join(STYLES)} '
        f'({"; ".join(k + " = " + s["label"] for k, s in STYLES.items())})\n'
        '- "name": the name on the door, at most 24 characters\n'
        f'- "departments": a list of up to {MAX_DEPTS} objects {{"name", "color", "members"}}; '
        f'color one of {", ".join(COLORS)}; members only from: {agents}\n'
        '- "meeting": true/false (a meeting room, where huddles gather)\n'
        '- "lounge": true/false\n'
        f'- "decor": a list from {", ".join(DECOR)}\n'
        f'- "pet": one of {", ".join(PETS)}\n'
        "Set only the fields the description is about. Keep the current departments unless "
        f"asked to change them. Currently: {json.dumps(current_of(v))}")
    return system, prompt


def current_of(v: dict) -> dict:
    o = v["office"]
    return {k: o[k] for k in ("style", "name", "departments", "meeting", "lounge", "decor", "pet")}


def read_design(raw: str, known: list[str]) -> tuple[dict, list[str]]:
    """The model's JSON, field by field through the closed set. Returns (patch,
    dropped) — dropped names every field or member that was not allowed."""
    m = re.search(r"\{.*\}", str(raw or ""), re.S)
    if not m:
        return {}, []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}, []
    patch, dropped = {}, []
    for k in ("style", "name", "departments", "meeting", "lounge", "decor", "pet"):
        if k not in data:
            continue
        try:
            got, lost = clean({k: data[k]}, known=known)
            patch.update(got)
            dropped += [f"member {x}" for x in lost]
        except ValueError:
            dropped.append(f"{k} {data[k]!r}")
    return patch, dropped


_STYLE_WORDS = {"pop": ("pop", "comic", "cartoon"), "loft": ("loft", "startup", "brick", "wood"),
                "tower": ("tower", "glass", "corporate", "skyscraper"), "cozy": ("cozy", "cosy", "studio", "warm"),
                "space": ("space", "station", "spaceship", "orbit", "sci-fi", "scifi"),
                "garden": ("garden", "greenhouse", "plants", "green"), "night": ("night", "dark", "late")}


def from_words(description: str) -> dict:
    """With no brain to ask: the closed set's own words in what was typed."""
    t = " " + re.sub(r"[^a-z0-9\- ]", " ", str(description or "").lower()) + " "
    patch: dict = {}
    # the style whose words appear most: "a cosy space station" is a station, cosily.
    # A tie goes to the word said LAST — the noun follows its adjectives, so "a cosy
    # greenhouse" is a greenhouse, cosily, not a cosy studio.
    hits = {k: (sum(f" {w} " in t for w in words), max((t.rfind(f" {w} ") for w in words), default=-1))
            for k, words in _STYLE_WORDS.items()}
    best = max(hits, key=lambda k: hits[k])
    if hits[best][0]:
        patch["style"] = best
    for p in PETS[1:]:
        if f" {p} " in t:
            patch["pet"] = p
    decor = [d for d in DECOR if f" {d.rstrip('s')}" in t]
    if decor:
        patch["decor"] = decor
    m = re.search(r"(?:called|named)\s+[\"']?(.+?)(?:[\"',.;]|\s+(?:with|and|for|in|that|where)\s|$)",
                  str(description or ""))
    if m and m.group(1).strip():
        patch["name"] = _plain(m.group(1))
    return patch
