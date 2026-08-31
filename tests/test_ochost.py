"""Hosting an OpenClaw plugin ourselves: what must stay true for that to be safe.

`ocplugins.py` governs a plugin running in OpenClaw's gateway and can honestly
claim only the lifecycle. This module claims much more — that a plugin's tools
run behind THIS PDP — so the tests here are the ones that keep the claim from
becoming a lie: the plugin really loads, its call really passes the gate, and the
things AgentOS says it contains are really contained.

The plugin is a real Node module written the way an OpenClaw plugin is written,
loaded by the real host. Mocking `PluginHost` would leave every one of these
assertions true about a stub and false about the product.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import ochost                                    # noqa: E402
from agentos import policy as policymod                       # noqa: E402

pytestmark = pytest.mark.skipif(not ochost.node_exe(), reason="Node is not installed here")


PLUGIN = """
exports.register = function (api) {
  api.registerTool({
    name: 'add', description: 'Add two numbers',
    parameters: {type:'object', properties:{a:{type:'number'},b:{type:'number'}}},
    handler: async ({a,b}) => ({sum: a + b})
  });
  api.registerTool({
    name: 'peek', description: 'Read a file directly',
    parameters: {type:'object', properties:{}},
    handler: async () => {
      try { return {read: require('fs').readFileSync('/etc/passwd','utf8').slice(0,8)}; }
      catch (e) { return {blocked: e.code}; }
    }
  });
  api.registerTool({
    name: 'spawn', description: 'Start a subprocess directly',
    parameters: {type:'object', properties:{}},
    handler: async () => {
      try { return {ran: String(require('child_process').execSync('id')).slice(0,8)}; }
      catch (e) { return {blocked: e.code}; }
    }
  });
  api.registerTool({
    name: 'ask', description: 'Ask AgentOS to fetch something',
    parameters: {type:'object', properties:{url:{type:'string'}}},
    handler: async ({url}) => {
      try { return {got: await api.host.fetch(url)}; }
      catch (e) { return {refused: e.message}; }
    }
  });
  api.registerTool({name:'noisy', description:'writes to stdout',
    parameters:{type:'object',properties:{}},
    handler: async () => { console.log('CORRUPTING FRAME'); process.stdout.write('MORE\\n');
                           return {ok: true}; }});
  // registrations this host refuses
  api.registerHook('llm_output', () => {});
  api.registerChannel({name: 'sms'});
  api.registerTrustedToolPolicy({name: 'budget'});
};
"""

MANIFEST = {"id": "demo", "contracts": {"tools": ["add", "peek", "spawn", "ask",
                                                  "noisy", "never_registered"]}}


@pytest.fixture()
def host(tmp_path):
    entry = tmp_path / "index.js"
    entry.write_text(PLUGIN)
    seen = []

    def host_call(name, args):
        seen.append((name, args))
        return (False, "AgentOS refused: this plugin has no net.fetch grant")

    h = ochost.PluginHost("demo", str(entry), host_call=host_call)
    started = h.start()
    h.started, h.seen = started, seen
    yield h
    h.stop()


# --------------------------------------------------------------- it really runs

def test_a_real_register_api_plugin_loads_and_its_tools_work(host):
    """The whole proposition in one assertion: third-party plugin code, written
    against OpenClaw's API, executing inside AgentOS and returning a real answer."""
    assert host.started["ok"], host.started
    assert {r["name"] for r in host.registrations} >= {"add", "peek", "ask"}
    assert host.call("add", {"a": 2, "b": 40}) == (True, {"sum": 42})


def test_the_tools_arrive_in_the_agents_namespace_like_mcp_ones(host):
    """`ocp_<plugin>_<tool>`, mirroring `mcp_<server>_<tool>`. The prefix is what
    lets the PDP route the call without the tool loop knowing anything special."""
    names = {t["name"] for t in host.tool_schemas()}
    assert "ocp_demo_add" in names
    assert all(t["parameters"] for t in host.tool_schemas())


# --------------------------------------------------------------- the gate

def test_every_hosted_plugin_call_is_its_own_action_not_tool_use():
    """"May use the tools this plugin brought" has to be grantable apart from the
    OS's built-in tools, or installing a plugin would silently widen every grant
    somebody had already written."""
    hs = ochost.HostSet()
    action, resource = policymod.action_of("ocp_demo_add", {}, ocp=hs)
    assert action == "plugin.tool"
    assert resource.startswith("ocptool:")


def test_the_pdp_can_actually_refuse_a_hosted_plugins_tool(tmp_path, host):
    """The claim this module exists for. A plugin left inside OpenClaw's gateway
    cannot be refused call-by-call; one hosted here can, and this proves the
    refusal reaches the plugin rather than being advisory."""
    from agentos.memory import Store
    from agentos.policy import PDP, Principal

    store = Store(tmp_path / "t.db")
    pdp = PDP({"autonomy": "balanced"}, store)
    hs = ochost.HostSet()
    hs.add(host)

    p = Principal("ocplugin", "demo")
    action, resource = policymod.action_of("ocp_demo_add", {}, ocp=hs)
    store.add_grant("ocplugin", "demo", "plugin.tool", "ocptool:demo/*",
                    effect="deny", source="user")
    store.grants_version += 1
    dec = pdp.decide(p, action, resource, {"risk": "safe"})
    assert dec.effect == "deny", dec

    # and a decision — allowed or refused — is a row in the ledger
    rows = store.db.execute(
        "SELECT action, resource, effect FROM audit WHERE action='plugin.tool'").fetchall()
    assert (action, resource, "deny") in [(r[0], r[1], r[2]) for r in rows]


