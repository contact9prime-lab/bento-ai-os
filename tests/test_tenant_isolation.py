"""Accounts are a boundary against each other's DATA through the agent's tools.

This is the enforcement layer of docs/design/tenant-isolation.md: on a machine
with accounts, a tool may not read or write another account's home — through the
in-process file tools OR through the shell — and if the shell cannot be jailed at
all, it is refused rather than run unconfined. A single-user machine has no second
tenant and is left exactly as it was.

Full defeat of a user with root or physical access is a deployment concern (see
the design doc); this defends the surface AgentOS itself exposes: its tools.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod                                # noqa: E402
from agentos import tools as toolsmod                               # noqa: E402
from agentos import users as usersmod                               # noqa: E402


@pytest.fixture()
def two(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    usersmod.reset_caches()
    usersmod.set_current("")
    ada = usersmod.create("ada", "hunter2hunter")["id"]
    bob = usersmod.create("bob", "hunter2hunter", role="executor")["id"]
    (usersmod.home_for(ada) / "secret.txt").write_text("ada's private data")
    yield ada, bob
    usersmod.reset_caches()
    usersmod.set_current("")


def _box(cfg, uid):
    return toolsmod.Toolbox(cfg, usersmod.store_for(uid))


def run(coro):
    # A fresh loop per call: other test files close the shared loop, and a closed
    # loop leaves these coroutines un-awaited (and the assertions meaningless).
    return asyncio.new_event_loop().run_until_complete(coro)


def _cfg(sandbox: bool):
    c = cfgmod.load_config()
    c["sandbox"] = {"enabled": sandbox, "root": ""}
    return c


# ---------------------------------------------------------------------------
# The in-process file tools honour the boundary — with the sandbox on OR off
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sandbox", [True, False])
def test_a_tool_cannot_read_another_accounts_file(two, sandbox):
    ada, bob = two
    tb = _box(_cfg(sandbox), bob)
    with usersmod.as_user(bob):
        out = run(tb.read_file(str(usersmod.home_for(ada) / "secret.txt")))
    assert "another account" in out and "private data" not in out


@pytest.mark.parametrize("sandbox", [True, False])
def test_a_tool_cannot_write_into_another_accounts_home(two, sandbox):
    ada, bob = two
    tb = _box(_cfg(sandbox), bob)
    with usersmod.as_user(bob):
        out = run(tb.write_file(str(usersmod.home_for(ada) / "planted.txt"), "x"))
    assert "another account" in out
    assert not (usersmod.home_for(ada) / "planted.txt").exists()


def test_a_tool_cannot_list_another_accounts_home(two):
    ada, bob = two
    tb = _box(_cfg(False), bob)
    with usersmod.as_user(bob):
        out = run(tb.list_dir(str(usersmod.home_for(ada))))
    assert "another account" in out


def test_the_boundary_holds_even_with_the_sandbox_toggle_off(two):
    """The sandbox jails the SHELL; cross-tenant reads through the in-process file
    tools are a separate boundary that must hold with the sandbox off, which is
    exactly when the old workspace-confinement did nothing."""
    ada, bob = two
    tb = _box(_cfg(False), bob)
    with usersmod.as_user(bob):
        assert "another account" in run(tb.read_file(str(usersmod.home_for(ada) / "secret.txt")))


# ---------------------------------------------------------------------------
# The shell: jailed to the account's home, or refused
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not toolsmod.sandbox_mechanism(), reason="needs a jail mechanism (bwrap)")
def test_the_shell_cannot_see_another_accounts_home(two):
    ada, bob = two
    tb = _box(_cfg(True), bob)
    with usersmod.as_user(bob):
        out = run(tb.run_command(f"cat {usersmod.home_for(ada) / 'secret.txt'} 2>&1 || echo BLOCKED"))
    assert "private data" not in out
    assert "No such file" in out or "BLOCKED" in out


@pytest.mark.skipif(not toolsmod.sandbox_mechanism(), reason="needs a jail mechanism (bwrap)")
def test_the_shell_runs_in_the_accounts_own_home(two):
    _, bob = two
    tb = _box(_cfg(True), bob)
    with usersmod.as_user(bob):
        out = run(tb.run_command("pwd"))
    assert bob in out


def test_the_shell_fails_closed_when_no_jail_is_available(two, monkeypatch):
    """No jail cannot mean no walls: a shell that could read /home/.agentos/users/
    <somebody-else> is the whole isolation gone."""
    monkeypatch.setattr(toolsmod, "sandbox_mechanism", lambda: "")
    _, bob = two
    tb = _box(_cfg(True), bob)
    with usersmod.as_user(bob):
        out = run(tb.run_command("echo TENANTMARKER"))
    assert "per-account jail" in out and "TENANTMARKER" not in out


# ---------------------------------------------------------------------------
# A single-user machine is untouched
# ---------------------------------------------------------------------------

def test_a_single_user_machine_keeps_reading_across_the_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    usersmod.reset_caches()
    usersmod.set_current("")
    f = tmp_path / "anywhere.txt"
    f.write_text("ordinary file")
    tb = _box(_cfg(False), "")
    assert "ordinary file" in run(tb.read_file(str(f)))
    usersmod.reset_caches()
