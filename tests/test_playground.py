"""The playground off the Office: Chat, apps, Telegram, the terminal and setup.

What these defend:

- the tap hears only agents TALKING, only in a conversation somebody listens to, and
  every line keeps who spoke, to whom and what; a tap that is never closed has a
  ceiling;
- the comic painter draws the real characters (avatars.paint, never its own people),
  in the office's style, and never lets the picture carry words the caption does not:
  a script the pixel font cannot draw says "(below)" and the caption has every word;
- the roll call is read from the machine: busy is a run OPEN in fabric_runs (a stale
  one is a crash, not work), and a caller that cannot see the lead says so;
- Telegram: after a turn in which agents talked, one strip with the words in its
  caption; nothing extra when nobody talked or comics are off; /office is a picture;
- setup: the crew step creates the characters and the office, ticks on evidence,
  and the terminal walks the same code;
- the page: the play strip is fed by the one seam, only by events, and appears where
  the surface that shows the turn says.
"""
import asyncio
import os
import struct
import sys
import tempfile
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import avatars, comic, onboarding, playground            # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _png_size(b: bytes) -> tuple[int, int]:
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", b[16:24])


def _world(tmp_path):
    store = Store(tmp_path / "a.db")
    for n in ("researcher", "validator"):
        store.save_subagent({"name": n, "soul": n})
    return {"agent_name": "Aria", "office": {"style": "space", "name": "Orbit HQ"}}, store


def test_the_tap_hears_only_agents_talking_in_its_conversation():
    buf = playground.listen("c1")
    other = playground.listen("c2")
    playground.observe({"type": "agent_msg", "conversation_id": "c1", "phase": "ask",
                        "from": "researcher", "to": "validator", "text": "Is  this\ncurrent?"})
    playground.observe({"type": "agent_msg", "conversation_id": "c1", "phase": "reply",
                        "from": "validator", "to": "researcher", "text": "Yes."})
    playground.observe({"type": "agent_say", "conversation_id": "c1", "speaker": "writer", "text": "pass"})
    playground.observe({"type": "tool_start", "conversation_id": "c1", "name": "fetch_url"})
    playground.observe({"type": "agent_msg", "conversation_id": "c3", "phase": "ask", "from": "a", "to": "b", "text": "x"})
    assert [(x["speaker"], x["to"], x["kind"]) for x in buf] == [
        ("researcher", "validator", "ask"), ("validator", "researcher", "say"), ("writer", "", "say")]
    assert buf[0]["text"] == "Is this current?" and other == []
    assert playground.close("c1", buf) is buf and "c1" not in playground._TAPS
    for i in range(playground.MAX_LINES + 10):
        playground.observe({"type": "agent_say", "conversation_id": "c2", "speaker": "w", "text": str(i)})
    assert len(other) == playground.MAX_LINES, "a tap nobody closes has a ceiling"
    playground.close("c2", other)
    cap = playground.caption(buf)
    assert cap.splitlines()[0] == "researcher → validator: Is this current?"


def test_the_picture_never_carries_words_the_caption_does_not():
    assert comic.drawable("Café — “ok” ✅") == ('Cafe - "ok" ✓', True)
    s, whole = comic.drawable("नमस्ते दुनिया")
    assert not whole and s == "... ...", "another script is marked, never silently dropped"
    assert comic._say_lines("नमस्ते दुनिया, how are you", 24, 3) == ["(below)"]
    # a little lost is marked where it was, never dropped: the balloon must not say
    # a different sentence from the one that was said
    assert comic.drawable("hello 👋 there")[0] == "hello ... there"
    rows = comic.wrap("a " * 200, 20, 3)
    assert len(rows) == 3 and rows[-1].endswith("...")
    assert all(len(v) == 7 for v in comic.GLYPH.values())
    assert set(" !?.,:'\"-") <= set(comic.GLYPH), "the punctuation a sentence needs"


