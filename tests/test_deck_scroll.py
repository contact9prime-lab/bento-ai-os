"""The desktop's scroll gesture is opt-in, and the hot corners open both faces.

Reported as "the scroll is really sensitive to the widgets and apps, it should come from
the hot corners": a trackpad's lightest touch on the desktop added up to the gesture and
flipped the whole screen to All apps or Widgets.
"""
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src" / "js"


def test_the_wheel_on_the_desktop_is_off_unless_switched_on():
    deck = (JS / "06a-deck.js").read_text()
    wheel = deck.split("addEventListener('wheel',e=>{", 1)[1].split("\n},", 1)[0]
    assert "zone==='wall'&&!DECKFULL&&!deckScrollOn()" in wheel
    assert "localStorage.getItem('deck.scroll')==='1'" in deck, "off by default"


def test_the_corners_open_both_faces_and_the_card_has_the_switch():
    hc = (JS / "15b-hotcorners.js").read_text()
    defaults = hc.split("const HC_DEFAULTS=", 1)[1].split(";", 1)[0]
    assert "'deck.all'" in defaults and "'deck.widgets'" in defaults
    assert 'id="hc-scroll"' in hc and "localStorage.setItem('deck.scroll'" in hc
