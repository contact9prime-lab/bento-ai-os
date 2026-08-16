"""The external executor's session, and the three ways it used to lose your context.

`--resume <id>` is what makes a second message in a chat a continuation rather
than a stranger. That id lived in `state["exec_sessions"]`, a dict on the server,
and all three bugs follow from where it was kept rather than from what it did:

  1. a restart dropped every one, so a machine that had been up for a week came
     back with every conversation amnesiac;
  2. "Clear session" wiped the transcript and left the id, so the UI emptied, the
     toast said "session cleared", and the model still remembered everything —
     the same bug pointing the other way;
  3. deleting a conversation left its id behind forever.

It now lives on the conversation row, which fixes all three at once and puts it
in the per-user database, where the rest of somebody's data already is.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos.memory import Store                           # noqa: E402


def test_a_session_survives_a_restart(tmp_path):
    """The whole reason it moved out of memory."""
    db = tmp_path / "a.db"
    s = Store(db)
    cid = s.create_conversation("one")
    s.set_exec_session(cid, "sess-abc")
    del s
    assert Store(db).exec_session(cid) == "sess-abc"


def test_clearing_a_session_clears_the_executors_too(tmp_path):
    """Otherwise "clear" means two different things depending on which engine is
    answering — and the one that ignores it is the one that looks like it worked."""
    s = Store(tmp_path / "a.db")
    cid = s.create_conversation("one")
    s.set_exec_session(cid, "sess-abc")
    s.clear_messages(cid)
    assert s.exec_session(cid) == ""


def test_deleting_a_conversation_takes_its_session_with_it(tmp_path):
    s = Store(tmp_path / "a.db")
    cid = s.create_conversation("one")
    s.set_exec_session(cid, "sess-abc")
    s.delete_conversation(cid)
    assert s.exec_session(cid) == ""


def test_a_fresh_conversation_starts_with_no_session(tmp_path):
    """A new chat must not resume somebody else's — this is the "new chat still
    knows the last one" complaint, and it is the default that prevents it."""
    s = Store(tmp_path / "a.db")
    first = s.create_conversation("one")
    s.set_exec_session(first, "sess-abc")
    assert s.exec_session(s.create_conversation("two")) == ""


def test_sessions_do_not_cross_between_conversations(tmp_path):
    s = Store(tmp_path / "a.db")
    a, b = s.create_conversation("a"), s.create_conversation("b")
    s.set_exec_session(a, "sess-a")
    s.set_exec_session(b, "sess-b")
    assert (s.exec_session(a), s.exec_session(b)) == ("sess-a", "sess-b")


def test_an_existing_database_migrates(tmp_path):
    """Every install already has a conversations table without this column, and a
    migration that only runs on a fresh file is not a migration."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, "
                "created_at REAL, updated_at REAL)")
    con.execute("INSERT INTO conversations VALUES ('c1','old chat',0,0)")
    con.commit(); con.close()

    s = Store(db)
    assert s.exec_session("c1") == "", "the column was not added to an existing table"
    s.set_exec_session("c1", "sess-new")
    assert s.exec_session("c1") == "sess-new"


def test_an_unknown_conversation_answers_empty_rather_than_raising(tmp_path):
    """The reader runs on every turn, including the first one in a chat whose row
    is not written yet — raising there would take the turn down."""
    assert Store(tmp_path / "a.db").exec_session("nope") == ""
