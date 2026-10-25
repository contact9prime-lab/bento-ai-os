"""The town (24t-island.js, office.py look "island"): the Office drawn as a place of the
person's choosing (an island, islands, a canal city, a castle, a forest), each room a building
that opens while it works, a district of houses for each department and a carrier for work.

What this pins:
- the setting is one closed set on every door (office.SETTINGS = the page's ISL_SETS), said
  in words ("build a Venice like city") it is the town look in that setting, and changing it
  keeps the person's houses;
- a room's building opens only because something happens in it (OFFICE.people), and closes
  when it goes quiet: decided from the Office's own state, never a timer;
- the island builder is office.py's closed set on every door: the plan, the agent's
  set_office, `bento office island`, and PUT /api/office (a ledger row like any change);
- the railway never runs across a terrace (found in the first screenshot: the train went
  through the Research room's desks), checked by running the real file in Node;
- the train only moves because work was handed over: its queue is filled from the Office's
  papers (24d decides those) and from nothing else, each paper once;
- the time of day is the person's input, kept per browser, and nothing else reads it;
- the island is a drawing of the 3D office: no painter, no loop of its own, faces from the
  avatar sheet through 24k, and the scene is wired where Office HQ is.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agentos import office

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "agentos" / "ui" / "src" / "js"
ISLAND = (JS / "24t-island.js").read_text()


# ---- the closed set ------------------------------------------------------------------

def test_the_island_is_a_closed_set():
    got, _ = office.clean({"look": "island", "island": {"houses": {"Sales": 40, " Research ": "3"},
                                                        "train": "off", "trees": "lots"}}, None)
    assert got["look"] == "island"
    assert got["island"] == {"houses": {"Sales": office.MAX_HOUSES, "Research": 3}, "train": False, "trees": "lots",
                             "setting": "island"}
    with pytest.raises(ValueError, match="number of trees"):
        office.clean({"island": {"trees": "jungle"}}, None)
    with pytest.raises(ValueError, match="from 0 to 12"):
        office.clean({"island": {"houses": {"Sales": "many"}}}, None)
    with pytest.raises(ValueError, match="setting, houses, train, trees"):
        office.clean({"island": "big"}, None)
    # a stored office with no island draws the default, and it is a copy, never shared
    a, b = office.current({}), office.current({})
    assert a["island"] == {"houses": {}, "train": True, "trees": "some", "setting": "island"}
    a["island"]["houses"]["X"] = 1
    assert b["island"]["houses"] == {} and office.ISLAND_DEFAULT["houses"] == {}


def test_a_district_grows_with_its_team_until_the_person_chooses():
    v = {"office": {"island": {"houses": {"sales": 2}}},
         "rooms": [{"kind": "dept", "name": "Sales", "members": ["a", "b"]},
                   {"kind": "dept", "name": "Research", "members": ["c"]}]}
    assert office.houses_of(v["office"]["island"], "Sales", v) == 2          # chosen, any case
    assert office.houses_of(v["office"]["island"], "Research", v) == 6       # 4 + 2 a person
    # the page counts the same way (officeHouses in 24t-island.js)
    assert "return Math.min(12,4+2*(r.members||[]).length);" in ISLAND


def test_words_and_the_designer_know_the_island():
    assert office.from_words("put my office on a little island")["look"] == "island"
    _, prompt = office.design_prompt("an island", {"agents": [], "office": office.current({})})
    assert '"look": one of 3d, flat, island' in prompt and '"island" (for the island look)' in prompt
    assert '"setting": one of island, islands, canals, castle, forest' in prompt
    # only the fields the model named come back: the person's houses are not reset
    patch, dropped = office.read_design('{"look": "island", "island": {"trees": "few"}}', [])
    assert patch == {"look": "island", "island": {"trees": "few"}} and not dropped
    # the word "world" belongs to the World scene; office.py never names it (test_world)
    assert "world" not in (ROOT / "agentos" / "office.py").read_text().lower()


def test_the_terminal_builds_it(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "office", *a], cwd=ROOT, env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=60)
    cfg = {"office": {"departments": [{"name": "Sales", "color": "sky", "members": []}]}}
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    assert run("look", "island").returncode == 0
    r = run("island", "houses", "sales", "9")
    assert r.returncode == 0 and "houses Sales 9" in r.stdout, r.stderr
    r = run("island", "trees", "lots")
    assert r.returncode == 0 and "trees lots" in r.stdout
    r = run("island", "train", "off")
    assert r.returncode == 0 and "train off" in r.stdout
    saved = json.loads((tmp_path / "config.json").read_text())["office"]
    assert saved["island"] == {"houses": {"Sales": 9}, "train": False, "trees": "lots", "setting": "island"}
    r = run("setting", "venice")
    assert r.returncode == 0 and "island: canals · houses Sales 9" in r.stdout, r.stderr
    saved = json.loads((tmp_path / "config.json").read_text())["office"]
    assert saved["look"] == "island" and saved["island"]["setting"] == "canals" and saved["island"]["houses"] == {"Sales": 9}
    r = run("setting")
    assert r.returncode == 0 and "▸ canals" in r.stdout and "forest" in r.stdout
    r = run("setting", "moon")
    assert r.returncode == 2 and "choose one of: island, islands, canals, castle, forest" in r.stderr
    r = run("island")
    assert r.returncode == 0 and "Sales" in r.stdout and "▮" * 9 in r.stdout
    r = run("island", "houses", "Nope", "3")
    assert r.returncode == 2 and "no department called 'Nope'" in r.stderr
    r = run("island", "trees", "jungle")
    assert r.returncode == 2 and "choose one of: few, some, lots" in r.stderr


def test_the_agent_builds_it_with_set_office():
    from agentos.tools import TOOL_SCHEMAS
    schema = next(s for s in TOOL_SCHEMAS if (s.get("name") or s.get("function", {}).get("name")) == "set_office")
    props = (schema.get("parameters") or schema["function"]["parameters"])["properties"]
    assert props["look"]["enum"] == ["3d", "flat", "island"]
    assert set(props["island"]["properties"]) == {"setting", "houses", "train", "trees"}
    assert props["island"]["properties"]["setting"]["enum"] == list(office.SETTINGS)
    assert props["island"]["properties"]["trees"]["enum"] == list(office.TREES)
    src = (ROOT / "agentos" / "tools.py").read_text()
    assert 'patch["island"] = island' in src


def test_the_route_saves_it_and_writes_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_HOME", str(tmp_path))
    monkeypatch.setenv("AGENTOS_VAULT_KEYRING", "0")
    from fastapi.testclient import TestClient
    import importlib
    import agentos.server as server
    importlib.reload(server)
    with TestClient(server.app) as c:
        r = c.put("/api/office", json={"look": "island", "island": {"houses": {"Sales": 5}, "trees": "few"}})
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["office"]["look"] == "island" and v["office"]["island"]["trees"] == "few"
        assert v["trees"] == ["few", "some", "lots"] and v["max_houses"] == 12
        assert c.put("/api/office", json={"island": {"trees": "jungle"}}).status_code == 400
        rows = server.state["store"].db.execute(
            "SELECT action, rule FROM audit WHERE action='office.write'").fetchall()
    assert rows and rows[-1][1] == "person"


# ---- the page --------------------------------------------------------------------------

def _node(script: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    r = subprocess.run([node, "-e", script, str(JS / "24t-island.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


HARNESS = r"""
const fs=require('fs'),vm=require('vm');
const ctx={Math,JSON,Object,Array,String,Number,isFinite,console,performance:{now:()=>0},
  localStorage:{_:{},getItem(k){return k in this._?this._[k]:null},setItem(k,v){this._[k]=String(v)},removeItem(k){delete this._[k]}},
  document:{}};
