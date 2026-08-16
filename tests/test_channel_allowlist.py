"""Who may talk to the agent on a messenger channel, and what is written down when
somebody may not.

Two failures this file exists to prevent, both of which looked fine from the desk:

1. **A stranger was refused in silence.** Both bridges logged the inbound text and
   then returned, so a message that was answered and a message from somebody with
   no business here left log lines of the same shape. "Has anyone else been trying
   to reach my agent?" was not answerable from the record — which is the one
   question the record exists for.

2. **Permission could only be granted after the refusal.** `allowed` is a column on
   a row that does not exist until somebody writes in, and the only control was a
   toggle beside that row. So letting a colleague in required waiting for them to
   be turned away first. The standing allow-list is written in advance.

The allow-list is one string on the channel (`channels.<id>.allow`), which is what
makes it reachable from all three faces without a line of UI code: the desktop card
renders the field, `bento channels telegram --set allow=…` sets it over SSH, and the
bridges read the same value.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import channels as chanmod                    # noqa: E402
from agentos.memory import Store                           # noqa: E402
from agentos.policy import PDP                             # noqa: E402
from agentos.tools import Toolbox                          # noqa: E402

OWNER, GUEST, STRANGER = 111, 222, 333


class FakeFabric:
    async def run(self, *a, **k):
        return {"reply": "ok", "steps": []}


async def _broadcast(_ev):
    pass


# --------------------------------------------------------- the matcher itself

def test_a_phone_number_with_spaces_is_one_entry_not_three():
    """`+44 7700 900123` split on whitespace becomes three entries that match
    nothing — and a list matching nothing looks exactly like a list nobody is on."""
    assert chanmod.allow_list({"allow": "+44 7700 900123"}) == ["447700900123"]


def test_a_number_matches_however_either_side_spelled_it():
    """The owner types it the way it is printed; WhatsApp delivers bare digits."""
    conf = {"allow": "+44 (7700) 900-123"}
    assert chanmod.preauthorised(conf, "447700900123") == "447700900123"


def test_a_handle_matches_with_or_without_the_at_and_in_any_case():
    conf = {"allow": "@Bob"}
    assert chanmod.preauthorised(conf, "bob")
    assert chanmod.preauthorised(conf, "@BOB")


def test_names_separated_by_spaces_are_still_several_entries():
    """Unambiguous once the phone-shaped ones are out of the way."""
    assert chanmod.allow_list({"allow": "@bob @sam"}) == ["bob", "sam"]


def test_an_empty_allow_list_admits_nobody():
    """The dangerous direction. An empty setting must not read as 'anyone'."""
    for conf in ({}, {"allow": ""}, {"allow": "  ,  "}):
        assert chanmod.preauthorised(conf, "bob", "12345") == ""


def test_both_messenger_channels_offer_the_field():
    """Three faces: the field IS the surface. Missing on one channel means that
    channel can only be opened up from the desktop, and only after a refusal."""
    for cid in ("telegram", "whatsapp"):
        keys = [f.key for f in chanmod.BY_ID[cid].fields]
        assert "allow" in keys, f"{cid} has no standing allow-list"
        fld = next(f for f in chanmod.BY_ID[cid].fields if f.key == "allow")
        assert not fld.required, (
            f"{cid}'s allow-list is required, so an empty one would hold the "
            f"whole channel off as unconfigured")
        assert not fld.secret, (
            f"{cid}'s allow-list is write-only, so nobody can read back who they "
            f"have already let in")


# ------------------------------------------------------- Telegram, end to end

def _tg(tmp_path, monkeypatch, allow=""):
    from agentos.telegram import TelegramBridge
    store = Store(tmp_path / "t.db")
    cfg = {"autonomy": "balanced", "default_model": "m", "policies": [],
           "workspace": str(tmp_path / "ws"),
           "telegram": {"bot_token": "x", "owner_chat_id": OWNER},
           "channels": {"telegram": {"allow": allow}}}
    toolbox = Toolbox(cfg, store)
    toolbox.pdp = PDP(cfg, store)
    toolbox.fabric = FakeFabric()
    tg = TelegramBridge(cfg, store, toolbox, _broadcast)
    sent = []

    async def _send(text, chat_id=None):
        sent.append(text)
    monkeypatch.setattr(tg, "send", _send)
    store.tg_upsert_chat(OWNER, "Owner", "", "private")
    store.tg_set_allowed(OWNER, 1)
    return tg, store, sent


def _msg(chat_id, text="hello", username=""):
    return {"chat": {"id": chat_id, "type": "private", "username": username},
            "text": text, "from": {"id": chat_id, "first_name": "X"}}


@pytest.mark.asyncio
async def test_a_refused_telegram_sender_is_written_to_the_log(tmp_path, monkeypatch):
    tg, store, _ = _tg(tmp_path, monkeypatch)
    await tg._handle(_msg(STRANGER, "let me in"))
    refusals = [l for l in store.list_logs(limit=50) if "refused" in (l.get("message") or "")]
    assert refusals, "a stranger reached the agent and nothing recorded that it was refused"
    assert str(STRANGER) in refusals[0]["message"]


@pytest.mark.asyncio
async def test_every_refusal_is_recorded_not_only_the_first(tmp_path, monkeypatch):
    """The one-time reply is rate-limited on purpose; the RECORD must not be, or a
    sustained attempt to reach the agent shows up once and then stops."""
    tg, store, _ = _tg(tmp_path, monkeypatch)
    for _ in range(3):
        await tg._handle(_msg(STRANGER, "again"))
    refusals = [l for l in store.list_logs(limit=50) if "refused" in (l.get("message") or "")]
    assert len(refusals) == 3, f"3 attempts produced {len(refusals)} refusal records"


@pytest.mark.asyncio
async def test_a_preauthorised_telegram_handle_is_let_in(tmp_path, monkeypatch):
    tg, store, _ = _tg(tmp_path, monkeypatch, allow="@sam")
    await tg._handle(_msg(GUEST, "hello", username="sam"))
    row = [c for c in store.tg_list_chats() if c["chat_id"] == GUEST][0]
    assert row["allowed"], "a chat named on the allow-list was still refused"
    assert not [l for l in store.list_logs(limit=50) if "refused" in (l.get("message") or "")]


@pytest.mark.asyncio
async def test_someone_not_on_the_list_is_still_refused(tmp_path, monkeypatch):
    """The allow-list admits who it names and nobody else."""
    tg, store, _ = _tg(tmp_path, monkeypatch, allow="@sam")
    await tg._handle(_msg(STRANGER, "hello", username="eve"))
    row = [c for c in store.tg_list_chats() if c["chat_id"] == STRANGER][0]
    assert not row["allowed"]
    assert [l for l in store.list_logs(limit=50) if "refused" in (l.get("message") or "")]


# ------------------------------------------------------- WhatsApp, end to end

def _wa(tmp_path, monkeypatch, allow=""):
    from agentos.whatsapp import WhatsAppBridge
    store = Store(tmp_path / "w.db")
    cfg = {"autonomy": "balanced", "default_model": "m", "policies": [],
           "workspace": str(tmp_path / "ws"),
           "whatsapp": {"owner_wa_id": "111", "access_token": "x",
                        "phone_number_id": "p"},
           "channels": {"whatsapp": {"allow": allow}}}
    toolbox = Toolbox(cfg, store)
    toolbox.pdp = PDP(cfg, store)
    toolbox.fabric = FakeFabric()
    wa = WhatsAppBridge(cfg, store, toolbox, _broadcast)
    sent = []

    async def _send(text, wa_id=None):
        sent.append(text)
    monkeypatch.setattr(wa, "send", _send)
    store.wa_upsert_chat("111", "Owner")
    store.wa_set_allowed("111", 1)
    return wa, store, sent


def _wa_msg(wa_id, text="hello"):
    """(message, value) as Meta delivers them — `_one` is the per-message entry."""
    msg = {"from": wa_id, "type": "text", "text": {"body": text},
           "id": f"m{wa_id}{len(text)}"}
    val = {"contacts": [{"wa_id": wa_id, "profile": {"name": "Someone"}}]}
    return msg, val


@pytest.mark.asyncio
async def test_a_refused_whatsapp_number_is_written_to_the_log(tmp_path, monkeypatch):
    wa, store, _ = _wa(tmp_path, monkeypatch)
    await wa._one(*_wa_msg("999"))
    refusals = [l for l in store.list_logs(limit=50) if "refused" in (l.get("message") or "")]
    assert refusals, "an unknown number reached the agent with nothing recording the refusal"
    assert "999" in refusals[0]["message"]


@pytest.mark.asyncio
async def test_a_preauthorised_whatsapp_number_is_let_in(tmp_path, monkeypatch):
    """Written the way a person writes it; WhatsApp delivers it as bare digits."""
    wa, store, _ = _wa(tmp_path, monkeypatch, allow="+44 7700 900123")
    await wa._one(*_wa_msg("447700900123"))
    row = [c for c in store.wa_list_chats() if c["wa_id"] == "447700900123"][0]
    assert row["allowed"], "a number on the allow-list was still refused"
