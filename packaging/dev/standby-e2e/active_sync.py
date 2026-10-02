# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Active sync, end to end, with no Docker: two real Bento servers on this machine (the
laptop and a "cloud", each with its own $HOME) paired over HTTP, a fake provider for the
chat. What it measures:

  1. how long a chat message, a memory, a settings change and a workspace file take to
     reach the cloud with active sync on;
  2. what an idle laptop sends (nothing, if no table churns on its own);
  3. the laptop killed with SIGKILL right after a chat: the cloud takes over with that chat
     in it, and every table matches what the laptop held;
  4. a clean shutdown (SIGTERM) in copies mode sends a last copy, and in active-sync mode a
     last update.

    .venv/bin/python packaging/dev/standby-e2e/fakes.py &      # the fake provider
    .venv/bin/python packaging/dev/standby-e2e/active_sync.py
"""
import json, os, shutil, signal, sqlite3, subprocess, time
from pathlib import Path
import httpx
from h import E, REPO, LHOME, LAG, LPORT, LURL, HOSTIP, say, lenv, laptop_start, laptop_kill, laptop_pid, wait_up, lget, lpost, chat, counts_local, diff

CHOME = E / "cloud-user"
CAG = CHOME / ".agentos"
CPORT = 8973
CURL_ = f"http://127.0.0.1:{CPORT}"


def cenv():
    env = lenv()
    env["HOME"] = str(CHOME)
    return env


def cloud_start():
    p = subprocess.Popen([f"{REPO}/.venv/bin/python", "-m", "agentos", "serve", "--no-browser", "--port", str(CPORT),
                          "--if-running=fail"], cwd=REPO, env=cenv(), stdout=open(E / "cloud-local.log", "a"),
                         stderr=subprocess.STDOUT, start_new_session=True, stdin=subprocess.DEVNULL)
    (E / "cloud-local.pid").write_text(str(p.pid))
    wait_up(CURL_)
    return p


def cloud_kill():
    try:
        pid = int((E / "cloud-local.pid").read_text())
        os.killpg(pid, signal.SIGKILL)
    except Exception:
        pass
    time.sleep(1)


def cstatus():
    return httpx.get(CURL_ + "/api/standby", timeout=10).json()


def lstatus():
    return lget("/api/standby").json()


def wait_for(fn, timeout=60, step=0.2):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v:
            return time.time() - t, v
        time.sleep(step)
    return None, None


def cpu_seconds(pid):
    f = open(f"/proc/{pid}/stat").read().split()
    return (int(f[13]) + int(f[14])) / os.sysconf("SC_CLK_TCK")


ONLY_SHUTDOWN = os.environ.get("ONLY_SHUTDOWN") == "1"
# ---- two fresh machines ------------------------------------------------------------------
laptop_kill()
cloud_kill()
for h in (LHOME, CHOME):
    shutil.rmtree(h, ignore_errors=True)
LAG.mkdir(parents=True)
CAG.mkdir(parents=True)
(LHOME / "AgentOS").mkdir()
cfg = {"setup_complete": True, "agent_name": "Aria", "engine": "aria", "default_model": "custom/fake-1",
       "providers": {"custom": {"enabled": True, "base_url": f"http://{HOSTIP}:9301/v1", "api_key": "", "models": ["fake-1"]}},
       "autonomy": "balanced", "pricing_skip": ["custom/fake-1"], "workspace": str(LHOME / "AgentOS")}
(LAG / "config.json").write_text(json.dumps(cfg))
(CAG / "config.json").write_text(json.dumps({"setup_complete": True, "agent_name": "Cloud"}))


# ---- 4. a clean shutdown sends what is left ---------------------------------------------
def shutdown_checks():
    def fresh_pair(mode):
        laptop_kill(); cloud_kill()
        for h in (LHOME, CHOME):
            shutil.rmtree(h, ignore_errors=True)
        LAG.mkdir(parents=True); CAG.mkdir(parents=True); (LHOME / "AgentOS").mkdir()
        (LAG / "config.json").write_text(json.dumps(cfg))
        (CAG / "config.json").write_text(json.dumps({"setup_complete": True, "agent_name": "Cloud"}))
        laptop_start(); cloud_start()
        r = subprocess.run([f"{REPO}/.venv/bin/python", "-m", "agentos", "standby", "wait"], cwd=REPO, env=cenv(),
                           capture_output=True, text=True)
        code = [w for w in r.stdout.split() if len(w) == 9 and w[4] == "-"][0]
        lpost("/api/standby/pair", json={"url": CURL_, "code": code})
        cloud_kill(); cloud_start()
        if mode == "active":
            lpost("/api/standby/settings", json={"sync": "active"})
        wait_for(lambda: lstatus().get("last_push"), 90)


    for mode in ("copies", "active"):
        fresh_pair(mode)
        time.sleep(3)
        # idle cost, for the footprint note
        time.sleep(5)
        idle = int(os.environ.get("IDLE_S", "60"))
        c0 = cpu_seconds(laptop_pid()); time.sleep(idle); c1 = cpu_seconds(laptop_pid())
        say(f"[{mode}] idle laptop CPU {(c1 - c0) / idle * 100:.2f}% of a core")
        s0 = cstatus()
        chat(LURL, f"said just before a clean shutdown ({mode})")
        t0 = time.time()
        os.kill(laptop_pid(), signal.SIGTERM)
        for _ in range(300):
            try:
                if open(f"/proc/{laptop_pid()}/stat").read().split()[2] == "Z":
                    break                      # exited; this script is its parent and has not reaped it
                time.sleep(0.1)
            except FileNotFoundError:
                break
        s1 = cstatus()
        key = "copy_at" if mode == "copies" else "update_at"
        sent = s1.get(key, 0) > max(s0.get(key, 0), t0 - 1)
        say(f"[{mode}] SIGTERM: the cloud's {key} moved: {sent} ({time.time() - t0:.1f}s to stop)")
        assert sent, f"no last {key} on shutdown in {mode} mode"
    laptop_kill(); cloud_kill()


if ONLY_SHUTDOWN:
    shutdown_checks()
    raise SystemExit(0)
laptop_start()
cloud_start()
say("both up")
r = subprocess.run([f"{REPO}/.venv/bin/python", "-m", "agentos", "standby", "wait"], cwd=REPO, env=cenv(),
                   capture_output=True, text=True)
code = [w for w in r.stdout.split() if len(w) == 9 and w[4] == "-"][0]
pr = lpost("/api/standby/pair", json={"url": CURL_, "code": code})
say("paired:", pr.status_code, pr.json().get("peer_host"))
# the cloud's gate needs a restart to stand by; a fresh `serve` reads the pairing at start
cloud_kill(); cloud_start()
cid, ans = chat(LURL, "first chat, before active sync")
say("chat 1:", ans[:50])
s = lpost("/api/standby/settings", json={"sync": "active"}).json()
say("active sync:", s.get("sync"))
dt, _ = wait_for(lambda: lstatus().get("sync_at"), 60)
say(f"first send (a full copy to build on) after {dt:.1f}s; copy {lstatus().get('last_push_bytes')} bytes")

# ---- 1. how long things take to arrive -----------------------------------------------------
results = {}


def arrives(label, act, word):
    n0 = cstatus().get("update_n", 0)
    t0 = time.time()
    act()
    dt, st = wait_for(lambda: (lambda s: s if s.get("update_n", 0) > n0 and any(
        word in ", ".join(f.get("changes") or []) for f in s.get("feed", [])) else None)(cstatus()), 30)
    results[label] = dt
    say(f"{label}: on the cloud {dt:.2f}s after it happened" if dt else f"{label}: NOT seen in 30s")
    return st


st = arrives("chat message", lambda: chat(LURL, "second chat, with active sync"), "chat message")
say("  the cloud's feed:", st["feed"][0]["changes"] if st else None)
arrives("memory", lambda: lpost("/api/memories", json={"content": "Piyush prefers short answers"}), "memor")
def change_settings():
    c = json.loads((LAG / "config.json").read_text())
    c["agent_name"] = "Aria Two"
    (LAG / "config.json").write_text(json.dumps(c))
arrives("settings", change_settings, "settings")
arrives("workspace file", lambda: (LHOME / "AgentOS" / "deck.md").write_text("made on the laptop"), "workspace file")
def change_brain():
    c = json.loads((LAG / "config.json").read_text())
    c["default_model"] = "custom/fake-2"
    (LAG / "config.json").write_text(json.dumps(c))
arrives("the brain (meta)", change_brain, "brain changed")

# ---- 2. what an idle laptop sends --------------------------------------------------------
time.sleep(5)
n0, c0 = cstatus().get("update_n", 0), cpu_seconds(laptop_pid())
time.sleep(60)
n1, c1 = cstatus().get("update_n", 0), cpu_seconds(laptop_pid())
say(f"idle 60s: {n1 - n0} updates sent, laptop CPU {c1 - c0:.2f}s ({(c1 - c0) / 60 * 100:.2f}% of a core)")
feed = cstatus().get("feed", [])
if n1 > n0:
    say("  idle updates held:", [f.get("changes") for f in feed[:n1 - n0]])
rss = int([l for l in open(f"/proc/{laptop_pid()}/status") if l.startswith("VmRSS")][0].split()[1]) // 1024
say(f"laptop RSS {rss} MB")

# ---- 3. killed right after a chat ---------------------------------------------------------
chat(LURL, "the last words before the lid closed")
time.sleep(3)                        # the next look (2 s) and its send
before = counts_local(LAG)
laptop_kill()
say("laptop killed with SIGKILL, 3 s after its last chat")
subprocess.run([f"{REPO}/.venv/bin/python", "-c",
                "from agentos import standby as s; st=s.load(); st['last_beat']-=10000; s.save(st)"],
               cwd=REPO, env=cenv(), check=True)
dt, _ = wait_for(lambda: cstatus().get("active"), 60, 1)
say(f"cloud took over {dt:.0f}s after the grace was pushed back; replayed: {cstatus().get('replayed')}")
cloud_kill(); cloud_start()
after = counts_local(CAG)
real, noisy = diff(before, after, "laptop", "cloud")
real = [x for x in real if "_bento_sync" not in x]   # the journal lives on the laptop only
say("tables that differ (laptop at kill vs cloud after takeover):", real or "none", "| noisy:", len(noisy))
con = sqlite3.connect(CAG / "agentos.db")
titles = [r[0] for r in con.execute("select content from messages where role='user' order by created_at")]
con.close()
say("the cloud's user messages:", titles)
assert "the last words before the lid closed" in titles, "the last chat did not make it"
say("workspace file on the cloud:", (CHOME / "AgentOS" / "deck.md").exists() or list((CHOME).glob("**/deck.md")))
say("RESULTS", json.dumps({k: round(v, 2) if v else None for k, v in results.items()}))
cloud_kill()



shutdown_checks()
