"""Missions → History: every run that happened on its own, schedules included
(agentos/runlog.py, scheduler task_runs).

Reported as "I can't find the runs of the schedules in the mission". What these defend:

- every time a schedule fires it leaves a row, with the door to what it produced: the
  conversation for a scheduled prompt, the flow run for a mission;
- a mission started by a schedule is ONE row in the history (its flow run), saying which
  schedule started it; a mission the schedule could not start is a `skipped` row, said;
- the history is filtered by one schedule or one mission, and the Schedule tab's rows
  carry how each schedule's last run went;
- a run still "running" long after it started reads as stopped, never as working;
- the terminal prints the same history with the server down, and the page has the tab,
  the Runs buttons and the launcher word.
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import fabric, flows, providers, runlog                  # noqa: E402
from agentos.memory import Store                                     # noqa: E402
from agentos.policy import PDP                                       # noqa: E402
from agentos.scheduler import Scheduler                              # noqa: E402
from agentos.tools import Toolbox                                    # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _call(name, args, cid="c1"):
    return {"type": "tool_call", "id": cid, "name": name, "args": args}


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


def _world(tmp_path):
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 8, "default_model": "ollama/x",
         "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)

    async def broadcast(ev):
        pass

    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    sch = Scheduler(c, store, tb, broadcast)
    sch.fabric = cp
    store.save_subagent({"name": "researcher", "soul": "research", "tools": ["recall"]})
    return c, store, cp, sch


def _mission(store, name="page-watch", enabled=1):
    flow, _ = flows.save(store, {"name": name, "mission": "Check the page.", "roster": ["researcher"],
                                 "permissions": {"tools": [], "memory": "read-space"}, "sinks": [],
                                 "enabled": enabled})
    return flow


def _task(store, tid):
    return next(t for t in store.list_tasks() if t["id"] == tid)


# ---- a scheduled prompt ----

def test_a_scheduled_prompt_leaves_a_row_with_the_door_to_its_answer(tmp_path, monkeypatch):
    cfg, store, cp, sch = _world(tmp_path)
    monkeypatch.setattr(providers, "chat", _script([[{"type": "text", "text": "Disk is 41% full."}]]))
    msg = sch.create_task("check disk space", "interval", interval_minutes=60)
    tid = msg.split()[2].rstrip(":")
    asyncio.run(sch._run_task(_task(store, tid)))

    runs = store.task_runs(task_id=tid)
    assert len(runs) == 1 and runs[0]["status"] == "ok" and runs[0]["conversation_id"]
    h = runlog.history(store)
    row = next(r for r in h["runs"] if r["task_id"] == tid)
    assert row["kind"] == "prompt" and row["title"] == "check disk space"
    assert row["started_by"] == "on its schedule, every hour"
    assert row["status"] == "ok" and row["said"] == "Disk is 41% full."
    assert row["conversation_id"] == runs[0]["conversation_id"], "the door opens the chat it made"
    conv = store.get_conversation(row["conversation_id"])
    assert conv and conv["origin"] == "schedule"

    s = next(x for x in runlog.schedules(store) if x["id"] == tid)
    assert s["words"] == "every hour" and s["runs_7d"] == 1 and s["last_status"] == "ok"
    assert s["last_conversation"] == row["conversation_id"]


def test_a_failed_prompt_says_failed(tmp_path, monkeypatch):
    cfg, store, cp, sch = _world(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("the model is down")
    monkeypatch.setattr(providers, "chat", boom)
    tid = sch.create_task("summarise mail", "daily", at_time="08:30").split()[2].rstrip(":")
    asyncio.run(sch._run_task(_task(store, tid)))
    row = runlog.history(store, task_id=tid)["runs"][0]
    assert row["status"] == "failed" and row["started_by"] == "on its schedule, daily at 08:30"
    s = next(x for x in runlog.schedules(store) if x["id"] == tid)
    assert s["failed_7d"] == 1 and s["last_status"] == "failed"


# ---- a scheduled mission ----

def test_a_mission_started_by_its_schedule_is_one_row_that_names_the_schedule(tmp_path, monkeypatch):
    cfg, store, cp, sch = _world(tmp_path)
    flow = _mission(store)
    tid = store.add_task("Check the page.", "interval", 3600, None, time.time() + 3600, flow=flow["name"])
    monkeypatch.setattr(providers, "chat", _script([
        [_call("delegate", {"subagent": "researcher", "task": "look"})],
        [{"type": "text", "text": "Nothing changed on the page."}],
        [_call("finish", {"summary": "No change since yesterday."}, cid="c2")],
        [{"type": "text", "text": ""}]]))
    asyncio.run(sch._run_task(_task(store, tid)))

    tr = store.task_runs(task_id=tid)[0]
    assert tr["status"] == "ok" and tr["run_id"], "the firing points at the run it started"
    h = runlog.history(store)
    mine = [r for r in h["runs"] if r["mission"] == "page-watch"]
    assert len(mine) == 1, "one row per run, not one for the firing and one for the flow"
    assert mine[0]["run_id"] == tr["run_id"] and mine[0]["started_by"] == "on its schedule, every hour"
    assert mine[0]["said"] == "No change since yesterday." and mine[0]["scheduled"]
    # filtered by the schedule and by the mission, it is the same run
    assert [r["run_id"] for r in runlog.history(store, task_id=tid)["runs"]] == [tr["run_id"]]
    assert [r["run_id"] for r in runlog.history(store, mission="page-watch")["runs"]] == [tr["run_id"]]
    assert runlog.history(store, task_id=tid)["filter"]["title"] == "page-watch, every hour"


def test_a_mission_the_schedule_could_not_start_is_said(tmp_path):
    cfg, store, cp, sch = _world(tmp_path)
    _mission(store, "news-watch", enabled=0)
    tid = store.add_task("Watch the news.", "daily", None, "07:00", time.time() + 60, flow="news-watch")
    asyncio.run(sch._run_task(_task(store, tid)))
    rows = runlog.history(store, mission="news-watch")["runs"]
    assert len(rows) == 1 and rows[0]["status"] == "skipped"
    assert "switched off" in rows[0]["said"] and rows[0]["started_by"] == "on its schedule, daily at 07:00"


def test_a_mission_run_by_hand_says_who_started_it(tmp_path, monkeypatch):
    cfg, store, cp, sch = _world(tmp_path)
    flow = _mission(store)
    monkeypatch.setattr(providers, "chat", _script([
        [_call("delegate", {"subagent": "researcher", "task": "look"})],
        [{"type": "text", "text": "done"}],
        [_call("finish", {"summary": "ok"}, cid="c2")], [{"type": "text", "text": ""}]]))
    asyncio.run(cp.run_flow(flow, "", origin={"surface": "gui"}))
    row = runlog.history(store)["runs"][0]
    assert row["started_by"] == "started by you" and not row["scheduled"]


# ---- honesty ----

def test_a_run_left_running_reads_as_stopped(tmp_path):
    store = Store(tmp_path / "a.db")
    tid = store.add_task("x", "interval", 60, None, time.time())
    rid = store.task_run_start(store.list_tasks()[0])
    store.db.execute("UPDATE task_runs SET started_at=? WHERE id=?", (time.time() - 4 * 3600, rid))
    store.db.commit()
    assert runlog.history(store, task_id=tid)["runs"][0]["status"] == "stopped"


def test_schedule_words():
    w = runlog.schedule_words
    assert w({"schedule_type": "interval", "interval_seconds": 900}) == "every 15 minutes"
    assert w({"schedule_type": "interval", "interval_seconds": 7200}) == "every 2 hours"
    assert w({"schedule_type": "weekly", "weekday": 0, "at_time": "10:00"}) == "every Monday at 10:00"
    assert w({"schedule_type": "trigger", "trigger": "file_change",
              "trigger_config": '{"path": "~/Downloads"}'}) == "when a file changes in ~/Downloads"
    assert w({"schedule_type": "once"}) == "once"
    assert w(None) == "a schedule that was removed"


def test_old_runs_are_pruned_with_usage(tmp_path):
    store = Store(tmp_path / "a.db")
    store.add_task("x", "interval", 60, None, time.time())
    rid = store.task_run_start(store.list_tasks()[0])
    store.db.execute("UPDATE task_runs SET started_at=? WHERE id=?", (time.time() - 400 * 86400, rid))
    store.db.commit()
    gone = store.prune()
    assert gone.get("task_runs") == 1 and not store.task_runs()


# ---- the faces ----

def test_the_route_and_the_schedule_rows(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        d = cl.get("/api/missions/history").json()
        assert "runs" in d and "counts" in d and d["filter"]["title"] == ""
        t = cl.get("/api/tasks").json()["tasks"]
        assert all("words" in x and "runs_7d" in x for x in t)


def test_the_terminal_prints_the_history_with_the_server_down(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    store = Store(tmp_path / "agentos.db")
    tid = store.add_task("check disk", "interval", 3600, None, time.time() + 60)
    rid = store.task_run_start(next(t for t in store.list_tasks() if t["id"] == tid))
    store.task_run_finish(rid, "ok", "Disk is fine.", conversation_id="c123")
    store.db.close()
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "job", *a], cwd=ROOT,  # noqa: E731
                                    env=env, capture_output=True, text=True, timeout=90)
    r = run("history")
    assert r.returncode == 0, r.stderr
    assert "check disk" in r.stdout and "on its schedule, every hour" in r.stdout
    assert "Disk is fine." in r.stdout and "in Chat (c123)" in r.stdout
    r = run("history", "--task", "nope")
    assert r.returncode == 1 and "no schedule with id nope" in r.stdout and tid in r.stdout


def test_the_page_has_the_tab_the_buttons_and_the_word():
    jobs = (JS / "14a-jobs.js").read_text()
    assert "'history'" in jobs and "'History'" in jobs and "renderJobHistory(body)" in jobs
    assert "jobHistoryFor({mission:" in jobs, "a mission row opens its own runs"
    sched = (JS / "15-scheduler-taskmgr.js").read_text()
    assert "jobHistoryFor({task_id:" in sched, "a schedule row opens its own runs"
    hist = (JS / "14c-history.js").read_text()
    assert "/api/missions/history" in hist and "fgWatch(" in hist and "openConv(" in hist
    places = (JS / "05b-places.js").read_text()
    assert "'Missions → History'" in places and "placeMissions('history')" in places
