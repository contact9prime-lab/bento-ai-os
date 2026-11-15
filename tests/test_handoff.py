"""The sign-in link: a page the browser is stuck on, opened on the phone you're holding,
through remote access and nothing else.

Asked for with a screenshot of Aria giving up on a GitHub sign-in ("it can only be done at the
machine, not from Telegram"), then: "bento should give the link to open it on the phone directly
… prompted about and via permission … if granted open it only for the session to key in". The
first cut opened a door of its own, and the owner's answer was: "it needs to come in the remote
itself … the user will have to login to the remote … it must only go through remote".

Pinned here, each one a way this could go wrong:

- it is offered only while remote access is on, in words that say you sign in there first; with
  remote access off nothing is offered and the message says what is missing;
- no agent can open one: there is no tool, and the switch is not the agent's to change;
- the routes are behind the remote gate (not in REMOTE_OPEN_PATHS): a phone with no session gets
  the sign-in page at the link's own address, and comes back to the link after signing in;
- every route and the socket ask who is signed in: nobody, and another account, are refused;
- the phone can type and tap, and can't navigate or touch another tab;
- it ends on Done, when the wall is gone, when nobody opened it in time, and when remote access
  is switched off;
- the link is never written to the diary, and goes to Telegram as plain text.
"""
import asyncio
import contextlib
import json
import os
import socket
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


def _cfg(remote=True, on=True) -> dict:
    return {"agent_name": "Aria", "port": 8321, "handoff": {"enabled": on},
            "remote": {"enabled": remote, "pass_hash": "x" if remote else "", "pass_salt": "s"}}


# who a cookie is, in these tests: the machine's one person, another account, or nobody
PEOPLE = {"ada": "", "bob": "u-bob"}
ADA, BOB = {"Cookie": "sess=ada"}, {"Cookie": "sess=bob"}


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
    """A machine with remote access on, a browser at a wall, a chat, and a ledger to read."""
    b = _FakeBrowser()
    rows, said, cfg = [], [], _cfg()
    monkeypatch.setitem(cdpbrowser._BROWSERS, "", b)
    monkeypatch.setenv("AGENTOS_HANDOFF_BASE", "http://127.0.0.1")
    old = dict(handoff._HOOKS)

    async def gate(ws):
        return False
    handoff.bind(cfg=lambda: cfg, ledger=lambda uid, a, r, d, surface: rows.append((a, d, surface)),
                 who=lambda conn: PEOPLE.get(conn.cookies.get("sess")), ws_gate=gate)

    async def say(text, buttons):
        said.append((text, buttons))
    yield type("W", (), {"b": b, "rows": rows, "said": said, "say": staticmethod(say), "cfg": cfg})
    handoff._HOOKS.clear()
    handoff._HOOKS.update(old)
    handoff._T.clear()
    cdpbrowser._REACH.clear()
    cdpbrowser._SAY.clear()


@contextlib.asynccontextmanager
async def served(w):
    """The link's routes on a real port, as this server mounts them (the remote gate is the
    server's, and has its own test below)."""
    import uvicorn
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    w.cfg["port"] = port
    server = uvicorn.Server(uvicorn.Config(handoff.app(), log_level="warning", lifespan="off"))
    server.install_signal_handlers = lambda: None
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(0.02)
    try:
        yield port
    finally:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, 5)


def _link(said) -> str:
    return next(w[4:] for _l, w in said[-1][1] if w.startswith("url:"))


async def _open(w) -> str:
    assert await handoff.from_chat(w.cfg, "", "tg:5", "open", w.say) == handoff.HANDLED
    return _link(w.said)


# ---- offered in words, only through remote access, and only by a person -----------------------

def test_it_is_offered_only_while_remote_access_is_on(world):
    att = world.b.attention
    offer = cdpbrowser.phone_offer(att)
    assert offer == {"ok": True}
    words = cdpbrowser.phone_words(att, "Aria", offer=offer)
    assert "Open on this phone" in words and "sign in to your Bento's remote access" in words
    assert "Passwords don't go through chat" in words
    # WhatsApp has no buttons: a word to reply with
    assert "Reply “open”" in cdpbrowser.phone_words(att, "Aria", button=False, offer=offer)
    # a code is typed in the chat: no page is offered for it
    assert cdpbrowser.phone_offer({"kind": "code"}) == {"ok": False}
    # remote access off: nothing is offered, and the message says what is missing
    handoff.bind(cfg=lambda: _cfg(remote=False))
    off = cdpbrowser.phone_offer(att)
    assert not off["ok"] and off["needs"] == "remote" and "bento remote --on" in off["why"]
    words = cdpbrowser.phone_words(att, "Aria", offer=off)
    assert "Open on this phone" not in words and "remote access has to be on first" in words
    # switched off on the machine: the old words, unchanged
    handoff.bind(cfg=lambda: _cfg(on=False))
    off = cdpbrowser.phone_offer(att)
    assert not off["ok"] and "needs" not in off
    words = cdpbrowser.phone_words(att, "Aria", offer=off)
    assert "Open" not in words and "remote access" not in words