def test_the_strip_draws_the_real_people_in_the_office_style(tmp_path, monkeypatch):
    cfg, store = _world(tmp_path)
    painted = []
    real = avatars.paint
    monkeypatch.setattr(avatars, "paint", lambda rec, frame=0: painted.append(rec) or real(rec, frame))
    lines = [{"speaker": "researcher", "to": "validator", "text": "Is it current?", "kind": "ask"},
             {"speaker": "validator", "to": "researcher", "text": "Yes.", "kind": "say"}]
    w, h = _png_size(comic.strip(store, cfg, lines, "Orbit HQ · researcher asks validator"))
    assert w == (comic.GUTTER + 2 * (comic.PW + comic.GUTTER)) * comic.SCALE
    assert painted and painted[0] == avatars.recipe_for(store, "researcher"), "no second painter"
    src = (ROOT / "agentos/comic.py").read_text()
    assert "PIL" not in src and "import PIL" not in src, "stdlib only — no new dependency"


def test_busy_is_a_run_that_is_open_now(tmp_path):
    cfg, store = _world(tmp_path)
    now = time.time()
    store.db.execute("INSERT INTO fabric_runs(id,kind,ref,status,input,started_at) VALUES(?,?,?,?,?,?)",
                     ("r1", "delegate", "researcher", "running", "Find the churn numbers. Then more.", now - 5))
    store.db.execute("INSERT INTO fabric_runs(id,kind,ref,status,input,started_at) VALUES(?,?,?,?,?,?)",
                     ("r2", "delegate", "validator", "running", "stale", now - playground.STALE_S - 10))
    store.db.commit()
    rows = {r["key"]: r for r in playground.rollcall(store, cfg, lead_busy=True, now=now)}
    assert rows["researcher"]["working"] and rows["researcher"]["doing"] == "Find the churn numbers"
    assert not rows["validator"]["working"], "a run left open by a crash is not work"
    assert rows["@agent"]["working"]
    text = playground.rollcall_text(list(rows.values()))
    assert "researcher: busy — Find the churn numbers" in text and "2 of 3 at work" in text
    unknown = playground.rollcall(store, cfg, lead_busy=None, now=now)
    assert "not visible from here" in playground.rollcall_text(unknown)
    _png_size(comic.rollcall_image(store, cfg, list(rows.values()), "Orbit HQ"))


def test_telegram_sends_one_strip_when_agents_talked(tmp_path):
    from agentos.telegram import TelegramBridge
    cfg, store = _world(tmp_path)
    cfg["telegram"] = {"bot_token": "t", "owner_chat_id": 42}
    tg = TelegramBridge(cfg, store, toolbox=None, broadcast=None)
    sent = []

    async def fake_photo(png, caption="", chat_id=None):
        sent.append((png[:8], caption, chat_id))
        return "sent via Telegram"
    tg.send_photo = fake_photo
    lines = [{"speaker": "researcher", "to": "validator", "text": "नमस्ते — is it current?", "kind": "ask"}]
    asyncio.run(tg.send_talk([], 42))
    assert sent == [], "nobody talked: nothing extra"
    asyncio.run(tg.send_talk(lines, 42))
    assert len(sent) == 1 and sent[0][0] == b"\x89PNG\r\n\x1a\n"
    assert "नमस्ते — is it current?" in sent[0][1], "every word is in the caption"
    cfg["telegram"]["comics"] = False
    asyncio.run(tg.send_talk(lines, 42))
    assert len(sent) == 1, "switched off means off"


def test_telegram_office_is_a_picture_and_a_listed_command(tmp_path):
    from agentos import telegram_admin
    from agentos.telegram import TelegramBridge
    cfg, store = _world(tmp_path)
    cfg["telegram"] = {"bot_token": "t", "owner_chat_id": 42}
    tg = TelegramBridge(cfg, store, toolbox=None, broadcast=None)
    sent = []

    async def fake_photo(png, caption="", chat_id=None):
        sent.append(caption)
        return "sent via Telegram"
    tg.send_photo = fake_photo
    out = asyncio.run(tg._console._cmd_office(42, ""))
    assert out == "" and sent and "researcher" in sent[0]
    assert any(c == "/office" for c, _, _ in telegram_admin.COMMANDS)
    src = (ROOT / "agentos/telegram.py").read_text()
    assert "AGENTOS_TELEGRAM_API" in src and "_pg.listen(cid)" in src and "_pg.close(cid, tap)" in src


