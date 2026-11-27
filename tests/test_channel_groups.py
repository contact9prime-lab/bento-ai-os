"""Groups on Telegram and WhatsApp reach the owner for a decision, and one list holds them all.

Reported as "when I message it from the group it doesn't come in the groups authorization in
the channel, and so it is not in WhatsApp too; there has to be approval for such groups, and
it should go to the WhatsApp and Telegram admin", then "we need a separate section of
Authorization for all the channels". Read from the owner's record: their bot had received no
group message at all. Telegram's privacy mode hands a bot only messages that mention it, and
a group was listed only when one did; the linked WhatsApp device dropped every group message.
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import chanauth, whatsapp            # noqa: E402
from agentos.memory import Store                   # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from test_channel_tables import _tg, _wa           # noqa: E402

ROOT = Path(__file__).parent.parent
G = -1002


def _added(tg, status="member", old="left"):
    asyncio.run(tg._membership({
        "chat": {"id": G, "type": "supergroup", "title": "Family"},
        "from": {"id": 5, "first_name": "PC"},
        "old_chat_member": {"status": old}, "new_chat_member": {"status": status}}))


def test_a_telegram_group_is_listed_and_asked_the_moment_the_bot_is_added(tmp_path, monkeypatch):
    tg, sent, _, events = _tg(tmp_path, monkeypatch)
    tg.reads_groups = False
    tg.bot_username = "aos_bot"
    wa, said, _, _ = _wa(tmp_path, monkeypatch, tg)
    tg.toolbox.whatsapp = wa
    _added(tg)
    row = next(c for c in tg.store.tg_list_chats() if c["chat_id"] == G)
    assert row["allowed"] == 0 and row["type"] == "supergroup"
    ask = [s for s in sent if s.get("chat_id") == 5 and "added me to the group Family" in s.get("text", "")]
    assert ask, "the owner's Telegram is asked, with no message in the group needed"
    assert "/setprivacy" in ask[0]["text"], "and told why group messages may not arrive"
    assert ask[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"who:{G}:1"
    assert any(to == "44" and f"/allow tg:{G}" in text for to, text in said), "the owner's WhatsApp too"
    assert any(e.get("type") == "telegram_request" and e.get("group") for e in events), "and the desktop"
    assert not [s for s in sent if s.get("chat_id") == G], "nothing is said in the group"
    # a second add (or being made admin) after a decision asks nobody again
    sent.clear()
    asyncio.run(tg.decide_newcomer(G, False, "the owner"))
    _added(tg, "administrator", "member")
    assert not [s for s in sent if s.get("chat_id") == 5]


def test_making_the_bot_an_admin_lists_a_group_it_was_already_in(tmp_path, monkeypatch):
    """The owner's group had the bot in it before this existed: promoting it is the way in."""
    tg, sent, _, _ = _tg(tmp_path, monkeypatch)
    tg.reads_groups = False
    _added(tg, "administrator", "member")
    assert any(c["chat_id"] == G for c in tg.store.tg_list_chats())
    ask = [s for s in sent if s.get("chat_id") == 5]
    assert ask and "/setprivacy" not in ask[0]["text"], "an admin reads the whole group"


def test_the_whatsapp_owner_answers_a_telegram_request(tmp_path, monkeypatch):
    tg, sent, _, _ = _tg(tmp_path, monkeypatch)
    wa, said, _, msg = _wa(tmp_path, monkeypatch, tg)
    _added(tg)
    msg("44", f"/allow tg:{G}")
    row = next(c for c in tg.store.tg_list_chats() if c["chat_id"] == G)
    assert row["allowed"] == 1 and row["decided_by"] == "the owner, on WhatsApp"
    assert any("allowed" in text for to, text in said if to == "44")


def _group(b, n, text, who="9177", name="Ravi", addressed=False):
    asyncio.run(b._one({"from": "120363", "id": f"g{n}", "type": "text", "text": {"body": text},
                        "group": {"subject": "Cricket club", "participant": who, "name": name,
                                  "addressed": addressed}}, {"contacts": []}))