def test_asking_with_remote_access_off_opens_nothing(world):
    world.cfg["remote"]["enabled"] = False
    cdpbrowser.reach("", "tg:5", lambda att, png: None, say=world.say)
    assert asyncio.run(cdpbrowser.from_phone("", "tg:5", "open")) == handoff.HANDLED
    assert "Remote access is off" in world.said[-1][0] and not world.said[-1][1]
    assert not handoff._T and not world.rows


def test_an_unwired_embedding_offers_nothing(world):
    handoff.bind(cfg=lambda: None)
    assert not handoff.can_offer(handoff.cfg())["ok"]
    cdpbrowser.reach("", "tg:5", lambda att, png: None, say=world.say)
    assert asyncio.run(cdpbrowser.from_phone("", "tg:5", "open")) == ""      # it goes on to the agent
    assert not handoff._T
    # and with nothing wired, nobody is anybody and the socket gate is shut
    handoff._HOOKS.update(who=None, ws_gate=None)
    assert handoff._who(object()) is None


def test_no_agent_can_open_one():
    from agentos import tools
    src = Path(tools.__file__).read_text(encoding="utf-8")
    assert "handoff" not in src                              # no tool reaches it
    assert "handoff" not in tools.CONFIG_SAFE_KEYS           # and the switch is not the agent's
    from agentos import users
    assert "handoff" not in users.USER_KEYS                  # it is the machine's


def test_there_is_no_second_door():
    """The first cut started a listener of its own when remote access was off. It is gone."""
    src = Path(handoff.__file__).read_text(encoding="utf-8")
    for gone in ("uvicorn", "_door_open", "set_cookie", "randbelow"):
        assert gone not in src
    from agentos import config
    assert config.DEFAULTS["handoff"] == {"enabled": True}


# ---- the whole road ----------------------------------------------------------------------------

def test_only_its_own_person_signed_in_gets_the_page(world):
    async def run():
        async with served(world) as port:
            url = await _open(world)
            assert url.startswith(f"http://127.0.0.1:{port}/handoff/")
            text = world.said[-1][0]
            assert url in text and "You sign in to your Bento first" in text
            e = handoff.for_user("")
            assert e["state"] == "sent"
            ws_url = url.replace("http", "ws") + "/ws"
            async with httpx.AsyncClient() as c:
                # nobody signed in, and another account: every route says no and nothing changes
                for who in ({}, BOB):
                    r = await c.get(url, headers=who)
                    assert r.status_code == 403 and "isn't yours to open" in r.text and "BOOT={" not in r.text
                    assert (await c.post(url + "/join", headers=who)).status_code == 403
                    assert (await c.get(url + "/state", headers=who)).status_code == 403
                    assert (await c.post(url + "/done", headers=who)).status_code == 403
                assert e["state"] == "sent" and not world.b.did
                assert [r[0] for r in world.rows].count("handoff.refused") == 1      # one row an incident
                # its person, signed in: the page, and its own POST opens it
                r = await c.get(url, headers=ADA)
                assert r.status_code == 200 and "BOOT={" in r.text and "github.com" in r.text
                assert r.headers["cache-control"] == "no-store"
                assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
                assert e["state"] == "sent"                   # reading it changed nothing
                # a page elsewhere can't drive it
                r = await c.post(url + "/join", headers={**ADA, "Origin": "https://evil.example"})
                assert r.status_code == 403 and e["state"] == "sent"
                assert (await c.post(url + "/join", headers=ADA)).json() == {"state": "live", "site": "github.com"}
                assert "open on your phone" in world.said[-1][0] and not world.said[-1][1]
                # the socket asks too: nobody and another account never see a frame
                for who in ({}, BOB):
                    with pytest.raises(Exception):
                        async with websockets.connect(ws_url, additional_headers=who):
                            pass
                assert not world.b.viewers
                async with websockets.connect(ws_url, additional_headers=ADA) as ws:
                    await ws.send('{"type":"hello","w":390,"h":700}')
                    # the phone hears this page's size, never the other tabs or addresses
                    assert json.loads(await ws.recv()) == {"type": "state", "size": [390, 700], "url": ""}
                    assert await ws.recv() == b"\xff\xd8frame"
                    for op in ({"type": "text", "text": "hunter2"}, {"type": "navigate", "url": "https://bank.example"},
                               {"type": "tab_switch", "id": "T1"}, {"type": "tab_new"}, {"type": "handoff_close"},
                               {"type": "key", "key": "Enter"}):
                        await ws.send(json.dumps(op))
                    await asyncio.sleep(0.2)
                    assert [o["type"] for o in world.b.did] == ["text", "key"]      # typed and tapped, nothing else
                    # Done on the page: the agent carries on and the page hears it
                    assert (await c.post(url + "/done", headers=ADA)).json() == {"ok": True}
                    assert json.loads(await ws.recv()) == {"type": "ended", "done": True}
                assert (await c.post(url + "/join", headers=ADA)).status_code == 410
        assert world.b.did[-1] == {"type": "resume"} and world.b.attention is None
        assert world.b.size == (1280, 800)                   # the desk got its size back
        assert [r[0] for r in world.rows] == ["handoff.open", "handoff.refused", "handoff.join", "handoff.end"]
        assert {r[2] for r in world.rows} == {"telegram"}       # on the channel it was asked from
        assert "through remote access" in world.rows[0][1]
        assert "Done on your phone" in world.said[-1][0]
    asyncio.run(run())


