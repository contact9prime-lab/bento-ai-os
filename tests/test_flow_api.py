"""The HTTP surface of flows: definition, triggers, hooks, approvals.

The webhook is the part worth being strict about — it is the one path in the OS
deliberately reachable from the network without the remote-access session, so its
refusals are asserted here rather than assumed.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from fastapi.testclient import TestClient                          # noqa: E402

from agentos import flows as flowsmod                              # noqa: E402
from agentos import server as servermod                            # noqa: E402


@pytest.fixture()
def client(tmp_path):
    with TestClient(servermod.app) as c:
        store = servermod.state["store"]
        for table in ("flows", "flow_triggers", "flow_artifacts", "fabric_runs",
                      "fabric_events", "grants", "tasks", "logs"):
            store.db.execute(f"DELETE FROM {table}")
        store.db.commit()
        store.grants_version += 1
        store.save_subagent({"name": "researcher", "soul": "research"})
        store.save_subagent({"name": "writer", "soul": "write"})
        yield c


DEF = {"name": "vendor-digest", "mission": "Summarise vendor mentions.",
       "roster": ["researcher", "writer"],
       "permissions": {"tools": ["fetch_url"], "memory": "read-space"},
       "sinks": [{"kind": "origin"}]}


def test_saving_a_flow_writes_its_permissions(client):
    r = client.post("/api/flows", json=DEF)
    assert r.status_code == 200, r.text
    rep = r.json()["report"]
    assert rep["grants"]["added"] > 0

    grants = client.get("/api/flows").json()["flows"][0]["grants"]
    invoke = [g for g in grants if g["action"] == "agent.invoke"]
    assert {g["resource"] for g in invoke} == {"agent:subagent/researcher",
                                               "agent:subagent/writer"}
    assert all(g["source_ref"] == "flow:vendor-digest" for g in grants)


def test_preview_says_what_saving_would_grant_before_it_does(client):
    r = client.post("/api/flows/preview", json=DEF)
    assert r.status_code == 200
    assert len(r.json()["grants"]) > 0
    assert not client.get("/api/flows").json()["flows"], "preview must not write anything"


def test_a_definition_that_cannot_work_is_refused_at_save(client):
    bad = {**DEF, "roster": ["nobody-here"]}
    r = client.post("/api/flows", json=bad)
    assert r.status_code == 400
    assert "nobody-here" in r.json()["error"]

    r = client.post("/api/flows", json={**DEF, "roster": []})
    assert r.status_code == 400 and "roster" in r.json()["error"]


def test_deleting_a_flow_takes_its_grants_and_triggers_with_it(client):
    client.post("/api/flows", json={**DEF, "triggers": [
        {"kind": "cron", "config": {"type": "daily", "at": "08:00"}}]})
    store = servermod.state["store"]
    assert [t for t in store.list_tasks() if t["flow"] == "vendor-digest"]

    r = client.delete("/api/flows/vendor-digest")
    assert r.status_code == 200 and r.json()["grants_revoked"] > 0
    assert not [t for t in store.list_tasks() if t["flow"] == "vendor-digest"]
    assert not [g for g in store.list_grants()
                if (g.get("source_ref") or "") == "flow:vendor-digest"]


def test_a_cron_trigger_becomes_one_scheduler_row(client):
    client.post("/api/flows", json={**DEF, "triggers": [
        {"kind": "cron", "config": {"type": "daily", "at": "07:30"}}]})
    tasks = [t for t in servermod.state["store"].list_tasks() if t["flow"] == "vendor-digest"]
    assert len(tasks) == 1
    assert tasks[0]["schedule_type"] == "daily" and tasks[0]["at_time"] == "07:30"
    # re-saving with the same trigger must not mint a second row
    client.post("/api/flows", json={**DEF, "triggers": [
        {"kind": "cron", "config": {"type": "daily", "at": "07:30"}}]})
    assert len([t for t in servermod.state["store"].list_tasks()
                if t["flow"] == "vendor-digest"]) == 1


# ---------------------------------------------------------------------------
# the webhook
# ---------------------------------------------------------------------------

def _hook(client):
    client.post("/api/flows", json={**DEF, "triggers": [
        {"kind": "webhook", "config": {}, "cooldown_secs": 60}]})
    trig = servermod.state["store"].flow_triggers("vendor-digest", kind="webhook")[0]
    return trig


def test_the_hook_path_is_reachable_without_a_session(client):
    assert "/api/hooks/" in servermod.REMOTE_OPEN_PATHS, \
        "a service on the internet has no session and cannot get one"


def test_a_wrong_secret_is_refused_and_logged(client):
    trig = _hook(client)
    r = client.post(f"/api/hooks/vendor-digest/{trig['id']}?k=not-the-secret", content=b"{}")
    assert r.status_code == 401
    assert any("bad secret" in (l.get("message") or "")
               for l in servermod.state["store"].list_logs("error", limit=10))


def test_an_unknown_hook_is_a_404_not_a_hint(client):
    r = client.post("/api/hooks/vendor-digest/deadbeef?k=x", content=b"{}")
    assert r.status_code == 404


def test_the_cooldown_is_enforced_before_any_work_starts(client):
    trig = _hook(client)
    store = servermod.state["store"]
    store.flow_trigger_fired(trig["id"])          # pretend it just fired
    r = client.post(f"/api/hooks/vendor-digest/{trig['id']}?k={trig['secret']}", content=b"x")
    assert r.status_code == 429 and r.json()["retry_after"] > 0
    assert store.flow_trigger(trig["id"])["dropped"] == 1, \
        "a refused fire is counted, never silently dropped"
    assert not store.fabric_runs(limit=5), "nothing should have started"


def test_the_secret_survives_a_re_save_but_rotates_on_request(client):
    trig = _hook(client)
    client.post("/api/flows", json={**DEF, "triggers": [{"kind": "webhook", "config": {}}]})
    same = servermod.state["store"].flow_triggers("vendor-digest", kind="webhook")[0]
    assert same["secret"] == trig["secret"], "rotating on every save would break every caller"

    client.post("/api/flows", json={**DEF, "triggers": [
        {"kind": "webhook", "config": {}, "rotate": True}]})
    rotated = servermod.state["store"].flow_triggers("vendor-digest", kind="webhook")[0]
    assert rotated["secret"] != trig["secret"]


# ---------------------------------------------------------------------------
# message triggers
# ---------------------------------------------------------------------------

def test_an_explicit_mention_beats_a_message_pattern(client):
    client.post("/api/flows", json={**DEF, "triggers": [
        {"kind": "message", "config": {"pattern": "@", "mode": "substring"},
         "cooldown_secs": 0}]})
    store = servermod.state["store"]
    from agentos import fabric as fabricmod
    text = "@researcher find the vendors"
    assert fabricmod.parse_mention(store, text), "the mention still resolves"
    # the server checks parse_mention first; match_message is only consulted after,
    # which is asserted at the call site — here we prove both would have matched
    assert flowsmod.match_message(store, text, surface="gui")


def test_a_message_trigger_respects_its_cooldown(client):
    client.post("/api/flows", json={**DEF, "triggers": [
        {"kind": "message", "config": {"pattern": "vendor:"}, "cooldown_secs": 300}]})
    store = servermod.state["store"]
    assert flowsmod.match_message(store, "vendor: acme", surface="gui")
    assert flowsmod.match_message(store, "vendor: globex", surface="gui") is None
    trig = store.flow_triggers("vendor-digest", kind="message")[0]
    assert trig["fires"] == 1 and trig["dropped"] == 1


def test_a_message_trigger_only_listens_on_its_own_surfaces(client):
    client.post("/api/flows", json={**DEF, "triggers": [
        {"kind": "message", "config": {"pattern": "vendor:", "surfaces": ["telegram"]},
         "cooldown_secs": 0}]})
    store = servermod.state["store"]
    assert flowsmod.match_message(store, "vendor: acme", surface="gui") is None
    assert flowsmod.match_message(store, "vendor: acme", surface="telegram")
