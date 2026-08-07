"""The agent's own flow tools — and the one thing they must never let it do.

A flow definition IS a set of standing permissions. So "may define a flow" is a capability
of a different kind from "may fetch a URL", and an agent that could define AND enable one
could grant itself anything by writing a flow that says so. These tests are that boundary.
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
from agentos.policy import MAIN, PDP, Principal, action_of         # noqa: E402
from agentos.tools import ALWAYS_ASK, TOOL_SCHEMAS, Toolbox        # noqa: E402


@pytest.fixture()
def tb(tmp_path):
    cfg = {"autonomy": "full", "workspace": str(tmp_path), "providers": {}}
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher", "soul": "You research."})
    box = Toolbox(cfg, store)
    box.pdp = PDP(cfg, store)
    return box


# ---------------------------------------------------------------------------
# the boundary
# ---------------------------------------------------------------------------

def test_a_flow_made_by_the_agent_is_born_disabled_and_grants_nothing(tb):
    out = asyncio.run(tb.create_flow(
        name="agent-made", mission="Do the thing.",
        roster=[{"subagent": "researcher", "why": "does it"}],
        permissions={"tools": ["fetch_url"], "memory": "read-space"}))

    flow = tb.store.get_flow("agent-made")
    assert flow and flow["enabled"] == 0
    assert [g for g in tb.store.list_grants()
            if (g.get("source_ref") or "") == "flow:agent-made"] == [], \
        "an agent must not be able to grant permissions by writing a definition"
    assert "disabled" in out and "Enable" in out, "it has to say the flow is not live yet"
    assert "would grant" in out, "and what enabling it would cost"


def test_enabling_is_a_separate_capability_that_always_asks(tb):
    """Not a preference — this is the only thing standing between 'the agent wrote a flow'
    and 'the agent granted itself tools'."""
    assert "enable_flow" in ALWAYS_ASK, \
        "enabling must confirm every time, full autonomy included"
    action, resource = action_of("enable_flow", {"name": "x"})
    assert (action, resource) == ("flow.write", "flow:x")
    level, why = tb.risk_of("enable_flow", {"name": "x"})
    assert level == "risky" and "rant" in why


def test_nothing_but_the_user_may_write_a_flow(tb):
    """An app, a subagent or another flow writing one is the privilege-escalation path."""
    for kind in ("app", "subagent", "workflow", "flow"):
        d = tb.pdp.decide(Principal(kind, "x"), "flow.write", "flow:anything")
        assert d.effect == "deny" and d.rule == "builtin-deny", f"{kind} could define a flow"
    assert tb.pdp.decide(MAIN, "flow.write", "flow:anything").effect != "deny"


def test_creating_a_flow_is_risky_so_an_unattended_turn_cannot_do_it_quietly(tb):
    level, why = tb.risk_of("create_flow", {"name": "x"})
    assert level == "risky" and "disabled" in why


# ---------------------------------------------------------------------------
# the tools themselves
# ---------------------------------------------------------------------------

def test_the_tools_are_declared_the_way_every_other_tool_is(tb):
    names = {t["name"] for t in TOOL_SCHEMAS}
    for n in ("create_flow", "enable_flow", "list_flows", "run_flow"):
        assert n in names, f"{n} is missing from TOOL_SCHEMAS"
        assert hasattr(tb, n), f"{n} has a schema but no implementation"


def test_create_flow_can_bring_its_own_specialists(tb):
    asyncio.run(tb.create_flow(
        name="with-agents", mission="m",
        roster=[{"subagent": "scribe"}],
        new_agents=[{"name": "scribe", "soul": "You write.", "tools": ["fetch_url"]}]))
    assert tb.store.get_subagent("scribe")["tools"] == ["fetch_url"]


def test_a_bad_definition_comes_back_as_a_sentence_not_a_traceback(tb):
    out = asyncio.run(tb.create_flow(name="no-roster", mission="m", roster=[]))
    assert out.startswith("[error]") and "roster" in out
    assert tb.store.get_flow("no-roster") is None


def test_enable_flow_reports_what_it_granted(tb):
    asyncio.run(tb.create_flow(name="live-one", mission="m",
                               roster=[{"subagent": "researcher"}],
                               permissions={"tools": ["fetch_url"], "memory": "read-space"}))
    out = asyncio.run(tb.enable_flow("live-one", True))
    assert "live" in out and "granted" in out
    assert tb.store.get_flow("live-one")["enabled"] == 1
    assert [g for g in tb.store.list_grants() if g.get("source_ref") == "flow:live-one"]

    off = asyncio.run(tb.enable_flow("live-one", False))
    assert "off" in off
    assert [g for g in tb.store.list_grants() if g.get("source_ref") == "flow:live-one"] == []


def test_list_flows_says_whether_each_is_live(tb):
    asyncio.run(tb.create_flow(name="one", mission="m", roster=[{"subagent": "researcher"}]))
    out = asyncio.run(tb.list_flows())
    assert "one" in out and "disabled" in out


def test_run_flow_names_the_ones_that_exist_when_you_get_it_wrong(tb):
    asyncio.run(tb.create_flow(name="one", mission="m", roster=[{"subagent": "researcher"}]))
    out = asyncio.run(tb.run_flow("nope"))
    assert out.startswith("[error]") and "one" in out


# ---------------------------------------------------------------------------
# composing a subagent
# ---------------------------------------------------------------------------

DRAFT = '{"name":"disk-watch","soul":"You watch disks.","tools":["system_info","teleport"],' \
        '"skills":[],"autonomy_cap":"balanced","max_steps":8,"max_seconds":240,"notes":"ok"}'
TOOLS = [{"name": "system_info", "description": "disk"}, {"name": "fetch_url", "description": "web"}]


def _compose(store, text=DRAFT, current=None):
    from agentos import providers

    async def fake(cfg, model, prompt, system=""):
        _compose.prompt = prompt
        return text
    providers.complete, real = fake, providers.complete
    try:
        return asyncio.run(flowsmod.compose_subagent({"default_model": "ollama/x"}, store,
                                                     "watch my disk", TOOLS, current=current))
    finally:
        providers.complete = real


def test_a_composed_subagent_cannot_name_a_tool_this_machine_lacks(tmp_path):
    store = Store(tmp_path / "t.db")
    d = _compose(store)
    assert d["tools"] == ["system_info"]
    assert any("teleport" in w for w in d["warnings"])
    assert not store.list_subagents(), "composing writes nothing"


def test_revising_keeps_the_name_so_an_edit_cannot_fork(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "keeper", "soul": "old", "tools": []})
    d = _compose(store, current=store.get_subagent("keeper"))
    assert d["name"] == "keeper"
    assert "REVISE" in _compose.prompt and "old" in _compose.prompt


def test_limits_are_clamped_to_something_sane(tmp_path):
    store = Store(tmp_path / "t.db")
    d = _compose(store, text='{"name":"x","soul":"s","tools":[],"max_steps":999,"max_seconds":99999}')
    assert d["max_steps"] == 40 and d["max_seconds"] == 1800
