"""Window lifecycle: background apps must not keep working.

Every AgentOS app lives in one Chromium renderer, so an app that polls while it
is minimised is spending the same main thread the visible app needs — which is
exactly why a desktop with several apps open used to get sluggish in a way a
native one does not. `winTick` ties periodic work to a window's visibility.

These are source-level assertions because the behaviour is a convention: the
moment an app goes back to a bare `setInterval` the guarantee is quietly gone,
and nothing else would notice.
"""
import pathlib
import re

JS = pathlib.Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src" / "js"


def read(name: str) -> str:
    return (JS / name).read_text()


def test_lifecycle_module_exists():
    src = read("04c-lifecycle.js")
    for fn in ("function winAwake", "function winTick", "function stopWinTicks",
               "function applyWindowActivity", "function stopTick"):
        assert fn in src, f"{fn} missing from the lifecycle module"


def test_closing_a_window_stops_its_ticks():
    """Otherwise every app has to remember, and one that forgets leaks forever.

    Scoped to the whole function rather than its first 400 characters: that budget
    was measuring how much COMMENT sits above the call, so explaining a line near
    the top of closeWin failed a test about timer cleanup.
    """
    wm = read("04-wm.js")
    body = wm.split("function closeWin")[1].split("\nfunction ")[0]
    assert "stopWinTicks(w)" in body


def test_visibility_changes_reapply_activity():
    """The four ways a window stops being visible must all reach the same pass."""
    assert "applyWindowActivity()" in read("04-wm.js").split("function minimizeWin")[1][:500]
    assert "applyWindowActivity()" in read("04-wm.js").split("function restoreWin")[1][:400]
    assert "applyWindowActivity()" in read("03-virtual-desktops.js")   # desktop switch
    assert "visibilitychange" in read("04c-lifecycle.js")              # page backgrounded


def test_no_app_polls_with_a_bare_window_timer():
    """`w.timer=setInterval(...)` is the pattern winTick replaced."""
    offenders = []
    for f in sorted(JS.glob("*.js")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"\bw\.timer\s*=\s*setInterval", line):
                offenders.append(f"{f.name}:{n}")
    assert not offenders, "use winTick(w, fn, ms) so the work stops with the window: " + ", ".join(offenders)


def test_host_screen_capture_is_window_bound():
    """A full-screen PNG every 2s is the most expensive thing the shell does."""
    src = read("24a-hostscreen.js")
    assert "winTick(w,()=>hsFrame(w)" in src
    assert "setInterval" not in src
