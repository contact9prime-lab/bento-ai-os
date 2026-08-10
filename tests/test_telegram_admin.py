"""The Telegram admin console: operating the machine from the phone.

Two properties matter more than any individual command, and both are tested
here because both are the kind of thing a later refactor quietly loses:

  1. Only the paired OWNER may operate. Being allow-listed buys a conversation,
     not administration.
  2. A command is never cheaper than the equivalent tool call. `/run` is
     `delegate`, `/model` is `configure_agentos` — same PDP, same grants, same
     approval, same audit row. A console that bypassed the gate would be a
     second, unaudited way to use the machine.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import telegram_admin                       # noqa: E402
from agentos.memory import Store                         # noqa: E402
from agentos.policy import PDP                           # noqa: E402
from agentos.tools import Toolbox                        # noqa: E402

OWNER, GUEST = 111, 222


class FakeFabric:
    """Just enough to prove the command reached the run, not to run anything."""

    def __init__(self):
        self.ran = []

    async def run_subagent(self, defn, task, **kw):
        self.ran.append((defn["name"], task))
        return {"status": "ok", "content": "done", "steps": []}

    async def run_flow(self, flow, text, **kw):
        self.ran.append((flow["name"], text))
        return {"status": "ok", "content": "", "fault": "", "delegations": 0}


class FakeBridge:
    """Everything Console reaches for on the real TelegramBridge."""

    def __init__(self, tmp_path, autonomy="balanced", approve=True):
        self.store = Store(tmp_path / "t.db")
        self.cfg = {"autonomy": autonomy, "default_model": "ollama/qwen",
                    "workspace": str(tmp_path / "ws"), "policies": [],
                    "telegram": {"owner_chat_id": OWNER}}
        self.toolbox = Toolbox(self.cfg, self.store)
        self.toolbox.pdp = PDP(self.cfg, self.store)
        self.toolbox.fabric = FakeFabric()
        self.sent: list[str] = []
        self.asked: list[tuple] = []
        self._approve = approve
        self._busy = False
        self.broadcasts: list[dict] = []

    def _t(self):
        return self.cfg["telegram"]

    async def send(self, text, chat_id=None):
        self.sent.append(text)

    async def broadcast(self, ev):
        self.broadcasts.append(ev)

    async def ask_approval(self, chat_id, name, args, reason, offer=None, timeout=300):
        self.asked.append((name, args, reason, offer))
        return self._approve

    def _conversation_for_chat(self, chat_id):
        return "cid"


def _console(tmp_path, **kw):
    tg = FakeBridge(tmp_path, **kw)
    return telegram_admin.Console(tg), tg


async def _run(console, text, who=OWNER):
    return await console.handle(who, text)


# ------------------------------------------------- the gate

@pytest.mark.asyncio
async def test_only_the_owner_may_operate(tmp_path):
    console, tg = _console(tmp_path)
    assert await _run(console, "/logs", who=GUEST) is True   # handled...
    assert "owner of this machine only" in tg.sent[0]        # ...by refusing
    assert len(tg.sent) == 1


@pytest.mark.asyncio
async def test_an_unknown_slash_word_is_left_to_the_conversation(tmp_path):
    """/start and /clear belong to the bridge, and a sentence beginning with a
    slash is still a sentence — the console must not swallow either."""
    console, _ = _console(tmp_path)
    assert await _run(console, "/start") is False
    assert await _run(console, "/clear") is False
    assert await _run(console, "/why did that fail") is False


@pytest.mark.asyncio
async def test_help_lists_every_command_that_exists(tmp_path):
    console, tg = _console(tmp_path)
    await _run(console, "/help")
    for cmd, _, _ in telegram_admin.COMMANDS:
        assert cmd in tg.sent[0], f"{cmd} is missing from /help"


# ------------------------------------------------- reading

@pytest.mark.asyncio
async def test_logs_shows_the_diary_and_what_was_gated(tmp_path):
    """Both questions get asked from a phone: what has it been doing, and what
    did it decide it was allowed to do."""
    console, tg = _console(tmp_path)
    tg.store.log("agent", "wrote the morning report")
    tg.toolbox.pdp.decide(__import__("agentos.policy", fromlist=["MAIN"]).MAIN,
                          "agent.invoke", "agent:subagent/researcher", {"risk": "safe"})
    await _run(console, "/logs")
    out = tg.sent[0]
    assert "wrote the morning report" in out
    assert "Gated recently" in out and "agent.invoke" in out


@pytest.mark.asyncio
async def test_agents_and_perms_read_without_asking(tmp_path):
    console, tg = _console(tmp_path)
    tg.store.save_subagent({"name": "researcher", "soul": "you research things",
                            "tools": ["fetch_url"]})
    tg.store.add_grant("user", "", "agent.invoke", "agent:subagent/researcher")
    await _run(console, "/agents")
    await _run(console, "/perms")
    assert "researcher" in tg.sent[0]
    assert "agent.invoke" in tg.sent[1]
    assert not tg.asked, "listing what exists is not an action and must not prompt"


@pytest.mark.asyncio
async def test_logs_work_while_a_turn_is_running(tmp_path):
    """'What is it doing' is exactly the question you ask when it is busy, so the
    console must not queue behind the conversation lock."""
    console, tg = _console(tmp_path)
    tg._busy = True
    tg.store.log("agent", "still going")
    await _run(console, "/logs")
    assert "still going" in tg.sent[0]


# ------------------------------------------------- acting

@pytest.mark.asyncio
async def test_run_goes_through_the_same_consent_as_delegate(tmp_path):
    console, tg = _console(tmp_path)
    tg.store.save_subagent({"name": "researcher", "soul": "you research", "tools": ["fetch_url"]})
    await _run(console, "/run researcher find the EV numbers")
    assert tg.asked, "/run must ask exactly as delegate does"
    name, args, reason, offer = tg.asked[0]
    assert name == "delegate" and args["subagent"] == "researcher"
    assert offer and offer["resource"] == "agent:subagent/researcher"
    assert "fetch_url" in reason, "the phone gets the same informed card as the desktop"


@pytest.mark.asyncio
async def test_an_existing_grant_means_run_stops_asking(tmp_path):
    console, tg = _console(tmp_path)
    tg.store.save_subagent({"name": "researcher", "soul": "you research"})
    tg.store.add_grant("user", "", "agent.invoke", "agent:subagent/researcher")
    await _run(console, "/run researcher go")
    assert not tg.asked, "consent already given at the desk must carry to the phone"


@pytest.mark.asyncio
async def test_refusing_the_prompt_does_not_run_it(tmp_path):
    console, tg = _console(tmp_path)
    tg._approve = False
    tg.store.save_subagent({"name": "researcher", "soul": "you research"})
    await _run(console, "/run researcher go")
    assert "not approved" in tg.sent[-1]


@pytest.mark.asyncio
async def test_switching_the_model_is_gated_and_then_sticks(tmp_path, monkeypatch):
    console, tg = _console(tmp_path)
    from agentos import providers

    async def fake(_cfg):
        return [{"id": "ollama/qwen"}, {"id": "anthropic/claude-opus-5"}]
    monkeypatch.setattr(providers, "available_models", fake)

    await _run(console, "/model anthropic/claude-opus-5")
    assert tg.asked and tg.asked[0][0] == "configure_agentos"
    assert tg.cfg["default_model"] == "anthropic/claude-opus-5"
    assert {"type": "config"} in tg.broadcasts, "the desktop must learn it changed"


@pytest.mark.asyncio
async def test_an_unknown_model_is_refused_with_the_near_miss(tmp_path, monkeypatch):
    console, tg = _console(tmp_path)
    from agentos import providers

    async def fake(_cfg):
        return [{"id": "anthropic/claude-opus-5"}]
    monkeypatch.setattr(providers, "available_models", fake)
    await _run(console, "/model gpt-9")
    assert "not one of this machine's models" in tg.sent[-1]
    assert tg.cfg["default_model"] == "ollama/qwen", "nothing changed"
    # a unique substring is resolved rather than refused on a phone keyboard
    await _run(console, "/model opus")
    assert tg.cfg["default_model"] == "anthropic/claude-opus-5"


@pytest.mark.asyncio
async def test_a_broken_command_does_not_kill_the_poller(tmp_path):
    """The bridge is a long-running loop; one bad command must be one bad reply."""
    console, tg = _console(tmp_path)
    await _run(console, "/run nosuchagent do a thing")
    assert "no agent called" in tg.sent[-1]
    await _run(console, "/flow nosuchflow")
    assert "no flow called" in tg.sent[-1]


# ------------------------------------------------- wired into the real bridge

@pytest.mark.asyncio
async def test_the_real_bridge_routes_commands_to_the_console(tmp_path, monkeypatch):
    """The Console can be perfect and still never be reached. This drives
    TelegramBridge._handle itself: allow-list first, console before the turn."""
    from agentos.telegram import TelegramBridge

    store = Store(tmp_path / "t.db")
    cfg = {"autonomy": "balanced", "default_model": "m", "policies": [],
           "workspace": str(tmp_path / "ws"),
           "telegram": {"bot_token": "x", "owner_chat_id": OWNER}}
    toolbox = Toolbox(cfg, store)
    toolbox.pdp = PDP(cfg, store)
    toolbox.fabric = FakeFabric()

    sent = []

    async def _broadcast(_ev):
        pass

    tg = TelegramBridge(cfg, store, toolbox, _broadcast)

    async def _send(text, chat_id=None):
        sent.append(text)
    monkeypatch.setattr(tg, "send", _send)
    store.tg_upsert_chat(OWNER, "Owner", "", "private")
    store.tg_set_allowed(OWNER, 1)
    store.log("agent", "a thing happened")

    await tg._handle({"chat": {"id": OWNER, "type": "private"}, "text": "/logs",
                      "from": {"id": OWNER, "first_name": "P"}})
    assert any("a thing happened" in s for s in sent), sent
    assert not tg._busy, "a console command must not take the conversation lock"
