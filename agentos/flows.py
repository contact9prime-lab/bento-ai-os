"""Flows: standing missions, their permissions, and what starts them.

A flow is the definition; `fabric.ControlPlane.run_flow` is the execution. This module
holds neither — it turns a definition into the two things the rest of the OS enforces:

  - GRANTS. What a flow may do is declared when it is defined, and materialised as real
    `grants` rows (source='definition'). There is no second permission system: the PDP
    that gates the main agent gates a flow's roster too, reading the same table the
    Permissions app shows. Re-saving a definition reconciles only the rows that
    definition wrote — a grant a person added by hand, or tapped "Always" on, is
    source='user' and is never touched.

  - TRIGGERS. What starts a flow is declared the same way. Cron and OS-event triggers
    materialise a real `tasks` row, because the scheduler already owns due-polling,
    claim-on-fire, cooldowns and the file/idle/notification/login pollers; a second
    implementation of any of that is a second set of bugs. Message and webhook triggers
    have no time dimension and are dispatched where the message or the request arrives.

Everything here is deliberately pure or store-only: no HTTP, no asyncio, no agent. That
is what lets the UI ask "what would saving this grant?" before anything is written.
"""

import json
import os
import re
import secrets
import time

TRIGGER_KINDS = ("cron", "message", "webhook", "os_event")
OS_EVENTS = ("notification", "file_change", "login", "idle")
CRON_TYPES = ("interval", "daily", "once")
SINK_KINDS = ("origin", "telegram", "gui", "notify", "report", "conversation")
MEMORY_SCOPES = ("none", "read", "read-space", "read-write")

DEFINITION_SOURCE = "definition"


def source_ref(flow_name: str) -> str:
    return f"flow:{flow_name}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,48}$")


