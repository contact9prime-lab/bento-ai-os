"""The Brief: what the missions produced, as things a person acts on — not messages.

Every other agent delivers a mission the same way: a wall of prose lands in a
chat or a file, once, and the next run lands another one under it. Nothing in
that wall can be tapped, nothing in it remembers that you dealt with it, and
the third morning you stop reading. This OS delivers differently:

- **A mission produces ITEMS.** `brief_item` is a tool every specialist has:
  kind (needs_you / decide / fyi / done), a title, two lines, who, by when, a
  draft if there is one, the source it came from, and for a decision the
  choices. The narrative `finish` still exists — it is the long form, saved as a
  report — but what reaches the person is the items.
- **One living page per day**, the same page on the desktop's home scene, on
  the phone (one item per screen), in a Telegram message with buttons, and
  read aloud. A mission's next run UPDATES an item it wrote before (same
  mission, same key) rather than adding a twin, and an item marked Done stays
  done. A thing that needs you does not stop needing you at midnight: open
  items carry over.
- **Every item has hands.** Done and Later are one tap. A draft can be sent —
  through the same gate, as the person, so `mail_send` asks. A decision's
  choices are buttons, and the answer is HANDED BACK TO THE AGENT as a turn:
  "you decided: counter at $20 — draft the reply", with the item as context.
  That loop — mission → decision inbox → your one word → the next step — is the
  thing a message cannot do.

Kept free of HTTP and asyncio: `bento brief` reads and acts on the same rows
with the server down, and the routes are thin doors.
"""

from __future__ import annotations

import datetime as dt
import re

KINDS = ("needs_you", "decide", "fyi", "done")
LABELS = {"needs_you": "Needs you", "decide": "Decide", "fyi": "FYI", "done": "Done for you"}
ORDER = {k: i for i, k in enumerate(KINDS)}
STATES = ("open", "done", "later", "decided")
ACTIONS = ("done", "later", "reopen", "decide")


def today() -> str:
    return dt.date.today().isoformat()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def _short(text: str, n: int = 48) -> str:
    """A button's label: cut at a word, never mid-word — 'higher seat cou' is a
    choice nobody can read back."""
    t = " ".join(text.split())
    if len(t) <= n:
        return t
    cut = t[:n - 1].rsplit(" ", 1)[0] if " " in t[:n - 1] else t[:n - 1]
    return cut.rstrip(",;:") + "…"


def add(store, mission: str, run_id: str, kind: str, title: str, body: str = "",
        who: str = "", due: str = "", draft: str = "", source: dict | None = None,
        options: list | None = None, key: str = "", space_id: str = "") -> dict:
    """One item into today's Brief. Refuses an empty title and an unknown kind in
    a sentence the model can act on; the key defaults to the title's slug so a
    re-run of the same mission updates rather than duplicates."""
    kind = (kind or "fyi").strip().lower().replace("-", "_")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    title = " ".join(str(title or "").split())[:160]
    if not title:
        raise ValueError("an item needs a title — the one line the person will read")
    opts = [_short(str(o)) for o in (options or []) if str(o).strip()][:4]
    if kind == "decide" and not opts:
        opts = ["Yes", "No"]
    fields = {"kind": kind, "title": title, "body": str(body or "").strip()[:1200],
              "who": str(who or "").strip()[:120], "due": str(due or "").strip()[:60],
              "draft": str(draft or "").strip()[:3000], "source": source or {},
              "options": opts, "run_id": run_id or "", "space_id": space_id or ""}
    key = (key or "").strip()[:120] or slug(title)
    bid, created = store.brief_upsert(today(), mission or "", key, fields)
    return {"id": bid, "created": created, "kind": kind, "title": title}


def page(store, day: str = "") -> dict:
    """Today's Brief, grouped and counted — what every surface renders."""
    day = day or today()
    # the same item filed by several runs is one card (fold), and counted once
    items = fold(store.brief_items(day=day, open_only=True))
    items.sort(key=lambda i: (0 if i["state"] in ("open", "later") else 1,
                              ORDER.get(i["kind"], 9), -(i.get("updated_at") or 0)))
    groups = {k: [] for k in KINDS}
    for i in items:
        groups.setdefault(i["kind"], []).append(i)
    open_items = [i for i in items if i["state"] in ("open", "later")]
    return {"day": day, "items": items,
            "groups": [{"kind": k, "label": LABELS[k], "items": groups[k]} for k in KINDS if groups[k]],
            "counts": counts_of(items),
            "missions": sorted({i["mission"] for i in items if i.get("mission")}),
            "open": len(open_items)}


