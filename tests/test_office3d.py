"""The 3D office: rooms around the Brain, and a big team that does not clutter it.

Asked for with a screenshot of an isometric agent HQ and one worry: "when I add so many
agents it becomes really cluttered". What these defend:

- the look is office.py's closed set (`look`: 3d or flat), on every door: the editor,
  `bento office look`, the agent's `set_office`, the designer reading words;
- the Brain counts rows (memories, knowledge-graph facts), never a guess;
- a room seats OF3_SEATS people and the rest are on its card; who has a desk follows
  the work, somebody working is never moved out, and seats do not shuffle by themselves
  (run in Node against the real file);
- the drawing is a drawing: the flat office decides every walk and balloon, every face
  is the server's sheet (no second painter), and a screen with no 3D graphics gets the
  flat office and a sentence saying why.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import office                                           # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
SRC = (JS / "24k-office3d.js").read_text()
FLAT = (JS / "24d-office.js").read_text()


# ---- the setting ----

def test_the_look_is_a_closed_set_and_3d_by_default(tmp_path):
    assert office.current({})["look"] == "3d"
    assert office.clean({"look": "flat"}, None)[0] == {"look": "flat"}
    assert office.clean({"look": "3D"}, None)[0] == {"look": "3d"}
    assert office.clean({"look": "comic"}, None)[0] == {"look": "flat"}
    with pytest.raises(ValueError, match="choose one of: 3d, flat"):
        office.clean({"look": "hologram"}, None)
    # a stored bad value draws the default for that field, never an error
    assert office.current({"office": {"look": "hologram"}})["look"] == "3d"


def test_the_designer_and_the_words_know_the_look(tmp_path):
    store = Store(tmp_path / "a.db")
    v = office.view({}, store)
    _, prompt = office.design_prompt("make it 3d", v)
    assert '"look": one of 3d, flat' in prompt
    assert office.from_words("a realistic 3d space station")["look"] == "3d"
    assert office.from_words("just a flat comic")["look"] == "flat"
    patch, dropped = office.read_design('{"look": "flat", "pet": "dog"}', [])
    assert patch == {"look": "flat", "pet": "dog"} and not dropped
    assert "look: 3D rooms around the Brain" in office.text(v)


def test_the_brain_counts_rows(tmp_path):
    store = Store(tmp_path / "a.db")
    assert office.view({}, store)["brain"] == {"memories": 0, "facts": 0}
    for i in range(3):
        store.add_memory(f"the person likes tea, note {i}")
    assert office.view({}, store)["brain"]["memories"] == 3
    assert office.view({}, store)["looks"] == office.LOOKS


def test_the_terminal_and_the_agent_set_it(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "office", *a], cwd=ROOT, env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=60)
    r = run("look", "flat")
    assert r.returncode == 0 and "look: Flat comic plan" in r.stdout, r.stderr
    assert json.loads((tmp_path / "config.json").read_text())["office"]["look"] == "flat"
    r = run("look", "hologram")
    assert r.returncode == 2 and "choose one of: 3d, flat" in r.stderr

    from agentos.tools import TOOL_SCHEMAS, Toolbox
    schema = next(s for s in TOOL_SCHEMAS if (s.get("name") or s.get("function", {}).get("name")) == "set_office")
    props = (schema.get("parameters") or schema["function"]["parameters"])["properties"]
    assert props["look"]["enum"] == ["3d", "flat"]
    store = Store(tmp_path / "t.db")
    cfg = {"workspace": str(tmp_path / "ws")}
    tb = Toolbox(cfg, store)
    out = asyncio.run(tb.set_office(look="flat"))
    assert not out.startswith("[error]") and cfg["office"]["look"] == "flat"
    assert asyncio.run(tb.set_office(look="hologram")).startswith("[error]")


# ---- the drawing ----

def test_the_flat_office_decides_and_the_3d_one_draws():
    # one layout door: the 3D plan is chosen inside officeLayout, before the flat one
    lay = FLAT[FLAT.index("function officeLayout(){"):][:600]
    assert "if(of3Wanted())return of3Layout();" in lay and "of3Off();" in lay
    assert "if(OFFICE.L&&OFFICE.L.radial)return of3Route(p,to);" in FLAT
    assert "if(O.L.radial)return of3Draw();" in FLAT
    assert "if(OFFICE.L&&OFFICE.L.radial)return of3Seat();" in FLAT
    # one rule for the frames, and one door for a tap
    assert "function officeFrameOf(p,seated)" in FLAT and "officeFrameOf(p,seated)" in SRC
    assert "return officeTapPerson(best)" in SRC
    # nothing but the Office's own pulse sends a spark to the Brain
    assert re.findall(r"\bof3Tool\(", FLAT) == ["of3Tool("]
    assert "of3Tool(who,label)" in FLAT


def test_work_finds_a_desk_before_anything_is_shown():
    for fn, needle in (("officeWork", "if(on)of3Need(p)"), ("officeSay", "of3Need(p);"),
                       ("officeBurst", "of3Need(p);"), ("officeHandOver", "of3Need(to);"),
                       ("officeEscalate", "of3Need(p);")):
        body = FLAT[FLAT.index(f"function {fn}("):][:700]
        assert needle in body, fn


def test_there_is_no_second_painter():
    # every face is the server's sheet; the 3D file paints rooms and furniture, nobody
    assert "avatarSrc(p.key,{sheet:1})" in SRC and "avatarRecipeSrc(p.recipe,{sheet:1})" in SRC
    assert "/api/avatar.png" not in SRC
    assert "getImageData" not in SRC and "putImageData" not in SRC


def test_no_3d_graphics_means_the_flat_office_and_a_sentence():
    assert "This screen has no 3D graphics, so the office is drawn flat." in SRC
    assert "This screen could not start 3D graphics, so the office is drawn flat." in SRC
    # and Design says it where the look is chosen
    assert "OF3.why&&(of.look||'3d')==='3d'" in FLAT and "data-look" in FLAT


def test_it_is_cheap_where_it_must_be():
    assert "wlBake(T,still)" in SRC                      # furniture baked into a few draw calls
    assert "worldQuality(OF3.r)" in SRC and "classList.contains('kiosk')" in SRC
    assert "setInterval" not in SRC and "requestAnimationFrame" not in SRC   # the Office's loop draws
    assert "import('/assets/three.module.min.js')" in SRC     # loaded only when this look is on
    # the desktop scene is behind the windows: nothing on it is wired for input
    assert "if(O.w&&O.w.scene)return;" in SRC[SRC.index("function of3Input"):][:200]


def test_the_cards_carry_the_company_numbers():
    co = (JS / "24g-company.js").read_text()
    assert "if(O.L.radial){host.innerHTML='';of3Cards(true);return}" in co
    assert "waiting" in SRC[SRC.index("function of3Cards"):] and "flagged" in SRC[SRC.index("function of3Cards"):]


# ---- seating, run against the real file ----

HARNESS = r"""
const vm=require('vm'),fs=require('fs');
let now=1000;const walks=[];
const ctx={console,Math,JSON,Object,Array,Set,Map,performance:{now:()=>now},
  officeWalk:(p,to,mode)=>{walks.push(p.key);p.mode='walk'},officeKick:()=>{},document:{body:{classList:{contains:()=>false}}}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8')+'\n;this.OF3=OF3;',ctx);
vm.runInContext(`var OFFICE={static:false,people:{},L:{radial:true,rooms:[]}};`,ctx);
const O=ctx.OFFICE;
const ms=['engineer','toolsmith','tester','devops','reviewer','architect','debugger'];
const r={kind:'dept',name:'Engineering',x:0,y:0,w:330,h:280,lead:'engineer',members:ms,inside:{x:150,y:240}};
O.L.rooms=[r];
ms.forEach(m=>O.people[m]={key:m,label:m,room:r,home:{x:0,y:0},x:0,y:0,mode:'seat',busy:0,bench:true,path:[]});
const out={};
ctx.of3Reseat(r,null,true);
out.first=[...r.seats];out.firstWalks=walks.length;
out.bench=ms.filter(m=>O.people[m].bench);
ctx.of3Reseat(r,null,false);out.again=[...r.seats];
// work arrives for somebody on the card: they get a desk, an idle colleague gives one up
now=2000;O.people.reviewer.busy=now;ctx.of3Need(O.people.reviewer);
out.afterReviewer=[...r.seats];out.reviewerWalked=walks.includes('reviewer');
out.reviewerShown=ctx.of3Shown(O.people.reviewer);
// every desk busy: the next one to get work stays on the card, nobody is moved out
now=3000;['tester','devops','toolsmith'].forEach(k=>{O.people[k].busy=now;ctx.of3Need(O.people[k])});
const full=[...r.seats];
now=4000;O.people.architect.busy=now;ctx.of3Need(O.people.architect);
out.full=full;out.afterArchitect=[...r.seats];out.architectBench=O.people.architect.bench;
// a route from the card's door goes out through the door, round the ring
const other={kind:'dept',name:'Writing',x:600,y:0,w:330,h:280,members:[],inside:{x:640,y:120},doorPt:{x:600,y:140},spoke:{x:230,y:0}};
r.doorPt={x:165,y:280};r.spoke={x:0,y:230};O.L.rooms.push(other);
ctx.officeRoomAt=pt=>O.L.rooms.find(q=>pt.x>=q.x-2&&pt.x<=q.x+q.w+2&&pt.y>=q.y&&pt.y<=q.y+q.h+4);
const p=O.people.debugger;p.mode='seat';p.bench=true;p.home=r.inside;
out.route=ctx.of3Route(p,{x:700,y:150}).map(q=>[Math.round(q.x),Math.round(q.y)]);
console.log(JSON.stringify(out));
"""


def test_desks_follow_the_work_and_never_shuffle(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    h = tmp_path / "h.js"
    h.write_text(HARNESS)
    r = subprocess.run([node, str(h), str(JS / "24k-office3d.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # seven people, four desks: the head first, then the department's own order
    assert out["first"] == ["engineer", "toolsmith", "tester", "devops"]
    assert out["bench"] == ["reviewer", "architect", "debugger"] and out["firstWalks"] == 0
    assert out["again"] == out["first"]                       # nothing happened, nothing moved
    # the reviewer got work: an idle desk is theirs, they walk in, the head keeps theirs
    assert "reviewer" in out["afterReviewer"] and "engineer" in out["afterReviewer"]
    assert out["reviewerWalked"] and out["reviewerShown"]
    assert len(out["afterReviewer"]) == 4
    # all four desks working: the architect's work is on the card, nobody is moved out
    assert out["afterArchitect"] == out["full"] and out["architectBench"]
    # out of the door, onto the spoke, round the ring, into the other room
    route = out["route"]
    assert route[0] == [150, 240] and route[1] == [165, 280] and route[2] == [0, 230]
    assert route[-1] == [700, 150] and [600, 140] in route and [640, 120] in route


def test_the_office_doc_shows_it():
    doc = (ROOT / "docs/office.md").read_text()
    assert "screenshots/office-3d.png" in doc and "screenshots/office-3d-room.png" in doc
    assert (ROOT / "docs/screenshots/office-3d.png").exists()
    assert (ROOT / "docs/screenshots/office-3d-room.png").exists()
