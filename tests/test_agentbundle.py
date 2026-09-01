"""Fork my agent: the properties that make sharing an agent safe enough to exist.

Most of this file is attacks, like test_appregistry.py, because the claims here
are the kind that rot silently: "nothing personal travels" is true until one
field is added to the wrong dict. The export is attacked with a machine FULL of
secrets and memories; the fork is attacked with tampered and over-claiming
bundles. If any of these ever fails, the feature must not ship that day.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import agentbundle as ab                        # noqa: E402
from agentos import flows as flowsmod                        # noqa: E402
from agentos.memory import Store                             # noqa: E402

#: A config with a credential in every slot one can live in. The export must
#: never reach for ANY of it — the whitelist argument, made executable.
POISONED_CFG = {
    "agent_name": "Invoicer",
    "providers": {"anthropic": {"api_key": "sk-ant-SECRETaaaaaaaaaaaaaaa"},
                  "openai": {"api_key": "sk-SECRETbbbbbbbbbbbbbbbbbbbb"}},
    "telegram": {"bot_token": "123456789:AAF-secretsecretsecretsecretsec"},
    "github": {"token": "ghp_SECRETcccccccccccccccccccc", "username": "me"},
    "whatsapp": {"app_secret": "wa-super-secret-value-here"},
    "mcp_servers": {"stripe": {"transport": "stdio", "command": "npx",
                               "args": "-y stripe-mcp",
                               "env": {"STRIPE_KEY": "sk-live-SECRETdddddddddddd"},
                               "headers": {"Authorization": "Bearer SECRETeeeeeeeeeeeeeeeeeeee"}}},
}

SECRET_STRINGS = ("sk-ant-SECRET", "sk-SECRETbb", "AAF-secret", "ghp_SECRET",
                  "wa-super-secret", "sk-live-SECRET", "SECRETeeee",
                  "my darkest secret", "colleague@example.com")


@pytest.fixture()
def machine():
    """A source machine with everything an agent accrues: memories, a soul's
    worth of skills, a specialist, a flow with a live webhook secret, an app."""
    store = Store(Path(tempfile.mkdtemp()) / "src.db")
    store.add_memory("my darkest secret")
    store.add_memory("email colleague@example.com about the merger")
    store.save_skill("invoice-style", "how I like invoices", "Always net-30, EUR.")
    store.save_subagent({"name": "chaser", "soul": "chase late invoices politely",
                         "tools": ["fetch_url"]})
    flowsmod.save(store, {"name": "monthly-invoices", "mission": "Send the invoices.",
                          "roster": [{"subagent": "chaser"}],
                          "permissions": {"tools": ["fetch_url"]},
                          "triggers": [{"kind": "webhook", "config": {}}]})
    store.save_app("Invoice Viewer", "x", "view invoices",
                   "<html><body>invoices</body></html>")
    return store


@pytest.fixture()
def fresh():
    return Store(Path(tempfile.mkdtemp()) / "dst.db"), {}


# ------------------------------------------------------------- the vital drop

def test_no_credential_and_no_memory_survives_export(machine):
    """The headline property. A config poisoned in every slot, a store full of
    memories — and none of it in the bytes. This is the test that, failing,
    means the feature is withdrawn, not patched around."""
    bundle, _ = ab.export(machine, POISONED_CFG, apps="all")
    blob = json.dumps(bundle)
    for s in SECRET_STRINGS:
        assert s not in blob, f"LEAKED: {s}"


def test_the_flows_webhook_secret_stays_home(machine):
    """The webhook secret is this machine's credential; the forking machine
    mints its own when (if) the flow is enabled there."""
    secret = machine.flow_triggers("monthly-invoices")[0]["secret"]
    assert secret                                     # precondition: one exists
    bundle, _ = ab.export(machine, POISONED_CFG)
    assert secret not in json.dumps(bundle)


def test_mcp_values_become_placeholders_but_the_shape_travels(machine):
    """Someone forking the agent needs to know WHICH server and WHICH variables —
    and must supply the values themselves. Shape yes, credential never."""
    bundle, _ = ab.export(machine, POISONED_CFG)
    srv = bundle["manifest"]["mcp_servers"][0]
    assert srv["command"] == "npx"
    assert srv["env_template"] == {"STRIPE_KEY": "<YOUR_STRIPE_KEY>"}
    assert srv["headers_template"] == {"Authorization": "<your value>"}
    assert "env" not in srv and "headers" not in srv


def test_the_soul_is_opt_in_and_shown_before_it_travels(machine, monkeypatch):
    """A soul is learned from its owner's life as much as written, so it is off
    by default — and when it IS shared, the report carries the full text for one
    last read. Nothing personal leaves silently."""
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "load_soul", lambda: "I am terse. My owner hates mornings.")
    b1, r1 = ab.export(machine, POISONED_CFG)
    assert b1["manifest"]["soul"] == "" and r1["traveled"]["soul"] is False
    b2, r2 = ab.export(machine, POISONED_CFG, with_soul=True)
    assert "hates mornings" in b2["manifest"]["soul"]
    assert r2["soul_text"] == b2["manifest"]["soul"]
    assert any("IS included" in w for w in r2["withheld"])


def test_a_key_smuggled_into_prose_refuses_the_whole_export(machine):
    """The whitelist cannot stop a paste: a key in a skill's text is whitelisted
    prose. The tripwire refuses the export, names what it saw and where — and
    there is deliberately no flag that ships it anyway."""
    machine.save_skill("oops", "notes", "use sk-ant-api03-PASTEDKEYPASTEDKEY for calls")
    with pytest.raises(ab.LeakRefusal) as e:
        ab.export(machine, POISONED_CFG)
    assert "Anthropic" in str(e.value)
    assert "remove it" in str(e.value)


def test_a_key_hardcoded_in_a_shipped_app_is_caught_too(machine):
    machine.save_app("Leaky", "x", "oops",
                     "<script>fetch(u,{headers:{Authorization:'Bearer ghp_REALTOKENREALTOKENRE'}})</script>")
    with pytest.raises(ab.LeakRefusal):
        ab.export(machine, POISONED_CFG, apps="all")
    # and NOT shipping the leaky app exports fine — the refusal is per-bundle,
    # not a lockout of the whole machine
    bundle, _ = ab.export(machine, POISONED_CFG, apps=["Invoice Viewer"])
    assert [a["name"] for a in bundle["manifest"]["apps"]] == ["Invoice Viewer"]


def test_the_export_is_a_whitelist_of_known_fields_only(machine):
    """No manifest key may appear that export() did not deliberately construct.
    A new top-level field is a new decision about what travels, and this test is
    where that decision is forced to be made."""
    bundle, _ = ab.export(machine, POISONED_CFG, apps="all")
    assert set(bundle["manifest"]) == {
        "name", "description", "created_at", "soul", "skills", "subagents",
        "flows", "apps", "mcp_servers", "permissions", "security"}
    assert set(bundle) == {"format", "manifest", "checksum", "signature"}


# ------------------------------------------------------------- shipping apps

def test_apps_ship_only_when_chosen(machine):
    """Shipping an app is a per-app choice, never a default: an app's HTML is
    the piece most likely to have something personal built in."""
    none, _ = ab.export(machine, POISONED_CFG)
    assert none["manifest"]["apps"] == []
    named, _ = ab.export(machine, POISONED_CFG, apps=["invoice viewer"])
    assert [a["name"] for a in named["manifest"]["apps"]] == ["Invoice Viewer"]
    everything, rep = ab.export(machine, POISONED_CFG, apps="all")
    assert len(everything["manifest"]["apps"]) == 1
    assert everything["manifest"]["security"]["apps_scanned"] == 1


# ------------------------------------------------------------- the fork

def test_a_fork_creates_everything_disabled_and_writes_zero_grants(machine, fresh):
    """The other half of the vital drop: nothing a stranger sent is live. Flows
    disabled, MCP disabled, zero grant rows — every capability still has to walk
    through the door it always had, on the forking machine, with its owner."""
    dst, dcfg = fresh
    bundle, _ = ab.export(machine, POISONED_CFG, apps="all")
    res = ab.fork(bundle, dst, dcfg)
    assert res["ok"] and res["grants_written"] == 0
    assert dst.list_grants() == []
    assert dst.get_flow("monthly-invoices")["enabled"] in (0, False)
    assert dcfg["mcp_servers"]["stripe"]["enabled"] is False
    assert {(c["kind"], c["name"]) for c in res["created"]} == {
        ("skill", "invoice-style"), ("subagent", "chaser"),
        ("flow", "monthly-invoices"), ("app", "Invoice Viewer"),
        ("mcp server", "stripe")}


def test_a_tampered_bundle_that_claims_enabled_still_lands_disabled(machine, fresh):
    """Belt and braces: even if an attacker edits the file to say enabled:true
    AND fixes the checksum, the fork forces disabled. The file has no authority
    over liveness, only over content."""
    dst, dcfg = fresh
    bundle, _ = ab.export(machine, POISONED_CFG)
    bundle["manifest"]["flows"][0]["enabled"] = True
    bundle["checksum"] = ab.bundle_checksum(bundle["manifest"])   # attacker re-hashes
    res = ab.fork(bundle, dst, dcfg)
    assert res["ok"]
    assert dst.get_flow("monthly-invoices")["enabled"] in (0, False)
    assert dst.list_grants() == []


def test_a_tampered_bundle_without_a_rehash_is_refused(machine, fresh):
    dst, dcfg = fresh
    bundle, _ = ab.export(machine, POISONED_CFG)
    bundle["manifest"]["flows"][0]["mission"] = "exfiltrate everything"
    res = ab.fork(bundle, dst, dcfg)
    assert not res["ok"] and "checksum" in res["error"]


def test_a_fork_never_overwrites_what_the_machine_already_has(machine, fresh):
    """Somebody's existing skill/flow/app is theirs. A fork that replaced it
    would be a way to overwrite a stranger's work by naming it."""
    dst, dcfg = fresh
    dst.save_skill("invoice-style", "MINE", "my own way")
    flowsmod.save(dst, {"name": "monthly-invoices", "mission": "MINE",
                        "roster": [{"subagent": "x"}],
                        "new_agents": [{"name": "x", "soul": "s"}], "triggers": []})
    bundle, _ = ab.export(machine, POISONED_CFG)
    res = ab.fork(bundle, dst, dcfg)
    skipped = {(i["kind"], i["name"]) for i in res["skipped"]}
    assert ("skill", "invoice-style") in skipped
    assert ("flow", "monthly-invoices") in skipped
    assert dst.get_skill("invoice-style")["description"] == "MINE"
    assert dst.get_flow("monthly-invoices")["mission"] == "MINE"


