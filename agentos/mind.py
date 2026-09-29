"""The Mind: your agents, what they know and how it connects, as one picture.

Asked for with a video of a glowing brain on a wall screen ("get into the brains of our
agents and their data and how that is interconnected"). This module is the data half;
`01g-mind.js` draws it. The rule is the Office's: nothing on screen that did not come
from here. Every cluster is a real thing, every filament a real connection, and every
number a count read from the database.

- The **core** is your lead agent.
- A **cluster** per specialist (its skills and its runs this week), plus **Memory**
  (what it remembers about you), **Knowledge** (the entities and facts in the graph, and
  the edges between them) and **Missions** (each flow, wired to the agents on its roster).
- **Links** between specialists are the times they actually asked each other
  (`fabric.talk_log`), thicker the more they did.
- **This week** and **right now** are the side panels; `spoken()` says them aloud, from
  the same numbers, so the voice never claims what the screen does not show.

Kept free of HTTP: `bento mind` prints the same snapshot in a terminal.
"""

from __future__ import annotations

import time

MAX_MEMORY = 140
MAX_KNOWLEDGE = 160
MAX_KG_EDGES = 260
MAX_RUNS_PER_AGENT = 14
MAX_MENTIONS = 320
WEEK = 7 * 86400
#: fixed hues for the three shared lobes; specialists take the rest of the wheel
HUES = {"memory": 188, "knowledge": 276, "missions": 36}
AGENT_HUES = (330, 140, 212, 12, 58, 300, 165, 96, 245, 350)
#: a department's cluster takes its room's colour (office.COLORS), so Finance is the same
#: amber in the Office and in the Mind. Amber leans gold here, away from Missions' orange.
DEPT_HUES = {"teal": 172, "violet": 262, "amber": 48, "rose": 345, "sky": 200,
             "lime": 88, "orange": 22, "slate": 222}


