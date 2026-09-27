"""A forwarded chat keeps its thread.

Reported as "the chat is losing context": in the Office's agent panel, on Claude Code,
"write a ppt for it" came back as "I don't know what 'it' refers to", right under the
answer it referred to. A resumed session knows only the turns that ran in it, so
`carry_over` hands over whatever else the thread holds, and a session the CLI no
longer has is replaced by the thread as text instead of failing the turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

from agentos import executors as ex

ROOT = Path(__file__).resolve().parents[1]


def _m(role, content, **meta):
    return {"role": role, "content": content, "meta": meta}


def test_a_thread_with_no_session_hands_the_whole_conversation_over():
    prior = [_m("user", "explain a differential"), _m("assistant", "A differential lets wheels…")]
    sid, now, fallback = ex.carry_over(prior, "", "claude-code")
    assert sid == ""
    assert "explain a differential" in now and "lets wheels" in now


def test_a_session_is_told_only_what_it_did_not_see():
    prior = [_m("user", "one"), _m("assistant", "first answer", exec_session="S1"),
             _m("user", "two"), _m("assistant", "stopped half way")]      # a turn with no stamp
    sid, now, fallback = ex.carry_over(prior, "S1", "claude-code")
    assert sid == "S1"
    assert "two" in now and "stopped half way" in now
    assert "first answer" not in now, "what the session already holds is not repeated"
    assert "first answer" in fallback, "if the session is gone, the whole thread goes"


def test_nothing_is_carried_when_the_session_saw_everything():
    prior = [_m("user", "one"), _m("assistant", "answer", exec_session="S1")]
    assert ex.carry_over(prior, "S1", "claude-code")[1] == ""


def test_an_older_thread_without_stamps_counts_this_engines_replies_as_seen():
    prior = [_m("user", "one"), _m("assistant", "from claude", engine="claude-code"),
             _m("user", "two"), _m("assistant", "from the built-in agent", model="x")]
    _, now, _ = ex.carry_over(prior, "S-old", "claude-code")
    assert "from the built-in agent" in now and "from claude" not in now


def test_a_different_session_than_the_stamped_one_gets_everything():
    prior = [_m("user", "one"), _m("assistant", "answer", exec_session="OLD")]
    _, now, _ = ex.carry_over(prior, "NEW", "claude-code")
    assert "answer" in now


def test_a_cli_that_cannot_resume_always_gets_the_thread():
    prior = [_m("user", "one"), _m("assistant", "answer", exec_session="S1")]
    sid, now, _ = ex.carry_over(prior, "S1", "gemini-cli")
    assert sid == "" and "answer" in now


def test_the_carried_thread_reaches_claude_codes_prompt():
    env = ex.Envelope(workspace="/tmp/w", session_id="S1", transcript="Person: explain it")
    cmd = ex.build_command("write a ppt for it", env)
    prompt = cmd[cmd.index("--print") + 1]
    assert "Person: explain it" in prompt and prompt.rstrip().endswith("write a ppt for it")
    assert cmd[cmd.index("--resume") + 1] == "S1"
    plain = ex.build_command("hi", ex.Envelope(workspace="/tmp/w"))
    assert plain[plain.index("--print") + 1] == ex.as_prose("hi"), "nothing to carry, nothing added"


def test_a_child_never_inherits_the_parents_claude_session(monkeypatch):
    """Measured: started from inside a Claude Code session, `claude --print` reported
    the PARENT's session id, so every conversation here was saved into one session."""
    for k in ex.PARENT_SESSION_VARS:
        monkeypatch.setenv(k, "parent")
    env = ex.child_env()
    assert not any(k in env for k in ex.PARENT_SESSION_VARS)


