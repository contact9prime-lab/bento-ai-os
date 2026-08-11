"""Typing again while the agent is working must never be dropped.

The message is QUEUED. At its next step boundary the running turn decides whether it
belongs to the run in flight (fold it in) or is a separate ask (leave it queued — it
starts as the next turn). This covers both halves: the agent-side triage/fold, and the
server-side queue that owns the backlog.
"""

import asyncio
import inspect
import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import providers                    # noqa: E402
from agentos import server                       # noqa: E402
from agentos.agent import Agent                  # noqa: E402
from agentos.memory import Store                 # noqa: E402
from agentos.tools import Toolbox                # noqa: E402


def _agent(tmp_path, events, **over):
    cfg = {"agent_name": "Aria", "autonomy": "balanced", "max_steps": 6,
           "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0},
           **over}
    tb = Toolbox(cfg, Store(tmp_path / "t.db"))

    async def emit(ev):
        events.append(ev)

    async def approver(*a, **k):
        return False

    return Agent(cfg, tb, "ollama/thinky", emit, approver)


def _two_step_chat(calls):
    """A model that calls one tool, then answers — two step boundaries."""
    def fake_chat(cfg, model, messages, tools, options=None):
        calls.append(list(messages))

        async def gen():
            if len(calls) == 1:
                yield {"type": "tool_call", "id": "c1", "name": "list_dir", "args": {"path": "."}}
                yield {"type": "finish", "reason": "tool_calls"}
            else:
                yield {"type": "text", "text": "done"}
                yield {"type": "finish", "reason": "stop"}
        return gen()
    return fake_chat


def test_queued_message_is_folded_into_the_running_turn(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "chat", _two_step_chat(calls))

    async def fake_complete(cfg, model, prompt, system=""):
        assert "New message:" in prompt and "actually make it a PDF" in prompt
        return '{"mode":"now","reason":"changes the output format"}'
    monkeypatch.setattr(providers, "complete", fake_complete)

    events, decided = [], []
    ag = _agent(tmp_path, events)

    async def hook(item, mode, reason):
        decided.append((item["id"], mode))
    ag.on_steer_decision = hook
    ag.inbox.append({"id": "q1", "text": "actually make it a PDF", "images": []})

    res = asyncio.run(ag.run([{"role": "user", "content": "write me a report"}]))

    assert decided == [("q1", "now")], "the server must be told what happened to it"
    steer = [e for e in events if e["type"] == "steer"]
    assert steer and steer[0]["mode"] == "now" and "PDF" in steer[0]["text"]
    # it reached the model as a real user message, marked as arriving mid-run
    folded = [m for m in calls[-1]
              if m.get("role") == "user" and "PDF" in (m.get("content") or "")]
    assert folded, "a folded-in message must be in the prompt of the next step"
    assert "WHILE you were working" in folded[0]["content"]
    assert any(s.get("type") == "steer" for s in res["steps"]), "the trace must record it"
    assert not ag.inbox


def test_unrelated_message_is_left_for_the_next_turn(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "chat", _two_step_chat(calls))

    async def fake_complete(cfg, model, prompt, system=""):
        return '{"mode":"later","reason":"a separate errand"}'
    monkeypatch.setattr(providers, "complete", fake_complete)

    events, decided = [], []
    ag = _agent(tmp_path, events)

    async def hook(item, mode, reason):
        decided.append((item["id"], mode))
    ag.on_steer_decision = hook
    ag.inbox.append({"id": "q1", "text": "also, what's the weather tomorrow?", "images": []})

    res = asyncio.run(ag.run([{"role": "user", "content": "write me a report"}]))

    assert decided == [("q1", "later")]
    assert not any(s.get("type") == "steer" for s in res["steps"])
    assert not [m for m in calls[-1]
                if m.get("role") == "user" and "weather" in (m.get("content") or "")], \
        "a deferred message must NOT leak into the running turn"


def test_triage_falls_back_to_wording_when_no_model_answers(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "chat", _two_step_chat(calls))

    async def dead_complete(cfg, model, prompt, system=""):
        raise RuntimeError("no provider")
    monkeypatch.setattr(providers, "complete", dead_complete)

    events = []
    ag = _agent(tmp_path, events)
    ag.inbox.append({"id": "a", "text": "wait — use the other folder", "images": []})
    ag.inbox.append({"id": "b", "text": "book me a flight to Berlin", "images": []})
    asyncio.run(ag.run([{"role": "user", "content": "tidy my downloads"}]))

    modes = {e["id"]: e["mode"] for e in events if e["type"] == "steer"}
    assert modes["a"] == "now", "a correction opener steers the live run"
    assert modes["b"] == "later", "anything ambiguous waits — that is the safe default"


