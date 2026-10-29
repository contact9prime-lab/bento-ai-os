"""The logical map of this hub, and what each tie is given: one computation for every face.

Asked for as "Aria controls a lot of companies, and different companies have different personas
and departments; the Zeros or the teams can talk to either Aria, which controls all the
departments, or to each department only … when I look into the topology of the company and the
network it should be like that. That is the logical topology. The physical topology is the
devices the hub is connected to", and "show the users what all they have given it access to".

  * `logical(cfg, store)` is the tree: the lead at the top, every company the person keeps (the
    open one and the parked ones), each company's departments, each department's people, and the
    agents in no department under "Default company". Every agent carries its brain, its hands,
    its tools and its permissions (agentmap.overview, never a second reading), and every tie
    (a Zero or a linked team) hangs from what it talks to (ties.target_of).
  * `access(cfg, store, lk)` is what one tie is given here, in words: who answers it, what that
    one can reach, which of your agents it may also ask directly, and the standing permissions
    written for it. Talking to the lead is the wide one, and its caution says so.

Free of HTTP and asyncio: `bento network map` prints the same tree with the server down.
"""
from __future__ import annotations

DEFAULT_COMPANY = "Default company"


def _agents(store, cfg: dict) -> dict:
    from . import agentmap
    try:
        ov = agentmap.overview(store, cfg)
    except Exception:
        ov = {"agents": []}
    return {a["key"]: a for a in ov.get("agents") or []}


def _person(a: dict | None, name: str) -> dict:
    a = a or {}
    auth = a.get("authority") or {}
    brain = a.get("brain") or {}
    return {"name": name, "tools": list(a.get("tools") or []), "skills": list(a.get("skills") or []),
            "hands": (a.get("hands") or {}).get("name") or "default",
            "hands_summary": (a.get("hands") or {}).get("summary") or "",
            "brain": brain.get("model") or brain.get("provider_name") or "",
            "autonomy": auth.get("autonomy") or "",
            "allow": int(auth.get("allow") or 0), "deny": int(auth.get("deny") or 0),
            "families": auth.get("families") or {}, "missions": list(a.get("missions") or [])}


def logical(cfg: dict, store, ties: list[dict] | None = None) -> dict:
    """The tree, top down. `ties` are ties.ties() rows (their `talks_to` places them)."""
    from . import company as companymod
    cfg = cfg or {}
    by = _agents(store, cfg)
    lead_key = next((k for k, a in by.items() if a.get("master")), "")
    lead = {**_person(by.get(lead_key), cfg.get("agent_name") or "Aria"), "lead": True}
    placed: set = set()
    companies = []
    for co in companymod.companies(cfg):
        ccfg = companymod.cfg_of(cfg, co["id"]) if co["id"] or co["active"] else None
        if ccfg is None:
            continue
        depts = []
        for d in companymod.departments(ccfg, store):
            people = []
            for m in d["members"]:
                placed.add(m.lower())
                people.append({**_person(by.get(m), m), "head": m == d.get("lead") and d.get("named")})
            depts.append({"name": d["name"], "color": d.get("color") or "", "about": d.get("about") or "",
                          "head": d.get("lead") or "", "desk": d.get("desk") or "", "people": people})
        pr = companymod.profile(ccfg)
        companies.append({"id": co["id"], "name": co["name"], "about": pr.get("about") or "",
                          "open": co["active"], "departments": depts})
    # the auditor checks every department's work from outside them all: it stands with the
    # companies, never as somebody's stray agent
    auditor = str(getattr(companymod, "AUDITOR", "auditor") or "auditor").lower()
    for c in companies:
        if auditor in {k.lower() for k in by}:
            c["auditor"] = _person(by.get(next(k for k in by if k.lower() == auditor)), auditor)
    loose = [_person(a, a["name"]) for k, a in by.items()
             if not a.get("master") and a["name"].lower() not in placed and a["name"].lower() != auditor]
    if loose or not companies:
        companies.append({"id": "", "name": DEFAULT_COMPANY, "about": "", "open": not companies,
                          "default": True, "departments": [],
                          "people": loose})
    for t in ties or []:
        # a link left over from a reinstall reaches nothing: the device map leaves it off, so does this
        if t.get("stale"):
            continue
        tt = t.get("talks_to") or {"to": "lead"}
        ag = t.get("agent") if isinstance(t.get("agent"), dict) else {}
        # named for the machine: a link's label grows -2, -3 with each reinstall, and every
        # Zero's agent starts out as Aria, so neither tells two Pis apart
        node = {"label": t.get("label"), "kind": t.get("kind"), "peer": t.get("peer"),
                "name": t.get("peer") or t.get("label"), "agent": ag.get("name") or "",
                "answering": t.get("answering"), "stale": False}
        if tt.get("to") == "department":
            for c in companies:
                if (c["id"] or "") != (tt.get("company") or "") and not (c.get("open") and not tt.get("company")):
                    continue
                d = next((x for x in c["departments"] if x["name"].lower() == str(tt["department"]).lower()), None)
                if d is not None:
                    d.setdefault("ties", []).append(node)
                    break
            else:
                lead.setdefault("ties", []).append({**node, "missing": tt.get("department")})
        else:
            lead.setdefault("ties", []).append(node)
    return {"lead": lead, "companies": companies}


