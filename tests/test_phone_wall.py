"""A sign-in wall met during a phone turn is asked of that phone (0.6.59).

Asked for as "every AI agent dies at the login screen; mine texts me". A Telegram or WhatsApp
turn with no screen open used to end at a code page with "[nobody here]". Now the turn
registers its chat while it runs (`cdpbrowser.reach`), the wall goes to that chat as a picture
and one question, and a code typed in the chat goes into the page. Pinned here:

- only a chat whose own turn registered itself can answer, so a stranger cannot type into the
  page, and a message that is not an answer goes on to the agent;
- a code is typed into the code field and never saved in the conversation or the diary;
- a password is never taken from a chat (chat history keeps it), only "done" after signing in
  on a screen;
- with a phone registered, waiting is not "[nobody here]".
"""
import asyncio
import http.server
import os
import sys
import tempfile
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import cdpbrowser   # noqa: E402


class _FakeBrowser:
    """Enough of a Browser for from_phone: running, a wall, and what the person did."""
    running = True

    def __init__(self, kind="code"):
        self.attention = {"kind": kind, "site": "shop.example", "reason": "the shop sent a code"}
        self.did = []

    async def person(self, op):
        self.did.append(("person", op))

    async def person_code(self, code):
        self.did.append(("code", code))
        return True


@pytest.fixture
def fake(monkeypatch):
    b = _FakeBrowser()
    monkeypatch.setitem(cdpbrowser._BROWSERS, "", b)
    yield b
    cdpbrowser._REACH.clear()


def test_only_the_chat_that_is_asked_can_answer(fake):
    # nobody registered: the message is not an answer, and the page is untouched
    assert asyncio.run(cdpbrowser.from_phone("", "tg:5", "123456")) == ""
    cdpbrowser.reach("", "tg:5", lambda att, png: None)
    assert asyncio.run(cdpbrowser.from_phone("", "tg:9", "123456")) == ""     # another chat
    assert asyncio.run(cdpbrowser.from_phone("ada", "tg:5", "123456")) == ""  # another account
    assert fake.did == []
    said = asyncio.run(cdpbrowser.from_phone("", "tg:5", "123 456"))
    assert said.startswith("Typed into shop.example") and fake.did == [("code", "123456")]
    cdpbrowser.unreach("", "tg:5")
    assert asyncio.run(cdpbrowser.from_phone("", "tg:5", "654321")) == ""
    assert cdpbrowser._REACH == {}


def test_words_that_are_not_a_code_go_to_the_agent(fake):
    cdpbrowser.reach("", "tg:5", lambda att, png: None)
    for words in ("what is it asking for?", "12", "abcdef", "my code is 123456 thanks"):
        assert asyncio.run(cdpbrowser.from_phone("", "tg:5", words)) == "", words
    assert fake.did == []
    assert asyncio.run(cdpbrowser.from_phone("", "tg:5", "Done.")) == "Carrying on."
    assert fake.did == [("person", {"type": "resume"})]


def test_a_password_is_never_taken_from_a_chat(fake):
    fake.attention["kind"] = "login"
    cdpbrowser.reach("", "tg:5", lambda att, png: None)
    assert asyncio.run(cdpbrowser.from_phone("", "tg:5", "hunter22")) == ""
    assert asyncio.run(cdpbrowser.from_phone("", "tg:5", "123456")) == ""
    assert fake.did == []
    words = cdpbrowser.phone_words(fake.attention, "Aria")
    assert "Passwords don't go through chat" in words and "tap Done" in words
    assert "reply “done”" in cdpbrowser.phone_words(fake.attention, "Aria", button=False)
    code = cdpbrowser.phone_words({"kind": "code", "site": "shop.example"}, "Aria")
    assert code.startswith("🔐 Aria needs you on shop.example.") and "Reply here with the code" in code


def test_a_phone_means_somebody_is_here(monkeypatch):
    class B:
        uid = ""
        attention = None

        async def read(self):
            return {"wall": {"kind": "code"}}

        async def need_person(self, wall, reason=""):
            self.attention = {"kind": wall["kind"], "site": "shop.example"}

        async def phone_shot(self):
            return b"\x89PNG"

        async def _state(self):
            pass
    asked = []

    async def ask(att, png):
        asked.append((att["kind"], png))
    cdpbrowser.bind(presence=lambda uid: False)
    cdpbrowser.reach("", "tg:5", ask)
    try:
        b = B()

        async def go():
            # the wall goes away on its own once the code is in; read() says so on the 2nd look
            looks = iter([{"wall": {"kind": "code"}}, {}, {}, {}])

            async def read():
                return next(looks, {})
            b.read = read
            b.resumed = asyncio.Event()
            b.touch = lambda: None

            async def settle(*a):
                pass
            b.settle = settle
            return await cdpbrowser.tool_wait(b, "the code", timeout=10)
        out = asyncio.run(go())
    finally:
        cdpbrowser._REACH.clear()
    assert not out.startswith("[nobody here]") and out.startswith("[carry on]")
    assert asked == [("code", b"\x89PNG")]


# ---- the bridges: a code never reaches the conversation or the diary ----

