"""Known vulnerabilities in what Bento installs (packaging/audit-vulns.py, .github/workflows/vulns.yml).
The scanners are run, never depended on: pip-audit through uvx, npm audit on a throwaway lockfile."""
import datetime
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "packaging" / "audit-vulns.py"


def _mod():
    spec = importlib.util.spec_from_file_location("audit_vulns", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_an_exception_has_a_date_and_is_looked_at_again_after_it(tmp_path, monkeypatch):
    m = _mod()
    f = tmp_path / "ex.txt"
    f.write_text("# comment\nGHSA-aaaa | waiting on upstream | until 2026-12-01\n"
                 "PYSEC-1 | old | until 2020-01-01\nbroken line\nX | y | until someday\n")
    monkeypatch.setattr(m, "EXCEPTIONS", f)
    keep, stale = m.exceptions(datetime.date(2026, 11, 23))
    assert keep == {"GHSA-aaaa": "waiting on upstream"}
    assert len(stale) == 3 and any("look at it again" in s for s in stale)


def test_a_finding_not_excepted_is_red_and_an_excepted_one_is_said(monkeypatch, tmp_path):
    m = _mod()
    monkeypatch.setattr(m, "EXCEPTIONS", tmp_path / "none.txt")
    monkeypatch.setattr(m, "python_findings", lambda: ([
        {"where": "python", "package": "pyjwt", "version": "2.13.0", "id": "PYSEC-2026-4145",
         "aliases": ["CVE-2026-1"], "fix": ["2.14.0"]}], ""))
    monkeypatch.setattr(m, "node_findings", lambda folder: ([], ""))
    rep = m.audit()
    assert rep["open"] == 1 and not rep["ok"]
    (tmp_path / "none.txt").write_text("CVE-2026-1 | a reason | until 2999-01-01\n")
    rep = m.audit()
    assert rep["ok"] and rep["findings"][0]["excepted"] == "a reason", "an alias matches as well as the id"
    monkeypatch.setattr(m, "node_findings", lambda folder: ([], "npm isn't installed"))
    assert not m.audit()["ok"], "a scanner that didn't run is never a pass"


def test_the_sidecar_with_no_dependencies_is_not_resolved():
    m = _mod()
    assert m.node_findings("agentos/ocp_host") == ([], "")


def test_it_runs_on_a_bare_python_and_the_scanner_is_never_a_dependency():
    out = subprocess.run([sys.executable, "-I", "-S", "-c",
                          f"import importlib.util as u;s=u.spec_from_file_location('a',{str(SCRIPT)!r});"
                          "m=u.module_from_spec(s);s.loader.exec_module(m);print(m.PIP_AUDIT)"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout.startswith("pip-audit==")
    assert "pip-audit" not in (ROOT / "pyproject.toml").read_text()
    wf = (ROOT / ".github/workflows/vulns.yml").read_text()
    assert "packaging/audit-vulns.py" in wf and "schedule:" in wf and "pull_request:" in wf


def test_the_lock_carries_the_fixed_versions():
    lock = (ROOT / "uv.lock").read_text()

    def versions(name):
        out, lines = [], lock.splitlines()
        for i, line in enumerate(lines):
            if line == f'name = "{name}"':
                out.append(lines[i + 1].split('"')[1])
        return out
    v = lambda s: tuple(int(x) for x in s.split(".")[:3])  # noqa: E731
    assert max(v(x) for x in versions("cryptography")) >= (50, 0, 0)
    assert all(v(x) >= (1, 30, 0) for x in versions("mcp")) and all(v(x) >= (2, 15, 0) for x in versions("pyjwt"))