def counts_of(items: list) -> dict:
    out = {k: 0 for k in KINDS}
    for i in items:
        if i["state"] in ("open", "later"):
            out[i["kind"]] = out.get(i["kind"], 0) + 1
    out["open"] = sum(v for k, v in out.items() if k in KINDS)
    return out


def headline(counts: dict) -> str:
    """'2 need you · 1 decision' — the home scene's line and the toast."""
    parts = []
    if counts.get("needs_you"):
        n = counts["needs_you"]
        parts.append(f"{n} need{'s' if n == 1 else ''} you")
    if counts.get("decide"):
        n = counts["decide"]
        parts.append(f"{n} decision{'s' if n != 1 else ''}")
    if counts.get("fyi"):
        parts.append(f"{counts['fyi']} FYI")
    if counts.get("done"):
        parts.append(f"{counts['done']} done for you")
    return " · ".join(parts) or "nothing open"


def act(store, bid: str, action: str, choice: str = "") -> dict:
    """Done / Later / Reopen / Decide on one item. Pure state; the answer TURN a
    decision starts is the server's (it needs the agent), and `decide_prompt`
    is what it sends."""
    item = store.brief_get(bid)
    if not item:
        raise ValueError(f"no item '{bid}' in the Brief")
    if action not in ACTIONS:
        raise ValueError(f"action is one of {', '.join(ACTIONS)}")
    if action == "done":
        store.brief_set(bid, state="done")
    elif action == "later":
        # tomorrow's page: it carries as open anyway, `later` only says you saw it
        store.brief_set(bid, state="later",
                        day=(dt.date.today() + dt.timedelta(days=1)).isoformat())
    elif action == "reopen":
        store.brief_set(bid, state="open", decision="", answer_cid="", day=today())
    elif action == "decide":
        opts = item.get("options") or []
        c = str(choice or "").strip()
        if not c:
            raise ValueError(f"which choice? one of: {', '.join(opts) or 'Yes, No'}")
        store.brief_set(bid, state="decided", decision=c[:80])
    return store.brief_get(bid) or item


def parked_run(item: dict) -> str:
    """The run this item's answer carries on, or '' when it is an ordinary item.
    A mission that stopped to wait for a person files its question with source
    {"type": "parked", "ref": <run id>} (fabric.py `_park`), and answering it resumes
    that run instead of starting a new turn."""
    src = (item or {}).get("source") or {}
    return str(src.get("ref") or "") if src.get("type") == "parked" else ""


def allows(item: dict, choice: str) -> bool:
    """Whether a choice on a parked question is the yes. The first option is the yes
    ("Allow"); a typed yes counts too, and anything else is a no."""
    c = str(choice or "").strip().lower()
    opts = [str(o).strip().lower() for o in ((item or {}).get("options") or [])]
    return bool(c) and ((opts and c == opts[0]) or c in ("allow", "yes", "y", "ok", "do it"))


def decide_prompt(item: dict, choice: str) -> str:
    """The turn a decision hands back to the agent — the item is its whole context."""
    src = item.get("source") or {}
    where = f" (source: {src.get('type')} {src.get('ref')})" if src.get("ref") else ""
    lines = [f"The user answered an item from today's Brief, written by the "
             f"'{item.get('mission') or 'brief'}' mission{where}.",
             f"Item: {item.get('title')}",
             f"Detail: {item.get('body')}" if item.get("body") else "",
             f"Who: {item.get('who')}" if item.get("who") else "",
             f"Due: {item.get('due')}" if item.get("due") else "",
             f"Draft on file: {item.get('draft')}" if item.get("draft") else "",
             f"The user decided: {choice}.",
             "Do the next step that decision implies — write or adjust the reply text, note "
             "what changes, or say plainly that nothing further is needed. The user sends it "
             "themselves from the Brief; do not send anything unless the user asked you to "
             "send, and sending always asks. Keep it short."]
    return "\n".join(ln for ln in lines if ln)


