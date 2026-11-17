"""An update over files that are already there, untracked.

Reported with a screenshot of Settings → System: "could not fast-forward to origin/master:
… The following untracked working tree files would be overwritten by merge: docs/screenshots/
… Please move or remove them before you merge. Aborting", shown twice, while the terminal said
up to date. The service ran a development tree that held five files the update adds, each byte
for byte what was arriving; the terminal's `bento update` had updated its own clone. What these
defend:

- an untracked file identical to what the update adds is cleared and the update goes through;
- one that differs stops the update in a sentence naming it, and nothing changes;
- the page says a refusal once, though the POST and the socket both carry it;
- `bento update` says when the copy the server runs is behind, and fails when it could not
  update that copy.

Driven against real git repositories, like test_update_rollback.py.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import updates as upd                         # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)


def head(root):
    return git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-q", "-b", "master")
    git(remote, "config", "user.email", "t@example.com")
    git(remote, "config", "user.name", "T")
    (remote / "agentos").mkdir()
    (remote / "agentos" / "VERSION").write_text("0.0.1\n")
    git(remote, "add", ".")
    git(remote, "commit", "-qm", "base")
    local = tmp_path / "local"
    git(tmp_path, "clone", "-q", str(remote), str(local))
    monkeypatch.setattr(upd, "install_dir", lambda: local)
    monkeypatch.setattr(upd, "_python", lambda root: sys.executable)
    monkeypatch.setattr(upd, "_history_path", lambda: tmp_path / "update-history.json")
    # the release brings a test and a screenshot
    (remote / "agentos" / "VERSION").write_text("0.0.2\n")
    (remote / "tests").mkdir()
    (remote / "tests" / "test_new.py").write_text("def test_x():\n    assert True\n")
    (remote / "shot.png").write_bytes(b"\x89PNG fake")
    git(remote, "add", ".")
    git(remote, "commit", "-qm", "release 0.0.2")
    return remote, local


@pytest.mark.asyncio
async def test_identical_files_in_the_way_are_cleared(repo):
    remote, local = repo
    (local / "tests").mkdir()
    (local / "tests" / "test_new.py").write_text("def test_x():\n    assert True\n")
    (local / "shot.png").write_bytes(b"\x89PNG fake")
    before = head(local)
    res = await upd.apply({"updates": {"branch": "master"}}, run_tests=False)
    assert res["ok"], res
    assert head(local) != before and (local / "shot.png").read_bytes() == b"\x89PNG fake"
    assert not git(local, "status", "--porcelain").stdout.strip(), "nothing left untracked"


@pytest.mark.asyncio
async def test_a_different_file_in_the_way_stops_it_in_a_sentence(repo):
    remote, local = repo
    (local / "shot.png").write_bytes(b"my own picture")
    before = head(local)
    res = await upd.apply({"updates": {"branch": "master"}}, run_tests=False)
    assert not res["ok"] and res["in_the_way"] == ["shot.png"]
    assert "shot.png" in res["error"] and "Nothing changed" in res["error"]
    assert "Aborting" not in res["error"], "a sentence, never git's own refusal"
    assert head(local) == before and (local / "shot.png").read_bytes() == b"my own picture"


def test_the_page_says_a_refusal_once():
    js = (ROOT / "agentos" / "ui" / "src" / "js")
    note = (js / "24-notifications.js").read_text()
    body = note[note.index("function updateFailed(d)"):]
    body = body[:body.index("\nfunction ", 5)]
    assert "UPD_FAILED.msg" in body and "return" in body.split("UPD_FAILED.msg=why")[0]
    settings = (js / "11-settings.js").read_text()
    assert "UPD_FAILED.msg=String(d.error)" in settings


def test_the_terminal_names_the_copy_the_server_runs():
    src = (ROOT / "agentos" / "__main__.py").read_text()
    fn = src[src.index("def _served_behind("):src.index("def _update_cli(")]
    assert "upd.other_copies()" in fn and "_say_behind" in fn
    cli = src[src.index("def _update_cli("):src.index("def _service_cli(")]
    assert "_served_behind(tracked)" in cli
    # a failed update of the served copy is the last line, and a failure
    assert "other_failed" in cli and "return 0 if started and not other_failed else 1" in cli