def test_setup_creates_the_crew_and_the_office(tmp_path):
    store = Store(tmp_path / "s.db")
    store.save_subagent({"name": "researcher", "soul": "r"})
    cfg = {"agent_name": "Aria"}
    step = next(s for s in onboarding.state(cfg, store)["steps"] if s["id"] == "crew")
    assert step["status"] == "todo" and step["blocked"] == []
    out = onboarding.crew(cfg, store, "garden", "The Greenhouse")
    keys = {p["key"] for p in out["people"]}
    assert {avatars.AGENT, avatars.ME, "researcher"} <= keys
    stored = {r["key"] for r in store.db.execute("SELECT key FROM avatars").fetchall()}
    assert {avatars.AGENT, avatars.ME, "researcher"} <= stored, "characters are STORED, not re-derived"
    step = next(s for s in onboarding.state(cfg, store)["steps"] if s["id"] == "crew")
    assert step["status"] == "done" and step["detail"] == "The Greenhouse · Greenhouse"
    from agentos import setup_tui
    assert setup_tui.HANDLERS["crew"] is setup_tui._step_crew
    ob = (JS / "14b-onboarding.js").read_text()
    assert "crew:s=>" in ob and "async crew()" in ob and "/api/office/setup" in ob
    assert "/api/office/rollcall.png" in ob, "the preview is the picture the phone gets"


