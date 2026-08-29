"""The HTTP surface of OpenClaw plugins.

Separate from `test_ocplugins.py` because the questions are different. That file
asks whether the review says the right things; this one asks whether the routes
can be made to skip it — whether install can be reached without the ledger,
whether `force` can be defaulted on, and whether a machine with no OpenClaw
serves a pane of buttons that do nothing.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from fastapi.testclient import TestClient                          # noqa: E402

from agentos import ocplugins as ocp                               # noqa: E402
from agentos import server as servermod                            # noqa: E402
from tests.test_ocplugins import LOUD, QUIET, _fake_openclaw       # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    state = tmp_path / "openclaw-state"
    script = _fake_openclaw(tmp_path, {
        "loud": {"manifest": LOUD, "enabled": False, "source": "git:github.com/acme/loud"},
        "quiet": {"manifest": QUIET, "enabled": False, "source": "clawhub:quiet"},
    }, state)
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state))
    monkeypatch.setattr(ocp, "cli", lambda: str(script))
    with TestClient(servermod.app) as c:
        store = servermod.state["store"]
        for table in ("grants", "quarantine", "audit", "logs"):
            store.db.execute(f"DELETE FROM {table}")
        store.db.commit()
        store.grants_version += 1
        c.db = tmp_path / "fake-openclaw.json"
        yield c


@pytest.fixture()
def no_openclaw(monkeypatch):
    monkeypatch.setattr(ocp, "cli", lambda: "")
    with TestClient(servermod.app) as c:
        yield c


def test_a_machine_without_openclaw_serves_a_sentence_not_a_pane(no_openclaw):
    """`available:false` plus the sentence is the WHOLE answer — the pane renders
    that and nothing else. A list of controls that answer a tap by doing nothing
    is indistinguishable from the OS being broken."""
    d = no_openclaw.get("/api/openclaw/plugins").json()
    assert d["available"] is False and d["plugins"] == []
    assert "not installed" in d["problem"]
    assert no_openclaw.get("/api/openclaw/plugins/search?q=x").json()["available"] is False
    assert no_openclaw.get("/api/openclaw/plugins-doctor").json()["available"] is False


def test_the_list_says_what_is_on_off_and_held(client):
    servermod.state["store"].quarantine_add("ocplugin", "loud", "noisy")
    d = client.get("/api/openclaw/plugins").json()
    by = {p["id"]: p for p in d["plugins"]}
    assert d["available"] is True
    assert by["loud"]["held"] and by["loud"]["held_reason"] == "noisy"
    assert not by["quiet"]["held"] and not by["quiet"]["enabled"]


def test_preview_is_the_consent_screen(client):
    p = client.get("/api/openclaw/plugins/loud").json()
    assert p["security"]["verdict"] == "caution"
    assert p["capabilities"] and p["grants"]
    assert "vouching" in p["source_note"]        # git: is not a trusted source


def test_install_needs_a_spec(client):
    assert client.post("/api/openclaw/plugins/install", json={}).status_code == 400


def test_an_untrusted_source_is_refused_and_says_what_would_change_that(client):
    """`force` is never defaulted: it answers OpenClaw's own provenance question,
    so the refusal has to hand the decision back rather than take it."""
    r = client.post("/api/openclaw/plugins/install",
                    json={"spec": "git:github.com/acme/loud"})
    assert r.status_code == 400
    d = r.json()
    assert d["needs_force"] is True and "vouching" in d["source_note"]

    ok = client.post("/api/openclaw/plugins/install",
                     json={"spec": "git:github.com/acme/loud", "force": True})
    assert ok.status_code == 200 and ok.json()["ok"]


def test_an_install_lands_disabled_and_returns_the_review(client):
    r = client.post("/api/openclaw/plugins/install", json={"spec": "clawhub:quiet"}).json()
    assert r["ok"]
    assert all(not p["enabled"] for p in client.get("/api/openclaw/plugins").json()["plugins"])
    assert r["preview"]["capabilities"]


def test_enabling_writes_grants_and_disabling_takes_them_back(client):
    r = client.post("/api/openclaw/plugins/quiet/enable", json={"enabled": True}).json()
    assert r["ok"] and r["grants"]["added"] >= 2
    live = [g for g in servermod.state["store"].list_grants()
            if g.get("source") == ocp.GRANT_SOURCE]
    assert live and {g["principal_kind"] for g in live} == {"ocplugin"}
    assert json.loads(client.db.read_text())["quiet"]["enabled"] is True

    off = client.post("/api/openclaw/plugins/quiet/enable", json={"enabled": False}).json()
    assert off["ok"] and off["revoked"] >= 2
    assert json.loads(client.db.read_text())["quiet"]["enabled"] is False


def test_every_lifecycle_call_leaves_a_row_in_the_ledger(client):
    """The PDP is the only place an audit row is written, so a lifecycle verb that
    routed around it would be a change to the machine with no record of who made
    it. Reading the list is deliberately not audited — it changes nothing."""
    store = servermod.state["store"]
    before = len(store.db.execute("SELECT 1 FROM audit").fetchall())
    client.get("/api/openclaw/plugins")
    assert len(store.db.execute("SELECT 1 FROM audit").fetchall()) == before

    client.post("/api/openclaw/plugins/quiet/enable", json={"enabled": True})
    rows = store.db.execute(
        "SELECT action, resource FROM audit WHERE action LIKE 'plugin.%'").fetchall()
    assert ("plugin.enable", "ocplugin:quiet") in [(r[0], r[1]) for r in rows]


def test_a_deny_grant_still_refuses_even_from_the_desktop(client):
    """The click answers an `ask` — it does not answer a `deny`. Somebody who has
    written "this machine does not install plugins" in the Permissions app must
    not be able to undo it by pressing the button they left on screen."""
    store = servermod.state["store"]
    store.add_grant("user", "", "plugin.install", "*", effect="deny", source="user")
    store.grants_version += 1
    r = client.post("/api/openclaw/plugins/install", json={"spec": "clawhub:quiet"})
    assert r.status_code == 403, r.text


def test_holding_a_plugin_disables_it_and_revokes_what_it_held(client):
    client.post("/api/openclaw/plugins/quiet/enable", json={"enabled": True})
    r = client.post("/api/openclaw/plugins/quiet/hold", json={"reason": "calling home"}).json()
    assert r["ok"] and r["quarantine_id"]
    assert json.loads(client.db.read_text())["quiet"]["enabled"] is False
    assert not ocp.consented(servermod.state["store"], "quiet")

    again = client.post("/api/openclaw/plugins/quiet/enable", json={"enabled": True}).json()
    assert not again["ok"] and "held" in again["error"]


def test_a_held_plugin_shows_up_in_the_ordinary_quarantine_list(client):
    """One quarantine surface, not two. Somebody looking at this list is already
    worried; a second place to look is how the thing they need gets missed."""
    client.post("/api/openclaw/plugins/quiet/hold", json={"reason": "calling home"})
    rows = client.get("/api/quarantine").json()
    held = [q for q in (rows.get("held") or rows.get("quarantine") or rows.get("rows") or [])
            if q.get("principal_id") == "quiet"]
    assert held and held[0]["principal_kind"] == "ocplugin"


def test_doctor_turns_off_what_no_longer_has_permission(client):
    """The one question nothing else asks: does OpenClaw's enablement still agree
    with what this OS was told to allow?"""
    client.post("/api/openclaw/plugins/quiet/enable", json={"enabled": True})
    ocp.revoke_grants(servermod.state["store"], "quiet")
    d = client.get("/api/openclaw/plugins-doctor").json()
    assert [x["id"] for x in d["agentos"]["disabled"]] == ["quiet"]
    assert json.loads(client.db.read_text())["quiet"]["enabled"] is False


def test_uninstalling_revokes_everything_it_was_granted(client):
    client.post("/api/openclaw/plugins/quiet/enable", json={"enabled": True})
    d = client.delete("/api/openclaw/plugins/quiet").json()
    assert d["ok"] and d["revoked"] >= 2
    assert not ocp.consented(servermod.state["store"], "quiet")
