#!/usr/bin/env python3
"""Known vulnerabilities in what Bento installs, checked on every pull request and every week.

Asked for after a reel of incidents: vendor code turned on 178 organisations, a Java flaw and a
Jira flaw exploited for months after the fix shipped. Bento's own updates are signed and
fast-forward only (updates.py), but the packages it installs are other people's code, and a
locked version stays vulnerable until somebody notices.

    python3 packaging/audit-vulns.py            # report; exit 1 on a vulnerability not excepted
    python3 packaging/audit-vulns.py --json     # the same, as JSON

What it reads:
  * uv.lock, exported as the requirements every install resolves to (uv export --no-dev), and
    checked with pip-audit (Apache-2.0) run through uvx, so it is never one of Bento's
    dependencies. The armv7 cryptography pin (pyproject.toml) is a different resolution and is
    said, not scanned: a Pi on Buster has no newer wheel.
  * Each Node sidecar's package.json (wa_bridge, ocp_host), resolved into a throwaway lockfile with
    --ignore-scripts (no package code runs) and checked with npm audit. ocp_host has no dependencies.

An advisory nobody can fix yet goes in packaging/vuln-exceptions.txt as `ID | why | until DATE`.
A line past its date counts as not excepted, so an exception is looked at again, never forgotten.
Stdlib only, like versioning.py: the check must not fail on a dependency.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCEPTIONS = ROOT / "packaging" / "vuln-exceptions.txt"
NODE = ("agentos/wa_bridge", "agentos/ocp_host")
PIP_AUDIT = "pip-audit==2.10.1"


def exceptions(today: datetime.date | None = None) -> tuple[dict, list[str]]:
    """{id: why} still in date, and the lines that are past it or can't be read."""
    today = today or datetime.date.today()
    keep, stale = {}, []
    if not EXCEPTIONS.exists():
        return keep, stale
    for n, line in enumerate(EXCEPTIONS.read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3 or not parts[2].startswith("until "):
            stale.append(f"line {n} isn't `ID | why | until YYYY-MM-DD`")
            continue
        try:
            until = datetime.date.fromisoformat(parts[2][6:].strip())
        except ValueError:
            stale.append(f"line {n}: {parts[2]!r} isn't a date")
            continue
        if until < today:
            stale.append(f"{parts[0]} was excepted until {until}: look at it again")
            continue
        keep[parts[0]] = parts[1]
    return keep, stale


def _run(argv, cwd=None, timeout=600) -> subprocess.CompletedProcess:
    env = {**os.environ, "NO_COLOR": "1"}
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def python_findings() -> tuple[list[dict], str]:
    """(findings, problem): each finding {where, package, version, id, aliases, fix}."""
    if not shutil.which("uv"):
        return [], "uv isn't installed, so uv.lock couldn't be read"
    with tempfile.TemporaryDirectory() as tmp:
        req, out = Path(tmp) / "req.txt", Path(tmp) / "audit.json"
        r = _run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes",
                  "--format", "requirements-txt", "-o", str(req)], cwd=ROOT)
        if r.returncode:
            return [], "uv export failed: " + (r.stderr.strip().splitlines() or ["?"])[-1]
        r = _run(["uvx", PIP_AUDIT, "-r", str(req), "--no-deps", "--disable-pip",
                  "--progress-spinner", "off", "-f", "json", "-o", str(out)])
        if not out.exists():
            return [], "pip-audit didn't answer: " + (r.stderr.strip().splitlines() or ["?"])[-1]
        data = json.loads(out.read_text() or "{}")
    found = []
    for dep in data.get("dependencies") or []:
        for v in dep.get("vulns") or []:
            found.append({"where": "python", "package": dep["name"], "version": dep.get("version") or "",
                          "id": v["id"], "aliases": v.get("aliases") or [], "fix": v.get("fix_versions") or []})
    return found, ""


def node_findings(folder: str) -> tuple[list[dict], str]:
    pkg = json.loads((ROOT / folder / "package.json").read_text())
    if not pkg.get("dependencies"):
        return [], ""
    if not shutil.which("npm"):
        return [], "npm isn't installed, so the Node sidecars weren't checked"
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(ROOT / folder / "package.json", tmp)
        r = _run(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=tmp)
        if r.returncode:
            return [], f"{folder}: npm couldn't resolve it: " + (r.stderr.strip().splitlines() or ["?"])[-1]
        r = _run(["npm", "audit", "--json"], cwd=tmp)
        try:
            data = json.loads(r.stdout or "{}")
        except ValueError:
            return [], f"{folder}: npm audit didn't answer"
    found = []
    for name, v in (data.get("vulnerabilities") or {}).items():
        for via in v.get("via") or []:
            if not isinstance(via, dict):
                continue                    # pulled in by another vulnerable package, named there
            ident = (via.get("url") or "").rsplit("/", 1)[-1] or str(via.get("source"))
            fix = v.get("fixAvailable")
            found.append({"where": folder, "package": name, "version": v.get("range") or "", "id": ident,
                          "aliases": [], "severity": via.get("severity") or "",
                          "fix": [fix["version"]] if isinstance(fix, dict) and fix.get("version") else
                                 (["yes"] if fix is True else [])})
    return found, ""


def audit() -> dict:
    keep, stale = exceptions()
    found, problems = [], []
    got, why = python_findings()
    found += got
    problems += [why] if why else []
    for folder in NODE:
        got, why = node_findings(folder)
        found += got
        problems += [why] if why else []
    seen, rows = set(), []
    for f in found:
        key = (f["where"], f["package"], f["id"])
        if key in seen:
            continue
        seen.add(key)
        ids = [f["id"], *f["aliases"]]
        f["excepted"] = next((keep[i] for i in ids if i in keep), "")
        rows.append(f)
    bad = [f for f in rows if not f["excepted"]]
    return {"findings": rows, "open": len(bad), "stale": stale, "problems": problems,
            "ok": not bad and not stale and not problems}


def main(argv) -> int:
    rep = audit()
    if "--json" in argv:
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1
    for f in rep["findings"]:
        mark = "·" if f["excepted"] else "✗"
        fix = f"fixed in {', '.join(f['fix'])}" if f["fix"] else "no fix yet"
        print(f"  {mark} {f['where']}: {f['package']} {f['version']} {f['id']} ({fix})"
              + (f" excepted: {f['excepted']}" if f["excepted"] else ""))
    for s in rep["stale"]:
        print(f"  ✗ vuln-exceptions.txt: {s}")
    for p in rep["problems"]:
        print(f"  ✗ {p}")
    print("  armv7 keeps cryptography 46.0.3 on purpose (no newer wheel for a Pi on Buster); it isn't scanned here.")
    if rep["ok"]:
        print(f"  ✓ no known vulnerability open ({len(rep['findings'])} excepted)" if rep["findings"]
              else "  ✓ no known vulnerability in what Bento installs")
        return 0
    print(f"  {rep['open']} open. Upgrade the package (uv lock --upgrade-package NAME), or, when nobody can "
          "fix it yet, add `ID | why | until YYYY-MM-DD` to packaging/vuln-exceptions.txt.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
