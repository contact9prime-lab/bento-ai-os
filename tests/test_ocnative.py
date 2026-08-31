"""Porting a foreign plugin to this OS's own parts: the disclaimer, the brief, the check.

Three claims here can quietly become lies, and each has a test that would catch it:

  · the disclaimer says what will NOT work — if a gap stops being reported, somebody
    enables a plugin believing a boundary exists that does not;
  · the brief is DERIVED — if it ever invents a step the manifest did not declare,
    the agent builds a plausible implementation of something nobody asked for;
  · the check reads the brief — if it drifts from what was asked for, "verified"
    stops meaning anything and becomes the most dangerous word on the screen.
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import ocnative as N                            # noqa: E402
from agentos.memory import Store                             # noqa: E402
from tests.test_ocplugins import LOUD, QUIET                 # noqa: E402


@pytest.fixture()
def store():
    return Store(Path(tempfile.mkdtemp()) / "t.db")


class FakeMCP:
    def __init__(self, names): self.names = names
    def tool_schemas(self): return [{"name": n} for n in self.names]


# --------------------------------------------------------------- the disclaimer

def test_the_gateway_bargain_is_stated_before_anything_is_enabled():
    """The one gap that applies to every un-hosted plugin. If this stops being
    reported, somebody turns a plugin on believing AgentOS can refuse it."""
    c = N.compatibility(QUIET, hosted=False)
    assert c["gaps"], "a plugin left in OpenClaw's gateway always has this gap"
    top = c["gaps"][0]
    assert top["severity"] == "high"
    assert "cannot refuse" in top["what"]
    assert top["remedy"], "a gap with no way forward is a dead end"


def test_hosting_it_here_reports_the_REAL_refusals_not_a_prediction():
    """When a plugin has actually been loaded, the gaps come from that load — the
    refused APIs, the discrepancy and the sandbox verdict — rather than from
    guessing at the manifest."""
    hosting = {
        "unsupported": [{"api": "registerHook:llm_output", "detail": "not hosted"}],
        "discrepancy": "its manifest declares foo, which this host did not see",
        "sandbox": {"network": False, "network_note": "CANNOT CONTAIN the network",
                    "filesystem": True, "filesystem_note": "ok"},
    }
    c = N.compatibility(QUIET, hosted=True, hosting=hosting)
    whats = " ".join(g["what"] for g in c["gaps"])
    assert "registerHook:llm_output" in whats
    assert "did not register" in whats
    assert "network cannot be contained" in whats
    # and the gateway sentence must NOT appear — it is the other bargain
    assert "cannot refuse what this plugin does" not in whats


def test_things_with_no_equivalent_are_named_as_unportable():
    c = N.compatibility(LOUD, hosted=False)
    whats = " ".join(g["what"] for g in c["gaps"])
    assert "host-trusted pre-tool policies" in whats
    assert "rewriting tool results" in whats
    assert "memory" in whats
    assert c["verdict"] == "partial"


def test_the_headline_offers_the_other_road():
    """A disclaimer whose only way forward is Proceed is a formality people learn
    to click through. It has to name the alternative."""
    c = N.compatibility(LOUD, hosted=False)
    assert "rebuild" in c["headline"]


# --------------------------------------------------------------- the brief

def test_the_brief_is_derived_from_the_manifest_and_nothing_else():
    b = N.brief("loud", LOUD, "clawhub:loud")
    items = {i for s in b["steps"] for i in s["items"]}
    # everything asked for traces to something LOUD actually declares
    assert items <= {"twilio", "place_call", "loud"}, items
    assert b["buildable"]


def test_a_manifest_that_declares_nothing_produces_no_steps():
    """The most important negative. Guessing what a plugin called 'voice-call'
    probably does would produce a confident implementation of something nobody
    asked for, and nothing downstream could tell the difference."""
    b = N.brief("mystery", {"id": "mystery", "configSchema": {}})
    assert b["steps"] == [] and b["buildable"] is False
    assert "declares nothing" in N.brief_prompt(b)


def test_an_in_turn_hook_is_reported_unportable_not_silently_dropped(store):
    """It cannot be built and must not become a checkable item — a brief asking
    for a flow named `llm_output` would fail its own acceptance test forever,
    which is how a verification step stops being believed. So it has to leave the
    steps AND appear in what cannot be carried."""
    b = N.brief("loud", LOUD)
    flow_items = {i for s in b["steps"] if s["target"] == "flow" for i in s["items"]}
    assert "llm_output" not in flow_items
    assert any("inside the turn" in g["what"] for g in b["not_portable"])


def test_mcp_servers_port_across_unchanged():
    """The cheapest real win in a port, and the brief should say so rather than
    proposing to rebuild something AgentOS already runs and gates."""
    step = next(s for s in N.brief("loud", LOUD)["steps"] if "twilio" in s["items"])
    assert "unchanged" in step["do"]


def test_the_prompt_carries_the_rules_that_keep_the_build_honest():
    p = N.brief_prompt(N.brief("loud", LOUD))
    assert "do not guess" in p.lower()
    assert "DISABLED" in p
    assert "Never copy a secret" in p
    assert "verify" in p.lower()
    # and it must tell the agent what NOT to attempt
    assert "out of scope" in p


# --------------------------------------------------------------- the check

def test_verify_fails_before_anything_is_built(store):
    v = N.verify(N.brief("loud", LOUD), store, {})
    assert not v["ok"] and v["passed"] == 0
    assert "still missing" in N.verdict_line(v)


def test_verify_passes_once_the_parts_actually_exist(store):
    """Built and checked from ONE document. This is what stops 'done' meaning
    'the agent said done'."""
    b = N.brief("loud", LOUD)
    store.save_flow({"name": "loud", "mission": "x",
                     "roster": [{"subagent": "caller"}], "enabled": False})
    cfg = {"mcp_servers": {"twilio": {"command": "npx"}}}
    v = N.verify(b, store, cfg, mcp=FakeMCP(["mcp_twilio_place_call"]))
    assert v["ok"], v["results"]
    assert v["passed"] == v["checked"] == 3


def test_verify_is_honest_about_what_it_did_not_check(store):
    """It proves reachability, not behaviour. Claiming more would make the word
    'verified' the most dangerous thing on the screen."""
    v = N.verify(N.brief("loud", LOUD), store, {})
    assert "does not prove" in v["note"]


def test_a_configured_server_with_no_live_tools_says_so(store):
    """Configured is not connected. Reporting a pass for a server that is not
    actually offering anything is exactly the false green this exists to avoid."""
    b = N.brief("loud", LOUD)
    v = N.verify(b, store, {"mcp_servers": {"twilio": {}}}, mcp=FakeMCP([]))
    row = next(r for r in v["results"] if r["item"] == "twilio")
    assert row["ok"] and "no tools are live" in row["note"]


def test_a_setting_the_user_declined_is_not_a_failure(store):
    """Failing an unanswered setting would push the agent to invent one, which is
    the exact thing the brief forbids."""
    man = dict(QUIET, configSchema={"type": "object",
                                    "properties": {"api_key": {"type": "string"}}})
    v = N.verify(N.brief("q", man), store, {})
    row = next(r for r in v["results"] if r["target"] == "config")
    assert row["ok"] and "on purpose" in row["note"]
    assert row["item"] == "api_key"
    # and it is excluded from the pass/fail count entirely, so a declined setting
    # cannot make an otherwise-complete build look incomplete
    assert v["checked"] == len([r for r in v["results"] if r["target"] != "config"])


# --------------------------------------------------------------- wiring

def test_the_preview_carries_the_disclaimer_and_the_offer(monkeypatch):
    """One computation, every surface. A warning that differs between the terminal
    and the desktop is one somebody has already got wrong."""
    from agentos import ocplugins as ocp
    monkeypatch.setattr(ocp, "inspect", lambda pid: ({"id": pid, "source": "clawhub:x"}, ""))
    monkeypatch.setattr(ocp, "manifest_of", lambda pid, rec=None: (LOUD, ""))
    monkeypatch.setattr(ocp, "package_json_of", lambda pid, rec=None: {})
    pv = ocp.preview("loud", {})
    assert pv["compatibility"]["gaps"]
    assert pv["native"]["buildable"]


def test_the_brief_and_the_check_are_read_only_actions():
    """Neither writes anything; the building happens through create_flow /
    add_mcp_server / save_skill, each gated on its own terms. A write-shaped
    action here would be a permission for something that does not happen."""
    from agentos import policy as policymod
    for tool in ("port_openclaw_plugin", "verify_openclaw_port"):
        action, _ = policymod.action_of(tool, {"id": "x"})
        assert action == "plugin.read", tool


def test_the_agent_is_told_to_relay_the_check_rather_than_its_own_opinion():
    from agentos.tools import TOOL_SCHEMAS
    by = {t["name"]: t for t in TOOL_SCHEMAS}
    assert {"port_openclaw_plugin", "verify_openclaw_port"} <= set(by)
    d = by["verify_openclaw_port"]["description"]
    assert "not what you believe you did" in d
    b = by["port_openclaw_plugin"]["description"]
    assert "never invent behaviour" in b and "lands disabled" in b


# --------------------------------------------------------------- licensing

def test_the_licence_classifier_does_not_conflate_the_gpl_family():
    """"AGPL" is not "GPL" is not "LGPL". A substring match that conflated them
    would give exactly the wrong sentence about the most consequential one."""
    from agentos.ocplugins import classify_licence as c
    assert c("MIT") == c("Apache-2.0") == c("ISC") == "permissive"
    assert c("LGPL-3.0") == c("MPL-2.0") == "weak-copyleft"
    assert c("GPL-3.0") == c("AGPL-3.0") == c("SSPL-1.0") == "copyleft"
    assert c("UNLICENSED") == "proprietary"
    assert c("") == c("WTFPL-9000") == "unknown"


def test_a_dual_licence_is_read_the_way_it_actually_works():
    """OR lets you choose the best branch; AND binds you to the worst."""
    from agentos.ocplugins import classify_licence as c
    assert c("MIT OR GPL-3.0") == "permissive"
    assert c("MIT AND GPL-3.0") == "copyleft"


def test_no_declared_licence_is_never_softened_into_probably_fine():
    """The strongest statement, not the weakest: with no grant, the default is
    that you have no rights to copy or adapt it."""
    pos = N.licence_position({"spdx": "", "klass": "unknown"}, "port")
    assert pos["needs_ack"]
    assert "not the same as permissive" in pos["implication"]


def test_installing_and_porting_get_different_answers():
    """Running someone's GPL software is what the GPL is for and needs nobody's
    permission. Rebuilding it is a different question, and conflating the two
    would either nag on every install or stay silent on the one that matters."""
    lic = {"spdx": "GPL-3.0", "klass": "copyleft"}
    install = N.licence_position(lic, "install")
    port = N.licence_position(lic, "port")
    assert not install["needs_ack"], "running copyleft software is not a decision"
    assert port["needs_ack"], "rebuilding it is"
    assert install["implication"] != port["implication"]


def test_permissive_never_stops_anybody():
    for action in ("install", "port"):
        assert not N.licence_position({"spdx": "MIT", "klass": "permissive"},
                                      action)["needs_ack"]


def test_the_ask_names_the_licence_and_the_act():
    """"Would you like to continue?" on its own is a question nobody can answer."""
    ask = N.licence_position({"spdx": "AGPL-3.0", "klass": "copyleft"}, "port")["ask"]
    assert "AGPL-3.0" in ask
    assert "does not copy its source" in ask
    assert "cannot make for you" in ask


def test_what_a_port_reads_is_stated_once_for_every_surface():
    assert "does not copy" in N.PORT_READS


def test_a_licence_is_read_from_the_plugins_own_files(tmp_path, monkeypatch):
    from agentos import ocplugins as ocp
    root = tmp_path / "ext" / "p"
    root.mkdir(parents=True)
    (root / ocp.MANIFEST_NAME).write_text('{"id":"p","configSchema":{}}')
    (root / "package.json").write_text('{"name":"p","license":"AGPL-3.0"}')
    lic = ocp.licence_of("p", {"id": "p", "path": str(root)})
    assert lic["spdx"] == "AGPL-3.0" and lic["klass"] == "copyleft"
    assert lic["where"] == "package.json"


def test_a_licence_file_is_read_when_nothing_declares_one(tmp_path):
    from agentos import ocplugins as ocp
    root = tmp_path / "ext" / "p"
    root.mkdir(parents=True)
    (root / ocp.MANIFEST_NAME).write_text('{"id":"p","configSchema":{}}')
    (root / "LICENSE").write_text("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3")
    lic = ocp.licence_of("p", {"id": "p", "path": str(root)})
    assert lic["klass"] == "copyleft" and lic["where"] == "LICENSE"


# --------------------------------------------------------------- the report

def _report(store, cfg=None, mcp=None, lic=None):
    b = N.brief("loud", LOUD)
    v = N.verify(b, store, cfg or {}, mcp=mcp)
    return N.report("loud", b, v, lic or {"spdx": "MIT", "klass": "permissive"})


def test_the_report_separates_ported_outstanding_and_never(store):
    store.save_flow({"name": "loud", "mission": "x",
                     "roster": [{"subagent": "c"}], "enabled": False})
    r = _report(store, {"mcp_servers": {"twilio": {}}}, FakeMCP(["mcp_twilio_place_call"]))
    assert [p["item"] for p in r["ported"]] == ["twilio", "place_call", "loud"]
    assert r["outstanding"] == []
    assert r["not_portable"], "the things with no equivalent must still be listed"


def test_every_unportable_thing_says_what_LOSING_it_costs(store):
    """A list of names with no consequence attached is a list people skim. This is
    the half a migration decision actually turns on."""
    r = _report(store)
    assert r["not_portable"]
    for g in r["not_portable"]:
        assert g["implication"] and len(g["implication"]) > 30, g
    joined = " ".join(g["implication"] for g in r["not_portable"])
    assert "Permissions" in joined          # the budget/guardrail row names the fix
    assert "flow that runs around the turn" in joined


def test_the_report_ends_in_a_proposal_not_a_verdict(store):
    """A gap is not a verdict — it is a thing somebody can decide to have built,
    live with, or keep the original for. All three are always offered."""
    r = _report(store)
    p = r["proposal"]
    assert p["build_the_rest"] is True          # nothing built yet
    assert p["continue_as_is"] is True          # always a real answer
    assert p["keep_the_plugin"] is True
    text = N.report_text(r)
    assert "What would you like to do?" in text
    assert "continue as it is" in text
    assert "keep running the original" in text


def test_continue_as_is_is_offered_even_when_the_port_is_complete(store):
    store.save_flow({"name": "loud", "mission": "x",
                     "roster": [{"subagent": "c"}], "enabled": False})
    r = _report(store, {"mcp_servers": {"twilio": {}}}, FakeMCP(["mcp_twilio_place_call"]))
    assert r["complete"] is True
    assert r["proposal"]["continue_as_is"] is True
    assert r["proposal"]["build_the_rest"] is False   # nothing left to build


def test_the_report_carries_the_licence_position(store):
    r = _report(store, lic={"spdx": "AGPL-3.0", "klass": "copyleft"})
    assert r["licence"]["needs_ack"]
    assert "AGPL-3.0" in N.report_text(r)


def test_the_terminal_and_the_gui_read_one_report(store):
    """A migration where the desktop and the terminal disagree about what got
    carried is a migration nobody can sign off."""
    r = _report(store)
    text = N.report_text(r)
    for g in r["not_portable"]:
        assert g["what"] in text
    assert r["headline"] in text


def test_the_agent_is_told_to_put_the_choice_to_the_user():
    from agentos.tools import TOOL_SCHEMAS
    d = {t["name"]: t for t in TOOL_SCHEMAS}["openclaw_migration_report"]["description"]
    assert "Do not decide for them" in d
    assert "COSTS" in d
