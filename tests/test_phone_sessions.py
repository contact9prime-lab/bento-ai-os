"""A phone chat keeps several sessions: start a new one, go back to an earlier one.

Asked for as "Telegram and WhatsApp should have an option of starting new session or
reverting to existing sessions". Before, a chat had one conversation and /clear deleted it.
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import executors, phonesessions, telegram_admin, whatsapp   # noqa: E402
from agentos.memory import Store                                         # noqa: E402


def _tg(tmp_path, monkeypatch):
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    cfg = {"agent_name": "Aria", "autonomy": "full",
           "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 5}}
    store = Store(tmp_path / "a.db")
    sent, asked = [], []

    async def bc(ev):
        pass
    b = TelegramBridge(cfg, store, Toolbox(cfg, store), bc)
    for chat in (5, 6):
        store.tg_upsert_chat(chat, f"P{chat}", "", "private")
        store.tg_set_allowed(chat, 1)

    async def api(method, **kw):
        sent.append({"method": method, **kw})
        return {}
    b._api = api
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")

    async def fake_forward(engine, text, cfg, ws, emit=None, session_id="", **kw):
        # stands in for Claude Code: a new session when it is given none, else the same one
        asked.append((text, session_id))
        return f"answer to {text}", types.SimpleNamespace(session_id=session_id or f"cc-{len(asked)}")
    monkeypatch.setattr(executors, "forward", fake_forward)
    return b, sent, asked


def _say(b, chat, text):
    asyncio.run(b._handle({"chat": {"id": chat, "type": "private"}, "from": {"first_name": f"P{chat}"},
                           "text": text}))


def _tap(b, chat, data, who=None):
    asyncio.run(b._handle_callback({"id": "q", "data": data, "from": {"id": who or chat},
                                    "message": {"chat": {"id": chat}, "message_id": 1}}))


def _open(b, chat):
    return next(c for c in b.store.tg_list_chats() if c["chat_id"] == chat)["conversation_id"]


def _texts(sent):
    return [s.get("text", "") for s in sent]


def test_a_new_session_keeps_the_old_one_and_resume_brings_it_back(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    _say(b, 5, "plan my trip to Kyoto")
    first = _open(b, 5)
    _say(b, 5, "/new invoices")
    second = _open(b, 5)
    assert second != first, "a new conversation, not the old one emptied"
    assert len(b.store.get_messages(first)) == 2, "the session before keeps what was said"
    _say(b, 5, "chase the March invoice")
    assert asked[-1] == ("chase the March invoice", ""), "a new session starts a new Claude Code session"

    _say(b, 5, "/sessions")
    listing = sent[-1]
    assert "▶ 1. invoices" in listing["text"] and "2. “plan my trip to Kyoto”" in listing["text"]
    buttons = [r[0]["callback_data"] for r in listing["reply_markup"]["inline_keyboard"]]
    assert buttons == [f"ss:{first}", "ss:new"], "a button for each other session, and a new one"

    _say(b, 5, "/resume 2")
    assert _open(b, 5) == first
    assert "You last asked: “plan my trip to Kyoto”" in sent[-1]["text"]
    _say(b, 5, "and the hotel?")
    assert asked[-1] == ("and the hotel?", "cc-1"), "back in the session Claude Code remembers"
    assert [m["content"] for m in b.store.get_messages(first)][-2:] == ["and the hotel?", "answer to and the hotel?"]
    assert len(b.store.get_messages(second)) == 2, "nothing of it went into the other session"


def test_a_session_is_reopened_by_its_name_or_a_tap(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    _say(b, 5, "hello")
    first = _open(b, 5)
    _say(b, 5, "/new invoices")
    second = _open(b, 5)
    _tap(b, 5, f"ss:{first}")
    assert _open(b, 5) == first
    _say(b, 5, "/resume invoi")
    assert _open(b, 5) == second
    _say(b, 5, "/resume 9")
    assert "no session 9" in sent[-1]["text"] and _open(b, 5) == second
    _say(b, 5, "chase the March invoice")
    _tap(b, 5, "ss:new")
    assert _open(b, 5) not in (first, second)
    _say(b, 5, "/new")
    assert "new already" in sent[-1]["text"], "empty sessions do not pile up"


def test_a_chat_reaches_only_its_own_sessions(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    _say(b, 5, "the owner's private question")
    owners = _open(b, 5)
    _say(b, 6, "hello from a colleague")
    theirs = _open(b, 6)
    # a colleague's chat may use sessions, though it is not the owner's
    _say(b, 6, "/sessions")
    assert "private question" not in sent[-1]["text"] and "hello from a colleague" in sent[-1]["text"]
    # an id is a caller's word: another chat's session is not reopened by naming it
    _tap(b, 6, f"ss:{owners}")
    assert _open(b, 6) == theirs
    assert "not here any more" in sent[-1]["text"]
    # and a chat that was never let in has no buttons at all
    b.store.tg_upsert_chat(7, "Stranger", "", "private")
    n = len(sent)
    _tap(b, 7, "ss:new")
    assert [s for s in sent[n:] if s["method"] == "sendMessage"] == []
    assert not next(c for c in b.store.tg_list_chats() if c["chat_id"] == 7).get("conversation_id")


def test_a_session_is_not_switched_under_a_running_turn(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    _say(b, 5, "hello")
    first = _open(b, 5)
    b._busy_chats.add(5)
    _say(b, 5, "/new")
    assert sent[-1]["text"] == phonesessions.BUSY and _open(b, 5) == first
    _say(b, 5, "/sessions")
    assert "Your sessions here" in sent[-1]["text"], "looking is fine while it works"


def test_a_chat_from_before_sessions_keeps_its_conversation(tmp_path):
    store = Store(tmp_path / "a.db")
    old = store.create_conversation("Telegram · PC", origin="telegram")    # no channel_ref yet
    store.add_message(old, "user", "an old question")
    res = phonesessions.handle(store, "telegram", 5, "PC", old, "/sessions")
    assert [r["id"] for r in res["rows"]] == [old] and res["rows"][0]["current"]
    # once it is one chat's, another chat cannot claim it
    store.claim_conversation(old, "telegram:6")
    assert store.get_conversation(old)["channel_ref"] == "telegram:5"


def test_the_commands_are_offered_to_every_enabled_chat():
    names = {c["command"] for c in telegram_admin.menu(False)}
    assert {"new", "sessions", "resume"} <= names
    assert {c[1:] for c in phonesessions.COMMANDS} <= telegram_admin._BRIDGE_OWNED


def test_whatsapp_has_the_same_sessions(tmp_path, monkeypatch):
    store = Store(tmp_path / "a.db")
    cfg = {"agent_name": "Aria", "whatsapp": {"mode": "baileys", "enabled": True, "owner_wa_id": "44"}}
    said, turns = [], []

    async def bc(ev):
        pass
    b = whatsapp.WhatsAppBridge(cfg, store, types.SimpleNamespace(fabric=None), bc)

    async def send(text, wa_id=None, quiet=False):
        said.append(text)
        return "sent"

    async def turn(chat, wa_id, text):
        cid = b._conversation(chat)
        turns.append(cid)
        store.add_message(cid, "user", text)
    monkeypatch.setattr(b, "send", send)
    monkeypatch.setattr(b, "_turn", turn)
    store.wa_upsert_chat("44", "PC")
    store.wa_set_allowed("44", 1)
    n = [0]

    def msg(text):
        n[0] += 1
        asyncio.run(b._one({"from": "44", "id": f"m{n[0]}", "type": "text", "text": {"body": text}},
                           {"contacts": [{"wa_id": "44", "profile": {"name": "PC"}}]}))
    msg("what sells in March")
    msg("/new pricing")
    msg("draft the price list")
    assert turns[0] != turns[1]
    msg("/sessions")
    assert "▶ 1. pricing" in said[-1] and "2. “what sells in March”" in said[-1]
    msg("/resume 2")
    assert "Back in “what sells in March”" in said[-1]
    msg("and in April?")
    assert turns[2] == turns[0]
    assert store.get_conversation(turns[1])["channel_ref"] == "whatsapp:44"
