"""A phone hears at once that its blueprint is being drawn.

Reported as "when I ask for a blueprint on Telegram it shows the stage on the desktop but not on
Telegram". Measured on the owner's machine: the reply came at 12:20:40, the desktop drew the
outline then, and Telegram's nine pictures arrived at 12:23:43. In between the phone showed
nothing, not even the reply, while the parts were looked up (bpfill, `PHONE_WAIT_S`).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import bpfill, stage, stagestill  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from test_telegram_stage import _bridge as _tg  # noqa: E402
from test_whatsapp_stage import _bridge as _wa, _blueprint  # noqa: E402


def _filling(monkeypatch, store, cid, secs):
    """Make this chat's blueprint look as if it is still being filled for `secs` seconds."""
    ids = [r["id"] for r in stage.story(store, cid, stage.last_question(store, cid))]

    async def run():
        async def slow():
            await asyncio.sleep(secs)
        for i in ids:
            t = asyncio.ensure_future(slow())
            bpfill._TASKS[i] = t
            t.add_done_callback(lambda _t, i=i: bpfill._TASKS.pop(i, None))
    return run


def test_telegram_says_so_at_once_and_shows_it_is_sending_a_photo(tmp_path, monkeypatch):
    b, calls = _tg(tmp_path)
    cid = _blueprint(b.store)
    start = _filling(monkeypatch, b.store, cid, 0.3)

    async def render(html, cfg=None):
        return []
    monkeypatch.setattr(stagestill, "render", render)

    async def doc(*a, **k):
        return "sent via Telegram"
    b.send_document = doc

    async def go():
        await start()
        await b.send_stage(cid, "reply", 5)
    asyncio.run(go())
    methods = [m for m, _ in calls]
    first = next(kw for m, kw in calls if m == "sendMessage")
    assert "Drawing your blueprint" in first["text"] and "my answer" in first["text"]
    assert ("sendChatAction", {"chat_id": 5, "action": "upload_photo"}) in calls
    assert methods.index("sendMessage") < methods.index("sendChatAction")


def test_nothing_filling_says_nothing_extra(tmp_path, monkeypatch):
    b, calls = _tg(tmp_path)
    cid = _blueprint(b.store)

    async def render(html, cfg=None):
        return []
    monkeypatch.setattr(stagestill, "render", render)

    async def doc(*a, **k):
        return "sent via Telegram"
    b.send_document = doc
    asyncio.run(b.send_stage(cid, "reply", 5))
    assert not [kw for m, kw in calls if m == "sendMessage" and "Drawing" in kw.get("text", "")]


def test_whatsapp_says_so_before_it_waits(tmp_path, monkeypatch):
    b = _wa(tmp_path)
    cid = _blueprint(b.store)
    start = _filling(monkeypatch, b.store, cid, 0.2)
    said = []

    async def send(text, wa_id=None):
        said.append(text)
        return "sent via WhatsApp"
    b.send = send

    async def render(html, cfg=None):
        return []
    monkeypatch.setattr(stagestill, "render", render)

    async def go():
        await start()
        await b.send_stage(cid, "reply", "44")
    asyncio.run(go())
    assert said and "Drawing your blueprint" in said[0] and "my answer" not in said[0]
    assert bpfill.filling(["nope"]) == 0
