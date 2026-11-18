"""Every approval for an account is asked on its screens AND its phones, one door, first answer wins.

Reported with two screenshots: a department run started from Telegram ("quant asks to run
Python code") raised its card on the desktop only, while Telegram sat on "Taken into what
I'm working on.", then "the approvals should be done in Telegram, whatever concerns the
account, and on WhatsApp too; the channels should be defined, and consistent". The cause:
`department_task` stamps its run's origin `chat`, and the broker only asked a phone when the
origin said Telegram. Now `request_approval` is the one door and it asks every channel.
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import channels as chanmod      # noqa: E402

ROOT = Path(__file__).parent.parent


class _Phone:
    """A stand-in bridge: answers after `after` seconds with `answer`, or never."""
    def __init__(self, owner, answer=True, after=0.05, status="polling"):
        self.owner, self.answer, self.after, self.status = owner, answer, after, status
        self.asked, self.cancelled = [], 0

    def _t(self):
        return {"owner_chat_id": self.owner}

    def _c(self):
        return {"owner_wa_id": self.owner}

    async def ask_approval(self, to, name, args, reason, offer=None, timeout=300, unanswered=None):
        self.asked.append(str(to))
        try:
            if self.after is None:
                await asyncio.sleep(3600)
            await asyncio.sleep(self.after)
            return self.answer
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


@pytest.fixture()
def srv(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    from agentos import whatsapp as wamod
    with TestClient(servermod.app):
        st = servermod.state
        sent = []

        async def bc(ev):
            sent.append(ev)
        monkeypatch.setattr(wamod, "configured", lambda cfg: True)
        cfg = st["cfg"]
        old = cfg.get("approvals")
        cfg["approvals"] = {}
        olds = {k: (st[k] if k in st else None) for k in ("telegram", "whatsapp")}
        old_bc = st["broadcast"]
        st["broadcast"] = bc
        try:
            yield servermod, st, sent
        finally:
            for k, v in olds.items():
                st[k] = v
            st["broadcast"] = old_bc
            if old is None:
                cfg.pop("approvals", None)
            else:
                cfg["approvals"] = old


def _tg_conversation(st, chat_id, ctype="private"):
    store = st["store"]
    store.tg_upsert_chat(chat_id, "PC", "", ctype)
    cid = store.create_conversation("Telegram · PC", origin="telegram")
    store.claim_conversation(cid, f"telegram:{chat_id}", "")
    return cid


@pytest.mark.asyncio
async def test_a_department_run_from_telegram_is_asked_on_telegram(srv):
    servermod, st, sent = srv
    tg = _Phone(1145038494)
    st["telegram"], st["whatsapp"] = tg, None
    cid = _tg_conversation(st, 1145038494)
    ok = await servermod.request_approval("request_capability", {"ability": "code"}, "quant asks",
                                          conversation_id=cid, timeout=5)
    assert ok is True and tg.asked == ["1145038494"], "the phone the chat came from is asked"
    shown = [e for e in sent if e.get("type") == "approval_request"]
    closed = [e for e in sent if e.get("type") == "approval_resolved"]
    assert shown and shown[0].get("conversation_id") == cid, "and the desktop shows the same card"
    assert closed and closed[-1]["how"] == "elsewhere", "which closes when the phone answers"


@pytest.mark.asyncio
async def test_every_approval_reaches_the_phones_switched_on(srv):
    servermod, st, sent = srv
    tg, wa = _Phone(5, after=None), _Phone("44", answer=False, after=0.05)
    st["telegram"], st["whatsapp"] = tg, wa
    ok = await servermod.request_approval("run_command", {"command": "ls"}, "why", timeout=5)
    assert ok is False, "WhatsApp's no came first and counts"
    assert tg.asked == ["5"] and wa.asked == ["44"], "an approval from the desk goes to both phones"
    assert tg.cancelled == 1, "and the card still waiting on Telegram is closed"
    # switched off: only a chat that came from that phone is still asked there
    st["cfg"]["approvals"] = {"off": ["telegram", "whatsapp"]}
    tg2, wa2 = _Phone(5), _Phone("44")
    st["telegram"], st["whatsapp"] = tg2, wa2
    task = asyncio.ensure_future(servermod.request_approval("run_command", {}, "why", timeout=0.2))
    assert await task is False and not tg2.asked and not wa2.asked
    cid = _tg_conversation(st, 5)
    assert await servermod.request_approval("run_command", {}, "why", conversation_id=cid, timeout=5)
    assert tg2.asked == ["5"] and not wa2.asked


@pytest.mark.asyncio
async def test_a_groups_question_goes_to_the_owner_never_into_the_group(srv):
    servermod, st, sent = srv
    tg = _Phone(5)
    st["telegram"], st["whatsapp"] = tg, None
    st["cfg"]["approvals"] = {"off": ["telegram"]}
    cid = _tg_conversation(st, -1002, "supergroup")
    assert servermod._phone_of(cid) == ("telegram", "5")
    assert await servermod.request_approval("run_command", {}, "why", conversation_id=cid, timeout=5)
    assert tg.asked == ["5"]


def test_a_phone_that_is_not_connected_is_said_not_asked(srv):
    servermod, st, sent = srv
    st["telegram"], st["whatsapp"] = _Phone(0, status="off"), None
    ch = {c["id"]: c for c in servermod.approval_channels()}
    assert not ch["telegram"]["connected"] and "Pair your Telegram" in ch["telegram"]["why"]
    assert servermod._approval_phones("") == []


def test_the_bridges_find_the_accounts_other_phone_not_the_machines():
    mine, machines = object(), object()
    tb = types.SimpleNamespace(telegram=machines, bridge=lambda n: mine if n == "telegram" else None)
    assert chanmod.sibling(tb, "telegram") is mine
    assert chanmod.sibling(types.SimpleNamespace(telegram=machines), "telegram") is machines
    for f in ("telegram.py", "whatsapp.py"):
        src = (ROOT / "agentos" / f).read_text()
        assert 'getattr(self.toolbox, "telegram"' not in src and 'getattr(self.toolbox, "whatsapp"' not in src


def test_phone_turns_ask_through_the_one_door():
    for f in ("telegram.py", "whatsapp.py"):
        src = (ROOT / "agentos" / f).read_text()
        assert 'getattr(self.toolbox, "approve", None)' in src and "conversation_id=cid" in src
    srv = (ROOT / "agentos" / "server.py").read_text()
    assert "toolbox.approve = request_approval" in srv
    fa = srv[srv.index("async def _flow_approval("):][:2600]
    assert "request_approval(" in fa


def test_settings_and_the_terminal_name_the_channels():
    js = (ROOT / "agentos" / "ui" / "src" / "js" / "11m-chanauth.js").read_text()
    assert "/api/channels/approvals" in js and "chanApprovalsPaint" in js
    assert "['Approvals','Approvals']" in (ROOT / "agentos/ui/src/js/11l-setsubs.js").read_text()
    from agentos import users
    assert "approvals" in users.USER_KEYS, "a person's phones are theirs"
    assert "def channels_approvals" in (ROOT / "agentos" / "__main__.py").read_text()


@pytest.mark.asyncio
async def test_the_reported_path_a_desk_run_asked_from_telegram(srv):
    """The control plane's broker for a department run whose chat is a Telegram thread
    (origin `chat`, as department_task stamps it)."""
    servermod, st, sent = srv
    tg = _Phone(1145038494)
    st["telegram"], st["whatsapp"] = tg, None
    st["cfg"]["approvals"] = {"off": ["telegram"]}      # even switched off: the chat asked
    cid = _tg_conversation(st, 1145038494)
    rid = st["store"].fabric_run_start("flow", "research-desk", "backtest", conversation_id=cid,
                                       flow="research-desk", origin_surface="chat", origin_ref="Research")
    ok = await servermod._flow_approval(rid, "request_capability", {"ability": "code"},
                                        "quant asks to run Python", None,
                                        {"surface": "chat", "ref": "Research"})
    assert ok is True and tg.asked == ["1145038494"]


def test_state_get_resolves_the_account_like_state_index(monkeypatch):
    from agentos import server as servermod
    from agentos import users as usersmod
    st = servermod._State()
    dict.__setitem__(st, "telegram", "machine's bot")
    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "services", lambda: {"telegram": "ada's bot"})
    assert st["telegram"] == "ada's bot"
    assert st.get("telegram") == "ada's bot", "get used to skip the account and return the machine's"
    assert st.get("nothing", 7) == 7
