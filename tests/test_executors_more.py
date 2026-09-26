"""Gemini CLI and Codex as brains, beside Claude Code.

Asked for as "what about the Gemini CLI or OpenAI CLI access like Claude Code". Each is
one catalogue entry, one command builder and one stream reader; the turn, the context,
the envelope and every surface stay the ones Claude Code already had. Found on the way:
choosing Hermes or OpenClaw as the brain ran CLAUDE CODE under their name, because the
command builder only knew one CLI — a detected agent this OS cannot drive is now refused
in a sentence and never offered as a brain.
"""

import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import components as comps                            # noqa: E402
from agentos import config as cfgmod                               # noqa: E402
from agentos import executors as execmod                           # noqa: E402

ROOT = Path(__file__).parent.parent


def env(engine, tools=execmod.DEFAULT_TOOLS, **kw):
    return execmod.Envelope(workspace="/tmp/ws", tools=tuple(tools), engine=engine, **kw).sanitized()


# ------------------------------------------------------------------ the catalogue

def test_both_are_offered_with_a_licence_and_the_real_command():
    by_id = {c["id"]: c for c in comps.catalog()}
    for eid, pkg in (("gemini-cli", "@google/gemini-cli"), ("codex", "@openai/codex")):
        spec = execmod.EXECUTORS_BY_ID[eid]
        assert spec["licence"] == "Apache-2.0"
        assert spec["install_cmd"] == f"npm install --global --prefix ~/.local {pkg}"
        assert spec["signin_cmd"]
        assert eid in by_id and by_id[eid]["licence"] == "Apache-2.0"
        cmd = by_id[eid]["command"]
        if cmd:                                   # npm present: the argv shown is the argv run
            assert not cmd.startswith("sudo ") and cmd.endswith(pkg) and "--prefix" in cmd


def test_the_engine_lists_agree_with_the_catalogue():
    ids = tuple(e["id"] for e in execmod.EXECUTOR_CATALOGUE)
    assert set(execmod.ENGINES) == set(ids)
    assert tuple(cfgmod.ENGINE_NAMES) == execmod.ENGINES
    assert set(execmod.DRIVEN) == {"claude-code", "gemini-cli", "codex"}
    assert execmod.MCP_ENGINES == ("claude-code",), \
        "a mission runs only where the bridge can serve this OS's tools"


def test_the_page_names_every_driven_executor():
    js = (ROOT / "agentos/ui/src/js/10-chat.js").read_text()
    line = js[js.index("var EXEC_TITLES="):].split("\n", 1)[0]
    for eid in execmod.DRIVEN:
        assert f"'{eid}'" in line, f"a {eid} reply would be labelled as the built-in agent"


def test_each_offers_its_own_models_and_the_honest_default():
    for eid in ("gemini-cli", "codex"):
        ids = [m for m, _ in execmod.AGENT_MODELS[eid]]
        assert ids[0] == "", "whatever it is signed in to use"
        assert "opus" not in ids


# ------------------------------------------------------------------ the envelope as flags

def test_gemini_is_read_only_unless_the_envelope_widens_it():
    cmd = execmod.build_command("look at my notes", env("gemini-cli"))
    assert Path(cmd[0]).name == "gemini"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--approval-mode" not in cmd, "headless it runs only its read-only tools"
    cmd = execmod.build_command("x", env("gemini-cli", ("Read", "Write")))
    assert cmd[cmd.index("--approval-mode") + 1] == "auto_edit"
    cmd = execmod.build_command("x", env("gemini-cli", ("Read", "Bash"), model="gemini-2.5-pro"))
    assert cmd[cmd.index("--approval-mode") + 1] == "yolo"
    assert cmd[cmd.index("--model") + 1] == "gemini-2.5-pro"


def test_codex_is_sandboxed_to_the_workspace():
    cmd = execmod.build_command("tidy this", env("codex"))
    assert Path(cmd[0]).name == "codex" and cmd[1] == "exec" and "--json" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("--cd") + 1] == "/tmp/ws"
    assert "--skip-git-repo-check" in cmd
    cmd = execmod.build_command("tidy this", env("codex", ("Read", "Edit")))
    assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"
    assert "danger-full-access" not in " ".join(cmd)
    assert cmd[-1].endswith("tidy this"), "the prompt is the last argument"


