"""Changing a machine's screen from Devices and from chat (screen_face, /api/network/ties/…/faces,
wire op zero_face). Asked for as "can I change the widget on the Pi from Devices and chat".

A turn in a Zero's section (its chat, worked on the hub) may change only that Zero's screen,
whatever the model named: the server reads it from the section, never from the arguments."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

ROOT = Path(__file__).parent.parent


def test_the_tool_changes_this_screen_and_says_what_it_can(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server
    with TestClient(server.app) as cl:
        tb = server.state["toolbox"]
        said = cl.portal.call(tb.screen_face)
        assert "wears" in said and "board" in said and "timer" in said, said
        got = cl.portal.call(lambda: tb.screen_face(new_face={"name": "Desk", "layout": "board",
                                                              "widgets": ["clock", "timer", "bogus"]}))
        assert "wears 'Desk'" in got and "bogus" in got, got
        assert cl.get("/api/face/faces").json()["current"] == "desk"
        cl.portal.call(lambda: tb.screen_face(remove="desk"))
        assert cl.get("/api/face/faces").json()["current"] == "chat"


def test_a_zeros_chat_changes_only_its_own_screen(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import provision, server
    with TestClient(server.app):
        monkeypatch.setattr(provision, "load", lambda: {"enabled": {"fp1": {"label": "kitchen-pi", "space": "s-kitchen",
                                                                            "execution": "hub"}}, "keys": [], "devices": {}})
        got = asyncio.run(server._screen_tool("garage-pi", {"use": "clock"}, "s-kitchen"))
        assert not got["ok"] and "only kitchen-pi's own screen" in got["error"]
        got = asyncio.run(server._screen_tool("", {}, "s-kitchen"))
        assert not got["ok"] and "kitchen-pi" in got["error"], "it goes to its own Zero, which isn't linked here"


def test_the_doors_and_the_gate():
    from agentos import executors, fabric, policy, tools
    assert "screen_face" in fabric.ZERO_CHAT_TOOLS and "screen_face" in executors.TEAM_TOOLS
    assert "screen_face" in tools.SPACE_SCOPED_TOOLS, "the section is how its own screen is known"
    assert policy.action_of("screen_face", {"machine": "pi"}) == ("face.write", "screen:pi")
    srv = (ROOT / "agentos/server.py").read_text()
    for r in ('@app.get("/api/network/ties/{label}/faces")', '@app.put("/api/network/ties/{label}/faces")'):
        body = srv[srv.index(r):]
        body = body[:body.index("\n@app.")]
        assert "_require_admin()" in body
    h = srv[srv.index('if req.get("op") == "zero_face":'):]
    assert "is_my_hub" in h[:400], "only its own hub changes a Zero's screen"
    js = (ROOT / "agentos/ui/src/js/24p-ties.js").read_text()
    assert "tieScreenHTML" in js and "{build:false}" in js
