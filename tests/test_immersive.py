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
    # EVERY scene canvas, not just this one: they share the rule, so they are
    # asserted together rather than the CSS being split to keep a regex happy.
    assert re.search(r"body\.immersive #movement,body\.immersive #crew\{[^}]*pointer-events:none", CODE)
    # 01c and 01d load after 01b: each scene starts itself at first paint, and
    # 01b tests for each separately — one early return on the first undefined
    # would leave the other permanently unreachable on a first paint
    assert "if(typeof MOVEMENT!=='undefined')" in JS and "if(typeof CREW!=='undefined')" in JS
    assert MOVE.rstrip().endswith("movementStart();")
    assert (UI / "assets" / "wallpapers" / "immersive-movement.svg").exists()
    assert "'immersive-movement'" in WALLS.split("const BUILTIN_WALLS")[1].split("\n")[0]


# ---------------------------------------------------------------------------
# the third scene: the crew
#
# It is the one scene that draws PEOPLE, which is exactly why it needs pinning:
# a cast is the easiest thing in this product to quietly fake. Every figure has
# to come from the roster the Team app shows, and the empty case has to stay an
# honest empty case rather than a demo crowd.
# ---------------------------------------------------------------------------

CREW = (UI / "src" / "js" / "01d-crew.js").read_text()
# comments stripped, for the assertions that must not match this file's own
# explanation of what it deliberately does not do
CREW_CODE = re.sub(r"/\*.*?\*/", "", re.sub(r"(?m)^\s*//.*$", "", CREW), flags=re.S)


def test_the_cast_is_the_real_roster_and_nothing_else():
    """One figure per subagent this machine has. Invented colleagues would be the
    dead control this project's honesty rules forbid, wearing a friendlier face."""
    assert "fetch('/api/subagents')" in CREW, "the cast must come from the roster route"
    assert "60000" in CREW, "the roster is read once a minute, never per frame"
    # nothing seeds, pads or invents a figure
    assert not re.search(r"cast\s*=\s*\[\s*\{", CREW), "no hardcoded cast"
    assert "No specialists yet" in CREW, "a machine with none must say so"


def test_a_figure_moves_only_because_something_happened():
    """Every gesture maps to a real event off the same stream the dial reads."""
    assert "function crewPulse(" in CREW
    for kind in ("'turn'", "'turnend'", "'tool'", "'flow'", "'done'"):
        assert kind in CREW, f"the scene ignores {kind}"
    assert "RUNNING" in CREW, "the agent wakes because a turn is running"
    # one seam: the websocket still calls movementPulse, which forwards
    assert "crewPulse(kind,label,ev)" in (UI / "src" / "js" / "01c-movement.js").read_text()


def test_an_unmatched_event_lights_nobody():
    """A flow event names a flow, an agent or an event, and only sometimes a cast
    member. Lighting a figure anyway would make the scene look busy while telling
    the person something untrue about who is working."""
    assert "function crewMatch(" in CREW
    assert "return null" in CREW.split("function crewMatch(")[1][:700]


def test_the_crew_costs_what_the_dial_costs():
    """Same loop, same gates. A scene that draws while nobody can see it is the
    one way a wallpaper becomes a battery complaint."""
    assert "function crewCovered(" in CREW
    assert "document.hidden" in CREW and "has-fullwin" in CREW and "w.max&&!w.min" in CREW
    assert "0.048" in CREW and "0.083" in CREW, "the 20/12 fps dt gate"
    assert "requestAnimationFrame" in CREW and "setInterval" not in CREW
    assert "crewReduced()" in CREW and "CREW.static" in CREW, "one still frame under reduced motion"
    # A shadow is a blur by another name, and a canvas filter over a full-screen
    # layer is re-run on every frame the parallax moves it. Matched as the canvas
    # APIs rather than as the words: `.filter(` is an honest array method, and
    # both appear in this file's own comments explaining why they are not used.
    assert "shadowBlur" not in CREW_CODE and "shadowColor" not in CREW_CODE
    assert not re.search(r"\bctx\.filter\b", CREW_CODE)


def test_every_colour_is_mixed_from_the_theme():
    """One file has to hold up on a dark theme and a light one. A literal white
    or black is how a scene ends up unreadable on half of them."""
    assert "dataset.theme==='light'" in CREW
    body = CREW_CODE.split("function crewInk(")[1][:400]
    assert "#" not in body, "colours come from the theme's tokens, not hex literals"