def test_the_gate_is_shut_when_nothing_wired_the_socket(world):
    handoff._HOOKS["ws_gate"] = None

    async def run():
        async with served(world):
            url = await _open(world)
            async with httpx.AsyncClient() as c:
                await c.post(url + "/join", headers=ADA)
            with pytest.raises(Exception):
                async with websockets.connect(url.replace("http", "ws") + "/ws", additional_headers=ADA):
                    pass
        assert not world.b.viewers
    asyncio.run(run())


def test_close_in_the_chat_closes_it(world):
    async def run():
        await _open(world)
        assert await handoff.from_chat(world.cfg, "", "tg:9", "close", world.say) == ""     # another chat can't
        assert await handoff.from_chat(world.cfg, "", "tg:5", "close", world.say) == handoff.HANDLED
        assert "closed" in world.said[-1][0] and handoff.for_user("") is None
        assert not world.b.did and world.b.attention            # the wall still waits for a screen
    asyncio.run(run())


def test_it_ends_by_itself(world, monkeypatch):
    async def run():
        # nobody opened it in time
        monkeypatch.setattr(handoff, "OPEN_S", 0)
        await _open(world)
        e = handoff.for_user("")
        await asyncio.sleep(1.3)
        assert e["state"] == "ended" and e["why"] == "not opened in time"
        assert "wasn't opened in time" in world.said[-1][0]
        monkeypatch.setattr(handoff, "OPEN_S", 300)
        # remote access is switched off while it is out: the link goes with it
        await _open(world)
        e = handoff.for_user("")
        world.cfg["remote"]["enabled"] = False
        await asyncio.sleep(1.3)
        assert e["state"] == "ended" and e["why"] == "remote access was turned off"
        assert "remote access was turned off" in world.said[-1][0]
        world.cfg["remote"]["enabled"] = True
        # the wall went away (they signed in at the desk): the link closes with it
        await _open(world)
        e = handoff.for_user("")
        world.b.attention = None
        await asyncio.sleep(1.3)
        assert e["state"] == "ended" and e["why"] == "the page moved on"
    asyncio.run(run())


def test_a_new_link_replaces_the_old(world):
    async def run():
        async with served(world):
            first = await _open(world)
            second = await _open(world)
            assert first != second
            async with httpx.AsyncClient() as c:
                assert (await c.post(first + "/join", headers=ADA)).status_code == 410
                assert (await c.get(second.rsplit("/", 1)[0] + "/" + "x" * 32, headers=ADA)).status_code == 404
                assert (await c.post(second + "/join", headers=ADA)).json()["state"] == "live"
            await handoff.close("")
    asyncio.run(run())


def test_the_desk_can_see_it_and_close_it(world):
    async def run():
        await _open(world)
        v = handoff.view(handoff.for_user(""))
        assert v["state"] == "sent" and v["site"] == "github.com" and "h" not in v
        st = handoff.status(world.cfg)
        assert st["open"]["id"] == v["id"] and st["remote"] is True and st["can"] == {"ok": True}
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
    assert "t" * 32 not in page                                             # the address is the page's own
    closed = handoff.page_html(None, "t" * 32, "plain")
    assert "This link has closed" in closed
    # somebody else gets a card with nothing of the page in it
    other = handoff.page_html(e, "t" * 32, "plain", "Aria", theirs=False)
    assert "isn't yours to open" in other and "onerror" not in other and "BOOT=null" in other


