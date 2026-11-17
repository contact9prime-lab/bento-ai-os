"""A company is addressed by name, the lead decides who does the work, and a mission,
a chat and what is remembered belong to one company.

Asked for in four messages:

- "I should be able to add @company in the chat as well, and that asks the user to switch
  the company. The mission can be company dependent and it will run with that set of the
  agents in the company; we need to check that."
- "If the company is not correct for the question, like I ask a stock market question to
  the kids learning YouTube channel, it can say the context is different, you don't have
  a company, would you like to create a company, and it does that or switches."
- "It is still letting Aria do all the heavy lifting … Aria has to learn to delegate
  unless it is alone, or set up specialised agents if no company is set, or switch
  company or create one; it needs to take that cognitive decision."
- "The context, KB and memory should be company specific, and a generic memory concept
  that helps to move around the agents."

What these defend:

- `@Acme` names a company on every chat surface, after an agent's name and a department
  of the open company; the gate decides `company.switch`, a PERSON is asked whatever the
  autonomy, and what follows the name is answered there;
- the lead's `open_company` and `new_company` are asked every time, are refused to
  everybody but the person's own agent, and are on the forwarded lead's door;
- the lead is told who does the work as ONE decision, near the top, with what this
  machine has: departments, specialists, other companies, or that it is alone;
- a mission made while a company is open is that company's, never takes somebody from
  another company, and runs under its own company's settings while that company is parked;
- a company's memory is its own, what is saved `everywhere` is read in every company,
  and a chat goes with the company it was moved to.
"""
import asyncio
import inspect
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import agent as agentmod, company, executors, fabric, flows, phoneturn, policy, tools, toolscope  # noqa: E402
from agentos.memory import Store                                     # noqa: E402
from agentos.policy import PDP, MAIN, Principal                      # noqa: E402
from agentos.tools import Toolbox                                    # noqa: E402

ROOT = Path(__file__).parent.parent


def _setup(cfg, store, keys, name):
    plan, _ = company.normalize(company.template_plan(list(keys), name),
                                [t["name"] for t in tools.TOOL_SCHEMAS])
    return company.apply(cfg, store, plan, {"mail": True, "calendar": True}, talk=False)


