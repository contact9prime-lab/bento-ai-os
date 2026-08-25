"""`bento update` on a checkout with your own edits in it: a decision, not a wall.

The gate itself is right — a fast-forward on top of uncommitted work is how somebody
loses an afternoon, and `can_apply` must keep refusing it for every unattended caller
(the Settings button, the watcher, the `update_agentos` tool). What was wrong was the
end of the sentence. "There are 1 uncommitted change(s)" does not say WHICH file, and
"commit or stash them first" is an instruction to leave the command and run git by
hand, so the commonest outcome of a blocked update was no update.

So the terminal names the files and offers the one answer that loses nothing: park
them with `git stash`, update, and say — on every exit path, including the failures —
how to get them back. Silence is a no: no terminal, no prompt, same refusal as before.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import updates as upd                           # noqa: E402


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)


def _repo(tmp_path):
    """A one-commit checkout with an uncommitted edit and an untracked file in it."""
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "tracked.py").write_text("original\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "first")
    (root / "tracked.py").write_text("mine\n")           # the blocker
    (root / "scratch.log").write_text("noise\n")         # untracked: never the blocker
    return root


def test_the_refusal_can_name_the_files(tmp_path):
    root = _repo(tmp_path)
    changed = upd.local_changes(root)
    assert [c["path"] for c in changed] == ["tracked.py"], \
        "an untracked file is not work a fast-forward can clobber and must not count"
    assert changed[0]["code"] == "M"


def test_stashing_leaves_a_clean_tree_and_says_how_to_undo(tmp_path):
    root = _repo(tmp_path)
    ok, msg = upd.stash_local(root)
    assert ok, msg
    assert "stash pop" in msg, "parked work with no way back is work the user thinks was eaten"
    assert upd.local_changes(root) == []
    assert (root / "tracked.py").read_text() == "original\n"
    assert (root / "scratch.log").exists(), "an untracked file was swept up in the stash"

    # …and it is genuinely parked, not discarded: this is the whole reason a stash
    # is offered where a `checkout --` is not.
    _git(root, "stash", "pop")
    assert (root / "tracked.py").read_text() == "mine\n"


def test_a_clean_tree_is_not_told_it_has_something_to_recover(tmp_path):
    """`git stash push` exits 0 on a clean tree having stashed nothing. Reporting
    that as a park sends the user to somebody else's stash, or to an empty list."""
    root = _repo(tmp_path)
    _git(root, "checkout", "--", "tracked.py")
    ok, msg = upd.stash_local(root)
    assert ok and "stash pop" not in msg


def test_the_gate_still_refuses_for_everyone_who_cannot_be_asked(tmp_path, monkeypatch):
    """The no-regression half. `can_apply` is what the Settings button, the update
    watcher and the `update_agentos` tool all consult, and none of them has a
    terminal — the prompt lives in the CLI precisely so this stays a refusal."""
    root = _repo(tmp_path)
    monkeypatch.setattr(upd, "install_dir", lambda: root)
    ok, why = upd.can_apply({})
    assert not ok
    assert "uncommitted" in why


def test_silence_is_a_no(monkeypatch):
    """A cron line, a systemd timer or a CI step must never block on a prompt, and
    must never be answered 'yes' on the user's behalf."""
    from agentos import __main__ as cli

    class _NotATTY:
        @staticmethod
        def isatty():
            return False
    monkeypatch.setattr(cli.sys, "stdin", _NotATTY)
    monkeypatch.setattr(cli.sys, "stdout", _NotATTY)
    monkeypatch.setattr("builtins.input", lambda *a: pytest_fail_if_called())

    def pytest_fail_if_called():
        raise AssertionError("an unattended run was asked a question")

    assert cli._confirm("install the update?") is False
