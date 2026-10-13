"""Watch me once (00i-watch.js) and the routine card it leaves (07-widgets.js).

Asked for as "the OS quietly notices a repetitive task and offers a one-click widget or
cron job". What these defend:

- a sequence is offered only when the newest steps happened the same way earlier, with
  at least three steps and two different doors, inside the window; never a step repeated
  in place, never something a routine replayed or code opened;
- what is noted is the door (app, tab, place, Logs filter), never content, kept in the
  page's memory only, and a "not this one" is never offered again;
- what it makes is a Routine (the desktop's own steps), whose new `place` and `view`
  steps the server keeps and the runner replays, and a native card on the desktop.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
SRC = (JS / "00i-watch.js").read_text()


def _fn(name: str) -> str:
    i = SRC.index(f"function {name}(")
    depth, j = 0, SRC.index("{", i)
    for k in range(j, len(SRC)):
        depth += {"{": 1, "}": -1}.get(SRC[k], 0)
        if depth == 0:
            return SRC[i:k + 1]
    raise AssertionError(name)


def _find(keys, ages=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    now = 10_000_000
    steps = [{"key": k, "at": now - (ages[i] if ages else 1000 * (len(keys) - i))} for i, k in enumerate(keys)]
    prog = ("var WATCH_WINDOW=45*60*1000,WATCH_MIN=3,WATCH_MAX=6;" + _fn("watchFind")
            + f"\nconsole.log(JSON.stringify(watchFind({json.dumps(steps)},{now})));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_same_steps_twice_is_offered():
    hit = _find(["place:Ledger", "app:logs#error", "app:brief", "place:Ledger", "app:logs#error", "app:brief"])
    assert hit and hit["sig"] == "place:Ledger>app:logs#error>app:brief"
    # longest first: four repeated steps are offered as four, not as the last three
    hit = _find(["a", "b", "c", "d", "x", "a", "b", "c", "d"])
    assert hit["sig"] == "a>b>c>d"


def test_what_is_not_a_routine_is_not_offered():
    assert _find(["a", "b", "a", "b"]) is None, "two steps are not worth a routine"
    assert _find(["a", "a", "a", "a", "a", "a"]) is None, "one door is not a routine"
    assert _find(["a", "b", "c", "a", "b", "d"]) is None
    # the earlier time was over the window ago
    assert _find(["a", "b", "c", "a", "b", "c"], ages=[3_000_000, 2_999_000, 2_998_000, 3000, 2000, 1000]) is None


def test_only_doors_are_noted_and_only_a_persons_own():
    note = _fn("watchNote")
    assert "navigator.userActivation" in note and "AUTO_RUNNING" in note
    assert "localStorage" not in _fn("watchPush"), "the steps stay in the page's memory"
    assert "watch.declined" in SRC and "watchDecline(hit.sig)" in SRC
    # the hooks: openApp, places, the Settings rail, Missions tabs, the Logs filter
    hooks = {"04-wm.js": "watchNote('app',id)", "05b-places.js": "watchNote('place',label)",
             "11-settings.js": "watchNote('view','settings',SETTAB)", "14a-jobs.js": "watchNote('view','jobs',JOBS.tab)",
             "16-mcp-telegram-logs.js": "watchNote('view','logs',w.kind)"}
    for f, hook in hooks.items():
        assert hook in (JS / f).read_text(), f
    assert "pSwitch('s-watch',watchOn())" in (JS / "11-settings.js").read_text()


def test_a_routine_keeps_places_and_views():
    from agentos import server
    steps = server._clean_steps([{"kind": "place", "place": "Ledger"}, {"kind": "place"},
                                 {"kind": "app", "app": "logs", "view": "error<script>"},
                                 {"kind": "app", "app": "settings", "view": "team"}])
    assert steps == [{"kind": "place", "place": "Ledger"}, {"kind": "app", "app": "logs", "view": "errorscript"},
                     {"kind": "app", "app": "settings", "view": "team"}]
    run = (JS / "15a-automations.js").read_text()
    assert "case 'place':" in run and "function automationView(" in run
    w = (JS / "07-widgets.js").read_text()
    assert "function pinRoutine(" in w and "function createRoutineWidgetEl(" in w and "runAutomation(rt)" in w


def test_a_pinned_routine_lands_clear_of_the_greeting():
    """#home sits above the widgets and its chips take taps: a routine pinned in the middle
    of the screen showed a Play button nobody could press (found by the live walk)."""
    js = (ROOT / "agentos/ui/src/js/07-widgets.js").read_text()
    pin = js.split("function pinRoutine(", 1)[1].split("\n}", 1)[0]
    assert "innerWidth-266" in pin and "x:170" not in pin
