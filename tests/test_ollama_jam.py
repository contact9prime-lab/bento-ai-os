"""A local model that is busy or oversized never holds a chat.

Found on the owner's machine: every chat sat on "sent — waking the agent" with Claude
Code as the brain, and a local model read "loading model" for minutes. Measured there:

- Ollama had qwen3.5:9b loaded at a 262,144-token window, 13.3 of the GPU's 16 GB. Its
  log showed the window on requests of about a thousand tokens: the background calls
  (`providers.complete`: memory extraction, summaries) sent no context size, and this
  Ollama then loads the model at its own default.
- With the GPU full, one embedding request took 2 min 30 s. The memory ranking in front
  of every forwarded turn (`agent.memory_text`) waited on it for up to 120 s before the
  turn had even started.

What these defend: every call to Ollama carries a context size, one size for all of them
unless the prompt needs more; and the ranking in front of a turn waits a few seconds at
most, once, then leaves the embedding model alone for a minute.
"""
import asyncio
import inspect
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import agent as agentmod, knowledge, providers          # noqa: E402
from agentos.memory import Store                                     # noqa: E402


def test_every_call_to_ollama_says_how_big_its_window_is(monkeypatch):
    seen = []

    async def fake(base_url, model, messages, tools, options=None):
        seen.append(options)
        yield {"type": "text", "text": "ok"}
    monkeypatch.setattr(providers, "_chat_ollama", fake)
    cfg = {"providers": {"ollama": {"base_url": "http://x", "enabled": True}}, "ollama_num_ctx": 24576}
    assert asyncio.run(providers.complete(cfg, "ollama/qwen3.5:9b", "Summarise this.")) == "ok"
    assert seen[-1]["num_ctx"] == 24576, "a background call no longer leaves the size to Ollama"

    async def run(options, messages):
        async for _ in providers.chat(cfg, "ollama/qwen3.5:9b", messages, [], options):
            pass
    # the agent loop's own size is kept as it is: one size, so the model is not reloaded
    asyncio.run(run({"num_ctx": 49152, "think": False}, [{"role": "user", "content": "hi"}]))
    assert seen[-1] == {"num_ctx": 49152, "think": False}
    # other options are kept, and the size is added
    asyncio.run(run({"num_predict": 200}, [{"role": "user", "content": "hi"}]))
    assert seen[-1] == {"num_predict": 200, "num_ctx": 24576}
    # a prompt too long for it gets a window that fits, in whole steps, under a ceiling
    asyncio.run(run(None, [{"role": "user", "content": "x" * 150_000}]))
    assert seen[-1]["num_ctx"] > 24576 and seen[-1]["num_ctx"] % 4096 == 0
    asyncio.run(run(None, [{"role": "user", "content": "x" * 3_000_000}]))
    assert seen[-1]["num_ctx"] == providers.OLLAMA_WINDOW_CEILING
    assert providers.OLLAMA_WINDOW_CEILING < 262144


def test_the_ranking_in_front_of_a_turn_never_holds_it(monkeypatch):
    calls = []

    async def stuck(cfg, texts):
        calls.append(time.time())
        await asyncio.sleep(30)          # an embedding model waiting for a full GPU
    monkeypatch.setattr(knowledge, "embed_texts", stuck)
    monkeypatch.setattr(knowledge, "_quick", {"until": 0.0})
    mems = [{"id": i, "content": f"fact {i}", "embedding": "[1, 0]"} for i in range(40)]
    t0 = time.time()
    assert asyncio.run(knowledge.quick_rank({}, mems, "what do I like", wait=0.2)) is None
    assert time.time() - t0 < 2, "it gives up in the time it was given"
    # and is not asked again for a minute: one short wait, not one per message
    t0 = time.time()
    assert asyncio.run(knowledge.quick_rank({}, mems, "again", wait=0.2)) is None
    assert time.time() - t0 < 0.1 and len(calls) == 1
    assert knowledge.QUICK_WAIT <= 5 and knowledge.QUICK_BACKOFF >= 30


