"""Making a flow: creating its agents with it, and drafting one from a sentence.

The composer's job is not to be right — it is to be *inspectable*. What matters here is
that it writes nothing, that it cannot smuggle in a tool or an agent this machine does not
have, and that a draft can be previewed before its specialists exist.
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
from agentos import providers                                      # noqa: E402
from agentos.memory import Store                                   # noqa: E402

TOOLS = [{"name": "fetch_url", "description": "get a page"},
         {"name": "save_report", "description": "write a report"},
         {"name": "system_info", "description": "disk, memory"}]


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "t.db")


# ---------------------------------------------------------------------------
# creating the agents with the flow
# ---------------------------------------------------------------------------

def test_a_flow_can_bring_its_own_specialists(store):
    flow, report = flowsmod.save(store, {
        "name": "digest", "mission": "Summarise the week.",
        "new_agents": [{"name": "scout", "soul": "You find things.", "tools": ["fetch_url"]},
                       {"name": "scribe", "soul": "You write things."}],
        "roster": ["scout", "scribe"],
        "permissions": {"tools": ["fetch_url"], "memory": "read-space"}})

    assert sorted(report["agents_created"]) == ["scout", "scribe"]
    assert store.get_subagent("scout")["tools"] == ["fetch_url"]
    assert [r["subagent"] for r in flow["roster"]] == ["scout", "scribe"]
    # and they are real principals, granted by the flow that made them
    assert [g for g in store.list_grants()
            if g["principal_id"] == "scout" and g["resource"] == "tool:fetch_url*"]


def test_an_existing_agent_is_never_overwritten(store):
    store.save_subagent({"name": "researcher", "soul": "the one I already tuned",
                         "tools": ["fetch_url", "run_command"]})
    _, report = flowsmod.save(store, {
        "name": "digest", "mission": "m",
        "new_agents": [{"name": "researcher", "soul": "a bland replacement", "tools": []}],
        "roster": ["researcher"], "permissions": {"memory": "read-space"}})

    assert report["agents_created"] == []
    kept = store.get_subagent("researcher")
    assert kept["soul"] == "the one I already tuned"
    assert kept["tools"] == ["fetch_url", "run_command"]


def test_a_draft_previews_before_its_agents_exist(store):
    """The editor must be able to show what a draft would grant while the specialists it
    proposes are still hypothetical."""
    d = flowsmod.validate({"name": "digest", "mission": "m",
                           "new_agents": [{"name": "scout"}], "roster": ["scout"],
                           "permissions": {"tools": ["fetch_url"], "memory": "read-space"}},
                          store)
    res = [g["resource"] for g in flowsmod.declared_grants(d)]
    assert "agent:subagent/scout" in res and "tool:fetch_url*" in res


def test_a_roster_naming_nobody_still_fails(store):
    with pytest.raises(ValueError, match="ghost"):
        flowsmod.validate({"name": "d", "mission": "m", "roster": ["ghost"]}, store)


def test_a_bad_agent_name_is_skipped_not_crashed(store):
    made = flowsmod.ensure_agents(store, [{"name": "has spaces"}, {"name": ""}, {"name": "ok"}])
    assert made == ["ok"]


# ---------------------------------------------------------------------------
# the composer
# ---------------------------------------------------------------------------

DRAFT = """Sure! Here you go:
```json
{"name":"morning-check","description":"disk and news","mission":"Check the disk and report.",
 "new_agents":[{"name":"scout","soul":"You look things up.","tools":["fetch_url","teleport"]}],
 "roster":[{"subagent":"scout","why":"it looks"},{"subagent":"ghost","why":"nonexistent"}],
 "permissions":{"tools":["system_info","mind_control"],"memory":"read-space"},
 "sinks":[{"kind":"origin"}],"triggers":[],"notes":"assumed daily is enough"}
```"""


def _compose(store, text=DRAFT, monkeypatch=None):
    async def fake_complete(cfg, model, prompt, system=""):
        _compose.prompt = prompt
        return text
    providers.complete, real = fake_complete, providers.complete
    try:
        return asyncio.run(flowsmod.compose({"default_model": "ollama/x"}, store,
                                            "check my disk every morning", TOOLS))
    finally:
        providers.complete = real


def test_the_composer_writes_nothing(store):
    before = (len(store.list_flows()), len(store.list_subagents()), len(store.list_grants()))
    _compose(store)
    assert (len(store.list_flows()), len(store.list_subagents()),
            len(store.list_grants())) == before


def test_a_tool_this_machine_does_not_have_is_dropped_and_said_out_loud(store):
    d = _compose(store)
    assert d["permissions"]["tools"] == ["system_info"]
    assert d["new_agents"][0]["tools"] == ["fetch_url"]      # 'teleport' gone
    assert any("mind_control" in w for w in d["warnings"])


def test_a_roster_entry_with_no_agent_behind_it_is_dropped(store):
    d = _compose(store)
    assert [r["subagent"] for r in d["roster"]] == ["scout"]
    assert any("ghost" in w for w in d["warnings"])


def test_the_draft_survives_validation(store):
    """Whatever the model wrote, what comes back must be savable."""
    d = _compose(store)
    ok = flowsmod.validate(d, store)
    assert ok["name"] == "morning-check" and ok["mission"]


def test_the_inventory_is_in_the_prompt(store):
    store.save_subagent({"name": "researcher", "soul": "You research."})
    _compose(store)
    p = _compose.prompt
    assert "researcher: You research." in p, "it must reuse what exists"
    assert "fetch_url" in p and "system_info" in p
    assert "teleport" not in p, "only real tools are offered"


def test_the_flat_trigger_shape_a_model_writes_is_lifted_not_rejected(store):
    """Models reliably write {"type":"cron","at":"06:30"} for the wrapper shape. That is a
    key, not a misunderstanding — losing an otherwise good draft over it is pedantry."""
    assert flowsmod._lift_trigger({"type": "cron", "at": "06:30"}) == \
        {"kind": "cron", "config": {"type": "daily", "at": "06:30"}}
    assert flowsmod._lift_trigger({"event": "file_change", "path": "/tmp"})["kind"] == "os_event"
    assert flowsmod._lift_trigger({"pattern": "vendor:"})["kind"] == "message"
    assert flowsmod._lift_trigger({"minutes": 30})["config"]["type"] == "interval"
    assert flowsmod._lift_trigger({"nonsense": 1}) is None


@pytest.mark.parametrize("given,want", [
    (730, "07:30"), ("730", "07:30"), ("7:30", "07:30"), ("07:30", "07:30"),
    ("7.30", "07:30"), ("7", "07:00"), ("", "08:00"), (None, "08:00")])
def test_a_time_of_day_is_understood_however_it_was_written(given, want):
    """_next_daily silently falls back to 09:00 on anything it cannot split, so `730`
    would have become a job that runs at the wrong hour and never said why."""
    assert flowsmod._at_time(given) == want


@pytest.mark.parametrize("bad", ["quarter past", "25:00", "07:75", "morning"])
def test_an_unreadable_time_is_refused_where_someone_can_see_it(bad):
    with pytest.raises(ValueError, match="time of day"):
        flowsmod._at_time(bad)


# ---------------------------------------------------------------------------
# a draft is a flow you can read, and it holds nothing until you enable it
# ---------------------------------------------------------------------------

def _draft(store, name="morning-check"):
    return flowsmod.save_draft(store, {
        "name": name, "mission": "Check the disk each morning.",
        "new_agents": [{"name": "disk-monitor", "soul": "You watch disks.",
                        "tools": ["system_info"]}],
        "roster": [{"subagent": "disk-monitor", "why": "it watches"}],
        "permissions": {"tools": ["system_info"], "memory": "read-space"},
        "triggers": [{"kind": "cron", "config": {"type": "daily", "at": "08:00"}},
                     {"kind": "webhook", "config": {}}],
        "model": "ollama/x", "notes": "assumed daily", "warnings": [], "request": "…"})


def test_a_drafted_flow_is_inert_until_enabled(store):
    flow, report = _draft(store)

    assert flow["enabled"] == 0
    assert flow["draft"]["model"] == "ollama/x"
    assert flow["draft"]["agents_created"] == ["disk-monitor"]
    # it exists and its agent exists — but it has been granted nothing
    assert store.get_subagent("disk-monitor")
    assert [g for g in store.list_grants()
            if g.get("source_ref") == "flow:morning-check"] == []
    # the trigger DECLARATIONS survive, none of them armed
    trigs = store.flow_triggers("morning-check")
    assert {t["kind"] for t in trigs} == {"cron", "webhook"}
    assert all(not t["enabled"] and not t["task_id"] for t in trigs)
    assert not [t for t in store.list_tasks() if t["flow"] == "morning-check"]


def test_enabling_is_what_grants_and_arms(store):
    _draft(store)
    flow, report = flowsmod.set_enabled(store, "morning-check", True)

    assert flow["enabled"] == 1
    assert report["grants"]["added"] > 0
    live = [g for g in store.list_grants() if g.get("source_ref") == "flow:morning-check"]
    assert any(g["resource"] == "tool:system_info*" for g in live)
    task = [t for t in store.list_tasks() if t["flow"] == "morning-check"]
    assert len(task) == 1 and task[0]["at_time"] == "08:00"
    assert all(t["enabled"] for t in store.flow_triggers("morning-check"))
    assert flow["draft"] == {}, "once enabled it is yours, not a draft"


def test_turning_a_flow_off_takes_its_permissions_back(store):
    """Not only for drafts: a flow you disable has no business keeping standing access."""
    _draft(store)
    flowsmod.set_enabled(store, "morning-check", True)
    secret = store.flow_triggers("morning-check", kind="webhook")[0]["secret"]

    _, report = flowsmod.set_enabled(store, "morning-check", False)

    assert report["grants"]["revoked"] > 0
    assert [g for g in store.list_grants()
            if g.get("source_ref") == "flow:morning-check"] == []
    assert not [t for t in store.list_tasks() if t["flow"] == "morning-check"]
    # the declarations — and the webhook secret — survive, so enabling restores exactly
    # what you wrote rather than a new URL every caller has to be told about
    assert store.flow_triggers("morning-check", kind="webhook")[0]["secret"] == secret
    assert len(store.flow_triggers("morning-check")) == 2


def test_enabling_again_restores_what_you_wrote(store):
    _draft(store)
    for on in (True, False, True):
        flowsmod.set_enabled(store, "morning-check", on)
    assert len([t for t in store.list_tasks() if t["flow"] == "morning-check"]) == 1
    assert [g for g in store.list_grants() if g.get("source_ref") == "flow:morning-check"]


def test_discarding_a_draft_takes_the_agents_it_brought(store):
    _draft(store)
    res = flowsmod.discard(store, "morning-check")
    assert res["ok"] and res["agents_removed"] == ["disk-monitor"]
    assert store.get_subagent("disk-monitor") is None
    assert store.get_flow("morning-check") is None


def test_an_agent_another_flow_uses_survives_the_discard(store):
    _draft(store)
    flowsmod.save(store, {"name": "keeper", "mission": "m", "roster": ["disk-monitor"],
                          "permissions": {"memory": "read-space"}})
    res = flowsmod.discard(store, "morning-check")
    assert res["agents_removed"] == []
    assert store.get_subagent("disk-monitor"), "it is on somebody else's roster"


def test_a_second_draft_of_the_same_thing_does_not_clobber_the_first(store):
    a, _ = _draft(store)
    b, _ = _draft(store)
    assert a["name"] == "morning-check" and b["name"] == "morning-check-2"
    assert store.get_flow("morning-check") and store.get_flow("morning-check-2")


def test_a_revision_does_not_null_out_what_it_did_not_touch(store):
    """A revision returns the whole definition, and models fill untouched fields with null.
    Merged as-is that silently resets a budget somebody tuned."""
    store.save_subagent({"name": "researcher"})
    current = {"name": "keeper", "mission": "the original mission", "roster": [{"subagent": "researcher"}],
               "permissions": {"tools": ["fetch_url"], "memory": "read-space"},
               "max_delegations": 30, "autonomy_cap": "full", "sinks": [{"kind": "notify"}]}
    thin = ('{"name":"keeper","mission":"the original mission","roster":[{"subagent":"researcher"}],'
            '"permissions":{"tools":["fetch_url","system_info"],"memory":"read-space"},'
            '"max_delegations":null,"autonomy_cap":null,"sinks":[{"kind":"notify"}],'
            '"new_agents":[],"triggers":[],"notes":"added system_info"}')

    from agentos import providers

    async def fake(cfg, model, prompt, system=""):
        return thin
    providers.complete, real = fake, providers.complete
    try:
        d = asyncio.run(flowsmod.compose({"default_model": "ollama/x"}, store,
                                         "let it see the disk too", TOOLS, current=current))
    finally:
        providers.complete = real

    assert d["permissions"]["tools"] == ["fetch_url", "system_info"], "the asked-for change landed"
    assert d["max_delegations"] == 30, "a tuned budget survived the edit"
    assert d["autonomy_cap"] == "full"
    assert d["name"] == "keeper", "an edit must never fork into a new flow"


def test_unusable_model_output_says_so_rather_than_guessing(store):
    d = _compose(store, text="I'm afraid I can't help with that.")
    assert d.get("error") and "did not return a usable design" in d["error"]


def test_no_model_configured_is_an_honest_sentence(store):
    async def never(*a, **k):
        raise AssertionError("should not have asked a model")
    providers.complete, real = never, providers.complete
    try:
        d = asyncio.run(flowsmod.compose({}, store, "do a thing", TOOLS))
    finally:
        providers.complete = real
    assert "no model configured" in d["error"]
