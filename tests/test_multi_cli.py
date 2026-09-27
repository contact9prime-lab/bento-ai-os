"""Claude Code, Gemini CLI and Codex on one team.

Asked for as "multiple CLIs can work together, Claude Code with Gemini with Codex, not
just one". An agent can be pinned to any of the three; it then answers on that CLI
through the run bridge, with this OS's tools and gate, whatever the machine's own
brain is. What these defend:

- each CLI is handed the bridge in ITS OWN way (Claude Code a JSON flag, Gemini CLI a
  settings file, Codex `-c` overrides), and the token never sits on a command line
  where `ps` would show it, except Claude Code's, which has no other door;
- a mission runs a specialist on its CLI only where that CLI's own tools can all be
  switched off: Codex keeps a read-only shell, so a mission runs a Codex agent on the
  machine's brain and says so;
- a CLI that never asked the bridge for its tools did nothing through this OS, and
  the run says so instead of reporting its prose as the result.

The CLIs are stand-ins that read their config the way the real ones do (checked
against Gemini CLI 0.61 and Codex 0.157) and call the real bridge.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors, fabric, flows, mcpbridge            # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP                                     # noqa: E402
from agentos.tools import Toolbox                                  # noqa: E402


def _world(tmp_path, **cfg):
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321,
         "memory": {"inject_facts": 0, "inject_user": 0}}
    c.update(cfg)
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    events = []

    async def broadcast(ev):
        events.append(ev)
    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    return c, store, tb, cp, events


@pytest.fixture()
def installed(monkeypatch):
    monkeypatch.setattr(executors, "probe", lambda eid, refresh=False: {
        "installed": True, "title": executors.EXECUTORS_BY_ID[eid]["title"], "why_not": ""})


# ------------------------------------------------------------------ one answer: agent_brain

def test_an_agent_pinned_to_a_cli_answers_there(installed):
    for pin, title, fenced in (("gemini-cli/gemini-2.5-pro", "Gemini CLI", True),
                               ("codex/gpt-5", "Codex CLI", False),
                               ("claude-code/default", "Claude Code", True)):
        b = fabric.agent_brain({}, {"name": "x", "model": pin})
        assert b["own"] and b["engine"] == pin.split("/")[0], b
        assert b["provider_name"] == title and b["fenced"] is fenced


def test_a_pin_says_why_when_it_cannot_be_used(monkeypatch):
    monkeypatch.setattr(executors, "probe", lambda eid, refresh=False: {"installed": False})
    b = fabric.agent_brain({}, {"name": "x", "model": "gemini-cli/gemini-2.5-pro"})
    assert not b["own"] and "not installed" in b["note"]
    b = fabric.agent_brain({"team": {"own_brains": False}}, {"name": "x", "model": "codex/gpt-5"})
    assert not b["own"] and "machine's brain" in b["note"]


def test_a_pin_is_one_of_the_clis_own_models(tmp_path, installed):
    c, store, *_ = _world(tmp_path)
    store.save_subagent({"name": "coder", "soul": "codes"})
    assert fabric.set_agent_model(store, c, "coder", "codex/gpt-5")["engine"] == "codex"
    assert fabric.set_agent_model(store, c, "coder", "claude-code/default")["engine"] == "claude-code"
    with pytest.raises(ValueError, match="does not offer 'opus'"):
        fabric.set_agent_model(store, c, "coder", "codex/opus")


# ------------------------------------------------------------------ each CLI, its own door

def test_gemini_gets_a_settings_file_and_the_token_stays_off_the_command_line(tmp_path):
    cmd, env = executors.build_bridge_run("gemini-cli", "do it", "SYSTEM", "http://h/api/mcp/run/T",
                                          "SECRET", 1.0, "gemini-2.5-pro", str(tmp_path),
                                          str(tmp_path))
    assert "SECRET" not in " ".join(cmd)
    settings = json.loads(Path(env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"]).read_text())
    server = settings["mcpServers"]["bento"]
    assert server["httpUrl"] == "http://h/api/mcp/run/T" and server["trust"] is True
    assert server["headers"]["Authorization"] == "Bearer SECRET"
    # fenced: no built-in tool is registered, and only this server is allowed
    assert settings["tools"]["core"] == [] and settings["mcp"]["allowed"] == ["bento"]
    assert cmd[cmd.index("--allowed-mcp-server-names") + 1] == "bento"
    assert Path(env["GEMINI_SYSTEM_MD"]).read_text() == "SYSTEM", "the prompt is replaced"
    assert oct(os.stat(env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"]).st_mode)[-3:] == "600"
    # the real CLI disables every MCP server in a folder it does not trust: this run's
    # working folder is trusted, and nothing else
    trusted = json.loads(Path(env["GEMINI_CLI_TRUSTED_FOLDERS_PATH"]).read_text())
    assert trusted == {str(tmp_path.resolve()): "TRUST_FOLDER"}


def test_the_scratch_folder_is_in_the_agentos_home_not_the_system_temp():
    """Gemini CLI skips a settings file when a folder above it is writable by others
    ("Parent directory '/tmp' is insecure"), found by pointing the real CLI at one. The
    run's folder is 0700 under the AgentOS home, whose parents a person owns."""
    from agentos import config as cfgmod
    d = Path(executors._mkscratch())
    try:
        assert d.parent == Path(cfgmod.AGENTOS_HOME) / "run"
        assert oct(d.stat().st_mode)[-3:] == "700" and oct(d.parent.stat().st_mode)[-3:] == "700"
        assert d.parent != Path(tempfile.gettempdir())
    finally:
        executors._drop_scratch(str(d))


