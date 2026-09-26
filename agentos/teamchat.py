"""People on linked teams, writing to each other.

A link was agents reaching agents. This is the people behind them: you and whoever is on
the other team — another Bento over the same mutual-TLS link, or another account on this
machine — sending each other messages, live over each side's websocket.

Four rules keep it what it says:

- **A message is between PEOPLE.** No agent reads one: there is no tool, it is never in a
  prompt, and the `team_messages` table is opened by nothing but this module and the
  routes over it. Somebody else's words are exactly the untrusted content the taint rules
  exist for, and the simplest honest answer is that they never reach a model at all.
- **The link is the door, and each side can close it.** Only a linked team can write, over
  the pinned certificate (or, between accounts, the signed cookie); `chat_muted` on the
  receiving side's link refuses with a sentence the sender sees. A message runs nothing
  and spends nothing, so it is not a PDP decision per message — that would put every
  "hi" in the hash-chained ledger forever — but the switch that closes the door is
  audited (`link.chat`), and so is every link that opens one.
- **Nothing is lost to an unreachable peer.** A message that cannot be delivered now is
  kept, marked undelivered, and goes with the next exchange in either direction: a
  retry, the other side's next message (the answer carries what was waiting for it), or
  a pull. The id is the same on both sides, so a retry is never a duplicate.
- **Bounded.** 4,000 characters a message, 30 a minute from one link (in memory, the
  webhook ceiling's reason: a gate that costs a write is one a flood turns into a disk
  problem), and at most 500 UNREAD from one link: messages are the person's own and
  never pruned, so the only honest ceiling on a peer filling the disk is a person not
  reading — back-pressure, said to the sender in words.
- **Cleaned on the way in.** Text and names pass `teamlink.plain` where they arrive, so
  no terminal escape or bidi override reaches `bento link chat` or the TUI; the page
  escapes HTML besides. A conversation is keyed by the link's ID, never its label — a
  label is reused after a link is removed, and the old thread must not appear to be
  with the new party.

Kept free of HTTP and asyncio, so `bento link say` / `bento link chat` read and write the
same rows with the server down.
"""
from __future__ import annotations

import secrets
import time

MAX_TEXT = 4000
RATE = 30                 # messages from one link per RATE_WINDOW
RATE_WINDOW = 60.0
MAX_UNREAD = 500          # unread messages from one link before it must wait for a reader

_meter: dict = {}


def identity(cfg: dict, store, owner: str = "") -> dict:
    """Who answers for `owner`'s team: the agent's name and look, and the person's —
    the account's name on a machine with accounts, else `team.my_name`, else the
    machine's. One function, so a message sent from `bento link say` carries the same
    face and name as one sent from the desktop."""
    from . import avatars, teamlink
    from . import users as usersmod
    try:
        avatars.ensure(store, cfg)
    except Exception:
        pass
    u = usersmod.get(owner) if owner else None
    person = ((u.get("display") or u.get("name")) if u else
              ((cfg.get("team") or {}).get("my_name") or teamlink.machine_name(cfg)))
    return {"agent_name": cfg.get("agent_name") or "Aria", "person": person,
            "agent": avatars.recipe_for(store, avatars.AGENT), "me": avatars.recipe_for(store, avatars.ME)}


def new_message(text: str, identity: dict | None) -> dict:
    """A message from this person, carrying who they are (name + look) — the identity
    the other side paints beside it."""
    from .teamlink import plain
    if len(str(text or "").strip()) > MAX_TEXT:
        raise ValueError(f"a message is at most {MAX_TEXT} characters")
    t = plain(text, MAX_TEXT)
    if not t:
        raise ValueError("say something first")
    ident = identity or {}
    return {"id": secrets.token_hex(8), "text": t, "ts": time.time(),
            "sender": plain(ident.get("person"), 40, newlines=False) or "someone",
            "look": ident.get("me") or {}}


def clean_message(m) -> dict:
    """What arrived, held to the shape: an id, a sender name, a look from the closed
    set, the text cut to size. Anything else in it is dropped, not stored."""
    from . import avatars
    from .teamlink import plain
    if not isinstance(m, dict):
        raise ValueError("not a message")
    mid = str(m.get("id") or "")
    if not (8 <= len(mid) <= 64) or not mid.replace("-", "").replace("_", "").isalnum():
        raise ValueError("a message needs an id")
    text = plain(m.get("text"), MAX_TEXT)
    if not text:
        raise ValueError("an empty message")
    try:
        ts = float(m.get("ts") or time.time())
    except (TypeError, ValueError):
        ts = time.time()
    return {"id": mid, "text": text, "ts": min(ts, time.time() + 60),
            "sender": plain(m.get("sender"), 40, newlines=False) or "someone",
            "look": avatars.clean(m.get("look")) if isinstance(m.get("look"), dict) else {}}


def overflowing(owner: str, link_id: str) -> bool:
    """True once this link has written RATE messages in the last minute."""
    now = time.time()
    key = (owner or "", link_id)
    hits = [t for t in _meter.get(key, []) if t > now - RATE_WINDOW]
    if len(hits) >= RATE:
        _meter[key] = hits
        return True
    hits.append(now)
    _meter[key] = hits
    return False


def receive(store, owner: str, lk: dict, m) -> tuple[dict | None, str]:
    """A message arriving on link `lk`. Returns (the stored message, '') or (None, why)."""
    if lk.get("chat_muted"):
        return None, "they are not taking messages on this link"
    if overflowing(owner, lk["id"]):
        return None, "too many messages in a minute — slow down"
    if store.team_unread(lk["id"]) >= MAX_UNREAD:
        return None, f"they have {MAX_UNREAD} unread messages from you — wait until they catch up"
    try:
        msg = clean_message(m)
    except ValueError as e:
        return None, str(e)
    if not store.team_msg_add(lk["id"], msg, "in"):
        return None, ""                               # already here: a retry, not an error
    return {**msg, "dir": "in", "link": lk["label"], "read": 0}, ""


def threads(store, links: list[dict]) -> list[dict]:
    """One row per link — the people you can write to — newest conversation first."""
    got = store.team_threads()
    out = []
    for lk in links:
        t = got.get(lk["id"]) or {}
        out.append({"label": lk["label"], "kind": lk.get("kind"), "muted": bool(lk.get("chat_muted")),
                    "reachable": lk.get("kind") == "account" or bool(lk.get("url")),
                    "identity": lk.get("peer_identity") or {},
                    "unread": t.get("unread", 0), "last": t.get("last")})
    out.sort(key=lambda r: -((r["last"] or {}).get("ts") or 0))
    return out
