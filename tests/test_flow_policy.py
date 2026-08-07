"""What a flow may do, and what nothing can talk it into.

Three boundaries are asserted directly rather than inferred from behaviour, because each
one is a single line in policy.py that a later refactor could quietly drop:
the roster, the two-deep cap, and the skill allow-list.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import flows as flowsmod                              # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP, Principal                          # noqa: E402


@pytest.fixture()
def world(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher", "skills": ["webapp-testing"]})
    store.save_subagent({"name": "writer"})
    store.save_subagent({"name": "outsider"})
    flow, _ = flowsmod.save(store, {
        "name": "digest", "mission": "summarise", "roster": ["researcher"],
        "permissions": {"tools": ["fetch_url"], "skills": ["webapp-testing"],
                        "memory": "read-space"}})
    return store, PDP({"autonomy": "balanced"}, store), flow


def test_a_flow_may_invoke_only_its_roster(world):
    store, pdp, flow = world
    F = Principal("flow", "digest")
    assert pdp.decide(F, "agent.invoke", "agent:subagent/researcher").effect == "allow"
    d = pdp.decide(F, "agent.invoke", "agent:subagent/outsider")
    assert d.effect == "deny" and d.rule == "roster"


def test_delegation_has_no_default_so_an_unlisted_agent_is_not_reachable(world):
    """`delegate` is not in risk_of's table, so it arrives as 'safe'. Without the roster
    deny in _default it would be allowed outright — this is load-bearing, not belt."""
    store, pdp, flow = world
    d = pdp.decide(Principal("flow", "never-defined"), "agent.invoke",
                   "agent:subagent/researcher")
    assert d.effect == "deny" and d.rule == "roster"


def test_a_roster_member_of_an_unenabled_flow_asks_rather_than_refusing(tmp_path):
    """A flow you drafted holds no grants. Denying its delegations outright would make a
    test run pointless — the master could never call anyone — so it escalates instead."""
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "greeter"})
    store.save_subagent({"name": "stranger"})
    flowsmod.save(store, {"name": "draft-flow", "mission": "m", "roster": ["greeter"],
                          "permissions": {"memory": "read-space"}, "enabled": 0})
    pdp = PDP({"autonomy": "balanced"}, store)
    F = Principal("flow", "draft-flow")

    on_roster = pdp.decide(F, "agent.invoke", "agent:subagent/greeter")
    assert on_roster.effect == "ask" and on_roster.rule == "roster-ungranted"
    assert on_roster.grant_offer, "answering 'Always' has to be able to write the grant"

    # not on the roster is still a flat refusal — there is nothing to ask about
    off = pdp.decide(F, "agent.invoke", "agent:subagent/stranger")
    assert off.effect == "deny" and off.rule == "roster"

    # and enabling it turns the ask into an allow, with no prompt at all
    flowsmod.set_enabled(store, "draft-flow", True)
    pdp = PDP({"autonomy": "balanced"}, store)
    assert pdp.decide(F, "agent.invoke", "agent:subagent/greeter").effect == "allow"


def test_the_tree_is_exactly_two_deep(world):
    """The cap is the gate, not a counter somebody has to remember to increment."""
    store, pdp, flow = world
    d = pdp.decide(Principal("subagent", "researcher"), "agent.invoke",
                   "agent:subagent/writer")
    assert d.effect == "deny" and d.rule == "builtin-deny"


def test_a_flow_may_never_rewrite_the_os(world):
    store, pdp, flow = world
    d = pdp.decide(Principal("flow", "digest"), "tool.use", "tool:update_soul {}")
    assert d.effect == "deny" and d.rule == "builtin-deny"


def test_declared_skills_become_an_allow_list(world):
    store, pdp, flow = world
    R = Principal("subagent", "researcher")
    assert pdp.decide(R, "skill.use", "skill:webapp-testing").effect == "allow"
    d = pdp.decide(R, "skill.use", "skill:something-else")
    assert d.effect == "deny" and d.rule == "skill-allowlist"


def test_a_subagent_that_lists_no_skills_is_unrestricted(world):
    """The pre-existing behaviour: an allow-list you did not write is not one."""
    store, pdp, flow = world
    assert pdp.decide(Principal("subagent", "writer"), "skill.use",
                      "skill:anything").effect != "deny"


def test_memory_scope_denies_writing_without_denying_reading(world):
    store, pdp, flow = world
    R = Principal("subagent", "researcher")
    assert pdp.decide(R, "memory.write", "memory:user").effect == "deny"
    assert pdp.decide(R, "kg.write", "kg:*").effect == "deny"
    assert pdp.decide(R, "memory.read", "memory:user").effect != "deny"


def test_memory_none_closes_reading_too(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher"})
    flowsmod.save(store, {"name": "sealed", "mission": "m", "roster": ["researcher"],
                          "permissions": {"memory": "none"}})
    pdp = PDP({"autonomy": "balanced"}, store)
    assert pdp.decide(Principal("subagent", "researcher"), "memory.read",
                      "memory:user").effect == "deny"


def test_webhook_is_a_real_io_gate(world):
    """A grant scoped to the desk must not apply to something posting from the internet."""
    from agentos.policy import SURFACES, surface_allows
    assert "webhook" in SURFACES
    assert surface_allows("gui", "webhook") is False
    assert surface_allows("webhook", "webhook") is True


def test_a_hand_written_grant_outlives_the_definition_that_looks_like_it(world):
    """add_grant dedupes on the tuple; provenance is part of that key, or re-saving a
    flow would silently revoke a permission somebody deliberately gave."""
    store, pdp, flow = world
    mine = store.add_grant("subagent", "researcher", "tool.use", "tool:fetch_url*",
                           source="user", note="I meant this")
    flowsmod.save(store, {"name": "digest", "mission": "summarise",
                          "roster": ["researcher"], "permissions": {"memory": "read-space"}})
    assert any(g["id"] == mine for g in store.list_grants()), "the user's grant was revoked"
    assert not [g for g in store.list_grants()
                if g.get("source_ref") == "flow:digest" and g["resource"] == "tool:fetch_url*"]
