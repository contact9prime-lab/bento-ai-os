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


# --------------------------------------------------------------------------------------
# The whole chain, in one test.
#
# Everything above verifies a link: `reconcile_triggers` writes a `tasks` row, and
# `_run_task` starts a flow when a row names one. Nothing joined them, so the question
# "I scheduled a workflow — does it actually run?" could not be answered by the suite.
# It has four seams and each one is somebody's reasonable place to stop:
#
#   flows.save() → reconcile_triggers → tasks row → due_tasks() → _run_task → run_flow
#
# The seam most likely to rot silently is `due_tasks`: it filters on
# `enabled=1 AND next_run IS NOT NULL AND next_run<=now`, and a flow trigger row that
# ever stopped satisfying that filter would simply never fire — no error, no log, and
# a flow card still showing its schedule.

def test_a_scheduled_flow_travels_the_whole_way_from_save_to_run(sched):
    """Save a flow with a clock, wind the clock forward, tick the scheduler once."""
    import time

    s, store, _ = sched
    flow = _flow_with_cron(store, at="08:00")
    assert flow["enabled"], "a saved flow with a trigger should be armed"

    trigs = store.flow_triggers("digest")
    assert len(trigs) == 1 and trigs[0]["task_id"], "no tasks row was created"

    # The clock is a real column, so make it due the way time would.
    # `list_tasks()` rather than a get-by-id: the Store has no get_task.
    task = next(t for t in store.list_tasks() if t["id"] == trigs[0]["task_id"])
    assert task["flow"] == "digest", "the task does not name the flow"
    store.update_task(task["id"], next_run=time.time() - 1)

    due = [t for t in store.due_tasks(time.time()) if t["id"] == task["id"]]
    assert due, ("due_tasks() does not select the flow's task — it would never fire, "
                 "with no error anywhere and the flow card still showing its schedule")

    asyncio.run(s._run_task(due[0], origin="schedule"))
    assert s.fabric.calls, "the scheduler did not start the flow"
    assert s.fabric.calls[0][0] == "digest"
    assert s.fabric.calls[0][2]["origin"]["surface"] == "task"


def test_disabling_a_flow_takes_it_off_the_clock(sched):
    """The declaration survives; the thing that fires does not. A disabled flow that
    kept its task row would keep running — the one failure worse than not running."""
    import time

    s, store, _ = sched
    _flow_with_cron(store)
    tid = store.flow_triggers("digest")[0]["task_id"]

    flowsmod.set_enabled(store, "digest", False)
    assert not [t for t in store.list_tasks() if t["id"] == tid], \
        "a disabled flow left its clock armed"
    assert store.flow_triggers("digest"), "the trigger declaration was lost"
    assert not [t for t in store.due_tasks(time.time() + 86400) if t.get("flow") == "digest"]

    flowsmod.set_enabled(store, "digest", True)
    again = store.flow_triggers("digest")[0]["task_id"]
    assert again, "re-enabling did not re-arm the clock"
    rearmed = next(t for t in store.list_tasks() if t["id"] == again)
    assert rearmed["flow"] == "digest"


# ---------------------------------------------------------------------------
# An OS event this machine cannot deliver is refused, not stored
# ---------------------------------------------------------------------------

def test_the_os_events_that_need_the_session_are_named_per_mode():
    """Two of the four OS events only reach a machine where AgentOS IS the Linux
    session: the notification daemon claims org.freedesktop.Notifications in DE
    mode only, and the login hook runs in DE/KIOSK only. The other two are polled
    by the scheduler and work headless. One function answers for every surface."""
    assert flowsmod.os_event_problem("notification", "de") == ""
    assert flowsmod.os_event_problem("login", "de") == ""
    assert flowsmod.os_event_problem("login", "kiosk") == ""
    # …and on a machine that is only hosting AgentOS as an app, they cannot fire
    assert flowsmod.os_event_problem("notification", "hosted")
    assert flowsmod.os_event_problem("notification", "kiosk")
    assert flowsmod.os_event_problem("login", "hosted")
    # the two that are polled work everywhere, which is what a headless Pi runs on
    for mode in ("de", "kiosk", "hosted"):
        assert flowsmod.os_event_problem("file_change", mode) == ""
        assert flowsmod.os_event_problem("idle", mode) == ""


def test_the_reason_says_what_would_fix_it():
    """The honesty rule: a missing capability reports why, in a sentence, plus the
    component that would fix it — never a bare refusal."""
    why = flowsmod.os_event_problem("notification", "hosted")
    assert "Linux session" in why, why
    assert "install-session" in why, "the refusal must name the fix"
    assert "webhook" in why, "it must point at a trigger that DOES work here"


def test_a_trigger_that_could_never_fire_is_refused_at_save(monkeypatch):
    """Storing it is the bug: it sits in the editor looking armed for the life of
    the flow and never once fires. Refused with the same sentence the editor greys
    it with — while the same trigger saves fine on a machine that can deliver it."""
    monkeypatch.setattr(flowsmod, "os_event_problem",
                        lambda ev, mode=None: "" if ev in ("file_change", "idle")
                        else "'%s' needs AgentOS to be your Linux session" % ev)
    with pytest.raises(ValueError, match="Linux session"):
        flowsmod._validate_trigger({"kind": "os_event",
                                    "config": {"event": "notification", "match": "invoice"}})
    # the polled ones still validate — the gate is per event, not a blanket refusal
    ok = flowsmod._validate_trigger({"kind": "os_event",
                                     "config": {"event": "file_change", "path": "~/Downloads"}})
    assert ok["config"]["event"] == "file_change"


