"""Run the live end-to-end harnesses under packaging/dev, one after another, and record how each went.

    .venv/bin/python packaging/dev/test-report/live.py OUT/live.json [NAME ...]

Each run is a real `bento serve` (or several) on a throwaway home, with stand-in brains, phones and
machines; none touches ~/.agentos. A run passes when it exits 0 and its output carries no traceback
(walk.py also has to print empty FINDINGS). A run that needs what this machine lacks is recorded as not
run, with the reason, rather than started. build.py folds the result into the report.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv" / "bin" / "python")
DEV = ROOT / "packaging" / "dev"


def _have(*tools: str) -> str:
    missing = [t for t in tools if not shutil.which(t)]
    return ("needs " + ", ".join(missing)) if missing else ""


def _docker() -> str:
    if not shutil.which("docker"):
        return "needs Docker"
    try:
        ok = subprocess.run(["docker", "info"], capture_output=True, timeout=60).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        ok = False
    return "" if ok else "needs a running Docker daemon"


def _cpu_temp() -> str:
    """device_run.py reads and permits the Zero's CPU temperature, so it needs a sensor here."""
    sys.path.insert(0, str(ROOT))
    try:
        from agentos import hardware
        ok = any(i["id"] == "cpu.temp" for i in hardware._temperatures())
    except Exception:
        ok = False
    return "" if ok else "needs a CPU temperature sensor (a thermal zone, k10temp or coretemp)"


def _image(tag: str) -> str:
    """network-e2e's stand-in Pi is built on the image standby-e2e's run makes."""
    try:
        ok = subprocess.run(["docker", "image", "inspect", tag], capture_output=True, timeout=60).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        ok = False
    return "" if ok else f"needs the {tag} image, which the standby run builds"


def _uv_download() -> str:
    """Bento's image installs uv from astral.sh while it builds. A machine that cannot fetch it
    cannot build the image the standby, network and free-cloud runs start."""
    import urllib.request
    try:
        urllib.request.urlopen("https://astral.sh/uv/install.sh", timeout=20).close()
        return ""
    except Exception:
        return "needs to build Bento's image, which downloads uv from astral.sh, and this machine cannot reach it"


def _work(name: str) -> str:
    return tempfile.mkdtemp(prefix=f"bento-live-{name}-")


# name -> (path, command builder, precondition, timeout seconds)
RUNS = {
    "stitch-walk": ("stitch-e2e/walk.py", lambda w: [PY, str(DEV / "stitch-e2e/walk.py")],
                    lambda: "", 900),
    "pool": ("pool-e2e/run.py", lambda w: [PY, str(DEV / "pool-e2e/run.py"), w], lambda: "", 900),
    "provision": ("provision-e2e/run.py", lambda w: [PY, str(DEV / "provision-e2e/run.py"), w], lambda: "", 900),
    "zero": ("provision-e2e/zero_run.py", lambda w: [PY, str(DEV / "provision-e2e/zero_run.py"), w],
             lambda: "", 900),
    "zero-accounts": ("provision-e2e/zero_accounts_run.py",
                      lambda w: [PY, str(DEV / "provision-e2e/zero_accounts_run.py"), w], lambda: "", 900),
    "device-get-set": ("provision-e2e/device_run.py",
                       lambda w: [PY, str(DEV / "provision-e2e/device_run.py"), w], _cpu_temp, 900),
    "dhcp-moves": ("provision-e2e/dhcp_run.py", lambda w: [PY, str(DEV / "provision-e2e/dhcp_run.py"), w],
                   lambda: "", 900),
    "edge-code": ("provision-e2e/edge_code_run.py",
                  lambda w: [PY, str(DEV / "provision-e2e/edge_code_run.py"), w], lambda: _have("bwrap"), 900),
    "hub-hearing": ("provision-e2e/hub_hear_run.py",
                    lambda w: [PY, str(DEV / "provision-e2e/hub_hear_run.py"), w], lambda: "", 900),
    "install-over-ssh": ("provision-e2e/install_over_ssh.py",
                         lambda w: [PY, str(DEV / "provision-e2e/install_over_ssh.py"), w],
                         lambda: _have("sshd", "ssh") or ("needs root" if os.geteuid() else ""), 1500),
    "link-files": ("link-files-e2e/run.py", lambda w: [PY, str(DEV / "link-files-e2e/run.py"), w],
                   lambda: "", 900),
    "phone-steps": ("phone-steps-e2e/run.py", lambda w: [PY, str(DEV / "phone-steps-e2e/run.py"), w],
                    lambda: "", 600),
    "seal": ("seal-e2e/run.py", lambda w: [PY, str(DEV / "seal-e2e/run.py"), w],
             lambda: "" if Path("/opt/pw-browsers/chromium").exists() or shutil.which("chromium") else "needs Chromium", 900),
    "release": ("release-e2e/run.py", lambda w: [PY, str(DEV / "release-e2e/run.py"), w],
                lambda: "" if Path("/opt/pw-browsers/chromium").exists() or shutil.which("chromium") else "needs Chromium", 900),
    "sites": ("sites-e2e/run.py", lambda w: [PY, str(DEV / "sites-e2e/run.py"), w],
              lambda: "" if Path("/opt/pw-browsers/chromium").exists() or shutil.which("chromium") else "needs Chromium", 900),
    "warehouse": ("warehouse/run.py", lambda w: [PY, str(DEV / "warehouse/run.py"), w], lambda: "", 900),
    "active-sync": ("standby-e2e/active_sync.py", None, lambda: "", 900),
    "standby": ("standby-e2e/run.sh", lambda w: ["sh", str(DEV / "standby-e2e/run.sh")],
                lambda: _docker() or ("needs root" if os.geteuid() else "") or _uv_download(), 3000),
    "network": ("network-e2e/run.py", None, lambda: _docker() or _have("ssh") or _image("bento-standby-base") or _uv_download(), 1800),
    "handoff": ("handoff-e2e/run.js", lambda w: ["node", str(DEV / "handoff-e2e/run.js"), w],
                lambda: _have("node"), 900),
    "free-cloud": ("free-cloud/run.py", None, lambda: _docker() or _uv_download(), 1800),
    "sui-testbed": ("sui-testbed.sh", None, lambda: _have("sway", "grim"), 900),
}


