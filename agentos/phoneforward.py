"""From the desktop to your phone: carry a chat on there, send a reply, send a story.

Asked for as "have a chat response to continue in the Telegram, send the stage to Telegram
or WhatsApp … only users' chats to their own accounts. The user can decide which Telegram
chat it needs to forward to, or to WhatsApp."

Three things can leave, each to one chat the person picks (and `mirror` sends a desk turn
to the phone chat whose session it is, on its own, below):

  * `continue`: the chat becomes a session of that phone chat (phonesessions.py) and the
    phone is pointed at it, so the next message there carries on with its whole history
    and the agent CLI's own session;
  * `reply`: one answer, as text;
  * `stage`: one story, as the pictures and video a phone turn gets (`send_stage`).

Four rules:

  * It is a person's act. There is no agent tool for it: an agent that could forward a
    chat could be talked into it by a page it read.
  * Only your own. The conversation is read from the caller's store and the bridges are
    the caller's (accounts are separate homes), and the chat must be one of `targets()`:
    the owner's chat, a person who was let in, a group that is answered. A chat id from a
    page is a caller's word, so it is looked up again here.
  * A chat that is another phone chat's session is never moved (`claim_conversation`).
  * Nothing is switched until the message got there.
"""
from __future__ import annotations

from . import phonesessions

WHATS = ("continue", "reply", "stage")
REPLY_MAX = 12000
TAIL = 600


def _short(text: str, n: int) -> str:
    return phonesessions._short(text, n)


def _tg_targets(tg) -> list[dict]:
    t = tg._t()
    if not (t.get("enabled") and t.get("bot_token")):
        return []
    owner = t.get("owner_chat_id") or 0
    groups_on = tg.groups_on()
    out = []
    for c in tg.store.tg_list_chats():
        private = (c.get("type") or "private") == "private"
        mine = c["chat_id"] == owner
        if not (mine or c.get("allowed")) or (not private and not groups_on):
            continue
        out.append({"channel": "telegram", "to": str(c["chat_id"]),
                    "name": c.get("title") or (("@" + c["username"]) if c.get("username") else str(c["chat_id"])),
                    "kind": "you" if mine else ("person" if private else "group"),
                    "ready": True, "why": "", "busy": c["chat_id"] in tg._busy_chats})
    if owner and not any(x["kind"] == "you" for x in out):
        out.insert(0, {"channel": "telegram", "to": str(owner), "name": "Your Telegram", "kind": "you",
                       "ready": True, "why": "", "busy": owner in tg._busy_chats})
    return out


def _wa_targets(wa) -> list[dict]:
    c = wa._c()
    if not c.get("enabled"):
        return []
    owner = str(c.get("owner_wa_id") or "")
    out = []
    for ch in wa.store.wa_list_chats():
        mine = str(ch["wa_id"]) == owner
        if not (mine or ch.get("allowed")):
            continue
        why = wa._refusal(c, str(ch["wa_id"]))
        out.append({"channel": "whatsapp", "to": str(ch["wa_id"]),
                    "name": ch.get("name") or ("+" + str(ch["wa_id"])),
                    "kind": "you" if mine else "person", "ready": not why,
                    "why": why.replace("[error] ", "").strip(), "busy": bool(wa._busy)})
    return out


def targets(tg, wa) -> list[dict]:
    """Every chat of this account something may be sent to, yours first."""
    rows = []
    for fn, bridge in ((_tg_targets, tg), (_wa_targets, wa)):
        try:
            rows += fn(bridge) if bridge else []
        except Exception:
            pass
    rows.sort(key=lambda r: (r["channel"], {"you": 0, "person": 1, "group": 2}[r["kind"]]))
    return rows


def _last_reply(store, cid: str, mid: str = "") -> dict | None:
    msgs = [m for m in store.get_messages(cid)
            if m.get("role") == "assistant" and (m.get("content") or "").strip()]
    if mid:
        return next((m for m in msgs if m.get("id") == mid), None)
    return msgs[-1] if msgs else None


def stories_of(store, cid: str) -> list[dict]:
    """The stories this chat showed, newest last: what `stage` can send."""
    from . import stage as stagemod
    out = []
    for st in stagemod.stories(store, cid):
        if st.get("scenes"):
            out.append({"answer_to": st["answer_to"], "scenes": len(st["scenes"]),
                        "question": stagemod.question_of(store, st["answer_to"])})
    return out