vm.createContext(ctx);
vm.runInContext(`var OF3_U=100,OF3_RING=230,OF_WALK_S=3.2,OF3={};function officeKick(){}`,ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+'\n;this.ISL=ISL;',ctx);
// the 3D office's ring, as of3Layout lays it out for a wide window
vm.runInContext(`var L=(function(){const n=8,R=650,rooms=[];
  for(let i=0;i<n;i++){const a=-3*Math.PI/4+i*2*Math.PI/n,u=Math.cos(a+3*Math.PI/4)*1.4,s=Math.sin(a+3*Math.PI/4)*1.6;
    const cx=R*(-u*.7071+s*.7071),cy=R*(-u*.7071-s*.7071),w=i?330:360,h=280;
    rooms.push({kind:i?'dept':'lead',name:'R'+i,x:cx-w/2,y:cy-h/2,w,h,cx,cy,members:[]})}
  return {R,rooms}})();`,ctx);
"""


def test_the_railway_never_crosses_a_terrace():
    out = _node(HARNESS + r"""
vm.runInContext(`var sh=islShapes(L),rail=islRailLine(sh),bad=0;
  rail.forEach(p=>sh.rooms.forEach(q=>{if(Math.abs(p[0]-q.cx)<q.hx+.3&&Math.abs(p[1]-q.cz)<q.hz+.3)bad++}));
  sh.rail=rail;           // as islWorld does: the land follows the line
  this.out={bad,n:rail.length,land:rail.every(p=>islDist(sh,p[0],p[1])<0)};`,ctx);
