"""Backup and restore (agentos/backup.py): the whole machine in one encrypted file.

Asked for as "what is missing from a portability point of view": nothing could move a
machine, and Snapshots kept three files of one home on the same disk. What these pin:

- a backup carries every account, consistent copies of live databases, the vault keys
  and the workspace, and leaves caches out;
- a wrong passphrase, a file cut short, a changed byte and extra data are each refused
  with a sentence, before anything is written;
- nothing in a file can land outside the home;
- a restore moves the current home ASIDE and never deletes it, puts vault keys where
  this machine can keep them, and rewrites folder paths for the new machine;
- the desktop's restore is staged and applied on the next start, only by an admin at
  the machine itself; the snapshot bug (old code copied over new) is fixed.
"""
import io
import json
import sqlite3
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import backup  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PW = "correct horse battery"


@pytest.fixture(autouse=True)
def _quick_kdf(request, monkeypatch):
    """The real scrypt cost is a third of a second per open; the round trip keeps it,
    the rest use a cheaper one (the reader takes the cost from the file's header)."""
    if request.node.name != "test_everything_that_is_yours_travels_and_caches_do_not":
        monkeypatch.setattr(backup, "SCRYPT", {"n": 1 << 10, "r": 8, "p": 1})


def _machine(tmp_path, name="old"):
    """A home with an account, a live WAL database, a vault, caches and a workspace
    outside it."""
    base = tmp_path / name
    home, ws = base / ".agentos", base / "AgentOS"
    (home / "users" / "u1").mkdir(parents=True)
    ws.mkdir()
    (ws / "deck.md").write_text("# the deck")
    (home / "config.json").write_text(json.dumps({"workspace": str(ws), "engine": "aria"}))
    (home / "users.json").write_text(json.dumps({"users": [{"id": "u1", "name": "ada", "admin": True}]}))
    con = sqlite3.connect(home / "agentos.db")
    con.execute("pragma journal_mode=wal")
    con.execute("create table t(x)")
    con.execute("insert into t values (42)")
    con.commit()                       # left open: the WAL holds the row, not the file
    ucon = sqlite3.connect(home / "users" / "u1" / "agentos.db")
    ucon.execute("create table executor_profiles(name text primary key, spec text)")
    ucon.execute("insert into executor_profiles values ('ro', ?)",
                 (json.dumps({"folders": [{"path": str(ws / "notes"), "mode": "ro"}]}),))
    ucon.commit()
    ucon.close()
    (home / "users" / "u1" / "config.json").write_text(json.dumps({"persona": "founder"}))
    (home / "snapshots").mkdir()
    (home / "snapshots" / "big.bin").write_bytes(b"x" * 5000)
    (home / "speech-cache").mkdir()
    (home / "speech-cache" / "a.mp3").write_bytes(b"y" * 100)
    (home / "mcp_index.json").write_text("{}")
    return home, ws, con


def test_everything_that_is_yours_travels_and_caches_do_not(tmp_path):
    home, ws, con = _machine(tmp_path)
    m = backup.create(tmp_path / "b.bento", PW, home=home)
    assert (tmp_path / "b.bento").stat().st_mode & 0o777 == 0o600
    assert set(m["databases"]) == {"agentos.db", "users/u1/agentos.db"}
    assert [u["name"] for u in m["accounts"]] == ["ada"]
    assert m["workspace_included"] and m["workspace"] == str(ws)
    new = tmp_path / "new" / ".agentos"
    new.mkdir(parents=True)
    (new / "config.json").write_text('{"mine": true}')
    r = backup.restore(tmp_path / "b.bento", PW, home=new)
    assert not list(new.glob("*.db-wal")), "the copy is whole, no WAL rides along"
    # the row that was only in the WAL made it: a consistent copy, not a file copy
    assert sqlite3.connect(new / "agentos.db").execute("select x from t").fetchall() == [(42,)]
    assert json.loads((new / "users" / "u1" / "config.json").read_text())["persona"] == "founder"
    for skipped in ("snapshots", "speech-cache", "mcp_index.json"):
        assert not (new / skipped).exists(), skipped
    # what was here is kept, not deleted
    prev = Path(r["previous"])
    assert prev.parent == new and json.loads((prev / "config.json").read_text()) == {"mine": True}
    assert Path(r["workspace"], "deck.md").read_text() == "# the deck"
    assert json.loads((new / backup.LAST).read_text())["from_host"] == m["host"]
    con.close()


def _sealed(tmp_path):
    home, _, con = _machine(tmp_path)
    con.close()
    return home, backup.create(tmp_path / "b.bento", PW, home=home, workspace=False)


