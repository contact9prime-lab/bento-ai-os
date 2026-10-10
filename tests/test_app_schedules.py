"""A schedule set up for an app knows its app, and Missions, App Studio and the chat say so.

Reported with a screenshot of App Studio's Builder: "Can you update it every 10 mins" was
answered by "(building with Claude Code in /Users/…/builds/Make-an-application-that-
tracks-the-stoc — up to $25.00)", a full four-stage rebuild, and no schedule anywhere.
Asked alongside it: "if I am asking to set up the schedule, should it be done based on
the mission? That connection should be there in the chat."

Before this, nothing linked a schedule to an app. App Studio could not make one, Claude
Code in Chat could only draft a whole mission, an app's own appTool('schedule_task') made
an anonymous row, and a scheduled run had no way to save anything into the app it was
meant to keep fresh.
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors as execmod                           # noqa: E402
from agentos import mcpbridge, runlog                              # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP                                     # noqa: E402
from agentos.scheduler import Scheduler                            # noqa: E402
from agentos.tools import APP_BOUND_TOOLS, SAFE_TOOLS, Toolbox      # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
SERVER = (ROOT / "agentos/server.py").read_text()
APP = "<!doctype html><html><head><title>{}</title></head><body>hi</body></html>"


def _world(tmp_path):
    c = {"agent_name": "Arie", "autonomy": "balanced", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321,
         "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    seen = []

    async def broadcast(ev):
        seen.append(ev)
    tb.broadcast = broadcast
    tb.scheduler = Scheduler(c, store, tb, broadcast)
    return c, store, tb, seen


def test_an_old_database_gets_the_column(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, prompt TEXT, schedule_type TEXT, "
                "interval_seconds INTEGER, at_time TEXT, next_run REAL, last_run REAL, "
                "last_result TEXT, enabled INTEGER DEFAULT 1, created_at REAL)")
    con.execute("INSERT INTO tasks (id, prompt, schedule_type) VALUES ('t','old','interval')")
    con.commit()
    con.close()
    store = Store(db)
    assert store.list_tasks()[0]["app_id"] == "", "a schedule from before is for no app"


def test_a_chat_names_the_app_and_a_typo_never_links_to_nothing(tmp_path):
    _, store, tb, _ = _world(tmp_path)
    aid = store.save_app("Stock Tracker", "", "", APP.format("Stock Tracker"))
    out = asyncio.run(tb.execute("schedule_task", {
        "prompt": "fetch the prices", "schedule_type": "interval", "interval_minutes": 10,
        "app": "stock tracker"}))
    assert "for this app" in out and "every 10 min" in out, out
    assert store.list_tasks()[0]["app_id"] == aid
    bad = asyncio.run(tb.execute("schedule_task", {
        "prompt": "x", "schedule_type": "interval", "interval_minutes": 10, "app": "Stok Tracker"}))
    assert bad.startswith("[error] no app named") and "Stock Tracker" in bad
    assert len(store.list_tasks()) == 1


def test_the_same_schedule_asked_twice_is_one_row(tmp_path):
    """A Studio build runs in four stages, and an app may ask every time it opens."""
    _, store, tb, _ = _world(tmp_path)
    aid = store.save_app("Stock Tracker", "", "", APP.format("Stock Tracker"))
    args = {"prompt": "fetch the prices", "schedule_type": "interval", "interval_minutes": 10,
            "_app": aid}
    asyncio.run(tb.execute("schedule_task", dict(args)))
    again = asyncio.run(tb.execute("schedule_task", dict(args)))
    assert again.startswith("already scheduled") and len(store.list_tasks()) == 1
    # a different interval is a different schedule, and so is the same one for no app
    asyncio.run(tb.execute("schedule_task", {**args, "interval_minutes": 30}))
    asyncio.run(tb.execute("schedule_task", {k: v for k, v in args.items() if k != "_app"}))
    assert len(store.list_tasks()) == 3


def test_the_app_is_the_callers_never_the_models():
    agent = (ROOT / "agentos/agent.py").read_text()
    assert "if name in APP_BOUND_TOOLS:" in agent and 'k != "_app"' in agent
    assert 'args["_app"] = self.app_id' in agent
    assert set(APP_BOUND_TOOLS) == {"schedule_task", "create_trigger", "update_app_data"}
    tools = (ROOT / "agentos/tools.py").read_text()
    assert '{"_app"} if name in APP_BOUND_TOOLS' in tools
    # an app's own appTool call is filed under that app, after the `_` strip
    i = SERVER.index("async def api_run_tool")
    route = SERVER[i:SERVER.index("# ---- Grants:", i)]
    assert route.index('str(k).startswith("_")') < route.index('"_app": principal.id')
    assert 'principal.kind == "app" and name in tools.APP_BOUND_TOOLS' in route


def test_a_schedule_keeps_its_apps_data_fresh_and_only_its_own(tmp_path):
    _, store, tb, seen = _world(tmp_path)
    aid = store.save_app("Stock Tracker", "", "", APP.format("Stock Tracker"))
    other = store.save_app("Notes", "", "", APP.format("Notes"))
    store.set_app_data(aid, json.dumps({"watch": ["AAPL"]}))
    out = asyncio.run(tb.execute("update_app_data", {
        "name": "Stock Tracker", "key": "prices", "value": '{"AAPL": 231.5}', "_app": aid}))
    assert out.startswith("saved 'prices'"), out
    assert json.loads(store.get_app_data(aid)) == {"watch": ["AAPL"], "prices": {"AAPL": 231.5}}, \
        "one key is set and the rest is kept; a JSON string is stored as what it says"
    assert {"type": "app_data", "app_id": aid, "key": "prices"} in seen, "an open app hears it"
    refused = asyncio.run(tb.execute("update_app_data", {
        "name": "Notes", "key": "x", "value": 1, "_app": aid}))
    assert "can change only its data" in refused and store.get_app_data(other) == "{}"
    big = asyncio.run(tb.execute("update_app_data", {
        "name": "Notes", "key": "x", "value": "y" * 210_000}))
    assert "200 KB" in big
    # safe: a scheduled refresh that fetched a page must not be held for a person nobody is
    assert "update_app_data" in SAFE_TOOLS and tb.risk_of("update_app_data", {})[0] == "safe"


def test_a_scheduled_run_is_told_its_app_and_carries_it(tmp_path, monkeypatch):
    c, store, tb, _ = _world(tmp_path)
    aid = store.save_app("Stock Tracker", "", "", APP.format("Stock Tracker"))
    sch = tb.scheduler
    sch.create_task("fetch the prices", "interval", 10, app_id=aid)
    task = store.list_tasks()[0]
    got = {}

    async def fake_run_prompt(prompt, origin="schedule", title="", space_id="", app_id=""):
        got.update(prompt=prompt, app_id=app_id)
        return "", "done"
    monkeypatch.setattr(sch, "run_prompt", fake_run_prompt)
    asyncio.run(sch._run_task(task))
    assert got["app_id"] == aid
    assert 'belongs to the app "Stock Tracker"' in got["prompt"] and "update_app_data" in got["prompt"]


def test_a_forwarded_schedule_gets_a_door_with_the_apps_two_tools(tmp_path):
    c, store, tb, _ = _world(tmp_path)
    aid = store.save_app("Stock Tracker", "", "", APP.format("Stock Tracker"))
    store.save_app("Notes", "", "", APP.format("Notes"))
    env = execmod.Envelope(workspace=str(tmp_path))

    async def approver(*a, **k):
        return False                      # nobody is there: the two tools are safe anyway
    token = execmod.open_app_door(env, c, tb, aid, approver)
    assert token and "--mcp-config" in execmod.build_command("hi", env)
    _, listed = asyncio.run(mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
    assert sorted(t["name"] for t in listed["result"]["tools"]) == ["read_app_data", "update_app_data"]

    def call(name, args):
        _, r = asyncio.run(mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                    "params": {"name": name, "arguments": args}}))
        return json.dumps(r)
    assert "saved 'prices'" in call("update_app_data", {"name": "Stock Tracker", "key": "prices",
                                                        "value": [1, 2], "_app": "forged"})
    assert json.loads(store.get_app_data(aid))["prices"] == [1, 2], "the forged _app was dropped"
    assert "can change only its data" in call("update_app_data", {"name": "Notes", "key": "k", "value": 1})
    mcpbridge.close_session(token)
    # no app, or an executor with no door: nothing opened
    assert execmod.open_app_door(execmod.Envelope(workspace=str(tmp_path)), c, tb, "", approver) == ""
    sched = (ROOT / "agentos/scheduler.py").read_text()
    assert 'app={"toolbox": self.toolbox, "app_id": app_id' in sched


def test_missions_the_studio_and_the_terminal_show_the_app(tmp_path):
    _, store, tb, _ = _world(tmp_path)
    aid = store.save_app("Stock Tracker", "", "", APP.format("Stock Tracker"))
    tb.scheduler.create_task("fetch the prices", "interval", 10, app_id=aid)
    tb.scheduler.create_task("tidy downloads", "daily", at_time="09:00")
    tb.scheduler.create_task("ping the old app", "interval", 60, app_id="gone123")
    rows = {r["prompt"]: r for r in runlog.schedules(store)}
    assert rows["fetch the prices"]["app_name"] == "Stock Tracker"
    assert rows["tidy downloads"]["app_name"] == "" and not rows["tidy downloads"]["app_gone"]
    assert rows["ping the old app"]["app_gone"], "a deleted app's schedule says so"
    txt = runlog.schedules_text(runlog.schedules(store), app="stock tracker")
    assert "fetch the prices" in txt and "for the app Stock Tracker" in txt and "tidy" not in txt
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"schedules"])' in main and "runlog.schedules_text" in main
    tui = (ROOT / "agentos/tui_app.py").read_text()
    assert 'tk.get("app_name")' in tui
    tasks = (JS / "15-scheduler-taskmgr.js").read_text()
    assert "t.app_name?" in tasks and "taskOpenApp(" in tasks and "app that was deleted" in tasks
    studio = (JS / "26-studio.js").read_text()
    assert "studioTab('sched')" in studio and "t.app_id===STUDIO.sel" in studio
    assert "ev.name==='schedule_task'" in studio and "Open in Missions" in studio
    hand = (JS / "10a-handoff.js").read_text()
    assert "args.app?'for '" in hand


def test_the_history_says_which_app_a_run_refreshed(tmp_path):
    """Missions → History said "scheduled prompt" for a run that refreshed an app, so the
    run and the app it fed were two places with nothing between them."""
    _, store, tb, _ = _world(tmp_path)
    aid = store.save_app("Volume Tracker", "", "", APP.format("Volume Tracker"))
    tb.scheduler.create_task("fetch today's volumes", "interval", 10, app_id=aid)
    t = next(x for x in store.list_tasks() if x["app_id"] == aid)
    store.task_run_finish(store.task_run_start(t), "ok", "saved 'latest'")
    row = runlog.history(store)["runs"][0]
    assert (row["app_id"], row["app_name"]) == (aid, "Volume Tracker")
    hist = (JS / "14c-history.js").read_text()
    assert "r.app_name?'for '+esc(r.app_name)" in hist and "taskOpenApp('${esc(r.app_id)}')" in hist


def test_an_answered_approval_takes_its_toast_with_it():
    """The toast's Review stayed up after the card was answered, opening nothing."""
    ws = (JS / "09-websocket.js").read_text()
    assert "tt.dataset.approval=ev.id" in ws
    res = ws[ws.index("case 'approval_resolved':"):][:400]
    assert "t.dataset.approval===String(ev.id)" in res
    core = (JS / "00-core.js").read_text()
    assert "  return d;\n}" in core[core.index("function toast(t,act)"):][:3200]

