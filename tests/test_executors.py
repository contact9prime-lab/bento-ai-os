"""Delegating a task to another agent on this machine.

The envelope is the whole safety story: this build of the Claude Code CLI has no
per-call permission hook, so what a run may touch is decided once, before it
starts. These tests exist so that stays true — a widening that slips through here
is a capability the user never granted.
"""

import asyncio
import json
import os
import shutil
from pathlib import Path
from unittest import mock

import pytest

from agentos import executors as ex


# --- the envelope ----------------------------------------------------------

def test_unknown_tools_are_dropped_not_passed_through():
    """An unrecognised name would reach the CLI verbatim and mean whatever it
    made of it — which is exactly what the envelope exists to prevent."""
    env = ex.Envelope(workspace="/tmp/ws", tools=("Read", "Bash", "Sudo", "")).sanitized()
    assert env.tools == ("Read", "Bash")


def test_budget_is_clamped_at_both_ends():
    assert ex.Envelope(workspace="/w", budget_usd=0).sanitized().budget_usd == 0.05
    assert ex.Envelope(workspace="/w", budget_usd=10_000).sanitized().budget_usd == ex.MAX_BUDGET_USD
    assert ex.Envelope(workspace="/w", budget_usd=1.5).sanitized().budget_usd == 1.5


def test_the_default_envelope_cannot_change_anything():
    """Switching an executor on must not, by itself, grant write access."""
    assert set(ex.DEFAULT_TOOLS).isdisjoint({"Write", "Edit", "Bash"})


def test_the_envelope_says_plainly_whether_it_can_write():
    read_only = ex.Envelope(workspace="/w", tools=("Read", "Grep")).describe()
    assert "read-only" in read_only

    writes = ex.Envelope(workspace="/w", tools=("Read", "Bash")).describe()
    assert "can change files and run commands" in writes


# --- the command ------------------------------------------------------------

def test_every_bound_reaches_the_command_line():
    """A bound that isn't in argv isn't a bound at all."""
    env = ex.Envelope(workspace="/tmp/ws", tools=("Read", "Grep"),
                      model="opus", budget_usd=3.5).sanitized()
    cmd = ex.build_command("do the thing", env)

    assert "--print" in cmd and "do the thing" in cmd
    # a program is driving this, so the machine-readable stream is not optional
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd, "the CLI rejects stream-json without it"
    assert cmd[cmd.index("--add-dir") + 1] == "/tmp/ws"
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep"
    assert cmd[cmd.index("--max-budget-usd") + 1] == "3.50"
    assert cmd[cmd.index("--model") + 1] == "opus"
    # headless: a prompt nobody can answer would hang the turn forever
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"


def test_no_tools_means_the_flag_is_still_sent():
    """Omitting --tools would fall back to the CLI's full default set — the exact
    opposite of what an empty envelope asked for."""
    cmd = ex.build_command("x", ex.Envelope(workspace="/w", tools=()).sanitized())
    assert cmd[cmd.index("--tools") + 1] == ""


def test_resuming_carries_the_executor_session():
    cmd = ex.build_command("x", ex.Envelope(workspace="/w", session_id="abc-123").sanitized())
    assert cmd[cmd.index("--resume") + 1] == "abc-123"
    assert "--resume" not in ex.build_command("x", ex.Envelope(workspace="/w").sanitized())


# --- translation into AgentOS turn events -----------------------------------

def test_assistant_text_becomes_a_text_delta():
    run = ex.Run()
    out = ex.translate({"type": "assistant",
                        "message": {"content": [{"type": "text", "text": "hello"}]}}, run)
    assert out == [{"type": "text_delta", "text": "hello"}]


def test_tool_use_and_result_pair_up_by_call_id():
    """The chat window matches tool_end to tool_start by call_id — if the ids
    don't line up, a delegated run shows tool chips that never resolve."""
    run = ex.Run()
    start = ex.translate({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file": "a.py"}}]}}, run)
    assert start[0]["type"] == "tool_start"
    assert start[0]["call_id"] == "toolu_1" and start[0]["name"] == "Read"
    assert start[0]["pending_approval"] is False   # the envelope already decided

    end = ex.translate({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "toolu_1",
         "content": [{"type": "text", "text": "print(1)"}]}]}}, run)
    assert end[0]["type"] == "tool_end"
    assert end[0]["call_id"] == "toolu_1"
    assert end[0]["output"] == "print(1)" and end[0]["ok"] is True


