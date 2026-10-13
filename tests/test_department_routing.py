"""A department is reached by name, from chat and by the lead.

Reported with a screenshot: "Can you check the list of the products that are viral in
the market", Aria on Claude Code running WebSearch herself, and the question "why are
no agents being invoked when I ask Aria?" The company's departments sat idle because
nothing could reach them from a conversation: `@name` matched specialists only, and
the lead was told work "goes to its head" with no tool that did it. Pinned here:

- `@Sales …` (and `@Customer Care`, `@customer-care`, `@CustomerCare`) is a task for
  that department, the longest name wins, and a specialist's name is checked first;
- `department_task` is the lead's tool for the same thing. The gate decides it as
  `agent.invoke` on the desk's flow, and the desk is resolved by the agent loop, never
  taken from the model, so a deny on the desk refuses it;
- the forwarded lead's team door offers it, and the lead is told to use it;
- Chat, Telegram and WhatsApp route `@Department` through one door
  (ControlPlane.department_task), and every composer suggests agents and departments.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import company, executors, fabric, policy, toolscope, tools   # noqa: E402
from agentos.agent import Agent                                          # noqa: E402
from agentos.memory import Store                                         # noqa: E402
from agentos.policy import PDP                                           # noqa: E402
from agentos.tools import Toolbox                                        # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _company(tmp_path, keys=("sales", "finance", "support")):
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321,
         "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    plan, _ = company.normalize(company.template_plan(list(keys), "Acme"),
                                [t["name"] for t in tools.TOOL_SCHEMAS])
    company.apply(c, store, plan, {"mail": True, "calendar": True})
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)

    async def broadcast(ev):
        pass
    tb.fabric = fabric.ControlPlane(c, store, tb, broadcast)
    return c, store, tb


def test_a_department_is_addressed_by_its_name(tmp_path):
    c, store, _ = _company(tmp_path)
    names = [d["name"] for d in company.departments(c, store)]
    assert "Sales" in names and "Finance" in names
    support = next(n for n in names if n not in ("Sales", "Finance"))
    hit = company.parse_department(c, store, "@Sales find ten clinics in Pune")
    assert hit and hit[0]["name"] == "Sales" and hit[1] == "find ten clinics in Pune"
    assert company.parse_department(c, store, "@finance: draft our invoice terms")[0]["name"] == "Finance"
    # a name of two words, however it is typed
    for typed in (support, support.lower().replace(" ", "-"), support.replace(" ", "")):
        h = company.parse_department(c, store, f"@{typed} answer the angry email")
        assert h and h[0]["name"] == support and h[1] == "answer the angry email", typed
    assert company.parse_department(c, store, "@Salesforce sync it") is None, "a word, not a prefix"
    assert company.parse_department(c, store, "@Sales") is None, "an address with no task is not a task"
    assert company.parse_department(c, store, "Sales, find clinics") is None


def test_the_longest_name_wins(tmp_path):
    c, store, _ = _company(tmp_path)
    office = c["office"]
    first = office["departments"][0]
    moved = first["members"][-1]
    first["members"] = first["members"][:-1]
    office["departments"].append({**first, "name": first["name"] + " Ops", "members": [moved],
                                  "lead": moved})
    hit = company.parse_department(c, store, f"@{first['name']} Ops plan the week")
    assert hit[0]["name"] == first["name"] + " Ops" and hit[1] == "plan the week"


def test_addresses_list_people_and_departments(tmp_path):
    c, store, _ = _company(tmp_path)
    a = company.addresses(c, store)
    assert {d["name"] for d in a["departments"]} >= {"Sales", "Finance"}
    assert all(d["head"] and d["people"] >= 1 and d["desk"] for d in a["departments"])
    assert any(x["dept"] == "Finance" for x in a["agents"])
    assert company.AUDITOR not in {x["name"] for x in a["agents"]}


def test_the_lead_hands_work_to_a_department_through_the_gate(tmp_path, monkeypatch):
    c, store, tb = _company(tmp_path)
    ran = []

    async def fake_run_flow(flow, text, origin=None, conversation_id="", **k):
        ran.append((flow["name"], text, origin, conversation_id))
        return {"status": "ok", "content": "Ten clinics, one line each.", "fault": "",
                "delegations": 2, "usage": {}}
    monkeypatch.setattr(tb.fabric, "run_flow", fake_run_flow)

    async def emit(ev):
        pass

    async def approver(*a, **k):
        return True
    lead = Agent(c, tb, "ollama/x", emit, approver, conversation_id="conv-1")
    desk = company.desk_for(c, store, "Sales")["name"]
    # the model names a desk of its own choosing; the loop replaces it with the real one
    out, ok, *_ = asyncio.run(lead.call_tool("department_task", {
        "department": "Sales", "task": "find ten clinics", "_desk": "some-other-flow",
        "_conv": "someone-elses-chat"}))
    assert ok and "Ten clinics" in out and "Sales · ok" in out
    assert ran == [(desk, "find ten clinics", {"surface": "chat", "ref": "Sales"}, "conv-1")]
    rows = store.audit_rows(limit=5) if hasattr(store, "audit_rows") else None
    if rows is not None:
        assert any(r.get("resource") == f"agent:flow/{desk}" for r in rows)
    # a deny on the desk refuses the department, whatever the model says
    store.add_grant("user", "", "agent.invoke", f"agent:flow/{desk}", effect="deny")
    out, ok, *_ = asyncio.run(lead.call_tool("department_task", {
        "department": "Sales", "task": "again", "_desk": "unrelated"}))
    assert out.startswith("[denied]") and len(ran) == 1
    out, ok, *_ = asyncio.run(lead.call_tool("department_task", {"department": "Legal", "task": "x"}))
    assert "no department called 'Legal'" in out


def test_the_action_is_the_desk_the_loop_resolved():
    assert policy.action_of("department_task", {"department": "Sales", "_desk": "sales-desk"}) == \
        ("agent.invoke", "agent:flow/sales-desk")
    assert "department_task" in tools.SAFE_TOOLS and "department_task" in toolscope.CORE
    assert "department_task" in executors.TEAM_TOOLS


def test_the_lead_is_told_to_use_the_departments(tmp_path):
    c, store, tb = _company(tmp_path)
    n = company.note(c, store)
    assert "department_task" in n and "Do not do a department's work yourself" in n
    door = company.note(c, store, desks=False, tool="mcp__bento__department_task")
    assert "mcp__bento__department_task" in door


def test_every_chat_door_routes_a_department():
    src = (ROOT / "agentos/server.py").read_text()
    assert "_companymod.parse_department(cfg, store, text)" in src
    assert "elif dept_hit:" in src and 'state["fabric"].department_task(' in src
    for f in ("telegram.py", "whatsapp.py"):
        s = (ROOT / "agentos" / f).read_text()
        assert "parse_department(self.cfg, self.store, text)" in s and "fabricmod.department_reply(" in s, f
    assert '@app.get("/api/chat/addresses")' in src


def test_a_channel_reply_names_the_department(tmp_path, monkeypatch):
    c, store, tb = _company(tmp_path)

    async def fake_run_flow(flow, text, **k):
        return {"status": "ok", "content": "Invoice terms drafted.", "fault": "", "delegations": 1}
    monkeypatch.setattr(tb.fabric, "run_flow", fake_run_flow)
    said = asyncio.run(fabric.department_reply(tb.fabric, "Finance", "draft terms", "c1", None, "telegram"))
    assert said.startswith("▦ Finance · ok") and "Invoice terms drafted." in said
    said = asyncio.run(fabric.department_reply(tb.fabric, "Legal", "x", "c1", None, "telegram"))
    assert "no department called 'Legal'" in said


def test_every_composer_suggests_agents_and_departments():
    js = (JS / "10d-mentions.js").read_text()
    assert "/api/chat/addresses" in js and "#input,#omni-in,.cp-in" in js
    # while the list is open, Enter picks and does not send
    assert "e.stopImmediatePropagation()" in js and "},true);" in js
    css = (ROOT / "agentos/ui/src/css/09-chat-team-docs.css").read_text()
    assert "min-height:var(--tap,40px)" in css.split(".ats-row{", 1)[1].split("}", 1)[0]
    ws = (JS / "09-websocket.js").read_text()
    assert "department:ev.department||''" in ws and "if(dp)return chatWho(" in ws


def test_a_forwarded_lead_reaches_a_department_through_its_door(tmp_path, monkeypatch):
    from agentos import mcpbridge
    c, store, tb = _company(tmp_path)
    ran = []

    async def fake_run_flow(flow, text, origin=None, conversation_id="", **k):
        ran.append((flow["name"], text, conversation_id))
        return {"status": "ok", "content": "Viral this week: three products.", "fault": "", "delegations": 1}
    monkeypatch.setattr(tb.fabric, "run_flow", fake_run_flow)
    seen = {}

    async def fake_cli(text, env, sink, run):
        seen["context"] = env.context
        token = env.team_mcp[1]
        _, listed = await mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        seen["tools"] = {t["name"] for t in listed["result"]["tools"]}
        _, out = await mcpbridge.handle(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "department_task", "arguments": {"department": "sales", "task": "what is viral in the market"}}})
        seen["out"] = out["result"]["content"][0]["text"]
        await sink({"type": "text_delta", "text": "Sales found three."})
        return run
    monkeypatch.setattr(executors, "run_task", fake_cli)

    async def approver(*a, **k):
        return True
    said, _ = asyncio.run(executors.forward("claude-code", "what is viral in the market", c, str(tmp_path),
                                            team={"toolbox": tb, "store": store, "approver": approver,
                                                  "conversation_id": "c9", "surface": "gui"}))
    assert said == "Sales found three."
    assert "department_task" in seen["tools"]
    assert "mcp__bento__department_task" in seen["context"] and "Do not do a department's work yourself" in seen["context"]
    desk = company.desk_for(c, store, "Sales")["name"]
    assert ran == [(desk, "what is viral in the market", "c9")] and "three products" in seen["out"]


def test_a_parked_companys_people_are_not_suggested(tmp_path):
    c, store, _ = _company(tmp_path)
    store.save_subagent({"name": "zed", "soul": "elsewhere"})
    c["companies"] = {"x1": {"company": {"name": "Other"}, "office": {"departments": [
        {"name": "Ops", "members": ["zed"]}]}}}
    assert "zed" not in {a["name"] for a in company.addresses(c, store)["agents"]}
