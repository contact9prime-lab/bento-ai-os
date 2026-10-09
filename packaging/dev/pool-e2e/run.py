"""A community of three real Bento servers on one box: a leader and two small machines.

Each is `bento serve` in its own home with its own link door, linked the way a person
links them (Ask on one, Approve on the other), then formed into a community through the
same routes the Settings group uses. Two stand-in brains (fake_brain.py) say whose key
answered. What it checks, in order:

  1. the kitchen Pi has no key, and thinks with the leader's brain
  2. the leader splits a bigger task, one piece per member, at once
  3. a note shared on one Pi reaches the other through the leader
  4. the leader's ledger and usage carry the members' calls
  5. the leader is killed: the garage Pi (whose admin agreed to lead) takes over,
     and the kitchen Pi follows it and thinks with ITS brain now
  6. the old leader comes back and steps down

    python run.py [WORKDIR] [--keep]      # --keep leaves the three servers running
"""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="pool-e2e-"))
KEEP = "--keep" in sys.argv
ENV = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
       "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1"}
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    ENV.pop(k, None)

MACHINES = [  # name, http port, link port, brain port (None: no key of its own), lite
    ("big-box", 8511, 8611, 9411, False),
    ("pi-kitchen", 8512, 8612, None, True),
    ("pi-garage", 8513, 8613, 9412, True),
]
PROCS: dict = {}
REPORT: dict = {"steps": []}


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def http(port, method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def home(name):
    return WORK / name


def config(name, port, tport, brain, lite):
    cfg = {"setup_complete": True, "agent_name": "Aria", "autonomy": "full",
           "profile": "lite" if lite else "full",
           "team": {"listen": True, "link_port": tport, "machine_name": name},
           "default_model": "custom/fake-1" if brain else "", "pricing_skip": ["custom/fake-1"]}
    if brain:
        cfg["providers"] = {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{brain}/v1",
                                       "models": ["fake-1"]}}
    h = home(name)
    h.mkdir(parents=True, exist_ok=True)
    (h / "config.json").write_text(json.dumps(cfg, indent=1))


def start(name):
    _, port, *_ = next(m for m in MACHINES if m[0] == name)
    log = open(home(name) / "server.log", "a")
    PROCS[name] = subprocess.Popen([sys.executable, "-m", "agentos", "serve", "--port", str(port),
                                    "--no-browser", "--if-running", "fail"],
                                   cwd=REPO, env={**ENV, "AGENTOS_HOME": str(home(name))},
                                   stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            if http(port, "GET", "/api/pool", timeout=3)[0] == 200:
                return time.time() - t0
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{name} did not come up; see {home(name) / 'server.log'}")


def rss(name):
    try:
        for ln in open(f"/proc/{PROCS[name].pid}/status"):
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1]) // 1024
    except OSError:
        return 0


def port(name):
    return next(m for m in MACHINES if m[0] == name)[1]


def link(member, leader="big-box"):
    tport = next(m for m in MACHINES if m[0] == leader)[2]
    st, r = http(port(member), "POST", "/api/team/links/request", {"address": f"127.0.0.1:{tport}"})
    assert st == 200, (member, r)
    sas = r["request"]["sas"]
    for _ in range(40):
        inc = http(port(leader), "GET", "/api/team/links")[1].get("incoming") or []
        if inc:
            break
        time.sleep(0.5)
    assert inc[0]["sas"] == sas, "both screens show the same six digits"
    st, r = http(port(leader), "POST", f"/api/team/links/requests/{inc[0]['id']}/approve", {})
    assert st == 200, r
    for _ in range(40):
        links = http(port(member), "GET", "/api/team/links")[1].get("links") or []
        if links:
            return links[0]["label"]
        time.sleep(0.5)
    raise SystemExit(f"{member} never heard its link approved")


def pool(name):
    return http(port(name), "GET", "/api/pool")[1]


def wait(what, fn, limit=120, every=2):
    t0 = time.time()
    while time.time() - t0 < limit:
        got = fn()
        if got:
            return time.time() - t0, got
        time.sleep(every)
    raise SystemExit(f"timed out waiting for: {what}")


def chat(name, text):
    st, r = http(port(name), "POST", "/api/chat", {"text": text}, timeout=300)
    assert st == 200, (name, r)
    return r.get("content") or ""


def step(title, **facts):
    say(f"✓ {title}" + "".join(f"\n     {k}: {v}" for k, v in facts.items()))
    REPORT["steps"].append({"step": title, **facts})


