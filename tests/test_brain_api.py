"""The HTTP surface of the brain: /api/brains and PUT /api/brain.

One route answers "what can answer here" and one writes the choice, because the
choice is one thing: an executor and one of ITS models. Two routes writing half
of it each is how the machine ended up forwarding to Claude Code with a Gemini
model recorded underneath — which is what the picker then showed.

Also covers POST /api/conversations, which exists so the prompt bar's thread is
real from the moment you press Enter rather than when the server gets round to
the turn.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from fastapi.testclient import TestClient                          # noqa: E402

from agentos import server as servermod                            # noqa: E402


@pytest.fixture()
def client():
    with TestClient(servermod.app) as c:
        cfg = servermod.state["cfg"]
        # Two providers with pinned models: enough to assert the grouping without
        # depending on what this machine can actually reach.
        cfg["providers"]["custom"].update({"enabled": True, "models": ["local-a", "local-b"],
                                           "base_url": "http://127.0.0.1:9/v1"})
        cfg["providers"]["google"].update({"enabled": True, "api_key": "not-a-real-key",
                                           "models": ["gemini-x"]})
        cfg["engine"] = "aria"
        cfg["default_model"] = "custom/local-a"
        yield c


def ex(body, eid):
    return next(e for e in body["executors"] if e["id"] == eid)


def test_brains_lists_every_executor_with_its_own_models(client):
    d = client.get("/api/brains").json()
    assert [m["id"] for m in ex(d, "custom")["models"]] == ["custom/local-a", "custom/local-b"]
    assert [m["id"] for m in ex(d, "google")["models"]] == ["google/gemini-x"]
    assert d["current"] == {"executor": "custom", "model": "custom/local-a"}
    # the agents are in the same list, so one question has one answer
    assert {"claude-code", "hermes", "openclaw"} <= {e["id"] for e in d["executors"]}


def test_choosing_a_model_moves_the_executor_with_it(client):
    r = client.put("/api/brain", json={"executor": "google", "model": "google/gemini-x"})
    assert r.status_code == 200, r.text
    assert r.json()["current"] == {"executor": "google", "model": "google/gemini-x"}
    cfg = client.get("/api/config").json()
    assert cfg["engine"] == "aria" and cfg["default_model"] == "google/gemini-x"


def test_a_model_that_belongs_to_another_executor_is_refused(client):
    r = client.put("/api/brain", json={"executor": "custom", "model": "google/gemini-x"})
    assert r.status_code == 400
    assert "does not offer" in r.json()["error"]
    # and nothing was written
    assert client.get("/api/config").json()["default_model"] == "custom/local-a"


def test_an_executor_that_cannot_answer_here_is_refused_with_its_reason(client):
    r = client.put("/api/brain", json={"executor": "openai", "model": ""})
    assert r.status_code == 400
    assert r.json()["error"]


def test_an_unknown_executor_is_refused(client):
    assert client.put("/api/brain", json={"executor": "banana"}).status_code == 400


def test_choosing_an_agent_writes_the_engine_and_its_model_together(client):
    d = client.get("/api/brains").json()
    if not ex(d, "claude-code")["available"]:
        pytest.skip("Claude Code is not installed on this machine")
    r = client.put("/api/brain", json={"executor": "claude-code", "model": "sonnet"})
    assert r.status_code == 200, r.text
    assert r.json()["current"] == {"executor": "claude-code", "model": "sonnet"}
    cfg = client.get("/api/config").json()
    assert cfg["engine"] == "claude-code"
    assert cfg["executors"]["claude_code"]["model"] == "sonnet"
    # the provider model it would fall back to is untouched
    assert cfg["default_model"] == "custom/local-a"
    client.put("/api/brain", json={"executor": "custom", "model": "custom/local-a"})


def test_the_bar_can_open_its_thread_before_the_turn_exists(client):
    r = client.post("/api/conversations", json={"origin": "omni", "title": "◉ Desktop"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    listed = client.get("/api/conversations").json()["conversations"]
    row = next(c for c in listed if c["id"] == cid)
    assert row["origin"] == "omni"          # Chat groups it under Desktop by this
    assert client.get(f"/api/conversations/{cid}").json()["messages"] == []
