"""What ran on its own, and what started it: the history the Missions app shows.

Two kinds of thing run without somebody typing at the time:

- a **mission** (a flow): each run is a `fabric_runs` row of kind `flow`, whatever
  started it (a schedule, a webhook, another mission finishing, Run now, chat);
- a **scheduled prompt** (a `tasks` row that names no mission): each firing is a
  `task_runs` row, and its answer is a conversation in Chat.

`history()` is the one answer to "what did my schedules and missions do?" for the
History tab, the Runs buttons, `/api/missions/history` and `bento job history`. It
reads rows and decides nothing a second time: a mission run started by a schedule is
the fabric run (the task_runs row only points at it), and a status is the word the
run recorded, put into the few the page draws.

Kept free of HTTP and asyncio, like jobs.py: `bento job history` works with the server
down, on a headless box where a schedule earns its keep.
"""
from __future__ import annotations

import json
import time

WEEK = 7 * 86400
STALE_S = 3 * 3600        # a run still "running" this long after it started was cut off
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

#: What a flow run's origin surface means, in words a person reads under the run.
STARTED_BY = {
    "gui": "started by you",
    "cli": "started from a terminal",
    "telegram": "started from Telegram",
    "whatsapp": "started from WhatsApp",
    "webhook": "started by a webhook",
    "api": "started by an API call",
    "flow": "started when another mission finished",
    "team": "started by a linked team",
    "chat": "started from chat",
}


def schedule_words(task: dict | None) -> str:
    """'every 60 minutes' / 'daily at 09:00' / 'when a file lands in Downloads': what a
    schedule is, in the words the Schedule tab uses for it."""
    if not task:
        return "a schedule that was removed"
    t = task.get("schedule_type") or ""
    if t == "interval":
        mins = round((task.get("interval_seconds") or 0) / 60)
        if mins and mins % 60 == 0:
            h = mins // 60
            return "every hour" if h == 1 else f"every {h} hours"
        return f"every {mins} minutes"
    if t == "daily":
        return f"daily at {task.get('at_time') or '09:00'}"
    if t == "weekly":
        wd = int(task.get("weekday") or 0)
        return f"every {DAYS[wd % 7]} at {task.get('at_time') or '09:00'}"
    if t == "trigger":
        cfg = {}
        try:
            cfg = json.loads(task.get("trigger_config") or "{}")
        except (TypeError, ValueError):
            pass
        kind = task.get("trigger") or ""
        if kind == "file_change":
            return f"when a file changes in {cfg.get('path') or 'a folder'}"
        if kind == "idle":
            return f"after {int(cfg.get('minutes') or 30)} idle minutes"
        if kind == "login":
            return "when you log in"
        if kind == "notification":
            return "when a notification arrives"
        return "on an event"
    return "once"


def _status(raw: str, started: float, now: float) -> str:
    """The run's own word, put into the six the page draws. `parked` is waiting for
    you in the Brief; `interrupted`/`cancelled` were stopped, which is not a failure."""
    raw = raw or ""
    if raw == "running":
        return "stopped" if now - float(started or now) > STALE_S else "running"
    if raw == "parked":
        return "waiting"
    if raw in ("ok", "partial", "skipped"):
        return raw
    if raw in ("interrupted", "cancelled", "expired"):
        return "stopped"
    return "failed"


def _said(text: str, n: int = 240) -> str:
    return " ".join(str(text or "").split())[:n]


def _secs(a, b) -> int | None:
    return int(round(float(b) - float(a))) if a and b else None


def history(store, task_id: str = "", mission: str = "", limit: int = 80,
            now: float | None = None) -> dict:
    """Every run a schedule or a mission made, newest first, with what started each
    and the door to what it produced. Filter by one schedule (`task_id`) or one
    mission (`mission`); both empty is everything."""
    now = now if now is not None else time.time()
    tasks = {t["id"]: t for t in store.list_tasks()}
    flows = {f["name"]: f for f in store.list_flows()}
    apps = {a["id"]: a["name"] for a in store.list_apps()}
    rows: list[dict] = []
    task = tasks.get(task_id) if task_id else None

    # missions: every orchestrator run, whatever started it
    sql, args = "SELECT * FROM fabric_runs WHERE kind='flow'", []
    if mission:
        sql += " AND flow=?"
        args.append(mission)
    if task_id:
        sql += " AND origin_surface='task' AND origin_ref=?"
        args.append(task_id)
    for r in store.db.execute(sql + " ORDER BY started_at DESC LIMIT ?",
                              (*args, int(limit))).fetchall():
        r = dict(r)
        surf = r.get("origin_surface") or ""
        if surf == "task":
            t = tasks.get(r.get("origin_ref") or "")
            by = f"on its schedule, {schedule_words(t)}" if t else "by a schedule that was removed"
        else:
            by = STARTED_BY.get(surf, "started by hand" if not surf else f"started from {surf}")
        name = r.get("flow") or r.get("ref") or ""
        f = flows.get(name) or {}
        rows.append({"kind": "mission", "id": r["id"], "mission": name,
                     "title": name, "about": _said(f.get("description"), 120),
                     "task_id": r.get("origin_ref") if surf == "task" else "",
                     "started_by": by, "scheduled": surf == "task",
                     "started_at": r.get("started_at"), "finished_at": r.get("finished_at"),
                     "seconds": _secs(r.get("started_at"), r.get("finished_at")),
                     "status": _status(r.get("status"), r.get("started_at"), now),
                     "said": _said(r.get("output") or r.get("fault")),
                     "tokens": int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0),
                     "run_id": r["id"], "conversation_id": r.get("conversation_id") or ""})

    # scheduled prompts, and a schedule that could not start its mission. A firing
    # that did start a mission is already above, as that mission's run.
    for r in store.task_runs(task_id=task_id, limit=limit * 2):
        if r.get("run_id"):
            continue
        if mission and (r.get("flow") or "") != mission:
            continue
        # a schedule that keeps an app fresh says which app, here as on the Schedule tab
        app_id = (tasks.get(r.get("task_id") or "") or {}).get("app_id") or ""
        rows.append({"kind": "mission" if r.get("flow") else "prompt", "id": r["id"],
                     "mission": r.get("flow") or "",
                     "title": r.get("flow") or _said(r.get("prompt"), 90) or "(a scheduled prompt)",
                     "about": "", "task_id": r.get("task_id") or "",
                     "started_by": f"on its schedule, {schedule_words(tasks.get(r.get('task_id') or ''))}",
                     "scheduled": True,
                     "started_at": r.get("started_at"), "finished_at": r.get("finished_at"),
                     "seconds": _secs(r.get("started_at"), r.get("finished_at")),
                     "status": _status(r.get("status"), r.get("started_at"), now),
                     "said": _said(r.get("result")), "tokens": 0,
                     "app_id": app_id, "app_name": apps.get(app_id, ""),
                     "run_id": "", "conversation_id": r.get("conversation_id") or ""})

    rows.sort(key=lambda x: float(x.get("started_at") or 0), reverse=True)
    rows = rows[:limit]
    week = [r for r in rows if float(r.get("started_at") or 0) > now - WEEK]
    counts = {k: sum(r["status"] == k for r in rows)
              for k in ("running", "ok", "partial", "failed", "waiting", "stopped", "skipped")}
    counts["week"] = len(week)
    counts["scheduled"] = sum(1 for r in rows if r["scheduled"])
    title = ""
    if task_id:
        title = (f"{task['flow']}, {schedule_words(task)}" if task and task.get("flow")
                 else _said((task or {}).get("prompt"), 90) or "a schedule that was removed")
    elif mission:
        title = mission
    return {"runs": rows, "counts": counts, "filter": {"task_id": task_id, "mission": mission,
                                                       "title": title}}


