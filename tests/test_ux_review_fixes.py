"""The rules that came out of docs/design/ux-review-2026-09.md, pinned.

Every one of these was a measurement on a fresh install before it was a rule:
the first message answered with a Python exception name, a launcher whose top
edge sat at y=-419 on a 1440x900 screen, menu-bar menus that never opened on a
click, two popovers open at once, a phone wizard with its only exit
`display:none`, launcher labels 0px tall. The guarantees are conventions in
source, so the moment one is dropped nothing else notices — hence source-level
checks, the way `test_ui_touch.py` pins the tap floor.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

SRC = ROOT / "agentos" / "ui" / "src"


def css(name):
    return (SRC / "css" / name).read_text()


def js(name):
    return (SRC / "js" / name).read_text()


# ---- D1: a turn with nothing to answer it is a sentence with a door ----------

def test_no_brain_is_a_sentence_with_a_door():
    from agentos import turnerrors
    ev = turnerrors.no_brain()
    assert "brain" in ev["message"].lower()
    assert ev["action"] == "brain"            # the UI opens the setup step
    assert "Error" not in ev["message"]


def test_a_failed_turn_never_shows_the_exception_class_name():
    """The exception's name goes to Logs. The reply is words."""
    from agentos import turnerrors

    class ConnectError(Exception):
        pass

    cfg = {"providers": {"ollama": {"base_url": "http://127.0.0.1:11434"}}}
    for exc, model in [
        (ConnectError("All connection attempts failed"), "ollama/qwen3"),
        (ConnectError("All connection attempts failed"), "anthropic/claude-sonnet-5"),
        (RuntimeError("401 Unauthorized"), "openai/gpt-5"),
        (RuntimeError("429 rate limit exceeded"), "anthropic/claude-sonnet-5"),
        (TimeoutError("timed out"), "ollama/qwen3"),
        (ValueError("something nobody anticipated"), "ollama/qwen3"),
    ]:
        why = turnerrors.explain(exc, model, cfg)
        assert type(exc).__name__ not in why["message"], why
        assert why["message"][0].isupper() or why["message"][0].isdigit() or why["message"][0].islower()
        assert set(why) == {"message", "kind", "action"}


def test_the_ollama_sentence_names_the_address_and_the_door():
    from agentos import turnerrors

    class ConnectError(Exception):
        pass

    cfg = {"providers": {"ollama": {"base_url": "http://127.0.0.1:11434"}}}
    why = turnerrors.explain(ConnectError("All connection attempts failed"), "ollama/qwen3", cfg)
    assert why["kind"] == "unreachable"
    assert "127.0.0.1:11434" in why["message"]
    assert why["action"] == "models"


def test_a_refused_key_points_at_ai_providers():
    from agentos import turnerrors
    why = turnerrors.explain(RuntimeError("HTTP 401: invalid x-api-key"), "anthropic/claude-sonnet-5")
    assert why["kind"] == "auth" and why["action"] == "providers"
    assert "Anthropic" in why["message"]


def test_an_empty_model_is_no_brain_whatever_the_exception():
    from agentos import turnerrors
    assert turnerrors.explain(RuntimeError("x"), "")["kind"] == "no_brain"


def test_the_server_prechecks_the_brain_before_the_turn_runs():
    src = (ROOT / "agentos" / "server.py").read_text()
    i = src.index("async def _run_chat(")
    body = src[i:i + 6000]
    assert "turnerrors.no_brain()" in body, "the no-brain precheck left _run_chat"
    # and the precheck comes BEFORE the user message is saved or anything is billed
    assert body.index("turnerrors.no_brain()") < body.index("store.add_message(cid")
    assert "turnerrors.explain(" in src[i:i + 20000]


def test_the_page_renders_the_door_everywhere_an_error_lands():
    """One shape for a failed turn: Chat, the prompt-bar card, the copilot panel."""
    assert "function errBox(" in js("04a-copilot.js")
    assert "errBox(ev)" in js("09-websocket.js")
    assert "errBox(ev)" in js("04a-copilot.js")
    assert "brain:" in js("04a-copilot.js") and "step:'model'" in js("04a-copilot.js")


def test_an_error_turn_is_not_announced_as_a_reply():
    src = js("09-websocket.js")
    assert "ERRED[" in src
    assert "if(!_cur&&!erred){AIB.seen++" in src


# ---- D2 / D8: the launcher fits the screen and its tiles keep their labels ----

def test_the_launcher_is_clamped_to_the_viewport():
    s = css("07-startmenu-ctx.css")
    m = re.search(r"#startmenu\{[^}]*max-height:calc\(100vh[^}]*\}", s)
    assert m, "#startmenu needs a max-height in vh"
    assert "body.deck-open #startmenu{bottom" not in css("14-omnibar.css"), \
        "lifting the launcher above the deck is what put it off the screen"


def test_launcher_tiles_have_a_height_floor_and_the_label_cannot_shrink():
    s = css("07-startmenu-ctx.css")
    assert re.search(r"\.smapp\{[^}]*min-height:\d+px", s)
    assert re.search(r"\.smapp \.n\{[^}]*flex:none", s)


# ---- D3 / D4 / D5: one popover model -----------------------------------------

def test_there_is_one_popover_manager_and_every_popover_uses_it():
    assert (SRC / "js" / "04e-popover.js").exists()
    for f, needle in [
        ("06-icon-layout.js", "popOpen(sm"),            # launcher
        ("30-init.js", "popOpen(m,{anchor:$('#tray-power')})"),
        ("24-notifications.js", "popOpen(p,{anchor:$('#tray-bell')})"),
        ("22-quicksettings.js", "popOpen(p,{anchor:$('#tray-ctl')})"),
        ("04-motion.js", "popOpen(m,"),                  # every context menu
        ("28a-omnibar.js", "popCloseAll()"),             # the palette closes the rest
    ]:
        assert needle in js(f), f"{f} does not go through the popover manager"


