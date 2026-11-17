"""Who may ask whom is decided company by company, over the Default company's.

Asked for as "by default there would be a Default Company (all agents) that defines how every
agent talks to each other, then you can define it at the company level … if A can talk to B in
default but not in the company, and that company is selected, it continues with that permission
(A cannot talk to B) unless the company is switched or the person changes the permission", and
"Democracy … remove it". What these defend:

- a company's own cell decides first while work is in that company's space, either way; an empty
  one falls back to the Default company's; outside every company only the Default company counts;
- a company's own mode (off, matrix, swarm) overrides the Default company's there only;
- the refusal says where and what to do (work in another company, or change the cell);
- a company's cells never touch the Default company's grid, and the other way round;
- Democracy is gone, and a machine that had it asks as before.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import company, fabric, policy, tools                  # noqa: E402
from agentos.memory import Store                                     # noqa: E402
from agentos.policy import PDP, Principal                            # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _world(tmp_path):
    c = {"agent_name": "Aria", "autonomy": "full", "team": {"talk": "matrix"},
         "workspace": str(tmp_path)}
    store = Store(tmp_path / "t.db")
    plan, _ = company.normalize(company.template_plan(["sales", "finance"], "Acme"),
                                [t["name"] for t in tools.TOOL_SCHEMAS])
    company.apply(c, store, plan, {"mail": True, "calendar": True})
    cid = company.ensure_id(c, store, "Acme")
    sid = c["company"]["space_id"]
    d = {x["name"]: x["members"] for x in company.departments(c, store)}
    a, b = d["Sales"][0], d["Finance"][0]
    for x, y in ((a, b), (b, a)):          # the setup may have filled this pair; start empty
        fabric.set_cell(store, x, y, "ask")
    return c, store, cid, sid, a, b


def _ask(pdp, a, b, space=""):
    return pdp.decide(Principal("subagent", a), "agent.message", f"agent:subagent/{b}",
                      {"surface": "gui", "risk": "safe", "space_id": space})


def test_a_company_cell_decides_there_and_only_there(tmp_path):
    c, store, cid, sid, a, b = _world(tmp_path)
    fabric.set_cell(store, a, b, "allow")                     # the Default company: yes
    fabric.set_cell(store, a, b, "deny", company=cid)         # Acme: no
    pdp = PDP(c, store)
    assert _ask(pdp, a, b).effect == "allow", "outside every company the Default company decides"
    d = _ask(pdp, a, b, sid)
    assert d.effect == "deny" and "in Acme" in d.reason and "Working together" in d.reason
    # back to the Default company's inside Acme too
    fabric.set_cell(store, a, b, "ask", company=cid)
    assert _ask(PDP(c, store), a, b, sid).effect == "allow"
    # and a company may open a pair the Default company leaves to ask
    fabric.set_cell(store, b, a, "allow", company=cid)
    assert _ask(PDP(c, store), b, a, sid).effect == "allow"
    assert _ask(PDP(c, store), b, a).effect == "ask"


def test_the_two_grids_never_touch(tmp_path):
    c, store, cid, sid, a, b = _world(tmp_path)
    fabric.set_cell(store, a, b, "deny", company=cid)
    fabric.set_cell(store, a, b, "allow")
    assert fabric.matrix(store, c)["cells"][f"{a}>{b}"] == "allow"
    m = fabric.matrix(store, c, cid)
    assert m["cells"] == {f"{a}>{b}": "deny"} and m["base"][f"{a}>{b}"] == "allow"
    assert set(m["agents"]) <= {s["name"] for s in store.list_subagents()} and a in m["agents"]
    fabric.set_cell(store, a, b, "ask")                       # clearing Default leaves Acme's
    assert fabric.matrix(store, c, cid)["cells"] == {f"{a}>{b}": "deny"}


def test_a_company_mode_overrides_the_default_company_there(tmp_path):
    c, store, cid, sid, a, b = _world(tmp_path)
    company.set_talk(c, cid, "off")
    d = _ask(PDP(c, store), a, b, sid)
    assert d.effect == "deny" and "in Acme" in d.reason
    assert _ask(PDP(c, store), a, b).effect == "ask"
    company.set_talk(c, cid, "swarm")
    assert _ask(PDP(c, store), a, b, sid).effect == "allow"
    company.set_talk(c, cid, "default")
    assert fabric.talk_mode_of(c, cid) == "" and _ask(PDP(c, store), a, b, sid).effect == "ask"
    with pytest.raises(ValueError):
        company.set_talk(c, cid, "democracy")


def test_democracy_is_gone():
    assert policy.TALK_MODES == ("off", "matrix", "swarm")
    assert policy.team_talk({"team": {"talk": "democracy"}}) == "matrix"
    assert not (ROOT / "tests/test_democracy.py").exists()
    for f in ("agentos/policy.py", "agentos/agent.py", "agentos/fabric.py"):
        assert 'rule="democracy"' not in (ROOT / f).read_text()
    assert "'democracy'" not in (JS / "11-settings.js").read_text()


def test_the_routes_and_the_terminal(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        assert cl.get("/api/team/matrix?company=nobody").status_code == 404
        assert cl.put("/api/companies/talk", json={"company": "nobody", "talk": "off"}).status_code == 400
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert 'if a == "talk":' in cli and "/api/companies/talk" in cli
