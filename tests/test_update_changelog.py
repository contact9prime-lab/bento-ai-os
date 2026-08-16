"""What an update brings, from git rather than from a file somebody maintains.

CHANGELOG.md is a published release note. On any branch between releases it says
nothing, which is most of the time — so "a new version is available" arrived with
no answer to the only question that matters before restarting the machine you are
working on: what changes.

Git already knows. These assert the primitive, because everything above it (the
CLI before and after an apply, the update card, apply()'s own report) is the same
list rendered three ways.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import updates as upd                         # noqa: E402


def _repo(tmp_path):
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True,
                       capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Tester")
    # Three commits, so HEAD~2 is a real revision. With two, HEAD~2 is before the
    # root commit, git errors, and the helper correctly returns [] — which reads
    # as a broken changelog rather than a broken test.
    (tmp_path / "f.txt").write_text("0")
    git("add", "."); git("commit", "-qm", "zeroth change")
    (tmp_path / "f.txt").write_text("1")
    git("commit", "-qam", "first change")
    (tmp_path / "f.txt").write_text("2")
    git("commit", "-qam", "second change")
    return tmp_path


def test_the_commits_between_two_revisions_are_listed_newest_first(tmp_path):
    root = _repo(tmp_path)
    out = upd.commits("HEAD~2", "HEAD", root=root)
    assert [c["title"] for c in out] == ["second change", "first change"]
    assert all(c["hash"] and c["author"] == "Tester" and c["at"] > 0 for c in out)


def test_a_merge_commit_is_skipped(tmp_path):
    """Its subject is "Merge pull request #11", which is true and tells you
    nothing. What it brought in is in the range anyway."""
    root = _repo(tmp_path)
    def git(*a):
        subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True)
    git("checkout", "-q", "-b", "side")
    (root / "g.txt").write_text("x")
    git("add", "."); git("commit", "-qm", "work on a branch")
    git("checkout", "-q", "main")
    git("merge", "--no-ff", "-q", "side", "-m", "Merge pull request #11")
    titles = [c["title"] for c in upd.commits("HEAD~3", "HEAD", root=root)]
    assert "work on a branch" in titles
    assert not any(t.startswith("Merge ") for t in titles), titles


def test_nothing_between_two_identical_revisions(tmp_path):
    """An update that changed nothing must not invent a changelog."""
    assert upd.commits("HEAD", "HEAD", root=_repo(tmp_path)) == []


def test_a_bad_revision_answers_empty_rather_than_raising(tmp_path):
    """This runs inside the update path. A changelog that cannot be read is a
    missing paragraph, never a failed upgrade."""
    assert upd.commits("HEAD", "no-such-rev", root=_repo(tmp_path)) == []
    assert upd.commits("", "", root=_repo(tmp_path)) == []


def test_the_limit_is_honoured(tmp_path):
    """A machine ten releases behind must not push the Update button off screen."""
    assert len(upd.commits("HEAD~2", "HEAD", limit=1, root=_repo(tmp_path))) == 1


def test_only_the_subject_is_kept(tmp_path):
    """Bodies in this repo run to forty lines of reasoning — right in `git log`,
    wrong in a list of what an update brings."""
    root = _repo(tmp_path)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m",
                    "a short subject\n\nand a very long body\nover several lines"],
                   cwd=root, check=True, capture_output=True, text=True)
    top = upd.commits("HEAD~1", "HEAD", root=root)[0]
    assert top["title"] == "a short subject"
    assert "body" not in top["title"]
