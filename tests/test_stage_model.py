"""The Stage's model: a thing or a place built in 3D from solids, and a blueprint drawn in 3D.

Asked for as "paper style detailed blueprint with brown paper and black lines, a bit animated …
projected in the air … if I have to build Kyoto with pink leaves and trees I should be able to
see them coming to life". Pinned here:

- a model is a closed set read field by field: shapes, colours, moves, looks, weather and ground
  from the lists, what is dropped is named, copies are capped, and nothing the agent wrote runs;
- a blueprint may carry the same solids, each naming a part that exists;
- the page can draw every shape, colour and look the server lets through, and the tool says them;
- every piece the painter makes is a closed solid wound outward (run in Node), because the ink
  drawing decides what is in front from each face's direction;
- a phone gets it as the first picture of a blueprint's album, and the words say what stands in it;
- the painter rests: no frame while hidden or off the page, a still drawing on a small screen.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import stage, tools  # noqa: E402

ROOT = Path(__file__).parent.parent
JS = (ROOT / "agentos/ui/src/js/24x-model.js").read_text()

KYOTO = {"kind": "model", "title": "Kyoto in spring", "style": "paper", "weather": "petals", "ground": "grass",
         "solids": [
             {"shape": "pagoda", "at": [0, 0, -8], "size": [11, 34, 11], "tiers": 5, "label": "Yasaka Pagoda",
              "note": "The landmark of the old town."},
             {"shape": "blossom", "at": [0, 0, 0], "count": 34, "spread": [100, 60], "color": "pink"},
             {"shape": "water", "at": [0, 26], "size": [120, 0.1, 10]},
             {"shape": "cloud", "at": [-25, 34, -20], "move": "drift"}]}


def test_a_model_is_a_closed_set_read_field_by_field():
    sc, dropped = stage.clean(KYOTO)
    assert not dropped and sc["style"] == "paper" and sc["weather"] == "petals" and sc["ground"] == "grass"
    pagoda, grove, water, cloud = sc["solids"]
    assert pagoda == {"shape": "pagoda", "at": [0.0, 0.0, -8.0], "size": [11.0, 34.0, 11.0], "tiers": 5,
                      "label": "Yasaka Pagoda", "note": "The landmark of the old town."}
    # a note is what the tour says at a named thing: one with no label has no stop to say it at
    assert "note" not in stage.clean({"kind": "model", "title": "t", "solids": [{"shape": "box", "note": "x"}]})[0]["solids"][0]
    assert grove["count"] == 34 and grove["spread"] == [100.0, 60.0] and grove["size"] == [5.0, 5.5, 5.0]
    assert water["at"] == [0.0, 0.0, 26.0]                       # [x, z] stands on the ground
    assert cloud["move"] == "drift"
    sc, dropped = stage.clean({"kind": "model", "title": "t", "style": "neon", "weather": "frogs", "solids": [
        {"shape": "dragon"}, {"shape": "box", "color": "#GGGGGG", "move": "teleport", "script": "alert(1)",
                              "count": 9999, "tilt": 450, "label": "x" * 99}]})
    assert dropped == ["solids[0].shape 'dragon'", "solids[1].script", "solids[1].color '#gggggg'",
                       "solids[1].move 'teleport'", "style 'neon'", "weather 'frogs'"]
    box = sc["solids"][0]
    assert box["count"] == stage.MODEL_COPIES and box["tilt"] == 90.0 and len(box["label"]) <= 40
    assert sc["style"] == "paper" and sc["weather"] == "none" and "color" not in box
    with pytest.raises(ValueError, match="needs solids"):
        stage.clean({"kind": "model", "title": "nothing", "solids": [{"shape": "dragon"}]})
    many, dropped = stage.clean({"kind": "model", "title": "t", "solids": [
        {"shape": "tree", "count": 60, "spread": [9, 9]} for _ in range(stage.MODEL_SOLIDS + 5)]})
    assert len(many["solids"]) == stage.MODEL_SOLIDS and any("past" in d for d in dropped)
    assert sum(s.get("count", 1) for s in many["solids"]) <= stage.MODEL_PIECES + stage.MODEL_SOLIDS


def test_a_blueprint_carries_its_own_model_and_a_tower_is_stacked():
    bp, dropped = stage.clean({"kind": "blueprint", "title": "Jet", "style": "hologram",
                               "parts": [{"name": "Fan"}, {"name": "Core"}],
                               "model": [{"shape": "cylinder", "part": "Fan", "tilt": 90},
                                         {"shape": "cone", "part": "Afterburner"}]})
    assert dropped == ["model[1].part (names a part that is not there)"]
    assert bp["model"][0]["part"] == "fan" and "part" not in bp["model"][1] and bp["style"] == "hologram"
    assert stage.has_model(bp) and stage.still_views(bp)[0] == {"mode": "model", "path": []}
    assert "built in 3D" in stage.still_caption_for(bp, {"mode": "model", "path": []}, 0, 3)
    tower, _ = stage.clean({"kind": "blueprint", "title": "T", "form": "tower", "illustrative": True, "parts": [
        {"name": "Base", "from": 0, "to": 10}, {"name": "Top", "from": 10, "to": 40}]})
    assert stage.has_model(tower) and "model" not in tower            # the page stacks it (bpModelOf)
    flat, _ = stage.clean({"kind": "blueprint", "title": "F", "parts": [{"name": "A"}, {"name": "B"}]})
    assert not stage.has_model(flat) and stage.still_views(flat)[0]["mode"] == "parts"
    assert "function bpModelOf(" in JS and "bpModelView(st)" in (ROOT / "agentos/ui/src/js/24v-blueprint.js").read_text()


def test_the_words_say_what_stands_in_it():
    sc, _ = stage.clean(KYOTO)
    assert "Built in 3D: Yasaka Pagoda (pagoda), 34 × blossom" in stage.text(sc)
    assert "Built in 3D" in stage.still_caption(sc, 0, 1)
    assert stage.STILL_KIND["model"] == "3D model" and stage.has_model(sc)


def test_the_page_draws_everything_the_server_lets_through():
    for shape in stage.MODEL_SHAPES:
        assert f"case '{shape}':" in JS, shape
    for table, names in (("MDL_COL", stage.MODEL_COLORS), ("MDL_LOOK", stage.MODEL_STYLES),
                         ("MDL_WEATHER", stage.MODEL_WEATHER[1:]), ("MDL_GROUND", stage.MODEL_GROUND[1:])):
        body = JS[JS.index(f"var {table}="):]
        body = body[:body.index("};")]
        for n in names:
            assert f"{n}:" in body, (table, n)
    for move in stage.MODEL_MOVES:
        assert f"'{move}'" in JS or f"{move}:" in JS, move
    assert set(stage.MODEL_SIZE) == set(stage.MODEL_PROPS)
    schema = next(s for s in tools.STAGE_TOOL_SCHEMAS if s["name"] == "show_scene")
    props = schema["parameters"]["properties"]
    assert "model" in props["kind"]["enum"]
    for shape in stage.MODEL_SHAPES:
        assert shape in props["solids"]["description"], shape
    for c in stage.MODEL_COLORS:
        assert c in props["solids"]["description"], c
    assert props["style"]["enum"] == list(stage.MODEL_STYLES)
    assert props["weather"]["enum"] == list(stage.MODEL_WEATHER) and props["ground"]["enum"] == list(stage.MODEL_GROUND)
    stg = (ROOT / "agentos/ui/src/js/24l-stage.js").read_text()
    assert "model:stageModel" in stg and "model:'3D model'" in stg
    assert "24x-model.js" in stage.PAINTER_JS and "42-model.css" in stage.PAINTER_CSS
    assert "function mdlMount(" in (ROOT / "agentos/ui/index.html").read_text()


def test_the_agent_is_told_how_to_build_one():
    for cfg in ({"stage": {"big": True}}, {"stage": {"big": False}}):
        note = stage.note(cfg)
        assert "show ONE model scene" in note and "blossom" in note and "tilt" in note
        assert "Give model too" in note                                  # a blueprint's own 3D
    assert "model (a place or a thing built in 3D" in next(
        s for s in tools.STAGE_TOOL_SCHEMAS if s["name"] == "show_scene")["description"]


def test_the_painter_rests_and_never_runs_what_it_was_given():
    assert "innerHTML" not in JS and "eval(" not in JS and "new Function" not in JS
    for needle in ("host.isConnected", "document.hidden", "MDL_LIFE_S", "forceContextLoss", "mdlLite()",
                   "stageReduced()", "window.STAGE_REPORT", "mdlStill(host,model", "host.clientWidth",
                   # shade is cast once per pixel, a tour ends at a touch, and a name is a stop on it
                   "stencilWrite:true", "T.NotEqualStencilFunc", "cv0(host,stop)", "'mdl-cap'", "mdlDimension("):
        assert needle in JS, needle
    css = (ROOT / "agentos/ui/src/css/42-model.css").read_text()
    assert "infinite" not in css and "body.still .stg-model" in css


def test_a_phone_page_carries_the_ink_drawing():
    sc, _ = stage.clean(KYOTO)
    page = stage.page_html([sc], "Build me Kyoto", still=True)
    assert "function mdlStill(" in page and '"kind": "model"' in page and "STAGE_STILL=true" in page


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the painter's geometry")
def test_every_piece_is_a_closed_solid_and_a_model_fits_the_sheet():
    script = JS + """
