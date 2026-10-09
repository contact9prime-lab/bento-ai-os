# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Helpers for the cloud-standby end-to-end run (see run.sh).

The laptop is this checkout, run as a process with its own $HOME; the cloud is the real
Docker image with its entrypoint, /data volume and passphrase. Both talk to a fake
OpenAI-compatible provider and a fake Telegram (fakes.py) on this host's address.
"""
import json, os, signal, sqlite3, subprocess, sys, time, glob
from pathlib import Path
import httpx
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + "," + (os.environ.get("STANDBY_E2E_HOSTIP") or subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()[0]); os.environ["no_proxy"] = os.environ["NO_PROXY"]

REPO = str(Path(__file__).resolve().parents[3])
# everything the run writes (two homes, logs, pid files) lives here, never in the checkout
E = Path(os.environ.get("STANDBY_E2E_DIR", "/tmp/bento-standby-e2e"))
E.mkdir(parents=True, exist_ok=True)
LHOME = E / "laptop-user"            # the laptop's $HOME; its Bento home is $HOME/.agentos
LAG = LHOME / ".agentos"
LPORT = 8971
LURL = f"http://127.0.0.1:{LPORT}"
HOSTIP = os.environ.get("STANDBY_E2E_HOSTIP") or subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()[0]
CPORT = 8972
CURL = f"http://{HOSTIP}:{CPORT}"
CPASS = "cloud-door-passphrase-123"
CNAME = "bento-cloud"
IMAGE = os.environ.get("STANDBY_E2E_IMAGE", "bento-standby-test")
T0 = time.time()

def say(*a):
    print(f"[{time.time()-T0:7.1f}s]", *a, flush=True)

def lenv():
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTOS_")}
    env.update(HOME=str(LHOME), AGENTOS_TELEGRAM_API=f"http://{HOSTIP}:9302/A", AGENTOS_VAULT_KEYRING="0",
               NO_PROXY=os.environ.get("NO_PROXY", "") + f",{HOSTIP}", no_proxy=os.environ.get("no_proxy", "") + f",{HOSTIP}")
    return env

def laptop_start(log="laptop.log"):
    t = time.time()
    p = subprocess.Popen([f"{REPO}/.venv/bin/python", "-m", "agentos", "serve", "--no-browser", "--port", str(LPORT),
                          "--if-running=fail"], cwd=REPO, env=lenv(), stdout=open(E / log, "a"),
                         stderr=subprocess.STDOUT, start_new_session=True, stdin=subprocess.DEVNULL)
    (E / "laptop.pid").write_text(str(p.pid))
    wait_up(LURL)
    say(f"laptop up in {time.time()-t:.1f}s (pid {p.pid})")
    return time.time() - t

def laptop_pid():
    try:
        return int((E / "laptop.pid").read_text())
    except Exception:
        return 0

def laptop_kill():
    pid = laptop_pid()
    if pid:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(1)
    say("laptop killed")

def laptop_signal(sig):
    os.kill(laptop_pid(), sig)

def wait_up(url, timeout=90, path="/api/standby"):
    t = time.time()
    while time.time() - t < timeout:
        try:
            r = httpx.get(url + path, timeout=2)
            if r.status_code < 500 or r.status_code == 503:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{url} did not come up")

def cloud_start(fresh=False):
    if fresh:
        subprocess.run(["docker", "rm", "-f", CNAME], capture_output=True)
        subprocess.run(["docker", "volume", "rm", "-f", f"{CNAME}-data"], capture_output=True)
        subprocess.run(["docker", "run", "-d", "--name", CNAME, "-p", f"{CPORT}:8321", "-v", f"{CNAME}-data:/data",
                        "-e", f"AGENTOS_PASSPHRASE={CPASS}", "-e", f"AGENTOS_TELEGRAM_API=http://{HOSTIP}:9302/B",
                        "-e", "AGENTOS_VAULT_KEYRING=0", IMAGE], check=True, capture_output=True)
    else:
        subprocess.run(["docker", "start", CNAME], check=True, capture_output=True)
    wait_up(CURL, path="/login")
    say("cloud up")

def cexec(*cmd, check=True):
    r = subprocess.run(["docker", "exec", CNAME, *cmd], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(r.stdout + r.stderr)
    return r.stdout

def cpy(code):
    return cexec("/opt/agentos/.venv/bin/python", "-c", code)

class Cloud:
    """The person, signed in to the cloud from another machine (not loopback)."""
    def __init__(self, base=None, user=None, pw=CPASS):
        self.base = base or CURL
        self.c = httpx.Client(base_url=self.base, timeout=60)
        self.login(user, pw)
    def login(self, user=None, pw=CPASS):
        body = {"passphrase": pw} if not user else {"username": user, "password": pw}
        r = self.c.post("/api/remote/login", json=body)
        if r.status_code != 200:
            r = self.c.post("/api/users/login", json={"username": user, "password": pw}) if user else r
        return r
    def get(self, p, **k):
        return self.c.get(p, **k)
    def post(self, p, **k):
        return self.c.post(p, **k)

def lget(p, **k):
    return httpx.get(LURL + p, timeout=60, **k)

def lpost(p, **k):
    return httpx.post(LURL + p, timeout=600, **k)

def counts_local(home: Path):
    out = {}
    for db in [home / "agentos.db", *sorted((home / "users").glob("*/agentos.db"))]:
        if not db.exists():
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rel = str(db.relative_to(home))
        out[rel] = {t: con.execute(f'select count(*) from "{t}"').fetchone()[0]
                    for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
        con.close()
    return out

COUNT_CODE = r'''
import sqlite3,json
from pathlib import Path
home=Path("/data");out={}
for db in [home/"agentos.db",*sorted((home/"users").glob("*/agentos.db"))]:
    if not db.exists(): continue
    con=sqlite3.connect(f"file:{db}?mode=ro",uri=True)
    out[str(db.relative_to(home))]={t:con.execute(f'select count(*) from "{t}"').fetchone()[0] for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
print(json.dumps(out))
'''

def counts_cloud():
    return json.loads(cpy(COUNT_CODE))

# tables written by the server itself just by running (diaries, caches, the ledger, usage):
NOISY = {"logs", "audit", "usage", "fabric_events", "kg_meta", "proactive", "notifications",
         "embeddings", "memory_fts", "memory_fts_data", "memory_fts_idx", "memory_fts_docsize",
         "memory_fts_config", "memory_fts_content", "avatars", "office_log", "task_runs", "tasks"}

def diff(a, b, label_a="A", label_b="B"):
    """Rows that differ between two sets of counts, noisy tables apart."""
    real, noisy = [], []
    for db in sorted(set(a) | set(b)):
        ta, tb = a.get(db, {}), b.get(db, {})
        for t in sorted(set(ta) | set(tb)):
            if ta.get(t) != tb.get(t):
                (noisy if t in NOISY else real).append(f"{db}:{t} {label_a}={ta.get(t)} {label_b}={tb.get(t)}")
    return real, noisy

def chat(base, text, cookies=None, timeout=60):
    """One chat turn over the desktop's socket. Returns (conversation_id, reply text)."""
    import asyncio, websockets
    async def go():
        url = base.replace("http", "ws") + "/ws"
        hdr = {"Cookie": "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())} if cookies else {}
        async with websockets.connect(url, additional_headers=hdr, open_timeout=10, proxy=None) as ws:
            await ws.send(json.dumps({"type": "chat", "text": text, "title": text[:40]}))
            cid, out, t = None, "", time.time()
            while time.time() - t < timeout:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if ev.get("type") in ("turn_start", "conversation") and not cid:
                    cid = ev.get("conversation_id") or ev.get("id")
                if ev.get("conversation_id") not in (None, cid):
                    continue
                if ev.get("type") == "text_delta":
                    out += ev.get("text", "")
                if ev.get("type") == "error":
                    out += " [error] " + ev.get("message", "")
                if ev.get("type") == "turn_end":
                    return cid, out
            return cid, out + " [timeout]"
    return asyncio.run(go())

def tg_inject(text):
    return httpx.post(f"http://{HOSTIP}:9302/inject", json={"text": text}).json()["update_id"]

def tg_log():
    return httpx.get(f"http://{HOSTIP}:9302/log").json()

def tg_wait_reply(uid_text, timeout=60):
    """Wait until some side answers after the injected message; returns the side."""
    t = time.time()
    while time.time() - t < timeout:
        lg = tg_log()
        seen = [s for s in lg["seen"] if s["text"] == uid_text]
        sent = [s for s in lg["sent"] if s["at"] > (seen[0]["at"] if seen else 1e18)]
        if seen and sent:
            return {"seen_by": sorted({s["side"] for s in seen}), "answered_by": sent[0]["side"],
                    "answer": sent[0]["text"][:80], "seconds": round(sent[0]["at"] - seen[0]["at"], 1)}
        time.sleep(0.5)
    return {"seen_by": sorted({s["side"] for s in tg_log()["seen"] if s["text"] == uid_text}), "answered_by": None}

def polls_since(seconds):
    """Which sides polled Telegram in the last `seconds`."""
    lg = tg_log()
    return {s: v for s, v in lg["polls"].items() if v["last_ago"] <= seconds}

def conv_titles_local(home=LAG):
    con = sqlite3.connect(f"file:{home/'agentos.db'}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("select title from conversations order by created_at")]
    finally:
        con.close()

def conv_titles_cloud():
    return json.loads(cpy("import sqlite3,json;print(json.dumps([r[0] for r in sqlite3.connect('file:/data/agentos.db?mode=ro',uri=True).execute('select title from conversations order by created_at')]))"))

def wait_for(fn, timeout, every=3, label=""):
    t = time.time()
    while time.time() - t < timeout:
        try:
            v = fn()
            if v:
                return v, time.time() - t
        except Exception:
            pass
        time.sleep(every)
    raise SystemExit(f"timed out waiting for {label}")

def cstatus(cloud):
    return cloud.get("/api/standby").json()

def lstatus():
    return lget("/api/standby").json()

def cip():
    return subprocess.run(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", CNAME],
                          capture_output=True, text=True).stdout.strip()

def counts_cloud_titles():
    return conv_titles_cloud()
