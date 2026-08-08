"""Window chrome and placement: the conventions that make a stack of windows readable.

Source-level assertions, in the same spirit as test_ui_lifecycle: each of these is a
rule that nothing else would notice being broken. A window manager that quietly goes
back to "centre it, plus 26px" still passes every functional test — it just produces
the pile of near-identical rectangles that these rules exist to prevent.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src"


def js(name: str) -> str:
    return (ROOT / "js" / name).read_text()


def css(name: str) -> str:
    return (ROOT / "css" / name).read_text()


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

def test_a_window_you_placed_opens_where_you_left_it():
    src = js("04-wm.js")
    for fn in ("function winSaveGeom", "function winLoadGeom", "function winPlace"):
        assert fn in src, f"{fn} missing — window geometry is not being remembered"
    assert "winPlace(el,app)" in src


def test_geometry_is_saved_after_a_move_and_after_a_resize():
    """Only saving on one of them is the version of this feature that feels broken:
    you resize a window, reopen it, and it is the size you never chose."""
    src = js("04-wm.js")
    drag = src.split("function dragify")[1][:1600]
    assert "winSaveGeom(w)" in drag, "a drag must persist the new position"
    resize = src.split("function resizify")[1][:2200]
    assert "winSaveGeom(w)" in resize, "a resize must persist the new size"


def test_a_maximised_or_snapped_window_does_not_overwrite_your_geometry():
    """Otherwise maximising once and closing means every future open is full screen,
    and the shape you actually chose is gone."""
    save = js("04-wm.js").split("function winSaveGeom")[1][:220]
    for state in ("w.max", "w.min", "w.snap"):
        assert state in save, f"winSaveGeom must skip {state}"


def test_saved_geometry_is_clamped_into_the_current_screen():
    """Geometry can arrive from a bigger monitor. Unclamped, the window opens
    off-screen and there is no way to reach its title bar to drag it back."""
    place = js("04-wm.js").split("function winPlace")[1][:900]
    assert "Math.max(a.x,Math.min(" in place and "Math.max(a.y,Math.min(" in place


def test_the_cascade_wraps_on_the_screen_not_on_the_window():
    """perCol derived from the window's own height gave every app a different wrap
    point, so window six jumped to a column window five had not started."""
    place = js("04-wm.js").split("function winPlace")[1][:1200]
    assert "const perCol=Math.max(1,Math.min(6,Math.floor(a.h/(WIN_STEP*3))))" in place
    # the wrap point must be a function of the area alone
    assert "Math.floor((a.h-height)/WIN_STEP)" not in place


def test_the_cascade_step_is_taller_than_a_title_bar():
    """26px was less than the 36px title bar, so a cascaded window covered the name
    of the one underneath it — which is the only thing a cascade is for."""
    src = js("04-wm.js")
    step = int(src.split("var WIN_STEP=")[1].split(",")[0])
    bar = int(css("03-windows.css").split(".win .ttl{")[1].split("height:")[1].split("px")[0])
    assert step > bar, f"cascade step {step}px must clear the {bar}px title bar"


def test_windows_are_sized_to_the_usable_area_not_the_viewport():
    """--mbh and --tbh already describe the menu bar and the dock band. Sizing to the
    raw viewport is what opened tall windows with their footer under the dock."""
    area = js("04-wm.js").split("function winArea")[1][:500]
    assert "--mbh" in area and "--tbh" in area


# ---------------------------------------------------------------------------
# Depth: which window am I typing into?
# ---------------------------------------------------------------------------

def test_the_active_window_is_unmistakable():
    """--el-5 against --el-4 and a .16 border against a .10 one are differences you
    cannot see at a glance, and a stack of five read as one dark mush."""
    win = css("03-windows.css")
    base = win.split(".win{")[1].split("}")[0]
    active = win.split(".win.active{")[1].split("}")[0]
    assert "--el-2" in base, "an inactive window should recede"
    assert "--el-5" in active and "--acc" in active, "the active window needs a ring"


def test_the_base_window_rule_still_never_blurs():
    """CLAUDE.md: --bg is opaque in every theme, so a blur here blurs a backdrop the
    window then paints over — invisible, and 60fps to 8fps with five windows open."""
    base = css("03-windows.css").split(".win{")[1].split("}")[0]
    assert "backdrop-filter" not in base


def test_dragging_lifts_the_window_being_dragged():
    assert ".win.dragging{" in css("03-windows.css")


# ---------------------------------------------------------------------------
# The agent mark
# ---------------------------------------------------------------------------

def test_the_copilot_mark_is_present_on_the_active_window_and_quiet_elsewhere():
    """It is the one piece of chrome people read as agentic, so it should not have to
    be discovered by hovering. Eight glowing marks would say nothing, so it is the
    ACTIVE window that shows it."""
    src = css("14-omnibar.css")
    active = src.split(".win.active .cp-btn{")[1].split("}")[0]
    assert "opacity:1" in active and "--acc" in active
    base = src.split(".win .cp-btn{")[1].split("}")[0]
    assert "opacity:0" in base, "inactive windows keep it out of the way"


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

def test_a_panel_does_not_repeat_the_window_title():
    """'Memory' above 'Memory' spent the widest row in every app on a word the user
    had just read, and pushed the search box into the corner."""
    shell = js("04-wm.js").split("function panelShell")[1][:900]
    assert ".tname" in shell and "dup" in shell


def test_a_settings_row_wraps_instead_of_crushing_its_label():
    """flex:1;min-width:0 against a control with a hard minimum meant the LABEL gave
    up all its space: 'Ollama base URL' broke over two lines beside a field with room
    to spare."""
    src = css("14-omnibar.css")
    row = src.split(".prow{")[1].split("}")[0]
    assert "flex-wrap:wrap" in row
    assert ".prow .pl{flex:1 1 240px" in src


def test_a_stat_tile_colour_does_not_paint_a_band_across_it():
    """.audok and friends are badge recipes — a tint behind an inline pill. On .val,
    which is a block, the tint became a coloured bar through the middle of the tile."""
    src = css("09a-gallery-spaces.css")
    assert ".val.audok,.val.audden,.val.audask{background:none}" in src


def test_the_summary_grid_does_not_orphan_a_fourth_tile():
    assert "auto-fit" in css("10-panels.css").split(".tmgrid{")[1].split("}")[0]