def test_codex_gets_config_overrides_and_its_token_from_the_environment(tmp_path):
    cmd, env = executors.build_bridge_run("codex", "do it", "SYSTEM", "http://h/api/mcp/run/T",
                                          "SECRET", 1.0, "", str(tmp_path), str(tmp_path))
    line = " ".join(cmd)
    assert "SECRET" not in line and env["BENTO_RUN_TOKEN"] == "SECRET"
    assert 'mcp_servers.bento.url="http://h/api/mcp/run/T"' in line
    assert 'mcp_servers.bento.bearer_token_env_var="BENTO_RUN_TOKEN"' in line
    assert 'default_tools_approval_mode="approve"' in line
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "shell_tool" in cmd, "its shell tool is switched off"
    assert "model_instructions_file=" in line


def test_a_chat_on_gemini_or_codex_gets_the_team_door(tmp_path):
    for eng in ("gemini-cli", "codex"):
        e = executors.Envelope(workspace=str(tmp_path), engine=eng,
                               team_mcp=("http://h/api/mcp/run/T", "SECRET"))
        cmd = executors.build_command("hi", e)
        assert "SECRET" not in " ".join(cmd)
        assert e.extra_env, "the door is in this run's environment"
        executors._drop_scratch(e.scratch)


# ------------------------------------------------------------------ a team of three CLIs

class _CLIs:
    """Stands in for `_drive`: reads the bridge the way each real CLI would, asks it
    for its tools, calls one, answers."""

    def __init__(self):
        self.seen = []

    async def __call__(self, cmd, cwd, emit, run, extra_env=None):
        env = extra_env or {}
        if run.engine == "gemini-cli":
            s = json.loads(Path(env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"]).read_text())
            url = s["mcpServers"]["bento"]["httpUrl"]
            token = s["mcpServers"]["bento"]["headers"]["Authorization"].split()[-1]
        elif run.engine == "codex":
            url = next(a for a in cmd if a.startswith("mcp_servers.bento.url=")).split("=", 1)[1]
            url = json.loads(url)
            token = env[json.loads(next(a for a in cmd if "bearer_token_env_var" in a)
                                   .split("=", 1)[1])]
        else:
            conf = json.loads(cmd[cmd.index("--mcp-config") + 1])["mcpServers"]["bento"]
            url, token = conf["url"], conf["headers"]["Authorization"].split()[-1]
        assert url.endswith(token)
        _, listed = await mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in listed["result"]["tools"]}
        _, res = await mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                "params": {"name": "recall", "arguments": {"query": "x"}}})
        self.seen.append((run.engine, "recall" in names, res["result"]["isError"]))
        await emit({"type": "text_delta", "text": f"answered on {run.engine}"})
        return run


def test_three_specialists_on_three_clis_each_answer_on_their_own(tmp_path, installed, monkeypatch):
    c, store, tb, cp, events = _world(tmp_path)
    for name, pin in (("planner", "claude-code/default"), ("researcher", "gemini-cli/gemini-2.5-pro"),
                      ("coder", "codex/gpt-5")):
        store.save_subagent({"name": name, "soul": name, "tools": ["recall"], "model": pin})
    clis = _CLIs()
    monkeypatch.setattr(executors, "_drive", clis)
    for name in ("planner", "researcher", "coder"):
        res = asyncio.run(cp.run_subagent(store.get_subagent(name), "what do we know?"))
        assert res["status"] == "ok", res
        assert res["content"] == f"answered on {res['model'].split('/')[0]}"
    assert [e for e, _l, _err in clis.seen] == ["claude-code", "gemini-cli", "codex"]
    assert all(listed and not err for _e, listed, err in clis.seen), clis.seen
    # every call went through the gate, as that specialist
    rows = [r for r in store.audit_list(limit=100) if r["principal_kind"] == "subagent"]
    assert {r["principal_id"] for r in rows} >= {"planner", "researcher", "coder"}
    assert not mcpbridge.SESSIONS


def test_a_mission_runs_a_codex_agent_on_the_machines_brain_and_says_so(tmp_path, installed,
                                                                         monkeypatch):
    c, store, tb, cp, events = _world(tmp_path)
    store.save_subagent({"name": "coder", "soul": "codes", "tools": ["recall"], "model": "codex/gpt-5"})
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "gemini-cli")
    clis = _CLIs()
    monkeypatch.setattr(executors, "_drive", clis)
    res = asyncio.run(cp.run_subagent(store.get_subagent("coder"), "task", flow="nightly"))
    assert res["status"] == "ok" and res["model"].startswith("gemini-cli/")
    assert [e for e, *_ in clis.seen] == ["gemini-cli"]
    logs = [ev for ev in events if ev.get("type") == "fabric_event" and ev.get("event") == "log"]
    assert any("keeps its own read-only shell" in str(ev) for ev in logs)


def test_a_cli_that_never_asked_for_its_tools_is_an_error(tmp_path, installed, monkeypatch):
    c, store, tb, cp, events = _world(tmp_path)
    store.save_subagent({"name": "researcher", "soul": "r", "tools": ["recall"],
                         "model": "gemini-cli/gemini-2.5-pro"})

    async def talker(cmd, cwd, emit, run, extra_env=None):
        await emit({"type": "text_delta", "text": "I searched everything. Done."})
        return run
    monkeypatch.setattr(executors, "_drive", talker)
    res = asyncio.run(cp.run_subagent(store.get_subagent("researcher"), "task"))
    assert res["status"] == "error" and "never connected to the run bridge" in res["fault"]
