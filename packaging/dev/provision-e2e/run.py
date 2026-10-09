"""New machines turned on, heard, and set up from the leader: real servers on one box.

A leader (`bento serve` with a stand-in brain) and three stand-in Raspberry Pis, each a
fresh `bento serve` in its own home that has never been set up. Discovery is real UDP
broadcast on the box (127.255.255.255 on a port of its own, so a real LAN is not
touched), and every claim is real TLS. What it checks, in order:

  1. every Pi announces itself when it starts, and the leader hears each one ONCE
     (the toast a person would get), with its board and memory
  2. the third Pi was flashed with the community's automatic enrolment key, so the
     leader sets it up the moment it is heard, with no code and nobody pressing anything
  3. the other two are enabled together from the leader's list, each with the code
     shown on its own screen, one as a kiosk; a wrong code is refused first
  4. all three are members a few seconds later, each a finished setup with its agent
     and its profile, and the first one's screen step is ticked (kiosk)
  5. a Pi with no key of its own thinks with the leader's brain
  6. the ledger on both sides says what happened

    python run.py [WORKDIR] [--keep]
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="prov-e2e-"))
KEEP = "--keep" in sys.argv
ENV = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
       "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1",
       "AGENTOS_DISCOVER_UDP": "18620", "AGENTOS_DISCOVER_TARGETS": "127.255.255.255"}
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    ENV.pop(k, None)

# name, http, link, claim door, brain, pi board
MACHINES = [
    ("big-box", 8531, 8631, 0, 9431, ""),
    ("pi-one", 8532, 8632, 8732, None, "Raspberry Pi 5 Model B Rev 1.0"),
    ("pi-two", 8533, 8633, 8733, None, "Raspberry Pi 4 Model B Rev 1.5"),
    ("pi-three", 8534, 8634, 8734, None, "Raspberry Pi Zero 2 W Rev 1.0"),
]
PROCS: dict = {}
REPORT: dict = {"steps": []}


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def m(name):
    return next(x for x in MACHINES if x[0] == name)


def http(name, method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{m(name)[1]}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def home(name):
    return WORK / name


def config(name, http_port, link, door, brain, board):
    cfg = {"agent_name": "Aria", "pricing_skip": ["custom/fake-1"],
           "team": {"link_port": link, "machine_name": name}}
    if brain:
        cfg.update(setup_complete=True, default_model="custom/fake-1",
                   providers={"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{brain}/v1",
                                         "models": ["fake-1"]}})
    if door:
        cfg["provision"] = {"port": door}
    home(name).mkdir(parents=True, exist_ok=True)
    (home(name) / "config.json").write_text(json.dumps(cfg, indent=1))


def start(name, extra=None):
    x = m(name)
    env = {**ENV, "AGENTOS_HOME": str(home(name)), "AGENTOS_PI_MODEL": x[5], **(extra or {})}
    log = open(home(name) / "server.log", "a")
    PROCS[name] = subprocess.Popen([sys.executable, "-m", "agentos", "serve", "--port", str(x[1]),
                                    "--no-browser", "--if-running", "fail"],
                                   cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            if http(name, "GET", "/api/provision", timeout=3)[0] == 200:
                return round(time.time() - t0, 1)
        except Exception:
            pass
        time.sleep(0.4)
    raise SystemExit(f"{name} did not come up; see {home(name) / 'server.log'}")


def rss(name):
    try:
        for ln in open(f"/proc/{PROCS[name].pid}/status"):
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1]) // 1024
    except OSError:
        return 0


def wait(what, fn, limit=90, every=1.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        got = fn()
        if got:
            return round(time.time() - t0, 1), got
        time.sleep(every)
    raise SystemExit(f"timed out waiting for: {what}")


def step(title, **facts):
    say(f"✓ {title}" + "".join(f"\n     {k}: {v}" for k, v in facts.items()))
    REPORT["steps"].append({"step": title, **facts})


def ledger(name, prefix):
    con = sqlite3.connect(home(name) / "agentos.db")
    rows = con.execute("select action, coalesce(reason,'') || coalesce(detail,'') from audit "
                       "where action like ? order by rowid", (prefix + "%",)).fetchall()
    con.close()
    return rows


def main():
    say(f"work dir {WORK}")
    brain = subprocess.Popen([sys.executable, str(REPO / "packaging/dev/pool-e2e/fake_brain.py"), "9431",
                              "big-box's brain"], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for x in MACHINES:
            config(*x)
        up = {"big-box": start("big-box")}
        st, v = http("big-box", "POST", "/api/provision/key", {"label": "zero-touch Pis", "auto": True})
        assert st == 200, v
        key = v["key"]["text"]
        step("leader up, listening, with an automatic enrolment key",
             seconds=up["big-box"], watching=v["watching"], key_id=v["key"]["id"])

        t_on = time.time()
        for n in ("pi-one", "pi-two"):
            up[n] = start(n)
        up["pi-three"] = start("pi-three", {"AGENTOS_ENROLL": key})
        codes = {}
        for n in ("pi-one", "pi-two"):
            me = http(n, "GET", "/api/provision")[1]["this"]
            assert me["waiting"] and len(me["pin"]) == 6, (n, me)
            codes[n] = me["pin"]
        me = http("pi-three", "GET", "/api/provision")[1]["this"]
        assert me["pin"] == "" and me["key_id"], "a keyed Pi shows no code"   # it may be set up already
        took, seen = wait("the leader hears all three", lambda: (lambda s: s if len(s) >= 3 else None)(
            http("big-box", "GET", "/api/provision")[1]["seen"]), limit=40)
        heard = [r for r in ledger("big-box", "provision.seen")]
        step("1. three Pis turned on and announced themselves; the leader heard each once",
             heard_within_s=round(time.time() - t_on, 1), servers_up_s=up,
             seen=[f"{e['name']}: {e['hw']['board']}, {e['hw']['ram_mb']} MB, id {e['id']}" for e in seen],
             asked_once_each=len(heard))
        assert len(heard) == 3

        took, me3 = wait("pi-three is set up by its key", lambda: (lambda t: t if t["claimed"] else None)(
            http("pi-three", "GET", "/api/provision")[1]["this"]), limit=40)
        step("2. pi-three carried the automatic key and was set up with nobody pressing anything",
             after_s=took, by=me3["claimed"].get("by"), how=me3["claimed"].get("how"))

        fp = {e["name"]: e["fp"] for e in seen}
        st, bad = http("big-box", "POST", "/api/provision/enable",
                       {"machines": [{"fp": fp["pi-one"], "code": "000000" if codes["pi-one"] != "000000" else "111111"}]})
        assert not bad["results"][0]["ok"], bad
        t0 = time.time()
        st, r = http("big-box", "POST", "/api/provision/enable", {
            "machines": [{"fp": fp["pi-one"], "code": codes["pi-one"], "name": "kitchen"},
                         {"fp": fp["pi-two"], "code": codes["pi-two"]}],
            "profile": {"kiosk": True, "buddy": "on", "agent_name": "Pip", "lite": True}})
        assert st == 200 and all(x["ok"] for x in r["results"]), r
        step("3. pi-one and pi-two enabled together with the codes from their screens",
             wrong_code=bad["results"][0]["error"], seconds=round(time.time() - t0, 2),
             results=[f"{x['name']} ({x['how']})" for x in r["results"]])

        def members():
            ms = http("big-box", "GET", "/api/pool")[1].get("machines") or []
            return ms if sum(1 for x in ms if x.get("state") == "member" and not x.get("here")) >= 3 else None
        took, ms = wait("all three are members", members, limit=60)
        one = json.loads((home("pi-one") / "config.json").read_text())
        ob = http("pi-one", "GET", "/api/onboarding")[1]
        screen = next(s for s in ob["steps"] if s["id"] == "screen")
        step("4. all three are members, each a finished setup with its own agent",
             members_after_s=took, machines=[f"{x['name']}: {x.get('state')}" for x in ms],
             pi_one={"name": one["team"]["machine_name"], "agent": one["agent_name"],
                     "kiosk": one["face"]["kiosk"], "buddy": one["face"]["buddy"], "profile": one["profile"],
                     "model": one["default_model"], "setup_complete": one["setup_complete"]},
             screen_step=f"{screen['status']} ({screen['detail']})")
        assert one["face"]["kiosk"] and screen["status"] == "done"

        t0 = time.time()
        st, ans = http("pi-two", "POST", "/api/chat", {"text": "good morning from the garage"}, timeout=300)
        assert st == 200 and (ans.get("content") or "").startswith("big-box's brain heard"), ans
        step("5. a Pi with no key thinks with the leader's brain", answer=ans["content"],
             seconds=round(time.time() - t0, 2))

        step("6. the ledger on both sides",
             leader=[f"{a}: {d[:90]}" for a, d in ledger("big-box", "provision.")],
             pi_one=[f"{a}: {d[:90]}" for a, d in ledger("pi-one", "provision.")],
             rss_mb={n: rss(n) for n in PROCS})
        REPORT["ok"] = True
    finally:
        (WORK / "report.json").write_text(json.dumps(REPORT, indent=1))
        if not KEEP:
            for p in list(PROCS.values()) + [brain]:
                p.terminate()
        else:
            say("left running: " + ", ".join(f"{n} http://127.0.0.1:{m(n)[1]}" for n in PROCS))


if __name__ == "__main__":
    main()
