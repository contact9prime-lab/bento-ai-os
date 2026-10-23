"""Settings has a Permissions tab, and Team & Communications is split between Agents and Network & Teams.

Asked for as "In settings permissions should be added as a separate tab. Team &
Communications should be added as a separate tab with all the options". The Agents page
had grown to hold everything about agents working together, linked teams and the
community of machines, and the permission settings were scattered. Then (2026-10) "agents'
own providers, talk and huddles move to Agents; the rest merges with Network". These pin
where each now lives, and that nothing that pointed at an old place still does.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JS = ROOT / "agentos/ui/src/js"
SETTINGS = (JS / "11-settings.js").read_text()


def _tab(name: str) -> str:
    """The source of one tab's block: from its want() to the next tab's."""
    i = SETTINGS.index(f"if(want('{name}')){{")
    j = SETTINGS.find("if(want('", i + 10)
    return SETTINGS[i:j]


def test_the_tabs_sit_after_agents():
    ids = re.findall(r"^\s+\['(\w+)','[^']*','([^']*)','(\w+)'\],", SETTINGS, re.M)
    order = [i for i, _, _ in ids]
    assert order[:4] == ["ai", "agent", "network", "permissions"], order
    labels = {i: l for i, l, _ in ids}
    assert "team" not in labels and labels["permissions"] == "Permissions"
    assert labels["network"] == "Network & Teams"


def test_every_team_option_has_a_home():
    agent = _tab("agent")
    for piece in ("s-team-own", "s-team-list", "s-team-talk", "s-team-freetalk", "s-team-talklog",
                  "s-team-limits", "s-team-matrix"):
        assert piece in agent, piece
    for kept in ('id="agents-list"', 'id="agents-graph"', "s-hist-compact", "agent-share-box"):
        assert kept in agent, kept
    net = _tab("network")
    for piece in ("s-net", "s-prov", "netPaint", "provPaint", "s-team-links", "s-pool",
                  "openApp(\\'teamchat\\')", "tcRename()"):
        assert piece in net, piece
    for gone in ("s-pool", "s-prov", "s-taint", "s-team-links"):
        assert gone not in agent, f"{gone} on the Agents page"


def test_permissions_holds_the_decisions_and_opens_the_app():
    perm = _tab("permissions")
    for piece in ("s-autonomy", "s-taint", "s-perm-sum", "s-audit-strict", "permVerifyLedger",
                  "permGo(\\'ledger\\')"):
        assert piece in perm, piece
    assert "function permGo" in SETTINGS and "function permSummaryPaint" in SETTINGS
    assert "patch.security.audit_fail_closed" in SETTINGS


def test_nothing_points_at_the_old_place():
    ws = (JS / "09-websocket.js").read_text()
    assert 'data-t="team"' not in ws, "the team tab is gone: its toasts open Network & Teams"
    assert ws.count('data-t="network"') >= 3, "new machines, devices, links and the community open Network"
    for f in JS.glob("*.js"):
        t = f.read_text()
        assert "Agents → Working together" not in t and "Agents → Community" not in t, f.name
        assert "placeSettings('team')" not in t, f.name
    places = (JS / "05b-places.js").read_text()
    for name, tab in (("'Community'", "network"), ("'Free talk'", "agent"), ("'Network'", "network"),
                      ("'New machines'", "network"), ("'Devices without Bento'", "network")):
        line = next(ln for ln in places.splitlines() if ln.strip().startswith("[" + name))
        assert f"placeSettings('{tab}')" in line, name


def test_the_rail_draws_both():
    icons = (JS / "00d-icons.js").read_text()
    assert re.search(r"^\s+team:'M", icons, re.M) and re.search(r"^\s+shield:'M", icons, re.M)
    css = (ROOT / "agentos/ui/src/css/20-immersive.css").read_text()
    assert "[data-t=team] .psi" in css and "[data-t=permissions] .psi" in css
    assert "[data-t=network] .psi" in css and re.search(r"^\s+wifi:'M", icons, re.M)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        yield cl, servermod


def test_the_ledger_switch_saves(client):
    cl, servermod = client
    before = (servermod.state["cfg"].get("security") or {}).get("audit_fail_closed")
    try:
        r = cl.put("/api/config", json={"security": {"audit_fail_closed": True}})
        assert r.status_code == 200, r.text
        assert servermod.state["cfg"]["security"]["audit_fail_closed"] is True
        cl.put("/api/config", json={"security": {"audit_fail_closed": "yes"}})
        assert servermod.state["cfg"]["security"]["audit_fail_closed"] is True, "only a real true/false is taken"
        assert cl.get("/api/audit/verify").json().get("ok") in (True, False)
    finally:
        cl.put("/api/config", json={"security": {"audit_fail_closed": bool(before)}})
