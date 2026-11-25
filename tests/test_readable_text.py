"""Secondary text reads on every theme.

Reported as "the dark font behind the dark is just so silly, how can I read it". Measured on the
owner's screen: --dim2 (a schedule's details, hint lines, section labels) was 3.0:1 on its panel,
and the menu bar's ADMIN read at 1.3:1. `themeReadable` (02-themes-shells.js) lifts --dim and
--dim2 to 4.5:1 against bg, bg2 and bg3 wherever a theme is applied, custom ones included.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
JS = (ROOT / "agentos/ui/src/js/02-themes-shells.js").read_text()
CSS = (ROOT / "agentos/ui/src/css/04-menubar.css").read_text()


def _node(script: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_every_built_in_theme_reads_at_four_and_a_half_to_one():
    themes = JS[:JS.index("\n};\n") + 4]
    helpers = JS[JS.index("var READ_FLOOR"):JS.index("function themeReadable")]
    out = _node(themes + helpers + """
const res={};
for(const [id,t] of Object.entries(THEMES)){
  const v=t.v||{}, txt=_rgbOf(v.txt), bgs=['bg','bg2','bg3'].map(k=>_rgbOf(v[k])).filter(Boolean);
  if(!txt||!bgs.length) continue;
  for(const k of READ_KEYS){ const fg=_rgbOf(v[k]); if(!fg) continue;
    const c=_rgbOf(readableTone(fg,txt,bgs)||v[k]);
    res[id+'.'+k]=Math.min(...bgs.map(b=>_contrast(c,b))); }
}
console.log(JSON.stringify(res));""")
    assert len(out) >= 20
    low = {k: round(v, 2) for k, v in out.items() if v < 4.5}
    assert not low, low


def test_a_theme_that_already_reads_is_left_alone_and_the_tint_is_kept():
    helpers = JS[JS.index("var READ_FLOOR"):JS.index("function themeReadable")]
    out = _node(helpers + """
const fine=readableTone(_rgbOf('#b3bbc4'),_rgbOf('#eef1f4'),[_rgbOf('#16191d')]);
const lifted=readableTone(_rgbOf('#5c6577'),_rgbOf('#e6ebf2'),[_rgbOf('#111419'),_rgbOf('#171b22')]);
const light=readableTone(_rgbOf('#8f8b87'),_rgbOf('#1d1b19'),[_rgbOf('#faf9f8'),_rgbOf('#ecebe9')]);
console.log(JSON.stringify({fine, lifted, light,
  lc:Math.min(_contrast(_rgbOf(lifted),_rgbOf('#111419')),_contrast(_rgbOf(lifted),_rgbOf('#171b22'))),
  dc:_contrast(_rgbOf(light),_rgbOf('#ecebe9'))}));""")
    assert out["fine"] is None
    assert out["lifted"] != "#e6ebf2" and out["lc"] >= 4.5, "the smallest step, not the main text colour"
    assert out["dc"] >= 4.5, "a light theme's faint text gets darker"


def test_the_floor_runs_wherever_a_theme_is_applied():
    body = JS[JS.index("function _applyThemeObj"):JS.index("var READ_FLOOR")]
    assert "themeReadable(v);" in body


def test_the_role_on_the_account_chip_is_not_a_dark_pill():
    rule = CSS[CSS.index("#mb-user .badge{"):]
    rule = rule[:rule.index("}")]
    assert "background:none" in rule and "color:inherit" in rule
