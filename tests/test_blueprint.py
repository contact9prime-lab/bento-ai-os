"""The Stage's blueprint and the X-ray (agentos/stage.py `blueprint`, agentos/xray.py,
24v-blueprint.js). Asked for as "give me a fine blueprint of Burj Khalifa … it opens the
building inside out and I can drill into anything", and as a Jarvis-style blueprint that gets
to the bottom of things rather than presenting a chart. Pinned here:

- a blueprint is a closed set read at every level: parts nest four deep, what is dropped is
  named with where it was, ids are unique, links resolve by name, a width over 1 is a real
  width;
- its numbers say where they came from (the scene's source, or a part's own);
- the agent is told how to make one with Answer BIG on and off, and "Take this apart" asks
  for one part by its place in the whole;
- an X-ray is the trace, drawn: exactly that turn's ledger rows and runs, a refusal and an
  ask stated as such, and what the record cannot see said in words;
- one painter: the desk and the phone's page draw it with the same file, as text.
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import stage, xray  # noqa: E402

ROOT = Path(__file__).parent.parent
PAINTER = ROOT / "agentos/ui/src/js/24v-blueprint.js"
STAGE_JS = ROOT / "agentos/ui/src/js/24l-stage.js"


def _burj(**kw):
    spec = {"kind": "blueprint", "title": "Burj Khalifa", "unit": "m", "source": "CTBUH",
            "parts": [
                {"name": "Foundation", "from": -50, "to": 0, "width": 140, "role": "holds it up",
                 "facts": [{"label": "piles", "value": 192}],
                 "parts": [{"name": "Raft", "parts": [{"name": "Concrete", "parts": [
                     {"name": "Aggregate", "parts": [{"name": "too deep"}]}]}]},
                           {"name": "Piles", "certainty": "estimated"}]},
                {"name": "Spire", "from": 585, "to": 828, "width": 6, "status": "ok"},
                {"name": "Spire", "from": 0, "to": 1}]}
    spec.update(kw)
    return stage.clean(spec)


def test_a_blueprint_is_a_closed_set_at_every_level():
    sc, dropped = _burj(links=[{"from": "Spire", "to": "Foundation", "verb": "stands on"},
                               {"from": "nothing", "to": "Spire"}], unknowns=["", "pile loads today"])
    assert sc["kind"] == "blueprint" and sc["form"] == "tower" and sc["subject"] == "Burj Khalifa"
    # four levels under the subject, the fifth named rather than silently lost
    assert any("deeper than 4" in d for d in dropped)
    assert [p["id"] for p in sc["parts"]] == ["foundation", "spire", "spire-2"]
    assert sc["links"] == [{"from": "spire", "to": "foundation", "verb": "stands on", "kind": ""}]
    assert "links[1] (names a part that is not there)" in dropped
    assert sc["unknowns"] == ["pile loads today"]
    # 0 to 1 is a share of the widest; over 1 is the real width, kept
    assert sc["parts"][0]["width"] == 140 and sc["parts"][1]["width"] == 6
    sc2, d2 = stage.clean({"kind": "blueprint", "parts": [
        {"name": "a", "colour": "red", "certainty": "sure", "status": "great", "form": "cube"},
        {"name": "b", "width": 0.001}, "c", {"role": "no name"}]})
    assert {"parts[0].colour", "parts[0].certainty 'sure'", "parts[0].status 'great'",
            "parts[0].form 'cube'", "parts[3] (a part needs a name)"} <= set(d2)
    assert sc2["parts"][0]["certainty"] == "known" and sc2["parts"][1]["width"] == 0.02
    assert sc2["form"] == "exploded" and [p["name"] for p in sc2["parts"]] == ["a", "b", "c"]
    with pytest.raises(ValueError, match="at least two"):
        stage.clean({"kind": "blueprint", "parts": [{"name": "alone"}]})
    # too many at one level, and too many in all, are named
    _, d3 = stage.clean({"kind": "blueprint", "parts": [{"name": f"p{i}"} for i in range(20)]})
    assert any("past 12 at one level" in d for d in d3)
    many = [{"name": f"a{i}", "parts": [{"name": f"b{i}-{j}", "parts": [{"name": f"c{i}-{j}-{k}"}
                                                                          for k in range(12)]}
                                         for j in range(12)]} for i in range(3)]
    sc4, d4 = stage.clean({"kind": "blueprint", "parts": many})
    assert sum(1 for _ in stage.bp_walk(sc4["parts"])) == stage.BP_NODES
    assert any(f"past the limit of {stage.BP_NODES}" in d for d in d4)
    # a web page's controls never reach the page or a terminal
    sc5, _ = stage.clean({"kind": "blueprint", "parts": [{"name": "x\x1b]0;pwned\x07"}, "y"]})
    assert "\x1b" not in sc5["parts"][0]["name"]


def test_a_blueprints_numbers_say_where_they_came_from():
    bare = {"kind": "blueprint", "parts": [{"name": "a", "facts": [{"label": "h", "value": 828}]}, "b"]}
    with pytest.raises(ValueError, match="came from"):
        stage.clean(bare)
    with pytest.raises(ValueError, match="came from"):   # a height is a measurement too
        stage.clean({"kind": "blueprint", "parts": [{"name": "a", "from": 0, "to": 9}, "b"]})
    stage.clean({**bare, "source": "CTBUH"})
    stage.clean({**bare, "illustrative": True})
    # a part's own source covers it and everything inside it
    stage.clean({"kind": "blueprint", "parts": [
        {"name": "a", "source": "SOM", "facts": [{"label": "h", "value": 1}],
         "parts": [{"name": "a1", "facts": [{"label": "w", "value": 2}]}, "a2"]}, "b"]})
    # words alone are not measurements
    stage.clean({"kind": "blueprint", "parts": [{"name": "a", "role": "holds it"}, "b"]})


def test_the_terminal_and_the_phone_read_it():
    sc, _ = _burj(unknowns=["pile loads today"])
    t = stage.text(sc)
    assert t.startswith("▶ Burj Khalifa") and "⌖ tower" in t
    assert "├─ Foundation [-50 → 0 m] — holds it up  · piles 192" in t
    assert "│  └─ Piles (estimated)" in t and "✓ Spire" in t and "? pile loads today" in t
    cap = stage.still_caption(sc, 0, 1)
    assert "1. Foundation: holds it up (2 parts inside)" in cap
    assert stage.bp_value({"value": "828", "unit": "m"}) == "828 m"
    assert stage.bp_value({"value": "$1.69", "unit": "$"}) == "$1.69"
    assert stage.bp_value({"value": "12", "unit": "%"}) == "12%"


def test_the_agent_is_told_how_and_the_tool_offers_it():
    on, off = stage.note({"stage": {"big": True}}), stage.note({"stage": {"big": False}})
    for n in (on, off):
        assert "blueprint" in n and "certainty" in n and "unknowns" in n and "really is" in n
    from agentos.tools import TOOL_SCHEMAS
    schema = next(s for s in TOOL_SCHEMAS if s["name"] == "show_scene")
    props = schema["parameters"]["properties"]
    assert props["kind"]["enum"] == list(stage.KINDS)
    for k in ("subject", "form", "parts", "links", "unknowns"):
        assert k in props and k in stage.FIELDS["blueprint"]
    assert props["form"]["enum"] == list(stage.BP_FORMS)


def test_take_this_apart_asks_for_one_part_by_its_place(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "blueprint of burj khalifa")
    sc, _ = _burj()
    row = stage.add(store, cid, sc)
    q = stage.ask_deeper(store, cid, row["answer_to"], row["seq"], part="piles")
    assert q.startswith('Go deeper on "Piles" in Burj Khalifa › Foundation')
    assert "as its own blueprint" in q
    with pytest.raises(ValueError, match="not in this blueprint"):
        stage.ask_deeper(store, cid, row["answer_to"], row["seq"], part="nope")
    other, _ = stage.clean({"kind": "steps", "items": ["a"]})
    r2 = stage.add(store, cid, other)
    with pytest.raises(ValueError, match="only a blueprint"):
        stage.ask_deeper(store, cid, r2["answer_to"], r2["seq"], part="piles")
    # the next story is linked to the scene it went deeper on, as Go deeper always was
    store.add_message(cid, "user", q)
    child = stage.add(store, cid, sc)
    assert stage.links(store, cid)[child["answer_to"]] == {"answer_to": row["answer_to"], "seq": row["seq"]}


def _turn(store, cid, *, engine="claude-code"):
    q = store.add_message(cid, "user", "backtest the spread and give it to your departments")
    time.sleep(0.01)
    store.audit_add("user", "", "gui", "agent.invoke", "agent:flow/research-desk", "allow", "5608e405c0cd",
                    conversation_id=cid, outcome="ok", duration_ms=1200)
    desk = store.fabric_run_start("flow", "research-desk", "deepen the spread", conversation_id=cid,
                                  flow="research-desk", origin_surface="chat")
    lead = store.fabric_run_start("delegate", "research-lead", "write a plan", parent_run=desk,
                                  conversation_id=cid)
    store.audit_add("subagent", "research-lead", "gui", "fs.read", "fs:/data/a.csv", "allow", "default",
                    conversation_id=cid, run_id=lead, outcome="ok")
    store.audit_add("subagent", "research-lead", "gui", "tool.use", 'tool:run_python {"code": "1"}', "ask",
                    "29f9b3453ac8", conversation_id=cid, run_id=lead, outcome="ok")
    store.audit_add("subagent", "research-lead", "gui", "tool.use", 'tool:run_command {"command": "rm -rf /"}',
                    "deny", "builtin", conversation_id=cid, run_id=lead, outcome="denied")
    store.fabric_run_finish(lead, "ok", output="the plan", tokens_in=100, tokens_out=50, steps=3)
    store.fabric_run_finish(desk, "error", fault="the quant was not on the roster")
    store.usage_add("claude-code/claude-opus-5-5", 1000, 200, 0.42, conversation_id=cid)
    store.add_message(cid, "assistant", "I ran it and handed the rest on.",
                      meta={"engine": engine, "engine_model": "claude-opus-5-5", "steps": []})
    return q


def test_an_xray_is_that_turns_record_and_nothing_else(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("Research")
    q = _turn(store, cid)
    time.sleep(0.01)
    # the next turn's rows are not this turn's
    store.add_message(cid, "user", "thanks")
    store.audit_add("user", "", "gui", "fs.write", "fs:/x", "allow", "default", conversation_id=cid)
    sc = xray.turn(store, {"agent_name": "Aria"}, cid, q)
    assert sc["kind"] == "blueprint" and sc["form"] == "flow" and sc["source"] == xray.SOURCE
    names = [p["name"] for p in sc["parts"]]
    assert names == ["You asked", "Aria, on Claude Code", "research-desk (desk)", "The answer"]
    assert sc["xray"]["decisions"] == 4 and sc["xray"]["refused"] == 1 and sc["xray"]["asked"] == 1
    assert sc["xray"]["cost"] == 0.42
    # the caption is the takeaway, from the rows
    assert sc["caption"].startswith("Aria handed it to research-desk, 1 person worked on it, the gate made 4 "
                                    "decisions, refused 1, asked you 1 and research-desk ended with an error")
    desk = sc["parts"][2]
    assert desk["status"] == "failed" and "the quant was not on the roster" in desk["detail"]
    lead = desk["parts"][0]
    assert lead["name"] == "@research-lead" and lead["status"] == "ok"
    groups = {g["name"]: g for g in lead["parts"]}
    assert set(groups) == {"read a file", "run_python", "run_command"}
    assert groups["run_command"]["status"] == "refused" and groups["run_python"]["status"] == "asked"
    row = groups["run_command"]["parts"][0]
    assert row["status"] == "refused" and "rm -rf /" in row["role"] and row["evidence"].startswith("ledger #")
    assert "by builtin" in row["detail"]
    # a grant's id is a permission somebody gave, said so
    assert "a permission you gave (29f9b3)" in groups["run_python"]["role"]
    brain = sc["parts"][1]
    assert any(f["label"] == "cost" and f["value"] == "$0.42" for f in brain["facts"])
    # what the record cannot see is said, never filled in
    assert any("Claude Code" in u for u in sc["unknowns"])
    # the built-in loop has no session of its own to hide
    cid2 = store.create_conversation("b")
    q2 = _turn(store, cid2, engine="aria")
    assert not any("session" in u for u in xray.turn(store, {}, cid2, q2)["unknowns"])
    with pytest.raises(KeyError):
        xray.turn(store, {}, cid, "not-a-message")
    with pytest.raises(KeyError):
        xray.turn(store, {}, "no-such-chat")


def test_an_xray_of_a_run_starts_at_its_top(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("Research")
    _turn(store, cid)
    lead = store.db.execute("SELECT id FROM fabric_runs WHERE kind='delegate'").fetchone()[0]
    sc = xray.run(store, {}, lead)     # asked about a child: the whole task, from its top
    names = [p["name"] for p in sc["parts"]]
    assert names[0] == "What started it" and names[1] == "research-desk (desk)" and names[-1] == "How it ended"
    assert "started by a chat" in sc["parts"][0]["role"]
    assert sc["parts"][-1]["status"] == "failed"


def test_one_painter_drawn_as_text():
    js = PAINTER.read_text()
    assert "innerHTML" not in js, "a part's words are a model's, often a web page's"
    assert "\nlet " not in js and "\nconst " not in js, "top-level let/const is the bundle's trap"
    # certainty is the line itself and every state has its icon and its word
    assert "BP_DASH={known:''" in js and all(f"{s}:[" in js for s in stage.BP_STATUS)
    # sized from the layout box, and the resize observer lets go of a drawing that left
    assert "draw.clientWidth" in js and "getBoundingClientRect()" not in js.split("function bpRender")[1].split("}")[0]
    assert "if(!art.isConnected){st.ro.disconnect()" in js
    sjs = STAGE_JS.read_text()
    assert "blueprint:stageBlueprint" in sjs and "blueprint:'Blueprint'" in sjs and "blueprint:205" in sjs
    for k in stage.KINDS:
        assert f"{k}:'" in sjs.split("var STAGE_KIND=")[1].split(";")[0], k
    assert stage.STILL_KIND["blueprint"] == "Blueprint"
    # the phone's page embeds the same painter and its styles
    assert stage.PAINTER_JS[:2] == ("24l-stage.js", "24v-blueprint.js")
    assert "40-blueprint.css" in stage.PAINTER_CSS


def test_the_phones_page_draws_a_blueprint(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    q = store.add_message(cid, "user", "blueprint please </script>")
    sc, _ = _burj()
    stage.add(store, cid, sc)
    page = stage.report_html(store, cid, q, agent="Aria")
    assert "function stageBlueprint(" in page and ".bp-spec" in page
    assert page.count("</script>") == 1


def test_the_doors_to_an_xray():
    chat = (ROOT / "agentos/ui/src/js/10-chat.js").read_text()
    assert "xrayAttach(cid)" in chat
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "xrayLive(_cid,curBody.closest('.msg'))" in ws
    hist = (ROOT / "agentos/ui/src/js/14c-history.js").read_text()
    assert "data-xray-run" in hist and "data-xray-conv" in hist
    fab = (ROOT / "agentos/ui/src/js/13-fabric.js").read_text()
    assert "stageXray({run:FG.run}" in fab
    srv = (ROOT / "agentos/server.py").read_text()
    assert '@app.get("/api/stage/xray")' in srv and 'part=str(b.get("part") or "")' in srv
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert '"xray", "contact", "export"])' in cli and "xraymod.turn(store, cfg, cid, args.answer)" in cli


def test_the_xray_route_answers_in_words(tmp_path, monkeypatch):
    # called directly on a throwaway store, not through a TestClient: the server's own store
    # is opened on the developer's home, and nothing here should start its runners
    import asyncio
    from agentos import server as servermod
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    monkeypatch.setitem(servermod.state, "store", store)
    monkeypatch.setitem(servermod.state, "cfg", {"agent_name": "Aria"})
    cid = store.create_conversation("Research")
    q = _turn(store, cid)
    r = asyncio.run(servermod.api_stage_xray())
    assert r.status_code == 400
    r = asyncio.run(servermod.api_stage_xray(run="nothing-here"))
    assert r.status_code == 404 and b"no record" in r.body
    got = asyncio.run(servermod.api_stage_xray(conversation=cid, answer_to=q))
    assert got["scene"]["kind"] == "blueprint" and got["scene"]["xray"]["decisions"] == 4
    rid = store.db.execute("SELECT id FROM fabric_runs WHERE kind='flow'").fetchone()[0]
    assert asyncio.run(servermod.api_stage_xray(run=rid))["scene"]["parts"][0]["name"] == "What started it"
