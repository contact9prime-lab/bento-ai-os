"""The team: agents on their own AI providers, and agents talking to each other.

What these defend: one answer to "which brain does this agent use" (agent_brain),
honest about a switched-off provider, a missing key and the team switch; a pinned
specialist answering on its OWN provider even when the machine's brain is an
executor; one door for pinning a model; a huddle that is ordinary runs on each
agent's own model, ends when nobody has anything to add and is bounded; a gate that
asks before a huddle and refuses one to every principal that is not your agent;
the chat syntax; and every face of it — the page, the stage, the TUI and the CLI.
"""

import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors, fabric, policy, providers             # noqa: E402
from agentos.memory import Store                                    # noqa: E402
from agentos.policy import PDP, Principal, MAIN                     # noqa: E402
from agentos.tools import TOOL_SCHEMAS, Toolbox                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos" / "ui" / "src" / "js"


def _cfg(tmp_path, **over):
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 6, "default_model": "openai/gpt-4o",
         "workspace": str(tmp_path), "memory": {"inject_facts": 0, "inject_user": 0},
         "providers": {"openai": {"enabled": True, "api_key": "sk-x"},
                       "anthropic": {"enabled": True, "api_key": "sk-ant-x"},
                       "google": {"enabled": False, "api_key": "g"},
                       "openrouter": {"enabled": True, "api_key": ""},
                       "ollama": {"enabled": True}},
         "team": {"own_brains": True}}
    c.update(over)
    return c


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    c = _cfg(tmp_path)
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher", "soul": "research", "model": "anthropic/claude-sonnet-5"})
    store.save_subagent({"name": "validator", "soul": "check", "model": "ollama/qwen3"})
    store.save_subagent({"name": "writer", "soul": "write", "model": ""})
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    events = []

    async def broadcast(ev):
        events.append(ev)
    tb.broadcast = broadcast
    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    return c, store, tb, cp, events


def _talking_provider(lines):
    """A provider that answers as whoever the huddle turn names, and records which
    MODEL each answer came from — the proof that each agent spoke on its own brain."""
    seen = []

    def chat(cfg, model, messages, tools, options=None):
        async def gen():
            user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
            who = re.search(r"You are ([\w-]+), in a conversation", user)
            name = who.group(1) if who else "?"
            seen.append((name, model))
            said = user.count(f"\n{name}:")
            script = lines.get(name, ["pass"])
            yield {"type": "text", "text": script[min(said, len(script) - 1)]}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat, seen


# ---- which brain -----------------------------------------------------------------

def test_a_pinned_agent_answers_on_its_own_provider_when_it_can(world):
    c, store, *_ = world
    b = fabric.agent_brain(c, store.get_subagent("researcher"))
    assert b["own"] and b["model"] == "anthropic/claude-sonnet-5"
    assert b["provider_name"] == "Anthropic" and b["short"] == "claude-sonnet-5" and not b["note"]
    # unpinned: the machine's brain, named
    w = fabric.agent_brain(c, store.get_subagent("writer"))
    assert not w["own"] and w["model"] == "openai/gpt-4o" and w["provider_name"] == "OpenAI"


@pytest.mark.parametrize("pin,change,note", [
    ("google/gemini-3", {}, "switched off"),                            # provider off
    ("openrouter/x/y", {}, "no key"),                                   # keyed, no key
    ("nowhere/x", {}, "not a provider"),
    ("anthropic/claude-sonnet-5", {"team": {"own_brains": False}}, "machine's brain"),
])
def test_a_pin_that_cannot_be_used_says_why_and_the_badge_does_not_lie(tmp_path, monkeypatch,
                                                                        pin, change, note):
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    c = _cfg(tmp_path, **change)
    b = fabric.agent_brain(c, {"name": "x", "model": pin})
    assert not b["own"] and note in b["note"]
    assert b["model"] == "openai/gpt-4o" and b["provider_name"] == "OpenAI", \
        "the badge must name what actually answers, not the pin"


def test_no_brain_at_all_is_said_rather_than_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    b = fabric.agent_brain(_cfg(tmp_path, default_model=""), {"name": "x"})
    assert b["provider_name"] == "No brain yet" and b["short"] == "not set"