def validate(body: dict, store=None, pending: set | None = None) -> dict:
    """Normalise an incoming definition, or raise ValueError with a sentence a human can
    act on. Roster members are checked against the store because a flow whose roster
    names a subagent that does not exist is a flow that will fail at its first
    delegation, and it should fail at Save instead.

    `pending` names agents this definition is about to create (see `ensure_agents`), so a
    draft can be previewed before its specialists exist without the check going soft."""
    pending = pending or {a.get("name") for a in (body.get("new_agents") or [])
                          if isinstance(a, dict)}
    name = (body.get("name") or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError("a flow name is 1-49 characters of letters, digits, '-' or '_'")
    mission = (body.get("mission") or "").strip()
    if not mission:
        raise ValueError("a flow needs a mission — what it is for, in your own words")
    roster = []
    for item in (body.get("roster") or []):
        if isinstance(item, str):
            item = {"subagent": item}
        sub = (item.get("subagent") or "").strip()
        if not sub:
            continue
        if store is not None and sub not in pending and not store.get_subagent(sub):
            raise ValueError(f"no subagent named '{sub}' — create it in Workflows → Agents first")
        roster.append({"subagent": sub, "why": (item.get("why") or "").strip()[:200]})
    if not roster:
        raise ValueError("a flow needs at least one agent on its roster — the master "
                         "orchestrates, it does not do the work itself")
    sinks = []
    for s in (body.get("sinks") or []):
        if isinstance(s, str):
            s = {"kind": s}
        kind = (s.get("kind") or "").strip()
        if kind not in SINK_KINDS:
            raise ValueError(f"unknown delivery sink '{kind}' — one of {', '.join(SINK_KINDS)}")
        sinks.append({k: v for k, v in s.items() if k in ("kind", "chat_id", "id", "to_telegram")})
    perms = body.get("permissions") or {}
    if not isinstance(perms, dict):
        raise ValueError("permissions must be an object")
    mem = str(perms.get("memory") or "read-space")
    if mem not in MEMORY_SCOPES:
        raise ValueError(f"memory must be one of {', '.join(MEMORY_SCOPES)}")
    perms = {**perms, "memory": mem}
    return {
        "name": name,
        "description": (body.get("description") or "").strip()[:500],
        "mission": mission,
        "roster": roster,
        "model": (body.get("model") or "").strip(),
        "permissions": perms,
        "sinks": sinks,
        "autonomy_cap": body.get("autonomy_cap") or "balanced",
        "max_delegations": max(1, int(body.get("max_delegations") or 12)),
        "max_steps": max(2, int(body.get("max_steps") or 24)),
        "max_seconds": max(30, int(body.get("max_seconds") or 1800)),
        "space_id": body.get("space_id") or "",
        "enabled": int(bool(body.get("enabled", 1))),
        "builtin": int(body.get("builtin") or 0),
        # which jobs.py recipe this came out of, '' when it was written by hand. Carried
        # rather than dropped, so re-saving a job from the editor does not orphan it.
        "job": re.sub(r"[^a-z0-9-]", "", str(body.get("job") or "").lower())[:48],
        "triggers": [_validate_trigger(t) for t in (body.get("triggers") or [])],
        "new_agents": [a for a in (body.get("new_agents") or []) if isinstance(a, dict)],
    }


def _at_time(v) -> str:
    """A time of day as 'HH:MM', from whatever was written.

    `_next_daily` splits on ':' and silently falls back to 09:00 when that fails, so `730`
    or `7.30` would become a job that runs at the wrong time and never says why. Anything
    unreadable is refused here instead, where there is somebody to tell."""
    s = str(v if v is not None else "").strip()
    if not s:
        return "08:00"
    m = re.fullmatch(r"(\d{1,2})\s*[:.h]\s*(\d{2})", s) or re.fullmatch(r"(\d{1,2})(\d{2})", s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
    elif re.fullmatch(r"\d{1,2}", s):
        hh, mm = int(s), 0
    else:
        raise ValueError(f"'{v}' is not a time of day — write it as HH:MM, e.g. 08:00")
    if hh > 23 or mm > 59:
        raise ValueError(f"'{v}' is not a time of day — write it as HH:MM, e.g. 08:00")
    return f"{hh:02d}:{mm:02d}"


def _validate_trigger(t: dict) -> dict:
    kind = (t.get("kind") or "").strip()
    if kind not in TRIGGER_KINDS:
        raise ValueError(f"trigger kind must be one of {', '.join(TRIGGER_KINDS)}")
    conf = dict(t.get("config") or {})
    if kind == "cron":
        ctype = conf.get("type") or "daily"
        if ctype not in CRON_TYPES:
            raise ValueError(f"a cron trigger's type is one of {', '.join(CRON_TYPES)}")
        conf["type"] = ctype
        if ctype == "daily":
            conf["at"] = _at_time(conf.get("at"))
        elif ctype == "interval":
            conf["minutes"] = max(1, int(conf.get("minutes") or 60))
        else:
            conf["delay_minutes"] = max(0, int(conf.get("delay_minutes") or 0))
    elif kind == "message":
        if not str(conf.get("pattern") or "").strip():
            raise ValueError("a message trigger needs a pattern to match")
        mode = conf.get("mode") or "prefix"
        if mode not in ("prefix", "substring", "regex"):
            raise ValueError("a message trigger's mode is prefix, substring or regex")
        if mode == "regex":
            try:
                re.compile(conf["pattern"])
            except re.error as e:
                raise ValueError(f"that regex does not compile: {e}") from None
        conf["mode"] = mode
        conf["surfaces"] = [s for s in (conf.get("surfaces") or []) if s] or ["telegram", "gui"]
    elif kind == "os_event":
        ev = conf.get("event")
        if ev not in OS_EVENTS:
            raise ValueError(f"an OS event is one of {', '.join(OS_EVENTS)}")
        if ev == "notification" and not str(conf.get("match") or "").strip():
            raise ValueError("a notification trigger needs `match`")
        if ev == "file_change" and not str(conf.get("path") or "").strip():
            raise ValueError("a file_change trigger needs `path`")
    return {"kind": kind, "config": conf,
            "cooldown_secs": max(0, int(t.get("cooldown_secs") or 60)),
            "enabled": int(bool(t.get("enabled", 1))),
            "rotate": bool(t.get("rotate"))}


# ---------------------------------------------------------------------------
# Permissions: a definition, expressed as grants
# ---------------------------------------------------------------------------

def declared_grants(flow: dict) -> list[dict]:
    """The exact grant rows this definition implies.

    Pure — no database. That is what lets the UI show "saving this will grant …" before
    a single row is written, and what makes the reconciler testable without a server.
    """
    name = flow.get("name") or ""
    perms = flow.get("permissions") or {}
    surfaces = str(perms.get("surfaces") or "*") or "*"
    roster = [r["subagent"] if isinstance(r, dict) else str(r) for r in (flow.get("roster") or [])]
    out: list[dict] = []

    def add(kind, pid, action, resource, effect="allow", note=""):
        out.append({"principal_kind": kind, "principal_id": pid, "action": action,
                    "resource": resource, "effect": effect, "surfaces": surfaces,
                    "note": note[:300]})

    # 1. the flow's own roster: the only thing that satisfies the `roster` deny default
    for sub in roster:
        add("flow", name, "agent.invoke", f"agent:subagent/{sub}",
            note=f"on the roster of the '{name}' flow")

    # 2. what the roster may do. The flow declares once; every member gets the same
    #    envelope, because "who may fetch" is a property of the mission, not of which
    #    specialist happens to be holding it.
    for sub in roster:
        for tool in (perms.get("tools") or []):
            add("subagent", sub, "tool.use", f"tool:{tool}*", note=f"granted by flow '{name}'")
        for m in (perms.get("mcp") or []):
            add("subagent", sub, "mcp.use", f"mcp:{m}", note=f"granted by flow '{name}'")
        for sk in (perms.get("skills") or []):
            add("subagent", sub, "skill.use", f"skill:{sk}", note=f"granted by flow '{name}'")
        for url in (perms.get("net") or []):
            add("subagent", sub, "net.fetch", f"net:{url}", note=f"granted by flow '{name}'")
        for p in (perms.get("fs_read") or []):
            add("subagent", sub, "fs.read", f"fs:{os.path.expanduser(p)}",
                note=f"granted by flow '{name}'")
        for p in (perms.get("fs_write") or []):
            add("subagent", sub, "fs.write", f"fs:{os.path.expanduser(p)}",
                note=f"granted by flow '{name}'")
        for m in (perms.get("models_deny") or []):
            add("subagent", sub, "model.use", f"model:{m}", effect="deny",
                note=f"denied by flow '{name}'")
        # memory is a scope, not a list: it says how far into the user's world a
        # specialist working on this mission may reach
        mem = perms.get("memory") or "read-space"
        if mem == "none":
            add("subagent", sub, "memory.read", "memory:*", effect="deny",
                note=f"flow '{name}' runs without memory")
            add("subagent", sub, "kg.read", "kg:*", effect="deny",
                note=f"flow '{name}' runs without memory")
        if mem in ("none", "read", "read-space"):
            add("subagent", sub, "memory.write", "memory:*", effect="deny",
                note=f"flow '{name}' may read memory but not write it")
            add("subagent", sub, "kg.write", "kg:*", effect="deny",
                note=f"flow '{name}' may read facts but not write them")
    return out


def reconcile_grants(store, flow: dict) -> dict:
    """Regenerate a definition's grants, leaving everything a human wrote alone.

    The filter is `source='definition' AND source_ref='flow:<name>'`. A grant the user
    wrote by hand, or tapped "Always" on, is source='user' and is never in this set —
    which is the whole point: editing a flow must not quietly undo a permission somebody
    deliberately gave it.

    A DISABLED flow holds nothing. Permissions exist so that a flow can act; one that
    cannot run has no business keeping standing access to anything, and a drafted flow
    waiting to be looked at must not have granted itself tools in the meantime. Enabling
    is what grants; disabling is what takes it back.
    """
    ref = source_ref(flow["name"])
    want = declared_grants(flow) if flow.get("enabled") else []
    have = [g for g in store.list_grants()
            if g.get("source") == DEFINITION_SOURCE and (g.get("source_ref") or "") == ref]

    def key(g):
        return (g["principal_kind"], g["principal_id"], g["action"], g["resource"],
                g.get("effect") or "allow", (g.get("surfaces") or "*"))

    wk = {key(w): w for w in want}
    hk = {key(h): h for h in have}
    revoked = sum(1 for k, h in hk.items() if k not in wk and store.revoke_grant(h["id"]))
    added = 0
    for k, w in wk.items():
        if k not in hk:
            store.add_grant(w["principal_kind"], w["principal_id"], w["action"], w["resource"],
                            effect=w.get("effect", "allow"), source=DEFINITION_SOURCE,
                            note=w.get("note", ""), surfaces=w.get("surfaces", "*"),
                            source_ref=ref)
            added += 1
    return {"added": added, "revoked": revoked, "kept": len(set(wk) & set(hk))}


def revoke_definition_grants(store, flow_name: str) -> int:
    """Everything a deleted flow was granted goes with it. Grants outlive the thing that
    asked for them otherwise, and an orphaned allow is the kind of permission nobody ever
    goes looking for."""
    ref = source_ref(flow_name)
    n = 0
    for g in store.list_grants():
        if g.get("source") == DEFINITION_SOURCE and (g.get("source_ref") or "") == ref:
            n += int(bool(store.revoke_grant(g["id"])))
    return n


# ---------------------------------------------------------------------------
# Triggers: a definition, expressed as rows the rest of the OS already polls
# ---------------------------------------------------------------------------

def _canonical(kind: str, config: dict) -> str:
    """What makes two triggers 'the same one' across a save. Deliberately not the whole
    config: a webhook's secret and a cooldown may change without the trigger becoming a
    different trigger — otherwise every edit would mint a new URL."""
    c = config or {}
    if kind == "cron":
        return f"cron:{c.get('type')}:{c.get('at') or c.get('minutes') or c.get('delay_minutes')}"
    if kind == "message":
        return f"message:{c.get('mode')}:{c.get('pattern')}"
    if kind == "os_event":
        return (f"os_event:{c.get('event')}:{c.get('match') or c.get('path') or ''}"
                f"{c.get('glob') or ''}{c.get('minutes') or ''}")
    return "webhook"


def _task_fields(flow: dict, trig: dict) -> dict | None:
    """The `tasks` row a trigger needs, or None when it needs none."""
    kind, conf = trig["kind"], trig["config"]
    now = time.time()
    prompt = flow.get("mission") or ""
    common = {"prompt": prompt, "flow": flow["name"], "space_id": flow.get("space_id") or "",
              "cooldown_secs": trig.get("cooldown_secs", 60)}
    if kind == "cron":
        ctype = conf.get("type") or "daily"
        if ctype == "interval":
            secs = max(60, int(conf.get("minutes", 60)) * 60)
            return {**common, "schedule_type": "interval", "interval_seconds": secs,
                    "at_time": None, "next_run": now + secs}
        if ctype == "daily":
            from .scheduler import _next_daily
            at = conf.get("at") or "08:00"
            return {**common, "schedule_type": "daily", "interval_seconds": None,
                    "at_time": at, "next_run": _next_daily(at, now)}
        return {**common, "schedule_type": "once", "interval_seconds": None, "at_time": None,
                "next_run": now + max(0, int(conf.get("delay_minutes", 0))) * 60}
    if kind == "os_event":
        ev = conf.get("event")
        tconf = {k: v for k, v in conf.items() if k in ("match", "path", "glob", "minutes")}
        return {**common, "schedule_type": "trigger", "interval_seconds": None, "at_time": None,
                "next_run": None, "trigger": ev, "trigger_config": tconf}
    return None  # message / webhook: nothing polls a clock for these


def reconcile_triggers(store, flow: dict, triggers: list[dict]) -> dict:
    """Same algorithm as the grants, over `flow_triggers` — keyed on what makes a trigger
    that trigger, so a save that only changes a cooldown keeps the row (and, for a
    webhook, its secret: rotating on every save would break every caller).

    A disabled flow keeps its trigger DECLARATIONS but none of them are armed: the rows
    stay so enabling restores exactly what you wrote, and the `tasks` rows that make a
    clock tick are removed. The declaration is what you meant; the task row is what fires.
    """
    import json as _json
    live = bool(flow.get("enabled"))
    have = {(_canonical(t["kind"], t["config"])): t for t in store.flow_triggers(flow["name"])}
    want = {(_canonical(t["kind"], t["config"])): t for t in triggers}
    added = removed = updated = 0
    for k, old in have.items():
        if k not in want:
            if old.get("task_id"):
                store.delete_task(old["task_id"])
            store.delete_flow_trigger(old["id"])
            removed += 1
    for k, t in want.items():
        old = have.get(k)
        fields = _task_fields(flow, t) if live else None
        if old:
            upd = {"config": t["config"], "cooldown_secs": t["cooldown_secs"],
                   "enabled": int(bool(t["enabled"])) if live else 0}
            if t["kind"] == "webhook" and (t.get("rotate") or not old.get("secret")):
                upd["secret"] = secrets.token_urlsafe(24)
            if not live and old.get("task_id"):
                store.delete_task(old["task_id"])       # disarm the clock, keep the words
                upd["task_id"] = ""
            store.update_flow_trigger(old["id"], **upd)
            if fields and old.get("task_id"):
                tf = dict(fields)
                if "trigger_config" in tf:
                    tf["trigger_config"] = _json.dumps(tf["trigger_config"])
                tf["enabled"] = t["enabled"]
                store.update_task(old["task_id"], **tf)
            elif fields and not old.get("task_id"):
                store.update_flow_trigger(old["id"],
                                          task_id=_new_task(store, fields, _json))
            updated += 1
            continue
        task_id = _new_task(store, fields, _json) if fields else ""
        store.add_flow_trigger(flow["name"], t["kind"], t["config"], task_id=task_id,
                               secret=secrets.token_urlsafe(24) if t["kind"] == "webhook" else "",
                               cooldown_secs=t["cooldown_secs"],
                               enabled=int(bool(t["enabled"])) if live else 0)
        added += 1
    return {"added": added, "removed": removed, "updated": updated, "armed": live}


def _new_task(store, fields: dict, _json) -> str:
    tf = dict(fields)
    return store.add_task(
        tf.pop("prompt"), tf.pop("schedule_type"), tf.pop("interval_seconds"),
        tf.pop("at_time"), tf.pop("next_run"), trigger=tf.pop("trigger", ""),
        trigger_config=_json.dumps(tf.pop("trigger_config", {})),
        cooldown_secs=tf.pop("cooldown_secs"), flow=tf.pop("flow"),
        space_id=tf.pop("space_id"))


def delete_triggers(store, flow_name: str) -> int:
    n = 0
    for t in store.flow_triggers(flow_name):
        if t.get("task_id"):
            store.delete_task(t["task_id"])
        store.delete_flow_trigger(t["id"])
        n += 1
    return n


# ---------------------------------------------------------------------------
# The one save path — used by the API route, the CLI and the seeder
# ---------------------------------------------------------------------------

def ensure_agents(store, specs: list) -> list[str]:
    """Create the roster members a definition asks for and that do not exist yet.

    A flow and the specialists it needs are one thought, so they are one save: making
    somebody leave the editor, create three subagents, and come back to re-pick them is
    how a good idea becomes a chore. An existing name is never overwritten — a flow
    saying "I need a researcher" must not silently rewrite the researcher you already
    have and every other flow that uses it.
    """
    created = []
    for spec in specs or []:
        if isinstance(spec, str):
            spec = {"name": spec}
        name = (spec.get("name") or "").strip()
        if not _NAME_RE.match(name) or store.get_subagent(name):
            continue
        store.save_subagent({
            "name": name,
            "soul": (spec.get("soul") or "").strip(),
            "model": (spec.get("model") or "").strip(),
            "tools": [str(t) for t in (spec.get("tools") or [])],
            "skills": [str(s) for s in (spec.get("skills") or [])],
            "autonomy_cap": spec.get("autonomy_cap") or "balanced",
            "max_steps": int(spec.get("max_steps") or 12),
            "max_seconds": int(spec.get("max_seconds") or 300),
        })
        created.append(name)
    return created


def save(store, body: dict) -> tuple[dict, dict]:
    """Validate → persist → reconcile grants and triggers. Returns (flow, report).

    One path, so the permissions a flow has can never depend on which door it was
    created through."""
    created = ensure_agents(store, body.get("new_agents") or [])
    d = validate(body, store)
    triggers = d.pop("triggers")
    d.pop("new_agents", None)      # they exist now; the flow row does not record them
    store.save_flow(d)
    flow = store.get_flow(d["name"])
    report = {"grants": reconcile_grants(store, flow),
              "triggers": reconcile_triggers(store, flow, triggers),
              "agents_created": created}
    try:
        store.log("policy", f"flow '{flow['name']}' saved: "
                            f"{report['grants']['added']} grants added, "
                            f"{report['grants']['revoked']} revoked, "
                            f"{report['triggers']['added']} triggers added"
                            + (f", agents created: {', '.join(created)}" if created else ""),
                  {"flow": flow["name"], **report})
    except Exception:
        pass
    return flow, report


def set_enabled(store, flow_name: str, on: bool) -> tuple[dict, dict]:
    """Turn a flow on or off. This is where permissions are granted and taken back, and
    where triggers are armed and disarmed — see `reconcile_grants`."""
    flow = store.get_flow(flow_name)
    if not flow:
        raise ValueError(f"no flow '{flow_name}'")
    triggers = [_validate_trigger({"kind": t["kind"], "config": t["config"],
                                   "cooldown_secs": t["cooldown_secs"], "enabled": 1})
                for t in store.flow_triggers(flow_name)]
    flow["enabled"] = 1 if on else 0
    if on:
        flow["draft"] = {}      # once you have enabled it, it is yours, not a draft
    store.save_flow(flow)
    flow = store.get_flow(flow_name)
    report = {"grants": reconcile_grants(store, flow),
              "triggers": reconcile_triggers(store, flow, triggers)}
    store.log("policy", f"flow '{flow_name}' {'enabled' if on else 'disabled'}: "
                        f"{report['grants']['added']} granted, "
                        f"{report['grants']['revoked']} revoked",
              {"flow": flow_name, **report})
    return flow, report


def save_draft(store, draft: dict) -> tuple[dict, dict]:
    """Persist a composed draft as a DISABLED flow, so it shows up as a real card you can
    read rather than a modal you have to answer.

    Disabled means it holds no permissions and no armed trigger, so a draft sitting in the
    list is inert — which is what makes it safe to create one without asking first.
    """
    body = {k: v for k, v in draft.items()
            if k not in ("grants", "warnings", "model", "notes", "request", "new_agents")}
    body["enabled"] = 0
    body["new_agents"] = draft.get("new_agents") or []
    name = (body.get("name") or "").strip()
    if name and store.get_flow(name):
        body["name"] = _unique_name(store, name)
    flow, report = save(store, body)
    # provenance, kept on the row: which model, what it assumed, what it dropped, and the
    # agents that came with it (so Discard can take them away again)
    flow["draft"] = {"model": draft.get("model", ""), "notes": draft.get("notes", ""),
                     "warnings": draft.get("warnings") or [],
                     "request": draft.get("request", ""),
                     "agents_created": report.get("agents_created") or []}
    store.save_flow(flow)
    return store.get_flow(flow["name"]), report


def _unique_name(store, name: str) -> str:
    for n in range(2, 50):
        candidate = f"{name}-{n}"
        if not store.get_flow(candidate):
            return candidate
    return f"{name}-{secrets.token_hex(3)}"


def discard(store, flow_name: str) -> dict:
    """Throw a draft away, including the agents it brought with it — but only those that
    nothing else is using. An agent you have since put on another flow's roster stays."""
    flow = store.get_flow(flow_name)
    if not flow:
        return {"ok": False}
    mine = set((flow.get("draft") or {}).get("agents_created") or [])
    used = {r["subagent"] for f in store.list_flows() if f["name"] != flow_name
            for r in (f.get("roster") or [])}
    res = delete(store, flow_name)
    removed = []
    for nm in sorted(mine - used):
        defn = store.get_subagent(nm)
        if defn and not defn.get("builtin"):
            store.delete_subagent(defn["id"])
            removed.append(nm)
    res["agents_removed"] = removed
    return res


def delete(store, flow_name: str) -> dict:
    flow = store.get_flow(flow_name)
    if not flow:
        return {"ok": False}
    n_t = delete_triggers(store, flow_name)
    n_g = revoke_definition_grants(store, flow_name)
    store.delete_flow(flow["id"])
    try:
        store.log("policy", f"flow '{flow_name}' deleted: {n_g} grants revoked, "
                            f"{n_t} triggers removed", {"flow": flow_name})
    except Exception:
        pass
    return {"ok": True, "grants_revoked": n_g, "triggers_removed": n_t}


# ---------------------------------------------------------------------------
# Message triggers
# ---------------------------------------------------------------------------

def match_message(store, text: str, surface: str = "") -> tuple[dict, dict] | None:
    """(trigger, flow) for the first enabled message trigger this text matches, or None.

    Cooldowns are checked here rather than at dispatch, so a chat that repeats itself
    cannot start ten runs — and the refusal is counted, not silently dropped."""
    text = (text or "").strip()
    if not text:
        return None
    now = time.time()
    for t in store.flow_triggers(kind="message", enabled_only=True):
        conf = t.get("config") or {}
        surfaces = conf.get("surfaces") or []
        if surface and surfaces and surface not in surfaces:
            continue
        pat, mode = str(conf.get("pattern") or ""), conf.get("mode") or "prefix"
        if not pat:
            continue
        hit = False
        if mode == "prefix":
            hit = text.lower().startswith(pat.lower())
        elif mode == "substring":
            hit = pat.lower() in text.lower()
        else:
            try:
                hit = bool(re.search(pat, text, re.I))
            except re.error:
                hit = False
        if not hit:
            continue
        flow = store.get_flow(t["flow"])
        if not flow or not flow.get("enabled"):
            continue
        if now - (t.get("last_fired") or 0) < (t.get("cooldown_secs") or 0):
            store.flow_trigger_fired(t["id"], dropped=True)
            continue
        store.flow_trigger_fired(t["id"])
        return t, flow
    return None


# ---------------------------------------------------------------------------
# Composing a flow from a sentence
# ---------------------------------------------------------------------------

COMPOSE_PROMPT = """You design FLOWS for AgentOS, an agent operating system.

A flow is a standing mission. A master orchestrator is given the mission and picks which
specialists to use, and in what order, WHILE IT RUNS — so you do not write steps. You write
the mission, the roster it may call on, exactly what that roster is allowed to touch, and
what starts it.

{intent}

WHAT THIS MACHINE ALREADY HAS

Existing agents (reuse these by name wherever one fits — do not invent a near-duplicate):
{agents}

Tools the roster may be granted (use these names EXACTLY; anything not listed does not exist):
{tools}

Installed skills:
{skills}

RULES
- The master orchestrates and has no tools that act. All real work is delegated, so a flow
  needs at least one agent on its roster.
- Grant the FEWEST permissions that let the mission succeed. Every tool you list is a
  standing permission the user is being asked to approve. If the mission only reads and
  reports, do not grant anything that writes.
- `memory` is one of: none | read | read-space | read-write. Prefer "read-space".
- Only create a new agent when no existing one fits. A new agent needs a `soul` written in
  the second person that says what it does and how ("You research. Gather real information,
  verify it, return a dense sourced summary.").
- Triggers: cron {{"type":"daily","at":"HH:MM"}} or {{"type":"interval","minutes":N}};
  message {{"pattern":"...","mode":"prefix|substring|regex"}}; webhook {{}};
  os_event {{"event":"notification|file_change|login|idle", ...}}.
  Add a trigger ONLY if the user asked for one. A flow with no trigger runs when they say so.
- Sinks: origin (answer wherever it was triggered from — the usual choice), telegram, gui,
  notify, report.
- If the request is vague, choose the smallest thing that is unmistakably useful and say what
  you assumed in `notes`. Do not ask questions; there is nobody to answer them.

- `roster` and `permissions.tools` must NOT be empty. Naming an agent in the mission text is
  not the same as putting it on the roster: the mission is prose the orchestrator reads, the
  roster is what it is actually allowed to call. Same for tools — a tool mentioned in the
  mission but missing from `permissions.tools` is a tool the agent will be denied.

WORKED EXAMPLE — for "watch my downloads folder and file anything that looks like an invoice":

{{"name": "invoice-filer",
 "description": "Files invoices that land in Downloads.",
 "mission": "When a new file appears in ~/Downloads, decide whether it is an invoice. If it is, read it, extract the supplier, date and amount, and file a one-line summary. If it is not, do nothing and finish saying so.",
 "new_agents": [{{"name": "filer", "soul": "You sort documents. Read what you are given, decide what it is, and return a single structured line: supplier, date, amount. Say 'not an invoice' rather than guessing.", "tools": ["read_file", "list_dir"], "max_steps": 8, "max_seconds": 240}}],
 "roster": [{{"subagent": "filer", "why": "reads the file and decides what it is"}}],
 "permissions": {{"tools": ["read_file", "list_dir"], "skills": [], "net": [], "fs_read": ["~/Downloads/*"], "fs_write": [], "memory": "read-space"}},
 "sinks": [{{"kind": "notify"}}],
 "triggers": [{{"kind": "os_event", "config": {{"event": "file_change", "path": "~/Downloads"}}}}],
 "notes": "Only reads; it summarises rather than moving anything, since you did not say where filed invoices should go."}}

NOW ANSWER. JSON only, exactly this shape:
{{"name": "short-kebab-name",
 "description": "one line",
 "mission": "what the orchestrator is told, in the second person, specific enough to act on",
 "new_agents": [{{"name": "...", "soul": "...", "tools": ["..."], "max_steps": 12,
                 "max_seconds": 300}}],
 "roster": [{{"subagent": "name", "why": "what it is for here"}}],
 "permissions": {{"tools": ["..."], "skills": [], "net": [], "fs_read": [], "fs_write": [],
                 "memory": "read-space"}},
 "sinks": [{{"kind": "origin"}}],
 "triggers": [],
 "notes": "one sentence on what you assumed or left out"}}
"""


def _lift_trigger(t) -> dict | None:
    """Accept the flatter trigger shape a model naturally writes and lift it into
    {kind, config}.

    Asked for `{"kind":"cron","config":{"type":"daily","at":"06:30"}}`, models reliably
    write `{"type":"cron","at":"06:30"}` instead. That is a wrapper key, not a
    misunderstanding — throwing away an otherwise correct draft over it would be pedantry.
    """
    if not isinstance(t, dict):
        return None
    if t.get("kind") in TRIGGER_KINDS and isinstance(t.get("config"), dict):
        return t
    known = {"kind", "config", "cooldown_secs", "enabled", "rotate"}
    conf = dict(t.get("config") or {})
    conf.update({k: v for k, v in t.items() if k not in known})
    kind = t.get("kind") or conf.pop("type", "") or ""
    if kind not in TRIGGER_KINDS:
        # infer from what the fields say it is, before giving up on it
        if conf.get("event") in OS_EVENTS:
            kind = "os_event"
        elif conf.get("pattern"):
            kind = "message"
        elif conf.get("at") or conf.get("minutes") or conf.get("cron"):
            kind = "cron"
        else:
            return None
    if kind == "cron" and "type" not in conf:
        conf["type"] = "interval" if conf.get("minutes") else "daily"
    out = {"kind": kind, "config": conf}
    for k in ("cooldown_secs", "enabled"):
        if k in t:
            out[k] = t[k]
    return out


async def compose(cfg: dict, store, request: str, tools: list, model: str = "",
                  current: dict | None = None) -> dict:
    """Draft a flow from a sentence, or revise one you already have. Writes NOTHING.

    The draft is a proposal the user reads and saves themselves. That is not timidity about
    model quality — a flow's definition IS its permissions, and something that grants
    standing access to tools should never appear without a person having looked at it.

    `current` turns this into an edit: "also send it to Telegram" and "make me one that
    sends to Telegram" are the same question from two starting points, so they take one path.
    """
    from . import knowledge as _k
    from . import providers as _p

    model = model or cfg.get("default_model") or ""
    if not model:
        return {"error": "no model configured — set one in the Models app first"}
    if current:
        keep = ("name", "description", "mission", "roster", "permissions", "sinks",
                "autonomy_cap", "max_delegations", "max_steps", "max_seconds")
        intent = ("REVISE this existing flow. Keep its name. Change only what the request asks "
                  "for — leave everything else exactly as it is — and return the WHOLE "
                  "definition:\n"
                  + json.dumps({k: current.get(k) for k in keep}, indent=1)
                  + "\n\nIts triggers right now: "
                  + (json.dumps(current.get("triggers") or []) or "none")
                  + f"\n\nTHE CHANGE ASKED FOR:\n{(request or '').strip()[:1000]}")
    else:
        intent = f"THE USER WANTS:\n{(request or '').strip()[:2000]}"
    agents = "\n".join(
        f"  - {s['name']}: {' '.join((s.get('soul') or '(no persona)').split())[:150]}"
        for s in store.list_subagents()) or "  (none yet — you will have to create them)"
    tool_lines = "\n".join(f"  - {t['name']}: {' '.join((t.get('description') or '').split())[:90]}"
                           for t in (tools or [])[:120]) or "  (none)"
    skills = ", ".join(s["name"] for s in store.list_skills()) or "(none installed)"
    prompt = COMPOSE_PROMPT.format(intent=intent, agents=agents,
                                   tools=tool_lines, skills=skills)
    try:
        raw = await _p.complete(cfg, model, prompt,
                                system="You are a systems designer. Answer with JSON only.")
    except Exception as e:
        # The model is a capability like any other: when it is missing or misconfigured,
        # say which one and what went wrong, rather than letting a 500 stand in for it.
        return {"error": f"{model} could not answer: {e}"}
    draft = _k._parse_json(raw)
    if not draft:
        return {"error": f"{model} did not return a usable design — try again, or write it "
                         f"by hand", "raw": raw[:600]}

    # Keep the model honest about the inventory: a roster naming an agent that neither
    # exists nor is being created would fail validation later with a worse message, and a
    # tool that does not exist would become a grant for something unreachable.
    known_tools = {t["name"] for t in (tools or [])}
    have = {s["name"] for s in store.list_subagents()}
    new_agents, dropped_agents = [], []
    for a in (draft.get("new_agents") or []):
        nm = (a.get("name") or "").strip()
        if not _NAME_RE.match(nm) or nm in have:
            continue
        a["tools"] = [t for t in (a.get("tools") or []) if t in known_tools]
        new_agents.append(a)
        have.add(nm)
    draft["new_agents"] = new_agents
    roster = []
    for r in (draft.get("roster") or []):
        if isinstance(r, str):
            r = {"subagent": r}
        if (r.get("subagent") or "") in have:
            roster.append(r)
        else:
            dropped_agents.append(r.get("subagent") or "?")
    draft["roster"] = roster
    perms = draft.get("permissions") or {}
    dropped_tools = [t for t in (perms.get("tools") or []) if t not in known_tools]
    perms["tools"] = [t for t in (perms.get("tools") or []) if t in known_tools]
    # A blank entry becomes a grant for `net:` or `fs:`, which means nothing and reads as
    # something. Models emit them when they have no answer for a field they were shown.
    for k in ("skills", "net", "fs_read", "fs_write", "mcp"):
        perms[k] = [str(v).strip() for v in (perms.get(k) or []) if str(v).strip()]
    draft["permissions"] = perms
    draft["triggers"] = [_lift_trigger(t) for t in (draft.get("triggers") or [])]
    draft["triggers"] = [t for t in draft["triggers"] if t]
    warnings = []
    if dropped_tools:
        warnings.append(f"dropped tools this machine does not have: {', '.join(dropped_tools)}")
    if dropped_agents:
        warnings.append(f"dropped roster entries with no agent behind them: "
                        f"{', '.join(dropped_agents)}")
    if not roster:
        warnings.append("no usable roster — pick or create at least one agent before saving")
    # A revision returns the WHOLE definition, and models fill the fields they did not
    # touch with null. Merged as-is that quietly resets a max_delegations somebody tuned,
    # so "I did not change this" must not arrive looking like "set this to nothing".
    for k in [k for k, v in list(draft.items()) if v is None]:
        draft.pop(k, None)
    if current:
        draft = {**current, **draft, "name": current.get("name") or draft.get("name", "")}
    draft["warnings"] = warnings
    draft["model"] = model
    draft["request"] = (request or "").strip()[:2000]   # so "draft again" can re-ask
    return draft


SUBAGENT_PROMPT = """You design SUBAGENTS for AgentOS, an agent operating system.

A subagent is one specialist: a persona, a model, and an explicit list of tools it may use.
It is called by a flow's orchestrator or addressed directly as `@name`. It does ONE job well.

{intent}

Tools it can be given (use these names EXACTLY; anything not listed does not exist):
{tools}

Installed skills: {skills}

RULES
- The `soul` is written in the second person and says what it does AND how it behaves when
  unsure: "You research. Gather real information with your tools, verify it, and return a
  dense, sourced summary. Never pad; never invent."
- Give it the FEWEST tools that let it do its job. Memory and skills access
  (use_skill, recall, kg_query, remember) is always included — never list those.
- `max_steps` 4-20, `max_seconds` 120-600. A validator needs fewer than a researcher.
- `autonomy_cap` is paranoid | balanced | full. Prefer balanced.

Reply with JSON only:
{{"name": "short-kebab-name", "soul": "...", "tools": ["..."], "skills": [],
  "autonomy_cap": "balanced", "max_steps": 12, "max_seconds": 300,
  "notes": "one sentence on what you assumed"}}
"""


async def compose_subagent(cfg: dict, store, request: str, tools: list,
                           current: dict | None = None, model: str = "") -> dict:
    """Draft (or revise) one specialist. Writes nothing — same contract as `compose`.

    Revision is the same call with the existing definition in the prompt, because "make it
    also read files" and "make me one that reads files" are the same question asked from
    two different starting points.
    """
    from . import knowledge as _k
    from . import providers as _p

    model = model or cfg.get("default_model") or ""
    if not model:
        return {"error": "no model configured — set one in the Models app first"}
    if current:
        intent = ("REVISE this existing subagent. Keep its name. Change only what the request "
                  "asks for, and return the WHOLE definition:\n"
                  + json.dumps({k: current.get(k) for k in
                                ("name", "soul", "tools", "skills", "autonomy_cap",
                                 "max_steps", "max_seconds")}, indent=1)
                  + f"\n\nTHE CHANGE ASKED FOR:\n{(request or '').strip()[:1000]}")
    else:
        intent = f"THE USER WANTS:\n{(request or '').strip()[:1000]}"
    tool_lines = "\n".join(f"  - {t['name']}: {' '.join((t.get('description') or '').split())[:90]}"
                           for t in (tools or [])[:120]) or "  (none)"
    skills = ", ".join(s["name"] for s in store.list_skills()) or "(none installed)"
    try:
        raw = await _p.complete(cfg, model,
                                SUBAGENT_PROMPT.format(intent=intent, tools=tool_lines,
                                                       skills=skills),
                                system="You are a systems designer. Answer with JSON only.")
    except Exception as e:
        return {"error": f"{model} could not answer: {e}"}
    d = _k._parse_json(raw)
    if not d:
        return {"error": f"{model} did not return a usable design — try again, or write it by hand"}
    known = {t["name"] for t in (tools or [])}
    dropped = [t for t in (d.get("tools") or []) if t not in known]
    d["tools"] = [t for t in (d.get("tools") or []) if t in known]
    d["skills"] = [s["name"] for s in store.list_skills()
                   if s["name"] in set(d.get("skills") or [])]
    if current:
        d["name"] = current.get("name") or d.get("name") or ""
    if not _NAME_RE.match((d.get("name") or "").strip()):
        d["name"] = re.sub(r"[^A-Za-z0-9_-]+", "-", (d.get("name") or "specialist")).strip("-")[:48] \
            or "specialist"
    d["autonomy_cap"] = d.get("autonomy_cap") if d.get("autonomy_cap") in \
        ("paranoid", "balanced", "full") else "balanced"
    d["max_steps"] = max(2, min(int(d.get("max_steps") or 12), 40))
    d["max_seconds"] = max(30, min(int(d.get("max_seconds") or 300), 1800))
    d["warnings"] = ([f"dropped tools this machine does not have: {', '.join(dropped)}"]
                     if dropped else [])
    d["model_used"] = model
    d["request"] = (request or "").strip()[:1000]
    return d


def seed_builtin(store) -> bool:
    """One flow out of the box, so the control plane has something to show.

    Seeded WITHOUT triggers on purpose: a fresh install that starts doing things
    unattended at 08:00 because it was installed is a surprise, not a feature. The
    trigger is one click away in Workflows → Flows, made deliberately.
    """
    if store.list_flows():
        return False
    have = {s["name"] for s in store.list_subagents()}
    roster = [n for n in ("researcher", "writer") if n in have]
    if not roster:
        return False
    save(store, {
        "name": "daily-briefing", "builtin": 1,
        "description": "What happened, what needs you, and what is worth reading — in one page.",
        "mission": "Produce a short briefing for the user: what changed on this machine, "
                   "anything that needs their attention, and a few lines on the topics they "
                   "follow. Use `recall` and `kg_query` to find out what they actually care "
                   "about before deciding what belongs in it. Keep it to one page.",
        "roster": [{"subagent": n, "why": "research the material" if n == "researcher"
                    else "write the briefing itself"} for n in roster],
        "permissions": {"tools": ["fetch_url", "system_info"], "memory": "read-space"},
        "sinks": [{"kind": "origin"}],
        "triggers": [],
    })
    try:
        store.log("system", "flows: seeded the built-in 'daily-briefing' flow (no trigger — "
                            "add one in Workflows → Flows to make it run by itself)")
    except Exception:
        pass
    return True


def hook_url(cfg: dict, flow: str, trigger: dict, base: str = "") -> str:
    """The full URL a service posts to. Handed over complete with its secret, so the copy
    button gives you something that works rather than something to assemble.

    `base` is how the caller actually reached this server; it wins over the configured
    port, because a server started on another port or reached from another machine would
    otherwise be told to post somewhere that does not answer."""
    base = (base or f"http://localhost:{int(cfg.get('port') or 8765)}").rstrip("/")
    return f"{base}/api/hooks/{flow}/{trigger['id']}?k={trigger.get('secret') or ''}"