def test_the_lead_still_gets_its_memory_when_the_embedding_model_is_stuck(tmp_path, monkeypatch):
    async def stuck(cfg, texts):
        await asyncio.sleep(30)
    monkeypatch.setattr(knowledge, "embed_texts", stuck)
    monkeypatch.setattr(knowledge, "_quick", {"until": 0.0})
    monkeypatch.setattr(knowledge, "QUICK_WAIT", 0.2)
    store = Store(tmp_path / "m.db")
    for i in range(30):
        store.add_memory(f"The person's fact number {i}.", scope="user")
    cfg = {"memory": {"inject_user": 5, "inject_facts": 0}}
    t0 = time.time()
    text, _ = asyncio.run(agentmod.memory_text(cfg, store, "", "", "what do you know about me"))
    assert time.time() - t0 < 3
    assert text.count("The person's fact number") == 5, "the newest ones, as with no embedding model"


def test_a_working_embedding_model_still_ranks(monkeypatch):
    async def fine(cfg, texts):
        return [[1.0, 0.0]]
    monkeypatch.setattr(knowledge, "embed_texts", fine)
    monkeypatch.setattr(knowledge, "_quick", {"until": 0.0})
    mems = [{"id": 1, "content": "far", "embedding": "[0, 1]"}, {"id": 2, "content": "near", "embedding": "[1, 0]"}]
    got = asyncio.run(knowledge.quick_rank({}, mems, "q"))
    assert [m["id"] for m in got] == [2, 1]


def test_nothing_a_turn_waits_on_calls_the_unbounded_ranking():
    from agentos import tools, zeromind
    for mod in (agentmod, tools, zeromind):
        assert "knowledge.semantic_rank(" not in inspect.getsource(mod), mod.__name__
    from agentos import server
    src = inspect.getsource(server._run_chat)
    assert src.index("reading what I know about you") < src.index("mind=await execmod.mind_note(")


def test_a_window_that_had_to_grow_is_kept_for_that_model(monkeypatch):
    """Asked for as "if the context window changes locally because it can't fit, that
    should be stored somewhere in the config"."""
    from agentos import config as cfgmod, users
    saved = []
    monkeypatch.setattr(cfgmod, "save_config", lambda c: saved.append(dict(c.get("ollama_windows") or {})))
    cfg = {"providers": {"ollama": {"base_url": "http://x", "enabled": True}}, "ollama_num_ctx": 24576}
    seen = []

    async def fake(base_url, model, messages, tools, options=None):
        seen.append(options["num_ctx"])
        yield {"type": "text", "text": "ok"}
    monkeypatch.setattr(providers, "_chat_ollama", fake)

    async def run(model, text):
        async for _ in providers.chat(cfg, model, [{"role": "user", "content": text}], []):
            pass
    asyncio.run(run("ollama/qwen3.5:9b", "x" * 150_000))
    grown = seen[-1]
    assert grown > 24576 and cfg["ollama_windows"] == {"qwen3.5:9b": grown} and saved == [{"qwen3.5:9b": grown}]
    # the next call to that model starts there, short prompt or not: one size, no reload
    asyncio.run(run("ollama/qwen3.5:9b", "hi"))
    assert seen[-1] == grown and len(saved) == 1, "and nothing is written when nothing grew"
    # another model keeps the machine's size
    asyncio.run(run("ollama/gemma4:12b", "hi"))
    assert seen[-1] == 24576
    # it only ever grows, and never past the ceiling
    assert providers.learn_window(cfg, "qwen3.5:9b", 30000) is False
    assert providers.learn_window(cfg, "qwen3.5:9b", 10 ** 9) is True
    assert cfg["ollama_windows"]["qwen3.5:9b"] == providers.OLLAMA_WINDOW_CEILING
    assert "ollama_windows" in users.USER_KEYS and cfgmod.DEFAULTS["ollama_windows"] == {}


def test_the_agent_loop_starts_at_the_kept_window_and_keeps_what_it_grows(monkeypatch):
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "save_config", lambda c: None)
    cfg = {"ollama_num_ctx": 24576, "ollama_windows": {"qwen3.5:9b": 49152}}
    a = agentmod.Agent.__new__(agentmod.Agent)
    a.cfg, a.model = cfg, "ollama/qwen3.5:9b"
    assert a._gen_options()["num_ctx"] == 49152
    a._ctx_up, a._ctx_need = True, 61440
    assert a._gen_options()["num_ctx"] == 98304
    assert cfg["ollama_windows"]["qwen3.5:9b"] == 98304, "the size it had to grow to is kept"
    b = agentmod.Agent.__new__(agentmod.Agent)
    b.cfg, b.model = cfg, "anthropic/claude-opus-5-5"
    assert b._gen_options()["num_ctx"] == 24576, "only a local model's window is this machine's to learn"
