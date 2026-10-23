"""Faces for this machine's own screen (agentos/faces.py, 24q-kioskfaces.js).

Asked for from a Pi's kiosk: "different faces and widgets so I can add or build", "some cool
widgets". A face is a layout and its widgets, read field by field: an unknown widget or layout is
dropped and named, a built-in face is never overwritten, and an app's widget is only one of your
apps. The page stops the Office scene while a widget face shows (a Pi 3 drawing a canvas nobody
sees is what this screen was made light to avoid) and ticks every widget on one timer."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import faces  # noqa: E402

ROOT = Path(__file__).parent.parent


def test_built_in_faces_and_the_one_worn():
    cfg = {}
    st = faces.state(cfg)
    assert [f["id"] for f in st["faces"]] == ["chat", "office", "clock", "board", "ambient"]
    assert st["current"] == "chat", "the kiosk as it was, until somebody chooses"
    faces.use(cfg, "board")
    assert faces.current(cfg) == "board"
    with pytest.raises(ValueError):
        faces.use(cfg, "nope")


def test_your_own_face_is_read_field_by_field():
    cfg = {}
    face, dropped = faces.save(cfg, {"name": "Kitchen", "layout": "board",
                                     "widgets": ["clock", "timer", "bogus", "app:notes", "app:gone", "clock"]},
                               app_ids=["notes"])
    assert face["widgets"] == ["clock", "timer", "app:notes"]
    assert "widget 'bogus'" in dropped and "widget 'app:gone'" in dropped
    face2, dropped2 = faces.save(cfg, {"name": "Weird", "layout": "spaceship", "widgets": ["clock"]})
    assert face2["layout"] == "board" and "layout 'spaceship'" in dropped2
    clash, _ = faces.save(cfg, {"name": "Clock", "layout": "clock", "widgets": ["clock"]})
    assert clash["id"] == "my-clock", "a built-in face is never overwritten"
    assert any(f["id"] == "clock" and f["builtin"] for f in faces.faces(cfg))
    with pytest.raises(ValueError):
        faces.save(cfg, {"name": "", "widgets": []})
    many, _ = faces.save(cfg, {"name": "Lots", "widgets": list(faces.WIDGETS) + ["clock"]})
    assert len(many["widgets"]) <= faces.MAX_WIDGETS


def test_removing_the_worn_face_goes_back_to_chat():
    cfg = {}
    f, _ = faces.save(cfg, {"name": "Desk", "layout": "clock", "widgets": ["clock"]})
    faces.use(cfg, f["id"])
    assert faces.delete(cfg, f["id"]) and faces.current(cfg) == "chat"
    assert not faces.delete(cfg, "board"), "a built-in face stays"


def test_the_route_is_the_machines_and_the_page_is_light():
    from fastapi.testclient import TestClient
    from agentos import server
    with TestClient(server.app) as cl:
        st = cl.get("/api/face/faces").json()
        assert st["current"] and any(w["id"] == "timer" for w in st["widgets"])
        r = cl.put("/api/face/faces", json={"save": {"name": "Hall", "layout": "board", "widgets": ["clock", "x"]}}).json()
        assert r["current"] == "hall" and r["dropped"] == ["widget 'x'"]
        cl.put("/api/face/faces", json={"delete": "hall"})
        assert "temp_c" in cl.get("/api/system").json()
    js = (ROOT / "agentos/ui/src/js/24q-kioskfaces.js").read_text()
    assert "officeSceneStop" in js, "the Office stops while a widget face shows"
    assert js.count("setInterval(") == 1, "one timer for every widget"
    assert 'sandbox="allow-scripts allow-forms"' in js and "allow-same-origin" not in js
