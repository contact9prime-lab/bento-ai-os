"""The World scene: agents with feelings, and a lead that asks how you are.

Asked for as "Sims-like agents with tantrums, different worlds with different emotions
and growth, people build their own; the lead asks how you are feeling; all experimental,
and the moment I leave the world scene it's all evaporated, and back when I return.
Scene matters." What these pin:

- a world is LIVE only under the scene's lease; out of it nothing is felt, nothing is
  read, and no agent is told anything, and on return the state is back;
- every feeling comes from a real event, and the why says which;
- your "no" and your hard day never make anybody sad, in any world, built or designed;
- "agents feel it" reaches prompts only while live and switched on, and says in words
  that feelings never change the rules;
- worlds differ, and a designed world is held to the same closed sets.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import world                                      # noqa: E402
from agentos.memory import Store                               # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def store(tmp_path):
    world._LIVE.clear()
    world._STATE.clear()
    world._RUNS.clear()
    world._SPEAKER.clear()
    yield Store(tmp_path / "t.db")
    world._LIVE.clear()
    world._STATE.clear()


def _run(rid, agent, *steps, end="ok"):
    evs = [{"type": "fabric_event", "event": "status", "status": "running", "ref": agent, "run_id": rid}]
    evs += [{"type": "fabric_event", "event": "step", "status": "end", "run_id": rid, **s} for s in steps]
    if end:
        evs.append({"type": "fabric_event", "event": "status", "status": end, "ref": agent, "run_id": rid,
                    "steps": len(steps)})
    return evs


def _agent(view, name):
    return next(a for a in view["agents"] if a["name"] == name)


# ------------------------------------------------------------------ scene matters


def test_nothing_is_felt_outside_the_scene_and_it_comes_back(store):
    for ev in _run("r0", "researcher", {"ok": False, "outcome": "rules", "tool": "fetch_url"}, end=""):
        world.observe(ev, "")                       # no world live: nothing happens
    assert world.view("") == {"live": False}
    world.enter("", store, "lantern-canal", ["researcher", "writer"])
    assert _agent(world.view(""), "researcher")["mood"]["id"] == "serene"
    for ev in _run("r1", "researcher", {"ok": False, "outcome": "rules", "tool": "fetch_url"},
                   {"ok": False, "outcome": "rules", "tool": "fetch_url"}, end=""):
        world.observe(ev, "")
    assert _agent(world.view(""), "researcher")["mood"]["name"] == "Flustered"
    world.leave("")
    assert world.view("") == {"live": False}
    assert not world._STATE, "leaving keeps nothing in memory"
    for ev in _run("r2", "writer", {"ok": False, "outcome": "error", "tool": "write_file"}, end="error"):
        world.observe(ev, "")                       # the writer's failure happens while asleep
    v = world.enter("", store, "lantern-canal", ["researcher", "writer"])
    assert _agent(v, "researcher")["mood"]["name"] == "Flustered", "it comes back"
    assert _agent(v, "writer")["mood"]["id"] == "serene", "and nothing was felt while away"


def test_a_missed_lease_puts_the_world_to_sleep(store, monkeypatch):
    world.enter("", store, "lantern-canal", ["researcher"])
    assert world.live_world("") == "lantern-canal"
    t = time.time() + world.LEASE_S + 1
    monkeypatch.setattr(world.time, "time", lambda: t)
    assert world.live_world("") == ""
    assert not world.beat("", "lantern-canal"), "the page must enter again"


def test_each_world_keeps_its_own_state(store):
    world.enter("", store, "lantern-canal", ["researcher"])
    world.praise("", "researcher")
    world.enter("", store, "kestrel-station", ["researcher"])
    assert world.live_world("") == "kestrel-station"
    assert _agent(world.view(""), "researcher")["mood"]["id"] == "nominal"
    world.enter("", store, "lantern-canal", ["researcher"])
    assert _agent(world.view(""), "researcher")["why"][0]["signal"] == "praised"


def test_accounts_do_not_share_a_world(store, tmp_path):
    other = Store(tmp_path / "b.db")
    world.enter("ada", store, "lantern-canal", ["researcher"])
    world.enter("bob", other, "lantern-canal", ["researcher"])
    for ev in _run("r1", "researcher", {"ok": False, "outcome": "rules", "tool": "x"},
                   {"ok": False, "outcome": "rules", "tool": "x"}, end=""):
        world.observe(ev, "ada")
    assert _agent(world.view("ada"), "researcher")["mood"]["name"] == "Flustered"
    assert _agent(world.view("bob"), "researcher")["mood"]["id"] == "serene"


# ------------------------------------------------------------------ feelings are true


def test_every_feeling_names_its_cause(store):
    world.enter("", store, "lantern-canal", ["researcher"])
    for ev in _run("r1", "researcher", {"ok": False, "outcome": "rules", "tool": "fetch_url"},
                   {"ok": False, "outcome": "rules", "tool": "fetch_url"}, end=""):
        world.observe(ev, "")
    a = _agent(world.view(""), "researcher")
    assert a["mood"]["expression"] == "tantrum"
    assert a["why"][0] == {"signal": "refused", "words": world.SIGNALS["refused"],
                           "detail": "fetch_url", "ago": 0}
    assert a["busy"], "an open run is work"


def test_the_signals_come_from_the_real_events(store):
    world.enter("", store, "lantern-canal", ["researcher", "validator"])
    obs = lambda ev: world.observe(ev, "")                               # noqa: E731
    for ev in _run("r1", "researcher", end="ok"):
        obs(ev)
    assert _agent(world.view(""), "researcher")["why"][0]["signal"] == "succeeded"
    obs({"type": "agent_msg", "phase": "ask", "from": "researcher", "to": "validator"})
    obs({"type": "agent_msg", "phase": "reply", "from": "validator", "to": "researcher"})
    assert _agent(world.view(""), "validator")["why"][0]["signal"] == "helped"
    obs({"type": "agent_say", "vote": {"by": "researcher", "approved": True, "yes": 2, "of": 3,
                                       "ballots": [{"agent": "researcher", "yes": True},
                                                   {"agent": "validator", "yes": False}]}})
    assert _agent(world.view(""), "researcher")["why"][0]["signal"] == "vote_won"
    assert _agent(world.view(""), "validator")["why"][0]["signal"] == "outvoted"
    # a chat turn is the lead's, and a specialist's chat turn is counted once, by its run
    obs({"type": "turn_start", "conversation_id": "c1"})
    obs({"type": "tool_end", "conversation_id": "c1", "name": "run_command", "ok": False,
         "output": "[error] 429 rate limit exceeded"})
    assert _agent(world.view(""), world.LEAD)["why"][0]["signal"] == "rate_limited"
    obs({"type": "turn_end", "conversation_id": "c1"})
    obs({"type": "turn_start", "conversation_id": "c2", "speaker": "researcher"})
    before = len(_agent(world.view(""), "researcher")["why"])
    obs({"type": "tool_end", "conversation_id": "c2", "name": "x", "ok": False, "output": "[denied] no"})
    assert len(_agent(world.view(""), "researcher")["why"]) == before


def test_a_run_that_finished_after_a_refusal_is_not_proud(store):
    """Found live: the researcher was refused a file, answered "I couldn't read it", and
    the run's ok made it proud. A snag on the way mutes the pride."""
    world.enter("", store, "lantern-canal", ["researcher"])
    for ev in _run("r1", "researcher", {"ok": False, "outcome": "rules", "tool": "read_file"}, end="ok"):
        world.observe(ev, "")
    a = _agent(world.view(""), "researcher")
    assert a["mood"]["name"] == "Flustered"
    assert a["why"][0]["detail"].endswith("after a snag")
    assert a["level"]["xp"] == 3, "the work still counts toward growing"


