"""The security review of linked teams and Team Chat, one test per finding.

Each of these was a real gap found by reading the code as an attacker would, and each
test is written against the running pieces (real listeners, real TLS) where the network
is involved:

1. a link granted the ROSTER without a cell — every agent's name and provider;
2. "no agent called X" vs "not allowed" let a linked team enumerate agents anyway;
3. a linked team's REFUSAL text reached this agent unmarked (the taint rules skipped it);
4. text from elsewhere reached terminals raw — escape sequences, bidi overrides, and Rich
   markup in the chat TUI (a "[link=…]" is a clickable link there);
5. on a machine with accounts, a machine's request was shown to — and approvable by —
   every account, so the first tap won a link meant for somebody else;
6. a conversation was keyed by the link's LABEL, which is reused after a remove, so an
   old thread would appear to be with a new party;
7. nothing bounded unread messages (never pruned: a peer could fill the disk), the
   listener's open connections, a linked peer's unmetered calls, or how often a person
   could make this server dial out;
8. a request's claimed port was not range-checked; a rename was not audited.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric, providers, teamchat, teamlink            # noqa: E402
from agentos.memory import Store                                      # noqa: E402
from test_teamlink import _scripted, pair                             # noqa: E402,F401
from test_teamlink_request import _ask as _ask_link, _waiting, two    # noqa: E402,F401

ESC_TRICKS = "ok\x1b]52;c;ZXZpbA==\x07\x1b[2J‮gnp.exe⁦x\x9b31m"


# ---- 1, 2: what a link reveals before anything is allowed -----------------------------------

def _roster(B, loop):
    async def go():
        with teamlink.at(B["home"]):
            return await teamlink.call(teamlink.find("", "office"), {"op": "roster"})
    return loop.run_until_complete(go())


def test_the_roster_shows_only_the_agents_a_link_may_ask(pair):
    A, B, inv, loop = pair
    A["store"].save_subagent({"name": "secret-ops", "soul": "x"})
    assert _roster(B, loop)["agents"] == [], "a link grants nothing — not even the names"
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["analyst"])
    assert [a["name"] for a in _roster(B, loop)["agents"]] == ["analyst"]


def test_a_refusal_says_the_same_thing_whether_the_agent_exists_or_not(pair):
    A, B, inv, loop = pair

    async def ask(to):
        with teamlink.at(B["home"]):
            return await teamlink.call(teamlink.find("", "office"),
                                       {"op": "ask", "from": "researcher", "to": to, "question": "hi"})
    real, ghost = loop.run_until_complete(ask("analyst")), loop.run_until_complete(ask("nobody-here"))
    assert not real["ok"] and not ghost["ok"]
    assert real["error"] == ghost["error"], "the refusal must not tell which names exist"


# ---- 3: a refusal's wording is theirs --------------------------------------------------------

def test_a_linked_teams_refusal_arrives_marked_untrusted(pair, monkeypatch):
    A, B, inv, loop = pair
    monkeypatch.setattr(providers, "chat", _scripted())

    async def go():
        with teamlink.at(B["home"]):
            return await B["cp"].message("researcher", "analyst@office", "what is Pro churn?",
                                         chain=["researcher"], root="t1")
    out = loop.run_until_complete(go())
    assert out.startswith(fabric.TAINTED_REPLY) and "[refused]" in out


# ---- 4: text from elsewhere is text -------------------------------------------------------------

def test_escape_sequences_and_bidi_never_survive_the_way_in():
    clean = teamlink.plain(ESC_TRICKS)
    assert "\x1b" not in clean and "\x07" not in clean and "\x9b" not in clean
    assert "‮" not in clean and "⁦" not in clean
    m = teamchat.clean_message({"id": "abcdef0123456789", "text": ESC_TRICKS, "sender": "ev\x1bil‮"})
    assert "\x1b" not in m["text"] + m["sender"] and "‮" not in m["sender"]
    ident = teamlink.clean_identity({"agent_name": "A\x1b[31mria", "person": "‮Priya"})
    assert ident == {"agent_name": "A[31mria", "person": "Priya"}
    assert teamlink.plain("line one\nline two") == "line one\nline two", "newlines are kept"


def test_the_chat_tui_prints_markup_as_text():
    from rich.text import Text
    from agentos.tui_app import _esc
    shown = Text.from_markup("x " + _esc("[link=http://evil]click[/link] [red]ERROR")).plain
    assert "[link=http://evil]click[/link]" in shown, "no clickable link, no forged colour"
    src = (Path(__file__).parent.parent / "agentos/tui_app.py").read_text()
    for kind in ("agent_msg", "agent_say", "team_message", "team_link_request"):
        block = src[src.index(f'elif t == "{kind}"'):]
        block = block[:block.index("elif t ==", 10)]
        assert "{ev.get('text'" not in block and "{ev.get('sender'" not in block, \
            f"{kind} interpolates another party's words unescaped"


# ---- 5: a machine's request goes to the person it was for ------------------------------------------

def test_on_a_machine_with_accounts_a_request_reaches_only_who_it_was_for():
    r_ada = {"kind": "machine", "to_account": "ada"}
    r_none = {"kind": "machine", "to_account": ""}
    ada = {"multi": True, "admin": False, "name": "ada"}
    bob = {"multi": True, "admin": False, "name": "bob"}
    root = {"multi": True, "admin": True, "name": "root"}
    single = {"multi": False}
    assert teamlink.may_answer(r_ada, "u-ada", ada) and not teamlink.may_answer(r_ada, "u-bob", bob)
    assert not teamlink.may_answer(r_ada, "u-root", root), "even an admin does not take Ada's"
    assert teamlink.may_answer(r_none, "u-root", root) and not teamlink.may_answer(r_none, "u-bob", bob)
    assert teamlink.may_answer(r_none, "", single), "one person, no accounts: theirs"


def test_a_request_can_name_the_account_and_only_that_account_can_approve(two):
    A, B, loop = two
    async def ask():
        with teamlink.at(B["home"]):
            return await teamlink.request_link(f"ada@127.0.0.1:{A['port']}", "", cfg=B["cfg"])
    p = loop.run_until_complete(ask())
    with teamlink.at(A["home"]):
        bob = {"multi": True, "admin": True, "name": "bob"}
        assert teamlink.requests("u-bob", bob)["incoming"] == []
        rid = teamlink._load()["requests"][0]["id"]
        with pytest.raises(ValueError):
            teamlink.approve(rid, "u-bob", who=bob)
        ada = {"multi": True, "admin": False, "name": "ada"}
        assert [r["name"] for r in teamlink.requests("u-ada", ada)["incoming"]] == ["home"]
        assert teamlink.approve(rid, "u-ada", who=ada)["pending"]["owner"] == "u-ada"
    assert p["sas"]


# ---- 6: a conversation belongs to a link, not to a name ----------------------------------------------

def test_a_new_link_with_an_old_name_does_not_inherit_the_old_conversation(tmp_path):
    s = Store(tmp_path / "a.db")
    old = {"id": "link-1", "label": "office", "owner": ""}
    teamchat.receive(s, "", old, {"id": "a" * 16, "text": "old secret"})
    new = {"id": "link-2", "label": "office", "owner": ""}
    assert s.team_msgs(new["id"]) == [], "the new 'office' is somebody else"
    t = teamchat.threads(s, [new])[0]
    assert t["last"] is None and t["unread"] == 0


# ---- 7: ceilings ------------------------------------------------------------------------------------

def test_unread_messages_push_back_instead_of_filling_the_disk(tmp_path, monkeypatch):
    s = Store(tmp_path / "a.db")
    lk = {"id": "l", "label": "office", "owner": ""}
    monkeypatch.setattr(teamchat, "MAX_UNREAD", 3)
    teamchat._meter.clear()
    for i in range(3):
        assert teamchat.receive(s, "", lk, {"id": f"{i:016d}", "text": "hi"})[0]
    msg, why = teamchat.receive(s, "", lk, {"id": "9" * 16, "text": "hi"})
    assert msg is None and "unread" in why, "the sender is told, in words"
    s.team_msg_read("l")
    assert teamchat.receive(s, "", lk, {"id": "8" * 16, "text": "hi"})[0], "reading lets them through again"
    teamchat._meter.clear()


def test_a_linked_peer_is_metered_on_every_kind_of_call(pair, monkeypatch):
    A, B, inv, loop = pair
    monkeypatch.setattr(teamlink, "PEER_CALLS", 3)

    async def hello():
        with teamlink.at(B["home"]):
            return await teamlink.call(teamlink.find("", "office"), {"op": "hello"})
    got = [loop.run_until_complete(hello()) for _ in range(4)]
    assert [g["ok"] for g in got] == [True, True, True, False]
    assert "slow down" in got[-1]["error"]


def test_the_listener_closes_the_door_at_its_connection_ceiling(pair, monkeypatch):
    A, B, inv, loop = pair
    monkeypatch.setattr(teamlink, "MAX_OPEN", 0)

    async def hello():
        with teamlink.at(B["home"]):
            return await teamlink.call(teamlink.find("", "office"), {"op": "hello"})
    assert not loop.run_until_complete(hello())["ok"], "closed at once, not queued"


def test_a_claimed_port_is_a_port():
    assert teamlink._port("8322") == 8322
    for bad in (-1, 0, 70000, "x", None, 10 ** 30):
        assert teamlink._port(bad) == 0


def test_a_person_cannot_make_the_server_dial_out_without_limit(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    servermod._TEAM_DIALS.clear()
    with TestClient(servermod.app) as cl:
        codes = [cl.post("/api/team/links/request", json={"address": "127.0.0.1:1"}).status_code
                 for _ in range(servermod.TEAM_DIALS + 1)]
        assert codes[:-1] == [400] * servermod.TEAM_DIALS and codes[-1] == 429
        # and the rename is cleaned and in the ledger
        got = cl.put("/api/team/me", json={"name": "Sam\x1b[2J‮"}).json()
        assert got["name"] == "Sam[2J"
        rows = servermod.state["store"].audit_list(limit=10)
        assert any(r.get("resource") == "team:my_name" for r in rows)
    servermod._TEAM_DIALS.clear()
