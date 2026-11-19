"""When the jail hides Claude Code's sign-in, Bento says so instead of "network issue".

Found while filming an ad in a cloud session: Claude Code signs in there with a token file
named by CLAUDE_SESSION_INGRESS_TOKEN_FILE, kept in another user's home. Bento's CLI jail
blanks every home on purpose, so every forwarded turn failed with "Authentication error ·
This may be a temporary network issue". What these defend:

- the check only READS where the CLI is told its sign-in is, and says whether the jail hides
  it: it opens, binds and copies nothing, and the jail's mounts are unchanged;
- a sign-in the jail keeps (the state folder's credentials) is not reported;
- a turn that fails to sign in for that reason says the real reason once, in words, and that
  sentence lets a fallback brain take the turn;
- Settings and `bento doctor` say it before the first turn fails.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import executors, fallback                               # noqa: E402

ROOT = Path(__file__).parent.parent
VAR = "CLAUDE_SESSION_INGRESS_TOKEN_FILE"


@pytest.fixture
def jailed(monkeypatch):
    monkeypatch.setattr(executors, "JAIL_ENFORCED", True)
    monkeypatch.setattr(executors, "jail_ready", lambda refresh=False: True)


def _token(tmp_path, *parts):
    p = tmp_path.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("t")
    return str(p)


def test_a_sign_in_the_jail_hides_is_named(tmp_path, jailed):
    # pytest's tmp_path is under /tmp, which the jail blanks
    tok = _token(tmp_path, "other-home", ".claude", "remote", ".session_ingress_token")
    env = {VAR: tok, "CLAUDE_CONFIG_DIR": str(tmp_path / "state")}
    assert executors.hidden_signin("claude-code", env) == os.path.realpath(tok)


def test_a_sign_in_the_jail_keeps_is_not(tmp_path, jailed):
    state = tmp_path / "state"
    tok = _token(state, ".credentials.json")
    assert executors.hidden_signin("claude-code", {VAR: tok, "CLAUDE_CONFIG_DIR": str(state)}) == ""


def test_nothing_is_said_without_a_reason(tmp_path, jailed, monkeypatch):
    tok = _token(tmp_path, "x", "token")
    assert executors.hidden_signin("claude-code", {}) == ""                       # nothing named
    assert executors.hidden_signin("claude-code", {VAR: str(tmp_path / "gone")}) == ""   # no file
    assert executors.hidden_signin("claude-code", {VAR: "/etc/passwd"}) == ""     # not blanked
    assert executors.hidden_signin("gemini-cli", {VAR: tok}) == ""                # not its variable
    monkeypatch.setattr(executors, "jail_ready", lambda refresh=False: False)
    assert executors.hidden_signin("claude-code", {VAR: tok}) == ""               # no jail runs


def test_the_check_opens_nothing():
    src = (ROOT / "agentos" / "executors.py").read_text()
    body = src[src.index("def hidden_signin"):src.index("def signin_words")]
    for verb in ("open(", "read_text", "copy", "bind", "symlink", "chmod", "_bwrap"):
        assert verb not in body, verb


def _events(run, hidden, monkeypatch):
    monkeypatch.setattr(executors, "hidden_signin", lambda engine, environ=None: hidden)
    said = "Authentication error · This may be a temporary network issue, please try again"
    out = executors.translate({"type": "assistant", "error": "authentication_failed",
                               "message": {"model": "<synthetic>",
                                           "content": [{"type": "text", "text": said}]}}, run)
    out += executors.translate({"type": "result", "subtype": "success", "is_error": True,
                                "result": said, "total_cost_usd": 0, "usage": {}}, run)
    return out


def test_the_turn_says_the_real_reason_once(monkeypatch):
    run = executors.Run()
    out = _events(run, "/home/claude/.claude/remote/.session_ingress_token", monkeypatch)
    errors = [e for e in out if e["type"] == "error"]
    assert len(errors) == 1 and errors[0]["kind"] == "signin_hidden"
    assert "sandbox hides on purpose" in errors[0]["message"]
    assert "network issue" not in errors[0]["message"]
    assert not [e for e in out if e["type"] == "text_delta"]
    assert run.auth_failed and run.reported_error
    # a fallback brain may take the turn: this is "could not answer", not a refusal
    assert fallback.unavailable([errors[0]["message"]])


def test_a_sign_in_failure_for_another_reason_is_left_alone(monkeypatch):
    run = executors.Run()
    out = _events(run, "", monkeypatch)
    errors = [e for e in out if e["type"] == "error"]
    assert len(errors) == 1 and "Authentication error" in errors[0]["message"]
    assert run.auth_failed


def test_settings_and_the_doctor_say_it():
    js = (ROOT / "agentos" / "ui" / "src" / "js" / "11-settings.js").read_text()
    assert "ex.signin_hidden" in js and "ex.signin_words" in js
    assert "${ex.signin_hidden?'':bill}" in js, "the green signed-in line gives way to the warning"
    cli = (ROOT / "agentos" / "__main__.py").read_text()
    assert "hidden_signin(\"claude-code\")" in cli and "signin_words(\"claude-code\"" in cli


def test_available_carries_it(monkeypatch):
    monkeypatch.setattr(executors, "claude_exe", lambda: sys.executable)
    monkeypatch.setattr(executors, "hidden_signin", lambda engine, environ=None: "/home/x/token")
    got = executors.available()
    assert got["signin_hidden"] == "/home/x/token" and "can't sign in" in got["signin_words"]
    monkeypatch.setattr(executors, "hidden_signin", lambda engine, environ=None: "")
    got = executors.available()
    assert got["signin_hidden"] == "" and got["signin_words"] == ""
