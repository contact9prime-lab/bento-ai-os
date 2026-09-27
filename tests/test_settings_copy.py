"""Settings says a line or two, and the rest is behind an ⓘ.

Reported as "there is a lot of text in every setting ... you don't need to irritate the
user", and about the voice: no dash-joined clauses, no "not this, not that, just this".
What this pins: the row helper takes a short `desc` and a `more` for the ⓘ, a long
paragraph is split at its first sentence wherever it was written, the tip is placed by
hand inside the screen and opens on hover, focus and tap, and the strings in the panes
stay short and dash-free so the next edit does not grow them back.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos" / "ui" / "src" / "js"
PANES = ["11-settings.js", "11a-whatsapp.js", "11b-openclaw.js", "11c-agentshare.js",
         "11d-accounts.js", "11e-hands.js", "18-themes-personalize.js"]


def _visible(s):
    return re.sub(r"<[^>]*>|\$\{[^}]*\}", "", s)


def test_the_row_takes_a_line_and_a_more():
    st = (JS / "11-settings.js").read_text()
    row = st.split("function pRow(")[1].split("\n}")[0]
    assert "o.more" in row and "pSplit(o.desc)" in row and "pInfo(m)" in row
    # what is behind the ⓘ can still be found by the search box
    assert "pPlain(m)" in row.split("data-f=")[1][:80]


def test_a_long_paragraph_is_split_at_a_sentence_and_never_inside_a_tag():
    st = (JS / "11-settings.js").read_text()
    sp = st.split("function pSplit(")[1].split("function pTidy(")[0]
    assert "PTIP_AT" in sp and "!open.length" in sp, "a <b> or <code> is never cut in half"
    tidy = st.split("function pTidy(")[1].split("function pTipShow(")[0]
    assert ".ghint,.lead,.pl>small" in tidy
    assert "button,a,input,select,textarea" in tidy, "a paragraph holding a control is left whole"
    # every pane paints in pieces, so the tidy follows what lands in it
    assert "new MutationObserver(" in st.split("async function renderSettings(")[1].split("function setTab(")[0]


def test_the_tip_opens_on_hover_focus_and_tap_and_stays_on_screen():
    st = (JS / "11-settings.js").read_text()
    show = st.split("function pTipShow(")[1].split("function pTipHide(")[0]
    assert "innerWidth-tw-12" in show and "innerHeight" in show, "clamped inside a 390px screen"
    bind = st.split("function pTipBind(")[1].split("\n}")[0]
    for ev in ("pointerover", "focusin", "click", "Escape"):
        assert ev in bind, ev
    assert "pointerType!=='touch'" in bind, "a finger has no hover: a tap toggles it"
    css = (ROOT / "agentos/ui/src/css/11-prefs.css").read_text()
    # real size on a touch screen, never a halo that eats a neighbour's taps
    rule = css.split("body.dev-touch .pinfo{")[1].split("}")[0]
    assert "var(--tap)" in rule and "margin:-" not in rule


def test_the_panes_stay_short_and_say_it_plainly():
    for f in PANES:
        s = (JS / f).read_text()
        for d in re.findall(r"desc:\s*'((?:[^'\\]|\\.)*)'", s):
            v = _visible(d)
            assert len(v) <= 140, f"{f}: a setting's line is a line, not a paragraph: {v[:80]}…"
            assert "—" not in v, f"{f}: no dash-joined clauses in a setting's line: {v[:80]}"
        for g in re.findall(r'class="ghint"[^>]*>([^<]*)', s):
            assert "—" not in g, f"{f}: {g[:80]}"
