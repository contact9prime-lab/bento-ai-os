"""The chat turn is stitched: what was attached, what was said and what was spent all arrive.

Found by reading one chat turn end to end (`server._run_chat`). Each of these passed every
test and failed a person:

- a picture attached in chat never reached a CLI brain (Claude Code answered as if nothing
  was attached);
- a turn on a CLI brain that was stopped or failed half-way saved an empty reply;
- `@researcher summarise it` ran with the task alone, so there was no "it";
- a chat turn on a CLI brain was missing from Usage.
"""
import asyncio
import base64
import copy
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors as ex  # noqa: E402

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


# --- pictures ---------------------------------------------------------------------------

def test_a_picture_is_part_of_claude_codes_first_message():
    blocks = ex.image_blocks("what is this?", (PNG,))
    assert blocks[0] == {"type": "text", "text": "what is this?"}
    assert blocks[1]["type"] == "image" and blocks[1]["source"]["media_type"] == "image/png"
    assert blocks[1]["source"]["data"] == PNG.split(";base64,", 1)[1]
    assert ex.image_blocks("no picture", ()) == "no picture", "a turn without one is the text, as before"


def test_only_pictures_survive_the_envelope_and_they_do_survive(tmp_path):
    env = ex.Envelope(workspace=str(tmp_path), images=(PNG, "data:text/html;base64,PGI+", "http://x/y.png", PNG))
    kept = env.sanitized().images
    assert kept == (PNG, PNG), "sanitized() once dropped a new field and nothing steered"
    assert len(ex.Envelope(workspace=str(tmp_path), images=(PNG,) * 9).sanitized().images) == ex.MAX_IMAGES


def test_a_cli_that_reads_one_prompt_gets_the_pictures_as_files(tmp_path):
    env = ex.Envelope(workspace=str(tmp_path), engine="gemini-cli", images=(PNG,))
    line = ex._attach(env)
    paths = [ln for ln in line.splitlines() if ln.startswith(str(tmp_path))]
    assert len(paths) == 1 and Path(paths[0]).read_bytes().startswith(b"\x89PNG")
    assert "ATTACHED BY THE PERSON" in line
    assert ex._attach(ex.Envelope(workspace=str(tmp_path))) == ""


def test_run_task_hands_the_pictures_over(tmp_path, monkeypatch):
    """Claude Code: its first message carries them, on the stream input even when the turn
    was not steerable. Another CLI: files named in its prompt."""
    seen = {}

    async def drive(cmd, cwd, emit, run, extra_env=None, first=None, prompt=None):
        seen.update(cmd=cmd, first=first, prompt=prompt)
        return run
    monkeypatch.setattr(ex, "_drive", drive)
    monkeypatch.setattr(ex, "_jailed", lambda cmd, e: cmd)
    monkeypatch.setattr(ex, "confine", lambda e: (e, "", ""))

    async def emit(_ev):
        pass
    asyncio.run(ex.run_task("what is this?", ex.Envelope(workspace=str(tmp_path), images=(PNG,)), emit))
    assert isinstance(seen["first"], list) and seen["first"][1]["type"] == "image"
    assert "stream-json" in " ".join(seen["cmd"]) and seen["prompt"] is None

    seen.clear()
    asyncio.run(ex.run_task("what is this?", ex.Envelope(workspace=str(tmp_path), engine="codex",
                                                         images=(PNG,)), emit))
    assert seen["first"] is None and "ATTACHED BY THE PERSON" in seen["prompt"]


# --- the thread, for whoever is addressed by name ----------------------------------------

def test_the_thread_note_is_the_conversation_and_empty_for_a_first_message():
    assert ex.thread_note([]) == ""
    note = ex.thread_note([
        {"role": "user", "content": "which three EV makers grew fastest?"},
        {"role": "assistant", "content": "BYD, Tesla and Xiaomi.", "meta": {}},
        {"role": "assistant", "content": "I checked the filings.", "meta": {"speaker": "validator"}},
        {"role": "tool", "content": "ignored"}], lead="Aria")
    assert "Person: which three EV makers" in note and "Aria: BYD, Tesla and Xiaomi." in note
    assert "@validator: I checked the filings." in note and "ignored" not in note
    assert note.startswith("SAID IN THIS CONVERSATION BEFORE YOU WERE ASKED")


# --- the turn itself ---------------------------------------------------------------------

