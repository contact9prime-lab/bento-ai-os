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
    m = re.search(r"pickedWall\(\)\|\|themeWall\(\)\|\|\(typeof immersiveWall", WALLS)
    assert m, "a theme's wallpaper outranks the look's; the look's outranks the preset"


def test_shipped_bundle_carries_it():
    assert "body.immersive .win.active" in BUNDLE and "function setImmersive" in BUNDLE


def test_base_window_still_has_no_blur():
    """The rule this look must not undo: 03-windows.css's .win never blurs."""
    base = (UI / "src" / "css" / "03-windows.css").read_text()
    win = re.search(r"\n\.win\{([^}]*)\}", base)
    assert win and "backdrop-filter" not in win.group(1)


# ---- the ground-up pass (phases 1–5): the shape of the scene, the kit, the icons ----

SHELL = (UI / "src" / "shell.html").read_text()
ICONS = (UI / "src" / "js" / "00d-icons.js").read_text()
CHAT = (UI / "src" / "js" / "10-chat.js").read_text()
OMNI = (UI / "src" / "js" / "28a-omnibar.js").read_text()
LAYOUT = (UI / "src" / "js" / "06-icon-layout.js").read_text()


def test_tokens_are_set_once_and_body_type_is_fifteen():
    """The whole desktop reflows from one block: thirty apps read --fs-*."""
    m = re.search(r"body\.immersive\{([^}]*)\}", CODE)
    assert m and "--fs-base:15px" in m.group(1) and "--r-lg:16px" in m.group(1)


def test_field_rule_has_zero_specificity():
    """:where() — the plain :not chain out-ranked .psearch and put the magnifier
    over the placeholder in every search box (measured)."""
    assert "body.immersive :where(input:not([type=checkbox])" in CODE
    assert re.search(r"body\.immersive input:not\(\[type=checkbox\]\)", CODE) is None


def test_icons_are_drawn_here_and_glyphs_stay_in_the_standard_look():
    assert "var UI_ICONS={" in ICONS and "function uiIcon(" in ICONS
    for line in ICONS.splitlines():
        assert not line.startswith(("let ", "const ")), line
    # the rail carries both forms; the base stylesheet hides the svg
    assert "<i>${ic}</i>${uiIcon(ico,14)}" in SETTINGS
    assert ".prefs-side .psi svg{display:none}" in (UI / "src" / "css" / "14-omnibar.css").read_text()
    # glyph buttons say what they mean, and the swap keeps the glyph to restore
    for f, needle in [(SHELL, 'data-ic="power"'), (CHAT, 'data-ic="send"'), (CHAT, 'data-ic="image"')]:
        assert needle in f
    assert "el.dataset.gl=el.innerHTML" in JS and "el.innerHTML=el.dataset.gl" in JS


def test_home_scene_exists_only_in_the_look_and_yields_to_windows():
    assert '<div id="home" hidden>' in SHELL
    assert "function homeRender" in JS and "setInterval(homeRender,60000)" in JS
    # the deck leaves the desktop; the launcher button opens the wall
    assert "body.immersive:not(.deck-full) #deck{display:none}" in CODE
    assert "immersiveOn()&&typeof deckFull==='function'" in LAYOUT
    # a window open: scene fades, bar stands down unless summoned
    assert "body.immersive.has-win #home" in CODE
    assert "body.immersive.has-win #omnibar:not(.summoned):not(.pop)" in CODE
    assert "function immersiveWinChange" in JS and "immersiveWinChange()" in (UI / "src" / "js" / "04c-lifecycle.js").read_text()
    # chips fill the bar, they never send
    assert "inp.value=chips[i]" in JS and "omniAsk" not in JS.split("function homeRender")[1]


def test_spotlight_sections_and_chat_drawer_are_emitted_always_and_shown_by_the_look():
    assert 'class="omni-sec"' in OMNI
    assert ".omni-sec{display:none}" in (UI / "src" / "css" / "14-omnibar.css").read_text()
    assert 'id="cs-toggle"' in CHAT
    assert "#cs-toggle{display:none}" in (UI / "src" / "css" / "09-chat-team-docs.css").read_text()
    # the button sits above the drawer it opens, or it could never close it
    assert re.search(r"body\.immersive #cs-toggle\{[^}]*z-index:4", CODE)


