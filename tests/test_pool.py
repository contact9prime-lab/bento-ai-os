"""A community of machines: one leader holds the keys, small machines join and share.

Asked for as "a pool mode where multiple small computers make a bigger task so the
agents share the common pool of memory … they elect a leader and the leader has all the
creds like a control plane and the small agents join the community". Three machines
stand up in this process, each with its own home, its own link door on loopback (real
mutual TLS, the linked-teams wire) and its own gate. The leader's brain is a stand-in
that says who it is, so every answer shows which machine thought it.
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import executors, pool, teamlink                       # noqa: E402
from agentos.memory import Store                                    # noqa: E402
from agentos.policy import PDP, Principal                           # noqa: E402

ROOT = Path(__file__).parent.parent


def _brain(who):
    def chat(cfg, model, messages, tools, options=None):
        async def gen():
            user = [m for m in messages if m.get("role") == "user"][-1]["content"]
            yield {"type": "text", "text": f"{who} thought about: {user}"}
            yield {"type": "usage", "input": 12, "output": 7}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat


def _machine(home: Path, name: str, brain=True):
    home.mkdir(parents=True, exist_ok=True)
    cfg = {"agent_name": "Aria", "default_model": "openai/gpt-4o" if brain else "",
           "providers": {"openai": {"enabled": True, "api_key": "k" if brain else ""}},
           "team": {"machine_name": name}}
    store = Store(home / "agentos.db")
    pdp = PDP(cfg, store)
    worked = []

    async def work(task, frm, pid):
        worked.append(task)
        return {"ok": True, "text": f"{name} did: {task}"}
    p = pool.Pool(cfg=lambda: cfg, store=lambda: store, pdp=lambda: pdp, chat=_brain(name), work=work)
    return {"home": home, "name": name, "cfg": cfg, "store": store, "pdp": pdp, "pool": p,
            "worked": worked}


def _at(m):
    return teamlink.at(m["home"])


async def _listen(m, port=0):
    async def on_pool(lk, req):
        with _at(m):
            return await m["pool"].on_op(lk, req)
    with _at(m):
        m["lst"] = teamlink.Listener(m["cfg"], on_pool=on_pool)
        m["port"] = await m["lst"].start("127.0.0.1", port)


async def _link(a, b):
    """b joins a through a real invite: a machine link both ways, as Linked teams makes."""
    with _at(a):
        inv = teamlink.invite("", "machine", address="127.0.0.1", port=a["port"], cfg=a["cfg"])
    with _at(b):
        return await teamlink.join(inv["invite"], "", cfg=b["cfg"], my_port=b["port"])


async def _tick(m):
    with _at(m):
        return await m["pool"].tick()


def _peer(name):
    """The whole record of this machine's community link to `name` (views drop the CA)."""
    return next(lk for lk in teamlink._load()["links"] if lk.get("kind") == "pool" and lk.get("peer_name") == name)


def _stale(m):
    """Pretend this member last heard its leader longer ago than DEAD_S."""
    with _at(m):
        d = pool.load()
        d["last_ok"] = time.time() - pool.DEAD_S - 5
        pool.save(d)


@pytest.fixture()
def net(tmp_path, monkeypatch):
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    L = _machine(tmp_path / "lead", "big-box")
    A = _machine(tmp_path / "pi-a", "pi-kitchen", brain=False)
    B = _machine(tmp_path / "pi-b", "pi-garage")
    loop = asyncio.new_event_loop()

    async def setup():
        for m in (L, A, B):
            await _listen(m)
        A["link"] = await _link(L, A)
        B["link"] = await _link(L, B)
    loop.run_until_complete(setup())
    yield L, A, B, loop
    for m in (L, A, B):
        if m.get("lst"):
            loop.run_until_complete(m["lst"].stop())
    loop.close()


def _form(L, A, B, loop):
    """L starts 'Home', A and B ask, L lets both in, both hear back."""
    async def go():
        with _at(L):
            pool.create(L["cfg"], "Home")
        for m in (A, B):
            with _at(m):
                await pool.join(m["cfg"], m["link"]["label"])
                d = pool.load()
                pool.grant_work(m["store"], d["pool"]["id"], d["pool"]["name"])
        with _at(L):
            assert {e["name"] for e in pool.view(L["cfg"])["pending"]} == {"pi-kitchen", "pi-garage"}
            for m in (A, B):
                pool.approve(L["store"], m["name"])
        for m in (A, B):
            assert (await _tick(m))["role"] == "member"
    loop.run_until_complete(go())