def test_context_and_conversation_travel_in_the_prompt():
    """Neither takes a system prompt flag, and this OS does not resume their sessions —
    so the context and the conversation so far are IN the prompt, labelled."""
    e = env("gemini-cli", context="The person is looking at Notes.",
            transcript="Person: what is 2+2\nYou: 4")
    prompt = execmod.build_command("and times three?", e)[2]
    assert "CONTEXT" in prompt and "Notes" in prompt
    assert "THE CONVERSATION SO FAR" in prompt and "You: 4" in prompt
    assert prompt.index("THE CONVERSATION") < prompt.index("and times three?")


def test_only_claude_code_is_promised_a_spend_ceiling():
    assert "up to $" in env("claude-code").describe()
    for eid in ("gemini-cli", "codex"):
        d = env(eid).describe()
        assert "up to $" not in d and "no spend ceiling" in d
        assert execmod.EXECUTORS_BY_ID[eid]["title"] in d


# ------------------------------------------------------------------ reading their streams

def test_a_gemini_stream_becomes_the_same_turn_events():
    run = execmod.Run(engine="gemini-cli")
    lines = [
        {"type": "init", "session_id": "s1", "model": "gemini-2.5-pro"},
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "tool_use", "tool_name": "read_file", "tool_id": "t1",
         "parameters": {"absolute_path": "/tmp/ws/a.txt"}},
        {"type": "tool_result", "tool_id": "t1", "status": "success", "output": "hello"},
        {"type": "message", "role": "assistant", "content": "It says hello.", "delta": True},
        {"type": "result", "status": "success", "stats": {"input_tokens": 12, "output_tokens": 4}},
    ]
    out = [e for ev in lines for e in execmod.translate_gemini(ev, run)]
    kinds = [e["type"] for e in out]
    assert kinds == ["engine_info", "status", "tool_start", "tool_end", "text_delta"]
    assert out[0]["engine"] == "gemini-cli" and out[0]["model"] == "gemini-2.5-pro"
    assert out[3]["name"] == "read_file" and out[3]["ok"] and out[3]["output"] == "hello"
    assert "user" not in json.dumps(out[4]) and out[4]["text"] == "It says hello."
    assert (run.tokens_in, run.tokens_out) == (12, 4)


def test_a_failed_gemini_run_says_why_once():
    run = execmod.Run(engine="gemini-cli")
    out = execmod.translate_gemini({"type": "error", "severity": "error",
                                    "message": "not signed in"}, run)
    out += execmod.translate_gemini({"type": "result", "status": "error"}, run)
    assert [e["type"] for e in out] == ["error"] and run.reported_error