def test_offer_triages_while_the_reply_is_still_streaming(tmp_path, monkeypatch):
    """The decision must not be paid for at the step boundary: a cold local
    classifier costs tens of seconds, and that would stall the turn it is meant
    to keep moving."""
    order = []

    def fake_chat(cfg, model, messages, tools, options=None):
        async def gen():
            order.append("step-start")
            await asyncio.sleep(0.25)
            yield {"type": "text", "text": "done"}
            yield {"type": "finish", "reason": "stop"}
            order.append("step-end")
        return gen()
    monkeypatch.setattr(providers, "chat", fake_chat)

    async def fake_complete(cfg, model, prompt, system=""):
        order.append("triage")
        return '{"mode":"later","reason":"separate"}'
    monkeypatch.setattr(providers, "complete", fake_complete)

    async def scenario():
        ag = _agent(tmp_path, [])
        turn = asyncio.create_task(ag.run([{"role": "user", "content": "tidy up"}]))
        await asyncio.sleep(0.1)                      # the model step is in flight
        ag.offer({"id": "q1", "text": "and rename them", "images": []})
        await asyncio.sleep(0.05)
        decided_early = "triage" in order
        await turn
        return decided_early

    assert asyncio.run(scenario()), "triage must start when the message lands"
    assert order.index("triage") < order.index("step-end")


def test_steering_can_be_turned_off(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "chat", _two_step_chat(calls))

    async def fake_complete(cfg, model, prompt, system=""):
        raise AssertionError("triage must not run when steering is off")
    monkeypatch.setattr(providers, "complete", fake_complete)

    events = []
    ag = _agent(tmp_path, events, steer_queued_messages=False)
    ag.inbox.append({"id": "q1", "text": "wait, stop that", "images": []})
    asyncio.run(ag.run([{"role": "user", "content": "tidy my downloads"}]))
    assert [e["mode"] for e in events if e["type"] == "steer"] == ["later"]


def test_a_turn_about_to_end_still_takes_in_a_late_message(tmp_path, monkeypatch):
    """The message landed while the last reply was streaming: the turn keeps going
    rather than closing a job the user just changed."""
    calls = []

    def fake_chat(cfg, model, messages, tools, options=None):
        calls.append(list(messages))

        async def gen():
            yield {"type": "text", "text": "here is your report" if len(calls) == 1
                   else "here it is as a PDF"}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", fake_chat)

    async def fake_complete(cfg, model, prompt, system=""):
        return '{"mode":"now","reason":"changes the deliverable"}'
    monkeypatch.setattr(providers, "complete", fake_complete)

    events = []
    ag = _agent(tmp_path, events)

    async def emit(ev):
        events.append(ev)
        # the user types while that first reply is streaming
        if ev["type"] == "text_delta" and len(calls) == 1 and not ag.inbox and len(calls) < 2:
            ag.inbox.append({"id": "q1", "text": "make it a PDF", "images": []})
    ag.emit = emit

    res = asyncio.run(ag.run([{"role": "user", "content": "write me a report"}]))
    assert len(calls) == 2, "the turn must continue instead of ending on a stale plan"
    assert res["content"] == "here it is as a PDF"


# ---- the server side: the queue itself --------------------------------------------

def test_busy_conversation_queues_instead_of_erroring():
    src = inspect.getsource(server)
    assert "already has a turn running" not in src, \
        "a second message must be queued, not refused"
    assert "_queue_add(cid, data)" in src and "ag.offer(item)" in src


def test_queue_flushes_into_the_next_turn():
    src = inspect.getsource(server._queue_flush)
    assert "run_chat(cid, data)" in src
    assert 'state["turns"][cid] = {"agent": None' in src, "claim the slot before starting"
    # run_chat flushes on every exit path, right after it releases the slot
    rc = inspect.getsource(server._run_chat)
    assert rc.index("turns.pop(cid, None)") < rc.index("_queue_flush(cid)")


