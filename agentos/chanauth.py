"""Who may talk to the agent, on every channel, in one list.

Asked for as "we need a separate section of Authorization for all the channels, so it's
easier": the requests were spread over the Telegram app's two tables and the WhatsApp
card, and a group that wrote in sat somewhere nobody looked. This is the one reading of
those rows. Settings → Channels → Authorization, `/api/channels/authorization` and
`bento channels who` all draw it, so they cannot disagree about what is waiting.

Nothing is stored here: Telegram's chats are `telegram_chats`, WhatsApp's are
`whatsapp_chats`, and a decision still goes through each bridge's own
`decide_newcomer` (which tells the person they are in). Kept free of HTTP and asyncio,
so the terminal reads it with the server down.
"""
from __future__ import annotations

#: the words each state is shown with
STATES = {"waiting": "waiting for you", "allowed": "let in", "blocked": "blocked"}


def state_of(row: dict) -> str:
    """A row nobody decided is waiting. Allowed is allowed. Decided and not allowed is
    blocked. An old row with no decision recorded and not allowed reads as waiting too:
    nobody ever said no to it."""
    if row.get("allowed"):
        return "allowed"
    return "blocked" if row.get("decided_at") else "waiting"


def _tg(store, cfg: dict) -> list[dict]:
    owner = int(((cfg or {}).get("telegram") or {}).get("owner_chat_id") or 0)
    out = []
    for c in store.tg_list_chats():
        group = (c.get("type") or "private") != "private"
        out.append({
            "channel": "telegram", "kind": "group" if group else "person",
            "id": str(c["chat_id"]), "ref": f"tg:{c['chat_id']}",
            "name": c.get("title") or str(c["chat_id"]),
            "handle": ("@" + c["username"]) if c.get("username") else "",
            "owner": c["chat_id"] == owner,
            "state": state_of(c), "decided_at": c.get("decided_at"),
            "decided_by": c.get("decided_by") or "", "messages": c.get("msg_count") or 0,
            "last_seen": c.get("last_seen"),
            "members": len(store.members("telegram", c["chat_id"])) if group else 0,
        })
    return out


def _wa(store, cfg: dict) -> list[dict]:
    wa = (cfg or {}).get("whatsapp") or {}
    owner = str(wa.get("owner_wa_id") or "")
    out = []
    for c in store.wa_list_chats():
        group = (c.get("kind") or "") == "group"
        out.append({
            "channel": "whatsapp", "kind": "group" if group else "person",
            "id": c["wa_id"], "ref": f"wa:{c['wa_id']}",
            "name": c.get("name") or (c["wa_id"] if group else "+" + c["wa_id"]),
            "handle": "" if group else "+" + c["wa_id"],
            "owner": c["wa_id"] == owner,
            "state": state_of(c), "decided_at": c.get("decided_at"),
            "decided_by": c.get("decided_by") or "", "messages": c.get("msg_count") or 0,
            "last_seen": c.get("last_seen"),
            "members": len(store.members("whatsapp", c["wa_id"])) if group else 0,
        })
    return out


def rows(store, cfg: dict) -> list[dict]:
    """Every person and group that reached a channel, waiting first, then newest. The
    owner's own chat is left out: it is the one that decides."""
    order = {"waiting": 0, "blocked": 1, "allowed": 2}
    out = [r for r in _tg(store, cfg) + _wa(store, cfg) if not r["owner"]]
    out.sort(key=lambda r: (order[r["state"]], -(r["last_seen"] or 0)))
    return out


def summary(items: list[dict]) -> dict:
    return {s: sum(1 for r in items if r["state"] == s) for s in STATES}


def split_ref(ref: str) -> tuple[str, str]:
    """'tg:-100123' → ('telegram', '-100123'); 'wa:4477…' → ('whatsapp', '4477…')."""
    kind, _, key = (ref or "").partition(":")
    channel = {"tg": "telegram", "wa": "whatsapp"}.get(kind.strip().lower(), "")
    if not channel or not key.strip():
        raise ValueError("a request is tg:<chat id> or wa:<number or group id>")
    key = key.strip()
    if channel == "telegram":
        int(key)        # a Telegram chat id is a number, a group's is negative
    return channel, key


def decide(store, ref: str, allow: bool, by: str) -> str:
    """Record a decision straight in the database (the terminal, with or without the
    server). The person is not told here; the bridges' own door does that when the
    server makes the decision."""
    channel, key = split_ref(ref)
    if channel == "telegram":
        if not any(str(c["chat_id"]) == key for c in store.tg_list_chats()):
            return "nobody by that id wrote on Telegram"
        store.tg_set_allowed(int(key), 1 if allow else 0, by)
    else:
        if not store.wa_get_chat(key):
            return "nobody by that id wrote on WhatsApp"
        store.wa_set_allowed(key, 1 if allow else 0, by)
    store.log(channel, f"{'allowed' if allow else 'blocked'} {ref} ({by})",
              {"ref": ref, "allowed": allow, "by": by})
    return "allowed" if allow else "blocked"
