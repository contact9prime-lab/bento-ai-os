"""One JSON file for one execution: everything that happened, to read or to hand to an AI.

Asked for as "for every execution I should be able to get the json file to see what
happened, what the office was and what executed, so I can send it to the AI to analyse
and fix the problem". The record already exists across a dozen tables; this gathers one
conversation (or one mission run) into a single document:

- the messages, with every step each answer took;
- every run it started (a department's desk, its people, a review, an audit), as a tree,
  each with its events;
- every decision the gate made for them (the ledger rows) and the log lines;
- the scenes it showed;
- the setting it ran in: the brain, autonomy, the company, its departments, who sits where
  and what tools each one holds, the team's talk mode;
- the configuration, with every secret masked.

Two rules. **Nothing secret leaves**: any value under a key that names a key, token, secret,
password, passphrase, cookie or credential is masked to its last four characters, at any
depth, and the vault is never opened. **It is read-only**: it reads rows and writes nothing,
so `bento trace` works with the server down. Free of HTTP and asyncio, like brief.py.
"""

from __future__ import annotations

import json
import re
import time

FORMAT = "bento-trace/1"
SECRET = re.compile(r"(api_?key|key$|token|secret|password|passphrase|cookie|credential|bearer|private|auth$|authorization)", re.I)
MAX_EVENTS = 3000
MAX_AUDIT = 5000
MAX_LOGS = 2000

HOW_TO_READ = (
    "This is one execution in Bento Box AI (AgentOS). `conversation.messages` is what the "
    "person and the agent said, in order; an assistant message's `meta.steps` are the tools it "
    "used. `runs` is every run this started, as a tree (`parent_run`): a department task is a "
    "`flow` run whose children are `delegate` runs (its people), `review` runs (each boss "
    "signing off) and an `audit` run; each has its `events`. `ledger` is every decision the "
    "permission gate made (effect allow/deny/ask, rule, reason, outcome). `logs` are the "
    "free-text diary lines. `setting` is what the machine looked like: the brain, autonomy, "
    "the company and departments with each person's tools. Secrets are masked.")


def mask(value, key: str = ""):
    """Every secret-looking value masked to its last four characters, at any depth."""
    if isinstance(value, dict):
        return {k: mask(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v, key) for v in value]
    if isinstance(value, str) and key and SECRET.search(key) and value:
        return "•••" + value[-4:] if len(value) > 8 else "•••"
    return value


def _rows(store, sql: str, params: tuple = ()) -> list[dict]:
    cur = store.db.execute(sql, params)
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k in ("meta", "detail", "input_json", "data"):
            if isinstance(d.get(k), str) and d[k][:1] in "{[":
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        out.append(d)
    return out


