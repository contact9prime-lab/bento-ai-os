"""The MCP media bridge and the asset store.

The regression this file exists to prevent: MCPManager.call() used to render every
non-text content block as the literal string "[image]". Every media MCP — anything
that draws, speaks or renders — reported success while handing back nothing. If
"[image]" ever comes back from a call again, these tests fail.
"""

import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import assets as assetmod                             # noqa: E402
from agentos.agent import _media_result                            # noqa: E402
from agentos.mcp_client import MCPManager                          # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.tools import _truncate_envelope                       # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 256


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Image:
    type = "image"

    def __init__(self, raw=PNG, mime="image/png"):
        self.data = base64.b64encode(raw).decode()
        self.mimeType = mime


class _Resource:
    """An EmbeddedResource carrying a blob — the other shape servers really send."""
    type = "resource"

    def __init__(self, raw, mime):
        self.resource = type("R", (), {"blob": base64.b64encode(raw).decode(),
                                       "mimeType": mime})()


def _manager(tmp_path, blocks, home, is_error=False):
    assetmod.ASSETS_ROOT = home / "assets"
    assetmod.THUMBS_ROOT = home / "assets" / ".thumbs"
    store = Store(tmp_path / "t.db")
    result = type("Res", (), {"content": blocks, "isError": is_error})()
    session = type("S", (), {"call_tool": staticmethod(
        lambda tool, args: asyncio.sleep(0, result=result))})()
    mgr = MCPManager({}, store)
    mgr.servers["srv"] = type("Srv", (), {"status": "connected", "session": session})()
    return mgr, store


def test_an_image_becomes_an_asset_not_the_string_image(tmp_path):
    mgr, store = _manager(tmp_path, [_Text("here you go"), _Image()], tmp_path)
    out = asyncio.run(mgr.call("srv", "generate_image", {"prompt": "a cat"},
                               context={"conversation_id": "c1", "space_id": "s1"}))
    assert "[image]" not in out, "the discard regression is back"
    rows = store.asset_list()
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "image"
    assert row["mime"] == "image/png"
    assert row["source"] == "mcp:srv/generate_image"
    assert row["conversation_id"] == "c1" and row["space_id"] == "s1"
    assert row["prompt"] == "a cat"          # provenance, not just bytes
    assert Path(row["path"]).is_file()


def test_the_agent_sees_text_and_the_image_is_attached(tmp_path):
    mgr, _ = _manager(tmp_path, [_Text("here you go"), _Image()], tmp_path)
    out = asyncio.run(mgr.call("srv", "draw", {}, context={}))
    text, image_path = _media_result(out)
    assert "here you go" in text
    assert image_path and Path(image_path).is_file()


def test_video_is_kept_but_never_attached_as_an_image(tmp_path):
    """No provider path can carry video bytes. Attaching it would be a silent
    no-op dressed up as vision; the asset id in the text is the honest answer."""
    mgr, store = _manager(tmp_path, [_Resource(MP4, "video/mp4")], tmp_path)
    out = asyncio.run(mgr.call("srv", "render", {}, context={}))
    text, image_path = _media_result(out)
    assert image_path == ""
    assert store.asset_list()[0]["kind"] == "video"
    assert "asset" in text


def test_identical_bytes_are_stored_once(tmp_path):
    mgr, store = _manager(tmp_path, [_Image()], tmp_path)
    asyncio.run(mgr.call("srv", "draw", {}, context={}))
    asyncio.run(mgr.call("srv", "draw", {}, context={}))
    assert len(store.asset_list()) == 1


def test_a_block_with_no_payload_says_so(tmp_path):
    empty = type("E", (), {"type": "annotation"})()
    mgr, store = _manager(tmp_path, [empty], tmp_path)
    out = asyncio.run(mgr.call("srv", "x", {}, context={}))
    assert "no data" in out
    assert store.asset_list() == []


def test_an_error_result_stays_an_error(tmp_path):
    mgr, _ = _manager(tmp_path, [_Text("boom")], tmp_path, is_error=True)
    out = asyncio.run(mgr.call("srv", "x", {}, context={}))
    assert out.startswith("[error]")


def test_truncation_never_shreds_the_envelope(tmp_path):
    """Cutting a media envelope at a byte count would lose the asset ids — the one
    part of the result that has to survive."""
    mgr, _ = _manager(tmp_path, [_Text("x" * 50000), _Image()], tmp_path)
    out = asyncio.run(mgr.call("srv", "draw", {}, context={}))
    cut = _truncate_envelope(out, limit=200)
    import json
    parsed = json.loads(cut)          # still valid JSON
    assert parsed["__media__"][0]["asset_id"]
    assert "truncated" in parsed["text"]


def test_capability_reports_why_and_which_component(monkeypatch):
    """A missing capability is a sentence naming its fix, never a bare False."""
    monkeypatch.setattr(assetmod.shutil, "which", lambda *a, **k: None)
    cap = assetmod.capability()
    assert cap["ffmpeg"] is False
    assert cap["component"] == "ffmpeg"
    assert "ffmpeg is not installed" in cap["why"]
    assert "cannot" in cap["why"]          # says what is lost, not just that it is missing


def test_ffmpeg_is_offered_never_shipped():
    """It is GPL. The catalogue may offer it with the licence in view; the packaged
    dependency set may never contain it."""
    from agentos import components
    entry = components.CATALOG["ffmpeg"]
    assert entry["group"] == "optional"
    assert "GPL" in entry["licence"]
    assert entry["unlocks"] and "without it" in entry["unlocks"].lower()
    audit = (Path(__file__).parent.parent / "packaging" / "audit-licenses.sh").read_text()
    shipped = audit.split("SHIPPED=(")[1].split(")")[0]
    assert "ffmpeg" not in shipped


def test_deleting_an_asset_removes_the_file(tmp_path):
    assetmod.ASSETS_ROOT = tmp_path / "assets"
    assetmod.THUMBS_ROOT = tmp_path / "assets" / ".thumbs"
    store = Store(tmp_path / "t.db")
    row = asyncio.run(assetmod.put_bytes(store, PNG, name="a.png", source="test"))
    path = Path(row["path"])
    assert path.is_file()
    assert assetmod.delete(store, row["id"])
    assert not path.exists()
    assert store.asset_get(row["id"]) is None


def test_a_row_whose_file_vanished_reports_missing_rather_than_raising(tmp_path):
    assetmod.ASSETS_ROOT = tmp_path / "assets"
    assetmod.THUMBS_ROOT = tmp_path / "assets" / ".thumbs"
    store = Store(tmp_path / "t.db")
    row = asyncio.run(assetmod.put_bytes(store, PNG, name="a.png", source="test"))
    Path(row["path"]).unlink()
    assert assetmod.path_of(store.asset_get(row["id"])) is None
