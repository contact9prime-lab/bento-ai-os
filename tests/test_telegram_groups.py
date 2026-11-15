"""Group chats are answered only when the owner switched them on, and only the ones picked.

Asked for as "allow group chats to be enabled only if enabled by the channel admin … for the
groups where the messages have come in, so the user can select which group to enable".
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import executors, telegram_admin        # noqa: E402
from agentos.memory import Store                     # noqa: E402

G1, G2 = -1001, -1002


def _tg(tmp_path, monkeypatch, **tele):
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    cfg = {"agent_name": "Aria", "autonomy": "full",
           "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 5, **tele}}
    store = Store(tmp_path / "a.db")
    sent, asked = [], []

    async def bc(ev):
        pass
    b = TelegramBridge(cfg, store, Toolbox(cfg, store), bc)
    store.tg_upsert_chat(5, "PC", "", "private")
    store.tg_set_allowed(5, 1)

    async def api(method, **kw):
        sent.append({"method": method, **kw})
        return {}
    b._api = api
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")
    monkeypatch.setattr("agentos.config.save_config", lambda cfg: None)

    async def fake_forward(engine, text, cfg, ws, emit=None, **kw):
        asked.append(text)
        return f"answer to {text}", types.SimpleNamespace(session_id="s")
    monkeypatch.setattr(executors, "forward", fake_forward)
    return b, sent, asked


def _group(b, gid, text, title="Family"):
    asyncio.run(b._handle({"chat": {"id": gid, "type": "supergroup", "title": title},
                           "from": {"first_name": "Asha"}, "text": text}))


def _owner(b, text):
    asyncio.run(b._handle({"chat": {"id": 5, "type": "private"}, "from": {"first_name": "PC"}, "text": text}))


def _tap(b, data):
    asyncio.run(b._handle_callback({"id": "q", "data": data, "from": {"id": 5},
                                    "message": {"chat": {"id": 5}, "message_id": 1, "text": "asked"}}))


def _to(sent, chat):
    return [s for s in sent if s.get("chat_id") == chat and s["method"] == "sendMessage"]


def test_a_group_is_not_answered_while_group_chats_are_off(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    assert b.groups_on() is False, "off until the owner says otherwise"
    _group(b, G1, "@bot what's the weather")
    assert asked == [] and _to(sent, G1) == [], "nothing is said in a group nobody enabled"
    told = _to(sent, 5)
    assert len(told) == 1 and "Group chats are off" in told[0]["text"] and "Family" in told[0]["text"]
    assert told[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"who:{G1}:1"
    _group(b, G1, "hello?")
    assert len(_to(sent, 5)) == 1, "the owner hears of a group once"
    # the allow-list written ahead does not get a group past the switch
    b.cfg["telegram"]["allow"] = [str(G2)]
    _group(b, G2, "let me in", title="Work")
    assert asked == [] and _to(sent, G2) == []


def test_the_owner_picks_the_groups_that_are_answered(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    _group(b, G1, "first")
    _group(b, G2, "first", title="Work")
    _tap(b, f"who:{G1}:1")                      # the button under the owner's message
    assert b.groups_on() is True, "picking a group switches group chats on"
    _group(b, G1, "what's the weather")
    assert asked == ["what's the weather"]
    _group(b, G2, "and here?", title="Work")
    assert asked == ["what's the weather"], "a group that was not picked stays unanswered"

    _owner(b, "/groups")
    listing = sent[-1]
    assert "Group chats are on" in listing["text"]
    assert "✓ Family" in listing["text"] and "• Work" in listing["text"]
    assert [r[0]["callback_data"] for r in listing["reply_markup"]["inline_keyboard"]] == \
        [f"who:{G2}:1", f"who:{G1}:0"] or \
        sorted(r[0]["callback_data"] for r in listing["reply_markup"]["inline_keyboard"]) == \
        sorted([f"who:{G2}:1", f"who:{G1}:0"])

    _owner(b, "/groups off")
    assert b.groups_on() is False
    _group(b, G1, "still there?")
    assert asked == ["what's the weather"], "off stops every group, picked or not"
    _owner(b, "/groups on")
    _group(b, G1, "back?")
    assert asked[-1] == "back?", "the picks are kept across off and on"


def test_only_the_owner_decides(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    b.store.tg_upsert_chat(6, "Colleague", "", "private")
    b.store.tg_set_allowed(6, 1)
    asyncio.run(b._handle({"chat": {"id": 6, "type": "private"}, "from": {"first_name": "C"},
                           "text": "/groups on"}))
    assert b.groups_on() is False and "owner" in sent[-1]["text"]
    assert "/groups" not in {"/" + c["command"] for c in telegram_admin.menu(False)}
    # a tap from anybody else in a group does nothing
    _group(b, G1, "first")
    asyncio.run(b._handle_callback({"id": "q", "data": f"who:{G1}:1", "from": {"id": 77},
                                    "message": {"chat": {"id": G1}, "message_id": 1}}))
    assert b.groups_on() is False


def test_a_machine_already_answering_a_group_keeps_answering_it(tmp_path, monkeypatch):
    b, sent, asked = _tg(tmp_path, monkeypatch)
    b.store.tg_upsert_chat(G1, "Family", "", "supergroup")
    b.store.tg_set_allowed(G1, 1)               # enabled before the switch existed
    assert b.groups_on() is True
    _group(b, G1, "hello")
    assert asked == ["hello"]
    b.set_groups(False)
    _group(b, G1, "hello again")
    assert asked == ["hello"]
    assert b.info()["groups"] is False


def test_an_old_story_is_not_pinned_under_the_newest_answer():
    """Reported as "I am seeing Weather for Bangalore when last I had asked the Nifty market":
    a story whose question had been wiped by /clear got its chip at the end of the chat."""
    js = (Path(__file__).parent.parent / "agentos/ui/src/js/24l-stage.js").read_text()
    body = js[js.index("async function stageAttach"):js.index("/* ---------- the window: a theater")]
    assert "if(!u)return;" in body and "feed.appendChild" not in body