def test_the_scene_is_offered_switched_and_dressed():
    assert "'crew'" in SETTINGS and "Crew" in SETTINGS, "not offered in Settings"
    assert "specialists you actually have" in SETTINGS, \
        "the row must say the cast is real, or people will expect one"
    assert "imm-crew" in CODE, "no body class, so the plate is never dressed for it"
    assert "immersive-crew" in JS, "the scene has no wallpaper of its own"
    assert (UI / "assets" / "wallpapers" / "immersive-crew.svg").exists()
    assert "'immersive-crew'" in WALLS.split("const BUILTIN_WALLS")[1].split("\n")[0]
    # an unknown scene name out of localStorage must not break the desktop
    assert "IMMERSIVE_SCENES" in JS and "indexOf(scene)<0?'aurora'" in JS


def test_the_crew_file_keeps_the_bundle_rules():
    """One concatenated script: a top-level let/const is in the temporal dead zone
    for anything earlier in filename order that calls into this file."""
    for line in CREW.splitlines():
        assert not line.startswith(("let ", "const ")), line
    assert CREW.rstrip().endswith("crewStart();"), "01d must start itself at first paint"
    assert "var CREW=" in CREW




def test_each_specialist_gets_a_colour_and_two_never_share_one():
    """A hash alone collides about as often as birthdays do: with four figures on
    stage, two came out the same green. Two specialists in one colour is the exact
    opposite of what a colour per specialist is for."""
    assert "var CREW_HUES=[" in CREW, "no palette"
    draw = CREW_CODE.split("function crewDraw(")[1]
    assert "used[" in draw and "hueOf" in draw, "hues are not de-duplicated across the row"
    assert "AGENT_IX" in draw, "the agent's hue must be reserved, not raced for"
    # a curated set, not a free hash — a random hue lands on bile green often enough
    hues = CREW.split("var CREW_HUES=[")[1].split("]")[0]
    assert len([h for h in hues.split(",") if h.strip()]) >= 6



def _figure():
    return CREW_CODE.split("function crewFigure(")[1].split("\nfunction ")[0]


# ---------------------------------------------------------------------------
# the crew are PEOPLE, drawn as pixel art
#
# It took four passes to get here, and each one taught a rule that is pinned
# below. Wire outlines in one colour with a dot for a face read as SCARY. Filled
# vector blobs read as an infographic. Outlined vector cartoons read as mascots
# — one colour head to toe, a ball for a head. What reads as a person at forty
# pixels is a person's PARTS: skin that is a skin colour, hair that is its own
# shape, a shirt, trousers, shoes. So each figure is a small pixel-art sprite
# built from a recipe, painted once and blitted at a whole-number scale.
# ---------------------------------------------------------------------------

def _paint():
    return CREW_CODE.split("function crewPaint(")[1].split("\nfunction ")[0]


def _figure():
    return CREW_CODE.split("function crewFigure(")[1].split("\nfunction ")[0]


def test_a_figure_is_a_recipe_of_a_person_s_parts():
    """Eight figures have to be eight different people: skin tone, hair style
    and colour, glasses, trousers — all from the specialist's own seed, so the
    same specialist is the same person on every reload."""
    rec = CREW_CODE.split("function crewRecipe(")[1].split("\nfunction ")[0]
    for part in ("skin", "style", "hair", "pants", "glasses", "shirt"):
        assert part + ":" in rec or part + "," in rec or f"{part}=" in rec, f"no {part} in the recipe"
    assert "crewRand(seed)" in rec, "the recipe must come from the specialist's own seed"
    styles = CREW.split("var CREW_STYLES=[")[1].split("]")[0]
    assert len(styles.split(",")) >= 6, "too few hair styles to tell a row apart"
    skins = CREW.split("var CREW_SKINS=[")[1].split("];")[0]
    assert skins.count("[") >= 5, "people come in more than a couple of skin tones"


def test_the_shirt_is_the_specialists_colour_and_the_theme_s():
    """Skin and hair are properties of PEOPLE, not of a theme — the one declared
    exception to this look's colour rule — so what carries the specialist's
    colour, at the theme's saturation, is the shirt. A working figure's shirt is
    the more saturated one."""
    rec = CREW_CODE.split("function crewRecipe(")[1].split("\nfunction ")[0]
    assert "shirt:crewRgb(hue" in rec, "the shirt must be the hue the row handed out"
    assert "ink.satLit" in rec and "ink.satDim" in rec
    ink = CREW_CODE.split("function crewInk(")[1][:600]
    lit = int(re.search(r"satLit:\s*light\s*\?\s*(\d+)", ink).group(1))
    dim = int(re.search(r"satDim:\s*light\s*\?\s*(\d+)", ink).group(1))
    assert lit > dim, "working must read as MORE colour, not just paler"
    # the declared exception is written down where the palettes are
    assert "properties of\n   PEOPLE, not of a theme" in CREW or "properties of PEOPLE" in CREW


