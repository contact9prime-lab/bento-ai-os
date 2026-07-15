"""Core regression suite — the safety net for chat, builds, git, and policy.

Run with:  uv run pytest -q
The agent's `run_tests` tool runs this before any self-modification restart.
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod           # noqa: E402
from agentos import providers                  # noqa: E402
from agentos.memory import Store               # noqa: E402
from agentos.tools import Toolbox, classify_command  # noqa: E402
from agentos.server import _validate_app_html  # noqa: E402


# ---------------------------------------------------------------------------
# shell risk classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd,want", [
    ("ls -la", "safe"),
    ("git status", "safe"),
    ("git log --oneline", "safe"),
    ("git diff HEAD~1", "safe"),
    ("git config user.name", "safe"),
    ("git config user.name Bob", "risky"),
    ("git push origin main", "risky"),
    ("git reset --hard", "risky"),
    ("git clean -fdx", "risky"),
    ("git remote -v", "safe"),
    ("git remote add origin http://x", "risky"),
    ("git branch -a -v", "safe"),
    ("git branch -D main", "risky"),
    ("ls && git push", "risky"),
    ("rm -rf /", "blocked"),
    ("curl https://example.com", "safe"),
])
def test_classify_command(cmd, want):
    assert classify_command(cmd) == want


# ---------------------------------------------------------------------------
# app completeness validator
# ---------------------------------------------------------------------------

GOOD_APP = """<!DOCTYPE html><html><head><title>x</title></head>
<body><div id="a"><button onclick="go()">go</button></div>
<script>function go(){document.getElementById('a').textContent='hi'}</script>
</body></html>"""


def test_validator_accepts_complete_app():
    assert _validate_app_html(GOOD_APP) == []


@pytest.mark.parametrize("html,fragment", [
    ("", "empty"),
    ("<html><body><div>truncated", "never closes"),
    (GOOD_APP + "\n<script>(function(){", "after </html>"),
    ("<body><script>var a=1;", "unclosed <script"),
    ("<div>x</div> function foo(){ document.getElementById('x') }", "visible page text"),
    ("```html\n<div>hi</div>\n```", "code fence"),
])
def test_validator_rejects_broken_apps(html, fragment):
    issues = _validate_app_html(html)
    assert issues, f"expected issues for {html[:40]!r}"
    assert any(fragment in i for i in issues), f"{fragment!r} not in {issues}"


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------

def test_parse_model_id():
    assert providers.parse_model_id("ollama/qwen3.5:9b") == ("ollama", "qwen3.5:9b")
    assert providers.parse_model_id("qwen3.5:9b") == ("ollama", "qwen3.5:9b")
    assert providers.parse_model_id("anthropic/claude-sonnet-5") == ("anthropic", "claude-sonnet-5")


def test_norm_finish():
    assert providers._norm_finish("length") == "length"
    assert providers._norm_finish("max_tokens") == "length"
    assert providers._norm_finish("stop") == "stop"
    assert providers._norm_finish("") == "stop"


@pytest.mark.asyncio
async def test_unknown_provider_raises():
    with pytest.raises(providers.ProviderError):
        async for _ in providers.chat({"providers": {}}, "nope/model", [], []):
            pass


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

def test_store_wal_and_roundtrip(tmp_path):
    s = Store(tmp_path / "t.db")
    assert s.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    cid = s.create_conversation("hello")
    s.add_message(cid, "user", "hi")
    s.add_message(cid, "assistant", "yo", {"steps": []})
    msgs = s.get_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]


# ---------------------------------------------------------------------------
# git tools (real git in a temp workspace)
# ---------------------------------------------------------------------------

@pytest.fixture()
def toolbox(tmp_path):
    cfg = cfgmod.load_config()
    cfg["workspace"] = str(tmp_path)
    cfg["sandbox"] = {"enabled": False, "root": ""}
    return Toolbox(cfg, Store(tmp_path / "db.sqlite"))


@pytest.mark.asyncio
async def test_git_roundtrip(toolbox, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.txt").write_text("one\n")
    out = await toolbox.git_init(str(proj))
    assert "Initialized" in out
    out = await toolbox.git_commit(str(proj), "first")
    assert not out.startswith("[error]"), out
    (proj / "a.txt").write_text("two\n")
    d = await toolbox.git_diff(str(proj))
    assert "-one" in d and "+two" in d
    out = await toolbox.git_commit(str(proj), "second")
    assert not out.startswith("[error]")
    log = await toolbox.git_log(str(proj))
    assert "second" in log and "first" in log
    # push without a remote fails with guidance, not a crash
    out = await toolbox.git_push(str(proj))
    assert out.startswith("[error]") and "remote" in out


@pytest.mark.asyncio
async def test_git_commit_empty_message(toolbox, tmp_path):
    proj = tmp_path / "p2"
    proj.mkdir()
    await toolbox.git_init(str(proj))
    out = await toolbox.git_commit(str(proj), "   ")
    assert out.startswith("[error]")


def test_git_risk_levels(toolbox):
    ws = toolbox.cfg["workspace"]
    assert toolbox.risk_of("git_status", {})[0] == "safe"
    assert toolbox.risk_of("git_commit", {"path": ws})[0] == "safe"
    assert toolbox.risk_of("git_commit", {"path": "/etc"})[0] == "risky"
    assert toolbox.risk_of("git_push", {})[0] == "risky"
    assert toolbox.risk_of("git_clone", {})[0] == "risky"
    assert toolbox.risk_of("export_app_to_git", {"app": "x"})[0] == "safe"
    assert toolbox.risk_of("export_app_to_git", {"app": "x", "push": True})[0] == "risky"


def test_train_risk_levels(toolbox):
    assert toolbox.risk_of("trainforge_service", {"action": "start"})[0] == "safe"
    assert toolbox.risk_of("train_autopilot", {"goal": "x"})[0] == "risky"
    assert toolbox.risk_of("train_job", {"action": "create"})[0] == "risky"
    assert toolbox.risk_of("train_job", {"action": "list"})[0] == "safe"
    assert toolbox.risk_of("train_model", {"action": "publish"})[0] == "risky"
    assert toolbox.risk_of("train_model", {"action": "predict"})[0] == "safe"


# ---------------------------------------------------------------------------
# toolbox execute guardrails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_truncated_tool_call_args_get_guidance(toolbox):
    out = await toolbox.execute("create_app", {"_raw": '{"name": "x", "html": "<div'})
    assert "cut off" in out and "```html" in out


@pytest.mark.asyncio
async def test_unknown_tool(toolbox):
    out = await toolbox.execute("no_such_tool", {})
    assert out.startswith("[error]")


# ---------------------------------------------------------------------------
# sandbox (cross-platform jail wrapper)
# ---------------------------------------------------------------------------

def test_macos_sandbox_profile_confines_writes():
    from agentos.tools import _sandbox_exec_profile, sandbox_exec_argv
    prof = _sandbox_exec_profile("/Users/x/AgentOS")
    assert "(deny file-write*)" in prof
    assert '(subpath "/Users/x/AgentOS")' in prof
    argv = sandbox_exec_argv("/Users/x/AgentOS", "echo hi", chdir="/Users/x/AgentOS")
    assert argv[0] == "sandbox-exec" and argv[1] == "-p"
    assert argv[-1].startswith("cd ") and "echo hi" in argv[-1]


def test_jail_argv_picks_mechanism(monkeypatch):
    import agentos.tools as T
    monkeypatch.setattr(T, "sandbox_mechanism", lambda: "bwrap")
    assert T.jail_argv("/root", "ls")[0] == "bwrap"
    monkeypatch.setattr(T, "sandbox_mechanism", lambda: "sandbox-exec")
    assert T.jail_argv("/root", "ls")[0] == "sandbox-exec"
    monkeypatch.setattr(T, "sandbox_mechanism", lambda: "")
    assert T.jail_argv("/root", "ls") is None


# ---------------------------------------------------------------------------
# hermes companion (no CLI needed — just the parsing/guards)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_ask_without_cli(monkeypatch):
    from agentos import hermes
    monkeypatch.setattr(hermes, "cli_path", lambda: "")
    out = await hermes.ask("hi")
    assert out.startswith("[error]") and "not installed" in out


@pytest.mark.asyncio
async def test_hermes_send_requires_target(monkeypatch):
    from agentos import hermes
    monkeypatch.setattr(hermes, "cli_path", lambda: "/usr/bin/hermes")
    out = await hermes.send("", "hello")
    assert out.startswith("[error]")


def test_hermes_risk_levels(toolbox):
    assert toolbox.risk_of("hermes_status", {})[0] == "safe"
    assert toolbox.risk_of("hermes_ask", {"task": "x"})[0] == "risky"
    assert toolbox.risk_of("hermes_send", {"target": "slack"})[0] == "risky"


@pytest.mark.asyncio
async def test_hermes_write_config_rejects_broken_yaml(tmp_path, monkeypatch):
    from agentos import hermes
    cfgfile = tmp_path / "config.yaml"
    cfgfile.write_text("model:\n  default: gemma\n")
    monkeypatch.setattr(hermes, "HOME", str(tmp_path))
    monkeypatch.setattr(hermes, "CONFIG_PATH", str(cfgfile))
    before = cfgfile.read_text()
    out = await hermes.write_config("model:\n  default: [unclosed")
    assert out.startswith("[error]")
    assert cfgfile.read_text() == before        # a bad edit never overwrites the good file
    ok = await hermes.write_config("model:\n  default: qwen\n")
    assert not ok.startswith("[error]")
    assert "qwen" in cfgfile.read_text()


def test_hermes_conf_defaults():
    from agentos import hermes
    c = hermes.conf({})
    assert c["repo"].endswith("hermes-agent.git")
    assert c["engine_enabled"] is True
    c2 = hermes.conf({"hermes": {"engine_enabled": False, "repo": "x"}})
    assert c2["engine_enabled"] is False and c2["repo"] == "x"