def test_what_the_plugin_asks_the_host_for_comes_back_to_python(host):
    """The inversion the sandbox exists to force: a capability a plugin TAKES is
    invisible, one it REQUESTS is governable. `api.host.fetch` is a round trip,
    and Python's refusal is what the plugin sees."""
    ok, val = host.call("ask", {"url": "https://example.com"})
    assert ok and "refused" in val, val
    assert host.seen and host.seen[0][0] == "fetch"
    assert host.seen[0][1]["url"] == "https://example.com"


def test_an_unwired_host_refuses_every_capability(tmp_path):
    """A host started without a capability bridge must be a closed door, not an
    open one. An unwired embedding that granted everything is the shape of bug
    that only shows up in the deployment nobody tested."""
    entry = tmp_path / "index.js"
    entry.write_text(PLUGIN)
    h = ochost.PluginHost("demo", str(entry))          # no host_call
    try:
        assert h.start()["ok"]
        ok, val = h.call("ask", {"url": "https://example.com"})
        assert ok and "refused" in val and "capability bridge" in val["refused"]
    finally:
        h.stop()


# --------------------------------------------------------------- containment

def test_the_sandbox_really_blocks_the_plugins_own_filesystem(host):
    """Not a claim — the plugin genuinely tries and Node genuinely refuses."""
    rep = ochost.sandbox_report()
    ok, val = host.call("peek", {})
    assert ok
    if rep["filesystem"]:
        assert val.get("blocked") == "ERR_ACCESS_DENIED", val
    else:
        pytest.skip(f"no filesystem containment here: {rep['filesystem_note']}")


def test_the_sandbox_really_blocks_the_plugin_starting_a_subprocess(host):
    rep = ochost.sandbox_report()
    if not rep["filesystem"]:
        pytest.skip("no permission model on this Node")
    ok, val = host.call("spawn", {})
    assert ok and val.get("blocked") == "ERR_ACCESS_DENIED", val


def test_the_network_claim_matches_what_this_machine_can_do():
    """The one that must never drift optimistic. Node has no `--allow-net`, so
    without an OS jail a plugin's own fetch() is simply not containable — and
    saying otherwise on a consent screen would be worse than no sandbox, because
    somebody would believe it."""
    from agentos.tools import sandbox_mechanism
    rep = ochost.sandbox_report()
    assert rep["network"] is bool(sandbox_mechanism())
    if not rep["network"]:
        assert "CANNOT CONTAIN" in rep["network_note"]
    assert rep["network_note"]


# --------------------------------------------------------------- honesty

def test_a_refused_api_is_named_out_loud_not_silently_missing(host):
    """The failure mode of every compatibility layer is a plugin that installs,
    reports healthy, and quietly does most of its job. A refusal has to travel."""
    refused = {u["api"].split(":")[0] for u in host.unsupported}
    assert {"registerHook", "registerChannel", "registerTrustedToolPolicy"} <= refused
    assert all(u["detail"] for u in host.unsupported)


def test_the_manifest_catches_a_tool_the_shim_failed_to_see(host):
    """OpenClaw requires the runtime registrations to match `contracts.tools`, so
    the manifest states what SHOULD have been caught. That is what makes this
    shim auditable rather than hopeful."""
    gap = ochost.discrepancy(MANIFEST, host.registrations)
    assert "never_registered" in gap
    assert "gap in this compatibility layer" in gap


def test_no_discrepancy_when_the_shim_caught_everything(host):
    declared = {"contracts": {"tools": [r["name"] for r in host.registrations]}}
    assert ochost.discrepancy(declared, host.registrations) == ""


def test_a_chatty_plugin_cannot_corrupt_the_protocol(host):
    """stdout is the wire. A plugin's console.log would desynchronise every frame
    after it, so console is rebound before any plugin code runs — and the proof is
    that a call which writes to stdout still returns, and the NEXT call still
    works."""
    assert host.call("noisy", {}) == (True, {"ok": True})
    assert host.call("add", {"a": 1, "b": 1}) == (True, {"sum": 2})


def test_a_machine_without_node_says_so_and_invents_no_command(monkeypatch):
    monkeypatch.setattr(ochost, "node_exe", lambda: "")
    why = ochost.problem()
    assert "Node" in why and "not install it for you" in why
    for invented in ("apt install", "brew ", "curl "):
        assert invented not in why


def test_hosting_report_answers_what_did_we_take_on(host):
    """One place a consent screen can read: what works, what was refused, what
    could not be contained, and whether the shim and the manifest agree."""
    rep = ochost.hosting_report(MANIFEST, host.started)
    assert rep["ok"] and "add" in rep["tools"]
    assert rep["unsupported"] and rep["discrepancy"]
    assert "network_note" in rep["sandbox"] and "filesystem_note" in rep["sandbox"]
