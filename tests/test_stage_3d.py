"""Charts and maps built in 3D, the lit look a drawing comes to life in, and the clip a phone gets.

Asked for as "the 3D it builds should not be short of the 3D we see today", "in case of Telegram it
should not just send a diagram … a working feed with audio", and "also update the skills for this".
The page turns a chart's own numbers and a map's own places into solids (24x-model.js), so they are
inked, raised, lit and toured like any model; a phone gets the build as a video with sound
(stageclip.py); a page made by a skill carries three.js and builds live.
"""
import asyncio
import json
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from agentos import skillpack, stage, stageclip

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "agentos/ui/src/js/24x-model.js").read_text()
STAGE_JS = (ROOT / "agentos/ui/src/js/24l-stage.js").read_text()
CSS = (ROOT / "agentos/ui/src/css/42-model.css").read_text()

BARS = {"kind": "chart", "chart_type": "bar", "title": "Power by source", "unit": "TWh", "source": "Ember",
        "series": [{"name": "", "points": [["Coal", 10600], ["Gas", 6700], ["Solar", 2100]]}]}
MAP = {"kind": "map", "title": "Hot places", "unit": "°C", "source": "WMO", "route": True,
       "points": [{"label": "Furnace Creek, USA", "lat": 36.4, "lon": -116.8, "value": 56.7, "note": "The record, 1913."},
                  {"label": "Kebili", "lat": 33.7, "lon": 8.9, "value": 55}]}
KYOTO = {"kind": "model", "title": "Kyoto", "caption": "A garden in spring.",
         "solids": [{"shape": "pagoda", "at": [0, 0, 0], "size": [6, 20, 6], "label": "Pagoda", "note": "Five storeys."},
                    {"shape": "blossom", "at": [0, 0, 4], "size": [5, 6, 5], "count": 8, "spread": [30, 20]}]}

# the helpers the builders borrow from 24l-stage.js, as that file has them
PRE = """
function stageTicks(lo,hi,n){if(lo===hi){lo-=1;hi+=1}const span=hi-lo,raw=span/Math.max(1,n),mag=Math.pow(10,Math.floor(Math.log10(raw)));
  const step=[1,2,2.5,5,10].map(f=>f*mag).find(s=>s>=raw)||raw;const t0=Math.floor(lo/step)*step,out=[];for(let t=t0;t<=hi+step*0.001;t+=step)out.push(+t.toFixed(10));return out}
function stageFmt(n,u){return String(n)+(u?' '+u:'')}
function stageSigned(v){return v.some(x=>x>0)&&v.some(x=>x<0)}
function stageFmtS(n,u,s){return (s&&n>0?'+':'')+stageFmt(n,u)}
function stageDate(){return null}function stageDateLabel(x){return String(x)}
function bpFmt(n){return String(n)}
var STAGE_VIEW={world:[-180,-58,180,84]};
"""


