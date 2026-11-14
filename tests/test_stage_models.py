"""A real model for a thing in a scene: looked up by words, kept with its credit, never by address.

Asked for with three.js's example of an artist's model ("this is so so amazing … we have the
potential"), and then "bundled free kit, free online libraries, generate with a 3D service" as the
sources allowed. This is the first of them: a free library (Poly Haven, CC0) searched by the
agent's words. stagemodels.py is driven here by a stand-in for the network.
"""
import asyncio
import json
from pathlib import Path

from agentos import stage, stagemodels as sm

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "agentos/ui/src/js/24x-model.js").read_text()

INDEX = {"ArmChair_01": {"name": "Arm Chair 01", "tags": ["chair", "furniture", "wood"], "categories": ["furniture", "seating"],
                         "polycount": 5626, "authors": {"Ada Maker": "All"}},
         "potted_plant_04": {"name": "Potted Plant 04", "tags": ["plant", "pot"], "categories": ["plants"], "polycount": 9000,
                             "authors": {"Bo": "All"}},
         "covered_car": {"name": "Covered Car", "tags": ["car", "vehicle"], "categories": ["vehicles"], "polycount": 30000},
         "../evil": {"name": "Arm Chair", "tags": ["chair"]}}
FILES = {"gltf": {"1k": {"gltf": {"url": "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/ArmChair_01/ArmChair_01_1k.gltf",
                                    "include": {"ArmChair_01.bin": {"url": "https://dl.polyhaven.org/f/ArmChair_01.bin"},
                                                "textures/a_diff_1k.jpg": {"url": "https://dl.polyhaven.org/f/a_diff_1k.jpg"}}}}}}


def _net(files=FILES, log=None):
    async def get(url, cap):
        if log is not None:
            log.append(url)
        if url.endswith("/assets?t=models"):
            return json.dumps(INDEX).encode()
        if "/files/" in url:
            return json.dumps(files).encode()
        return b"x" * 3000
    return get


def test_words_pick_the_thing_or_nothing():
    assert sm.pick(INDEX, "a wooden armchair") is None             # "armchair" is no word of this list: nothing, not a guess
    assert sm.pick(INDEX, "wooden arm chair") == "ArmChair_01"
    assert sm.pick(INDEX, "potted plants") == "potted_plant_04"    # a plural is the same thing
    assert sm.pick(INDEX, "pagoda") is None and sm.pick(INDEX, "the of") is None
    assert sm.pick(INDEX, "furniture") is None                     # a category alone names no thing
    assert sm.pick({"../evil": INDEX["../evil"]}, "chair") is None  # a name that is no plain name is never a model


def test_a_model_is_fetched_once_with_its_credit_from_the_librarys_own_hosts(tmp_path):
    log = []
    meta = asyncio.run(sm.find(tmp_path, "arm chair", _net(log=log)))
    assert meta["id"] == "ArmChair_01" and meta["file"] == "ArmChair_01_1k.gltf"
    assert meta["credit"] == "Ada Maker" and meta["licence"] == "CC0" and meta["source"] == "https://polyhaven.com/a/ArmChair_01"
    assert (tmp_path / "ArmChair_01/textures/a_diff_1k.jpg").exists() and (tmp_path / "ArmChair_01/ArmChair_01.bin").exists()
    assert all(u.startswith(("https://api.polyhaven.com/", "https://dl.polyhaven.org/")) for u in log)
    n = len(log)
    again = asyncio.run(sm.find(tmp_path, "arm chair", _net(log=log)))
    assert again["id"] == "ArmChair_01" and len(log) == n            # kept: the list for a day, the files for good


def test_what_the_library_says_is_read_strictly(tmp_path):
    for bad in ({"../up.bin": {"url": "https://dl.polyhaven.org/f/x.bin"}},               # out of its folder
                {"a/b/c.bin": {"url": "https://dl.polyhaven.org/f/x.bin"}},               # too deep
                {"run.sh": {"url": "https://dl.polyhaven.org/f/run.sh"}},                 # no kind the page reads
                {"ok.bin": {"url": "https://elsewhere.example/x.bin"}},                   # another host
                {"ok.bin": {"url": "http://dl.polyhaven.org/f/x.bin"}}):                  # not https
        files = json.loads(json.dumps(FILES))
        files["gltf"]["1k"]["gltf"]["include"] = bad
        assert asyncio.run(sm.find(tmp_path / "x", "arm chair", _net(files))) is None, bad
    assert not (tmp_path / "x" / "ArmChair_01").exists()               # nothing half-written
    assert not sm._ok_url("https://api.polyhaven.com.evil.example/x") and sm._ok_url("https://api.polyhaven.com/assets")


