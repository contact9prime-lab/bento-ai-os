"""The Town is where Bento opens, and what is on it can be tapped.

Reported with a screenshot of the Town: the Brain and the FILES label did nothing when
clicked, because in Office HQ and the Town the 3D canvas lives in the wall under the desktop
and takes no tap. What this pins:
- a browser that never chose a scene gets the Town ('island'), except on a Zero, whose
  office is one person drawn flat: it gets the sky;
- a browser that chose another scene before is moved to the Town ONCE after the update, with
  a toast to go back, and never on a Zero or a small machine's own screen;
- the Brain, the files and a person's name are doors (role=button, a click and a key), and
  a click on open ground in HQ/Town reaches the picture the way the wheel does;
- the desktop band scene (not HQ) still takes no tap.
"""
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src"
IMM = (UI / "js" / "01b-immersive.js").read_text()
O3 = (UI / "js" / "24k-office3d.js").read_text()
CSS = (UI / "css" / "23-office.css").read_text()


def test_a_new_browser_opens_on_the_town_unless_it_is_a_zero():
    assert "scene:sceneStored()||'island'" in IMM
    assert "chosen:!!sceneStored()" in IMM
    now = IMM[IMM.index("function immersiveSceneNow(){"):][:220]
    assert "if(!IMMERSIVE.chosen&&zeroScreen())s='aurora';" in now
    # the Zero answer is remembered for the next first paint, like screen.lite
    assert "localStorage.setItem('screen.zero'" in IMM
    # choosing a scene is a choice, and a stale stored name still falls back
    assert "IMMERSIVE.chosen=true" in IMM


def test_an_updated_browser_is_moved_to_the_town_once_with_a_way_back():
    intro = IMM[IMM.index("function townIntro(){"):][:700]
    assert "localStorage.getItem('immersive.town')" in intro and "localStorage.setItem('immersive.town','1')" in intro
    assert "zeroScreen()" in intro and "liteScreen()" in intro and "!IMMERSIVE.chosen" in intro
    assert "setImmersiveScene('island')" in intro
    assert "go:()=>setImmersiveScene(was)" in intro
    # it runs once the platform answered, so a Zero is known before it decides
    assert "townIntro();" in IMM[IMM.index("function liteScreenSet(){"):][:500]


def test_the_brain_files_and_names_are_doors():
    assert "function of3Door(e,label,fn)" in O3
    assert "'Open memory and knowledge',of3BrainOpen)" in O3
    assert "'Files your agents made',of3FilesOpen)" in O3
    assert "of3PersonOpen(O.people[p.key]||p)" in O3
    door = O3[O3.index("function of3Door("):][:400]
    assert "role','button'" in door and "tabIndex=0" in door and "onkeydown" in door
    # the scene has no drawer: the files are the Files app there
    assert "if(of3HQ()){OFFICE.newFiles=0;if(typeof openApp==='function')openApp('files')}" in O3
    assert ".of3-brain,.of3-files,.of3-tag{pointer-events:auto;cursor:pointer}" in CSS
    # the band under the home screen still takes no tap
    assert "#office-scene .of3-ui *{pointer-events:none!important}" in CSS


def test_a_click_on_open_ground_reaches_the_picture_in_hq():
    i = O3.index("document.addEventListener('click',e=>{")
    click = O3[i:i + 600]
    assert "if(!of3HQ()||!OF3.cv" in click and "has-win" in click
    assert "t.id==='desktop'" in click and "of3Tap(e)" in click
    assert ">5)return;" in click   # a drag is not a click
