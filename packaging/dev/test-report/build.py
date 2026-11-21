"""Build the test report: every test in tests/, what it checks, how it ran, grouped by area.

    .venv/bin/python -m pytest -q -p no:cacheprovider tests --junitxml=OUT/junit.xml -o junit_family=xunit2
    .venv/bin/python packaging/dev/test-report/build.py OUT/junit.xml OUT/report.json [--notes notes.json] [--live live.json]

Reads the junit XML pytest wrote, and the test files themselves (with `ast`, nothing is imported or run),
so the report says what each file defends in its own words: the module docstring's first paragraph and
each test's docstring or name. It also lists the live end-to-end harnesses under packaging/dev, which the
suite does not run, and the modules no test names. `--notes` is a JSON object: `failures` maps a test id (or a
file stem, for every test in it) to {cause, kind}, what was found by reading the failure, written by
whoever ran it; `findings` is a list of {title, state, area, detail} for what the testing turned up.
A failure with no note says so.

Stdlib only, so it runs with a bare python3.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / "tests"

# Area by test file stem, first match wins. The names are the product's own sections (CLAUDE.md).
AREAS: list[tuple[str, str]] = [
    ("Ethics", r"^ethics"),
    ("Security and the gate", r"^(gate_|permissions_|policy|protected|tools_cannot_reach|integrity|holdclear|secevents|"
                              r"security_|perimeter|machine_routes|machine_verbs|quarantine|taint|audit|followups_security|"
                              r"peercheck|net_guard|jail|cli_jail|safe_folders|web_headers|ws_origin|ws_owner|"
                              r"ws_account|app_origin|tenant_isolation|test_isolation|suite_home|remember_sticks|stitched_walk|"
                              r"approval_card|phone_approvals|flow_policy|hands|vault|signin_hidden|tool_parity)"),
    ("Accounts, spaces and remote access", r"^(users|account_|accounts|remote|session|tui_accounts|signin|shared_folders|spaces|"
                                   r"user_scoped|mcp_accounts|tunnel|serve_|handoff)"),
    ("Chat, brains and executors", r"^(chat_|exec|executor|executors|brain|brains|multi_cli|fallback|empty_turn|"
                                   r"claimed_not_done|queued_turns|ollama|provider|cloud_providers|pricing|modelcatalog|"
                                   r"mcpbridge|mcp_catalog|team_door|toolscope|find_capability|followups|core|search|docs_rag|"
                                   r"outputs|run_inspector|trace|timetravel|arena|evals)"),
    ("Agents and teams", r"^(agent_|agents_|agentbundle|agentshare|team|teamlink|teamchat|linked_|link_|guest_pass|"
                         r"huddle|freetalk|pool|avatar|avatars|drama|world|mind|proactivity|ux_review)"),
    ("Company and departments", r"^(company|at_company|department|desk_handback)"),
    ("Missions, flows and the Brief", r"^(flow_|jobs|mission|missions_|brief|parked|automations|history|watch)"),
    ("Stage and blueprints", r"^(stage|blueprint|build_model|build_scenes|video_gen|skillpack|phone_blueprint)"),
    ("Apps and App Studio", r"^(app_|appcheck|appregistry|studio_|ui_app_registry|setup_appllm|copilot)"),
    ("Phones and channels", r"^(telegram|whatsapp|wa_|phone_|channel|channels|notifications)"),
    ("Devices, network and Zeros", r"^(device|devices|esp_|pi_|network|discovery|edge_code|ties|zero|provision|"
                                   r"hub_|warehouse|wifi|kiosk|screen|face|lite_screen|hearing|voiceprint|map_and)"),
    ("Desktop, Office and scenes", r"^(ui_|immersive|island|office|town|deck_|desktop_|panels|places|menubar|"
                                   r"theme|i18n|locale|settings_|task_desktops|app_fold|app_icons|playground|"
                                   r"live_windows|sui_|sway|compositor|open_on|platform|osdetect|media_bridge|"
                                   r"voice_stop|speech|doc_images|bundle_parses|cli_help|config_cli|setup_|onboarding)"),
    ("Updates, backup, standby and cloud", r"^(update|versioning|restart|backup|standby|keep|cloud_deploy|"
                                           r"install|installer|network_install|packaging|service_cli|components|"
                                           r"licensing|footprint|ocplugins|ochost|ocnative|hostctl)"),
]


def area_of(stem: str) -> str:
    s = stem[5:] if stem.startswith("test_") else stem
    for name, rx in AREAS:
        if re.search(rx, s):
            return name
    return "Other"


def _first_para(doc: str | None, limit: int = 700) -> str:
    if not doc:
        return ""
    para = doc.strip().split("\n\n", 1)[0]
    para = " ".join(line.strip() for line in para.splitlines())
    # a lead-in to a list ("What it checks, in order:") says nothing once the list is cut off
    if para.endswith(":"):
        cut = max(para.rfind(". ", 0, len(para) - 1), para.rfind("; ", 0, len(para) - 1))
        para = para[:cut + 1] if cut > 0 else para.rstrip(":") + "."
    return para[:limit]


def _humanise(name: str) -> str:
    n = re.sub(r"^test_", "", name)
    n = re.sub(r"\[.*\]$", "", n)
    return n.replace("_", " ").strip().capitalize()


def read_files() -> dict:
    """Each test file's docstring, its tests' docstrings, and whether it runs Node or a browser."""
    out = {}
    for p in sorted(TESTS.glob("test_*.py")):
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            out[p.stem] = {"doc": "", "tests": {}, "node": False, "browser": False, "lines": src.count("\n")}
            continue
        tests = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                tests[node.name] = _first_para(ast.get_docstring(node), 400)
        out[p.stem] = {
            "doc": _first_para(ast.get_docstring(tree)),
            "tests": tests,
            "node": bool(re.search(r"['\"]node['\"]|shutil\.which\(\"node\"\)", src)),
            "browser": "playwright" in src or "chromium" in src.lower(),
            "lines": src.count("\n") + 1,
        }
    return out


def read_junit(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    rows = []
    for tc in root.iter("testcase"):
        cls = tc.get("classname") or ""
        file = cls.split(".")[1] if cls.startswith("tests.") else cls.split(".")[0]
        name = tc.get("name") or ""
        status, msg = "passed", ""
        for tag in ("failure", "error", "skipped"):
            el = tc.find(tag)
            if el is not None:
                status = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                msg = (el.get("message") or (el.text or "")).strip()
                break
        rows.append({"file": file, "name": name, "id": f"tests/{file}.py::{name}",
                     "status": status, "time": round(float(tc.get("time") or 0), 3), "msg": msg[:600]})
    return rows


def live_harnesses() -> list[dict]:
    """The end-to-end runs under packaging/dev: real servers, real ssh, real browsers. Not in the suite."""
    out = []
    dev = ROOT / "packaging" / "dev"
    for p in sorted(dev.rglob("*")):
        if p.suffix not in (".py", ".sh", ".js") or not p.is_file() or "test-report" in p.parts:
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        doc = ""
        if p.suffix == ".py":
            try:
                doc = _first_para(ast.get_docstring(ast.parse(txt)), 400)
            except SyntaxError:
                doc = ""
        else:
            lines = [ln.lstrip("#/ *").strip() for ln in txt.splitlines()[:14]
                     if ln.startswith(("#", "//", " *", "/*")) and not ln.startswith("#!")]
            doc = " ".join(x for x in lines if x)[:400]
        rel = str(p.relative_to(ROOT))
        if re.match(r"^(run\.(py|js|sh)|walk\.py|.*_run\.py|active_sync\.py|install_over_ssh\.py|sui-testbed\.sh)$", p.name):
            out.append({"path": rel, "doc": doc})
    return out


def untested_modules(files: dict) -> list[str]:
    """agentos modules no test file imports or reaches as `agentos.<name>` (a test may still exercise one
    through another module, so this is a list to read, not a verdict)."""
    blob = "\n".join((TESTS / f"{stem}.py").read_text(encoding="utf-8", errors="replace") for stem in files)
    out = []
    for p in sorted((ROOT / "agentos").glob("*.py")):
        m = p.stem
        if m.startswith("_"):
            continue
        pat = (rf"agentos\.{re.escape(m)}\b|from agentos import [^\n]*\b{re.escape(m)}\b|"
               rf"from agentos import \([^)]*\b{re.escape(m)}\b")
        if not re.search(pat, blob):
            out.append(m)
    return out


def main(argv: list[str]) -> int:
    junit, dest = Path(argv[1]), Path(argv[2])
    live_runs: dict = {}
    if "--live" in argv:
        live_runs = {v["path"]: v for v in json.loads(Path(argv[argv.index("--live") + 1]).read_text()).values()}
    notes: dict = {}
    findings: list = []
    impact: dict = {}
    if "--notes" in argv:
        notes = json.loads(Path(argv[argv.index("--notes") + 1]).read_text())
        findings = notes.pop("findings", [])
        impact = notes.pop("impact", {})
        notes = notes.get("failures", notes)
    files = read_files()
    rows = read_junit(junit)
    for r in rows:
        f = files.get(r["file"], {})
        base = re.sub(r"\[.*\]$", "", r["name"])
        r["what"] = (f.get("tests") or {}).get(base) or _humanise(r["name"])
        r["param"] = r["name"][len(base):] if r["name"] != base else ""
        r["area"] = area_of(r["file"])
        if r["status"] in ("failed", "error"):
            n = notes.get(r["id"]) or notes.get(r["file"]) or {}
            r["cause"] = n.get("cause", "") if isinstance(n, dict) else str(n)
            r["kind"] = n.get("kind", "unknown") if isinstance(n, dict) else "unknown"
    by_file: dict[str, dict] = {}
    for r in rows:
        b = by_file.setdefault(r["file"], {"file": r["file"], "area": r["area"],
                                           "doc": files.get(r["file"], {}).get("doc", ""),
                                           "node": files.get(r["file"], {}).get("node", False),
                                           "browser": files.get(r["file"], {}).get("browser", False),
                                           "passed": 0, "failed": 0, "error": 0, "skipped": 0, "time": 0.0,
                                           "count": 0})
        b[r["status"]] += 1
        b["count"] += 1
        b["time"] = round(b["time"] + r["time"], 2)
    areas: dict[str, dict] = {}
    for b in by_file.values():
        a = areas.setdefault(b["area"], {"area": b["area"], "files": 0, "count": 0, "passed": 0, "failed": 0,
                                         "error": 0, "skipped": 0, "time": 0.0})
        a["files"] += 1
        for k in ("count", "passed", "failed", "error", "skipped"):
            a[k] += b[k]
        a["time"] = round(a["time"] + b["time"], 1)
    totals = {k: sum(a[k] for a in areas.values()) for k in ("count", "passed", "failed", "error", "skipped")}
    totals["time"] = round(sum(r["time"] for r in rows), 1)
    totals["files"] = len(by_file)
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %s"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        branch = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        head = branch = ""
    version = (ROOT / "agentos" / "VERSION").read_text().strip() if (ROOT / "agentos" / "VERSION").exists() else ""
    py = sys.version.split()[0]
    venv = ROOT / ".venv" / "bin" / "python"
    if venv.exists():       # the suite's own python, not the one building the report
        try:
            py = subprocess.run([str(venv), "--version"], capture_output=True, text=True,
                                timeout=10).stdout.split()[-1]
        except Exception:
            pass
    suite = ET.parse(junit).getroot()
    inner = suite.find("testsuite")
    suite = suite if suite.tag == "testsuite" else (inner if inner is not None else suite)
    ran_at = (suite.get("timestamp") or "")[:16].replace("T", " ")
    host = suite.get("hostname") or ""
    report = {
        "made_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "version": version, "commit": head, "branch": branch,
        "python": py, "ran_at": ran_at + (" UTC" if ran_at else ""), "host": host,
        "totals": totals,
        "areas": sorted(areas.values(), key=lambda a: -a["count"]),
        "files": sorted(by_file.values(), key=lambda b: (b["area"], b["file"])),
        "failures": [r for r in rows if r["status"] in ("failed", "error")],
        "findings": findings,
        "impact": impact,
        "slowest": sorted(rows, key=lambda r: -r["time"])[:25],
        "live": [{**h, **{k: live_runs[h["path"]][k] for k in ("status", "why", "seconds", "tail", "at")
                          if h["path"] in live_runs}} for h in live_harnesses()],
        "untested": untested_modules(files),
        "node_files": sorted(f for f, v in files.items() if v["node"]),
        "browser_files": sorted(f for f, v in files.items() if v["browser"]),
    }
    dest.write_text(json.dumps(report, indent=1))
    tests_out = dest.with_name("tests.json")
    tests_out.write_text("[\n" + ",\n".join(json.dumps({k: r[k] for k in ("area", "file", "name", "what", "status",
                                                                            "time", "msg")}
                                                       | ({"cause": r["cause"], "kind": r["kind"]} if "cause" in r else {}))
                                            for r in rows) + "\n]\n")
    print(f"{totals['count']} tests in {totals['files']} files: {totals['passed']} passed, "
          f"{totals['failed'] + totals['error']} failed, {totals['skipped']} skipped -> {dest}, {tests_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