def test_a_bad_file_is_refused_before_anything_moves(tmp_path):
    home, m = _sealed(tmp_path)
    f = tmp_path / "b.bento"
    data = f.read_bytes()
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("mine")

    def refused(blob, words, pw=PW):
        p = tmp_path / "bad.bento"
        p.write_bytes(blob)
        with pytest.raises(backup.BackupError) as e:
            backup.restore(p, pw, home=target)
        assert words in str(e.value), str(e.value)
        assert sorted(x.name for x in target.iterdir()) == ["keep.txt"], "nothing moved, nothing left"

    refused(data, "passphrase is wrong", pw="not the one at all")
    refused(data[:-40], "cut short")
    mid = len(data) // 2
    refused(data[:mid] + bytes([data[mid] ^ 1]) + data[mid + 1:], "changed or damaged")
    refused(data + b"more", "extra data")
    refused(b"PK\x03\x04 not a backup", "not a Bento backup")
    with pytest.raises(backup.BackupError, match="at least"):
        backup.create(tmp_path / "c.bento", "short", home=home)
    with pytest.raises(backup.BackupError, match="outside the Bento folder"):
        backup.create(home / "inside.bento", PW, home=home)


def test_nothing_in_a_file_can_land_outside_the_home(tmp_path):
    """A backup is a file somebody can hand you. Its names are checked like any
    archive's: no absolute paths, no .., no links."""
    def forged(members):
        p = tmp_path / "forged.bento"
        with open(p, "wb") as out:
            s = backup._Sealer(out, PW)
            with tarfile.open(fileobj=s, mode="w|gz") as tar:
                man = json.dumps({"format": backup.FORMAT}).encode()
                ti = tarfile.TarInfo("manifest.json")
                ti.size = len(man)
                tar.addfile(ti, io.BytesIO(man))
                for m, data in members:
                    tar.addfile(m, io.BytesIO(data) if data is not None else None)
            s.seal()
        return p

    target = tmp_path / "t"
    for name in ("../../escape.txt", "/etc/escape.txt", "home/../../escape.txt"):
        ti = tarfile.TarInfo(name)
        ti.size = 4
        with pytest.raises(backup.BackupError, match="outside"):
            backup.stage(forged([(ti, b"evil")]), PW, home=target)
    assert not (tmp_path / "escape.txt").exists()
    # a link is dropped, never followed
    link = tarfile.TarInfo("home/link")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    ok = tarfile.TarInfo("home/ok.txt")
    ok.size = 2
    m = backup.stage(forged([(link, None), (ok, b"hi")]), PW, home=target)
    st = Path(m["staging"])
    assert (st / "home" / "ok.txt").read_text() == "hi" and not (st / "home" / "link").exists()
    assert not list(target.glob(".restoring-*/keys.json")) or \
        (st / "keys.json").stat().st_mode & 0o777 == 0o600


def test_a_keyring_key_travels_and_lands_where_this_machine_can_keep_it(tmp_path, monkeypatch):
    """A vault keyed in the old machine's keyring would arrive locked. The key rides
    inside the sealed file and goes into the new keyring, or into a 0600 key file on
    a machine with none, and everything in the vault still opens."""
    from agentos import config as cfgmod
    from agentos import vault
    ring = {}
    monkeypatch.setattr(vault, "_keyring_tool", lambda: "secret-tool")
    monkeypatch.setattr(vault, "_keyring_get", lambda scope: ring.get(scope, ""))
    monkeypatch.setattr(vault, "_keyring_set", lambda scope, k: ring.__setitem__(scope, k) or True)
    home, _, con = _machine(tmp_path)
    con.close()
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", home)
    vault.put("mail.password", "hunter2-app-password")
    assert json.loads((home / "vault.json").read_text())["key"] == "keyring"
    m = backup.create(tmp_path / "b.bento", PW, home=home, workspace=False)
    assert m["vaults"] == [{"path": "vault.json", "mechanism": "keyring", "carried": True}]
    # the new machine has no keyring at all
    ring.clear()
    monkeypatch.setattr(vault, "_keyring_tool", lambda: "")
    new = tmp_path / "new"
    r = backup.restore(tmp_path / "b.bento", PW, home=new)
    assert json.loads((new / "vault.json").read_text())["key"] == "file"
    assert (new / "vault.key").stat().st_mode & 0o777 == 0o600
    assert any("no keyring" in a for a in r["attention"])
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", new)
    assert vault.get("vault:mail.password") == "hunter2-app-password"


