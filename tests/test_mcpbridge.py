"""The run bridge: an executor's model, this OS's hands.

What these defend: a tool call that arrives from Claude Code over MCP passes the
SAME gate as one from the built-in loop — the PDP decision, the ledger row, the
tool log, the step ceiling — and a whole flow (master, specialist, blackboard,
deliverable) can run on the executor with no provider model at all. The CLI is
faked; the bridge, the fabric and the gate are real.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors, fabric, flows, jobs, mcpbridge      # noqa: E402
from agentos.agent import Agent                                    # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP, Principal                          # noqa: E402
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


def _agent(c, tb, tools, events):
    async def emit(ev):
        events.append(ev)

    async def approver(*a, **k):
        return True
    return Agent(c, tb, "ollama/x", emit, approver, tool_filter=tools,
                 principal=Principal("subagent", "researcher"))


async def _rpc(token, method, params=None, rid=1):
    return await mcpbridge.handle(token, {"jsonrpc": "2.0", "id": rid, "method": method,
                                          "params": params or {}})


# ---------------------------------------------------------------------------
# The session and the gate
# ---------------------------------------------------------------------------

def test_a_session_serves_exactly_the_agents_tools_and_nothing_else(tmp_path):
    c, store, tb, cp, events = _world(tmp_path)
    a = _agent(c, tb, ["system_info", "recall"], events)
    a._task_text = "x"
    token = mcpbridge.open_session(a, a._tools(), run_id="r1", label="test")
    try:
        code, body = asyncio.run(_rpc(token, "initialize"))
        assert code == 200 and body["result"]["serverInfo"]["name"] == "bento"
        code, body = asyncio.run(_rpc(token, "tools/list"))
        names = {t["name"] for t in body["result"]["tools"]}
        assert names == {"system_info", "recall"}
        assert all("inputSchema" in t for t in body["result"]["tools"])
        # a tool the run was never given is refused BY NAME, not silently run
        code, body = asyncio.run(_rpc(token, "tools/call",
                                      {"name": "read_file", "arguments": {"path": "/etc/passwd"}}))
        assert body["result"]["isError"] and "no tool called 'read_file'" in \
            body["result"]["content"][0]["text"]
    finally:
        mcpbridge.close_session(token)


def test_a_call_over_the_bridge_passes_the_gate_and_lands_in_the_ledger(tmp_path):
    c, store, tb, cp, events = _world(tmp_path)
    a = _agent(c, tb, ["system_info"], events)
    a._task_text = "x"
    token = mcpbridge.open_session(a, a._tools(), run_id="r1")
    before = len(store.audit_list(limit=1000))
    try:
        code, body = asyncio.run(_rpc(token, "tools/call",
                                      {"name": "system_info", "arguments": {}}))
    finally:
        mcpbridge.close_session(token)
    assert code == 200 and body["result"]["isError"] is False
    assert body["result"]["content"][0]["text"]
    rows = store.audit_list(limit=1000)
    assert len(rows) == before + 1                      # one PDP decision, one ledger row
    assert rows[0]["principal_id"] == "researcher" and rows[0]["outcome"] == "ok"
    kinds = [e["type"] for e in events]
    assert "tool_start" in kinds and "tool_end" in kinds   # the run stream saw the step


def test_the_step_ceiling_and_a_stopped_run_refuse_further_calls(tmp_path):
    c, store, tb, cp, events = _world(tmp_path)
    a = _agent(c, tb, ["system_info"], events)
    a._task_text = "x"
    token = mcpbridge.open_session(a, a._tools(), max_calls=2)
    try:
        for _ in range(2):
            code, body = asyncio.run(_rpc(token, "tools/call", {"name": "system_info"}))
            assert not body["result"]["isError"]
        code, body = asyncio.run(_rpc(token, "tools/call", {"name": "system_info"}))
        assert body["result"]["isError"] and "step limit" in body["result"]["content"][0]["text"]
        a.aborted = True
        s = mcpbridge.get(token)
        s.max_calls = 10
        code, body = asyncio.run(_rpc(token, "tools/call", {"name": "system_info"}))
        assert body["result"]["isError"] and "stopped" in body["result"]["content"][0]["text"]
    finally:
        mcpbridge.close_session(token)


def test_an_unknown_or_closed_token_answers_nothing(tmp_path):
    c, store, tb, cp, events = _world(tmp_path)
    a = _agent(c, tb, ["system_info"], events)
    a._task_text = "x"
    code, body = asyncio.run(_rpc("nope", "tools/list"))
    assert code == 401
    token = mcpbridge.open_session(a, a._tools())
    mcpbridge.close_session(token)
    code, body = asyncio.run(_rpc(token, "tools/list"))
    assert code == 401
    # a notification wants no answer
    token = mcpbridge.open_session(a, a._tools())
    try:
        code, body = asyncio.run(mcpbridge.handle(
            token, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        assert code == 202 and body is None
    finally:
        mcpbridge.close_session(token)


def test_the_bridge_command_confines_the_executor_to_our_tools():
    cmd = executors.build_bridge_command("do it", "SYS", "http://127.0.0.1:1/api/mcp/run/T",
                                         "T", 3.0, model="sonnet")
    s = " ".join(cmd)
    i = cmd.index("--tools")
    assert cmd[i + 1] == ""                                  # every native tool off
    assert "--strict-mcp-config" in cmd                       # nothing from ~/.claude.json
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__bento"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "--system-prompt" in cmd and "--append-system-prompt" not in cmd
    assert '"Authorization": "Bearer T"' in s and '"type": "http"' in s
    assert cmd[cmd.index("--model") + 1] == "sonnet"


# ---------------------------------------------------------------------------
# A whole flow on the executor, with no provider model at all
# ---------------------------------------------------------------------------

class _FakeCLI:
    """Plays Claude Code: reads the tool list over the bridge and works through it.
    The master delegates once and finishes; the specialist recalls and answers."""

    def __init__(self):
        self.runs = []

    async def __call__(self, task, system, url, token, emit, budget_usd=0.0, model="",
                       cwd="", run=None):
        run = run or executors.Run()
        self.runs.append({"task": task, "system": system, "url": url, "budget": budget_usd})
        assert url.endswith("/api/mcp/run/" + token)
        assert "mcp__bento__" in system                 # the note that names our tools
        _, listed = await _rpc(token, "tools/list")
        names = {t["name"] for t in listed["result"]["tools"]}
        if "delegate" in names:                        # the master
            assert {"delegate", "read_handle", "note", "finish", "recall"} <= names
            assert "fetch_url" not in names            # the master does no work itself
            await _rpc(token, "tools/call", {"name": "note", "arguments": {"text": "plan: ask"}})
            _, res = await _rpc(token, "tools/call",
                                {"name": "delegate",
                                 "arguments": {"subagent": "researcher", "task": "find it"}})
            assert not res["result"]["isError"], res
            assert "researcher · ok" in res["result"]["content"][0]["text"]
            _, fin = await _rpc(token, "tools/call",
                                {"name": "finish", "arguments": {"summary": "ACME was mentioned."}})
            assert "complete" in fin["result"]["content"][0]["text"]
            # anything after finish is refused: the run is over
            _, late = await _rpc(token, "tools/call", {"name": "note", "arguments": {"text": "x"}})
            assert late["result"]["isError"]
        else:                                          # a specialist
            assert "recall" in names and "delegate" not in names
            await _rpc(token, "tools/call", {"name": "recall", "arguments": {"query": "ACME"}})
            await emit({"type": "text_delta", "text": "ACME appears twice."})
        run.model = "claude-sonnet-x"
        run.tokens_in, run.tokens_out, run.cost_usd = 120, 30, 0.0042
        return run


def test_a_flow_runs_end_to_end_on_the_executor_through_the_bridge(tmp_path, monkeypatch):
    # The URL must name the port the server is LISTENING on, not the one in config:
    # `bento serve --port N` binds N and leaves config alone, and the first real run
    # built its URL from config (8321), reached nothing, and reported "bridge failed".
    monkeypatch.setenv("AGENTOS_BOUND_PORT", "8399")
    c, store, tb, cp, events = _world(tmp_path, engine="claude-code")
    store.save_subagent({"name": "researcher", "soul": "research", "tools": ["recall"]})
    flow, _ = flows.save(store, {"name": "digest", "mission": "Find the mentions.",
                                 "roster": ["researcher"],
                                 "permissions": {"tools": [], "memory": "read-space"},
                                 "sinks": []})
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")
    cli = _FakeCLI()
    monkeypatch.setattr(executors, "run_on_bridge", cli)
    res = asyncio.run(cp.run_flow(flow, origin={"surface": "task"}))
    assert res["status"] == "ok", res
    assert res["content"] == "ACME was mentioned."
    assert res["delegations"] == 1
    assert len(cli.runs) == 2                          # the master and one specialist
    assert all(r["url"].startswith("http://127.0.0.1:8399/api/mcp/run/") for r in cli.runs)
    master = store.fabric_run(res["run_id"])
    assert master["model"].startswith("claude-code/")
    kids = store.fabric_runs(parent_run=res["run_id"])
    assert len(kids) == 1 and kids[0]["status"] == "ok" and "ACME" in kids[0]["output"]
    assert kids[0]["model"].startswith("claude-code/")
    # the spend is in Usage, priced, under the executor's name
    used = store.usage_summary(group="model")
    assert any(u["bucket"].startswith("claude-code/") for u in used)
    # every call went through the gate: ledger rows for the flow and the child
    kinds = {r["principal_kind"] for r in store.audit_list(limit=1000)}
    assert {"flow", "subagent"} <= kinds
    assert not mcpbridge.SESSIONS                      # nothing left open
    # the graph the UI draws saw the delegation
    types = [e.get("event") for e in events if e.get("type") == "fabric_event"]
    assert "node_add" in types and "flow_end" in types


def test_readiness_is_green_on_an_executor_that_takes_the_bridge(monkeypatch):
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")
    r = jobs.readiness({"engine": "claude-code", "default_model": "", "providers": {}})
    assert r["ok"] and "MCP" in r["note"] and not r["fix"]
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "hermes")
    r = jobs.readiness({"engine": "hermes", "default_model": "", "providers": {}})
    assert r["ok"] is False and "Hermes" in r["note"] and "Claude Code can" in r["note"]


# ---------------------------------------------------------------------------
# The door
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        yield cl


def test_the_route_wants_a_live_token_twice_and_is_loopback_only(client, tmp_path):
    assert client.post("/api/mcp/run/nope", json={"jsonrpc": "2.0", "id": 1,
                                                  "method": "ping"}).status_code == 401
    from agentos import server as servermod
    st = servermod.state
    a = _agent(st["cfg"], st["toolbox"], ["system_info"], [])
    a._task_text = "x"
    token = mcpbridge.open_session(a, a._tools())
    try:
        # the token in the URL alone is not enough: the header must carry it too
        r = client.post(f"/api/mcp/run/{token}", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 401
        h = {"Authorization": f"Bearer {token}"}
        r = client.post(f"/api/mcp/run/{token}", headers=h,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200
        assert [t["name"] for t in r.json()["result"]["tools"]] == ["system_info"]
        r = client.post(f"/api/mcp/run/{token}", headers=h,
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert r.status_code == 202
        r = client.post(f"/api/mcp/run/{token}", headers=h,
                        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "system_info", "arguments": {}}})
        assert r.status_code == 200 and not r.json()["result"]["isError"]
        assert client.get(f"/api/mcp/run/{token}", headers=h).status_code == 405
        assert client.delete(f"/api/mcp/run/{token}", headers=h).status_code == 200
    finally:
        mcpbridge.close_session(token)
    # the route is open to a cookie-less caller: it must be in the remote-open list
    assert any(p.startswith("/api/mcp/run") for p in servermod.REMOTE_OPEN_PATHS)


def test_a_master_that_neither_delegates_nor_finishes_is_not_ok(tmp_path, monkeypatch):
    """The first real run on the bridge produced the single word 'delegate' as text —
    the CLI had connected to nothing — and the row said ok. It must not."""
    c, store, tb, cp, events = _world(tmp_path, engine="claude-code")
    store.save_subagent({"name": "researcher", "soul": "research", "tools": ["recall"]})
    flow, _ = flows.save(store, {"name": "digest", "mission": "Find it.", "roster": ["researcher"],
                                 "permissions": {"tools": [], "memory": "read-space"}, "sinks": []})
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")

    async def silent(task, system, url, token, emit, budget_usd=0.0, model="", cwd="", run=None):
        await emit({"type": "text_delta", "text": "delegate"})
        return run or executors.Run()
    monkeypatch.setattr(executors, "run_on_bridge", silent)
    res = asyncio.run(cp.run_flow(flow, origin={"surface": "task"}))
    assert res["status"] == "error" and "without delegating" in res["fault"]

    async def unconnected(task, system, url, token, emit, budget_usd=0.0, model="", cwd="", run=None):
        await emit({"type": "engine_info", "engine": "claude-code", "model": "m", "tools": [],
                    "mcp": [{"name": "bento", "status": "failed"}]})
        await emit({"type": "text_delta", "text": "delegate"})
        return run or executors.Run()
    monkeypatch.setattr(executors, "run_on_bridge", unconnected)
    res = asyncio.run(cp.run_flow(flow, origin={"surface": "task"}))
    assert res["status"] == "error" and "bridge did not connect" in res["fault"]
    logs = [e for e in events if e.get("type") == "fabric_event" and e.get("event") == "log"]
    assert any("bridge failed" in (e.get("text") or "") for e in logs)