def test_a_failed_tool_result_is_reported_as_failed():
    run = ex.Run()
    out = ex.translate({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t", "content": "boom", "is_error": True}]}}, run)
    assert out[0]["ok"] is False


def test_init_records_the_session_so_the_next_turn_continues_it():
    run = ex.Run()
    ex.translate({"type": "system", "subtype": "init", "session_id": "sess-9",
                  "model": "claude-opus-5", "tools": ["Read"]}, run)
    assert run.session_id == "sess-9"


def test_blocked_tools_are_named_rather_than_silently_dropped():
    """A run that quietly did less than asked because a tool was withheld is the
    one failure the user cannot diagnose from the transcript."""
    run = ex.Run()
    out = ex.translate({"type": "result", "subtype": "success", "total_cost_usd": 0.4,
                        "num_turns": 3,
                        "permission_denials": [{"tool_name": "Bash"}]}, run)
    text = "".join(o.get("text", "") for o in out)
    assert "Bash" in text and "Settings" in text
    assert run.cost_usd == 0.4 and run.turns == 3


def test_a_failed_run_surfaces_an_error_event():
    run = ex.Run()
    out = ex.translate({"type": "result", "subtype": "error_max_turns",
                        "is_error": True, "result": "ran out of turns"}, run)
    assert any(o["type"] == "error" and "ran out of turns" in o["message"] for o in out)


def test_a_successful_run_raises_no_error():
    run = ex.Run()
    out = ex.translate({"type": "result", "subtype": "success", "result": "done",
                        "total_cost_usd": 0.1, "num_turns": 1}, run)
    assert not [o for o in out if o["type"] == "error"]


# --- availability -----------------------------------------------------------

def test_a_missing_executor_explains_itself_and_offers_the_fix():
    """The honesty rule: never a dead control."""
    with mock.patch.object(ex, "claude_exe", lambda: ""):
        info = ex.available()
    assert info["available"] is False
    assert info["reason"].strip()
    assert info.get("install")


# --- end to end against a stub CLI -----------------------------------------

@pytest.mark.asyncio
async def test_a_run_streams_translated_events_and_records_the_cost(tmp_path):
    """Drive the real subprocess path with a stub that speaks the CLI's wire
    format, so the parsing is exercised without spending money or needing auth."""
    stub = tmp_path / "claude"
    events = [
        {"type": "system", "subtype": "init", "session_id": "s1",
         "model": "m", "tools": ["Read"], "claude_code_version": "9.9"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}},
        {"type": "result", "subtype": "success", "result": "working",
         "total_cost_usd": 0.25, "num_turns": 2, "permission_denials": []},
    ]
    body = "\n".join(f"echo '{json.dumps(e)}'" for e in events)
    stub.write_text(f"#!/bin/sh\n{body}\n")
    stub.chmod(0o755)

    seen: list[dict] = []

    async def emit(ev):
        seen.append(ev)

    with mock.patch.object(ex, "claude_exe", lambda: str(stub)):
        run = await ex.run_task("hi", ex.Envelope(workspace=str(tmp_path / "ws")), emit)

    kinds = [e["type"] for e in seen]
    assert "text_delta" in kinds
    assert "".join(e.get("text", "") for e in seen).find("working") != -1
    assert run.session_id == "s1"
    assert run.cost_usd == 0.25 and run.turns == 2
    assert "error" not in kinds
    assert (tmp_path / "ws").is_dir(), "the workspace is created rather than failing the run"


@pytest.mark.asyncio
async def test_non_json_chatter_on_stdout_is_ignored(tmp_path):
    """The CLI also prints things that aren't ours; one stray line must not kill
    an otherwise good run."""
    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\n"
                    "echo 'npm notice: a new version is available'\n"
                    f"echo '{json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'ok'}]}})}'\n")
    stub.chmod(0o755)

    seen: list[dict] = []
    with mock.patch.object(ex, "claude_exe", lambda: str(stub)):
        await ex.run_task("hi", ex.Envelope(workspace=str(tmp_path / "ws")),
                          lambda ev: asyncio.sleep(0, result=seen.append(ev)))
    assert [e["type"] for e in seen] == ["text_delta"]


