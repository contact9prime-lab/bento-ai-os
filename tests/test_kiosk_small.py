"""The kiosk on a Pi's own small screen (24h-kiosk.js, 27-kiosk.css, 24d-office.js).

Asked for as "the screen should be responsive on the pi so I can see it on the small screen with
text". Photographed at 480x320, 800x480, 1024x600 and 480x800 (docs/small-screens.md). What it
found, pinned here: the phone rule hid the Office on a 480-wide kiosk; the band spilled its text
out of the card; a long answer was cut; the rooms stacked into a narrow column."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
CSS = ROOT / "agentos/ui/src/css"
JS = ROOT / "agentos/ui/src/js"


def test_a_small_kiosk_still_draws_the_office():
    imm = (CSS / "20-immersive.css").read_text()
    assert "body.immersive.dev-mobile:not(.kiosk) #office-scene:not(.hq){display:none}" in imm
    assert "body.immersive.dev-mobile #office-scene:not(.hq){display:none}" not in imm


def test_the_band_is_compact_and_its_text_ends_inside_it_on_short_screens():
    css = (CSS / "27-kiosk.css").read_text()
    short = css[css.index("@media (max-height:520px)"):]
    assert "-webkit-line-clamp:2" in short and "#kiosk-hud .kh-face{width:40px" in short
    tiny = css[css.index("@media (max-height:360px)"):]
    assert ".kh-reply{max-height:40vh}" in tiny and "-webkit-line-clamp:1" in tiny
    js = (JS / "24h-kiosk.js").read_text()
    assert "r.scrollTop=r.scrollHeight" in js, "the newest words of an answer stay in view"


def test_a_narrow_kiosk_keeps_its_rooms_side_by_side():
    assert "Math.max(cw<720?.5:.9," in (JS / "24d-office.js").read_text()


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_can_not_hear_line_is_one_short_sentence_on_the_screen():
    src = (JS / "24h-kiosk.js").read_text()
    fn = re.search(r"function kioskShort\(t\)\{.*?\n", src).group(0)
    long = ("Nothing here can understand speech yet: whisper.cpp is not installed, and no voice service is "
            "set up. Install whisper.cpp, or add an ElevenLabs, OpenAI or Google Cloud key under Voice.")
    out = subprocess.run(["node", "-e", fn + f"console.log(kioskShort({long!r}))"], capture_output=True, text=True)
    assert out.stdout.strip() == "Nothing here can understand speech yet."


def test_the_kiosk_can_be_typed_to_and_answers_in_its_band():
    """'the kiosk mode should be the light mode with a keyboard option': with nothing that hears,
    the box is simply there; the answer stays in the band and the replied pill is not shown."""
    js = (JS / "24h-kiosk.js").read_text()
    assert '<form class="kh-type"' in js and "kioskAsk(t)" in js
    assert "const typing=KIOSK.typing||!can" in js, "no hearing: typing is the way in"
    assert "!hear.engine?(KIOSK.reply?'Type again below.'" in js, "never 'listening' with nothing that hears"
    assert "body.kiosk #aibubble{display:none!important}" in (CSS / "27-kiosk.css").read_text()


def test_a_small_machine_draws_its_own_screen_light():
    """Measured with Chrome drawing in software at 1920x1080: two windows with the glass blur
    took a whole core at rest (100%), without it 0.8%; the kiosk's Office went from 18% to 4%
    once its decor and rest slowed down on a small machine."""
    srv = (ROOT / "agentos/server.py").read_text()
    assert 'state_["small"] = _prof.resolve(state.machine_cfg()) == "lite"' in srv
    glass = (JS / "01a-glass.js").read_text()
    assert "function glassSmall(small)" in glass and "remoteClient()" in glass[glass.index("function glassSmall"):]
    assert "glassSmall(PLATFORM.small)" in (JS / "22-quicksettings.js").read_text()
    office = (JS / "24d-office.js").read_text()
    assert "every=work?(light?1/8:1/30):decor?(light?1/4:1/30):(light?1/2:sea?1/12:1/6)" in office
    # not due: a timer, never a frame asked for on every refresh
    assert "O.raf=-1;O.wait=setTimeout(" in office and office.count("clearTimeout(OFFICE.wait)") == 3


def test_the_platform_route_says_whether_the_machine_is_small(tmp_path, monkeypatch):
    from agentos import profile
    assert profile.resolve({"profile": "lite"}) == "lite"
    assert profile.resolve({"profile": "full"}) == "full"
