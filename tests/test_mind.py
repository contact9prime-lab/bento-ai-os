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
import json
import re
import sys
from pathlib import Path

import pytest

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
    assert "lively?30:20" in src and "prefers-reduced-motion" in src
    assert "/api/mind" in src and "filter" not in src.split("function mindDraw(", 1)[1].split("\nfunction ", 1)[0]
    # a tap carries data; a name is never pasted into an onclick string
    assert "data-hub=" in src and "onclick=\"mindCard(" not in src
    assert "speakAs('@agent',S.spoken" in src, "Tell me says the snapshot's own sentence"
    settings = (JS / "11-settings.js").read_text()
    assert "['mind','Mind']" in settings
    assert (ROOT / "agentos/ui/src/css/26-mind.css").exists()


def test_the_route_and_the_terminal():
    srv = (ROOT / "agentos/server.py").read_text()
    route = srv.split('@app.get("/api/mind")', 1)[1].split("\n@app.", 1)[0]
    assert "mindmod.snapshot" in route and 'state["store"]' in route
    main = (ROOT / "agentos/__main__.py").read_text()
    assert 'verb("mind"' in main and "mindmod.snapshot(store, cfg)" in main
    assert fabric.talk_log   # the links are read from the one agent-to-agent log


def test_what_it_remembers_is_joined_to_what_it_knows(tmp_path):
    """From a screenshot: Memory and Knowledge sat as two clouds with nothing between
    them. A memory or a run that names an entity is joined to it, whole words only."""
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher", "soul": "x"})
    store.add_memory("Priya leads the Acme account")
    store.add_memory("Prefers tea")                                   # names nobody
    store.kg_add("Priya", "leads", "Acme")
    store.kg_add("Al", "knows", "Priya")                              # too short to match
    rid = store.fabric_run_start("delegate", "researcher", "find out when Acme renews")
    store.fabric_run_finish(rid, "ok")
    s = mind.snapshot(store, CFG)
    names = {n["id"]: n["label"] for n in s["nodes"]}
    ment = [(names[k["a"]], names[k["b"]]) for k in s["links"] if k["kind"] == "mention"]
    assert ("Priya leads the Acme account", "Priya") in ment
    assert ("Priya leads the Acme account", "Acme") in ment
    assert any(b == "Acme" and a.startswith("find out") for a, b in ment), "a run names it too"
    assert not any(b == "Al" for _, b in ment), "a two-letter name matches everything"
    assert not any(a == "Prefers tea" for a, _ in ment)
    assert s["stats"]["mentions"] == len(ment)
    assert all("full" not in n for n in s["nodes"]), "the page gets the short label only"


def test_peace_shows_only_the_mind():
    src = (JS / "01g-mind.js").read_text()
    css = (ROOT / "agentos/ui/src/css/26-mind.css").read_text()
    assert "function mindPeace(" in src and "localStorage.setItem('mind.peace'" in src
    assert "k.kind!=='mention'" in src, "the lines between clusters are drawn"
    for sel in (".mn-left", ".mn-right", ".mn-tags", ".mn-card"):
        assert f"#mind-ui.peace {sel}" in css, sel
    assert "body.mind-peace" in css and "#omnibar:not(.summoned)" in css
    assert "classList.remove('mind-peace')" in src, "leaving the scene gives the bar back"


def test_the_core_speaks_with_the_voice_and_the_neurons_rest_awake():
    """"The centre is just beeping while speaking" and "the neurons in standby should be
    sending signals anyway", with a screenshot that read as too systematic.
    - the core follows the SOUND through an analyser, and the tap is only made on a
      running AudioContext, because routing the voice into a suspended one silences it;
    - resting glints are scenery and are kept apart from news: they never flare a
      cluster, and only mindPulse (fed by scenePulse) sends a spark;
    - fibres wander (mindFibre) and the ring is not a clock face."""
    src = (JS / "01g-mind.js").read_text()
    tap = src.split("function mindTap(", 1)[1].split("\n}", 1)[0]
    assert "createMediaElementSource" in tap and "state!=='running'" in tap
    assert tap.index("state!=='running'") < tap.index("createMediaElementSource")
    voice = src.split("function mindVoice(", 1)[1].split("\n}", 1)[0]
    assert "getByteFrequencyData" in voice and "SPEECH.audio" in voice
    core = src.split("function mindCore(", 1)[1].split("\n}", 1)[0]
    assert "v.bins" in core and "ellipse(" not in core, "the soma, not two orbits"
    glints = src.split("function mindGlint(", 1)[1].split("\nfunction mindSparks(", 1)[0]
    assert "MIND.flare" not in glints and "MIND.sparks" not in glints, "a glint is never news"
    assert "MIND.flare[s.to]=1" in src.split("function mindSparks(", 1)[1]
    assert "mindGlint(" not in src.split("function mindPulse(", 1)[1].split("\n}", 1)[0]
    draw = src.split("function mindDraw(", 1)[1].split("\nfunction ", 1)[0]
    assert "mindNodeFibre(" in draw and "quadraticCurveTo(qx" not in draw
    layout = src.split("function mindLayout(", 1)[1].split("\n}", 1)[0]
    assert "far=" in layout and "den.push" in layout


