"""The immersive experience (beta): a look laid over the theme, switched in Settings.

What this pins is the shape of the thing, because every rule below is one that a
later edit could drop without anything else noticing:

  * It is one body class. Every rule in 20-immersive.css is scoped to it, so
    switching it off leaves the standard desktop byte-for-byte as it was. A rule
    that escapes the prefix restyles everybody, and the beta stops being opt-in.
  * It adds exactly one blurred surface — the ACTIVE window — and the inactive
    ones stay opaque. That is the 16-glass convention: cost stays flat however
    many windows are open. And `body.glass-off` still wins over it, because a
    machine that cannot draw blur must be able to turn it all off in one place.
  * The active tint is opaque enough that the window underneath does not read
    through. Measured: at 76% the text of a stacked window was legible through
    the glass; 88% is the floor.
  * The parallax is never armed on a touch screen or under reduced motion, and
    it is a transform on the wallpaper layer, not a filter.
  * The switch lives in Settings → Appearance, applies on the spot, and its own
    text says the TUI has no equivalent (a terminal has no wallpaper or glass).
  * The wallpaper it ships is ranked BELOW a theme's own — the theme designed its
    scene — and above the wizard's preset.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
UI = ROOT / "agentos" / "ui"
CSS = (UI / "src" / "css" / "20-immersive.css").read_text()
CODE = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
JS = (UI / "src" / "js" / "01b-immersive.js").read_text()
SETTINGS = (UI / "src" / "js" / "11-settings.js").read_text()
WALLS = (UI / "src" / "js" / "08-wallpaper-jarvis-voice.js").read_text()
BUNDLE = (UI / "index.html").read_text()


def _selectors():
    """Every selector list in the file, comments stripped, one entry per rule."""
    out = []
    for block in re.findall(r"([^{}]+)\{[^{}]*\}", CODE):
        sel = block.strip()
        if sel and not sel.startswith("@"):
            out.append(sel)
    return out


def test_every_rule_is_scoped_to_the_body_class():
    """Opt-in means opt-in: no selector may reach the standard desktop."""
    loose = []
    for sel in _selectors():
        for part in sel.split(","):
            part = part.strip()
            if not part:
                continue
            # `:root[data-theme=light] body.immersive …` is the light-theme form
            if "body.immersive" not in part:
                loose.append(part)
    assert not loose, f"rules outside body.immersive: {loose}"


def test_only_the_active_window_is_glass_and_glass_off_still_wins():
    active = re.search(r"body\.immersive \.win\.active\{([^}]*)\}", CODE)
    assert active and "backdrop-filter:blur" in active.group(1)
    inactive = re.search(r"body\.immersive \.win\{([^}]*)\}", CODE)
    assert inactive and "backdrop-filter" not in inactive.group(1), "inactive windows must stay opaque"
    off = re.search(r"body\.immersive\.glass-off \.win\.active\{([^}]*)\}", CODE)
    assert off and "backdrop-filter:none" in off.group(1) and "background:var(--bg)" in off.group(1)


def test_active_window_tint_is_opaque_enough_to_hide_the_window_beneath():
    m = re.search(r"body\.immersive \.win\.active\{[^}]*color-mix\(in srgb,var\(--bg\) (\d+)%,transparent\)", CODE)
    assert m, "active window background must be mixed from --bg"
    assert int(m.group(1)) >= 88, "at 76% the window underneath read through the glass (measured)"


def test_parallax_is_a_transform_on_the_wallpaper_and_never_on_touch():
    assert "isTouch()" in JS and "prefers-reduced-motion" in JS
    assert "translate3d(" in JS and "requestAnimationFrame" in JS
    assert "filter" not in JS.split("function immersivePointer")[1], "the wallpaper moves; it is never re-filtered"
    # armed on pointer only, and torn down when the look is switched off
    assert "addEventListener('pointermove'" in JS and "removeEventListener('pointermove'" in JS


def test_module_state_uses_var_not_let():
    """The bundle is one script in file order; a top-level let/const is read by
    earlier files in the temporal dead zone (CLAUDE.md: the UI is built)."""
    for line in JS.splitlines():          # unindented = top level of the bundle
        assert not line.startswith(("let ", "const ")), line


def test_switch_lives_in_settings_appearance_and_applies_on_the_spot():
    look = SETTINGS.split("if(want('look'))")[1].split("if(want('system'))")[0]
    assert "pSwitch('s-imm'" in look and "Immersive experience (beta)" in look
    assert "setImmersive(im.checked)" in SETTINGS
    # the honesty rule: the switch says what the terminal face does not have
    assert "TUI" in look and "no wallpaper or glass" in look


def test_wallpaper_ships_and_ranks_below_the_theme_s_own():
    assert (UI / "assets" / "wallpapers" / "immersive.svg").exists()
    assert "'immersive'" in WALLS.split("const BUILTIN_WALLS")[1].split("\n")[0]
    m = re.search(r"pickedWall\(\)\|\|themeWall\(\)\|\|\(typeof immersiveOn", WALLS)
    assert m, "a theme's wallpaper outranks the look's; the look's outranks the preset"


def test_shipped_bundle_carries_it():
    assert "body.immersive .win.active" in BUNDLE and "function setImmersive" in BUNDLE


def test_base_window_still_has_no_blur():
    """The rule this look must not undo: 03-windows.css's .win never blurs."""
    base = (UI / "src" / "css" / "03-windows.css").read_text()
    win = re.search(r"\n\.win\{([^}]*)\}", base)
    assert win and "backdrop-filter" not in win.group(1)
