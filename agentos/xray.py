"""X-ray: one answer taken apart, from this machine's own records.

Asked for as "a Jarvis-style blueprint, like you are getting to the bottom of things rather
than presenting a chart". A blueprint of the Burj Khalifa is drawn from what a model says; an
X-ray is drawn from what HAPPENED: the question, the brain that answered it, every run it
started (a department's desk, its people, a review, an audit), every decision the permission
gate made for them, what it cost, and the answer. Opened on the Stage as a blueprint scene,
so the person drills from "the Research desk" to "@data-analyst" to "run_python ×12" to the
one ledger row that was refused.

Three rules:

- **It is the trace, drawn.** Every row comes from `trace.conversation` / `trace.run`, the same
  gathering `bento trace` writes out. There is no second reading of the record, so the X-ray
  and the JSON a person hands to an AI cannot disagree.
- **Nothing is guessed.** A part is a row. What the record cannot say (an agent CLI's own reads
  and searches inside its session never pass the gate) is in `unknowns`, in words. A run still
  going says so, and the time it was read.
- **Read-only, no HTTP or asyncio**, like trace.py: `bento stage xray` works with the server down.
"""

from __future__ import annotations

import re
import time

from . import stage as stagemod
from . import trace as tracemod

SOURCE = "This machine's records: the chat, the run log and the permission gate's ledger"
CLI_ENGINES = {"claude-code": "Claude Code", "gemini-cli": "Gemini CLI", "codex": "Codex",
               "hermes": "Hermes", "openclaw": "OpenClaw"}
RUN_STATUS = {"ok": "ok", "done": "ok", "error": "failed", "timeout": "failed", "failed": "failed",
              "partial": "failed", "parked": "waiting", "waiting": "waiting", "interrupted": "stopped",
              "cancelled": "stopped", "stopped": "stopped", "skipped": "stopped", "running": "running"}
RUN_WORDS = {"flow": "desk", "delegate": "person", "review": "sign-off", "audit": "audit",
             "huddle": "huddle", "vote": "vote", "freetalk": "free talk"}
MAX_ROWS_SHOWN = 10      # single ledger rows under one group; the group carries the count


def _t(ts) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts)) if ts else ""


def _took(a, b) -> str:
    if not a or not b or b < a:
        return ""
    s = b - a
    if s < 60:
        return f"{s:.0f} s"
    if s < 3600:
        return f"{s / 60:.0f} min"
    return f"{s / 3600:.1f} h"


def _money(x: float) -> str:
    return f"${x:,.2f}" if x >= 0.01 else ("under $0.01" if x > 0 else "$0")


def _n(x) -> str:
    return f"{int(x):,}"


def _row_status(r: dict) -> str:
    eff, out = (r.get("effect") or ""), (r.get("outcome") or "")
    if eff == "deny" or out == "denied":
        return "refused"
    if eff == "ask":
        return "asked"
    if out in ("error", "fail"):
        return "failed"
    return "ok"


ACTION_WORDS = {"agent.invoke": "hand-over", "agent.message": "asked a colleague",
                "agent.huddle": "huddle", "fs.read": "read a file", "fs.write": "wrote a file",
                "net.fetch": "fetched a page", "memory.read": "recalled", "memory.write": "remembered",
                "kg.read": "looked up facts", "kg.write": "noted a fact", "mail.read": "read mail",
                "mail.send": "sent mail", "calendar.read": "read the calendar",
                "capability.grant": "asked for an ability", "model.use": "used a model",
                "browser.read": "read the browser", "browser.act": "used the browser",
                "media.generate": "made a picture", "grant.write": "permission written",
                "grant.revoke": "permission removed", "company.review": "sign-off",
                "company.audit": "audit", "skill.use": "used a skill", "flow.read": "read a mission",
                "space.read": "read a space", "device.get": "read a device", "device.set": "switched a device"}


