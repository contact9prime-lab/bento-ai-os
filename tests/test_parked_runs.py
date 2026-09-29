"""A mission that asks a question nobody is awake for WAITS, and carries on when answered.

Before this, an unanswered approval was a denial after fifteen minutes: the run finished
without the step, and a Brief item said so. Now a run on the built-in loop parks: its
history, board and budget are saved (`fabric_parked`), the question is a Brief item, and
answering it resumes the run from the call it stopped on, after a restart too. These
tests pin the parts that make that true:

- the saved state is enough: a FRESH store and control plane carry the run on
- the answer goes back through the gate (a revoked grant still refuses the step)
- a specialist's question parks the mission's master too, and both resume in order
- one answer counts once; a run nobody answered stops, and says why
- a run the server was stopped in the middle of is marked, not left "running"
- a mission on an agent CLI cannot park, and keeps the old refusal
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import brief as briefmod, fabric, flows, providers   # noqa: E402
from agentos.agent import PARK                                    # noqa: E402
from agentos.memory import Store                                  # noqa: E402
from agentos.policy import PDP                                    # noqa: E402
from agentos.tools import Toolbox                                 # noqa: E402


def _script(turns):
    state = {"i": 0, "seen": []}

    def chat(cfg, model, messages, tools, options=None):
        state["seen"].append(messages)

        async def gen():
            i = min(state["i"], len(turns) - 1)
            state["i"] += 1
            for ev in turns[i]:
                yield ev
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat, state


def _call(name, args, cid):
    return {"type": "tool_call", "id": cid, "name": name, "args": args}


def _cfg(tmp_path):
    return {"agent_name": "Aria", "autonomy": "balanced", "max_steps": 8,
            "default_model": "ollama/x", "workspace": str(tmp_path), "providers": {},
            "memory": {"inject_facts": 0, "inject_user": 0}}


def _plane(tmp_path, answer=PARK):
    """A control plane over the database at tmp_path/t.db. Built again to stand for a
    restarted server: nothing but the database carries over."""
    c = _cfg(tmp_path)
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    events = []

    async def broadcast(ev):
        events.append(ev)

    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    asked = []

    async def approvals(run_id, name, args, reason, offer, origin, park=False):
        asked.append({"tool": name, "park": park})
        return answer if (answer is not PARK or park) else False
    cp.approvals = approvals
    return c, store, cp, events, asked


def _mission(store):
    store.save_subagent({"name": "writer", "soul": "write", "tools": ["write_file"],
                         "autonomy_cap": "balanced"})
    flow, _ = flows.save(store, {"name": "notes", "mission": "Write today's note.",
                                 "roster": ["writer"], "autonomy_cap": "balanced",
                                 "permissions": {"tools": ["write_file"],
                                                 "folders": {"write": [str(store.path.parent)]}},
                                 "sinks": []})
    return flow


def _turns(target):
    return [
        [_call("delegate", {"subagent": "writer", "task": "write the note"}, "m1")],
        [_call("write_file", {"path": target, "content": "hello"}, "w1")],
        [{"type": "text", "text": "Wrote the note."}],
        [_call("finish", {"summary": "The note is written."}, "m2")],
        [{"type": "text", "text": ""}],
    ]


def _park_one(tmp_path, monkeypatch):
    cfg, store, cp, events, asked = _plane(tmp_path)
    flow = _mission(store)
    target = str(tmp_path / "note.txt")
    chat, st = _script(_turns(target))
    monkeypatch.setattr(providers, "chat", chat)
    res = asyncio.run(cp.run_flow(flow, "", origin={"surface": "task"}))
    return res, store, target, st, asked, events


def test_an_unanswered_question_parks_the_run_and_files_it(tmp_path, monkeypatch):
    res, store, target, _st, asked, events = _park_one(tmp_path, monkeypatch)
    assert asked and asked[0]["tool"] == "write_file" and asked[0]["park"] is True
    assert res["status"] == "parked"
    assert not Path(target).exists(), "nothing ran while it waited"

    flow_run = store.fabric_run(res["run_id"])
    assert flow_run["status"] == "parked" and not flow_run["finished_at"]
    kid = store.fabric_runs(parent_run=res["run_id"])[0]
    assert kid["status"] == "parked", "the specialist that asked is waiting too"

    row = store.park_get(res["run_id"])
    assert row["state"] == "waiting" and row["expires_at"] > time.time()
    item = store.brief_get(row["brief_id"])
    assert item["kind"] == "decide" and item["options"] == ["Allow", "Deny"]
    assert briefmod.parked_run(item) == res["run_id"]
    assert "writer" in item["title"] and "write_file" in item["title"]
    assert "paused where it stopped" in item["body"]
    kinds = [e.get("event") for e in events if e.get("type") == "fabric_event"]
    assert "parked" in kinds and "flow_end" not in kinds, "a waiting run has not ended"


def test_after_a_restart_allow_carries_the_run_on_from_where_it_stopped(tmp_path, monkeypatch):
    res, store, target, st, _asked, _ev = _park_one(tmp_path, monkeypatch)
    rid = res["run_id"]

    # a new server: new store connection, new control plane, same database
    _c, store2, cp2, events2, asked2 = _plane(tmp_path, answer=True)
    assert cp2.answer_parked(rid, True) == {"ok": True}
    out = asyncio.run(cp2.resume_parked(rid))

    assert out["status"] == "ok", out
    assert out["content"] == "The note is written."
    assert Path(target).read_text() == "hello", "the step it asked about ran, once"
    assert out["run_id"] == rid, "the same run carried on, not a new one"
    assert not asked2, "the person's answer stood in for the approver: nobody was asked twice"
    assert store2.park_get(rid) is None
    assert store2.fabric_run(rid)["status"] == "ok"
    kid = store2.fabric_runs(parent_run=rid)[0]
    assert kid["status"] == "ok" and kid["output"] == "Wrote the note."
    assert {a["handle"] for a in store2.artifact_index(rid)} >= {"a1"}, \
        "the specialist's work landed on the same board"
    # the resumed model saw its own earlier call, answered, not a restart of the task
    resumed = st["seen"][2]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "w1" for m in resumed)
    assert sum(1 for m in resumed if m.get("role") == "user") == 1


def test_deny_carries_the_run_on_without_the_step(tmp_path, monkeypatch):
    res, store, target, st, _a, _e = _park_one(tmp_path, monkeypatch)
    _c, store2, cp2, _e2, _a2 = _plane(tmp_path)
    cp2.answer_parked(res["run_id"], False)
    out = asyncio.run(cp2.resume_parked(res["run_id"]))
    assert out["status"] == "ok"
    assert not Path(target).exists()
    told = [m for m in st["seen"][2] if m.get("tool_call_id") == "w1"][0]["content"]
    assert told.startswith("[denied]"), "the model is told no, in the tool's own result"


def test_a_deny_written_while_it_waited_still_refuses_the_step(tmp_path, monkeypatch):
    res, store, target, _st, _a, _e = _park_one(tmp_path, monkeypatch)
    _c, store2, cp2, _e2, _a2 = _plane(tmp_path)
    store2.add_grant("subagent", "writer", "fs.write", "*", effect="deny")
    cp2.answer_parked(res["run_id"], True)
    asyncio.run(cp2.resume_parked(res["run_id"]))
    assert not Path(target).exists(), "an answer is not a way round the gate"


def test_one_answer_counts_once(tmp_path, monkeypatch):
    res, store, *_ = _park_one(tmp_path, monkeypatch)
    _c, store2, cp2, _e, _a = _plane(tmp_path, answer=True)
    assert cp2.answer_parked(res["run_id"], True)["ok"]
    second = cp2.answer_parked(res["run_id"], False)
    assert not second["ok"] and "already" in second["why"]
    assert store2.park_claim(res["run_id"]) is not None
    assert store2.park_claim(res["run_id"]) is None, "two resumes cannot both start"


def test_a_run_nobody_answered_stops_and_says_so(tmp_path, monkeypatch):
    res, store, *_ = _park_one(tmp_path, monkeypatch)
    rid = res["run_id"]
    store.db.execute("UPDATE fabric_parked SET expires_at=? WHERE run_id=?", (time.time() - 1, rid))
    store.db.commit()
    _c, store2, cp2, _e, _a = _plane(tmp_path)
    brief_id = store2.park_get(rid)["brief_id"]
    got = cp2.sweep_parked()
    assert got["expired"] == 1
    assert store2.fabric_run(rid)["status"] == "expired"
    assert store2.fabric_runs(parent_run=rid)[0]["status"] == "expired"
    assert store2.brief_get(brief_id)["state"] == "done"
    assert store2.park_get(rid) is None
    late = cp2.answer_parked(rid, True)
    assert not late["ok"] and late["why"]


def test_an_answer_given_while_the_server_was_down_is_found_at_start(tmp_path, monkeypatch):
    res, store, *_ = _park_one(tmp_path, monkeypatch)
    # `bento brief decide` with no server: it records the answer and nothing else
    fabric.ControlPlane(_cfg(tmp_path), store, None).answer_parked(res["run_id"], True)
    _c, _s2, cp2, _e, _a = _plane(tmp_path)
    assert cp2.sweep_parked(boot=True)["answered"] == [res["run_id"]]


def test_stop_ends_a_waiting_run_and_closes_its_question(tmp_path, monkeypatch):
    """The inspector shows Stop on a run that has not ended; on a waiting run that
    button must do something, or it is a dead control."""
    res, store, *_ = _park_one(tmp_path, monkeypatch)
    _c, store2, cp2, _e, _a = _plane(tmp_path)
    brief_id = store2.park_get(res["run_id"])["brief_id"]
    assert cp2.cancel(res["run_id"]) is True
    assert store2.fabric_run(res["run_id"])["status"] == "cancelled"
    assert store2.brief_get(brief_id)["state"] == "done"
    assert not cp2.answer_parked(res["run_id"], True)["ok"]


def test_a_run_cut_off_by_a_restart_is_marked_not_left_running(tmp_path):
    _c, store, cp, _e, _a = _plane(tmp_path)
    rid = store.fabric_run_start("flow", "notes", "go", flow="notes")
    got = cp.sweep_parked(boot=True, since=time.time() + 1)
    assert got["interrupted"] == 1
    run = store.fabric_run(rid)
    assert run["status"] == "interrupted" and "stopped" in run["fault"]


def test_a_newer_run_asking_the_same_replaces_the_older(tmp_path, monkeypatch):
    res, store, target, *_ = _park_one(tmp_path, monkeypatch)
    _c, store2, cp2, _e, _a = _plane(tmp_path)
    chat, _st = _script(_turns(target))
    monkeypatch.setattr(providers, "chat", chat)
    res2 = asyncio.run(cp2.run_flow(store2.get_flow("notes"), "", origin={"surface": "task"}))
    assert res2["status"] == "parked"
    assert store2.park_get(res["run_id"]) is None
    assert store2.fabric_run(res["run_id"])["status"] == "cancelled"
    assert [p["run_id"] for p in store2.parked_runs()] == [res2["run_id"]]


def test_a_mission_on_an_agent_cli_does_not_park(tmp_path, monkeypatch):
    """Its conversation lives inside the CLI, which this OS cannot save and carry on,
    so the broker is never offered the third answer."""
    _c, store, cp, _e, asked = _plane(tmp_path)
    monkeypatch.setattr(cp, "_executor", lambda: "claude-code")
    async def fake_exec(agent, task, run_id, engine, model=None):
        return {"content": "", "steps": [], "tokens": {}}
    monkeypatch.setattr(cp, "_run_on_executor", fake_exec)
    flow = _mission(store)
    res = asyncio.run(cp.run_flow(flow, "", origin={"surface": "task"}))
    assert res["status"] != "parked"
    assert store.parked_runs() == []


def test_a_run_with_somebody_answering_does_not_park(tmp_path, monkeypatch):
    """A chat that started a mission hands in its own approver: the person is there,
    and the card is theirs to answer."""
    _c, store, cp, _e, asked = _plane(tmp_path)
    flow = _mission(store)
    chat, _st = _script(_turns(str(tmp_path / "x.txt")))
    monkeypatch.setattr(providers, "chat", chat)

    async def person(name, args, reason, offer=None):
        return False
    res = asyncio.run(cp.run_flow(flow, "", origin={"surface": "gui"}, approver=person))
    assert res["status"] != "parked"
    assert store.parked_runs() == []


def test_the_brief_says_which_choice_is_yes():
    item = {"options": ["Allow", "Deny"], "source": {"type": "parked", "ref": "r1"}}
    assert briefmod.parked_run(item) == "r1"
    assert briefmod.allows(item, "Allow") and briefmod.allows(item, "yes")
    assert not briefmod.allows(item, "Deny") and not briefmod.allows(item, "")
    assert briefmod.parked_run({"source": {"type": "run", "ref": "r1"}}) == ""


# -- the server: the broker's third answer, and the Brief door -----------------------

import pytest                                                      # noqa: E402


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        s = servermod.state["store"]
        s.db.execute("DELETE FROM brief_items")
        s.db.execute("DELETE FROM fabric_parked")
        s.db.commit()
        yield cl, servermod


@pytest.mark.asyncio
async def test_the_broker_answers_park_when_nobody_answers(client):
    _cl, servermod = client
    cfg = servermod.state["cfg"]
    old = dict(cfg.get("fabric") or {})
    cfg["fabric"] = {**old, "approval_timeout": 0.05}
    try:
        store = servermod.state["store"]
        before = len(briefmod.page(store)["items"])
        got = await servermod._flow_approval("r1", "fetch_url", {"url": "https://x"}, "why",
                                             None, {}, park=True)
        assert got is PARK
        assert len(briefmod.page(store)["items"]) == before, \
            "a parked run files its own question; the 'did not wait' item is not filed too"
        got = await servermod._flow_approval("r1", "fetch_url", {"url": "https://x"}, "why",
                                             None, {})
        assert got is False
        assert len(briefmod.page(store)["items"]) == before + 1, \
            "a run that cannot wait still gets the question on the Brief"
    finally:
        cfg["fabric"] = old


def test_allow_on_the_brief_carries_the_run_on(client, monkeypatch):
    cl, servermod = client
    store = servermod.state["store"]
    item = briefmod.add(store, "notes", "rp1", "decide", "notes is waiting for you",
                        options=["Allow", "Deny"], source={"type": "parked", "ref": "rp1"},
                        key="parked:rp1:1")
    store.park_save("rp1", "notes", "write_file:", {"run_id": "rp1"}, item["id"],
                    time.time() + 3600)
    resumed = []

    async def fake_resume(run_id):
        resumed.append((run_id, store.park_get(run_id)["decision"]))
        return {"status": "ok"}
    monkeypatch.setattr(servermod.state["fabric"], "resume_parked", fake_resume)
    j = cl.post(f"/api/brief/{item['id']}/act",
                json={"action": "decide", "choice": "Allow", "wait": True}).json()
    assert j["resumed"] == "rp1" and resumed == [("rp1", "allow")]
    assert j["item"]["state"] == "decided"
    assert "started" not in j, "no second turn is started beside the run carrying on"


def test_answering_a_run_that_stopped_waiting_says_so(client):
    cl, servermod = client
    store = servermod.state["store"]
    item = briefmod.add(store, "notes", "gone", "decide", "notes is waiting for you",
                        options=["Allow", "Deny"], source={"type": "parked", "ref": "gone"},
                        key="parked:gone:1")
    r = cl.post(f"/api/brief/{item['id']}/act", json={"action": "decide", "choice": "Allow"})
    assert r.status_code == 409 and "not waiting" in r.json()["error"]
    assert store.brief_get(item["id"])["state"] == "done"