;const shapes=%s;let bad=[];
for(const sh of shapes){for(const pc of mdlPieces({shape:sh,size:[4,6,3],at:[0,0,0],tiers:3})){
  const me=mdlMesh(pc),dir={},key=p=>p.map(x=>Math.round(x*500)).join(',');
  me.f.forEach(fc=>{for(let a=0;a<fc.i.length;a++){const p=key(me.v[fc.i[a]]),q=key(me.v[fc.i[(a+1)%%fc.i.length]]);if(p!==q)dir[p+'>'+q]=(dir[p+'>'+q]||0)+1}});
  for(const k of Object.keys(dir)){const [p,q]=k.split('>');if(dir[k]!==1||dir[q+'>'+p]!==1){bad.push(sh+'/'+pc.k);break}}
  let vol=0;me.f.forEach(fc=>{const a=me.v[fc.i[0]];for(let t=1;t<fc.i.length-1;t++){const b=me.v[fc.i[t]],c=me.v[fc.i[t+1]];
    vol+=a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])}});
  if(!(vol>0))bad.push(sh+'/'+pc.k+' inside out')}}
const B=mdlBuild({solids:%s});
const grove=B.solids[1],pag=B.solids[0];
const inPagoda=grove.meshes.some(m=>m.leaf&&m.v.every(p=>p[0]>pag.lo[0]&&p[0]<pag.hi[0]&&p[2]>pag.lo[2]&&p[2]<pag.hi[2]));
const ruled=sh=>mdlBuild({solids:[{shape:sh,at:[0,0,0],size:[8,6,6]}]}).solids[0].meshes.reduce((t,x)=>t+x.f.reduce((u,f)=>u+(f.lines||[]).length,0),0);
const walkers=mdlBuild({solids:[{shape:'person',at:[0,0,0],size:[.6,1.8,.4],count:3,spread:[9,9]}]}).solids[0];
const dim=mdlDimension(%s,'m');
const lying=mdlBuild({solids:[{shape:'cylinder',at:[0,1,0],size:[2,6,2],tilt:90}]}).solids[0];
const twr=bpModelOf({form:'tower',unit:'m',parts:[{id:'a',from:-50,to:0,width:110},{id:'b',from:0,to:400,width:60},{id:'c',from:400,to:828,width:8}]});
console.log(JSON.stringify({bad,longest:Math.max(B.W,B.D),low:Math.min(...B.solids.map(s=>s.lo[1])),copies:grove.meshes.length,
  inPagoda,lyingLong:(lying.hi[0]-lying.lo[0])/(lying.hi[1]-lying.lo[1]),tower:twr.solids.filter(s=>s.part).map(s=>[s.part,s.at[1],s.size[1]]),
  rule:twr.solids.filter(s=>s.label).map(s=>s.label),ruled:['house','roof','wall','bridge','pagoda'].map(ruled),
  walk:[walkers.move,walkers.meshes[0].go.length,Math.hypot(walkers.meshes[0].go[0],walkers.meshes[0].go[1])],
  dim:[dim.length,dim[0].label,dim[0].size[1]]}));
