"""A lead hands independent parts to several specialists at once.

Reported as "when the task or the chat is running, the main agent is only spawning work to one
sub agent; it must be able to do things in parallel". Three causes, each found:

- The built-in loop ran a reply's tool calls one after another, so two `delegate` calls in one
  reply waited for each other.
- Claude Code runs MCP tool calls of one reply together only when the tool is marked
  `readOnlyHint`. Measured on 2.1.332 with a stand-in server: three calls to an unmarked tool
  took 18 s (6 s each, in turn), three to a marked one 6.4 s. The run bridge marked nothing.
- The flow master was told "delegate one concrete task at a time", and the lead nothing.
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors, fabric, mcpbridge, policy, providers   # noqa: E402
from agentos.agent import HAND_OUT_AT_ONCE, PARALLEL_TOOLS, Agent     # noqa: E402
from agentos.memory import Store                                      # noqa: E402
from agentos.policy import PDP                                        # noqa: E402
from agentos.tools import Toolbox                                     # noqa: E402

SAID = "I'll give the research to both of them at once."


def _lead(tmp_path, monkeypatch, approver=None, work_s=0.4):
    cfg = {"agent_name": "Aria", "autonomy": "full", "max_steps": 8, "default_model": "ollama/x",
           "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(cfg, store)
    tb.pdp = PDP(cfg, store)

    async def broadcast(ev):
        pass
    cp = fabric.ControlPlane(cfg, store, tb, broadcast)
    tb.fabric = cp
    for n in ("alpha", "beta"):
        store.save_subagent({"name": n, "soul": n, "tools": ["recall"], "autonomy_cap": "full"})
    seen = []

    async def run_subagent(defn, task, **kw):
        seen.append(("start", defn["name"], time.monotonic()))
        await asyncio.sleep(work_s)
        seen.append(("end", defn["name"], time.monotonic()))
        return {"status": "ok", "model": "x", "content": f"{defn['name']} did {task}",
                "fault": "", "run_id": "", "taint": []}
    cp.run_subagent = run_subagent
    asked = []

    def chat(cfg, model, messages, tools, options=None):
        asked.append([dict(m) for m in messages])

        async def gen():
            if len(asked) == 1:
                yield {"type": "text", "text": SAID}
                for i, n in enumerate(("alpha", "beta")):
                    yield {"type": "tool_call", "id": f"c{i}", "name": "delegate",
                           "args": {"subagent": n, "task": f"part {i}"}}
            else:
                yield {"type": "text", "text": "Both are done."}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", chat)

    async def emit(ev):
        pass

    async def yes(*a, **k):
        return True
    agent = Agent(cfg, tb, "ollama/x", emit, approver or yes, surface="chat")
    return agent, seen, asked


def test_two_hand_overs_in_one_reply_run_at_the_same_time(tmp_path, monkeypatch):
    agent, seen, asked = _lead(tmp_path, monkeypatch)
    out = asyncio.run(agent.run([{"role": "user", "content": "research this two ways"}]))
    starts = [t for k, _n, t in seen if k == "start"]
    ends = [t for k, _n, t in seen if k == "end"]
    assert len(starts) == 2 and max(starts) < min(ends), f"they ran one after another: {seen}"
    took = max(ends) - min(starts)
    assert took < 0.6, f"two 0.4 s hand-overs took {took:.2f} s"
    results = [m for m in asked[1] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in results] == ["c0", "c1"], "results go back in the order asked"
    assert "alpha did part 0" in results[0]["content"] and "beta did part 1" in results[1]["content"]
    assert out["content"].strip().endswith("Both are done.")


def test_a_run_that_can_park_still_hands_out_one_at_a_time(tmp_path, monkeypatch):
    """A parked call is remembered one per agent, so two parking side by side would lose one."""
    agent, seen, _asked = _lead(tmp_path, monkeypatch, work_s=0.1)
    agent.can_park = True
    asyncio.run(agent.run([{"role": "user", "content": "research this two ways"}]))
    order = [(k, n) for k, n, _t in seen]
    assert order == [("start", "alpha"), ("end", "alpha"), ("start", "beta"), ("end", "beta")]


def test_each_card_keeps_the_words_its_call_was_made_with(tmp_path, monkeypatch):
    """The first call to finish clears `_said`; the second card was asked with none."""
    heard = []

    async def approver(name, args, reason, offer=None):
        if args.get("subagent") == "beta":
            await asyncio.sleep(0.3)            # alpha has finished by now
        heard.append((args.get("subagent"), policy.said()))
        return True
    agent, seen, _asked = _lead(tmp_path, monkeypatch, approver=approver, work_s=0.05)
    agent.cfg["autonomy"] = "strict"
    asyncio.run(agent.run([{"role": "user", "content": "research this two ways"}]))
    assert {n for n, _s in heard} == {"alpha", "beta"}, heard
    assert all(s == SAID for _n, s in heard), heard


def test_the_bridge_tells_a_cli_that_hand_overs_may_run_together():
    tools = mcpbridge.mcp_tools([{"name": n, "description": n, "parameters": {"type": "object"}}
                                 for n in ("delegate", "department_task", "write_file", "huddle")])
    marked = {t["name"] for t in tools if (t.get("annotations") or {}).get("readOnlyHint")}
    assert marked == {"delegate", "department_task"} == set(PARALLEL_TOOLS)


def test_every_lead_is_told_to_hand_independent_parts_out_together(tmp_path):
    assert HAND_OUT_AT_ONCE in executors.team_note([{"name": "alpha", "soul": "Research."}])
    assert HAND_OUT_AT_ONCE in executors.team_note([{"name": "alpha", "soul": "Research."}], prefix="")
    src = (Path(__file__).parent.parent / "agentos").joinpath("fabric.py").read_text()
    assert "one concrete task at a time" not in src and "+ HAND_OUT_AT_ONCE +" in src
    assert "HAND_OUT_AT_ONCE" in (Path(__file__).parent.parent / "agentos" / "company.py").read_text()