def _node(body: str) -> dict:
    out = subprocess.run(["node", "-e", PRE + JS + "\n;" + body], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the painter's builders")
def test_a_chart_becomes_bars_that_carry_their_values():
    got = _node("""
const m=mdlOfChart(%s),bars=m.solids.filter(s=>s.note);
const moves=mdlOfChart({chart_type:'bar',unit:'%%',series:[{points:[['A',2],['B',-3]]}]}).solids.filter(s=>s.note);
const line=mdlOfChart({chart_type:'line',series:[{name:'Solar',points:[['2020',1],['2021',3],['2022',9]]}]});
console.log(JSON.stringify({labels:bars.map(s=>s.label),cols:bars.map(s=>s.color),h:bars.map(s=>s.size[1]),notes:bars.map(s=>s.note),
  ticks:m.solids.filter(s=>s._quiet).map(s=>s.label),grid:m.lines.length,
  pie:mdlOfChart({chart_type:'pie',series:[{points:[['a',1],['b',2]]}]}),
  moves:moves.map(s=>[s.label,s.color,s.size[1]>0]),
  line:[line.lines.filter(l=>l.late).length,line.solids.filter(s=>s.label&&!s._quiet).map(s=>s.label),line.solids.filter(s=>s.note).map(s=>s.note)],
  built:mdlBuild(m).solids.length}));""" % json.dumps(stage.clean(BARS)[0]))
    assert got["labels"] == ["Coal 10600 TWh", "Gas 6700 TWh", "Solar 2100 TWh"]      # a turned bar is read from its name
    assert got["cols"] == ["gold", "blue", "blue"] and got["h"][0] > got["h"][1] > got["h"][2] > 0
    assert got["notes"][0] == "The highest of 3." and got["notes"][1].startswith("2nd of 3, 37% below Coal")
    assert got["ticks"][0] == "0 TWh" and len(got["ticks"]) >= 3 and got["grid"] >= 3   # the rule beside it is labelled
    assert got["pie"] is None                                                           # what 3D would distort stays flat
    # a rise and a fall are both bars that stand up: the sign is a word, a mark and a colour
    assert got["moves"] == [["A ▲ +2 %", "green", True], ["B ▼ -3 %", "red", True]]
    assert got["line"][0] == 1 and "Solar 9" in got["line"][1] and "From 1 to 9: up 800%." in got["line"][2]
    assert got["built"] == len(stage.clean(BARS)[0]["series"][0]["points"]) + 1 + len(got["ticks"])


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the painter's builders")
def test_a_map_becomes_land_pins_and_arcs_and_an_outline_is_cut_into_a_closed_plate():
    world = {"countries": [{"n": "Squareland", "a3": "SQL", "r": [[-1200, 300, -1000, 300, -1000, 450, -1100, 380, -1200, 450]]}]}
    got = _node("""
const world=%s;world.idx={squareland:world.countries[0]};
const m=mdlOfMap(%s,world),land=m.solids.find(s=>s.shape==='_land'),pins=m.solids.filter(s=>s.shape==='sphere');
const up=mdlOfMap({regions:[{country:'Squareland',value:4}],points:[]},world).solids.filter(s=>s.shape==='_poly');
const L=[[0,0],[4,0],[4,1],[1,1],[1,3],[0,3]],tri=mdlEar(L);
let area=0;tri.forEach(t=>{const a=L[t[0]],b=L[t[1]],c=L[t[2]];area+=Math.abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2});
const me=mdlMesh({k:'poly',ring:L,h:1,w:1,d:1}),dir={},key=p=>p.join(',');
me.f.forEach(fc=>{for(let a=0;a<fc.i.length;a++){const k=key(me.v[fc.i[a]])+'>'+key(me.v[fc.i[(a+1)%%fc.i.length]]);dir[k]=(dir[k]||0)+1}});
const open=Object.keys(dir).filter(k=>{const [p,q]=k.split('>');return dir[k]!==1||dir[q+'>'+p]!==1}).length;
const B=mdlBuild(m);
console.log(JSON.stringify({land:land&&land._rings.length,pins:pins.map(s=>[s.label,s.note]),tall:pins.map(s=>s.at[1]),
  arcs:m.lines.filter(l=>l.late).length,ground:m.ground,up:up.map(s=>[s.label,s.size[1]>0]),tri:tri.length,area,open,
  lines:B.lines.length,fits:Math.abs(Math.max(B.W,B.D)-20)<.01}));""" % (json.dumps(world), json.dumps(stage.clean(MAP)[0])))
    assert got["land"] == 1 and got["ground"] == "water"
    assert got["pins"] == [["1 · Furnace Creek 56.7 °C", "The record, 1913."], ["Kebili 55 °C", ""]]   # the tour reads the note
    assert got["tall"][0] > got["tall"][1]                    # a pin is as tall as its value
    assert got["arcs"] == 1                                   # a journey is an arc in the air
    assert got["up"] == [["Squareland 4", True]]              # a country with a value stands up out of the land
    assert got["tri"] == 4 and abs(got["area"] - 6) < 1e-9 and got["open"] == 0
    assert got["lines"] > 3 and got["fits"]


def test_the_page_builds_them_only_where_it_can_and_keeps_the_flat_one_a_tap_away():
    for needle in ("function stageD3ok(){return !(window.STAGE_REPORT&&!window.MDL_THREE)&&!window.STAGE_STILL&&!stageReduced()&&!mdlLite()&&mdlGLok()}",
                   "localStorage.getItem('stage.flat')", "'▤ Flat'", "'◈ 3D'", "maxTags:24,stack:true"):
        assert needle in JS, needle
    assert "art.clientWidth<520" in JS            # a phone's width keeps a chart flat until 3D is asked for
    assert "if(stageD3(art,sc,mdlOfChart(sc),stageChart))return;" in STAGE_JS
    assert "stageD3(art,sc,mdlOfMap(sc,world),stageMap,ol)" in STAGE_JS
    # a scene built in 3D is the whole theater, and what lies over it lets the pointer through
    assert ".stg-scene.k-3d>.stg-art{grid-row:1/-1" in CSS and "pointer-events:none" in CSS
    assert "stageWide(art,true)" in JS and "!window.STAGE_REPORT&&art.closest" in JS


def test_a_drawing_comes_to_life_and_real_is_the_look_nobody_chose():
    assert stage.MODEL_STYLES[0] == "real"
    sc, _ = stage.clean(dict(KYOTO))
    assert sc["style"] == "real"
    assert "real (inked and raised on paper, then it comes to life" in stage.MODEL_LINE
    for needle in ("real:{name:'Real'", "PCFSoftShadowMap", "castShadow", "receiveShadow", "ACESFilmicToneMapping",
                   "customDepthMaterial", "function mdlLive(", "T.Fog(", "(MDL_LOOK[model.style]?model.style:'real')"):
        assert needle in JS, needle
    # the lit surfaces still sway and walk, by the drawing's own movement put into the standard shader
    assert "sh.vertexShader.replace('#include <begin_vertex>'" in JS and "+MDL_SWAY+'\\n'+" in JS


def test_what_builds_in_3d_is_one_rule_and_the_clip_says_only_the_scenes_own_words():
    yes = [stage.clean(BARS)[0], stage.clean(MAP)[0], stage.clean(KYOTO)[0]]
    pie = stage.clean({**BARS, "chart_type": "pie"})[0]
    nums = stage.clean({"kind": "numbers", "title": "n", "source": "s", "items": [{"label": "a", "value": 1}]})[0]
    assert all(stage.builds_3d(s) for s in yes) and not stage.builds_3d(pie) and not stage.builds_3d(nums)
    assert stage.clip_words(yes[2]) == "A garden in spring. Pagoda. Five storeys."
    assert stage.clip_words(yes[1]).endswith("Furnace Creek. The record, 1913.")


def test_the_clip_page_carries_the_painter_and_three_and_a_story_page_only_when_given_it():
    sc = stage.clean(KYOTO)[0]
    page = stage.clip_html(sc, three="/*three*/export const X=1;")
    assert "window.STAGE_CLIP=true" in page and "window.MDL_THREE=URL.createObjectURL" in page
    assert "function mdlClip(" in page and "stageClip(" in page and "/*three*/" in page
    assert "STAGE_REPORT=true" not in page                      # it draws live, never the still
    for needle in ("MediaRecorder", "captureStream(30)", "createMediaStreamDestination", "video/mp4;codecs=avc1",
                   "window.MDL_ONFRAME", "window.STAGE_CLIP_DONE"):
        assert needle in JS, needle
    live = stage.page_html([sc], "q", three="/*three*/")
    assert "window.MDL_THREE=" in live and "/*three*/" in live
    assert "window.MDL_THREE=" not in stage.page_html([sc], "q")                              # Bento's own report: stills
    assert "window.MDL_THREE=" not in stage.page_html([sc], "q", still=True, three="/*three*/")   # a phone's picture
    nums = stage.clean({"kind": "numbers", "title": "n", "source": "s", "items": [{"label": "a", "value": 1}]})[0]
    assert "/*three*/" not in stage.page_html([nums], "q", three="/*three*/")                 # nothing to build: not carried


def test_the_skills_carry_three_and_say_what_the_page_does():
    files = skillpack.files()
    for name in ("bento-stage", "bento-blueprint"):
        assert len(files[f"skills/{name}/assets/three.module.min.js"]) > 300_000
    assert "skills/bento-brief/assets/three.module.min.js" not in files
    md = files["skills/bento-stage/SKILL.md"].decode()
    assert "What the page does in 3D" in md and "**model**" in md and "pagoda" in md and "real, paper, blueprint, hologram" in md.replace("`", "")
    assert 'three=_read("three.module.min.js")' in files["skills/bento-stage/scripts/render.py"].decode()


def _bridge(clips=True, engine="browser"):
    sent, acts = [], []
    me = types.SimpleNamespace(cfg={"speech": {"engine": engine}, "agent_name": "Aria"},
                               store=types.SimpleNamespace(log=lambda *a, **k: acts.append(("log", a))))
    me._t = lambda: {"clips": clips}

    async def _api(method, **kw):
        acts.append((method, kw))
    me._api = _api

    async def send_video(data, mime, caption="", chat_id=None, seconds=0):
        sent.append((len(data), mime, caption, chat_id))
        return "sent"
    me.send_video = send_video
    return me, sent, acts


def test_a_phone_gets_a_video_of_what_is_built_and_at_most_two(monkeypatch):
    from agentos.telegram import TelegramBridge
    made = []

    async def render(sc, cfg=None, narration=None):
        made.append((sc["kind"], narration))
        await asyncio.sleep(0.01)
        return b"x" * 5000, "video/mp4", 21.0
    monkeypatch.setattr(stageclip, "render", render)
    monkeypatch.setattr(stageclip, "available", lambda cfg=None: True)
    nums = stage.clean({"kind": "numbers", "title": "n", "source": "s", "items": [{"label": "a", "value": 1}]})[0]
    scenes = [nums, stage.clean(BARS)[0], stage.clean(MAP)[0], stage.clean(KYOTO)[0]]
    me, sent, acts = _bridge()
    assert asyncio.run(TelegramBridge.send_clips(me, scenes, 7)) == 2
    assert [m[0] for m in made] == ["chart", "map"] and all(m[1] is None for m in made)   # no server voice: its own sound only
    assert sent == [(5000, "video/mp4", "▶ Power by source", 7), (5000, "video/mp4", "▶ Hot places", 7)]
    assert ("sendChatAction", {"chat_id": 7, "action": "upload_video"}) in acts            # the chat says a video is coming
    # the owner's switch, and a machine that cannot record: pictures only, said in the diary, never an error
    me, sent, _ = _bridge(clips=False)
    assert asyncio.run(TelegramBridge.send_clips(me, scenes, 7)) == 0 and sent == []

    async def none(sc, cfg=None, narration=None):
        return None
    monkeypatch.setattr(stageclip, "render", none)
    me, sent, acts = _bridge()
    assert asyncio.run(TelegramBridge.send_clips(me, scenes, 7)) == 0 and sent == []
    assert any(a[0] == "log" and "no video" in a[1][1] for a in acts)


def test_the_clips_switch_is_a_command_and_the_recorder_refuses_what_is_flat():
    from agentos import telegram_admin
    assert any(c[0] == "/clips" for c in telegram_admin.COMMANDS) if hasattr(telegram_admin, "COMMANDS") else True
    assert "_cmd_clips" in (ROOT / "agentos/telegram_admin.py").read_text()
    nums = stage.clean({"kind": "numbers", "title": "n", "source": "s", "items": [{"label": "a", "value": 1}]})[0]
    assert asyncio.run(stageclip.render(nums, {})) is None
    src = (ROOT / "agentos/stageclip.py").read_text()
    assert "--mute-audio" not in src and "--remote-debugging-pipe" in src and "--remote-debugging-port" not in src


@pytest.mark.skipif(not shutil.which("google-chrome") and not shutil.which("chromium")
                    and not shutil.which("chromium-browser"), reason="no Chromium here")
def test_a_real_browser_records_the_build_with_its_sound():
    sc = stage.clean({"kind": "model", "title": "A house", "solids": [{"shape": "house", "at": [0, 0, 0], "size": [8, 6, 6]}]})[0]
    got = asyncio.run(stageclip.render(sc, {}))
    assert got, "no clip came back"
    data, mime, secs = got
    assert mime in ("video/mp4", "video/webm") and len(data) > 100_000 and 10 < secs < 40
    assert data[4:8] == b"ftyp" if mime == "video/mp4" else data[:4] == b"\x1a\x45\xdf\xa3"


def test_a_viewer_in_india_sees_indias_own_boundary_and_no_land_is_lost_or_doubled():
    """Asked for as "India map has to be proper as I am from India". The base map (Natural Earth)
    stops India at the lines of control; the file carries India's boundary as India draws it, and
    the page uses it for a viewer in India."""
    d = json.loads((ROOT / "agentos/ui/assets/world-110m.json").read_text())
    by = {c["a3"]: c for c in d["countries"] if c.get("a3")}
    pov = d["pov"]["IN"]
    pts = lambda r: [(r[i] / 10, r[i + 1] / 10) for i in range(0, len(r), 2)]
    area = lambda ps: abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ps, ps[1:] + ps[:1]))) / 2
    ind = pts(pov["IND"][0])
    assert max(p[1] for p in ind) >= 37.0                          # to the Karakoram, north of Gilgit
    assert min(p[0] for p in ind if p[1] > 35) <= 72.7             # Gilgit-Baltistan's west
    assert max(p[0] for p in ind if 34 < p[1] < 36.5) >= 80.3      # round Aksai Chin
    before = sum(area(pts(by[a]["r"][i])) for a, i in (("IND", 0), ("PAK", 0), ("CHN", 1)))
    after = sum(area(pts(pov[a][i])) for a, i in (("IND", 0), ("PAK", 0), ("CHN", 1)))
    assert abs(before - after) < 0.2 and area(ind) > area(pts(by["IND"]["r"][0])) + 10   # moved, not lost or doubled
    assert pov["CHN"][0] == by["CHN"]["r"][0]                      # nothing else is touched
    for needle in ("d.pov&&d.pov[stagePov()]", "tz==='Asia/Kolkata'||tz==='Asia/Calcutta'", "localStorage.getItem('stage.borders')"):
        assert needle in STAGE_JS, needle
    assert '"pov"' in stage.painter()[2]                           # the phone's picture and the skills get it too


