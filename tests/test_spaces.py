"""Spaces: the migration cannot lose anything, and scope means space ∪ global.

The promise being tested is the one that would be expensive to discover in
production: adding spaces to a database that predates them must leave every
existing memory and every existing fact exactly as visible as it was.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import spaces as spacemod                             # noqa: E402
from agentos.memory import Store                                   # noqa: E402

# The schema as it stood before spaces existed. Kept verbatim rather than derived
# from SCHEMA, because the point of the test is that the CURRENT code can open a
# database written by the OLD code.
PRE_SPACES = """
CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, created_at REAL, updated_at REAL,
                            rolled_up INTEGER DEFAULT 0, origin TEXT DEFAULT 'user');
CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT,
                       meta TEXT, created_at REAL);
CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT, scope TEXT DEFAULT 'user',
                       conversation_id TEXT, pinned INTEGER DEFAULT 0, source TEXT DEFAULT '',
                       embedding TEXT, updated_at REAL, created_at REAL);
CREATE TABLE logs (id TEXT PRIMARY KEY, kind TEXT, message TEXT, meta TEXT, created_at REAL);
CREATE TABLE kg_nodes (id TEXT PRIMARY KEY, name TEXT UNIQUE, type TEXT, created_at REAL);
CREATE TABLE kg_edges (id TEXT PRIMARY KEY, src TEXT, dst TEXT, relation TEXT, created_at REAL);
CREATE TABLE tasks (id TEXT PRIMARY KEY, prompt TEXT, schedule_type TEXT, next_run REAL,
                    created_at REAL);
CREATE TABLE fabric_runs (id TEXT PRIMARY KEY, kind TEXT, ref TEXT, status TEXT, started_at REAL);
CREATE TABLE grants (id TEXT PRIMARY KEY, principal_kind TEXT, principal_id TEXT, action TEXT,
                     resource TEXT, effect TEXT, source TEXT, created_at REAL);
CREATE TABLE user_apps (id TEXT PRIMARY KEY, name TEXT UNIQUE, icon TEXT, description TEXT,
                        html TEXT, created_at REAL, updated_at REAL);