def test_other_companies_and_unattached_agents_are_one_cluster_each(tmp_path):
    """Reported with a screenshot of 47 clusters: "the mind should be better organized". Only the
    open company's departments were grouped; everybody in a parked company, and everybody in no
    company, stood as a cluster of their own."""
    store = Store(tmp_path / "t.db")
    loose = [f"solo{i}" for i in range(mind.MAX_OWN + 1)]
    for n in ["seller", "closer", "ops1", "ops2", "legal1"] + loose:
        store.save_subagent({"name": n, "soul": "x"})
    cfg = {"agent_name": "Aria",
           "company": {"id": "aaaa1111", "name": "Open Co"},
           "office": {"departments": [{"name": "Sales", "members": ["seller", "closer"], "lead": "seller"}]},
           "companies": {"bbbb2222": {"company": {"id": "bbbb2222", "name": "Other Co"},
                                      "office": {"departments": [
                                          {"name": "Ops", "members": ["ops1", "ops2"], "lead": "ops1"},
                                          {"name": "Legal", "members": ["legal1"]}]}}}}
    rid = store.fabric_run_start("delegate", "ops2", "reconcile the ledger")
    store.fabric_run_finish(rid, "ok")
    s = mind.snapshot(store, cfg, running={"ops1"})
    hubs = {h["id"]: h for h in s["hubs"]}
    assert set(hubs) == {"memory", "knowledge", "missions", "dept:Sales", "co:bbbb2222", mind.LOOSE}
    other = hubs["co:bbbb2222"]
    assert other["label"] == "Other Co" and other["company"] and other["busy"], "one working person lights it"
    assert sorted(other["members"]) == ["legal1", "ops1", "ops2"]
    people = {n["label"]: n for n in s["nodes"] if n["hub"] == "co:bbbb2222" and n["kind"] == "person"}
    assert people["ops1"]["title"].startswith("Ops") and people["legal1"]["title"].startswith("Legal")
    assert any(n["kind"] == "run" and n["hub"] == "co:bbbb2222" for n in s["nodes"]), "its work sits on it"
    assert hubs[mind.LOOSE]["label"] == mind.LOOSE_LABEL and sorted(hubs[mind.LOOSE]["members"]) == sorted(loose)
    assert s["where"]["ops2"] == "co:bbbb2222" and s["where"]["solo0"] == mind.LOOSE
    row = {t["name"]: t for t in s["team"]}
    assert row["ops1"]["hub"] == "co:bbbb2222" and row["ops1"]["group"] == "Other Co"
    assert row["seller"]["hub"] == "dept:Sales" and row["seller"]["dept"] == "Sales"


def test_a_few_unattached_agents_keep_a_cluster_each(tmp_path):
    store = Store(tmp_path / "t.db")
    for n in ("a", "b"):
        store.save_subagent({"name": n, "soul": "x"})
    hubs = {h["id"] for h in mind.snapshot(store, {"agent_name": "Aria"})["hubs"]}
    assert {"agent:a", "agent:b"} <= hubs and mind.LOOSE not in hubs


def test_the_page_groups_its_team_list_by_cluster():
    js = (ROOT / "agentos/ui/src/js/01g-mind.js").read_text() if "ROOT" in globals() else \
        (Path(__file__).parent.parent / "agentos/ui/src/js/01g-mind.js").read_text()
    assert "S.team.filter(a=>a.hub===h.id)" in js, "one row per cluster, not one per person"
    assert "(a.hub||'').indexOf('agent:')===0" in js
    assert "h.company?" in js and ":h.loose?" in js, "a task goes only to a department of the open company"


def test_speaking_moves_the_cores_edge_and_never_floods_the_picture():
    """Reported with a screenshot, "the mind animation is so screwed": speaking, the core was a
    white disc some 220px across with lumpy rings 318px out, over the clusters. Every reach is
    a multiple of the radius in MIND_CORE, and the radius itself is bounded."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    src = (ROOT / "agentos/ui/src/js/01g-mind.js").read_text()
    decl = re.search(r"^var MIND_CORE=.*?;$", src, re.M).group(0)
    fn = re.search(r"^function mindCoreR\(.*$", src, re.M).group(0)
    js = decl + fn + ("const r=mindCoreR(1,1),q=mindCoreR(.25,0);"
                      "console.log(JSON.stringify({r,q,over:mindCoreR(9,9),halo:r*MIND_CORE.halo,ring:r*MIND_CORE.ring,"
                      "edge:r*(1+.14+MIND_CORE.edge),rings:MIND_CORE.rings}))")
    d = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert d["r"] <= 45 and d["r"] - d["q"] <= 12, "speaking adds a few pixels to the core, it does not double it"
    assert d["over"] == d["r"], "a level past 1 changes nothing"
    assert d["edge"] <= 70 and d["halo"] <= 160 and d["ring"] <= 130 and d["rings"] <= 4
    core = src.split("function mindCore(", 1)[1].split("\n}", 1)[0]
    assert "R*4.4" not in core and "u*3.2" not in core and "*.92" not in core
    css = (ROOT / "agentos/ui/src/css/26-mind.css").read_text()
    assert "body.mind-telling:not(.has-win) #omnibar" in css, "the spoken line is not written under the prompt bar"
    assert "classList.remove('mind-telling')" in src