def _telegram(tmp_path):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    cfg = {"agent_name": "Aria", "autonomy": "full",
           "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 5}}
    store = Store(tmp_path / "a.db")

    async def bc(ev):
        pass
    b = TelegramBridge(cfg, store, Toolbox(cfg, store), bc)
    store.tg_upsert_chat(5, "PC", "", "private")
    store.tg_set_allowed(5, 1)
    sent = []

    async def api(method, **kw):
        sent.append((method, kw.get("text", "")))
        return {}
    b._api = api
    return b, store, sent


def _code_kept_nowhere(store, code):
    import sqlite3
    db = sqlite3.connect(store.path)
    try:
        rows = db.execute("SELECT * FROM messages").fetchall() + db.execute("SELECT * FROM logs").fetchall()
    finally:
        db.close()
    return not any(code in str(x) for r in rows for x in r)


def test_telegram_types_the_code_and_keeps_it_nowhere(tmp_path, fake):
    b, store, sent = _telegram(tmp_path)
    cdpbrowser.reach("", "tg:5", lambda att, png: None)
    asyncio.run(b._handle({"chat": {"id": 5, "type": "private"}, "from": {"first_name": "PC"},
                           "text": "482913"}))
    assert fake.did == [("code", "482913")]
    assert any(t.startswith("✓ Typed into shop.example") for _m, t in sent)
    assert _code_kept_nowhere(store, "482913")


def test_telegram_done_button_carries_on(tmp_path, fake):
    b, _store, sent = _telegram(tmp_path)
    cdpbrowser.reach("", "tg:5", lambda att, png: None)
    asyncio.run(b._handle_callback({"id": "q", "data": "bw:done", "from": {"id": 5},
                                    "message": {"chat": {"id": 5}}}))
    assert fake.did == [("person", {"type": "resume"})]
    assert any(t == "✓ Carrying on." for _m, t in sent)


def test_whatsapp_types_the_code_and_keeps_it_nowhere(tmp_path, fake):
    from agentos.memory import Store
    from agentos.tools import Toolbox
    from agentos.whatsapp import WhatsAppBridge
    cfg = {"agent_name": "Aria", "whatsapp": {"enabled": True, "owner_wa_id": "4477"}}
    store = Store(tmp_path / "w.db")

    async def bc(ev):
        pass
    w = WhatsAppBridge(cfg, store, Toolbox(cfg, store), bc)
    sent = []

    async def send(text, wa_id=None):
        sent.append(text)
        return "sent via WhatsApp"
    w.send = send
    cdpbrowser.reach("", "wa:4477", lambda att, png: None)
    asyncio.run(w._one({"from": "4477", "id": "m1", "type": "text", "text": {"body": "482913"}}, {}))
    assert fake.did == [("code", "482913")]
    assert sent and sent[0].startswith("✓ Typed into")
    assert _code_kept_nowhere(store, "482913")


def test_both_bridges_register_their_chat_for_the_turn():
    root = Path(__file__).parent.parent / "agentos"
    for f, key in (("telegram.py", 'f"tg:{chat_id}"'), ("whatsapp.py", 'f"wa:{wa_id}"')):
        src = (root / f).read_text()
        assert f"_cdpb.reach(_wall_uid, {key}" in src and f"_cdpb.unreach(_wall_uid, {key})" in src, f
        assert src.index("from_phone") < src.index("add_message"), f   # before anything is saved


# ---- the real browser: a code page takes the code ----

PAGES = {
    "/code": "<title>Verify</title><form action=/orders><p>We sent a code to your phone</p>"
             "<input name=otp autocomplete=one-time-code><button>Verify</button></form>",
    "/orders": "<title>Orders</title><h1>Your orders</h1><p>Order #1042 arrives Thursday</p>",
}


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], "<p>nothing</p>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(not cdpbrowser.binary({}), reason="no Chromium here")
def test_a_code_from_the_phone_gets_the_agent_past_the_page(tmp_path):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    cdpbrowser.bind(presence=lambda uid: False)          # nobody at a screen, only the phone
    asked = []

    async def go():
        b = await cdpbrowser.get("", {}, tmp_path)
        try:
            async def ask(att, png):
                asked.append((att["kind"], png))

                async def reply():
                    await asyncio.sleep(0.5)
                    said = await cdpbrowser.from_phone("", "tg:5", "482913")
                    asked.append(said)
                asyncio.ensure_future(reply())
            cdpbrowser.reach("", "tg:5", ask)
            words = await cdpbrowser.tool_open(b, base + "/code")
            assert "[needs you]" in words and b.attention["kind"] == "code"
            after = await cdpbrowser.tool_wait(b, "the shop sent a code", timeout=20)
            assert after.startswith("[carry on]") and "arrives Thursday" in after
            assert "otp=482913" in b.tab().get("url", "")
        finally:
            cdpbrowser._REACH.clear()
            await cdpbrowser.stop_all()
    asyncio.run(go())
    srv.shutdown()
    kind, png = asked[0]
    assert kind == "code" and png[:4] == b"\x89PNG" and asked[1].startswith("Typed into 127.0.0.1")
    # cropped to the form at twice the size, not the whole 1280x800 frame of margin
    w, h = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    assert 720 <= w < 2 * 1280 and h < 2 * 800 and w != 1280, (w, h)
