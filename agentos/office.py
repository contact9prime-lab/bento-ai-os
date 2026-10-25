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
#: How the office is drawn. "3d": rooms round the Brain in 3D (24k-office3d.js), which
#: falls back to "flat" on a screen with no 3D graphics and says so. "flat": the comic plan.
#: "island": the same rooms as buildings in a town of the person's choosing (an island, a
#: canal city, a castle...), each department's district of houses behind its building,
#: a carrier for work handed over (24t-island.js). The id stays "island", the first setting.
LOOKS = {"3d": "3D rooms around the Brain", "flat": "Flat comic plan",
         "island": "A town: an island, a canal city, a castle or a forest"}
#: The town builder (the person's own arrangement, look "island"): the setting it stands in,
#: how many houses each district grows, whether the carrier runs, how wooded it is.
#: Houses are scenery. Who works where is still the departments' members, never a house.
TREES = ("few", "some", "lots")
#: The settings the page can draw (ISL_SETS in 24t-island.js holds the same names).
SETTINGS = {"island": "An island in the sea, with a lighthouse and a railway",
            "islands": "A cluster of small islands joined by footbridges, a ferry between them",
            "canals": "A city on canals, like Venice, with gondolas and a bell tower",
            "castle": "A castle town inside walls and a moat, with a keep",
            "forest": "A town in a forest by a river, with a watchtower"}
MAX_HOUSES = 12
ISLAND_DEFAULT: dict = {"houses": {}, "train": True, "trees": "some", "setting": "island"}
PETS = ("none", "cat", "dog", "robot")

MAX_DEPTS = 10         # a company's worth of rooms (company.py), plus the fixed ones
NAME_MAX = 24
ABOUT_MAX = 200        # a department's one-line mandate
TITLE_MAX = 40         # "Head of Finance"
_DESK = re.compile(r"^[A-Za-z0-9_-]{1,49}$")   # the department's desk is a flow name
_HANDS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")   # hands.py's profile names
MAX_REPORT_DEPTH = 4   # departments in one line of reports, before the lead
FLOOR = "Open floor"   # where a specialist nobody placed sits