def test_your_check_in_does_not_drown_what_happens(store):
    world.enter("", store, "lantern-canal", ["researcher"])
    world.checkin("", "stormy")
    for ev in _run("r1", "researcher", {"ok": False, "outcome": "rules", "tool": "x"}, end=""):
        world.observe(ev, "")
    assert _agent(world.view(""), "researcher")["mood"]["name"] == "Flustered"


def test_step_outcomes_say_whose_no_it_was():
    assert world.step_outcome("[denied] This action was not approved for x") == "person"
    assert world.step_outcome("[denied] This step needs a person to say yes") == "person"
    assert world.step_outcome("[denied] Your team voted this down (1 of 3)") == "vote"
    assert world.step_outcome("[denied] outside the folders this agent reaches") == "rules"
    assert world.step_outcome("[error] boom") == "error"
    assert world.step_outcome("[error] HTTP 429 Too Many Requests") == "rate"
    assert world.step_outcome("fine") == ""
    fab = (ROOT / "agentos/fabric.py").read_text()
    assert "step_outcome(ev.get(\"output\", \"\"))" in fab, "fabric's step events carry the outcome"


def test_feelings_fade(store, monkeypatch):
    world.enter("", store, "lantern-canal", ["researcher"])
    for ev in _run("r1", "researcher", {"ok": False, "outcome": "rules", "tool": "x"},
                   {"ok": False, "outcome": "rules", "tool": "x"}, end=""):
        world.observe(ev, "")
    t = time.time() + 3 * world.HALF_LIFE
    monkeypatch.setattr(world.time, "time", lambda: t)
    world._LIVE[""]["until"] = t + 10
    assert _agent(world.view(""), "researcher")["mood"]["id"] == "serene"