def digest(items: list, mission: str = "", limit: int = 8) -> str:
    """The Brief as text: for Telegram, a notification and the voice. Counts,
    then the items that need the person, numbered so a reply can name one."""
    live = [i for i in items if i["state"] in ("open", "later")]
    live.sort(key=lambda i: ORDER.get(i["kind"], 9))
    c = counts_of(live)
    head = f"▲ {mission + ' · ' if mission else ''}{headline(c)}"
    lines = [head]
    n = 0
    for i in live:
        if i["kind"] == "fyi" and n >= limit:
            continue
        n += 1
        if n > limit:
            lines.append(f"… and {len(live) - limit} more in the Brief")
            break
        tag = {"needs_you": "•", "decide": "?", "fyi": "·", "done": "✓"}.get(i["kind"], "·")
        who = f" — {i['who']}" if i.get("who") else ""
        due = f" (by {i['due']})" if i.get("due") else ""
        lines.append(f"{n}. {tag} {i['title']}{who}{due}")
        if i["kind"] == "decide" and i.get("options"):
            lines.append("   " + " / ".join(i["options"]))
    return "\n".join(lines)


def spoken(items: list) -> str:
    """What the voice says: the headline and the needs-you titles, as sentences."""
    live = [i for i in items if i["state"] in ("open", "later")]
    c = counts_of(live)
    parts = [headline(c).replace(" · ", ", ") + "."]
    for i in [x for x in live if x["kind"] in ("needs_you", "decide")][:5]:
        s = i["title"]
        if i.get("who"):
            s += f", from {i['who']}"
        if i.get("due"):
            s += f", by {i['due']}"
        parts.append(s + ".")
    return " ".join(parts)


def telegram_rows(items: list, limit: int = 6) -> list[list[dict]]:
    """Inline buttons: Done and Later per item that needs the person, and the
    choices for a decision. `br:<id>:<action>[:<choice>]`, read by telegram.py."""
    rows = []
    live = [i for i in items if i["state"] in ("open", "later") and i["kind"] in ("needs_you", "decide")]
    for n, i in enumerate(live[:limit], 1):
        if i["kind"] == "decide":
            rows.append([{"text": f"{n}: {o}"[:30], "callback_data": f"br:{i['id']}:decide:{o}"[:64]}
                         for o in (i.get("options") or ["Yes", "No"])[:3]])
        else:
            rows.append([{"text": f"✓ {n} done", "callback_data": f"br:{i['id']}:done"},
                         {"text": f"⏸ {n} later", "callback_data": f"br:{i['id']}:later"}])
    return rows


# -- the Brief as something you watch, on a schedule ----------------------------------------
#
# Asked for as "the brief experience is not very good: if that is the first thing I hear after
# a while it must be immersive", then "the brief should periodically check, on a schedule, and
# give a brief, which is what the brief is about". So the Brief comes at the times the person
# chose (`brief.times`, `brief.days`), and when it comes it is a Stage story built from the
# rows: what needs you, what to decide, each mission at a glance, what's worth knowing. Built
# from the rows and nothing else, so it is there at once, costs nothing and invents nothing;
# an AI summary on top is the person's choice (`brief.summary`).

SCHEDULE_DEFAULT = {"times": ["08:00"], "days": "daily", "summary": "plain", "telegram": True}
DAYS = ("daily", "weekdays")
SHOW = 4               # cards per list scene: one row on a wide screen, nothing cut off
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def schedule(cfg: dict) -> dict:
    """The person's Brief schedule, every field checked."""
    raw = {**SCHEDULE_DEFAULT, **((cfg or {}).get("brief") or {})}
    times = []
    for t in raw.get("times") or []:
        m = _HHMM.match(str(t).strip())
        if m:
            hhmm = f"{int(m.group(1)):02d}:{m.group(2)}"
            if hhmm not in times:
                times.append(hhmm)
    return {"times": sorted(times)[:6], "days": raw.get("days") if raw.get("days") in DAYS else "daily",
            "summary": "ai" if raw.get("summary") == "ai" else "plain",
            "telegram": raw.get("telegram") is not False, "last_at": float(raw.get("last_at") or 0)}


