"""App Studio: whose choice the build model is, and never losing the model's work.

Two real failures this pins down:
  * a hardcoded ranking of model names picked a LOCAL 9B on a machine with a
    Gemini key (the ladder had no "gemini" in it) — so the ladder is gone, and
    the user's own preference decides;
  * a build died showing the app's own source because the model wrote a ```html
    block instead of calling create_app, and nothing salvaged it.
"""

import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos.server import _resolve_build_model, _other_models, _salvage_app_html   # noqa: E402


def _models(*ids):
    return [{"id": i} for i in ids]


AVAIL = _models("ollama/qwen3.5:9b", "ollama/gemma4:12b", "google/gemini-3.5-flash-lite")


def test_this_builds_pick_wins():
    cfg = {"default_model": "ollama/qwen3.5:9b", "build": {"model": "ollama/gemma4:12b"}}
    assert _resolve_build_model(cfg, AVAIL, "google/gemini-3.5-flash-lite") \
        == "google/gemini-3.5-flash-lite"


def test_saved_build_preference_beats_the_chat_default():
    cfg = {"default_model": "ollama/qwen3.5:9b", "build": {"model": "google/gemini-3.5-flash-lite"}}
    assert _resolve_build_model(cfg, AVAIL) == "google/gemini-3.5-flash-lite"


def test_falls_back_to_the_users_default_not_a_ranking():
    cfg = {"default_model": "google/gemini-3.5-flash-lite", "build": {"model": ""}}
    assert _resolve_build_model(cfg, AVAIL) == "google/gemini-3.5-flash-lite"
    # a local default is honoured too — the OS does not "know better"
    assert _resolve_build_model({"default_model": "ollama/qwen3.5:9b"}, AVAIL) == "ollama/qwen3.5:9b"


def test_auto_is_not_a_model_name():
    assert _resolve_build_model({"default_model": "ollama/qwen3.5:9b"}, AVAIL, "auto") \
        == "ollama/qwen3.5:9b"


def test_unavailable_choice_is_skipped_never_substituted_silently():
    cfg = {"default_model": "anthropic/claude-sonnet-5", "build": {"model": "openai/gpt-4o"}}
    # neither is installed right now → falls through to what exists, in order
    assert _resolve_build_model(cfg, AVAIL) == AVAIL[0]["id"]


def test_retry_options_exclude_the_failed_model_and_embeddings():
    opts = _other_models(_models("ollama/qwen3.5:9b", "ollama/nomic-embed-text:latest",
                                 "google/gemini-3.5-flash-lite"), "ollama/qwen3.5:9b")
    assert opts == ["google/gemini-3.5-flash-lite"]


def test_salvage_builds_an_app_written_as_text():
    body = ("<!doctype html><html><body><div id='app'></div><script>"
            + "/* ticker */ " * 30 + "setInterval(()=>fetch('/x'),300000)</script></body></html>")
    name, desc, html = _salvage_app_html(
        f"Here it is.\nname: Stock Ticker\ndescription: NSE, every 5 minutes\n```html\n{body}\n```")
    assert name == "Stock Ticker" and desc.startswith("NSE")
    assert "setInterval" in html


def test_salvage_ignores_prose_and_non_app_code():
    assert _salvage_app_html("I will build that for you shortly:") == ("", "", "")
    assert _salvage_app_html("```python\nprint('hi')\n```") == ("", "", "")
    assert _salvage_app_html("") == ("", "", "")


def test_builds_do_not_run_the_generic_unfinished_nudge():
    import inspect
    from agentos import server
    src = inspect.getsource(server._run_build)
    assert "nudge_unfinished = False" in src
