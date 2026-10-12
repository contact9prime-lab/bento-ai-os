"""An App Studio build is your agent working, and every surface shows who is working.

Reported with three screenshots: Claude Code building an app in App Studio while the
World stood idle ("the agents are quiet too"), App Studio labelling the builder "▲ Aria",
and Chat drawing a plain dot where the agent's face goes ("why agents are not shown in
the chat, their icons"). Three causes:

- the page handed every build_* event to the Studio and returned, so the World, the
  Office, the Crew stage, the Mind and the dial never saw a build; and the World's
  server side had no mapping for build events either;
- the Studio wrote a ▲ glyph where every other surface draws the agent's face;
- "Faces beside messages" was one localStorage key per BROWSER, so one account's "off"
  turned faces off for every account signed in on that browser afterwards.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import world                                          # noqa: E402
from agentos.memory import Store                                   # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
SERVER = (ROOT / "agentos/server.py").read_text()


def _lead(v):
    return next(a for a in v["agents"] if a["name"] == world.LEAD)


def test_a_build_is_the_lead_at_work_in_the_world(tmp_path):
    store = Store(tmp_path / "t.db")
    uid = "build-u1"
    world.enter(uid, store, "lantern-canal", ["researcher"])
    try:
        world.observe({"type": "build_start"}, uid)
        assert _lead(world.view(uid))["busy"], "the lead is at work while the build runs"
        world.observe({"type": "build_tool_end", "ok": True, "name": "Write"}, uid)
        world.observe({"type": "build_done", "name": "Volume Tracker"}, uid)
        lead = _lead(world.view(uid))
        assert not lead["busy"]
        assert any(w["signal"] == "succeeded" and "Volume Tracker" in w["detail"] for w in lead["why"])
    finally:
        world.leave(uid)


def test_stopping_a_build_is_not_the_agents_failure(tmp_path):
    store = Store(tmp_path / "t.db")
    uid = "build-u2"
    world.enter(uid, store, "lantern-canal", [])
    try:
        world.observe({"type": "build_start"}, uid)
        world.observe({"type": "build_error", "message": "build cancelled"}, uid)
        lead = _lead(world.view(uid))
        assert not lead["busy"]
        assert not any(w["signal"] == "failed" for w in lead["why"])
        world.observe({"type": "build_start"}, uid)
        world.observe({"type": "build_error", "message": "the brain did not answer"}, uid)
        assert any(w["signal"] == "failed" for w in _lead(world.view(uid))["why"])
    finally:
        world.leave(uid)


def test_build_events_reach_every_scene_on_the_page():
    ws = (JS / "09-websocket.js").read_text()
    head = ws[ws.index("function handle(ev){"):][:300]
    assert "buildPulse(ev)" in head, "a build event must not stop at the Studio"
    fn = ws[ws.index("function buildPulse(ev)"):][:700]
    assert "worldHear(ev)" in fn
    assert "movementPulse('turn','build'" in fn and "movementPulse('tool'" in fn
    assert "movementPulse('turnend','build')" in fn
    hears = (JS / "01e-world.js").read_text()
    hears = hears[hears.index("var WORLD_HEARS"):][:300]
    for t in ("build_start", "build_done", "build_error"):
        assert f"'{t}'" in hears


def test_the_studio_draws_the_agents_face_not_a_glyph():
    studio = (JS / "26-studio.js").read_text()
    assert "'<b>▲ '" not in studio and "chatWho('@agent'" in studio


def test_faces_on_or_off_is_per_account():
    av = (JS / "00e-avatars.js").read_text()
    assert "function avatarsOffKey(uid){return 'avatars.off'+(uid?':'+uid:'')}" in av
    load = av[av.index("function avatarsLoad()"):][:800]
    assert "AVATARS.uid=uid" in load and "avatarsOffStored(uid)" in load
    off = av[av.index("function setAvatarsOff("):][:300]
    assert "avatarsOffKey(AVATARS.uid)" in off
    route = SERVER[SERVER.index('@app.get("/api/avatars")'):][:600]
    assert '"uid": usersmod.current()' in route


# "If Aria is working on something, why is it not showing on the desktop?" — a
# screenshot of a Claude Code build in progress, and Aria standing idle in the World
# with "started on a task" on her card but no "at work". Busy was remembered from
# events only, so it was lost when the scene's lease lapsed mid-build (a hidden tab
# beats once a minute) and when any chat turn ended while the build was running.

def test_busy_is_read_from_what_is_running(tmp_path):
    store = Store(tmp_path / "t.db")
    uid = "build-u3"
    running = {"@agent"}
    world.bind_working(lambda u, s: running if u == uid else set())
    try:
        world.enter(uid, store, "lantern-canal", ["researcher"])
        # entered mid-build: no build_start was ever heard, and the lead is at work
        assert _lead(world.view(uid))["busy"]
        # a chat turn ends while the build is still going
        world.observe({"type": "turn_start", "conversation_id": "c1"}, uid)
        world.observe({"type": "turn_end", "conversation_id": "c1"}, uid)
        assert _lead(world.view(uid))["busy"]
        assert world.busy_now(uid) == ["@agent"]
        running.clear()
        running.add("Researcher")              # a run's ref, matched without case
        v = world.view(uid)
        assert not _lead(v)["busy"]
        assert next(a for a in v["agents"] if a["name"] == "researcher")["busy"]
    finally:
        world.leave(uid)
        world.bind_working(None)


def test_the_server_says_who_is_working_and_the_heartbeat_carries_it(tmp_path):
    from agentos import server as servermod
    import asyncio
    store = Store(tmp_path / "t.db")
    loop = asyncio.new_event_loop()
    try:
        pending = loop.create_future()
        st = servermod.state
        saved = {k: st.get(k) for k in ("turns", "build")}
        st["turns"], st["build"] = {}, {}
        turns = st["turns"]
        turns["cw1"] = {"task": pending, "uid": "ada"}
        turns["cw2"] = {"task": pending, "uid": "ada", "speaker": "researcher"}
        turns["cw3"] = {"task": pending, "uid": "bob"}
        # and on what: the door the World's "…" bubble opens
        assert servermod._world_working("ada", store) == {
            "@agent": {"kind": "chat", "id": "cw1"}, "researcher": {"kind": "chat", "id": "cw2"}}
        turns.pop("cw1"), turns.pop("cw2")
        st["build"].update(task=pending, uid="ada")
        assert servermod._world_working("ada", store) == {"@agent": {"kind": "build", "id": ""}}
        assert set(servermod._world_working("bob", store)) == {"@agent"}
        turns.pop("cw3")
        assert servermod._world_working("bob", store) == {}
    finally:
        for k, v in saved.items():
            if v is None:
                st.pop(k, None)
            else:
                st[k] = v
        loop.close()
    assert "build[\"uid\"] = ws_uid" in SERVER
    beat = SERVER[SERVER.index('@app.post("/api/world/beat")'):][:400]
    assert "worldmod.busy_now(uid)" in beat
    page = (JS / "01e-world.js").read_text()
    page = page[page.index("async function worldBeat()"):][:1200]
    assert "d.busy" in page and "worldRefresh()" in page


def test_the_line_under_the_prompt_bar_counts_a_build():
    home = (JS / "01b-immersive.js").read_text()
    assert "var BUILD_LIVE=false;" in home
    fn = home[home.index("function homeRender(){"):][:3000]
    assert "BUILD_LIVE?'an app in App Studio'" in fn
    ws = (JS / "09-websocket.js").read_text()
    pulse = ws[ws.index("function buildPulse(ev)"):][:700]
    assert "BUILD_LIVE=ev.type==='build_start'" in pulse
    assert "BUILD_LIVE=!!ev.build_mine" in ws
    spin = ws[ws.index("function updateSpin(){"):][:600]
    assert "homeRender()" in spin, "the line follows a turn starting, not the minute timer"
    assert '"build_mine"' in SERVER