def _tables(store) -> set:
    return {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _run_tree(store, roots: list[str]) -> list[dict]:
    """The runs named and every run below them, oldest first, each with its events."""
    seen, queue, out = set(), list(roots), []
    while queue:
        rid = queue.pop(0)
        if not rid or rid in seen:
            continue
        seen.add(rid)
        row = _rows(store, "SELECT * FROM fabric_runs WHERE id=?", (rid,))
        if not row:
            continue
        r = row[0]
        r["events"] = _rows(store, "SELECT * FROM fabric_events WHERE run_id=? ORDER BY ts LIMIT ?",
                            (rid, MAX_EVENTS)) if "fabric_events" in _tables(store) else []
        out.append(r)
        queue += [c["id"] for c in _rows(store, "SELECT id FROM fabric_runs WHERE parent_run=?", (rid,))]
    return sorted(out, key=lambda r: r.get("started_at") or 0)


def _setting(store, cfg: dict) -> dict:
    """What the machine looked like: the brain, the gate, the company and its people."""
    out: dict = {"engine": cfg.get("engine") or "aria", "default_model": cfg.get("default_model", ""),
                 "agent_name": cfg.get("agent_name", ""), "autonomy": cfg.get("autonomy", ""),
                 "team": mask(cfg.get("team") or {}), "stage": cfg.get("stage") or {}}
    try:
        from . import company as companymod
        out["company"] = companymod.profile(cfg)
        out["departments"] = [{"name": d["name"], "lead": d.get("lead"), "members": d["members"],
                               "about": d.get("about", ""), "desk": d.get("desk", ""),
                               "reports_to": d.get("reports_to", ""),
                               "can": companymod.abilities(store, d["members"])
                               if hasattr(companymod, "abilities") else ""}
                              for d in companymod.departments(cfg, store)]
    except Exception as e:
        out["company_error"] = str(e)
    try:
        out["agents"] = [{"name": a.get("name"), "tools": a.get("tools") or [], "model": a.get("model", ""),
                          "profile": a.get("profile", ""), "max_steps": a.get("max_steps"),
                          "soul": " ".join(str(a.get("soul") or "").split())[:300]}
                         for a in store.list_subagents()]
    except Exception:
        out["agents"] = []
    return out


def _meta(kind: str, ref: str) -> dict:
    try:
        from . import updates
        version = updates.current()
    except Exception:
        version = ""
    return {"format": FORMAT, "kind": kind, "ref": ref, "made_at": time.time(),
            "made": time.strftime("%Y-%m-%d %H:%M:%S"), "version": version,
            "how_to_read": HOW_TO_READ}


def conversation(store, cfg: dict, cid: str) -> dict:
    """Everything one chat did. Raises KeyError for a chat that is not there."""
    conv = store.get_conversation(cid)
    if not conv:
        raise KeyError(cid)
    tables = _tables(store)
    msgs = _rows(store, "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (cid,))
    roots = [r["id"] for r in _rows(store, "SELECT id FROM fabric_runs WHERE conversation_id=? "
                                           "AND (parent_run IS NULL OR parent_run='')", (cid,))]
    runs = _run_tree(store, roots)
    run_ids = [r["id"] for r in runs]
    marks = ",".join("?" * len(run_ids)) or "''"
    ledger = _rows(store, f"SELECT * FROM audit WHERE conversation_id=? OR run_id IN ({marks}) "
                          f"ORDER BY ts LIMIT ?", (cid, *run_ids, MAX_AUDIT)) if "audit" in tables else []
    logs = _rows(store, "SELECT * FROM logs WHERE conversation_id=? ORDER BY rowid LIMIT ?",
                 (cid, MAX_LOGS)) if "logs" in tables else []
    out = {**_meta("conversation", cid), "conversation": {**conv, "messages": msgs},
           "runs": runs, "ledger": ledger, "logs": logs, "setting": _setting(store, cfg),
           "config": mask(_config_view(cfg))}
    try:
        from . import stage as stagemod
        out["stage"] = stagemod.stories(store, cid)
    except Exception:
        out["stage"] = []
    if "task_runs" in tables:
        out["schedule_runs"] = _rows(store, "SELECT * FROM task_runs WHERE conversation_id=?", (cid,))
    return out


def run(store, cfg: dict, rid: str) -> dict:
    """Everything one mission or department run did, from its top run down."""
    row = _rows(store, "SELECT * FROM fabric_runs WHERE id=?", (rid,))
    if not row:
        raise KeyError(rid)
    top = row[0]
    while top.get("parent_run"):          # always the whole task, from its top
        up = _rows(store, "SELECT * FROM fabric_runs WHERE id=?", (top["parent_run"],))
        if not up:
            break
        top = up[0]
    runs = _run_tree(store, [top["id"]])
    run_ids = [r["id"] for r in runs]
    marks = ",".join("?" * len(run_ids))
    tables = _tables(store)
    ledger = _rows(store, f"SELECT * FROM audit WHERE run_id IN ({marks}) ORDER BY ts LIMIT ?",
                   (*run_ids, MAX_AUDIT)) if "audit" in tables else []
    out = {**_meta("run", top["id"]), "runs": runs, "ledger": ledger,
           "setting": _setting(store, cfg), "config": mask(_config_view(cfg))}
    if top.get("conversation_id"):
        conv = store.get_conversation(top["conversation_id"])
        if conv:
            out["conversation"] = {**conv, "messages": _rows(
                store, "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",
                (top["conversation_id"],))}
    if top.get("flow"):
        flow = store.get_flow(top["flow"]) if hasattr(store, "get_flow") else None
        if flow:
            out["mission"] = flow
    return out


def _config_view(cfg: dict) -> dict:
    """The configuration as a person would see it, without the bulky caches."""
    drop = {"_uid", "widgets", "desktop", "shortcuts", "history"}
    return {k: v for k, v in (cfg or {}).items() if k not in drop}


def filename(doc: dict) -> str:
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(doc.get("made_at") or time.time()))
    return f"bento-trace-{doc.get('kind')}-{str(doc.get('ref'))[:12]}-{stamp}.json"


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False, default=str)