def main():
    say(f"work dir {WORK}")
    brains = [subprocess.Popen([sys.executable, str(HERE / "fake_brain.py"), str(p), n], env=ENV,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
              for p, n in ((9411, "big-box's brain"), (9412, "pi-garage's brain"))]
    try:
        for m in MACHINES:
            config(*m)
        ups = {m[0]: round(start(m[0]), 1) for m in MACHINES}
        step("three servers up", seconds=ups, rss_mb={n: rss(n) for n in PROCS})

        labels = {n: link(n) for n in ("pi-kitchen", "pi-garage")}
        step("both Pis linked to big-box by Ask and Approve", labels=labels)

        assert http(port("big-box"), "POST", "/api/pool/create", {"name": "Home"})[0] == 200
        assert http(port("pi-garage"), "PUT", "/api/pool", {"lead_ok": True})[0] == 200
        st, r = http(port("pi-kitchen"), "POST", "/api/pool/join", {"label": labels["pi-kitchen"]})
        assert st == 200 and r["role"] == "pending" and r["using_brain"], r
        st, r = http(port("pi-garage"), "POST", "/api/pool/join", {"label": labels["pi-garage"], "use_brain": False})
        assert st == 200, r
        pend = pool("big-box")["pending"]
        assert {p["name"] for p in pend} == {"pi-kitchen", "pi-garage"}, pend
        for p in pend:
            assert http(port("big-box"), "POST", "/api/pool/approve", {"who": p["fp"]})[0] == 200
        took, _ = wait("both Pis are members", lambda: all(pool(n)["role"] == "member" for n in ("pi-kitchen", "pi-garage")))
        step("community 'Home' formed", heard_back_in_s=round(took, 1),
             line=pool("big-box")["line"], kitchen_sees=[m["name"] for m in pool("pi-kitchen")["machines"]])

        t0 = time.time()
        ans = chat("pi-kitchen", "good morning from the kitchen")
        assert ans.startswith("big-box's brain heard"), ans
        step("1. the kitchen Pi has no key and thinks with the leader's brain",
             answer=ans, seconds=round(time.time() - t0, 2))

        t0 = time.time()
        ans = chat("big-box", "split: count the jars in the pantry | read the garage thermometer")
        assert "pi-kitchen" in ans and "pi-garage" in ans, ans
        step("2. the leader split a bigger task across the members", seconds=round(time.time() - t0, 2),
             answer=ans.replace("\n", " ⏎ ")[:400])

        chat("pi-garage", "share: the garage door sticks when it is cold")
        took, _ = wait("the note reaches the kitchen", lambda: any(
            "garage door" in n["content"] for n in http(port("pi-kitchen"), "GET", "/api/pool/notes")[1]["notes"]))
        ans = chat("pi-kitchen", "what does the community know about garage door?")
        assert "sticks when it is cold" in ans, ans
        step("3. a note shared on one Pi reached the other through the leader",
             reached_in_s=round(took, 1), kitchen_agent=ans.replace("\n", " ⏎ ")[:300])

        con = sqlite3.connect(home("big-box") / "agentos.db")
        led = con.execute("select count(*) from audit where principal_kind='pool' and action='model.use' "
                          "and effect='allow'").fetchone()[0]
        use = con.execute("select count(*), coalesce(sum(tokens_in),0), coalesce(sum(tokens_out),0) "
                          "from usage where surface='pool'").fetchone()
        con.close()
        assert led > 0 and use[0] > 0
        step("4. the members' thinking is on the leader's ledger and usage",
             ledger_rows=led, usage_rows=use[0], tokens_in=use[1], tokens_out=use[2],
             rss_mb={n: rss(n) for n in PROCS})

        say("killing big-box (the leader) …")
        PROCS["big-box"].send_signal(signal.SIGKILL)
        PROCS["big-box"].wait()
        t_kill = time.time()
        took, _ = wait("pi-garage takes over", lambda: pool("pi-garage")["role"] == "leader", limit=200, every=3)
        took2, _ = wait("pi-kitchen follows it", lambda: (pool("pi-kitchen")["leader"] or {}).get("name") == "pi-garage",
                        limit=120, every=3)
        ans = chat("pi-kitchen", "are you still there?")
        assert ans.startswith("pi-garage's brain heard"), ans
        step("5. the leader went away: pi-garage took over and the kitchen follows it",
             took_over_after_s=round(took, 1), kitchen_followed_after_s=round(time.time() - t_kill, 1),
             term=pool("pi-garage")["term"], kitchen_answer=ans)

        up = start("big-box")
        took, _ = wait("big-box steps down", lambda: pool("big-box")["role"] == "member", limit=120, every=2)
        v = pool("big-box")
        assert v["leader"]["name"] == "pi-garage", v
        step("6. the old leader came back and stepped down", restarted_in_s=round(up, 1),
             stepped_down_after_s=round(took, 1), now=v["line"], rss_mb={n: rss(n) for n in PROCS})
        REPORT["ok"] = True
    finally:
        (WORK / "report.json").write_text(json.dumps(REPORT, indent=1))
        if not KEEP:
            for p in list(PROCS.values()) + brains:
                p.terminate()
        else:
            say("left running: " + ", ".join(f"{n} http://127.0.0.1:{port(n)}" for n in PROCS))


if __name__ == "__main__":
    main()
