"""Permissions and hands at the department level.

Asked for as "build PDP between the departments instead of just the agents, and switch
between the two; the departments can be given executors instead of the agents". What
these defend:

- the switch is the company's (`company.permissions`), and in department mode the gate
  decides an ask between two people of the company by their departments: colleagues
  may ask each other, a department cell decides between departments, an empty cell
  goes to the team's default (ask, swarm or a vote);
- an agent-level block still refuses, so switching the level never reopens a pair a
  person closed; and inside a mission only the mission's own consent counts;
- a department cell is an ordinary grant row (principal `department:<company>/<Dept>`);
- a department's executor is every member's unless the member has one of its own.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import company, hands, office, tools                   # noqa: E402
from agentos.memory import Store                                     # noqa: E402
from agentos.policy import PDP, Principal                            # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _company(tmp_path):
    c = {"agent_name": "Aria", "autonomy": "full", "team": {"talk": "matrix"},
         "workspace": str(tmp_path)}
    store = Store(tmp_path / "t.db")
    plan, _ = company.normalize(company.template_plan(["sales", "finance"], "Acme"),
                                [t["name"] for t in tools.TOOL_SCHEMAS])
    company.apply(c, store, plan, {"mail": True, "calendar": True})
    depts = {d["name"]: d["members"] for d in company.departments(c, store)}
    return c, store, depts


def _ask(pdp, a, b, **ctx):
    return pdp.decide(Principal("subagent", a), "agent.message", f"agent:subagent/{b}",
                      {"surface": "gui", "risk": "safe", **ctx})


def test_agent_mode_is_unchanged(tmp_path):
    c, store, d = _company(tmp_path)
    pdp = PDP(c, store)
    s2, f1 = d["Sales"][1], d["Finance"][0]
    assert company.permission_mode(c) == "agent"
    assert _ask(pdp, s2, f1).effect == "ask", "an empty cell still asks at the agent level"


def test_department_mode_decides_by_department(tmp_path):
    c, store, d = _company(tmp_path)
    pdp = PDP(c, store)
    s1, s2, f1 = d["Sales"][0], d["Sales"][1], d["Finance"][0]
    company.set_permission_mode(c, store, "department")
    dec = _ask(pdp, s1, s2)
    assert dec.effect == "allow" and dec.rule == "department-same"
    assert _ask(pdp, s1, f1).effect == "ask", "an empty department cell asks"
    company.set_dept_cell(c, store, "Sales", "Finance", "allow")
    assert _ask(pdp, s1, f1).effect == "allow"
    assert _ask(pdp, f1, s1).effect == "ask", "a cell has a direction: rows ask, columns answer"
    rows = store.list_grants(principal_kind="department")
    assert rows and rows[0]["principal_id"] == company.dept_key(c, "Sales") \
        and rows[0]["resource"] == "department:Finance"
    company.set_dept_cell(c, store, "Sales", "Finance", "deny")
    assert _ask(pdp, s1, f1).effect == "deny"
    company.set_dept_cell(c, store, "Sales", "Finance", "ask")
    assert not store.list_grants(principal_kind="department")


def test_an_agent_level_block_still_holds(tmp_path):
    from agentos import fabric
    c, store, d = _company(tmp_path)
    pdp = PDP(c, store)
    s1, f1 = d["Sales"][0], d["Finance"][0]
    fabric.set_cell(store, s1, f1, "deny")
    company.set_permission_mode(c, store, "department")
    company.set_dept_cell(c, store, "Sales", "Finance", "allow")
    assert _ask(pdp, s1, f1).effect == "deny"


def test_a_mission_keeps_its_own_consent(tmp_path):
    c, store, d = _company(tmp_path)
    pdp = PDP(c, store)
    s1, s2 = d["Sales"][:2]
    company.set_permission_mode(c, store, "department")
    dec = _ask(pdp, s1, s2, flow="sales-desk")
    assert dec.effect == "deny" and dec.rule == "message-flow"


def test_the_switch_needs_departments(tmp_path):
    store = Store(tmp_path / "t.db")
    with pytest.raises(ValueError):
        company.set_permission_mode({}, store, "department")
    c, store, _ = _company(tmp_path / "b")
    with pytest.raises(ValueError):
        company.set_permission_mode(c, store, "team")
    with pytest.raises(ValueError):
        company.set_dept_cell(c, store, "Sales", "Sales", "allow")
    with pytest.raises(KeyError):
        company.set_dept_cell(c, store, "Sales", "Legal", "allow")


def test_a_department_gives_its_people_their_hands(tmp_path):
    c, store, d = _company(tmp_path)
    s1, s2 = d["Sales"][:2]
    hands.save(store, "research", {"tools": ["fetch_url", "remember"], "folders": [], "web": ["*"], "mcp": []},
               "reads the web, writes nothing")
    assert hands.profile_name(store, c, "subagent", s1) == hands.DEFAULT
    company.set_hands(c, store, "Sales", "research")
    assert any(x.get("hands") == "research" for x in office.current(c)["departments"])
    assert hands.profile_name(store, c, "subagent", s1) == "research"
    # an agent with hands of its own keeps them
    hands.save(store, "locked", {"tools": ["remember"], "folders": [], "web": [], "mcp": []}, "")
    store.db.execute("UPDATE subagents SET profile='locked' WHERE name=?", (s2,))
    store.db.commit()
    assert hands.profile_name(store, c, "subagent", s2) == "locked"
    # the finance people are untouched
    assert hands.profile_name(store, c, "subagent", d["Finance"][0]) == hands.DEFAULT
    company.set_hands(c, store, "Sales", "")
    assert hands.profile_name(store, c, "subagent", s1) == hands.DEFAULT
    with pytest.raises(ValueError):
        company.set_hands(c, store, "Sales", "nonexistent")
    with pytest.raises(KeyError):
        company.set_hands(c, store, "Legal", "research")
    assert any(r.get("action") == "agent.hands" for r in store.audit_list(limit=50))


def test_department_of_reads_parked_companies():
    cfg = {"office": {"departments": [{"name": "Sales", "members": ["nora"]}]},
           "company": {"id": "aa", "permissions": "department"},
           "companies": {"bb": {"company": {"id": "bb"}, "office": {"departments": [
               {"name": "Quality", "members": ["hana"]}]}}}}
    assert office.department_of(cfg, "NORA")[0]["name"] == "Sales"
    d, co = office.department_of(cfg, "hana")
    assert d["name"] == "Quality" and co["id"] == "bb"
    assert office.department_of(cfg, "nobody") is None


def test_every_face_reaches_it():
    src = (ROOT / "agentos/server.py").read_text()
    assert '@app.put("/api/company/permissions")' in src and '@app.put("/api/company/hands")' in src
    assert 'str(b.get("level") or "") == "department"' in src
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert 'if a == "permissions":' in cli and 'if a in ("allow", "block", "ask"):' in cli and 'if a == "hands":' in cli
    s = (JS / "11-settings.js").read_text()
    assert "function paintDeptMatrix(" in s and "level:'department'" in s
    co = (JS / "24g-company.js").read_text()
    assert "data-hands=" in co and "/api/company/hands" in co and "/api/company/permissions" in co
