"""Glass quality: the shell must not blur what nobody can see through.

`backdrop-filter` compounds — each translucent surface makes the compositor
re-blur everything beneath it — so a stack of windows is where a web desktop
stops feeling native. Measured here: five windows in the Liquid Glass theme ran
at 6.5fps; the same five at "reduced" ran at 27, and at "off" at 60.

Two rules keep that honest, and both are easy to undo by accident:
  1. The base `.win` rule must never blur. Its background is an opaque theme
     colour, so the blur was invisible and still cost the whole frame budget.
  2. Turning the blur off must also make the surface opaque, or a glass theme's
     66%-transparent window becomes four windows of text legible through each
     other — cheaper to draw and impossible to read.
"""
import pathlib
import re

UI = pathlib.Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src"


def test_base_window_rule_does_not_blur():
    css = (UI / "css" / "03-windows.css").read_text()
    rule = css.split(".win{", 1)[1].split("}", 1)[0]
    assert "backdrop-filter" not in rule, (
        "the base .win rule blurs behind an opaque background — invisible, and it "
        "cost 8x the frame time with five windows open"
    )


def test_themes_declare_their_own_glass():
    """Glass themes are where blur is the design; they set both halves themselves."""
    js = (UI / "js" / "02-themes-shells.js").read_text()
    for rule in re.findall(r"\.win\{[^}]*backdrop-filter:blur[^}]*\}", js):
        assert "background:rgba" in rule, (
            "a theme blurring .win must also make it translucent, or the blur is "
            f"invisible again: {rule[:90]}"
        )


def test_reduced_and_off_go_opaque():
    css = (UI / "css" / "16-glass.css").read_text()
    lite = css.split("body.glass-lite .win:not(.active){", 1)[1].split("}", 1)[0]
    assert "background:var(--bg)!important" in lite
    assert "backdrop-filter:none!important" in lite
    assert "body.glass-off .win{background:var(--bg)!important}" in css


def test_auto_probe_is_time_bounded():
    """A frame-count probe makes the slowest machine wait longest for the fix."""
    js = (UI / "js" / "01a-glass.js").read_text()
    assert "t-t0<900" in js, "the auto probe must sample by elapsed time, not frame count"
    assert "GLASS.level==='off'" in js, "the ladder must stop at off instead of recursing"


def test_glass_module_loads_before_themes():
    """applyTheme() re-probes at load; a const read before its file runs throws."""
    names = sorted(p.name for p in (UI / "js").glob("*.js"))
    assert names.index("01a-glass.js") < names.index("02-themes-shells.js")
