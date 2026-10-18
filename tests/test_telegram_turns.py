"""Two people on one bot are answered side by side, and the Office sees phone turns.

Reported as "if multiple people are talking to the same Telegram, why is it queuing them" and
"when I send a message on Telegram the office is generally quiet". Measured on the owner's
machine: the owner's question arrived at 23:30:42 and was saved at 23:33:27, the second the
diary said "compacted 2 earlier messages into a summary". The bridge rebuilt (and compacted, with
a model call) the long thread's history BEFORE saving the message, for a forwarded brain that
never reads it, while a newer, shorter chat went straight through. And every event of a phone
turn was dropped (`emit` did nothing), so the Office had nothing to show.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import executors, history                              # noqa: E402


def _bridge(tmp_path):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    cfg = {"agent_name": "Aria", "autonomy": "full", "telegram": {"enabled": True, "bot_token": "1:T",
                                                                    "owner_chat_id": 5}}
    store = Store(tmp_path / "a.db")
    tb = Toolbox(cfg, store)
    events, sent = [], []

    async def bc(ev):
        events.append(ev)
    b = TelegramBridge(cfg, store, tb, bc)
    store.tg_upsert_chat(5, "PC", "", "private")
    store.tg_set_allowed(5, 1)

    async def api(method, **kw):
        sent.append((method, kw.get("text", "")))
        return {}
    b._api = api
    return b, events, sent


def test_a_forwarded_turn_is_saved_first_and_shown_on_the_screens(tmp_path, monkeypatch):
    b, events, sent = _bridge(tmp_path)
    order = []

    async def slow_build(*a, **k):
        order.append("history built")
        return [], {}
    monkeypatch.setattr(history, "build", slow_build)
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")

    async def fake_forward(engine, text, cfg, ws, emit=None, **kw):
        order.append("saved before the brain" if any(m["content"] == text for m in
                     b.store.get_messages(b.store.tg_list_chats()[0]["conversation_id"])) else "not saved")
        await emit({"type": "tool_start", "name": "WebSearch", "args": {}})
        await emit({"type": "tool_start", "name": "mcp__bento__show_scene", "args": {}})
        return "the news", None
    monkeypatch.setattr(executors, "forward", fake_forward)
    asyncio.run(b._handle({"chat": {"id": 5, "type": "private"}, "from": {"first_name": "PC"},
                           "text": "what is in the news"}))
    assert order == ["saved before the brain"], "no history rebuild on a forwarded brain"
    kinds = [e["type"] for e in events]
    assert kinds.index("telegram_in") < kinds.index("turn_start") < kinds.index("tool_start") \
        < kinds.index("turn_end") < kinds.index("telegram_out")
    tools = [e["name"] for e in events if e["type"] == "tool_start"]
    assert tools == ["WebSearch"], "the CLI's copy of a tool this OS ran is dropped"
    assert all(e.get("conversation_id") for e in events if e["type"] in ("turn_start", "tool_start", "turn_end"))
    assert ("sendMessage", "the news") in [(m, t) for m, t in sent]


def test_the_built_in_loop_still_gets_its_history_once(tmp_path, monkeypatch):
    b, events, sent = _bridge(tmp_path)
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    seen = {}

    class FakeAgent:
        def __init__(self, *a, **k):
            pass

        async def run(self, msgs):
            seen["msgs"] = msgs
            return {"content": "hi", "steps": [], "tokens": {}}
    import agentos.telegram as tgmod
    monkeypatch.setattr(tgmod, "Agent", FakeAgent)
    asyncio.run(b._handle({"chat": {"id": 5, "type": "private"}, "from": {"first_name": "PC"}, "text": "hello"}))
    users = [m for m in seen["msgs"] if m["role"] == "user"]
    assert len(users) == 1 and users[0]["content"].endswith("hello") and "via Telegram" in users[0]["content"]


def test_whatsapp_does_the_same():
    src = (Path(__file__).parent.parent / "agentos/whatsapp.py").read_text()
    body = src[src.index("async def _turn_in"):]
    assert body.index('self.store.add_message(cid, "user", text)') < body.index("async def built_history")
    assert 'await emit({"type": "turn_start"' in body and 'await emit({"type": "turn_end"})' in body


def test_two_people_in_two_chats_run_at_the_same_time_in_their_own_sessions(tmp_path, monkeypatch):
    """"If two people are talking on the same account in different sessions, or on different
    Telegram chats, they are different sessions." Each chat is its own conversation with its own
    Claude Code session, and neither waits for the other."""
    import time as _t
    b, events, sent = _bridge(tmp_path)
    b.store.tg_upsert_chat(7, "Pankaj", "", "private")
    b.store.tg_set_allowed(7, 1)
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")
    runs = []

    async def slow_forward(engine, text, cfg, ws, emit=None, session_id="", **kw):
        runs.append((text, _t.monotonic(), session_id))
        await asyncio.sleep(0.5)

        class R:
            pass
        r = R()
        r.session_id = "sess-" + text
        return "answer to " + text, r
    monkeypatch.setattr(executors, "forward", slow_forward)

    async def both():
        t0 = _t.monotonic()
        await asyncio.gather(
            b._handle({"chat": {"id": 5, "type": "private"}, "from": {"first_name": "PC"}, "text": "news"}),
            b._handle({"chat": {"id": 7, "type": "private"}, "from": {"first_name": "Pankaj"}, "text": "trade"}))
        return _t.monotonic() - t0
    took = asyncio.run(both())
    assert took < 0.9, f"side by side, not one after the other ({took:.2f}s)"
    convs = {c["chat_id"]: c["conversation_id"] for c in b.store.tg_list_chats()}
    assert convs[5] != convs[7], "a conversation each"
    assert b.store.exec_session(convs[5]) == "sess-news" and b.store.exec_session(convs[7]) == "sess-trade"