""" % (json.dumps(list(stage.MODEL_SHAPES)), json.dumps(stage.clean(KYOTO)[0]["solids"]),
       json.dumps(stage.clean(KYOTO)[0]["solids"]))
    # the helpers the painter borrows from the Stage's other files
    pre = "function stageTicks(lo,hi,n){const o=[];for(let t=0;t<=hi;t+=200)o.push(t);return o}function bpFmt(n){return String(n)}\n"
    out = subprocess.run(["node", "-e", pre + script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-800:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["bad"] == []
    assert abs(got["longest"] - 20) < 0.01 and abs(got["low"]) < 1e-6      # fitted to the sheet, standing on it
    assert got["copies"] == 34 * 4 and not got["inPagoda"]                 # a grove grows round the temple
    assert got["lyingLong"] > 2.5                                          # tilt 90 lays it on its side
    assert got["tower"] == [["a", 0, 50], ["b", 50, 400], ["c", 450, 428]]
    assert "Ground" in got["rule"] and "828 m" in got["rule"]
    assert all(n > 0 for n in got["ruled"])                                # tiles, courses, planks are drawn
    assert got["walk"][0] == "walk" and got["walk"][1] == 3 and abs(got["walk"][2] - 1) < 1e-6
    assert got["dim"] == [3, "34 m", 34]                                   # the tallest named thing is measured
