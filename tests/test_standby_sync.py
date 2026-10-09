"""Active sync for the cloud standby (agentos/standbysync.py): the cloud a few seconds
behind your machine, not ten minutes.

Asked for as "an option of active sync where before every chat it is sending the chat,
context and relevant information. Also the meta sync should happen along, like did we
change the system anywhere". What these pin, with the two homes and the in-process
transport of tests/test_standby.py:

- with active sync on, every database row and every changed file reaches the cloud as a
  small sealed update, and a takeover replays them over the copy: the cloud carries on
  from the last change, not the last copy;
- updates carry each row's current value, so a row changed many times is sent once and
  replay is idempotent; deletes travel too;
- a full copy and the updates around it fit together by the journal's high-water mark,
  so entries already in the copy are skipped;
- a new table, a new account's database, a new column all arrive;
- the cloud refuses an update that does not build on the copy it holds, and the main
  machine answers with a fresh copy;
- the machine's own facts travel (version, brain, installed agent CLIs) and the cloud says
  in words what changed and what it would be missing;
- turned off, and on every side that is not the working main machine, there is no
  journal: a backup restored elsewhere never keeps journaling for nobody.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import standby, standbysync as ss  # noqa: E402
import test_standby as ts  # noqa: E402

# the two homes and the in-process transport of tests/test_standby.py
pair, _quick = ts.pair, ts._quick
_say, _titles = ts._say, ts._titles


@pytest.fixture(autouse=True)
def _fresh():
    ss.forget_connections()
    standby._LOOK.clear()
    yield
    ss.forget_connections()


def _active(laptop):
    standby.settings({"sync": "active"}, laptop)
    r = standby.sync(laptop)
    assert r["sent"] and r["kind"] == "copy", r
    return r


def _take_over(cloud):
    st = standby.load(cloud.home)
    st["last_beat"] = time.time() - standby.GRACE_S - 5
    standby.save(st, cloud.home)
    r = standby.takeover(standby.due_takeover(cloud.home), cloud.home)
    cloud.restart()
    ss.forget_connections()
    return r


def _rows(h, table):
    con = sqlite3.connect(h / "agentos.db")
    try:
        return con.execute(f"select * from {table} order by 1").fetchall()
    finally:
        con.close()


def test_every_change_reaches_the_cloud_and_a_takeover_starts_from_the_last_one(pair):
    laptop, cloud = pair
    _say(laptop, "before the copy")
    _active(laptop)
    # the journal is there, and only on the working main machine
    con = sqlite3.connect(laptop / "agentos.db")
    trig = {r[0] for r in con.execute("select name from sqlite_master where type='trigger'")}
    con.close()
    assert {"_bento_sync_i_messages", "_bento_sync_u_messages", "_bento_sync_d_messages"} <= trig
    # a chat after the copy, a settings change and a workspace file
    _say(laptop, "after the copy")
    cfg = json.loads((laptop / "config.json").read_text())
    cfg["agent_name"] = "renamed"
    (laptop / "config.json").write_text(json.dumps(cfg))
    (laptop / "workspace" / "notes.md").write_text("from the laptop")
    assert standby.sync_due(laptop)["due"]
    r = standby.sync(laptop)
    assert r["sent"] and r["kind"] == "update" and r["n"] == 1, r
    assert "1 chat message" in r["changes"] and "1 chat" in r["changes"]
    assert "settings" in r["changes"] and "1 workspace file" in r["changes"]
    st = standby.status(cloud.home)
    assert st["update_n"] == 1 and st["feed"][0]["changes"] == r["changes"]
    # nothing new: nothing sent
    assert standby.sync(laptop) == {"sent": False, "why": "nothing changed"}
    # the machine is gone; the cloud carries on from the update, not the copy
    rep = _take_over(cloud)
    assert rep["updates"] == 1 and not rep["replay_error"]
    assert {"before the copy", "after the copy"} <= _titles(cloud.home)
    assert json.loads((cloud.home / "config.json").read_text())["agent_name"] == "renamed"
    assert (cloud.home / "workspace" / "notes.md").read_text() == "from the laptop"
    # the cloud works: it keeps no journal
    con = sqlite3.connect(cloud.home / "agentos.db")
    names = {r[0] for r in con.execute("select name from sqlite_master")}
    con.close()
    assert not any(n.startswith("_bento_sync") for n in names)


def test_updates_carry_current_values_deletes_and_skip_what_the_copy_holds(pair):
    laptop, cloud = pair
    _active(laptop)
    con = sqlite3.connect(laptop / "agentos.db")
    con.execute("insert into conversations values ('a','first',1,1)")
    con.execute("insert into conversations values ('b','doomed',1,1)")
    con.commit()
    assert standby.sync(laptop)["n"] == 1
    for t in ("second", "third", "final"):
        con.execute("update conversations set title=? where id='a'", (t,))
    con.execute("delete from conversations where id='b'")
    con.commit()
    con.close()
    r = standby.sync(laptop)
    assert r["n"] == 2 and r["changes"] == ["2 chats"], r
    # the journal is pruned once the cloud has it
    con = sqlite3.connect(laptop / "agentos.db")
    assert con.execute("select count(*) from _bento_sync").fetchone()[0] == 0
    con.close()
    # replaying the same update twice changes nothing (applied in the takeover below,
    # whose copy already holds some of the earlier entries)
    _take_over(cloud)
    assert ("a", "final", 1, 1) in _rows(cloud.home, "conversations")
    assert "doomed" not in _titles(cloud.home)


def test_a_new_table_a_new_column_and_a_new_account_database_arrive(pair):
    laptop, cloud = pair
    _active(laptop)
    con = sqlite3.connect(laptop / "agentos.db")
    con.execute("create table later(id integer primary key, v text)")
    con.execute("insert into later(v) values ('made after the copy')")
    con.execute("alter table conversations add column pinned integer")
    con.execute("insert into conversations values ('p','pinned one',1,1,1)")
    con.commit()
    con.close()
    acct = laptop / "users" / "ada"
    acct.mkdir(parents=True)
    c2 = sqlite3.connect(acct / "agentos.db")
    c2.execute("create table memories(id integer primary key, text text)")
    c2.execute("insert into memories(text) values ('ada likes tea')")
    c2.commit()
    c2.close()
    standby._LOOK.clear()
    assert standby.sync_due(laptop)["due"]          # also installs the journal on the new ones
    standby.sync(laptop)
    _take_over(cloud)
    assert _rows(cloud.home, "later") == [(1, "made after the copy")]
    assert ("p", "pinned one", 1, 1, 1) in _rows(cloud.home, "conversations")
    c3 = sqlite3.connect(cloud.home / "users" / "ada" / "agentos.db")
    assert c3.execute("select text from memories").fetchall() == [("ada likes tea",)]
    c3.close()


def test_an_update_the_cloud_cannot_place_is_answered_with_a_fresh_copy(pair):
    laptop, cloud = pair
    _active(laptop)
    _say(laptop, "one")
    assert standby.sync(laptop)["kind"] == "update"
    # the cloud lost its copy id (a restart from an older copy, an update gone missing)
    st = standby.load(cloud.home)
    st["copy_id"] = "0" * 32
    standby.save(st, cloud.home)
    _say(laptop, "two")
    r = standby.sync(laptop)
    assert r["sent"] and r["kind"] == "copy", r
    _say(laptop, "three")
    assert standby.sync(laptop)["kind"] == "update"
    _take_over(cloud)
    assert {"one", "two", "three"} <= _titles(cloud.home)


def test_a_tampered_or_mislabelled_update_is_refused(pair):
    laptop, cloud = pair
    _active(laptop)
    st = standby.load(cloud.home)
    with pytest.raises(standby.StandbyError, match="did not check out"):
        standby.receive_update([b"BENTOBK1\nnot really"], st["copy_id"], 1, cloud.home)
    # an update number that skips ahead is refused without reading it
    out = standby.receive_update([b""], st["copy_id"], 5, cloud.home)
    assert not out["ok"] and "missing" in out["error"]


def test_the_machine_itself_travels_and_the_cloud_says_what_it_would_miss(pair, monkeypatch):
    laptop, cloud = pair
    from agentos import executors as ex
    installed = {"claude-code": False, "gemini-cli": False, "codex": False}
    monkeypatch.setattr(ex, "probe", lambda eid, refresh=False: {"installed": installed.get(eid, False)})
    _active(laptop)
    installed["gemini-cli"] = True
    standby._LOOK.clear()
    assert standby.sync_due(laptop)["due"]
    r = standby.sync(laptop)
    assert "Gemini CLI installed" in r["changes"], r
    # the cloud does not have it, and says so in words
    monkeypatch.setattr(ex, "probe", lambda eid, refresh=False: {"installed": False})
    notes = standby.status(cloud.home)["notes"]
    assert any("Gemini CLI is installed on your machine but not here" in n for n in notes), notes
    assert ss.meta_changes({"version": "1", "engine": "aria", "model": "a", "clis": {}},
                           {"version": "2", "engine": "claude-code", "model": "", "clis": {}}) == [
        "Bento updated from 1 to 2", "the brain changed to claude-code"]


def test_off_means_no_journal_anywhere_and_a_new_vault_goes_in_a_full_copy(pair):
    laptop, cloud = pair
    _active(laptop)
    (laptop / "users").mkdir(exist_ok=True)
    (laptop / "users" / "bo").mkdir()
    (laptop / "users" / "bo" / "vault.json").write_text("{}")
    standby._LOOK.clear()
    r = standby.sync(laptop)
    assert r["kind"] == "copy" and "vault" in r["why"], r
    standby.settings({"sync": "copies"}, laptop)
    ss.ensure(laptop, on=False)
    con = sqlite3.connect(laptop / "agentos.db")
    names = {r[0] for r in con.execute("select name from sqlite_master")}
    con.close()
    assert not any(n.startswith("_bento_sync") for n in names)
    # copies mode never sends updates
    assert standby.sync(laptop) == {"sent": False, "why": "active sync is off"}


def test_the_server_wiring_is_where_it_must_be():
    src = (Path(__file__).resolve().parents[1] / "agentos" / "server.py").read_text()
    # every side settles the journal at start, before anything writes
    start = src[src.index("def _standby_start"):src.index("async def _standby_primary_loop")]
    assert "ss.ensure(on=standbymod.active_sync(st)" in start
    # a clean shutdown sends what is left, and never while a swap is staged
    flush = src[src.index("async def _standby_flush"):src.index("def _standby_split_brief")]
    assert "bk.pending()" in flush and "wait_for" in flush
    assert src.index("await _standby_flush()") < src.index('if state.get("notifd"):\n        state["notifd"].stop()')
    assert '"/api/standby/peer/update"' in src
