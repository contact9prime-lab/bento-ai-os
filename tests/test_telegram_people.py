"""Telegram: the Stage reaches the phone, the owner is asked about newcomers, and phone
chats have their own place in Chats.

Reported as "when I am typing on Telegram I am not getting the stage, I am not getting an
option to authorize other people on Telegram, and the telegram chats are not visible in
the Chats". Measured on a copy of the owner's home against a stand-in Telegram server:
before, a Nifty question was answered in words with no scenes, because the Stage line
said "the person watches your answers on the Stage", untrue on a phone; after, the reply
was followed by the story as a document. A stranger's first message now asks the owner
with Allow / Block, and the desktop's Allow tells them they're in.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent


def test_a_phone_turn_is_told_where_its_scenes_go():
    from agentos import stage
    assert "phone" not in stage.note({})
    tg = stage.note({}, surface="telegram")
    assert "Telegram" in tg and "sent to them as one page right after your reply" in tg
    assert "WhatsApp" in stage.note({}, surface="whatsapp")
    door = (ROOT / "agentos/executors.py").read_text()
    assert 'tool="mcp__bento__show_scene", surface=surface' in door
    wa = (ROOT / "agentos/whatsapp.py").read_text()
    assert "await self.send_stage(cid, reply, wa_id)" in wa


def test_the_owner_is_asked_about_somebody_new(tmp_path):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    store = Store(tmp_path / "a.db")
    cfg = {"agent_name": "Aria", "telegram": {"bot_token": "1:T", "owner_chat_id": 111}}
    calls, events = [], []

    async def bc(ev):
        events.append(ev)
    tb = TelegramBridge.__new__(TelegramBridge)
    tb.cfg, tb.store, tb.broadcast = cfg, store, bc

    async def api(method, **kw):
        calls.append((method, kw))
        return {}

    async def send(text, chat_id=None):
        calls.append(("send", {"chat_id": chat_id, "text": text}))
    tb._api, tb.send = api, send
    store.tg_upsert_chat(222, "Ravi", "ravi_k", "private")
    asyncio.run(tb.ask_owner_about(222, "Ravi", "ravi_k", "hi"))
    m, kw = next(c for c in calls if c[0] == "sendMessage")
    assert kw["chat_id"] == 111 and "Ravi (@ravi_k) wants to talk to Aria" in kw["text"]
    buttons = kw["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == ["who:222:1", "who:222:0"]
    assert events and events[-1]["type"] == "telegram_request"
    assert asyncio.run(tb.decide_newcomer(222, True)) == "allowed"
    assert any(c[0] == "send" and c[1]["chat_id"] == 222 and "You're in" in c[1]["text"] for c in calls)
    src = (ROOT / "agentos/telegram.py").read_text()
    cb = src[src.index("async def _handle_callback("):][:1600]
    assert 'data.startswith("who:")' in cb and "decide_newcomer" in cb
    assert cb.index("owner_chat_id") < cb.index('"who:"'), "only the owner's buttons count"
    srv = (ROOT / "agentos/server.py").read_text()
    assert "await tg.decide_newcomer(chat_id, bool(body[\"allowed\"]))" in srv


def test_phone_chats_have_their_own_tab():
    chat = (ROOT / "agentos/ui/src/js/10-chat.js").read_text()
    # its own tab now (chattabs.py): Chat → Channels
    assert "c.tabs||[c.tab]" in chat
    assert 'return "channels"' in (ROOT / "agentos/chattabs.py").read_text()
    assert 'origin="telegram"' in (ROOT / "agentos/telegram.py").read_text()
    assert 'origin="whatsapp"' in (ROOT / "agentos/whatsapp.py").read_text()
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'telegram_request':" in ws and "tgAllow(ev.chat_id,1)" in ws
    st = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "Who can talk to it" in st
