"""The lead hands work to the team, whatever its brain.

Reported with two screenshots: a toolsmith built for exactly this, and "build me a
tool" answered by Claude Code doing it itself (Bash, Write, build.py) while the
toolsmith sat idle. Three causes, each pinned here:

- a chat turn forwarded to an executor knew nothing of the team — its context even
  said it could not use this OS's tools — and had no way to hand over. It now gets a
  TEAM DOOR: one MCP server (the run bridge, bound to the turn) offering exactly
  `delegate` and `huddle`, each call through `Agent.call_tool` — this OS's gate and
  ledger — and a note naming who does what;
- the executor branch was checked BEFORE `@mention`, huddles and message triggers, so
  even `@toolsmith build …` went to Claude Code;
- the built-in lead knew `delegate` existed but not whom it could delegate to.

And the other half of the report: an agent's look can be changed from its own card.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors, fabric, mcpbridge                    # noqa: E402
from agentos.agent import Agent                                    # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP                                     # noqa: E402
from agentos.tools import Toolbox                                  # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
TOOLSMITH = ("You are the toolsmith: you build new tools for this machine. Given a need, "
             "you pick the lightest form that solves it.")


def _world(tmp_path):
    c = {"agent_name": "Arie", "autonomy": "balanced", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321,
         "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "toolsmith", "soul": TOOLSMITH})
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)

    async def broadcast(ev):
        pass
    tb.fabric = fabric.ControlPlane(c, store, tb, broadcast)
    return c, store, tb


def test_a_forwarded_turn_hands_over_through_the_gate(tmp_path, monkeypatch):
    c, store, tb = _world(tmp_path)
    handed = []

    async def fake_subagent(defn, task, conversation_id="", **k):
        handed.append((defn["name"], task, conversation_id))
        return {"status": "ok", "model": "test", "content": "made tools/vcp.py", "fault": "", "steps": []}
    monkeypatch.setattr(tb.fabric, "run_subagent", fake_subagent)
    seen = {}

    async def fake_cli(text, env, sink, run):
        # what the executor was told and given
        seen["context"], seen["argv"] = env.context, executors.build_command(text, env)
        token = env.team_mcp[1]
        _, listed = await mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        seen["tools"] = sorted(t["name"] for t in listed["result"]["tools"])
        _, out = await mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "delegate", "arguments": {"subagent": "toolsmith", "task": "build a VCP scanner"}}})
        seen["out"] = out["result"]["content"][0]["text"]
        _, bad = await mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "run_command", "arguments": {"command": "id"}}})
        seen["bad"] = bad["result"]["content"][0]["text"]
        seen["token"] = token
        await sink({"type": "text_delta", "text": "The toolsmith built it."})
        return run
    monkeypatch.setattr(executors, "run_task", fake_cli)

    async def approver(*a, **k):
        return True
    said, _ = asyncio.run(executors.forward("claude-code", "build me a tool for VCP", c, str(tmp_path),
                                            team={"toolbox": tb, "store": store, "approver": approver,
                                                  "conversation_id": "c1", "surface": "telegram"}))
    assert said == "The toolsmith built it."
    assert "YOUR TEAM" in seen["context"] and "toolsmith: You are the toolsmith" in seen["context"]
    assert "HAND IT OVER" in seen["context"]
    assert seen["tools"] == ["delegate", "huddle"], "the door offers the team and nothing else"
    assert handed == [("toolsmith", "build a VCP scanner", "c1")] and "made tools/vcp.py" in seen["out"]
    assert "[denied] no tool called 'run_command'" in seen["bad"]
    argv = seen["argv"]
    assert "--allowedTools" in argv and "mcp__bento" in argv and "--mcp-config" in argv
    assert "--strict-mcp-config" not in argv, "the person's own chat keeps its MCP config"
    assert mcpbridge.get(seen["token"]) is None, "closed when the turn ends"
    # the hand-over is in the ledger, as any built-in delegate would be
    rows = store.db.execute("SELECT action, resource FROM audit ORDER BY id DESC LIMIT 20").fetchall()
    assert any("toolsmith" in str(r[1]) for r in rows), rows


def test_no_team_no_door(tmp_path):
    c, store, tb = _world(tmp_path)
    store.db.execute("DELETE FROM subagents")
    store.db.commit()
    env = executors.Envelope(workspace=str(tmp_path))

    async def approver(*a, **k):
        return True
    assert executors.open_team_door(env, c, tb, store, None, approver) == ""
    assert env.team_mcp == () and "--mcp-config" not in executors.build_command("hi", env)


def test_the_built_in_lead_knows_its_team(tmp_path):
    c, store, tb = _world(tmp_path)

    async def emit(ev):
        pass

    async def approver(*a, **k):
        return True
    lead = Agent(c, tb, "ollama/x", emit, approver)
    system = asyncio.run(lead._system("build me a tool"))
    assert "toolsmith: You are the toolsmith" in system and "call delegate with" in system
    from agentos import toolscope
    assert {"delegate", "huddle"} <= toolscope.CORE, "a narrowed tool set keeps the team"


def test_an_address_wins_over_the_brain():
    src = (ROOT / "agentos/server.py").read_text()
    assert 'if model == "claude-code" and not (mention or huddle_hit or flow_hit):' in src
    assert "execmod.open_team_door(" in src
    assert 'startswith(f"mcp__{execmod.BRIDGE_SERVER}__")' in src, "one card per hand-over"
    for f in ("telegram.py", "whatsapp.py"):
        assert '"toolbox": self.toolbox' in (ROOT / "agentos" / f).read_text(), f"{f} opens the door too"
    assert "fabricmod.parse_mention(self.store, text)" in (ROOT / "agentos/whatsapp.py").read_text()


def test_an_agents_look_is_changed_from_its_card():
    hands = (JS / "11e-hands.js").read_text()
    assert "class=\"ag-face\" onclick=\"avatarEdit(" in hands and "avatarDesignAsk(" in hands
    assert "avatarEdit('@agent')" in (JS / "11-settings.js").read_text(), "the lead too"
    assert "function avatarDesignAsk(" in (JS / "00e-avatars.js").read_text()