console.log(JSON.stringify(ctx.out));""")
    assert out["n"] == 72 and out["bad"] == 0
    # and the land runs under it: no stretch of track over the sea
    assert out["land"] is True


def test_the_train_only_runs_on_work_handed_over():
    out = _node(HARNESS + r"""
vm.runInContext(`var OFFICE={L:{rooms:L.rooms},papers:[],people:{}};
  ISL.curve={};ISL.stations={'lead:R0':.1,'dept:R2':.4,'dept:R5':.7};
  const at=r=>({x:r.x+r.w/2,y:r.y+r.h/2});
  OFFICE.papers.push({from:at(L.rooms[0]),to:at(L.rooms[2])});           // lead hands work to R2
  OFFICE.papers.push({from:at(L.rooms[2]),to:at(L.rooms[2])});           // inside one room: no trip
  islPapers();const first=ISL.queue.slice();
  islPapers();const again=ISL.queue.length;                              // each paper once
  OFFICE.papers.push({from:at(L.rooms[5]),to:at(L.rooms[0])});
  islPapers();
  this.out={first,again,after:ISL.queue.slice()};`,ctx);
console.log(JSON.stringify(ctx.out));""")
    assert out["first"] == [0.1, 0.4]
    assert out["again"] == 2
    assert out["after"] == [0.1, 0.4, 0.7, 0.1]
    # nothing else fills the queue: the papers are the only door
    assert ISLAND.count("ISL.queue.push(") == 1
    assert re.search(r"function islPapers\(\)\{[^}]*ISL\.queue\.push\(", ISLAND, re.S)


def test_the_time_of_day_is_the_persons_input():
    out = _node(HARNESS + r"""
vm.runInContext(`const real=islHour();localStorage.setItem('island.hour','21.5');const set=islHour(),on=islHourSet();
  localStorage.setItem('island.hour','');const back=islHourSet();
  this.out={set,on,back,realOk:real>=0&&real<24};`,ctx);
