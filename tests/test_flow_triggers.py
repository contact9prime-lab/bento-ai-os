"""The clock and the flow: a scheduled task that names a flow starts that flow.

The point of routing this through the existing scheduler rather than a second loop is
that everything around it — due-polling, claim-on-fire, cooldowns, the Tasks app — keeps
working unchanged. These tests assert the seam, not the scheduler.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import flows as flowsmod                              # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.scheduler import Scheduler                            # noqa: E402
from agentos.tools import Toolbox                                  # noqa: E402


class _FakeFabric:
    def __init__(self):
        self.calls = []

    async def run_flow(self, flow, text, **kw):
        self.calls.append((flow["name"], text, kw))
        return {"run_id": "r1", "content": "the digest", "status": "ok"}


@pytest.fixture()
def sched(tmp_path):
    cfg = {"autonomy": "balanced", "workspace": str(tmp_path), "providers": {}}
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher"})
    events = []

    async def broadcast(ev):
        events.append(ev)
    s = Scheduler(cfg, store, Toolbox(cfg, store), broadcast)
    s.fabric = _FakeFabric()
    return s, store, events


def _flow_with_cron(store, at="08:00"):
    flow, _ = flowsmod.save(store, {
        "name": "digest", "mission": "Summarise the day.", "roster": ["researcher"],
        "permissions": {"memory": "read-space"},
        "triggers": [{"kind": "cron", "config": {"type": "daily", "at": at}}]})
    return flow


def test_a_task_that_names_a_flow_runs_the_flow(sched):
    s, store, events = sched
    _flow_with_cron(store)
    task = [t for t in store.list_tasks() if t["flow"] == "digest"][0]

    asyncio.run(s._run_task(task, origin="schedule"))

    assert s.fabric.calls, "the flow never started"
    name, text, kw = s.fabric.calls[0]
    assert name == "digest"
    assert kw["origin"] == {"surface": "task", "ref": task["id"]}
    fin = [e for e in events if e["type"] == "task_finished"][0]
    assert fin["run_id"] == "r1" and "digest" in fin["result"]


def test_the_task_is_rescheduled_like_any_other(sched):
    s, store, events = sched
    _flow_with_cron(store, at="07:00")
    task = [t for t in store.list_tasks() if t["flow"] == "digest"][0]
    before = task["next_run"]
    asyncio.run(s._run_task(task, origin="schedule"))
    after = [t for t in store.list_tasks() if t["flow"] == "digest"][0]
    assert after["next_run"] and after["next_run"] >= before
    assert after["last_result"] == "the digest"


def test_a_task_whose_flow_is_gone_says_so_instead_of_running_a_prompt(sched):
    s, store, events = sched
    _flow_with_cron(store)
    task = [t for t in store.list_tasks() if t["flow"] == "digest"][0]
    flowsmod.delete(store, "digest")           # the trigger row goes, but prove the guard
    store.add_task("orphan", "daily", None, "08:00", 1.0, flow="digest")
    orphan = [t for t in store.list_tasks() if t["prompt"] == "orphan"][0]

    asyncio.run(s._run_task(orphan, origin="schedule"))

    assert not s.fabric.calls, "nothing should have run"
    assert any("gone or disabled" in (l["message"] or "")
               for l in store.list_logs("error", limit=5))
    del task


def test_a_plain_task_is_untouched(sched, monkeypatch):
    """The branch must not change what a scheduled prompt does."""
    s, store, events = sched
    ran = {}

    async def fake_run_prompt(prompt, origin="schedule", title="", space_id=""):
        ran["prompt"] = prompt
        return "cid", "done"
    monkeypatch.setattr(s, "run_prompt", fake_run_prompt)
    store.add_task("check the disk", "daily", None, "08:00", 1.0)
    task = [t for t in store.list_tasks() if t["prompt"] == "check the disk"][0]

    asyncio.run(s._run_task(task, origin="schedule"))
    assert "check the disk" in ran["prompt"]
    assert not s.fabric.calls


def test_os_event_triggers_become_trigger_tasks(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher"})
    flowsmod.save(store, {"name": "watcher", "mission": "watch", "roster": ["researcher"],
                          "permissions": {"memory": "read-space"},
                          "triggers": [{"kind": "os_event",
                                        "config": {"event": "file_change",
                                                   "path": str(tmp_path)}}]})
    task = [t for t in store.list_tasks() if t["flow"] == "watcher"][0]
    assert task["schedule_type"] == "trigger" and task["trigger"] == "file_change"
    assert task["next_run"] is None, "an event-driven task is never time-due"


def test_message_and_webhook_triggers_get_no_task_row(tmp_path):
    """A tasks row with next_run NULL and no trigger kind is a row nothing polls."""
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher"})
    flowsmod.save(store, {"name": "chatty", "mission": "m", "roster": ["researcher"],
                          "permissions": {"memory": "read-space"},
                          "triggers": [{"kind": "message", "config": {"pattern": "hi"}},
                                       {"kind": "webhook", "config": {}}]})
    assert not [t for t in store.list_tasks() if t["flow"] == "chatty"]
    assert len(store.flow_triggers("chatty")) == 2
