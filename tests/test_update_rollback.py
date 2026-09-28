"""An update can be taken back, and a branch switch is a button.

Reported with a screenshot: the tracked branch was changed to test a newer build, and
Settings said "0.6.7 → 0.6.8 available", then a sentence about `bento update --apply
--switch`, and a Check now button. No way to update from the page, and no way back
afterwards. What these defend:

- an installed update is recorded (where from, which branch, which version);
- `last_update` answers only while the checkout still holds that update's result;
- `rollback` puts the commit AND the branch back, and the tracked branch with it;
- a rolled-back update cannot be rolled back twice;
- the page offers "Switch … and update" and "Roll back", and the terminal has
  `bento update --rollback`.

Driven against real git repositories, like test_update_gate.py.
"""
import json
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


def on(root):
    return git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


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
    git(local, "config", "user.email", "t@example.com")
    git(local, "config", "user.name", "T")
    monkeypatch.setattr(upd, "install_dir", lambda: local)
    monkeypatch.setattr(upd, "_python", lambda root: sys.executable)
    monkeypatch.setattr(upd, "_history_path", lambda: tmp_path / "update-history.json")
    return remote, local, tmp_path / "update-history.json"


def bump(remote, version, branch="master"):
    (remote / "agentos" / "VERSION").write_text(version + "\n")
    (remote / f"f{version}.txt").write_text(version)
    git(remote, "add", ".")
    git(remote, "commit", "-qm", f"release {version}")


@pytest.mark.asyncio
async def test_an_update_is_recorded_and_can_be_taken_back(repo):
    remote, local, hist = repo
    before = head(local)
    bump(remote, "0.0.2")
    res = await upd.apply({"updates": {"branch": "master"}}, run_tests=False)
    assert res["ok"] and head(local) != before
    rec = json.loads(hist.read_text())[-1]
    assert rec["from"] == before and rec["to"] == head(local) and rec["to_version"] == "0.0.2"
    assert upd.last_update(local)["from"] == before

    cfg = {"updates": {"branch": "master"}}
    back = await upd.rollback(cfg)
    assert back["ok"] and head(local) == before and back["version"] == "0.0.1"
    assert on(local) == "master"
    assert upd.last_update(local) is None, "a rolled-back update cannot be taken back twice"
    assert json.loads(hist.read_text())[-1]["rolled_back"]
    again = await upd.rollback(cfg)
    assert not again["ok"] and "no update to roll back" in again["error"]


@pytest.mark.asyncio
async def test_switching_branch_is_undone_with_the_branch(repo):
    """The screenshot: updates were pointed at a test branch while the checkout sat on
    master. Switch-and-update, then roll back: master again, tracked again."""
    remote, local, _ = repo
    git(remote, "checkout", "-qb", "try-it")
    bump(remote, "0.0.3")
    git(remote, "checkout", "-q", "master")
    before = head(local)
    cfg = {"updates": {"branch": "try-it"}}
    ok, why = upd.can_apply(cfg)
    assert not ok and "--switch" in why
    assert upd.can_apply(cfg, switch=True)[0], "the page's button: nothing but the branch in the way"
    res = await upd.apply(cfg, run_tests=False, switch=True)
    assert res["ok"] and res["switched"] == "master" and on(local) == "try-it"

    back = await upd.rollback(cfg)
    assert back["ok"] and on(local) == "master" and head(local) == before
    assert cfg["updates"]["branch"] == "master", "the panel agrees with the checkout again"


@pytest.mark.asyncio
async def test_only_the_update_it_installed_is_undone(repo):
    """A commit made on top of an update is somebody's work, and rollback leaves it."""
    remote, local, _ = repo
    bump(remote, "0.0.2")
    assert (await upd.apply({"updates": {"branch": "master"}}, run_tests=False))["ok"]
    (local / "mine.txt").write_text("mine")
    git(local, "add", ".")
    git(local, "commit", "-qm", "my own work")
    assert upd.last_update(local) is None
    assert not (await upd.rollback({"updates": {"branch": "master"}}))["ok"]


def test_the_page_and_the_terminal_offer_it():
    st = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "updateNow(this,true)" in st and "function verRollback(" in st
    assert "/api/update/rollback" in st
    srv = (ROOT / "agentos/server.py").read_text()
    assert '@app.post("/api/update/rollback")' in srv and '"can_switch": can_switch' in srv
    route = srv.split('@app.post("/api/update/rollback")', 1)[1].split("\n@app.", 1)[0]
    assert "is_loopback" in route, "rolling back replaces the code: this machine only"
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"--rollback"' in main and "upd.rollback(cfg" in main