def test_joining_is_asked_and_admitting_is_one_grant(net):
    L, A, B, loop = net

    async def go():
        with _at(L):
            pool.create(L["cfg"], "Home")
        with _at(A):
            v = await pool.join(A["cfg"], A["link"]["label"])
        assert v["role"] == "pending"
        assert (await _tick(A))["role"] == "pending", "nothing until the leader's admin says yes"
        with _at(A):
            with pytest.raises(Exception, match="still waiting"):
                async for _ in pool.chat(A["cfg"], "default", [{"role": "user", "content": "hi"}], []):
                    pass
        with _at(L):
            pool.approve(L["store"], "pi-kitchen")
            rows = [g for g in L["store"].list_grants() if g["principal_kind"] == "pool"]
        assert [(g["action"], g["resource"]) for g in rows] == [("model.use", "model:*")], \
            "admission writes exactly one grant: think with this machine's brain"
        assert (await _tick(A))["role"] == "member"
        with _at(A):
            v = pool.view(A["cfg"])
        assert {m["name"] for m in v["machines"]} == {"big-box", "pi-kitchen"}
        assert v["leader"]["name"] == "big-box"
    loop.run_until_complete(go())


def test_a_member_thinks_with_the_leaders_brain_through_the_leaders_gate(net):
    L, A, B, loop = net
    _form(L, A, B, loop)

    async def ask():
        with _at(A):
            out = []
            async for ev in pool.chat(A["cfg"], "default", [{"role": "user", "content": "plan the week"}], []):
                out.append(ev)
            return out
    evs = loop.run_until_complete(ask())
    assert evs[0] == {"type": "text", "text": "big-box thought about: plan the week"}, \
        "the leader's brain answered, with the leader's key"
    with _at(A):
        assert [m["id"] for m in pool.models()][0] == "pool/default"
    with _at(L):
        led = L["store"].audit_list(action="model.use")
        assert any(r["principal_kind"] == "pool" and r["effect"] == "allow" for r in led), "on the leader's ledger"
        # revoking the one grant stops it at the gate
        fp = next(fp for fp, e in pool.load()["members"].items() if e["name"] == "pi-kitchen")
        L["store"].revoke_grants_for("pool", pool.principal_id(fp))
    with pytest.raises(Exception, match="refused"):
        loop.run_until_complete(ask())


def test_a_pool_principal_is_refused_everything_it_was_not_granted(net):
    L, A, B, loop = net
    with _at(L):
        pdp = L["pdp"]
        for action, res in (("tool.use", "tool:run_command"), ("fs.read", "fs:/etc/passwd"),
                            ("agent.message", "agent:subagent/x"), ("model.use", "model:openai/gpt-4o")):
            d = pdp.decide(Principal("pool", "abcd"), action, res, {"surface": "pool"})
            assert d.effect == "deny", (action, d)
        assert d.rule == "pool-default"


def test_notes_are_shared_through_the_leader_and_forgetting_travels(net):
    L, A, B, loop = net
    _form(L, A, B, loop)
    with _at(A):
        got = pool.note_add("the garage door sticks in the cold", machine="pi-kitchen")
        assert not got["shared"], "a member's note waits for the leader"
    loop.run_until_complete(_tick(A))       # A sends it
    loop.run_until_complete(_tick(B))       # B receives it
    with _at(B):
        rows = pool.notes_search("garage")
        assert [r["content"] for r in rows] == ["the garage door sticks in the cold"]
        assert rows[0]["machine"] == "pi-kitchen", "named by who sent it, as the leader saw it"
        nid = rows[0]["id"]
        assert pool.note_forget(nid)
    loop.run_until_complete(_tick(B))
    loop.run_until_complete(_tick(A))
    with _at(A):
        assert pool.notes_search("garage") == [], "a forget reaches every machine"
    with _at(L):
        assert pool.notes_count() == 0


def test_a_bigger_task_is_split_across_the_members(net):
    L, A, B, loop = net
    _form(L, A, B, loop)

    async def go():
        with _at(L):
            return await L["pool"].hand_out(["count the jars in the pantry", "read the garage thermometer"])
    res = loop.run_until_complete(go())
    assert all(r["ok"] for r in res)
    assert {r["machine"] for r in res} == {"pi-kitchen", "pi-garage"}, "one piece each, at once"
    assert len(A["worked"]) == 1 and len(B["worked"]) == 1
    # a member's own admin can take the consent back: the leader is refused there
    with _at(A):
        A["store"].revoke_grants_for("pool", pool.load()["pool"]["id"])
    res = loop.run_until_complete(go())
    refused = [r for r in res if not r["ok"]]
    assert refused and "no longer takes work" in refused[0]["text"]


def test_only_the_leader_hands_out_work(net):
    L, A, B, loop = net
    _form(L, A, B, loop)

    async def go():
        with _at(A):
            peer = _peer("pi-garage")
            return await teamlink.call(peer, {"op": "pool_work", "task": "wipe the disk"}, timeout=10)
    got = loop.run_until_complete(go())
    assert not got["ok"] and "only this machine's community leader" in got["error"]
    assert B["worked"] == []


