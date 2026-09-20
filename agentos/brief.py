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
    items = store.brief_items(day=day, open_only=True)
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
