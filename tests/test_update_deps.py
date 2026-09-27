"""The dependencies step of an update, on the machine it actually runs on.

Reported from the desktop's Update button on a Mac: "dependencies could not be
installed: …/.venv/bin/python: No module named pip — rolled back". Three attempts were
made and only the LAST one's reason was shown: `uv sync` (twice) and then `python -m
pip`. The venv was made by uv, which does not put pip in it, so the last attempt could
never work there. And uv itself was not found: the server behind the desktop was
started at login, and that PATH does not include ~/.local/bin, where uv installs
itself. The fix finds uv where it lives, falls back to things that work in a uv venv,
and says what EVERY attempt said.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import updates as up                                  # noqa: E402


def _checkout(tmp_path):
    r = tmp_path / "repo"
    (r / "agentos").mkdir(parents=True)
    (r / "agentos" / "VERSION").write_text("0.1.0\n")
    (r / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n')
    for a in (["init", "-q", "-b", "master"], ["config", "user.email", "t@t"],
              ["config", "user.name", "t"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *a], cwd=r, check=True)
    # what `uv venv` makes: an interpreter with NO pip in it
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(r / ".venv")], check=True)
    return r


@pytest.fixture()
def machine(tmp_path, monkeypatch):
    """A checkout, a home with no uv in it, and a PATH a login service would have."""
    r = _checkout(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(up, "install_dir", lambda: r)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    real = up._run

    def run(args, cwd=None, timeout=60, env=None):
        if args[:2] == ["git", "fetch"]:
            return True, ""
        if args[:2] == ["git", "merge"]:     # the pull: a new version that changes deps
            (r / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.2.0"\n')
            subprocess.run(["git", "commit", "-aqm", "v0.2"], cwd=r, check=True)
            return True, ""
        if args[1:3] == ["-m", "agentos"]:   # the migrate step: not what is tested here
            return True, ""
        return real(args, cwd, timeout, env)
    monkeypatch.setattr(up, "_run", run)
    return r, home


def _pip_install(monkeypatch, ok, said=""):
    """The network half — `pip install -e .` — stood in for; `pip --version` and
    `ensurepip` stay real, because that is where a uv venv differs."""
    inner = up._run

    def run(args, cwd=None, timeout=60, env=None):
        if args[1:4] == ["-m", "pip", "install"]:
            return ok, said
        return inner(args, cwd, timeout, env)
    monkeypatch.setattr(up, "_run", run)


def test_a_uv_venv_with_no_uv_around_still_gets_its_dependencies(machine, monkeypatch):
    """No uv anywhere and no pip in the venv: ensurepip gives it one, from the
    interpreter's own bundle, and the install goes ahead."""
    r, home = machine
    _pip_install(monkeypatch, True)
    res = asyncio.run(up.apply({}, run_tests=False))
    assert res["ok"], res
    ok, _ = up._run([str(r / ".venv" / "bin" / "python"), "-m", "pip", "--version"])
    assert ok, "the venv now has pip"


def test_a_failure_says_what_every_attempt_said(machine, monkeypatch):
    r, home = machine
    _pip_install(monkeypatch, False, "ERROR: Could not find a version that satisfies httpx>=9")
    res = asyncio.run(up.apply({}, run_tests=False))
    assert res["ok"] is False and res.get("rolled_back")
    err = res["error"]
    # the reason that matters is FIRST, in words, with the fix and where it looked
    assert "uv was not found" in err and ".local/bin" in err and "astral.sh/uv" in err, err
    assert "satisfies httpx>=9" in err, "and what pip said, not only the last attempt"
    assert err.index("uv was not found") < err.index("pip install")
    assert "rolled back" in err


def test_uv_is_found_where_it_installs_itself(machine):
    """~/.local/bin is where uv's installer puts it; a login service's PATH lacks it."""
    r, home = machine
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    log = home / "uv.log"
    uv = bindir / "uv"
    uv.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nexit 0\n")
    uv.chmod(0o755)
    res = asyncio.run(up.apply({}, run_tests=False))
    assert res["ok"], res
    assert log.read_text().splitlines()[0] == "sync --frozen", "the lockfile, exactly"