def _stub(tmp_path: Path) -> Path:
    """A stand-in CLI: it knows session 'LIVE' only, records its argv, and speaks the
    real CLI's wire format for a session it does not have (measured on 2.1.283)."""
    log = tmp_path / "argv.jsonl"
    stub = tmp_path / "claude"
    stub.write_text(f"""#!{sys.executable}
import json, sys
a = sys.argv[1:]
open({str(log)!r}, "a").write(json.dumps(a) + "\\n")
sid = a[a.index("--resume") + 1] if "--resume" in a else "NEW"
if sid not in ("LIVE", "NEW"):
    print("No conversation found with session ID: " + sid, file=sys.stderr)
    print(json.dumps({{"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "errors": ["No conversation found with session ID: " + sid]}}))
    sys.exit(1)
print(json.dumps({{"type": "system", "subtype": "init", "session_id": sid, "model": "m"}}))
print(json.dumps({{"type": "assistant", "message": {{"content": [{{"type": "text", "text": "ok"}}]}}}}))
print(json.dumps({{"type": "result", "subtype": "success", "result": "ok", "total_cost_usd": 0}}))
""")
    stub.chmod(0o755)
    return log


@pytest.mark.asyncio
async def test_a_session_the_cli_no_longer_has_is_replaced_by_the_thread(tmp_path):
    log = _stub(tmp_path)
    seen: list[dict] = []

    async def emit(ev):
        seen.append(ev)

    env = ex.Envelope(workspace=str(tmp_path / "ws"), session_id="GONE",
                      transcript="", fallback="Person: explain a differential")
    with mock.patch.object(ex, "claude_exe", lambda: str(log.parent / "claude")):
        run = await ex.run_task("write a ppt for it", env, emit)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 2
    assert "--resume" not in calls[1], "the retry starts a new session"
    assert "explain a differential" in calls[1][calls[1].index("--print") + 1]
    assert run.session_id == "NEW"
    assert not [e for e in seen if e["type"] == "error"], "the missing session is not the person's error"
    assert any("earlier session is gone" in str(e.get("message")) for e in seen)


@pytest.mark.asyncio
async def test_a_live_session_is_resumed_once(tmp_path):
    log = _stub(tmp_path)
    env = ex.Envelope(workspace=str(tmp_path / "ws"), session_id="LIVE")
    with mock.patch.object(ex, "claude_exe", lambda: str(log.parent / "claude")):
        run = await ex.run_task("hi", env, lambda ev: asyncio.sleep(0))
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 1 and calls[0][calls[0].index("--resume") + 1] == "LIVE"
    assert run.session_id == "LIVE"


def test_every_surface_that_forwards_a_thread_carries_it():
    """Chat, Telegram and WhatsApp read the session from the conversation row and
    stamp the reply with it; an in-memory dict lost every phone thread on restart."""
    srv = (ROOT / "agentos/server.py").read_text()
    assert "execmod.carry_over(" in srv and '"exec_session": exec_sid' in srv
    # the save happens in `finally`, so a stopped turn is not forgotten
    body = srv[srv.index("await execmod.run_task(text, env, _relay, run)"):]
    fin = body[body.index("finally:"):body.index("if checkout:")]
    assert "set_exec_session" in fin
    for f in ("telegram.py", "whatsapp.py"):
        src = (ROOT / "agentos" / f).read_text()
        assert "_exec_sessions" not in src
        assert "prior=self.store.get_messages(cid)[:-1]" in src
        assert re.search(r'"exec_session": \w*run\.session_id', src)


def test_a_stored_reply_keeps_the_break_where_a_tool_ran():
    """The page draws the tool card between the two halves of a forwarded answer; the
    stored reply has no card, and a reload read "for you.Here are the three points"."""
    srv = (ROOT / "agentos/server.py").read_text()
    relay = srv[srv.index("async def _relay(ev: dict):"):srv.index("await execmod.run_task(text, env, _relay, run)")]
    brk = relay.index('collected.append("\\n\\n")')
    assert relay.index('"tool_start"') < brk < relay.index("BRIDGE_SERVER"), \
        "the break is kept for the bridge's own tool events too, before they are dropped"