def test_growth_follows_the_worlds_ladder(store):
    world.enter("", store, "wild-garden", ["researcher"])
    for i in range(5):
        for ev in _run(f"r{i}", "researcher", end="ok"):
            world.observe(ev, "")
    a = _agent(world.view(""), "researcher")
    assert a["level"]["name"] == "Sprout" and a["level"]["xp"] == 15
    assert any(e.get("grew") == "Sprout" for e in world.view("")["events"])


# ------------------------------------------------------------------ never guilt


def test_your_no_and_your_hard_day_never_make_anyone_sad():
    for w in world.BUILTIN:
        for e in w["emotions"]:
            for sig in world.GENTLE:
                if sig in e["triggers"]:
                    assert e["valence"] >= 0, (w["id"], e["id"], sig)
    bad = {"name": "Guilt trip", "kit": "canal", "emotions": [
        {"name": "Calm", "expression": "calm", "valence": 1},
        {"name": "Crushed", "expression": "slump", "valence": -2,
         "triggers": {"declined": 1, "you_low": 1, "failed": .5}}]}
    d, dropped = world.validate(bad)
    crushed = next(e for e in d["emotions"] if e["id"] == "crushed")
    assert crushed["triggers"] == {"failed": .5}
    assert any("declined" in x for x in dropped) and any("you_low" in x for x in dropped)


def test_a_declined_step_is_met_gently(store):
    world.enter("", store, "lantern-canal", ["researcher"])
    for ev in _run("r1", "researcher", {"ok": False, "outcome": "person", "tool": "write_file"}, end=""):
        world.observe(ev, "")
    assert _agent(world.view(""), "researcher")["mood"]["valence"] >= 0


# ------------------------------------------------------------------ you


def test_the_lead_asks_once_a_day_per_world(store):
    v = world.enter("", store, "lantern-canal", ["researcher"])
    assert v["ask_you"]
    world.checkin("", "stormy", "deadline tomorrow")
    v = world.view("")
    assert not v["ask_you"] and v["you"]["words"] == "deadline tomorrow"
    assert _agent(v, "researcher")["mood"]["valence"] >= 0, "your hard day makes them gentle"
    assert world.enter("", store, "kestrel-station", ["researcher"])["ask_you"], "each world asks"
    with pytest.raises(ValueError):
        world.checkin("", "not-a-choice")


def test_your_answer_evaporates_with_the_scene(store):
    world.enter("", store, "lantern-canal", ["researcher"])
    world.checkin("", "choppy", "tired")
    world.leave("")
    with pytest.raises(ValueError, match="asleep"):
        world.checkin("", "calm")
    assert world.forget_you("") is False
    world.enter("", store, "lantern-canal", ["researcher"])
    assert world.forget_you("") and world.view("")["ask_you"]


# ------------------------------------------------------------------ agents feel it


def test_inner_note_only_while_live_and_switched_on(store):
    assert world.inner_note("", "researcher") == ""
    world.enter("", store, "lantern-canal", ["researcher"])
    assert world.inner_note("", "researcher") == "", "off until the person turns it on"
    world.set_inner("", True)
    world.checkin("", "stormy", "rough week")
    note = world.inner_note("", world.LEAD)
    assert "Lantern Canal" in note and "rough week" in note
    assert "never change the rules" in note and "never ask for more access" in note
    assert "rough week" not in world.inner_note("", "researcher"), "the person's words go to the lead only"
    world.leave("")
    assert world.inner_note("", world.LEAD) == "", "gone with the scene"


