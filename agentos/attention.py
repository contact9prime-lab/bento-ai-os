"""The attention engine: what deserves the user's attention, decided in the background.

Three proactive behaviours, all model-idle-deferred (they never make a live chat
queue behind them) and all degrading to nothing when there is no model, no
notification daemon, or no material:

  - notification triage — batch-scores the notification center (importance 0-2),
    groups related items, and writes a one-paragraph "For you" digest,
  - the "while you were away" briefing — on login/unlock after ≥30 min away,
    a 3-sentence summary of what happened, delivered as a notification + WS event,
  - suggestions — at most ONE actionable suggestion at a time, rate-limited hard,
    produced after the knowledge loop's session rollup.

Everything it runs goes through the scheduler's background-chat path, so every
turn it initiates is origin-tagged and counted by the OS-initiative metric.
"""

import asyncio
import json
import time

from . import knowledge, providers

TRIAGE_PROMPT = """You triage the desktop notification center of AgentOS. Below are the current notifications. Score each one's importance for the user: 0 = noise (can be ignored), 1 = normal, 2 = needs attention. Group related items and write ONE short paragraph (2-3 sentences max) digesting what matters right now — lead with the important things; omit pure noise. If nothing matters, make "digest" an empty string.

Return ONLY a JSON object (no markdown, no commentary):
{{"importance": {{"<id>": 0|1|2, ...}}, "digest": "<one paragraph or empty>", "top_ids": [<ids of the most important items, max 3>]}}

Notifications (id | app | summary | body):
{items}"""

BRIEFING_PROMPT = """Compose a 3-sentence "while you were away" briefing from the material below. Plain text only, no headings, no lists — just three friendly, information-dense sentences covering what actually matters. Do not invent anything not in the material.

=== material ===
{material}
=== end material ==="""

SUGGEST_PROMPT = """You are the proactivity subsystem of AgentOS. Below are the user's recent chat turns. If — and only if — a clear recurring need shows (the same topic asked repeatedly, a manual chore that could be scheduled, a check they keep running), propose ONE actionable automation. Otherwise propose nothing; silence beats noise.

Return ONLY a JSON object:
{{"suggestion": {{"text": "<one sentence offer to the user, e.g. 'You asked about X three times — want a scheduled digest?'>", "action_prompt": "<the exact prompt AgentOS should run if they accept>"}}}}
or {{}} if nothing is clearly worth suggesting.

Recent turns:
{turns}"""

TRIAGE_MIN_BATCH = 5          # score when the center holds this many items, or…
TRIAGE_MAX_AGE = 1800         # …when 30 min passed since the last pass
BRIEFING_MIN_AWAY = 1800      # no briefing for absences under 30 min
SUGGEST_DISMISS_QUIET = 86400  # a dismissed suggestion silences us for 24 h

_state = {"last_triage": 0.0}


def _model(cfg: dict) -> str:
    return (cfg.get("memory") or {}).get("model") or cfg.get("default_model") or ""


# ---------------------------------------------------------------------------
# Notification triage → importance scores + the "For you" digest
# ---------------------------------------------------------------------------

def should_triage(notifd, now: float | None = None) -> bool:
    """Batch gate: only with unscored items, and only when the pile is worth a
    model call (≥5 items) or the last pass is stale (≥30 min)."""
    if notifd is None or not getattr(notifd, "items", None):
        return False
    if not any("importance" not in n for n in notifd.items):
        return False
    if len(notifd.items) >= TRIAGE_MIN_BATCH:
        return True
    return (now or time.time()) - _state["last_triage"] >= TRIAGE_MAX_AGE