def _chat(monkeypatch, run_task, data, prior=()):
    """One real `_run_chat` with Claude Code stood in for by `run_task`."""
    from fastapi.testclient import TestClient
    from agentos import server
    monkeypatch.setattr(ex, "run_task", run_task)
    monkeypatch.setattr(ex, "resolve_engine", lambda cfg, requested="": "claude-code")
    monkeypatch.setattr(ex, "available", lambda *a, **k: {"available": True})
    monkeypatch.setattr(ex, "open_team_door", lambda *a, **k: "")
    monkeypatch.setattr(server, "_agent_cli_refused", lambda m: "")
    with TestClient(server.app) as cl:
        store = server.state["store"]
        cid = store.create_conversation("stitch")
        for role, text, meta in prior:
            store.add_message(cid, role, text, meta)
        cl.portal.call(server._run_chat, cid, data)
        msgs = store.get_messages(cid)
        usage = [dict(r) for r in store.db.execute(
            "SELECT model, tokens_in, tokens_out, cost_usd FROM usage WHERE conversation_id=?", (cid,))]
    return msgs, usage


def test_a_stopped_cli_turn_keeps_what_it_had_said(monkeypatch):
    async def run_task(task, env, emit, run=None):
        await emit({"type": "text_delta", "text": "Here is the first half"})
        raise asyncio.CancelledError()
    msgs, _ = _chat(monkeypatch, run_task, {"text": "write it", "model": ""})
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "Here is the first half", "it saved an empty reply"
    assert msgs[1]["meta"].get("engine") == "claude-code", "and it still says who answered"


def test_a_turn_stopped_before_a_word_is_not_a_blank_bubble(monkeypatch):
    async def run_task(task, env, emit, run=None):
        raise asyncio.CancelledError()
    msgs, _ = _chat(monkeypatch, run_task, {"text": "write it", "model": ""})
    assert msgs[1]["content"] == "(stopped before it answered)"


def test_a_failed_cli_turn_keeps_its_text_and_says_why(monkeypatch):
    async def run_task(task, env, emit, run=None):
        await emit({"type": "text_delta", "text": "Half an answer"})
        raise RuntimeError("the pipe broke")
    msgs, _ = _chat(monkeypatch, run_task, {"text": "write it", "model": ""})
    assert msgs[1]["content"].startswith("Half an answer\n\n[error] ")


def test_a_cli_chat_turn_is_in_usage_with_the_bill_it_reported(monkeypatch):
    async def run_task(task, env, emit, run=None):
        await emit({"type": "text_delta", "text": "Done."})
        run.cost_usd, run.tokens_in, run.tokens_out, run.model = 0.42, 1200, 80, "claude-opus"
        return run
    msgs, usage = _chat(monkeypatch, run_task, {"text": "hello", "model": ""})
    assert msgs[1]["content"] == "Done."
    assert usage == [{"model": "claude-code", "tokens_in": 1200, "tokens_out": 80, "cost_usd": 0.42}], \
        "what it spent was kept only inside the message"


def test_the_pictures_reach_the_brain_that_answers(monkeypatch):
    got = {}

    async def run_task(task, env, emit, run=None):
        got["images"] = env.images
        await emit({"type": "text_delta", "text": "A red square."})
        return run
    _chat(monkeypatch, run_task, {"text": "what is this?", "model": "", "images": [PNG]})
    assert got["images"] == (PNG,)


def test_an_agent_addressed_by_name_reads_the_thread(monkeypatch):
    from agentos import server
    seen = {}

    async def run_subagent(self, defn, task, context="", **kw):
        seen.update(task=task, context=context)
        return {"content": "A summary.", "status": "ok", "fault": "", "steps": [], "model": "m", "usage": {}}
    monkeypatch.setattr(server.fabricmod, "parse_huddle", lambda store, text: None)
    monkeypatch.setattr(server.fabricmod, "parse_mention",
                        lambda store, text: ({"name": "researcher", "model": ""}, "summarise it")
                        if text.startswith("@researcher") else None)

    async def never(*a, **k):
        raise AssertionError("an address beats the brain")
    # on the class: the server builds its control plane again at each start
    monkeypatch.setattr(server.fabricmod.ControlPlane, "run_subagent", run_subagent)
    monkeypatch.setattr(server.fabricmod.ControlPlane, "resolve_model", lambda self, defn: "m")
    msgs, _ = _chat(monkeypatch, never, {"text": "@researcher summarise it", "model": ""},
                    prior=[("user", "which EV makers grew fastest?", None),
                           ("assistant", "BYD, Tesla and Xiaomi grew fastest.", None)])
    assert seen["task"] == "summarise it"
    assert "BYD, Tesla and Xiaomi grew fastest." in seen["context"], "there was no 'it' to summarise"
    assert "@researcher summarise it" not in seen["context"], "the request itself is not history"
    assert msgs[-1]["meta"].get("speaker") == "researcher"


# --- a phone turn is the same turn (phoneturn.py) ----------------------------------------