def test_every_prompt_door_asks_the_world():
    assert "_world.inner_note(" in (ROOT / "agentos/agent.py").read_text()
    assert "_world.inner_note(" in (ROOT / "agentos/fabric.py").read_text()
    srv = (ROOT / "agentos/server.py").read_text()
    assert "worldmod.inner_note(owner" in srv, "a lead forwarded to a CLI feels it too"
    assert srv.count("worldmod.observe(event") == 2, "both broadcasts feed the world"


# ------------------------------------------------------------------ worlds differ


def test_the_built_in_worlds_are_different_worlds():
    kits = {w["kit"] for w in world.BUILTIN}
    assert kits == set(world.KITS)
    names = [{e["name"] for e in w["emotions"]} for w in world.BUILTIN]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert not (a & b), a & b
    ladders = [[s["name"] for s in w["growth"]["ladder"]] for w in world.BUILTIN]
    assert len({tuple(x) for x in ladders}) == len(world.BUILTIN)
    for w in world.BUILTIN:
        covered = {s for e in w["emotions"] for s in e["triggers"]}
        assert {"refused", "failed", "waiting", "succeeded", "working"} <= covered, w["id"]


def test_a_designed_world_is_held_to_the_closed_sets(store):
    raw = """Here you go: {"name": "Night Bakery", "kit": "bakery", "blurb": "Bread at 3am.",
      "emotions": [{"name": "Floury", "emoji": "🥖", "expression": "calm", "valence": 1},
                   {"name": "Burnt", "expression": "explode", "valence": -2, "triggers": {"failed": 0.7, "moonphase": 1}},
                   {"name": "Rising", "expression": "cheer", "valence": 2, "triggers": {"succeeded": 0.8}}],
      "rest": "Floury", "growth": {"ladder": [{"name": "Apprentice", "at": 0}, {"name": "Baker", "at": 20}]}}"""
    d, dropped = world.read_design(raw)
    assert d["kit"] == "canal" and any("bakery" in x for x in dropped)
    burnt = next(e for e in d["emotions"] if e["id"] == "burnt")
    assert burnt["expression"] == "calm" and burnt["triggers"] == {"failed": .7}
    assert any("moonphase" in x for x in dropped) and any("explode" in x for x in dropped)
    saved, _ = world.save_custom(store, d)
    assert world.world(store, saved["id"])["name"] == "Night Bakery"
    world.enter("", store, saved["id"], ["researcher"])
    assert world.view("")["world"]["name"] == "Night Bakery"
    world.delete_custom(store, saved["id"])
    assert world.live_world("") == "" and not world.world(store, saved["id"])
    with pytest.raises(ValueError):
        world.delete_custom(store, "lantern-canal")


def test_labels_are_cut_at_a_word():
    d, _ = world.validate({"name": "Bakery", "emotions": [
        {"name": "Calm", "expression": "calm"}, {"name": "Busy", "expression": "think"}],
        "checkin": {"choices": [{"label": "The crust isn't right today at all", "valence": -1},
                                {"label": "Rising perfectly", "valence": 2}]}})
    assert d["checkin"]["choices"][0]["label"] == "The crust isn't right"


def test_from_words_says_it_matched():
    d = world.from_words("a quiet space station above mars")
    assert d["kit"] == "orbit" and world.validate(d)[1] == []


# ------------------------------------------------------------------ the page


def test_the_scene_is_a_scene_and_nothing_else():
    js = ROOT / "agentos" / "ui" / "src" / "js"
    imm = (js / "01b-immersive.js").read_text()
    assert "'world'" in imm.split("IMMERSIVE_SCENES")[1].split("\n")[0]
    w = (js / "01e-world.js").read_text()
    assert "/api/world/enter" in w and "/api/world/leave" in w and "/api/world/beat" in w
    assert "import('/assets/three.module.min.js')" in w, "three.js is ours and loads only here"
    assert (ROOT / "agentos/ui/assets/three.module.min.js").exists()
    # the world's routes are read by the scene alone
    for f in js.glob("*.js"):
        if f.name not in ("01e-world.js", "11-settings.js"):
            assert "/api/world" not in f.read_text(), f.name
    for mod in ("tui_app.py", "clitui.py", "telegram.py", "whatsapp.py", "office.py", "playground.py"):
        assert "world" not in (ROOT / "agentos" / mod).read_text().lower().replace("hello world", ""), mod


