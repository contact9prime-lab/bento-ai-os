"""Touch targets: the phone half of the three faces.

The bug this file exists to prevent does not look like a bug in the source. The
phone layout was carefully built — sheets, a bottom dock, safe-area padding, a
launcher that fills the screen — and then every control INSIDE an app kept the
size a mouse gave it. Measured in a real browser at 390x844, over remote access,
signed in as a phone would be:

    Flows          a 10x16 ✕
    Chat           a 98x23 "clear session"
    Studio         a 97x24 toolbar button
    every window   a 26x26 close button, in the corner, the hardest place to aim
    Settings       a 188px rail on a 390px screen, so the brain picker, the model
                   picker, the Ollama URL and every API key field sat between
                   x=404 and x=571 — off the side of the phone, clipped by an
                   overflow:hidden ancestor, with nothing saying they existed
    App Store      six tabs adding up to 469px in a strip that did not scroll, so
                   "Build with AI" was not on the phone at all
    every window   a ✦ copilot button whose panel is display:none on a phone —
                   a control that answers a tap by doing nothing

A fingertip is about 9mm; Apple asks for 44pt and Android for 48dp. A 16px
target is not a button people miss occasionally, it is a button that does not
work — and "the buttons don't work" is exactly how it was reported.

These are source-level assertions for the same reason as tests/test_ui_lifecycle:
the guarantee is a convention, and the moment a rule is dropped nothing else
notices. The measurements above came from Chrome with real touch emulation, not
from reading the CSS.
"""
import pathlib
import re

CSS = pathlib.Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src" / "css"
SRC = (CSS / "15-responsive.css").read_text()
#: The same file with comments removed. The comments here carry the measurements
#: that justify each rule, and they contain commas and braces — parsing rules out
#: of the raw text hands you half a paragraph as a selector.
CODE = re.sub(r"/\*.*?\*/", "", SRC, flags=re.S)


def _rule(selector_fragment: str) -> str:
    """The declaration block of the first rule whose selector contains the text."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CODE):
        if selector_fragment in m.group(1):
            return m.group(2)
    return ""


def _exact(selector: str) -> str:
    """The block of the rule whose selector list contains exactly this selector —
    `.prefs` must not be answered by the rule for `.prefs-side`."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CODE):
        if selector in [s.strip() for s in m.group(1).split(",")]:
            return m.group(2)
    return ""


# ------------------------------------------------------------------ the floor

def test_there_is_a_touch_target_floor_and_it_is_a_token():
    """One number, in one place. Spelled out per rule it drifts, and the rule that
    drifted is whichever one nobody was looking at."""
    assert re.search(r"body\.dev-touch\{[^}]*--tap:\s*(\d+)px", SRC), (
        "the --tap token is gone — there is no single answer to how big a "
        "touch target is")
    size = int(re.search(r"--tap:\s*(\d+)px", SRC).group(1))
    assert size >= 36, f"--tap is {size}px; a fingertip needs at least 36"


def test_the_floor_reaches_inside_apps_not_just_the_window_chrome():
    """It used to cover three things: the traffic lights, the prompt bar and the
    tray. Everything a person actually presses is inside a window."""
    block = _rule("body.dev-touch .win button")
    assert "min-height:var(--tap)" in block, (
        "controls inside app windows no longer get the touch floor")
    assert "min-width:var(--tap)" in block, (
        "an icon-only button can still be 10px wide")
    for sel in ("body.dev-touch .win select", "body.dev-touch #startmenu button",
                "body.dev-touch #powermenu button"):
        assert sel in SRC, f"{sel} is no longer covered by the touch floor"


def test_the_floor_is_real_size_not_an_invisible_halo():
    """A pseudo-element halo is the tempting fix — nothing reflows. But two
    adjacent 16px buttons with 40px halos overlap, and whichever paints last
    silently eats the other's taps: the same bug, harder to see."""
    touch = SRC.split("dev-touch", 1)[1].split("TABLET", 1)[0]
    assert "::after" not in touch, (
        "the touch floor is being applied with a pseudo-element overlay; "
        "adjacent halos overlap and steal each other's taps")