def _short(text: str, n: int = 70) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def snapshot(store, cfg: dict, running: set | None = None, now: float | None = None) -> dict:
    """The whole picture for this person. `running` is the names of agents with a run
    open right now (the control plane's live instances); the rest is read from their
    own database, so a person sees only their own mind."""
    from . import fabric as fabricmod
    now = now or time.time()
    since = now - WEEK
    running = set(running or ())
    lead = str(cfg.get("agent_name") or "Aria")
    agents = [d for d in store.list_subagents()
              if d.get("enabled") is not False and "@" not in d["name"]]

    hubs = [{"id": "memory", "kind": "memory", "label": "Memory", "hue": HUES["memory"]},
            {"id": "knowledge", "kind": "knowledge", "label": "Knowledge", "hue": HUES["knowledge"]},
            {"id": "missions", "kind": "missions", "label": "Missions", "hue": HUES["missions"]}]
    nodes: list[dict] = []
    links: list[dict] = []
    # With a company (company.py), a department is ONE cluster and its people are points
    # in it: twenty-one specialists as twenty-one clusters crowded the ring into a wall of
    # names. Anybody in no department keeps a cluster of their own, as before.
    from . import company as companymod
    try:
        org = companymod.membership(cfg, store)
    except Exception:
        org = {"departments": [], "of": {}}
    names_live = {d["name"] for d in agents}
    where: dict = {}
    for dept in org["departments"]:
        people = [m for m in dept["members"] if m in names_live]
        if not people:
            continue
        hid = f"dept:{dept['name']}"
        hubs.append({"id": hid, "kind": "dept", "label": dept["name"],
                     "hue": DEPT_HUES.get(dept["color"], 200), "head": dept["head"],
                     "members": people, "busy": any(m in running for m in people)})
        for m in people:
            where[m] = hid
            nodes.append({"id": f"a:{m}", "hub": hid, "label": m, "kind": "person",
                          "head": m == dept["head"] and dept["named"],
                          "title": org["of"].get(m, {}).get("title", ""), "busy": m in running})
    for i, d in enumerate(a for a in agents if a["name"] not in where):
        hubs.append({"id": f"agent:{d['name']}", "kind": "agent", "label": d["name"],
                     "hue": AGENT_HUES[i % len(AGENT_HUES)],
                     "busy": d["name"] in running})
        where[d["name"]] = f"agent:{d['name']}"

    mems = store.search_memories(limit=MAX_MEMORY)
    for m in mems:
        nodes.append({"id": f"m:{m['id']}", "hub": "memory", "label": _short(m.get("content")),
                      "full": str(m.get("content") or ""),
                      "t": m.get("updated_at") or m.get("created_at") or 0,
                      "pinned": bool(m.get("pinned"))})

    try:
        g = store.kg_graph()
    except Exception:
        g = {"nodes": [], "edges": []}
    degree: dict = {}
    for e in g["edges"]:
        degree[e["src"]] = degree.get(e["src"], 0) + 1
        degree[e["dst"]] = degree.get(e["dst"], 0) + 1
    kg = sorted(g["nodes"], key=lambda n: -degree.get(n["id"], 0))[:MAX_KNOWLEDGE]
    kept = {n["id"] for n in kg}
    for n in kg:
        nodes.append({"id": f"k:{n['id']}", "hub": "knowledge", "label": _short(n.get("name"), 40),
                      "w": degree.get(n["id"], 0)})
    for e in [e for e in g["edges"] if e["src"] in kept and e["dst"] in kept][:MAX_KG_EDGES]:
        links.append({"a": f"k:{e['src']}", "b": f"k:{e['dst']}", "kind": "fact",
                      "label": _short(e.get("rel") or e.get("relation") or "", 30)})

    names = {d["name"] for d in agents}
    for f in store.list_flows():
        fid = f"f:{f['name']}"
        nodes.append({"id": fid, "hub": "missions", "label": f["name"], "on": bool(f.get("enabled"))})
        wired = set()
        for m in (f.get("roster") or []):
            member = m.get("subagent") if isinstance(m, dict) else m
            if member in names and where.get(member) not in wired:
                wired.add(where[member])          # a desk's whole roster is one department
                links.append({"a": fid, "b": where[member], "kind": "roster"})

    runs = [r for r in store.fabric_runs(limit=600) if (r.get("started_at") or 0) >= since]
    per: dict = {}
    for r in runs:
        per.setdefault(r.get("ref") or "", []).append(r)
    for d in agents:
        for s in (d.get("skills") or [])[:8]:
            nodes.append({"id": f"s:{d['name']}:{s}", "hub": where[d["name"]],
                          "label": s, "kind": "skill"})
        for r in per.get(d["name"], [])[:MAX_RUNS_PER_AGENT]:
            nodes.append({"id": f"r:{r['id']}", "hub": where[d["name"]],
                          "label": _short(str(r.get("input") or "").split("\n")[0], 60),
                          "full": str(r.get("input") or "")[:2000],
                          "kind": "run", "status": r.get("status") or "", "t": r.get("started_at") or 0})

    # The lines BETWEEN the clusters: a memory or a run that names a person, place or topic
    # in the graph is joined to it. Asked for from a screenshot ("the mind has certain
    # lines that need to be created"): Memory and Knowledge sat as two clouds with nothing
    # between them, though half the memories were about the entities next door.
    links.extend(_mentions(nodes, kg))

    # who actually talked to whom this week, from the runs they already are
    talk: dict = {}
    for e in fabricmod.talk_log(store, 120):
        if e["when"] < since:
            continue
        who = [w for w in e.get("who") or [] if w in names]
        for i in range(len(who)):
            for j in range(i + 1, len(who)):
                k = tuple(sorted((who[i], who[j])))
                talk[k] = talk.get(k, 0) + 1
    # between clusters: two people in one department talking is inside that cluster
    between: dict = {}
    for (a, b), n in talk.items():
        ha, hb = where.get(a), where.get(b)
        if ha and hb and ha != hb:
            k = tuple(sorted((ha, hb)))
            between[k] = between.get(k, 0) + n
    for (a, b), n in between.items():
        links.append({"a": a, "b": b, "kind": "talk", "n": n})

    # a free talk's messages are conversation, not tasks; they are counted on their own
    for n in nodes:
        n.pop("full", None)             # matched above; the page gets the short label only
    week = [r for r in runs if r.get("kind") in ("flow", "delegate", "message", "huddle")]
    flows_run = [r for r in runs if r.get("kind") == "flow"]
    stats = {"runs": len(week),
             "missions": len(flows_run),
             "missions_ok": sum(1 for r in flows_run if r.get("status") == "ok"),
             "failed": sum(1 for r in week if r.get("status") in ("error", "timeout")),
             "tokens": sum(int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0) for r in runs),
             "asks": sum(1 for r in runs if r.get("kind") == "message"),
             "free_talks": sum(1 for r in runs if r.get("kind") == "freetalk" and not r.get("parent_run")),
             "memories": len(mems), "knowledge": len(g["nodes"]), "facts": len(g["edges"]),
             "mentions": sum(1 for k in links if k["kind"] == "mention"),
             "missions_on": sum(1 for n in nodes if n["hub"] == "missions" and n.get("on"))}
    brief = {}
    try:
        from . import brief as briefmod
        brief = briefmod.page(store)["counts"]
    except Exception:
        brief = {}
    team = []
    for d in agents:
        mine = per.get(d["name"], [])
        last = mine[0] if mine else None
        team.append({"name": d["name"], "busy": d["name"] in running, "runs": len(mine),
                     "dept": org["of"].get(d["name"], {}).get("dept", ""),
                     "last": _short(str(last.get("input") or "").split("\n")[0], 60) if last else "",
                     "last_status": (last or {}).get("status", ""),
                     "brain": fabricmod.agent_brain(cfg, d).get("provider_name", "")})
    out = {"lead": lead, "hubs": hubs, "nodes": nodes, "links": links, "stats": stats,
           "brief": brief, "team": team, "at": now, "where": where}
    out["spoken"] = spoken(out)
    return out