def test_every_figure_is_outlined_by_one_pass():
    """One pass over the finished figure turns every empty pixel that touches it
    into the line colour — so a new hair style needs no outline of its own and
    cannot forget one. The line is a deep shade of the figure's own hue."""
    paint = _paint()
    assert "alpha[y*W+x-1]" in paint and "alpha[(y-1)*W+x]" in paint, "no outline pass"
    assert "put(x,y,ln)" in paint
    assert "line:crewRgb(hue" in CREW_CODE, "the outline must be the figure's own hue, not one black"


def test_a_face_is_two_eyes_a_mouth_and_nothing_on_it_that_masks_it():
    """Two eyes, never one centred mark — that made the first cut frightening,
    which is why the working light is above the head. The mouth is a LIP colour,
    because darker skin under a nose read as a goatee. And glasses are a rim and
    a pale lens: a full frame in the line colour, beside a one-pixel eye, filled
    the whole eye band and gave a dark-skinned figure no face at all."""
    paint = _paint()
    assert "put(6,7,ln)" in paint and "put(9,7,ln)" in paint, "two eyes, mirrored"
    assert "frame===1" in paint, "no blink frame"
    mouth = CREW.split("const mouth=")[1].split(";")[0]
    assert "*.78" in mouth and "*.42" in mouth, "the mouth must be warmer than the skin, not darker"
    glasses = paint.split("if(rec.glasses){")[1].split("}")[0]
    assert "lens" in glasses, "glasses need a pale lens"
    assert "box(x0,9,x1,9,ln)" not in glasses, "a full frame masks the face at this size"
    fig = _figure()
    assert "fillRect(cxd-Math.round(q/2),dy-q-u" in fig, "the working light must sit ABOVE the head"


def test_limbs_end_in_hands_and_shoes():
    """A limb that stops in mid-air reads as unfinished, in pixels as in vector."""
    paint = _paint()
    assert "box(x0,17,x0+1,17,sk)" in paint and "box(x0,8,x0+1,8,sk)" in paint, "no hands"
    assert "box(4,23,7,24,ln)" in paint and "box(8,23,11,24,ln)" in paint, "no shoes"


def test_it_is_pixel_art_so_it_stays_crisp():
    """A whole number of device pixels per sprite pixel, with smoothing off —
    otherwise a forty-pixel figure is a blur. And it moves in whole pixels, the
    way pixel art does, rather than sliding between them."""
    fig = _figure()
    assert "Math.round(s*dpr/" in fig, "the scale must be an integer"
    assert "imageSmoothingEnabled=false" in fig
    assert "setTransform(1,0,0,1,0,0)" in fig, "blit in device pixels, or the integer is lost"
    assert "Math.round(Math.abs(Math.sin" in fig, "the hop must be in whole pixels"


def test_each_frame_is_painted_once_and_the_cache_is_bounded():
    """A figure on screen is one drawImage. The cache key carries everything that
    changes the pixels — the theme's lightness included — and it is bounded and
    dropped when the scene stops, so a roster that churns does not keep every
    person it ever drew."""
    spr = CREW_CODE.split("function crewSprite(")[1].split("\nfunction ")[0]
    for part in ("seed", "hue", "lit", "ink.light", "frame"):
        assert part in spr.split("const key=")[1].split(";")[0], f"{part} missing from the cache key"
    assert "CREW_SPRITE_N>" in spr, "the cache has no ceiling"
    stop = CREW_CODE.split("function crewStop(")[1].split("\nfunction ")[0]
    assert "CREW_SPRITES={}" in stop, "switching the scene off must let the people go"
    assert _figure().count("drawImage(") == 1


def test_nobody_is_ever_completely_still_except_when_asked():
    """A motionless row is a waxwork: an idle figure breathes a pixel on its own
    phase and blinks, a working one hops and waves one arm then the other. Under
    reduced motion it stands still in its first frame."""
    fig = _figure()
    assert "breath" in fig and "blinking" in fig and "hop" in fig
    assert "still=C.static" in fig and "still?0:" in fig
    paint = _paint()
    assert "frame===2" in paint and "frame===3" in paint, "working has two frames, one arm then the other"


def test_the_shadow_follows_the_step_and_stays_down_through_the_hop():
    """A flat ellipse, never a canvas shadow (a blur under the parallax). At the
    feet after the step — a figure that walks up the stage and leaves its shadow
    on the front line hangs like a puppet — and not lifted by the hop, which is
    the only thing that tells a jump from a float."""
    fig = _figure()
    assert "ctx.ellipse(x,y+1" in fig
    assert "shadowBlur" not in fig