def _tool_of(r: dict) -> str:
    """What a ledger row is about, as a person reads it: the tool, else the action in words."""
    act, res = r.get("action") or "", r.get("resource") or ""
    if act == "tool.use" and res.startswith("tool:"):
        return res[5:].split(" ", 1)[0] or act
    return ACTION_WORDS.get(act, act)


def _arg_of(r: dict) -> str:
    res = r.get("resource") or ""
    if res.startswith("tool:") and " " in res:
        return res.split(" ", 1)[1]
    return res


def rule_words(rule: str) -> str:
    """A rule as a person reads it: a grant's id is a permission somebody gave."""
    if not rule:
        return "?"
    if re.fullmatch(r"[0-9a-f]{8,}", rule):
        return f"a permission you gave ({rule[:6]})"
    return {"default": "the defaults", "roster": "the mission's roster",
            "roster-ungranted": "the roster (not granted)", "always-ask": "always asking you"}.get(rule, rule)


def _ledger_part(name: str, rows: list[dict], what: str = "", inside: bool = True) -> dict:
    """A group of the gate's decisions: one part, its count and mix, and (when there is a
    level left for them) the rows themselves."""
    sts = [_row_status(r) for r in rows]
    worst = next((s for s in ("refused", "failed", "asked") if s in sts), "ok")
    facts = [{"label": "decisions", "value": _n(len(rows))}]
    for s, word in (("ok", "allowed"), ("asked", "asked you"), ("refused", "refused"), ("failed", "failed")):
        if sts.count(s) and (s != "ok" or len(set(sts)) > 1):
            facts.append({"label": word, "value": _n(sts.count(s))})
    ms = sum(int(r.get("duration_ms") or 0) for r in rows)
    if ms:
        facts.append({"label": "time inside", "value": _took(0.0001, ms / 1000) or f"{ms} ms"})
    rules = sorted({r.get("rule") or "" for r in rows} - {""})
    kids = []
    for r in (rows[-MAX_ROWS_SHOWN:] if inside else []):
        st = _row_status(r)
        arg = " ".join(_arg_of(r).split())
        kids.append({"name": f"{_t(r.get('ts'))} {name}", "status": st,
                     "role": arg[:160],
                     "detail": " ".join(x for x in (
                         f"The gate said {r.get('effect') or '?'}, by {rule_words(r.get('rule') or '')}.",
                         (r.get("reason") or "").strip(),
                         f"Then: {r['outcome']}." if r.get("outcome") else "") if x),
                     "evidence": f"ledger #{r.get('seq') or r.get('id')} · {r.get('principal_kind')}:"
                                 f"{r.get('principal_id')} · {r.get('surface') or ''}".strip(" ·")})
    hidden = len(rows) - len(kids)
    return {"name": f"{name} ×{len(rows)}" if len(rows) > 1 else name, "status": worst,
            "role": what or (f"decided by {', '.join(rule_words(x) for x in rules[:3])}"
                             if rules else "decided by the permission gate"),
            "detail": (f"Showing the last {len(kids)} of {len(rows)}; the rest are in the trace."
                       if hidden and kids else ""),
            "facts": facts, "parts": kids, "form": "flow"}


def _ledger_groups(rows: list[dict], inside: bool = True) -> list[dict]:
    groups: dict[str, list] = {}
    for r in sorted(rows, key=lambda r: r.get("ts") or 0):
        groups.setdefault(_tool_of(r), []).append(r)
    order = sorted(groups.items(), key=lambda kv: kv[1][0].get("ts") or 0)
    return [_ledger_part(k, v, inside=inside) for k, v in order]


def _cap(parts: list[dict], n: int = stagemod.BP_CHILDREN) -> list[dict]:
    """At most n parts at a level; the rest fold into one that says how many."""
    if len(parts) <= n:
        return parts
    keep, rest = parts[:n - 1], parts[n - 1:]
    return keep + [{"name": f"{len(rest)} more", "role": "the rest of this level, in the trace",
                    "facts": [{"label": "parts", "value": _n(len(rest))}],
                    "parts": rest[:stagemod.BP_CHILDREN]}]