# ---------------------------------------------------------------------------
# Chaining: a flow finishing starts the next one
# ---------------------------------------------------------------------------

def test_a_flow_can_follow_another_flow():
    """Chaining used to mean the first flow POSTing the second one's webhook — an
    HTTP round trip and a shared secret to say something entirely local. flow_done
    says it in the OS instead."""
    t = flowsmod._validate_trigger({"kind": "flow_done",
                                    "config": {"flow": "Scan", "status": "ok"}})
    assert t["config"] == {"flow": "Scan", "status": "ok"}
    # status defaults to 'any' — a chain usually wants to run either way
    assert flowsmod._validate_trigger(
        {"kind": "flow_done", "config": {"flow": "Scan"}})["config"]["status"] == "any"
    for bad in ({}, {"flow": ""}, {"flow": "Scan", "status": "sometimes"}):
        with pytest.raises(ValueError):
            flowsmod._validate_trigger({"kind": "flow_done", "config": bad})


def test_a_flow_that_follows_itself_is_refused():
    """A loop with no exit. The cooldown would only slow it down, and one trigger on
    its own cannot see the flow's name — so this is caught at the save."""
    body = {"name": "loop", "mission": "m", "roster": [{"subagent": "researcher"}],
            "triggers": [{"kind": "flow_done", "config": {"flow": "LOOP"}}]}
    with pytest.raises(ValueError, match="loop with no way out"):
        flowsmod.validate(body)          # case-insensitive: 'LOOP' is the same flow


def test_a_chained_trigger_needs_no_clock_row():
    """flow_done fires in-process the moment the upstream run ends. A tasks row would
    be a second thing to keep in step, and a clock that never ticks."""
    assert flowsmod._task_fields({"name": "x"},
                                 {"kind": "flow_done",
                                  "config": {"flow": "y", "status": "any"}}) is None


# ---------------------------------------------------------------------------
# A webhook carries no cookie, so the trigger row is what identifies its owner
# ---------------------------------------------------------------------------

def test_a_trigger_records_the_account_that_created_it(tmp_path):
    """A webhook is the one door with no session behind it: the caller is GitHub, not
    a browser. Without an owner on the row the fire resolves to the machine, which on
    a multi-user box is the wrong home entirely — or none, since the trigger lives in
    its owner's own database."""
    store = Store(tmp_path / "t.db")
    tid = store.add_flow_trigger("nightly", "webhook", {}, secret="s3cret", uid="ada")
    row = store.flow_trigger(tid)
    assert row["uid"] == "ada"
    assert row["secret_rotated_at"] > 0, "a minted secret records when it was minted"
    # '' is the single-user machine, exactly as space_id does it elsewhere
    assert store.flow_trigger(
        store.add_flow_trigger("nightly", "webhook", {}, uid=""))["uid"] == ""


def test_rotating_a_hook_secret_revokes_the_old_url(tmp_path):
    """Revoking a leaked key must not need the whole flow re-saved (and so
    re-validated, and possibly re-armed) — the old URL stops working immediately."""
    store = Store(tmp_path / "t.db")
    tid = store.add_flow_trigger("nightly", "webhook", {}, secret="old-one", uid="")
    was = store.flow_trigger(tid)["secret_rotated_at"]
    fresh = store.rotate_hook_secret(tid)
    row = store.flow_trigger(tid)
    assert fresh and fresh != "old-one"
    assert row["secret"] == fresh
    assert row["secret_rotated_at"] >= was, "rotation must be dateable"


def test_a_finished_flow_starts_only_the_followers_that_asked_for_that_outcome(tmp_path):
    """The selection `_fire_flow_done` performs, against real rows.

    Driven through the store rather than mocked because the bug this pins was a type
    error, not a logic one: `flow_triggers` already decodes `config` to a dict, so the
    dispatcher calling `json.loads` on it raised on the first chained run — the shape
    of failure a mocked dict would have hidden completely.
    """
    store = Store(tmp_path / "t.db")
    store.add_flow_trigger("report", "flow_done", {"flow": "scan", "status": "ok"})
    store.add_flow_trigger("alert", "flow_done", {"flow": "scan", "status": "failed"})
    store.add_flow_trigger("always", "flow_done", {"flow": "scan", "status": "any"})

    def followers(name, ok):
        waiting = [t for t in store.flow_triggers(kind="flow_done", enabled_only=True)
                   if ((t.get("config") or {}).get("flow") or "").lower() == name.lower()]
        out = []
        for t in waiting:
            want = ((t.get("config") or {}).get("status") or "any").lower()
            if want == "ok" and not ok:
                continue
            if want == "failed" and ok:
                continue
            out.append(t["flow"])
        return sorted(out)

    assert followers("scan", True) == ["always", "report"]
    assert followers("scan", False) == ["alert", "always"]
    assert followers("something-else", True) == []
    # config comes back decoded — the assumption the dispatcher must hold
    assert isinstance(store.flow_triggers(kind="flow_done")[0]["config"], dict)