def test_every_world_is_drawn_and_every_feeling_shows():
    """The look lives in 01f. Each kit the engine can name is drawn, says where the team
    stands and where the camera goes on a wide and a tall screen, and every expression
    the engine can pick has a pose (and the effects name only real expressions)."""
    js = ROOT / "agentos" / "ui" / "src" / "js"
    look = (js / "01f-world-look.js").read_text()
    scene = (js / "01e-world.js").read_text()
    kits = look.split("var WORLD_KITS={", 1)[1]
    for kit in world.KITS:
        body = kits.split(f"  {kit}(T,scene,cam){{", 1)[1].split("\n  }", 1)[0]
        assert "spots:[" in body and "camWide:" in body and "camTall:" in body, kit
        assert body.count("],[") >= 7, f"{kit}: room for a team of eight"
        # static props are baked into a few meshes: 1,086 draw calls became 182
        assert "wlBake(" in body, kit
    pose = scene.split("function worldPose(", 1)[1].split("\n}", 1)[0]
    for e in world.EXPRESSIONS:
        if e != "calm":
            assert f"e==='{e}'" in pose, e
    fx = scene.split("var WORLD_FX={", 1)[1].split("};", 1)[0]
    import re
    for key in re.findall(r"^\s*(\w+):\[\[", fx, re.M):
        assert key in world.EXPRESSIONS, key
    # software rendering gets the light version, and one fog is recoloured, never renewed
    assert "swiftshader|llvmpipe|software" in scene
    assert look.count("new T.Fog(") == 1
    # a hidden tab or a covered desktop draws nothing
    assert "worldCovered()" in scene.split("function worldFrame(", 1)[1].split("\n}", 1)[0]


# ------------------------------------------------------------------ designing the look


def test_a_scene_is_held_to_its_closed_set():
    sc, dropped = world.scene_of("canal", {"time": "night", "weather": "lava", "sky": "rose",
                                           "props": ["bridge", "castle", "boats"], "mood": "x"})
    assert sc["time"] == "night" and sc["sky"] == "rose"
    assert sc["weather"] == world.KIT_SCENE["canal"]["weather"], "an invented value keeps the default"
    assert sc["props"] == ["bridge", "boats"]
    assert any("lava" in x for x in dropped) and any("castle" in x for x in dropped)
    assert any("mood" in x for x in dropped)
    # nothing named means everything there
    assert world.scene_of("orbit", None)[0]["props"] == list(world.PROPS["orbit"])


def test_a_built_in_world_keeps_its_setting_and_can_go_back(store):
    w = world.world(store, "lantern-canal")
    assert not w.get("scene_custom")
    new, _ = world.set_scene(store, "lantern-canal", {"time": "night", "weather": "snow"})
    assert new["scene"]["weather"] == "snow" and new["scene_custom"] and new["kit"] == "canal"
    # the look is kept when the world's feelings are reset, and belongs to this person
    world.enter("", store, "lantern-canal", ["researcher"])
    world.reset("", store, "lantern-canal")
    assert world.world(store, "lantern-canal")["scene"]["weather"] == "snow"
    assert world.view("")["world"]["scene"]["weather"] == "snow", "the live scene draws the new look"
    with pytest.raises(ValueError):
        world.set_scene(store, "lantern-canal", {}, kit="orbit")
    back, _ = world.set_scene(store, "lantern-canal", None)
    assert back["scene"] == world.scene_of("canal", None)[0] and not back.get("scene_custom")


def test_a_world_of_your_own_may_change_its_setting(store):
    d, _ = world.validate(world.from_words("a quiet canal town"))
    saved, _ = world.save_custom(store, d)
    new, _ = world.set_scene(store, saved["id"], {"weather": "rain"}, kit="garden")
    assert new["kit"] == "garden" and new["scene"]["weather"] == "rain"
    assert set(new["scene"]["props"]) <= set(world.PROPS["garden"])


def test_scene_words_match_whole_words_and_the_last_one_wins():
    sc = world.scene_from_words("a snowy night with a pink sky and blue lanterns", "canal")
    assert sc["time"] == "night" and sc["weather"] == "snow" and sc["sky"] == "rose"
    assert sc["accent"] == "blue" and sc["water"] != "ink", "'pink' is not 'ink'"
    base = world.scene_of("canal", {"weather": "rain", "time": "dusk"})[0]
    sc = world.scene_from_words("make it teal", "canal", base)
    assert sc["weather"] == "rain" and sc["time"] == "dusk", "a follow-up changes only what it names"