def schedules(store, now: float | None = None) -> list[dict]:
    """Every schedule with what it has done: the Schedule tab's rows. `words` is the
    schedule in words; a mission's schedule is named by its mission, not the prompt."""
    now = now if now is not None else time.time()
    out = []
    by_task: dict[str, list] = {}
    for r in store.task_runs(limit=2000, since=now - 30 * 86400):
        by_task.setdefault(r.get("task_id") or "", []).append(r)
    # the app a schedule is for, by name, so Missions, App Studio and the terminal say it;
    # one whose app was deleted keeps running and says that instead of naming nothing
    apps = {a["id"]: a["name"] for a in store.list_apps()}
    for t in store.list_tasks():
        runs = by_task.get(t["id"], [])
        last = runs[0] if runs else None
        week = [r for r in runs if float(r.get("started_at") or 0) > now - WEEK]
        out.append({**t, "words": schedule_words(t),
                    "title": t.get("flow") or _said(t.get("prompt"), 120),
                    "runs_7d": len(week),
                    "failed_7d": sum(1 for r in week if r.get("status") == "failed"),
                    "last_status": _status(last.get("status"), last.get("started_at"), now) if last else "",
                    "last_at": (last.get("finished_at") or last.get("started_at")) if last else None,
                    "last_said": _said((last or {}).get("result"), 160),
                    "last_run_id": (last or {}).get("run_id") or "",
                    "last_conversation": (last or {}).get("conversation_id") or "",
                    "app_id": t.get("app_id") or "",
                    "app_name": apps.get(t.get("app_id") or "", ""),
                    "app_gone": bool(t.get("app_id")) and (t.get("app_id") not in apps)})
    return out


def schedules_text(rows: list[dict], app: str = "") -> str:
    """The Schedule tab for a terminal: one line a schedule, the app it is for under it."""
    if app:
        want = app.strip().lower()
        rows = [r for r in rows if (r.get("app_name") or "").lower() == want or r.get("app_id") == app]
    if not rows:
        return ("nothing is scheduled for that app." if app else
                "nothing is scheduled. Ask in Chat, or add one in Missions → Schedule.")
    out = []
    for r in rows:
        state = "" if r.get("enabled") else "  (off)"
        out.append(f"{r['id']}  {r.get('words') or '':<24} {(r.get('title') or '')[:70]}{state}")
        if r.get("app_gone"):
            out.append("      for an app that was deleted")
        elif r.get("app_name"):
            out.append(f"      for the app {r['app_name']}")
    return "\n".join(out)


def text(h: dict) -> str:
    """The history for a terminal: one line a run, the door under it."""
    rows = h.get("runs") or []
    head = h.get("filter", {}).get("title") or "Everything that ran on its own"
    if not rows:
        return head + "\n\n  Nothing has run yet."
    lines = [head, ""]
    for r in rows:
        when = time.strftime("%a %d %b %H:%M", time.localtime(float(r.get("started_at") or 0)))
        took = f" · {r['seconds']}s" if r.get("seconds") is not None else ""
        lines.append(f"  {when}  {r['status']:<8} {r['title'][:48]:<48}{took}")
        lines.append(f"  {'':<16} {r['started_by']}")
        if r.get("said"):
            lines.append(f"  {'':<16} {r['said'][:100]}")
        door = (f"bento flow events {r['run_id']}" if r.get("run_id")
                else f"in Chat ({r['conversation_id']})" if r.get("conversation_id") else "")
        if door:
            lines.append(f"  {'':<16} → {door}")
    return "\n".join(lines)