def _phone(tmp_path, extra=None):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    cfg = {"agent_name": "Aria", "autonomy": "full", "default_model": "openai/first",
           "providers": {"openai": {"enabled": True, "api_key": "k"}},
           "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 5}, **(extra or {})}
    store = Store(tmp_path / "a.db")
    events, sent = [], []

    async def bc(ev):
        events.append(ev)
    b = TelegramBridge(cfg, store, Toolbox(cfg, store), bc)
    store.tg_upsert_chat(5, "PC", "", "private")
    store.tg_set_allowed(5, 1)

    async def api(method, **kw):
        sent.append((method, kw.get("text", "")))
        return {}
    b._api = api
    return b, events, sent


def _say(b, text, **more):
    asyncio.run(b._handle({"chat": {"id": 5, "type": "private"}, "from": {"first_name": "PC"},
                           "text": text, **more}))
    cid = b.store.tg_list_chats()[0]["conversation_id"]
    return b.store.get_messages(cid), cid


def test_a_phone_turn_whose_brain_is_out_goes_to_the_next(tmp_path, monkeypatch):
    """Fallback lived in the desktop's chat runner alone: a usage limit on Claude Code simply
    failed on Telegram, the surface where nobody is watching."""
    import agentos.agent as agentmod
    b, events, sent = _phone(tmp_path, {"engine": "claude-code",
                                        "brain_fallbacks": [{"executor": "aria", "model": "openai/second"}]})
    monkeypatch.setattr(ex, "resolve_engine", lambda cfg, requested="": "claude-code")
    asked = []

    async def forward(engine, text, cfg, ws, emit=None, **kw):
        asked.append(engine)
        await emit({"type": "error", "message": "You've hit your usage limit · resets 6pm"})
        return "[error] You've hit your usage limit · resets 6pm", None
    monkeypatch.setattr(ex, "forward", forward)

    class FakeAgent:
        partial_steps = []

        def __init__(self, cfg, toolbox, model, *a, **k):
            asked.append(model)

        async def run(self, msgs):
            return {"content": "Answered by the second.", "steps": [], "tokens": {"input": 10, "output": 2}}
    monkeypatch.setattr(agentmod, "Agent", FakeAgent)
    msgs, _ = _say(b, "hello")
    assert asked == ["claude-code", "openai/second"]
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["content"] == "Answered by the second."
    assert any("isn't available right now" in t and "openai/second" in t for _m, t in sent), "and the phone is told"


def test_a_cli_turn_from_a_phone_is_in_usage(tmp_path, monkeypatch):
    b, events, sent = _phone(tmp_path)
    monkeypatch.setattr(ex, "resolve_engine", lambda cfg, requested="": "claude-code")

    async def forward(engine, text, cfg, ws, emit=None, run=None, **kw):
        run.cost_usd, run.tokens_in, run.tokens_out, run.session_id = 0.2, 900, 40, "s1"
        return "the news", run
    monkeypatch.setattr(ex, "forward", forward)
    msgs, cid = _say(b, "what is in the news")
    rows = [tuple(r) for r in b.store.db.execute(
        "SELECT model, tokens_in, cost_usd, surface FROM usage WHERE conversation_id=?", (cid,))]
    assert rows == [("claude-code", 900, 0.2, "telegram")]
    assert msgs[1]["meta"]["exec_session"] == "s1"


def test_a_photo_from_telegram_reaches_the_brain(tmp_path, monkeypatch):
    """A photo was ignored without a word: `_handle` returned on a message with no text."""
    import agentos.telegram as tgmod
    b, events, sent = _phone(tmp_path)
    monkeypatch.setattr(ex, "resolve_engine", lambda cfg, requested="": "claude-code")
    got = {}

    async def forward(engine, text, cfg, ws, emit=None, images=(), **kw):
        got.update(text=text, images=images)
        return "A red square.", None
    monkeypatch.setattr(ex, "forward", forward)
    old_api = b._api

    async def api(method, **kw):
        if method == "getFile":
            return {"file_path": "photos/file_1.png"}
        return await old_api(method, **kw)
    b._api = api

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            got["url"] = url

            class R:
                status_code = 200
                content = b"\x89PNG\r\n\x1a\n" + b"0" * 40
            return R()
    monkeypatch.setattr(tgmod.httpx, "AsyncClient", Client)
    msgs, _ = _say(b, "", caption="what is this?", photo=[{"file_id": "small", "file_size": 900},
                                                          {"file_id": "big", "file_size": 90_000}])
    assert got["text"] == "what is this?" and len(got["images"]) == 1
    assert got["images"][0].startswith("data:image/png;base64,") and got["url"].endswith("/photos/file_1.png")
    assert msgs[0]["meta"].get("images"), "kept on the message, so the desktop's chat shows it too"
    assert ("sendMessage", "A red square.") in sent


def test_a_huddle_can_be_called_from_a_phone(tmp_path, monkeypatch):
    from agentos import fabric as fabricmod
    b, events, sent = _phone(tmp_path)
    seen = {}

    class Control:
        async def huddle(self, names, topic, conversation_id="", say=None, approver=None, **k):
            seen.update(names=names, topic=topic)
            await say({"agent": "researcher", "text": "I think so."})
            return {"text": "[huddle · researcher, validator · 1 round]\n@researcher (m): I think so.",
                    "agents": names}
    b.toolbox.fabric = Control()
    monkeypatch.setattr(fabricmod, "parse_huddle",
                        lambda store, text: (["researcher", "validator"], "should we ship it?")
                        if text.startswith("@researcher @validator") else None)
    msgs, _ = _say(b, "the launch is on Friday")          # an ordinary turn first
    msgs, _ = _say(b, "@researcher @validator should we ship it?")
    assert seen["names"] == ["researcher", "validator"]
    assert seen["topic"].startswith("should we ship it?") and "the launch is on Friday" in seen["topic"], \
        "the room reads the thread it was called in"
    assert msgs[-1]["meta"].get("huddle") == ["researcher", "validator"]
    assert any(e.get("type") == "agent_say" for e in events), "and the Office sees them talk"


# --- what a forwarded lead knows (memory, graph, skills, servers) -------------------------

def test_a_forwarded_lead_reads_the_same_memory_as_the_built_in_one(tmp_path):
    from agentos.agent import memory_text
    from agentos.memory import Store
    store = Store(tmp_path / "m.db")
    store.add_memory("The person trades Nifty options on Thursdays.", scope="user")
    store.kg_add("Acme", "is a client of", "the person")
    store.save_skill("weekly-report", "How the weekly report is laid out", "1. …")
    cfg = {"agent_name": "Aria"}
    built_in, _z = asyncio.run(memory_text(cfg, store))
    note = asyncio.run(ex.mind_note(cfg, None, store, "", "", "what do I trade?"))
    assert "trades Nifty options on Thursdays" in built_in and built_in.strip() in note, "one reading for both"
    assert "Acme" in note and "weekly-report" in note and "mcp__bento__use_skill" in note
    quiet = asyncio.run(ex.mind_note(cfg, None, store, door=False))
    assert "trades Nifty" in quiet and "use_skill" not in quiet, "a schedule is told of no tool it has not got"
    assert asyncio.run(ex.mind_note(cfg, None, None)) == ""


def test_the_door_has_the_memory_tools_and_says_where_memory_lives():
    assert set(ex.MIND_DOOR_TOOLS) <= set(ex.DOOR_TOOLS)
    assert not set(ex.MIND_DOOR_TOOLS) & set(ex.LINKED_LEAD_TOOLS), "a linked team's task gets none of it"
    rule = ex.mind_rule()
    assert "mcp__bento__remember" in rule and "mcp__bento__recall" in rule
    assert "Never keep it in your own memory files" in rule
    src = (Path(__file__).parent.parent / "agentos/executors.py").read_text()
    door = src[src.index("def open_team_door("):src.index("def _pool_note(")]
    assert door.index("finish_line()") < door.index("stage_note + dept_note"), \
        "near the top: a rule at the end of a long context is the one not followed"
    assert door.rstrip().endswith("capability_note() + mind\n    return token")


def test_both_leads_are_told_to_finish_the_job():
    """21 of the owner's last 133 replies from Claude Code ended on an offer to do the next
    step instead of doing it; neither lead's prompt asked it to finish."""
    from agentos import agent as agentmod
    line = ex.finish_line()
    assert line.startswith("FINISH THE JOB.") and "mcp__bento__schedule_task" in line
    assert "not that the reply is long" in line
    assert "{finish}" in agentmod.SYSTEM_PROMPT and "Be concise and concrete" not in agentmod.SYSTEM_PROMPT
    assert "`schedule_task`" in agentmod._finish_line()
    wa = (Path(__file__).parent.parent / "agentos/whatsapp.py").read_text()
    assert "Keep it \"\n                \"short enough" not in wa and "Do the whole" in wa


def test_one_fallback_rule_for_every_surface():
    from agentos import fallback
    cfg = {"providers": {"openai": {"enabled": True, "api_key": "k"}},
           "brain_fallbacks": [{"executor": "aria", "model": "openai/second"}]}
    tried = []
    nxt = fallback.after(cfg, tried, "claude-code", "", ["You've hit your usage limit"], "")
    assert nxt == {"executor": "aria", "model": "openai/second"} and tried == ["claude-code"]
    assert fallback.after(cfg, [], "claude-code", "", [], "A real answer.") is None
    assert fallback.after(cfg, [], "claude-code", "", ["turn stopped"], "") is None, "a stop is the person's"
    assert fallback.after(cfg, [], "claude-code", "", ["usage limit"], "", skip=["openai/second"]) is None
    root = Path(__file__).parent.parent / "agentos"
    for f in ("server.py", "phoneturn.py", "scheduler.py"):
        assert ".after(" in (root / f).read_text(), f