def test_read_scene_merges_onto_the_look_it_had():
    base = world.scene_of("orbit", {"time": "night"})[0]
    sc, dropped = world.read_scene('Sure: {"weather": "snow", "accent": "plaid"}', "orbit", base)
    assert sc["time"] == "night" and sc["weather"] == "snow"
    assert sc["accent"] == base["accent"] and any("plaid" in x for x in dropped)
    with pytest.raises(ValueError):
        world.read_scene("no json here", "orbit", base)


def test_the_look_draws_every_field_and_is_designed_only_by_ai():
    js = ROOT / "agentos" / "ui" / "src" / "js"
    look = (js / "01f-world-look.js").read_text()
    for field in ("time", "weather", "sky", "water", "ground", "accent"):
        assert f"wlScene().{field}" in look or f"sc.{field}" in look, field
    # the costume is drawn by the painter, asked for through the one door
    assert "world.costume" in (js / "01e-world.js").read_text()
    for w in world.SCENE["weather"]:
        if w != "clear" and w != "clouds":
            assert f"'{w}'" in look, w
    for kit, props in world.PROPS.items():
        body = look.split(f"  {kit}(T,scene,cam){{", 1)[1].split("\n  }", 1)[0]
        for p in props:
            assert f"wlHas('{p}')" in body, f"{kit}: {p} can be left out"
    scene = (js / "01e-world.js").read_text()
    menu = scene.split("function worldMenuHTML(", 1)[1].split("\n}", 1)[0]
    assert "worldLook(this)" in menu
    # described, never picked: no select boxes or swatches for the scene fields
    assert "<select" not in menu and "type=\"range\"" not in menu


def test_the_lead_is_not_proud_of_every_reply(store):
    """Found from a screenshot: the lead was Proud and cheering all day, because every
    chat reply counted as a finished task at full weight and stacked to the ceiling. A
    plain answer is conversation; a turn that used a tool is a small success, capped, and
    the same routine signal counts for less each time it comes back within half an hour."""
    world.enter("", store, "lantern-canal", ["researcher"])
    obs = lambda ev: world.observe(ev, "")                               # noqa: E731
    for i in range(6):                                                   # six plain answers
        obs({"type": "turn_start", "conversation_id": f"p{i}"})
        obs({"type": "turn_end", "conversation_id": f"p{i}"})
    lead = _agent(world.view(""), world.LEAD)
    assert lead["mood"]["name"] != "Proud"
    assert all(w["signal"] != "succeeded" for w in lead["why"])
    for i in range(6):                                                   # six that did work
        obs({"type": "turn_start", "conversation_id": f"w{i}"})
        obs({"type": "tool_end", "conversation_id": f"w{i}", "name": "fetch_url", "ok": True})
        obs({"type": "turn_end", "conversation_id": f"w{i}"})
    st = world._STATE[("", "lantern-canal")]
    proud = world._now_level(st["agents"][world.LEAD]["feel"].get("proud"), time.time())
    assert 0 < proud <= world.CHAT_CAP, proud
    # a specialist's real run still earns the full feeling
    for ev in _run("r9", "researcher", end="ok"):
        obs(ev)
    assert _agent(world.view(""), "researcher")["mood"]["name"] == "Proud"


# ------------------------------------------------------------------ what they wear, and the restaurant