def _with_fakes(cmd: list[str], fakes: list[list[str]], timeout: int, env: dict) -> subprocess.CompletedProcess:
    procs = [subprocess.Popen(f, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for f in fakes]
    time.sleep(2)
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    finally:
        for p in procs:
            p.terminate()


def run_one(name: str) -> dict:
    path, build, pre, timeout = RUNS[name]
    rec = {"name": name, "path": f"packaging/dev/{path}", "status": "not run", "why": "", "seconds": 0,
           "tail": ""}
    why = pre()
    if why:
        rec["why"] = why
        return rec
    w = _work(name)
    env = {**os.environ, "STANDBY_E2E_DIR": w}
    t0 = time.time()
    try:
        if name == "active-sync":
            p = _with_fakes([PY, str(DEV / "standby-e2e/active_sync.py")],
                            [[PY, str(DEV / "standby-e2e/fakes.py")]], timeout, env)
        elif name == "network":
            b = subprocess.run(["sh", str(DEV / "network-e2e/build.sh"), w], cwd=ROOT, capture_output=True,
                               text=True, timeout=1200, env=env)
            if b.returncode:
                rec.update(status="failed", why="the stand-in Pi's image did not build",
                           tail=(b.stdout + b.stderr)[-1500:], seconds=round(time.time() - t0))
                return rec
            p = subprocess.run([PY, str(DEV / "network-e2e/run.py"), w], cwd=ROOT, capture_output=True,
                               text=True, timeout=timeout, env=env)
        elif build is None:
            rec["why"] = "has no unattended entry point here"
            return rec
        else:
            p = subprocess.run(build(w), cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        rec.update(status="failed", why=f"did not finish in {timeout} s", seconds=round(time.time() - t0),
                   tail=((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes)
                         else (e.stdout or ""))[-1500:])
        return rec
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    rec["seconds"] = round(time.time() - t0)
    rec["tail"] = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", out)[-1800:]
    bad = []
    if p.returncode:
        bad.append(f"exited {p.returncode}")
    if "Traceback (most recent call last)" in out:
        bad.append("printed a traceback")
    if name in ("stitch-walk", "phone-steps", "sites", "seal", "release"):
        m = re.search(r"FINDINGS:\s*(\[[^\]]*\])", out, re.S)
        if not m:
            bad.append("printed no FINDINGS")
        elif json.loads(m.group(1)):
            bad.append("FINDINGS were not empty")
    rec["status"] = "failed" if bad else "passed"
    rec["why"] = "; ".join(bad)
    return rec


def main(argv: list[str]) -> int:
    dest = Path(argv[1])
    names = argv[2:] or list(RUNS)
    done = json.loads(dest.read_text()) if dest.exists() else {}
    for n in names:
        print(f"▸ {n} …", flush=True)
        rec = run_one(n)
        rec["at"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        done[n] = rec
        dest.write_text(json.dumps(done, indent=1))
        print(f"  {rec['status']}" + (f" ({rec['why']})" if rec["why"] else "") + f" in {rec['seconds']} s",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