@pytest.mark.asyncio
async def test_a_whole_app_on_one_stream_line_does_not_kill_the_run(tmp_path):
    """One `stream-json` line carries a whole tool payload — the 44KB app file
    the executor just wrote, read back to check its own work. asyncio's default
    64KiB line limit made that raise "Separator is found, but chunk is longer
    than limit", which failed a build whose app was already finished on disk."""
    big = "<div>" + ("x" * 200_000) + "</div>"          # comfortably past 64KiB
    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\ncat <<'EOF'\n" + "\n".join([
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Write",
             "input": {"file_path": "/w/app.html", "content": big}}]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big}]}}),
        json.dumps({"type": "result", "subtype": "success", "result": "done",
                    "total_cost_usd": 1.5, "num_turns": 4}),
    ]) + "\nEOF\n")
    stub.chmod(0o755)

    seen: list[dict] = []

    async def emit(ev):
        seen.append(ev)

    with mock.patch.object(ex, "claude_exe", lambda: str(stub)):
        run = await ex.run_task("hi", ex.Envelope(workspace=str(tmp_path / "ws")), emit)

    kinds = [e["type"] for e in seen]
    assert "tool_start" in kinds and "tool_end" in kinds
    assert run.cost_usd == 1.5 and run.turns == 4        # the run reached its own end
    assert not run.dropped
    assert [e for e in seen if e["type"] == "error"] == []


@pytest.mark.asyncio
async def test_a_silent_executor_is_stopped_instead_of_hanging_forever(tmp_path, monkeypatch):
    """A CLI that never prints — wedged before sign-in, a pre-model network stall —
    used to block `readline()` forever: the turn froze at "working 0s" and every
    later message in that conversation queued behind a turn that would never end.
    The startup deadline turns that into an honest error and lets the process go.
    The outer `wait_for` here is the assertion itself — run_task must RETURN."""
    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\nsleep 30\n")             # produces nothing at all
    stub.chmod(0o755)
    monkeypatch.setattr(ex, "STARTUP_TIMEOUT", 0.4)

    seen: list[dict] = []

    async def emit(ev):
        seen.append(ev)

    with mock.patch.object(ex, "claude_exe", lambda: str(stub)):
        run = await asyncio.wait_for(
            ex.run_task("hi", ex.Envelope(workspace=str(tmp_path / "ws")), emit),
            timeout=10)

    assert run.reported_error, "a stalled start must be reported, not swallowed"
    errs = [e for e in seen if e["type"] == "error"]
    assert errs and "no output" in errs[0]["message"], seen
    assert "sign in" in errs[0]["message"], "the error must say the likely fix"


@pytest.mark.asyncio
async def test_a_slow_first_line_is_not_mistaken_for_a_stall(tmp_path, monkeypatch):
    """The deadline bounds ONLY the wait for the first byte. A CLI that is slow to
    start but then talks must run to completion — the watchdog must not clip it."""
    stub = tmp_path / "claude"
    ok = json.dumps({"type": "assistant",
                     "message": {"content": [{"type": "text", "text": "hello"}]}})
    result = json.dumps({"type": "result", "subtype": "success", "result": "hello",
                         "total_cost_usd": 0.1, "num_turns": 1})
    # A pause shorter than the deadline, then output — the healthy slow-start case.
    stub.write_text(f"#!/bin/sh\nsleep 0.2\necho '{ok}'\necho '{result}'\n")
    stub.chmod(0o755)
    monkeypatch.setattr(ex, "STARTUP_TIMEOUT", 1.0)

    seen: list[dict] = []

    async def emit(ev):
        seen.append(ev)

    with mock.patch.object(ex, "claude_exe", lambda: str(stub)):
        run = await ex.run_task("hi", ex.Envelope(workspace=str(tmp_path / "ws")), emit)

    assert not run.reported_error
    assert [e for e in seen if e["type"] == "error"] == []
    assert "hello" in "".join(e.get("text", "") for e in seen)