def test_under_an_executor_a_pinned_specialist_still_answers_on_its_provider(world, monkeypatch):
    """With Claude Code as the machine's brain, a specialist pinned to another
    provider answers THERE, through this OS's own loop — that is agents on
    different providers working together. The unpinned one rides the executor."""
    c, store, tb, cp, _ = world
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "claude-code")
    b = fabric.agent_brain(c, store.get_subagent("writer"))
    assert b["engine"] == "claude-code" and b["provider_name"] == "Claude Code"
    assert fabric.agent_brain(c, store.get_subagent("researcher"))["own"]

    chat, seen = _talking_provider({"researcher": ["found it"]})
    monkeypatch.setattr(providers, "chat", chat)

    async def no_bridge(*a, **k):
        raise AssertionError("a pinned specialist was sent to the executor")
    monkeypatch.setattr(cp, "_executor", lambda: "claude-code")
    monkeypatch.setattr(cp, "_run_on_executor", no_bridge)
    res = asyncio.run(cp.run_subagent(store.get_subagent("researcher"),
                                      "You are researcher, in a conversation with x"))
    assert res["status"] == "ok" and res["model"] == "anthropic/claude-sonnet-5"
    assert seen == [("researcher", "anthropic/claude-sonnet-5")]


def test_one_door_pins_a_model_and_refuses_a_provider_that_is_not_here(world):
    c, store, *_ = world
    b = fabric.set_agent_model(store, c, "writer", "anthropic/claude-sonnet-5")
    assert b["own"] and store.get_subagent("writer")["model"] == "anthropic/claude-sonnet-5"
    assert store.get_subagent("writer")["soul"] == "write", "pinning must not rewrite the agent"
    assert not fabric.set_agent_model(store, c, "writer", "")["own"]      # back to the machine's
    with pytest.raises(ValueError, match="provider/model"):
        fabric.set_agent_model(store, c, "writer", "martian/gpt")
    with pytest.raises(KeyError):
        fabric.set_agent_model(store, c, "nobody", "openai/gpt-4o")
    # a pin on a provider that is off is KEPT, and the brain says what answers meanwhile
    b = fabric.set_agent_model(store, c, "writer", "google/gemini-3")
    assert store.get_subagent("writer")["model"] == "google/gemini-3" and "switched off" in b["note"]


# ---- huddles ---------------------------------------------------------------------

def test_a_huddle_is_each_agent_on_its_own_brain_until_nobody_has_more(world, monkeypatch):
    c, store, tb, cp, _ = world
    chat, seen = _talking_provider({
        "researcher": ["Per-seat is the norm.", "Fair — the enterprise tiers are quote-only.", "pass"],
        "validator": ["Two of those pages are a year old.", "pass"],
    })
    monkeypatch.setattr(providers, "chat", chat)
    said = []

    async def say(e):
        said.append(e)
    res = asyncio.run(cp.huddle(["researcher", "@validator"], "per seat?", rounds=3, say=say))
    # round 1 both spoke, round 2 only the researcher, round 3 nobody -> ends
    assert [e["speaker"] for e in res["transcript"]] == ["researcher", "validator", "researcher"]
    assert res["rounds"] == 3 and said == res["transcript"]
    assert dict(seen)["researcher"] == "anthropic/claude-sonnet-5"
    assert dict(seen)["validator"] == "ollama/qwen3", "each turn is on the agent's OWN model"
    assert res["transcript"][1]["provider"] == "Ollama"
    # each turn is an ordinary run — in Observability, with its own ledger
    runs = [r for r in store.fabric_runs(limit=50) if r["kind"] == "huddle"]
    assert len(runs) >= 5 and {r["ref"] for r in runs} == {"researcher", "validator"}
    # the second speaker saw the first: agents answer each other, not the void
    assert "researcher: Per-seat is the norm." in "\n".join(
        m for m in [r["input"] for r in runs if r["ref"] == "validator"])