def test_stopping_a_turn_drops_its_backlog():
    src = inspect.getsource(server)
    i = src.index('elif t == "abort":')
    assert "_queue_drop(cid)" in src[i:i + 1200], \
        "stop must mean stop — the queue cannot outlive the turn it was typed behind"


def test_queue_never_broadcasts_image_payloads():
    src = inspect.getsource(server._queue_public)
    assert 'len(i["images"])' in src and '"images": i["images"]' not in src


def test_run_chat_hands_the_queue_to_the_agent():
    src = inspect.getsource(server._run_chat)
    assert 'for queued in state["queues"].get(cid) or []:' in src
    assert "agent.offer(queued)" in src
    assert "agent.on_steer_decision = _steer_hook(cid)" in src


# ---- over the real socket ---------------------------------------------------------

def _slow_model(turns):
    """A model whose reply takes long enough that you can type again mid-turn."""
    def fake_chat(cfg, model, messages, tools, options=None):
        turns.append(list(messages))
        n = len(turns)

        async def gen():
            await asyncio.sleep(0.4)
            yield {"type": "text", "text": f"reply {n}"}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return fake_chat


def _busy_chat(monkeypatch, verdict):
    """Open a chat, start a turn, type a second message into it. Returns
    (client, socket, conversation_id, turns-seen-by-the-model)."""
    from fastapi.testclient import TestClient
    turns = []
    monkeypatch.setattr(providers, "chat", _slow_model(turns))

    async def fake_complete(cfg, model, prompt, system=""):
        return '{"mode":"%s","reason":"because"}' % verdict
    monkeypatch.setattr(providers, "complete", fake_complete)

    c = TestClient(server.app)
    c.__enter__()
    server.state["cfg"]["default_model"] = "ollama/x"
    ws = c.websocket_connect("/ws").__enter__()
    ws.receive_json()                                   # state_sync
    ws.send_json({"type": "chat", "text": "write me a report"})
    cid = None
    for _ in range(3):
        ev = ws.receive_json()
        if ev["type"] == "conversation":
            cid = ev["id"]
        if ev["type"] == "turn_start":
            break
    ws.send_json({"type": "chat", "text": "also check the weather",
                  "conversation_id": cid})
    return c, ws, cid, turns


def test_ws_second_message_is_queued_then_runs_as_the_next_turn(monkeypatch):
    c, ws, cid, turns = _busy_chat(monkeypatch, "later")
    try:
        events = []
        for _ in range(20):     # read until the queued message starts its own turn
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "turn_start" and any(e["type"] == "turn_end" for e in events):
                break
        kinds = [e["type"] for e in events]
        assert "error" not in kinds, "a busy chat must queue, never refuse"
        q = next(e for e in events if e["type"] == "queue_update")
        assert q["queue"][0]["text"] == "also check the weather"
        assert any(e["type"] == "steer" and e["mode"] == "later" for e in events)
        # (the first turn_start was consumed while opening the chat)
        assert kinds.count("turn_start") == 1, "a second, separate turn must start"
        assert kinds.index("turn_end") < kinds.index("turn_start"), "…after this one ends"
        assert "also check the weather" in turns[-1][-1]["content"]
        assert not server.state["queues"].get(cid), "the queue empties as it drains"
    finally:
        ws.__exit__(None, None, None)
        c.__exit__(None, None, None)


def test_ws_steered_message_joins_the_running_turn_and_is_kept(monkeypatch):
    c, ws, cid, turns = _busy_chat(monkeypatch, "now")
    try:
        kinds = []
        for _ in range(16):
            kinds.append(ws.receive_json()["type"])
            if kinds[-1] == "turn_end":
                break
        assert "turn_start" not in kinds, "folded in — it must NOT also run as its own turn"
        assert "steer" in kinds
        folded = [m for step in turns for m in step
                  if m["role"] == "user" and "weather" in (m.get("content") or "")]
        assert folded, "the running turn must actually see it"
        assert "WHILE you were working" in folded[0]["content"]
        # and it stays in the transcript: the turn that would have persisted it
        # never happened, so the steer hook has to
        said = [m["content"] for m in server.state["store"].get_messages(cid)
                if m["role"] == "user"]
        assert any("also check the weather" == s for s in said)
        assert not server.state["queues"].get(cid)
    finally:
        ws.__exit__(None, None, None)
        c.__exit__(None, None, None)
