"""History rebuild: tool traces survive the turn, and a long thread compacts
instead of dying at the context window."""

import os
import tempfile

import pytest

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import history                     # noqa: E402
from agentos.memory import Store                # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "t.db")


def _cfg(**kw):
    c = {"default_model": "ollama/x", "ollama_num_ctx": 24576}
    c.update(kw)
    return c


# ---------------------------------------------------------------------------
# tool traces
# ---------------------------------------------------------------------------

def test_trace_block_keeps_name_args_and_head_of_output():
    steps = [{"type": "tool", "name": "read_file", "args": {"path": "/etc/hosts"},
              "output": "127.0.0.1 localhost", "ok": True},
             {"type": "text", "text": "ignored"}]
    b = history.trace_block(steps)
    assert "read_file" in b and "/etc/hosts" in b and "127.0.0.1 localhost" in b
    assert b.startswith("<tool_trace>") and b.endswith("</tool_trace>")


def test_trace_block_marks_failures_and_truncates():
    steps = [{"type": "tool", "name": "fetch_url", "args": {}, "output": "x" * 5000, "ok": False}]
    b = history.trace_block(steps, limit=100)
    assert "[failed]" in b
    assert "not kept" in b
    assert len(b) < 500


def test_trace_block_empty_without_tools():
    assert history.trace_block([{"type": "text", "text": "hi"}]) == ""


def test_trace_block_caps_number_of_calls():
    steps = [{"type": "tool", "name": f"t{i}", "args": {}, "output": "o", "ok": True}
             for i in range(40)]
    b = history.trace_block(steps, max_calls=5)
    assert b.count("\n- ") <= 6          # 5 calls + the "omitted" note
    assert "earlier call(s) in this turn omitted" in b


@pytest.mark.asyncio
async def test_history_replays_tool_traces_to_the_next_turn(store):
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "what is in hosts?")
    store.add_message(cid, "assistant", "It maps localhost.",
                      {"steps": [{"type": "tool", "name": "read_file",
                                  "args": {"path": "/etc/hosts"},
                                  "output": "127.0.0.1 localhost", "ok": True}]})
    hist, info = await history.build(store, cid, _cfg())
    assert info["compacted"] == 0
    assert hist[-1]["role"] == "assistant"
    # the model can now see WHICH file it read and WHAT came back
    assert "read_file" in hist[-1]["content"]
    assert "/etc/hosts" in hist[-1]["content"]
    assert "It maps localhost." in hist[-1]["content"]


@pytest.mark.asyncio
async def test_tool_trace_can_be_turned_off(store):
    cid = store.create_conversation("t")
    store.add_message(cid, "assistant", "done",
                      {"steps": [{"type": "tool", "name": "read_file", "args": {},
                                  "output": "x", "ok": True}]})
    hist, _ = await history.build(store, cid, _cfg(history={"tool_trace": False}))
    assert "read_file" not in hist[-1]["content"]


@pytest.mark.asyncio
async def test_images_survive_the_rebuild(store):
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "look", {"images": ["data:image/png;base64,AAA"]})
    hist, _ = await history.build(store, cid, _cfg())
    assert hist[-1]["images"] == ["data:image/png;base64,AAA"]


@pytest.mark.asyncio
async def test_internal_id_never_reaches_the_model(store):
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "hi")
    hist, _ = await history.build(store, cid, _cfg())
    assert all("_id" not in m for m in hist)


# ---------------------------------------------------------------------------
# budget + compaction
# ---------------------------------------------------------------------------

def test_budget_follows_the_local_context_window():
    small = history.budget_chars({"default_model": "ollama/x", "ollama_num_ctx": 8192})
    big = history.budget_chars({"default_model": "ollama/x", "ollama_num_ctx": 131072})
    assert big > small
    # an explicit setting always wins over the derived one
    assert history.budget_chars({"history": {"budget_tokens": 100},
                                 "default_model": "ollama/x"}) == 400


@pytest.mark.asyncio
async def test_long_thread_is_compacted_not_dropped(store, monkeypatch):
    calls = []

    async def fake_summarise(cfg, model, entries, previous=""):
        calls.append((model, len(entries), previous))
        return "SUMMARY OF EARLIER"

    monkeypatch.setattr(history, "summarise", fake_summarise)
    cid = store.create_conversation("t")
    for i in range(60):
        store.add_message(cid, "user", f"question {i} " + "x" * 400)
        store.add_message(cid, "assistant", f"answer {i} " + "y" * 400)

    hist, info = await history.build(store, cid, _cfg(history={"budget_tokens": 1000}))
    assert info["compacted"] > 0
    assert calls, "the summariser was never called"
    # the summary leads, as a system message, and the newest turn is still verbatim
    assert hist[0]["role"] == "system"
    assert "SUMMARY OF EARLIER" in hist[0]["content"]
    assert "answer 59" in hist[-1]["content"]
    assert sum(len(m["content"]) for m in hist) < 1000 * history.CHARS_PER_TOKEN + 2000
    # and it is persisted, so the next turn does not pay for it again
    conv = store.get_conversation(cid)
    assert conv["summary"] == "SUMMARY OF EARLIER"
    assert conv["summary_upto"]
    assert conv["summary_msgs"] == info["compacted"]


@pytest.mark.asyncio
async def test_second_pass_reuses_the_stored_summary(store, monkeypatch):
    n = {"calls": 0}

    async def fake_summarise(cfg, model, entries, previous=""):
        n["calls"] += 1
        return f"S{n['calls']}"

    monkeypatch.setattr(history, "summarise", fake_summarise)
    cid = store.create_conversation("t")
    for i in range(40):
        store.add_message(cid, "user", "q " + "x" * 400)
        store.add_message(cid, "assistant", "a " + "y" * 400)
    cfg = _cfg(history={"budget_tokens": 1000})
    await history.build(store, cid, cfg)
    first = n["calls"]
    hist, info = await history.build(store, cid, cfg)
    # nothing new fell out of the budget, so no second summarisation
    assert n["calls"] == first
    assert info["compacted"] == 0
    assert hist[0]["content"].startswith(history.SUMMARY_HEADER)


@pytest.mark.asyncio
async def test_newest_message_is_kept_even_when_it_alone_blows_the_budget(store, monkeypatch):
    async def fake_summarise(cfg, model, entries, previous=""):
        return "S"

    monkeypatch.setattr(history, "summarise", fake_summarise)
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "old")
    store.add_message(cid, "user", "z" * 50_000)
    hist, _ = await history.build(store, cid, _cfg(history={"budget_tokens": 10}))
    assert hist[-1]["content"].startswith("z")


@pytest.mark.asyncio
async def test_compaction_off_still_says_so(store):
    cid = store.create_conversation("t")
    for i in range(30):
        store.add_message(cid, "user", "x" * 500)
    hist, info = await history.build(
        store, cid, _cfg(history={"budget_tokens": 100, "compact": False}))
    assert info["compacted"] > 0
    assert not info["summary"]
    assert any("dropped" in (r.get("message") or "") for r in store.list_logs(limit=20))


@pytest.mark.asyncio
async def test_summariser_failure_falls_back_to_a_digest(store, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(history.providers, "complete", boom)
    entries = [{"role": "user", "content": "the port is 8321"},
               {"role": "assistant", "content": "noted"}]
    out = await history.summarise({}, "ollama/x", entries)
    assert "8321" in out          # the thread is degraded, never lost


@pytest.mark.asyncio
async def test_no_model_configured_still_produces_a_digest(store):
    out = await history.summarise({}, "", [{"role": "user", "content": "hello there"}])
    assert "hello there" in out
