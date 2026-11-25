"""Your apps from the phone: `/apps` lists them, `/app <name>` shows the latest numbers its
jobs saved, and `/app <name> <question>` asks the app's own assistant.

The channels had no hook into the apps: a phone could talk to the agent but not look at a
dashboard it had built. Telegram and WhatsApp both call this module, so they cannot disagree
about what an app shows. Two rules:

- **A glance reads, it runs nothing.** It is the app's saved data and each job's last run
  (`_jobs`), as the app's page would show them on open. No model, no step, no grant.
- **A question is the app's own assistant** (`server.app_ask_from_phone`): it runs as the
  app, with the app's code and data in front of it, through the same doors as the ✦ inside
  the app. The owner only, like the rest of the console.
"""
from __future__ import annotations

import json
import time

GLANCE_CHARS = 1500      # what a phone shows of an app's data before "…"


def listing(store) -> list[dict]:
    return [{"id": a["id"], "name": a.get("name") or a["id"]} for a in store.list_apps()]


def find(store, words: str) -> tuple[dict | None, str]:
    """(app, the rest of the words). The longest app name the words start with wins, so
    "/app Signal Desk what moved" finds "Signal Desk" before an app called "Signal"."""
    said = " ".join(str(words or "").split())
    low = said.lower()
    best = None
    for a in store.list_apps():
        name = (a.get("name") or "").strip()
        n = name.lower()
        if n and (low == n or low.startswith(n + " ")) and (best is None or len(n) > len(best[0])):
            best = (n, a)
    if best:
        return best[1], said[len(best[0]):].strip()
    return None, said


def _ago(ms) -> str:
    try:
        s = max(0, time.time() - float(ms) / 1000)
    except (TypeError, ValueError):
        return ""
    return ("just now" if s < 60 else f"{int(s // 60)} min ago" if s < 3600
            else f"{int(s // 3600)} h ago" if s < 86400 else f"{int(s // 86400)} days ago")


def _compact(value) -> str:
    """A phone's view of saved data: a flat object is a line per value ("signals: 42"), anything
    deeper is its JSON, cut at GLANCE_CHARS."""
    if isinstance(value, dict) and value and all(isinstance(v, (str, int, float, bool)) or v is None
                                                 for v in value.values()):
        text = "\n".join(f"{k}: {v}" for k, v in list(value.items())[:30])
    else:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    return text if len(text) <= GLANCE_CHARS else text[:GLANCE_CHARS].rsplit(" ", 1)[0] + " …"


def glance(store, app: dict) -> str:
    """The app as its page would open: each job's last run and what it saved, then any other
    data. Words only; nothing runs."""
    from . import appjobs
    try:
        data = json.loads(store.get_app_data(app["id"]) or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    lines = [f"▦ {app.get('name') or app['id']}"]
    jobs = appjobs.of_app(store, app["id"])
    runs = data.get(appjobs.STATUS_KEY) if isinstance(data.get(appjobs.STATUS_KEY), dict) else {}
    shown = {appjobs.STATUS_KEY}
    for t in jobs:
        title, key = t.get("prompt") or "", t.get("data_key") or ""
        run = runs.get(title) or {}
        when = _ago(run.get("at")) if run.get("at") else "has not run yet"
        state = "" if run.get("ok", True) else f" · failed: {run.get('note', '')[:160]}"
        lines.append(f"\n{title} · every {int(t.get('interval_seconds') or 0) // 60} min · {when}{state}")
        if key in data:
            lines.append(_compact(data[key]))
            shown.add(key)
    rest = {k: v for k, v in data.items() if k not in shown}
    if rest:
        lines.append("\n" + _compact(rest))
    if len(lines) == 1:
        lines.append("Nothing saved yet. Open the app on the desktop to set it up.")
    lines.append(f"\nAsk it something: /app {app.get('name')} <your question>")
    return "\n".join(lines)


def apps_text(store) -> str:
    rows = listing(store)
    if not rows:
        return "▲ No apps yet. Ask me to build one."
    return ("▲ Your apps. Tap one for its latest numbers, or /app <name> <question> to ask it.\n"
            + "\n".join(f"• {r['name']}" for r in rows[:40]))


async def answer(store, words: str, surface: str, approver) -> str:
    """`/app <name> [question]`: a glance, or the app's assistant answering."""
    app, rest = find(store, words)
    if app is None:
        names = ", ".join(r["name"] for r in listing(store)[:12]) or "none yet"
        return f"▲ Which app? /app <name>. Your apps: {names}"
    if not rest:
        return glance(store, app)
    from . import server
    out = await server.app_ask_from_phone(app["id"], rest, surface, approver)
    return f"▦ {app.get('name')}\n{out}"
