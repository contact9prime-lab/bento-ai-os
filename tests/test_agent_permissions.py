"""The permission matrix for agents invoking agents.

The shape being enforced, end to end:

    a conversation                          -> may it start another agent?      ask, once per agent
      builds one if none fits               -> may it DEFINE an agent?          agent.write, user only
      invokes it                            -> agent.invoke agent:subagent/<n>  remembered as a grant
    the agent it started                    -> may IT start another?            never (built-in deny)
                                            -> may it define one?               never (built-in deny)
    every one of those decisions            -> one audit row                    always

The point of asking once rather than every time is that the grant is scoped to a
single named agent: approving `researcher` is not approving `deploy-bot`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos.memory import Store                          # noqa: E402
from agentos.policy import PDP, MAIN, Principal, action_of  # noqa: E402


def _pdp(tmp_path, autonomy="balanced"):
    store = Store(tmp_path / "t.db")
    return PDP({"autonomy": autonomy}, store), store


def _agent(store, name, **kw):
    store.save_subagent({"name": name, "soul": "you do one thing",
                         "tools": kw.get("tools", []), "skills": kw.get("skills", []),
                         "model": kw.get("model", ""), "max_steps": 8, "max_seconds": 120})


# ------------------------------------------------- the vocabulary

def test_building_and_invoking_are_different_capabilities():
    """They must be grantable apart: "may use the researcher" is not "may invent
    an agent that can do anything and then use it"."""
    assert action_of("create_subagent", {"name": "researcher"}) == (
        "agent.write", "agent:subagent/researcher")
    assert action_of("delegate", {"subagent": "researcher"}) == (
        "agent.invoke", "agent:subagent/researcher")


# ------------------------------------------------- chat -> agent

def test_starting_an_agent_asks_the_first_time(tmp_path):
    pdp, store = _pdp(tmp_path)
    _agent(store, "researcher", tools=["fetch_url", "read_file"])
    dec = pdp.decide(MAIN, "agent.invoke", "agent:subagent/researcher",
                     {"risk": "safe", "surface": "gui"})
    assert dec.effect == "ask", "delegating is not covered by the risk table — it must ask"
    assert dec.grant_offer, "the ask must be answerable with 'allow & remember'"
    assert dec.grant_offer["resource"] == "agent:subagent/researcher"


def test_the_card_says_what_the_agent_will_be_able_to_do(tmp_path):
    """Consent to an actor you cannot picture is consent in name only."""
    pdp, store = _pdp(tmp_path)
    _agent(store, "researcher", tools=["fetch_url", "read_file"], skills=["web-research"])
    dec = pdp.decide(MAIN, "agent.invoke", "agent:subagent/researcher",
                     {"risk": "safe", "surface": "gui"})
    assert "researcher" in dec.reason
    assert "fetch_url" in dec.reason and "read_file" in dec.reason
    assert "web-research" in dec.reason
    assert "8 steps" in dec.reason


def test_approving_one_agent_is_not_approving_the_others(tmp_path):
    pdp, store = _pdp(tmp_path)
    _agent(store, "researcher")
    _agent(store, "deploy-bot")
    store.add_grant("user", "", "agent.invoke", "agent:subagent/researcher")
    assert pdp.decide(MAIN, "agent.invoke", "agent:subagent/researcher",
                      {"risk": "safe"}).effect == "allow"
    assert pdp.decide(MAIN, "agent.invoke", "agent:subagent/deploy-bot",
                      {"risk": "safe"}).effect == "ask"


def test_full_autonomy_does_not_ask(tmp_path):
    """Consistent with the rest of the OS: full autonomy means stop asking."""
    pdp, store = _pdp(tmp_path, autonomy="full")
    _agent(store, "researcher")
    assert pdp.decide(MAIN, "agent.invoke", "agent:subagent/researcher",
                      {"risk": "safe"}).effect == "allow"


def test_unattended_it_is_refused_rather_than_acquired(tmp_path):
    """A scheduled run has nobody to ask. Its approver declines, so the ask ends as a
    denial — which is the point: something running alone must not be able to pick up
    an actor the user never approved. One approval at the desk writes the grant and
    the job works from then on."""
    pdp, store = _pdp(tmp_path)
    _agent(store, "researcher")
    dec = pdp.decide(MAIN, "agent.invoke", "agent:subagent/researcher",
                     {"risk": "safe", "surface": "task"})
    assert dec.effect == "ask"          # the caller's headless approver turns this down
    store.add_grant("user", "", "agent.invoke", "agent:subagent/researcher")
    assert pdp.decide(MAIN, "agent.invoke", "agent:subagent/researcher",
                      {"risk": "safe", "surface": "task"}).effect == "allow"


# ------------------------------------------------- the tree stays two deep

def test_an_agent_may_not_start_or_define_another(tmp_path):
    pdp, _ = _pdp(tmp_path, autonomy="full")     # even at full autonomy
    kid = Principal("subagent", "researcher")
    assert pdp.decide(kid, "agent.invoke", "agent:subagent/anything",
                      {"risk": "safe"}).effect == "deny"
    assert pdp.decide(kid, "agent.write", "agent:subagent/anything",
                      {"risk": "safe"}).effect == "deny"


def test_nothing_but_the_user_may_define_an_agent(tmp_path):
    """A definition IS a capability set, so anything that could write one could hand
    itself capabilities by naming them in a new agent and then calling it."""
    pdp, store = _pdp(tmp_path, autonomy="full")
    for kind, pid in (("app", "notes"), ("subagent", "r"), ("workflow", "w"), ("flow", "f")):
        dec = pdp.decide(Principal(kind, pid), "agent.write", "agent:subagent/x",
                         {"risk": "safe"})
        assert dec.effect == "deny", f"{kind} was allowed to define an agent"
        assert dec.rule == "builtin-deny"
    # ...and a grant cannot buy the way out of a built-in deny
    store.add_grant("app", "notes", "agent.write", "*")
    assert pdp.decide(Principal("app", "notes"), "agent.write", "agent:subagent/x",
                      {"risk": "safe"}).effect == "deny"


# ------------------------------------------------- everything is logged

def test_every_decision_in_the_chain_lands_in_the_ledger(tmp_path):
    pdp, store = _pdp(tmp_path)
    _agent(store, "researcher", tools=["fetch_url"])
    pdp.decide(MAIN, "agent.write", "agent:subagent/researcher", {"risk": "risky"})
    pdp.decide(MAIN, "agent.invoke", "agent:subagent/researcher", {"risk": "safe"})
    pdp.decide(Principal("subagent", "researcher"), "net.fetch", "net:https://example.com",
               {"risk": "safe"})
    seen = {(r["action"], r["principal_kind"], r["principal_id"])
            for r in store.audit_list(limit=50)}
    assert ("agent.write", "user", "") in seen
    assert ("agent.invoke", "user", "") in seen
    assert ("net.fetch", "subagent", "researcher") in seen, \
        "what the agent DID must be attributable to the agent, not to the chat"
