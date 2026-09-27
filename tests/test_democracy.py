"""Democracy mode: where swarm would open, the team votes, and 2 of 3 decide.

Asked for as "the swarm mode can also be democracy mode, where 2 out of 3 (a quorum)
agrees". The steps swarm opens without asking (a specialist asking a colleague, your
agent handing work over or starting a huddle, on a surface somebody is at) go to a
council of three of your agents instead, on different brains where they can be, and
a majority decides. What these defend:

- the council never answers what must be a PERSON's (after untrusted content, the
  confirm-every-time actions) and never reaches where swarm does not (a linked team,
  a mission, an unattended run);
- a vote is read strictly: an answer that is neither yes nor no is not consent;
- with fewer than two agents to vote there is no council, and you are asked;
- a ballot is an opinion, not work: a vote run has no tools;
- a huddle ends with a vote on the last word said, stored as one line the page draws.
"""

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric                                         # noqa: E402
from agentos.agent import Agent                                    # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP, Principal, team_talk               # noqa: E402
from agentos.tools import Toolbox                                  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _world(tmp_path, talk="democracy", **cfg):
    c = {"agent_name": "Aria", "autonomy": "balanced", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321,
         "team": {"talk": talk}, "memory": {"inject_facts": 0, "inject_user": 0}}
    c.update(cfg)
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)

    async def broadcast(ev):
        pass
    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    for n in ("researcher", "validator", "writer", "analyst"):
        store.save_subagent({"name": n, "soul": n, "tools": ["recall"]})
    return c, store, tb, cp


def _voters(cp, votes: dict, calls: list):
    """run_subagent stand-in: a ballot answers from `votes`, anything else answers."""
    async def fake(defn, task, kind="delegate", **k):
        calls.append((defn["name"], kind))
        if kind == "vote":
            return {"content": votes.get(defn["name"], "maybe\nnot sure"), "model": "m",
                    "status": "ok", "fault": "", "run_id": "r", "usage": {}, "steps": []}
        return {"content": f"{defn['name']} answers", "model": "m", "status": "ok",
                "fault": "", "run_id": "r", "usage": {}, "steps": [], "tainted": False}
    cp.run_subagent = fake


# ------------------------------------------------------------------ the gate

def test_democracy_is_a_talk_mode():
    assert team_talk({"team": {"talk": "democracy"}}) == "democracy"
    assert team_talk({"team": {"talk": "anarchy"}}) == "matrix"


def test_an_empty_cell_goes_to_the_council_and_a_block_still_wins(tmp_path):
    c, store, tb, cp = _world(tmp_path)
    d = tb.pdp.decide(Principal("subagent", "researcher"), "agent.message",
                      "agent:subagent/validator", {"surface": "gui"})
    assert d.effect == "ask" and d.rule == "democracy"
    fabric.set_cell(store, "researcher", "validator", "deny")
    d = tb.pdp.decide(Principal("subagent", "researcher"), "agent.message",
                      "agent:subagent/validator", {"surface": "gui"})
    assert d.effect == "deny", "a person's block beats any vote"
    # another team is never put to this team's vote
    d = tb.pdp.decide(Principal("subagent", "researcher"), "agent.message",
                      "agent:subagent/analyst@office", {"surface": "gui"})
    assert d.rule != "democracy"


def test_the_leads_hand_over_goes_to_a_vote_only_where_somebody_is(tmp_path):
    c, store, tb, cp = _world(tmp_path)
    lead = Principal("user", "")
    d = tb.pdp.decide(lead, "agent.invoke", "agent:subagent/writer", {"surface": "gui"})
    assert d.effect == "ask" and d.rule == "democracy"
    d = tb.pdp.decide(lead, "agent.invoke", "agent:subagent/writer", {"surface": "task"})
    assert d.rule != "democracy", "an unattended run is asked as before, never voted through"


# ------------------------------------------------------------------ the council

