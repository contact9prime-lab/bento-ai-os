"""Every card says how an approval ended, and so does the agent.

Reported from Telegram: "On approval it said answered on another screen, but that hasn't
been done by me." Two cards (at 02:22 and at 08:04) were closed with "→ Answered on another
screen." while nobody had answered either. The agent replied five minutes after the second
one, exactly the approval timeout, and told the person "this machine's autonomy setting
blocked it".

The cause: `request_approval` races the desktop's card against the phones'. All of them wait
300 s and the desktop's started first, so it timed out first and the race closed the phones'
cards, whose only cancel path said "answered on another screen". The agent was handed the
same refusal for a no, a timeout and a Stop: "not approved at the current autonomy level".

Now whichever card settles an approval writes how it ended (`policy.note_outcome`), and every
other card, the desktop's copy and the agent read that one record.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import policy  # noqa: E402

ROOT = Path(__file__).parent.parent


def _bridge(tmp_path, monkeypatch):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    store = Store(tmp_path / "t.db")
    cfg = {"policies": [], "workspace": str(tmp_path / "ws"), "telegram": {"bot_token": "x"}}

    async def _b(_ev):
        pass
    tg = TelegramBridge(cfg, store, Toolbox(cfg, store), _b)
    calls = []

    async def _api(method, **params):
        calls.append((method, params))
        return {"message_id": 7} if method == "sendMessage" else {}
    monkeypatch.setattr(tg, "_api", _api)
    tg.status = "polling"
    return tg, calls


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
        olds = {k: (st[k] if k in st else None) for k in ("telegram", "whatsapp", "broadcast")}
        old_ap = st["cfg"].get("approvals")
        st["cfg"]["approvals"] = {}
        st["broadcast"] = bc
        try:
            yield servermod, st, sent
        finally:
            for k, v in olds.items():
                st[k] = v
            if old_ap is None:
                st["cfg"].pop("approvals", None)
            else:
                st["cfg"]["approvals"] = old_ap


def _edits(calls):
    return [p["text"] for m, p in calls if m == "editMessageText"]


@pytest.mark.asyncio
async def test_a_card_nobody_answered_is_never_said_to_be_answered(srv, tmp_path, monkeypatch):
    servermod, st, sent = srv
    tg, calls = _bridge(tmp_path, monkeypatch)
    tg.cfg["telegram"]["owner_chat_id"] = 5
    st["telegram"], st["whatsapp"] = tg, None
    asked = {}
    tok = policy._ASKED.set(asked)
    try:
        ok = await servermod.request_approval("create_flow", {"name": "scan"}, "Sets up a mission.",
                                              timeout=0.3)
    finally:
        policy._ASKED.reset(tok)
    assert ok is False
    assert asked.get("how") == "timeout", "the agent hears nobody answered"
    edit = _edits(calls)
    assert edit and "Nobody answered" in edit[-1] and "wasn't done" in edit[-1]
    assert not any("Answered on another screen" in e for e in edit)
    assert not any("timed out" in p.get("text", "") for m, p in calls if m == "sendMessage"), \
        "the desk keeps the clock, so the phone never times out on its own"
    closed = [e for e in sent if e.get("type") == "approval_resolved"]
    assert closed and closed[-1]["how"] == "timeout", "and so does the desktop's copy"


@pytest.mark.asyncio
async def test_an_answer_on_the_desktop_closes_the_phone_with_what_it_was(srv, tmp_path, monkeypatch):
    servermod, st, sent = srv
    tg, calls = _bridge(tmp_path, monkeypatch)
    tg.cfg["telegram"]["owner_chat_id"] = 5
    st["telegram"], st["whatsapp"] = tg, None
    asked = {}
    tok = policy._ASKED.set(asked)
    try:
        task = asyncio.ensure_future(servermod.request_approval("run_python", {"code": "1"}, "why",
                                                                timeout=5))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if st["pending_approvals"]:
                break
        aid = next(iter(st["pending_approvals"]))
        assert await servermod.resolve_approval(aid, False, uid="")
        assert await task is False
    finally:
        policy._ASKED.reset(tok)
    assert asked == {"how": "answered", "via": "on a screen", "approved": False}
    assert _edits(calls)[-1].endswith("→ Denied on a screen.")


@pytest.mark.asyncio
async def test_a_tap_on_telegram_says_allowed_on_telegram_on_the_desktop(srv, tmp_path, monkeypatch):
    servermod, st, sent = srv
    tg, calls = _bridge(tmp_path, monkeypatch)
    tg.cfg["telegram"]["owner_chat_id"] = 5
    st["telegram"], st["whatsapp"] = tg, None
    asked = {}
    tok = policy._ASKED.set(asked)
    try:
        task = asyncio.ensure_future(servermod.request_approval("run_python", {"code": "1"}, "why",
                                                                timeout=5))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if tg._pending:
                break
        next(iter(tg._pending.values())).set_result("1")
        assert await task is True
    finally:
        policy._ASKED.reset(tok)
    assert asked["how"] == "answered" and asked["via"] == "on Telegram" and asked["approved"]
    closed = [e for e in sent if e.get("type") == "approval_resolved"][-1]
    assert closed["how"] == "elsewhere" and closed["approved"] is True and closed["via"] == "on Telegram", \
        "the desktop's copy read ✕ Denied when a phone allowed"


@pytest.mark.asyncio
async def test_stop_closes_the_cards_as_stopped(srv, tmp_path, monkeypatch):
    servermod, st, sent = srv
    tg, calls = _bridge(tmp_path, monkeypatch)
    tg.cfg["telegram"]["owner_chat_id"] = 5
    st["telegram"], st["whatsapp"] = tg, None
    asked = {}
    tok = policy._ASKED.set(asked)
    try:
        task = asyncio.ensure_future(servermod.request_approval("run_python", {}, "why", timeout=5))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if st["pending_approvals"]:
                break
        entry = next(iter(st["pending_approvals"].values()))
        entry["stopped"] = True           # what the socket's Stop does before it settles them
        entry["fut"].set_result(False)
        assert await task is False
    finally:
        policy._ASKED.reset(tok)
    assert asked.get("how") == "stopped"
    assert _edits(calls)[-1].endswith("→ Stopped, so this wasn't done.")


def test_closed_words_say_each_outcome():
    w = policy.closed_words
    assert w({"how": "answered", "via": "on WhatsApp", "approved": True}) == "→ Allowed on WhatsApp."
    assert w({"how": "timeout", "minutes": 5, "brief": True}) == \
        "⌛ Nobody answered within 5 min, so this wasn't done. It's on your Brief."
    assert "called off" in w({}), "a step cancelled for another reason never claims an answer"
    for src in ("telegram.py", "whatsapp.py"):
        code = (ROOT / "agentos" / src).read_text()
        assert "→ Answered on another screen." not in code and "was answered on another screen.\"" not in code


@pytest.mark.asyncio
async def test_the_agent_is_told_nobody_answered_not_that_autonomy_refused(tmp_path):
    from agentos.agent import Agent
    from agentos.memory import Store
    from agentos.tools import Toolbox
    store = Store(tmp_path / "a.db")
    cfg = {"policies": [], "workspace": str(tmp_path / "ws"), "autonomy": "balanced"}
    tb = Toolbox(cfg, store)

    async def timed_out(name, args, reason, offer=None):
        policy.note_outcome("timeout", minutes=5, brief=True)
        return False

    async def said_no(name, args, reason, offer=None):
        policy.note_outcome("answered", via="on Telegram", approved=False)
        return False

    async def sink(_ev):
        pass
    out = {}
    for label, ap in (("timeout", timed_out), ("no", said_no)):
        ag = Agent(cfg, tb, "", sink, ap, conversation_id="", surface="telegram")
        out[label] = (await ag.call_tool("run_command", {"command": "rm -rf build"}, "c1"))[0]
    assert out["timeout"].startswith("[not done] Nobody answered") and "autonomy setting didn't block" in out["timeout"]
    assert "Brief" in out["timeout"]
    assert out["no"].startswith("[denied] The user said no to this step on Telegram")
    for v in out.values():
        assert "current autonomy level" not in v
