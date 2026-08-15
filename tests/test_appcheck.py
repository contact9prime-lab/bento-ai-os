"""The app contract, enforced — `agentos/appcheck.py`.

`BUILDER_PERSONA` has always described what a Bento app is: two surfaces, state in
`appData` rather than localStorage, a resident copilot, the AI runtime built in, no
external assets. None of it was checked. The one-shot builder got a truncation check
and three layout smells; the Claude Code executor path — the good one, the one that
writes the app as a file and can iterate — returned before the verification block
entirely. The better the build path, the less anyone looked at what came out.

The tests that matter here are the CONTRACT ones. A missing widget view or state
stranded in localStorage does not throw, does not show up in a console, and looks
completely fine in the window the author is staring at. It surfaces later as "why do
generated apps feel generic" — which is not a bug report anyone can act on.
"""

import pytest

from agentos import appcheck

# A minimal app that honours the whole contract. Every test below is a single
# deviation from this, so a failure names exactly one rule.
GOOD = """<!doctype html><html><head><title>T</title></head><body>
<div class="desktop-only">
  <h1>Tasks</h1>
  <div class="card"><div class="empty">Nothing yet — add your first task.</div>
    <ul id="list"></ul></div>
</div>
<div class="widget-only"><div class="kpi"><b id="n">0</b><span>open</span></div></div>
<script>
(async () => {
  const st = await appData.get();
  try { await appTool('system_info', {}); } catch (e) { }
  (st.items || []).forEach(i => { });
  await appData.set(st);
  appLLM.stream('summarise', {onDelta: t => {}});
  appCopilot.mount({starters: ['add a task']});
})();
</script></body></html>"""


def rules(html, known=None):
    return {i.rule for i in appcheck.check(html, known).issues}


def test_a_good_app_is_clean():
    """The fixture every other test mutates. If this ever reports something, the rest
    of the file is testing noise rather than the rule it names."""
    assert appcheck.check(GOOD, {"system_info"}).issues == []


# ------------------------------------------------------------------ broken: it fails

def test_external_assets_are_blocked_at_runtime():
    """A strict CSP blocks these, so the app loads and does nothing. The author's
    browser may have it cached, which is how it ships."""
    html = GOOD.replace("<body>", '<body><script src="https://cdn.example.com/x.js"></script>')
    assert "external-asset" in rules(html, {"system_info"})


def test_a_tool_that_does_not_exist_is_caught():
    html = GOOD.replace("appTool('system_info', {})", "appTool('nonexistent_tool', {})")
    assert "unknown-tool" in rules(html, {"system_info"})


def test_the_tool_check_is_skipped_rather_than_guessed_when_the_toolbox_is_absent():
    """Without a toolbox, every tool name would look unknown — and a check that
    invents defects gets switched off by whoever reads it next."""
    html = GOOD.replace("appTool('system_info', {})", "appTool('anything_at_all', {})")
    assert "unknown-tool" not in rules(html, None)


def test_top_level_await_is_caught():
    """The single most common way a generated app dies completely: a plain <script>
    is not a module, so this is a SyntaxError and NOTHING in the file runs. A blank
    window and one line in a console nobody has open."""
    html = GOOD.replace("(async () => {", "await appData.get();\n(async () => {")
    assert "top-level-await" in rules(html, {"system_info"})


def test_await_inside_a_function_is_not_top_level():
    assert "top-level-await" not in rules(GOOD, {"system_info"})


def test_the_word_await_inside_a_string_is_not_code():
    """A rule fooled by its own keyword appearing in a message reports a SyntaxError
    that is not there, and the fix pass then 'repairs' working code."""
    html = GOOD.replace("appLLM.stream('summarise'",
                        "appLLM.stream('await the results, then await more'")
    assert "top-level-await" not in rules(html, {"system_info"})


def test_await_in_a_comment_is_not_code():
    html = GOOD.replace("<script>", "<script>\n// await appData.get() would go here\n")
    assert "top-level-await" not in rules(html, {"system_info"})


# -------------------------------------------------- contract: it runs, but it is not ours

def test_a_missing_widget_surface_is_a_contract_violation():
    """Pinned to the desktop, an app with no widget view renders the entire
    application into a 260x170 tile. It does not error; it is just useless there,
    and nothing told anyone."""
    html = GOOD.replace('<div class="widget-only">', '<div class="hidden-thing">')
    assert "no-widget-surface" in rules(html, {"system_info"})


