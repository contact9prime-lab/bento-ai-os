"""The OpenAI-compatible wire format — provider baggage must survive a round-trip.

Gemini 2.5 signs every function call ("thought_signature") and rejects the NEXT
request with HTTP 400 if that signature is not replayed alongside the call:

    Function call is missing a thought_signature in functionCall parts …
    position 4 — INVALID_ARGUMENT

So whatever a provider attaches to a tool call has to come back verbatim.
"""

import json
import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos.providers import _openai_messages      # noqa: E402


SIG = {"google": {"thought_signature": "CiwBVKhc7v0…"}}


def test_tool_call_extra_is_replayed():
    msgs = _openai_messages([
        {"role": "user", "content": "what is in the news"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "name": "fetch_url", "args": {"url": "https://x"},
             "extra": {"extra_content": SIG}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "…"},
    ])
    tc = msgs[1]["tool_calls"][0]
    assert tc["extra_content"] == SIG, "the thought signature must ride along"
    assert tc["function"]["name"] == "fetch_url"
    assert json.loads(tc["function"]["arguments"]) == {"url": "https://x"}


def test_tool_call_without_extra_is_unchanged():
    msgs = _openai_messages([
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c", "name": "read_file", "args": {}}]},
    ])
    tc = msgs[0]["tool_calls"][0]
    assert set(tc) == {"id", "type", "function"}      # nothing invented for other providers


def test_images_and_plain_messages_still_shaped_right():
    msgs = _openai_messages([
        {"role": "user", "content": "look", "images": ["data:image/png;base64,AAA"]},
        {"role": "assistant", "content": "ok"},
    ])
    assert msgs[0]["content"][0]["type"] == "image_url"
    assert msgs[1] == {"role": "assistant", "content": "ok"}


def test_agent_threads_extra_from_the_tool_call_event():
    import inspect
    from agentos.agent import Agent
    src = inspect.getsource(Agent.run)
    assert '"extra": t["extra"]' in src, "the agent must carry the signature into history"