@pytest.mark.asyncio
async def test_a_line_past_even_that_ceiling_costs_one_event_not_the_run(tmp_path):
    """There is always a bigger line. Dropping the event keeps the run alive —
    the executor carries on regardless of what we manage to read."""
    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\ncat <<'EOF'\n" + "\n".join([
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "z" * 4000}]}}),
        json.dumps({"type": "result", "subtype": "success", "result": "done",
                    "total_cost_usd": 0.2, "num_turns": 1}),
    ]) + "\nEOF\n")
    stub.chmod(0o755)

    seen: list[dict] = []

    async def emit(ev):
        seen.append(ev)

    # squeeze the ceiling so the first line cannot fit but the last one can
    with mock.patch.object(ex, "claude_exe", lambda: str(stub)), \
            mock.patch.object(ex, "STREAM_LINE_LIMIT", 1024):
        run = await ex.run_task("hi", ex.Envelope(workspace=str(tmp_path / "ws")), emit)

    assert run.dropped == 1
    assert any(e["type"] == "error" and "still running" in e["message"] for e in seen)
    assert run.cost_usd == 0.2, "the events after the oversized one still arrive"


def test_a_failure_says_why_in_words_not_a_subtype(monkeypatch):
    """"the executor failed" is the message that taught us this was needed: the
    run had hit the spend ceiling the user set, and reporting it as a nameless
    failure hid the one fact that made it fixable."""
    # pinned to API billing: the wording differs on a subscription, where the
    # same stop is a work limit and nothing was actually spent
    monkeypatch.setattr(ex, "billing", lambda: {"mode": "api"})
    run = ex.Run()
    run.cost_usd = 1.11
    out = ex.translate({"type": "result", "subtype": "error_max_budget",
                        "is_error": True, "total_cost_usd": 1.11}, run)
    msg = [o for o in out if o["type"] == "error"][0]["message"]
    assert "spend ceiling" in msg and "Settings" in msg
    assert run.reported_error is True


def test_the_cli_s_own_message_is_preferred_when_it_gives_one():
    run = ex.Run()
    out = ex.translate({"type": "result", "subtype": "error", "is_error": True,
                        "result": "workspace is not writable"}, run)
    assert [o for o in out if o["type"] == "error"][0]["message"] == "workspace is not writable"


@pytest.mark.asyncio
async def test_one_failure_is_reported_once_not_twice(tmp_path):
    """The result event and the non-zero exit are the same failure seen from two
    sides; emitting both reads as two separate problems."""
    stub = tmp_path / "claude"
    bad = {"type": "result", "subtype": "error_max_budget", "is_error": True,
           "total_cost_usd": 1.0, "num_turns": 1}
    stub.write_text(f"#!/bin/sh\necho '{json.dumps(bad)}'\nexit 1\n")
    stub.chmod(0o755)

    seen: list[dict] = []

    async def emit(ev):
        seen.append(ev)

    with mock.patch.object(ex, "claude_exe", lambda: str(stub)):
        await ex.run_task("hi", ex.Envelope(workspace=str(tmp_path / "ws")), emit)

    assert len([e for e in seen if e["type"] == "error"]) == 1


# --- forwarding: the machine as a front end ---------------------------------

def test_forwarding_is_off_until_asked_for():
    assert ex.resolve_engine({}) == "aria"
    assert ex.forwarding({}) == ""


def test_a_forwarding_machine_forwards_by_default():
    cfg = {"engine": "claude-code"}
    assert ex.resolve_engine(cfg) == "claude-code"
    assert ex.forwarding(cfg) == "claude-code"


def test_an_explicit_choice_beats_the_machine_setting():
    """Picking a model in one chat is a local override, not a fight with the
    machine setting — otherwise a forwarder could never be escaped per-chat."""
    cfg = {"engine": "claude-code"}
    assert ex.resolve_engine(cfg, "ollama/qwen3.5:9b") == "aria"
    assert ex.resolve_engine(cfg, "claude-code") == "claude-code"