def test_the_window_close_button_is_big_enough_on_a_phone():
    """A sheet's only way out, in the corner. It was 26px."""
    block = _rule("body.dev-mobile .win .tbtns .cls")
    m = re.search(r"width:\s*(\d+)px", block)
    assert m, "the mobile close button has lost its explicit size"
    assert int(m.group(1)) >= 36, (
        f"the phone's close button is {m.group(1)}px — smaller than a fingertip")


# ------------------------------------------------- rows that ran off the side

def test_the_settings_rail_collapses_on_a_phone():
    """188px of a 390px screen, and the pane beside it could not hold its own
    rows — so half of Settings was off the side of the phone. Hiding the rail is
    not an option: it is the only way to the other ten tabs."""
    assert "body.dev-mobile .prefs-side" in SRC, (
        "Settings' rail is back to its desktop width on a phone")
    block = _rule("body.dev-mobile .prefs-side")
    assert "overflow-x:auto" in block, (
        "the rail does not scroll, so tabs past the edge are unreachable")
    assert "column" in _exact("body.dev-mobile .prefs"), (
        "the rail is still beside the content rather than above it")


def test_segmented_tab_strips_scroll_on_a_phone():
    """`.seg` is shared by every app with tabs, so this was never one app's bug."""
    block = _rule("body.dev-mobile .seg")
    assert "overflow-x:auto" in block, "a tab strip wider than the phone still clips"
    assert "max-width:100%" in block, "the strip can still push past the screen"


def test_the_dock_cannot_rest_on_a_half_visible_icon():
    """A scroller resting mid-icon puts the centre of the button outside the box,
    where a tap lands on the taskbar instead. Measured with four windows open:
    the sixth icon spanned 306..352 in a box ending at 328."""
    block = _rule("body.dev-mobile #dock")
    assert "scroll-snap-type" in block, "the dock can stop on a half-cut icon again"
    assert "scroll-snap-align" in _rule("body.dev-mobile #dock .dockb"), (
        "nothing tells the dock's icons where to stop")


# ------------------------------------------------------------ no dead controls

def test_the_copilot_button_is_not_offered_where_its_panel_cannot_open():
    """`.copanel` is display:none on a phone — it needs a second column. The ✦
    that toggles it stayed in every title bar, and pressing it did nothing at
    all, which is the honesty rule's dead control exactly."""
    assert "display:none" in _rule("body.dev-mobile .copanel"), (
        "the copilot rail is being drawn on a phone after all — then the button "
        "below should come back with it")
    assert re.search(r"body\.dev-mobile \.win \.cp-btn\{[^}]*display:none", SRC), (
        "the ✦ is back on a phone, where the panel it opens cannot be shown")


def test_the_prompt_bar_input_is_tall_enough_to_hit():
    """The one control on the phone's home screen, and it was 17px tall."""
    block = _rule("body.dev-touch #omni-in")
    m = re.search(r"min-height:\s*(\d+)px", block)
    assert m and int(m.group(1)) >= 30, (
        "the prompt bar's input is back to a mouse-sized target")


def test_the_settings_rail_turns_sideways_not_just_flexible():
    """The mobile rule said `display:flex` and assumed the default direction —
    but the BASE rail is `flex-direction:column`, so the "strip above the
    content" rendered as a 390x425px vertical wall of tabs: more than half the
    phone spent before a single setting was visible. Measured with the computed
    style at 390x844, reported as "on the phone it looks very cluttered". The
    direction has to be said out loud, and so does the snap — a strip that can
    rest half-way puts a button's centre outside its own box (the dock's rule)."""
    block = _rule("body.dev-mobile .prefs-side")
    assert "flex-direction:row" in block, (
        "the rail inherits the base column direction and becomes a wall of tabs")
    assert "scroll-snap-type:x" in block, (
        "the rail strip can rest between chips")


def test_a_checkbox_label_is_a_real_target_on_touch():
    """A checkbox is a shape, so its LABEL is the tap target. Measured on the
    share pane at 390x844: the box was 13x13 with a 16px label — 'ship this
    app?' decided by whichever tap lands nearest. The label gets the real floor
    (never a halo) and the box grows enough to read as one."""
    block = _exact("body.dev-touch .win label.ck")
    assert "min-height:var(--tap)" in block, (
        "checkbox labels are back under the touch floor")
    box = _exact("body.dev-touch .win label.ck input[type=checkbox]")
    assert box, "the checkbox itself no longer grows on touch"
