"""Knowing there is a new version, and installing it without breaking the machine.

An update here is not "replace an app". It is three things in order — the code on
disk, the running service, the page on screen — and the interesting tests are all
about refusing to do it badly: never without being asked, never onto somebody's
uncommitted work, and never leaving a machine that cannot answer.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import updates as up               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------- the version file

def test_the_version_lives_in_exactly_one_place():
    """A release should be one edit. Two copies means the day one of them is
    forgotten, the updater compares the wrong number against the world."""
    import tomllib

    from agentos import __version__
    f = ROOT / "agentos" / "VERSION"
    assert f.is_file(), "agentos/VERSION is the source of truth and must exist"
    assert f.read_text().strip() == __version__
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == __version__, (
        "pyproject.toml and agentos/VERSION disagree — bump both, or the update "
        "checker and the package metadata describe different builds")


def test_the_version_ships_inside_the_package():
    """Not at the repo root: a wheel would not carry it, and an installed copy
    could not say what it is."""
    assert (ROOT / "agentos" / "VERSION").is_file()


# ---------------------------------------------------------------- the comparison

def test_newer_is_newer():
    assert up.is_newer("0.2.0", "0.1.0")
    assert up.is_newer("0.1.1", "0.1.0")
    assert up.is_newer("1.0.0", "0.9.9")
    assert up.is_newer("0.10.0", "0.9.0"), "10 > 9, not '10' < '9'"


def test_same_or_older_is_not_an_update():
    assert not up.is_newer("0.1.0", "0.1.0")
    assert not up.is_newer("0.1.0", "0.2.0")
    assert not up.is_newer("", "0.1.0")


def test_a_label_does_not_reorder_a_release():
    """Pretending to a total order over arbitrary suffixes is how a machine
    decides a release is older than itself and updates in a loop."""
    assert not up.is_newer("0.1.0-rc1", "0.1.0")
    assert not up.is_newer("0.1.0+build9", "0.1.0")
    assert up.is_newer("0.2.0-rc1", "0.1.0")


# ------------------------------------------------------------------- the check

class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _http(routes):
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **k):
            return _Resp(200, routes[url]) if url in routes else _Resp(404, "")
    return C


def test_a_newer_published_version_is_reported(monkeypatch):
    monkeypatch.setattr(up, "__version__", "0.1.0")
    monkeypatch.setattr(up, "current", lambda: "0.1.0")
    monkeypatch.setattr(up.httpx, "AsyncClient", _http({
        f"{up.RAW}/master/agentos/VERSION": "0.9.0\n",
        # this project's changelog uses ### for entries, under a single # title
        f"{up.RAW}/master/CHANGELOG.md":
            "# Changelog\n\n### 0.9.0\n- did things\n\n### 0.1.0\n- old"}))
    res = asyncio.run(up.check({}))
    assert res["update_available"] and res["latest"] == "0.9.0"
    assert "did things" in res["notes"]
    assert "0.1.0\n- old" not in res["notes"], "the notes stop at the previous entry"


def test_being_current_is_not_an_update(monkeypatch):
    monkeypatch.setattr(up, "current", lambda: "0.9.0")
    monkeypatch.setattr(up.httpx, "AsyncClient",
                        _http({f"{up.RAW}/master/agentos/VERSION": "0.9.0"}))
    assert asyncio.run(up.check({}))["update_available"] is False


def test_no_network_is_reported_not_raised(monkeypatch):
    class Boom:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise OSError("no route to host")
    monkeypatch.setattr(up.httpx, "AsyncClient", Boom)
    res = asyncio.run(up.check({}))
    assert res["update_available"] is False and res["error"]


def test_a_junk_response_is_not_treated_as_a_version(monkeypatch):
    """A captive portal returns a login page with HTTP 200."""
    monkeypatch.setattr(up.httpx, "AsyncClient",
                        _http({f"{up.RAW}/master/agentos/VERSION": "<!DOCTYPE html>"}))
    res = asyncio.run(up.check({}))
    assert res["update_available"] is False and res["error"]


def test_checks_can_be_switched_off_but_a_manual_one_still_works(monkeypatch):
    monkeypatch.setattr(up, "current", lambda: "0.1.0")
    monkeypatch.setattr(up.httpx, "AsyncClient",
                        _http({f"{up.RAW}/master/agentos/VERSION": "0.9.0"}))
    cfg = {"updates": {"enabled": False}}
    assert asyncio.run(up.check(cfg))["error"]                      # automatic: no
    assert asyncio.run(up.check(cfg, force=True))["update_available"]  # asked: yes


# ------------------------------------------------------------------ the refusals

def _repo(tmp_path, dirty=False, branch="master"):
    r = tmp_path / "repo"
    (r / "agentos").mkdir(parents=True)
    (r / "agentos" / "VERSION").write_text("0.1.0\n")
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=r, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=r, check=True)
    if dirty:
        (r / "agentos" / "VERSION").write_text("0.1.0-mine\n")
    return r


def test_it_refuses_to_pull_over_your_own_work(tmp_path, monkeypatch):
    """Somebody developing against their own install must not lose it to a
    version check."""
    r = _repo(tmp_path, dirty=True)
    monkeypatch.setattr(up, "install_dir", lambda: r)
    ok, why = up.can_apply({})
    assert not ok and "uncommitted" in why and str(r) in why


def test_it_refuses_on_a_different_branch(tmp_path, monkeypatch):
    r = _repo(tmp_path, branch="my-experiment")
    monkeypatch.setattr(up, "install_dir", lambda: r)
    ok, why = up.can_apply({})
    assert not ok and "my-experiment" in why


def test_a_clean_checkout_on_the_right_branch_may_update(tmp_path, monkeypatch):
    r = _repo(tmp_path)
    monkeypatch.setattr(up, "install_dir", lambda: r)
    ok, why = up.can_apply({})
    assert ok and not why


def test_a_non_git_install_says_so_instead_of_pretending(monkeypatch):
    monkeypatch.setattr(up, "install_dir", lambda: None)
    ok, why = up.can_apply({})
    assert not ok and "installed from git" in why


def test_apply_refuses_before_touching_anything(tmp_path, monkeypatch):
    r = _repo(tmp_path, dirty=True)
    monkeypatch.setattr(up, "install_dir", lambda: r)
    res = asyncio.run(up.apply({}, run_tests=False))
    assert res["ok"] is False and "uncommitted" in res["error"]
    assert (r / "agentos" / "VERSION").read_text() == "0.1.0-mine\n", "nothing was touched"


def test_a_version_that_fails_its_own_tests_is_rolled_back(tmp_path, monkeypatch):
    """A machine that cannot answer is worse than a machine one version behind."""
    r = _repo(tmp_path)
    monkeypatch.setattr(up, "install_dir", lambda: r)
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True,
                            text=True).stdout.strip()

    real = up._run

    def fake(args, cwd=None, timeout=60):
        if args[:2] == ["git", "fetch"]:
            return True, ""
        if args[:2] == ["git", "merge"]:
            # stand in for the pull: a commit that is "the new version"
            (r / "agentos" / "VERSION").write_text("0.9.0\n")
            subprocess.run(["git", "commit", "-aqm", "v0.9.0"], cwd=r, check=True)
            return True, ""
        if "pytest" in args:
            return False, "3 failed"
        return real(args, cwd, timeout)
    monkeypatch.setattr(up, "_run", fake)

    res = asyncio.run(up.apply({}, run_tests=True))
    assert res["ok"] is False and res.get("rolled_back")
    now = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True,
                         text=True).stdout.strip()
    assert now == before, "the checkout must be back where it started"
    assert (r / "agentos" / "VERSION").read_text().strip() == "0.1.0"


# -------------------------------------------------------------- telling the user

def test_a_version_is_announced_once_not_every_check():
    """A card that reappears daily for a version somebody declined is how people
    learn to dismiss cards without reading them."""
    cfg = {"updates": {"last_seen": "0.9.0"}}
    c = up.conf(cfg)
    assert c["last_seen"] == "0.9.0"
    # the watcher's condition, stated directly
    assert not ("0.9.0" not in (c.get("skipped"), c.get("last_seen")))


def test_a_skipped_version_stays_skipped():
    cfg = {"updates": {"skipped": "0.9.0"}}
    assert up.conf(cfg)["skipped"] == "0.9.0"


def test_checking_is_on_by_default_but_installing_is_never_automatic():
    c = up.conf({})
    assert c["enabled"] is True
    # There is deliberately no "install automatically" setting to find:
    assert "auto_install" not in c and "automatic" not in c