def _run_part(run: dict, by_parent: dict, audit_by_run: dict, depth: int) -> dict:
    kind = run.get("kind") or "run"
    who = run.get("ref") or run.get("flow") or kind
    st = RUN_STATUS.get(run.get("status") or "", "running" if not run.get("finished_at") else "")
    facts = []
    took = _took(run.get("started_at"), run.get("finished_at"))
    if took:
        facts.append({"label": "took", "value": took})
    if run.get("steps"):
        facts.append({"label": "steps", "value": _n(run["steps"])})
    tok = int(run.get("tokens_in") or 0) + int(run.get("tokens_out") or 0)
    if tok:
        facts.append({"label": "tokens", "value": _n(tok)})
    if run.get("model"):
        facts.append({"label": "brain", "value": str(run["model"])[:28]})
    kids = []
    if depth < stagemod.BP_DEPTH:      # its runs and its decisions are the next level
        kids = [_run_part(c, by_parent, audit_by_run, depth + 1) for c in by_parent.get(run["id"], [])]
        rows = audit_by_run.get(run["id"], [])
        if rows:
            kids += _ledger_groups(rows, inside=depth + 1 < stagemod.BP_DEPTH)
    said = " ".join(str(run.get("fault") or run.get("output") or "").split())
    name = f"@{who}" if kind == "delegate" else f"{who} ({RUN_WORDS.get(kind, kind)})"
    return {"name": name, "status": st,
            "role": " ".join(str(run.get("input") or "").split())[:160],
            "detail": (("It ended: " if run.get("fault") else "It said: ") + said[:500]) if said else "",
            "facts": facts, "parts": _cap(kids), "form": "flow",
            "evidence": f"run {run['id']} · {kind} · started {_t(run.get('started_at'))}",
            "unknowns": (["It was still going when this was read."] if st == "running" else [])}


def _runs_parts(runs: list[dict], audit: list[dict]) -> list[dict]:
    ids = {r["id"] for r in runs}
    by_parent: dict[str, list] = {}
    roots = []
    for r in sorted(runs, key=lambda r: r.get("started_at") or 0):
        par = r.get("parent_run") or ""
        (by_parent.setdefault(par, []) if par in ids else roots).append(r)
    audit_by_run: dict[str, list] = {}
    for a in audit:
        if a.get("run_id") in ids:
            audit_by_run.setdefault(a["run_id"], []).append(a)
    return [_run_part(r, by_parent, audit_by_run, 1) for r in roots]


def _usage(store, cid: str, t0: float, t1: float) -> tuple[int, int, float]:
    try:
        row = store.db.execute("SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0), "
                               "COALESCE(SUM(cost_usd),0) FROM usage WHERE conversation_id=? AND ts>=? "
                               "AND ts<=?", (cid, t0, t1)).fetchone()
        return int(row[0]), int(row[1]), float(row[2])
    except Exception:
        return 0, 0, 0.0


def _brain(meta: dict, cfg: dict) -> tuple[str, str]:
    eng = (meta or {}).get("engine") or ""
    model = (meta or {}).get("engine_model") or (meta or {}).get("model") or ""
    if eng and eng != "aria":
        return CLI_ENGINES.get(eng, eng), model or "its own setting"
    return "the built-in agent", model or cfg.get("default_model") or ""


