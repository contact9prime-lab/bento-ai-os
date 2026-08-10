"""`bento setup` — the same arc, in a terminal.

The claim these defend is that this is not a second wizard. It reads the same
catalogue and the same probe, so the only things worth testing are the ones that
would let the two drift: a step with nothing behind it here, a tick that means
something different, and the handover when the account step changes who this
session is half way through.
"""

import builtins
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod                                # noqa: E402
from agentos import onboarding as ob                                # noqa: E402
from agentos import setup_tui                                       # noqa: E402
from agentos import users as usersmod                               # noqa: E402
from agentos.memory import Store                                    # noqa: E402


@pytest.fixture()
def machine(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    usersmod.reset_caches()
    usersmod.set_current("")
    yield cfgmod.load_config(), Store(tmp_path / "agentos.db")
    usersmod.reset_caches()
    usersmod.set_current("")


def drive(monkeypatch, answers, passwords=()):
    """Type these, in order. Anything asked for beyond the script answers empty,
    which every prompt treats as "leave it" — so a test cannot hang."""
    it, pw = iter(answers), iter(passwords)
    monkeypatch.setattr(builtins, "input", lambda *_a: next(it, ""))
    monkeypatch.setattr(setup_tui.getpass, "getpass", lambda *_a: next(pw, ""))


# ---------------------------------------------------------------------------
# One arc, two faces
# ---------------------------------------------------------------------------

def test_every_step_in_the_catalogue_can_be_done_from_a_terminal():
    """A step with nothing behind it here is exactly the silent gap the
    three-faces rule exists to prevent — it would be discovered by somebody on a
    headless machine, which is the one place the whole arc matters most."""
    assert {s.id for s in ob.STEPS} == set(setup_tui.HANDLERS)


def test_the_rail_shows_what_the_server_shows(machine, capsys):
    cfg, store = machine
    setup_tui._draw(ob.state(cfg, store), "Aria")
    out = capsys.readouterr().out
    for s in ob.STEPS:
        assert s.title in out
    assert f"0 of {len(ob.STEPS)} done" in out


def test_a_finished_step_reads_as_finished_in_both(machine, capsys):
    """Same probe, so a machine set up half way in the browser opens here with the
    right steps already green."""
    cfg, store = machine
    cfg["agent_name"] = "Bento"
    setup_tui._draw(ob.state(cfg, store), "Bento")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "Name your agent" in ln]
    assert lines and lines[0].strip().startswith("✓")


def test_a_blocked_step_says_what_it_is_waiting_for(machine, capsys):
    cfg, store = machine
    setup_tui._draw(ob.state(cfg, store), "Aria")
    line = next(ln for ln in capsys.readouterr().out.splitlines()
                if "Give the specialist a mission" in ln)
    assert "needs agent" in line


# ---------------------------------------------------------------------------
# Doing things
# ---------------------------------------------------------------------------

def test_naming_it_writes_the_name(machine, monkeypatch):
    cfg, store = machine
    drive(monkeypatch, ["1", "Bento", "q"])
    setup_tui.run(cfg, store)
    assert cfgmod.load_config()["agent_name"] == "Bento"


def test_building_the_agent_creates_the_same_one_the_wizard_does(machine, monkeypatch):
    cfg, store = machine
    cfg["default_model"] = "ollama/x"
    drive(monkeypatch, ["4", "y", "q"])
    setup_tui.run(cfg, store)
    assert store.get_subagent(ob.STARTER_AGENT["name"])


def test_the_flow_step_refuses_before_there_is_an_agent(machine, monkeypatch, capsys):
    """Not a dead end with a confusing error — the rail blocks it and the handler
    says why if somebody types the number anyway."""
    cfg, store = machine
    setup_tui._step_flow(cfg, store)
    assert "build an agent first" in capsys.readouterr().out


def test_skipping_is_remembered_and_offered_again(machine, monkeypatch):
    cfg, store = machine
    drive(monkeypatch, ["s7", "q"])
    setup_tui.run(cfg, store)
    assert cfgmod.load_config()["onboarding"]["skipped"] == ["channel"]
    drive(monkeypatch, ["q"])
    cfg2 = cfgmod.load_config()
    ob.restart(cfg2)
    setup_tui.run(cfg2, store)
    assert cfgmod.load_config()["onboarding"]["skipped"] == []


