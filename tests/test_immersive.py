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


def _figure():
    return CREW_CODE.split("function crewFigure(")[1].split("\nfunction ")[0]


# ---------------------------------------------------------------------------
# the crew are the SAME people as everywhere else
#
# Four passes of drawing taught the rules for a person at forty pixels (two
# eyes, a lip-coloured mouth, glasses that do not mask, hands and shoes, one
# outline pass, a colour per specialist). Those rules now live with the one
# painter, in agentos/avatars.py, and are pinned in tests/test_avatars.py. What
# is pinned HERE is that this scene has no painter of its own — a second one
# would be a second definition of a face — and the rules about MOVEMENT.
# ---------------------------------------------------------------------------

def test_the_stage_draws_the_server_s_characters_not_its_own():
    """The researcher on the stage and the researcher in Chat must be one person.
    That is only true while there is one painter, so this file must not grow one
    back — and the colour it tints a name with is the character's stored hue."""
    for gone in ("function crewPaint(", "function crewRecipe(", "CREW_SKINS", "CREW_HUES",
                 "new ImageData("):
        assert gone not in CREW_CODE, f"{gone}: the scene is painting people again"
    sheet = CREW_CODE.split("function crewSheet(")[1].split("\nfunction ")[0]
    assert "avatarSrc(key,{sheet:1})" in sheet, "the sheet must be the server's PNG"
    assert "e.v!==v" in sheet, "an edited character must fetch its new sheet"
    hue = CREW_CODE.split("function crewHueOf(")[1].split("\nfunction ")[0]
    assert "a.recipe.hue" in hue, "the colour is the character's own, not the scene's"
    assert "'@agent'" in _figure() or "'@agent'" in CREW_CODE.split("function crewDraw(")[1]
    # an edit anywhere reaches the stage
    assert "function crewAvatarsChanged(" in CREW
    assert "crewAvatarsChanged()" in (UI / "src" / "js" / "00e-avatars.js").read_text()


def test_a_sheet_frame_is_blitted_crisp_at_a_whole_number():
    """One drawImage per figure from a sub-rect of the sheet, at an integer number
    of device pixels per sprite pixel with smoothing off — otherwise pixel art is
    a blur. A sheet that has not arrived draws nothing, never a stand-in."""
    fig = _figure()
    assert "Math.round(s*dpr/" in fig, "the scale must be an integer"
    assert "imageSmoothingEnabled=false" in fig
    assert "setTransform(1,0,0,1,0,0)" in fig, "blit in device pixels, or the integer is lost"
    assert "frame*CREW_SPR_W,0,CREW_SPR_W,CREW_SPR_H" in fig, "a frame is a sub-rect of the sheet"
    assert "if(sheet)" in fig
    assert fig.count("drawImage(") == 1
    stop = CREW_CODE.split("function crewStop(")[1].split("\nfunction ")[0]
    assert "CREW_SHEETS={}" in stop, "switching the scene off must let the people go"
    assert "fillRect(cxd-Math.round(q/2),dy-q-u" in fig, "the working light sits ABOVE the head"


def test_nobody_is_ever_completely_still_except_when_asked():
    """A motionless row is a waxwork: an idle figure breathes a pixel on its own
    phase and blinks, a working one hops and waves one arm then the other, a new
    arrival swings its arms as it walks. Under reduced motion: the first frame."""
    fig = _figure()
    assert "breath" in fig and "blinking" in fig and "hop" in fig and "walking" in fig
    assert "still=C.static" in fig and "still?0:" in fig
    assert "Math.round(Math.abs(Math.sin" in fig, "the hop must be in whole pixels"


def test_the_shadow_follows_the_step_and_stays_down_through_the_hop():
    """A flat ellipse, never a canvas shadow (a blur under the parallax). At the
    feet after the step, and not lifted by the hop — the only thing that tells a
    jump from a float."""
    fig = _figure()
    assert "ctx.ellipse(x,y+1" in fig
    assert "shadowBlur" not in fig


def test_a_newcomer_walks_on_and_nobody_else_moves():
    """A specialist made while the stage is on walks in and says hello. Nobody
    walks in on a page load (every reload would be a parade), and the people
    already there keep their places: sorted afresh, a new name early in the
    alphabet slid the whole row sideways the moment it arrived."""
    roster = CREW_CODE.split("async function crewRoster(")[1].split("\nfunction ")[0]
    assert "if(CREW.known)" in roster, "the first roster must not be an arrival"
    assert "CREW.arrive[c.name]=now" in roster and "crewSay(c.name," in roster
    assert "was.indexOf(n)" in roster and ".sort(" in roster, "places must be kept"
    assert roster.index(".sort(") < roster.index(".slice(0,CREW_MAX)"), \
        "cap AFTER ordering, or a newcomer can push an old hand off the stage"
    assert "CREW_WALK_MS" in CREW_CODE.split("function crewDraw(")[1]


def test_a_bubble_says_only_what_happened():
    """Three things are said on the stage: hello on arrival, done when work
    finished, and a huddle's turn in the speaker's own words. All three are events;
    none is chatter on a timer."""
    assert "crewSay(who,'done" in CREW_CODE
    assert "crewSay(c.name,'hello!')" in CREW_CODE
    assert "crewSay(w,String((ev&&ev.text)||''),true)" in CREW_CODE
    assert CREW_CODE.count("crewSay(") == 4, "one definition, three sayings — nothing else talks"
    step = CREW_CODE.split("function crewStep(")[1].split("\nfunction ")[0]
    assert "CREW_SAY_MS" in step, "a bubble must go away"