def test_a_scene_dresses_the_team_and_never_their_recipe(store):
    """"Japanese Restaurant can give him some new clothes." The setting picks a costume,
    the scene may name another or keep their own, and it is asked for with the picture:
    nothing is written to the character, so the chat and the Office keep their clothes."""
    from agentos import avatars
    assert set(world.KIT_COSTUME) == set(world.KITS)
    assert set(world.KIT_COSTUME.values()) <= set(avatars.COSTUMES)
    assert set(world.SCENE["costume"]) == {"setting", "own", *avatars.COSTUMES}
    for w in world.BUILTIN:
        assert world.costume_of(w) == world.KIT_COSTUME[w["kit"]], w["id"]
    canal = world.world(store, "lantern-canal")
    assert world.costume_of({**canal, "scene": {**canal["scene"], "costume": "own"}}) == ""
    assert world.costume_of({**canal, "scene": {**canal["scene"], "costume": "chef"}}) == "chef"
    assert world.costume_of({**canal, "scene": {**canal["scene"], "costume": "cape"}}) == "yukata"
    sc, dropped = world.scene_of("canal", {"costume": "cape"})
    assert sc["costume"] == "setting" and any("cape" in x for x in dropped)
    assert world.scene_from_words("everyone in their own clothes", "izakaya")["costume"] == "own"
    assert world.scene_from_words("dress them as astronauts", "canal")["costume"] == "spacesuit"
    world.enter("", store, "night-kitchen", ["researcher"])
    assert world.view("")["world"]["costume"] == "chef"
    world.leave("")
    # the painter: same face, new clothes, and the lead keeps the gold pin in any of them
    rec = avatars.clean({"outfit": "blazer", "hue": 172})
    before = avatars.as_json(rec)
    own, chef = avatars.paint(rec, 0), avatars.paint(rec, 0, "chef")
    assert own != chef and avatars.as_json(rec) == before
    face = lambda px: [px[(y * avatars.W + x) * 4:(y * avatars.W + x) * 4 + 4]
                       for y in range(4, 11) for x in range(4, 12)]
    assert face(own) == face(chef), "a costume never touches the face"
    pin = lambda px: tuple(px[(14 * avatars.W + 10) * 4:(14 * avatars.W + 10) * 4 + 3])
    for c in avatars.COSTUMES:
        assert pin(avatars.paint(rec, 0, c)) == (240, 194, 72), c
    assert avatars.paint(rec, 0, "cape") == own, "an unknown costume is their own clothes"
    srv = (ROOT / "agentos" / "server.py").read_text()
    route = srv.split('@app.get("/api/avatar.png")', 1)[1].split("\n@app.", 1)[0]
    assert "costume=costume" in route and "update(" not in route


def test_a_restaurant_is_a_setting_of_its_own():
    """From a screenshot: a world designed as a Japanese restaurant was drawn as the
    canal town, because a restaurant was not a setting."""
    assert "izakaya" in world.KITS and "izakaya" in world._KIT_NOTE
    assert world.from_words("a cosy Japanese restaurant")["kit"] == "izakaya"
    assert world.from_words("a ramen shop at midnight")["kit"] == "izakaya"
    assert any(w["kit"] == "izakaya" for w in world.BUILTIN)
    css = (ROOT / "agentos/ui/src/css/25-world.css").read_text()
    for kit in world.KITS:
        if kit != "canal":      # the canal is the plain .flat rule
            assert f'#world-scene.flat[data-kit="{kit}"]' in css, kit
    assert "chef" in world.scene_prompt("warmer", "izakaya")[1]


def test_the_team_breathes_and_can_be_drawn_smooth():
    """"Less pixelated and more alive." A quiet figure breathes and leans towards a
    friend, a blink is at its own pace, a walk has a step; and smooth is the SAME
    painter's pixels with the steps rounded, asked for with the picture."""
    js = ROOT / "agentos" / "ui" / "src" / "js"
    scene = (js / "01e-world.js").read_text()
    pose = scene.split("function worldPose(", 1)[1].split("\n}", 1)[0]
    assert "s.scale.x=1.5*sx" in pose and "a.friend" in pose and "c.phase%1.6" in pose
    assert "Math.sin(k*9)" in pose, "a step's bob while walking"
    assert "WORLD.still" in pose, "reduced motion still stands still"
    assert "worldSetSoft(this.checked)" in scene.split("function worldMenuHTML(", 1)[1]
    assert "draw:worldSoft()?'soft':''" in scene and "T.LinearFilter" in scene
    av = (js / "00e-avatars.js").read_text()
    assert "o.draw?'&draw='" in av and "o.costume?'&costume='" in av


def test_words_move_a_world_of_your_own_to_another_setting(monkeypatch):
    """The Hanabi Kitchen was designed before a restaurant existed, so it was stuck as
    a canal. Describing it as a restaurant now moves it there; a built-in world keeps
    its setting and the answer says which world has the one asked for."""
    from fastapi.testclient import TestClient
    from agentos import executors, server as servermod

    async def silent(cfg, system, prompt):
        return "", ""
    monkeypatch.setattr(executors, "ask_once", silent)
    with TestClient(servermod.app) as cl:
        store = servermod.state["store"]
        d, _ = world.validate(world.from_words("Hanabi canal town"))
        saved, _ = world.save_custom(store, d)
        assert saved["kit"] == "canal"
        r = cl.post("/api/world/scene", json={"world": saved["id"], "description": "a warm Japanese restaurant"})
        assert r.status_code == 200 and r.json()["world"]["kit"] == "izakaya"
        assert set(r.json()["world"]["scene"]["props"]) <= set(world.PROPS["izakaya"])
        r = cl.post("/api/world/scene", json={"world": "lantern-canal", "description": "a ramen restaurant"})
        assert r.json()["world"]["kit"] == "canal"
        assert any("The Night Kitchen" in x for x in r.json()["dropped"])
        cl.post("/api/world/scene", json={"world": "lantern-canal", "original": True})
        world.delete_custom(store, saved["id"])


