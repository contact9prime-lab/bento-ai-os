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
    assert pngs == [b"png1", b"png2"] and caps[0] == "▶ show me the funnel\n\n1/2 · How", "the question on top"
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


def test_a_map_says_what_happened_at_each_place():
    """The owner's India news map came through as pins with lines between them and nothing
    about what happened anywhere: the agent HAD written a note per place, and the map showed
    notes only on hover. Lines between unrelated places read as a route nobody took."""
    sc, dropped = stage.clean({"kind": "map", "title": "India today", "source": "DT Next",
                               "points": [{"lat": 22.57, "lon": 88.36, "label": "Kolkata",
                                           "note": "stampede: 19 dead"},
                                          {"lat": 13.08, "lon": 80.27, "label": "Chennai",
                                           "note": "red alert for rain"}]})
    assert not dropped and sc["route"] is False
    cap = stage.still_caption(sc, 0, 1)
    assert "1. Kolkata: stampede: 19 dead" in cap and "2. Chennai: red alert for rain" in cap
    assert stage.clean({"kind": "map", "points": [{"lat": 1, "lon": 2, "label": "a"}],
                        "route": True})[0]["route"] is True
    js = (Path(__file__).parent.parent / "agentos/ui/src/js/24l-stage.js").read_text()
    assert "if(sc.route&&pts.length>=2" in js, "lines only for a journey"
    assert "'st-mapnotes'" in js and "st-pinno" in js, "numbered pins, notes listed under the map"
    big = stage.BIG_LINE
    assert "END on what it means for this person" in big and "never a label" in big
    assert "give every point a note" in big


def test_the_story_comes_first_and_is_told_aloud(tmp_path, monkeypatch):
    from agentos import speech
    b, calls = _bridge(tmp_path)
    src = (Path(__file__).parent.parent / "agentos/telegram.py").read_text()
    turn = src[src.index("await self.send_stage(cid, reply, chat_id)") - 300:][:600]
    assert turn.index("send_stage(") < turn.index("self.send(reply, chat_id)"), "the pictures, then the words"
    scenes = [{"kind": "map", "title": "India today", "say": "Here is India today."},
              {"kind": "numbers", "title": "Toll", "caption": "Nineteen dead in Kolkata"}]
    # the browser voice lives in a browser: nothing is sent
    assert asyncio.run(b.send_narration(scenes, 5)) == ""
    b.cfg["speech"] = {"engine": "openai"}
    said = {}

    async def speak(cfg, text, agent="", lead=False, **k):
        said["text"] = text
        return b"ID3audio", "audio/mpeg", {}
    monkeypatch.setattr(speech, "speak", speak)

    class R:
        def json(self):
            return {"ok": True}

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None, files=None):
            said["url"], said["file"] = url, files["audio"][0]
            return R()
    import agentos.telegram as tgmod
    monkeypatch.setattr(tgmod.httpx, "AsyncClient", C)
    assert asyncio.run(b.send_narration(scenes, 5)) == "sent"
    assert said["text"] == "Here is India today. Nineteen dead in Kolkata."
    assert said["url"].endswith("/sendAudio") and said["file"] == "story.mp3"
