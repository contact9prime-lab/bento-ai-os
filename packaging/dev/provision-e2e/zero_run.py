"""A Zero made from the hub's one line, on real servers: the hub (`bento serve` with a
stand-in brain) and a Zero (a fresh `bento serve` in its own home that has never been set
up). What it checks, in order:

  1. the hub prints the one line: install.sh --zero with its automatic key and addresses,
     and the Tailscale key goes into the line and nowhere on disk
  2. the Zero is started the way install.sh leaves it (`bento pool hub`, the key in
     AGENTOS_ENROLL) on a network that carries NO broadcast, as a tailnet does, so the
     hub hears it only because it announced to the hub's address
  3. the hub sets it up the moment it is heard, with the standard profile and nobody
     pressing anything: no seeded agents, the hub's "scout" with its executor, Light mode
  4. a chat on the Zero runs on the hub (fabric.zero_chat): the hub's lead gives it to the
     hub's writer, the file comes back into the Zero's from-<hub>/ folder, and the session is
     kept on the hub in the Zero's section, the same conversation for the next turn
  5. its memory, graph and soul are on the hub, in its own section: what it knew before
     moved there once, what it remembers now is written there, the Zero sees nothing of
     the hub's own memory, and the hub's screens and terminal show the section
  6. the ledger on both sides says what happened
  7. Network on the hub lists the Zero as a tie that answers, its own sessions read back,
     and the brain its work runs on can be chosen

    python zero_run.py [WORKDIR] [--keep]
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
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="zero-e2e-"))
KEEP = "--keep" in sys.argv
TS_KEY = "tskey-auth-kSTANDIN123-abcdefghijklmnop"
ENV = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
       "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1", "AGENTOS_DISCOVER_UDP": "18621"}
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    ENV.pop(k, None)

# name, http, link, claim door, brain port, broadcast targets
MACHINES = [
    ("big-box", 8541, 8651, 0, 9441, "127.255.255.255"),
    # TEST-NET-3, routed nowhere: a broadcast nobody hears. Not 192.0.2.x: a cloud container
    # can sit in that range, and the first run's "unheard" broadcast reached the hub.
    ("pi-zero", 8542, 8652, 8752, None, "203.0.113.255"),
]
PROCS: dict = {}
REPORT: dict = {"steps": []}


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def m(name):
    return next(x for x in MACHINES if x[0] == name)


def home(name):
    return WORK / name


def http(name, method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{m(name)[1]}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


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
        # a real Ollama on this computer would be picked as the Zero's own brain, and a member
        # with a brain of its own never thinks with the hub's: point it at nothing
        cfg["providers"] = {"ollama": {"base_url": "http://127.0.0.1:9"}}
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


def ledger(name, prefix):
    con = sqlite3.connect(home(name) / "agentos.db")
    rows = con.execute("select action, coalesce(reason,'') || coalesce(detail,'') from audit where action like ? order by rowid",
                       (prefix,)).fetchall()
    con.close()
    return rows


def main():
    say(f"work dir {WORK}")
    brain = subprocess.Popen([sys.executable, str(HERE / "zero_brain.py"), "9441"], env=ENV,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for x in MACHINES:
            config(*x)
        up = {"big-box": start("big-box")}
        st, w = http("big-box", "POST", "/api/subagents", {
            "name": "writer", "soul": "WRITER-SOUL. You write plans into files.", "tools": ["write_file"]})
        assert st == 200, w
        st, w = http("big-box", "PUT", "/api/hands/web-only", {
            "spec": {"tools": ["fetch_url", "recall"], "folders": [], "web": "any", "mcp": []},
            "description": "Reads the web and its memory, touches no folder."})
        assert st == 200, w
        st, w = http("big-box", "POST", "/api/subagents", {
            "name": "scout", "soul": "You look things up on the web.", "tools": ["fetch_url", "recall"],
            "profile": "web-only"})
        assert st == 200, w
        st, std = http("big-box", "POST", "/api/provision/standard/agent", {"name": "scout"})
        assert st == 200, std
        st, z = http("big-box", "POST", "/api/provision/zero", {"hubs": ["127.0.0.1"], "tailscale_key": TS_KEY})
        assert st == 200, z
        on_disk = [str(f.relative_to(WORK)) for f in home("big-box").rglob("*")
                   if f.is_file() and TS_KEY.encode() in f.read_bytes()]
        assert not on_disk, on_disk
        cli = bento("big-box", "pool", "zero", "--tailscale-key", TS_KEY, "127.0.0.1")
        (WORK / "pool-zero.txt").write_text(f"$ bento pool zero --tailscale-key {TS_KEY[:14]}… 127.0.0.1\n"
                                            + cli.stdout.replace(TS_KEY, TS_KEY[:14] + "…"))
        std_cli = bento("big-box", "pool", "standard")
        (WORK / "pool-standard.txt").write_text("$ bento pool standard\n" + std_cli.stdout)
        step("1. the hub prints the one line", line=z["line"].replace(TS_KEY, TS_KEY[:14] + "…"),
             hubs=z["hubs"], key=z["key"], standard_agents=[a["name"] for a in z["standard"]["agents"]],
             tailscale_key_on_disk=on_disk, cli_ok=cli.returncode == 0)

        enroll = re.search(r"--enroll=(\S+)", z["line"]).group(1)
        hubs = re.search(r"--hub=(\S+)", z["line"]).group(1)
        set_hub = bento("pi-zero", "pool", "hub", hubs)
        assert set_hub.returncode == 0, set_hub.stderr
        # what the Pi knew before it was set up: it moves to the hub once
        sys.path.insert(0, str(REPO))
        os.environ["AGENTOS_HOME"] = str(home("pi-zero"))
        from agentos.memory import Store
        before = Store(home("pi-zero") / "agentos.db")
        before.add_memory("before the hub: the kettle is left of the sink")
        before.kg_add("Kettle", "is left of", "sink")
        before.db.close()
        (home("pi-zero") / "soul.md").write_text("You are Pip, the kitchen's helper. You keep answers short and warm.\n")
        os.environ.pop("AGENTOS_HOME")
        http("big-box", "POST", "/api/memories", {"content": "HUB-PRIVATE: the hub owner's own note"})
        t_on = time.time()
        up["pi-zero"] = start("pi-zero", {"AGENTOS_ENROLL": enroll})
        took, seen = wait("the hub hears the Zero", lambda: (lambda s: s or None)(
            http("big-box", "GET", "/api/provision")[1]["seen"]), limit=40)
        froms = [r for r in ledger("big-box", "provision.seen")]
        assert all(" at 127.0.0.1 " in d for _, d in froms), froms
        step("2. the Zero announced to the hub's address (its broadcast reaches nobody)",
             heard_from=[d.split(" is waiting")[0] for _, d in froms],
             heard_after_s=round(time.time() - t_on, 1), hub_cli=set_hub.stdout.strip(),
             seen=[f"{e['name']}: {e['hw']['board']}, {e.get('via')}" for e in seen])

        took, me = wait("the Zero is set up by the key", lambda: (lambda t: t if t["claimed"] else None)(
            http("pi-zero", "GET", "/api/provision")[1]["this"]), limit=40)

        def joined():
            c = json.loads((home("pi-zero") / "config.json").read_text())
            return c if str(c.get("default_model") or "").startswith("pool/") else None
        _, zc = wait("the Zero thinks with the hub's brain", joined, limit=60)
        agents = [f"{a['name']} (executor {a.get('profile') or 'default'})"
                  for a in http("pi-zero", "GET", "/api/subagents")[1]["subagents"]]
        hands = [h["name"] for h in (http("pi-zero", "GET", "/api/hands")[1].get("profiles") or [])]
        step("3. set up with the standard profile, nobody pressing anything",
             set_up_after_s=took, how=me["claimed"].get("how"), by=me["claimed"].get("by"),
             zero=zc.get("zero"), profile=zc.get("profile"), model=zc.get("default_model"),
             agents=agents, executors=hands)
        assert agents == ["scout (executor web-only)"] and "web-only" in hands, (agents, hands)
        assert zc["zero"]["execution"] == "hub"

        t0 = time.time()
        st, ans = http("pi-zero", "POST", "/api/chat", {"text": "make me a kitchen plan"}, timeout=300)
        assert st == 200, ans
        got = sorted(str(p.relative_to(home("pi-zero"))) for p in (home("pi-zero") / "workspace").rglob("*")
                     if p.is_file())
        step("4. a task on the Zero ran on the hub and its file came back",
             seconds=round(time.time() - t0, 2), answer=ans.get("content", "")[:600], zero_files=got)
        came = [g for g in got if "from-big-box/kitchen-plan.md" in g]
        assert came, got
        REPORT["file"] = (home("pi-zero") / came[0]).read_text()

        # the session is the hub's: one conversation there, in the Zero's section, which the
        # next turn on the same chat continues
        st, ans2 = http("pi-zero", "POST", "/api/chat", {"text": "thanks", "conversation_id": ans["conversation_id"]},
                        timeout=300)
        con = sqlite3.connect(home("big-box") / "agentos.db")
        zconv = con.execute("select c.id, c.title, s.name, (select count(*) from messages m where m.conversation_id=c.id) "
                            "from conversations c join spaces s on s.id=c.space_id where c.origin='zero'").fetchall()
        con.close()
        assert len(zconv) == 1 and zconv[0][3] == 4, zconv
        shipped = [d for a, d in ledger("big-box", "link.files")]
        assert len(shipped) == 1, f"the second turn made nothing, so it sends nothing back: {shipped}"
        REPORT["hub_session"] = zconv
        st, rem = http("pi-zero", "POST", "/api/memories", {"content": "the user likes green tea"})
        assert st == 200 and rem.get("kept_on") == "big-box", rem
        st, zm = http("pi-zero", "GET", "/api/memories")
        st, zs = http("pi-zero", "GET", "/api/soul")
        st, hm = http("big-box", "GET", "/api/memories")
        st, hs = http("big-box", "GET", "/api/soul?zero=pi-zero")
        con = sqlite3.connect(home("pi-zero") / "agentos.db")
        local = [r[0] for r in con.execute("select content from memories")]
        con.close()
        con = sqlite3.connect(home("big-box") / "agentos.db")
        hub_conv = con.execute("select c.space_id, s.name from conversations c join spaces s on s.id = c.space_id "
                               "where c.origin = 'zero'").fetchall()
        con.close()
        mine = [m["content"] for m in zm["memories"]]
        assert "HUB-PRIVATE: the hub owner's own note" not in mine
        assert "before the hub: the kettle is left of the sink" in mine and "the user likes green tea" in mine
        assert zs["kept_on"] == "big-box" and zs["content"].startswith("You are Pip")
        assert hs["content"].startswith("You are Pip") and "pi-zero" in hs["zeros"]
        hub_cli = bento("big-box", "pool", "mind")
        hub_one = bento("big-box", "pool", "mind", "pi-zero")
        zero_cli = bento("pi-zero", "pool", "mind")
        assert "pi-zero" in hub_cli.stdout and "the user likes green tea" in hub_one.stdout, \
            (hub_cli.stdout + hub_cli.stderr, hub_one.stderr)
        (WORK / "pool-mind.txt").write_text("$ bento pool mind            (on the hub)\n" + hub_cli.stdout
                                            + "\n$ bento pool mind pi-zero    (on the hub)\n" + hub_one.stdout
                                            + "\n$ bento pool mind            (on the Zero)\n" + zero_cli.stdout)
        step("5. its memory, graph and soul are on the hub, in its own section",
             zero_prompt="the Zero's lead was told its memory is on big-box",
             zero_sees=mine, zero_soul=zs["content"][:60], kept_on=zs["kept_on"],
             hub_rows_for_zero=[f"{m['content']} ({m['zero']})" for m in hm["memories"] if m.get("zero")],
             hub_task_section=hub_conv, rows_left_on_the_zero=local,
             hub_cli=hub_cli.stdout.strip().splitlines()[:3], zero_cli=zero_cli.stdout.strip().splitlines()[:2])
        step("6. the ledger on both sides",
             hub=[f"{a}: {d[:110]}" for a, d in ledger("big-box", "provision.%") + ledger("big-box", "link.%")
                  + ledger("big-box", "zero.%")],
             zero=[f"{a}: {d[:110]}" for a, d in ledger("pi-zero", "provision.%")])
        st, tv = http("big-box", "GET", "/api/network/ties?probe=2")
        tie = next(t for t in tv["ties"] if t["kind"] == "zero")
        st, sess = http("big-box", "GET", f"/api/network/ties/{tie['label']}/view?what=sessions")
        st, mem = http("big-box", "GET", f"/api/network/ties/{tie['label']}/view?what=memory")
        st, logs = http("big-box", "GET", f"/api/network/ties/{tie['label']}/view?what=logs")
        st, br = http("big-box", "PUT", f"/api/network/ties/{tie['label']}/brain",
                      {"executor": "aria", "model": "custom/fake-1"})
        assert tie["answering"] is True and sess["rows"] and br.get("ok"), (tie, sess, br)
        assert any("green tea" in r["content"] for r in mem["rows"]), mem
        assert not any("HUB-PRIVATE" in r["content"] for r in mem["rows"]), mem
        step("7. Network on the hub: the Zero answers, and its own rows read back",
             tie={k: tie[k] for k in ("label", "kind", "answering", "peer", "stale")},
             sessions=[f"{r['title']} ({r['messages']} messages)" for r in sess["rows"]],
             memory=[r["content"] for r in mem["rows"]], log_lines=len(logs["rows"]), runs_on=br["brain"])
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
