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

REAL_LOADED = providers.ollama_loaded      # conftest stands a "nothing loaded" in for every test


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
    a.cfg, a.model_id = cfg, "ollama/qwen3.5:9b"
    assert a._gen_options()["num_ctx"] == 49152
    a._ctx_up, a._ctx_need = True, 61440
    assert a._gen_options()["num_ctx"] == 98304
    assert cfg["ollama_windows"]["qwen3.5:9b"] == 98304, "the size it had to grow to is kept"
    b = agentmod.Agent.__new__(agentmod.Agent)
    b.cfg, b.model_id = cfg, "anthropic/claude-opus-5-5"
    assert b._gen_options()["num_ctx"] == 24576, "only a local model's window is this machine's to learn"
    # the loop's real constructor sets the name these read (an attribute the test set by
    # hand hid a wrong one, and every local turn failed)
    import inspect as _i
    assert "self.model_id = model_id" in _i.getsource(agentmod.Agent.__init__)


def test_a_model_already_in_memory_is_not_loaded_again(monkeypatch):
    """Asked for as "if the local model is already loaded then it should not be loaded
    again, it is doing that a lot for the local models". Ollama reloads a model whenever a
    call names another window than the one it runs with."""
    loaded = {"gemma4:12b": 49152}

    async def ps(base_url):
        return dict(loaded)
    monkeypatch.setattr(providers, "ollama_loaded", ps)
    monkeypatch.setattr(providers, "_loaded", {"at": 0.0, "base": "", "models": {}})
    seen = []

    async def fake(base_url, model, messages, tools, options=None):
        seen.append((model, options["num_ctx"]))
        yield {"type": "text", "text": "ok"}
    monkeypatch.setattr(providers, "_chat_ollama", fake)
    cfg = {"providers": {"ollama": {"base_url": "http://x", "enabled": True}}, "ollama_num_ctx": 24576}

    async def run(model, options=None, text="hi"):
        async for _ in providers.chat(cfg, model, [{"role": "user", "content": text}], [], options):
            pass
    # a background call and the agent loop's own size both get the window it is running with
    asyncio.run(run("ollama/gemma4:12b"))
    asyncio.run(run("ollama/gemma4:12b", {"num_ctx": 24576, "think": False}))
    assert seen == [("gemma4:12b", 49152), ("gemma4:12b", 49152)]
    # a call that needs more than is loaded is the only one that loads it again
    asyncio.run(run("ollama/gemma4:12b", {"num_ctx": 65536}))
    assert seen[-1] == ("gemma4:12b", 65536)
    # a model that is not loaded gets the machine's size
    asyncio.run(run("ollama/qwen3.5:9b"))
    assert seen[-1] == ("qwen3.5:9b", 24576)
    # one loaded past the ceiling (the jam) is not kept that way
    loaded["qwen3.5:9b"] = 262144
    asyncio.run(run("ollama/qwen3.5:9b"))
    assert seen[-1] == ("qwen3.5:9b", 24576)


def test_what_is_loaded_is_read_from_ollama_and_never_holds_a_call(monkeypatch):
    import httpx
    asked = []

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "gemma4:12b", "model": "gemma4:12b", "context_length": 49152},
                               {"name": "broken"}]}

    class _C:
        def __init__(self, timeout=None):
            asked.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            if "down" in url:
                raise httpx.ConnectError("no")
            return _R()
    monkeypatch.setattr(providers.httpx, "AsyncClient", _C)
    monkeypatch.setattr(providers, "_loaded", {"at": 0.0, "base": "", "models": {}})
    assert asyncio.run(REAL_LOADED("http://up")) == {"gemma4:12b": 49152}
    assert asked == [1.5], "a short wait: this is asked in front of every call"
    assert asyncio.run(REAL_LOADED("http://up")) == {"gemma4:12b": 49152} and len(asked) == 1, "kept a few seconds"
    # an Ollama that does not answer is simply asked for the size we wanted
    assert asyncio.run(REAL_LOADED("http://down")) == {}
