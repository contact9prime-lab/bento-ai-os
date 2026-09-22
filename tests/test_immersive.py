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


# ---------------------------------------------------------------------------
# the crew has to read as PEOPLE
#
# The first cut drew outlined wire bodies, identical in one brass colour, frozen
# at rest, with a single red dot in the middle of each face. The report on it was
# one word: scary. Each assertion below is one of the four things that fixed it,
# and each is easy to undo by accident while "simplifying" the drawing.
# ---------------------------------------------------------------------------

def test_a_face_has_two_eyes_and_no_mark_in_the_middle_of_it():
    """A single centred mark is a cyclops, not a face — it is what made a row of
    these read as something to be afraid of. The running indicator lives above
    the head, and the mouth survives a blink."""
    fig = CREW_CODE.split("function crewFigure(")[1].split("\nfunction ")[0]
    assert "[-1,1].forEach" in fig, "eyes must be drawn as a symmetric pair"
    assert "headR*.36" in fig, "the eyes are offset either side of centre"
    assert "blinking" in fig, "a face that never blinks is a mask"
    # the status light is ABOVE the head, never on it
    assert "headY-headR*1.32" in fig
    # and the mouth is not tied to the blink
    assert "if(!blinking){" not in fig, "a blink must not take the mouth with it"


def test_figures_are_filled_and_stand_on_something():
    """An outline is a ghost; a filled shape has weight. The contact ellipse is a
    flat fill, NOT a canvas shadow — this layer is re-composited under the parallax
    and a shadow is a blur by another name."""
    fig = CREW_CODE.split("function crewFigure(")[1].split("\nfunction ")[0]
    assert fig.count("ctx.fill()") >= 4, "body, head and eyes are filled"
    assert "ctx.ellipse(cx,ground+1" in fig, "no ground contact — they float"
    assert "shadowBlur" not in fig


def test_nobody_is_ever_completely_still():
    """A row of motionless figures staring out of a dark room is a waxwork. Three
    sines cost nothing and turn the same drawing into somebody waiting."""
    fig = CREW_CODE.split("function crewFigure(")[1].split("\nfunction ")[0]
    for name in ("breath", "sway", "bob"):
        assert name in fig, f"no {name} — the figures are frozen at rest"
    assert "CREW.t" in fig, "the life has to come from the scene clock"
    # ...except where the person asked for that
    assert "still=CREW.static" in fig and "still?0:" in fig, \
        "reduced motion must still hold them still"


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


def test_working_reads_as_more_colour_not_more_white():
    """Raising lightness alone took every figure towards beige, so a stage with
    three of them busy read as one washed pastel repeated."""
    ink = CREW_CODE.split("function crewInk(")[1][:600]
    assert "satLit" in ink and "satDim" in ink, "saturation must change with state"
    lit = int(re.search(r"satLit:\s*light\s*\?\s*(\d+)", ink).group(1))
    dim = int(re.search(r"satDim:\s*light\s*\?\s*(\d+)", ink).group(1))
    assert lit > dim, "a working figure must be MORE saturated, not just paler"