DEFAULT: dict = {
    "name": "HQ",
    "style": DEFAULT_STYLE,
    "departments": [],
    "meeting": True,
    "lounge": True,
    "decor": ["plants", "coffee", "whiteboard"],
    "pet": "cat",
    "look": "3d",
    "island": ISLAND_DEFAULT,
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
    out = json.loads(json.dumps(DEFAULT))       # a deep copy: the island's houses are a dict
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
    if "look" in spec:
        v = str(spec["look"] or "").strip().lower().replace(" ", "")
        out["look"] = _choice({"3-d": "3d", "comic": "flat", "2d": "flat", "plan": "flat"}.get(v, v), LOOKS, "look")
    if "island" in spec:
        out["island"] = clean_island(spec["island"])
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
            dept = {"name": name, "color": color, "members": members}
            # What makes a room a DEPARTMENT of a company (company.py): who heads it,
            # what it is for, the flow that is its desk, and each person's title. All
            # optional, so an office drawn by hand is still just rooms.
            lead = str(d.get("lead") or "").strip().lstrip("@")
            if lead and lead.lower() in {m.lower() for m in members}:
                dept["lead"] = next(m for m in members if m.lower() == lead.lower())
            about = _plain(d.get("about"), ABOUT_MAX)
            if about:
                dept["about"] = about
            desk = str(d.get("desk") or "").strip()
            if desk and _DESK.match(desk):
                dept["desk"] = desk
            titles = d.get("titles") if isinstance(d.get("titles"), dict) else {}
            kept = {m: _plain(titles.get(m) or titles.get(m.lower()), TITLE_MAX) for m in members}
            kept = {m: t for m, t in kept.items() if t}
            if kept:
                dept["titles"] = kept
            boss = _plain(d.get("reports_to"))
            if boss:
                dept["reports_to"] = boss
            # the executor (hands profile) the department's people work with unless one
            # of them has their own (hands.profile_name); a name, checked by company.py
            hands_ = str(d.get("hands") or "").strip()
            if hands_ and _HANDS.match(hands_):
                dept["hands"] = hands_
            # the kit a new department was set up with (company.recommend): what it was
            # offered and took, kept so the panel can say what is still not switched on
            kit = d.get("kit") if isinstance(d.get("kit"), dict) else None
            if kit:
                dept["kit"] = {k: [str(x)[:64] for x in (kit.get(k) or [])[:12] if str(x).strip()]
                               for k in ("tools", "skills", "mcp") if kit.get(k)}
            depts.append(dept)
        _reporting_lines(depts)
        out["departments"] = depts
    return out, dropped


def clean_island(spec) -> dict:
    """The island builder's settings, each field on its own: a house count is a whole
    number from 0 to MAX_HOUSES for a district named by its department, the trees one of
    TREES, the train on or off. A missing field keeps its default, and a district that is
    not a department any more is simply not drawn (the view skips it), as stale members are."""
    if not isinstance(spec, dict):
        raise ValueError("the island is a set of fields: setting, houses, train, trees")
    out = {"houses": {}, "train": ISLAND_DEFAULT["train"], "trees": ISLAND_DEFAULT["trees"],
           "setting": ISLAND_DEFAULT["setting"]}
    houses = spec.get("houses") or {}
    if not isinstance(houses, dict):
        raise ValueError("houses is a district name and a number, e.g. {\"Sales\": 6}")
    for k, n in list(houses.items())[:MAX_DEPTS]:
        name = _plain(k)
        if not name:
            continue
        try:
            n = int(n)
        except (TypeError, ValueError):
            raise ValueError(f"{name} needs a number of houses from 0 to {MAX_HOUSES}") from None
        out["houses"][name] = max(0, min(MAX_HOUSES, n))
    if "train" in spec:
        out["train"] = bool(spec["train"]) and str(spec["train"]).lower() not in ("false", "no", "off", "0")
    if "trees" in spec:
        out["trees"] = _choice(spec["trees"], TREES, "number of trees")
    if "setting" in spec:
        s = str(spec["setting"] or "").strip().lower()
        out["setting"] = _choice(_SETTING_ALIASES.get(s, s), SETTINGS, "setting")
    return out


#: what people call the settings, read only by clean_island (the closed set stays five words)
_SETTING_ALIASES = {"venice": "canals", "canal": "canals", "canal city": "canals", "archipelago": "islands",
                    "isles": "islands", "woods": "forest", "woodland": "forest", "fortress": "castle",
                    "kingdom": "castle", "sea": "island"}


def _reporting_lines(depts: list[dict]) -> None:
    """Who each department reports to: another department, or the lead when the field
    is absent. A name that is not a department here (a rename, a typo) falls back to
    the lead. A loop or a line deeper than MAX_REPORT_DEPTH is refused in a sentence:
    a loop has no top, so its work would never reach anybody who can sign it off."""
    names = {d["name"].lower(): d["name"] for d in depts}
    for d in depts:
        boss = str(d.get("reports_to") or "").strip()
        real = names.get(boss.lower())
        if not real or real == d["name"]:
            d.pop("reports_to", None)
        else:
            d["reports_to"] = real
    up = {d["name"]: d.get("reports_to") or "" for d in depts}
    for d in depts:
        line, at = [d["name"]], up[d["name"]]
        while at:
            if at in line:
                raise ValueError(f"{' → '.join(line + [at])} is a loop. One of them has to "
                                 f"report to the lead instead.")
            line.append(at)
            at = up.get(at, "")
        if len(line) > MAX_REPORT_DEPTH:
            raise ValueError(f"{' → '.join(line)} is {len(line)} departments deep. A line of "
                             f"reports can be {MAX_REPORT_DEPTH} at most, then the lead.")


def save(cfg: dict, store, patch: dict) -> tuple[dict, list[str]]:
    """Apply a patch to the stored office. The caller saves config and says what changed."""
    office = current(cfg)
    if isinstance(patch.get("island"), dict):
        # a change to one field of the town keeps the others (a new setting keeps the houses)
        patch = {**patch, "island": {**office["island"], **patch["island"]}}
    fields, dropped = clean(patch, known=agents(store))
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
        room = {"kind": "dept", "name": d["name"], "color": d["color"], "members": members}
        for k in ("about", "desk", "reports_to"):
            if d.get(k):
                room[k] = d[k]
        if d.get("lead") in members:
            room["lead"] = d["lead"]
        if d.get("titles"):
            room["titles"] = {m: t for m, t in d["titles"].items() if m in members}
        rooms.append(room)
    # somebody who works in another of the person's companies (company.py) is not on
    # this company's open floor: each company is its own office
    away = set()
    for rec in ((cfg or {}).get("companies") or {}).values():
        o = rec.get("office") if isinstance(rec, dict) else None
        for d in (o or {}).get("departments") or [] if isinstance(o, dict) else []:
            if isinstance(d, dict):
                away.update(str(m).lower() for m in d.get("members") or [])
    loose = [r for r in roster if r.lower() not in placed and r.lower() not in away]
    if loose or not office["departments"]:
        rooms.append({"kind": "floor", "name": FLOOR, "color": "slate", "members": loose})
    if office["meeting"]:
        rooms.append({"kind": "meeting", "name": "Meeting room", "color": "amber", "members": []})
    if office["lounge"]:
        rooms.append({"kind": "lounge", "name": "Lounge", "color": "lime", "members": []})
    # Buddy (face.py): only the lead is drawn. Specialists still exist and still work,
    # and the page lights the lead's desk for their work; the editor keeps the full plan.
    from . import face as facemod
    from . import zero as zeromod
    one = facemod.buddy(cfg)
    if one:
        rooms = [r for r in rooms if r["kind"] in ("lead", "lounge")]
    # A Zero is a small screen whose work runs on its hub: one person at a desk, drawn flat.
    # No lounge regulars, no pet, no meeting table, no 3D. Only what is DRAWN changes; the
    # saved plan is left alone, so the machine looks the same again if it stops being a Zero.
    is_zero = zeromod.runs_on_hub(cfg)
    if is_zero:
        one = True
        rooms = [r for r in rooms if r["kind"] == "lead"]
        office = {**office, "look": "flat", "pet": "none", "meeting": False, "lounge": False}
    return {"office": office, "rooms": rooms, "agents": [r for r in roster if r.lower() not in away],
            "buddy": one, "zero": is_zero, "brain": _brain_here(cfg, store),
            "looks": LOOKS, "trees": list(TREES), "max_houses": MAX_HOUSES, "settings": SETTINGS,
            "style": STYLES[office["style"]], "styles": STYLES, "colors": COLORS,
            "decor": list(DECOR), "pets": list(PETS), "max_departments": MAX_DEPTS}


def brain(store) -> dict:
    """What the Brain in the middle of the 3D office holds: counted rows, never a guess.
    Memories are the person's notes; facts are knowledge-graph edges. Every space's rows
    count, because the office is the whole team's and is not scoped to a project."""
    out = {"memories": 0, "facts": 0}
    for key, table in (("memories", "memories"), ("facts", "kg_edges")):
        try:
            out[key] = int(store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except Exception:
            pass
    return out


def _brain_here(cfg: dict, store) -> dict:
    """A Zero's memory and graph are its section on the hub (zeromind.py), so counting
    this machine's own tables would show an empty brain that is not its brain. Say where
    it is instead; the page writes "on <hub>"."""
    try:
        from . import zeromind
        lk = zeromind.hub_link(cfg) if zeromind.zeromod.runs_on_hub(cfg) else None
    except Exception:
        lk = None
    if lk:
        return {"on": str(lk.get("label") or "the hub")}
    return brain(store)


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
                 f" · decor: {', '.join(o['decor']) or 'none'} · pet: {o['pet']}"
                 f" · look: {LOOKS.get(o.get('look'), o.get('look'))}")
    if o.get("look") == "island":
        lines.append("  " + island_text(v))
    if not v["agents"]:
        lines.append("  No specialists yet — ask your agent for one and they take a desk here.")
    return "\n".join(lines)


def island_text(v: dict) -> str:
    """The island builder's settings in one line: houses per district, train, trees."""
    isl = v["office"].get("island") or ISLAND_DEFAULT
    depts = [r["name"] for r in v["rooms"] if r["kind"] == "dept"]
    houses = ", ".join(f"{d} {houses_of(isl, d, v)}" for d in depts) or "no districts yet"
    return (f"island: {isl.get('setting', 'island')} · houses {houses} · train {'on' if isl.get('train', True) else 'off'}"
            f" · trees {isl.get('trees', 'some')}")


def houses_of(isl: dict, dept: str, v: dict) -> int:
    """How many houses a district grows: the person's number, or four and two for each
    of the department's people (a bigger team is a bigger district) until they choose."""
    got = (isl.get("houses") or {})
    for k, n in got.items():
        if k.lower() == dept.lower():
            return int(n)
    room = next((r for r in v["rooms"] if r["kind"] == "dept" and r["name"].lower() == dept.lower()), None)
    return min(MAX_HOUSES, 4 + 2 * len((room or {}).get("members") or []))


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
        f'- "look": one of {", ".join(LOOKS)} ({"; ".join(k + " = " + d for k, d in LOOKS.items())})\n'
        f'- "island" (for the island look): {{"setting": one of {", ".join(SETTINGS)} '
        f'({"; ".join(k + " = " + d for k, d in SETTINGS.items())}), '
        f'"houses": {{department name: 0 to {MAX_HOUSES}}}, "train": true/false, "trees": one of {", ".join(TREES)}}}. '
        'A place to build (Venice, a castle, a forest, islands) is the island look with that setting.\n'
        "Set only the fields the description is about. Keep the current departments unless "
        f"asked to change them. Currently: {json.dumps(current_of(v))}")
    return system, prompt


