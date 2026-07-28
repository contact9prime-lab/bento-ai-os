"""Automations: the store, the step validator, and the three agent tools.

An automation is replayed unattended — from a hot corner, a schedule, or the
agent naming it — so the contract these tests pin down is that a malformed step
is rejected at save time, never at 7am on a Monday, and that saving an existing
name EDITS it rather than quietly forking a second automation with the same name.
"""

import asyncio
import json
import os
import tempfile

import pytest

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod                     # noqa: E402
from agentos.memory import Store                         # noqa: E402
from agentos.server import _clean_steps                  # noqa: E402
from agentos.tools import (AUTOMATION_TOOL_SCHEMAS,      # noqa: E402
                           TOOL_SCHEMAS, Toolbox, _automation_step_label)


@pytest.fixture()
def toolbox(tmp_path):
    cfg = cfgmod.load_config()
    cfg["workspace"] = str(tmp_path)
    cfg["sandbox"] = {"enabled": False, "root": ""}
    return Toolbox(cfg, Store(tmp_path / "db.sqlite"))


# ---------------------------------------------------------------------------
# step validation
# ---------------------------------------------------------------------------

def test_clean_steps_keeps_every_supported_kind():
    steps = [
        {"kind": "app", "app": "chat"},
        {"kind": "action", "action": "deck"},
        {"kind": "theme", "theme": "minimal"},
        {"kind": "wallpaper", "wallpaper": "spatial"},
        {"kind": "desktop", "desk": 2},
        {"kind": "agent", "prompt": "summarise my day"},
        {"kind": "wait", "ms": 500},
    ]
    assert _clean_steps(steps) == steps


@pytest.mark.parametrize("bad", [
    {"kind": "rm -rf"},          # not a known kind
    {"app": "chat"},             # no kind at all
    "open chat",                 # not even an object
    None,
])
def test_clean_steps_drops_anything_it_cannot_replay(bad):
    assert _clean_steps([bad]) == []


def test_clean_steps_clamps_out_of_range_values():
    out = _clean_steps([{"kind": "desktop", "desk": 99}, {"kind": "wait", "ms": 10 ** 9}])
    assert out[0]["desk"] == 9
    assert out[1]["ms"] == 60000


def test_clean_steps_is_bounded():
    assert len(_clean_steps([{"kind": "wait", "ms": 1}] * 500)) == 40


def test_clean_steps_survives_junk_input():
    assert _clean_steps(None) == []
    assert _clean_steps([]) == []


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

def test_saving_the_same_name_edits_in_place(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    first = store.save_automation("Morning", json.dumps([{"kind": "app", "app": "chat"}]))
    again = store.save_automation("Morning", json.dumps([{"kind": "app", "app": "files"}]))
    assert first == again                       # same row, not a fork
    assert len(store.list_automations()) == 1
    assert store.get_automation("Morning")["steps"] == [{"kind": "app", "app": "files"}]


def test_lookup_by_name_is_case_insensitive(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    aid = store.save_automation("Start Work", json.dumps([{"kind": "app", "app": "chat"}]))
    assert store.get_automation("start work")["id"] == aid
    assert store.get_automation(aid)["id"] == aid
    assert store.get_automation("nope") is None


def test_run_counters_advance(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    aid = store.save_automation("Focus", json.dumps([{"kind": "action", "action": "deck"}]))
    store.mark_automation_run(aid)
    store.mark_automation_run(aid)
    row = store.get_automation(aid)
    assert row["runs"] == 2 and row["last_run"] > 0


def test_delete_removes_it(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.save_automation("Gone", json.dumps([{"kind": "wait", "ms": 1}]))
    store.delete_automation("Gone")
    assert store.list_automations() == []


# ---------------------------------------------------------------------------
# the agent tools
# ---------------------------------------------------------------------------

def test_the_three_tools_are_registered_and_dispatchable():
    names = {t["name"] for t in AUTOMATION_TOOL_SCHEMAS}
    assert names == {"list_automations", "run_automation", "save_automation"}
    registered = {t["name"] for t in TOOL_SCHEMAS}
    for n in names:
        assert n in registered, f"{n} missing from TOOL_SCHEMAS"
        assert callable(getattr(Toolbox, n, None)), f"{n} has no implementation"


def test_save_then_list_then_run(toolbox):
    fired = []
    toolbox.broadcast = lambda ev: asyncio.sleep(0, result=fired.append(ev))

    out = asyncio.run(toolbox.save_automation(
        "Start work", json.dumps([{"kind": "app", "app": "chat"},
                                  {"kind": "theme", "theme": "minimal"}]), "🌅"))
    assert "created" in out and "Start work" in out

    listed = asyncio.run(toolbox.list_automations())
    assert "Start work" in listed and "open chat" in listed

    assert "ran automation 'Start work'" in asyncio.run(toolbox.run_automation("start work"))
    ran = [e for e in fired if e["type"] == "automation.run"]
    assert len(ran) == 1 and ran[0]["automation"]["name"] == "Start work"


def test_saving_an_existing_name_reports_an_edit(toolbox):
    steps = json.dumps([{"kind": "app", "app": "chat"}])
    asyncio.run(toolbox.save_automation("Morning", steps))
    assert "updated" in asyncio.run(toolbox.save_automation("Morning", steps))


def test_bad_input_is_a_sentence_not_a_raise(toolbox):
    assert asyncio.run(toolbox.run_automation("nothing here")).startswith("[error]")
    assert asyncio.run(toolbox.save_automation("X", "not json")).startswith("[error]")
    assert asyncio.run(toolbox.save_automation("X", '{"kind":"app"}')).startswith("[error]")
    assert asyncio.run(toolbox.save_automation("X", '[{"kind":"nope"}]')).startswith("[error]")


def test_list_is_helpful_when_empty(toolbox):
    assert "no automations saved yet" in asyncio.run(toolbox.list_automations())


def test_every_step_kind_has_a_label():
    for kind in ("app", "action", "theme", "wallpaper", "desktop", "wait", "agent"):
        label = _automation_step_label({"kind": kind, "app": "chat", "action": "deck",
                                        "theme": "minimal", "wallpaper": "clay",
                                        "desk": 1, "ms": 10, "prompt": "hi"})
        assert label and label != kind
