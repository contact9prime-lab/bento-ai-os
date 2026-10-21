"""A Zero belongs to one account on its hub, on real servers. The hub (`bento serve` with two
accounts and a stand-in brain) and a Zero (a fresh `bento serve` that has never been set up).
What it checks, in order:

  1. bob makes his own Zero line, signed in (it carries his own key); ada cannot make one for him
  2. the Zero is heard and set up with nobody pressing anything, and the hub lists it as bob's
  3. a task typed on the Zero is answered on the hub as bob: his lead is offered his MCP
     server's tool (pantry), ada's is not, and the file comes back to the Zero
  4. the conversation and the Zero's memory section are in bob's database, not ada's or the
     machine's
  5. the Zero's own screen is the light one (its few apps, the hub named) and it started no
     integrations of its own
  6. the ledger says whose it is

    python zero_accounts_run.py [WORKDIR] [--keep]
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
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="zero-acc-"))
KEEP = "--keep" in sys.argv
ENV = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
       "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1", "AGENTOS_DISCOVER_UDP": "18631"}
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    ENV.pop(k, None)
# name, http, link, claim door, brain port, broadcast targets
MACHINES = [("big-box", 8561, 8661, 0, 9461, "127.255.255.255"),
            ("pi-zero", 8562, 8662, 8762, None, "203.0.113.255")]
PROCS: dict = {}
REPORT: dict = {"steps": []}
JARS: dict = {}


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def m(name):
    return next(x for x in MACHINES if x[0] == name)


def home(name):
    return WORK / name


def http(name, method, path, body=None, timeout=120, who=""):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{m(name)[1]}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JARS[who])) if who else \
        urllib.request.build_opener()
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def login(who, password):
    import http.cookiejar as cj
    JARS[who] = cj.CookieJar()
    st, r = http("big-box", "POST", "/api/users/login", {"name": who, "password": password}, who=who)
    assert st == 200, r


def env_of(name, extra=None):
    x = m(name)
    return {**ENV, "AGENTOS_HOME": str(home(name)), "AGENTOS_DISCOVER_TARGETS": x[5],
            "AGENTOS_PI_MODEL": "Raspberry Pi Zero 2 W Rev 1.0" if name == "pi-zero" else "", **(extra or {})}


def config(name, http_port, link, door, brain, _targets):
    cfg = {"agent_name": "Aria", "pricing_skip": ["custom/fake-1"],
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


def start(name, extra=None, probe="/api/platform"):
    log = open(home(name) / "server.log", "a")
    PROCS[name] = subprocess.Popen([sys.executable, "-m", "agentos", "serve", "--port", str(m(name)[1]),
                                    "--no-browser", "--if-running", "fail"],
                                   cwd=REPO, env=env_of(name, extra), stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            try:
                code = urllib.request.urlopen(f"http://127.0.0.1:{m(name)[1]}{probe}", timeout=3).status
            except urllib.error.HTTPError as e:
                code = e.code
            if code in (200, 401):
                return round(time.time() - t0, 1)
        except Exception:
            pass
        time.sleep(0.4)
    raise SystemExit(f"{name} did not come up; see {home(name) / 'server.log'}")


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


def account(name):
    sys.path.insert(0, str(REPO))
    os.environ["AGENTOS_HOME"] = str(home("big-box"))
    import importlib
    from agentos import users
    importlib.reload(users)
    u = users.by_name(name)
    return u["id"], users.home_for(u["id"])


def rows(db, sql, *a):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql, a).fetchall()
    finally:
        con.close()


def main():
    say(f"work dir {WORK}")
    brain = subprocess.Popen([sys.executable, str(HERE / "zero_brain.py"), "9461"], env=ENV,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for x in MACHINES:
            config(*x)
        for who, role in (("ada", "admin"), ("bob", "executor")):
            r = bento("big-box", "user", "add", who, "--role", role, "--password", f"{who}-pass-123")
            assert r.returncode == 0, r.stderr + r.stdout
        bob_id, bob_home = account("bob")
        ada_id, ada_home = account("ada")
        # bob's own integration: an MCP server only he has
        bcfg_p = bob_home / "config.json"
        bcfg = json.loads(bcfg_p.read_text())
        bcfg["agent_name"] = "Bo"
        bcfg["mcp_servers"] = {"pantry": {"command": f"{sys.executable} {HERE / 'pantry_mcp.py'}",
                                          "enabled": True}}
        bcfg_p.write_text(json.dumps(bcfg, indent=1))
        start("big-box")
        login("ada", "ada-pass-123")
        login("bob", "bob-pass-123")
        st, w = http("big-box", "POST", "/api/subagents", {
            "name": "writer", "soul": "WRITER-SOUL. You write plans into files.",
            "tools": ["write_file", "mcp_pantry_pantry_list"]}, who="bob")
        assert st == 200, w
        _, mcp = wait("bob's pantry server is connected", lambda: (lambda r: r if any(
            s.get("status") == "connected" for s in (r.get("servers") or [])) else None)(
            http("big-box", "GET", "/api/mcp", who="bob")[1]), limit=60)
        st, pv = http("big-box", "GET", "/api/provision", who="bob")
        # a Zero is made by its owner, signed in: bob makes his; nobody makes one for him
        st, z = http("big-box", "POST", "/api/provision/zero", {"hubs": ["127.0.0.1"]}, who="bob")
        assert st == 200 and z["for"]["name"] == "bob", z
        st_ada, za = http("big-box", "POST", "/api/provision/zero", {"hubs": ["127.0.0.1"], "for": "bob"}, who="ada")
        st_own, zown = http("big-box", "POST", "/api/provision/zero", {"hubs": ["127.0.0.1"]}, who="ada")
        cli = bento("big-box", "pool", "zero", "--for", "bob", "127.0.0.1")
        (WORK / "pool-zero-for.txt").write_text("$ bento pool zero --for bob 127.0.0.1\n" + cli.stdout)
        step("1. bob makes his own Zero line; ada cannot make one for him",
             page_offers_others="accounts" in pv, page_says=pv.get("me_name"), line_for=z["for"],
             key=z["key"], ada_for_bob=f"{st_ada} {za.get('error', '')}", ada_for_herself=zown.get("for"),
             cli=cli.stdout.strip().splitlines()[0] if cli.stdout else cli.stderr)
        assert st_ada == 400 and st_own == 200 and zown["for"]["name"] == "ada" and "accounts" not in pv, (za, zown)

        enroll = re.search(r"--enroll=(\S+)", z["line"]).group(1)
        hubs = re.search(r"--hub=(\S+)", z["line"]).group(1)
        assert bento("pi-zero", "pool", "hub", hubs).returncode == 0
        start("pi-zero", {"AGENTOS_ENROLL": enroll}, probe="/api/provision")
        # Both servers share this host and its discovery port, and the kernel hands a
        # unicast datagram to the socket bound LAST, which was the Zero's own. On a LAN
        # they are two machines. The hub starting after the Zero listens last, as it
        # would there; its sign-in cookies stay valid (the session key is on disk).
        PROCS["big-box"].terminate()
        PROCS["big-box"].wait(timeout=30)
        start("big-box")
        took, me = wait("the Zero is set up by bob's key", lambda: (lambda t: t if t["claimed"] else None)(
            http("pi-zero", "GET", "/api/provision")[1]["this"]), limit=60)

        def joined():
            c = json.loads((home("pi-zero") / "config.json").read_text())
            return c if str(c.get("default_model") or "").startswith("pool/") else None
        wait("the Zero thinks with the hub's brain", joined, limit=60)
        _, seen = wait("the hub lists it", lambda: [s for s in http("big-box", "GET", "/api/provision", who="ada")[1]
                                                    ["seen"] if s.get("state") == "enabled"], limit=30)
        step("2. the Zero is set up with nobody pressing anything, and it is bob's",
             set_up_after_s=took, how=me["claimed"].get("how"),
             hub_lists=[f"{s['name']} for {s.get('owner_name') or 'the machine'}" for s in seen])
        assert seen[0]["owner"] == bob_id and seen[0]["owner_name"] == "bob"

        calls_before = len(json.loads(urllib.request.urlopen("http://127.0.0.1:9461/__calls").read())["calls"])
        t0 = time.time()
        st, ans = http("pi-zero", "POST", "/api/chat", {"text": "make me a kitchen plan"}, timeout=300)
        assert st == 200, ans
        calls = json.loads(urllib.request.urlopen("http://127.0.0.1:9461/__calls").read())["calls"][calls_before:]
        hub_lead = [c for c in calls if c.get("linked_lead")]
        writer = [c for c in calls if c.get("writer")]
        pantry = [t for c in writer for t in c["tools"] if t.startswith("mcp_pantry")]
        st, adaq = http("big-box", "POST", "/api/chat", {"text": "hello"}, who="ada")
        calls2 = json.loads(urllib.request.urlopen("http://127.0.0.1:9461/__calls").read())["calls"][-3:]
        ada_pantry = [t for c in calls2 for t in c["tools"] if t.startswith("mcp_pantry")]
        got = sorted(str(p.relative_to(home("pi-zero"))) for p in (home("pi-zero") / "workspace").rglob("*")
                     if p.is_file())
        step("3. the Zero's task is answered as bob, with his integration",
             seconds=round(time.time() - t0, 1), answer=ans.get("content", "")[:300],
             hub_lead_for_it=sorted({c["agent"] for c in hub_lead}),
             bobs_writer_was_offered=sorted(set(pantry)), adas_lead_was_offered_pantry=ada_pantry,
             zero_files=got)
        assert pantry and not ada_pantry, (writer, calls2)
        assert {c["agent"] for c in hub_lead} == {"Bo"}, hub_lead
        assert any("from-big-box/kitchen-plan.md" in g for g in got), got

        q = "select count(*) from conversations where title like '↔ pi-zero%'"
        conv = {"bob": rows(bob_home / "agentos.db", q)[0][0], "ada": rows(ada_home / "agentos.db", q)[0][0],
                "machine": rows(home("big-box") / "agentos.db", q)[0][0]}
        st, rem = http("pi-zero", "POST", "/api/memories", {"content": "the user likes green tea"})
        mq = "select count(*) from memories where content = 'the user likes green tea'"
        mem = {"bob": rows(bob_home / "agentos.db", mq)[0][0], "ada": rows(ada_home / "agentos.db", mq)[0][0],
               "machine": rows(home("big-box") / "agentos.db", mq)[0][0]}
        plan = list((bob_home).rglob("for-pi-zero/kitchen-plan.md"))
        step("4. its conversation, memory and files are in bob's home on the hub",
             conversations=conv, memory_rows=mem, kept_on=rem.get("kept_on"),
             made_in=[str(p.relative_to(WORK)) for p in plan])
        assert conv == {"bob": 1, "ada": 0, "machine": 0}, conv
        assert mem == {"bob": 1, "ada": 0, "machine": 0}, mem

        # it became a Zero after it started: from its next start it starts none of its own
        PROCS["pi-zero"].terminate()
        PROCS["pi-zero"].wait(timeout=30)
        start("pi-zero", probe="/api/provision")
        st, plat = http("pi-zero", "GET", "/api/platform")
        log = (home("pi-zero") / "server.log").read_text()
        diary = rows(home("pi-zero") / "agentos.db", "select message from logs where message like '%is a Zero of%'")
        step("5. the Zero's screen is the light one and it started no integrations",
             platform_zero=plat.get("zero"), buddy=plat.get("face", {}).get("buddy"),
             diary=[d[0] for d in diary][:1])
        assert plat["zero"]["on_hub"] and plat["face"]["buddy"] is True and diary, (plat, diary)

        led = rows(home("big-box") / "agentos.db",
                   "select action, coalesce(reason,'')||coalesce(detail,'') from audit where action like 'provision.%' order by rowid")
        led_bob = rows(bob_home / "agentos.db",
                       "select action, coalesce(reason,'')||coalesce(detail,'') from audit where action like 'provision.%' order by rowid")
        step("6. the ledger says whose it is", machine=[f"{a}: {d[:120]}" for a, d in led],
             bob=[f"{a}: {d[:120]}" for a, d in led_bob])
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
