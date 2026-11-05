"""A Telegram turn belongs to the account whose bot it came to. Reported as "if there are multiple
users, the instruction given by Telegram to the tied user is accepted by Aria in all the users": the
bridges were handed the machine-wide broadcast, so every account's Chat and Office lit up, and an
account with no Telegram of its own read the machine's token as its own."""
import asyncio

from agentos import server
from agentos import users as usersmod


def test_a_bridge_sends_to_its_owner_only(monkeypatch):
    got = []

    async def bu(ev, uid):
        got.append(uid)
    monkeypatch.setitem(server.state, "broadcast_user", bu)
    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "list_users", lambda: [{"id": "ada"}, {"id": "bob"}, {"id": "cy"}])
    monkeypatch.setattr(usersmod, "is_admin", lambda u: u in ("ada", "cy"))
    asyncio.run(server._owner_send("bob")({"type": "turn_start"}))
    assert got == ["bob"]
    got.clear()
    asyncio.run(server._owner_send()({"type": "telegram_in"}))          # the machine's, belonging to nobody
    assert got == ["ada", "cy"]
    got.clear()
    with usersmod.as_user("bob"):
        asyncio.run(server._owner_send()({"type": "telegram_in"}))
    assert got == ["bob"]


def test_an_account_never_sees_the_machines_telegram_as_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(usersmod, "cfg_path_for", lambda uid: tmp_path / f"{uid}.json")
    usersmod._cfgs.clear()
    machine = {"telegram": {"bot_token": "123:machine", "enabled": True}, "whatsapp": {"mode": "cloud"},
               "providers": {"x": 1}}
    try:
        c = usersmod.cfg_for("newbie", machine=machine)
        assert c["telegram"] == {} and c["whatsapp"] == {} and c["providers"] == {"x": 1}
        (tmp_path / "own.json").write_text('{"telegram": {"bot_token": "9:mine"}}')
        assert usersmod.cfg_for("own", machine=machine)["telegram"] == {"bot_token": "9:mine"}
    finally:
        usersmod._cfgs.clear()


def test_every_bridge_is_built_with_an_owner_sender():
    src = (server.__file__ and open(server.__file__).read())
    for line in src.splitlines():
        if "TelegramBridge(" in line or "WhatsAppBridge(" in line:
            if "import" in line or "class " in line:
                continue
            assert "_owner_send(" in line, line.strip()
