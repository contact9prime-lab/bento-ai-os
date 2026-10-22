"""A Pi's speech understood by its hub, on real servers: a hub and an edge machine set up from
it with an automatic key, linked over real mTLS. The hub's whisper.cpp is a stand-in that says
how many bytes it was given, so what arrived is checked, not assumed. In order:

  1. the edge, with nothing of its own to hear with, says its hub understands its speech
  2. the hub can't hear yet: the edge's kiosk gets that in one sentence, nothing worse
  3. the hub gets whisper.cpp: a recording posted to the EDGE's /api/speech/hear comes back as
     text the hub understood, with every byte; timed over 10 utterances
  4. revoking `speech.hear` on the hub stops it, in a sentence on the edge

    python hub_hear_run.py [WORKDIR] [--keep]
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
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="hear-e2e-"))
KEEP = "--keep" in sys.argv
ENV = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
       "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1", "AGENTOS_DISCOVER_UDP": "18641",
       "AGENTOS_DISCOVER_TARGETS": "127.255.255.255"}
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    ENV.pop(k, None)

# name, http, link, claim door, brain port
MACHINES = [("big-box", 8561, 8661, 0, 9461), ("pi-edge", 8562, 8662, 8762, None)]
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


def wav(seconds: float) -> bytes:
    import struct
    n = int(16000 * seconds)
    data = b"\x00\x01" * n
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def hear(name, body: bytes):
    req = urllib.request.Request(f"http://127.0.0.1:{m(name)[1]}/api/speech/hear?lang=en", data=body, method="POST",
                                 headers={"Content-Type": "audio/wav"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    say(f"work dir {WORK}")
    brain = subprocess.Popen([sys.executable, str(HERE / "zero_brain.py"), "9461"], env=ENV,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for x in MACHINES:
            config(*x)
        key = re.search(r"(bento-enroll-1\.\S+)", bento("big-box", "pool", "key", "edge", "--auto").stdout).group(1)
        start("big-box")
        start("pi-edge", {"AGENTOS_ENROLL": key})
        wait("the edge is set up", lambda: http("pi-edge", "GET", "/api/provision")[1]["this"]["claimed"], limit=60)
        wait("the edge joined", lambda: ledger("pi-edge", "provision.joined") or None, limit=60)
        st = http("pi-edge", "GET", "/api/face")[1].get("hear") or {}
        assert st.get("engine") == "hub", st
        step("1. the edge hears through its hub", line=st.get("line"), grant=[f"{k}:{p} {r}" for _, k, p, r, _s in
                                                                           grants("big-box", "speech.hear")])

        code, out = hear("pi-edge", wav(1.0))
        assert code == 400 and "can't understand speech yet" in out["error"], (code, out)
        step("2. a hub with nothing to hear with says so", answer=out["error"])

        stub = WORK / "whisper-cli"
        stub.write_text("#!/bin/sh\nfor a; do [ \"$prev\" = -f ] && f=\"$a\"; prev=\"$a\"; done\n"
                        "echo \"turn on the kitchen light ($(wc -c < \"$f\") bytes)\"\n")
        stub.chmod(0o755)
        (WORK / "ggml-base.en.bin").write_text("stand-in model")
        cfg = json.loads((home("big-box") / "config.json").read_text())
        cfg.setdefault("speech", {})["hear"] = {"whisper_bin": str(stub), "whisper_model": str(WORK / "ggml-base.en.bin")}
        (home("big-box") / "config.json").write_text(json.dumps(cfg, indent=1))
        for p in PROCS.values():
            pass
        PROCS["big-box"].terminate(); PROCS["big-box"].wait(15)
        start("big-box")
        times, body = [], wav(3.0)
        for _ in range(10):
            t0 = time.time()
            code, out = hear("pi-edge", body)
            times.append(time.time() - t0)
            assert code == 200 and f"({len(body)} bytes)" in out["text"], (code, out)
        times.sort()
        step("3. the hub understood the edge's recording, every byte of it",
             text=out["text"], recording=f"{len(body)} bytes (3 s of 16 kHz audio)",
             round_trip_ms=f"median {times[5]*1000:.0f}, fastest {times[0]*1000:.0f}, slowest {times[-1]*1000:.0f}")

        for gid, *_ in grants("big-box", "speech.hear"):
            r = bento("big-box", "grants", "revoke", gid)
            assert r.returncode == 0, r.stderr
        code, out = hear("pi-edge", wav(1.0))
        assert code == 400 and "Permissions" in out["error"], (code, out)
        step("4. revoked on the hub, refused in a sentence on the edge", answer=out["error"])
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
