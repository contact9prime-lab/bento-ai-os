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
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import company, executors, fabric, mcpbridge, policy, toolscope, tools   # noqa: E402
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


def test_the_lead_picks_departments_not_heads(tmp_path):
    """Reported as "they are not delegating the tasks to the most responsible": the
    lead heard every specialist in one flat `delegate` list beside the departments,
    and handed a whole episode to the Studio's head, where the scriptwriter and the
    animator never took part. A department's people are heard only as its people now,
    with their titles and what the department does."""
    c, store, _ = _company(tmp_path)
    store.save_subagent({"name": "loner", "soul": "You do odd jobs."})
    grouped = company.membership(c, store)["of"]
    assert grouped
    team = executors.team_note(store.list_subagents(), in_departments=grouped)
    assert "- loner:" in team and "outside the departments" in team
    assert not any(f"- {m}:" in team for m in grouped)
    # with nobody outside the departments there is no flat list to pick a head from
    solo = executors.team_note([s for s in store.list_subagents() if s["name"] in grouped],
                               in_departments=grouped)
    assert "YOU LEAD A TEAM" not in solo
    n = company.note(c, store)
    d = company.departments(c, store)[0]
    title = (d.get("titles") or {}).get(d["lead"])
    assert title and f"{d['lead']} ({title})" in n
    assert "not even the head" in n and "by what it does" in n
    for src in ("agentos/agent.py", "agentos/executors.py"):
        assert "in_departments=grouped" in (ROOT / src).read_text(), src


def test_a_long_team_names_everyone(tmp_path):
    subs = [{"name": f"a{i}", "soul": "x."} for i in range(23)]
    team = executors.team_note(subs)
    assert "a19:" in team and "also: a20, a21, a22" in team


def test_the_desk_master_splits_work_by_job(tmp_path):
    c, store, tb = _company(tmp_path)
    flow = company.desk_for(c, store, "Sales")
    p = tb.fabric._master_persona(flow)
    assert "whose job" in p and "rather than handing the whole thing to one" in p


def test_the_forwarded_lead_hears_who_does_the_work_first(tmp_path):
    """Measured on the reporting machine: Claude Code was told first that it could not
    use this OS's tools, then given them, with the department rule the last of ~8,000
    characters, and a list naming another company's people. It did the work itself."""
    c, store, tb = _company(tmp_path)
    # a second company, parked, with its own person
    c["companies"] = {"kids": {"company": {"name": "Kids"}, "office": {"departments": [
        {"name": "Studio", "members": ["animator"]}]}}}
    store.save_subagent({"name": "animator", "soul": "You animate."})
    env = executors.envelope_from(c, str(tmp_path), "claude-code")
    env.context = executors.context_for("")
    assert executors.NO_DOOR_LINE in env.context

    async def q(e):
        pass

    async def ap(*a, **k):
        return True
    tok = executors.open_team_door(env, c, tb, store, q, ap, conversation_id="x", text="x")
    try:
        ctx = env.context
        assert executors.NO_DOOR_LINE not in ctx and executors.DOOR_LINE in ctx
        assert ctx.index("YOUR COMPANY") < ctx.index("MISSIONS") < ctx.index("FINDING WHAT")
        assert "- animator:" not in ctx, "another company's people are that company's"
        assert "- auditor:" not in ctx
        argv = executors.build_command("x", env)
        conf = json.loads(argv[argv.index("--mcp-config") + 1])
        assert conf["mcpServers"]["bento"]["timeout"] == executors.BRIDGE_CALL_MS >= 30 * 60 * 1000
    finally:
        mcpbridge.close_session(tok)


def test_a_mission_on_claude_code_waits_for_its_specialists():
    src = (ROOT / "agentos/executors.py").read_text()
    assert src.count('"timeout": BRIDGE_CALL_MS') == 2


def test_the_lead_signs_off_without_tools():
    gate = {"lead": True, "who": "Aria", "department": ""}
    text = company.review_task({"name": "Research"}, gate, "t", "d", "ok", "", [], [], [], [], True)
    assert "no tools in this step" in text


def test_a_verdict_after_a_preamble_is_read_but_never_as_a_pass():
    v, f = company.read_verdict("I've checked the board. Verdict follows.\n\nFAIL\n- Nothing was delivered.")
    assert v == "fail" and f == ["Nothing was delivered."]
    assert company.read_verdict("Checked.\n**CONCERNS**\n- thin data")[0] == "concerns"
    assert company.read_verdict("Checked it all.\nPASS\n- fine")[0] == "", "a pass must lead"
    assert company.read_verdict("PASS\n- fine")[0] == "pass"


def test_a_department_can_run_code_and_a_person_is_asked_each_time(tmp_path):
    """The owner's choice after a live run where Research could only plan: "Python,
    asked each time". The switch changes each person's tools and grants nothing."""
    c, store, tb = _company(tmp_path)
    c["autonomy"] = "full"
    dept = company.departments(c, store)[0]
    got = company.set_code(c, store, dept["name"], True)
    assert got["changed"] and all("run_python" in store.get_subagent(m)["tools"] for m in dept["members"])
    assert company.stats(c, store)[0]["code"] == "all"
    assert not [g for g in store.list_grants() if "run_python" in (g.get("resource") or "")]
    asked, ran = [], []

    async def approver(name, args, reason, offer=None):
        asked.append(name)
        return False

    async def emit(ev):
        pass

    async def fake_cmd(command, **k):
        ran.append(command)
        return "ok"
    tb.run_command = fake_cmd
    from agentos.policy import Principal
    sub = Agent(c, tb, "", emit, approver, principal=Principal("subagent", dept["members"][0]))
    asyncio.run(sub.call_tool("run_python", {"code": "print(1)"}, "c1"))
    assert asked == ["run_python"] and not ran, "full autonomy still asks a person"
    company.set_code(c, store, dept["name"], False)
    assert company.code_state(store, dept["members"]) == "none"
    assert "run_python" in company.ALLOWED_TOOLS and "run_python" in company.KITS["tech"]["tools"]
    assert "run_command" not in company.ALLOWED_TOOLS
    src = (ROOT / "agentos/__main__.py").read_text()
    assert '"/api/company/code"' in src and 'choices=["show"' in src and '"kit", "code"]' in src
    assert "data-code=" in (JS / "24g-company.js").read_text()


def test_python_runs_inside_the_jail(tmp_path):
    """Found live: every run_python failed with "No such file or directory", because the
    server's venv python is under /home and bwrap blanks /home."""
    import shutil
    import pytest
    if not shutil.which("bwrap") or not tools.sandbox_mechanism():
        pytest.skip("no bwrap here")
    ws = tmp_path / "ws"
    ws.mkdir()
    c = {"workspace": str(ws), "sandbox": {"enabled": True}, "autonomy": "full", "providers": {}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    out = asyncio.run(tb.run_python("print(6 * 7)"))
    assert "42" in out, out
    assert not tools.jail_python(sys.executable).startswith("/home/")


def test_the_jail_python_is_never_a_hidden_one(tmp_path):
    fake = tmp_path / "venv-python"
    fake.write_text("")
    assert tools.jail_python(str(fake)) != str(fake) or not str(fake).startswith("/home/")
