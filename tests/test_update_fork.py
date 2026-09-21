"""`bento update` from a fork, and the two files it must never ask to stash.

Reported on a real install: every `bento update` said "same version (0.4.0)" and
then asked to stash. The version line was true — VERSION only moves at a release —
and the stash prompt was the updater's own doing: its `uv sync` re-resolved
`uv.lock`, the tree was dirty, and the next run found "1 uncommitted change".
Restoring the derived files and syncing `--frozen` ends that loop.

The other half: updates come from a repository and a branch, both settings, so a
fork can be followed without hand-editing git remotes — and `origin` is never
rewritten, so going back is one command.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import updates as upd                           # noqa: E402


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)


def _repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "uv.lock").write_text("lock v1\n")
    (root / "agentos" / "ui").mkdir(parents=True)
    (root / "agentos" / "ui" / "index.html").write_text("<html>built</html>\n")
    (root / "tracked.py").write_text("original\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "first")
    return root


# ---- the source ---------------------------------------------------------------

def test_a_repository_is_accepted_in_every_form_people_paste():
    for text in ["someone/bento-ai-os", "https://github.com/someone/bento-ai-os",
                 "https://github.com/someone/bento-ai-os.git", "github.com/someone/bento-ai-os/",
                 "git@github.com:someone/bento-ai-os.git"]:
        assert upd.parse_repo(text) == "someone/bento-ai-os", text


def test_a_typo_is_refused_not_fetched_from():
    for bad in ["", "nope", "a/b/c", "https://gitlab.com/a/b", "a b/c", "../x/y"]:
        assert upd.parse_repo(bad) == "", bad


def test_the_official_repository_keeps_origin_and_a_fork_gets_its_own_remote():
    assert upd.remote_name({}) == "origin"
    cfg = {"updates": {"repo": "Some.One/bento-ai-os"}}
    assert upd.remote_name(cfg) == "fork-some.one"
    assert upd.remote_url(cfg) == "https://github.com/Some.One/bento-ai-os.git"
    assert upd.raw_base(cfg).endswith("/Some.One/bento-ai-os")


def test_set_source_is_persisted_in_config_and_official_puts_it_back():
    cfg = {}
    src = upd.set_source(cfg, "https://github.com/you/bento-ai-os", "feature")
    assert src == {"repo": "you/bento-ai-os", "branch": "feature", "remote": "fork-you"}
    assert cfg["updates"]["repo"] == "you/bento-ai-os"
    assert cfg["updates"]["branch"] == "feature"
    back = upd.set_source(cfg, upd.DEFAULT_REPO, upd.DEFAULT_BRANCH)
    assert back["remote"] == "origin"


def test_set_source_refuses_a_bad_repository_or_branch():
    import pytest
    with pytest.raises(ValueError):
        upd.set_source({}, "not a repo")
    with pytest.raises(ValueError):
        upd.set_source({}, None, "-rf")


def test_ensure_remote_adds_the_fork_and_never_touches_origin(tmp_path):
    root = _repo(tmp_path)
    _git(root, "remote", "add", "origin", "https://github.com/contact9prime-lab/bento-ai-os.git")
    cfg = {"updates": {"repo": "you/bento-ai-os"}}
    ok, msg = upd.ensure_remote(cfg, root)
    assert ok and "added" in msg
    assert _git(root, "remote", "get-url", "fork-you").stdout.strip() == "https://github.com/you/bento-ai-os.git"
    assert _git(root, "remote", "get-url", "origin").stdout.strip().endswith("contact9prime-lab/bento-ai-os.git")
    # pointing at another fork moves the SAME remote rather than adding a third
    cfg = {"updates": {"repo": "you/other"}}
    upd.ensure_remote(cfg, root)
    assert _git(root, "remote", "get-url", "fork-you").stdout.strip() == "https://github.com/you/other.git"


# ---- derived files -------------------------------------------------------------

def test_a_rewritten_lockfile_is_not_the_users_work(tmp_path):
    root = _repo(tmp_path)
    (root / "uv.lock").write_text("lock v2, re-resolved by uv sync\n")
    (root / "agentos" / "ui" / "index.html").write_text("<html>rebuilt</html>\n")
    assert sorted(upd.derived_changes(root)) == ["agentos/ui/index.html", "uv.lock"]
    assert upd.own_changes(root) == [], "nothing of the user's is in a derived file"


def test_derived_files_are_restored_and_own_edits_are_left_alone(tmp_path):
    root = _repo(tmp_path)
    (root / "uv.lock").write_text("lock v2\n")
    (root / "tracked.py").write_text("mine\n")
    assert upd.restore_derived(root) == ["uv.lock"]
    assert (root / "uv.lock").read_text() == "lock v1\n"
    assert (root / "tracked.py").read_text() == "mine\n", "restore must never touch the user's edit"
    assert [c["path"] for c in upd.own_changes(root)] == ["tracked.py"]


def test_the_gate_ignores_derived_files_and_refuses_only_own_edits(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(upd, "install_dir", lambda: root)
    (root / "uv.lock").write_text("lock v2\n")
    ok, why = upd.can_apply({})
    assert ok, why
    (root / "tracked.py").write_text("mine\n")
    ok, why = upd.can_apply({})
    assert not ok and "1 uncommitted" in why


def test_the_gate_names_switch_on_the_wrong_branch_and_lets_switch_through(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(upd, "install_dir", lambda: root)
    _git(root, "checkout", "-qb", "elsewhere")
    ok, why = upd.can_apply({})
    assert not ok and "--switch" in why
    ok, why = upd.can_apply({}, switch=True)
    assert ok, why


def test_the_dependency_sync_does_not_rewrite_the_lockfile():
    src = Path(upd.__file__).read_text()
    i = src.index("async def apply(")
    body = src[i:]
    assert '"uv", "sync", "--frozen"' in body
    assert body.index("restore_derived(root)") < body.index('"git", "fetch"'), \
        "derived files are restored before the pull, or the pull refuses over them"
    assert "restore_derived(root)          # whatever the sync rewrote" in body


def test_nothing_in_the_updater_is_hard_wired_to_origin_any_more():
    src = Path(upd.__file__).read_text()
    for needle in ['"origin/', "f\"origin/", '"fetch", "origin"']:
        assert needle not in src, f"{needle}: a fork would be fetched from the wrong place"
