"""Files across a linked team's hand-over, on real servers: 'home' and 'office', two
`bento serve` processes in their own homes, linked by an invite over mutual TLS, each with
a stand-in brain (brain.py). What it checks, in order:

  1. the two machines link with an invite, and office lets home's agents ask its analyst
  2. home's lead hands "build the Q3 deck" to analyst@office with data.csv; the file is
     its own gate decision on home (file.send on team:office) and arrives on office in
     from-home/
  3. office's analyst makes the deck in for-home/ (a folder the link's files-back
     permission opened) from the data it was sent
  4. the deck comes back to home, into from-office/, and home's answer names it there; an
     older file the answer also names stays on office, and the answer says so
  5. office switches files back off: the next deck is not made and nothing comes back
  6. the ledger on both sides says what moved

    python run.py [WORKDIR] [--keep]
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="linkfiles-"))
KEEP = "--keep" in sys.argv
ENV = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
       "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1"}
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    ENV.pop(k, None)
MACHINES = {"office": (8551, 8651, 9451), "home": (8552, 8652, 9452)}
PROCS: dict = {}
REPORT: dict = {"steps": []}


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def home(n):
    return WORK / n


def http(n, method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{MACHINES[n][0]}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def bento(n, *args):
    r = subprocess.run([sys.executable, "-m", "agentos", *args], cwd=REPO, capture_output=True, text=True,
                       timeout=120, env={**ENV, "AGENTOS_HOME": str(home(n))})
    if r.returncode:
        raise SystemExit(f"bento {' '.join(args)} on {n} failed: {r.stderr or r.stdout}")
    return r.stdout


def start(n):
    http_port, link_port, brain = MACHINES[n]
    h = home(n)
    (h / "workspace").mkdir(parents=True, exist_ok=True)
    (h / "config.json").write_text(json.dumps({
        "agent_name": "Aria", "setup_complete": True, "autonomy": "full", "pricing_skip": ["custom/fake-1"],
        "default_model": "custom/fake-1", "workspace": str(h / "workspace"),
        "memory": {"auto_extract": False},
        "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{brain}/v1", "models": ["fake-1"]}},
        "team": {"machine_name": n, "link_port": link_port, "listen": True}}, indent=1))
    log = open(h / "server.log", "a")
    PROCS[n] = subprocess.Popen([sys.executable, "-m", "agentos", "serve", "--port", str(http_port),
                                 "--no-browser", "--if-running", "fail"], cwd=REPO,
                                env={**ENV, "AGENTOS_HOME": str(h)}, stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            if http(n, "GET", "/api/team/links", timeout=3)[0] == 200:
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise SystemExit(f"{n} did not come up; see {h / 'server.log'}")


def step(title, **facts):
    say(f"✓ {title}" + "".join(f"\n     {k}: {v}" for k, v in facts.items()))
    REPORT["steps"].append({"step": title, **facts})


def ledger(n, action):
    con = sqlite3.connect(home(n) / "agentos.db")
    rows = con.execute("select action, effect, coalesce(reason,'') || coalesce(detail,'') from audit "
                       "where action like ? order by rowid", (action,)).fetchall()
    con.close()
    return rows


def files(n):
    return sorted(str(p.relative_to(home(n) / "workspace")) for p in (home(n) / "workspace").rglob("*") if p.is_file())


def main():
    say(f"work dir {WORK}")
    old = home("office") / "workspace" / "old-plan.txt"
    brains = [subprocess.Popen([sys.executable, str(HERE / "brain.py"), str(MACHINES[n][2]), str(old)],
                               env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for n in MACHINES]
    try:
        for n in MACHINES:
            start(n)
        old.write_text("last quarter's plan")
        os.utime(old, (1, 1))
        (home("home") / "workspace" / "data.csv").write_text("month,revenue\nJul,10\nAug,11\nSep,14\n")
        st, r = http("office", "POST", "/api/subagents", {"name": "analyst", "soul": "SOUL-analyst. You build decks.",
                                                          "tools": ["write_file", "read_file"]})
        assert st == 200, r
        inv = bento("office", "link", "invite", "machine").split()
        invite = next(x for x in inv if x.startswith("bento://"))
        bento("home", "link", "join", invite, "office")
        bento("office", "link", "allow", "home", "analyst")
        bento("home", "grants", "allow", "user", "agent.message", "agent:subagent/analyst@office")
        st, links = http("office", "GET", "/api/team/links")
        lk = next(x for x in links["links"] if x["label"] == "home")
        step("1. linked by invite; office lets home's agents ask its analyst",
             office_sees=f"{lk['label']} ({lk['kind']})", their_agents_may_ask=lk["theirs_may_ask"],
             files_back=lk["files_back"])

        t0 = time.time()
        st, ans = http("home", "POST", "/api/chat", {"text": "make the deck from data.csv"})
        assert st == 200, ans
        content = ans.get("content", "")
        on_office, on_home = files("office"), files("home")
        step("2-4. the file went with the task, the deck came back",
             seconds=round(time.time() - t0, 2), office_workspace=on_office, home_workspace=on_home,
             answer=content.replace(str(WORK), "~")[:900])
        assert "from-home/data.csv" in on_office, on_office
        assert "for-home/q3-deck.pptx" in on_office, on_office
        assert "from-office/q3-deck.pptx" in on_home, on_home
        deck = (home("home") / "workspace" / "from-office" / "q3-deck.pptx").read_text()
        assert "Sep,14" in deck, deck
        assert "old-plan.txt" in content and "not made for this task" in content
        assert not (home("home") / "workspace" / "from-office" / "old-plan.txt").exists()
        REPORT["deck"] = deck

        out = bento("office", "link", "files", "home", "off")
        st, ans2 = http("home", "POST", "/api/chat", {"text": "make the deck from data.csv again"})
        after = files("home")
        step("5. office switched files back off", cli=out.strip().splitlines()[0],
             answer=ans2.get("content", "").replace(str(WORK), "~")[:400],
             home_workspace=after)
        assert after.count("from-office/q3-deck.pptx") == 1 and not any("q3-deck-2" in f for f in after)
        (WORK / "link-files.txt").write_text(
            "$ bento link files home off      (on office)\n" + out
            + "\n$ bento link                     (on office)\n" + bento("office", "link")
            + "\n$ bento link                     (on home)\n" + bento("home", "link"))

        step("6. the ledger on both sides",
             home=[f"{a} {e}: {d[:110]}" for a, e, d in ledger("home", "file.send") + ledger("home", "link.files")],
             office=[f"{a} {e}: {d[:110]}" for a, e, d in ledger("office", "file.send") + ledger("office", "link.files")])
        REPORT["ok"] = True
    finally:
        (WORK / "report.json").write_text(json.dumps(REPORT, indent=1))
        if not KEEP:
            for p in list(PROCS.values()) + brains:
                p.terminate()
        else:
            say("left running: " + ", ".join(f"{n} http://127.0.0.1:{MACHINES[n][0]}" for n in PROCS))


if __name__ == "__main__":
    main()