def test_a_required_step_cannot_be_skipped_here_either(machine, monkeypatch, capsys):
    cfg, store = machine
    drive(monkeypatch, ["s2", "q"])
    setup_tui.run(cfg, store)
    assert "cannot work without" in capsys.readouterr().out


def test_finishing_writes_it_down(machine, monkeypatch):
    cfg, store = machine
    drive(monkeypatch, ["q"])
    setup_tui.run(cfg, store)
    assert cfgmod.load_config()["setup_complete"] is True


def test_nonsense_is_answered_rather_than_crashed_on(machine, monkeypatch, capsys):
    cfg, store = machine
    drive(monkeypatch, ["banana", "99", "q"])
    setup_tui.run(cfg, store)
    assert "a step number" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The account step, which changes who this session is
# ---------------------------------------------------------------------------

def test_creating_the_first_account_from_a_terminal(machine, monkeypatch):
    cfg, store = machine
    drive(monkeypatch, ["9", "ada", "Ada Lovelace", "q"], ["hunter2hunter"])
    setup_tui.run(cfg, store)
    assert [u["name"] for u in usersmod.list_users()] == ["ada"]
    assert usersmod.check_password(usersmod.by_name("ada")["id"], "hunter2hunter")


def test_the_rest_of_the_session_belongs_to_the_account_just_made(machine, monkeypatch):
    """Without the handover the next save writes the whole config — agent name,
    channels, theme — back into the MACHINE file that `adopt` just stripped, and
    hands it to the next person who signs up."""
    cfg, store = machine
    drive(monkeypatch, ["1", "Bento", "9", "ada", "Ada", "s7", "q"], ["hunter2hunter"])
    setup_tui.run(cfg, store)
    import json
    raw = json.loads(cfgmod.CONFIG_PATH.read_text())
    assert "agent_name" not in raw and "onboarding" not in raw
    uid = usersmod.by_name("ada")["id"]
    own = json.loads(usersmod.cfg_path_for(uid).read_text())
    assert own["agent_name"] == "Bento"
    assert own["onboarding"]["skipped"] == ["channel"]
    assert own["setup_complete"] is True


def test_the_account_step_ticks_once_somebody_exists(machine, monkeypatch):
    cfg, store = machine
    drive(monkeypatch, ["9", "ada", "Ada", "q"], ["hunter2hunter"])
    setup_tui.run(cfg, store)
    st = {s["id"]: s for s in ob.state(cfgmod.load_config(), store)["steps"]}
    assert st["account"]["status"] == "done" and st["account"]["detail"] == "ada"


def test_a_bad_username_is_refused_with_the_reason(machine, monkeypatch, capsys):
    cfg, store = machine
    drive(monkeypatch, ["9", "Ada Lovelace!", "q"], ["hunter2hunter"])
    setup_tui.run(cfg, store)
    assert "lowercase letters" in capsys.readouterr().out
    assert usersmod.list_users() == []


def test_leaving_the_username_blank_keeps_it_single_user(machine, monkeypatch):
    """A machine that stays single-user is a finished machine, and the step must
    not be a trap that turns accounts on because somebody pressed Enter."""
    cfg, store = machine
    drive(monkeypatch, ["9", "", "q"])
    setup_tui.run(cfg, store)
    assert usersmod.enabled() is False


def test_the_second_account_is_an_executor_unless_asked_otherwise(machine, monkeypatch):
    cfg, store = machine
    drive(monkeypatch, ["9", "ada", "Ada", "q"], ["hunter2hunter"])
    setup_tui.run(cfg, store)
    usersmod.set_current("")
    drive(monkeypatch, ["9", "bob", "Bob", "executor", "q"], ["hunter2hunter"])
    setup_tui.run(cfgmod.load_config(), store)
    assert usersmod.by_name("bob")["role"] == "executor"
