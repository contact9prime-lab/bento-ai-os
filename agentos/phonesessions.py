"""Sessions on a phone: start a new one, go back to an earlier one.

A Telegram or WhatsApp chat had exactly one conversation, and the only way to start over
was /clear, which deletes it. Asked for as "an option of starting a new session or
reverting to existing sessions". A session IS a conversation row, so going back to one
brings its messages, its summary and the agent CLI's own session (`exec_session`) with it.

Which conversations are a chat's is a column (`conversations.channel_ref`, e.g.
`telegram:12345`), never the title: a chat may only list and reopen its own, and a title
is something anybody can match.

One implementation for both channels (the WhatsApp rule: a channel's behaviour is written
once). No HTTP, no asyncio: the bridge sends what `handle` says.
"""
from __future__ import annotations

import time

#: how many sessions a phone lists; older ones stay in Chat on the desktop
KEEP = 10
NAME_MAX = 48
COMMANDS = ("/new", "/sessions", "/resume")
BUSY = "⏳ I'm still answering in this session. Switch once that's done."


def ref(channel: str, key) -> str:
    return f"{channel}:{key}"


def _short(text: str, n: int) -> str:
    """Cut at a word, and say that it was cut."""
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0] or text[:n]
    return cut + "…"


def _name(arg: str) -> str:
    """A session's name is the person's words: one line, no controls, bounded."""
    clean = "".join(ch for ch in (arg or "") if ch.isprintable())
    return _short(clean, NAME_MAX).rstrip("…").strip(" ·")


def _when(ts: float, now: float | None = None) -> str:
    now = now or time.time()
    t, n = time.localtime(ts or 0), time.localtime(now)
    if (t.tm_year, t.tm_yday) == (n.tm_year, n.tm_yday):
        return "today " + time.strftime("%H:%M", t)
    if now - (ts or 0) < 6 * 86400:
        return time.strftime("%a %H:%M", t)
    return time.strftime("%d %b", t)


def label(row: dict) -> str:
    """What a session is called in the list: its name, else what it opened with."""
    if row.get("channel_name"):
        return row["channel_name"]
    first = _short(row.get("first") or "", 40)
    return f"“{first}”" if first else "nothing asked yet"


def sessions(store, chat_ref: str, current: str = "") -> list[dict]:
    """This chat's sessions, newest first, the open one always among them."""
    if current:
        store.claim_conversation(current, chat_ref)   # a chat from before the column
    rows = store.channel_conversations(chat_ref, KEEP)
    for i, r in enumerate(rows, 1):
        r["n"], r["current"], r["label"] = i, r["id"] == current, label(r)
    return rows


def listing(rows: list[dict]) -> str:
    out = ["▲ Your sessions here (▶ is the open one)"]
    for r in rows:
        n = int(r.get("msgs") or 0)
        out.append(f"{'▶' if r['current'] else '•'} {r['n']}. {r['label']} · "
                   f"{n} message{'' if n == 1 else 's'} · {_when(r.get('updated_at') or 0)}")
    out.append("")
    out.append("/resume 2 goes back to one. /new starts another; add a name if you like.")
    return "\n".join(out)


def pick(rows: list[dict], arg: str) -> tuple[dict | None, str]:
    """A session by its number or by a part of its name. Never a guess."""
    arg = (arg or "").strip()
    if arg.isdigit():
        hit = next((r for r in rows if r["n"] == int(arg)), None)
        return (hit, "") if hit else (None, f"▲ There is no session {arg}. /sessions shows them.")
    low = arg.lower()
    hits = [r for r in rows if low in r["label"].lower()]
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"▲ No session here matches “{_short(arg, 40)}”. /sessions shows them."
    return None, ("▲ That matches " + ", ".join(str(r["n"]) for r in hits)
                  + ". Say which by its number.")


def start(store, channel: str, key, title: str, name: str = "") -> str:
    """A new, empty session for this chat. The one before is kept."""
    word = "Telegram" if channel == "telegram" else "WhatsApp"
    name = _name(name)
    cid = store.create_conversation(f"{word} · {title}" + (f" · {name}" if name else ""),
                                    origin=channel)
    store.claim_conversation(cid, ref(channel, key), name)
    return cid


def reopen(store, chat_ref: str, cid: str) -> dict | None:
    """The session, only if it is this chat's. An id from a button is a caller's word."""
    row = store.get_conversation(cid)
    if not row or (row.get("channel_ref") or "") != chat_ref:
        return None
    return row


def _back_words(store, row: dict) -> str:
    last = next((m["content"] for m in reversed(store.get_messages(row["id"]))
                 if m.get("role") == "user" and (m.get("content") or "").strip()), "")
    said = f"▶ Back in {label(row)}."
    return said + (f" You last asked: “{_short(last, 80)}”" if last else " Nothing was asked in it yet.")


def handle(store, channel: str, key, title: str, current: str, text: str,
           busy: bool = False) -> dict | None:
    """Answer a session command. None when `text` is not one.

    Returns {"say": words, "cid": the session now open ('' = unchanged), "rows": the list
    when one was shown}. The bridge points the chat at `cid`; nothing here sends.
    """
    raw = (text or "").strip()
    head, _, arg = raw.partition(" ")
    cmd = head.split("@", 1)[0].lower()
    if cmd not in COMMANDS:
        return None
    arg = arg.strip()
    chat_ref = ref(channel, key)
    rows = sessions(store, chat_ref, current)
    if cmd == "/sessions" or (cmd == "/resume" and not arg):
        return {"say": listing(rows), "cid": "", "rows": rows}
    if busy:
        return {"say": BUSY, "cid": "", "rows": []}
    if cmd == "/new":
        cur = next((r for r in rows if r["current"]), None)
        if cur and not int(cur.get("msgs") or 0) and not _name(arg):
            return {"say": "▲ This session is new already. Send me anything.", "cid": "", "rows": []}
        cid = start(store, channel, key, title, arg)
        named = _name(arg)
        return {"say": "✦ New session" + (f", {named}" if named else "")
                       + ". The one before is kept: /sessions lists them.",
                "cid": cid, "rows": [], "new": True}
    hit, why = pick(rows, arg)
    if not hit:
        return {"say": why, "cid": "", "rows": []}
    if hit["current"]:
        return {"say": "▲ That one is open already.", "cid": "", "rows": []}
    return {"say": _back_words(store, hit), "cid": hit["id"], "rows": []}


def tapped(store, channel: str, key, title: str, current: str, what: str,
           busy: bool = False) -> dict:
    """A button under the list: `new`, or a session's id."""
    if busy:
        return {"say": BUSY, "cid": ""}
    if what == "new":
        return handle(store, channel, key, title, current, "/new") or {"say": "", "cid": ""}
    row = reopen(store, ref(channel, key), what)
    if not row:
        return {"say": "▲ That session is not here any more. /sessions shows them.", "cid": ""}
    if row["id"] == current:
        return {"say": "▲ That one is open already.", "cid": ""}
    row = next((r for r in sessions(store, ref(channel, key), current) if r["id"] == what), None) \
        or {**row, "label": label(row)}
    return {"say": _back_words(store, row), "cid": row["id"]}
