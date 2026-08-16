"""Which brains this machine can answer with, and what it may claim about them.

`available()` reported on Claude Code and only Claude Code, because for a long
time it was the only executor. That shape leaked: every surface that wanted to
know "what can answer here" either hardcoded the name or asked a boolean, so a
second executor meant editing each of them. `roster()` is the list, and the tests
that matter here are the ones about honesty rather than the ones about plumbing.

Hermes is back as an EXECUTOR and that is not the gateway that was removed: it
answers this OS's turns, through this PDP, into this ledger — the bar the carrier
failed. `tests/test_channels.py` still asserts the carrier surface is gone.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import components as comps                    # noqa: E402
from agentos import config as cfgmod                       # noqa: E402
from agentos import executors as execmod                   # noqa: E402


def test_the_roster_lists_every_engine_installed_or_not():
    """A missing executor is REPORTED, never omitted. Hidden reads as 'this OS
    cannot', when the truth is 'you do not have it yet'."""
    ids = [r["id"] for r in execmod.roster()]
    assert set(ids) == set(execmod.ENGINES), ids


def test_a_missing_executor_says_why():
    for r in execmod.roster():
        if not r["installed"]:
            assert r["why_not"], f"{r['id']} is missing and does not say so"


def test_the_builtin_agent_is_always_available():
    """Aria needs nothing installed; a machine that could not answer at all would
    have no fallback for every other failure in this file."""
    aria = execmod.probe("aria")
    assert aria["installed"] and aria["builtin"]


def test_an_unknown_executor_is_refused_rather_than_invented():
    assert execmod.probe("not-a-real-engine")["installed"] is False


# ------------------------------------------------- what may be claimed

def test_every_installable_executor_states_a_licence_and_a_real_command():
    """Nothing installs without the licence and the exact command in view — the
    rule the whole components catalogue exists to keep."""
    by_id = {c["id"]: c for c in comps.catalog()}
    for eid in ("claude-code", "hermes"):
        assert eid in by_id, f"{eid} is offered as an engine but cannot be installed"
        assert by_id[eid]["licence"], f"{eid} has no licence to show"
        assert by_id[eid]["command"], f"{eid} shows no command"


def test_an_executor_with_no_truthful_installer_offers_none():
    """OpenClaw is used if present and never installed by a guess. A fabricated
    command is a dead button, which is the one thing every honesty rule forbids."""
    assert "openclaw" not in {c["id"] for c in comps.catalog()}
    info = execmod.probe("openclaw")
    if not info["installed"]:
        assert not info["install_cmd"] and not info["repo"]
        assert "does not ship an installer" in info["why_not"]


def test_a_user_scoped_installer_is_not_shown_with_sudo():
    """These install into the user's own account. `sudo` on the shown command —
    the one people copy — installs them for root instead."""
    for c in comps.catalog():
        if c["id"] in ("claude-code", "hermes") and c["command"]:
            assert not c["command"].startswith("sudo "), c["command"]


# ------------------------------------------------- the setting vs the binary

def test_an_engine_that_is_not_installed_falls_back(monkeypatch):
    """The setting outlives the binary in more ways than a load-time migration
    can catch. A machine answering with nothing fails on every surface at once."""
    monkeypatch.setattr(execmod, "probe", lambda eid: {"installed": False})
    assert execmod.resolve_engine({"engine": "hermes"}) == "aria"
    assert execmod.resolve_engine({"engine": "claude-code"}) == "aria"


def test_an_installed_engine_is_honoured(monkeypatch):
    monkeypatch.setattr(execmod, "probe", lambda eid: {"installed": True})
    assert execmod.resolve_engine({"engine": "hermes"}) == "hermes"


def test_a_per_turn_model_still_means_the_builtin_agent(monkeypatch):
    """Picking a model in one chat is a local override, not a fight with the
    machine setting — and a model id is never an engine."""
    monkeypatch.setattr(execmod, "probe", lambda eid: {"installed": True})
    assert execmod.resolve_engine({"engine": "hermes"}, "ollama/qwen3") == "aria"


def test_the_two_engine_lists_agree():
    """Two copies, because importing one from the other would be a cycle."""
    assert set(cfgmod.ENGINE_NAMES) == set(execmod.ENGINES)