async def triage(cfg: dict, store, notifd, broadcast=None, force: bool = False) -> dict | None:
    """One triage pass. Returns what it decided, or None when gated/unavailable."""
    if not force and not should_triage(notifd):
        return None
    model = _model(cfg)
    if notifd is None or not model:
        return None
    _state["last_triage"] = time.time()
    await knowledge.wait_model_idle(model)  # background work defers to the user
    items = list(notifd.items)[:30]
    lines = "\n".join(f"{n['id']} | {n['app'] or 'system'} | {n['summary']} | {n['body'][:200]}"
                      for n in items)
    data = knowledge._parse_json(
        await providers.complete(cfg, model, TRIAGE_PROMPT.format(items=lines)))
    if not data:
        return None
    imp = data.get("importance") or {}
    scored = 0
    for n in notifd.items:
        v = imp.get(str(n["id"]), imp.get(n["id"]))
        if v is not None:
            try:
                n["importance"] = max(0, min(2, int(v)))
                scored += 1
            except Exception:
                continue
    digest = (data.get("digest") or "").strip()
    top_ids = [int(i) for i in (data.get("top_ids") or []) if str(i).lstrip("-").isdigit()][:3]
    if digest:
        store.dismiss_proactive(kind="digest")  # one live digest at a time
        store.add_proactive("digest", digest, {"top_ids": top_ids})
    store.log("system", f"notification triage: scored {scored}"
                        + (", digest updated" if digest else ""))
    if broadcast:
        await broadcast({"type": "notification_center"})
    return {"scored": scored, "digest": digest, "top_ids": top_ids}


def digest_state(store) -> dict | None:
    """The live digest in the /api/notifications additive shape, or None."""
    row = store.latest_proactive("digest")
    if not row:
        return None
    return {"text": row["text"], "at": row["created_at"],
            "top_ids": (row["data"] or {}).get("top_ids") or []}


def dismiss_digest(store):
    store.dismiss_proactive(kind="digest")


async def attention_loop(cfg: dict, store, notifd_get, broadcast=None, interval: int = 60):
    """Idle-scheduled triage: checks the batch gate every minute, works rarely."""
    from . import users as usersmod
    await asyncio.sleep(120)  # let the daemon claim the bus name and the desktop settle
    while True:
        # Triage is about somebody's own notifications and reads their own memory
        # to decide what matters to them, so it runs once per account rather than
        # once per machine.
        for uid in usersmod.sweep():
            with usersmod.as_user(uid):
                c, st = usersmod.resolve(cfg, store)
                try:
                    await triage(c, st, notifd_get(), broadcast)
                except Exception as e:
                    try:
                        st.log("error", f"notification triage failed: {type(e).__name__}: {e}")
                    except Exception:
                        pass
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# "While you were away" briefing
# ---------------------------------------------------------------------------

def _last_activity(store) -> float:
    """Last chat turn — in this process or, after a restart, from the turn log."""
    ts = 0.0
    try:
        row = store.db.execute(
            "SELECT MAX(created_at) t FROM logs WHERE kind='turn'").fetchone()
        ts = float(row["t"] or 0)
    except Exception:
        pass
    return max(ts, knowledge.last_turn_seen())


def briefing_material(store, notifd, since: float) -> str:
    """What happened while the user was away — empty string means 'nothing worth
    saying', which cancels the briefing."""
    parts = []
    if notifd is not None:
        unread = [n for n in getattr(notifd, "items", []) if not n.get("read")]
        if unread:
            parts.append("Unread notifications:\n" + "\n".join(
                f"- {n['app'] or 'system'}: {n['summary']}"
                + (f" — {n['body'][:120]}" if n["body"] else "") for n in unread[:10]))
    try:
        done = [t for t in store.list_tasks()
                if (t.get("last_run") or 0) > since and t.get("last_result")]
        if done:
            parts.append("Background tasks that finished:\n" + "\n".join(
                f"- {t['prompt'][:80]}: {t['last_result'][:160]}" for t in done[:5]))
    except Exception:
        pass
    try:
        mems = store.db.execute(
            "SELECT content FROM memories WHERE created_at>? AND scope='user' "
            "ORDER BY created_at DESC LIMIT 5", (since,)).fetchall()
        if mems:
            parts.append("New memories:\n" + "\n".join(f"- {m['content']}" for m in mems))
    except Exception:
        pass
    return "\n\n".join(parts)


