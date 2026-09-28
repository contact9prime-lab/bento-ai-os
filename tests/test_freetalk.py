"""Free talk: the team talks among itself, because a person let it.

Asked for as "allow for a period of 5 mins / 10 mins or 20 messages for agents to just
speak with one another, only when I am permitting them; show the caution of this being
risky but something to try; make sure the tool records everything". What these defend:

- only a person starts it (a route, a caution that must be ticked; no agent tool), it
  is refused while agents messaging each other is off, and one runs at a time;
- it ends on the FIRST of its clock, its message count, a quiet room or Stop, and the
  ceilings hold whatever a request asks for;
- talk mode has no tools at all; act mode has the agent's own tools, and anything
  gated pauses for the person;
- everything is kept: the session is a run, every message a run and a `talk` event,
  the transcript the session's output, and the start and end are ledger rows;
- one log lists every time agents talked to each other, read from those runs;
- each agent can be heard in its own voice.
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric                                         # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP                                     # noqa: E402
from agentos.tools import Toolbox                                  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "agentos" / "ui" / "src" / "js"


def _world(tmp_path, talk="swarm"):
    c = {"agent_name": "Aria", "autonomy": "balanced", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321,
         "team": {"talk": talk}, "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    events = []

    async def broadcast(ev):
        events.append(ev)
    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    for n in ("researcher", "validator", "writer"):
        store.save_subagent({"name": n, "soul": n, "tools": ["recall"]})
    return c, store, cp, events


def _script(cp, lines, calls):
    """run_subagent stand-in: each call says the next scripted line (or passes)."""
    it = iter(lines)

    async def fake(defn, task, kind="delegate", **k):
        calls.append({"who": defn["name"], "kind": kind, "task": task, **k})
        text = next(it, "pass")
        rid = cp.store.fabric_run_start(kind, defn["name"], task, parent_run=k.get("parent_run", ""))
        cp.store.fabric_run_finish(rid, "ok", output=text)
        return {"content": text, "model": "m/1", "status": "ok", "fault": "", "run_id": rid,
                "usage": {}, "steps": [], "tainted": False}
    cp.run_subagent = fake


# ------------------------------------------------------------------ the pure parts

def test_the_limits_hold_whatever_is_asked():
    assert fabric.free_talk_limits(5, 20) == (5, 20)
    assert fabric.free_talk_limits(600, 9000) == (fabric.FREE_TALK_MINUTES[-1], fabric.FREE_TALK_MESSAGES[-1])
    assert fabric.free_talk_limits("x", None) == (5, 20)
    assert fabric.free_talk_limits(0, -3) == (1, 1)


def test_who_a_message_is_for():
    names = ["researcher", "validator", "writer"]
    assert fabric.free_talk_addressee("@writer, can you draft it?", "researcher", names) == "writer"
    assert fabric.free_talk_addressee("I agree with Validator here.", "writer", names) == "validator"
    assert fabric.free_talk_addressee("@researcher talking to myself", "researcher", names) == ""
    assert fabric.free_talk_addressee("rewriter is not a name here", "researcher", names) == ""


def test_the_floor_goes_to_who_was_spoken_to_then_to_who_waited_longest():
    names = ["researcher", "validator", "writer"]
    assert fabric.free_talk_next(names, []) == "researcher"
    t = [{"speaker": "researcher", "to": "writer"}]
    assert fabric.free_talk_next(names, t) == "writer"
    t = [{"speaker": "researcher", "to": ""}, {"speaker": "validator", "to": ""}]
    assert fabric.free_talk_next(names, t) == "writer"
    t.append({"speaker": "writer", "to": "writer"})         # nobody talks to themselves
    assert fabric.free_talk_next(names, t) == "researcher"
    # found live: two who kept answering each other held the floor, and the third
    # never spoke. Nobody waits more than a lap of the room.
    pingpong = [{"speaker": "researcher", "to": "validator"}, {"speaker": "validator", "to": "researcher"},
                {"speaker": "researcher", "to": "validator"}]
    assert fabric.free_talk_next(names, pingpong) == "writer"


# ------------------------------------------------------------------ who may start it

def test_only_when_agents_may_talk_and_one_at_a_time(tmp_path):
    _c, _s, cp, _ = _world(tmp_path, talk="off")
    with pytest.raises(ValueError, match="off"):
        cp.start_free_talk(uid="u")
    _c, _s, cp, _ = _world(tmp_path / "b")
    with pytest.raises(ValueError, match="nobody|no agent called ghost"):
        cp.start_free_talk(["researcher", "ghost"], uid="u")
    with pytest.raises(ValueError, match="two"):
        cp.start_free_talk(["researcher"], uid="u")
    cp.start_free_talk(uid="u")
    with pytest.raises(ValueError, match="already"):
        cp.start_free_talk(uid="u")
    cp.start_free_talk(uid="someone else")                  # per person


def test_no_agent_can_start_one():
    tools = (ROOT / "agentos" / "tools.py").read_text()
    assert "free_talk" not in tools and "freetalk" not in tools
    srv = (ROOT / "agentos" / "server.py").read_text()
    route = srv.split('@app.post("/api/team/freetalk")', 1)[1].split("\n@app.", 1)[0]
    assert 'b.get("understood") is not True' in route, "the caution must be ticked"


# ------------------------------------------------------------------ a whole free talk

def test_it_ends_on_the_message_count_and_keeps_everything(tmp_path):
    c, store, cp, events = _world(tmp_path)
    calls = []
    _script(cp, ["@validator, should we test the launch page first?",
                 "@researcher, yes, and the signup flow.",
                 "@writer I can summarise what we find.",
                 "@researcher, noted.", "more", "more"], calls)
    s = cp.start_free_talk(uid="", topic="the launch", minutes=5, messages=4)
    said = []

    async def say(e):
        said.append(e)
    res = asyncio.run(cp.run_free_talk(s["id"], say=say))
    assert res["reason"] == "messages" and len(res["transcript"]) == 4
    # the floor followed who was spoken to
    assert [e["speaker"] for e in res["transcript"]] == ["researcher", "validator", "researcher", "writer"]
    assert res["transcript"][0]["to"] == "validator"
    # talk mode: no tools, nothing to ask about, each message a run under the session
    assert all(k["kind"] == "freetalk" and k["no_tools"] and not k["escalate"]
               and k["parent_run"] == s["id"] for k in calls)
    # the record: the session run, a talk event per message, the transcript as output
    run = store.fabric_run(s["id"])
    assert run["kind"] == "freetalk" and run["status"] == "ok" and run["steps"] == 4
    assert "@validator" in run["output"] and "the launch" in run["input"]
    talk = [e for e in store.fabric_events_for(s["id"]) if e["type"] == "talk"]
    assert len(talk) == 4 and talk[1]["payload"]["from"] == "validator"
    assert len(said) == 4
    # the ledger: the person started it and it ended, both pointing at the session
    rows = [r for r in store.audit_list(action="team.freetalk")]
    assert len(rows) == 2 and all(r["run_id"] == s["id"] for r in rows)
    assert any("started free talk" in r["detail"] for r in rows)
    assert any("ended" in r["detail"] and "message limit" in r["detail"] for r in rows)
    assert cp.free_talks("")[0]["status"] == "ended"


def test_act_mode_has_tools_and_asks_the_person(tmp_path):
    c, store, cp, _ = _world(tmp_path)
    calls = []
    _script(cp, ["@validator hi", "@researcher hi"], calls)
    s = cp.start_free_talk(uid="", mode="act", messages=2)
    asyncio.run(cp.run_free_talk(s["id"]))
    assert calls and all(not k["no_tools"] and k["escalate"] for k in calls)
    assert "use your tools" in calls[0]["task"]


def test_a_quiet_room_ends_it(tmp_path):
    _c, store, cp, _ = _world(tmp_path)
    _script(cp, ["@validator one thing", "pass", "pass", "pass"], [])
    s = cp.start_free_talk(uid="", messages=40)
    res = asyncio.run(cp.run_free_talk(s["id"]))
    assert res["reason"] == "quiet" and len(res["transcript"]) == 1


def test_the_clock_and_stop_end_it(tmp_path):
    _c, store, cp, _ = _world(tmp_path)
    _script(cp, ["@validator a", "@researcher b"] * 10, [])
    s = cp.start_free_talk(uid="", messages=40)
    cp._free_talks()[s["id"]]["until"] = time.time() - 1
    assert asyncio.run(cp.run_free_talk(s["id"]))["reason"] == "time"

    _c, store, cp, _ = _world(tmp_path / "b")
    calls = []
    lines = iter(["@validator a", "@researcher b", "@validator c"])

    async def fake(defn, task, kind="delegate", **k):
        calls.append(1)
        if len(calls) == 2:
            assert cp.stop_free_talk(sid, uid="")
        return {"content": next(lines), "model": "m", "status": "ok", "fault": "",
                "run_id": "r", "usage": {}, "steps": []}
    cp.run_subagent = fake
    sid = cp.start_free_talk(uid="", messages=40)["id"]
    res = asyncio.run(cp.run_free_talk(sid))
    assert res["reason"] == "stopped" and len(calls) == 2
    assert cp.store.fabric_run(sid)["status"] == "cancelled"
    assert not cp.stop_free_talk(sid, uid=""), "an ended talk cannot be stopped again"


def test_run_subagent_takes_the_tools_away_in_talk_mode():
    src = (ROOT / "agentos" / "fabric.py").read_text()
    body = src.split("    async def run_subagent(", 1)[1].split("\n    async def ", 1)[0]
    assert 'kind == "vote" or no_tools' in body
    assert '"freetalk")' in body.split("talks = team_talk", 1)[1].split("\n", 1)[0], \
        "a free-talk message never asks a colleague on top of the talk"


# ------------------------------------------------------------------ the log

def test_one_log_of_every_time_agents_talked(tmp_path):
    _c, store, cp, _ = _world(tmp_path)
    _script(cp, ["@validator a", "@researcher b"], [])
    s = cp.start_free_talk(uid="", messages=2, topic="pricing")
    asyncio.run(cp.run_free_talk(s["id"]))
    rid = store.fabric_run_start("message", "writer",
                                 "researcher (another agent on this team) asks you:\n\n"
                                 "Is the draft ready?\n\nAnswer researcher directly")
    store.fabric_run_finish(rid, "ok", output="Almost, ten minutes.")
    for who in ("researcher", "validator"):
        store.fabric_run_start("huddle", who, "You are x.\n\nQUESTION: ship friday?\n\nSO FAR")
    log = fabric.talk_log(store)
    kinds = [e["kind"] for e in log]
    assert kinds.count("freetalk") == 1 and kinds.count("ask") == 1 and kinds.count("huddle") == 1
    ft = next(e for e in log if e["kind"] == "freetalk")
    assert ft["title"] == "pricing" and ft["messages"] == 2 and set(ft["who"]) == {"researcher", "validator", "writer"}
    ask = next(e for e in log if e["kind"] == "ask")
    assert ask["who"] == ["researcher", "writer"] and ask["title"] == "Is the draft ready?"
    assert "ten minutes" in ask["detail"]
    hd = next(e for e in log if e["kind"] == "huddle")
    assert hd["messages"] == 2 and hd["title"] == "ship friday?"


# ------------------------------------------------------------------ the faces

def test_the_page_offers_it_with_the_caution_and_draws_it():
    ft = (JS / "24f-freetalk.js").read_text()
    assert "Experimental, and it can cost money" in ft and "I understand" in ft
    assert "understood:true" in ft and "disabled" in ft
    st = (JS / "11-settings.js").read_text()
    assert "s-team-freetalk" in st and "s-team-talklog" in st
    assert "case 'freetalk'" in (JS / "09-websocket.js").read_text()
    chat = (JS / "10-chat.js").read_text()
    assert "freeTalkRender(msg)" in chat and "origin==='freetalk'" in chat
    assert "phase==='say'" in (JS / "13-fabric.js").read_text(), "the Run Inspector replays it"


def test_the_terminal_has_it():
    main = (ROOT / "agentos" / "__main__.py").read_text()
    assert '"freetalk", "log"' in main and "--messages" in main and "--act" in main
    assert "fabricmod.talk_log(store" in main


def test_each_agent_speaks_in_its_own_voice():
    v = (JS / "08-wallpaper-jarvis-voice.js").read_text()
    assert "function agentVoice(" in v and "function voiceAgentLine(" in v
    assert "voiceAgentLine(" in (JS / "10b-huddle.js").read_text()
    assert "voiceAgentLine(" in (JS / "24f-freetalk.js").read_text()
    core = (JS / "00-core.js").read_text()
    speak = core.split("function jarvisSpeakAndListen(", 1)[1].split("\n}", 1)[0]
    assert "speechSynthesis.cancel()" not in speak, "the lead's reply queues after the agents"
    # speech has no "@": a spoken huddle is the names it opens with
    ask = core.split("function jarvisAsk(", 1)[1].split("\n}", 1)[0]
    assert "voiceAddress(text)" in ask


def test_a_spoken_request_opens_with_addresses():
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    src = (JS / "08-wallpaper-jarvis-voice.js").read_text()
    fn = src.split("function voiceAddress(", 1)[1].split("\n}", 1)[0]
    prog = ("var VOICE_AGENTS=['researcher','writer','validator'];function voiceAddress(" + fn + "\n}"
            "\nfor(const t of process.argv.slice(1))console.log(voiceAddress(t))")
    out = subprocess.run(["node", "-e", prog, "at researcher, at writer, should we ship?",
                          "ask writer to draft it", "look at writer's draft", "what time is it"],
                         capture_output=True, text=True, timeout=20).stdout.splitlines()
    assert out == ["@researcher @writer should we ship?", "@writer draft it",
                   "look at writer's draft", "what time is it"]