def test_folders_follow_the_machine():
    """/home/ada/AgentOS on Linux is /Users/ada/AgentOS on a Mac: a path under the old
    home or user folder is rewritten, anything else is left alone."""
    home = Path("/new/.agentos")
    m = {"home": "/home/ada/.agentos", "user_home": "/home/ada"}
    new_user = str(Path.home())
    assert backup._remap("/home/ada/AgentOS/x", m, home) == new_user + "/AgentOS/x"
    assert backup._remap("/home/ada/.agentos/users/u1", m, home) == "/new/.agentos/users/u1"
    assert backup._remap("/srv/shared", m, home) == "/srv/shared"
    assert backup._remap("/home/adam/x", m, home) == "/home/adam/x", "a prefix is a whole folder"
    assert backup._remap("~/AgentOS", m, home) == "~/AgentOS"
    win = {"home": "C:\\Users\\Ada\\.agentos", "user_home": "C:\\Users\\Ada"}
    if Path("/").as_posix() == "/":
        assert backup._remap("C:\\Users\\Ada\\AgentOS\\notes", win, home) == new_user + "/AgentOS/notes"


def test_paths_are_rewritten_in_configs_and_agent_folders(tmp_path, monkeypatch):
    home, ws, con = _machine(tmp_path)
    con.close()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "old"))
    backup.create(tmp_path / "b.bento", PW, home=home, workspace=False)
    new_user = tmp_path / "other-user"
    new_user.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: new_user))
    new = new_user / ".agentos"
    r = backup.restore(tmp_path / "b.bento", PW, home=new)
    assert r["paths_rewritten"] >= 2
    assert json.loads((new / "config.json").read_text())["workspace"] == str(new_user / "AgentOS")
    spec = sqlite3.connect(new / "users" / "u1" / "agentos.db").execute(
        "select spec from executor_profiles").fetchone()[0]
    assert json.loads(spec)["folders"][0]["path"] == str(new_user / "AgentOS" / "notes")


def test_a_workspace_fills_an_empty_folder_instead_of_nesting_in_it(tmp_path, monkeypatch):
    """A fresh install makes an empty ~/AgentOS on its first start. shutil.move into an
    existing folder puts the source INSIDE it, so the workspace landed at
    ~/AgentOS/workspace while the config said ~/AgentOS. Found moving a laptop to a
    fresh cloud container."""
    home, ws, con = _machine(tmp_path)
    con.close()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "old"))
    backup.create(tmp_path / "b.bento", PW, home=home)
    new_user = tmp_path / "fresh"
    (new_user / "AgentOS").mkdir(parents=True)          # what a first start leaves
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: new_user))
    r = backup.restore(tmp_path / "b.bento", PW, home=new_user / ".agentos")
    assert r["workspace"] == str(new_user / "AgentOS")
    assert (new_user / "AgentOS" / "deck.md").read_text() == "# the deck"
    assert not (new_user / "AgentOS" / "workspace").exists()
    assert not r["workspace_previous"], "an empty folder is not a previous workspace"


def test_a_mission_keeps_watching_its_folder_on_the_new_machine(tmp_path, monkeypatch):
    """A folder-watch mission names its folder in five places in the database: the
    flow's text and permissions, its trigger, the task it made and the folder grant.
    Only config and agent folders were rewritten, so after a move the mission watched
    the old machine's path and was silently dead. The ledger is history: never touched."""
    home, ws, con = _machine(tmp_path)
    inbox = str(tmp_path / "old" / "AgentOS" / "inbox")
    con.executescript(f"""
      create table flows(name text, mission text, permissions text);
      create table flow_triggers(id text, config text);
      create table grants(id text, resource text);
      create table tasks(id text, prompt text, trigger_config text);
      create table audit(id text, resource text);
      insert into flows values ('fw', 'Something new appeared in {inbox}. Work out what it is.',
                                '{{"folders": ["{inbox}"]}}');
      insert into flow_triggers values ('t1', '{{"path": "{inbox}", "glob": "*"}}');
      insert into grants values ('g1', 'fs:{inbox}/*');
      insert into tasks values ('k1', 'Something new appeared in {inbox}.', '{{"path": "{inbox}"}}');
      insert into audit values ('a1', 'fs:{inbox}/x');""")
    con.commit()
    con.close()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "old"))
    backup.create(tmp_path / "b.bento", PW, home=home, workspace=False)
    new_user = tmp_path / "other"
    new_user.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: new_user))
    new = new_user / ".agentos"
    backup.restore(tmp_path / "b.bento", PW, home=new)
    now = str(new_user / "AgentOS" / "inbox")
    db = sqlite3.connect(new / "agentos.db")
    assert db.execute("select mission from flows").fetchone()[0] == f"Something new appeared in {now}. Work out what it is."
    assert json.loads(db.execute("select permissions from flows").fetchone()[0]) == {"folders": [now]}
    assert json.loads(db.execute("select config from flow_triggers").fetchone()[0])["path"] == now
    assert db.execute("select resource from grants").fetchone()[0] == f"fs:{now}/*"
    assert json.loads(db.execute("select trigger_config from tasks").fetchone()[0])["path"] == now
    assert db.execute("select resource from audit").fetchone()[0] == f"fs:{inbox}/x", "the ledger is history"
    m = {"home": "/home/ada/.agentos", "user_home": "/home/ada"}
    assert backup._remap_text("see /home/adam/x and /home/ada/y", m, Path("/n")) == \
        f"see /home/adam/x and {Path.home()}/y"


