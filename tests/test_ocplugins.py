"""OpenClaw plugins: what the review must keep saying, and what it must never claim.

Most of this file is about honesty rather than plumbing, for the same reason
`test_appregistry.py` is mostly attacks: the plumbing is a subprocess call and it
either works or it visibly does not, while the claims — "this is what enabling
grants you", "this is held" — are the part that can silently become wrong.

A fake `openclaw` on PATH stands in for the real CLI. It is not a mock of
`ocplugins`: the module really does spawn it, really parses its `--json`, and
really writes to a real store. That is the point — a test that patched
`ocplugins.installed` would pass forever while the argv it builds drifted.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import ocplugins as ocp                       # noqa: E402
from agentos import policy as policymod                    # noqa: E402
from agentos.memory import Store                           # noqa: E402


# --------------------------------------------------------------------------- fake CLI

#: A plugin that asks for a lot, so the scan has something to find.
LOUD = {
    "id": "loud",
    "configSchema": {"type": "object"},
    "kind": "memory",
    "mcpServers": {"twilio": {"command": "node"}},
    "cliCommands": [{"name": "loud", "description": "x"}],
    "contracts": {"tools": ["place_call"], "trustedToolPolicies": ["budget"],
                  "agentToolResultMiddleware": ["codex"]},
    "activation": {"onHooks": ["llm_output"]},
    "openclaw": {"install": {"minHostVersion": ">=2026.3.22"}},
}

#: A plugin that asks for almost nothing.
QUIET = {"id": "quiet", "configSchema": {"type": "object"},
         "contracts": {"tools": ["today"]},
         "openclaw": {"compat": {"pluginApi": ">=2026.5.27"}}}


def _fake_openclaw(tmp_path: Path, plugins: dict, state: Path) -> Path:
    """A stand-in `openclaw` that answers the verbs ocplugins actually calls.

    `plugins` maps id -> {"manifest":…, "enabled":…, "source":…}. The script edits
    that JSON on disk for enable/disable, so a test can assert that the module
    drove the CLI rather than only that it returned something.
    """
    db = tmp_path / "fake-openclaw.json"
    db.write_text(json.dumps(plugins))
    for pid, p in plugins.items():
        d = state / "extensions" / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / ocp.MANIFEST_NAME).write_text(json.dumps(p["manifest"]))
        if p.get("package"):
            (d / "package.json").write_text(json.dumps(p["package"]))

    script = tmp_path / "openclaw"
    script.write_text(f'''#!{sys.executable}
import json, sys
DB = {str(db)!r}
ROOT = {str(state / "extensions")!r}
a = sys.argv[1:]
d = json.load(open(DB))
def save(): json.dump(d, open(DB, "w"))
def row(pid):
    p = d[pid]
    return {{"id": pid, "version": p.get("version", "1.0.0"),
             "enabled": p.get("enabled", False), "format": "openclaw",
             "bundled": p.get("bundled", False), "source": p.get("source", ""),
             "path": ROOT + "/" + pid}}
if a[:2] == ["plugins", "list"]:
    print("some warning line nobody parses")     # the trace/warning noise is real
    print(json.dumps({{"plugins": [row(p) for p in d]}}))
elif a[:2] == ["plugins", "inspect"]:
    pid = a[2]
    if pid not in d: sys.exit(3)
    print(json.dumps(row(pid)))
elif a[:2] == ["plugins", "search"]:
    print(json.dumps({{"results": [{{"name": "clock", "version": "2.0.0",
                                     "summary": "a clock"}}]}}))
elif a[:2] == ["plugins", "enable"]:
    d[a[2]]["enabled"] = True; save(); print("enabled")
elif a[:2] == ["plugins", "disable"]:
    d[a[2]]["enabled"] = False; save(); print("disabled")
elif a[:2] == ["plugins", "install"]:
    if "--force" not in a and "clawhub:" not in a[2] and not a[2].startswith("@openclaw/"):
        print("refusing an unreviewed source without --force", file=sys.stderr); sys.exit(1)
    print("installed plugin 'quiet'")
elif a[:2] == ["plugins", "update"]:
    if a[2] not in d: sys.exit(3)
    print("updated " + a[2])
elif a[:2] == ["plugins", "uninstall"]:
    d.pop(a[2], None); save(); print("uninstalled")
elif a[:2] == ["plugins", "doctor"]:
    print(json.dumps({{"ok": True}}))
else:
    sys.exit(9)
''')
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture
def oc(tmp_path, monkeypatch):
    """A machine with OpenClaw, two plugins, and a store to write decisions into."""
    state = tmp_path / "openclaw-state"
    plugins = {
        "loud": {"manifest": LOUD, "enabled": False, "source": "git:github.com/acme/loud",
                 "package": {"scripts": {"postinstall": "node evil.js"}}},
        "quiet": {"manifest": QUIET, "enabled": False, "source": "clawhub:quiet"},
    }
    script = _fake_openclaw(tmp_path, plugins, state)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state))
    # `cli()` prefers executors._find_bin, which walks its own extended path —
    # point the module at the fake directly so the fixture cannot be defeated by
    # whatever the developer happens to have installed.
    monkeypatch.setattr(ocp, "cli", lambda: str(script))
    store = Store(tmp_path / "t.db")
    return {"store": store, "cfg": {}, "state": state, "db": tmp_path / "fake-openclaw.json"}


# --------------------------------------------------------------------------- honesty

def test_a_machine_without_openclaw_says_why_and_offers_no_command(monkeypatch):
    """The dead-control rule. AgentOS does not ship an OpenClaw installer, so the
    refusal must not end in a command somebody invented — see executors.py, which
    leaves `install_cmd` off OpenClaw for exactly this reason."""
    monkeypatch.setattr(ocp, "cli", lambda: "")
    why = ocp.problem()
    assert why and "not installed" in why
    assert "install" in why.lower()
    for invented in ("npm i", "npm install", "curl", "brew ", "pip install"):
        assert invented not in why, f"problem() offers a command we made up: {why}"
    rows, err = ocp.installed()
    assert rows == [] and err == why


def test_the_scan_names_the_tiers_that_bypass_a_check():
    """The three high findings are the ones whose whole point is to sit in front
    of something. If a rename upstream makes these stop matching, the consent
    screen goes quiet about the loudest things a plugin can ask for."""
    sec = ocp.scan(LOUD, {"scripts": {"postinstall": "x"}},
                   ocp.parse_spec("git:github.com/acme/loud"))
    rules = {f["rule"] for f in sec["findings"]}
    assert {"trusted-tool-policies", "tool-result-middleware", "slot-memory",
            "conversation-hooks"} <= rules
    assert sec["verdict"] == "caution"
    assert {f["severity"] for f in sec["findings"]} >= {"high", "medium"}


def test_a_quiet_plugin_is_not_alarmed_about():
    """A scan that says 'caution' about everything is a scan nobody reads."""
    sec = ocp.scan(QUIET)
    assert sec["verdict"] == "pass", [f["note"] for f in sec["findings"]]
    assert all(f["severity"] == "info" for f in sec["findings"])


def test_an_untrusted_source_is_a_finding_and_a_sentence():
    """OpenClaw's own trust judgement, mirrored rather than re-invented: ClawHub
    and the official catalogue are trusted; npm, git, a path and a marketplace
    are the person vouching."""
    assert ocp.parse_spec("clawhub:x")["trusted"]
    assert ocp.parse_spec("@openclaw/discord")["trusted"]
    for spec in ("npm:left-pad", "git:github.com/a/b", "./here", "thing@market"):
        info = ocp.parse_spec(spec)
        assert not info["trusted"], spec
        assert "vouching" in ocp.source_sentence(info)
        assert "untrusted-source" in {f["rule"] for f in ocp.static_scan(QUIET, None, info)}


def test_capabilities_and_grants_come_from_one_manifest():
    """The jobs.py rule: the sentence somebody agreed to and the permission they
    got are one computation. Every tool named in the sentence has a row."""
    caps = " ".join(ocp.capabilities("loud", LOUD))
    grants = ocp.declared_grants("loud", LOUD)
    assert "place_call" in caps
    assert {"tool.use", "mcp.use", "plugin.run"} <= {g["action"] for g in grants}
    assert "tool:place_call" in {g["resource"] for g in grants}
    assert "mcp:twilio" in {g["resource"] for g in grants}
    assert all(g["principal_kind"] == ocp.PRINCIPAL_KIND for g in grants)


def test_a_plugin_that_declares_nothing_says_so_rather_than_looking_clean():
    caps = ocp.capabilities("mystery", {"id": "mystery", "configSchema": {}})
    assert any("declare nothing" in c for c in caps), caps


# --------------------------------------------------------------------------- lifecycle

def test_install_lands_disabled_and_holds_nothing(oc):
    """The load-bearing decision: bytes land first, disabled, and the scan reads
    the real manifest. Enabling is the act of granting — the same rule flows run
    on, and a drafted thing must not have granted itself anything meanwhile."""
    ok, _ = ocp.install("clawhub:quiet")
    assert ok
    rows, err = ocp.installed()
    assert not err
    assert all(not r["enabled"] for r in rows)
    assert ocp.declared_grants("quiet", QUIET)          # it WOULD grant something
    assert not ocp.consented(oc["store"], "quiet")      # and has not been given it


def test_one_answer_to_which_id_an_install_produced(oc):
    """A plugin id is not its package name, and three surfaces each guessing
    differently is how two of them review the wrong plugin. `installed_id` asks
    the registry, and says nothing rather than guessing when it cannot tell."""
    ok, out = ocp.install("clawhub:quiet")
    assert ok
    assert ocp.installed_id("clawhub:quiet", out) == "quiet"
    # the package name is not the id, and there is no near match to fall back on
    assert ocp.installed_id("clawhub:@scope/nothing-like-it", "") == ""


def test_an_untrusted_source_is_refused_without_the_user_vouching(oc):
    """`--force` answers OpenClaw's own provenance question, so it may only ever
    be passed on from a person. Defaulting it would silently answer for them."""
    ok, out = ocp.install("git:github.com/acme/loud", force=False)
    assert not ok and "unreviewed source" in out
    assert ocp.install("git:github.com/acme/loud", force=True)[0]


def test_enabling_writes_the_grants_and_disabling_takes_them_back(oc):
    res = ocp.enable_plugin(oc["store"], oc["cfg"], "loud")
    assert res["ok"] and res["grants"]["added"] >= 3
    assert ocp.consented(oc["store"], "loud")
    assert json.loads(oc["db"].read_text())["loud"]["enabled"] is True
    assert res["restart_note"]                          # it is not live until a restart

    off = ocp.disable_plugin(oc["store"], "loud")
    assert off["ok"] and off["revoked"] >= 3
    assert not ocp.consented(oc["store"], "loud")
    assert json.loads(oc["db"].read_text())["loud"]["enabled"] is False


def test_enabling_records_the_pin_under_the_personal_registry_key(oc):
    """Whom I trust is personal — it belongs under the existing `registry`
    USER_KEY, not a new machine-wide one. A key outside USER_KEYS silently never
    saves for anybody but the machine."""
    from agentos import users as usersmod
    ocp.enable_plugin(oc["store"], oc["cfg"], "quiet")
    assert oc["cfg"]["registry"]["openclaw"]["quiet"]["source"] == "clawhub:quiet"
    assert "registry" in usersmod.USER_KEYS


def test_reconcile_turns_a_revoked_grant_back_into_a_real_disable(oc):
    """This is what makes the grant row load-bearing rather than a note. A plugin
    runs inside OpenClaw; the ONLY thing this OS can enforce afterwards is
    enablement, so revoking consent has to reach the CLI."""
    ocp.enable_plugin(oc["store"], oc["cfg"], "loud")
    assert json.loads(oc["db"].read_text())["loud"]["enabled"] is True

    ocp.revoke_grants(oc["store"], "loud")              # e.g. the Permissions app
    res = ocp.reconcile(oc["store"], oc["cfg"])
    assert [d["id"] for d in res["disabled"]] == ["loud"]
    assert json.loads(oc["db"].read_text())["loud"]["enabled"] is False


def test_reconcile_never_enables_anything(oc):
    """The same asymmetry flows have: turning something ON is a person's act, and
    a reconciler that could do it would be a way to grant without being asked."""
    res = ocp.reconcile(oc["store"], oc["cfg"])
    assert res["disabled"] == []
    assert all(p["enabled"] is False for p in json.loads(oc["db"].read_text()).values())


def test_reconcile_leaves_bundled_plugins_alone(oc, tmp_path, monkeypatch):
    """Bundled plugins ship with OpenClaw and are not an install this OS reviewed.
    Disabling one for want of a grant it was never given would break OpenClaw's
    own defaults on a machine that did nothing wrong."""
    db = json.loads(oc["db"].read_text())
    db["quiet"].update(bundled=True, enabled=True)
    oc["db"].write_text(json.dumps(db))
    assert ocp.reconcile(oc["store"], oc["cfg"])["disabled"] == []


def test_a_held_plugin_is_disabled_and_refuses_to_be_enabled(oc):
    """Quarantine is the existing table with principal_kind='ocplugin', so a held
    plugin lands in the same list, with the same release modes, as a runaway app."""
    ocp.enable_plugin(oc["store"], oc["cfg"], "loud")
    qid = ocp.hold(oc["store"], "loud", "it started calling home")
    assert qid
    assert json.loads(oc["db"].read_text())["loud"]["enabled"] is False
    assert oc["store"].quarantined("ocplugin", "loud")
    # a hold that left the grants standing would be undone by the next reconcile,
    # which reads exactly those rows to decide the plugin is still allowed
    assert not ocp.consented(oc["store"], "loud")

    again = ocp.enable_plugin(oc["store"], oc["cfg"], "loud")
    assert not again["ok"] and "held" in again["error"]

    # one incident is one row, however many times it trips
    assert ocp.hold(oc["store"], "loud", "again") == ""
    assert len([q for q in oc["store"].quarantine_list() if q["principal_id"] == "loud"]) == 1


def test_release_forever_is_an_exemption_the_next_hold_respects(oc):
    q = oc["store"].quarantine_add("ocplugin", "loud", "noisy")
    oc["store"].quarantine_release(q, "forever")
    assert ocp.exempt(oc["store"], "loud")
    assert ocp.enable_plugin(oc["store"], oc["cfg"], "loud")["ok"]


def test_an_update_that_asks_for_more_is_held_not_upgraded(oc):
    """The supply-chain case this whole surface exists for. A plugin the user
    approved as harmless coming back wanting the conversation is not an upgrade."""
    ocp.enable_plugin(oc["store"], oc["cfg"], "quiet")
    # the update: same id, a manifest that now reaches the conversation
    grown = dict(QUIET, contracts={"tools": ["today"], "trustedToolPolicies": ["gate"]})
    (oc["state"] / "extensions" / "quiet" / ocp.MANIFEST_NAME).write_text(json.dumps(grown))
    res = ocp.update_plugin(oc["store"], oc["cfg"], "quiet")
    assert res["ok"] and res["held"], res
    assert oc["store"].quarantined("ocplugin", "quiet")
    assert not ocp.consented(oc["store"], "quiet")
    assert json.loads(oc["db"].read_text())["quiet"]["enabled"] is False


def test_an_update_that_moves_house_is_held_too(oc):
    """TOFU, the SSH model: same name, different origin, is either the author
    moving or somebody else taking the name — and the person decides."""
    ocp.enable_plugin(oc["store"], oc["cfg"], "quiet")
    db = json.loads(oc["db"].read_text())
    db["quiet"]["source"] = "git:github.com/somebody-else/quiet"
    oc["db"].write_text(json.dumps(db))
    assert ocp.pin_check(oc["cfg"], "quiet", db["quiet"]["source"])[0] == "changed-source"
    res = ocp.update_plugin(oc["store"], oc["cfg"], "quiet")
    assert res["held"] and "comes from" in res["reason"]


def test_an_ordinary_update_is_not_held(oc):
    """A hold that fires on every update is a hold people learn to click through."""
    ocp.enable_plugin(oc["store"], oc["cfg"], "quiet")
    res = ocp.update_plugin(oc["store"], oc["cfg"], "quiet")
    assert res["ok"] and not res["held"]
    assert ocp.consented(oc["store"], "quiet")


def test_a_plugin_that_grew_outside_this_os_is_caught_by_reconcile(oc):
    """The case only re-reading the bytes can see. AgentOS does not own the
    `openclaw` CLI: somebody can update a plugin in a terminal, or edit a linked
    plugin's own source, and nothing about that passes the consent screen. So the
    baseline is the verdict PINNED at enable, not a reading taken just before an
    update this OS happened to run."""
    ocp.enable_plugin(oc["store"], oc["cfg"], "quiet")
    assert oc["cfg"]["registry"]["openclaw"]["quiet"]["verdict"] == "pass"

    grown = dict(QUIET, contracts={"tools": ["today"], "trustedToolPolicies": ["gate"]})
    (oc["state"] / "extensions" / "quiet" / ocp.MANIFEST_NAME).write_text(json.dumps(grown))

    res = ocp.reconcile(oc["store"], oc["cfg"])
    assert [d["id"] for d in res["disabled"]] == ["quiet"]
    assert res["disabled"][0]["held"]
    assert oc["store"].quarantined("ocplugin", "quiet")
    assert json.loads(oc["db"].read_text())["quiet"]["enabled"] is False


def test_a_plugin_that_got_quieter_is_left_alone(oc):
    """Only an escalation is drift. Holding something for asking for LESS teaches
    people the hold means nothing, which is how a real one gets clicked through."""
    ocp.enable_plugin(oc["store"], oc["cfg"], "loud")
    assert oc["cfg"]["registry"]["openclaw"]["loud"]["verdict"] == "caution"
    (oc["state"] / "extensions" / "loud" / ocp.MANIFEST_NAME).write_text(
        json.dumps(dict(QUIET, id="loud")))
    assert ocp.reconcile(oc["store"], oc["cfg"])["disabled"] == []


def test_preview_is_what_enable_acts_on(oc):
    """One computation, so the screen and the save cannot drift. Everything the
    preview promised as a grant is a row that actually gets written."""
    pv = ocp.preview("loud", oc["cfg"], oc["store"])
    promised = {(g["action"], g["resource"]) for g in pv["grants"]}
    ocp.enable_plugin(oc["store"], oc["cfg"], "loud")
    written = {(g["action"], g["resource"]) for g in oc["store"].list_grants()
               if g.get("source") == ocp.GRANT_SOURCE}
    assert promised == written


def test_a_noisy_cli_does_not_break_the_reader(oc):
    """`plugins list` prints a warning line before its JSON, and OpenClaw
    documents a lifecycle trace on stderr. A surface that crashed on that would
    be a surface that vanishes exactly when something is wrong."""
    rows, err = ocp.installed()
    assert not err and {r["id"] for r in rows} == {"loud", "quiet"}


def test_inspect_never_loads_the_plugins_code(oc, monkeypatch):
    """`--runtime` imports the module. Running the code to decide whether to run
    the code answers the question by doing the thing."""
    seen = []
    real = ocp._run
    monkeypatch.setattr(ocp, "_run", lambda a, t, env=None: (seen.append(a), real(a, t, env))[1])
    ocp.preview("loud", oc["cfg"], oc["store"])
    assert seen and all("--runtime" not in a for a in seen), seen


# --------------------------------------------------------------------------- policy

def test_the_lifecycle_has_its_own_actions_not_another_tool_use_string():
    """'May install a plugin' and 'may read a file' are not the same question, so
    a grant written for one must not silently carry the other."""
    assert policymod.action_of("install_openclaw_plugin", {"spec": "clawhub:x"}) == \
        ("plugin.install", "ocplugin:clawhub:x")
    assert policymod.action_of("enable_openclaw_plugin", {"id": "x"})[0] == "plugin.enable"
    assert policymod.action_of("list_openclaw_plugins", {})[0] == "plugin.read"


def test_nothing_but_the_users_own_agent_may_reach_the_lifecycle():
    """An app or a subagent that could enable a plugin could hand itself tools by
    installing one that provides them — the same escalation _NO_FLOW_WRITE and
    _NO_AGENT_WRITE exist to close, and here there is no second chance to refuse:
    the plugin runs inside OpenClaw, not behind this gate."""
    for kind in ("app", "subagent", "workflow", "flow"):
        denied = set(policymod.BUILTIN_DENY[kind])
        assert ("plugin.install", "*") in denied, kind
        assert ("plugin.enable", "*") in denied, kind


def test_enabling_always_asks_even_at_full_autonomy():
    from agentos.tools import ALWAYS_ASK
    assert "enable_openclaw_plugin" in ALWAYS_ASK


def test_the_agent_is_told_it_cannot_enable_what_it_installs():
    """The tool description is the model's whole understanding of the rule; if it
    stops saying so, the model starts promising the user something it cannot do."""
    from agentos.tools import TOOL_SCHEMAS
    by = {t["name"]: t for t in TOOL_SCHEMAS}
    assert {"list_openclaw_plugins", "install_openclaw_plugin",
            "enable_openclaw_plugin"} <= set(by)
    d = by["install_openclaw_plugin"]["description"]
    assert "DISABLED" in d and "cannot enable" in d


def test_installing_and_enabling_are_never_silent():
    """Both are `risky`, so they surface for approval rather than running under
    the default autonomy — and the reason says which of the two it is."""
    from agentos.config import load_config
    from agentos.tools import Toolbox
    tb = Toolbox.__new__(Toolbox)
    tb.cfg = load_config()
    assert tb.risk_of("install_openclaw_plugin", {"spec": "clawhub:x"})[0] == "risky"
    lvl, why = tb.risk_of("enable_openclaw_plugin", {"id": "x"})
    assert lvl == "risky" and "no longer gate" in why
    assert tb.risk_of("list_openclaw_plugins", {})[0] == "safe"


def test_one_definition_of_how_bad_a_finding_is():
    """The verdict function is imported from appregistry, not copied. Two copies
    drift, and the half that drifts is whichever one nobody demoed."""
    from agentos import appregistry
    assert ocp.verdict_of is appregistry.verdict_of