def current_of(v: dict) -> dict:
    o = v["office"]
    return {k: o[k] for k in ("style", "name", "departments", "meeting", "lounge", "decor", "pet", "look", "island")}


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
    for k in ("style", "name", "departments", "meeting", "lounge", "decor", "pet", "look", "island"):
        if k not in data:
            continue
        try:
            got, lost = clean({k: data[k]}, known=known)
            if k == "island" and isinstance(data[k], dict):
                # only the town fields the model named: the rest stay as the person set them
                got["island"] = {f: v for f, v in got["island"].items() if f in data[k]}
            patch.update(got)
            dropped += [f"member {x}" for x in lost]
        except ValueError:
            dropped.append(f"{k} {data[k]!r}")
    return patch, dropped


_SETTING_WORDS = {
    "island": ("island", "isle", "lighthouse"),
    "islands": ("islands", "archipelago", "isles", "greek", "santorini", "cyclades"),
    "canals": ("venice", "venetian", "canal", "canals", "gondola", "gondolas", "lagoon"),
    "castle": ("castle", "fortress", "fort", "medieval", "kingdom", "citadel", "moat"),
    "forest": ("forest", "woods", "woodland", "jungle", "pines", "pine", "cabin", "cabins"),
}
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
    hits = {s: max((t.rfind(f" {w} ") for w in words), default=-1) for s, words in _SETTING_WORDS.items()}
    named = max(hits, key=lambda s: hits[s])
    if hits[named] >= 0:
        # a place said in words: the town look in that setting (the last one named wins)
        patch["look"] = "island"
        patch["island"] = {"setting": named}
    if any(f" {w} " in t for w in ("lots of trees", "many trees", "more trees", "plant trees")):
        patch.setdefault("island", {})["trees"] = "lots"
    elif any(f" {w} " in t for w in ("few trees", "fewer trees", "less trees")):
        patch.setdefault("island", {})["trees"] = "few"
    if "look" in patch:
        pass                                  # a place was named: that is the look
    elif any(f" {w} " in t for w in ("3d", "3-d", "isometric", "realistic")):
        patch["look"] = "3d"
    elif any(f" {w} " in t for w in ("flat", "2d", "2-d")):
        patch["look"] = "flat"
    decor = [d for d in DECOR if f" {d.rstrip('s')}" in t]
    if decor:
        patch["decor"] = decor
    m = re.search(r"(?:called|named)\s+[\"']?(.+?)(?:[\"',.;]|\s+(?:with|and|for|in|that|where)\s|$)",
                  str(description or ""))
    if m and m.group(1).strip():
        patch["name"] = _plain(m.group(1))
    return patch


def department_of(cfg: dict, member: str) -> tuple[dict, dict] | None:
    """(department, its company's settings) for an agent, in the open company or a
    parked one; None for an agent in no department. Read from the raw rooms, so the gate
    can ask it on every decision without a store: who is in which room is config."""
    m = str(member or "").strip().lower()
    if not m:
        return None
    places = [((cfg or {}).get("office") or {}, (cfg or {}).get("company") or {})]
    for rec in ((cfg or {}).get("companies") or {}).values():
        if isinstance(rec, dict):
            places.append((rec.get("office") or {}, rec.get("company") or {}))
    for off, co in places:
        for d in (off.get("departments") or []) if isinstance(off, dict) else []:
            if isinstance(d, dict) and m in {str(x).lower() for x in d.get("members") or []}:
                return d, (co if isinstance(co, dict) else {})
    return None

