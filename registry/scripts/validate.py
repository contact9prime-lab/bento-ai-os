#!/usr/bin/env python3
"""Validate every package in the registry — the same checks `bento registry verify`
runs, because it IS the same code: this script imports agentos.appregistry rather
than carrying a copy of the checksum, the scan rules or the signature check. Two
definitions of "what bytes does the signature cover?" is how every valid package
on one side becomes a checksum-mismatch on the other, so CI installs bento and
imports the one implementation.

Exit 0: every package is intact, scanned, and its verdict matches a fresh scan.
Exit 1: something is wrong; the output says what, per package.
"""
import json
import sys
from pathlib import Path

from agentos import appregistry as reg

ROOT = Path(__file__).resolve().parent.parent
failed = 0

for path in sorted(ROOT.glob("apps/*/*.agentapp.json")):
    rel = path.relative_to(ROOT)
    try:
        pkg = json.loads(path.read_text())
    except Exception as e:
        print(f"✗ {rel}: not JSON — {e}")
        failed += 1
        continue
    problems = []
    if pkg.get("format") != reg.PACKAGE_FORMAT:
        problems.append(f"format is {pkg.get('format')!r}, not {reg.PACKAGE_FORMAT!r}")
    man, html = pkg.get("manifest") or {}, pkg.get("html") or ""
    if not man.get("name"):
        problems.append("manifest has no name")
    if len(html.strip()) < 20:
        problems.append("no app markup")
    status, why = reg.verify_package(pkg)
    if status in ("checksum-mismatch", "bad-signature"):
        problems.append(f"{status}: {why}")
    ap = reg.author_problem(man)
    if ap:
        problems.append(ap + " — see COVENANT.md")
    sec = man.get("security") or {}
    if not sec:
        problems.append("not security-scanned — run `bento registry scan` before the PR")
    else:
        # the recorded STATIC findings must match a fresh scan of these bytes: a
        # hand-edited findings list is the same laundering the signature prevents,
        # caught here for the unsigned PR stage too
        fresh = reg.static_scan(html)
        recorded = [f for f in sec.get("findings", []) if f.get("rule") != "ai"]
        if reg.verdict_of(fresh + [f for f in sec.get("findings", []) if f.get("rule") == "ai"]) \
                != sec.get("verdict"):
            problems.append("security verdict does not match a fresh scan of this code")
        elif len(fresh) != len(recorded):
            problems.append(f"scan findings drifted: {len(recorded)} recorded, "
                            f"{len(fresh)} on a fresh scan")
    if problems:
        failed += 1
        print(f"✗ {rel}")
        for p in problems:
            print(f"    {p}")
    else:
        sig = "signed" if pkg.get("signature") else "unsigned (a maintainer signs on merge)"
        print(f"✓ {rel} — {sec.get('verdict')}, {sig}")

print(f"\n{'✗ ' + str(failed) + ' package(s) failed' if failed else '✓ all packages valid'}")
sys.exit(1 if failed else 0)