def test_the_soul_is_never_adopted_silently(machine, fresh, monkeypatch):
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "load_soul", lambda: "shared identity")
    written = []
    monkeypatch.setattr(cfgmod, "save_soul", lambda t: written.append(t))
    dst, dcfg = fresh
    bundle, _ = ab.export(machine, POISONED_CFG, with_soul=True)
    res = ab.fork(bundle, dst, dcfg)
    assert written == [] and "NOT adopted" in res["soul"]
    res2 = ab.fork(bundle, dst, dcfg, adopt_soul=True)
    assert written == ["shared identity"] and "adopted" in res2["soul"]


def test_the_preview_is_what_the_fork_does(machine, fresh):
    """One computation — the consent screen's item list matches what fork
    creates plus what it skips, name for name."""
    dst, dcfg = fresh
    bundle, _ = ab.export(machine, POISONED_CFG, apps="all")
    pv = ab.fork_preview(bundle, dst, dcfg)
    assert pv["grants_written_now"] == 0
    res = ab.fork(bundle, dst, dcfg)
    assert {i["name"] for i in pv["items"]} == \
        {c["name"] for c in res["created"]} | {s["name"] for s in res["skipped"]}


def test_the_permission_ceiling_is_disclosure_not_authority(machine, fresh):
    """The bundle lists what enabling every flow WOULD grant, so the person reads
    the ceiling first — and the fork still writes none of it."""
    dst, dcfg = fresh
    bundle, _ = ab.export(machine, POISONED_CFG)
    assert bundle["manifest"]["permissions"], "the ceiling must be stated"
    ab.fork(bundle, dst, dcfg)
    assert dst.list_grants() == []


