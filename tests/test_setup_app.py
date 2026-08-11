"""Setup as an app: the same arc in a window, and only one of it.

The arc has two homes — the first-run overlay and the Setup app — and exactly one
implementation. A "tour mode" that only showed you the steps would be a second
implementation to drift, and the one that drifted would be whichever nobody was
demoing. So these assert the properties that keep the two homes honest rather
than the pixels, which the screenshots cover.

Source-level, like the other UI tests: the behaviours here are conventions the
bundle has no way to enforce at runtime.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = ROOT / "agentos" / "ui" / "src" / "js"
CSS = ROOT / "agentos" / "ui" / "src" / "css"


def read(p) -> str:
    return p.read_text()


OB = read(JS / "14b-onboarding.js")
REG = read(JS / "05-apps-registry.js")


# ---------------------------------------------------------------------------
# It is an app
# ---------------------------------------------------------------------------

def test_setup_is_a_registered_app():
    """Openable from the deck, the start menu and the omnibar — all three read
    APPS, so being in it is the whole of being discoverable."""
    assert re.search(r"\bsetup:\{id:'setup'", REG), "no setup entry in APPS"
    assert "render:renderSetup" in REG


def test_it_is_in_a_group_people_would_look_in():
    """An app that exists but is in no group is an app you can only reach if you
    already knew it was there."""
    assert "'setup'" in read(JS / "06a-deck.js")


def test_the_copilot_can_say_what_it_is_showing():
    assert "setup:()=>" in REG


def test_settings_offers_it():
    s = read(JS / "11-settings.js")
    assert "openApp(\\'setup\\')" in s or 'openApp(\'setup\')' in s
    assert "obRestart()" in s, "and the full-screen re-run is still offered"


# ---------------------------------------------------------------------------
# One arc, two homes
# ---------------------------------------------------------------------------

def test_the_app_renders_the_same_arc_and_not_a_copy():
    """`renderSetup` must go through the same host/render path the overlay uses.
    A second renderer is the drift this whole design exists to avoid."""
    body = OB.split("async function renderSetup")[1].split("\nfunction obRender")[0]
    assert "obLoad()" in body, "same probe"
    assert "obHost(" in body, "same host claim"
    assert "obRender()" in body, "same renderer"
    assert "OB_PANES" not in body, "panes are shared, not re-declared"


def test_there_is_one_pane_table_and_one_wiring_table():
    assert OB.count("var OB_PANES=") == 1
    assert OB.count("var OB_WIRE=") == 1


def test_only_one_host_holds_the_arc_at_a_time():
    """Every pane wires itself by element id, so two hosts on screen would mean
    two `#ob-name-go` buttons and a coin toss over which one a click reached."""
    host = OB.split("function obHost")[1].split("\n}")[0]
    assert "OB.host&&OB.host!==el" in host, "it must tear down the other host"
    assert "OB.host=el" in host


def test_closing_the_app_hands_the_arc_back():
    """Otherwise the next `obShow()` renders into a host that is no longer on
    screen, and the first-run wizard silently stops appearing."""
    entry = REG.split("setup:{id:'setup'")[1].split("},\n")[0]
    assert "OB.host=null" in entry


def test_the_overlay_releases_it_too():
    close = OB.split("function obClose(")[1].split("\n}")[0]   # not obCloseApp
    assert "OB.host=null" in close


# ---------------------------------------------------------------------------
# A window is not a wizard
# ---------------------------------------------------------------------------

def test_closing_the_window_does_not_claim_setup_is_finished():
    """Somebody who opens the app to look around, on a machine still half
    configured, must not silently never see the first-run screen again."""
    render = OB.split("function obRender")[1]
    assert "if(!inWin)markSetupComplete();" in render


def test_the_window_offers_the_full_screen_version():
    assert "id=\"ob-full\"" in OB or "id='ob-full'" in OB
    assert "obShow({step:OB.open})" in OB, "and it opens where you were"


def test_the_resize_observer_is_disconnected_on_close():
    """A live ResizeObserver on a removed window body is a leak, and the one thing
    a closed window must not still be doing is work."""
    entry = REG.split("setup:{id:'setup'")[1].split("},\n")[0]
    assert "_obRO" in entry and "disconnect()" in entry


def test_the_window_layout_does_not_size_itself_against_the_viewport():
    """The overlay is `width:min(1080px,100vw)`. Inside a 1000px window that is
    the SCREEN, so the stage would overhang its own frame."""
    css = read(CSS / "18-onboarding.css")
    assert ".wbody.ob-inwin .ob-stage{width:100%" in css.replace("\n", "")


def test_a_narrow_window_gets_the_phone_layout():
    css = read(CSS / "18-onboarding.css")
    assert ".wbody.ob-inwin.narrow .ob-stage" in css
    assert "grid-template-columns:1fr" in css.split(".wbody.ob-inwin.narrow .ob-stage")[1][:80]
    assert "clientWidth<700" in OB, "and something sets the class"


# ---------------------------------------------------------------------------
# It is the real thing, which is only safe because re-running is safe
# ---------------------------------------------------------------------------

def test_the_app_does_real_work_rather_than_previewing_it():
    """The steps in the window call the same routes the wizard does. That is only
    acceptable because none of them destroys anything — `restart` explicitly does
    not wipe, and the starter agent and flow rename rather than overwrite."""
    ob_py = (ROOT / "agentos" / "onboarding.py").read_text()
    assert "def restart" in ob_py
    restart = ob_py.split("def restart")[1].split("\ndef ")[0]
    assert "factory reset" in restart.lower(), "the docstring must keep saying so"
    for fn in ("def starter_agent", "def starter_flow"):
        body = ob_py.split(fn)[1].split("\ndef ")[0]
        assert "while" in body, f"{fn} must rename on collision, not overwrite"