INSERT INTO memories (id, content, scope, created_at) VALUES ('m1','Piyush works at Accacia','user',1.0);
INSERT INTO memories (id, content, scope, created_at) VALUES ('m2','prefers short answers','user',2.0);
INSERT INTO conversations (id,title,created_at,updated_at) VALUES ('c1','old chat',1.0,1.0);
INSERT INTO kg_nodes VALUES ('n1','Piyush','person',1.0);
INSERT INTO kg_nodes VALUES ('n2','Accacia','org',1.0);
INSERT INTO kg_edges VALUES ('e1','n1','n2','works at',1.0);
"""


def _legacy_db(tmp_path) -> Path:
    p = tmp_path / "legacy.db"
    con = sqlite3.connect(str(p))
    con.executescript(PRE_SPACES)
    con.commit()
    con.close()
    return p


def test_migration_keeps_every_row_and_shows_it_everywhere(tmp_path):
    store = Store(_legacy_db(tmp_path))
    assert len(store.search_memories()) == 2
    assert store.kg_query("Piyush") == ["Piyush —works at→ Accacia"]

    # a brand-new space still sees everything that predates it: pre-spaces rows
    # are global, which is the correct reading of "we did not know about projects"
    sid = store.create_space("Launch", description="the Q3 launch")
    assert len(store.search_memories(space=sid)) == 2
    assert store.kg_query("", space=sid) == ["Piyush —works at→ Accacia"]


def test_reads_are_space_union_global(tmp_path):
    store = Store(tmp_path / "t.db")
    a = store.create_space("Alpha")
    b = store.create_space("Beta")
    store.add_memory("my name is Piyush")                 # global
    store.add_memory("alpha ships on Friday", space_id=a)
    store.add_memory("beta is paused", space_id=b)

    def texts(space=""):
        return {m["content"] for m in store.search_memories(space=space)}

    assert texts(a) == {"my name is Piyush", "alpha ships on Friday"}
    assert texts(b) == {"my name is Piyush", "beta is paused"}
    assert texts(store.GLOBAL_ONLY) == {"my name is Piyush"}
    assert len(texts()) == 3          # no space asked for = no filtering at all


def test_the_graph_is_scoped_on_edges_not_nodes(tmp_path):
    store = Store(tmp_path / "t.db")
    a = store.create_space("Alpha")
    store.kg_add("Ana", "works at", "Accacia")                     # global
    store.kg_add("Ana", "reviews", "launch copy", space_id=a)

    assert store.kg_query("", space=a) == [
        "Ana —reviews→ launch copy", "Ana —works at→ Accacia"]
    assert store.kg_query("", space=store.GLOBAL_ONLY) == ["Ana —works at→ Accacia"]
    # one entity, not one per space — a person does not fork when you switch project
    names = [n["name"] for n in store.kg_graph()["nodes"]]
    assert names.count("Ana") == 1


def test_session_memories_follow_their_conversation_into_a_space(tmp_path):
    store = Store(tmp_path / "t.db")
    cid = store.create_conversation("chat")
    store.add_memory("we chose sqlite", scope="session", conversation_id=cid)
    sid = store.create_space("Alpha")
    store.set_conversation_space(cid, sid)
    assert store.get_conversation(cid)["space_id"] == sid
    got = store.search_memories(scope="session", conversation_id=cid)
    assert got and got[0]["space_id"] == sid


def test_deleting_a_space_must_say_what_happens_to_its_contents(tmp_path):
    store = Store(tmp_path / "t.db")

    sid = store.create_space("Archive me")
    store.add_memory("scoped fact", space_id=sid)
    store.delete_space(sid, contents="archive")
    assert store.get_space(sid)["archived"] == 1
    assert sid not in [s["id"] for s in store.list_spaces()]        # no longer offered
    assert len(store.search_memories(space=sid)) == 1               # nothing was lost

    sid2 = store.create_space("Promote me")
    store.add_memory("becomes global", space_id=sid2)
    store.delete_space(sid2, contents="global")
    assert store.get_space(sid2) is None
    assert "becomes global" in {m["content"] for m in
                                store.search_memories(space=store.GLOBAL_ONLY)}

    sid3 = store.create_space("Delete me")
    store.add_memory("goes away", space_id=sid3)
    store.kg_add("X", "rel", "Y", space_id=sid3)
    counts = store.delete_space(sid3, contents="delete")
    assert counts.get("memories") == 1
    assert "goes away" not in {m["content"] for m in store.search_memories()}
    # entities left pointing at nothing go too, rather than littering the graph
    assert not [n for n in store.kg_graph()["nodes"] if n["name"] in ("X", "Y")]


def test_an_unknown_active_space_falls_back_to_global(tmp_path):
    """A dangling id must not filter everything out — losing all your memory
    because a space was deleted on another device is the worst failure here."""
    store = Store(tmp_path / "t.db")
    cfg = {"spaces": {"active": {"gui": "does-not-exist"}}}
    assert spacemod.active_for(cfg, "gui", store) == ""


def test_the_conversation_beats_the_surface_default(tmp_path):
    store = Store(tmp_path / "t.db")
    a = store.create_space("Alpha")
    b = store.create_space("Beta")
    cid = store.create_conversation("in alpha", space_id=a)
    cfg = {"spaces": {"active": {"gui": b}}}
    # reopening an old thread must not drag it into whatever is active now
    assert spacemod.active_for(cfg, "gui", store, cid) == a
    assert spacemod.active_for(cfg, "gui", store) == b


def test_active_space_is_per_surface(tmp_path):
    """One global 'current space' would have the desk and the phone fighting."""
    cfg = {}
    spacemod.set_active(cfg, "gui", "s1")
    spacemod.set_active(cfg, "telegram", "s2")
    assert cfg["spaces"]["active"] == {"gui": "s1", "telegram": "s2"}


def test_timeline_records_milestones_with_their_space(tmp_path):
    store = Store(tmp_path / "t.db")
    sid = store.create_space("Alpha")
    rid = store.fabric_run_start("delegate", "researcher", "find things", space_id=sid)
    store.fabric_run_finish(rid, "ok", output="done")
    kinds = [e["kind"] for e in store.timeline(space=sid)]
    assert "run" in kinds and "space" in kinds
    # a global view still sees it; a different space does not
    other = store.create_space("Beta")
    assert not [e for e in store.timeline(space=other) if e["kind"] == "run"]