# ------------------------------------------------------------- trust rails

def test_signature_and_tofu_ride_the_registry_rails(machine, fresh, tmp_path):
    """Same keygen, same trusted_keys, same tofu_check as the app registry —
    one definition of identity, one of 'is this the publisher I knew?'."""
    from agentos import appregistry as reg
    key = tmp_path / "k"
    _, key_id, pub = reg.keygen(key)
    bundle, _ = ab.export(machine, POISONED_CFG)
    signed = ab.sign_bundle(bundle, key)
    cfg = {"registry": {"keys": {key_id: pub}}}
    assert ab.verify_bundle(signed, cfg)[0] == "verified"
    assert ab.verify_bundle(signed, {})[0] == "unknown-key"
    signed["manifest"]["name"] = "Impostor"
    assert ab.verify_bundle(signed, cfg)[0] == "checksum-mismatch"

    dst, dcfg = fresh
    good, _ = ab.export(machine, POISONED_CFG)
    good = ab.sign_bundle(good, key)
    ab.fork(good, dst, dcfg, source="alice/agent")
    pv = ab.fork_preview(good, dst, dcfg, source="alice/agent")
    assert pv["tofu"]["status"] == "match"
    # the SIGNER changing under a known name is the loudest alarm
    unsigned, _ = ab.export(machine, POISONED_CFG)
    assert ab.fork_preview(unsigned, dst, dcfg,
                           source="alice/agent")["tofu"]["status"] == "changed-key"