def test_a_codex_stream_becomes_the_same_turn_events():
    run = execmod.Run(engine="codex")
    lines = [
        {"type": "thread.started", "thread_id": "th1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "i0", "type": "reasoning", "text": "look first"}},
        {"type": "item.started", "item": {"id": "i1", "type": "command_execution",
                                          "command": "ls -la", "status": "in_progress"}},
        {"type": "item.completed", "item": {"id": "i1", "type": "command_execution",
                                            "command": "ls -la", "aggregated_output": "a.txt\n",
                                            "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"id": "i2", "type": "file_change", "status": "completed",
                                            "changes": [{"path": "notes.md", "kind": "add"}]}},
        {"type": "item.completed", "item": {"id": "i3", "type": "agent_message", "text": "Done."}},
        {"type": "turn.completed", "usage": {"input_tokens": 30, "cached_input_tokens": 5,
                                             "output_tokens": 7}},
    ]
    out = [e for ev in lines for e in execmod.translate_codex(ev, run)]
    kinds = [e["type"] for e in out]
    assert kinds == ["engine_info", "status", "thinking_delta", "tool_start", "tool_end",
                     "tool_start", "tool_end", "text_delta"]
    assert out[3]["name"] == "shell" and out[3]["detail"] == "ls -la"
    assert out[4]["ok"] and out[4]["output"] == "a.txt\n"
    assert out[5]["name"] == "edit" and out[5]["detail"] == "notes.md"
    assert out[-1]["text"] == "Done."
    assert run.session_id == "th1" and (run.tokens_in, run.tokens_out) == (30, 7)


def test_a_failed_codex_command_is_a_failed_step_and_a_failed_turn_is_said():
    run = execmod.Run(engine="codex")
    execmod.translate_codex({"type": "item.started", "item": {
        "id": "c", "type": "command_execution", "command": "rm x"}}, run)
    end = execmod.translate_codex({"type": "item.completed", "item": {
        "id": "c", "type": "command_execution", "command": "rm x", "exit_code": 1,
        "status": "failed", "aggregated_output": "denied"}}, run)
    assert end[0]["ok"] is False
    err = execmod.translate_codex({"type": "turn.failed", "error": {"message": "401"}}, run)
    assert err == [{"type": "error", "message": "401"}] and run.reported_error


# ------------------------------------------------------------------ a whole turn

FAKE_GEMINI = r"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
prompt = args[args.index("--prompt") + 1]
with open(sys.argv[0] + ".log", "a") as f:
    f.write(json.dumps(args) + "\n")
for ev in ({"type": "init", "session_id": "g1", "model": "gemini-2.5-flash"},
           {"type": "message", "role": "assistant", "content": "gemini heard: ", "delta": True},
           {"type": "message", "role": "assistant", "content": prompt.splitlines()[-1], "delta": True},
           {"type": "result", "status": "success", "stats": {"input_tokens": 3, "output_tokens": 2}}):
    print(json.dumps(ev), flush=True)
"""


@pytest.fixture()
def fake_gemini(tmp_path, monkeypatch):
    exe = tmp_path / "gemini"
    exe.write_text(FAKE_GEMINI)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    real = execmod._find_bin
    monkeypatch.setattr(execmod, "_find_bin",
                        lambda names: str(exe) if "gemini" in names else real(names))
    return exe


def test_a_turn_is_forwarded_to_gemini_end_to_end(fake_gemini, tmp_path):
    cfg = {"executors": {"gemini_cli": {"model": "gemini-2.5-flash"}}}
    reply, run = asyncio.run(execmod.forward("gemini-cli", "what is in my inbox", cfg,
                                             str(tmp_path / "ws")))
    assert reply == "gemini heard: what is in my inbox"
    assert run.engine == "gemini-cli" and run.model == "gemini-2.5-flash"
    args = json.loads(Path(str(fake_gemini) + ".log").read_text().splitlines()[-1])
    assert args[args.index("--model") + 1] == "gemini-2.5-flash", "its OWN model, not claude's"


def test_drafting_a_mission_works_on_gemini(fake_gemini, tmp_path, monkeypatch):
    """ask_brain goes through forward, so the drafts that broke on an executor brain
    work on these too — the designer's answer comes back from the CLI."""
    monkeypatch.setattr(execmod, "resolve_engine", lambda cfg, requested="": "gemini-cli")
    text, who, why = asyncio.run(execmod.ask_brain({}, "You design.", "a mission please"))
    assert who == "gemini-cli" and not why and "a mission please" in text


def test_a_team_without_a_door_is_still_named(tmp_path):
    """No per-run MCP config for these, so no door — but the executor is told who the
    specialists are and to send the person to `@name`, rather than doing the
    toolsmith's job in silence."""
    class Store:
        def list_subagents(self):
            return [{"name": "toolsmith", "soul": "You build tools. Carefully."}]
    e = env("gemini-cli")
    token = execmod.open_team_door(e, {}, object(), Store(), None, None)
    assert token == "" and not e.team_mcp
    assert "toolsmith: You build tools." in e.context and "@name" in e.context
    assert "NEVER set it up yourself as a cron job" in e.context


# ------------------------------------------------------------------ the ones it cannot drive

def test_a_detected_agent_this_os_cannot_drive_is_refused_not_impersonated(monkeypatch):
    started = []

    async def never(*a, **k):
        started.append(a)
        raise AssertionError("no process may start")
    monkeypatch.setattr(execmod, "run_task", never)
    reply, run = asyncio.run(execmod.forward("hermes", "hi", {}, "/tmp/ws"))
    assert reply.startswith("[error] Hermes is installed, but AgentOS cannot run a turn on it")
    assert run is None and not started


def test_it_is_not_offered_as_a_brain_either(monkeypatch):
    monkeypatch.setattr(execmod, "probe", lambda eid, refresh=False: {
        "installed": True, "title": execmod.EXECUTORS_BY_ID[eid]["title"], "why_not": ""})
    st = execmod.brains({}, [])
    by = {e["id"]: e for e in st["executors"]}
    assert by["gemini-cli"]["available"] and by["codex"]["available"]
    assert not by["hermes"]["available"] and "cannot run a turn" in by["hermes"]["reason"]
    ok, why = execmod.set_brain({}, "openclaw", "", [])
    assert not ok and "cannot run a turn" in why
    ok, why = execmod.set_brain(c := {}, "codex", "gpt-5", [])
    assert ok and c["engine"] == "codex" and c["executors"]["codex"]["model"] == "gpt-5"