def test_a_scene_asks_in_words_and_only_the_server_sets_the_model(tmp_path):
    from agentos.memory import Store
    spec = {"kind": "model", "title": "A corner", "solids": [
        {"shape": "box", "at": [0, 0, 0], "size": [1, 1, 1], "label": "Chair", "look_for": "arm chair",
         "mesh": {"id": "../../etc", "file": "passwd"}},
        {"shape": "box", "at": [2, 0, 0], "size": [1, 1, 1], "look_for": "pagoda"},
        {"shape": "box", "at": [4, 0, 0], "size": [1, 1, 1]}]}
    sc, dropped = stage.clean(spec)
    assert sc["solids"][0]["look_for"] == "arm chair" and "mesh" not in sc["solids"][0]
    assert any("mesh" in d for d in dropped)                           # the agent's own address for a model is dropped and named
    assert sm.wanted(sc) == [(0, "arm chair"), (1, "pagoda")]
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("c")
    store.add_message(cid, "user", "q")
    row = stage.add(store, cid, sc)
    told = []

    async def tell(ev):
        told.append(ev)
    missing = asyncio.run(sm.fill(store, row, tell, _net()))
    assert missing == ["pagoda"]                                       # said, and that solid stays as it was built
    kept = json.loads(store.db.execute("SELECT scene FROM stage_scenes WHERE id=?", (row["id"],)).fetchone()[0])
    assert kept["solids"][0]["mesh"]["id"] == "ArmChair_01" and "mesh" not in kept["solids"][1]
    assert told and told[0]["type"] == "stage_fill" and told[0]["models"] is True
    # the files are served by a plain name from this person's own folder, and nothing else is
    assert sm.file_of(store, "ArmChair_01", "ArmChair_01_1k.gltf")[1] == "model/gltf+json"
    for aid, rel in (("ArmChair_01", "../meta.json"), ("..", "a.db"), ("ArmChair_01", "meta.json"), ("nope", "x.bin")):
        assert sm.file_of(store, aid, rel) is None


def test_more_than_eight_lookups_are_not_made_and_the_agent_is_told_how():
    sc, _ = stage.clean({"kind": "model", "title": "t", "solids": [
        {"shape": "box", "at": [i, 0, 0], "size": [1, 1, 1], "look_for": "chair"} for i in range(12)]})
    assert len(sm.wanted(sc)) == sm.MAX == 8
    assert "look_for" in stage.MODEL_LINE and "the noun last" in stage.MODEL_LINE


def test_the_page_stands_the_model_where_the_solid_was_and_names_its_maker():
    for needle in ("/assets/three-addons/GLTFLoader.js", "'/api/stage/model/'+encodeURIComponent(mi.id)+'/'+mi.file",
                   "new T.PMREMGenerator(R)", "S.environment=", "new T.AnimationMixer(hold)", "opts.credit(credits)",
                   "o.asset.visible=life>=1", "n.castShadow=true"):
        assert needle in JS, needle
    loader = (ROOT / "agentos/ui/assets/three-addons/GLTFLoader.js").read_text()
    assert "from '../three.module.min.js'" in loader and "from './BufferGeometryUtils.js'" in loader   # one three, never two
    assert "from 'three'" not in loader
    assert "if(ev.models){stagePaintIfOpen();return}" in (ROOT / "agentos/ui/src/js/24l-stage.js").read_text()


def test_a_wall_on_the_eyes_side_steps_out_of_the_way():
    """Found live: the agent built a reading corner with two walls, and the tour's stop at the
    armchair showed the back of a wall."""
    for needle in ("o.wall=[nx,nz,", "if(on)o.hung=on", "o.away=(cam.position.x*wl[0]+cam.position.z*wl[1])>wl[2]"):
        assert needle in JS, needle
