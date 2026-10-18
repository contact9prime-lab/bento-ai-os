"""Every account's Telegram works from boot, and the owner adds people from the phone.

Reported as "I opened the system, which should start the Telegram listener for every user
who has Telegram enabled on their Bento login, but it didn't", and "how can I add new users
to talk to the Telegram session?". Each account's bridge was built the first time that
person's own request touched it, so with nobody signed in after a boot no account's bot
polled. `_start_account_bridges` starts them at startup, one poller per bot token. The
owner's console gains /people, /allow and /block.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_every_enabled_account_starts_at_boot_once_per_bot(monkeypatch):
    from agentos import server as servermod
    from agentos import users as usersmod
    ada = usersmod.create("ada", "ada-password-1", role="admin")
    bob = usersmod.create("bob", "bob-password-1")
    cyd = usersmod.create("cyd", "cyd-password-1")
    dee = usersmod.create("dee", "dee-password-1")
    cfgs = {ada["id"]: {"telegram": {"enabled": True, "bot_token": "1:A"}},
            bob["id"]: {"telegram": {"enabled": False, "bot_token": "1:B"}},
            cyd["id"]: {"telegram": {"enabled": True, "bot_token": "1:A"}},   # ada's bot again
            dee["id"]: {"telegram": {"enabled": True, "bot_token": "1:D"}}}
    built = []
    monkeypatch.setattr(usersmod, "cfg_for", lambda uid, machine=None: cfgs.get(uid, {}))
    monkeypatch.setattr(usersmod, "services", lambda uid=None: built.append(uid) or {})
    assert servermod._start_account_bridges() == [ada["id"], dee["id"]]
    assert built == [ada["id"], dee["id"]]
    src = (Path(servermod.__file__)).read_text()
    assert "        _start_account_bridges()\n" in src[src.index("def startup"):]


def _bridge(tmp_path):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    from agentos import config as cfgmod
    cfg = {"agent_name": "Aria", "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 111}}
    b = TelegramBridge(cfg, Store(tmp_path / "a.db"), None, None)
    sent = []

    async def api(method, **kw):
        sent.append((kw.get("chat_id"), kw.get("text") or ""))
        return {}

    async def bc(ev):
        pass
    b._api, b.broadcast = api, bc
    return b, sent


def test_the_owner_adds_and_removes_people(tmp_path, monkeypatch):
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "save_config", lambda *a, **k: None)
    b, sent = _bridge(tmp_path)
    con = b._console
    say = lambda chat, text: asyncio.run(con.handle(chat, text))

    assert say(111, "/allow @Bob")
    assert "@bob" in b.cfg["channels"]["telegram"]["allow"]
    # bob writes for the first time and is let straight in, with no question to the owner
    msg = {"chat": {"id": 222, "type": "private", "username": "bob"},
           "from": {"first_name": "Bob", "username": "bob"}, "text": "/start"}
    asyncio.run(b._handle(msg))
    assert b.store.tg_list_chats()[0]["allowed"] == 1
    assert not any("wants to talk" in t for _, t in sent)

    say(111, "/people")
    assert "Bob @bob (222)" in sent[-1][1]
    say(111, "/block 222")
    assert [c["allowed"] for c in b.store.tg_list_chats() if c["chat_id"] == 222] == [0]
    assert "bob" not in b.cfg["channels"]["telegram"]["allow"]
    say(111, "/block 111")
    assert "can't block the owner" in sent[-1][1]
    # a colleague cannot run them
    say(222, "/allow @eve")
    assert "owner of this machine only" in sent[-1][1]


def test_the_owner_opens_a_company_from_the_phone(tmp_path, monkeypatch):
    """"With Telegram I should be able to open the companies.\""""
    from agentos import config as cfgmod, company as companymod
    monkeypatch.setattr(cfgmod, "save_config", lambda *a, **k: None)
    b, sent = _bridge(tmp_path)
    say = lambda chat, text: asyncio.run(b._console.handle(chat, text))
    say(111, "/companies")
    assert "No company yet" in sent[-1][1]
    companymod.create(b.cfg, b.store, "Bhav Capital", "trading research")
    companymod.create(b.cfg, b.store, "Kids Studio", "videos for children")
    assert companymod.companies(b.cfg)[0]["name"] == "Kids Studio"
    say(111, "/companies")
    assert "▶ Kids Studio" in sent[-1][1] or any("▶ Kids Studio" in t for _, t in sent[-2:])
    say(111, "/company bhav capital")
    assert "Bhav Capital is open" in sent[-1][1]
    assert companymod.companies(b.cfg)[0]["name"] == "Bhav Capital"
    say(111, "/company")
    assert sent[-1][1].startswith("▲ Bhav Capital")
    say(222, "/companies")
    assert "owner of this machine only" in sent[-1][1]
