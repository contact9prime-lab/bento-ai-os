"""A blueprint fills itself in after its outline is shown (agentos/bpfill.py). Asked for after
the first live blueprints came back thin: "it's not detailed enough … the output isn't good
enough" (40 parts, about one fact each, no "how it works", nothing looked up). Pinned here:

- the outline names which parts are being filled, and each part is asked for on its own;
- an answer is read by the same closed set as the agent's: invented fields dropped, ids unique
  across the whole scene, links only between parts that exist, the node cap shared;
- a part keeps what placed it (id, name, heights, width); a failure leaves it as it was and is
  named; a "filling" mark never outlives its deadline;
- the screens are told as each part lands, and show_scene tells the agent not to show it again;
- the painter draws two levels at once, the flows view, and the fill's state in words.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import bpfill, stage  # noqa: E402
from agentos.memory import Store  # noqa: E402

ROOT = Path(__file__).parent.parent
PAINTER = (ROOT / "agentos/ui/src/js/24v-blueprint.js").read_text()


def _outline():
    sc, _ = stage.clean({"kind": "blueprint", "title": "Jet engine", "form": "exploded",
                         "source": "outline",
                         "facts": [{"label": "thrust", "value": "120", "unit": "kN"}],
                         "parts": [{"name": "Fan", "role": "moves most of the air"},
                                   {"name": "Compressor", "role": "squeezes air"},
                                   {"name": "Turbine", "role": "drives the shafts",
                                    "how": "hot gas spins it", "facts": [{"label": "a", "value": 1},
                                                                         {"label": "b", "value": 2}],
                                    "parts": [{"name": f"stage {i}", "how": "x", "facts": [
                                        {"label": "a", "value": 1}, {"label": "b", "value": 2}]}
                                        for i in range(6)]}],
                         "links": [{"from": "Fan", "to": "Compressor", "verb": "feeds", "kind": "air"}]})
    return sc


def _row(tmp_path):
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "blueprint of a jet engine")
    return store, stage.add(store, cid, _outline())


def _answer(name, n=6, extra=None):
    kids = [{"name": f"{name} part {i}", "role": "does a thing", "how": "like so",
             "made_of": "titanium", "limits": "melts", "colour": "red",
             "facts": [{"label": "size", "value": i + 1, "unit": "cm"}, {"label": "mass", "value": 2, "unit": "kg"}],
             "parts": [{"name": f"{name} bit {i}.{j}"} for j in range(3)]} for i in range(n)]
    out = {"name": "ignored rename", "role": f"the real {name}", "how": f"how {name} works",
           "facts": [{"label": "diameter", "value": "3", "unit": "m"}], "certainty": "estimated",
           "parts": kids,
           "links": [{"from": f"{name} part 0", "to": f"{name} part 1", "verb": "drives", "kind": "power"},
                     {"from": f"{name} part 0", "to": "Fan", "verb": "x"}]}
    out.update(extra or {})
    return out


def test_the_outline_says_what_is_being_filled(tmp_path):
    store, row = _row(tmp_path)
    ids = bpfill.begin(store, row)
    # the turbine is already taken apart; the two thin parts are filled
    assert ids == ["fan", "compressor"]
    assert row["scene"]["filling"]["ids"] == ids and row["scene"]["filling"]["until"] > time.time()
    stored = json.loads(store.db.execute("SELECT scene FROM stage_scenes").fetchone()[0])
    assert stored["filling"]["ids"] == ids
    assert row["scene"]["facts"][0]["value"] == "120"


def test_each_part_is_filled_on_its_own_and_merged_by_the_closed_set(tmp_path):
    store, row = _row(tmp_path)
    bpfill.begin(store, row)
    asked, sent = [], []

    async def asker(cfg, prompt):
        name = "Fan" if "Fill in this part: Fan" in prompt else "Compressor"
        asked.append(name)
        assert "Look the facts up on the web first" in prompt and "kind one of" in prompt
        return "Here you go:\n```json\n" + json.dumps(_answer(name)) + "\n```", "claude-code", 3

    async def send(ev):
        sent.append(ev)
    sc = asyncio.run(bpfill.fill(store, {}, row, send, asker=asker))
    assert sorted(asked) == ["Compressor", "Fan"]
    fan = sc["parts"][0]
    # it keeps what placed it, and takes what it says about itself
    assert fan["id"] == "fan" and fan["name"] == "Fan"
    assert fan["role"] == "the real Fan" and fan["how"] == "how Fan works" and fan["certainty"] == "estimated"
    assert len(fan["parts"]) == 6 and fan["parts"][0]["made_of"] == "titanium"
    assert fan["parts"][0]["parts"][0]["name"] == "Fan bit 0.0"
    assert "colour" not in fan["parts"][0]
    ids = [p["id"] for p, _ in stage.bp_walk(sc["parts"])]
    assert len(ids) == len(set(ids))
    # a link inside the part is kept with its kind; one reaching outside it is not
    assert {"from": "fan-part-0", "to": "fan-part-1", "verb": "drives", "kind": "power"} in sc["links"]
    assert not any(ln["to"] == "fan" and ln["from"].startswith("fan-part") for ln in sc["links"])
    assert "filling" not in sc and sorted(sc["fill"]["done"]) == ["compressor", "fan"]
    assert sc["fill"]["looked_up"] == 6 and sc["fill"]["by"] == "claude-code"
    assert len(sent) == 2 and sent[-1]["type"] == "stage_fill" and sent[-1]["id"] == row["id"]
    assert "filling" not in sent[-1]["scene"]
    # what the page reloads is what was merged
    assert json.loads(store.db.execute("SELECT scene FROM stage_scenes").fetchone()[0]) == sc


def test_a_failure_leaves_the_part_and_says_why(tmp_path):
    store, row = _row(tmp_path)
    bpfill.begin(store, row)

    async def asker(cfg, prompt):
        if "Fill in this part: Fan" in prompt:
            raise RuntimeError("claude-code could not answer: rate limited")
        return "no json here", "claude-code", 0
    sc = asyncio.run(bpfill.fill(store, {}, row, None, asker=asker))
    assert sc["parts"][0]["role"] == "moves most of the air" and sc["parts"][0]["parts"] == []
    why = {f["id"]: f["why"] for f in sc["fill"]["failed"]}
    assert "rate limited" in why["fan"] and "no JSON" in why["compressor"]
    assert "filling" not in sc and sc["fill"]["done"] == []


def test_the_node_cap_is_shared(tmp_path):
    store, row = _row(tmp_path)
    bpfill.begin(store, row)

    async def asker(cfg, prompt):
        name = "Fan" if "Fill in this part: Fan" in prompt else "Compressor"
        return json.dumps(_answer(name, n=12)), "x", 0
    sc = asyncio.run(bpfill.fill(store, {}, row, None, asker=asker))
    assert sum(1 for _ in stage.bp_walk(sc["parts"])) <= stage.BP_NODES


def test_show_scene_starts_it_and_tells_the_agent(tmp_path, monkeypatch):
    from agentos import executors, tools
    store, _ = _row(tmp_path)
    cid = store.list_conversations()[0]["id"]
    started = []
    monkeypatch.setattr(executors, "has_brain", lambda cfg: True)
    monkeypatch.setattr(bpfill, "fill", lambda *a, **k: started.append(a) or asyncio.sleep(0))
    tb = tools.Toolbox({"workspace": str(tmp_path), "providers": {}}, store)
    spec = {"kind": "blueprint", "title": "Jet engine", "parts": [{"name": "Fan"}, {"name": "Core"}]}

    async def go():
        out = await tb.show_scene(_conv=cid, **spec)
        await asyncio.sleep(0)
        return out
    out = asyncio.run(go())
    assert "filling in 2 parts" in out and "do not show it again" in out
    assert started and started[0][2]["scene"]["filling"]["ids"] == ["fan", "core"]


def test_the_agent_is_asked_for_an_outline_and_the_flows():
    note = stage.note({"stage": {"big": False}})
    assert "OUTLINE" in note and "fills in every part on its own" in note
    assert all(k in note for k in stage.BP_FLOWS)
    sc, dropped = stage.clean({"kind": "blueprint", "parts": ["a", "b"],
                               "links": [{"from": "a", "to": "b", "kind": "vibes"}]})
    assert sc["links"][0]["kind"] == "" and "links[0].kind 'vibes'" in dropped
    assert stage.bp_thin({"facts": [{"value": 1}]}) and not stage.bp_thin({"how": "x"})


def test_the_painter_draws_two_levels_and_the_flows():
    for needle in ("function bpFlows(", "function bpFlowEdges(", "function bpRefill(", "bpInside(",
                   "'How it works · '", "filling in…", "function bpFillNote(", "'Made of'", "'Limits'",
                   "class:'bp-lbg'"):
        assert needle in PAINTER, needle
    # every kind of flow has its own line, so none rests on colour
    for k in stage.BP_FLOWS:
        assert f"{k}:[" in PAINTER, k
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'stage_fill'" in ws
    assert "innerHTML" not in PAINTER
