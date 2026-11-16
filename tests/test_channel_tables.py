"""Who may talk to the agent, when that was decided and by whom, and people inside a group.

Asked for as "the groups list and the people list should come in form of a table that we can
see when it was validated and who all, in groups also we should be able to see who all can
talk … in the group also you can restrict. Same for WhatsApp", and "the approval should go to
the account and associated account telegram or whatsapp admin or in the desktop".
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import executors, telegram_admin, whatsapp   # noqa: E402
from agentos.memory import Store                          # noqa: E402

G = -1001
ROOT = Path(__file__).parent.parent


def _tg(tmp_path, monkeypatch):
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    cfg = {"agent_name": "Aria", "autonomy": "full",
           "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 5, "groups": True}}
    store = Store(tmp_path / "a.db")
    sent, asked, events = [], [], []

    async def bc(ev):
        events.append(ev)
    b = TelegramBridge(cfg, store, Toolbox(cfg, store), bc)
    store.tg_upsert_chat(5, "PC", "", "private")
    store.tg_set_allowed(5, 1, "pairing: the first chat to write")

    async def api(method, **kw):
        sent.append({"method": method, **kw})
        return {}
    b._api = api
    b.status = "polling"
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")
    monkeypatch.setattr("agentos.config.save_config", lambda cfg: None)

    async def fake_forward(engine, text, cfg, ws, emit=None, **kw):
        asked.append(text)
        return f"answer to {text}", types.SimpleNamespace(session_id="s")
    monkeypatch.setattr(executors, "forward", fake_forward)
    return b, sent, asked, events


def _in_group(b, uid, name, text):
    asyncio.run(b._handle({"chat": {"id": G, "type": "supergroup", "title": "Family"},
                           "from": {"id": uid, "first_name": name}, "text": text}))


def _tap(b, data):
    asyncio.run(b._handle_callback({"id": "q", "data": data, "from": {"id": 5},
                                    "message": {"chat": {"id": 5}, "message_id": 1, "text": "asked"}}))


def _open_group(b):
    _in_group(b, 11, "Asha", "hello")
    asyncio.run(b.decide_newcomer(G, True))


def test_a_decision_records_when_and_who(tmp_path, monkeypatch):
    b, sent, asked, _ = _tg(tmp_path, monkeypatch)
    asyncio.run(b._handle({"chat": {"id": 6, "type": "private"}, "from": {"id": 6, "first_name": "Ravi"},
                           "text": "hi"}))
    _tap(b, "who:6:1")
    t = b.table()
    ravi = next(p for p in t["people"] if p["chat_id"] == 6)
    assert ravi["allowed"] and ravi["decided_by"] == "the owner, on Telegram" and ravi["decided_at"]
    assert next(p for p in t["people"] if p["owner"])["decided_by"].startswith("pairing")
    asyncio.run(b.decide_newcomer(6, False, "Piyush, at the desktop"))
    assert next(p for p in b.table()["people"] if p["chat_id"] == 6)["decided_by"] == "Piyush, at the desktop"
    asyncio.run(b._handle({"chat": {"id": 5, "type": "private"}, "from": {"id": 5, "first_name": "PC"},
                           "text": "/people"}))
    assert "blocked " in sent[-1]["text"] and "Piyush, at the desktop" in sent[-1]["text"]


def test_everybody_who_writes_in_a_group_is_listed_and_one_can_be_blocked(tmp_path, monkeypatch):
    b, sent, asked, _ = _tg(tmp_path, monkeypatch)
    _open_group(b)
    _in_group(b, 11, "Asha", "what's for dinner")
    _in_group(b, 12, "Dev", "and the weather")
    assert asked == ["what's for dinner", "and the weather"]
    g = b.table()["group_rows"][0]
    assert {m["name"] for m in g["members"]} == {"Asha", "Dev"} and all(m["talks"] for m in g["members"])
    assert b.decide_member(G, 12, "blocked", "Piyush, at the desktop") == "blocked there"
    _in_group(b, 12, "Dev", "hello?")
    assert asked[-1] == "and the weather", "a blocked person in an enabled group is not answered"
    dev = next(m for m in b.table()["group_rows"][0]["members"] if m["name"] == "Dev")
    assert dev["talks"] is False and dev["decided_by"] == "Piyush, at the desktop"
    _in_group(b, 11, "Asha", "still here")
    assert asked[-1] == "still here"


def test_a_group_can_answer_only_the_people_picked(tmp_path, monkeypatch):
    b, sent, asked, events = _tg(tmp_path, monkeypatch)
    _open_group(b)
    _tap(b, f"gm:{G}:1")
    assert b.table()["group_rows"][0]["members_only"] == 1
    n = len(sent)
    _in_group(b, 12, "Dev", "can you hear me")
    assert asked == [], "not picked, not answered"
    to_owner = [s for s in sent[n:] if s.get("chat_id") == 5]
    assert len(to_owner) == 1 and "Dev" in to_owner[0]["text"]
    assert to_owner[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"mem:{G}:12:1"
    assert any(e.get("type") == "telegram_request" and e.get("member") == "12" for e in events), \
        "the account's desktop is asked too"
    _in_group(b, 12, "Dev", "hello?")
    assert len([s for s in sent[n:] if s.get("chat_id") == 5]) == 1, "the owner is asked once"
    _tap(b, f"mem:{G}:12:1")
    _in_group(b, 12, "Dev", "now?")
    assert asked == ["now?"]
    _in_group(b, 5, "PC", "and me")
    assert asked[-1] == "and me", "the owner is always answered"
    assert b.decide_member(G, 5, "blocked").startswith("That's the owner")
    assert b.decide_member(G, 999, "allowed").startswith("Nobody")


def test_the_phone_lists_a_groups_people_with_a_button_each(tmp_path, monkeypatch):
    b, sent, asked, _ = _tg(tmp_path, monkeypatch)
    _open_group(b)
    _in_group(b, 12, "Dev", "hi")
    asyncio.run(b._handle({"chat": {"id": 5, "type": "private"}, "from": {"id": 5, "first_name": "PC"},
                           "text": "/members family"}))
    out = sent[-1]
    assert "everybody in it is answered" in out["text"] and "✓ Dev" in out["text"]
    data = [r[0]["callback_data"] for r in out["reply_markup"]["inline_keyboard"]]
    assert data[0] == f"gm:{G}:1" and f"mem:{G}:12:0" in data
    assert "/members" not in {"/" + c["command"] for c in telegram_admin.menu(False)}, "the owner's only"


def _wa(tmp_path, monkeypatch, tg=None):
    store = Store(tmp_path / "w.db")
    cfg = {"agent_name": "Aria", "whatsapp": {"mode": "baileys", "enabled": True, "owner_wa_id": "44"}}
    said, events = [], []

    async def bc(ev):
        events.append(ev)
    b = whatsapp.WhatsAppBridge(cfg, store, types.SimpleNamespace(fabric=None, telegram=tg), bc)

    async def send(text, wa_id=None, quiet=False):
        said.append((wa_id, text))
        return "sent"
    monkeypatch.setattr(b, "send", send)
    store.wa_upsert_chat("44", "PC")
    store.wa_set_allowed("44", 1, "pairing: the first chat to write")
    n = [0]

    def msg(frm, text, name="X"):
        n[0] += 1
        asyncio.run(b._one({"from": frm, "id": f"m{n[0]}", "type": "text", "text": {"body": text}},
                           {"contacts": [{"wa_id": frm, "profile": {"name": name}}]}))
    return b, said, events, msg


def test_a_new_whatsapp_number_is_asked_of_the_owner_everywhere(tmp_path, monkeypatch):
    tg, tsent, _, _ = _tg(tmp_path, monkeypatch)
    b, said, events, msg = _wa(tmp_path, monkeypatch, tg)
    tg.toolbox.whatsapp = b
    msg("9198", "hello, can I ask something", "Meera")
    assert any(to == "44" and "/allow 9198" in text for to, text in said), "the owner's WhatsApp"
    assert any(e.get("type") == "whatsapp_request" and e["wa_id"] == "9198" for e in events), "the desktop"
    ask = [s for s in tsent if s.get("chat_id") == 5 and "Meera" in s.get("text", "")]
    assert ask and ask[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "wan:9198:1", \
        "the account's Telegram, with buttons"
    _tap(tg, "wan:9198:1")
    row = b.store.wa_get_chat("9198")
    assert row["allowed"] == 1 and row["decided_by"] == "the owner, on Telegram" and row["decided_at"]


def test_the_whatsapp_owner_allows_and_blocks_from_their_phone(tmp_path, monkeypatch):
    b, said, events, msg = _wa(tmp_path, monkeypatch)
    msg("9198", "hello", "Meera")
    msg("9198", "/allow 9198", "Meera")
    assert not b.store.wa_get_chat("9198")["allowed"], "only the owner's chat decides"
    msg("44", "/allow 9198", "PC")
    assert b.store.wa_get_chat("9198")["allowed"] == 1
    assert b.store.wa_get_chat("9198")["decided_by"] == "the owner, on WhatsApp"
    msg("44", "/people", "PC")
    assert "+9198" in said[-1][1] and "let in" in said[-1][1] and "the owner, on WhatsApp" in said[-1][1]
    msg("44", "/block 44", "PC")
    assert b.store.wa_get_chat("44")["allowed"] == 1, "the owner is never blocked"


def test_the_tables_are_drawn_from_escaped_text_and_fit_a_phone():
    js = (ROOT / "agentos/ui/src/js/16b-chantables.js").read_text()
    for field in ("c.title", "g.title", "m.name", "c.name", "r.decided_by", "c.username"):
        assert f"esc({field}" in js, f"{field} is somebody else's words"
    assert "tgPeopleTable(d)" in (ROOT / "agentos/ui/src/js/16-mcp-telegram-logs.js").read_text()
    assert "waPeopleTable(d)" in (ROOT / "agentos/ui/src/js/11a-whatsapp.js").read_text()
    css = (ROOT / "agentos/ui/src/css/43b-chantables.css").read_text()
    assert "@container (max-width:560px)" in css and "content:attr(data-l)" in css
    assert "min-height:var(--tap" in css
    assert ".ctab" not in css.split("*/", 1)[1], "Chat's pill tabs own that class; it drew an oval round the table"