def _mentions(nodes: list[dict], kg: list[dict]) -> list[dict]:
    """A link from each memory or run to every graph entity its text names, as a whole
    word and ignoring case. Names under three letters are skipped (they match anything)."""
    import re
    names = {}
    for n in kg:
        name = " ".join(str(n.get("name") or "").split())
        if len(name) >= 3:
            names.setdefault(name.lower(), n["id"])
    if not names:
        return []
    pat = re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in
                                           sorted(names, key=len, reverse=True)) + r")(?!\w)",
                     re.IGNORECASE)
    out, seen = [], set()
    for node in nodes:
        if not (node["id"].startswith("m:") or node["id"].startswith("r:")):
            continue
        text = node.get("full") or node.get("label") or ""
        for m in pat.finditer(text):
            kid = names.get(m.group(1).lower())
            key = (node["id"], kid)
            if kid and key not in seen:
                seen.add(key)
                out.append({"a": node["id"], "b": f"k:{kid}", "kind": "mention"})
                if len(out) >= MAX_MENTIONS:
                    return out
    return out


def spoken(snap: dict) -> str:
    """The panels as sentences, for the Tell me button and `bento mind`. Only what the
    numbers say; a week with nothing in it says so."""
    s, b = snap["stats"], snap.get("brief") or {}
    parts = []
    if s["runs"]:
        parts.append(f"This week your team ran {s['runs']} task{'s' if s['runs'] != 1 else ''}"
                     + (f", including {s['missions']} mission run{'s' if s['missions'] != 1 else ''}"
                        if s["missions"] else "")
                     + (f", and {s['failed']} did not finish" if s["failed"] else "") + ".")
    else:
        parts.append("Your team has not run anything this week.")
    asks = f"asked each other {s['asks']} time{'s' if s['asks'] != 1 else ''}" if s["asks"] else ""
    free = (f"talked freely {s['free_talks']} time{'s' if s['free_talks'] != 1 else ''}"
            if s["free_talks"] else "")
    if asks or free:
        parts.append("They " + " and ".join(x for x in (asks, free) if x) + ".")
    busy = [t["name"] for t in snap["team"] if t["busy"]]
    if busy:
        parts.append(f"Right now {' and '.join(busy[:3])} {'is' if len(busy) == 1 else 'are'} working.")
    need = int(b.get("needs_you") or 0) + int(b.get("decide") or 0)
    if need:
        parts.append(f"{need} thing{'s' if need != 1 else ''} in your Brief need{'s' if need == 1 else ''} you.")
    if s["memories"] or s["knowledge"]:
        parts.append(f"I remember {s['memories']} thing{'s' if s['memories'] != 1 else ''} about you"
                     + (f" and know {s['knowledge']} people, places and topics" if s["knowledge"] else "")
                     + ".")
    else:
        parts.append("I have not saved anything about you yet.")
    return " ".join(parts)
