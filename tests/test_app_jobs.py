"""An app's periodic work runs in the framework: a schedule, no model, approved script, gated runs.

Asked for over Signal Desk, whose page ran a hidden Python reader every minute from a timer:
"when you have a framework, the app should look into the framework, the framework provides
mission, permissions, ethics". The owner's choice: numbers are an app job (this), judgement is
an agent schedule (schedule_task with the app).
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import appjobs, approvalcard                         # noqa: E402
from agentos.memory import Store                                  # noqa: E402
from agentos.policy import PDP, Principal                         # noqa: E402
from agentos.scheduler import Scheduler                           # noqa: E402
from agentos.tools import ALWAYS_ASK, APP_BOUND_TOOLS, Toolbox    # noqa: E402

SCRIPT = "import json\nprint(json.dumps({'signals': 47, 'newest': '13:20'}))\n"


def _world(tmp_path):
    c = {"agent_name": "Aria", "autonomy": "balanced", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path / "ws"), "providers": {}, "port": 8321,
         "sandbox": {"enabled": False}, "memory": {"inject_facts": 0, "inject_user": 0}}
    os.makedirs(c["workspace"], exist_ok=True)
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    events = []

    async def bc(ev):
        events.append(ev)
    tb.broadcast = bc
    sched = Scheduler(c, store, tb, bc)
    tb.scheduler = sched
    aid = store.save_app("Signal Desk", "", "", "<html><title>Signal Desk</title></html>")
    return c, store, tb, sched, aid, events


def test_a_job_is_asked_every_time_and_belongs_to_its_app():
    assert "schedule_app_job" in ALWAYS_ASK, "the card is the script; no autonomy answers it"
    assert {"schedule_app_job", "app_jobs"} <= set(APP_BOUND_TOOLS), "the app is the caller's, never the model's"


def test_the_card_shows_the_script_and_what_it_means(tmp_path):
    args = {"title": "Scan", "script": "import urllib.request\nprint(1)", "interval_minutes": 5, "key": "scan"}
    c = approvalcard.card("schedule_app_job", args, who='The app "Signal Desk"')
    assert c["body"].endswith(args["script"]) and "every 5 minutes, with no model" in c["body"].lower()
    means = " ".join(c["means"])
    assert "Missions → History" in means and "connects to the internet" in means
    assert "asked again" in means


def test_approved_it_runs_as_the_app_saves_its_output_and_is_a_history_row(tmp_path):
    c, store, tb, sched, aid, events = _world(tmp_path)
    out = asyncio.run(tb.schedule_app_job(title="Scan the market", script=SCRIPT,
                                          interval_minutes=5, key="scan", _app=aid))
    assert out.startswith("scheduled: Scan the market, every 5 min")
    task = appjobs.find(store, aid, "Scan the market")
    assert task and task["script"] == SCRIPT and task["interval_seconds"] == 300
    # asked again with the same script: one row, no second grant
    again = asyncio.run(tb.schedule_app_job(title="Scan the market", script=SCRIPT,
                                            interval_minutes=5, key="scan", _app=aid))
    assert again.startswith("already scheduled")
    assert len([g for g in store.list_grants() if (g.get("source_ref") or "") == f"job:{task['id']}"]) == 1
    asyncio.run(sched._run_task(task))
    data = json.loads(store.get_app_data(aid))
    assert data["scan"] == {"signals": 47, "newest": "13:20"}
    assert data["_jobs"]["Scan the market"]["ok"] is True
    runs = None
    rows = store.db.execute("SELECT status FROM task_runs WHERE task_id=?", (task["id"],)).fetchall()
    assert [r["status"] for r in rows] == ["ok"], runs
    led = store.db.execute("SELECT action, resource, effect FROM audit WHERE principal_kind='app' "
                           "AND principal_id=? AND surface='task' ORDER BY rowid DESC LIMIT 5", (aid,)).fetchall()
    assert any("run_python" in (r["resource"] or "") and r["effect"] == "allow" for r in led), \
        "the run passed the gate and is in the ledger"


def test_a_changed_script_is_refused_until_approved_again(tmp_path):
    c, store, tb, sched, aid, events = _world(tmp_path)
    asyncio.run(tb.schedule_app_job(title="Scan", script=SCRIPT, interval_minutes=5, key="scan", _app=aid))
    task = appjobs.find(store, aid, "Scan")
    store.update_task(task["id"], script=SCRIPT + "print('and something else')\n")
    asyncio.run(sched._run_task(appjobs.find(store, aid, "Scan")))
    data = json.loads(store.get_app_data(aid))
    assert "scan" not in data and data["_jobs"]["Scan"]["ok"] is False
    assert "no longer matches" in data["_jobs"]["Scan"]["note"]
    rows = store.db.execute("SELECT status FROM task_runs WHERE task_id=?", (task["id"],)).fetchall()
    assert [r["status"] for r in rows] == ["failed"]


def test_another_app_and_another_script_get_nothing_from_the_grant(tmp_path):
    c, store, tb, sched, aid, events = _world(tmp_path)
    asyncio.run(tb.schedule_app_job(title="Scan", script=SCRIPT, interval_minutes=5, key="scan", _app=aid))
    action, resource = appjobs.grant_of(SCRIPT)
    ctx = {"surface": "task", "tool": "run_python", "args": appjobs.args_of(SCRIPT)}
    raw = resource.replace("[*]", "*").replace("[?]", "?").replace("[[]", "[")
    assert tb.pdp.decide(Principal("app", aid), action, raw, ctx).effect == "allow"
    assert tb.pdp.decide(Principal("app", "other"), action, raw, ctx).effect != "allow"
    _a2, other = appjobs.grant_of("import os; os.system('rm -rf ~')")
    assert tb.pdp.decide(Principal("app", aid), action, other, ctx).effect != "allow"


def test_removing_the_job_removes_its_grant(tmp_path):
    c, store, tb, sched, aid, events = _world(tmp_path)
    asyncio.run(tb.schedule_app_job(title="Scan", script=SCRIPT, interval_minutes=5, key="scan", _app=aid))
    tid = appjobs.find(store, aid, "Scan")["id"]
    store.delete_task(tid)
    assert not [g for g in store.list_grants() if (g.get("source_ref") or "") == f"job:{tid}"]


def test_what_a_job_must_say_is_read_field_by_field():
    assert appjobs.clean("", SCRIPT, 5, "scan")[1].startswith("[error]")
    assert appjobs.clean("Scan", "", 5, "scan")[1].startswith("[error]")
    assert appjobs.clean("Scan", SCRIPT, 0, "scan")[1].startswith("[error]")
    assert appjobs.clean("Scan", SCRIPT, 5, "_jobs")[1].startswith("[error]")
    assert appjobs.clean("Scan", SCRIPT, 5, "1bad")[1].startswith("[error]")
    job, err = appjobs.clean("  Scan   the market ", SCRIPT, "5", "scan")
    assert not err and job["title"] == "Scan the market" and job["every"] == 5


def test_app_jobs_tells_the_app_its_jobs_without_the_script(tmp_path):
    c, store, tb, sched, aid, events = _world(tmp_path)
    asyncio.run(tb.schedule_app_job(title="Scan", script=SCRIPT, interval_minutes=5, key="scan", _app=aid))
    rows = json.loads(asyncio.run(tb.app_jobs(_app=aid)))
    assert rows[0]["title"] == "Scan" and rows[0]["every_minutes"] == 5 and rows[0]["key"] == "scan"
    assert rows[0]["script_sha"] == appjobs.digest(SCRIPT) and "script" not in rows[0]


SD = """<div class="desktop-only"></div><div class="widget-only"></div><script>
function esc(s){ return String(s).replace(/[&<>"]/g, c => '&#'+c.charCodeAt(0)+';'); }
async function load(){ const r = await window.appTool('run_command',{command:'echo X | base64 -d | python3'}); return r; }
async function refresh(){ document.title = esc(await load()); }
(async()=>{ appCopilot.mount({starters:['a']}); await refresh(); setInterval(()=>{ if(!document.hidden) refresh(); }, 60000); })();
</script>"""


def test_the_checker_names_work_on_a_page_timer_and_a_page_running_commands():
    from agentos import appcheck
    rules = {i.rule: i for i in appcheck.check(SD).issues}
    assert rules["clock-in-page"].severity == appcheck.CONTRACT
    assert "appJob.ensure" in rules["clock-in-page"].fix
    assert rules["runs-commands"].severity == appcheck.CONTRACT
    # a timer that only redraws, and a debounce, are fine
    ok = SD.replace("window.appTool('run_command',{command:'echo X | base64 -d | python3'})", "appData.get()")
    assert not {"clock-in-page", "runs-commands"} & {i.rule for i in appcheck.check(ok).issues}
    deb = '<script>let t;function k(){clearTimeout(t);t=setTimeout(()=>fetch("/x"),300)}</script>'
    assert "clock-in-page" not in {i.rule for i in appcheck.check(deb).issues}
    # found live: fetching once on open and redrawing "updated 3 min ago" on a timer is right
    right = """<script>function esc(s){return String(s).replace(/[&<>"]/g,c=>c)}
function render(){ document.body.textContent = esc('updated'); }
async function first(){ await appTool('fetch_url',{url:'https://x'}); render(); }
first(); setInterval(render, 30000);</script>"""
    assert "clock-in-page" not in {i.rule for i in appcheck.check(right).issues}


def test_the_builder_is_told_the_framework_runs_work_on_a_clock():
    src = (Path(__file__).parent.parent / "agentos/server.py").read_text()
    persona = src[src.index("BUILDER_PERSONA = "):src.index("APP_CRAFT = ")]
    assert "WORK ON A CLOCK" in persona and "appJob.ensure" in persona and "schedule_task" in persona
    assert "while the app is open is setInterval in the app" not in persona
    assert "never fetches, runs code or asks the AI" in persona
    rt = src[src.index("window.appJob = {"):src.index("\n};", src.index("window.appJob = {"))]
    assert "app_jobs" in rt and "schedule_app_job" in rt and "script_sha" in rt


def test_a_schedule_left_claimed_by_a_stop_gets_a_next_run_again(tmp_path):
    """Seen on the owner's machine: an every-3-hours schedule read "waiting for its event ·
    has not run yet" for good, because it was claimed (next_run cleared) and never booked."""
    c, store, tb, sched, aid, events = _world(tmp_path)
    tid = store.add_task("check the market", "interval", 3 * 3600, None, None)
    trig = store.add_task("on a file", "trigger", None, None, None, trigger="file_change")
    off = store.add_task("off", "interval", 600, None, None)
    store.update_task(off, enabled=0)
    assert sched.revive() == 1
    rows = {t["id"]: t for t in store.list_tasks()}
    assert rows[tid]["next_run"] and rows[tid]["last_run"] is None, "booked, and still never run"
    assert rows[trig]["next_run"] is None and rows[off]["next_run"] is None


def test_a_run_that_dies_still_books_its_next_run(tmp_path):
    c, store, tb, sched, aid, events = _world(tmp_path)
    tid = store.add_task("boom", "interval", 600, None, None)
    task = next(t for t in store.list_tasks() if t["id"] == tid)

    async def boom(*_a, **_k):
        raise RuntimeError("the brain went away")
    sched._run_task_inner = boom
    try:
        asyncio.run(sched._run_task(task))
    except RuntimeError:
        pass
    t = next(t for t in store.list_tasks() if t["id"] == tid)
    assert t["next_run"] and "the brain went away" in t["last_result"]


def test_missions_marks_an_app_job_and_never_carries_its_script(tmp_path):
    from agentos import runlog
    c, store, tb, sched, aid, events = _world(tmp_path)
    asyncio.run(tb.schedule_app_job(title="Scan", script=SCRIPT, interval_minutes=5, key="scan", _app=aid))
    row = next(r for r in runlog.schedules(store) if r.get("app_job"))
    assert row["app_name"] == "Signal Desk" and "script" not in row
    js = (Path(__file__).parent.parent / "agentos/ui/src/js/15-scheduler-taskmgr.js").read_text()
    assert "app job · no model" in js


def test_a_card_with_no_offer_still_names_who_asks():
    """Found live: an app's job card (asked every time, so no offer) said "Aria wants to …"."""
    tok = approvalcard.ASKER.set(approvalcard.asker_of(Principal("app", "a1")))
    try:
        who = approvalcard.who_of(None, lambda aid: "Crypto Prices", "Aria")
    finally:
        approvalcard.ASKER.reset(tok)
    assert who == 'The app "Crypto Prices"'
    assert approvalcard.who_of(None, agent_name="Aria") == "Aria"
    src = (Path(__file__).parent.parent / "agentos/agent.py").read_text()
    assert "_apc.ASKER.set(_apc.asker_of(self.principal))" in src


def test_a_job_saves_its_data_without_the_gates_untrusted_fence():
    """Found live: a job that downloaded prices saved '<untrusted source=…>{…}' as a string,
    and the app showed no prices."""
    from agentos.agent import fence
    fenced = fence("a download in the shell (urllib)", '{"btc": {"usd": 59064}}')
    ok, value, _line = appjobs.result_of(fenced)
    assert ok and value == {"btc": {"usd": 59064}}
    ok, value, _ = appjobs.result_of(fence("x", "plain text with </untrusted> inside"))
    assert ok and value == "plain text with </untrusted> inside"


def test_an_app_icon_is_the_size_of_a_letter_unless_the_app_says_otherwise():
    """Found in a live build: an unsized appIcon arrow filled a price card."""
    src = (Path(__file__).parent.parent / "agentos/server.py").read_text()
    line = src[src.index("window.appIcon = (n) =>"):].split("\n")[0]
    assert 'width="1em" height="1em"' in line
