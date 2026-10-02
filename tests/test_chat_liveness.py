"""A chat turn shows while it runs, not only when its answer arrives.

Claude Code sends its whole answer at the end: measured, 50 seconds of nothing between
`turn_start` and the first `text_delta`. Three things read as broken in that silence:
the Office's desk went dark after OF_WORK_MS, the reply had no name or face until the
text came, and the presence bubble sat over the Chat composer repeating the working row.
"""
from pathlib import Path

JS = Path(__file__).parent.parent / "agentos/ui/src/js"
CSS = Path(__file__).parent.parent / "agentos/ui/src/css"


def _js(n):
    return (JS / n).read_text()


def test_the_office_keeps_a_running_chat_at_work():
    of = _js("24d-office.js")
    assert "function officeLive(p)" in of
    assert "p.busy&&now-p.busy>OF_WORK_MS&&!p.hand&&!officeLive(p)" in of
    assert "officeSay(who,'…','think',600000)" in of, "a thinking balloon while the turn is open"
    assert "if(who.say&&who.say.kind==='think')who.say=null" in of, "and it goes at turn_end"


def test_the_reply_has_a_name_and_face_from_the_first_second():
    ws = _js("09-websocket.js")
    start = ws[ws.index("case 'turn_start':"):]
    start = start[:start.index("break;}")]
    assert "startAssistant();WORK_T0=t0;showWorking()" in start
    info = ws[ws.index("case 'engine_info':"):]
    info = info[:info.index("break;}")]
    assert "curBody.parentNode.querySelector('.who')" in info, "relabel the reply being written"


def test_small_feeds_say_who_answers():
    co = _js("04a-copilot.js")
    assert "function mfWho(speaker)" in co
    assert "mfWho(((m.meta||{}).speaker)||'')" in co, "history replay carries the face too"
    assert ".mf-who{" in (CSS / "14-omnibar.css").read_text()


def test_the_bubble_is_for_turns_you_cannot_see():
    ws = _js("09-websocket.js")
    assert "function turnOnScreen(cid)" in ws
    assert "!turnOnScreen(c)&&!AIB.snooze.has(c)" in ws
    assert 'class="ab-x"' in ws, "the bubble can be hidden until the next turn"
    css = (CSS / "14-omnibar.css").read_text()
    assert "text-overflow:ellipsis" in css[css.index("#aibubble .ab-t"):][:200]


def test_no_rings_on_the_desktop_during_a_chat():
    """The Aura theme's thinking rings came up mid-wallpaper on every turn, in every
    look ("like a clock"); they belong to that one theme."""
    j = _js("08-wallpaper-jarvis-voice.js")
    on = j[j.index("function jarvisOn("):][:600]
    assert "EXPERIENCE!=='jarvis')return" in on


def test_the_prompt_bar_stays_down_for_a_turn_shown_in_a_window():
    om = _js("28a-omnibar.js")
    pres = om[om.index("function omniPresence("):][:900]
    assert "turnInWindow(c)" in pres
