"""Toasts and the two tray panels.

What these defend:

- a toast says what KIND of news it is, read from the sentence, so the hundreds of
  existing call sites got an icon without being edited — and a caller can still say;
- every toast can be dismissed, shows how long it has left, holds while hovered, and a
  failure stays longer than a success because it is the one somebody has to read;
- the stack stays on screen: `#toasts .toast` resets the base rule's `right:14px`
  (`inset:auto`), which otherwise shifted every card off the edge of a phone;
- the notification centre says "all caught up" rather than showing nothing, and its ✕
  is reachable without a hover on a touch screen;
- every control-centre tile has an icon, and a tile whose control is missing here says so
  instead of standing empty.
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


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the page's own toastKind")
def test_a_toast_kind_is_read_from_the_sentence():
    src = (JS / "00-core.js").read_text()
    code = src[src.index("var TOAST_IC="):src.index("function toast(")] + """
const cases=[
 ['saved My Theme','ok'],['✓ copied','ok'],['analyst now works with "reports"','ok'],
 ['could not reach office','err'],['✗ nope','err'],['Failed to save','err'],['refused by the gate','err'],
 ['glass effects turned down to keep the desktop smooth','warn'],['⚠ careful','warn'],
 ['not connected to the server','err'],['no such automation','err'],['moved to Desktop 2','ok'],
 ['nothing selected','info'],['home asked to link','info'],['',''+'info'],[null,'info'],
];
console.log(JSON.stringify(cases.map(([t,k])=>[t,k,toastKind(t)]).concat([['forced','warn',toastKind('saved',{kind:'warn'})]])));
"""
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    for text, want, got in json.loads(r.stdout):
        assert got == want, (text, want, got)


def test_every_toast_can_be_dismissed_timed_and_held():
    src = (JS / "00-core.js").read_text()
    body = src[src.index("function toast("):src.index("const fmtBytes")]
    assert "toast-x" in body and "aria-label','Dismiss'" in body
    assert "toast-bar" in body and "--toast-ms" in body
    assert "kind==='err'?7000:3800" in body, "a failure stays longer than a success"
    assert "onmouseenter" in body and "clearTimeout(h)" in body, "hovering holds it"
    assert "role','alert'" in body and "aria-live" in body
    assert "box.children.length>5" in body, "the stack never grows unbounded"
    motion = (CSS / "13-motion.css").read_text()
    rule = re.search(r"#toasts \.toast\{[^}]*\}", motion).group(0)
    assert "inset:auto" in rule, "the base .toast's right:14px must not offset a stacked card"
    assert "animation-play-state:paused" in motion and "@keyframes toastbar" in motion
    assert re.search(r"body\.dev-touch[^{]*\.toast-x", motion), "the ✕ meets the tap floor"


def test_immersive_toasts_are_scoped_and_use_the_theme():
    imm = (CSS / "20-immersive.css").read_text()
    for ln in imm.splitlines():
        if ".toast" in ln and "{" in ln:
            assert ln.lstrip().startswith("body.immersive"), ln[:90]
    assert ".toast.k-info .toast-ic{background:var(--acc-grad)}" in imm


def test_the_notification_centre_is_never_blank():
    js = (JS / "24-notifications.js").read_text()
    assert 'class="np-empty"' in js and "all caught up" in js
    imm = (CSS / "20-immersive.css").read_text()
    assert "body.immersive.dev-touch .np-item .np-x" in imm, "no hover on a touch screen"


def test_every_control_centre_tile_has_an_icon_and_none_stands_empty():
    js = (JS / "22-quicksettings.js").read_text()
    tiles = re.findall(r'<div class="provbox cc-tile[^"]*"><div class="ptitle">(.{0,60})', js)
    assert len(tiles) == 5 and all('class="cc-ic"' in t for t in tiles), tiles
    assert "cc-wide" in js
    assert "ccNote('brightness.set')||" in js, "the brightness tile says why it is empty"