def set_schedule(cfg: dict, times=None, days=None, summary=None, telegram=None) -> dict:
    """Write the schedule; a bad time is refused in a sentence. [] switches it off."""
    cur = cfg.setdefault("brief", {})
    if times is not None:
        bad = [t for t in times if not _HHMM.match(str(t).strip())]
        if bad:
            raise ValueError(f"times are HH:MM, like 08:00 or 18:30 (not {', '.join(map(str, bad))})")
        cur["times"] = [str(t).strip() for t in times]
    if days is not None:
        if days not in DAYS:
            raise ValueError("days is daily or weekdays")
        cur["days"] = days
    if summary is not None:
        cur["summary"] = "ai" if summary == "ai" else "plain"
    if telegram is not None:
        cur["telegram"] = bool(telegram)
    return schedule(cfg)


def due_at(sched: dict, now: float) -> float:
    """The scheduled moment that is due now (the latest one passed today and not yet
    delivered), or 0. A machine that was off at 08:00 gives the 08:00 Brief when it wakes,
    the same day; it never gives yesterday's."""
    if not sched["times"]:
        return 0
    t = dt.datetime.fromtimestamp(now)
    if sched["days"] == "weekdays" and t.weekday() >= 5:
        return 0
    passed = []
    for hhmm in sched["times"]:
        h, m = map(int, hhmm.split(":"))
        at = t.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
        if at <= now:
            passed.append(at)
    at = max(passed) if passed else 0
    return at if at and at > sched["last_at"] else 0


def next_at(sched: dict, now: float) -> float:
    """When the next Brief comes, for the page and the terminal (0 when switched off)."""
    if not sched["times"]:
        return 0
    base = dt.datetime.fromtimestamp(now)
    for d in range(8):
        day = base + dt.timedelta(days=d)
        if sched["days"] == "weekdays" and day.weekday() >= 5:
            continue
        for hhmm in sched["times"]:
            h, m = map(int, hhmm.split(":"))
            at = day.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
            if at > now:
                return at
    return 0


def fold(items: list) -> list:
    """The same item filed by several runs (one per run: an audit, a review, a parked
    question) shown once, newest kept, with `twins` naming the others so one tap acts on
    all of them. Found on the owner's Brief: "The auditor failed Research's task" twice."""
    seen: dict = {}
    out = []
    for i in sorted(items, key=lambda x: -(x.get("updated_at") or 0)):
        k = (i.get("mission") or "", i["kind"], i["title"].strip().lower(), i["state"])
        if k in seen:
            seen[k].setdefault("twins", []).append(i["id"])
            continue
        seen[k] = i
        out.append(i)
    return out


def _greeting(now: float) -> str:
    h = dt.datetime.fromtimestamp(now).hour
    return "Good morning" if 5 <= h < 12 else "Good afternoon" if h < 17 else "Good evening"


