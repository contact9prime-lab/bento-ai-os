"""Small code on the edge, big code on its hub, on real servers: a hub (`bento serve` with a
stand-in brain) and an edge machine set up from it with an automatic key, linked over real
mTLS. What it checks, in order:

  1. the hub sets the edge up when it is heard, and writes its consent to run code for it
     (a `code.run` grant, a `provision.code` ledger row)
  2. small code runs on the edge (`/api/tool` run_python), nothing goes to the hub
  3. code that runs past the edge's limit is handed to the hub with its folder, runs in the
     hub's jail (no network, the hub's home not visible) and its files come back into that
     folder on the edge
  4. where="hub" sends it straight there
  5. revoking the grant on the hub stops it, in a sentence on the edge
  6. the ledger on the hub has a row per run

    python edge_code_run.py [WORKDIR] [--keep]
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="edge-e2e-"))
KEEP = "--keep" in sys.argv
ENV = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
       "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1", "AGENTOS_DISCOVER_UDP": "18631",
       "AGENTOS_DISCOVER_TARGETS": "127.255.255.255"}
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    ENV.pop(k, None)

# name, http, link, claim door, brain port
MACHINES = [("big-box", 8551, 8651, 0, 9451), ("pi-edge", 8552, 8652, 8752, None)]
PROCS: dict = {}
REPORT: dict = {"steps": []}


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def m(name):
    return next(x for x in MACHINES if x[0] == name)


def home(name):
    return WORK / name


def http(name, method, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{m(name)[1]}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def env_of(name, extra=None):
    return {**ENV, "AGENTOS_HOME": str(home(name)),
            "AGENTOS_PI_MODEL": "Raspberry Pi 3 Model B Plus Rev 1.3" if name == "pi-edge" else "",
            **({"AGENTOS_EDGE_SECONDS": "2"} if name == "pi-edge" else {}), **(extra or {})}


def config(name, http_port, link, door, brain):
    cfg = {"agent_name": "Aria", "pricing_skip": ["custom/fake-1"], "autonomy": "full",
           "team": {"link_port": link, "machine_name": name}, "workspace": str(home(name) / "workspace")}
    if brain:
        cfg.update(setup_complete=True, default_model="custom/fake-1",
                   providers={"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{brain}/v1",
                                         "models": ["fake-1"]}})
    if door:
        cfg["provision"] = {"port": door}
    home(name).mkdir(parents=True, exist_ok=True)
    (home(name) / "config.json").write_text(json.dumps(cfg, indent=1))


def bento(name, *args, extra=None):
    return subprocess.run([sys.executable, "-m", "agentos", *args], cwd=REPO, env=env_of(name, extra),
                          capture_output=True, text=True, timeout=120)


def start(name, extra=None):
    log = open(home(name) / "server.log", "a")
    PROCS[name] = subprocess.Popen([sys.executable, "-m", "agentos", "serve", "--port", str(m(name)[1]),
                                    "--no-browser", "--if-running", "fail"],
                                   cwd=REPO, env=env_of(name, extra), stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            if http(name, "GET", "/api/provision", timeout=3)[0] == 200:
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise SystemExit(f"{name} did not come up; see {home(name) / 'server.log'}")


def wait(what, fn, limit=90, every=1.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        got = fn()
        if got:
            return got
        time.sleep(every)
    raise SystemExit(f"timed out waiting for: {what}")


def step(title, **facts):
    say(f"✓ {title}" + "".join(f"\n     {k}: {v}" for k, v in facts.items()))
    REPORT["steps"].append({"step": title, **facts})


def ledger(name, action):
    con = sqlite3.connect(home(name) / "agentos.db")
    rows = con.execute("select coalesce(reason,'') || coalesce(detail,'') from audit where action = ? order by rowid",
                       (action,)).fetchall()
    con.close()
    return [r[0] for r in rows]


def grants(name, action):
    con = sqlite3.connect(home(name) / "agentos.db")
    rows = con.execute("select id, principal_kind, principal_id, resource, source from grants "
                       "where action = ? and revoked_at is null", (action,)).fetchall()
    con.close()
    return rows


def run_python(name, **args):
    st, out = http(name, "POST", "/api/tool", {"name": "run_python", "args": args})
    assert st == 200, (st, out)
    return str(out.get("result") or out.get("output") or out)


def main():
    say(f"work dir {WORK}")
    brain = subprocess.Popen([sys.executable, str(HERE / "zero_brain.py"), "9451"], env=ENV,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for x in MACHINES:
            config(*x)
        key = re.search(r"(bento-enroll-1\.\S+)", bento("big-box", "pool", "key", "edge", "--auto").stdout).group(1)
        start("big-box")
        start("pi-edge", {"AGENTOS_ENROLL": key})
        wait("the edge is set up", lambda: http("pi-edge", "GET", "/api/provision")[1]["this"]["claimed"], limit=60)
        wait("the edge joined", lambda: [r for r in ledger("pi-edge", "provision.joined")] or None, limit=60)
        g = wait("the hub's consent", lambda: grants("big-box", "code.run") or None, limit=20)
        step("1. the hub set the edge up and may run code for it",
             grant=[f"{k}:{p} {r} ({s})" for _, k, p, r, s in g], ledger=ledger("big-box", "provision.code"))

        ws = home("pi-edge") / "workspace"
        (ws / "job" / "data").mkdir(parents=True, exist_ok=True)
        (ws / "job" / "data" / "prices.csv").write_text("day,price\n1,10\n2,12\n3,9\n")
        t0 = time.time()
        out = run_python("pi-edge", code="print(sum(range(10)))", folder="job")
        assert out.strip().endswith("45") and "ran on the hub" not in out, out
        step("2. small code ran on the edge", output=out.strip(), seconds=round(time.time() - t0, 1),
             hub_runs=len(ledger("big-box", "edge.code")))

        code = ("import csv, os, socket, time\n"
                "time.sleep(4)   # past the edge's 2 s here, fine on the hub\n"
                "rows = list(csv.DictReader(open('data/prices.csv')))\n"
                "avg = sum(float(r['price']) for r in rows) / len(rows)\n"
                "os.makedirs('out', exist_ok=True)\n"
                "open('out/report.txt', 'w').write(f'average {avg:.2f} over {len(rows)} days\\n')\n"
                "print('average', round(avg, 2))\n"
                f"print('hub home visible:', os.path.exists({str(home('big-box'))!r}))\n"
                "try:\n    socket.create_connection(('1.1.1.1', 80), 2); print('network: yes')\n"
                "except OSError:\n    print('network: no')\n")
        t0 = time.time()
        out = run_python("pi-edge", code=code, folder="job")
        report = ws / "job" / "out" / "report.txt"
        assert "ran on the hub big-box" in out and report.exists(), out
        assert "network: no" in out and "hub home visible: False" in out, out
        step("3. code past the edge's limit ran on the hub, sandboxed, and its file came back",
             output=out.strip().splitlines(), file_back=f"{report.relative_to(WORK)}: {report.read_text().strip()}",
             seconds=round(time.time() - t0, 1))

        out = run_python("pi-edge", code="import platform; print('ran on', platform.node())", where="hub")
        assert "ran on the hub big-box because you asked for it" in out and "ran on sandbox" in out, out
        step("4. where='hub' sends it straight there", output=out.strip().splitlines())

        for gid, *_ in grants("big-box", "code.run"):
            r = bento("big-box", "grants", "revoke", gid)       # what Permissions does, from a terminal
            assert r.returncode == 0, r.stderr
        out = run_python("pi-edge", code="print(1)", where="hub")
        assert "does not run code" in out and "Permissions" in out, out
        step("5. revoked on the hub, refused in a sentence on the edge", output=out.strip())

        step("6. the hub's ledger", rows=ledger("big-box", "edge.code"))
        (WORK / "report.json").write_text(json.dumps(REPORT, indent=1))
        say(f"all steps passed; report in {WORK / 'report.json'}")
    finally:
        for p in PROCS.values():
            p.terminate()
        brain.terminate()
        for p in PROCS.values():
            try:
                p.wait(10)
            except Exception:
                p.kill()
        if not KEEP:
            import shutil
            shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
