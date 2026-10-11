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