console.log(JSON.stringify(ctx.out));""")
    assert out == {"set": 21.5, "on": True, "back": False, "realOk": True}
    # per browser: nothing outside the island reads or writes it
    for f in JS.iterdir():
        if f.name != "24t-island.js":
            assert "island.hour" not in f.read_text(), f.name


def test_a_drawing_of_the_3d_office_and_nothing_more():
    # no painter, no loop of its own, no top-level let/const (the bundle is one script)
    assert "/api/avatar.png" not in ISLAND and "getImageData" not in ISLAND
    assert "setInterval" not in ISLAND and "requestAnimationFrame" not in ISLAND and "setTimeout" not in ISLAND
    assert not re.search(r"^(let|const) ", ISLAND, re.M)
    k3 = (JS / "24k-office3d.js").read_text()
    # the 3D office hands its scene to the island, and draws rooms as terraces there
    assert "if(island){islWorld(S,still,L,v);" in k3
    assert "if(OF3.island)islTick(now);" in k3
    assert "if(OF3.island)return;              // a terrace has no wall to hold a window" in k3
    assert "(OF3.island&&islMoving())" in k3
    assert "look!=='3d'&&look!=='island'" in k3
    # the scene is wired where Office HQ is, and Settings offers it
    imm = (JS / "01b-immersive.js").read_text()
    assert "'mind','island'];" in imm and "OFFICE_SCENE.island=isl;OFFICE_SCENE.hq=hq;officeSceneStart()" in imm
    assert "['island','Town']" in (JS / "11-settings.js").read_text()
    d = (JS / "24d-office.js").read_text()
    assert "OFFICE_SCENE.island=IMMERSIVE.scene==='island'" in d.splitlines()[-1] or \
        "OFFICE_SCENE.island=IMMERSIVE.scene==='island'" in d.strip().splitlines()[-1]
    assert "islDesignHTML(v)" in d and "islDesignWire(el,v)" in d
    # the controls are tap-sized, like every control on a phone
    css = (ROOT / "agentos" / "ui" / "src" / "css" / "37-island.css").read_text()
    assert "min-height:var(--tap" in css and ".isl-hb{min-width:var(--tap" in css


def test_the_guide_shows_it():
    doc = (ROOT / "docs" / "island.md").read_text()
    for name in ("island-day", "island-night", "island-handover", "island-builder", "island-phone", "island-terminal"):
        assert f"screenshots/{name}.png" in doc
        assert (ROOT / "docs" / "screenshots" / f"{name}.png").stat().st_size > 20_000
    assert "(island.md)" in (ROOT / "docs" / "office.md").read_text()
    assert "(island.md)" in (ROOT / "docs" / "README.md").read_text()


# ---- settings and buildings ------------------------------------------------------------

def test_a_setting_is_one_closed_set_and_words_choose_it(tmp_path):
    # the page draws exactly the settings office.py offers
    page = re.findall(r"^  (\w+):\{label:", ISLAND, re.M)
    assert page == list(office.SETTINGS)
    for words, want in (("build a Venice like city", "canals"), ("make it a castle", "castle"),
                        ("put us in a forest", "forest"), ("greek islands please", "islands"),
                        ("an island in the sea", "island")):
        p = office.from_words(words)
        assert p["look"] == "island" and p["island"]["setting"] == want, words
    assert office.clean({"island": {"setting": "Venice"}}, None)[0]["island"]["setting"] == "canals"
    with pytest.raises(ValueError, match="not a setting"):
        office.clean({"island": {"setting": "moon"}}, None)
    # a new setting keeps the person's houses: a patch to the town merges into it
    cfg = {"office": {"departments": [{"name": "Sales", "color": "sky", "members": []}],
                      "island": {"houses": {"Sales": 9}, "trees": "lots"}}}
    class S:
        def list_subagents(self):
            return []
    o, _ = office.save(cfg, S(), {"look": "island", "island": {"setting": "castle"}})
    assert o["island"] == {"houses": {"Sales": 9}, "train": True, "trees": "lots", "setting": "castle"}


def test_a_building_opens_only_because_something_happens_in_it():
    out = _node(HARNESS + r"""
vm.runInContext(`var OFFICE={L:{rooms:L.rooms},people:{}};OF3.focus=null;OF3.follow='';
  const at=r=>({x:r.x+r.w/2,y:r.y+r.h/2}),R=L.rooms;
  ISL.shells=R.map(r=>({key:r.kind+':'+r.name,name:r.name}));
  const P=(room,o)=>Object.assign({room,mode:'seat',busy:0,...at(room)},o||{});
  const keys=w=>Object.keys(w).sort();
  OFFICE.people={a:P(R[1]),b:P(R[2])};
  const idle=keys(islShellWant());
  OFFICE.people.a.busy=123;                                  // somebody at work in R1
  const busy=keys(islShellWant());
  OFFICE.people.a.busy=0;Object.assign(OFFICE.people.b,at(R[4]));   // R2's person visiting R4
  const visit=keys(islShellWant());
  Object.assign(OFFICE.people.b,at(R[2]),{mode:'walk'});      // walking out of R2
  const walk=keys(islShellWant());
  OFFICE.people.b.mode='seat';OF3.focus='R6';                // the person looks into R6
  const look=keys(islShellWant());
  this.out={idle,busy,visit,walk,look};`,ctx);
console.log(JSON.stringify(ctx.out));""")
    assert out["idle"] == []
    assert out["busy"] == ["dept:R1"]
    assert out["visit"] == ["dept:R4"]
    assert out["walk"] == ["dept:R2"]
    assert out["look"] == ["dept:R6"]
    # opening is drawn from that decision each frame, and a quiet room closes a few seconds later
    assert "const goal=now-s.last<3500?1:0;" in ISLAND
    assert "islShells(now,dt);" in ISLAND and "islShellsMoving()" in ISLAND
