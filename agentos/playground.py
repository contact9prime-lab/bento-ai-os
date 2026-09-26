"""The playground off the desktop: who talked, and who is working right now.

The Office animates two kinds of truth. This module holds them for the surfaces
that cannot run the Office — a Telegram chat, a terminal — so that every face of
the OS tells the same story in its own medium:

- **What was said, in one conversation.** `listen(cid)` opens a tap; every agent
  talking in that conversation (an `agent_msg` ask or reply, an `agent_say` huddle
  turn) lands in it as it is broadcast, and `close()` hands the lines back. The
  Telegram bridge opens one around a turn and, if agents talked, sends the exchange
  as a comic strip (comic.strip). The tap is fed from the ONE place every such event
  already passes — the server's broadcast — so there is no second path for talk to
  travel and none to forget.
- **Who is doing what, now.** `rollcall()` is the office plan with each person's
  state read from the machine: a specialist is BUSY while it has a run open in
  `fabric_runs` (and what that run was asked is what it is doing); the lead is busy
  while a turn is running. It feeds the Telegram `/office` picture and `bento
  office`, so the phone and the terminal cannot disagree about who is at work.

Nothing here invents activity. A run left `running` by a crash is not work, so a
run older than STALE_S is not counted; an agent with nothing open is free, and
says so.

In memory and stdlib only, like the other playground modules: the tap is a list per
listener with a ceiling, because a conversation nobody closes must not grow forever.
"""
from __future__ import annotations

import time

from . import office

TALK = ("agent_msg", "agent_say")
MAX_LINES = 40              # a tap keeps this many lines; a strip draws far fewer
STALE_S = 3600              # an open run older than this is a crash's leftover, not work

_TAPS: dict[str, list[list]] = {}


def listen(cid: str) -> list:
    """Open a tap on one conversation. Returns the list that fills as agents talk."""
    buf: list = []
    if cid:
        _TAPS.setdefault(cid, []).append(buf)
    return buf


def close(cid: str, buf: list) -> list:
    taps = _TAPS.get(cid) or []
    if buf in taps:
        taps.remove(buf)
    if not taps:
        _TAPS.pop(cid, None)
    return buf


def observe(event: dict) -> None:
    """Called by the server's broadcast with every event; keeps only agents talking,
    and only for a conversation somebody is listening to. Cheap when nobody is."""
    if not _TAPS or not isinstance(event, dict) or event.get("type") not in TALK:
        return
    taps = _TAPS.get(event.get("conversation_id") or "")
    if not taps:
        return
    line = line_of(event)
    if not line:
        return
    for buf in taps:
        if len(buf) < MAX_LINES:
            buf.append(line)


def line_of(event: dict) -> dict | None:
    """One talk event as a line of a comic: who speaks, to whom, what they said."""
    if event.get("type") == "agent_say":
        who, to = event.get("speaker"), event.get("to") or ""
    elif event.get("phase") == "ask":
        who, to = event.get("from"), event.get("to") or ""
    else:                                   # a reply: said by the one who was asked
        who, to = event.get("from"), event.get("to") or ""
    text = " ".join(str(event.get("text") or "").split())
    if not who or not text:
        return None
    return {"speaker": str(who), "to": str(to), "text": text[:600],
            "kind": "ask" if event.get("phase") == "ask" else "say"}


def caption(lines: list[dict], limit: int = 1000) -> str:
    """Every word, in text: the picture carries only what the pixel font can draw
    and only as many lines as fit, and the caption is where the rest always is."""
    out = []
    for ln in lines:
        arrow = f" → {ln['to']}" if ln.get("to") and ln.get("kind") == "ask" else ""
        out.append(f"{ln['speaker']}{arrow}: {ln['text']}")
    s = "\n".join(out)
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def rollcall(store, cfg: dict, lead_busy: bool | None = False, now: float | None = None) -> list[dict]:
    """The office, room by room, with each person's state: [{room, color, key, label,
    working, doing}]. Busy is a run open in the ledger of runs, never a guess.

    `lead_busy=None` means the caller cannot know: a chat turn is visible only inside
    the running server, so `bento office` (another process) marks the lead `unknown`
    rather than calling it free."""
    now = now or time.time()
    v = office.view(cfg, store)
    open_runs: dict[str, str] = {}
    try:
        rows = store.db.execute(
            "SELECT ref, input FROM fabric_runs WHERE status='running' AND started_at>? "
            "ORDER BY started_at", (now - STALE_S,)).fetchall()
        for ref, task in rows:
            if ref:
                open_runs[str(ref).lower()] = " ".join(str(task or "").split())[:120]
    except Exception:
        pass
    out = []
    for r in v["rooms"]:
        if r["kind"] in ("meeting", "lounge"):
            continue
        for m in r["members"]:
            if m == "@agent":
                out.append({"room": r["name"], "color": r["color"], "key": m,
                            "label": (cfg or {}).get("agent_name") or "Aria",
                            "working": bool(lead_busy), "doing": "",
                            "unknown": lead_busy is None})
                continue
            doing = open_runs.get(m.lower())
            out.append({"room": r["name"], "color": r["color"], "key": m, "label": m,
                        "working": doing is not None, "doing": _task_line(doing or "")})
    return out


def _task_line(task: str) -> str:
    """A run's input is its whole brief; the first sentence is what it is doing."""
    t = task.split("\n")[0]
    for stop in (". ", "? ", "! "):
        if stop in t:
            t = t.split(stop)[0]
    return t[:80]


def rollcall_text(rows: list[dict]) -> str:
    """The roll call in words — the caption under the picture, and the terminal's."""
    lines, room = [], None
    for r in rows:
        if r["room"] != room:
            room = r["room"]
            lines.append(room)
        state = (f"busy — {r['doing']}" if r["working"] and r["doing"] else "busy" if r["working"]
                 else "not visible from here (a chat turn shows on the desktop)" if r.get("unknown") else "free")
        lines.append(f"  {r['label']}: {state}")
    busy = sum(1 for r in rows if r["working"])
    unknown = any(r.get("unknown") for r in rows)
    lines.append(f"{busy} of {len(rows)} at work" if busy
                 else "No specialist has work open." if unknown else "Everybody is free.")
    return "\n".join(lines)
