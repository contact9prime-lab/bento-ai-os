"""What a desktop shows, chosen on the desktop: its scene, the App Hub scene, the company it opens,
and which company a machine is for (03-virtual-desktops.js, 01i-apphub.js, devboard.company_map,
/api/devices/company). Asked for as "every desktop I add, I can change the scene: Town, Device, App
Hub (with widgets). That option should be available on the desktop itself. Also a different company
in different desktops … check if the devices are locked to the company or that data can be mapped"."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from agentos import config as cfgmod
from agentos import devboard, users

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
CSS = ROOT / "agentos/ui/src/css"


# ---- a machine is for one company, or for all of them --------------------------------------

def _machines():
    return [{"machine": "This hub", "here": True, "things": []},
            {"machine": "zone-cold", "tkey": "fp:aa", "things": []},
            {"machine": "zone-dock", "tkey": "fp:bb", "things": []},
            {"machine": "Demo floor", "demo": True, "things": []}]


def test_the_mapping_is_read_entry_by_entry_and_a_company_that_is_gone_frees_its_machines():
    cos = {"acme": "Acme", "bore": "Borealis"}
    got = devboard.company_map({"fp:aa": "ACME ", "fp:bb": "gone", "": "acme", "here": "", "x": None}, cos)
    assert got == {"fp:aa": "acme"}
    assert devboard.company_map(["not", "a", "dict"], cos) == {}
    assert [devboard.machine_key(m) for m in _machines()] == ["here", "fp:aa", "fp:bb", "demo:demo floor"]


def test_a_board_for_one_company_leaves_out_the_other_companies_machines_and_what_they_raised():
    cos = {"acme": "Acme", "bore": "Borealis"}
    cmap = {"fp:aa": "acme", "fp:bb": "bore"}
    ms = _machines()
    assert devboard.mark_companies(ms, cmap, cos) == set() and len(ms) == 4, "no company asked: everything"
    assert [m["company_name"] for m in ms] == ["", "Acme", "Borealis", ""]
    ms = _machines()
    hidden = devboard.mark_companies(ms, cmap, cos, only="acme")
    assert hidden == {"zone-dock"}
    assert [m["machine"] for m in ms] == ["This hub", "zone-cold", "Demo floor"], "a machine for no company stays"
    rows = [{"machine": "zone-dock", "id": 1}, {"machine": "Zone-Cold", "id": 2}, {"id": 3}]
    assert [r["id"] for r in devboard.without(rows, hidden)] == [2, 3]
    # a company id that is not theirs filters nothing: a stale choice never empties a board
    ms = _machines()
    assert devboard.mark_companies(ms, cmap, cos, only="nope") == set() and len(ms) == 4


def test_the_terminal_board_names_the_company():
    out = devboard.text({"machines": [{"machine": "zone-cold", "company_name": "Acme", "things": []}], "alarms": []})
    assert "zone-cold  (Acme)" in out


def test_the_mapping_is_the_persons_and_the_route_refuses_what_is_not_theirs():
    assert "device_companies" in users.USER_KEYS and cfgmod.DEFAULTS["device_companies"] == {}
    from fastapi.testclient import TestClient

    from agentos import server
    with TestClient(server.app) as c:
        d = c.get("/api/devices/board").json()
        assert "companies" in d and d["company"] == "" and d["elsewhere"] == 0
        assert c.put("/api/devices/company", json={"machine": "no-such", "company": ""}).status_code == 404
        assert c.get("/api/devices/board?company=not-mine").json()["company"] == ""
    src = (ROOT / "agentos/server.py").read_text()
    route = src.split('@app.put("/api/devices/company")')[1].split("\n@app.")[0]
    assert '"you keep no company by that id"' in route and '_ledger("device.company"' in route
    # a view, never a permission: the route writes no grant
    assert "add_grant" not in route and "sync_grants" not in route


def test_the_terminal_has_the_same_mapping():
    main = (ROOT / "agentos/__main__.py").read_text()
    assert 'if a == "company":' in main and "def _device_company_cli(rest):" in main
    assert '"/api/devices/company", "PUT"' in main


# ---- the page: the menu, the scene, the company ---------------------------------------------

def test_the_scene_is_chosen_on_the_desktop_and_a_new_desktop_asks():
    vd = (JS / "03-virtual-desktops.js").read_text()
    shell = (ROOT / "agentos/ui/src/shell.html").read_text()
    assert 'id="deskbtn"' in shell and 'aria-haspopup="dialog"' in shell
    assert "var DESK_MAIN_SCENES=['island','devices','apps'];" in vd
    add = vd.split("function deskAdd(){")[1].split("\n}")[0]
    assert "switchDesk(DESKS)" in add and "deskMenu()" in add
    assert "localStorage.removeItem('immersive.scene.d'+DESKS)" in add, "a reused number starts clean"
    menu = vd.split("function deskMenu(){")[1].split("\nfunction ")[0] if "\nfunction " in vd.split("function deskMenu(){")[1] else vd.split("function deskMenu(){")[1]
    assert "setImmersiveScene(s)" in menu and "LITE_SCENES[s]" in menu, "a small screen is offered only what it draws"
    assert "innerHTML" not in menu, "a company's name is the person's words: text nodes only"
    assert "DESKCO.list.length>1" in menu, "no company row until there are two to choose between"
    assert "Turn it on" in menu, "with the look off the menu says so, never a dead scene button"
    css = (CSS / "43-desks.css").read_text()
    assert "body.dev-mobile #deskbtn{position:fixed" in css and "height:var(--tap)" in css
    assert "body.dev-touch #deskmenu .dkm-s" in css and "min-height:var(--tap)" in css


def test_the_app_hub_is_a_scene_with_the_widgets_first_and_the_chat_on_the_right():
    imm = (JS / "01b-immersive.js").read_text()
    assert "'apps'" in imm.split("var IMMERSIVE_SCENES=")[1].split("\n")[0]
    # its widgets' cost on a Pi's own screen was never measured, so that screen is not offered it
    assert "apps" not in imm.split("var LITE_SCENES=")[1].split("\n")[0]
    assert "apps:'App Hub'" in imm and "appHubStart()" in imm and "appHubStop()" in imm
    hub = (JS / "01i-apphub.js").read_text()
    paint = hub.split("function appHubPaint(){")[1]
    assert paint.index('class="ah-wid"') < paint.index('class="ah-apps"'), "widgets first"
    assert "deckBoardHTML()" in paint and "deckShown(g)" in paint, "the deck's own groups and widget cards"
    assert "<iframe" not in hub, "it builds no frame of its own: the deck's sandboxed ones only"
    # widgets run only while the desktop is bare, and a rebuild of the deck does not reload them
    assert "if(!appHubBare()){if(APPHUB.live){el.textContent=''" in paint and "sig===APPHUB.sig" in paint
    assert "appHubSync()" in imm and "appHubPaint()" in (JS / "06a-deck.js").read_text()
    assert hub.rstrip().endswith("setTimeout(appHubStart,0);"), "the first paint runs before this file exists"
    # the chat is the Devices scene's panel, with its own remembered choice, open unless folded
    assert "devChatMount()" in hub.split("function appHubStart(){")[1].split("\n}")[0]
    dev = (JS / "01h-devscene.js").read_text()
    assert "(!!DEVSCENE.on||devChatHub())" in dev
    css = (CSS / "39-devscene.css").read_text()
    assert "body.immersive:is(.imm-devices,.imm-apps):not(.has-win):not(.deck-full):not(.dev-mobile) #omnibar," in css
    assert "body.imm-apps.dvc-open:not(.dev-mobile) #apphub{right:calc(var(--dvc-w) + 30px)}" in (CSS / "43-desks.css").read_text()
    assert "['apps','App Hub']" in (JS / "11-settings.js").read_text()


def test_a_desktop_opens_its_company_and_its_board_follows():
    vd = (JS / "03-virtual-desktops.js").read_text()
    sw = vd.split("function switchDesk(n){")[1].split("\n}")[0]
    assert "deskCompanySync(n);deskCompanyChanged();" in sw
    sync = vd.split("async function deskCompanySync(n){")[1].split("\n}")[0]
    assert "if(!id)return;" in sync, "a desktop with no company keeps whichever is open"
    assert "'/api/companies/active'" in sync and "if(c.active||n!==curDesk)return;" in sync
    assert "deskCompanySet(n,'')" in sync, "a company you no longer keep is let go"
    dev = (JS / "01h-devscene.js").read_text()
    assert "'/api/devices/board'+(co?'?company='+encodeURIComponent(co):'')" in dev
    assert 'data-dvs="every"' in dev, "an empty company board says where the machines are"
    assert "deskCompaniesLoad()" in (JS / "09-websocket.js").read_text()


def test_removing_a_desktop_moves_the_ones_after_it_down_with_what_they_showed():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    vd = (JS / "03-virtual-desktops.js").read_text()
    fn = "function deskShift(n){" + vd.split("function deskShift(n){")[1].split("\n}")[0] + "\n}"
    js = """
var store={'immersive.scene':'island','immersive.scene.d2':'devices','immersive.scene.d3':'apps','desk.company.d3':'acme'};
var localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=v},removeItem:k=>{delete store[k]}};
var DESKS=3,IMMERSIVE={chosen:true,scene:'island'};
function immersiveSceneOf(n){return store[n===1?'immersive.scene':'immersive.scene.d'+n]||IMMERSIVE.scene}
function deskCompanyOf(n){return store['desk.company.d'+n]||''}
""" + fn + "\ndeskShift(2);console.log(JSON.stringify(store));"
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out == {"immersive.scene": "island", "immersive.scene.d2": "apps", "desk.company.d2": "acme"}
    kp = (JS / "29-keyboard-palette.js").read_text()
    rm = kp.split("function removeDesk(n){")[1].split("\n}")[0]
    assert "if((w.desk||1)>n)w.desk=(w.desk||1)-1" in rm, "a window on a later desktop is never left on a number that is gone"
    assert re.search(r"deskShift\(n\);\s*DESKS--", rm)