def _sentence(text: str, n: int = 140) -> str:
    """The first sentence of an item's body, cut at a word: the context a card needs."""
    t = " ".join((text or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    return _short(m.group(1) if m else t, n)


def _mission_words(m: str) -> str:
    return " ".join((m or "").replace("_", "-").split("-")).strip()


def _line(i: dict) -> dict:
    """One card: the title whole (cut at a word), what it is about, who filed it, and the
    door to the item itself. A decision says its choices."""
    text = _sentence(i.get("body") or "")
    if i["kind"] == "decide" and i.get("options"):
        text = (text + " " if text else "") + "Choices: " + " · ".join(i["options"])
    who = [b for b in (i.get("who"), f"by {i['due']}" if i.get("due") else "",
                       f"from {_mission_words(i['mission'])}" if i.get("mission") else "") if b]
    return {"title": _short(i["title"], 100), "text": text[:200], "note": " · ".join(who)[:120],
            "open": f"brief:{i['id']}" if i.get("id") else ""}


# What each part of the Brief is, said once on its tile, so a count is never a bare number.
MEANS = {"needs_you": "only you can do these", "decide": "an agent is waiting for your answer",
         "fyi": "worth knowing, nothing to do", "done": "finished for you"}


def story(items: list, now: float, since: float = 0, agent: str = "", summary: str = "") -> list[dict]:
    """The Brief as Stage scenes (stage.clean's shapes), from the rows alone.

    Numbers carry their source ("your Brief"), because they are counts of rows here, and
    every scene says its line for the narrator. `since` marks what is new since the last
    Brief; `summary` is an AI's two sentences when the person asked for one."""
    live = fold([i for i in items if i["state"] in ("open", "later")])
    c = counts_of(live)
    new = [i for i in live if (i.get("created_at") or 0) > since] if since else []
    who = agent or "your agent"
    scenes = []
    nums = [{"label": LABELS[k], "value": str(c[k]), "note": MEANS[k], "open": f"brief:{k}"}
            for k in KINDS if c.get(k)]
    if new:
        nums.append({"label": "New since the last Brief", "value": str(len(new))})
    head = f"{_greeting(now)}. " + (headline(c).replace(" · ", ", ") + "." if live else "Nothing is waiting for you.")
    # the first thing heard says what this is: what the missions filed, to act on
    about = ("This is what your missions filed for you. Tap a card to act on it." if live else "")
    scenes.append({"kind": "numbers", "title": "Your Brief", "source": "your Brief",
                   "caption": (summary or head) + (" " + about if about else ""),
                   "say": (summary or head) + (f" {len(new)} of them came in since the last Brief." if new else ""),
                   "items": nums or [{"label": "Waiting for you", "value": "0"}]})
    need = [i for i in live if i["kind"] == "needs_you"]
    if need:
        scenes.append({"kind": "steps", "ordered": False, "title": "What needs you",
                       "items": [_line(i) for i in need[:SHOW]],
                       "caption": f"{len(need)} thing{'s' if len(need) != 1 else ''} your missions can't finish without you"
                                  + (f", {len(need) - SHOW} more in the Brief" if len(need) > SHOW else "")
                                  + ". Tap one to see it and mark it done.",
                       "say": "What needs you. " + " ".join(i["title"].rstrip(".") + "." for i in need[:3])})
    dec = [i for i in live if i["kind"] == "decide"]
    if dec:
        scenes.append({"kind": "steps", "ordered": False, "title": "Decisions waiting",
                       "items": [_line(i) for i in dec[:SHOW]],
                       "caption": (f"{len(dec) - SHOW} more in the Brief. " if len(dec) > SHOW else "")
                                  + "Tap one to choose. Your answer goes back to the agent that asked.",
                       "say": f"{len(dec)} decision{'s' if len(dec) != 1 else ''} waiting. "
                              + " ".join(i["title"].rstrip(".?") + "?" for i in dec[:2])})
    by: dict = {}
    for i in live:
        m = i.get("mission") or "Other"
        by.setdefault(m, {k: 0 for k in KINDS})[i["kind"]] += 1
    if len(by) > 1:
        top = sorted(by.items(), key=lambda kv: -sum(kv[1].values()))[:6]
        scenes.append({"kind": "chart", "chart_type": "bar", "title": "Where it comes from", "source": "your Brief",
                       "y_label": "items",
                       "series": [{"name": LABELS[k], "points": [[m[:28], v[k]] for m, v in top]}
                                  for k in ("needs_you", "decide", "fyi") if any(v[k] for _, v in top)],
                       "caption": f"{len(by)} missions filed what is waiting for you.",
                       "say": f"It comes from {len(by)} missions; {top[0][0]} filed the most."})
    fyi = [i for i in live if i["kind"] == "fyi"]
    if fyi:
        scenes.append({"kind": "steps", "ordered": False, "title": "Worth knowing",
                       "items": [_line(i) for i in fyi[:SHOW]],
                       "say": "Worth knowing. " + " ".join(i["title"].rstrip(".") + "." for i in fyi[:2])})
    done = [i for i in live if i["kind"] == "done"]
    if done:
        scenes.append({"kind": "steps", "ordered": False, "title": f"Done for you by {who}",
                       "items": [_line(i) for i in done[:SHOW]],
                       "say": f"And {len(done)} thing{'s' if len(done) != 1 else ''} done for you."})
    return scenes


def summary_prompt(items: list) -> str:
    """What the brain is asked when the person wants an AI summary: the digest, and two
    sentences back. The rows are the missions' words, so the answer is fenced to them."""
    return ("Here is my Brief, the items my missions filed:\n\n" + digest(items, limit=20)
            + "\n\nIn two short sentences, tell me what matters most and what to do first. Use only "
              "what is in the list. No preamble, no markdown.")
