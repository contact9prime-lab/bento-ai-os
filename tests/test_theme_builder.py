"""The modern default look (Nova) and the Theme Builder.

What these defend:

- Nova is the look a browser that never chose gets, and it ships its own wallpaper
  (gradients only: no blur filter, so a Pi rasterises it in one pass);
- the accent fill and the text on it are TOKENS (--acc-grad, --on-acc), so a violet
  accent gets white text instead of the dark ink written for teal;
- every Builder control writes a token the whole desktop already reads (corners,
  depth, glass, text size, accent), and the AI designer is told the same names;
- a palette generated from three colours is readable in both modes — and the Builder
  says the contrast out loud rather than letting somebody save one nobody can read;
- a live preview never starts the theme crossfade (a snapshot per slider step painted
  the previous screen over every window).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
CSS = ROOT / "agentos/ui/src/css"


def test_nova_is_the_default_and_ships_its_wallpaper():
    th = (JS / "02-themes-shells.js").read_text()
    assert "nova:{label:'Nova (modern)'" in th and "wall_img:'nova'" in th
    assert "||'nova';" in th, "a browser that never chose gets Nova"
    svg = (ROOT / "agentos/ui/assets/wallpapers/nova.svg").read_text()
    assert "<filter" not in svg and "Gradient" in svg
    assert "'nova'" in (JS / "08-wallpaper-jarvis-voice.js").read_text().split("const BUILTIN_WALLS")[1].split("\n")[0]


def test_the_accent_fill_and_its_text_are_tokens():
    base = (CSS / "00-tokens-base.css").read_text()
    assert "--acc-grad:" in base and "--on-acc:" in base
    for f in CSS.glob("*.css"):
        s = f.read_text()
        if f.name != "00-tokens-base.css":      # where the token itself is defined
            assert "linear-gradient(135deg,var(--acc),var(--acc2))" not in s, f"{f.name}: use var(--acc-grad)"
        for ln in s.splitlines():
            if "#04211c" in ln and "color:" in ln and "var(--ok)" not in ln and "--on-acc:" not in ln:
                pytest.fail(f"{f.name}: text on the accent must be var(--on-acc): {ln.strip()[:90]}")


def test_every_builder_control_writes_a_token_and_the_ai_is_told_the_same_names():
    b = (JS / "18-themes-personalize.js").read_text()
    for tok in ("'r-md'", "'el-3'", "'glass-blur'", "'glass-tint'", "'fs-base'", "'acc-grad'", "'on-acc'", "wall_img"):
        assert tok in b, tok
    assert "const preview=()=>{_applyThemeObj(WB);tbCheck()}" in b, "no crossfade per slider step"
    assert "tbCheck" in b and "4.5" in b, "the contrast is said out loud"
    tools = (ROOT / "agentos/tools.py").read_text()
    assert "acc-grad" in tools and "on-acc" in tools and "r-sm/r-md/r-lg/r-xl" in tools


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the page's own palette code")
def test_a_generated_palette_is_readable_in_both_modes():
    src = (JS / "18-themes-personalize.js").read_text()
    start = src.index("function tbHex(")
    end = src.index("function themeBuilder(")
    code = src[start:end] + """
const out=[];
for (const mode of ['dark','light']) for (const [tint,acc,acc2] of [['#1b2a24','#10b981','#a3e635'],['#222244','#7c6cff','#c084fc'],['#302018','#f97316','#facc15'],['#eeeeee','#2563eb','#06b6d4']]){
  const v=tbPalette(tint,mode,acc,acc2);
  out.push({mode,acc,txt:tbContrast(v.txt,v.bg2),dim:tbContrast(v.dim,v.bg2),onacc:tbContrast(v['on-acc'],v.acc)});
}
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    for row in json.loads(r.stdout):
        assert row["txt"] >= 7, row
        assert row["dim"] >= 4.5, row
        assert row["onacc"] >= 3, row       # the accent's own button text: large, bold