def turn(store, cfg: dict, cid: str, answer_to: str = "") -> dict:
    """The blueprint scene of one answer: `answer_to` is the person's message it answers
    (the last one when empty). Raises KeyError for a chat or message that is not there."""
    doc = tracemod.conversation(store, cfg, cid)
    msgs = doc["conversation"]["messages"]
    users = [m for m in msgs if m["role"] == "user"]
    if not users:
        raise KeyError("no question in this chat")
    q = next((m for m in users if m["id"] == answer_to), None) if answer_to else users[-1]
    if not q:
        raise KeyError(answer_to)
    t0 = q["created_at"] or 0
    later = [m["created_at"] for m in users if (m["created_at"] or 0) > t0]
    t1 = min(later) if later else time.time() + 1
    replies = [m for m in msgs if m["role"] == "assistant" and t0 <= (m["created_at"] or 0) < t1]
    runs_all = doc.get("runs") or []
    tops = {r["id"] for r in runs_all if not r.get("parent_run") and t0 <= (r.get("started_at") or 0) < t1}
    # a run belongs to its top run's turn, however long it went on after
    keep, changed = set(tops), True
    while changed:
        changed = False
        for r in runs_all:
            if r["id"] not in keep and r.get("parent_run") in keep:
                keep.add(r["id"])
                changed = True
    runs = [r for r in runs_all if r["id"] in keep]
    end = max([t1 if later else 0] + [m["created_at"] or 0 for m in replies]
              + [r.get("finished_at") or r.get("started_at") or 0 for r in runs]) or time.time()
    ledger = [a for a in doc.get("ledger") or []
              if a.get("run_id") in keep or (not a.get("run_id") and t0 <= (a.get("ts") or 0) <= end)]
    reply = replies[-1] if replies else None
    meta = reply.get("meta") if reply and isinstance(reply.get("meta"), dict) else {}
    question = stagemod._s(stagemod._question(q.get("content") or ""), 160)
    return _scene(store, cfg, cid, question, t0, end, meta, reply, runs, ledger,
                  scenes=len(stagemod.story(store, cid, q["id"])), still=bool(later) is False and not reply)


def run(store, cfg: dict, rid: str) -> dict:
    """The blueprint scene of one mission or department run, from its top run down."""
    doc = tracemod.run(store, cfg, rid)
    runs = doc.get("runs") or []
    top = runs[0] if runs else {}
    t0 = min((r.get("started_at") or 0) for r in runs) if runs else 0
    end = max((r.get("finished_at") or r.get("started_at") or 0) for r in runs) if runs else 0
    question = stagemod._s(top.get("ref") or top.get("flow") or "this run", 160)
    return _scene(store, cfg, top.get("conversation_id") or "", question, t0, end, {}, None, runs,
                  doc.get("ledger") or [], scenes=0, still=False, asked=False, top=top)


ORIGIN_WORDS = {"task": "its schedule", "chat": "a chat", "gui": "this screen", "webhook": "a webhook",
                "telegram": "Telegram", "whatsapp": "WhatsApp", "flow_done": "another mission finishing",
                "os_event": "something on this machine", "device": "a device", "message": "a message",
                "cron": "its schedule", "cli": "the terminal"}