def test_among_the_stars_the_middle_shines_and_the_rest_go_round_it():
    assert "space" in stage.MODEL_GROUND and "solar system" in stage.MODEL_LINE
    sc, dropped = stage.clean({"kind": "model", "title": "Sun and Earth", "ground": "space", "solids": [
        {"shape": "sphere", "at": [0, 0, 0], "size": [4, 4, 4], "color": "gold", "label": "Sun"},
        {"shape": "sphere", "at": [9, 0, 0], "size": [1, 1, 1], "color": "blue", "label": "Earth", "move": "orbit"}]})
    assert dropped == [] and sc["ground"] == "space"
    for needle in ("const space=model.ground==='space'", "new T.PointLight(", "Math.pow(near/rr,1.5)",
                   "if(space){let cx=0,cz=0,n=0;", "space:'#1b2540'"):
        assert needle in JS, needle


def test_things_that_go_round_keep_their_own_distance_and_every_name_is_shown():
    """Reported with a blueprint of the solar system: the agent sent eight planets and the drawing
    named three. A floor meant for circling birds (30% of the scene) had put Mercury, Venus, Earth
    and Mars on one path at one place, and a name that overlapped another was dropped."""
    assert "rr=Math.max(o.r,B.R*.3)" not in JS                       # no floor under a planet's distance
    for needle in ("const kepler=space||radii.length>=3", "Math.pow(near/rr,1.5)",       # the nearer, the faster
                   "radii.indexOf(o.r.toFixed(2))*2.399",                                # told in a row, spread round
                   "if(on)for(let n=0;n<6&&hit&&y>40;n++){y-=21;lead+=21;hit=clash()}",  # a name steps up, in every model
                   "tg.el.classList.toggle('tiny',small)"):
        assert needle in JS, needle
    assert "opts.stack&&on" not in JS
    assert ".mdl-tag.tiny::before" in CSS
