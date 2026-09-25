"""Linked teams: another machine over mutual TLS, or another account on this one.

What these defend: the pairing is a handshake bound to a single-use code AND to the
inviter's certificate (checked before the code is sent), a replayed or guessed code is
refused and a guessing address is shut out, only a certificate this machine paired with
gets past the handshake — and then only the exact one pinned; a link grants nothing:
their agents reach one of yours only through a cell here (never asked, never swarmed),
every answer from a linked team arrives marked untrusted, the question itself is
untrusted on the answering side; account links are the same bargain in-process; ending
a link revokes every permission that named it; and every step is in the ledger.
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

from agentos import config as cfgmod                                  # noqa: E402
from agentos import executors, fabric, providers, teamlink            # noqa: E402
from agentos import users as usersmod                                 # noqa: E402
from agentos.memory import Store                                      # noqa: E402
from agentos.policy import PDP, Principal                             # noqa: E402
from agentos.tools import Toolbox                                     # noqa: E402

ROOT = Path(__file__).parent.parent


def _machine(home: Path, name: str, talk="matrix"):
    """One Bento: its own home (PKI, links), store, gate and control plane."""
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 6, "default_model": "openai/gpt-4o",
         "workspace": str(home), "memory": {"inject_facts": 0, "inject_user": 0},
         "providers": {"openai": {"enabled": True, "api_key": "k"}},
         "team": {"talk": talk, "machine_name": name}}
    store = Store(home / "agentos.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    events = []

    async def broadcast(ev):
        events.append(ev)
    tb.broadcast = broadcast
    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    return {"home": home, "cfg": c, "store": store, "tb": tb, "cp": cp, "events": events}


def _scripted():
    """Every agent answers by its persona token; an asker asks as its plan says."""
    def chat(cfg, model, messages, tools, options=None):
        async def gen():
            sys_txt = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = next(m["content"] for m in messages if m["role"] == "user")
            tool_msgs = [m for m in messages if m["role"] == "tool"]
            if "SOUL-analyst" in sys_txt:
                yield {"type": "text", "text": "Churn is 4% on the Pro plan."}
            elif "SOUL-researcher" in sys_txt and not tool_msgs and "asks you" not in user:
                yield {"type": "tool_call", "id": "c1", "name": "ask_agent",
                       "args": {"agent": "analyst@office", "question": "what is Pro churn?"}}
                yield {"type": "finish", "reason": "tool_calls"}
                return
            elif tool_msgs:
                yield {"type": "text", "text": "FINAL " + tool_msgs[-1]["content"][:500]}
            else:
                yield {"type": "text", "text": "ok"}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat


@pytest.fixture()
def pair(tmp_path, monkeypatch):
    """Two machines, 'office' (has the analyst) and 'home' (has the researcher),
    each listening on loopback, paired through a real invite."""
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    A = _machine(tmp_path / "office", "office")
    B = _machine(tmp_path / "home", "home")
    A["store"].save_subagent({"name": "analyst", "soul": "SOUL-analyst"})
    B["store"].save_subagent({"name": "researcher", "soul": "SOUL-researcher", "tools": ["recall"]})

    async def setup():
        async def on_ask_a(lk, req):
            with teamlink.at(A["home"]):
                return await A["cp"].answer_linked(lk, req)
        with teamlink.at(A["home"]):
            A["lst"] = teamlink.Listener(A["cfg"], on_ask=on_ask_a)
            pa = await A["lst"].start("127.0.0.1", 0)
            inv = teamlink.invite("", "machine", address="127.0.0.1", port=pa, cfg=A["cfg"])
        with teamlink.at(B["home"]):
            B["lst"] = teamlink.Listener(B["cfg"])
            pb = await B["lst"].start("127.0.0.1", 0)
            B["link"] = await teamlink.join(inv["invite"], "", cfg=B["cfg"], my_port=pb)
        return inv
    loop = asyncio.new_event_loop()
    inv = loop.run_until_complete(setup())
    yield A, B, inv, loop
    for m in (A, B):
        loop.run_until_complete(m["lst"].stop())
    loop.close()


# ---- the handshake --------------------------------------------------------------------

def test_pairing_trades_cas_and_both_sides_can_reach_each_other_over_mtls(pair):
    A, B, inv, loop = pair
    assert B["link"]["label"] == "office" and B["link"]["kind"] == "machine"
    with teamlink.at(A["home"]):
        a_links = teamlink.links("")
    assert [lk["label"] for lk in a_links] == ["home"], "the inviter recorded the joiner too"
    assert all("peer_ca" not in lk for lk in a_links), "views never carry the PEM"

    async def hello():
        with teamlink.at(B["home"]):
            b_to_a = await teamlink.call(teamlink.find("", "office"), {"op": "hello"})
        with teamlink.at(A["home"]):
            a_to_b = await teamlink.call(teamlink.find("", "home"), {"op": "hello"})
        return b_to_a, a_to_b
    b_to_a, a_to_b = loop.run_until_complete(hello())
    assert {k: b_to_a[k] for k in ("ok", "name", "label_here")} == {"ok": True, "name": "office", "label_here": "home"}
    assert "identity" in b_to_a, "every answer says who the other team is"
    assert a_to_b["ok"] and a_to_b["name"] == "home", "mutual: the inviter can call the joiner"
    assert (A["home"] / "pki" / "ca.key").stat().st_mode & 0o077 == 0, "the CA key is private"


@pytest.fixture()
def truststore_injected(monkeypatch):
    """What `bento` does at startup, so provider calls read the OS store."""
    truststore = pytest.importorskip("truststore")
    import ssl
    monkeypatch.setattr(ssl, "SSLContext", truststore.SSLContext)


def test_a_link_trusts_its_pinned_ca_even_where_the_os_store_was_injected(truststore_injected, pair):
    # Found by the full suite: with truststore over ssl.SSLContext the listener could not
    # read a joiner that has no certificate yet, and a link would verify against the OS
    # store instead of the one CA it paired with.
    A, B, inv, loop = pair

    async def hello():
        with teamlink.at(B["home"]):
            return await teamlink.call(teamlink.find("", "office"), {"op": "hello"})
    assert loop.run_until_complete(hello())["ok"]


def test_a_code_works_once_and_a_wrong_certificate_is_caught_before_the_code_is_sent(pair, tmp_path):
    A, B, inv, loop = pair
    C = tmp_path / "stranger"

    async def go():
        with teamlink.at(C):
            try:
                await teamlink.join(inv["invite"], "")
            except ValueError as e:
                replay = str(e)
            # an invite that pins some OTHER certificate: refused before the code leaves
            forged = re.sub(r"#[0-9a-f]{64}$", "#" + "0" * 64, inv["invite"])
            try:
                await teamlink.join(forged, "")
            except ValueError as e:
                mitm = str(e)
        return replay, mitm
    replay, mitm = loop.run_until_complete(go())
    assert "wrong, used or expired" in replay
    assert "not the one that made the invite" in mitm and "nothing was sent" in mitm


def test_only_the_paired_certificate_gets_past_the_handshake(pair, tmp_path):
    """A stranger with its own CA cannot talk even with a copy of the link record; and
    a request without any certificate is only ever a pairing attempt."""
    A, B, inv, loop = pair
    with teamlink.at(B["home"]):
        stolen = teamlink.find("", "office")

    async def go():
        with teamlink.at(tmp_path / "stranger"):
            teamlink.ensure_pki()
            return await teamlink.call(stolen, {"op": "hello"})
    got = loop.run_until_complete(go())
    assert not got["ok"], got

    async def no_cert():
        import json
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        r, w = await asyncio.open_connection("127.0.0.1", A["lst"].port, ssl=ctx,
                                             server_hostname=teamlink.SNI)
        w.write(b'{"op":"ask","to":"analyst"}\n')
        await w.drain()
        out = json.loads(await r.readline())
        w.close()
        return out
    assert "pair first" in loop.run_until_complete(no_cert())["error"]


def test_a_guessing_address_is_shut_out(pair):
    A, B, inv, loop = pair
    with teamlink.at(A["home"]):
        fresh = teamlink.invite("", "machine", address="127.0.0.1", port=A["lst"].port)
    bad = re.sub(r"/[A-Za-z0-9_-]{16,}#", "/" + "x" * 24 + "#", fresh["invite"])

    async def go():
        with teamlink.at(B["home"].parent / "guesser"):
            for _ in range(teamlink.GUESS_LIMIT):
                with pytest.raises(ValueError):
                    await teamlink.join(bad, "")
            with pytest.raises(ValueError, match="too many wrong codes"):
                await teamlink.join(fresh["invite"], "")
    loop.run_until_complete(go())


def test_an_invite_that_is_not_one_says_what_one_looks_like():
    with pytest.raises(ValueError, match="bento://link/HOST:PORT/CODE#FINGERPRINT"):
        teamlink.parse_invite("https://example.com")
    got = teamlink.parse_invite("bento://link/10.0.0.5:8322/" + "a" * 20 + "#" + "b" * 64)
    assert got["host"] == "10.0.0.5" and got["port"] == 8322


# ---- a question across the link ----------------------------------------------------------

def _ask(B, loop):
    async def go():
        with teamlink.at(B["home"]):
            return await B["cp"].run_subagent(B["store"].get_subagent("researcher"),
                                              "find Pro churn", approver=_yes)
    return loop.run_until_complete(go())


async def _yes(name, args, reason, offer=None):
    return True


def test_a_link_grants_nothing_until_a_cell_on_the_answering_side_allows_it(pair, monkeypatch):
    A, B, inv, loop = pair
    monkeypatch.setattr(providers, "chat", _scripted())
    res = _ask(B, loop)
    assert "not allowed here" in res["content"], "office refused: no cell for home/*"
    assert res["tainted"], "the refusal's wording is theirs, so it arrives marked untrusted too"
    assert not [r for r in A["store"].fabric_runs(limit=20) if r["kind"] == "linked"]
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["analyst"])
    res = _ask(B, loop)
    assert "Churn is 4% on the Pro plan." in res["content"]
    assert res["tainted"], "an answer from another machine is untrusted on arrival"
    runs = [r for r in A["store"].fabric_runs(limit=20) if r["kind"] == "linked"]
    assert len(runs) == 1 and runs[0]["ref"] == "analyst"
    # the office ledger names who asked, by link and agent
    rows = [r for r in A["store"].audit_list(limit=50) if r["action"] == "agent.message"]
    assert rows[0]["principal_kind"] == "team" and rows[0]["principal_id"] == "home/researcher"
    assert {r["effect"] for r in rows} == {"deny", "allow"}


def test_the_asking_side_asks_its_person_and_swarm_never_opens_another_team(pair, monkeypatch):
    A, B, inv, loop = pair
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["analyst"])
    sub = Principal("subagent", "researcher")
    res = "agent:subagent/analyst@office"
    B["cfg"]["team"]["talk"] = "swarm"
    assert B["tb"].pdp.decide(sub, "agent.message", res, {}).effect == "ask", \
        "swarm opens your own agents' cells, never a linked team's"
    fabric.set_link_access(B["store"], "office", mine_may_ask=True)
    assert B["tb"].pdp.decide(sub, "agent.message", res, {}).effect == "allow"
    # and a linked team's agent is never asked for — nobody waits at the far end
    d = A["tb"].pdp.decide(Principal("team", "home/researcher"), "agent.message",
                           "agent:subagent/someone-else", {})
    assert d.effect == "deny" and d.rule == "team-default"
    for action in ("tool.use", "agent.invoke", "agent.huddle", "flow.write"):
        assert A["tb"].pdp.decide(Principal("team", "home/x"), action, "*", {}).effect == "deny"


def test_the_question_is_untrusted_where_it_is_answered(pair, monkeypatch):
    A, B, inv, loop = pair
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["analyst"])
    seen = {}
    real = A["cp"].run_subagent

    async def spy(defn, task, **kw):
        seen.update(kw)
        seen["task"] = task
        return await real(defn, task, **kw)
    monkeypatch.setattr(A["cp"], "run_subagent", spy)
    monkeypatch.setattr(providers, "chat", _scripted())
    _ask(B, loop)
    assert seen["taint"] == [{"tool": "linked team", "source": "home"}]
    assert "came from OUTSIDE this machine" in seen["task"]
    assert seen["chain"] == ["researcher@home"], "their names carry the link, so a loop is still seen"


def test_ending_a_link_revokes_every_cell_that_named_it(pair):
    A, B, inv, loop = pair
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["analyst"], mine_may_ask=True)
    assert fabric.link_access(A["store"], "home") == {"theirs_may_ask": ["analyst"], "mine_may_ask": True}
    with teamlink.at(A["home"]):
        assert teamlink.remove("", "home")
    assert fabric.forget_link_grants(A["store"], "home") == 2
    assert fabric.link_access(A["store"], "home") == {"theirs_may_ask": [], "mine_may_ask": False}
    revokes = [r for r in A["store"].audit_list(limit=50) if r["action"] == "grant.revoke"]
    assert len(revokes) >= 2, "each revoked cell is a ledger row"


# ---- two accounts on one machine ---------------------------------------------------------

@pytest.fixture()
def accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    ada = usersmod.create("ada", "hunter2hunter")["id"]
    bob = usersmod.create("bob", "hunter2hunter", role="executor")["id"]
    m = _machine(tmp_path, "shared")
    for uid, agent in ((ada, "researcher"), (bob, "analyst")):
        with usersmod.as_user(uid):
            usersmod.store_for(uid).save_subagent({"name": agent, "soul": f"SOUL-{agent}",
                                                    "tools": ["recall"]})
    return m, ada, bob


def test_an_account_link_is_a_code_redeemed_by_the_other_person(accounts):
    m, ada, bob = accounts
    inv = teamlink.invite(ada, "account")
    with pytest.raises(ValueError, match="your own code"):
        teamlink.redeem_account(inv["code"], ada)
    got = teamlink.redeem_account(inv["code"], bob, {ada: "ada", bob: "bob"})
    assert got["mine"]["label"] == "ada" and got["theirs"]["label"] == "bob"
    with pytest.raises(ValueError, match="wrong, used or expired"):
        teamlink.redeem_account(inv["code"], bob)
    # ending it from one side ends both halves
    assert teamlink.remove(bob, "ada")
    assert teamlink.links(ada) == [] and teamlink.links(bob) == []


def test_an_account_asks_another_in_process_under_the_other_persons_gate(accounts, monkeypatch):
    m, ada, bob = accounts
    inv = teamlink.invite(bob, "account")
    teamlink.redeem_account(inv["code"], ada, {ada: "ada", bob: "bob"})
    monkeypatch.setattr(providers, "chat", _scripted())

    async def ask():
        with usersmod.as_user(ada):
            return await m["cp"].message("researcher", "analyst@bob", "what is Pro churn?",
                                         ["researcher"], root="t1")
    out = asyncio.run(ask())
    assert "not allowed here" in out, "bob has not allowed ada's agents"
    with usersmod.as_user(bob):
        fabric.set_link_access(usersmod.store_for(bob), "ada", theirs_may_ask=["analyst"])
    out = asyncio.run(ask())
    assert "Churn is 4% on the Pro plan." in out and out.startswith(fabric.TAINTED_REPLY)
    runs = [r for r in usersmod.store_for(bob).fabric_runs(limit=10) if r["kind"] == "linked"]
    assert runs and runs[0]["ref"] == "analyst", "it ran in bob's account, on bob's database"
    assert not [r for r in usersmod.store_for(ada).fabric_runs(limit=10) if r["kind"] == "linked"]


# ---- faces ---------------------------------------------------------------------------------

def test_the_link_has_a_settings_face_and_a_terminal_one(tmp_path):
    st = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    for needle in ("function paintTeamLinks(", "/api/team/links/invite", "/api/team/links/join",
                   "/api/team/listen", "theirs_may_ask", "mine_may_ask"):
        assert needle in st, needle
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "link", *a],  # noqa: E731
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    r = run()
    assert r.returncode == 0 and "certificate" in r.stdout and "no linked teams" in r.stdout
    r = run("invite")
    assert re.search(r"bento://link/\S+:\d+/[A-Za-z0-9_-]{16,}#[0-9a-f]{64}", r.stdout)
    assert "not accepting linked teams" in r.stdout
    r = run("join", "bento://link/127.0.0.1:1/" + "a" * 24 + "#" + "b" * 64)
    assert r.returncode == 2 and "could not reach" in r.stdout


def test_a_question_from_another_team_is_not_written_into_the_open_chat():
    # The websocket treats "no conversation id" as "the open one"; a linked question has
    # none, and landed inside whatever chat the person was reading. Measured in Chromium:
    # before, a card; after, the stage and a toast only.
    js = (ROOT / "agentos/ui/src/js/10b-huddle.js").read_text()
    body = js[js.index("function agentMsgLive"):]
    body = body[:body.index("\n}\n")]
    assert body.index("if(!ev.conversation_id)") < body.index("huddleLive("), body
    guard = body[body.index("if(!ev.conversation_id)"):body.index("huddleLive(")]
    assert "return" in guard and "crewPulse" in guard