def test_an_unknown_engine_falls_back_to_the_built_in_agent():
    """A typo in config must not leave the machine answering with nothing."""
    assert ex.resolve_engine({"engine": "cluade-code"}) == "aria"
    assert ex.resolve_engine({"engine": None}) == "aria"


def test_the_surfaces_a_forwarder_covers_are_stated():
    """'Forward everything' has to mean more than the chat window; this is the
    list the UI promises, kept next to the code that honours it."""
    for surface in ("chat", "omnibar", "copilot", "telegram", "api", "task"):
        assert surface in ex.FORWARDED_SURFACES


@pytest.mark.asyncio
async def test_forwarding_collects_the_text_for_surfaces_with_no_stream(tmp_path):
    """Telegram, the API gate and scheduled turns have nowhere to stream to, so
    forward() has to hand back the finished text."""
    stub = tmp_path / "claude"
    ev = {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}
    stub.write_text(f"#!/bin/sh\necho '{json.dumps(ev)}'\n")
    stub.chmod(0o755)

    with mock.patch.object(ex, "claude_exe", lambda: str(stub)):
        text, run = await ex.forward("claude-code", "task", {}, str(tmp_path / "ws"))
    assert text == "done" and run is not None


def test_the_envelope_is_read_from_config_once():
    cfg = {"executors": {"claude_code": {"workspace": "/w", "tools": ["Read", "Nope"],
                                         "budget_usd": 3.0}}}
    env = ex.envelope_from(cfg, "/fallback")
    assert env.workspace == "/w" and env.tools == ("Read",) and env.budget_usd == 3.0
    assert ex.envelope_from({}, "/fallback").workspace == "/fallback"


# ---------------------------------------------- context reaching the executor

def test_copilot_context_reaches_the_delegated_run():
    """It used to be dropped: the built-in agent got extra_system, the executor
    got a bare sentence. "Make the button bigger" with no idea which button."""
    env = ex.Envelope(workspace="/tmp/ws",
                             context="App: Notes. Live app state: editing note 2").sanitized()
    cmd = ex.build_command("make the button bigger", env)
    assert "--append-system-prompt" in cmd
    assert "editing note 2" in cmd[cmd.index("--append-system-prompt") + 1]


def test_no_context_means_no_flag():
    cmd = ex.build_command("hello", ex.Envelope(workspace="/tmp/ws").sanitized())
    assert "--append-system-prompt" not in cmd


def test_context_drops_the_tool_list_the_executor_does_not_have():
    """The copilot preamble promises control_desktop/read_file/write_file, which
    only the built-in agent has. Passed through, it tells a filesystem agent to
    reach for tools that do not exist and it flails."""
    ui = ("App: Notes.\n"
          "Desktop control is available via control_desktop/desktop_state; "
          "files via search_files/read_file/write_file.")
    out = ex.context_for(ui)
    assert "control_desktop/desktop_state" not in out
    assert "App: Notes." in out, "the real context must survive"


def test_the_preamble_does_not_claim_where_apps_live():
    """AgentOS has two kinds of app and they are opposites. A blanket "apps are
    database rows" told someone asking to fix the Settings window that it needed
    App Studio — false, and App Studio cannot edit Settings either."""
    out = ex.context_for("")
    assert "no screen" in out
    assert "database" not in out.lower(), "the kind is decided per app, not here"
    assert "App Studio" not in out


def test_a_builtin_app_names_the_switch_that_would_let_it_help():
    """This is the exact failure the user hit: asked to fix the Settings theme
    dropdown, it blamed the database and pointed at App Studio."""
    note = ex.builtin_app_note("syssettings", allow_source=False)
    assert "BUILT-IN" in note
    assert "Let it work on AgentOS itself" in note, "name the switch"
    assert "not a database row" in note
    assert "Do not suggest App Studio" in note


def test_a_builtin_app_with_source_is_told_where_to_look():
    note = ex.builtin_app_note("syssettings", allow_source=True)
    assert "ui/src/js" in note and "ui/src/css" in note
    assert "ui.build" in note, "the UI is built, not edited"
    assert "never `agentos/ui/index.html`" in note


