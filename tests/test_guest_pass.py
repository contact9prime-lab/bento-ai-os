"""Guest passes: lend one of your specialists to a friend's Bento for a few minutes.

Asked for as "summon my Security Auditor agent into your Bento desktop … join their
huddle for 10 minutes, bringing its own expertise without exposing your private API
keys or raw filesystem". A pass is a linked-team invite that carries one agent and a
number of minutes. What these defend:

- redeemed, both halves of the link carry the pass; the lender writes ONE cell, that
  agent, expiring with the pass (source "pass", so the matrix editor never rewrites it);
- the lent agent answers in words only: no tools at all on the lender's machine;
- only the lent agent may be asked, and nothing once the time is up, on either side;
- the guest can sit in a huddle as name@link; a guest's words taint every local turn,
  and a guest never votes;
- what the other side claims about a pass is held to PASS_MAX and the painter's set;
- every face reaches it: routes, the CLI, Settings, the huddle card and the World.
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import config as cfgmod                                  # noqa: E402
from agentos import executors, fabric, providers, teamlink            # noqa: E402
from agentos import users as usersmod                                 # noqa: E402
from test_teamlink import _machine                                    # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


@pytest.fixture()
def lent(tmp_path, monkeypatch):
    """bob lends his auditor to ada for ten minutes; ada has a researcher of her own."""
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    ada = usersmod.create("ada", "hunter2hunter")["id"]
    bob = usersmod.create("bob", "hunter2hunter", role="executor")["id"]
    m = _machine(tmp_path, "shared")
    for uid, agents in ((ada, ("researcher",)), (bob, ("auditor", "analyst"))):
        with usersmod.as_user(uid):
            for a in agents:
                usersmod.store_for(uid).save_subagent({"name": a, "soul": f"SOUL-{a}",
                                                       "tools": ["recall", "write_file"]})
    inv = teamlink.invite(bob, "account", guest={"agent": "auditor", "minutes": 10,
                                                  "look": {"skin": 2, "hair": "bob"}})
    got = teamlink.redeem_account(inv["code"], ada, {ada: "ada", bob: "bob"})
    with usersmod.as_user(bob):
        fabric.grant_pass(usersmod.store_for(bob), got["theirs"])
    seen = []

    def chat(cfg, model, messages, tools, options=None):
        sys_txt = next((x["content"] for x in messages if x["role"] == "system"), "")
        user = next((x["content"] for x in messages if x["role"] == "user"), "")
        seen.append({"soul": sys_txt, "tools": [t.get("name") or t.get("function", {}).get("name")
                                                for t in (tools or [])], "user": user})

        async def gen():
            if "SOUL-auditor" in sys_txt:
                yield {"type": "text", "text": "Check the token expiry and the CORS list first."}
            elif "SOUL-analyst" in sys_txt:
                yield {"type": "text", "text": "analyst speaking"}
            else:
                yield {"type": "text", "text": "Agreed with the auditor, and I would add rate limits."}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", chat)
    return {"m": m, "ada": ada, "bob": bob, "inv": inv, "got": got, "seen": seen}


def _ask(L, to, sender="researcher"):
    async def go():
        with usersmod.as_user(L["ada"]):
            return await L["m"]["cp"].message(sender, to, "how would you review this login?",
                                              [sender], root=f"t{time.time()}")
    return asyncio.run(go())


def _end_pass(L):
    d = teamlink._load()
    for lk in d["links"]:
        if lk.get("pass"):
            lk["pass"]["until"] = time.time() - 1
    teamlink._save(d)
    # the lender's cell was written with the same end
    st = usersmod.store_for(L["bob"])
    st.db.execute("UPDATE grants SET expires_at=? WHERE source='pass'", (time.time() - 1,))
    st.db.commit()


def test_both_halves_carry_the_pass_and_the_lender_writes_one_expiring_cell(lent):
    L = lent
    assert L["inv"]["guest"] == {"agent": "auditor", "minutes": 10}, "the look is not echoed to the page"
    mine, theirs = L["got"]["mine"], L["got"]["theirs"]
    assert mine["pass"]["role"] == "guest" and theirs["pass"]["role"] == "lender"
    assert mine["pass"]["agent"] == theirs["pass"]["agent"] == "auditor"
    assert 9 * 60 < mine["pass"]["until"] - time.time() <= 10 * 60
    assert mine["pass"]["look"], "the guest side can draw the lent agent's own face"
    bob_store = usersmod.store_for(L["bob"])
    rows = [g for g in bob_store.list_grants() if g.get("source") == "pass"]
    assert len(rows) == 1 and rows[0]["resource"] == "agent:subagent/auditor"
    assert rows[0]["principal_id"] == "ada/*" and rows[0]["expires_at"] == theirs["pass"]["until"]
    with usersmod.as_user(L["bob"]):
        assert fabric.link_access(bob_store, "ada")["theirs_may_ask"] == ["auditor"]
        # the matrix editor's rewrite of the link's cells never wipes the pass's cell
        fabric.set_link_access(bob_store, "ada", theirs_may_ask=[])
    assert [g for g in bob_store.list_grants() if g.get("source") == "pass"]
    assert bob_store.db.execute("SELECT COUNT(*) FROM audit WHERE action='link.pass'").fetchone()[0] == 1


def test_the_lent_agent_answers_in_words_only_and_nobody_else_is_lent(lent):
    L = lent
    out = _ask(L, "auditor@bob")
    assert "token expiry" in out and out.startswith(fabric.TAINTED_REPLY)
    asked = [s for s in L["seen"] if "SOUL-auditor" in s["soul"]]
    assert asked and asked[-1]["tools"] == [], "a lent agent runs with no tools on the lender's machine"
    runs = [r for r in usersmod.store_for(L["bob"]).fabric_runs(limit=10) if r["kind"] == "linked"]
    assert runs and runs[0]["ref"] == "auditor", "it ran in bob's account"
    out = _ask(L, "analyst@bob")
    assert "lent auditor only" in out and not any("SOUL-analyst" in s["soul"] for s in L["seen"])


def test_an_ended_pass_is_refused_on_both_sides_and_swept(lent):
    L = lent
    _end_pass(L)
    assert "has ended" in _ask(L, "auditor@bob")
    # the lender refuses on its own clock too, whatever the guest side does
    bob_half = next(x for x in teamlink.links(L["bob"]) if x.get("pass"))
    got = asyncio.run(L["m"]["cp"].answer_linked(bob_half, {"op": "ask", "to": "auditor",
                                                            "from": "researcher", "question": "hi"}))
    assert not got["ok"] and "ended" in got["error"]
    assert {lk["owner"] for lk in teamlink.ended_passes()} == {L["ada"], L["bob"]}
    with usersmod.as_user(L["bob"]):
        assert fabric.link_access(usersmod.store_for(L["bob"]), "ada")["theirs_may_ask"] == []
    with usersmod.as_user(L["ada"]):
        assert fabric.guest_seat(L["ada"], "auditor@bob") is None


def test_a_guest_sits_in_a_huddle_taints_the_room_and_does_not_vote(lent, monkeypatch):
    L = lent
    with usersmod.as_user(L["ada"]):
        seat = fabric.guest_seat(L["ada"], "auditor@bob")
        assert seat and seat["linked"] and seat["name"] == "auditor@bob" and seat["look"]
        assert fabric.guest_seat(L["ada"], "analyst@bob") is None, "only the lent agent sits in a room"
        assert fabric.guest_seat(L["ada"], "auditor@nowhere") is None
        names, q = fabric.parse_huddle(usersmod.store_for(L["ada"]), "@researcher @auditor@bob review the login")
        assert names == ["researcher", "auditor@bob"] and q == "review the login"
        taints, said = [], []
        real = L["m"]["cp"].run_subagent

        async def spy(d, task, **kw):
            taints.append((d["name"], kw.get("taint")))
            return await real(d, task, **kw)
        monkeypatch.setattr(L["m"]["cp"], "run_subagent", spy)

        async def say(e):
            said.append(e)

        cp = L["m"]["cp"]
        cp.store = usersmod.store_for(L["ada"])
        out = asyncio.run(cp.huddle(["researcher", "auditor@bob"], "review the login", rounds=1, say=say))
    lines = out["text"].split("\n")
    assert any(x.startswith("@auditor@bob (") and "token expiry" in x for x in lines)
    assert [t for n, t in taints if n == "researcher"][0][0]["tool"] == "linked team"
    guest = [e for e in said if e["speaker"] == "auditor@bob"]
    assert guest and guest[0]["look"] and guest[0]["provider"] == "guest from bob"
    # a ballot never seats the guest
    src = (ROOT / "agentos/fabric.py").read_text()
    assert '[d for d in cast if not d.get("linked")]' in src


def test_what_the_other_side_claims_is_held_to_the_ceiling():
    far = time.time() + 10 * 3600
    p = teamlink.clean_pass({"agent": "aud\x1b[31mitor", "until": far, "look": {"skin": 99, "evil": 1}}, "guest")
    assert p["until"] <= time.time() + teamlink.PASS_MAX * 60 + 1
    assert "\x1b" not in p["agent"] and "evil" not in p["look"]
    assert teamlink.clean_pass({"agent": "x", "until": "soon"}, "guest") is None
    assert teamlink.clean_pass({"until": far}, "guest") is None
    inv = teamlink.invite("", "account", guest={"agent": "a", "minutes": 9999})
    assert inv["guest"]["minutes"] == teamlink.PASS_MAX


def test_every_face_reaches_it():
    src = (ROOT / "agentos/server.py").read_text()
    for needle in ('@app.post("/api/team/pass")', '@app.get("/api/team/passes")',
                   "fabricmod.grant_pass(", "def _team_end_link(", "def _world_guests(",
                   "a guest pass lends one agent"):
        assert needle in src, needle
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert 'if act == "pass":' in cli and '"--minutes"' in cli and "grant_pass(" in cli
    st = (JS / "11-settings.js").read_text()
    for fn in ("function tlLendHTML(", "function tlPassHTML(", "function tlPassTick(", "/api/team/pass"):
        assert fn in st, fn
    assert "avatarGuest(e.speaker,e.look)" in (JS / "10b-huddle.js").read_text()
    assert "if(AV_GUEST[key])return avatarRecipeSrc(" in (JS / "00e-avatars.js").read_text(), \
        "a guest's face is painted from its pass wherever its name appears"
    world = (JS / "01e-world.js").read_text()
    assert "a&&a.guest?avatarRecipeSrc(" in world and "function worldGuest(" in world


def test_a_pass_travels_through_the_machine_handshake(tmp_path, monkeypatch):
    """Over real mutual TLS: the lender's half arrives at its on_event with the pass, the
    joiner's half carries it as a guest, and the lent agent answers there with no tools."""
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    A = _machine(tmp_path / "lender", "lender")
    B = _machine(tmp_path / "friend", "friend")
    A["store"].save_subagent({"name": "auditor", "soul": "SOUL-auditor", "tools": ["write_file"]})
    paired, tools_seen = [], []

    def chat(cfg, model, messages, tools, options=None):
        tools_seen.append(list(tools or []))

        async def gen():
            yield {"type": "text", "text": "Rotate the signing key."}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", chat)

    async def go():
        async def on_event(kind, lk):
            paired.append(lk)
            with teamlink.at(A["home"]):
                fabric.grant_pass(A["store"], lk)

        async def on_ask(lk, req):
            with teamlink.at(A["home"]):
                return await A["cp"].answer_linked(lk, req)
        with teamlink.at(A["home"]):
            lst = teamlink.Listener(A["cfg"], on_ask=on_ask, on_event=on_event)
            port = await lst.start("127.0.0.1", 0)
            inv = teamlink.invite("", "machine", address="127.0.0.1", port=port, cfg=A["cfg"],
                                  guest={"agent": "auditor", "minutes": 5})
        try:
            with teamlink.at(B["home"]):
                lk = await teamlink.join(inv["invite"], "", cfg=B["cfg"])
                assert lk["pass"]["role"] == "guest" and lk["pass"]["agent"] == "auditor"
                assert fabric.guest_seat("", f"auditor@{lk['label']}")
                return await B["cp"].message("huddle", f"auditor@{lk['label']}", "review it",
                                             ["huddle"], root="h1")
        finally:
            await lst.stop()
    out = asyncio.run(go())
    assert paired and paired[0]["pass"]["role"] == "lender"
    assert "Rotate the signing key." in out and out.startswith(fabric.TAINTED_REPLY)
    assert tools_seen and tools_seen[-1] == [], "words only on the lender's machine"
    assert [g for g in A["store"].list_grants() if g.get("source") == "pass"]