def _grant_words(g: dict) -> str:
    who = str(g.get("principal_id") or "")
    res = str(g.get("resource") or "")
    return f"{g.get('effect')} {g.get('action')} on {res}" + (f" ({who})" if who and not who.endswith("/*") else "")


def access(cfg: dict, store, lk: dict) -> dict:
    """What one tie is given here, read from what decides it: who answers, what they reach, the
    cells, and the grant rows that name the link."""
    from . import company as companymod
    from . import fabric
    from . import ties as tiesmod
    from . import zero as zeromod
    cfg = cfg or {}
    t = tiesmod.target_of(lk)
    label = lk.get("label") or ""
    by = _agents(store, cfg)
    lead_name = cfg.get("agent_name") or "Aria"
    zero = zeromod.ships_to(lk)
    out = {"talks_to": t, "words": tiesmod.target_words(cfg, t), "caution": "", "reach": [],
           "tools": [], "asks": [], "grants": []}
    if t["to"] == "department":
        ccfg = companymod.cfg_of(cfg, t.get("company") or "")
        d = next((x for x in (companymod.departments(ccfg, store) if ccfg is not None else [])
                  if x["name"].lower() == t["department"].lower()), None)
        if d is None:
            out["caution"] = (f"{t['department']} is no longer a department here, so every question from "
                              f"{label} is refused until you choose again.")
        else:
            out["reach"] = [_person(by.get(m), m) for m in d["members"]]
            out["tools"] = sorted({x for p in out["reach"] for x in p["tools"]})
            out["persona"] = companymod.profile(ccfg).get("about") or ""
    else:
        from . import executors as execmod
        tools = list(fabric.ZERO_CHAT_TOOLS if zero else execmod.LINKED_LEAD_TOOLS)
        out["tools"] = tools
        # the auditor is on no roster: the lead cannot hand it work (company.normalize)
        auditor = str(getattr(companymod, "AUDITOR", "auditor")).lower()
        people = [_person(a, a["name"]) for a in by.values() if not a.get("master") and a["name"].lower() != auditor]
        out["reach"] = people
        n_depts = sum(len(companymod.departments_of(cfg, store, c["id"])) for c in companymod.companies(cfg))
        out["caution"] = (f"{lead_name} answers {label}, and {lead_name} can hand its work to every one of your "
                          f"{len(people)} agents" + (f" in {n_depts} departments" if n_depts else "")
                          + f", using {', '.join(tools)}. To keep {label} to one part of your company, "
                          f"have it talk to a department.")
    acc = fabric.link_access(store, label)
    out["asks"] = [lead_name if x == fabric.LEAD else x for x in acc["theirs_may_ask"]]
    rows = [g for g in store.list_grants(principal_kind="team")
            if str(g.get("principal_id") or "").split("/", 1)[0] == label]
    out["grants"] = [{"action": g.get("action"), "resource": g.get("resource"), "effect": g.get("effect"),
                      "source": g.get("source") or "", "words": _grant_words(g)} for g in rows]
    return out


def text(tree: dict) -> str:
    """The tree for a terminal."""
    lines = []
    lead = tree["lead"]

    def tie_line(x, pad):
        name = x.get("name") or x["label"]
        return (f"{pad}⇠ {name} ({x.get('kind')}" + (f", agent {x['agent']}" if x.get("agent") else "")
                + (f", link {x['label']}" if x["label"] != name else "") + ")") + (f"  · {x['missing']} is gone" if x.get("missing") else "")
    lines.append(f"{lead['name']} (lead)")
    for x in lead.get("ties") or []:
        lines.append(tie_line(x, "  "))
    for c in tree["companies"]:
        lines.append(f"  ▦ {c['name']}" + (" (open)" if c.get("open") and not c.get("default") else ""))
        for d in c["departments"]:
            lines.append(f"    ▸ {d['name']}" + (f", head {d['head']}" if d.get("head") else ""))
            for x in d.get("ties") or []:
                lines.append(tie_line(x, "      "))
            for p in d["people"]:
                lines.append(f"      · {p['name']}  [{p['hands']}]  {', '.join(p['tools'][:6]) or 'no tools'}")
        for p in c.get("people") or []:
            lines.append(f"    · {p['name']}  [{p['hands']}]  {', '.join(p['tools'][:6]) or 'no tools'}")
    return "\n".join(lines)
