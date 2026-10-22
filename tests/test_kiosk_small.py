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