def test_the_transcript_is_one_line_per_turn_the_page_can_read_back(world):
    text = fabric.huddle_text(["a", "b"], 2, [
        {"speaker": "a", "model": "openai/gpt-4o", "text": "yes"},
        {"speaker": "b", "model": "ollama/qwen3", "text": "no, because (x)"}])
    lines = text.split("\n")
    assert lines[0] == "[huddle · a, b · 2 rounds]"
    # the SAME pattern 10b-huddle.js parses on reload
    js = (JS / "10b-huddle.js").read_text()
    assert r"/^@([\w-]+) \(([^)]*)\): (.*)$/" in js
    pat = re.compile(r"^@([\w-]+) \(([^)]*)\): (.*)$")
    assert [pat.match(x).groups() for x in lines[1:]] == [
        ("a", "openai/gpt-4o", "yes"), ("b", "ollama/qwen3", "no, because (x)")]


def test_a_huddle_needs_two_agents_that_exist_and_is_bounded(world, monkeypatch):
    c, store, tb, cp, _ = world
    with pytest.raises(ValueError, match="at least two"):
        asyncio.run(cp.huddle(["researcher", "ghost"], "q"))
    for n in ("a1", "a2", "a3"):
        store.save_subagent({"name": n, "soul": n})
    chat2, _ = _talking_provider({n: ["something"] for n in
                                  ("researcher", "validator", "writer", "a1", "a2", "a3")})
    monkeypatch.setattr(providers, "chat", chat2)
    res = asyncio.run(cp.huddle(["researcher", "validator", "writer", "a1", "a2", "a3"], "q",
                                rounds=99))
    assert len(res["agents"]) == fabric.HUDDLE_MAX_AGENTS
    assert res["rounds"] == fabric.HUDDLE_MAX_ROUNDS
    assert len(res["transcript"]) <= fabric.HUDDLE_MAX_AGENTS * fabric.HUDDLE_MAX_ROUNDS


def test_the_chat_convenes_a_huddle_with_two_names_and_one_name_is_still_one_agent(world):
    _, store, *_ = world
    assert fabric.parse_huddle(store, "@researcher @validator should we?") == \
        (["researcher", "validator"], "should we?")
    assert fabric.parse_huddle(store, "@researcher, @validator and @writer: go")[0] == \
        ["researcher", "validator", "writer"]
    assert fabric.parse_huddle(store, "@researcher find X") is None
    assert fabric.parse_huddle(store, "@researcher @nobody hi") is None, \
        "an unknown name is a typo to show, not a smaller huddle"


def test_the_agent_can_convene_one_and_every_turn_is_broadcast(world, monkeypatch):
    c, store, tb, cp, events = world
    chat, _ = _talking_provider({"researcher": ["one", "pass"], "writer": ["two", "pass"]})
    monkeypatch.setattr(providers, "chat", chat)
    out = asyncio.run(tb.huddle(["researcher", "writer"], "q", rounds=2, conversation_id="c9"))
    assert out.startswith("[huddle · researcher, writer")
    says = [e for e in events if e.get("type") == "agent_say"]
    assert [e["speaker"] for e in says] == ["researcher", "writer"]
    assert all(e["conversation_id"] == "c9" for e in says)
    assert asyncio.run(tb.huddle(["researcher"], "q")).startswith("[error]")
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert {"huddle", "set_agent_brain"} <= names


# ---- the gate ------------------------------------------------------------------------

def test_a_huddle_is_its_own_action_and_only_your_agent_may_convene_one(world):
    c, store, *_ = world
    assert policy.action_of("huddle", {"agents": ["Writer", "@researcher"]}) == \
        ("agent.huddle", "agent:huddle/researcher,writer")
    assert policy.action_of("set_agent_brain", {"agent": "writer", "model": "x/y"}) == \
        ("agent.write", "agent:subagent/writer")
    pdp = PDP({**c, "autonomy": "balanced"}, store)
    res = "agent:huddle/researcher,validator"
    for who in (Principal("subagent", "writer"), Principal("flow", "digest"),
                Principal("app", "notes"), Principal("peer", "bob")):
        assert pdp.decide(who, "agent.huddle", res).effect == "deny", who.label
    d = pdp.decide(MAIN, "agent.huddle", res, {"autonomy": "balanced"})
    assert d.effect == "ask"
    assert "researcher (on Anthropic)" in d.reason and "validator (on Ollama)" in d.reason, \
        "the card must say who is in the room and what each one runs on"
    assert PDP({**c, "autonomy": "full"}, store).decide(MAIN, "agent.huddle", res,
                                                        {"autonomy": "full"}).effect == "allow"