def test_an_open_app_hears_that_its_data_changed():
    assert "e.data.agentos !== 'app_data'" in SERVER and "e.source !== parent" in SERVER
    assert "new CustomEvent('appdata'" in SERVER
    ws = (JS / "09-websocket.js").read_text()
    assert "case 'app_data':" in ws and "agentos:'app_data'" in ws


def test_chat_on_claude_code_can_set_up_a_schedule_for_an_app():
    assert "schedule_task" in execmod.TEAM_TOOLS
    note = execmod.team_note([])
    assert "SCHEDULES." in note and "mcp__bento__schedule_task" in note and "app=" in note
    co = {"name": "Stock Tracker", "path": "/x/app.html"}
    assert 'schedule_task with app=\\"Stock Tracker\\"' in json.dumps(execmod.chat_app_note(co))


def test_app_studio_sets_up_a_schedule_for_the_app_it_is_changing():
    i = SERVER.index("async def bapprove(name, args, reason, offer=None):")
    build = SERVER[i:i + 30000]
    assert 'if name == "schedule_task":' in build and "await request_approval(name, args" in build, \
        "a schedule outlives the build: the person says yes"
    # found live: with no conversation the card was drawn inside whatever chat was open
    assert '"conversation_id": cid' in build and "evsend=to_studio" in build
    assert '"where": where' in build and 'f"App Studio, for {existing[\'name\']}"' in build
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "ev.where?' · '+esc(ev.where)" in ws
    act = (ROOT / "agentos/ui/src/js/08b-activity.js").read_text()
    assert "name === 'schedule_task'" in act
    # a new app built in App Studio is named by its <title>, as one built in Chat is
    assert "titled = execmod._title_of(html)" in build and "execmod._unique_app_name(store, titled)" in build
    assert 'build_app_id = (existing or {}).get("id", "")' in build
    assert 'tf.append("schedule_task")' in build and "agent.app_id = build_app_id" in build
    assert 'tools=("schedule_task",)' in build and "mcpbridge.close_session(door)" in build
    # the closing message says it, because that is what the Builder shows after a reload
    assert 'f"Built with Claude Code (${run.cost_usd:.2f})." + sched_note()' in build
    assert '(result["content"] or "") + sched_note()' in build
    # the CLI's own copy of a door call is not shown twice
    assert 'startswith("mcp__bento__")' in build
    # the persona says where the data goes and how the app hears it
    assert "update_app_data" in SERVER[SERVER.index("ALERTS & CHANNELS"):SERVER.index("PERMISSIONS — declare")]


