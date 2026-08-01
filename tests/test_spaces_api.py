"""The HTTP surface for spaces, assets, the timeline and the ledger.

Kept separate from test_spaces.py: that one is about the storage rules, this one is
about the promises the API makes to the UI and to scripts.
"""

import base64
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
# Set before importing agentos, the way every other server test does: the config
# module resolves AGENTOS_HOME at import time. Reaching for sys.modules surgery
# instead would leak a second copy of every agentos module into the session and
# break identity checks in unrelated tests.
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from fastapi.testclient import TestClient                          # noqa: E402

from agentos import server as servermod                            # noqa: E402

PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
           "hKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture()
def client(tmp_path):
    """A live app on a fresh database. Spaces and assets are wiped between tests so
    each one states its own preconditions."""
    with TestClient(servermod.app) as c:
        store = servermod.state["store"]
        for table in ("spaces", "assets", "timeline_events", "audit", "memories",
                      "kg_edges", "kg_nodes", "logs"):
            store.db.execute(f"DELETE FROM {table}")
        store.db.commit()
        servermod.state["cfg"].setdefault("spaces", {})["active"] = {}
        yield c


def test_a_space_round_trips(client):
    r = client.post("/api/spaces", json={"name": "Q3 launch", "description": "the launch"})
    assert r.status_code == 200
    sid = r.json()["id"]
    assert [s["name"] for s in client.get("/api/spaces").json()["spaces"]] == ["Q3 launch"]
    assert client.post("/api/spaces/activate",
                       json={"space_id": sid, "surface": "gui"}).json()["name"] == "Q3 launch"


def test_a_space_needs_a_name(client):
    assert client.post("/api/spaces", json={"name": "  "}).status_code == 400


def test_activating_an_unknown_space_is_refused(client):
    assert client.post("/api/spaces/activate",
                       json={"space_id": "nope", "surface": "gui"}).status_code == 404


def test_deleting_a_space_demands_a_disposition(client):
    sid = client.post("/api/spaces", json={"name": "X"}).json()["id"]
    bad = client.delete(f"/api/spaces/{sid}?contents=nonsense")
    assert bad.status_code == 400
    assert "archive" in bad.json()["error"]      # says what the valid answers are
    ok = client.delete(f"/api/spaces/{sid}?contents=archive")
    assert ok.json()["disposition"] == "archive"


def test_deleting_the_active_space_leaves_no_dangling_filter(client):
    """A surface still pointing at a deleted space would filter everything out."""
    sid = client.post("/api/spaces", json={"name": "X"}).json()["id"]
    client.post("/api/spaces/activate", json={"space_id": sid, "surface": "gui"})
    client.delete(f"/api/spaces/{sid}?contents=delete")
    assert client.get("/api/spaces").json()["active"].get("gui", "") == ""


def test_an_inline_upload_becomes_a_servable_asset(client):
    sid = client.post("/api/spaces", json={"name": "S"}).json()["id"]
    r = client.post("/api/assets", json={"data_url": "data:image/png;base64," + PNG_B64,
                                         "title": "hero", "space_id": sid})
    assert r.status_code == 200
    a = r.json()["asset"]
    assert a["kind"] == "image" and a["space_id"] == sid
    assert "path" not in a          # absolute paths never leave the machine
    f = client.get(a["url"])
    assert f.status_code == 200 and f.headers["content-type"] == "image/png"
    assert f.content == base64.b64decode(PNG_B64)


def test_a_malformed_upload_is_refused_with_a_reason(client):
    r = client.post("/api/assets", json={"data_url": "not-a-data-url"})
    assert r.status_code == 400 and "data_url" in r.json()["error"]


def test_a_large_file_streams_in_over_raw_put(client):
    r = client.put("/api/assets/raw?name=clip.bin", content=b"x" * 200_000,
                   headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    assert r.json()["asset"]["bytes"] == 200_000


def test_an_asset_is_addressed_by_id_never_by_path(client):
    """There is no caller-supplied path anywhere in the asset routes, so there is
    nothing to traverse."""
    assert client.get("/api/assets/../../etc/passwd/file").status_code in (404, 400)
    assert client.get("/api/assets/nope/file").status_code == 404
    assert client.get("/api/assets/nope").status_code == 404


def test_assets_are_scoped_the_same_way_everything_else_is(client):
    a = client.post("/api/spaces", json={"name": "A"}).json()["id"]
    b = client.post("/api/spaces", json={"name": "B"}).json()["id"]
    client.post("/api/assets", json={"data_url": "data:image/png;base64," + PNG_B64,
                                     "space_id": a, "title": "in-a"})
    client.put("/api/assets/raw?name=global.bin", content=b"g" * 10,
               headers={"Content-Type": "application/octet-stream"})
    in_a = [x["title"] for x in client.get(f"/api/assets?space={a}").json()["assets"]]
    in_b = [x["title"] for x in client.get(f"/api/assets?space={b}").json()["assets"]]
    assert "in-a" in in_a
    assert "in-a" not in in_b
    assert "global.bin" in in_a and "global.bin" in in_b   # global is visible from both


def test_the_capability_endpoint_names_its_component(client, monkeypatch):
    from agentos import assets as assetmod
    monkeypatch.setattr(assetmod, "ffmpeg_path", lambda: "")
    monkeypatch.setattr(assetmod, "ffprobe_path", lambda: "")
    cap = client.get("/api/media/capability").json()
    assert cap["ffmpeg"] is False
    assert cap["component"] == "ffmpeg"
    assert cap["why"] and cap["licence"]          # the licence is in view before installing


def test_the_timeline_records_what_was_made(client):
    sid = client.post("/api/spaces", json={"name": "S"}).json()["id"]
    client.post("/api/assets", json={"data_url": "data:image/png;base64," + PNG_B64,
                                     "space_id": sid})
    kinds = [e["kind"] for e in client.get(f"/api/timeline?space={sid}").json()["events"]]
    assert "asset" in kinds and "space" in kinds


def test_the_ledger_is_readable_over_http(client):
    d = client.get("/api/audit?limit=5")
    assert d.status_code == 200 and isinstance(d.json()["entries"], list)
    s = client.get("/api/audit/summary")
    assert set(s.json()) >= {"effects", "top_denied", "by_surface", "total"}
