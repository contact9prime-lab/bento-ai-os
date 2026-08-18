""""Up to date" has to mean the code, not a file somebody remembers to edit.

The reported bug: pushed commit after commit, and both `bento update` and the
About panel kept saying 0.2.0 · up to date. They were telling the truth about
`agentos/VERSION` — a hand-written file that only moves at a release — and saying
nothing about the twenty commits waiting on the branch the machine tracks. Git
knew all along; nothing asked it.

So the check now has two sources: the published version file (the only thing a
pip install can compare against) and the checkout's own git (the only thing that
knows about commits between releases). Either may say "there is something newer".

These run against real git repositories — a remote and a clone — because that is
the thing that was wrong, and a mock of `git rev-list` would have agreed with the
broken version too.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import updates as upd                         # noqa: E402


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def clone(tmp_path, monkeypatch):
    """A published 'remote' on branch master, and a clone that tracks it."""
    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-q", "-b", "master")
    git(remote, "config", "user.email", "t@example.com")
    git(remote, "config", "user.name", "Tester")
    (remote / "agentos").mkdir()
    (remote / "agentos" / "VERSION").write_text(upd.current() + "\n")
    git(remote, "add", ".")
    git(remote, "commit", "-qm", "first release")

    local = tmp_path / "local"
    git(tmp_path, "clone", "-q", str(remote), str(local))
    git(local, "config", "user.email", "t@example.com")
    git(local, "config", "user.name", "Tester")

    monkeypatch.setattr(upd, "install_dir", lambda: local)

    # The published release notes are a second network call and not what these are
    # about; the version half is stubbed per test in run_check().
    async def notes(branch):
        return ""

    monkeypatch.setattr(upd, "_notes", notes)
    return remote, local


def push(remote, n=1, prefix="change"):
    for i in range(n):
        # the prefix is in the FILENAME too: a second push writing the same bytes
        # to the same path is not a commit, and the failure reads as a git bug
        (remote / f"{prefix}-{i}.txt").write_text(f"{prefix}{i}")
        git(remote, "add", ".")
        git(remote, "commit", "-qm", f"{prefix} {i}")


def cfg():
    return {"updates": {"enabled": True, "branch": "master"}}


# --- git's half, on its own -------------------------------------------------

def test_a_checkout_that_is_behind_says_how_far_and_which_commits(clone):
    remote, local = clone
    push(remote, 3)
    g = upd.git_state(cfg())
    assert g["behind"] == 3, g
    assert [c["title"] for c in g["commits"]] == ["change 2", "change 1", "change 0"]
    assert g["on_branch"] == "master" and g["tracks"] == "master"
    assert not g["error"]


def test_a_checkout_that_is_level_is_level(clone):
    g = upd.git_state(cfg())
    assert g["behind"] == 0 and g["ahead"] == 0 and g["commits"] == []


def test_your_own_unpushed_commits_are_reported_as_ahead(clone):
    """The other half of "I pushed and nothing happened": the code is here, it is
    just not upstream."""
    remote, local = clone
    (local / "mine.txt").write_text("x")
    git(local, "add", ".")
    git(local, "commit", "-qm", "my own work")
    g = upd.git_state(cfg())
    assert g["ahead"] == 1 and g["behind"] == 0


def test_a_checkout_on_another_branch_is_named_rather_than_compared_silently(clone):
    remote, local = clone
    git(local, "checkout", "-q", "-b", "feature")
    g = upd.git_state(cfg())
    assert g["on_branch"] == "feature" and g["tracks"] == "master"


def test_the_count_and_the_list_agree_when_only_merges_separate_them(clone):
    """"2 changes waiting" above an empty list reads as the updater being broken.
    A merge subject is nearly useless — and still better than no answer."""
    remote, local = clone
    git(remote, "checkout", "-q", "-b", "side")
    (remote / "s.txt").write_text("s")
    git(remote, "add", ".")
    git(remote, "commit", "-qm", "side work")
    git(remote, "checkout", "-q", "master")
    git(remote, "merge", "--no-ff", "-q", "side", "-m", "Merge pull request #1")
    g = upd.git_state(cfg())
    assert g["behind"] == len(g["commits"]) > 0


def test_not_a_git_install_is_a_fact_not_an_error(monkeypatch):
    monkeypatch.setattr(upd, "install_dir", lambda: None)
    g = upd.git_state(cfg())
    assert g["root"] == "" and g["behind"] == 0 and g["error"] == ""


# --- the check, both halves together ---------------------------------------

def run_check(c, monkeypatch, published=None, fail=False):
    published = upd.current() if published is None else published
    """check() with the network half stubbed — the git half is real."""
    class Resp:
        text = published + "\n"

        def raise_for_status(self):
            if fail:
                raise RuntimeError("offline")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return Resp()

    monkeypatch.setattr(upd.httpx, "AsyncClient", lambda *a, **k: Client())
    return asyncio.run(upd.check(c, force=True))


def test_the_same_version_with_commits_waiting_is_still_an_update(clone, monkeypatch):
    """The reported bug, in one assertion."""
    remote, local = clone
    push(remote, 8)
    c = cfg()
    # published == running: exactly the case that used to report "up to date"
    state = run_check(c, monkeypatch)
    assert state["current"] == state["latest"] == upd.current()
    assert state["update_available"] is True
    assert state["behind"] == 8
    assert len(state["commits"]) == 8


def test_level_with_the_branch_is_not_an_update(clone, monkeypatch):
    state = run_check(cfg(), monkeypatch)
    assert state["update_available"] is False
    assert state["behind"] == 0


def test_a_version_bump_still_counts_on_its_own(clone, monkeypatch):
    """A pip install has no checkout, so the version file is all it has."""
    monkeypatch.setattr(upd, "install_dir", lambda: None)
    state = run_check(cfg(), monkeypatch, published="9.9.9")
    assert state["update_available"] is True and state["latest"] == "9.9.9"


def test_the_check_reports_git_even_when_the_version_file_is_unreachable(clone, monkeypatch):
    remote, local = clone
    push(remote, 2)
    state = run_check(cfg(), monkeypatch, fail=True)
    assert state["error"]                      # the failure is named…
    assert state["update_available"] is True   # …and the answer still arrives
    assert state["behind"] == 2


def test_the_branch_the_checkout_is_on_reaches_the_caller(clone, monkeypatch):
    remote, local = clone
    git(local, "checkout", "-q", "-b", "feature")
    state = run_check(cfg(), monkeypatch)
    assert state["mismatch"] is True
    assert state["on_branch"] == "feature" and state["tracks"] == "master"


def test_the_check_remembers_both_halves_for_the_instant_path(clone, monkeypatch):
    """Opening Settings answers from this cache; a cache holding only a version
    number is the same lie in a cheaper place."""
    remote, local = clone
    push(remote, 4)
    c = cfg()
    run_check(c, monkeypatch)
    assert upd.conf(c)["last_behind"] == 4
    assert upd.conf(c)["last_on_branch"] == "master"


def test_the_announce_key_moves_with_new_commits(clone, monkeypatch):
    """`mark` is what stops the watcher announcing twice. Keyed on the version
    alone, a version announced once could never be announced again — so commits
    landing under it were silent forever."""
    remote, local = clone
    push(remote, 1, prefix="first")
    first = run_check(cfg(), monkeypatch)["mark"]
    git(local, "merge", "-q", "--ff-only", "origin/master")
    push(remote, 1, prefix="second")
    second = run_check(cfg(), monkeypatch)["mark"]
    assert first and second and first != second
