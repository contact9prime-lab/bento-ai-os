"""A specialist the lead hands work to in a chat asks the person in it (tools.delegate).

Found building the test report: a chat's `delegate` started the specialist with no approver,
so every gated step went to the headless approver, which says yes only at full autonomy and
never to a step that must be a person's. At the default autonomy the specialist's write was
refused with nobody asked, and request_capability (always a person's) could never reach
anybody. A department's task already escalated. The loop decides it from the turn's surface,
never the model: a schedule, a linked team or the Arena has nobody to ask.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric, providers                             # noqa: E402
from agentos.agent import Agent, PERSON_SURFACES                  # noqa: E402
from agentos.memory import Store                                  # noqa: E402
from agentos.policy import PDP                                    # noqa: E402
from agentos.tools import Toolbox                                 # noqa: E402


def _script(turns):
    state = {"i": 0}

    def chat(cfg, model, messages, tools, options=None):
        async def gen():
            i = min(state["i"], len(turns) - 1)
            state["i"] += 1
            for ev in turns[i]:
                yield ev
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat


def _call(name, args, cid):
    return {"type": "tool_call", "id": cid, "name": name, "args": args}


def _lead_hands_a_write(tmp_path, monkeypatch, surface, answer=True, forged=False):
    cfg = {"agent_name": "Aria", "autonomy": "balanced", "max_steps": 8, "default_model": "ollama/x",
           "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(cfg, store)
    tb.pdp = PDP(cfg, store)

    async def broadcast(ev):
        pass
    cp = fabric.ControlPlane(cfg, store, tb, broadcast)
    tb.fabric = cp
    asked = []

    async def approvals(run_id, name, args, reason, offer, origin, park=False):
        asked.append({"tool": name, "origin": origin})
        return answer
    cp.approvals = approvals
    store.save_subagent({"name": "writer", "soul": "write", "tools": ["write_file"], "autonomy_cap": "balanced"})
    target = str(tmp_path / "note.txt")
    args = {"subagent": "writer", "task": "write the note", **({"_escalate": True} if forged else {})}
    monkeypatch.setattr(providers, "chat", _script([
        [_call("delegate", args, "l1")],                             # the lead
        [_call("write_file", {"path": target, "content": "hello"}, "w1")],   # the writer
        [{"type": "text", "text": "Wrote it."}],
        [{"type": "text", "text": "The writer wrote it."}],          # the lead again
    ]))
    conv = store.create_conversation("a chat") if hasattr(store, "create_conversation") else "c1"
    cid = conv["id"] if isinstance(conv, dict) else conv

    async def emit(ev):
        pass

    async def lead_yes(*a, **k):
        return True
    agent = Agent(cfg, tb, "ollama/x", emit, lead_yes, conversation_id=cid, surface=surface)
    asyncio.run(agent.run([{"role": "user", "content": "have the writer write the note"}]))
    return asked, Path(target)


def test_a_chats_specialist_asks_the_person_and_carries_on(tmp_path, monkeypatch):
    asked, note = _lead_hands_a_write(tmp_path, monkeypatch, "gui")
    assert [a["tool"] for a in asked] == ["write_file"], asked
    assert asked[0]["origin"]["surface"] == "chat" and asked[0]["origin"]["ref"], "the card goes to that chat"
    assert note.read_text() == "hello"


def test_a_no_from_the_person_is_a_no(tmp_path, monkeypatch):
    asked, note = _lead_hands_a_write(tmp_path, monkeypatch, "telegram", answer=False)
    assert [a["tool"] for a in asked] == ["write_file"] and not note.exists()


def test_a_schedules_specialist_asks_nobody(tmp_path, monkeypatch):
    asked, note = _lead_hands_a_write(tmp_path, monkeypatch, "task")
    assert asked == [] and not note.exists(), "nobody is in a schedule's turn: refused at balanced, as before"


def test_the_model_cannot_say_a_person_is_there(tmp_path, monkeypatch):
    asked, note = _lead_hands_a_write(tmp_path, monkeypatch, "task", forged=True)
    assert asked == [] and not note.exists(), "the loop's _escalate, never the model's"


def test_the_people_surfaces_are_the_ones_a_person_answers_on():
    assert {"gui", "desktop", "telegram", "whatsapp"} <= PERSON_SURFACES
    assert not ({"task", "team", "arena", "widget", "webhook"} & PERSON_SURFACES)