async def run_briefing(cfg: dict, store, notifd, scheduler, broadcast=None,
                       reason: str = "login", force: bool = False) -> str | None:
    """Compose and deliver the briefing — only after ≥30 min away AND with material."""
    since = _last_activity(store)
    if not force and time.time() - since < BRIEFING_MIN_AWAY:
        return None
    material = briefing_material(store, notifd, since)
    if not material:
        return None
    if not _model(cfg):
        return None
    await knowledge.wait_model_idle(_model(cfg))
    cid, text = await scheduler.run_prompt(
        BRIEFING_PROMPT.format(material=material[:6000]),
        origin="briefing", title="☀ While you were away")
    text = (text or "").strip()
    if not text or text.startswith("[error]"):
        return None
    # deliver through the existing notify path: we ARE the daemon in de mode
    delivered = False
    if notifd is not None and getattr(notifd, "available", False):
        try:
            notifd.add("AgentOS", 0, "", "While you were away", text, {})
            delivered = True
        except Exception:
            pass
    if not delivered:
        try:
            from . import desktop as desktopmod
            desktopmod.send_notification("While you were away", text)
        except Exception:
            pass
    if broadcast:
        await broadcast({"type": "briefing", "text": text,
                         "reason": reason, "conversation_id": cid})
    store.log("system", f"briefing delivered ({reason})", {"conversation_id": cid})
    return text


async def session_start(cfg: dict, store, notifd_get, scheduler, broadcast=None):
    """Server started as the session (de/kiosk): fire login triggers, run the
    briefing, and — best-effort — re-run it on logind session unlock."""
    await asyncio.sleep(15)  # let the daemon claim the name and clients connect
    try:
        await scheduler.fire_login()
    except Exception:
        pass
    try:
        await run_briefing(cfg, store, notifd_get(), scheduler, broadcast, reason="login")
    except Exception as e:
        try:
            store.log("error", f"login briefing failed: {type(e).__name__}: {e}")
        except Exception:
            pass
    # lock→unlock briefings via logind's Session Unlock signal (best-effort:
    # no systemd / no bus / no signal support all silently mean login-only)
    try:
        from . import hostctl
        from .hostctl import logind
        iface = await hostctl.interface(logind.SERVICE, logind.SESSION_PATH,
                                        logind.SESSION_IFACE)

        def _on_unlock():
            asyncio.ensure_future(run_briefing(
                cfg, store, notifd_get(), scheduler, broadcast, reason="unlock"))

        iface.on_unlock(_on_unlock)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Suggestions (invoked by knowledge.run_maintenance after the session rollup)
# ---------------------------------------------------------------------------

async def maybe_suggest(cfg: dict, store, broadcast=None) -> dict | None:
    """At most ONE live suggestion, never within 24 h of a dismissal, and only
    when there is real material — all gates run BEFORE any model call."""
    if store.latest_proactive("suggestion"):
        return None  # one at a time — the user hasn't dealt with the last one
    if store.proactive_dismissed_since("suggestion", time.time() - SUGGEST_DISMISS_QUIET):
        return None  # they said no recently; stay quiet
    model = _model(cfg)
    if not model:
        return None
    turns = [L for L in store.list_logs("turn", limit=40)
             if time.time() - L["created_at"] < 48 * 3600]
    user_turns = []
    for L in turns:
        try:
            if (json.loads(L.get("meta") or "{}").get("origin") or "user") == "user":
                user_turns.append(L["message"])
        except Exception:
            user_turns.append(L["message"])
    if len(user_turns) < 3:
        return None  # not enough material for a pattern
    await knowledge.wait_model_idle(model)
    data = knowledge._parse_json(await providers.complete(
        cfg, model, SUGGEST_PROMPT.format(turns="\n".join(f"- {t}" for t in user_turns[:30]))))
    s = data.get("suggestion") or {}
    text = (s.get("text") or "").strip()
    action = (s.get("action_prompt") or "").strip()
    if not text or not action:
        return None
    sid = store.add_proactive("suggestion", text, {"action_prompt": action})
    store.log("system", f"suggestion floated: {text[:120]}", {"id": sid})
    if broadcast:
        await broadcast({"type": "suggestion", "id": sid, "text": text,
                         "action_prompt": action})
    return {"id": sid, "text": text, "action_prompt": action}