def test_two_of_three_carries_it_and_one_of_three_does_not(tmp_path):
    c, store, tb, cp = _world(tmp_path)
    calls = []
    _voters(cp, {"validator": "YES\nfine", "writer": "yes, good idea", "analyst": "NO\nwasteful"}, calls)
    v = asyncio.run(cp.council("researcher", "ask x", targets=["validator"]))
    assert v["decided"] and v["approved"] and (v["yes"], v["of"], v["need"]) == (2, 3, 2)
    assert "researcher" not in [b["agent"] for b in v["ballots"]], "the one asking does not vote"
    _voters(cp, {"validator": "YES", "writer": "no", "analyst": "I think so"}, calls)
    v = asyncio.run(cp.council("researcher", "ask x"))
    assert v["decided"] and not v["approved"] and v["yes"] == 1, \
        "an answer that is not yes or no is not consent"
    rows = [r for r in store.audit_list(limit=50) if r["action"] == "team.vote"]
    assert rows and rows[0]["rule"] == "democracy" and "1 of 3" in rows[0]["detail"]


def test_fewer_than_two_voters_is_no_council(tmp_path):
    c, store, tb, cp = _world(tmp_path)
    for n in ("validator", "writer"):
        store.delete_subagent(store.get_subagent(n)["id"])
    v = asyncio.run(cp.council("researcher", "hand work", targets=["analyst"]))
    assert not v["decided"] and "you are asked" in v["line"]


def test_the_lead_takes_a_seat_so_three_specialists_still_make_a_council(tmp_path, monkeypatch):
    """With the usual researcher, validator and writer, a specialist's question left one
    voter. The lead sits on the council (when the machine has a brain), and the one
    asked votes too; only the proposer never does."""
    from agentos import executors
    c, store, tb, cp = _world(tmp_path, default_model="ollama/x")
    store.delete_subagent(store.get_subagent("analyst")["id"])
    seats = cp.council_of(exclude=["researcher"])
    assert [d["name"] for d in seats][0] == "Aria" and seats[0]["lead"]
    assert {d["name"] for d in seats} == {"Aria", "validator", "writer"}
    assert "Aria" not in [d["name"] for d in cp.council_of(exclude=["@agent"])], \
        "the lead does not vote on its own hand-over"

    async def brain(cfg, system, prompt, timeout=180, model=""):
        return ("YES\nsensible", "ollama/x", "")
    monkeypatch.setattr(executors, "ask_brain", brain)
    calls = []
    _voters(cp, {"validator": "NO\nbusy", "writer": "YES"}, calls)
    v = asyncio.run(cp.council("researcher", "ask validator a question", targets=["validator"]))
    assert v["decided"] and v["approved"] and (v["yes"], v["of"]) == (2, 3)
    assert next(b for b in v["ballots"] if b["agent"] == "Aria")["key"] == "@agent"


def test_the_council_seats_different_brains_first(tmp_path, monkeypatch):
    c, store, tb, cp = _world(tmp_path)
    store.save_subagent({"name": "coder", "soul": "c", "model": "codex/gpt-5"})
    brains = {"validator": ("aria", "a"), "writer": ("aria", "a"), "analyst": ("aria", "a"),
              "coder": ("codex", "codex")}
    monkeypatch.setattr(fabric, "agent_brain", lambda cfg, d, o="": {
        "engine": brains.get(d["name"], ("aria", "a"))[0],
        "provider": brains.get(d["name"], ("aria", "a"))[1]})
    seats = [d["name"] for d in cp.council_of(exclude=["researcher"])]
    assert len(seats) == 3 and "coder" in seats


def test_a_ballot_has_no_tools(tmp_path, monkeypatch):
    c, store, tb, cp = _world(tmp_path)
    seen = {}

    async def run(self, msgs):
        seen["tools"] = list(self.tool_filter or [])
        return {"content": "YES\nok", "steps": [], "tokens": {}}
    monkeypatch.setattr(Agent, "run", run)
    asyncio.run(cp.run_subagent(store.get_subagent("validator"), "vote", kind="vote"))
    assert seen["tools"] == []


def test_votes_are_read_strictly():
    assert fabric.read_vote("YES\nbecause") is True
    assert fabric.read_vote("No. It is wasteful") is False
    assert fabric.read_vote("**Yes** — sensible") is True
    assert fabric.read_vote("I think so") is None


# ------------------------------------------------------------------ the agent loop

def _asker(c, tb, asked):
    async def emit(ev):
        pass

    async def approver(*a, **k):
        asked.append(a[0])
        return True
    a = Agent(c, tb, "ollama/x", emit, approver, tool_filter=["ask_agent"],
              principal=Principal("subagent", "researcher"), surface="gui")
    a.chain = ["researcher"]
    return a


