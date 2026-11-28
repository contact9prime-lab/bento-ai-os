"""A chat started on the phone and carried on at the desk shows on the phone too.

Reported as "if the chat is initiated in Telegram and then I chat on the Bento OS and then go
back to Telegram, the experience is not seamless; the other way round is great". Read from the
owner's record: the desk turns ran in the same Claude Code session, so the agent knew them, but
nothing said at the desk reached the phone. The owner chose every turn live."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import phoneforward                                 # noqa: E402
from test_phone_sessions import _tg, _say, _open                 # noqa: E402

ROOT = Path(__file__).parent.parent


def _mirror(b, cid, asked="what about tomorrow", answer="Flat, support at 24,800."):
    return asyncio.run(phoneforward.mirror(b.store, b, None, cid, asked, answer))


def _texts(sent):
    return [s.get("text", "") for s in sent if s["method"] == "sendMessage"]


def test_a_desk_turn_in_the_phone_session_goes_to_the_phone(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    _say(b, 5, "hello from the phone")
    cid = _open(b, 5)
    sent.clear()
    r = _mirror(b, cid)
    assert r["ok"], r
    said = _texts(sent)
    assert [s["chat_id"] for s in sent] == [5, 5]
    assert "at the desk" in said[0] and "what about tomorrow" in said[0]
    assert "support at 24,800" in said[1]


def test_a_session_the_phone_has_left_is_not_sent(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    _say(b, 5, "first topic")
    old = _open(b, 5)
    _say(b, 5, "/new other")
    sent.clear()
    r = _mirror(b, old)
    assert not r["ok"] and "another session" in r["why"] and not sent


def test_a_desk_chat_that_is_no_phone_session_sends_nothing(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    cid = b.store.create_conversation("desk only", origin="user")
    assert not _mirror(b, cid)["ok"] and not sent


def test_a_chat_that_may_no_longer_talk_is_not_sent(tmp_path, monkeypatch):
    b, sent, _ = _tg(tmp_path, monkeypatch)
    _say(b, 6, "hi")
    cid = _open(b, 6)
    b.store.tg_set_allowed(6, 0)
    sent.clear()
    assert not _mirror(b, cid)["ok"] and not sent


def test_the_chat_turn_hands_its_answer_to_the_mirror():
    src = (ROOT / "agentos/server.py").read_text()
    assert "asyncio.create_task(_mirror_to_phone(cid, text, header + result[\"content\"]))" in src
    assert "async def _mirror_to_phone" in src
