"""Brains, hands and agents: an executor profile is a CEILING the gate checks first.

What these defend:

- the default profile changes nothing (every tool, anywhere the machine allows);
- a profile refuses a tool it does not hold, a folder outside it, a write to a
  read-only folder, a `..` or symlink that leaves it, a web address it does not
  list and an MCP server it does not reach — each as an audited `reach` decision;
- no grant reaches past it: an agent granted fs.write everywhere still cannot write
  where its hands do not reach;
- a tool the hands cannot pick up is not even offered to the model;
- assigning and deleting are audited, and a deleted profile's agents fall back to
  default rather than keeping a stale name;
- the agents map (overview → graph) is ONE computation: brain, hands, talk, missions;
- the terminal and the routes read and write the same rows.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import agentmap, fabric, hands                          # noqa: E402
from agentos.memory import Store                                      # noqa: E402
from agentos.policy import MAIN, PDP, Principal                       # noqa: E402

ROOT = Path(__file__).parent.parent
AN = Principal("subagent", "analyst")


def _world(tmp_path, **cfg):
    c = {"agent_name": "Aria", "autonomy": "full", "workspace": str(tmp_path / "ws"),
         "default_model": "openai/gpt-4o", "providers": {"openai": {"enabled": True, "api_key": "k"}}}
    c.update(cfg)
    (tmp_path / "ws").mkdir(exist_ok=True)
    store = Store(tmp_path / "a.db")
    store.save_subagent({"name": "analyst", "soul": "numbers", "tools": ["read_file", "write_file"]})
    return c, store, PDP(c, store)


def _tool(pdp, who, name, args, risk="risky"):
    return pdp.decide_tool(who, name, args, risk, reason="test", autonomy="full")


def test_the_default_profile_changes_nothing(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    for name, args in [("write_file", {"path": "/srv/x.md"}), ("run_command", {"command": "ls"}),
                       ("fetch_url", {"url": "https://example.com"})]:
        assert _tool(pdp, MAIN, name, args).rule != "reach"
    assert [p["name"] for p in hands.list_profiles(store)][:2] == ["default", "read-only"]


def test_a_profile_is_a_ceiling_on_tools_folders_web_and_mcp(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "out").symlink_to(tmp_path)
    hands.save(store, "reports", {"tools": ["read_file", "write_file", "fetch_url"],
                                  "folders": [{"path": str(tmp_path / "reports"), "mode": "rw"},
                                              {"path": "@workspace", "mode": "ro"}],
                                  "web": ["https://api.example.com/*"], "mcp": ["github"]})
    hands.assign(store, cfg, "analyst", "reports")
    ok = _tool(pdp, AN, "write_file", {"path": str(tmp_path / "reports/r.md")})
    assert ok.rule != "reach", ok.reason
    cases = {
        ("run_command", "ls"): "not one of this executor's tools",
        ("write_file", str(tmp_path / "elsewhere.md")): "outside this executor's folders",
        ("write_file", str(tmp_path / "ws/notes.md")): "read-only for this executor",
        ("write_file", str(tmp_path / "reports/../escape.md")): "outside",
        ("write_file", str(tmp_path / "reports/out/escape.md")): "outside",
        ("fetch_url", "https://evil.example.org/x"): "not one of this executor's web addresses",
    }
    for (name, arg), why in cases.items():
        key = {"run_command": "command", "fetch_url": "url"}.get(name, "path")
        d = _tool(pdp, AN, name, {key: arg})
        assert d.effect == "deny" and d.rule == "reach" and why in d.reason, (name, arg, d.reason)
    assert _tool(pdp, AN, "read_file", {"path": str(tmp_path / "ws/notes.md")}, "safe").rule != "reach"
    d = pdp.decide(AN, "mcp.use", "mcp:slack/post", {"risk": "risky", "tool": "mcp_slack_post"})
    assert d.rule == "reach" and "slack" in d.reason
    rows = store.db.execute("SELECT effect, rule FROM audit WHERE rule='reach'").fetchall()
    assert len(rows) >= 6, "every refusal by the hands is in the ledger"


def test_no_grant_reaches_past_the_hands(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    hands.assign(store, cfg, "analyst", "read-only")
    store.add_grant("subagent", "analyst", "fs.write", "fs:*", source="user")
    store.add_grant("subagent", "analyst", "tool.use", "*", source="user")
    d = _tool(pdp, AN, "write_file", {"path": str(tmp_path / "ws/x.md")})
    assert d.effect == "deny" and d.rule == "reach"


def test_the_lead_agent_has_hands_too(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    hands.assign(store, cfg, "@agent", "read-only")
    assert cfg["agent_profile"] == "read-only"
    assert _tool(pdp, MAIN, "run_command", {"command": "ls"}).rule == "reach"


def test_a_tool_the_hands_cannot_hold_is_not_offered(tmp_path):
    from agentos.agent import Agent
    from agentos.tools import Toolbox
    cfg, store, pdp = _world(tmp_path)
    tb = Toolbox(cfg, store)
    tb.pdp = pdp
    hands.assign(store, cfg, "analyst", "read-only")

    async def nop(*a, **k):
        return False
    ag = Agent(cfg, tb, "openai/gpt-4o", nop, nop, principal=AN, tool_filter=["read_file", "write_file"])
    names = [t["name"] for t in ag._tools()]
    assert "read_file" in names and "write_file" not in names


def test_assigning_and_deleting_are_audited_and_never_leave_a_stale_name(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    hands.save(store, "narrow", {"tools": ["read_file"], "folders": [], "web": "none", "mcp": []})
    hands.assign(store, cfg, "analyst", "narrow")
    assert store.get_subagent("analyst")["profile"] == "narrow"
    store.save_subagent({"name": "analyst", "soul": "renamed soul"})
    assert store.get_subagent("analyst")["profile"] == "narrow", "an older save path never resets hands"
    assert hands.delete(store, "narrow") == 1
    assert store.get_subagent("analyst")["profile"] == ""
    with pytest.raises(ValueError):
        hands.delete(store, "default")
    with pytest.raises(ValueError):
        hands.save(store, "bad", {"folders": [{"path": "relative/dir"}]})
    acts = {r[0] for r in store.db.execute("SELECT action FROM audit").fetchall()}
    assert {"executor.write", "executor.delete", "agent.hands"} <= acts


def test_the_map_is_one_computation(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    store.save_subagent({"name": "writer", "soul": "words", "skills": ["style-guide"]})
    hands.assign(store, cfg, "analyst", "read-only")
    fabric.set_cell(store, "writer", "analyst", "allow")
    fabric.set_cell(store, "analyst", "writer", "deny")
    ov = agentmap.overview(store, cfg)
    by = {a["key"]: a for a in ov["agents"]}
    assert by["@agent"]["master"] and by["@agent"]["delegates_to"] == ["analyst", "writer"]
    assert by["analyst"]["hands"]["name"] == "read-only" and by["writer"]["asks"] == ["analyst"]
    g = agentmap.graph(ov)
    edges = {(e["from"], e["to"], e["kind"]) for e in g["edges"]}
    assert ("agent:analyst", "hands:read-only", "hands") in edges
    assert ("agent:writer", "agent:analyst", "talk") in edges
    assert ("agent:analyst", "agent:writer", "blocked") in edges
    assert ("agent:writer", "skill:style-guide", "skill") in edges
    assert any(k == "brain" for _, _, k in edges)
    assert "read-only" in agentmap.text(ov)


def test_the_terminal_and_the_routes(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", *a], cwd=ROOT, env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=60)
    r = run("hands", "set", "reports", "--tools", "read_file,write_file", "--folder", "~/reports:rw",
            "--web", "none")
    assert r.returncode == 0 and "2 tools" in r.stdout, r.stdout + r.stderr
    assert "no web" in run("hands", "show", "reports").stdout
    assert run("agents", "hands", "@agent", "reports").returncode == 0
    out = run("agents").stdout
    assert "executor   reports" in out     # on screen and in the terminal it is an executor
    assert run("hands", "rm", "default").returncode == 2


def test_the_routes(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        r = cl.put("/api/hands/web-only", json={"spec": {"tools": ["fetch_url"], "folders": [], "web": "any",
                                                         "mcp": []}, "description": "reads the web"})
        assert r.status_code == 200 and r.json()["profile"]["name"] == "web-only"
        h = cl.get("/api/hands").json()
        assert any(p["name"] == "web-only" for p in h["profiles"]) and "Files" in h["tools"]
        assert cl.put("/api/agents/@agent/hands", json={"profile": "nope"}).status_code == 400
        g = cl.get("/api/agents/graph").json()
        assert any(n["kind"] == "agent" and n.get("master") for n in g["nodes"])
        assert cl.delete("/api/hands/web-only").status_code == 200


def test_settings_has_three_clear_places():
    js = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "['agent','◈','Agents','agent']" in js
    assert "The brains." in js and 'id="exec-list"' in js, "installed agents are listed with the brains"
    assert 'id="hands-list"' in js and "An executor is what an agent can reach" in js
    assert 'id="agents-list"' in js and 'id="agents-graph"' in js and "Working together" in js
    ui = (ROOT / "agentos/ui/src/js/11e-hands.js").read_text()
    assert "/api/agents/graph" in ui and "/api/hands/" in ui


def test_the_immersive_look_is_the_default():
    js = (ROOT / "agentos/ui/src/js/01b-immersive.js").read_text()
    assert "immersiveStored()!=='0'" in js, "on unless this browser switched it off"


def test_no_two_files_declare_the_same_function():
    """The bundle is one script: a second top-level `function x` silently REPLACES the
    first everywhere. Found by a Settings helper named agentHands, which took over the
    copilot's "visible hands" glow of the same name without an error anywhere."""
    import collections
    import re
    seen = collections.defaultdict(list)
    for p in sorted((ROOT / "agentos/ui/src/js").glob("*.js")):
        for m in re.finditer(r"(?m)^(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\(", p.read_text()):
            seen[m.group(1)].append(p.name)
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dup, dup
