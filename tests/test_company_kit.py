"""The kit a new department starts with (company.KITS, recommend, clean_kit, apply_kit).

Asked for as "when I set up a new department it should ask questions and set up the
skills, tools and MCP servers most widely used for that kind of team, even ones I have
not used". What these defend:

- every kit is a closed set: tools from ALLOWED_TOOLS, skills written in KIT_SKILLS,
  servers in KIT_MCP, and every answer of every question leads somewhere real;
- the answers change the proposal (a CRM named is that CRM's server, mail read only
  when said yes), and an answer that is not an option falls back to the default;
- preview and apply are one computation: the kit's tools go to NEW people only, its
  skills are created when ticked and never over a skill of that name, and an untick is
  honoured;
- a server is never installed by a kit: the department remembers it and its card says
  Set it up until one by that name is configured.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import company, office, tools                          # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
TOOLS = [t["name"] for t in tools.TOOL_SCHEMAS]


def test_every_kit_is_a_closed_set():
    assert set(company.KITS) >= set(company.ORDER) | {"custom"}
    for kind, k in company.KITS.items():
        assert set(k["tools"]) <= set(company.ALLOWED_TOOLS) and set(k["tools"]) <= set(TOOLS), kind
        assert set(k["skills"]) <= set(company.KIT_SKILLS), kind
        assert set(k.get("mcp") or []) <= set(company.KIT_MCP), kind
        assert k["questions"], f"{kind} asks nothing"
        for cond, add in (k.get("if") or {}).items():
            q, _, v = cond.partition("=")
            assert any(x["id"] == q and v in {o[0] for o in x["options"]} for x in k["questions"]), cond
            assert set(add.get("tools") or []) <= set(company.ALLOWED_TOOLS), cond
            assert set(add.get("mcp") or []) <= set(company.KIT_MCP), cond
    for sid, s in company.KIT_SKILLS.items():
        assert s["name"] == sid and len(s["description"]) <= 200 and s["content"].strip()
    # a server is one the MCP app sets up (a preset or a sign-in one), or a search in the
    # Store: exactly one of the three, and the first two must really be there
    from agentos import mcp_catalog
    js = (JS / "16-mcp-telegram-logs.js").read_text()
    curated = {e["registry_name"] for e in mcp_catalog.CURATED} if hasattr(mcp_catalog, "CURATED") else \
        set(__import__("re").findall(r'"registry_name": "([^"]+)"', (ROOT / "agentos/mcp_catalog.py").read_text()))
    for m in company.KIT_MCP.values():
        assert sum(bool(m.get(k)) for k in ("preset", "curated", "search")) == 1, m["name"]
        if m.get("preset"):
            assert f"k:'{m['preset']}'" in js, f"{m['name']} is not in the MCP app's catalogue"
        if m.get("curated"):
            assert m["curated"] in curated, f"{m['name']} is not a sign-in server here"


def test_answers_shape_the_kit():
    sales = {"id": "sales", "name": "Sales"}
    r = company.recommend(sales)
    assert r["kind"] == "sales" and r["answers"] == {"crm": "hubspot", "mail": "yes"}
    assert {m["id"] for m in r["mcp"]} >= {"hubspot", "tavily"}
    assert "mail_read" in r["tools"]
    r = company.recommend(sales, {"crm": "pipedrive", "mail": "no"})
    assert "pipedrive" in {m["id"] for m in r["mcp"]} and "hubspot" not in {m["id"] for m in r["mcp"]}
    assert "mail_read" not in r["tools"]
    r = company.recommend(sales, {"crm": "a-crm-nobody-offered"})
    assert r["answers"]["crm"] == "hubspot", "an answer that is not an option is the default"
    assert company.kit_kind({"name": "Customer Care", "about": "answers customers"}) == "support"
    assert company.kit_kind({"name": "Sales & Orders"}) == "sales"
    assert company.kit_kind({"name": "Widgets"}) == "custom"


def test_a_kit_from_outside_is_read_field_by_field():
    kit, dropped = company.clean_kit({"tools": ["fetch_url", "run_command"], "skills": ["first-email", "rm-rf"],
                                      "mcp": ["hubspot", {"id": "evil"}]})
    assert kit == {"tools": ["fetch_url"], "skills": ["first-email"], "mcp": ["hubspot"]}
    assert "tool run_command" in dropped and "skill rm-rf" in dropped and "server evil" in dropped


def _plan(**dept):
    plan, _ = company.normalize({"company": {"name": "Acme"}, "departments": [
        {**company.template_plan(["sales"], "Acme")["departments"][0], **dept}]}, TOOLS)
    return plan


def test_preview_and_apply_are_one_computation(tmp_path):
    cfg, store = {"agent_name": "Aria"}, Store(tmp_path / "a.db")
    store.save_skill("first-email", "mine", "my own first email, do not touch")
    plan = _plan(answers={"crm": "salesforce", "mail": "no"})
    pv = company.preview(cfg, store, plan, {"mail": True, "calendar": True})
    d = pv["departments"][0]
    assert {m["id"] for m in d["kit_offer"]["mcp"]} >= {"salesforce"}
    assert d["kit"]["mcp"] and "lead-qualify" in d["kit"]["skills"]
    assert pv["kit"]["skills"] == 1, "first-email exists, so only lead-qualify is new"
    assert all("kg_add" in p["tools"] for p in d["people"]), "the kit's tools go to the new people"
    # untick a skill and a server: the save makes exactly what is ticked
    plan["departments"][0]["kit"] = {"tools": ["kg_add"], "skills": ["lead-qualify"], "mcp": ["tavily"]}
    plan, _ = company.normalize(plan, TOOLS)
    got = company.apply(cfg, store, plan, {"mail": True, "calendar": True}, talk=False)
    assert got["skills_made"] == ["lead-qualify"]
    assert store.get_skill("first-email")["content"] == "my own first email, do not touch"
    dept = next(x for x in office.current(cfg)["departments"] if x["name"] == "Sales")
    assert dept["kit"] == {"tools": ["kg_add"], "skills": ["lead-qualify"], "mcp": ["tavily"]}
    head = store.get_subagent(dept["members"][0])
    assert "lead-qualify" in head["skills"] and "kg_add" in head["tools"]
    st = company.kit_status({**cfg, "mcp_servers": {"tavily": {}}}, dept["kit"])
    assert st["mcp"] == [{**company.KIT_MCP["tavily"], "id": "tavily", "added": True}]


def test_an_existing_agent_joins_as_it_is(tmp_path):
    cfg, store = {"agent_name": "Aria"}, Store(tmp_path / "a.db")
    plan = _plan()
    first = plan["departments"][0]["people"][0]["name"]
    store.save_subagent({"name": first, "soul": "made by hand", "tools": ["recall"]})
    company.apply(cfg, store, plan, {"mail": True, "calendar": True}, talk=False)
    assert store.get_subagent(first)["tools"] == ["recall"]


def test_a_kit_for_a_department_that_exists(tmp_path):
    cfg, store = {"agent_name": "Aria"}, Store(tmp_path / "a.db")
    company.apply(cfg, store, _plan(kit={}), {"mail": True, "calendar": True}, talk=False)
    members = company.departments(cfg, store)[0]["members"]
    got = company.apply_kit(cfg, store, "sales", {"tools": ["fetch_url", "run_command"],
                                                  "skills": ["first-email"], "mcp": ["hubspot"]})
    assert got["dropped"] == ["tool run_command"] and set(got["agents"]) <= set(members)
    for m in members:
        a = store.get_subagent(m)
        assert "first-email" in a["skills"] and "run_command" not in a["tools"]
    assert got["kit"]["mcp"][0]["added"] is False
    assert any(r.get("action") == "company.kit" for r in store.audit_list(limit=20))


def test_every_face_reaches_it():
    src = (ROOT / "agentos/server.py").read_text()
    assert '@app.post("/api/company/kit/offer")' in src and '@app.post("/api/company/kit")' in src
    assert 'if a == "kit":' in (ROOT / "agentos/__main__.py").read_text()
    co = (JS / "24g-company.js").read_text()
    for fn in ("function companyKitBlock(", "function companyKitHTML(", "function companyKitOpen(",
               "function companyKitPaint(", "function companyKitSetUp("):
        assert fn in co, fn
    # a server is set up in the MCP app or found in the Store, never installed by the kit
    assert "mcpPreset(preset)" in co and "storeDiscover(q)" in co
