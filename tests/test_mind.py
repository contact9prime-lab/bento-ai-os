"""The Mind scene: your agents, what they know and how it connects, as one picture.

Asked for with a video of a glowing brain on a wall screen ("get into the brains of
our agents and their data and how that is interconnected"). What these defend:

- every cluster, filament and number comes from the person's own database (mind.py),
  so the picture cannot show a connection that is not there;
- two agents are linked only when one actually asked the other;
- the spoken summary says the panel's numbers and nothing else, and an empty week
  says so;
- the page draws only while its scene is on, sparks only on real events (the one seam,
  scenePulse), sleeps when covered, and every tap target carries data, never a name
  pasted into an onclick;
- the terminal gets the same snapshot (`bento mind`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import fabric, mind                               # noqa: E402
from agentos.memory import Store                               # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "agentos" / "ui" / "src" / "js"
CFG = {"agent_name": "Ada", "providers": {}, "default_model": "", "team": {}}


def _ask(store, frm, to, text="what changed?"):
    rid = store.fabric_run_start(
        "message", to, f"{frm} (another agent on this team) asks you:\n\n{text}\n\nAnswer in a few lines.")
    store.fabric_run_finish(rid, "ok", output="nothing much")
    return rid


def test_the_picture_is_the_database(tmp_path):
    store = Store(tmp_path / "t.db")
    for n in ("researcher", "writer", "idle-one"):
        store.save_subagent({"name": n, "soul": "x", "skills": ["summarise"] if n == "writer" else []})
    store.add_memory("Prefers short answers", pinned=1)
    store.add_memory("Runs a studio in Pune")
    store.kg_add("Priya", "works at", "Studio")
    store.kg_add("Acme", "is a client of", "Studio")
    store.save_flow({"name": "morning-news", "mission": "read", "roster": [{"subagent": "researcher"}],
                     "enabled": 1})
    rid = store.fabric_run_start("delegate", "researcher", "look up the renewal date")
    store.fabric_run_finish(rid, "ok", tokens_in=100, tokens_out=20)
    bad = store.fabric_run_start("delegate", "writer", "draft the note")
    store.fabric_run_finish(bad, "error", fault="boom")
    _ask(store, "researcher", "writer")
    _ask(store, "writer", "researcher")

    s = mind.snapshot(store, CFG, running={"researcher"})
    hubs = {h["id"]: h for h in s["hubs"]}
    assert {"memory", "knowledge", "missions", "agent:researcher", "agent:writer", "agent:idle-one"} <= set(hubs)
    assert hubs["agent:researcher"]["busy"] and not hubs["agent:writer"]["busy"]
    by = lambda hub: [n for n in s["nodes"] if n["hub"] == hub]
    assert len(by("memory")) == 2 and any(n["pinned"] for n in by("memory"))
    assert {n["label"] for n in by("knowledge")} == {"Priya", "Studio", "Acme"}
    assert by("missions")[0]["label"] == "morning-news" and by("missions")[0]["on"]
    assert [n["label"] for n in by("agent:writer") if n.get("kind") == "skill"] == ["summarise"]
    assert any(n.get("status") == "error" for n in by("agent:writer")), "a failed run shows as one"
    assert not by("agent:idle-one"), "an agent that did nothing holds nothing"
    kinds = [k["kind"] for k in s["links"]]
    assert kinds.count("fact") == 2
    assert {"a": "f:morning-news", "b": "agent:researcher", "kind": "roster"} in s["links"]
    talk = [k for k in s["links"] if k["kind"] == "talk"]
    assert talk == [{"a": "agent:researcher", "b": "agent:writer", "kind": "talk", "n": 2}]
    assert not any("idle-one" in (k["a"] + k["b"]) for k in s["links"]), "no link nobody made"
    st = s["stats"]
    assert (st["runs"], st["failed"], st["asks"], st["memories"], st["knowledge"], st["facts"]) == \
        (4, 1, 2, 2, 3, 2)
    assert st["tokens"] == 120


def test_the_spoken_summary_is_the_panel(tmp_path):
    store = Store(tmp_path / "t.db")
    empty = mind.snapshot(store, CFG)
    assert empty["spoken"] == ("Your team has not run anything this week. "
                               "I have not saved anything about you yet.")
    store.save_subagent({"name": "researcher", "soul": "x"})
    store.save_subagent({"name": "writer", "soul": "x"})
    _ask(store, "researcher", "writer")
    store.add_memory("Coffee over tea")
    s = mind.snapshot(store, CFG, running={"writer"})
    said = s["spoken"]
    assert "ran 1 task." in said and "asked each other 1 time." in said
    assert "Right now writer is working." in said and "I remember 1 thing about you." in said
    # nothing it says is a number the panels do not carry
    import re
    for n in re.findall(r"\d+", said):
        assert int(n) in {s["stats"][k] for k in s["stats"]}, n


def test_a_free_talk_is_conversation_not_tasks(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "a", "soul": "x"})
    sid = store.fabric_run_start("freetalk", "team", "(anything useful)\n\nagents: a · 5 min · 20 messages · talk")
    for _ in range(3):
        store.fabric_run_start("freetalk", "a", "say something", parent_run=sid)
    s = mind.snapshot(store, CFG)
    assert s["stats"]["runs"] == 0 and s["stats"]["free_talks"] == 1


def test_the_page_draws_only_what_happened():
    src = (JS / "01g-mind.js").read_text()
    imm = (JS / "01b-immersive.js").read_text()
    assert "'mind'" in imm.split("var IMMERSIVE_SCENES=", 1)[1].split(";", 1)[0]
    assert "mindStart()" in imm and "mindStop()" in imm and "imm-mind" in imm
    # one seam: only scenePulse feeds it
    for f in JS.glob("*.js"):
        if f.name in ("01g-mind.js", "01c-movement.js"):
            continue
        assert "mindPulse(" not in f.read_text(), f.name
    assert "mindPulse(kind,label,ev)" in (JS / "01c-movement.js").read_text().split("function scenePulse(", 1)[1].split("\n}", 1)[0]
    # it sleeps, caps its frame rate and never polls for the sake of animation
    assert "crewCovered()" in src and "setInterval" not in src
    assert "lively?30:12" in src and "prefers-reduced-motion" in src
    assert "/api/mind" in src and "filter" not in src.split("function mindDraw(", 1)[1].split("\nfunction ", 1)[0]
    # a tap carries data; a name is never pasted into an onclick string
    assert "data-hub=" in src and "onclick=\"mindCard(" not in src
    assert "speakAs('@agent',S.spoken" in src, "Tell me says the snapshot's own sentence"
    settings = (JS / "11-settings.js").read_text()
    assert "['mind','Mind:" in settings
    assert (ROOT / "agentos/ui/src/css/26-mind.css").exists()


def test_the_route_and_the_terminal():
    srv = (ROOT / "agentos/server.py").read_text()
    route = srv.split('@app.get("/api/mind")', 1)[1].split("\n@app.", 1)[0]
    assert "mindmod.snapshot" in route and 'state["store"]' in route
    main = (ROOT / "agentos/__main__.py").read_text()
    assert 'verb("mind"' in main and "mindmod.snapshot(store, cfg)" in main
    assert fabric.talk_log   # the links are read from the one agent-to-agent log
