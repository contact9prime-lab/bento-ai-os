"""The hosted share: "it stays with me — take it", as an authenticated MCP door.

Share and fork are two intentions. A fork is a copy the taker owns; a hosted
share is a standing arrangement the OWNER controls — a minted key, a live
export on every take, and two ways to end it (revoke the key, or revoke the
grant in Permissions) that must BOTH actually end it. Most of this file attacks
those claims, because each is the kind that rots silently: a refusal that stops
distinguishing revoked from unknown, a grant revocation the door stops reading,
a poisoned skill the hosted path serves anyway.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import agentbundle as ab                        # noqa: E402
from agentos.memory import Store                             # noqa: E402
from agentos.policy import PDP, Principal                    # noqa: E402


@pytest.fixture()
def store():
    return Store(Path(tempfile.mkdtemp()) / "host.db")


# ---------------------------------------------------------------------------
# Keys: mint, refuse, and the three different refusal sentences
# ---------------------------------------------------------------------------

def test_mint_writes_the_grant_and_the_key(store):
    cfg = {}
    key, err = ab.mint_peer(cfg, store, "laptop-b")
    assert not err and key.startswith("bap_")
    g = [x for x in store.list_grants("peer")]
    assert [(x["principal_id"], x["action"], x["resource"]) for x in g] == \
        [("laptop-b", "agent.share", "agent:bundle")]
    assert ab.peer_for_key(cfg, key) == ("laptop-b", "")


def test_three_refusals_have_three_sentences(store):
    """unknown / revoked / expired call for three different actions, so a vague
    refusal is a bug: 'expired' must never read as a leak to hunt."""
    cfg = {}
    key, _ = ab.mint_peer(cfg, store, "gone")
    ab.revoke_peer(cfg, store, "gone")
    _, revoked = ab.peer_for_key(cfg, key)
    assert "revoked" in revoked and "unknown" not in revoked

    key2, _ = ab.mint_peer(cfg, store, "stale", days=0.00001)
    time.sleep(1.1)
    _, expired = ab.peer_for_key(cfg, key2)
    assert "expired" in expired and "not a leak" in expired

    _, unknown = ab.peer_for_key(cfg, "bap_never-minted-anywhere")
    assert unknown == "unknown key"


def test_revoke_kills_key_and_grant_together(store):
    cfg = {}
    key, _ = ab.mint_peer(cfg, store, "ex")
    assert ab.revoke_peer(cfg, store, "ex")
    assert ab.peer_for_key(cfg, key)[0] == ""
    live = [g for g in store.list_grants("peer") if not g.get("revoked_at")]
    assert live == []
    # and the record survives, so the refusal can say WHY
    assert ab.list_peers(cfg)[0]["revoked"] is True


def test_rotate_keeps_the_arrangement(store):
    cfg = {}
    old, _ = ab.mint_peer(cfg, store, "friend")
    new, err = ab.rotate_peer(cfg, store, "friend")
    assert not err and new != old
    assert ab.peer_for_key(cfg, old)[0] == ""            # the old key is dead
    assert ab.peer_for_key(cfg, new) == ("friend", "")
    live = [g for g in store.list_grants("peer") if not g.get("revoked_at")]
    assert len(live) == 1                                # the grant never moved


def test_duplicate_mint_refused(store):
    cfg = {}
    ab.mint_peer(cfg, store, "twice")
    _, err = ab.mint_peer(cfg, store, "twice")
    assert "already has a live key" in err


# ---------------------------------------------------------------------------
# The peer principal: the grant is the WHOLE reach
# ---------------------------------------------------------------------------

def test_peer_defaults_deny_everything(store):
    """A peer with no grant gets deny — never ask (nobody is at its end to
    answer), and never the autonomy defaults a person gets."""
    pdp = PDP({"autonomy": "full"}, store)
    for action, res in (("agent.share", "agent:bundle"), ("model.use", "model:x"),
                        ("tool.use", "tool:run_command rm"), ("memory.read", "memory:*")):
        d = pdp.decide(Principal("peer", "stranger"), action, res,
                       {"surface": "api", "risk": "safe", "audit": False})
        assert d.effect == "deny", (action, d.effect, d.rule)


def test_minted_grant_allows_exactly_agent_share(store):
    cfg = {}
    ab.mint_peer(cfg, store, "laptop-b")
    pdp = PDP({}, store)
    ok = pdp.decide(Principal("peer", "laptop-b"), "agent.share", "agent:bundle",
                    {"surface": "api", "risk": "risky", "audit": False})
    assert ok.effect == "allow"
    no = pdp.decide(Principal("peer", "laptop-b"), "memory.read", "memory:*",
                    {"surface": "api", "risk": "safe", "audit": False})
    assert no.effect == "deny"


def test_revoking_the_grant_in_permissions_refuses_the_door(store):
    """The Permissions app must be able to end the arrangement — the plugin.run
    lesson: a grant the door does not re-read is a list of things it cannot do."""
    cfg = {}
    key, _ = ab.mint_peer(cfg, store, "laptop-b")
    for g in store.list_grants("peer"):
        store.revoke_grant(g["id"])
    assert ab.peer_for_key(cfg, key) == ("laptop-b", "")   # the key still opens…
    pdp = PDP({}, store)
    d = pdp.decide(Principal("peer", "laptop-b"), "agent.share", "agent:bundle",
                   {"surface": "api", "risk": "risky", "audit": False})
    assert d.effect == "deny"                              # …but the take is refused


# ---------------------------------------------------------------------------
# What a take serves — and refuses
# ---------------------------------------------------------------------------

def test_hosted_build_is_the_export(store):
    store.save_skill("greeting", "", "say hi warmly")
    cfg = {"mcp_servers": {"x": {"transport": "stdio", "command": "npx x",
                                 "env": {"K": "sk-live-SECRETvalue000000"}}}}
    bundle, err = ab.build_hosted(store, cfg)
    assert not err
    assert bundle["checksum"] == ab.bundle_checksum(bundle["manifest"])
    assert "sk-live-SECRET" not in json.dumps(bundle)
    assert bundle["manifest"]["mcp_servers"][0]["env_template"] == {"K": "<YOUR_K>"}


def test_poisoned_skill_refuses_every_take(store):
    """The host's tripwire protects the peer path too: a key pasted into a
    skill refuses the hosted fetch, with the finding named, until removed."""
    store.save_skill("oops", "", "auth with sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA")
    bundle, err = ab.build_hosted(store, {})
    assert bundle == {} and "Anthropic" in err


def test_share_tools_are_exactly_two():
    names = [t["name"] for t in ab.share_tools()]
    assert names == ["agent_card", "fetch_agent"]


# ---------------------------------------------------------------------------
# The door itself, end to end
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """The running server, tables wiped and share state reset per test — the
    test_ocplugins_api pattern, because reloading agentos modules mid-suite
    breaks every later test file that already imported them."""
    from fastapi.testclient import TestClient
    import agentos.server as srv
    with TestClient(srv.app) as c:
        st = srv.state["store"]
        for table in ("grants", "quarantine", "audit", "logs"):
            st.db.execute(f"DELETE FROM {table}")
        st.db.commit()
        st.grants_version += 1
        srv.state["cfg"].pop(ab.SHARE_KEY, None)
        srv._peer_hits.clear()
        from agentos import config as cfgmod
        cfgmod.save_config(srv.state["cfg"])
        yield c
        srv.state["cfg"].pop(ab.SHARE_KEY, None)


def _rpc(client, key, method, params=None, rid=1):
    h = {"Authorization": f"Bearer {key}"} if key else {}
    return client.post("/api/agent/mcp", headers=h,
                       json={"jsonrpc": "2.0", "id": rid, "method": method,
                             "params": params or {}})


def test_door_end_to_end(client):
    key = client.post("/api/agent/peers", json={"name": "laptop-b"}).json()["key"]
    client.put("/api/agent/host", json={"enabled": True})

    r = _rpc(client, key, "initialize")
    assert r.json()["result"]["serverInfo"]["name"] == "bento-agent-share"
    r = _rpc(client, key, "tools/list")
    assert [t["name"] for t in r.json()["result"]["tools"]] == \
        ["agent_card", "fetch_agent"]
    r = _rpc(client, key, "tools/call", {"name": "fetch_agent", "arguments": {}})
    body = r.json()["result"]
    assert not body.get("isError")
    bundle = json.loads(body["content"][0]["text"])
    assert bundle["format"] == ab.FORMAT
    assert bundle["checksum"] == ab.bundle_checksum(bundle["manifest"])
    # and the take is in the ledger, under the peer's own principal
    host = client.get("/api/agent/host").json()
    assert host["peers"][0]["last_fetch"] > 0


def test_door_refusals(client):
    # no key
    assert _rpc(client, "", "initialize").status_code == 401
    # unknown key
    r = _rpc(client, "bap_wrong", "initialize")
    assert r.status_code == 401 and r.json()["error"] == "unknown key"
    # a real key, but hosting is off: the sentence says what would fix it
    key = client.post("/api/agent/peers", json={"name": "early"}).json()["key"]
    r = _rpc(client, key, "initialize")
    assert r.status_code == 404 and "not hosting" in r.json()["error"]
    # revoked: the arrangement ended, and the refusal says so
    client.put("/api/agent/host", json={"enabled": True})
    client.delete("/api/agent/peers/early")
    r = _rpc(client, key, "initialize")
    assert r.status_code == 401 and "revoked" in r.json()["error"]


def test_door_honours_a_permissions_revocation(client):
    """Key alive, grant revoked in Permissions -> the take is refused and the
    refusal points at Permissions, not at the key."""
    key = client.post("/api/agent/peers", json={"name": "laptop-b"}).json()["key"]
    client.put("/api/agent/host", json={"enabled": True})
    grants = client.get("/api/grants").json()
    for g in grants if isinstance(grants, list) else grants.get("grants", []):
        if g.get("principal_kind") == "peer":
            client.delete(f"/api/grants/{g['id']}")
    r = _rpc(client, key, "tools/call", {"name": "fetch_agent", "arguments": {}})
    body = r.json()["result"]
    assert body.get("isError") and "Permissions" in body["content"][0]["text"]


def test_guess_flood_is_held(client):
    for _ in range(65):
        r = _rpc(client, "bap_guess", "initialize")
    assert r.status_code == 429


def test_fetched_bundle_forks_with_zero_grants(client, tmp_path):
    """The whole point, both intentions in one loop: take a HOSTED share and
    fork it — everything disabled, nothing granted, checksum intact."""
    client.post("/api/agent/share", json={})     # ensure export path works at all
    key = client.post("/api/agent/peers", json={"name": "laptop-b"}).json()["key"]
    client.put("/api/agent/host", json={"enabled": True})
    r = _rpc(client, key, "tools/call", {"name": "fetch_agent", "arguments": {}})
    bundle = json.loads(r.json()["result"]["content"][0]["text"])

    dst = Store(tmp_path / "taker.db")
    res = ab.fork(bundle, dst, {}, source="http://peer:8321")
    assert res["ok"] and res["grants_written"] == 0
    assert dst.list_grants() == []


def test_key_minted_by_another_process_opens_the_door(client, tmp_path):
    """The desync that shipped first: `bento agent peers --add` runs in another
    process while the server is up, so the door must answer from DISK — a key
    minted a minute ago works, and (the worse half) one revoked a minute ago
    stops working, without a restart."""
    from agentos import config as cfgmod
    from agentos.memory import Store as _Store

    # mint out-of-band: straight to the config file, as the CLI process would
    cfg = cfgmod.load_config()
    side = _Store(cfgmod.DB_PATH)
    key, err = ab.mint_peer(cfg, side, "cli-minted")
    assert not err
    cfgmod.save_config(cfg)
    client.put("/api/agent/host", json={"enabled": True})

    r = _rpc(client, key, "tools/call", {"name": "fetch_agent", "arguments": {}})
    assert not r.json()["result"].get("isError")

    # and the reverse: revoke out-of-band -> refused now, not at next restart
    cfg = cfgmod.load_config()
    ab.revoke_peer(cfg, side, "cli-minted")
    cfgmod.save_config(cfg)
    r = _rpc(client, key, "initialize")
    assert r.status_code == 401 and "revoked" in r.json()["error"]
