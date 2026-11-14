"""The sign-in link: a page the browser is stuck on, opened on the phone you're holding.

Asked for with a screenshot of Aria giving up on a GitHub sign-in ("it can only be done at the
machine, not from Telegram"), then: "bento should give the link to open it on the phone directly
… prompted about and via permission … if granted open it only for the session to key in".

Pinned here, each one a way this could go wrong:

- it is offered in words that say what opening it does, and only where the machine allows it;
- no agent can open one: there is no tool, and the switch is not the agent's to change;
- reading the link opens nothing (a chat app's preview is a GET); the page's own POST binds it
  to one device, and a second device is refused and reported;
- the page stays shut until the CHAT says the device is theirs, and "no" closes it;
- a phone already signed in to this Bento as the same person skips that question;
- the phone can type and tap, and can't navigate or touch another tab;
- it ends on Done, when the wall is gone, when nobody opened it in time, and the temporary door
  goes with it;
- the link is never written to the diary, and goes to Telegram as plain text.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import httpx
import pytest
import websockets

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import cdpbrowser, handoff   # noqa: E402

CFG = {"agent_name": "Aria", "port": 8321, "handoff": {"enabled": True, "port": 18327}}


class _FakeBrowser:
    """Enough of a Browser for a hand-off: a wall, viewers, a size, and what the person did."""
    running = True
    uid = ""

    def __init__(self, kind="login", site="github.com"):
        self.attention = {"kind": kind, "site": site, "reason": "to push the branch"}
        self.size = (1280, 800)
        self.did, self.viewers, self.states = [], {}, 0

    async def person(self, op):
        self.did.append(op)
        if op.get("type") == "resume":
            self.attention = None

    async def add_viewer(self, send_bytes, send_json, w=0, h=0):
        vid = len(self.viewers) + 1
        self.viewers[vid] = (send_bytes, send_json)
        if w and h:
            self.size = (w, h)
        await send_json({"type": "state", "size": list(self.size), "url": "https://github.com/login",
                         "tabs": [{"id": "T1", "title": "Bank", "url": "https://bank.example"}]})
        await send_bytes(b"\xff\xd8frame")
        return vid

    async def drop_viewer(self, vid):
        self.viewers.pop(vid, None)

    async def resize(self, w, h):
        self.size = (w, h)

    async def _state(self):
        self.states += 1


@pytest.fixture
def world(monkeypatch):
    """A machine with remote access off, a browser at a wall, a chat, and a ledger to read."""
    b = _FakeBrowser()
    rows, said = [], []
    monkeypatch.setitem(cdpbrowser._BROWSERS, "", b)
    monkeypatch.setenv("AGENTOS_HANDOFF_BASE", "http://127.0.0.1")
    monkeypatch.setenv("AGENTOS_HANDOFF_BIND", "127.0.0.1")
    monkeypatch.setattr(handoff, "DOOR_LINGER", 0.0)
    old = dict(handoff._HOOKS)
    handoff.bind(cfg=lambda: CFG, ledger=lambda uid, a, r, d, surface: rows.append((a, d, surface)),
                 screens=None, session=lambda request, uid: False)

    async def say(text, buttons):
        said.append((text, buttons))
    yield type("W", (), {"b": b, "rows": rows, "said": said, "say": staticmethod(say)})
    handoff._HOOKS.clear()
    handoff._HOOKS.update(old)
    handoff._T.clear()
    handoff._DOOR.update(server=None, task=None, port=0)     # its loop ended with the test
    handoff._GUESS.clear()
    cdpbrowser._REACH.clear()
    cdpbrowser._SAY.clear()


def _link(said) -> str:
    return next(w[4:] for _l, w in said[-1][1] if w.startswith("url:"))


async def _open(w) -> str:
    assert await handoff.from_chat(CFG, "", "tg:5", "open", w.say) == handoff.HANDLED
    return _link(w.said)


# ---- offered in words, and only by a person ---------------------------------------------------

def test_the_offer_says_what_opening_it_does(world):
    att = world.b.attention
    offer = cdpbrowser.phone_offer(att)
    assert offer == {"ok": True, "how": "door"}
    words = cdpbrowser.phone_words(att, "Aria", offer=offer)
    assert "Open on this phone" in words and "opens a door on your network for this one page" in words
    assert "Passwords don't go through chat" in words
    # with remote access on there is no door to open, and the sentence doesn't claim one
    words = cdpbrowser.phone_words(att, "Aria", offer={"ok": True, "how": "remote"})
    assert "Open on this phone" in words and "door" not in words
    # WhatsApp has no buttons: a word to reply with
    assert "Reply “open”" in cdpbrowser.phone_words(att, "Aria", button=False, offer=offer)
    # a code is typed in the chat: no page is offered for it
    assert cdpbrowser.phone_offer({"kind": "code"}) == {"ok": False}
    # switched off on the machine: the old words, unchanged
    handoff.bind(cfg=lambda: {"handoff": {"enabled": False}})
    assert not cdpbrowser.phone_offer(att)["ok"]
    assert "Open" not in cdpbrowser.phone_words(att, "Aria", offer=cdpbrowser.phone_offer(att))


def test_an_unwired_embedding_offers_nothing(world):
    handoff.bind(cfg=lambda: None)
    assert not handoff.can_offer(handoff.cfg())["ok"]
    cdpbrowser.reach("", "tg:5", lambda att, png: None, say=world.say)
    assert asyncio.run(cdpbrowser.from_phone("", "tg:5", "open")) == ""      # it goes on to the agent
    assert not handoff._T


def test_no_agent_can_open_one():
    from agentos import tools
    src = Path(tools.__file__).read_text(encoding="utf-8")
    assert "handoff" not in src                              # no tool reaches it
    assert "handoff" not in tools.CONFIG_SAFE_KEYS           # and the switch is not the agent's
    from agentos import users
    assert "handoff" not in users.USER_KEYS                  # it is the machine's


# ---- the whole road, over a real door ----------------------------------------------------------

def test_the_link_opens_nothing_until_the_person_says_whose_screen_it_is(world):
    async def run():
        url = await _open(world)
        assert url.startswith("http://127.0.0.1:18327/handoff/")
        text = world.said[-1][0]
        assert url in text and "isn't encrypted" not in text          # loopback is "on this machine"
        e = handoff.for_user("")
        assert e["state"] == "sent" and e["how"] == "door" and handoff._DOOR["port"] == 18327
        async with httpx.AsyncClient() as phone, httpx.AsyncClient() as thief:
            # a preview fetch is a GET: it gets a page with a button and binds nothing
            r = await phone.get(url)
            assert r.status_code == 200 and "Show the page" in r.text
            assert r.headers["cache-control"] == "no-store" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
            assert e["state"] == "sent" and not e["device"]
            # the page's own POST binds this device, and shows a number
            r = await phone.post(url + "/join")
            j = r.json()
            assert j["state"] == "joined" and len(j["code"]) == 4 and e["code"] == j["code"]
            ask, buttons = world.said[-1]
            assert j["code"] in ask and ("Yes, that's my screen", "yes") in buttons and ("No, close it", "no") in buttons
            # a second device is refused, and the chat hears it once
            assert (await thief.post(url + "/join")).status_code == 409
            assert (await thief.post(url + "/join")).status_code == 409
            assert (await thief.get(url + "/state")).status_code == 409
            assert sum("second device" in t for t, _b in world.said) == 1
            # nothing is drawn before the chat confirms
            with pytest.raises(Exception):
                async with websockets.connect(url.replace("http", "ws") + "/ws",
                                              additional_headers={"Cookie": r.headers["set-cookie"].split(";")[0]}):
                    pass
            assert not world.b.viewers
            # another chat can't confirm it; this one can
            assert await handoff.from_chat(CFG, "", "tg:9", "yes", world.say) == ""
            assert await handoff.from_chat(CFG, "", "tg:5", "yes", world.say) == handoff.HANDLED
            assert e["state"] == "live" and (await phone.get(url + "/state")).json()["state"] == "live"
            cookie = r.headers["set-cookie"].split(";")[0]
            assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
            async with websockets.connect(url.replace("http", "ws") + "/ws",
                                          additional_headers={"Cookie": cookie}) as ws:
                await ws.send('{"type":"hello","w":390,"h":700}')
                state = __import__("json").loads(await ws.recv())
                # the phone hears this page's size, never the other tabs or addresses
                assert state == {"type": "state", "size": [390, 700], "url": ""}
                assert await ws.recv() == b"\xff\xd8frame"
                for op in ({"type": "text", "text": "hunter2"}, {"type": "navigate", "url": "https://bank.example"},
                           {"type": "tab_switch", "id": "T1"}, {"type": "tab_new"}, {"type": "handoff_close"},
                           {"type": "key", "key": "Enter"}):
                    await ws.send(__import__("json").dumps(op))
                await asyncio.sleep(0.2)
                assert [o["type"] for o in world.b.did] == ["text", "key"]      # typed and tapped, nothing else
                # Done on the page: the agent carries on, the page hears it, the door goes
                r = await phone.post(url + "/done")
                assert r.json() == {"ok": True}
                assert __import__("json").loads(await ws.recv()) == {"type": "ended", "done": True}
        assert world.b.did[-1] == {"type": "resume"} and world.b.attention is None
        assert world.b.size == (1280, 800)                   # the desk got its size back
        assert e["state"] == "ended"
        await asyncio.sleep(0.3)
        assert handoff._DOOR["server"] is None               # a door that exists only while it is used
        with pytest.raises(httpx.ConnectError):
            async with httpx.AsyncClient() as c:
                await c.get(url)
        assert [r[0] for r in world.rows] == ["handoff.open", "handoff.join", "handoff.refused",
                                             "handoff.confirm", "handoff.end"]
        assert {r[2] for r in world.rows} == {"telegram"}       # on the channel it was asked from
        assert "door on port 18327" in world.rows[0][1]
        assert "Done on your phone" in world.said[-1][0]
    asyncio.run(run())


def test_no_closes_it_and_nobody_got_in(world):
    async def run():
        url = await _open(world)
        async with httpx.AsyncClient() as c:
            await c.post(url + "/join")
            assert await handoff.from_chat(CFG, "", "tg:5", "no", world.say) == handoff.HANDLED
            assert "Nobody got in" in world.said[-1][0]
            assert (await c.get(url + "/state")).json()["state"] == "ended"
            assert (await c.post(url + "/join")).status_code == 410
        assert not world.b.did and world.b.attention            # the wall still waits for a screen
    asyncio.run(run())


def test_a_signed_in_phone_skips_the_question(world):
    handoff.bind(session=lambda request, uid: True)

    async def run():
        url = await _open(world)
        async with httpx.AsyncClient() as c:
            j = (await c.post(url + "/join")).json()
        assert j == {"state": "live", "site": "github.com"}
        assert "signed-in phone" in world.said[-1][0] and not world.said[-1][1]
        await handoff.close("", "closed by you")
    asyncio.run(run())


def test_it_ends_by_itself(world, monkeypatch):
    async def run():
        # nobody opened it in time
        monkeypatch.setattr(handoff, "OPEN_S", 0)
        url = await _open(world)
        e = handoff.for_user("")
        await asyncio.sleep(1.3)
        assert e["state"] == "ended" and e["why"] == "not opened in time"
        assert "wasn't opened in time" in world.said[-1][0]
        # the wall went away (they signed in at the desk): the link closes with it
        monkeypatch.setattr(handoff, "OPEN_S", 300)
        url = await _open(world)
        e = handoff.for_user("")
        world.b.attention = None
        await asyncio.sleep(1.3)
        assert e["state"] == "ended" and e["why"] == "the page moved on"
        async with httpx.AsyncClient() as c:
            with pytest.raises(httpx.ConnectError):
                await c.get(url)
    asyncio.run(run())


def test_a_new_link_replaces_the_old_and_wrong_links_are_counted(world):
    async def run():
        first = await _open(world)
        second = await _open(world)
        assert first != second
        async with httpx.AsyncClient() as c:
            assert (await c.post(first + "/join")).status_code == 410
            base = second.rsplit("/", 1)[0]
            for _ in range(handoff.GUESS_LIMIT):
                assert (await c.get(base + "/" + "x" * 32)).status_code == 404
            assert (await c.get(base + "/" + "x" * 32)).status_code == 429
            assert (await c.get(second)).status_code == 429          # the same address waits too
        await handoff.close("")
    asyncio.run(run())


def test_the_desk_can_see_it_and_close_it(world):
    async def run():
        await _open(world)
        v = handoff.view(handoff.for_user(""))
        assert v["state"] == "sent" and v["site"] == "github.com" and "h" not in v and "code" not in v
        assert handoff.status(CFG)["open"]["id"] == v["id"]
        assert await handoff.close("") is True and handoff.for_user("") is None
        assert "closed" in world.said[-1][0]
    asyncio.run(run())


# ---- the page, and what the chats send ---------------------------------------------------------

def test_the_page_escapes_what_came_from_elsewhere():
    e = {"state": "sent", "site": "</script><img src=x onerror=alert(1)>", "kind": "login", "why": ""}
    page = handoff.page_html(e, "t" * 32, "plain", "<b>Aria</b>")
    assert "</script><img" not in page and "<b>Aria</b>" not in page
    assert "not encrypted beyond" in page.replace("isn't", "not")          # the road is said on the page
    assert "innerHTML" not in handoff._PAGE_JS                              # the page draws with text nodes
    closed = handoff.page_html(None, "t" * 32, "plain")
    assert "This link has closed" in closed


def test_the_live_window_client_is_the_desktops_own():
    js = handoff._client_js()
    assert "function streamView(" in js and "renderBrowser" not in js
    # the one helper it may use from the desktop
    for name in ("toast(", "apiJSON(", "openApp(", "winNeedsYou("):
        assert name not in js


def test_roads_are_named_honestly():
    assert handoff._kind_of("https://bento.example") == "https"
    assert handoff._kind_of("http://100.101.102.103:8327") == "tailscale"
    assert handoff._kind_of("http://192.168.1.20:8327") == "plain"
    assert "isn't encrypted" in handoff.ROAD_WORDS["plain"]


def test_telegram_sends_the_link_plain_and_keeps_it_out_of_the_diary():
    from agentos.telegram import TelegramBridge
    calls, logs = [], []
    tg = TelegramBridge.__new__(TelegramBridge)
    tg.store = type("S", (), {"log": staticmethod(lambda kind, text, *a: logs.append(text))})()

    async def api(method, **kw):
        calls.append((method, kw))
        if any("url" in b for row in (kw.get("reply_markup") or {}).get("inline_keyboard", []) for b in row):
            raise RuntimeError("BUTTON_URL_INVALID")
        return {}
    tg._api = api
    link = "http://192.168.1.20:8327/handoff/abc_DEF-ghi_jkl"
    asyncio.run(tg.say_wall(5, "🔗 Open this:\n" + link, [("Open the page", "url:" + link)]))
    # refused with the button, sent again without: the address is in the words
    assert len(calls) == 2 and "reply_markup" not in calls[1][1]
    assert all(link in kw["text"] and "parse_mode" not in kw for _m, kw in calls)
    assert not any("handoff/" in t for t in logs)
    calls.clear()
    asyncio.run(tg.say_wall(5, "Is that your screen?", [("Yes, that's my screen", "yes"), ("No, close it", "no")]))
    kb = calls[0][1]["reply_markup"]["inline_keyboard"]
    assert [b[0]["callback_data"] for b in kb] == ["bw:yes", "bw:no"]


def test_whatsapp_asks_in_words_and_keeps_the_link_out_of_the_diary():
    from agentos.whatsapp import WhatsAppBridge
    sent = []
    wa = WhatsAppBridge.__new__(WhatsAppBridge)

    async def send(text, wa_id=None, quiet=False):
        sent.append((text, quiet))
    wa.send = send
    asyncio.run(wa.say_wall("447", "Is that your screen?", [("Yes, that's my screen", "yes"), ("No, close it", "no")]))
    assert sent == [("Is that your screen?\nReply “yes” or “no”.", True)]
    src = Path(sys.modules["agentos.whatsapp"].__file__).read_text(encoding="utf-8")
    assert '"→ said something about a sign-in link" if quiet' in src


# ---- this server's own routes ------------------------------------------------------------------

def test_the_server_serves_it_past_the_remote_gate_and_guards_the_switch():
    from agentos import machineroutes as mr
    from agentos import server as servermod
    assert "/handoff/" in servermod.REMOTE_OPEN_PATHS
    assert any(getattr(r, "path", "") == "/handoff" for r in servermod.app.routes)
    assert mr.machine_only("POST", "/api/handoff/switch")
    import inspect
    assert "_local_admin_refusal(" in inspect.getsource(servermod.api_handoff_switch)
    # the config route can't change it (its keys are an allow-list)
    assert '"handoff"' not in inspect.getsource(servermod.api_put_config)


def test_the_web_window_hears_about_it(world):
    """Found by the live walk: the desk's Web window showed nothing, because the browser's
    state never carried the hand-off."""
    async def run():
        await _open(world)
        b = cdpbrowser.Browser("", {}, Path(tempfile.mkdtemp()))
        got = b.snapshot_state()["handoff"]
        assert got["state"] == "sent" and got["site"] == "github.com"
        await handoff.close("")
        assert b.snapshot_state()["handoff"] is None
    asyncio.run(run())
    js = (Path(handoff.__file__).parent / "ui" / "src" / "js" / "04f-streams.js").read_text(encoding="utf-8")
    assert "m.handoff" in js and "handoff_close" in js
    assert 'k == "handoff_close"' in Path(cdpbrowser.__file__).read_text(encoding="utf-8")