def test_a_shared_agent_resolves_like_a_shared_app(monkeypatch):
    """owner/repo across two CDNs at the agent well-known names — the registry's
    resolver, not a copy of it."""
    urls = ab.resolve_source("alice/my-agent@abc123")
    assert any("raw.githubusercontent.com/alice/my-agent/abc123/bento.agent.json" in u
               for u in urls)
    assert any("cdn.jsdelivr.net" in u for u in urls)
    assert len({u for u in urls}) == len(urls)


# ---------------------------------------------------------------------------
# The arrival — what an import must SAY, everywhere the same
# ---------------------------------------------------------------------------

def test_fork_returns_the_arrival(machine, tmp_path):
    """After an import, every face answers the same two questions — what changed
    and what did not — plus one suggested first message to test it with. One
    computation, or the wizard, Settings and the CLI drift into three stories."""
    bundle, _ = ab.export(machine, dict(POISONED_CFG), name="Invoicer", apps="all")
    dst = Store(tmp_path / "taker.db")
    res = ab.fork(bundle, dst, {})
    arr = res["arrival"]
    kinds = {c["kind"] for c in arr["changed"]}
    assert "app" in kinds and "mcp server" in kinds
    joined = " ".join(arr["unchanged"])
    assert "memory" in joined and "API keys" in joined and "0 rows" in joined
    assert "Invoicer" in arr["try_message"]


def test_arrival_never_calls_a_failed_flow_yours(machine, tmp_path):
    """A flow that failed validation did not arrive; the arrival must say that,
    not 'your existing flow' about a thing that is not there."""
    bundle, _ = ab.export(machine, dict(POISONED_CFG), name="Invoicer")
    # break the roster so the flow cannot validate on the taker
    man = bundle["manifest"]
    man["flows"][0]["roster"] = [{"subagent": "nobody-of-that-name"}]
    man["subagents"] = []
    bundle["checksum"] = ab.bundle_checksum(man)
    res = ab.fork(bundle, Store(tmp_path / "t.db"), {})
    lines = [u for u in res["arrival"]["unchanged"] if "monthly-invoices" in u]
    assert lines and lines[0].startswith("the flow") and "did not arrive" in lines[0]


def test_onboarding_offers_the_fork_step(machine):
    """The wizard is the viral entry point: the step exists, is optional, needs
    nothing, and is ticked by the evidence a fork leaves (its pin)."""
    from agentos import onboarding as ob_mod
    step = ob_mod.BY_ID.get("fork")
    assert step and step.optional and not step.needs
    st = ob_mod.state({}, machine)
    row = next(s for s in st["steps"] if s["id"] == "fork")
    assert row["status"] == "todo"
    st = ob_mod.state({"registry": {"agents": {"invoicer": {"at": 1}}}}, machine)
    row = next(s for s in st["steps"] if s["id"] == "fork")
    assert row["status"] == "done" and "invoicer" in row["detail"]


def test_every_step_has_a_terminal_handler():
    """The three-faces rule, pinned: a step in the catalogue with nothing behind
    it in `bento setup` is a silent gap the runtime only mentions in passing."""
    from agentos import onboarding as ob_mod
    from agentos import setup_tui
    assert [s.id for s in ob_mod.STEPS if s.id not in setup_tui.HANDLERS] == []
