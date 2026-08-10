"""Listing what an OpenAI-compatible provider can actually run.

The reported symptom: a provider that answers turns fine shows no models in the
picker. The cause was that every non-Ollama provider's list came from a static
`models` array in config — nothing ever asked the endpoint — and `custom`
defaults to `[]`. So a working llama.cpp / LM Studio / vLLM box looked empty.

Three things are tested here because each was a separate way to get it wrong:
the URL (llama.cpp serves under /v1 and prints a bare host), the parsing (Gemini
returns `models/x`, some local servers return a bare list), and the filtering
(a catalogue contains embedders and image models that produce "does not support
chat" on the first message).
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import providers as pr           # noqa: E402


# --------------------------------------------------------------- fake endpoint

class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def fake_http(routes: dict, seen: list | None = None):
    """routes: url -> body, anything else 404s."""
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            if seen is not None:
                seen.append(url)
            if url in routes:
                return _Resp(200, routes[url])
            return _Resp(404, {})
    return C


# --------------------------------------------------------------------- the URL

def test_a_bare_host_gets_v1_so_stock_llama_cpp_works():
    """llama-server prints `http://127.0.0.1:8080` and serves the API at /v1. A
    user pasting what the server told them must not land on a 404."""
    assert pr.openai_base("custom", {"base_url": "http://127.0.0.1:8080"}) == \
        "http://127.0.0.1:8080/v1"
    assert pr.openai_base("custom", {"base_url": "http://127.0.0.1:8080/"}) == \
        "http://127.0.0.1:8080/v1"


def test_a_url_that_already_says_v1_is_left_alone():
    for u in ("http://localhost:1234/v1", "https://api.openai.com/v1",
              "https://openrouter.ai/api/v1"):
        assert pr.openai_base("custom", {"base_url": u}) == u


def test_a_real_path_is_never_second_guessed():
    """Somebody behind a reverse proxy on a subpath knows their own URL."""
    assert pr.openai_base("custom", {"base_url": "https://proxy.example/llm"}) == \
        "https://proxy.example/llm"


def test_gemini_keeps_its_own_compatibility_path():
    assert pr.openai_base("google", {"base_url": "https://generativelanguage.googleapis.com"}) \
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    # already-resolved is not doubled
    assert pr.openai_base("google", {"base_url": "https://x/v1beta/openai"}) == \
        "https://x/v1beta/openai"


def test_no_base_url_is_not_a_request_to_nowhere():
    assert pr.openai_base("custom", {"base_url": ""}) == ""
    assert asyncio.run(pr.openai_models("", "")) == []


# ----------------------------------------------------------------- the parsing

def test_the_spec_shape(monkeypatch):
    monkeypatch.setattr(pr.httpx, "AsyncClient",
                        fake_http({"http://h/v1/models": {"data": [{"id": "b"}, {"id": "a"}]}}))
    assert asyncio.run(pr.openai_models("http://h/v1", "k")) == ["a", "b"]


def test_a_bare_list_is_accepted_too(monkeypatch):
    """Some local servers skip the envelope."""
    monkeypatch.setattr(pr.httpx, "AsyncClient",
                        fake_http({"http://h/v1/models": ["x", {"id": "y"}]}))
    assert asyncio.run(pr.openai_models("http://h/v1", "")) == ["x", "y"]


def test_geminis_models_prefix_is_dropped(monkeypatch):
    """Otherwise the same model appears twice, under two spellings, and never
    matches the one a user pinned by hand."""
    monkeypatch.setattr(pr.httpx, "AsyncClient", fake_http(
        {"http://h/models": {"data": [{"id": "models/gemini-3-pro"}]}}))
    assert asyncio.run(pr.openai_models("http://h", "")) == ["gemini-3-pro"]


def test_it_tries_the_other_convention_before_giving_up(monkeypatch):
    """A 404 from /models on a server that serves /v1/models would read to the
    user as "this endpoint has no models" — which is the bug being fixed."""
    seen = []
    monkeypatch.setattr(pr.httpx, "AsyncClient", fake_http(
        {"http://h/v1/models": {"data": [{"id": "m"}]}}, seen))
    assert asyncio.run(pr.openai_models("http://h", "")) == ["m"]
    assert seen == ["http://h/models", "http://h/v1/models"]


def test_an_unreachable_endpoint_is_silent_not_fatal(monkeypatch):
    class Boom:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise OSError("connection refused")
    monkeypatch.setattr(pr.httpx, "AsyncClient", Boom)
    assert asyncio.run(pr.openai_models("http://down", "")) == []


# ---------------------------------------------------------------- the filtering

def test_things_that_cannot_answer_a_turn_are_not_offered():
    for dead in ("text-embedding-3-small", "gemini-embedding-2", "imagen-4.0-generate-001",
                 "veo-3.1-generate-preview", "whisper-1", "dall-e-3",
                 "gemini-2.5-flash-preview-tts", "nomic-embed-text:latest"):
        assert not pr.is_chat_model(dead), dead
    for alive in ("gpt-4o", "gemini-3-pro", "claude-sonnet-5", "qwen3.5:9b",
                  "llama-3.1-8b-instruct", "gpt-4o-audio-preview"):
        assert pr.is_chat_model(alive), alive


def test_a_fetched_catalogue_is_filtered_but_a_pinned_model_is_never(monkeypatch):
    """Picking an embedder produces "does not support chat" on the first message,
    which reads as the OS being broken — but a model somebody pinned by hand is
    their explicit choice and is not ours to hide."""
    async def fetched(base, key):
        return ["gpt-4o", "text-embedding-3-small"]
    monkeypatch.setattr(pr, "openai_models", fetched)

    async def no_ollama(_b):
        return []
    monkeypatch.setattr(pr, "ollama_models", no_ollama)

    cfg = {"providers": {
        "ollama": {"enabled": False},
        "openai": {"enabled": True, "api_key": "k", "base_url": "https://api.openai.com/v1",
                   "models": ["my-private-embedding-deploy"]}}}
    ids = [m["id"] for m in asyncio.run(pr.available_models(cfg))]
    assert "openai/gpt-4o" in ids
    assert "openai/text-embedding-3-small" not in ids
    assert "openai/my-private-embedding-deploy" in ids, "a pinned model must survive"


def test_fetched_and_pinned_are_merged_without_duplicates(monkeypatch):
    async def fetched(base, key):
        return ["gpt-4o", "gpt-5"]
    monkeypatch.setattr(pr, "openai_models", fetched)

    async def no_ollama(_b):
        return []
    monkeypatch.setattr(pr, "ollama_models", no_ollama)
    cfg = {"providers": {"ollama": {"enabled": False},
                         "openai": {"enabled": True, "api_key": "k",
                                    "base_url": "https://api.openai.com/v1",
                                    "models": ["gpt-4o"]}}}
    ids = [m["id"] for m in asyncio.run(pr.available_models(cfg))]
    assert ids.count("openai/gpt-4o") == 1
    assert "openai/gpt-5" in ids


def test_anthropic_is_not_asked_because_it_has_no_such_endpoint(monkeypatch):
    called = []

    async def fetched(base, key):
        called.append(base)
        return []
    monkeypatch.setattr(pr, "openai_models", fetched)

    async def no_ollama(_b):
        return []
    monkeypatch.setattr(pr, "ollama_models", no_ollama)
    cfg = {"providers": {"ollama": {"enabled": False},
                         "anthropic": {"enabled": True, "api_key": "k",
                                       "base_url": "https://api.anthropic.com",
                                       "models": ["claude-sonnet-5"]}}}
    ids = [m["id"] for m in asyncio.run(pr.available_models(cfg))]
    assert ids == ["anthropic/claude-sonnet-5"]
    assert not called
