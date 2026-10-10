"""An app's AI answers on the machine's brain, as the app, through the PDP.

Asked as: "the app may need AI interfaces, and the app may be calling the agent, and the
agent may interface with executors and permissions of MCP… basically it may call the agent
and the rest follows the PDP. The app has its own permissions too, which should be tracked
in the PDP. PDP is the permission hub."

Before, appLLM, appChat, appLLM.stream and appAgent asked only `default_model`: on a
machine whose brain is Claude Code they all answered "no model configured", and so did the
in-app copilot built on appAgent. Now each one asks `executors.fenced_brain`: the machine's
brain when it can run with none of its own tools (Claude Code, Gemini CLI, over the run
bridge), else the provider model. The app is the principal of every call; which brain it
reaches is a `model.use` decision for that app, and an appAgent's tools (built-in and MCP)
are the app's, through Agent.call_tool.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors as execmod                           # noqa: E402
from agentos import mcpbridge                                      # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP, Principal                          # noqa: E402
from agentos.tools import Toolbox                                  # noqa: E402

ROOT = Path(__file__).parent.parent
SERVER = (ROOT / "agentos/server.py").read_text()


def _world(tmp_path, **cfg):
    c = {"agent_name": "Arie", "autonomy": "balanced", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321,
         "memory": {"inject_facts": 0, "inject_user": 0}, **cfg}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    return c, store, tb


def test_the_brain_an_app_reaches(monkeypatch):
    monkeypatch.setattr(execmod, "resolve_engine", lambda cfg, *a: cfg.get("_engine", "aria"))
    assert execmod.fenced_brain({"_engine": "claude-code"}) == ("claude-code", "", "")
    assert execmod.fenced_brain({"_engine": "gemini-cli"}) == ("gemini-cli", "", "")
    # Codex keeps a read-only shell however it starts: its provider model, or a sentence
    assert execmod.fenced_brain({"_engine": "codex", "default_model": "openai/x"}) == ("aria", "openai/x", "")
    e, m, why = execmod.fenced_brain({"_engine": "codex"})
    assert not e and "shell" in why and "Settings → AI providers" in why
    assert execmod.fenced_brain({"default_model": "anthropic/y"}) == ("aria", "anthropic/y", "")
    assert "no brain is set up" in execmod.fenced_brain({})[2]
    assert execmod.fenced_brain({"_engine": "claude-code"}, "named/model") == ("aria", "named/model", "")


def test_messages_become_one_prompt_for_a_cli():
    system, prompt = execmod.split_messages([
        {"role": "system", "content": "You are a stock analyst."},
        {"role": "user", "content": "INFY?"}, {"role": "assistant", "content": "Flat."},
        {"role": "user", "content": "And AAPL?"}])
    assert system == "You are a stock analyst."
    assert prompt.startswith("The conversation so far:") and "Assistant: Flat." in prompt
    assert prompt.endswith("And AAPL?")
    assert execmod.split_messages([{"role": "user", "content": "hi"}]) == ("", "hi")


def test_on_an_executor_it_answers_over_the_bridge_with_no_tools_as_the_app(tmp_path, monkeypatch):
    c, store, tb = _world(tmp_path)
    monkeypatch.setattr(execmod, "resolve_engine", lambda cfg, *a: "claude-code")
    seen = {}

    async def fake_bridge(task, system, url, token, emit, budget_usd=0.0, model="", cwd="",
                          run=None, engine="claude-code"):
        sess = mcpbridge.get(token)
        seen.update(task=task, system=system, engine=engine, tools=sess.schemas,
                    who=sess.agent.principal.label, token=token)
        await emit({"type": "text_delta", "text": "Volumes are "})
        await emit({"type": "text_delta", "text": "compressing."})
        run.model, run.tokens_in, run.tokens_out, run.cost_usd = "opus", 120, 8, 0.01
        return run
    monkeypatch.setattr(execmod, "run_on_bridge", fake_bridge)
    pieces = []

    async def sink(t):
        pieces.append(t)
    app = Principal("app", "a1b2")
    text, who, why = asyncio.run(execmod.ask_fenced(
        c, tb, [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "INFY?"}],
        principal=app, sink=sink))
    assert (text, why) == ("Volumes are compressing.", "") and pieces == ["Volumes are ", "compressing."]
    assert who == "claude-code/opus" and seen["engine"] == "claude-code"
    assert seen["tools"] == [], "no tools at all: the CLI's are off, and the app asked for none"
    assert seen["system"] == "Be brief." and seen["task"] == "INFY?"
    assert seen["who"] == app.label, "the call is the app's"
    assert mcpbridge.get(seen["token"]) is None, "the door closes when the answer is in"
    rows = store.db.execute("SELECT principal, kind, model FROM usage").fetchall()
    assert [tuple(r) for r in rows] == [(app.label, "app", "claude-code/opus")], "spend is the app's"


def test_on_codex_with_no_model_it_says_why(tmp_path, monkeypatch):
    c, store, tb = _world(tmp_path)
    monkeypatch.setattr(execmod, "resolve_engine", lambda cfg, *a: "codex")
    text, who, why = asyncio.run(execmod.ask_fenced(c, tb, [{"role": "user", "content": "hi"}]))
    assert not text and "shell" in why


def test_llm_generate_reaches_the_brain_without_a_provider(tmp_path, monkeypatch):
    c, store, tb = _world(tmp_path)
    got = {}

    async def fake(cfg, toolbox, messages, principal=None, sink=None, model="", **k):
        got["messages"] = messages
        return "an answer", "claude-code", ""
    monkeypatch.setattr(execmod, "ask_fenced", fake)
    out = asyncio.run(tb.execute("llm_generate", {"prompt": "hi", "system": "s"}))
    assert out == "an answer" and got["messages"][0] == {"role": "system", "content": "s"}


def test_every_app_ai_door_uses_the_one_brain_and_the_pdp():
    # the gate: quarantine first, then which brain is the app's decision, then llm_generate
    i = SERVER.index("async def _gate_app_llm")
    gate = SERVER[i:SERVER.index("def _app_llm_messages")]
    assert gate.index("_app_held(principal)") < gate.index('"model.use", f"model:{label}"') \
        < gate.index('decide_tool(principal, "llm_generate"')
    stream = SERVER[SERVER.index('@app.post("/api/apps/llm/stream")'):SERVER.index('@app.post("/api/apps/llm/chat")')]
    chat = SERVER[SERVER.index('@app.post("/api/apps/llm/chat")'):SERVER.index('@app.post("/api/apps/agent")')]
    agent = SERVER[SERVER.index('@app.post("/api/apps/agent")'):SERVER.index('@app.get("/api/apps/context")')]
    for door in (stream, chat):
        assert "_gate_app_llm(principal, named)" in door and "execmod.ask_fenced(" in door
        assert "principal=principal" in door and 'default_model' not in door
    assert "_app_held(principal)" in agent and '"model.use", f"model:{label}"' in agent
    assert "principal=principal" in agent and "fabric._run_on_executor(" in agent
    assert 'surface="gui", kind="app"' in agent
    ctx = SERVER[SERVER.index('@app.get("/api/apps/context")'):][:1400]
    assert '"ai_ready": not why' in ctx and '"brain": engine' in ctx
    # appLLM no longer goes through llm_generate's default-model-only path
    rt = SERVER[SERVER.index("window.appLLM = async"):][:500]
    assert "/api/apps/llm/chat" in rt and "appTool('llm_generate'" not in rt


def test_an_app_agent_is_not_a_run(tmp_path):
    """`_run_on_executor` files events under a run; an app's agent has none, and must
    not write fabric_events rows for nobody."""
    fab = (ROOT / "agentos/fabric.py").read_text()
    body = fab[fab.index("    async def _emit(self, run_id"):][:300]
    assert "if not run_id:" in body and "return" in body
    sig = fab[fab.index("    async def _run_on_executor"):][:300]
    assert 'surface: str = "task"' in sig and 'kind: str = "subagent"' in sig


def test_a_quarantined_app_is_held_on_its_ai_doors_too():
    held = SERVER[SERVER.index("def _app_held"):][:700]
    assert 'row.get("suspended_at")' in held and "status_code=409" in held


def test_calling_the_agent_is_the_apps_own_permission():
    """An app with no grant could start the agent; only its steps were asked."""
    agent = SERVER[SERVER.index('@app.post("/api/apps/agent")'):SERVER.index('@app.get("/api/apps/context")')]
    assert '"agent.invoke", "agent:main"' in agent
    assert agent.index('"agent.invoke", "agent:main"') < agent.index("_app_model_label(named)")
    assert 'request_approval(\n                "appAgent"' in agent and "offer=adec.grant_offer" in agent
    # the consent screen declares it for an app that calls the agent or mounts the ✦ assistant
    scan = SERVER[SERVER.index("def _scan_app_permissions"):SERVER.index("def _mine_app_log_permissions")]
    assert r'app(?:Agent\s*\(|Copilot\.mount\s*\()' in scan and '"agent.invoke", "agent:main"' in scan
    act = (ROOT / "agentos/ui/src/js/08b-activity.js").read_text()
    assert "name === 'appAgent'" in act


def test_the_pdp_asks_an_app_for_the_agent_and_a_grant_answers(tmp_path):
    c, store, tb = _world(tmp_path)
    app = Principal("app", "x1")
    assert tb.pdp.decide(app, "agent.invoke", "agent:main", {"surface": "gui"}).effect == "ask"
    store.add_grant("app", "x1", "agent.invoke", "agent:main", source="manifest")
    assert tb.pdp.decide(app, "agent.invoke", "agent:main", {"surface": "gui"}).effect == "allow"
    store.add_grant("app", "x1", "model.use", "model:claude-code", effect="deny", source="user")
    assert tb.pdp.decide(app, "model.use", "model:claude-code", {"surface": "gui"}).effect == "deny", \
        "which brain an app may reach is one row in Permissions"


def test_the_activity_log_never_proposes_a_runtime_name_as_a_tool():
    mine = SERVER[SERVER.index("def _mine_app_log_permissions"):SERVER.index("def _propose_manifest")]
    assert 'name.startswith(("appLLM", "appChat"))' in mine and 'name == "appAgent"' in mine