def test_context_is_capped_and_stripped():
    """It lands in a system prompt and comes from the UI."""
    env = ex.Envelope(workspace="/tmp/ws",
                             context="a" * 9000 + "\x00\x07bad").sanitized()
    assert len(env.context) <= 4096
    assert "\x00" not in env.context and "\x07" not in env.context


# ------------------------------- editing an app that is not a file on disk

class _AppStore:
    """Just enough of memory.Store to exercise checkout/commit."""

    def __init__(self, html="<h1>old</h1>"):
        self.app = {"id": "a1", "name": "Notes", "icon": "N",
                    "description": "notes", "html": html}
        self.saved = []

    def get_app(self, aid):
        return dict(self.app) if aid == "a1" else None

    def save_app(self, name, icon, description, html, note=""):
        self.saved.append({"name": name, "html": html, "note": note})
        self.app["html"] = html
        return "a1"


def test_an_app_is_checked_out_to_a_real_file(tmp_path):
    """A filesystem agent cannot touch a database row. Give it a file."""
    store = _AppStore()
    co = ex.checkout_app(store, "a1", str(tmp_path))
    from pathlib import Path
    assert Path(co["path"]).read_text() == "<h1>old</h1>"
    assert Path(co["dir"], "README.md").is_file(), "say what the file IS"
    assert str(tmp_path) in co["path"], "must land inside the allowed workspace"


def test_editing_the_file_saves_a_new_app_version(tmp_path):
    store = _AppStore()
    co = ex.checkout_app(store, "a1", str(tmp_path))
    from pathlib import Path
    Path(co["path"]).write_text("<h1>new</h1>")
    ok, msg = ex.commit_app(store, co)
    assert ok and "Notes" in msg
    assert store.saved and store.saved[0]["html"] == "<h1>new</h1>"


def test_an_untouched_app_is_not_resaved(tmp_path):
    """Every save records a version; saving an identical one is noise in the history."""
    store = _AppStore()
    co = ex.checkout_app(store, "a1", str(tmp_path))
    ok, msg = ex.commit_app(store, co)
    assert not ok and msg == "" and not store.saved


def test_an_emptied_or_deleted_app_is_refused(tmp_path):
    from pathlib import Path
    store = _AppStore()
    co = ex.checkout_app(store, "a1", str(tmp_path))
    Path(co["path"]).write_text("   ")
    ok, msg = ex.commit_app(store, co)
    assert not ok and "emptied" in msg and not store.saved

    co2 = ex.checkout_app(store, "a1", str(tmp_path))
    Path(co2["path"]).unlink()
    ok, msg = ex.commit_app(store, co2)
    assert not ok and "deleted" in msg and not store.saved


def test_a_runaway_write_does_not_become_a_database_row(tmp_path):
    from pathlib import Path
    store = _AppStore()
    co = ex.checkout_app(store, "a1", str(tmp_path))
    Path(co["path"]).write_text("x" * (ex.MAX_APP_HTML + 10))
    ok, msg = ex.commit_app(store, co)
    assert not ok and "limit" in msg and not store.saved


def test_checkout_of_an_unknown_app_is_none(tmp_path):
    assert ex.checkout_app(_AppStore(), "nope", str(tmp_path)) is None


def test_a_read_only_envelope_says_it_cannot_edit(tmp_path):
    """Never a control that lies: with no Write/Edit, say so instead of failing."""
    co = ex.checkout_app(_AppStore(), "a1", str(tmp_path))
    note = ex.app_checkout_note(co, ("Read", "Grep"))
    assert "READ-ONLY" in note and "Settings → Executors" in note
    writable = ex.app_checkout_note(co, ("Read", "Edit"))
    assert "Edit it in place" in writable


# ---------------------------------------- working on AgentOS's own source

def test_agentos_source_is_off_by_default():
    """The OS rewriting itself is its own decision, not a side effect."""
    env = ex.envelope_from({}, "/tmp/ws")
    assert env.allow_source is False
    assert ex.source_root() not in ex.build_command("x", env)


