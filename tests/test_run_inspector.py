"""The Run Inspector: a mission run told as a story.

Reported as "very weird, there is no intuitiveness of when it ran last, the screen is
so bland, I don't even see agent to agent chat there". What this pins: agents talking
inside a mission are written to the MISSION's run (so a replay shows them, not only a
live screen), and the page reads when, how long, started by what, the runs before it,
and a story with faces built from the same events live and on replay.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric                                        # noqa: E402
from agentos.memory import Store                                  # noqa: E402
from agentos.tools import Toolbox                                 # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos" / "ui" / "src" / "js"


def _cp(tmp_path):
    c = {"agent_name": "Aria", "autonomy": "full", "workspace": str(tmp_path),
         "team": {"talk": "swarm"}}
    store = Store(tmp_path / "t.db")
    for n in ("researcher", "validator"):
        store.save_subagent({"name": n, "soul": f"SOUL-{n}", "tools": ["recall"]})
    tb = Toolbox(c, store)
    sent = []

    async def broadcast(ev):
        sent.append(ev)
    cp = fabric.ControlPlane(c, store, tb, broadcast)

    async def fake_run(defn, task, **kw):
        return {"run_id": "", "status": "ok", "content": "the figure is right", "fault": "",
                "model": "m", "usage": {"in": 1, "out": 1}, "tainted": False}
    cp.run_subagent = fake_run
    return store, cp, sent


def test_talk_inside_a_mission_is_written_to_the_missions_run(tmp_path):
    store, cp, sent = _cp(tmp_path)
    flow_run = store.fabric_run_start("flow", "morning-brief", "go")
    child = store.fabric_run_start("delegate", "researcher", "find it", parent_run=flow_run)
    out = asyncio.run(cp.message("researcher", "validator", "is this figure right?",
                                 ["researcher"], parent_run=child))
    assert "the figure is right" in out
    talk = [e for e in store.fabric_events_for(flow_run) if e["type"] == "talk"]
    assert [t["payload"]["phase"] for t in talk] == ["ask", "reply"]
    assert talk[0]["payload"]["from"] == "researcher" and talk[0]["payload"]["to"] == "validator"
    assert talk[1]["payload"]["text"] == "the figure is right"
    # and it is live too, as a fabric event on the mission's run
    assert any(e.get("event") == "talk" and e.get("run_id") == flow_run for e in sent)


def test_talk_outside_a_mission_is_not_filed_under_anything(tmp_path):
    store, cp, sent = _cp(tmp_path)
    chat_child = store.fabric_run_start("delegate", "researcher", "find it")
    asyncio.run(cp.message("researcher", "validator", "q?", ["researcher"], parent_run=chat_child))
    assert not any(e["type"] == "talk" for e in store.fabric_events_for(chat_child))
    assert not any(e.get("event") == "talk" for e in sent)


def test_a_long_answer_is_cut_before_it_can_break_the_stored_event(tmp_path):
    store, cp, _ = _cp(tmp_path)

    async def long_run(defn, task, **kw):
        return {"run_id": "", "status": "ok", "content": "x" * 5000, "fault": "",
                "model": "m", "usage": {"in": 1, "out": 1}, "tainted": False}
    cp.run_subagent = long_run
    flow_run = store.fabric_run_start("flow", "f", "go")
    child = store.fabric_run_start("delegate", "researcher", "t", parent_run=flow_run)
    asyncio.run(cp.message("researcher", "validator", "q?", ["researcher"], parent_run=child))
    reply = [e for e in store.fabric_events_for(flow_run) if e["type"] == "talk"][-1]
    assert isinstance(reply["payload"], dict) and len(reply["payload"]["text"]) <= 700


def _js(name):
    return (JS / name).read_text()


def test_the_page_says_when_how_long_and_started_by_what():
    fb = _js("13-fabric.js")
    page = fb.split("function renderFlowRun(")[1].split("function fgWhen(")[0]
    for cls in ("fg-meta", "fg-pill", "fg-facts", "fg-runs", "fg-story"):
        assert cls in page, cls
    clock = fb.split("function fgClock(")[1].split("function fgRuns(")[0]
    assert "Started " in clock and "FG_ORIGIN" in clock and "Waiting for you" in clock
    # ticks by the window's clock, which sleeps when nobody can see it
    assert "winTick(w,fgClock,1000" in page
    runs = fb.split("async function fgRuns(")[1].split("function fgFace(")[0]
    assert "fgWatch(" in runs, "a past run is one tap away"


def test_the_story_is_one_computation_live_and_on_replay():
    fb = _js("13-fabric.js")
    apply = fb.split("function fgApply(")[1].split("async function fgLoad(")[0]
    for kind in ("'start'", "'ask'", "'tool'", "'talk'", "'done'", "'wait'", "'end'"):
        assert f"kind:{kind}" in apply, kind
    load = fb.split("async function fgLoad(")[1].split("function fgCol(")[0]
    # replay feeds the stored events through the same fgApply, with their own times
    assert "fgApply(Object.assign(" in load and "_ts:(e.ts||0)*1000" in load
    assert "fgLoadKids(" in load, "what each specialist did comes from its own run"
    story = fb.split("function fgPaintStory(")[1][:3000]
    assert "fgFace(" in story and "fr-bubble" in story
    # a mission is not a person: its rows get the mark, never a face
    face = fb.split("function fgFace(")[1].split("function fgWho(")[0]
    assert "-master" in face and "avatarImg(" in face


def test_the_tap_floor_holds_on_the_inspector():
    css = (ROOT / "agentos/ui/src/css/24-runinspector.css").read_text()
    assert "body.dev-touch .fr-run{" in css and "var(--tap)" in css
    assert "body.dev-touch .fr-link" in css
    assert "prefers-reduced-motion" in css
