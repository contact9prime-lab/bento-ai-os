"""A story reaches WhatsApp as pictures, and a blueprint as its walk-through and its PDF.

Reported as "blueprints and stages are not coming on whatsapp". The Telegram side had behaviour
tests; WhatsApp had only a grep, so this drives `send_stage` through a stand-in linked device.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import bpfill, stage, stagestill, whatsapp  # noqa: E402
from agentos.memory import Store  # noqa: E402


class _Link:
    def __init__(self):
        self.sent = []

    async def send_photo(self, png, cap, wa_id):
        self.sent.append(("photo", png, cap, wa_id))
        return "sent via WhatsApp"

    async def send_document(self, path, cap, wa_id):
        self.sent.append(("doc", Path(path).name, cap, wa_id))
        return "sent via WhatsApp"


def _bridge(tmp_path):
    store = Store(tmp_path / "a.db")
    cfg = {"agent_name": "Aria", "whatsapp": {"mode": "baileys", "enabled": True, "owner_wa_id": "44"}}

    async def bc(ev):
        pass
    b = whatsapp.WhatsAppBridge(cfg, store, None, bc)
    b.link = _Link()
    return b


def _blueprint(store):
    cid = store.create_conversation("WhatsApp · me", origin="whatsapp")
    store.add_message(cid, "user", "blueprint of a jet engine")
    sc, _ = stage.clean({"kind": "blueprint", "title": "Jet engine", "source": "maker",
                         "parts": [{"name": "Fan", "parts": [{"name": "Blades"}]},
                                   {"name": "Core", "parts": [{"name": "Burner"}]}]})
    stage.add(store, cid, sc)
    return cid


def test_a_blueprint_goes_as_its_walk_through_then_its_sheets(tmp_path, monkeypatch):
    b = _bridge(tmp_path)
    cid = _blueprint(b.store)
    n = len(stage.still_items([r["scene"] for r in stage.story(b.store, cid, stage.last_question(b.store, cid))]))

    async def render(html, cfg=None):
        assert "window.STAGE_STILL=true" in html
        return [b"png"] * n

    async def settle(ids, wait):
        return None

    async def to_file(store, cfg, sid, folder, agent, question):
        p = tmp_path / "jet-engine-blueprint.pdf"
        p.write_bytes(b"%PDF")
        return p
    from agentos import bpdoc
    monkeypatch.setattr(stagestill, "render", render)
    monkeypatch.setattr(bpfill, "settle", settle)
    monkeypatch.setattr(bpdoc, "to_file", to_file)
    asyncio.run(b.send_stage(cid, "here it is", "44"))
    photos = [s for s in b.link.sent if s[0] == "photo"]
    docs = [s for s in b.link.sent if s[0] == "doc"]
    assert n >= 3 and len(photos) == n, "the drawing, the parts, each main part"
    assert photos[0][2].startswith("▶ blueprint of a jet engine\n\n1/"), "the question on top"
    assert docs and docs[0][1] == "jet-engine-blueprint.pdf" and all(s[3] == "44" for s in b.link.sent)


def test_no_browser_sends_the_page_and_no_link_says_why(tmp_path, monkeypatch):
    b = _bridge(tmp_path)
    cid = _blueprint(b.store)

    async def none(html, cfg=None):
        return []

    async def settle(ids, wait):
        return None
    monkeypatch.setattr(stagestill, "render", none)
    monkeypatch.setattr(bpfill, "settle", settle)
    asyncio.run(b.send_stage(cid, "here it is", "44"))
    assert [s[0] for s in b.link.sent] == ["doc"] and b.link.sent[0][1].endswith(".html")
    b.link = None
    assert "not running" in asyncio.run(b.send_photo(b"x", "c", "44"))


def test_a_list_called_a_blueprint_is_told_to_be_one(tmp_path):
    """Seen on Telegram: "Can you build a blueprint" was answered with a steps scene titled
    "Blueprint: the seven layers of a quantum computer". The tool's answer now says so."""
    from agentos.tools import Toolbox
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "can you build a blueprint")
    tb = Toolbox({}, store)
    out = asyncio.run(tb.show_scene(kind="steps", title="Blueprint: the seven layers", items=["a", "b"], _conv=cid))
    assert "not a blueprint" in out and "kind blueprint" in out
    ok = asyncio.run(tb.show_scene(kind="steps", title="How it runs", items=["a", "b"], _conv=cid))
    assert "not a blueprint" not in ok
