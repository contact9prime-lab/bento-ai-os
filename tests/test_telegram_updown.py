"""A message on Telegram when the agent goes down and when it comes back.

Asked for as "in case of telegram, when the agent is coming up or going down, that message
needs to be sent". Measured against a stand-in Telegram server on a copy of the owner's
home: start, clean stop, start, kill -9, start gave "back online", "going offline", "back
online", and "back online … I wasn't shut down cleanly: I was last seen at …". The first
try sent nothing: telegram.py did not import contextlib, and the poller swallowed it.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent


def _bridge(tmp_path, **tg):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    cfg = {"agent_name": "Aria", "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 111, **tg}}
    b = TelegramBridge(cfg, Store(tmp_path / "a.db"), None, None)
    sent = []

    async def api(method, **kw):
        sent.append(kw.get("text"))
        return {}
    b._api = api
    return b, sent


def test_up_down_and_a_crash(tmp_path):
    b, sent = _bridge(tmp_path)
    asyncio.run(b.say_up())
    asyncio.run(b.say_up())                      # once per process
    assert len(sent) == 1 and sent[0].startswith("▲ Aria is back online")
    asyncio.run(b.say_down("to install an update"))
    assert sent[-1] == "▼ Aria is going offline to install an update. I'll message you when I'm back."
    b2, sent2 = _bridge(tmp_path)               # the next process, after a clean stop
    asyncio.run(b2.say_up())
    assert "shut down cleanly" not in sent2[0]
    b3, sent3 = _bridge(tmp_path)               # ... after one that never said goodbye
    asyncio.run(b3.say_up())
    assert "I wasn't shut down cleanly: I was last seen at" in sent3[0]


def test_it_can_be_switched_off_and_never_holds_a_shutdown(tmp_path):
    b, sent = _bridge(tmp_path, status_messages=False)
    asyncio.run(b.say_up())
    asyncio.run(b.say_down())
    assert sent == []
    adm = (ROOT / "agentos/telegram_admin.py").read_text()
    assert '("/updown", "[on|off]"' in adm and "async def _cmd_updown(" in adm
    srv = (ROOT / "agentos/server.py").read_text()
    sh = srv[srv.index("Say goodbye on every Telegram"):][:900]
    assert "asyncio.wait_for(tg.say_down(" in sh and ", 4)" in sh
    assert 'state["down_reason"] = "to install an update"' in srv
    src = (ROOT / "agentos/telegram.py").read_text()
    assert "\nimport contextlib\n" in src
