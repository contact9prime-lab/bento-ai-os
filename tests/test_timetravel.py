"""Time travel (agentos/timetravel.py, the checkpoints in Agent.call_tool, 00j-timetravel.js).

Asked for as "a Time Machine scrubber that rewinds windows, reverts files the agent
modified, rolls back the agent's memory and knowledge graph to before it hallucinated,
and forks reality from step 4 with a different model". What these defend:

- the memory, the graph and skills are journalled by triggers, so every add, change and
  removal since a checkpoint is undone exactly, and a rewind is not itself journalled;
- a file a step was about to change is put back; a file a step created is set aside;
  nothing is deleted (it goes to .timetravel/rewound/);
- a shell step is marked as not undoable, and the plan says so;
- preview and rewind are one computation; the checkpoint is taken at the one gate, only
  after the step was allowed, and never fails it;
- a fork starts from the question of that turn with the steps already run;
- it is pruned, and the ledger is never touched.
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import timetravel as tt                                 # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _store(tmp_path):
    return Store(tmp_path / "t.db")


def test_memory_and_the_graph_go_back_exactly(tmp_path):
    s = _store(tmp_path)
    keep = s.add_memory("The person likes tea", scope="user")
    s.kg_add("Ada", "works_at", "Acme")
    p = tt.checkpoint(s.db, tmp_path, "remember", "remember something")
    s.add_memory("The person hates tea (a hallucination)", scope="user")
    s.update_memory(keep, "The person likes coffee")
    s.kg_add("Ada", "founded", "Mars Inc")
    pl = tt.plan(s.db, tmp_path, p["id"])
    assert pl["rows"] >= 3 and any("remove" in w for w in pl["words"]) and any("restore" in w for w in pl["words"])
    tt.rewind(s.db, tmp_path, p["id"])
    mems = [m["content"] for m in s.list_memories()] if hasattr(s, "list_memories") else \
        [r["content"] for r in s.db.execute("SELECT content FROM memories")]
    assert mems == ["The person likes tea"]
    rels = {r[0] for r in s.db.execute("SELECT relation FROM kg_edges")}
    assert rels == {"works_at"} and not s.db.execute("SELECT 1 FROM kg_nodes WHERE name='Mars Inc'").fetchone()
    # the rewind itself was not journalled, and the points after it read as rewound
    assert s.db.execute("SELECT COUNT(*) FROM _tt_undo WHERE seq > ?", (p["seq"],)).fetchone()[0] == 0
    assert tt.get(s.db, p["id"])["state"] == "rewound"


def test_files_are_put_back_and_new_ones_set_aside(tmp_path):
    s = _store(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    good = ws / "app.py"
    good.write_text("print('works')\n")
    p1 = tt.checkpoint(s.db, tmp_path, "write_file", "app.py", [good])
    good.write_text("this is broken now")
    p2 = tt.checkpoint(s.db, tmp_path, "write_file", "junk.py", [ws / "junk.py"])
    (ws / "junk.py").write_text("junk")
    pl = tt.plan(s.db, tmp_path, p1["id"])
    assert pl["restore"] == [str(good)] and pl["remove"] == [str(ws / "junk.py")] and pl["steps"] == 2
    got = tt.rewind(s.db, tmp_path, p1["id"])
    assert good.read_text() == "print('works')\n" and not (ws / "junk.py").exists()
    aside = Path(got["aside"])
    assert any(p.read_text() == "junk" for p in aside.rglob("junk.py")), "nothing is deleted"
    assert any(p.read_text() == "this is broken now" for p in aside.rglob("app.py"))
    assert tt.get(s.db, p2["id"])["state"] == "rewound"


def test_a_shell_step_is_marked_and_a_big_file_is_named(tmp_path, monkeypatch):
    s = _store(tmp_path)
    p = tt.checkpoint(s.db, tmp_path, "run_command", "rm -rf build/")
    assert p["unseen"] == 1
    pl = tt.plan(s.db, tmp_path, p["id"])
    assert "not in the timeline" in pl["warning"] and pl["unseen"][0]["detail"] == "rm -rf build/"
    monkeypatch.setattr(tt, "FILE_CAP", 10)
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 100)
    assert "over" in tt.capture(tmp_path, big)["skipped"]
    assert not tt.changes_things("read_file") and tt.changes_things("write_file") and tt.changes_things("remember")


def test_the_gate_takes_a_checkpoint_after_allowing(tmp_path):
    from agentos import policy
    from agentos.agent import Agent
    from agentos.tools import Toolbox
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("before")
    cfg = {"agent_name": "Aria", "autonomy": "full", "workspace": str(ws), "max_steps": 4,
           "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0}}
    s = _store(tmp_path)
    tb = Toolbox(cfg, s)
    tb.pdp = policy.PDP(cfg, s)
    seen = []

    async def emit(ev):
        seen.append(ev)

    async def approver(*a, **k):
        return True
    ag = Agent(cfg, tb, "ollama/x", emit, approver, conversation_id="c1")
    out, ok, *_ = asyncio.run(ag.call_tool("write_file", {"path": "a.txt", "content": "after"}))
    assert ok and (ws / "a.txt").read_text() == "after"
    pts = tt.points(s.db, "c1")
    assert len(pts) == 1 and pts[0]["files"][0]["path"] == str(ws / "a.txt")
    assert any(e["type"] == "checkpoint" and e["id"] == pts[0]["id"] for e in seen)
    tt.rewind(s.db, tmp_path, pts[0]["id"])
    assert (ws / "a.txt").read_text() == "before"
    # a refused step takes no checkpoint
    tb.pdp = None
    cfg["policies"] = [{"match": "write_file", "action": "deny"}]
    out, ok, *_ = asyncio.run(ag.call_tool("write_file", {"path": "b.txt", "content": "x"}))
    assert not ok and len(tt.points(s.db)) == 1
    # reading takes none either
    asyncio.run(ag.call_tool("read_file", {"path": "a.txt"}))
    assert len(tt.points(s.db)) == 1


def test_a_fork_starts_from_that_turns_question(tmp_path):
    s = _store(tmp_path)
    cid = s.create_conversation("Build it")
    s.add_message(cid, "user", "Hello")
    s.add_message(cid, "assistant", "Hi")
    time.sleep(0.01)
    s.add_message(cid, "user", "Build the synth app")
    time.sleep(0.01)
    tt.checkpoint(s.db, tmp_path, "write_file", "synth.html", conversation_id=cid)
    time.sleep(0.01)
    p = tt.checkpoint(s.db, tmp_path, "write_file", "synth.js", conversation_id=cid)
    fk = tt.fork_history(s.db, s.get_messages(cid), p["id"])
    assert fk["ask"] == "Build the synth app" and [m["content"] for m in fk["history"]] == ["Hello", "Hi"]
    assert fk["already"] == ["write_file: synth.html"]


def test_it_is_pruned_and_never_touches_the_ledger(tmp_path):
    s = _store(tmp_path)
    blob_file = tmp_path / "f.txt"
    blob_file.write_text("old")
    old = tt.checkpoint(s.db, tmp_path, "write_file", "f.txt", [blob_file])
    s.db.execute("UPDATE _tt_points SET ts=? WHERE id=?", (time.time() - 30 * 86400, old["id"]))
    s.db.commit()
    assert tt.prune(s.db, tmp_path) == 1
    assert not list((tmp_path / ".timetravel" / "blobs").rglob("*.*")) or True
    assert not any(b.is_file() for b in (tmp_path / ".timetravel" / "blobs").rglob("*"))
    src = (ROOT / "agentos/timetravel.py").read_text()
    assert "audit" not in tt.TABLES and '"audit"' not in src.split("TABLES =")[1].split("\n")[0]


def test_every_face_reaches_it():
    src = (ROOT / "agentos/server.py").read_text()
    for route in ('@app.get("/api/timetravel")', '@app.get("/api/timetravel/{pid}/plan")',
                  '@app.post("/api/timetravel/{pid}/rewind")', '@app.post("/api/timetravel/{pid}/fork")'):
        assert route in src, route
    assert "def _timetravel_cli(" in (ROOT / "agentos/__main__.py").read_text()
    js = (JS / "00j-timetravel.js").read_text()
    for fn in ("function renderTimeTravel(", "function ttLayoutSave(", "function ttLayoutRestore(",
               "function ttRewind(", "function ttFork("):
        assert fn in js, fn
    assert "/plan" in js, "the scrubber shows the same plan the rewind does"
    ws = (JS / "09-websocket.js").read_text()
    assert "case 'checkpoint'" in ws and "case 'timetravel'" in ws
