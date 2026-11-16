"""From the desktop to your phone: carry a chat on, send an answer, send a story.

Asked for as "have a chat response to continue in the Telegram, send the stage to Telegram or
WhatsApp … only users' chats to their own accounts. The user can decide which Telegram chat".
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import chattabs, phoneforward, phonesessions      # noqa: E402
from test_phone_sessions import _tg, _say, _open                # noqa: E402

ROOT = Path(__file__).parent.parent


def _desk(store, title="Nifty tomorrow"):
    cid = store.create_conversation(title, origin="user")
    store.add_message(cid, "user", "what about nifty tomorrow")
    store.add_message(cid, "assistant", "Nifty looks flat, with support at 24,800.")
    return cid


def _send(b, to, what, cid, **kw):
    return asyncio.run(phoneforward.send(b.store, b, None, "telegram", str(to), what, cid, **kw))


def _texts(sent):
    return [s.get("text", "") for s in sent if s["method"] == "sendMessage"]


def test_only_chats_that_may_talk_are_offered(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    b.store.tg_upsert_chat(7, "Stranger", "", "private")            # wrote, never let in
    b.store.tg_upsert_chat(-9, "Family", "", "group")
    b.store.tg_set_allowed(-9, 1)
    b.set_groups(False)
    rows = phoneforward.targets(b, None)
    assert [r["to"] for r in rows] == ["5", "6"] and rows[0]["kind"] == "you"
    b.set_groups(True)
    assert "-9" in [r["to"] for r in phoneforward.targets(b, None)]
    cid = _desk(b.store)
    for to in (7, 12345):                                            # a chat id is a caller's word
        r = _send(b, to, "reply", cid)
        assert not r["ok"] and "isn't one of your chats" in r["message"]
    assert not sent


def test_an_answer_goes_to_the_chat_that_was_picked(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    cid = _desk(b.store)
    r = _send(b, 6, "reply", cid)
    assert r["ok"], r
    assert [s["chat_id"] for s in sent] == [6]
    assert "support at 24,800" in _texts(sent)[0] and "Nifty tomorrow" in _texts(sent)[0]
    assert (b.store.get_conversation(cid).get("channel_ref") or "") == ""    # sending moves nothing


def test_a_chat_carries_on_in_telegram_with_its_history(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    _say(b, 5, "hello")
    before = _open(b, 5)
    cid = _desk(b.store)
    r = _send(b, 5, "continue", cid)
    assert r["ok"] and r["switched"], r
    assert _open(b, 5) == cid
    assert b.store.get_conversation(cid)["channel_ref"] == "telegram:5"
    assert "Carrying on" in _texts(sent)[-1] and "support at 24,800" in _texts(sent)[-1]
    _say(b, 5, "and the day after?")
    said = [m["content"] for m in b.store.get_messages(cid)]
    assert any("day after" in s for s in said), said                 # the next message lands in it
    # the session the phone had is kept, and listed
    ids = [r["id"] for r in phonesessions.sessions(b.store, "telegram:5", cid)]
    assert before in ids and cid in ids


def test_a_session_of_one_chat_is_never_moved_to_another(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    cid = _desk(b.store)
    assert _send(b, 5, "continue", cid)["ok"]
    r = _send(b, 6, "continue", cid)
    assert not r["ok"] and "another phone chat" in r["message"]
    assert _open(b, 5) == cid and b.store.get_conversation(cid)["channel_ref"] == "telegram:5"
    assert _send(b, 6, "reply", cid)["ok"]                           # its answer may still be sent


def test_nothing_is_switched_when_the_message_did_not_get_there(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    cid = _desk(b.store)

    async def down(method, **kw):
        raise RuntimeError("network is down")
    b._api = down
    r = _send(b, 5, "continue", cid)
    assert not r["ok"] and "network is down" in r["message"]
    assert (b.store.get_conversation(cid).get("channel_ref") or "") == ""


def test_a_busy_chat_is_not_switched(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    cid = _desk(b.store)
    b._busy_chats.add(5)
    r = _send(b, 5, "continue", cid)
    assert not r["ok"] and "being answered" in r["message"]


def test_a_story_is_sent_as_the_one_that_was_named(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    cid = _desk(b.store)
    r = _send(b, 5, "stage", cid)
    assert not r["ok"] and "no story" in r["message"]
    from agentos import stage as stagemod
    mid = b.store.get_messages(cid)[0]["id"]
    monkeypatch.setattr(stagemod, "stories", lambda store, c: [{"answer_to": mid, "scenes": [{"scene": {"kind": "steps"}}]}])
    monkeypatch.setattr(stagemod, "story", lambda store, c, a: [{"scene": {"kind": "steps"}}] if a == mid else [])
    got = []

    async def fake_stage(c, reply, chat_id, ans=""):
        got.append((c, chat_id, ans))
        return "sent"
    b.send_stage = fake_stage
    r = _send(b, 6, "stage", cid)
    assert r["ok"] and got == [(cid, 6, mid)]


def test_whatsapp_says_why_a_closed_window_cannot_take_it(tmp_path):
    from agentos import whatsapp
    from agentos.memory import Store
    from agentos.tools import Toolbox
    cfg = {"whatsapp": {"enabled": True, "mode": "cloud", "phone_number_id": "1", "access_token": "t",
                        "verify_token": "v", "app_secret": "s", "owner_wa_id": "911"}}
    store = Store(tmp_path / "w.db")

    async def bc(ev):
        pass
    wa = whatsapp.WhatsAppBridge(cfg, store, Toolbox(cfg, store), bc)
    store.wa_upsert_chat("911", "Me")
    store.db.execute("UPDATE whatsapp_chats SET last_inbound=0 WHERE wa_id='911'")
    store.db.commit()
    rows = phoneforward.targets(None, wa)
    assert rows and rows[0]["to"] == "911" and not rows[0]["ready"] and "24 hours" in rows[0]["why"]
    cid = _desk(store)
    r = asyncio.run(phoneforward.send(store, None, wa, "whatsapp", "911", "continue", cid))
    assert not r["ok"] and "24 hours" in r["message"]
    assert (store.get_conversation(cid).get("channel_ref") or "") == ""


def test_the_desktop_lists_every_session_of_a_phone_chat(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    _say(b, 5, "hello")
    _say(b, 5, "/new trip")
    desk = _desk(b.store)
    assert _send(b, 5, "continue", desk)["ok"]
    r = phoneforward.new_session(b.store, b, None, "telegram", "5", "from the desk")
    assert r["ok"] and _open(b, 5) == desk                           # the phone stays where it is
    convs = phoneforward.mark(b.store, chattabs.tag(b.store, b.store.list_conversations()))
    mine = [c for c in convs if c.get("phone")]
    assert len(mine) == 4 and {c["phone"]["chat"] for c in mine} == {"P5"}
    assert [c["id"] for c in mine if c["phone"]["open"]] == [desk]
    assert {"trip", "from the desk"} <= {c["phone"]["session"] for c in mine}
    d = next(c for c in convs if c["id"] == desk)
    assert d["tab"] == "desktop" and "channels" in d["tabs"]         # found in both places
    assert not phoneforward.new_session(b.store, b, None, "telegram", "777")["ok"]


def test_no_agent_can_forward_a_chat():
    """A person's act: no tool, and the routes are ordinary cookie routes with a ledger row."""
    tools = (ROOT / "agentos/tools.py").read_text()
    assert "phoneforward" not in tools
    server = (ROOT / "agentos/server.py").read_text()
    assert '@app.post("/api/phone/send")' in server and '_ledger("phone.send"' in server
    js = (ROOT / "agentos/ui/src/js/10e-phonesend.js").read_text()
    assert "innerHTML" not in js                                      # names are other people's words