def test_a_whatsapp_group_waits_for_the_owner_and_stays_quiet(tmp_path, monkeypatch):
    tg, tsent, _, _ = _tg(tmp_path, monkeypatch)
    b, said, events, _ = _wa(tmp_path, monkeypatch, tg)
    turns = []

    async def turn(chat, wa_id, text, **kw):
        turns.append((wa_id, text))
    monkeypatch.setattr(b, "_turn", turn)
    _group(b, 1, "who is playing on sunday?")
    row = b.store.wa_get_chat("120363")
    assert row["kind"] == "group" and row["allowed"] == 0 and row["name"] == "Cricket club"
    assert [m["member_id"] for m in b.store.members("whatsapp", "120363")] == ["9177"]
    assert any(to == "44" and "Cricket club" in t and "/allow 120363" in t for to, t in said)
    assert not [t for to, t in said if to == "120363"], "nothing is said in the group"
    ask = [s for s in tsent if s.get("chat_id") == 5 and "Cricket club" in s.get("text", "")]
    assert ask and ask[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "wan:120363:1"
    assert any(e.get("type") == "whatsapp_request" and e.get("group") for e in events)
    _group(b, 2, "anyone?")
    assert len([1 for to, t in said if to == "44"]) == 1, "asked once"
    assert not turns

    # allowed: answered only when addressed, and the speaker is named in the turn
    asyncio.run(b.decide_newcomer("120363", True, "the owner"))
    assert any(to == "120363" and "Mention me" in t for to, t in said), "the group is told how"
    _group(b, 3, "just chatting among ourselves")
    assert not turns
    _group(b, 4, "Aria, what's the forecast for sunday?")
    _group(b, 5, "@bot hi", addressed=True)
    assert [t for _, t in turns] == [
        "[Ravi, in the WhatsApp group Cricket club] Aria, what's the forecast for sunday?",
        "[Ravi, in the WhatsApp group Cricket club] @bot hi"]
    # a member the owner blocked is never answered
    b.store.member_set("whatsapp", "120363", "9177", "blocked", "the owner")
    _group(b, 6, "Aria, hello?")
    assert len(turns) == 2


def test_a_group_turn_asks_its_approvals_in_the_owners_chat(tmp_path, monkeypatch):
    _, _, _, _ = _tg(tmp_path, monkeypatch)
    b, said, _, _ = _wa(tmp_path, monkeypatch)
    asked = []

    async def ask_approval(to, name, args, reason, offer=None, timeout=300):
        asked.append(to)
        return False
    monkeypatch.setattr(b, "ask_approval", ask_approval)
    captured = {}

    async def body(chat, wa_id, text, cid, emit, approver, note):
        captured["ok"] = await approver("run_command", {"command": "ls"}, "why")
    monkeypatch.setattr(b, "_turn_body", body)
    b.store.wa_upsert_chat("120363", "Cricket club", "group")
    chat = b.store.wa_get_chat("120363")
    asyncio.run(b._turn_in(chat, "120363", "hi", b._conversation(chat)))
    assert asked == ["44"], "never into the group, where anybody could answer it"


def test_the_bridge_passes_group_messages_on():
    js = (ROOT / "agentos" / "wa_bridge" / "bridge.js").read_text()
    assert "@g.us') || jid === 'status@broadcast') continue" not in js
    assert "ev.addressed" in js and "ev.participant" in js


def test_one_list_holds_every_channel_waiting_first(tmp_path):
    store = Store(tmp_path / "a.db")
    cfg = {"telegram": {"owner_chat_id": 5}, "whatsapp": {"owner_wa_id": "44"}}
    store.tg_upsert_chat(5, "PC", "", "private")
    store.tg_set_allowed(5, 1, "pairing")
    store.tg_upsert_chat(G, "Family", "", "supergroup")
    store.tg_upsert_chat(7, "Sam", "sam", "private")
    store.tg_set_allowed(7, 1, "the owner")
    store.wa_upsert_chat("44", "PC")
    store.wa_upsert_chat("120363", "Cricket club", "group")
    store.wa_upsert_chat("9198", "Meera")
    store.wa_set_allowed("9198", 0, "the owner")
    items = chanauth.rows(store, cfg)
    assert [r["ref"] for r in items][:2] in (["tg:-1002", "wa:120363"], ["wa:120363", "tg:-1002"])
    assert {r["ref"]: r["state"] for r in items} == {
        "tg:-1002": "waiting", "wa:120363": "waiting", "wa:9198": "blocked", "tg:7": "allowed"}, \
        "the owner's own chats are not requests"
    assert {r["ref"]: r["kind"] for r in items}["wa:120363"] == "group"
    assert chanauth.summary(items) == {"waiting": 2, "allowed": 1, "blocked": 1}
    assert chanauth.decide(store, "wa:120363", True, "an admin") == "allowed"
    assert chanauth.decide(store, "tg:404", True, "an admin").startswith("nobody")
    try:
        chanauth.split_ref("slack:1")
        raise AssertionError("an unknown channel is refused")
    except ValueError:
        pass


def test_settings_has_one_authorization_section():
    js = (ROOT / "agentos" / "ui" / "src" / "js" / "11l-setsubs.js").read_text()
    assert "['Authorization','Authorization']" in js
    page = (ROOT / "agentos" / "ui" / "src" / "js" / "11m-chanauth.js").read_text()
    assert "/api/channels/authorization" in page and "innerHTML" in page
    assert "esc(r.name)" in page, "names are other people's words"
    assert whatsapp.WhatsAppBridge._addressed  # the group rule is one function