def test_enabling_it_adds_the_source_directory():
    cfg = {"executors": {"claude_code": {"allow_source": True}}}
    env = ex.envelope_from(cfg, "/tmp/ws")
    assert env.allow_source is True
    cmd = ex.build_command("fix the window manager", env)
    assert cmd.count("--add-dir") == 2 and ex.source_root() in cmd
    assert "AgentOS's own source" in env.describe(), "the envelope must say so"


def test_the_source_note_states_the_two_load_bearing_rules():
    note = ex.source_note("/src")
    assert "ui.build" in note, "the UI is built, not edited"
    assert "pytest" in note, "a change that breaks the suite is not finished"
    assert "restart" in note


# ------------------------------------------------- installing it from here

def test_a_missing_executor_offers_the_exact_command(monkeypatch):
    """'Not installed' on its own is a dead end wearing an honest sentence."""
    # `claude_exe()` scans candidates itself now (it must pick the NEWEST of
    # several installs), so "no claude" is expressed by there being none to rank.
    monkeypatch.setattr(ex, "claude_candidates", list)
    monkeypatch.setattr(ex.shutil, "which", lambda n, **k: "" if n == "claude" else "/usr/bin/npm")
    info = ex.available()
    assert info["available"] is False
    assert info["install_cmd"] and info["can_install"] is True
    assert info["install_note"] and "API key" in info["install_note"]


def test_permission_mode_follows_the_envelope():
    """A hardcoded `dontAsk` DENIED the edit: an executor granted Write and Edit
    in Settings silently could not write. Caught by a real run, not by reasoning."""
    mk = lambda tools: ex.Envelope(workspace="/tmp/ws", tools=tools).sanitized()
    assert ex.permission_mode(mk(("Read", "Grep"))) == "dontAsk"
    assert ex.permission_mode(mk(("Read", "Edit"))) == "acceptEdits"
    assert ex.permission_mode(mk(("Read", "Write"))) == "acceptEdits"
    assert ex.permission_mode(mk(("Read", "Bash"))) == "bypassPermissions"


def test_a_read_only_run_never_bypasses_permissions():
    """The default envelope must not reach the permissive mode."""
    env = ex.envelope_from({}, "/tmp/ws")
    assert ex.permission_mode(env) == "dontAsk"
    assert "bypassPermissions" not in ex.build_command("x", env)


def test_the_spend_ceiling_follows_how_the_cli_is_billed(monkeypatch):
    """A $2 ceiling on a Max plan controls no spending at all — it only stops the
    work. A real build died mid-`python -m venv` at $2.40 having cost nothing."""
    monkeypatch.setattr(ex, "billing", lambda: {"mode": "subscription"})
    assert ex.default_budget() == ex.SUBSCRIPTION_BUDGET_USD
    monkeypatch.setattr(ex, "billing", lambda: {"mode": "api"})
    assert ex.default_budget() == ex.DEFAULT_BUDGET_USD


def test_an_explicit_budget_still_wins(monkeypatch):
    monkeypatch.setattr(ex, "billing", lambda: {"mode": "subscription"})
    env = ex.envelope_from({"executors": {"claude_code": {"budget_usd": 3}}}, "/tmp/ws")
    assert env.budget_usd == 3.0


def test_hitting_the_ceiling_on_a_subscription_does_not_talk_about_money(monkeypatch):
    monkeypatch.setattr(ex, "billing", lambda: {"mode": "subscription"})
    run = ex.Run(cost_usd=2.40)
    why = ex._why({"subtype": "error_max_budget"}, run)
    assert "Nothing was billed" in why
    assert "carry on" in why, "the session resumes — do not imply the work is lost"


def test_claude_is_found_when_path_is_the_one_systemd_gives(monkeypatch, tmp_path):
    """The bug this fixes: `available()` reported "not installed" on a machine
    where Claude Code plainly was installed.

    The server is started by systemd, which does not source a login shell, so
    ~/.local/bin — where Claude Code installs itself — is absent from PATH. The
    user's terminal finds it; the service does not.
    """
    from agentos import executors

    fake_home = tmp_path / "home"
    (fake_home / ".local" / "bin").mkdir(parents=True)
    exe = fake_home / ".local" / "bin" / "claude"
    exe.write_text("#!/bin/sh\necho 9.9.9\n")
    exe.chmod(0o755)

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/bin")   # what the service gets
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(fake_home), 1) if p.startswith("~") else p)

    assert shutil.which("claude") is None, "the fixture must reproduce the failure"
    assert executors.claude_exe() == str(exe), "it is right there in ~/.local/bin"