def options(store, tg, wa, cid: str) -> dict:
    """What the dialog shows for one chat: where it may go and what there is to send."""
    conv = store.get_conversation(cid) if cid else None
    reply = _last_reply(store, cid) if conv else None
    return {"targets": targets(tg, wa),
            "title": (conv or {}).get("title") or "",
            "session_of": (conv or {}).get("channel_ref") or "",
            "reply": _short((reply or {}).get("content") or "", 140),
            "stories": stories_of(store, cid) if conv else []}


async def send(store, tg, wa, channel: str, to: str, what: str, cid: str,
               mid: str = "", answer_to: str = "") -> dict:
    """Send it. {"ok", "message"}: the sentence is what the person reads."""
    if what not in WHATS:
        return {"ok": False, "message": "I can send a reply, a story, or carry the chat on there."}
    conv = store.get_conversation(cid) if cid else None
    if not conv:
        return {"ok": False, "message": "That chat isn't here any more."}
    tgt = next((t for t in targets(tg, wa) if t["channel"] == channel and t["to"] == str(to)), None)
    if not tgt:
        return {"ok": False, "message": "That isn't one of your chats. Pick one from the list."}
    if not tgt["ready"]:
        return {"ok": False, "message": tgt["why"] or "That chat can't be reached right now."}
    bridge = tg if channel == "telegram" else wa
    key = int(to) if channel == "telegram" else str(to)
    word = "Telegram" if channel == "telegram" else "WhatsApp"
    title = _short(conv.get("title") or "a chat", 60)

    if what == "reply":
        m = _last_reply(store, cid, mid)
        if not m:
            return {"ok": False, "message": "There is no answer in this chat to send yet."}
        text = m["content"]
        if len(text) > REPLY_MAX:
            text = text[:REPLY_MAX].rsplit("\n", 1)[0] + "\n\n… (the rest is in the chat on your desktop)"
        res = await bridge.send(f"▶ From your desktop chat “{title}”\n\n{text}", key)
        if str(res).startswith("[error]"):
            return {"ok": False, "message": str(res).replace("[error] ", "")}
        return {"ok": True, "message": f"Sent the answer to {tgt['name']} on {word}."}

    if what == "stage":
        from . import stage as stagemod
        ans = answer_to or next((s["answer_to"] for s in reversed(stories_of(store, cid))), "")
        if not ans or not stagemod.story(store, cid, ans):
            return {"ok": False, "message": "This chat has no story to send."}
        res = await bridge.send_stage(cid, "", key, ans=ans)
        if str(res).startswith("[error]") or not res:
            return {"ok": False, "message": str(res or "The story could not be sent.").replace("[error] ", "")}
        return {"ok": True, "message": f"Sent the story to {tgt['name']} on {word}."}

    # continue: this chat becomes a session of that phone chat, and the phone is pointed at it
    ref = phonesessions.ref(channel, key)
    was = conv.get("channel_ref") or ""
    if was and was != ref:
        return {"ok": False, "message": "This chat is a session of another phone chat, and a session stays "
                                        "with its chat. You can send its answer or its story there."}
    if tgt["busy"]:
        return {"ok": False, "message": f"{tgt['name']} is being answered right now. Try again when that is done."}
    rows = store.tg_list_chats() if channel == "telegram" else store.wa_list_chats()
    row = next((c for c in rows if str(c.get("chat_id", c.get("wa_id"))) == str(key)), None)
    if row is None and channel == "telegram":      # the owner's chat, before it ever wrote a row
        row = store.tg_upsert_chat(key, tgt["name"], "", "private")
    if row is None:
        return {"ok": False, "message": "That chat has not written here yet."}
    cur = row.get("conversation_id") or ""
    last = _last_reply(store, cid)
    n = len(store.get_messages(cid))
    said = (f"▶ Carrying on “{title}” from your desktop, {n} message{'' if n == 1 else 's'} so far."
            + (f"\n\nThe last answer:\n{_short(last['content'], TAIL)}" if last else "")
            + "\n\nSay anything here to continue. /sessions lists your other sessions.")
    if cur == cid:
        said = f"▶ “{title}” is the session open here already. Say anything to continue."
    res = await bridge.send(said, key)
    if str(res).startswith("[error]"):
        return {"ok": False, "message": str(res).replace("[error] ", "")}
    store.claim_conversation(cid, ref)
    (store.tg_set_conversation if channel == "telegram" else store.wa_set_conversation)(key, cid)
    store.db.commit()
    store.log(channel, f"session carried on from the desktop for {tgt['name']}",
              {"chat": str(key), "conversation_id": cid})
    return {"ok": True, "switched": True,
            "message": f"{tgt['name']} on {word} now carries this chat on. The session it had is kept."}


