"""A phone sees what its turn is doing: hand-overs, a department's people, sign-offs.

Reported as "when it is running a chat with Telegram or WhatsApp and it sends the message to the
department and sub department, it is not showing those interim steps in the channels". Every
event of a phone turn went to the desktop's screens; the phone got "typing…" and then the answer.
phonelive.py follows the turn (the events naming its conversation, and every run it started, as
Chat's department card does) and the bridges show it: Telegram edits one message, WhatsApp sends
short batches.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import executors, phonelive                           # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _desk_run(cid="c1"):
    """The events of '@Research …' asked from chat c1: the lead's hand-over, the desk's run, its
    analyst's run and steps, the head's sign-off, the finish."""
    return [
        {"type": "tool_start", "conversation_id": cid, "name": "department_task",
         "args": {"department": "Research", "task": "Backtest the five strategies end to end"}},
        {"type": "fabric_event", "run_id": "R1", "event": "flow_start", "conversation_id": cid,
         "department": "Research", "head": "maya", "flow": "research-desk"},
        {"type": "fabric_event", "run_id": "R1", "event": "heartbeat"},
        {"type": "fabric_event", "run_id": "R1", "event": "node_add", "agent": "analyst",
         "task": "Run the backtests in Python and report the Sharpe ratios"},
        {"type": "fabric_event", "run_id": "R2", "event": "status", "status": "running",
         "ref": "analyst", "parent_run": "R1", "kind": "subagent"},
        {"type": "fabric_event", "run_id": "R2", "event": "step", "tool": "run_python",
         "status": "start", "detail": "backtest.py"},
        {"type": "fabric_event", "run_id": "R2", "event": "status", "status": "ok", "ref": "analyst",
         "parent_run": "R1", "steps": 4},
        {"type": "fabric_event", "run_id": "R1", "event": "review", "phase": "start", "reviewer": "maya"},
        {"type": "fabric_event", "run_id": "R1", "event": "review", "phase": "done", "reviewer": "maya",
         "answer": "SEND BACK", "notes": ["add the drawdowns"]},
        {"type": "fabric_event", "run_id": "R1", "event": "audit", "phase": "done", "verdict": "concerns",
         "line": "Two of the five backtests have no costs"},
        {"type": "fabric_event", "run_id": "R1", "event": "flow_end", "status": "ok", "flow": "research-desk"},
    ]


def test_a_tap_follows_the_department_its_chat_asked():
    tap = phonelive.listen("c1")
    other = phonelive.listen("c2")
    try:
        for ev in _desk_run("c1"):
            phonelive.observe(ev)
        # another chat's desk run, and a run nobody here started, are not ours
        phonelive.observe({"type": "fabric_event", "run_id": "X9", "event": "flow_start",
                           "conversation_id": "c3", "department": "Sales"})
        phonelive.observe({"type": "fabric_event", "run_id": "X9", "event": "node_add", "agent": "rep",
                           "task": "call them"})
        text = "\n".join(tap.lines)
        assert tap.lines[0].startswith("▦ To Research: Backtest the five strategies")
        assert "▦ Research desk took it, head @maya" in text
        assert "↳ @analyst: Run the backtests in Python" in text
        assert "• @analyst run_python · backtest.py" in text, "a step of the desk's person is shown"
        assert "✓ @analyst finished (4 steps)" in text
        assert "⚑ The auditor has concerns: Two of the five backtests have no costs" in text
        assert "◇ @maya is checking it" in text and "◆ @maya sent it back: add the drawdowns" in text
        assert tap.lines[-1] == "▦ Research desk finished"
        assert "Sales" not in text and "@rep" not in text and "call them" not in text
        assert other.lines == [], "a chat sees only its own turn"
    finally:
        phonelive.close(tap)
        phonelive.close(other)
    assert not phonelive._TAPS


def test_a_specialist_handed_work_from_the_chat_is_followed_too():
    """`delegate` straight from the chat: the child run names the chat (fabric's status event)."""
    tap = phonelive.listen("c1")
    try:
        phonelive.observe({"type": "tool_start", "conversation_id": "c1", "name": "delegate",
                           "args": {"subagent": "researcher", "task": "Find three sources"}})
        phonelive.observe({"type": "fabric_event", "run_id": "S1", "event": "status", "status": "running",
                           "ref": "researcher", "parent_run": "", "conversation_id": "c1"})
        phonelive.observe({"type": "fabric_event", "run_id": "S1", "event": "step", "tool": "web_search",
                           "status": "start", "detail": "solar output 2026"})
        phonelive.observe({"type": "tool_start", "conversation_id": "c1", "name": "mcp__bento__delegate"})
        phonelive.observe({"type": "tool_start", "conversation_id": "c1", "name": "recall"})
        assert tap.lines == ["↳ To @researcher: Find three sources",
                             "• @researcher web_search · solar output 2026"]
    finally:
        phonelive.close(tap)
    src = (ROOT / "agentos" / "fabric.py").read_text()
    assert '**({"conversation_id": conversation_id}' in src, "a chat's own specialist names the chat"


def test_the_server_feeds_every_broadcast_to_the_taps():
    src = (ROOT / "agentos" / "server.py").read_text()
    assert src.count("phonelive.observe(event)") == 2, "broadcast and broadcast_user both feed it"


def _run_live(make, script):
    async def go():
        tap = phonelive.listen("c1")
        live = make(tap)
        for delay, ev in script:
            await asyncio.sleep(delay)
            if ev:
                phonelive.observe(ev)
        await live.end()
        return live
    return asyncio.run(go())


def test_telegram_edits_one_message_and_a_quick_turn_sends_none():
    sent, edits = [], []

    async def send(text):
        sent.append(text)
        return 77

    async def edit(mid, text):
        edits.append((mid, text))
    evs = _desk_run("c1")
    script = [(0, evs[0]), (0, evs[1]), (0.15, evs[3]), (0.15, evs[5]), (0.15, evs[-1]), (0.15, None)]
    _run_live(lambda tap: phonelive.Live(tap, send, edit, every=0.05, first=0.1), script)
    assert len(sent) == 1 and sent[0].startswith("⚙ Steps so far\n▦ To Research")
    assert edits and all(mid == 77 for mid, _ in edits)
    assert edits[-1][1].startswith("✓ Steps\n") and edits[-1][1].endswith("▦ Research desk finished")

    sent.clear(), edits.clear()
    _run_live(lambda tap: phonelive.Live(tap, send, edit, every=0.05, first=5), [(0, evs[0])])
    assert sent == [] and edits == [], "a turn that ends before `first` sends no steps"
    assert not phonelive._TAPS


def test_whatsapp_gets_short_batches_and_a_ceiling():
    sent = []

    async def send(text):
        sent.append(text)
    script = [(0.12, {"type": "tool_start", "conversation_id": "c1", "name": "web_search",
                      "detail": f"query {i}"}) for i in range(14)]
    _run_live(lambda tap: phonelive.Live(tap, send, every=0.01, first=0, cap=3), script)
    assert sent[0].startswith("⚙ • web_search · query 0")
    assert 3 <= len(sent) <= 5
    assert sent[3].startswith("⚙ …more steps are going on"), "past the ceiling it says so once"
    assert sum("more steps" in s for s in sent) == 1


def test_the_long_view_keeps_the_last_lines():
    text = phonelive.text_of([f"• step {i}" for i in range(30)])
    assert text.startswith(f"⚙ Steps so far (last {phonelive.SHOW} of 30)")
    assert text.endswith("• step 29") and "• step 15" not in text


def test_a_telegram_turn_shows_its_steps_before_the_answer(tmp_path, monkeypatch):
    from agentos import phoneturn
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    cfg = {"agent_name": "Aria", "autonomy": "full",
           "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 5}}
    store = Store(tmp_path / "a.db")
    calls = []

    async def bc(ev):                 # the server's broadcast feeds the taps
        phonelive.observe(ev)
    b = TelegramBridge(cfg, store, Toolbox(cfg, store), bc)
    store.tg_upsert_chat(5, "PC", "", "private")
    store.tg_set_allowed(5, 1)

    async def api(method, **kw):
        calls.append((method, kw.get("text", ""), kw.get("disable_notification")))
        return {"message_id": 41} if method == "sendMessage" else {}
    b._api = api
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")
    monkeypatch.setattr(phonelive.Live.__init__, "__defaults__", (None, 0.05, 0.05, 8))

    async def fake_answer(store, cfg, toolbox, *, cid, emit, **kw):
        for ev in _desk_run(cid):
            if ev["type"] == "tool_start":
                await emit(ev)          # the lead's step, through the bridge's own emit
            else:
                await bc(ev)            # the desk's run, as fabric broadcasts it
            await asyncio.sleep(0.03)
        await asyncio.sleep(0.1)
        return {"reply": "Sharpe ratios: …", "steps": [], "meta": {}}
    monkeypatch.setattr(phoneturn, "answer", fake_answer)
    asyncio.run(b._handle({"chat": {"id": 5, "type": "private"}, "from": {"first_name": "PC"},
                           "text": "@Research backtest the five strategies"}))
    texts = [(m, t) for m, t, _ in calls if m in ("sendMessage", "editMessageText")]
    first_steps = next(i for i, (m, t) in enumerate(texts) if t.startswith("⚙ Steps"))
    answer = texts.index(("sendMessage", "Sharpe ratios: …")) if ("sendMessage", "Sharpe ratios: …") in texts \
        else next(i for i, (m, t) in enumerate(texts) if "Sharpe" in t)
    assert first_steps < answer, "the steps come while it works, before the answer"
    last_edit = max(i for i, (m, t) in enumerate(texts) if m == "editMessageText")
    assert last_edit < answer and texts[last_edit][1].startswith("✓ Steps")
    assert "▦ Research desk took it" in texts[last_edit][1]
    assert [c for c in calls if c[1].startswith("⚙ Steps")][0][2] is True, "the steps don't buzz the phone"
    assert not phonelive._TAPS, "the turn's tap is closed"


def test_both_channels_have_a_switch():
    assert phonelive.on({}, "telegram") and not phonelive.on({"telegram": {"live_steps": False}}, "telegram")
    adm = (ROOT / "agentos" / "telegram_admin.py").read_text()
    assert '("/steps", "[on|off]"' in adm and "async def _cmd_steps(" in adm
    wa = (ROOT / "agentos" / "whatsapp.py").read_text()
    assert 'low.startswith("/steps")' in wa and '["live_steps"]' in wa