def test_the_builder_line_is_a_sentence_without_a_folder(tmp_path):
    assert "building with Claude Code in {co['dir']}" not in SERVER
    assert "Claude Code is {'changing' if existing else 'building'}" in SERVER
    assert "This build can spend up to $" in SERVER
    studio = (JS / "26-studio.js").read_text()
    assert "EXEC_TITLES[ev.engine]" in studio and "STUDIO._engShown" in studio


def test_a_refine_builds_from_the_current_version_in_the_apps_own_folder(tmp_path):
    ws = str(tmp_path)
    co = execmod.prepare_build(ws, "Make an application that tracks the stocks", "<p>v1</p>", key="abc123")
    assert co["dir"].endswith("builds/app-abc123"), "named by id, not an old sentence"
    Path(co["spec"]).write_text("old spec")
    Path(co["review"]).write_text("VERDICT: ship")
    Path(co["path"]).write_text("<p>an old build's leftover</p>")
    co2 = execmod.prepare_build(ws, "Stock Tracker", "<p>v2 from chat</p>", key="abc123")
    assert co2["dir"] == co["dir"] and co2["before"] == "<p>v2 from chat</p>", \
        "a chat edit since the last build is what this one starts from"
    assert not Path(co2["spec"]).exists() and not Path(co2["review"]).exists()
    assert 'key=(existing or {}).get("id", "")' in SERVER
