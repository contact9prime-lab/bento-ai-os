"""The agents, and everything each one is given — one computation, every surface.

An agent gets four things and this module is the one place that reads all four:

- a **brain** (`fabric.agent_brain`: its own pinned model, or the machine's brain);
- **hands** (`hands`: its executor profile — tools, folders, web, MCP);
- **authority** (its grants in the permission gate, and its autonomy);
- **company** — which colleagues it may ask (the matrix), which linked teams may ask
  it, which missions put it on their roster, and which skills it carries.

`overview()` is that list; `graph()` turns it into nodes and edges so the whole map
can be drawn (Settings → Agents), printed (`bento agents graph`) and checked by a
test from ONE answer. A second computation of "who may reach what" would be the
place the picture and the gate disagree, and the picture is what people trust.

Kept free of HTTP and asyncio: the terminal reads the same map with the server down.
"""
from __future__ import annotations

from . import hands

MASTER = "@agent"
_FAMS = (("files", "fs."), ("web", "net."), ("tools", "tool."), ("MCP", "mcp."), ("memory", "memory."),
         ("memory", "kg."), ("agents", "agent."), ("mail", "mail."), ("calendar", "calendar."),
         ("media", "media."), ("models", "model."), ("skills", "skill."), ("apps", "app."))


def _fam(action: str) -> str:
    for name, prefix in _FAMS:
        if action.startswith(prefix):
            return name
    return "other"


def _authority(store, name: str, autonomy: str) -> dict:
    """What an agent is allowed, counted by family. Grants written by a mission's
    definition count only inside that mission's runs, so they are counted apart."""
    fams: dict = {}
    desk = {"allow": 0, "deny": 0}
    in_missions = 0
    for g in store.list_grants(principal_kind="subagent"):
        pid = g.get("principal_id") or ""
        if pid not in (name, "*"):
            continue
        if g.get("source") == "definition":
            in_missions += 1
            continue
        eff = "deny" if g.get("effect") == "deny" else "allow"
        desk[eff] += 1
        f = fams.setdefault(_fam(str(g.get("action") or "")), {"allow": 0, "deny": 0})
        f[eff] += 1
    return {"autonomy": autonomy, "allow": desk["allow"], "deny": desk["deny"],
            "families": fams, "in_missions": in_missions}


def overview(store, cfg: dict) -> dict:
    """Every agent here with its brain, hands, authority, skills and company."""
    from . import fabric
    from . import teamlink
    from . import users as usersmod
    cfg = cfg or {}
    profiles = {p["name"].lower(): p for p in hands.list_profiles(store)}

    def hands_of(name: str) -> dict:
        p = profiles.get((name or hands.DEFAULT).lower()) or profiles[hands.DEFAULT]
        return {"name": p["name"], "summary": p["summary"], "builtin": p["builtin"]}

    mx = fabric.matrix(store, cfg)
    flows = store.list_flows()
    try:
        links = teamlink.links(usersmod.current() or "")
    except Exception:
        links = []
    access = {lk["label"]: fabric.link_access(store, lk["label"]) for lk in links}

    def missions_of(name: str) -> list[str]:
        out = []
        for f in flows:
            roster = [r.get("subagent") if isinstance(r, dict) else str(r) for r in (f.get("roster") or [])]
            if name in roster:
                out.append(f["name"])
        return out

    master_brain = fabric.agent_brain(cfg, None)
    agents = [{
        "key": MASTER, "name": cfg.get("agent_name") or "Aria", "master": True,
        "soul": " ".join(str(cfg.get("soul") or "").split())[:160],
        "brain": master_brain, "hands": hands_of(cfg.get("agent_profile") or hands.DEFAULT),
        "authority": {"autonomy": cfg.get("autonomy") or "balanced", "allow": 0, "deny": 0,
                      "families": {}, "in_missions": 0},
        "skills": [], "tools": ["*"],
        # the master reaches every specialist with `delegate` and a huddle — that is
        # what makes it the master; a mission's orchestrator reaches only its roster
        "delegates_to": [s["name"] for s in store.list_subagents()],
        "asks": [], "blocked": [], "asked_by": [], "missions": [],
        "links": [{"label": lk["label"], "kind": lk.get("kind"),
                   "mine_may_ask": access[lk["label"]]["mine_may_ask"]} for lk in links],
    }]
    for d in store.list_subagents():
        n = d["name"]
        cells = mx["cells"]
        agents.append({
            "key": n, "name": n, "master": False, "builtin": bool(d.get("builtin")),
            "soul": " ".join(str(d.get("soul") or "").split())[:160],
            "brain": fabric.agent_brain(cfg, d),
            "hands": hands_of(d.get("profile") or hands.DEFAULT),
            "authority": _authority(store, n, d.get("autonomy_cap") or "balanced"),
            "skills": list(d.get("skills") or []), "tools": list(d.get("tools") or []),
            "delegates_to": [],
            "asks": sorted(t for t in mx["agents"] if cells.get(f"{n}>{t}") == "allow"),
            "blocked": sorted(t for t in mx["agents"] if cells.get(f"{n}>{t}") == "deny"),
            "asked_by": sorted(f for f in mx["agents"] if cells.get(f"{f}>{n}") == "allow"),
            "missions": missions_of(n),
            "links": [{"label": lab, "they_may_ask": n in acc["theirs_may_ask"],
                       "standing": sum(1 for x in fabric.standing(store, lab) if x["agent"] == n),
                       "their_missions": [m["mission"] for m in fabric.linked_missions(store, lab)
                                          if n in m["agents"]]}
                      for lab, acc in access.items()],
        })
    return {"agents": agents, "talk": mx["talk"], "profiles": list(profiles.values()),
            "links": [{"label": lk["label"], "kind": lk.get("kind")} for lk in links],
            "missions": [{"name": f["name"], "enabled": bool(f.get("enabled"))} for f in flows]}


