"""The Stage on a phone is pictures in the chat, and a reply's markdown is formatted.

Reported as "the stage experience in Telegram is really bad": the story was one .html file to
download and open elsewhere (and a viewer that runs no script drew nothing), and every reply
showed its markdown stars. Each scene is now photographed by the Stage's own drawing code
(stagestill.py) and sent as an album with its words under each picture; replies go as
Telegram's HTML. With no browser to draw, the page is sent as before.
"""
import asyncio
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import stage, tgformat


def test_markdown_becomes_telegram_html():
    h = tgformat.to_html("## India\n**Kolkata:** a <b> & c\n- one\n* two\n`x*y*`\n[site](https://a.b/c?d=1&e=2)\n> quoted")
    assert "<b>India</b>" in h and "<b>Kolkata:</b> a &lt;b&gt; &amp; c" in h
    assert "• one" in h and "• two" in h and "<code>x*y*</code>" in h
    assert '<a href="https://a.b/c?d=1&amp;e=2">site</a>' in h and "<blockquote>quoted</blockquote>" in h
    assert tgformat.to_html("snake_case_name and 2*3*4") == "snake_case_name and 2*3*4"
    assert "<pre>a **b**</pre>" in tgformat.to_html("```py\na **b**\n```")
    long = ("word " * 400 + "\n\n") * 5
    parts = tgformat.chunks(long, 3000)
    assert all(len(p) <= 3000 for p in parts) and "".join(parts).split() == long.split()


def _bridge(tmp_path, fail_parse=False):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    b = TelegramBridge({"agent_name": "Aria", "telegram": {"enabled": True, "bot_token": "1:T",
                                                           "owner_chat_id": 5}},
                       Store(tmp_path / "a.db"), None, None)
    calls = []

    async def api(method, **kw):
        calls.append((method, kw))
        if fail_parse and kw.get("parse_mode"):
            raise RuntimeError("Bad Request: can't parse entities")
        return {}
    b._api = api
    return b, calls


def test_a_reply_is_formatted_and_never_lost(tmp_path):
    b, calls = _bridge(tmp_path)
    asyncio.run(b.send("**Hi**"))
    assert calls[-1][1]["parse_mode"] == "HTML" and calls[-1][1]["text"] == "<b>Hi</b>"
    b, calls = _bridge(tmp_path, fail_parse=True)
    assert asyncio.run(b.send("**Hi**")) == "sent via Telegram"
    assert calls[-1][1] == {"chat_id": 5, "text": "**Hi**"}


def _story(store):
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "show me the funnel")
    for spec in ({"kind": "steps", "title": "How", "items": ["a", "b"]},
                 {"kind": "chart", "title": "Funnel", "caption": "Few get out.", "source": "PhRMA",
                  "chart_type": "bar", "series": [{"points": [["in", 10], ["out", 1]]}]}):
        stage.add(store, cid, stage.clean(spec)[0])
    return cid


def test_the_story_goes_as_an_album_with_words_under_each(tmp_path, monkeypatch):
    from agentos import stagestill
    b, _ = _bridge(tmp_path)
    cid = _story(b.store)
    seen = {}

    async def render(html, cfg=None):
        seen["html"] = html
        return [b"png1", b"png2"]

    async def album(pngs, caps, chat_id=None):
        seen["album"] = (pngs, caps)
        return "sent via Telegram"

    async def doc(*a, **k):
        seen["doc"] = a
        return "sent via Telegram"
    monkeypatch.setattr(stagestill, "render", render)
    b.send_album, b.send_document = album, doc
    asyncio.run(b.send_stage(cid, "reply", 5))
    assert "window.STAGE_STILL=true" in seen["html"] and "still-card" in seen["html"]
    pngs, caps = seen["album"]
    assert pngs == [b"png1", b"png2"] and caps[0] == "1/2 · How"
    assert caps[1] == "2/2 · Funnel\nFew get out.\nSource: PhRMA" and "doc" not in seen

    async def none(html, cfg=None):
        return []                                  # no browser here: the page, as before
    monkeypatch.setattr(stagestill, "render", none)
    seen.clear()
    asyncio.run(b.send_stage(cid, "reply", 5))
    assert "album" not in seen and seen["doc"][0].endswith(".html")


@pytest.mark.skipif(not shutil.which("google-chrome") and not shutil.which("chromium")
                    and not shutil.which("chromium-browser"), reason="no Chromium here")
def test_a_real_browser_draws_one_picture_per_scene(tmp_path):
    from agentos.memory import Store
    from agentos import stagestill
    store = Store(tmp_path / "a.db")
    cid = _story(store)
    html = stage.report_html(store, cid, stage.last_question(store, cid), agent="Aria", still=True)
    pngs = asyncio.run(stagestill.render(html))
    assert len(pngs) == 2 and all(p[:8] == b"\x89PNG\r\n\x1a\n" and len(p) > 20000 for p in pngs)
