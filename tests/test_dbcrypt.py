"""Every Bento database is encrypted at rest with this machine's key (agentos/dbcrypt.py).

Asked for as "is the database encrypted at rest too? This should be decrypted by machine key".
These pin the rules: a new database is born encrypted, a plain one is converted once and checked
before it replaces anything, a file another process holds is left alone, a lost key is never
re-minted, a backup's copy is plain inside its sealed file, and nothing in Bento opens a
database any other way."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from agentos import dbcrypt

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(not dbcrypt.AVAILABLE, reason="SQLCipher has no build here")


def _plain_db(path: Path, rows=500):
    c = sqlite3.connect(path)
    c.execute("pragma journal_mode=wal")
    c.execute("create table notes(id integer primary key, text)")
    c.execute("create table log(n)")
    c.execute("create trigger noted after insert on notes begin insert into log values (new.id); end")
    c.executemany("insert into notes(text) values (?)", [(f"my secret note {i}",) for i in range(rows)])
    c.execute("pragma user_version=9")
    c.commit()
    c.close()


def test_a_new_database_is_born_encrypted(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    con = dbcrypt.connect(home / "agentos.db")
    con.execute("create table t(x)")
    con.execute("insert into t values ('the password is swordfish')")
    con.commit()
    con.close()
    raw = (home / "agentos.db").read_bytes()
    assert not raw.startswith(dbcrypt.HEADER) and b"swordfish" not in raw
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(home / "agentos.db").execute("select * from t").fetchall()
    assert dbcrypt.connect(home / "agentos.db").execute("select x from t").fetchone()[0].endswith("swordfish")
    # its key is its home's service key, kept beside it here (no keyring in the suite)
    assert json.loads((home / "away.json").read_text())["key"] in ("file", "keyring")


def test_a_plain_database_is_converted_whole_and_checked(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    db = home / "agentos.db"
    _plain_db(db)
    assert dbcrypt.is_plain(db) is True
    assert dbcrypt.encrypt_file(db) == ""
    assert dbcrypt.is_plain(db) is False and b"my secret note" not in db.read_bytes()
    assert not (home / "agentos.db-wal").exists() and not (home / "agentos.db.encrypting").exists()
    con = dbcrypt.connect(db)
    assert con.execute("select count(*) from notes").fetchone()[0] == 500
    assert con.execute("pragma user_version").fetchone()[0] == 9
    con.execute("insert into notes(text) values ('one more')")
    assert con.execute("select count(*) from log").fetchone()[0] == 501, "the trigger came across"
    con.commit()
    con.close()
    assert dbcrypt.encrypt_file(db) == "", "an encrypted file is left as it is"


def test_a_file_another_process_holds_is_left_plain(tmp_path):
    import subprocess
    import sys
    import time
    if not Path("/proc").is_dir():
        pytest.skip("no /proc to read here")
    home = tmp_path / "h"
    home.mkdir()
    db = home / "agentos.db"
    _plain_db(db)
    holder = subprocess.Popen([sys.executable, "-c",
                               "import sqlite3,sys,time; c=sqlite3.connect(sys.argv[1]); "
                               "c.execute('select 1').fetchone(); print('ok', flush=True); time.sleep(30)", str(db)],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ok"
        time.sleep(0.2)
        why = dbcrypt.encrypt_file(db)
    finally:
        holder.kill()
        holder.wait()
    assert "open in another process" in why and dbcrypt.is_plain(db) is True
    assert dbcrypt.encrypt_file(db) == "", "converted once nothing holds it"


def test_this_process_holding_it_counts_too(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    db = home / "agentos.db"
    _plain_db(db)
    held = dbcrypt.connect(db)
    held.execute("select count(*) from notes").fetchone()
    assert "open in another process" in dbcrypt.encrypt_file(db)
    held.close()
    assert dbcrypt.encrypt_file(db) == "", "a closed connection holds nothing"


def test_a_lost_key_is_never_minted_again(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    db = home / "agentos.db"
    con = dbcrypt.connect(db)
    con.execute("create table t(x)")
    con.commit()
    con.close()
    (home / "away.key").unlink()
    dbcrypt._KEY.clear()
    con = dbcrypt.connect(db)
    with pytest.raises(dbcrypt.DatabaseError):
        con.execute("select * from t").fetchall()
    assert not (home / "away.key").exists(), "an existing encrypted file never makes a new key"


def test_each_home_has_its_own_key(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "users" / "u1").mkdir(parents=True)
    b.mkdir()
    for h in (a, b):
        c = dbcrypt.connect(h / "agentos.db")
        c.execute("create table t(x)")
        c.commit()
        c.close()
    # an account's database belongs to the machine home above it
    assert dbcrypt.home_of(a / "users" / "u1" / "agentos.db") == a.resolve() or \
        dbcrypt.home_of(a / "users" / "u1" / "agentos.db") == Path(str(a))
    u = dbcrypt.connect(a / "users" / "u1" / "agentos.db")
    u.execute("create table t(x)")
    u.commit()
    u.close()
    assert not (a / "users" / "u1" / "away.json").exists()
    assert dbcrypt.key_hex(create=False, home=a) != dbcrypt.key_hex(create=False, home=b)
    for p in (a / "agentos.db", a / "users" / "u1" / "agentos.db", b / "agentos.db"):
        assert dbcrypt.connect(p).execute("select count(*) from t").fetchone()[0] == 0


def test_a_backup_copy_is_plain_inside_its_sealed_file(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    db = home / "agentos.db"
    _plain_db(db, rows=50)
    dbcrypt.encrypt_file(db)
    out = tmp_path / "copy.db"
    dbcrypt.plain_copy(db, out)
    assert dbcrypt.is_plain(out) is True and not (tmp_path / "copy.db.sealed").exists()
    c = sqlite3.connect(out)
    assert c.execute("select count(*) from notes").fetchone()[0] == 50
    assert c.execute("pragma user_version").fetchone()[0] == 9


def test_attach_keys_each_file_by_what_it_is(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    enc, plain = home / "agentos.db", tmp_path / "plain.db"
    _plain_db(enc, rows=3)
    dbcrypt.encrypt_file(enc)
    _plain_db(plain, rows=7)
    con = dbcrypt.connect(plain)
    dbcrypt.attach(con, enc, "was")
    assert con.execute("select count(*) from was.notes").fetchone()[0] == 3
    assert con.execute("select count(*) from main.notes").fetchone()[0] == 7


def test_only_the_servers_start_converts(tmp_path, monkeypatch):
    from agentos import config as cfgmod
    from agentos import migrate
    home = tmp_path / "home"
    home.mkdir()
    _plain_db(home / "telemetry.db", rows=5)
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", home)
    monkeypatch.setattr(cfgmod, "DB_PATH", home / "agentos.db")
    seen = []
    migrate.everyone(log=seen.append)
    assert dbcrypt.is_plain(home / "telemetry.db") is True, "`bento migrate` alone converts nothing"
    migrate.everyone(log=seen.append, encrypt=True)
    assert dbcrypt.is_plain(home / "telemetry.db") is False
    assert any("telemetry.db is encrypted" in s for s in seen)
    st = dbcrypt.status(home)
    assert st["state"] == "encrypted" and st["plain"] == 0 and "beside the databases" in st["detail"]


def test_the_server_converts_before_it_opens_anything():
    src = (ROOT / "agentos" / "server.py").read_text()
    start = src[src.index("async def startup():"):]
    assert start.index("encrypt=True") < start.index("store = Store(cfgmod.DB_PATH)")


def test_nothing_in_bento_opens_a_database_another_way():
    """One door: a module that opened sqlite3 itself would read an encrypted file as
    'not a database', or write a new one in the clear."""
    allowed = {"dbcrypt.py"}
    for p in (ROOT / "agentos").rglob("*.py"):
        if p.name in allowed:
            continue
        s = p.read_text()
        for m in re.finditer(r"sqlite3\.connect\(", s):
            line = s[:m.start()].count("\n") + 1
            near = s[max(0, m.start() - 300):m.start()]
            assert "desktoppicture" in near or "PYLOOK" in s[m.start() - 2000:m.start()], \
                f"{p.relative_to(ROOT)}:{line} opens a database without dbcrypt"
        assert not re.search(r"sqlite3\.(Row|Error|OperationalError|IntegrityError|DatabaseError)\b", s), \
            f"{p.relative_to(ROOT)} names sqlite3's classes, which an encrypted connection never raises"


def test_the_key_modules_are_watched():
    from agentos import protected
    for m in ("away.py", "dbcrypt.py", "diskcrypt.py"):
        assert f"agentos/{m}" in protected.SECURITY_MODULES


def test_the_disk_is_read_never_assumed(monkeypatch):
    from agentos import diskcrypt
    calls = []

    def run(argv, timeout=5):
        calls.append(argv[0])
        return {"findmnt": "/dev/mapper/root ext4\n", "lsblk": "crypt\npart\ndisk\n"}.get(argv[0], "")
    monkeypatch.setattr(diskcrypt, "_run", run)
    monkeypatch.setattr(diskcrypt.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(diskcrypt.platform, "system", lambda: "Linux")
    assert diskcrypt.state("/x", fresh=True)["state"] == "on" and "LUKS" in diskcrypt.state("/x")["line"]
    monkeypatch.setattr(diskcrypt, "_run", lambda argv, timeout=5: "overlay overlay\n" if argv[0] == "findmnt" else "")
    st = diskcrypt.state("/y", fresh=True)
    assert st["state"] == "unknown" and "host decides" in st["line"], "a container's disk is the host's to say"
    assert set(calls) <= {"findmnt", "lsblk"}, "only reading tools"


def test_a_scan_that_runs_out_of_time_leaves_the_file_plain(tmp_path, monkeypatch):
    if not Path("/proc").is_dir():
        pytest.skip("no /proc to read here")
    home = tmp_path / "h"
    home.mkdir()
    db = home / "agentos.db"
    _plain_db(db, rows=3)
    monkeypatch.setattr(dbcrypt, "OPEN_SCAN_S", -1.0)
    assert "couldn't check in time" in dbcrypt.encrypt_file(db) and dbcrypt.is_plain(db) is True