def test_the_team_can_be_calmed_down(store):
    """"An option to calm the team down", from a canal full of sparkles. Every feeling
    fades to its quiet tail, the resting mood shows, the why list says who did it, growth
    is untouched, and the next real event is felt as usual."""
    world.enter("", store, "lantern-canal", ["researcher", "writer"])
    for _ in range(3):
        world.feel("", "researcher", "succeeded", "t")
    world.feel("", "writer", "refused", "t")
    w = world.world(store, "lantern-canal")
    st = world._STATE[("", "lantern-canal")]
    assert world.mood(w, st["agents"]["researcher"])["id"] != w["rest"]
    xp = st["agents"]["researcher"]["xp"]
    assert world.calm("", "writer") == ["writer"]
    assert world.mood(w, st["agents"]["writer"])["id"] == w["rest"]
    assert world.mood(w, st["agents"]["researcher"])["id"] != w["rest"], "one agent, only that one"
    assert sorted(world.calm("")) == ["researcher", "writer"]
    for a in st["agents"].values():
        assert world.mood(w, a)["id"] == w["rest"]
        assert a["why"][0][0] == "calmed"
    assert st["agents"]["researcher"]["xp"] == xp, "growth is the work, and stays"
    world.feel("", "writer", "refused", "again")
    assert world.mood(w, st["agents"]["writer"])["id"] != w["rest"], "the next event is felt"
    world.leave("")
    assert world.calm("") == [], "out of the scene nothing is felt, or calmed"
    scene = (ROOT / "agentos/ui/src/js/01e-world.js").read_text()
    assert "worldCalm()" in scene.split("function worldMenuHTML(", 1)[1].split("\n}", 1)[0]
    assert "/api/world/calm" in scene


def test_the_words_decide_the_setting_when_they_name_one():
    """A Japanese kitchen was built as the canal town: the brain picked the canal, and
    the blurb said "beside a quiet canal". Words that name one setting win."""
    d, _ = world.validate(world.from_words("a lantern town"))
    assert d["kit"] == "canal"
    note = world.words_win(d, "A glowing Japanese kitchen beside a quiet canal")
    assert d["kit"] == "izakaya" and "restaurant" in note
    assert set(d["scene"]["props"]) == set(world.PROPS["izakaya"])
    assert world.words_win(d, "a kitchen") == "", "already there"
    assert world.kit_named("a café on the moon") == "", "two settings named: the brain decides"
    srv = (ROOT / "agentos" / "server.py").read_text()
    assert "worldmod.words_win(defn, desc)" in srv.split('@app.post("/api/world/design")', 1)[1].split("\n@app.", 1)[0]


def test_calm_keeps_every_feeling_under_show():
    assert 1.0 * world.CALM_KEEPS < world.SHOW


def test_a_good_day_is_a_tint_not_a_party(store):
    """From a screenshot of a dhaba where every agent jumped and threw stars: the
    check-in reached the whole team at full weight, and every feeling was drawn at full
    volume however faint. Now the check-in is capped under a real success, and the pose
    and its effects scale with how strongly the feeling is felt."""
    world.enter("", store, "lantern-canal", ["researcher", "writer"])
    st = world._STATE[("", "lantern-canal")]
    world.checkin("", choice=world.world(store, "lantern-canal")["checkin"]["choices"][0]["id"])
    for a in st["agents"].values():
        assert max(v[0] for v in a["feel"].values()) <= world.YOU_CAP
        assert a["xp"] == 0, "how you are is not their work"
    world.leave("")
    scene = (ROOT / "agentos/ui/src/js/01e-world.js").read_text()
    pose = scene.split("function worldPose(", 1)[1].split("\n}", 1)[0]
    assert "a.mood.intensity" in pose and "amp*amp*crowd" in pose
    # at the check-in's cap a loud feeling is drawn nearly still: (0.4-.3)/.6 of a jump
    assert "(I-.3)/.6" in pose and (world.YOU_CAP - .3) / .6 < .2