def test_the_setup_routes(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        r = cl.get("/api/office/rollcall.png", params={"style": "night"})
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert cl.get("/api/office/rollcall.png", params={"style": "castle"}).status_code == 400
        r = cl.post("/api/office/setup", json={"style": "loft", "name": "Loft"})
        assert r.status_code == 200 and r.json()["office"]["office"]["style"] == "loft"


# ---- the page ----

def test_the_play_strip_is_fed_by_the_one_seam_and_only_by_events():
    mv = (JS / "01c-movement.js").read_text()
    seam = mv.split("function scenePulse(")[1].split("\n}")[0]
    assert "playPulse(kind,label,ev)" in seam
    ps = (JS / "24e-playstrip.js").read_text()
    assert "setInterval" not in ps and "Math.random" not in ps, "nothing idles for the look"
    assert "comicWord(" in ps and "avatarImg(" in ps and "/api/avatar.png" not in ps
    assert "function playEnd(" in ps and "s.el.remove()" in ps, "a strip of nothing is not kept"
    for f in JS.glob("*.js"):
        if f.name not in ("01c-movement.js", "24e-playstrip.js"):
            assert "playPulse(" not in f.read_text(), f"{f.name} calls the strip directly — use scenePulse"
    ws = (JS / "09-websocket.js").read_text()
    assert "playHost(_cid,()=>chatPlayHost(_cid))" in ws and "currentConv!==cid" in ws
    cp = (JS / "04a-copilot.js").read_text()
    assert "playHost(ev.conversation_id" in cp and "noStrip:!!panel.closest('.of-chat')" in cp
    assert "playWindowBurst(w,ev.name)" in cp


def test_one_vocabulary_of_comic_words():
    words = (JS / "00f-comic.js").read_text()
    assert "var COMIC_WORDS=" in words and "function comicWord(" in words
    of = (JS / "24d-office.js").read_text()
    assert "OF_WORDS" not in of and "comicWord(tool)" in of, "the Office reads the shared words"
    css = (ROOT / "agentos/ui/src/css/23b-playstrip.css").read_text()
    assert "prefers-reduced-motion" in css


# ---- the phone: WhatsApp carries the same pictures, and Snap ----

def _wa_cloud(cfg):
    cfg["channels"] = {"whatsapp": {"enabled": True, "phone_number_id": "123", "access_token": "tok",
                                    "verify_token": "v", "owner_wa_id": "4477"}}
    return cfg


def test_whatsapp_sends_the_picture_on_both_transports(tmp_path, monkeypatch):
    import httpx
    from agentos import whatsapp as wamod
    cfg, store = _world(tmp_path)
    _wa_cloud(cfg)
    wa = wamod.WhatsAppBridge(cfg, store, toolbox=None, broadcast=None)
    seen = []

    def handler(req):
        seen.append((req.url.path, req.headers.get("content-type", "").split(";")[0], req.content))
        if req.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-9"})
        return httpx.Response(200, json={"messages": [{"id": "m"}]})
    real = httpx.AsyncClient
    monkeypatch.setattr(wamod.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(wa, "window_open", lambda wa_id: True)
    png = comic.rollcall_image(store, cfg, playground.rollcall(store, cfg), "Orbit HQ")
    assert asyncio.run(wa.send_photo(png, "Orbit HQ right now")) == "sent via WhatsApp"
    # Cloud API: the bytes are uploaded first (no public URL here), then sent by media id
    assert seen[0][0] == "/v21.0/123/media" and seen[0][1] == "multipart/form-data"
    assert b'"id":"media-9"' in seen[1][2].replace(b" ", b"") and b'"type":"image"' in seen[1][2].replace(b" ", b"")
    # the same refusals as text: outside the 24-hour window an image is not a template either
    monkeypatch.setattr(wa, "window_open", lambda wa_id: False)
    assert "24 hours" in asyncio.run(wa.send_photo(png, "x"))
    # the linked device: one frame over stdio, addressed to the learned jid
    from agentos import wa_baileys
    link = wa_baileys.BaileysTransport.__new__(wa_baileys.BaileysTransport)
    frames = []

    async def write(obj):
        frames.append(obj)
        return True
    link.state, link.error, link.store, link._jids, link._write = "ready", "", store, {"4477": "99@lid"}, write
    assert asyncio.run(link.send_photo(png, "cap", "4477")) == "sent via WhatsApp"
    assert frames[0]["type"] == "image" and frames[0]["to"] == "99@lid" and frames[0]["caption"] == "cap"
    import base64
    assert base64.b64decode(frames[0]["data"])[:8] == b"\x89PNG\r\n\x1a\n"
    js = (ROOT / "agentos/wa_bridge/bridge.js").read_text()
    assert "cmd.type === 'image'" in js and "Buffer.from(String(cmd.data" in js


def test_whatsapp_office_and_strips_match_telegram():
    src = (ROOT / "agentos/whatsapp.py").read_text()
    assert 'low.startswith("/office")' in src and "async def send_talk(" in src
    assert "_pg.listen(cid)" in src and "_pg.close(cid, tap)" in src, "the tap is closed in finally"
    assert 'get("comics") is False' in src, "switched off the same way as Telegram"


def test_snap_goes_where_it_can_and_says_where_it_cannot(tmp_path):
    cfg, store = _world(tmp_path)

    class Phone:
        def __init__(self, answer):
            self.answer, self.got = answer, []

        async def send_photo(self, png, caption="", *_):
            self.got.append(caption)
            return self.answer
    tg, wa = Phone("sent via Telegram"), Phone("sent via WhatsApp")
    out = asyncio.run(playground.snap(cfg, store, tg, wa))
    assert out["sent"] == [] and any("Telegram is not set up" in n for n in out["notes"])
    assert any("WhatsApp is not set up" in n for n in out["notes"]), "nothing went: every reason is said"
    cfg["telegram"] = {"bot_token": "t", "owner_chat_id": 42}
    out = asyncio.run(playground.snap(cfg, store, tg, wa))
    assert out == {"sent": ["Telegram"], "notes": []}, "an unset channel is not nagged about when one worked"
    assert tg.got[0].startswith("Orbit HQ right now") and "researcher" in tg.got[0]
    out = asyncio.run(playground.snap(cfg, store, tg, wa, "whatsapp"))
    assert out["sent"] == [] and "WhatsApp is not set up" in out["notes"][0], "asked by name: said"
    _wa_cloud(cfg)
    out = asyncio.run(playground.snap(cfg, store, Phone("[error] telegram photo failed: 403"), wa))
    assert out["sent"] == ["WhatsApp"] and out["notes"] == ["telegram photo failed: 403"]
    # a linked device is held by the running server: the terminal says so, never tries
    cfg["channels"]["whatsapp"]["mode"] = "baileys"
    from agentos import whatsapp as wamod
    real = wamod.configured
    try:
        wamod.configured = lambda c: True
        out = asyncio.run(playground.snap(cfg, store, tg, None, "whatsapp"))
    finally:
        wamod.configured = real
    assert "held by the running server" in out["notes"][0]


def test_words_choose_from_the_closed_set_and_the_noun_wins():
    from agentos import office
    assert office.from_words("a cosy greenhouse called The Nursery, with a dog") == \
        {"style": "garden", "pet": "dog", "name": "The Nursery"}, "the noun follows its adjectives"
    assert office.from_words("a cosy space station")["style"] == "space"
    assert office.from_words("somewhere nice") == {}, "nothing named: nothing invented"


def test_the_office_can_be_designed_from_words_and_undone(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import executors, server as servermod

    async def silent(cfg, system, prompt, timeout=120):
        return "", ""
    monkeypatch.setattr(executors, "ask_once", silent)
    with TestClient(servermod.app) as cl:
        before = cl.get("/api/office").json()["office"]
        r = cl.post("/api/office/design", json={"description": "a space station called Orbit with a dog"})
        d = r.json()
        assert r.status_code == 200 and d["how"] == "words" and "matched the words" in d["said"]
        assert (d["office"]["style"], d["office"]["name"], d["office"]["pet"]) == ("space", "Orbit", "dog")
        assert cl.put("/api/office", json=d["previous"]).status_code == 200
        after = cl.get("/api/office").json()["office"]
        assert (after["style"], after["name"], after["pet"]) == (before["style"], before["name"], before["pet"])
        assert cl.post("/api/office/design", json={"description": "zz"}).status_code == 400

        async def brain(cfg, system, prompt, timeout=120):
            return '{"style": "night", "name": "Late Shift", "pet": "unicorn"}', "Claude Code"
        monkeypatch.setattr(executors, "ask_once", brain)
        d = cl.post("/api/office/design", json={"description": "somewhere for the night owls"}).json()
        assert d["how"] == "brain" and d["who"] == "Claude Code" and d["office"]["style"] == "night"
        assert d["office"]["pet"] != "unicorn" and any("pet" in x for x in d["dropped"]), "invented: dropped and named"
        cl.put("/api/office", json=d["previous"])
        r = cl.post("/api/office/snap", json={"to": "pigeon"})
        assert r.status_code == 400


def test_the_playground_has_a_door_on_every_face():
    home = (ROOT / "agentos/ui/src/js/01b-immersive.js").read_text()
    assert ".hm-play" in home and "avatarImg(p.key,'av-play')" in home
    assert "openApp('office')" in (ROOT / "agentos/ui/src/shell.html").read_text()
    dock = (ROOT / "agentos/ui/src/js/06-icon-layout.js").read_text()
    assert "'chat','office'" in dock and "dock-office" in dock, "added once, never forced back"
    of = (JS / "24d-office.js").read_text()
    assert "function officeDescribe(" in of and "/api/office/design" in of and "function officeSnap(" in of
    assert "Redesign my office:" not in of, "the design goes through the server, not a chat an executor answers"
    assert "officeSettingsPaint()" in (JS / "11-settings.js").read_text(), "Appearance has the Office"
    assert "officeDescribe(" in (JS / "14b-onboarding.js").read_text(), "and setup asks for it"
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert '"design", "snap", "picture"' in cli and "_pg.snap(" in cli
