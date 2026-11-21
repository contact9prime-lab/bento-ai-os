"""Typing your Bento password from your phone after a restart (agentos/unlock.py).

The owner's rules: the phone chat offers a LINK; it opens the remote sign-in page on the phone;
signing in there opens the secrets set to "only while I'm signed in" for the missions; the
password is never typed into the chat; it only works through remote access, with no second
door; and the chat is the one paired to that account.
"""

import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import config as cfgmod                                # noqa: E402
from agentos import seal                                            # noqa: E402
from agentos import unlock                                          # noqa: E402
from agentos import users as usersmod                               # noqa: E402
from agentos import vault                                           # noqa: E402

PW = "correct horse 1"
ROOT = Path(__file__).parent.parent


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("AGENTOS_HANDOFF_BASE", "https://bento.example.ts.net")
    usersmod.reset_caches()
    usersmod.set_current("")
    seal._PADS.clear()
    vault.forget_held()
    unlock.forget()
    saved = dict(unlock._HOOKS)
    yield tmp_path
    unlock._HOOKS.update(saved)
    unlock.forget()
    seal._PADS.clear()
    usersmod.reset_caches()
    usersmod.set_current("")


class Loop:
    """A real event loop on its own thread, as the server's is, with phone chats that record."""

    def __init__(self, phones_for, remote_on=True):
        self.loop = asyncio.new_event_loop()
        self.t = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.t.start()
        self.said, self.rows = [], []
        cfg = {"remote": {"enabled": remote_on, "passphrase_hash": "x"}} if remote_on else {}

        def phones(uid):
            out = []
            for key in phones_for.get(uid, []):
                async def say(text, buttons, key=key):
                    self.said.append((key, text, buttons))
                out.append((key, None, say))
            return out
        unlock.bind(phones=phones, cfg=lambda: cfg, loop=self.loop, port=lambda: 8321,
                    ledger=lambda uid, a, r, w: self.rows.append((uid, a, r, w)))

    def settle(self):
        for _ in range(50):
            time.sleep(0.02)
        return self

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


def _ada():
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _ = seal.establish(u, PW)
    return u, priv


def test_the_link_goes_to_your_own_chat_and_never_asks_for_the_password_there(home, monkeypatch):
    from agentos import remote
    monkeypatch.setattr(remote, "enabled", lambda cfg: bool((cfg.get("remote") or {}).get("enabled")))
    u, _ = _ada()
    lp = Loop({u: ["tg:111"], "bob": ["tg:222"]})
    try:
        assert unlock.closed(u, "mail.password")
        lp.settle()
        assert [k for k, _t, _b in lp.said] == ["tg:111"]            # only this account's paired chat
        text, buttons = lp.said[0][1], lp.said[0][2]
        assert "https://bento.example.ts.net:8321/unlock" in text and buttons[0][1].endswith("/unlock")
        assert "never in this chat" in text and "Mail password" in text
        assert lp.rows and lp.rows[0][1] == "seal.unlock_link"
        # many steps, one message
        assert not unlock.closed(u, "oauth.mail") and len(lp.said) == 1
    finally:
        lp.stop()


def test_with_remote_access_off_there_is_no_link_and_nothing_waits(home):
    u, _ = _ada()
    lp = Loop({u: ["tg:111"]}, remote_on=False)
    try:
        assert unlock.closed(u, "mail.password") is False             # nothing to wait for
        lp.settle()
        text = lp.said[0][1]
        assert "/unlock" not in text and "Remote access is off" in text
        assert lp.said[0][2] is None
    finally:
        lp.stop()


def test_no_paired_chat_means_no_message_and_no_wait(home):
    u, _ = _ada()
    lp = Loop({})
    try:
        assert unlock.closed(u, "mail.password") is False
        lp.settle()
        assert not lp.said
    finally:
        lp.stop()


def test_a_waiting_step_carries_on_once_you_open_it_on_your_phone(home, monkeypatch):
    from agentos import remote
    monkeypatch.setattr(remote, "enabled", lambda cfg: True)
    monkeypatch.setattr(unlock, "WAIT_S", 10.0)
    monkeypatch.setattr(unlock, "POLL_S", 0.05)
    u, priv = _ada()
    lp = Loop({u: ["tg:111"]})
    with usersmod.as_user(u):
        vault.put("mail.password", "hunter2")
        vault.set_away("mail.password", "off")
    got = {}

    def step():                                     # a mission's step, in a worker thread
        with usersmod.as_user(u):
            got["v"] = vault.get("mail.password")
    t = threading.Thread(target=step)
    t.start()
    time.sleep(0.4)
    assert t.is_alive()                              # it waits for the person
    with usersmod.as_user(u):                        # their phone: signed in, "for the next run"
        vault.set_away("mail.password", "once", priv=priv)
    t.join(5)
    lp.stop()
    assert got.get("v") == "hunter2"
    with usersmod.as_user(u):
        assert vault.away_meta("mail.password")["used"]


def test_a_step_nobody_answers_is_refused_in_words(home, monkeypatch):
    from agentos import remote
    monkeypatch.setattr(remote, "enabled", lambda cfg: True)
    monkeypatch.setattr(unlock, "WAIT_S", 0.3)
    monkeypatch.setattr(unlock, "POLL_S", 0.05)
    u, _ = _ada()
    lp = Loop({u: ["tg:111"]})
    try:
        with usersmod.as_user(u):
            vault.put("mail.password", "hunter2")
            vault.set_away("mail.password", "off")
            err = {}

            def step():
                with usersmod.as_user(u):
                    try:
                        vault.get("mail.password")
                    except seal.Sealed as e:
                        err["e"] = str(e)
            t = threading.Thread(target=step)
            t.start()
            t.join(5)
        assert "only while you're signed in" in err["e"]
    finally:
        lp.stop()


def test_there_is_no_second_door():
    """The page is behind the remote gate like every page: not in REMOTE_OPEN_PATHS, no ticket,
    no listener of its own, and the sign-in page comes back to it."""
    from agentos import server
    assert not any("/unlock".startswith(p) for p in server.REMOTE_OPEN_PATHS)
    src = (ROOT / "agentos/unlock.py").read_text()
    for door in ("token_urlsafe", "start_server", "HTTPServer", "socket.socket"):
        assert door not in src
    login = (ROOT / "agentos/ui/login.html").read_text()
    assert "location.pathname==='/unlock'" in login


def test_the_page_draws_with_text_nodes_and_types_the_password_only_into_bento():
    html = (ROOT / "agentos/ui/unlock.html").read_text()
    assert "innerHTML" not in html
    assert "/api/seal/open" in html and "/api/seal/away" in html


def test_signed_in_the_page_is_served(home):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        c.post("/api/users", json={"name": "ada", "password": PW})
        r = c.get("/unlock")
        assert r.status_code == 200 and "Open your secrets" in r.text
        assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", "")
        c.cookies.clear()
        r = c.get("/unlock")
        # no session: the sign-in page, at the link's own address
        assert "Open your secrets" not in r.text