def graph(ov: dict) -> dict:
    """Nodes and edges from the overview. Node ids are namespaced (`agent:`, `brain:`,
    `hands:`, `skill:`, `team:`, `mission:`); every edge says what it means."""
    nodes: dict = {}
    edges: list = []

    def node(nid: str, kind: str, label: str, sub: str = "", **extra):
        nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, "sub": sub, **extra})

    for a in ov["agents"]:
        aid = f"agent:{a['key']}"
        node(aid, "agent", a["name"], "lead agent" if a["master"] else (a["soul"][:60] or "specialist"),
             key=a["key"], master=a["master"])
        b = a["brain"]
        bid = f"brain:{b['provider_name']}/{b['short']}"
        node(bid, "brain", b["provider_name"], b["short"])
        edges.append({"from": aid, "to": bid, "kind": "brain",
                      "label": "own brain" if b.get("own") else "machine's brain"})
        hid = f"hands:{a['hands']['name']}"
        node(hid, "hands", a["hands"]["name"], a["hands"]["summary"])
        edges.append({"from": aid, "to": hid, "kind": "hands", "label": "works with"})
        for s in a["skills"]:
            node(f"skill:{s}", "skill", s)
            edges.append({"from": aid, "to": f"skill:{s}", "kind": "skill", "label": "knows"})
        for t in a["delegates_to"]:
            edges.append({"from": aid, "to": f"agent:{t}", "kind": "delegate", "label": "delegates"})
        for t in a["asks"]:
            edges.append({"from": aid, "to": f"agent:{t}", "kind": "talk", "label": "may ask"})
        for t in a["blocked"]:
            edges.append({"from": aid, "to": f"agent:{t}", "kind": "blocked", "label": "may not ask"})
        for m in a["missions"]:
            node(f"mission:{m}", "mission", m, "mission")
            edges.append({"from": f"mission:{m}", "to": aid, "kind": "roster", "label": "on the roster"})
        for lk in a["links"]:
            tid = f"team:{lk['label']}"
            node(tid, "team", lk["label"], "linked team")
            if a["master"] and lk.get("mine_may_ask"):
                edges.append({"from": aid, "to": tid, "kind": "link", "label": "agents here may ask theirs"})
            if lk.get("they_may_ask"):
                edges.append({"from": tid, "to": aid, "kind": "link", "label": "may ask"
                              + (f" · {lk['standing']} standing" if lk.get("standing") else "")})
            for m in lk.get("their_missions") or []:
                edges.append({"from": tid, "to": aid, "kind": "roster", "label": f"their mission {m}"})
    if ov.get("talk") == "swarm":
        names = [a["key"] for a in ov["agents"] if not a["master"]]
        have = {(e["from"], e["to"]) for e in edges if e["kind"] in ("talk", "blocked")}
        for f in names:
            for t in names:
                if f != t and (f"agent:{f}", f"agent:{t}") not in have:
                    edges.append({"from": f"agent:{f}", "to": f"agent:{t}", "kind": "talk",
                                  "label": "may ask (swarm)"})
    return {"nodes": list(nodes.values()), "edges": edges}


def text(ov: dict) -> str:
    """The map as a terminal reads it: one block per agent."""
    out = []
    for a in ov["agents"]:
        b, h, au = a["brain"], a["hands"], a["authority"]
        out.append(f"{'★ ' if a['master'] else '  '}{a['name']}"
                   + ("  (lead agent)" if a["master"] else ""))
        out.append(f"    brain      {b['provider_name']} · {b['short']}"
                   + (f"  — {b['note']}" if b.get("note") else ""))
        out.append(f"    hands      {h['name']} — {h['summary']}")
        fams = ", ".join(f"{k} {v['allow']}✓{(' ' + str(v['deny']) + '✗') if v['deny'] else ''}"
                         for k, v in sorted(au["families"].items()))
        out.append(f"    authority  autonomy {au['autonomy']}"
                   + (f" · {au['allow']} allowed, {au['deny']} refused ({fams})" if au["allow"] or au["deny"] else "")
                   + (f" · {au['in_missions']} more inside missions" if au.get("in_missions") else ""))
        if a["skills"]:
            out.append(f"    skills     {', '.join(a['skills'])}")
        if a["delegates_to"]:
            out.append(f"    delegates  {', '.join(a['delegates_to'])}")
        if a["asks"] or a["blocked"]:
            out.append(f"    may ask    {', '.join(a['asks']) or '-'}"
                       + (f"   (blocked: {', '.join(a['blocked'])})" if a["blocked"] else ""))
        if a["missions"]:
            out.append(f"    missions   {', '.join(a['missions'])}")
        for lk in a["links"]:
            bits = []
            if lk.get("they_may_ask"):
                bits.append("they may ask" + (f", {lk['standing']} standing" if lk.get("standing") else ""))
            if lk.get("their_missions"):
                bits.append("their missions: " + ", ".join(lk["their_missions"]))
            if a["master"] and lk.get("mine_may_ask"):
                bits.append("your agents ask theirs freely")
            if bits:
                out.append(f"    {lk['label']:<10} {'; '.join(bits)}")
        out.append("")
    out.append(f"agents talk: {ov['talk']}")
    return "\n".join(out)
