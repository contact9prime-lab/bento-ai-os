"""The Arena (agentos/arena.py, the /api/arena routes, 00h-arena.js, `bento arena`).

Asked for as "split the desktop into 2 or 4 sandboxes, give the exact same task to two
different models, and show a live HUD with tokens a second, cost, refusals and time".
What these defend:

- a contender is a brain from `brains()` (an available executor and one of its models),
  never free text; two to four of them;
- each contender works in its own folder and its own conversation, and every tool call
  goes through the same gate (refusals are counted from what the gate said);
- the HUD measures (tokens a second from the first token, cost, refusals, steps, time)
  and the summary never names a winner on quality;
- one arena per person at a time, stoppable, and kept bounded in their own home.
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

import pytest                                                       # noqa: E402

from agentos import arena                                           # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"

BRAINS = {"executors": [
    {"id": "ollama", "name": "Ollama", "kind": "provider", "engine": "aria", "available": True,
     "models": [{"id": "ollama/llama3", "name": "llama3"}, {"id": "ollama/qwen2.5-coder", "name": "qwen2.5-coder"}]},
    {"id": "openai", "name": "OpenAI", "kind": "provider", "engine": "aria", "available": True,
     "models": [{"id": "openai/gpt-4o", "name": "gpt-4o"}]},
    {"id": "claude-code", "name": "Claude Code", "kind": "agent", "engine": "claude-code", "available": False,
     "models": [{"id": "", "name": "whatever it is set to"}, {"id": "sonnet", "name": "sonnet"}]},
]}


def test_a_contender_is_a_brain_this_machine_can_run():
    ch = arena.choices(BRAINS)
    assert {(c["executor"], c["model"]) for c in ch} == {
        ("ollama", "ollama/llama3"), ("ollama", "ollama/qwen2.5-coder"), ("openai", "openai/gpt-4o")}, \
        "an unavailable executor is never offered"
    seats = arena.contenders(BRAINS, [{"executor": "ollama", "model": "ollama/llama3"},
                                      {"executor": "openai", "model": "openai/gpt-4o"}])
    assert [s["label"] for s in seats] == ["Ollama · llama3", "OpenAI · gpt-4o"] and [s["slot"] for s in seats] == [0, 1]
    twice = arena.contenders(BRAINS, [{"executor": "openai", "model": "openai/gpt-4o"}] * 2)
    assert twice[1]["label"].endswith("#2")
    for bad in ([{"executor": "openai", "model": "openai/gpt-4o"}],
                [{"executor": "openai", "model": "openai/gpt-4o"}] * 5):
        with pytest.raises(arena.ArenaError, match="2 to 4"):
            arena.contenders(BRAINS, bad)
    with pytest.raises(arena.ArenaError, match="not one this machine can run"):
        arena.contenders(BRAINS, [{"executor": "openai", "model": "openai/gpt-4o"},
                                  {"executor": "claude-code", "model": "sonnet"}])
    with pytest.raises(arena.ArenaError, match="not one this machine"):
        arena.contenders(BRAINS, [{"executor": "openai", "model": "gpt-9-made-up"},
                                  {"executor": "openai", "model": "openai/gpt-4o"}])


def test_every_contender_has_its_own_folder(tmp_path):
    seats = arena.contenders(BRAINS, [{"executor": "openai", "model": "openai/gpt-4o"}] * 2)
    a = arena.new("Build a retro synth app", seats, str(tmp_path))
    folders = [c["folder"] for c in a["contenders"]]
    assert len(set(folders)) == 2 and all(f.startswith(str(tmp_path / "arena" / a["id"])) for f in folders)
    with pytest.raises(arena.ArenaError):
        arena.new("   ", seats, str(tmp_path))


def test_the_hud_measures_and_the_summary_never_crowns():
    now = time.time()
    c = {"started": now - 10, "first_token": now - 8, "finished": now, "tokens_out": 400, "tokens_in": 900,
         "cost": 0.0123, "refused": 2, "steps": 5, "files": ["a.py"], "priced": True}
    h = arena.hud(c, now)
    assert h["seconds"] == 10.0 and h["first_token_s"] == 2.0 and h["tok_s"] == 50.0, "speed counts from the first token"
    assert h["refused"] == 2 and h["files"] == 1
    a = {"contenders": [
        {**c, "label": "A", "status": "done"},
        {**c, "label": "B", "status": "done", "finished": now - 4, "cost": 0.001, "refused": 0, "tokens_out": 100}]}
    s = arena.summary(a)
    assert any("First to finish: B" in ln for ln in s["lines"]) and any("Spent least: B" in ln for ln in s["lines"])
    assert not any(w in " ".join(s["lines"]).lower() for w in ("won", "winner", "best"))


def test_arenas_are_per_person_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(arena, "_home", lambda uid: tmp_path / (uid or "m"))
    seats = arena.contenders(BRAINS, [{"executor": "openai", "model": "openai/gpt-4o"}] * 2)
    for i in range(arena.KEEP + 3):
        a = arena.new(f"task {i}", seats, str(tmp_path))
        a["id"] = f"20261013-0000{i:02d}-abcd"
        arena.save("ada", a)
    assert len(list((tmp_path / "ada" / "arena").glob("*.json"))) == arena.KEEP
    assert arena.load("ada", "20261013-000022-abcd")["task"] == "task 22"
    assert arena.load("ada", "../../etc/passwd") is None and arena.load("bob", "20261013-000022-abcd") is None


def test_a_whole_arena_runs_every_seat_through_the_gate(monkeypatch):
    """Two provider contenders, run by the server with a stubbed Agent loop that streams,
    counts a usage event, is refused once by the gate, and answers."""
    from fastapi.testclient import TestClient
    from agentos import agent as agentmod
    from agentos import executors as execmod
    from agentos import providers
    from agentos import server as servermod

    async def models(cfg):
        return []
    monkeypatch.setattr(providers, "available_models", models)
    monkeypatch.setattr(execmod, "brains", lambda cfg, m: BRAINS)
    seen = {}

    async def fake_run(self, history):
        seen.setdefault("folders", []).append(self.toolbox.cfg["workspace"])
        seen.setdefault("convs", []).append(self.conversation_id)
        assert history[-1]["content"] == "Fix this broken script"
        await self.emit({"type": "text_delta", "text": f"I am {self.model_id}. "})
        await self.emit({"type": "usage", "input": 300, "output": 120})
        await self.emit({"type": "tool_start", "call_id": "1", "name": "run_command", "args": {}, "pending_approval": False})
        await self.emit({"type": "tool_end", "call_id": "1", "name": "run_command", "ok": False,
                         "output": "[denied] This command is blocked (destructive to the system)."})
        await self.emit({"type": "text_delta", "text": "Done."})
        return {"content": f"I am {self.model_id}. Done.", "steps": [], "tokens": {"input": 300, "output": 120}}
    monkeypatch.setattr(agentmod.Agent, "run", fake_run)
    with TestClient(servermod.app) as cl:
        got = cl.get("/api/arena").json()
        assert len(got["choices"]) == 3 and got["max"] == 4
        r = cl.post("/api/arena", json={"task": "Fix this broken script", "contenders": [
            {"executor": "ollama", "model": "ollama/llama3"}, {"executor": "openai", "model": "openai/gpt-4o"}]})
        assert r.status_code == 200, r.text
        aid = r.json()["id"]
        for _ in range(100):
            cur = cl.get(f"/api/arena/{aid}").json()
            if not cur["live"]:
                break
            time.sleep(0.05)
        assert cur["status"] == "done"
        a, b = cur["contenders"]
        assert a["status"] == b["status"] == "done"
        assert a["answer"].startswith("I am ollama/llama3") and b["answer"].startswith("I am openai/gpt-4o")
        assert a["hud"]["refused"] == 1 and a["hud"]["steps"] == 1 and a["hud"]["tokens_out"] == 120
        assert a["hud"]["first_token_s"] is not None
        assert b["hud"]["cost"] > 0 and a["hud"]["cost"] == 0 and a["hud"]["priced"], "a local model is free, and priced"
        assert seen["folders"][0] != seen["folders"][1] and all("/arena/" in f for f in seen["folders"])
        assert len(set(seen["convs"])) == 2
        # a bad pick is a sentence, and the arena is kept for later
        assert "not one this machine" in cl.post("/api/arena", json={"task": "x", "contenders": [
            {"executor": "nope", "model": "x"}, {"executor": "openai", "model": "openai/gpt-4o"}]}).json()["error"]
        assert any(x["id"] == aid for x in cl.get("/api/arena").json()["recent"])


def test_every_face_reaches_it():
    src = (ROOT / "agentos/server.py").read_text()
    for route in ('@app.get("/api/arena")', '@app.post("/api/arena")', '@app.get("/api/arena/{aid}")',
                  '@app.post("/api/arena/{aid}/stop")'):
        assert route in src, route
    assert "def _arena_cli(" in (ROOT / "agentos/__main__.py").read_text()
    js = (JS / "00h-arena.js").read_text()
    for fn in ("function renderArena(", "function arenaEvent(", "function arenaHud(", "function arenaStart("):
        assert fn in js, fn
    # the HUD asks the server for money; it never prices anything itself
    assert "1e6" not in js and "pricing" not in js and "cost_usd" not in js
    assert "case 'arena'" in (JS / "09-websocket.js").read_text()
