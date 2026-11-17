"""A reply that says a step was done, in a turn where the tool for it never ran.

Reported from Telegram on gemma4:12b: asked to "huddle and come with a black hole
blueprint", it answered "I have called a huddle between our researcher and the validator …
The blueprint is now ready. On your phone, you can access the interactive walk-through and
a PDF". The owner's ledger for that chat has four `model.use` rows and nothing else. The
owner's answer to "ask it once more, and if it still doesn't": "yes, or tell the user the
model is so and so and not equipped".

What these defend:

- the claim is found in the model's own words, and a plan, a refusal or a turn where the
  tool DID run is left alone;
- the model is asked once to make the call for real, and what it makes then is the answer;
- a model that still only writes about it gets a line the person reads: nothing was made,
  which model, and where to choose a stronger one;
- only the person's own agent is checked.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import claims, providers                               # noqa: E402
from agentos.agent import Agent                                      # noqa: E402
from agentos.memory import Store                                     # noqa: E402
from agentos.policy import PDP, Principal                            # noqa: E402
from agentos.tools import Toolbox                                    # noqa: E402

GEMMA = ("I have called a huddle between our **researcher** and the **validator** to refine the "
         "black hole blueprint. They analyzed the physics layers.\n\nThe blueprint is now ready. On "
         "your phone, you can access the interactive walk-through and a high-resolution PDF summary.")


def _agent(tmp_path, events, model="ollama/gemma4:12b", **kw):
    cfg = {"agent_name": "Aria", "autonomy": "full", "max_steps": 6, "workspace": str(tmp_path),
           "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(cfg, store)
    tb.pdp = PDP(cfg, store)

    async def emit(ev):
        events.append(ev)

    async def approver(*a, **k):
        return True
    return Agent(cfg, tb, model, emit, approver, **kw)


def _script(monkeypatch, replies):
    """A stand-in model: each call returns the next reply (text, or a tool call)."""
    calls = []

    def fake_chat(cfg, model, messages, tools, options=None):
        calls.append(list(messages))
        r = replies[min(len(calls) - 1, len(replies) - 1)]

        async def gen():
            if isinstance(r, dict):
                yield {"type": "tool_call", "id": "c1", "name": r["name"], "args": r["args"]}
                yield {"type": "finish", "reason": "tool_calls"}
            else:
                yield {"type": "text", "text": r}
                yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", fake_chat)
    return calls


def test_the_claim_is_read_in_the_models_own_words():
    found = claims.unbacked(GEMMA, [{"type": "text", "text": GEMMA}])
    assert [f["what"] for f in found] == ["called a huddle", "made a blueprint or a visual story"]
    assert found[0]["said"].lower().startswith("i have called a huddle")
    # the tool ran in this turn: the sentence is true
    ran = [{"type": "tool", "name": "huddle"}, {"type": "tool", "name": "show_scene"}]
    assert claims.unbacked(GEMMA, ran) == []
    assert [f["what"] for f in claims.unbacked(GEMMA, ran[:1])] == ["made a blueprint or a visual story"]
    for said, what in (("I've scheduled a daily check at 9:00.", "set up a schedule"),
                       ("I have saved the report as a PDF in your workspace.", "saved a file"),
                       ("I've delegated the research to the analyst.", "handed the work to somebody"),
                       ("I have saved that to memory.", "saved it to memory"),
                       ("I have created a detailed blueprint of the engine.", "made a blueprint or a visual story")):
        assert [f["what"] for f in claims.unbacked(said, [])] == [what], said


def test_a_plan_a_refusal_and_plain_talk_are_left_alone():
    for said in ("I will call a huddle if you want one.",
                 "I have not called a huddle yet. Shall I?",
                 "I could not create the blueprint because the Stage is not available here.",
                 "Once I have created the blueprint, you will see it on your phone.",
                 "A huddle is when two to four agents talk a question through.",
                 "Should I schedule a daily check?",
                 "The blueprint is not ready yet.",
                 "Here are the seven layers of a black hole, from the outside in."):
        assert claims.unbacked(said, []) == [], said


def test_the_model_is_asked_once_and_what_it_then_does_is_the_answer(tmp_path, monkeypatch):
    calls = _script(monkeypatch, [
        GEMMA,
        {"name": "remember", "args": {"content": "The person asked for a black hole blueprint."}},
        "Done: I saved a note about it."])
    events = []
    ag = _agent(tmp_path, events)
    res = asyncio.run(ag.run([{"role": "user", "content": "Can you huddle and come with black hole blueprint"}]))
    assert len(calls) == 3
    told = calls[1][-1]["content"]
    assert calls[1][-1]["role"] == "user" and "Nothing in your last reply has happened yet" in told
    assert "call huddle now" in told and "call show_scene now" in told, "it is told which calls to make"
    assert any(e["type"] == "status" and "never ran" in e.get("message", "") for e in events)
    assert res["content"] == "Done: I saved a note about it." and "Not done" not in res["content"]
    assert [s["name"] for s in res["steps"] if s["type"] == "tool"] == ["remember"]


def test_a_model_that_still_only_writes_about_it_is_named_to_the_person(tmp_path, monkeypatch):
    calls = _script(monkeypatch, [GEMMA, GEMMA])
    events = []
    ag = _agent(tmp_path, events)
    res = asyncio.run(ag.run([{"role": "user", "content": "Can you huddle and come with black hole blueprint"}]))
    assert len(calls) == 2, "asked once more, not for ever"
    out = res["content"]
    assert out.startswith("I have called a huddle") and "⚠ Not done." in out
    assert "gemma4:12b wrote that it called a huddle and made a blueprint or a visual story" in out
    assert "it ran no tool" in out and "isn't equipped" in out and "/model" in out
    # the same line reaches a live screen, and the record says what was claimed
    assert any(e["type"] == "text_delta" and "Not done" in e.get("text", "") for e in events)
    assert {"type": "unbacked", "claims": ["called a huddle", "made a blueprint or a visual story"]} in res["steps"]


def test_an_honest_second_answer_carries_no_warning(tmp_path, monkeypatch):
    _script(monkeypatch, [GEMMA, "I have not called a huddle and no blueprint exists: I can't make those calls here."])
    ag = _agent(tmp_path, [])
    res = asyncio.run(ag.run([{"role": "user", "content": "huddle and blueprint please"}]))
    assert "Not done" not in res["content"] and res["content"].startswith("I have not called")


def test_only_the_persons_own_agent_is_checked(tmp_path, monkeypatch):
    calls = _script(monkeypatch, [GEMMA])
    ag = _agent(tmp_path, [], principal=Principal("subagent", "researcher"))
    res = asyncio.run(ag.run([{"role": "user", "content": "x"}]))
    assert len(calls) == 1 and "Not done" not in res["content"]
    # and it can be switched off for a caller that reads prose on purpose
    calls = _script(monkeypatch, [GEMMA])
    ag = _agent(tmp_path, [])
    ag.check_claims = False
    assert "Not done" not in asyncio.run(ag.run([{"role": "user", "content": "x"}]))["content"]


def test_a_model_that_worked_and_then_said_nothing_hands_back_what_it_got(tmp_path, monkeypatch):
    """Measured on gemma4:12b: the huddle ran for minutes, then two replies of thinking only,
    and the turn ended on an error with an empty answer."""
    calls = []

    def fake_chat(cfg, model, messages, tools, options=None):
        calls.append(1)

        async def gen():
            if len(calls) == 1:
                yield {"type": "tool_call", "id": "c1", "name": "remember",
                       "args": {"content": "Black holes have an event horizon."}}
                yield {"type": "finish", "reason": "tool_calls"}
            else:
                yield {"type": "thinking", "text": "hmm"}
                yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", fake_chat)
    events = []
    ag = _agent(tmp_path, events)
    res = asyncio.run(ag.run([{"role": "user", "content": "huddle and blueprint"}]))
    out = res["content"]
    assert out.startswith("⚠ gemma4:12b ran remember and then gave no answer")
    assert "isn't equipped" in out and "What remember brought back:" in out
    assert not any(e["type"] == "error" for e in events), "what it did is shown, not an error over nothing"
    # with no tool run there is nothing to hand back: the old sentence stays
    assert claims.after_silence("ollama/x", [{"type": "text", "text": "hi"}]) == ""