def _chat_of(ref: str) -> tuple[str, str]:
    """('telegram', '1145038494') from a session's channel_ref, or ('', '')."""
    channel, _, to = (ref or "").partition(":")
    return (channel, to) if channel in ("telegram", "whatsapp") and to else ("", "")


async def mirror(store, tg, wa, cid: str, asked: str, answer: str) -> dict:
    """A turn typed at the desk in a phone chat's session, sent to that phone chat too.

    Asked for as "if the chat is initiated in Telegram and then I chat on the Bento OS
    and then go back to Telegram, the experience is not seamless": the desktop showed
    every phone message, the phone saw nothing of the desk. The owner chose every turn
    live. Only when the phone chat is on this session right now (a session it has left
    stays where it is), only to one of `targets()`, and a closed WhatsApp window is
    said in the diary rather than tried. {"ok", "why"} for the log and the tests."""
    conv = store.get_conversation(cid) if cid else None
    channel, to = _chat_of((conv or {}).get("channel_ref") or "")
    if not channel or not (answer or "").strip():
        return {"ok": False, "why": "not a phone chat's session"}
    rows = store.tg_list_chats() if channel == "telegram" else store.wa_list_chats()
    row = next((c for c in rows if str(c.get("chat_id", c.get("wa_id"))) == to), None)
    if not row or (row.get("conversation_id") or "") != cid:
        return {"ok": False, "why": "the phone chat is on another session"}
    tgt = next((t for t in targets(tg, wa) if t["channel"] == channel and t["to"] == to), None)
    if not tgt:
        return {"ok": False, "why": "that chat can't be sent to from here"}
    if not tgt["ready"]:
        store.log(channel, f"a desk turn wasn't sent to {tgt['name']}: {tgt['why']}"[:300],
                  {"conversation_id": cid, "chat": to})
        return {"ok": False, "why": tgt["why"]}
    bridge = tg if channel == "telegram" else wa
    key = int(to) if channel == "telegram" else to
    text = answer
    if len(text) > REPLY_MAX:
        text = text[:REPLY_MAX].rsplit("\n", 1)[0] + "\n\n… (the rest is in the chat on your desktop)"
    for part in (f"💻 You, at the desk:\n{_short(asked, TAIL)}", text):
        res = await bridge.send(part, key)
        if str(res).startswith("[error]"):
            store.log(channel, f"a desk turn wasn't sent to {tgt['name']}: {res}"[:300],
                      {"conversation_id": cid, "chat": to})
            return {"ok": False, "why": str(res).replace("[error] ", "")}
    return {"ok": True, "why": ""}


def new_session(store, tg, wa, channel: str, to: str, name: str = "") -> dict:
    """A new session for one of your phone chats, started at the desktop. The phone stays
    where it is: /sessions there lists this one, and Send → Carry on opens it there."""
    tgt = next((t for t in targets(tg, wa) if t["channel"] == channel and t["to"] == str(to)), None)
    if not tgt:
        return {"ok": False, "message": "That isn't one of your chats."}
    key = int(to) if channel == "telegram" else str(to)
    cid = phonesessions.start(store, channel, key, tgt["name"], name)
    return {"ok": True, "id": cid}


def mark(store, convs: list[dict]) -> list[dict]:
    """Each conversation that is a phone chat's session gets `phone`: which chat, what the
    session is called, and whether it is the one open on the phone. The desktop's Channels
    tab groups by it, so a chat with several sessions shows all of them."""
    if not any(c.get("channel_ref") for c in convs):
        return convs
    chats = {}
    try:
        for c in store.tg_list_chats():
            chats[phonesessions.ref("telegram", c["chat_id"])] = (c.get("title") or str(c["chat_id"]), c.get("conversation_id") or "")
        for c in store.wa_list_chats():
            chats[phonesessions.ref("whatsapp", c["wa_id"])] = (c.get("name") or "+" + str(c["wa_id"]), c.get("conversation_id") or "")
    except Exception:
        pass
    out = []
    for c in convs:
        ref = c.get("channel_ref") or ""
        if ref:
            channel, _, key = ref.partition(":")
            name, cur = chats.get(ref, (key, ""))
            first = ""
            if not c.get("channel_name"):       # an unnamed session is called by what it opened with
                r = store.db.execute("SELECT content FROM messages WHERE conversation_id=? AND role='user' "
                                     "ORDER BY created_at LIMIT 1", (c["id"],)).fetchone()
                first = r[0] if r else ""
            c = {**c, "phone": {"channel": channel, "to": key, "chat": name,
                                "session": c.get("channel_name") or "", "open": cur == c["id"],
                                "label": phonesessions.label({"channel_name": c.get("channel_name"), "first": first})}}
        out.append(c)
    return out