def test_when_the_leader_goes_the_next_machine_that_may_lead_takes_over(net):
    L, A, B, loop = net
    with _at(B):
        pool.set_lead_ok(True)          # pi-garage's admin agreed to lead; pi-kitchen did not
    _form(L, A, B, loop)
    loop.run_until_complete(_tick(A))   # rosters now carry B's consent
    loop.run_until_complete(L["lst"].stop())
    L["lst"] = None
    _stale(A)
    r = loop.run_until_complete(_tick(A))
    assert r.get("leader") or r.get("role") == "member", r
    with _at(B):
        d = pool.load()
        assert d["role"] == "leader" and d["term"] == 2, "B promoted itself, after failing to reach L itself"
    with _at(A):
        d = pool.load()
        assert d["leader"]["name"] == "pi-garage" and d["term"] == 2
    assert loop.run_until_complete(_tick(A))["role"] == "member", "A beats the new leader"

    async def ask():
        with _at(A):
            return [ev async for ev in pool.chat(A["cfg"], "default", [{"role": "user", "content": "hi"}], [])]
    assert loop.run_until_complete(ask())[0]["text"].startswith("pi-garage thought"), \
        "now the new leader lends its brain, through its own gate"
    # the old leader comes back on its old port, hears nobody, asks, and steps down
    loop.run_until_complete(_listen(L, port=L["port"]))
    loop.run_until_complete(_tick(L))
    with _at(L):
        d = pool.load()
        assert d["role"] == "member" and d["leader"]["name"] == "pi-garage" and d["term"] == 2
        assert not [g for g in L["store"].list_grants() if g["principal_kind"] == "pool"], \
            "a leader that stepped down keeps no grants for members"


def test_a_machine_whose_admin_did_not_agree_never_leads(net):
    L, A, B, loop = net
    _form(L, A, B, loop)                # nobody but L may lead
    loop.run_until_complete(L["lst"].stop())
    L["lst"] = None
    _stale(A)
    r = loop.run_until_complete(_tick(A))
    assert r["role"] == "member" and not r.get("promoted")
    for m in (A, B):
        with _at(m):
            assert pool.load()["role"] == "member", "no machine took the keys it was not given"


def test_a_claim_from_a_machine_that_may_not_lead_is_refused(net):
    L, A, B, loop = net
    _form(L, A, B, loop)

    async def go():
        with _at(A):
            peer = _peer("pi-garage")
        with _at(B):
            mine = _peer("pi-kitchen")
            return await teamlink.call(mine, {"op": "pool_claim", "term": 99}, timeout=10), peer
    got, _ = loop.run_until_complete(go())
    assert not got["ok"] and "not one this community lets lead" in got["error"]
    with _at(A):
        assert pool.load()["term"] == 1


def test_community_links_carry_community_requests_only(net):
    L, A, B, loop = net
    _form(L, A, B, loop)

    async def go():
        with _at(A):
            peer = _peer("pi-garage")
            return await teamlink.call(peer, {"op": "ask", "to": "analyst", "question": "hi"}, timeout=10)
    got = loop.run_until_complete(go())
    assert not got["ok"] and "community requests only" in got["error"]
    with _at(A):
        assert all(lk["kind"] != "pool" for lk in teamlink.links(None)), "hidden from Linked teams"


def test_the_tools_exist_only_where_there_is_a_community(net, tmp_path):
    from agentos.tools import Toolbox
    L, A, B, loop = net
    names = lambda m: {t["name"] for t in Toolbox(m["cfg"], m["store"]).schemas()}   # noqa: E731
    with _at(A):
        assert not {"community_recall", "pool_task"} & names(A)
    _form(L, A, B, loop)
    with _at(A):
        assert "community_recall" in names(A) and "pool_task" not in names(A), "a member reads, the leader splits"
    with _at(L):
        assert {"community_recall", "pool_task"} <= names(L)
        assert "split a bigger task" in pool.note()
    from agentos import agent
    assert "community_recall" in agent.UNTRUSTED_TOOLS, "another machine's words taint the turn"
    from agentos.tools import SAFE_TOOLS
    assert "pool_task" not in SAFE_TOOLS


def test_a_pool_model_never_waits_on_a_price():
    from agentos import usage
    assert usage.price_state({}, "pool/default") == "pool" and not usage.needs_price({}, "pool/default")


def test_the_leaders_line_is_the_only_bigger_buffer():
    src = (ROOT / "agentos/teamlink.py").read_text()
    h = src[src.index("    async def _handle"):src.index("    async def _dispatch")]
    assert "known = bool(fp and _by_fp(fp))" in h and "POOL_LINE if known else MAX_LINE" in h, \
        "a stranger's first line stays small"
