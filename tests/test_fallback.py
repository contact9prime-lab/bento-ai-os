"""If the lead's brain isn't available, the next one answers (agentos/fallback.py).

Asked for from Settings → AI providers: "a pool of models it can take from based on availability;
if one is not available, point to the other". These run a real chat turn through the chat
runner with a stand-in provider: the first brain answers with a usage limit, the next one
answers, and only the answer is kept."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fallback, providers  # noqa: E402

ROOT = Path(__file__).parent.parent


def test_only_unavailable_is_a_reason():
    assert fallback.unavailable(["You've hit your usage limit · resets 6pm"])
    assert fallback.unavailable(["HTTP 429: rate limit exceeded"])
    assert fallback.unavailable(["Claude Code is not logged in. Run /login"])
    assert fallback.unavailable(["ConnectError: All connection attempts failed"])
    assert not fallback.unavailable(["turn stopped"]), "a stop is the person's"
    assert not fallback.unavailable(["[denied] may not use model x"]), "a refusal is not routed around"
    assert not fallback.unavailable([""]) and not fallback.unavailable(["the file has a typo"])


def test_the_list_is_checked_at_the_write():
    cfg = {"providers": {"ollama": {}, "openai": {"api_key": "k"}}}
    got = fallback.clean([{"executor": "aria", "model": "ollama/qwen3.5:9b"},
                          {"executor": "ollama", "model": "qwen3.5:9b"},          # the same, said another way
                          {"executor": "claude-code", "model": "opus"}], cfg)
    assert got == [{"executor": "aria", "model": "ollama/qwen3.5:9b"}, {"executor": "claude-code", "model": "opus"}]
    with pytest.raises(ValueError):
        fallback.clean([{"executor": "made-up"}], cfg)
    with pytest.raises(ValueError):
        fallback.clean([{"executor": "aria", "model": "nothing"}], cfg)
    assert len(fallback.clean([{"executor": "aria", "model": f"ollama/m{i}"} for i in range(9)], cfg)) == fallback.MAX


def test_a_brain_that_cannot_run_here_is_skipped():
    cfg = {"providers": {"ollama": {}, "openai": {}, "anthropic": {"api_key": "k", "enabled": False}},
           "brain_fallbacks": [{"executor": "aria", "model": "openai/gpt-x"},          # no key
                               {"executor": "aria", "model": "anthropic/claude-x"},    # switched off
                               {"executor": "aria", "model": "ollama/qwen3.5:9b"}]}
    assert fallback.next_for(cfg, [])["model"] == "ollama/qwen3.5:9b"
    assert fallback.next_for(cfg, ["ollama/qwen3.5:9b"]) is None


def test_a_turn_whose_brain_is_out_goes_to_the_next(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server
    calls = []

    def chat(cfg, model, messages, tools, options=None):
        calls.append(model)

        async def gen():
            if model == "openai/first":
                raise providers.ProviderError("HTTP 429: You've hit your usage limit")
            yield {"type": "text", "text": "Answered by the second."}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", chat)
    import copy
    with TestClient(server.app) as cl:
        cfg = server.state["cfg"]
        before = copy.deepcopy(dict(cfg))
        cfg["providers"].setdefault("openai", {}).update({"enabled": True, "api_key": "k"})
        cfg["default_model"], cfg["engine"] = "openai/first", "aria"
        cfg.setdefault("usage", {})
        cfg["pricing_skip"] = ["openai/first", "openai/second"]
        cfg["brain_fallbacks"] = [{"executor": "aria", "model": "openai/second"}]
        cid = server.state["store"].create_conversation("t")
        try:
            cl.portal.call(server._run_chat, cid, {"text": "hello", "model": ""})
            msgs = server.state["store"].get_messages(cid)
        finally:
            for k in ("providers", "default_model", "engine", "usage", "pricing_skip", "brain_fallbacks"):
                if k in before:
                    cfg[k] = before[k]
                else:
                    cfg.pop(k, None)
    assert calls[:1] == ["openai/first"] and "openai/second" in calls
    assert [m["role"] for m in msgs] == ["user", "assistant"], "one question, one answer: nothing empty kept"
    assert msgs[1]["content"] == "Answered by the second."


def test_the_settings_row_and_the_terminal():
    js = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "If it isn’t available" in js and "/api/brain/fallbacks" in js
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert "_fallbacks_cli" in cli
    from agentos import users
    assert "brain_fallbacks" in users.USER_KEYS
