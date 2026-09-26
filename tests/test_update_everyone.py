"""An update reaches every home, and a page never talks to a server older than itself.

Found on a real machine after `bento update`: the Office said "could not load the
office", Executors and the agents map sat on "loading…", and "＋ New agent" was never
drawn. The pull had put a NEW page on disk while the OLD server was still answering,
so the page called routes that did not exist yet. Three things defend against that:

- the server PINS the page it started with and serves that one while a newer build
  waits on disk, and says so (`pending_restart`, the page's "Restart now" notice);
- a pane that fails says WHY in a sentence (apiJSON names the old-server case), and
  keeps the button it exists for;
- `bento migrate` brings the machine's home AND every account's up to the code, in a
  fresh process, and one broken home never stops the others.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def test_migrate_reaches_every_account(tmp_path):
    home = tmp_path / "home"
    env = {**os.environ, "AGENTOS_HOME": str(home), "AGENTOS_VAULT_KEYRING": "0"}
    setup = ("from agentos import users\n"
             "users.create('ada','hunter2hunter');users.create('bob','hunter2hunter',role='executor')\n")
    subprocess.run([sys.executable, "-c", setup], env=env, cwd=ROOT, check=True, timeout=60)
    out = subprocess.run([sys.executable, "-m", "agentos", "migrate"], env=env, cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith(("✓", "✗"))]
    assert any("this machine" in ln for ln in lines)
    assert any("ada" in ln for ln in lines) and any("bob" in ln for ln in lines)
    assert all(ln.startswith("✓") for ln in lines), out.stdout
    # and it really wrote into each account's own database: built-in executors + characters
    check = ("from agentos import users, hands\n"
             "for u in users.list_users():\n"
             "    s=users.store_for(u['id'])\n"
             "    assert s.db.execute('SELECT COUNT(*) FROM avatars').fetchone()[0]>=2, u\n"
             "    assert any(p['name']=='default' for p in hands.list_profiles(s)), u\n"
             "print('ok')\n")
    r = subprocess.run([sys.executable, "-c", check], env=env, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "ok", r.stdout + r.stderr


def test_one_broken_home_does_not_stop_the_others(monkeypatch):
    from agentos import migrate
    seen = []

    def fake_one(label, cfg, store):
        seen.append(label)
        if label == "this machine":
            raise RuntimeError("disk full")
        return {"home": label, "ok": True, "characters": 2}
    monkeypatch.setattr(migrate, "_one", fake_one)
    from agentos import users
    monkeypatch.setattr(users, "enabled", lambda: True)
    monkeypatch.setattr(users, "list_users", lambda *a, **k: [{"id": "u1", "name": "ada"}])
    monkeypatch.setattr(users, "cfg_for", lambda uid, *a, **k: {})
    monkeypatch.setattr(users, "store_for", lambda uid=None: None)
    said = []
    rows = migrate.everyone(log=said.append)
    assert [r["ok"] for r in rows] == [False, True] and seen == ["this machine", "ada's home"]
    assert said[0].startswith("✗ this machine") and "disk full" in said[0]


def test_the_update_runs_it_in_a_fresh_process():
    src = (ROOT / "agentos/updates.py").read_text()
    assert '"-m", "agentos", "migrate"' in src, "the old process does not have the new migrations"
    assert "migrate.everyone" in (ROOT / "agentos/server.py").read_text(), "a hand pull + restart too"


def test_a_waiting_update_keeps_the_page_the_server_started_with(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        servermod._PAGE[:] = [("old", b"<html>the page this server started with</html>")]
        monkeypatch.setattr(servermod, "_running_build", lambda: "old")
        monkeypatch.setattr(servermod, "_disk_build", lambda: "new")
        r = cl.get("/")
        assert r.text == "<html>the page this server started with</html>"
        assert r.headers["x-bento-waiting"] == "new"
        assert cl.get("/api/update").json()["pending_restart"] == "new"
        # same build on disk (a rebuild without a commit, i.e. development): the disk page
        monkeypatch.setattr(servermod, "_disk_build", lambda: "old")
        r = cl.get("/")
        assert "x-bento-waiting" not in r.headers and "the page this server started with" not in r.text
        # restarting is replacing the code that enforces everything: never from afar
        monkeypatch.setattr(servermod.remotemod, "is_loopback", lambda addr: False)
        assert cl.post("/api/update/restart").status_code == 403


def test_a_pane_that_fails_says_why_and_keeps_its_button():
    hands = (JS / "11e-hands.js").read_text()
    for route in ("/api/hands", "/api/agents", "/api/agents/graph"):
        assert f"apiJSON('{route}')" in hands, f"{route} read with a bare .json() hangs on an old server"
    lst = hands.split("async function renderAgentsList(")[1].split("\n}")[0]
    fail = lst.split("catch(e){", 1)[1].split("return}", 1)[0]
    assert "agentEdit(" in fail and "e.message" in fail, "adding an agent must not depend on the overview"
    core = (JS / "13-fabric.js").read_text()
    assert "running older code" in core
    assert "apiJSON('/api/office')" in (JS / "24d-office.js").read_text()
    assert "updateWaitingCheck" in (JS / "30-init.js").read_text()