def test_the_desktop_stages_and_the_next_start_applies(tmp_path):
    home, _ = _sealed(tmp_path)
    target = tmp_path / "t"
    target.mkdir()
    (target / "config.json").write_text("{}")
    m = backup.stage(tmp_path / "b.bento", PW, home=target)
    backup.mark_ready(m["staging"], home=target)
    assert backup.pending(home=target)["accounts"] == 1
    assert json.loads((target / "config.json").read_text()) == {}, "nothing swapped yet"
    said = []
    r = backup.apply_pending(home=target, echo=said.append)
    assert r and not backup.pending(home=target) and said
    assert (target / "users.json").exists()
    assert backup.last_restore(home=target, forget=True)["from_host"] == m["host"]
    assert backup.last_restore(home=target) == {}, "the report is shown once"
    # cancelling removes the staging folder
    m2 = backup.stage(tmp_path / "b.bento", PW, home=target)
    backup.mark_ready(m2["staging"], home=target)
    assert backup.cancel_pending(home=target) and not Path(m2["staging"]).exists()
    # a backup never carries this module's own working folders
    assert not any(backup._private(rel.split("/")[0]) for rel, _ in backup._walk(target))


def test_a_restore_is_started_only_by_an_admin_at_the_machine(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        d = cl.get("/api/backup").json()
        assert d["admin"] and d["plan"]["files"] >= 0 and d["min"] == backup.MIN_PASSPHRASE
        r = cl.post("/api/backup", json={"passphrase": PW, "workspace": False})
        assert r.status_code == 200 and r.content.startswith(backup.MAGIC)
        assert cl.post("/api/backup", json={"passphrase": "short"}).status_code == 400
        # at the machine: checked, staged, then cancelled; nothing swapped under the server
        up = cl.post("/api/restore", content=r.content, headers={"X-Bento-Passphrase": "wrong one!"})
        assert up.status_code == 400 and "passphrase is wrong" in up.json()["error"]
        up = cl.post("/api/restore", content=r.content, headers={"X-Bento-Passphrase": PW})
        assert up.status_code == 200 and up.json()["pending"]["staging"]
        assert cl.get("/api/backup").json()["pending"]
        assert cl.delete("/api/restore").json()["cancelled"]
        # from another machine on the network: refused, and it says where to do it
        monkeypatch.setattr(servermod.remotemod, "is_loopback", lambda h: False)
        up = cl.post("/api/restore", content=r.content, headers={"X-Bento-Passphrase": PW})
        assert up.status_code == 403 and "machine itself" in up.json()["error"]
        assert cl.post("/api/restore/apply", json={"confirm": True}).status_code == 403
    srv = (ROOT / "agentos/server.py").read_text()
    for route in ('("POST", "/api/backup")', '("POST", "/api/restore")', '("DELETE", "/api/restore")'):
        assert route in srv, route
    assert "call_later(0.6, desktopmod.restart_service)" in srv, "the answer leaves before the restart"


def test_the_start_applies_a_restore_only_when_it_owns_the_home():
    main = (ROOT / "agentos/__main__.py").read_text()
    serve = main.split("def serve(", 1)[1].split("\ndef ", 1)[0]
    assert "apply_pending()" in serve
    assert serve.index("_resolve_running_instance") < serve.index("apply_pending()")
    assert 'if kind != "taken" or mode == "restart":' in serve
    assert 'verb("backup"' in main and 'verb("restore"' in main
    assert "BENTO_BACKUP_PASSPHRASE" in main and "--passphrase-file" in main


def test_a_snapshot_never_puts_old_code_over_new():
    """Restoring a snapshot copied its .py files over the running install: taken on
    0.5 and restored on 0.6, it rolled half the program back."""
    srv = (ROOT / "agentos/server.py").read_text()
    body = srv.split('async def api_snapshot_restore(', 1)[1].split("\n@app.", 1)[0]
    assert 'meta.get("version") == _running_version()' in body and "if code:" in body
    assert '"version": _running_version()' in srv.split("async def api_snapshot_create(", 1)[1].split("\n@app.", 1)[0]


def test_settings_offers_it_and_a_remote_browser_is_told_where():
    js = (ROOT / "agentos/ui/src/js/11g-backup.js").read_text()
    assert "/api/backup" in js and "/api/restore/apply" in js and "encodeURIComponent(pw)" in js
    assert "on the machine itself" in js, "a remote browser gets a sentence, not a button"
    settings = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "pGroup('Backup'" in settings and "paintBackup" in settings
    ob = (ROOT / "agentos/ui/src/js/14b-onboarding.js").read_text()
    assert "Restore a backup" in ob, "a new machine for somebody who already has one"