def test_localstorage_instead_of_appdata_is_a_contract_violation():
    """The defect with the longest fuse: it works perfectly for the author, and then
    the agent cannot read the app's data and the user's phone shows an empty app."""
    html = GOOD.replace("const st = await appData.get();",
                        "const st = JSON.parse(localStorage.getItem('s') || '{}');")
    html = html.replace("await appData.set(st);", "localStorage.setItem('s', JSON.stringify(st));")
    assert "localstorage-not-appdata" in rules(html, {"system_info"})


def test_localstorage_alongside_appdata_is_allowed():
    """A cache or a UI preference in localStorage is fine. The rule is about state
    that only lives there."""
    html = GOOD.replace("const st = await appData.get();",
                        "localStorage.setItem('tab','1');\n  const st = await appData.get();")
    assert "localstorage-not-appdata" not in rules(html, {"system_info"})


def test_a_missing_copilot_is_caught():
    html = GOOD.replace("appCopilot.mount({starters: ['add a task']});", "")
    assert "no-copilot" in rules(html, {"system_info"})


def test_an_app_that_uses_no_ai_at_all_is_caught():
    """The AI runtime is the reason this is not a static web page."""
    html = (GOOD.replace("appLLM.stream('summarise', {onDelta: t => {}});", "")
                .replace("appCopilot.mount({starters: ['add a task']});", ""))
    assert "no-ai" in rules(html, {"system_info"})


@pytest.mark.parametrize("css,rule", [
    ("position: fixed", "position-fixed"),
    ("position:absolute;a{position:absolute}b{position:absolute}", "position-absolute"),
    ("writing-mode: vertical-rl", "rotated-text"),
])
def test_layout_rules_the_design_system_exists_to_make_unnecessary(css, rule):
    html = GOOD.replace("<head>", f"<head><style>.x{{{css}}}</style>")
    assert rule in rules(html, {"system_info"})


def test_one_absolute_is_not_a_layout_smell():
    """A tooltip or a badge is a legitimate use. The rule is about layout BUILT on it."""
    html = GOOD.replace("<head>", "<head><style>.tip{position:absolute}</style>")
    assert "position-absolute" not in rules(html, {"system_info"})


# ------------------------------------------------------------------------ severities

def test_severity_decides_what_is_worth_another_build_turn():
    """A rebuild costs the user real money, so polish must never trigger one alone."""
    html = GOOD.replace('<div class="empty">Nothing yet — add your first task.</div>', "")
    rep = appcheck.check(html, {"system_info"})
    assert {i.rule for i in rep.issues} == {"no-empty-state"}
    assert rep.of(appcheck.POLISH), "an empty state is polish"
    assert not rep.worth_fixing, "polish alone must not justify a fix turn"


def test_broken_and_contract_are_both_worth_fixing():
    html = GOOD.replace('<div class="widget-only">', '<div class="x">')
    assert appcheck.check(html, {"system_info"}).worth_fixing


def test_the_brief_leads_with_the_worst():
    """It is handed to a model with a length cap; if truncation drops anything it
    must drop the least important thing."""
    html = (GOOD.replace('<div class="widget-only">', '<div class="x">')
                .replace("<body>", '<body><script src="https://cdn.example.com/a.js"></script>')
                .replace('<div class="empty">Nothing yet — add your first task.</div>', ""))
    brief = appcheck.check(html, {"system_info"}).brief()
    assert brief.index("[broken]") < brief.index("[contract]") < brief.index("[polish]")


def test_every_issue_says_what_to_do_about_it():
    """A finding with no fix is a complaint. The fix stage is a model reading these."""
    html = GOOD.replace('<div class="widget-only">', '<div class="x">')
    for i in appcheck.check(html, set()).issues:
        assert i.fix.strip(), f"{i.rule} reports a problem with no remedy"


def test_a_report_with_no_issues_is_falsey():
    assert not appcheck.check(GOOD, {"system_info"})


# ----------------------------------------------------------- the old entry point still works

def test_the_server_linter_still_returns_plain_strings():
    """`_lint_app_html` has existing call sites and a test in
    tests/test_permissions_surfaces.py. Moving the rules must not change its shape."""
    from agentos.server import _lint_app_html
    out = _lint_app_html('<img src="https://x.example/a.png">')
    assert isinstance(out, list) and out and all(isinstance(s, str) for s in out)
    assert any("x.example" in s for s in out)