def _two(tmp_path, autonomy="full"):
    """Brightdesk (sales, finance) parked, Kidstube (support) open."""
    cfg = {"agent_name": "Aria", "autonomy": autonomy, "max_steps": 6, "default_model": "",
           "workspace": str(tmp_path), "providers": {}, "port": 8321,
           "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    _setup(cfg, store, ["sales", "finance"], "Brightdesk")
    cfg["company"]["about"] = "sells software to clinics"
    company.create(cfg, store, "Kidstube", "a kids learning YouTube channel", surface="gui")
    _setup(cfg, store, ["support"], "Kidstube")
    tb = Toolbox(cfg, store)
    tb.pdp = PDP(cfg, store)
    seen = []

    async def broadcast(ev):
        seen.append(ev.get("type"))
    tb.broadcast = broadcast
    tb.fabric = fabric.ControlPlane(cfg, store, tb, broadcast)
    return cfg, store, tb, seen


def _open(cfg):
    return next(c for c in company.companies(cfg) if c["active"])["name"]


# ---- '@Company' ------------------------------------------------------------------

def test_a_company_is_addressed_by_its_name(tmp_path):
    cfg, store, _, _ = _two(tmp_path)
    hit = company.parse_company(cfg, "@Brightdesk draft the clinic offer")
    assert hit and hit[0]["name"] == "Brightdesk" and hit[1] == "draft the clinic offer"
    assert company.parse_company(cfg, "@brightdesk")[1] == "", "the name alone opens it"
    assert company.parse_company(cfg, "@Kidstube hello")[0]["active"], "the open one is named too"
    assert company.parse_company(cfg, "@Brightdesks sync") is None, "a word, not a prefix"
    assert company.parse_company(cfg, "Brightdesk, draft it") is None
    # the list `@` suggests names the other companies, never the open one
    names = [c["name"] for c in company.addresses(cfg, store)["companies"]]
    assert names == ["Brightdesk"]


def test_the_person_is_asked_and_a_yes_opens_it(tmp_path):
    cfg, store, tb, seen = _two(tmp_path)          # full autonomy: still asked
    cid = store.create_conversation("chat")
    asked = []

    async def yes(name, args, reason, offer=None):
        asked.append((name, args, policy.needs_person(), offer))
        return True
    got = asyncio.run(fabric.company_turn(tb.fabric, cfg, store, "@Brightdesk find ten clinics",
                                          "gui", yes, cid))
    assert asked and asked[0][0] == "open_company" and asked[0][1] == {"company": "Brightdesk"}
    assert asked[0][2], "a person's decision: autonomy never answers it"
    assert asked[0][3] is None, "and there is nothing to remember"
    assert got == {"reply": "", "rest": "find ten clinics", "company": "Brightdesk",
                   "status": "Brightdesk is open"}
    assert _open(cfg) == "Brightdesk" and "office" in seen
    bright = next(c for c in company.companies(cfg) if c["name"] == "Brightdesk")
    assert store.get_conversation(cid)["space_id"] == bright["space_id"], "the chat went with it"
    rows = [r for r in store.audit_list(limit=50) if r["action"] == "company.switch"]
    assert rows and rows[0]["resource"] == "company:brightdesk", "the gate decided it, and wrote it down"


def test_a_no_changes_nothing_and_sends_nothing(tmp_path):
    cfg, store, tb, _ = _two(tmp_path)

    async def no(name, args, reason, offer=None):
        return False
    got = asyncio.run(fabric.company_turn(tb.fabric, cfg, store, "@Brightdesk find ten clinics",
                                          "gui", no, ""))
    assert _open(cfg) == "Kidstube"
    assert got["rest"] == "" and "wasn't opened" in got["reply"] and "Nothing was sent" in got["reply"]
    # nobody to ask (a schedule, a webhook) is a no
    got = asyncio.run(fabric.company_turn(tb.fabric, cfg, store, "@Brightdesk", "task", None, ""))
    assert _open(cfg) == "Kidstube" and "wasn't opened" in got["reply"]
    # the open company named again asks nobody
    got = asyncio.run(fabric.company_turn(tb.fabric, cfg, store, "@Kidstube", "gui", None, ""))
    assert "already open" in got["reply"]
    assert asyncio.run(fabric.company_turn(tb.fabric, cfg, store, "@nobody hi", "gui", None, "")) is None


def test_a_deny_row_refuses_it_without_asking(tmp_path):
    cfg, store, tb, _ = _two(tmp_path)
    store.add_grant("user", "*", "company.switch", "company:brightdesk", effect="deny")
    asked = []

    async def yes(*a, **k):
        asked.append(a)
        return True
    got = asyncio.run(fabric.company_turn(tb.fabric, cfg, store, "@Brightdesk hi", "gui", yes, ""))
    assert not asked and _open(cfg) == "Kidstube" and got["reply"].startswith("▦ Brightdesk:")


def test_every_chat_surface_reads_the_same_door():
    from agentos import server
    chat = inspect.getsource(server._run_chat)
    phone = inspect.getsource(phoneturn.answer)
    for src in (chat, phone):
        assert "company_turn(" in src
        # an agent's name and a department of the open company are checked first
        assert src.index("parse_department") < src.index("company_turn(")
    assert "parse_department" in chat.split("company_turn(")[1].split("flow_hit = None")[0], \
        "'@Acme @Sales …' reaches that company's department"


# ---- the lead's two tools --------------------------------------------------------

def test_the_two_tools_are_the_persons_every_time():
    assert {"open_company", "new_company"} <= tools.ALWAYS_ASK
    assert {"open_company", "new_company"} <= set(executors.TEAM_TOOLS), "a forwarded lead has them"
    assert {"open_company", "new_company"} <= toolscope.CORE
    assert policy.action_of("open_company", {"company": "Acme"}) == ("company.switch", "company:acme")
    assert policy.action_of("new_company", {"name": "Bhav"}) == ("company.create", "company:bhav")
    for kind in ("app", "subagent", "workflow", "flow", "peer", "team", "pool"):
        rows = policy.BUILTIN_DENY[kind]
        assert ("company.switch", "*") in rows and ("company.create", "*") in rows, kind
    # the surface and the chat are the turn's, never the model's
    src = inspect.getsource(agentmod)
    assert '"_surface": self.surface or "gui", "_conv": self.conversation_id or ""' in src


def test_the_lead_opens_and_starts_a_company_through_the_gate(tmp_path):
    cfg, store, tb, _ = _two(tmp_path)
    cid = store.create_conversation("chat")
    asked = []

    async def approver(name, args, reason, offer=None):
        asked.append((name, policy.needs_person(), offer))
        return True

    async def emit(ev):
        pass
    a = agentmod.Agent(cfg, tb, "", emit, approver, conversation_id=cid, surface="telegram")
    out = asyncio.run(a.call_tool("open_company", {"company": "Brightdesk", "_surface": "gui"}, "c1"))
    assert "[opened] Brightdesk is open" in str(out) and _open(cfg) == "Brightdesk"
    assert asked == [("open_company", "confirmed every time", None)]
    bright = next(c for c in company.companies(cfg) if c["active"])
    assert cfg["spaces"]["active"]["telegram"] == bright["space_id"], "the turn's surface moved, not the model's"
    out = asyncio.run(a.call_tool("new_company", {"name": "Bhav Capital", "about": "trades Indian equities",
                                                  "objective": "steady monthly income"}, "c2"))
    assert "[started] Bhav Capital" in str(out) and _open(cfg) == "Bhav Capital"
    assert len(company.companies(cfg)) == 3 and asked[-1][0] == "new_company"
    assert store.get_conversation(cid)["space_id"] == company.profile(cfg)["space_id"]
    # a specialist asking is refused by the gate, not by a sentence
    sub = agentmod.Agent(cfg, tb, "", emit, approver, principal=Principal("subagent", "sales-lead"))
    out = asyncio.run(sub.call_tool("open_company", {"company": "Kidstube"}, "c3"))
    assert str(out[0]).startswith("[denied]") and _open(cfg) == "Bhav Capital"


def test_a_no_on_the_card_leaves_the_company_open(tmp_path):
    cfg, store, tb, _ = _two(tmp_path)

    async def no(*a, **k):
        return False

    async def emit(ev):
        pass
    a = agentmod.Agent(cfg, tb, "", emit, no)
    out = asyncio.run(a.call_tool("open_company", {"company": "Brightdesk"}, "c1"))
    assert "[denied]" in str(out) and _open(cfg) == "Kidstube"


# ---- who does the work -----------------------------------------------------------

def test_the_lead_decides_who_does_the_work_before_it_starts(tmp_path):
    cfg, store, _, _ = _two(tmp_path)
    note = company.route_note(cfg, store, "mcp__bento__")
    assert "WHO DOES THE WORK" in note and "a lead manages" in note
    order = [note.index(w) for w in ("Whose business is it?", "Does a department do this?",
                                     "Nobody fits", "Only then do it yourself")]
    assert order == sorted(order), "one decision, in order"
    assert "mcp__bento__open_company" in note and "mcp__bento__new_company" in note
    assert "mcp__bento__department_task" in note and "mcp__bento__create_subagent" in note
    assert "Kidstube" in note and "Doing work yourself that one of them is there for is a mistake" in note
    # specialists and no company: hand over or build one; no company step it cannot take
    solo = {"agent_name": "Aria"}
    s2 = Store(tmp_path / "b.db")
    s2.save_subagent({"name": "researcher", "soul": "Finds things out.", "tools": ["fetch_url"]})
    n2 = company.route_note(solo, s2)
    assert "1 specialist (researcher)" in n2 and "delegate" in n2 and "open_company" not in n2
    # alone: the work is the lead's, and a specialist is built when the work repeats
    s3 = Store(tmp_path / "c.db")
    n3 = company.route_note({"agent_name": "Aria"}, s3)
    assert "You work alone" in n3 and "create_subagent" in n3 and "new_company" in n3


def test_both_leads_read_the_decision_near_the_top(tmp_path):
    cfg, store, tb, _ = _two(tmp_path)
    env = executors.Envelope(workspace=str(tmp_path))

    async def emit(ev):
        pass
    token = executors.open_team_door(env, cfg, tb, store, emit, None, conversation_id="c", surface="gui")
    from agentos import mcpbridge
    mcpbridge.close_session(token)        # a door left open is another test's surprise
    ctx = env.context
    assert "WHO DOES THE WORK" in ctx and ctx.index("WHO DOES THE WORK") < ctx.index("FINISH THE JOB")
    assert ctx.index("WHO DOES THE WORK") < ctx.index("YOUR COMPANY")
    assert "WHICH COMPANY THIS IS" in ctx and "Brightdesk: sells software to clinics" in ctx
    assert "You can't set up, switch or remove a company" not in ctx
    src = inspect.getsource(agentmod)
    assert "_company.route_note(self.cfg, store) + _company.note(self.cfg, store)" in src


def test_the_lead_hears_about_the_other_companies_and_what_to_do(tmp_path):
    cfg, store, _, _ = _two(tmp_path)
    n = company.note(cfg, store)
    assert "The open company is Kidstube (a kids learning YouTube channel)" in n
    assert "different context" in n and "open_company" in n and "new_company" in n
    assert "never a reason to switch" in n, "small talk and a quick fact are answered here"
    # a new company with no departments still says where it is
    company.create(cfg, store, "Empty Co")
    assert "WHICH COMPANY THIS IS" in company.note(cfg, store)
    # somebody with no company at all is not pushed towards one
    assert company.others_note({"agent_name": "Aria"}) == ""


# ---- a mission is its company's ---------------------------------------------------

def test_a_mission_made_in_a_company_is_that_companys(tmp_path):
    cfg, store, tb, _ = _two(tmp_path)
    kid = company.profile(cfg)
    mine = next(d for d in company.departments(cfg, store))["members"][0]
    out = asyncio.run(tb.create_flow("weekly-video-ideas", "List five video ideas.", [mine]))
    assert "as a mission of Kidstube" in out, out
    f = store.get_flow("weekly-video-ideas")
    assert f["space_id"] == kid["space_id"] and company.of_flow(cfg, f)["name"] == "Kidstube"
    # nobody from another company goes on its roster, and the sentence says where they work
    out = asyncio.run(tb.create_flow("mixed", "x", [mine, "sales-lead"]))
    assert out.startswith("[error]") and "sales-lead works in Brightdesk" in out
    assert store.get_flow("mixed") is None
    with pytest.raises(ValueError, match="works in Brightdesk"):
        company.place_mission(cfg, store, {"name": "mixed2", "roster": [{"subagent": "sales-lead"}]})
    # a re-save that says nothing about the space keeps the mission in its company
    flows.save(store, {"name": "weekly-video-ideas", "mission": "List six.", "roster": [mine], "enabled": 0})
    assert store.get_flow("weekly-video-ideas")["space_id"] == kid["space_id"]
    # the lead's list says whose each mission is
    listed = asyncio.run(tb.list_flows())
    assert "company: Kidstube" in listed and "company: Brightdesk (not the open one)" in listed


def test_a_parked_companys_mission_runs_with_its_own_people_and_settings(tmp_path):
    cfg, store, tb, _ = _two(tmp_path)
    kid = company.profile(cfg)
    mine = next(d for d in company.departments(cfg, store))["members"][0]
    asyncio.run(tb.create_flow("weekly-video-ideas", "List five video ideas.", [mine]))
    bright = next(c for c in company.companies(cfg) if c["name"] == "Brightdesk")
    company.switch(cfg, store, bright["id"])
    f = store.get_flow("weekly-video-ideas")
    owner = company.of_flow(cfg, f)
    assert owner["name"] == "Kidstube" and not owner["active"]
    # its settings are its own company's while that company is parked: who signs it off,
    # whether it is audited, who may ask whom
    ccfg = company.cfg_for(cfg, f["name"], f["space_id"])
    assert company.profile(ccfg)["name"] == "Kidstube" and company.profile(cfg)["name"] == "Brightdesk"
    assert [r["subagent"] for r in f["roster"]] == [mine], "and its people are that company's"
    assert company.outsiders(cfg, f["roster"], f) == {}
    # the same for a desk and a mission the company's objective made
    assert company.profile(company.cfg_for(cfg, "kidstube-support-desk"))["name"] == "Kidstube"
    src = inspect.getsource(fabric.ControlPlane)
    assert src.count('companymod.cfg_for(self.cfg, flow["name"], flow.get("space_id") or "")') == 2
    # a mission of nobody's company is drafted from this company's people and the free ones
    comp = inspect.getsource(flows.compose)
    assert "_co.elsewhere(cfg, store=store)" in comp and 'not in away' in comp
    assert kid["space_id"]


# ---- memory ----------------------------------------------------------------------

def test_a_companys_memory_is_its_own_and_everywhere_goes_with_you(tmp_path):
    cfg, store, tb, _ = _two(tmp_path)
    kid = company.profile(cfg)["space_id"]
    bright = next(c for c in company.companies(cfg) if c["name"] == "Brightdesk")["space_id"]
    asyncio.run(tb.remember("The channel posts on Tuesdays.", space_id=kid))
    asyncio.run(tb.remember("The person likes short answers.", space_id=kid, everywhere=True))
    here = [m["content"] for m in store.search_memories("", limit=50, scope="user", space=kid)]
    there = [m["content"] for m in store.search_memories("", limit=50, scope="user", space=bright)]
    assert "The channel posts on Tuesdays." in here and "The channel posts on Tuesdays." not in there
    assert "The person likes short answers." in here and "The person likes short answers." in there
    # both leads are told which shelf is which (one reading: agent.memory_text)
    text, _ = asyncio.run(agentmod.memory_text(cfg, store, kid, "", ""))
    assert "Memory of the company Kidstube" in text and "everywhere: true" in text
    assert "never in the person's other companies" in text
    text, _ = asyncio.run(agentmod.memory_text(cfg, store, bright, "", ""))
    assert "Memory of the company Brightdesk" in text
    # a space that is no company's keeps its own words
    sid = store.create_space("Side project")
    text, _ = asyncio.run(agentmod.memory_text(cfg, store, sid, "", ""))
    assert "Current space: Side project" in text


def test_a_chat_held_in_another_company_asks_before_it_carries_on():
    from agentos import server
    src = inspect.getsource(server._run_chat)
    block = src.split("A chat belongs to the company it was held in")[1].split("if text.startswith")[1]
    assert "open_company(" in src and "set_conversation_space" in src
    assert block is not None