def test_the_child_gets_a_path_it_can_work_with(monkeypatch):
    """Resolving the executable and then starving it of node/git/ripgrep would be
    the same bug one level down."""
    from agentos import executors

    monkeypatch.setenv("PATH", "/usr/bin")
    env = executors.child_env()
    assert "/usr/bin" in env["PATH"]
    assert env["PATH"] != "/usr/bin", "the child's PATH must be the extended one"


# ---------------------------------------------------------------------------
# Which binary, and what happens when it refuses
# ---------------------------------------------------------------------------

def test_the_newest_cli_wins_when_several_are_installed(tmp_path, monkeypatch):
    """Several Claude Code installs on one machine is normal, not exotic.

    A Homebrew one from last year, the official installer's in `~/.local/bin`, and
    `~/.claude/local/claude` after `claude migrate-installer`. `shutil.which` takes
    whichever directory sorts first on PATH, and when that one predates the flags
    this module builds the CLI exits on `error: unknown option '--tools'` before
    doing any work — which reached a phone as "(done — no text output)" and left the
    Soul panel waiting. The flags only ever grow, so newest is the only defensible
    pick.
    """
    old, new = tmp_path / "old", tmp_path / "new"
    for d, ver in ((old, "1.0.27"), (new, "2.1.228")):
        d.mkdir()
        exe = d / "claude"
        exe.write_text(f"#!/bin/sh\necho '{ver} (Claude Code)'\n")
        exe.chmod(0o755)

    # old FIRST, exactly as Homebrew sits ahead of ~/.local/bin
    import agentos.mcp_client as mcpc
    monkeypatch.setattr(mcpc, "_extended_path", lambda: f"{old}{os.pathsep}{new}")
    monkeypatch.setattr(ex, "EXTRA_CLAUDE_PATHS", ())   # ignore this machine's own
    assert ex.claude_exe(refresh=True) == str(new / "claude")


def test_a_cli_that_will_not_report_a_version_is_still_used(tmp_path, monkeypatch):
    """Unreadable is not absent: one odd install must not read as 'not installed'."""
    d = tmp_path / "only"
    d.mkdir()
    exe = d / "claude"
    exe.write_text("#!/bin/sh\nexit 1\n")
    exe.chmod(0o755)
    import agentos.mcp_client as mcpc
    monkeypatch.setattr(mcpc, "_extended_path", lambda: str(d))
    monkeypatch.setattr(ex, "EXTRA_CLAUDE_PATHS", ())
    assert ex.claude_exe(refresh=True) == str(exe)


def test_a_failed_run_says_why_instead_of_going_quiet():
    """Every surface turns "" into "(done — no text output)", which describes a run
    that finished with nothing to add. A run that FAILED must not be indistinguishable
    from one that succeeded quietly."""
    async def go():
        async def fake_run_task(text, env, sink, run):
            await sink({"type": "error", "message": "error: unknown option '--tools'"})

        import agentos.executors as ex
        real, ex.run_task = ex.run_task, fake_run_task
        try:
            return await ex.forward("claude-code", "hi", {"executors": {}}, "/tmp")
        finally:
            ex.run_task = real

    reply, _run = asyncio.run(go())
    assert reply.startswith("[error]")
    assert "--tools" in reply


def test_text_still_wins_over_a_late_error():
    """A denial note is appended as text alongside an error event; the words the
    executor actually produced are the answer."""
    async def go():
        async def fake_run_task(text, env, sink, run):
            await sink({"type": "text_delta", "text": "here is your answer"})
            await sink({"type": "error", "message": "budget exceeded"})

        import agentos.executors as ex
        real, ex.run_task = ex.run_task, fake_run_task
        try:
            return await ex.forward("claude-code", "hi", {"executors": {}}, "/tmp")
        finally:
            ex.run_task = real

    reply, _run = asyncio.run(go())
    assert reply == "here is your answer"
