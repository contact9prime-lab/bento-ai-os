"""The self-update gate refuses REGRESSIONS, not a fragile machine.

`bento update` verifies the pulled code by running the test suite and rolling
back if it fails. The blunt version of that — "any failing test rolls back" —
bricked updates for a reason the update never caused: pytest's temp directory
resolves under a system directory on a Mac, so `test_safe_folders` failed there,
so the Mac could never self-update. A cloud-provider test with no network, or a
browser test with no browser, would do the same.

So the gate is regression-only: it refuses the update only when a test that
PASSED on the previous version FAILS on the new one. A test already red on this
machine is an environment fact, not the update's fault.

Driven against real git repositories with a real (tiny) pytest suite, because
the thing being tested is precisely "run the suite on new code, then on old, and
compare" — a mock of the runner would prove nothing.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import updates as upd                         # noqa: E402


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)


def write_suite(root: Path, body: str):
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_thing.py").write_text(body)


PASS = "def test_it():\n    assert 1 + 1 == 2\n"
FAIL = "def test_it():\n    assert 1 + 1 == 3\n"


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A remote on master and a clone tracking it, both a valid 'checkout' as far
    as updates.py is concerned. `_python` is pointed at the venv running these
    tests so the child pytest actually has pytest."""
    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-q", "-b", "master")
    git(remote, "config", "user.email", "t@example.com")
    git(remote, "config", "user.name", "T")
    (remote / "agentos").mkdir()
    (remote / "agentos" / "VERSION").write_text("0.0.1\n")
    write_suite(remote, PASS)
    git(remote, "add", ".")
    git(remote, "commit", "-qm", "base, green")

    local = tmp_path / "local"
    git(tmp_path, "clone", "-q", str(remote), str(local))
    git(local, "config", "user.email", "t@example.com")
    git(local, "config", "user.name", "T")

    monkeypatch.setattr(upd, "install_dir", lambda: local)
    monkeypatch.setattr(upd, "_python", lambda root: sys.executable)
    return remote, local


def cfg():
    return {"updates": {"enabled": True, "branch": "master"}}


async def apply(msgs=None):
    log = msgs.append if msgs is not None else None
    return await upd.apply(cfg(), run_tests=True, log=log)


def head(root):
    return git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.mark.asyncio
async def test_a_clean_update_applies(repo):
    remote, local = repo
    write_suite(remote, PASS)
    (remote / "feature.txt").write_text("x")
    git(remote, "add", "."); git(remote, "commit", "-qm", "still green")
    before = head(local)
    res = await apply()
    assert res["ok"] is True, res
    assert head(local) != before               # it actually moved


@pytest.mark.asyncio
async def test_a_real_regression_is_refused_and_rolled_back(repo):
    """The update turns a passing test red — this is exactly what the gate is
    for, and it must roll back."""
    remote, local = repo
    write_suite(remote, FAIL)                   # the update breaks the test
    git(remote, "add", "."); git(remote, "commit", "-qm", "oops, broke it")
    before = head(local)
    res = await apply()
    assert res["ok"] is False and res.get("rolled_back")
    assert "passing tests red" in res["error"]
    assert head(local) == before               # nothing changed


@pytest.mark.asyncio
async def test_a_preexisting_failure_does_not_block_the_update(repo):
    """The reported bug, generalised: a test ALREADY failing on this machine —
    red before the update AND after — must not strand the machine on old code.
    That is `test_safe_folders` on a Mac, or a cloud-provider test with no
    network: the update did not cause it, so it must not refuse the update.

    Built as ONE upstream history so the clone fast-forwards cleanly: the test
    is red at the point the clone sits, and the update is an unrelated commit
    that leaves it red."""
    remote, local = repo
    # Make the test red UPSTREAM first, and re-clone the local from that point so
    # the red test is the shared base — exactly a machine whose current version
    # already fails a test.
    write_suite(remote, FAIL)
    git(remote, "add", "."); git(remote, "commit", "-qm", "red is the base here")
    git(local, "fetch", "-q", "origin"); git(local, "reset", "-q", "--hard", "origin/master")
    # the update: an unrelated change, test stays exactly as red
    (remote / "unrelated.txt").write_text("y")
    git(remote, "add", "."); git(remote, "commit", "-qm", "unrelated change, test still red")
    before = head(local)
    msgs = []
    res = await apply(msgs)
    assert res["ok"] is True, (res, msgs)                     # not blocked
    assert head(local) != before                             # it applied
    assert any("failed on the previous version too" in m for m in msgs), msgs


@pytest.mark.asyncio
async def test_a_new_test_that_fails_here_is_not_counted_as_a_regression(repo):
    """A test file the update ADDS never passed before the update, so a failure
    in it is new behaviour the dev CI already vetted — not a regression that
    should strand this machine."""
    remote, local = repo
    (remote / "tests" / "test_new.py").write_text(FAIL)   # brand-new failing file
    git(remote, "add", "."); git(remote, "commit", "-qm", "add a test that fails here")
    before = head(local)
    msgs = []
    res = await apply(msgs)
    assert res["ok"] is True, res
    assert head(local) != before
    assert any("new to this update" in m for m in msgs), msgs


def test_the_verify_interpreter_is_found_on_every_platform(tmp_path, monkeypatch):
    """`_python` looked only under `.venv/bin`, so on Windows (Scripts\\python.exe)
    it fell through to `python3` — not a command on a default Windows box — and
    the whole verify gate could never launch. It must resolve the venv on the
    right platform and otherwise fall back to the running interpreter, which is
    guaranteed to exist and to have pytest."""
    import os
    import sys
    # no .venv on disk → the fallback must be a real interpreter, not "python3"
    assert upd._python(tmp_path) == sys.executable

    # a POSIX-layout venv is found on POSIX
    if os.name != "nt":
        (tmp_path / ".venv" / "bin").mkdir(parents=True)
        (tmp_path / ".venv" / "bin" / "python").write_text("")
        assert upd._python(tmp_path).endswith("/.venv/bin/python")