def test_wallpaper_follows_the_hour_and_only_reloads_on_a_band_change():
    for w in ("immersive", "immersive-dawn", "immersive-night"):
        assert (UI / "assets" / "wallpapers" / f"{w}.svg").exists()
        assert f"'{w}'" in WALLS.split("const BUILTIN_WALLS")[1].split("\n")[0]
    assert "function immersiveWallBand" in JS and "IMMERSIVE.band!==band" in JS
    assert "typeof immersiveWall==='function'?immersiveWall():''" in WALLS


def test_home_chips_meet_the_tap_floor_on_touch():
    assert re.search(r"body\.immersive\.dev-touch \.hm-chip\{[^}]*min-height:44px", CODE)


# ---- the Movement scene: the machine drawn as an automatic watch ----

MOVE = (UI / "src" / "js" / "01c-movement.js").read_text()
WS = (UI / "src" / "js" / "09-websocket.js").read_text()


def test_movement_is_a_scene_of_the_look_picked_in_settings():
    look = SETTINGS.split("if(want('look'))")[1].split("if(want('system'))")[0]
    assert "pSelect('s-imm-scene'" in look and "'movement'" in look and "'aurora'" in look
    assert "setImmersiveScene(sc.value)" in SETTINGS
    assert "function setImmersiveScene" in JS and "localStorage.setItem('immersive.scene'" in JS
    # the honesty in the row: what it costs, and when it does not draw
    assert "twenty times a second" in look and "reduced motion" in look and "no blur" in look


def test_movement_costs_what_it_says():
    """≤20 fps, no drawing when nobody can see it, one still frame under
    reduced motion, no filter or shadow (a canvas shadow is a blur)."""
    assert "requestAnimationFrame(movementFrame)" in MOVE and "setInterval" not in MOVE
    assert "if(dt<(busy?0.048:0.083))" in MOVE                    # 20 fps busy, 12 idle
    assert "if(!movementCovered()){const t0=performance.now();movementDraw(dt)" in MOVE
    assert "document.hidden" in MOVE and "has-fullwin" in MOVE and "w.max&&!w.min" in MOVE
    assert "prefers-reduced-motion" in MOVE and "if(MOVEMENT.static){movementDraw(0);return}" in MOVE
    assert "shadowBlur" not in MOVE and "filter" not in MOVE.split("/* ---- drawing ---- */")[1]
    for line in MOVE.splitlines():
        assert not line.startswith(("let ", "const ")), line


def test_movement_parts_are_the_machine_s_parts():
    """Every moving part maps to something real, and the events come from the
    stream the page already has — nothing polls for animation's sake."""
    assert "movementPulse('tool',ev.name)" in WS
    assert "movementPulse('flow'" in WS and "ev.event!=='heartbeat'" in WS
    assert "movementPulse('done',ev.flow)" in WS
    assert "RUNNING.size" in MOVE                                   # the train and the balance follow the turn
    assert "fetch('/api/flows')" in MOVE and "60000" in MOVE         # one wheel per enabled flow, once a minute
    assert "agentName()" in MOVE and "'SOUL · '" in MOVE and "'CAL. '" in MOVE
    # the canvas rides the wallpaper (parallax) and never takes a pointer
    assert "wall.appendChild(cv)" in MOVE
    assert re.search(r"body\.immersive #movement\{[^}]*pointer-events:none", CODE)
    # 01c loads after 01b: the scene starts itself at first paint, and 01b
    # never touches MOVEMENT before it exists
    assert "if(typeof MOVEMENT==='undefined')return;" in JS
    assert MOVE.rstrip().endswith("movementStart();")
    assert (UI / "assets" / "wallpapers" / "immersive-movement.svg").exists()
    assert "'immersive-movement'" in WALLS.split("const BUILTIN_WALLS")[1].split("\n")[0]