def _scene(store, cfg, cid, question, t0, end, meta, reply, runs, ledger, scenes, still,
           asked: bool = True, top: dict | None = None) -> dict:
    agent = cfg.get("agent_name") or "Your agent"
    parts = []
    if asked:
        parts.append({"name": "You asked", "role": question, "certainty": "known",
                      "facts": [{"label": "at", "value": _t(t0)}],
                      "evidence": "the chat's message"})
    brain, model = _brain(meta, cfg)
    tin, tout, cost = _usage(store, cid, t0, end) if cid else (0, 0, 0.0)
    if not cid:
        tin = sum(int(r.get("tokens_in") or 0) for r in runs)
        tout = sum(int(r.get("tokens_out") or 0) for r in runs)
    bfacts = [{"label": "brain", "value": brain[:28]}]
    if model:
        bfacts.append({"label": "model", "value": str(model)[:28]})
    if tin or tout:
        bfacts += [{"label": "read", "value": _n(tin), "unit": "tokens"},
                   {"label": "wrote", "value": _n(tout), "unit": "tokens"}]
    if cost:
        bfacts.append({"label": "cost", "value": _money(cost)})
    own = [a for a in ledger if not a.get("run_id")]
    is_cli = brain in CLI_ENGINES.values()
    if asked:
        parts.append({"name": f"{agent}, on {brain}", "certainty": "known",
                      "role": f"{agent} answered on {brain}" + (f" ({model})" if model else ""),
                      "detail": ("It ran inside its own session; the tools it reached through Bento "
                                 "are the decisions under it.") if is_cli else "",
                      "facts": bfacts, "form": "flow", "parts": _cap(_ledger_groups(own)),
                      "evidence": "the reply's record and the usage rows for this turn",
                      "unknowns": ([f"{brain}'s own reads, searches and edits inside its session never "
                                    "pass Bento's gate, so they are not in this record."] if is_cli else [])})
    if top:
        origin = top.get("origin_surface") or ""
        parts.append({"name": "What started it", "certainty": "known",
                      "role": f"started by {ORIGIN_WORDS.get(origin, origin or 'a person')}"
                              + (f" ({top['origin_ref']})" if top.get("origin_ref") else ""),
                      "detail": " ".join(str(top.get("input") or "").split())[:600],
                      "facts": [{"label": "at", "value": _t(t0)}],
                      "evidence": f"run {top.get('id')} · origin {origin or '?'}"})
    parts += _runs_parts(runs, ledger)
    if top:
        out = " ".join(str(top.get("fault") or top.get("output") or "").split())
        parts.append({"name": "What it delivered" if not top.get("fault") else "How it ended",
                      "role": out[:160] or "nothing was recorded",
                      "detail": out[160:600], "status": RUN_STATUS.get(top.get("status") or "", "running"),
                      "facts": [{"label": "took", "value": _took(t0, end)}] if _took(t0, end) else [],
                      "evidence": f"run {top.get('id')}"})
    if asked:
        text = " ".join(str((reply or {}).get("content") or "").split())
        afacts = [{"label": "words", "value": _n(len(text.split()))}] if text else []
        if scenes:
            afacts.append({"label": "scenes shown", "value": _n(scenes)})
        parts.append({"name": "The answer", "role": text[:160] or "no answer was saved",
                      "detail": text[160:600], "status": "ok" if text else ("running" if still else "failed"),
                      "facts": afacts, "evidence": "the chat's message"})
    refused = sum(1 for a in ledger if _row_status(a) == "refused")
    askedn = sum(1 for a in ledger if _row_status(a) == "asked")
    failed_runs = [r for r in runs if RUN_STATUS.get(r.get("status") or "") == "failed"]
    people = sorted({r.get("ref") for r in runs if r.get("kind") == "delegate"} - {None})
    desks = [r.get("ref") for r in runs if r.get("kind") == "flow"]
    # the takeaway, from the rows: who it went to, how much was decided, how it ended
    said = [f"{agent} handed it to {', '.join(desks[:2])}" if desks else
            f"{agent} answered it {'itself' if not runs else 'with ' + str(len(runs)) + ' runs'}"]
    if people:
        said.append(f"{len(people)} {'person' if len(people) == 1 else 'people'} worked on it")
    said.append(f"the gate made {_n(len(ledger))} decision{'s' if len(ledger) != 1 else ''}"
                + (f", refused {refused}" if refused else "") + (f", asked you {askedn}" if askedn else ""))
    if failed_runs:
        said.append(f"and {failed_runs[0].get('ref') or 'a run'} ended with "
                    f"{'an error' if failed_runs[0].get('status') == 'error' else 'a ' + str(failed_runs[0].get('status'))}")
    caption = (", ".join(said[:-1]) + (" " if said[-1].startswith("and ") else ", ") + said[-1]
               if len(said) > 1 else said[0]) + "."
    unknowns = []
    if is_cli:
        unknowns.append(f"What {brain} did inside its own session, apart from what it asked Bento for.")
    if any(not r.get("finished_at") for r in runs):
        unknowns.append(f"A run was still going at {_t(time.time())}; open the X-ray again to see the rest.")
    spec = {"kind": "blueprint", "title": f"X-ray: {question}"[:120], "subject": question or "This answer",
            "form": "flow", "caption": caption[:300], "source": SOURCE, "parts": parts,
            "unknowns": unknowns,
            "links": []}
    sc, _ = stagemod.clean(spec)
    sc["xray"] = {"took": _took(t0, end), "decisions": len(ledger), "refused": refused,
                  "asked": askedn, "runs": len(runs), "cost": round(cost, 4), "at": time.time()}
    return sc
