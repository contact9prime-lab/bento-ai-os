"""A small machine's own screen (a Pi) draws only what it can afford.

Measured with software rendering, the way a Pi without GPU drawing has it, on a copy of a real
company with the lite profile: the Town, the World and the Mind took every core, Movement and
Crew 2.6 cores, Office HQ 1.3, and the prompt bar's breathing orb alone 3.6. After this change
each of those screens costs about a quarter of a core and the kiosk's office about half.

What this pins:
- liteScreen() is the one answer, read from /api/platform (`small`, not a remote viewer) and
  remembered per browser for the next first paint; a phone or laptop looking at the Pi keeps
  every scene, because it draws for itself;
- on that screen only Aurora and the comic Office are drawn; the person's choice is kept, and
  every scene's own start line asks immersiveSceneNow(), never IMMERSIVE.scene;
- the Office app draws flat there and says why; the pet sits still (fetch never ends);
- decorations that animate forever stop there; a pulse that shows work keeps moving;
- Settings offers only the scenes that screen draws, and says how to get the rest.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "agentos" / "ui" / "src" / "js"
CSS = ROOT / "agentos" / "ui" / "src" / "css"
IMM = (JS / "01b-immersive.js").read_text()


def _fn(src, name):
    return re.search(r"^function " + name + r"\(.*?^\}$", src, re.M | re.S).group(0)


def _scenes(platform, memo=None):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    decl = re.search(r"^var LITE_SCENES=.*?;$", IMM, re.M).group(0)
    scenes = re.search(r"^var IMMERSIVE_SCENES=(\[.*?\]);$", IMM, re.M).group(1)
    js = "\n".join([
        decl,
        "var store=" + json.dumps({"screen.lite": memo} if memo is not None else {}) + ";",
        "var localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=v}};",
        ("var PLATFORM=" + json.dumps(platform) + ";") if platform is not None else "",
        "var IMMERSIVE={scene:'aurora'};",
        IMM[IMM.index("function liteScreen()"):IMM.index("function immersiveSceneNow()")],
        _fn(IMM, "immersiveSceneNow"),
        "var out={};" + scenes + ".forEach(s=>{IMMERSIVE.scene=s;out[s]=immersiveSceneNow()});",
        "console.log(JSON.stringify({lite:liteScreen(),out}))",
    ])
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_small_machines_own_screen_draws_only_the_light_scenes():
    got = _scenes({"small": True, "remote_client": False})
    assert got["lite"] is True
    for scene, drawn in got["out"].items():
        assert drawn == (scene if scene in ("aurora", "office") else "aurora"), (scene, drawn)


def test_a_phone_looking_at_the_pi_keeps_every_scene():
    got = _scenes({"small": True, "remote_client": True})
    assert got["lite"] is False
    assert all(s == d for s, d in got["out"].items())


def test_a_big_machine_keeps_every_scene():
    got = _scenes({"small": False})
    assert got["lite"] is False and all(s == d for s, d in got["out"].items())


def test_before_the_platform_answers_the_last_answer_is_used():
    # PLATFORM is a `let` in a later file: at first paint it is not there yet
    assert _scenes(None, "1")["lite"] is True
    assert _scenes(None, "0")["lite"] is False
    assert _scenes(None)["lite"] is False
    # and an answer without `small` (the placeholder before the fetch) is not an answer
    assert _scenes({"mode": "hosted"}, "1")["lite"] is True


def test_every_scene_starts_from_what_this_screen_draws():
    # a scene that started itself from IMMERSIVE.scene would run on a Pi whatever 01b decided
    for f in sorted(JS.glob("*.js")):
        if f.name == "01b-immersive.js":
            continue
        assert not re.search(r"IMMERSIVE\.scene\s*===", f.read_text()), f.name
    body = IMM[IMM.index("function applyImmersive(){"):IMM.index("var IMMERSIVE_SCENES")]
    assert "IMMERSIVE.scene" not in body
    assert "const scene=immersiveSceneNow();" in body
    assert "liteScreenSet()" in (JS / "22-quicksettings.js").read_text()


def test_the_office_is_flat_there_and_its_pet_sits_still():
    of3 = (JS / "24k-office3d.js").read_text()
    wanted = _fn(of3, "of3Wanted")
    assert wanted.index("liteScreen()") < wanted.index("of3HQ()")
    assert "OF3.why=" in wanted[wanted.index("liteScreen()"):]
    office = (JS / "24d-office.js").read_text()
    assert "function officeLight(){return liteScreen()}" in office
    assert "OFFICE.static||officeLight())return;" in _fn(office, "officePetStep")


def test_decorations_that_never_stop_stop_there():
    css = (CSS / "38-lite-screen.css").read_text()
    for sel in ("#omni-orb:not(.busy)", ".av-sprite", ".br-glow", ".stg-bg", ".stg-pic img", ".dm-bg line"):
        assert "body.lite-screen " + sel in css, sel
    # work in progress keeps its pulse: the busy orb is not stopped
    assert "#omni-orb.busy" not in css
    assert "classList.toggle('lite-screen',liteScreen())" in IMM


def test_settings_offers_only_what_that_screen_draws():
    st = (JS / "11-settings.js").read_text()
    row = st[st.index("pRow('Scene'"):st.index("pRow('Wallpaper'")]
    assert ".filter(o=>!liteScreen()||LITE_SCENES[o[0]])" in row
    assert "bento profile full" in row