def test_the_live_window_client_is_the_desktops_own():
    js = handoff._client_js()
    assert "function streamView(" in js and "renderBrowser" not in js
    # the one helper it may use from the desktop
    for name in ("toast(", "apiJSON(", "openApp(", "winNeedsYou("):
        assert name not in js


def test_roads_are_named_honestly():
    assert handoff._kind_of("https://bento.example") == "https"
    assert handoff._kind_of("http://100.101.102.103:8321") == "tailscale"
    assert handoff._kind_of("http://192.168.1.20:8321") == "plain"
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
    link = "http://192.168.1.20:8321/handoff/abc_DEF-ghi_jkl"
    asyncio.run(tg.say_wall(5, "🔗 Open this:\n" + link, [("Open the page", "url:" + link)]))
    # refused with the button, sent again without: the address is in the words
    assert len(calls) == 2 and "reply_markup" not in calls[1][1]
    assert all(link in kw["text"] and "parse_mode" not in kw for _m, kw in calls)
    assert not any("handoff/" in t for t in logs)
    src = Path(sys.modules["agentos.telegram"].__file__).read_text(encoding="utf-8")
    assert '"bw:open", "bw:close"' in src and "bw:yes" not in src


def test_whatsapp_keeps_the_link_out_of_the_diary():
    from agentos.whatsapp import WhatsAppBridge
    sent = []
    wa = WhatsAppBridge.__new__(WhatsAppBridge)

    async def send(text, wa_id=None, quiet=False):
        sent.append((text, quiet))
    wa.send = send
    link = "http://192.168.1.20:8321/handoff/abc_DEF-ghi_jkl"
    asyncio.run(wa.say_wall("447", "Open this:\n" + link, [("Open the page", "url:" + link)]))
    assert sent == [("Open this:\n" + link, True)]
    src = Path(sys.modules["agentos.whatsapp"].__file__).read_text(encoding="utf-8")
    assert '"→ said something about a sign-in link" if quiet' in src


# ---- this server: behind the remote gate -------------------------------------------------------

def test_the_server_keeps_it_behind_the_remote_gate():
    import inspect

    from fastapi.testclient import TestClient

    from agentos import machineroutes as mr
    from agentos import remote as remotemod
    from agentos import server as servermod
    assert not any(p.startswith("/handoff") for p in servermod.REMOTE_OPEN_PATHS)
    assert any(getattr(r, "path", "") == "/handoff" for r in servermod.app.routes)
    assert mr.machine_only("POST", "/api/handoff/switch")
    assert "_local_admin_refusal(" in inspect.getsource(servermod.api_handoff_switch)
    # the config route can't change it (its keys are an allow-list)
    assert '"handoff"' not in inspect.getsource(servermod.api_put_config)
    login = (Path(servermod.__file__).parent / "ui" / "login.html").read_text(encoding="utf-8")
    with TestClient(servermod.app, client=("192.168.1.50", 50000)) as c:
        live = servermod.state["cfg"]
        before = dict(live.get("remote") or {})
        try:
            live.setdefault("remote", {}).update({"enabled": True, "bind": "0.0.0.0", "session_days": 30})
            live["remote"]["pass_hash"], live["remote"]["pass_salt"] = remotemod.hash_passphrase("a good long phrase")
            remotemod.reset_failures()
            path = "/handoff/" + "t" * 32
            # a phone with no session: the sign-in page, at the link's own address
            r = c.get(path)
            assert r.status_code == 200 and r.text == login and "BOOT" not in r.text
            assert c.post(path + "/join").text == login
            with pytest.raises(Exception):
                with c.websocket_connect(path + "/ws"):
                    pass
            # signed in to remote access: the request reaches the link's own routes
            c.cookies.set(remotemod.COOKIE, remotemod.issue_session(live, ""))
            r = c.get(path)
            assert r.status_code == 404 and "This link has closed" in r.text
            assert c.post(path + "/join").status_code == 410
            # remote access off: a session from before is nobody
            live["remote"]["enabled"] = False
            assert c.get(path).text == login
        finally:
            live["remote"] = before
            c.cookies.clear()


def test_the_sign_in_page_comes_back_to_the_link():
    login = (Path(handoff.__file__).parent / "ui" / "login.html").read_text(encoding="utf-8")
    assert "const LINK=location.pathname.indexOf('/handoff/')===0;" in login
    assert "location.replace(LINK?location.pathname:'/')" in login           # back to the link, same origin
    assert "Sign in to open the page your agent is waiting on." in login


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
    assert "m.handoff" in js and "handoff_close" in js and "joined" not in js[js.index("m.handoff"):][:700]
    assert 'k == "handoff_close"' in Path(cdpbrowser.__file__).read_text(encoding="utf-8")
