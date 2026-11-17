"""An installed agent can be switched off as a brain, and Settings is laid out by who decides.

Asked for as "AI providers should show the providers that are activated and settings for each;
Answering should move to Agents → Lead agent … select the agents that are to be enabled as a
whole along with Claude Code, Gemini CLI, Codex, Hermes and OpenClaw". The old
`executors.claude_code.enabled` switch was read by nothing; `executors.off` is read everywhere a
brain is chosen (executors.switched_off).
"""
from pathlib import Path

from agentos import executors, fallback, fabric

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "agentos/ui/src/js"


def _installed(monkeypatch, *ids):
    real = executors.probe
    monkeypatch.setattr(executors, "probe", lambda e: {**real(e), "installed": e in ids,
                                                         "why_not": "" if e in ids else "not installed"})


def test_an_agent_that_is_off_is_never_a_brain(monkeypatch):
    _installed(monkeypatch, "claude-code", "gemini-cli")
    cfg = {"engine": "claude-code", "executors": {}, "providers": {}}
    assert executors.resolve_engine(cfg) == "claude-code"
    # the lead's own brain can't be switched off from the list
    ok, said = executors.set_use(cfg, "claude-code", False)
    assert not ok and "Lead agent" in said
    ok, said = executors.set_use(cfg, "gemini-cli", False)
    assert ok and cfg["executors"]["off"] == ["gemini-cli"]
    # not a per-turn brain, not a backup, not a pin
    assert executors.resolve_engine(cfg, "gemini-cli") == "aria"
    assert not fallback.usable(cfg, {"executor": "gemini-cli", "model": ""})
    b = fabric.agent_brain({**cfg, "team": {"own_brains": True}}, {"model": "gemini-cli/default"})
    assert not b["own"] and "switched off" in b["note"]
    row = next(e for e in executors.brains(cfg, [])["executors"] if e["id"] == "gemini-cli")
    assert row["on"] is False and not row["available"] and "switched off" in row["reason"]
    # and back on
    assert executors.set_use(cfg, "gemini-cli", True)[0] and cfg["executors"]["off"] == []
    assert executors.resolve_engine(cfg, "gemini-cli") == "gemini-cli"
    # a lead moved off it can then switch it off, and the machine answers with the built-in loop
    cfg["engine"] = "aria"
    assert executors.set_use(cfg, "claude-code", False)[0]
    cfg["engine"] = "claude-code"           # a hand edit, or a restored backup
    assert executors.resolve_engine(cfg) == "aria"
    assert not executors.set_use(cfg, "nope", False)[0]


def test_the_route_and_the_terminal():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        r = cl.put("/api/executors/use", json={"engine": "codex", "on": False})
        assert r.status_code == 200 and "codex" in r.json()["off"]
        assert cl.put("/api/executors/use", json={"engine": "codex", "on": True}).json()["off"] == []
        assert cl.put("/api/executors/use", json={"engine": "nope", "on": False}).status_code == 400
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert "_brain_agents_cli" in cli and 'args.executor == "agents"' in cli


def test_settings_puts_the_brain_on_the_lead_and_the_switches_with_the_providers():
    js = (JS / "11-settings.js").read_text()
    ai = js[js.index("if(want('ai'))"):js.index("if(want('executors'))")]
    agent = js[js.index("if(want('agent'))"):js.index("if(want('companies'))")]
    assert "pGroup('Answering'" not in js
    assert 'id="s-active"' in ai and 'id="exec-use"' in ai and "pGroup('Voice'" in ai and 'id="v-engine-box"' in ai
    lead = agent[agent.index("pGroup('Lead agent'"):agent.index("pGroup('How it works'")]
    assert 'id="s-brain"' in lead and 'id="s-fallbacks"' in lead
    # the dead switch is gone, and the Claude Code card still saves by its folder field
    assert "s-exec-on" not in js and "getElementById('s-exec-ws')!==null" in js
    prov = (JS / "11m-providers.js").read_text()
    assert "/api/executors/use" in prov and "function paintActiveProviders" in prov
    subs = (JS / "11l-setsubs.js").read_text()
    assert "['Voice','Voice']" in subs and "['In use','In use']" in subs


def test_a_switch_draws_and_an_opened_wrapper_is_never_left_hidden():
    # .psw draws its knob on an <i>; a <span> drew nothing, so the Brief's company switches
    # and the new ones were invisible
    for f in JS.glob("*.js"):
        for line in f.read_text().splitlines():
            if 'class="psw"' in line:
                assert "<span></span></label>" not in line, f.name
    subs = (JS / "11l-setsubs.js").read_text()
    assert "if(!of.has(e))e.classList.remove('ssub-off')" in subs
    co = (JS / "11k-companies.js").read_text()
    assert 'id="co-brief-all"' in co and "coSetBriefAll" in co