def test_moving_an_agent_to_another_provider_asks(world):
    _, _, tb, *_ = world
    level, why = tb.risk_of("set_agent_brain", {"agent": "writer", "model": "anthropic/x"})
    assert level == "risky" and "billed" in why


# ---- the routes and the faces -----------------------------------------------------------

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        s = servermod.state["store"]
        if not s.get_subagent("researcher"):
            s.save_subagent({"name": "researcher", "soul": "r"})
        yield cl, servermod


def test_the_roster_carries_each_brain_and_the_switch_applies(client):
    cl, servermod = client
    d = cl.get("/api/subagents").json()
    assert "agent_brain" in d and "own_brains" in d
    assert all("brain" in s and "provider_name" in s["brain"] for s in d["subagents"])
    r = cl.put("/api/subagents/researcher/brain", json={"model": "martian/x"})
    assert r.status_code == 400 and "provider/model" in r.json()["error"]
    assert cl.put("/api/subagents/nobody/brain", json={"model": ""}).status_code == 404
    assert cl.put("/api/subagents/researcher/brain", json={"model": ""}).json()["ok"]
    before = servermod.state["cfg"].get("team", {}).get("own_brains", True)
    try:
        cl.put("/api/config", json={"team": {"own_brains": False}})
        assert cl.get("/api/subagents").json()["own_brains"] is False
    finally:
        servermod.state["cfg"].setdefault("team", {})["own_brains"] = before


def test_every_face_shows_the_huddle_and_the_brain():
    ws, chat = (JS / "09-websocket.js").read_text(), (JS / "10-chat.js").read_text()
    hud, crew = (JS / "10b-huddle.js").read_text(), (JS / "01d-crew.js").read_text()
    assert "case 'agent_say':" in ws and "huddleLive(ev,_cur)" in ws
    assert "huddleCard(huddleParse(body),hud,true)" in chat, "a reloaded huddle reads as it did live"
    assert "s.name==='huddle'" in chat, "the agent's huddle tool call shows the conversation"
    assert "avatarImg(e.speaker,'av-who')" in hud and "brainChip(e.model,e.provider)" in hud
    # the stage: the speaker lights up and says it; every figure names its provider
    assert "kind==='say'" in crew and "crewSay(w," in crew
    assert "function crewTag(" in crew and "s.c.brain" in crew and "d.agent_brain" in crew
    # one bubble at a time in a conversation
    say = crew.split("function crewSay(")[1].split("\nfunction ")[0]
    assert "if(turn)for(const k in CREW.said)if(CREW.said[k].turn)delete" in say
    # the roster, Settings and the terminal
    assert "brainChip(s.brain.model,s.brain.provider_name)" in (JS / "13-fabric.js").read_text()
    st = (JS / "11-settings.js").read_text()
    assert "function paintTeamBrains(" in st and "/brain'" in st and "s-team-own" in st
    assert 't == "agent_say"' in (ROOT / "agentos" / "tui_app.py").read_text()


def test_bento_team_lists_and_pins_with_the_server_down(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "team", *a],  # noqa: E731
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    Store(tmp_path / "agentos.db").save_subagent({"name": "writer", "soul": "w"})
    r = run()
    assert r.returncode == 0 and "writer" in r.stdout and "your agent" in r.stdout, r.stderr
    r = run("set", "writer", "martian/x")
    assert r.returncode == 2 and "provider/model" in r.stdout
    r = run("set", "writer", "anthropic/claude-sonnet-5")
    assert r.returncode == 0 and "writer now answers on" in r.stdout
    assert "@researcher @validator" in run().stdout, "the list says how to start a huddle"