def test_the_council_answers_instead_of_the_person(tmp_path):
    c, store, tb, cp = _world(tmp_path)
    calls, asked = [], []
    _voters(cp, {"writer": "YES", "analyst": "YES", "validator": "NO"}, calls)
    a = _asker(c, tb, asked)
    out, ok, *_ = asyncio.run(a.call_tool("ask_agent", {"agent": "validator", "question": "is 4 right?"}, "c1"))
    assert not asked, "the person was not asked: the team decided"
    assert ok and "validator answers" in out
    voters = [n for n, k in calls if k == "vote"]
    assert "researcher" not in voters, "the one asking never votes"


def test_a_vote_down_is_a_refusal_with_the_teams_reasons(tmp_path):
    c, store, tb, cp = _world(tmp_path)
    calls, asked = [], []
    _voters(cp, {"writer": "NO\nwe already know", "analyst": "NO\nnot needed"}, calls)
    a = _asker(c, tb, asked)
    out, ok, *_ = asyncio.run(a.call_tool("ask_agent", {"agent": "validator", "question": "q"}, "c2"))
    assert not ok and out.startswith("[denied] Your team voted this down")
    assert "we already know" in out and not asked


def test_with_no_council_the_person_is_asked(tmp_path):
    c, store, tb, cp = _world(tmp_path)
    for n in ("writer", "analyst"):               # only the asker and the asked are left,
        store.delete_subagent(store.get_subagent(n)["id"])   # and no brain for a lead seat
    calls, asked = [], []
    _voters(cp, {}, calls)
    a = _asker(c, tb, asked)
    asyncio.run(a.call_tool("ask_agent", {"agent": "validator", "question": "q"}, "c3"))
    assert asked == ["ask_agent"] and not [k for _n, k in calls if k == "vote"]


def test_a_decision_that_must_be_a_persons_never_reaches_the_council():
    src = (ROOT / "agentos/agent.py").read_text()
    assert 'dec.rule == "democracy" and not must_person' in src


# ------------------------------------------------------------------ huddles

def test_a_huddle_ends_with_a_vote_on_the_last_word(tmp_path):
    c, store, tb, cp = _world(tmp_path)
    turns = iter(["We should ship Friday.", "Friday works if tests pass.", "pass"])

    async def fake(defn, task, kind="delegate", **k):
        if kind == "vote":
            return {"content": "YES\nagreed" if defn["name"] != "writer" else "NO\ntoo soon",
                    "model": "m", "status": "ok", "fault": ""}
        return {"content": next(turns, "pass"), "model": "m", "status": "ok", "fault": ""}
    cp.run_subagent = fake
    said = []

    async def say(e):
        said.append(e)
    res = asyncio.run(cp.huddle(["researcher", "validator", "writer"], "when do we ship?",
                                rounds=1, say=say))
    v = res["vote"]
    assert v["approved"] and (v["yes"], v["of"]) == (2, 3) and v["by"] == "validator"
    last = res["text"].splitlines()[-1]
    assert last.startswith("[vote] agreed, 2 of 3:") and "writer no" in last
    assert said[-1].get("vote"), "the vote is sent live, after the last turn"
    js = (ROOT / "agentos/ui/src/js/10b-huddle.js").read_text()
    assert r"^\[vote\] (.*)$" in js, "the page draws the stored vote line"


def test_matrix_and_swarm_huddles_do_not_vote(tmp_path):
    c, store, tb, cp = _world(tmp_path, talk="swarm")
    turns = iter(["one", "two"])

    async def fake(defn, task, kind="delegate", **k):
        assert kind != "vote"
        return {"content": next(turns, "pass"), "model": "m", "status": "ok", "fault": ""}
    cp.run_subagent = fake
    res = asyncio.run(cp.huddle(["researcher", "validator"], "q", rounds=1))
    assert res["vote"] is None and "[vote]" not in res["text"]


def test_every_surface_offers_it():
    st = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "['democracy','Democracy: 2 of 3 decide']" in st
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '("off", "matrix", "swarm", "democracy")' in main
    srv = (ROOT / "agentos/server.py").read_text()
    assert '("off", "matrix", "swarm", "democracy")' in srv
