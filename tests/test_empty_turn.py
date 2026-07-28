"""A thinking model that answers only in its thinking channel must never end a
turn silently — the agent retries once with thinking off, then says so out loud.

This is the failure the Desktop thread hit: `[assistant] len=0 steps=0`, an empty
bubble in the chat and an omnibar card that looked stuck.
"""

import asyncio
import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import providers                    # noqa: E402
from agentos.agent import Agent                  # noqa: E402
from agentos.memory import Store                 # noqa: E402
from agentos.tools import Toolbox                # noqa: E402


def _agent(tmp_path, events):
    cfg = {"agent_name": "Aria", "autonomy": "balanced", "max_steps": 6,
           "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0}}
    tb = Toolbox(cfg, Store(tmp_path / "t.db"))

    async def emit(ev):
        events.append(ev)

    async def approver(*a, **k):
        return False

    return Agent(cfg, tb, "ollama/thinky", emit, approver)


def test_all_thinking_reply_retries_with_thinking_off(tmp_path, monkeypatch):
    calls = []

    def fake_chat(cfg, model, messages, tools, options=None):
        calls.append(options or {})

        async def gen():
            if len(calls) == 1:            # first pass: reasoning only, no answer
                yield {"type": "thinking", "text": "hmm, let me think about this"}
                yield {"type": "finish", "reason": "stop"}
            else:                          # retry: a real answer
                yield {"type": "text", "text": "Here is the answer."}
                yield {"type": "finish", "reason": "stop"}
        return gen()

    monkeypatch.setattr(providers, "chat", fake_chat)
    events = []
    ag = _agent(tmp_path, events)
    res = asyncio.run(ag.run([{"role": "user", "content": "hi"}]))

    assert res["content"] == "Here is the answer."          # not an empty turn
    assert len(calls) == 2, "the agent should have retried once"
    assert calls[1].get("think") is False, "the retry must disable thinking"
    assert any(e["type"] == "status" and "thinking channel" in (e.get("message") or "")
               for e in events), "the user should see why it retried"


def test_persistently_empty_reply_reports_instead_of_silence(tmp_path, monkeypatch):
    def fake_chat(cfg, model, messages, tools, options=None):
        async def gen():
            yield {"type": "thinking", "text": "..."}
            yield {"type": "finish", "reason": "stop"}
        return gen()

    monkeypatch.setattr(providers, "chat", fake_chat)
    events = []
    ag = _agent(tmp_path, events)
    res = asyncio.run(ag.run([{"role": "user", "content": "hi"}]))

    errs = [e for e in events if e["type"] == "error"]
    assert errs, "an empty turn must surface an error, never an empty bubble"
    assert "without producing an answer" in errs[0]["message"]
    assert any(s.get("type") == "error" for s in res["steps"])


def test_announce_and_stop_gets_nudged(tmp_path, monkeypatch):
    """'Let me fetch some top stories:' then silence must not end the turn."""
    calls = []

    def fake_chat(cfg, model, messages, tools, options=None):
        calls.append(list(messages))

        async def gen():
            if len(calls) == 1:
                yield {"type": "text", "text": "I can fetch some top stories for you:"}
            else:
                yield {"type": "text", "text": "Top story: markets rallied today."}
            yield {"type": "finish", "reason": "stop"}
        return gen()

    monkeypatch.setattr(providers, "chat", fake_chat)
    events = []
    ag = _agent(tmp_path, events)
    res = asyncio.run(ag.run([{"role": "user", "content": "news for today"}]))

    assert len(calls) == 2, "a dangling lead-in should be pushed to finish"
    assert "Top story" in res["content"]
    nudge = calls[1][-1]["content"]
    assert "without delivering" in nudge and "RSS" in nudge


def test_unreported_tool_failure_is_detected():
    from agentos.agent import Agent as A
    steps = [{"type": "tool", "name": "fetch_url", "ok": True,
              "output": '[401] {"code":"apiKeyInvalid"}'}]
    # the reply never mentions the 401 → unfinished
    assert A._looks_unfinished("I can fetch some top stories for you", steps)
    # the reply owns the failure → finished, leave it alone
    assert not A._looks_unfinished(
        "That source needs an API key I don't have, so I couldn't fetch it.", steps)
    # a normal substantive answer with a good tool result → finished
    ok = [{"type": "tool", "name": "fetch_url", "ok": True, "output": "<rss>…</rss>"}]
    assert not A._looks_unfinished("Here are today's headlines: markets rallied.", ok)


def test_repeated_identical_tool_call_is_stopped_as_a_loop(tmp_path, monkeypatch):
    """The same tool + same args, over and over, is a groove — not progress."""
    calls = {"n": 0}

    def fake_chat(cfg, model, messages, tools, options=None):
        calls["n"] += 1

        async def gen():
            yield {"type": "tool_call", "id": f"c{calls['n']}", "name": "list_dir",
                   "args": {"path": "."}}
            yield {"type": "finish", "reason": "tool_calls"}
        return gen()

    monkeypatch.setattr(providers, "chat", fake_chat)
    events = []
    ag = _agent(tmp_path, events)
    res = asyncio.run(ag.run([{"role": "user", "content": "look around"}]))

    errs = [e for e in events if e["type"] == "error"]
    assert errs and "loop" in errs[0]["message"], "a repeating call must be called out"
    assert calls["n"] <= 5, "it must stop early, not burn the whole step budget"
    assert any(s.get("type") == "error" for s in res["steps"])


def test_varied_tool_calls_are_not_treated_as_a_loop(tmp_path, monkeypatch):
    seq = [{"path": "a"}, {"path": "b"}, {"path": "c"}, {"path": "d"}]

    def fake_chat(cfg, model, messages, tools, options=None):
        i = min(len(seq) - 1, sum(1 for m in messages if m.get("role") == "tool"))

        async def gen():
            if i >= len(seq) - 1:
                yield {"type": "text", "text": "done looking"}
                yield {"type": "finish", "reason": "stop"}
            else:
                yield {"type": "tool_call", "id": f"c{i}", "name": "list_dir", "args": seq[i]}
                yield {"type": "finish", "reason": "tool_calls"}
        return gen()

    monkeypatch.setattr(providers, "chat", fake_chat)
    events = []
    ag = _agent(tmp_path, events)
    res = asyncio.run(ag.run([{"role": "user", "content": "look around"}]))
    assert "done looking" in (res["content"] or "")
    assert not [e for e in events if e["type"] == "error"]