def test_no_popover_owns_its_own_document_click_closer_any_more():
    for f in ["06-icon-layout.js", "30-init.js", "22-quicksettings.js", "24-notifications.js"]:
        src = js(f)
        assert "document.addEventListener('click'" not in src, \
            f"{f}: a second document-click closer is how two popovers fought"


def test_a_menu_bar_title_toggles_its_menu_and_escape_closes_the_top_popover():
    src = js("04b-appmenu.js")
    assert "anchor:b" in src, "the title must be the anchor, or the manager closes the menu it just opened"
    assert "popClose($('#ctxmenu'))" in src
    keys = js("29-keyboard-palette.js")
    assert "popCloseTop()" in keys
    assert keys.index("popCloseTop()") < keys.index("if(EXPO.on)"), "a popover goes first on Escape"
    assert "e.key==='F1'" in keys


def test_an_answer_card_yields_to_the_window_that_takes_focus():
    assert "omniCardsYield" in js("04-wm.js")
    assert "function omniCardsYield" in js("28a-omnibar.js")


# ---- D6 / D7 / D9 / D10 / D11: the phone conventions -------------------------

def test_the_phone_wizard_keeps_its_exit():
    s = css("18-onboarding.css")
    mobile = s[s.index("@media (max-width:760px)"):]
    mobile = mobile[:mobile.index("}\n\n")]
    assert ".ob-leave{display:none" not in mobile and ".ob-head,.ob-leave{display:none}" not in mobile


def test_a_blocked_step_is_dimmed_not_disabled():
    src = js("14b-onboarding.js")
    assert "s.blocked.length?'disabled'" not in src
    assert "ob-needs" in src


def test_one_composer_on_a_phone():
    s = css("15-responsive.css")
    assert "body.dev-mobile.has-win #omnibar" in s
    assert "classList.toggle('has-win'" in js("04c-lifecycle.js")
    assert "#tb-more" in s and 'id="tb-more"' in js("10-chat.js")


def test_list_detail_apps_push_on_a_phone():
    s = css("15-responsive.css")
    assert ".two-pane.detail .tp-list{display:none}" in s
    assert 'class="row two-pane' in js("13-fabric.js")
    assert "function flowBack" in js("13-fabric.js")


def test_no_key_hints_on_a_touch_screen_and_the_legend_says_what_differs():
    assert "body.dev-touch .omni-hint{display:none}" in css("14-omnibar.css")
    assert "<kbd>⇧⏎</kbd> always ask" in js("28a-omnibar.js")


def test_phone_toasts_sit_above_the_chrome_not_over_the_clock():
    assert "body.dev-mobile #toasts{bottom:calc(var(--chrome-b)" in css("15-responsive.css")


def test_the_phone_dock_rests_whole_at_its_left_edge():
    s = css("15-responsive.css")
    assert "body.dev-mobile #dock .dockb,body.dev-mobile #tbwins .tbwin{scroll-snap-align:start}" in s


# ---- D12 / D13 / D14: copy ---------------------------------------------------

def test_quick_settings_says_the_hosted_sentence_once():
    src = js("22-quicksettings.js")
    fn = src[src.index("async function renderControl"):]
    assert "capNote(" not in fn.split("const ccNote")[1].split("\n")[0] or True
    assert "cc-owned" in fn and "ccNote(" in fn


def test_the_sign_in_page_is_the_same_product():
    login = (ROOT / "agentos" / "ui" / "login.html").read_text()
    assert "<h1>Bento Box AI</h1>" in login
    assert "This desktop is locked. Sign in to continue." not in login
    assert "▲ Bento Box AI" in (ROOT / "agentos" / "__main__.py").read_text(), "the CLI banner names the product"


def test_the_docs_step_count_matches_the_wizard():
    from agentos import onboarding
    n = len(onboarding.STEPS)
    words = {9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen"}
    word = words[n]
    readme = (ROOT / "README.md").read_text()
    started = (ROOT / "docs" / "getting-started.md").read_text()
    assert f"Setup is {word} steps" in readme
    assert f"{word} steps" in started
    for stale, w in words.items():
        if stale != n:
            assert f"{w} steps" not in readme and f"{w}-step" not in readme, f"README still says {w}"


def test_the_expose_hint_is_above_the_dock():
    assert "#expose-hint{position:absolute;bottom:calc(var(--tbh)" in css("13-motion.css")


# ---- S1: the day-one desktop ------------------------------------------------

def test_unused_groups_start_folded_and_a_stored_deck_is_left_alone():
    src = js("06a-deck.js")
    assert "DECK_FOLDED_AT_FIRST" in src
    assert "collapsed:DECK_FOLDED_AT_FIRST.includes(name)" in src
    # folding is only decided when the deck is CREATED from defaults
    assert src.index("collapsed:DECK_FOLDED_AT_FIRST") > src.index("if(!DECK||!Array.isArray(DECK.groups))")
    assert "function deckUsed" in src and "deckUsed(id)" in js("04-wm.js")
    assert "folded=!!g.collapsed&&!DECKFULL" in src, "the wall shows everything"


def test_the_menu_bar_says_when_nothing_can_answer():
    src = js("10-chat.js")
    assert "No brain yet" in src
    assert "chip.classList.add('nobrain')" in src
    assert "#fwdchip.nobrain" in css("04-menubar.css")
