"""The version number moves with the code.

Reported: "when I do `bento update` it still shows the old version number". It did —
agentos/VERSION was written only at a release, so forty pulled commits still said
0.4.0. What these defend:

- a bump moves VERSION, pyproject.toml and the changelog heading together, and only
  forwards;
- the check says a bump is needed exactly when something that SHIPS changed and the
  number did not move — docs and tests alone never demand one;
- the CI workflow runs that check on pull requests and bumps a push that forgot, and
  it runs on a bare python3 (no dependencies to fail);
- `bento update` names the version before and after, read from disk after the pull,
  and the build next to the number everywhere it is shown.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import versioning as v                                   # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("cur,kind,want", [
    ("0.4.0", "patch", "0.4.1"), ("0.4.9", "minor", "0.5.0"), ("0.4.2", "major", "1.0.0"),
    ("1.2", "patch", "1.2.1"),
])
def test_next_version(cur, kind, want):
    assert v.next_version(cur, kind) == want


def _repo(tmp_path, changelog="# Changelog\n\n## Unreleased\n\nNew things.\n\n## Older\n\nx\n"):
    (tmp_path / "agentos").mkdir()
    (tmp_path / "agentos" / "VERSION").write_text("0.4.0\n")
    (tmp_path / "agentos" / "core.py").write_text("x = 1\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "agentos"\nversion = "0.4.0"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    (tmp_path / "uv.lock").write_text('version = 1\n\n[[package]]\nname = "agentos"\nversion = "0.4.0"\n'
                                      'source = { editable = "." }\n\n[[package]]\nname = "httpx"\n'
                                      'version = "0.4.0"\n')
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("hi\n")
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True,  # noqa: E731
                                    capture_output=True)
    git("init", "-q", "-b", "master")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return git


def _commit(git, msg="c"):
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg)


def test_a_bump_moves_all_three_and_names_the_notes(tmp_path):
    _repo(tmp_path)
    got = v.bump("minor", root=tmp_path, today="2026-09-26")
    assert got == {"from": "0.4.0", "to": "0.5.0",
                   "files": ["agentos/VERSION", "pyproject.toml", "uv.lock", "CHANGELOG.md"]}
    lock = (tmp_path / "uv.lock").read_text()
    assert 'name = "agentos"\nversion = "0.5.0"' in lock and 'name = "httpx"\nversion = "0.4.0"' in lock, \
        "only this package's own line moves"
    assert (tmp_path / "agentos/VERSION").read_text().strip() == "0.5.0"
    assert 'version = "0.5.0"' in (tmp_path / "pyproject.toml").read_text()
    cl = (tmp_path / "CHANGELOG.md").read_text()
    assert "## 0.5.0 — 2026-09-26\n\nNew things." in cl and "Unreleased" not in cl
    assert "## Older" in cl, "only the top heading is renamed"


def test_with_no_notes_the_heading_still_says_what_to_read(tmp_path):
    _repo(tmp_path, changelog="# Changelog\n\n## 0.4.0 — 2026-09-01\n\nold\n")
    v.bump("patch", root=tmp_path, today="2026-09-26")
    cl = (tmp_path / "CHANGELOG.md").read_text()
    assert cl.index("## 0.4.1 — 2026-09-26") < cl.index("## 0.4.0"), "the new one is on top"
    assert "commits since 0.4.0" in cl


def test_a_bump_only_goes_forward(tmp_path):
    _repo(tmp_path)
    for to in ("0.4.0", "0.3.9", "banana"):
        with pytest.raises(ValueError):
            v.bump(root=tmp_path, to=to)
    with pytest.raises(ValueError):
        v.bump("sideways", root=tmp_path)
    assert (tmp_path / "agentos/VERSION").read_text().strip() == "0.4.0", "a refusal writes nothing"


def test_the_check_asks_for_a_bump_only_when_something_that_ships_changed(tmp_path):
    git = _repo(tmp_path)
    git("branch", "base")
    (tmp_path / "docs" / "guide.md").write_text("better words\n")
    _commit(git, "docs")
    r = v.needs_bump("base", root=tmp_path)
    assert not r["needed"] and r["shipped"] == [], "a guide or a test never demands a bump"
    (tmp_path / "agentos" / "core.py").write_text("x = 2\n")
    _commit(git, "code")
    r = v.needs_bump("base", root=tmp_path)
    assert r["needed"] and r["shipped"] == ["agentos/core.py"]
    assert (r["base_version"], r["head_version"]) == ("0.4.0", "0.4.0")
    v.bump("patch", root=tmp_path)
    _commit(git, "bump")
    r = v.needs_bump("base", root=tmp_path)
    assert not r["needed"] and r["head_version"] == "0.4.1"


def test_an_unreadable_base_is_an_error_not_a_pass(tmp_path):
    _repo(tmp_path)
    r = v.needs_bump("no-such-branch", root=tmp_path)
    assert r["error"] and not r["needed"]


def test_the_build_is_named_next_to_the_number(tmp_path):
    _repo(tmp_path)
    b = v.build(tmp_path)
    assert len(b) >= 7 and v.label(tmp_path) == f"0.4.0 ({b})"
    (tmp_path / "plain").mkdir()
    assert v.build(tmp_path / "plain") == "", "no checkout, no build — never a guess"


def test_ci_checks_pull_requests_and_bumps_a_push_that_forgot():
    wf = (ROOT / ".github/workflows/version.yml").read_text()
    assert "python3 -m agentos version check" in wf and "version bump patch" in wf
    assert "pull_request" in wf and "branches: [master, main]" in wf
    assert "contents: write" in wf and "git push" in wf


def test_the_check_runs_on_a_bare_python_with_nothing_installed():
    """CI runs it with the runner's python3: no uv sync, so nothing to fail on."""
    r = subprocess.run([sys.executable, "-I", "-S", "-c",
                        f"import sys; sys.path.insert(0, {str(ROOT)!r}); sys.argv=['agentos','version'];"
                        "import runpy; runpy.run_module('agentos', run_name='__main__')"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "Bento Box AI " in r.stdout, r.stderr


def test_update_says_the_version_before_and_after():
    src = (ROOT / "agentos/__main__.py").read_text()
    assert 'f"  version {was} → {now} (build {result[\'to\']})"' in src
    assert "_vmod.label()" in src, "the header names the build as well as the number"
    js = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "d.build" in js, "Settings shows the build beside the number"
