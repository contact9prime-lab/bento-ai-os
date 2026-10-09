"""Settings has a Permissions tab and a Team & Communications tab.

Asked for as "In settings permissions should be added as a separate tab. Team &
Communications should be added as a separate tab with all the options". The Agents page
had grown to hold everything about agents working together, linked teams and the
community of machines, and the permission settings were scattered. These pin where
each now lives, and that nothing that pointed at the old place still does.
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


def test_the_two_tabs_sit_after_agents():
    ids = re.findall(r"^\s+\['(\w+)','[^']*','([^']*)','(\w+)'\],", SETTINGS, re.M)
    order = [i for i, _, _ in ids]
    assert order[:4] == ["ai", "agent", "team", "permissions"], order
    labels = {i: l for i, l, _ in ids}
    assert labels["team"] == "Team & Communications" and labels["permissions"] == "Permissions"


def test_team_and_communications_holds_every_team_option():
    team = _tab("team")
    for piece in ("s-team-own", "s-team-list", "s-team-talk", "s-team-freetalk", "s-team-talklog",
                  "s-team-limits", "s-team-matrix", "s-team-links", "s-pool", "s-prov",
                  "openApp(\\'teamchat\\')", "tcRename()"):
        assert piece in team, piece
    agent = _tab("agent")
    for gone in ("s-team-", "s-pool", "s-prov", "s-taint"):
        assert gone not in agent, f"{gone} still on the Agents page"
    for kept in ('id="agents-list"', 'id="agents-graph"', "s-hist-compact", "agent-share-box"):
        assert kept in agent, kept


def test_permissions_holds_the_decisions_and_opens_the_app():
    perm = _tab("permissions")
    for piece in ("s-autonomy", "s-taint", "s-perm-sum", "s-audit-strict", "permVerifyLedger",
                  "permGo(\\'ledger\\')"):
        assert piece in perm, piece
    assert "function permGo" in SETTINGS and "function permSummaryPaint" in SETTINGS
    assert "patch.security.audit_fail_closed" in SETTINGS


def test_nothing_points_at_the_old_place():
    ws = (JS / "09-websocket.js").read_text()
    assert 'data-t="agent"' not in ws, "the community and machine toasts open the Team tab"
    assert ws.count('data-t="team"') >= 3
    for f in JS.glob("*.js"):
        t = f.read_text()
        assert "Agents → Working together" not in t and "Agents → Community" not in t, f.name
    places = (JS / "05b-places.js").read_text()
    for name in ("'Community'", "'New machines'", "'Devices without Bento'", "'Free talk'"):
        line = next(ln for ln in places.splitlines() if ln.strip().startswith("[" + name))
        assert "placeSettings('team')" in line, name


def test_the_rail_draws_both():
    icons = (JS / "00d-icons.js").read_text()
    assert re.search(r"^\s+team:'M", icons, re.M) and re.search(r"^\s+shield:'M", icons, re.M)
    css = (ROOT / "agentos/ui/src/css/20-immersive.css").read_text()
    assert "[data-t=team] .psi" in css and "[data-t=permissions] .psi" in css


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
