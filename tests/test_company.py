"""Your company: departments of agents, set up from a sentence (agentos/company.py).

What these defend:

- a draft is read field by field through a closed set: departments capped, one head
  each, names unique, tools only from an allow-list (never a shell, a push or a send),
  no blazer (it is your agent's), and everything dropped is NAMED;
- the preview and the save are one computation: the counts on the button are what the
  save makes, an agent or a desk that exists is never overwritten, the desks land OFF
  and hold nothing, and talk cells are written only when ticked;
- mail and calendar tools are given only when those accounts are set up, and the
  preview says who would get them;
- the numbers on a department's card are counts of runs and approvals: a hand-over
  inside a desk run is part of that task, not a task of its own;
- the Office keeps what makes a room a department (head, mandate, desk, titles), and
  the Design panel's save carries it;
- the lead is told how its specialists are organised; the terminal can show, set up
  and hand out work; the page shows every person before saving and asks the server
  to recount after every untick.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import company, office, users                          # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
ALL_MAIL = {"mail": True, "calendar": True}


def _tools():
    from agentos import tools
    return [t["name"] for t in tools.TOOL_SCHEMAS]


def _world(tmp_path, names=()):
    store = Store(tmp_path / "a.db")
    for n in names:
        store.save_subagent({"name": n, "soul": f"the {n} somebody made by hand"})
    return {"agent_name": "Aria"}, store


# ---- the catalogue ----

def test_the_catalogue_gives_only_tools_that_exist_and_are_allowed():
    have = set(_tools())
    for k in company.ORDER:
        d = company.DEPARTMENTS[k]
        assert d["color"] in office.COLORS
        assert sum(p["lead"] for p in d["people"]) == 1, f"{k} has exactly one head"
        assert len(d["people"]) <= company.MAX_PEOPLE
        for p in d["people"]:
            assert set(p["tools"]) <= set(company.ALLOWED_TOOLS), (k, p["name"])
            assert set(p["tools"]) <= have, f"{p['name']} is given a tool this machine does not have"
            assert "blazer" not in p["look"].values()
    for bad in ("run_command", "git_push", "mail_send", "write_file", "configure_agentos",
                "create_subagent", "delegate", "whatsapp_send", "telegram_send"):
        assert bad not in company.ALLOWED_TOOLS, bad
    names = [p["name"] for k in company.ORDER for p in company.DEPARTMENTS[k]["people"]]
    assert len(names) == len(set(names)), "one person, one department"
    # every persona says the honesty rules, and names the company it was made for
    plan = company.template_plan(["finance"], "Bean There", "a coffee subscription")
    soul = plan["departments"][0]["people"][0]["soul"]
    assert soul.startswith("You are the Head of Finance at Bean There (a coffee subscription)")
    assert company._HONEST in soul and "brief_item" in soul


# ---- reading a draft ----

def test_a_draft_is_read_field_by_field_and_what_is_dropped_is_named():
    people = lambda n, **kw: [{"name": f"{n}-{i}", "title": "t", "persona": "You do things.",  # noqa: E731
                               "tools": ["recall", "run_command"], **kw} for i in range(6)]
    raw = {"company": {"name": "Acme\x1b[31m", "about": "makes anvils"},
           "departments": [
               {"id": "finance", "name": "Money", "color": "plaid",
                "people": [{"name": "Finance Lead!", "title": "Head", "lead": True,
                            "persona": "You count.", "tools": ["read_file", "git_push", "mail_send"],
                            "look": {"outfit": "blazer", "glasses": True}},
                           {"name": "second", "title": "Also head", "lead": True, "persona": "x"}]},
               {"id": "made-up", "name": "Kitchen", "people": people("cook")},
               {"id": "sales", "name": "Money", "people": people("dup")},
           ] + [{"id": "admin", "name": f"Dept {i}", "people": people(f"p{i}")[:1]} for i in range(12)]}
    plan, dropped = company.normalize(raw, _tools())
    said = " | ".join(dropped)
    assert plan["company"] == {"name": "Acme[31m", "about": "makes anvils"}
    money = plan["departments"][0]
    assert money["color"] in office.COLORS and money["id"] == "finance"
    head = money["people"][0]
    assert head["name"] == "finance-lead" and head["lead"]
    assert [p["lead"] for p in money["people"]] == [True, False], "exactly one head"
    assert "git_push" not in head["tools"] and "mail_send" not in head["tools"] and "read_file" in head["tools"]
    assert "finance-lead's tools git_push, mail_send" in said
    assert "blazer" in said and head["look"] == {"glasses": True}
    kitchen = plan["departments"][1]
    assert kitchen["id"] == "custom" and len(kitchen["people"]) == company.MAX_PEOPLE
    assert kitchen["people"][0]["lead"], "a department with no head gets its first person"
    assert "department Money (named twice)" in said
    assert len(plan["departments"]) == company.MAX_DEPTS and "at most 10" in said
    assert sum(len(d["people"]) for d in plan["departments"]) <= company.MAX_TOTAL
    # the brain's text, with prose around it, is read the same way
    got, _ = company.read_plan('Sure! {"departments": [{"id": "hr", "people": [{"name": "people-lead", '
                               '"persona": "You hire."}]}]} Hope that helps.', _tools())
    assert got["departments"][0]["name"] == "HR" and got["departments"][0]["people"][0]["lead"]
    assert company.read_plan("no idea", _tools()) == ({}, [])


def test_the_words_pick_departments_when_no_brain_answers():
    names = lambda p: [d["id"] for d in p["departments"]]  # noqa: E731
    assert names(company.from_words("a coffee subscription startup")) == list(company.STARTUP)
    p = company.from_words("a restaurant: kitchen, suppliers and customers, called Paaji's Dhaba")
    assert "supply" in names(p) and "sales" in names(p)
    assert p["company"]["name"] == "Paaji's Dhaba"
    assert names(company.from_words("anything", ids=["legal", "admin"])) == ["admin", "legal"], \
        "the ticked chips win"


# ---- preview and apply ----

def test_preview_and_apply_are_one_computation_and_nothing_is_overwritten(tmp_path):
    cfg, store = _world(tmp_path, names=("engineer",))
    plan, _ = company.normalize(company.template_plan(["finance", "tech"], "Acme", "anvils"), _tools())
    pv = company.preview(cfg, store, plan, ALL_MAIL)
    assert pv["new"] == 5 and pv["existing"] == 1 and pv["desks"] == 2 and pv["fits"]
    assert "join as they are" in " ".join(pv["notes"])
    rep = company.apply(cfg, store, plan, ALL_MAIL)
    assert len(rep["made"]) == pv["new"] and rep["joined"] == ["engineer"]
    assert store.get_subagent("engineer")["soul"] == "the engineer somebody made by hand", \
        "an agent that exists is never rewritten"
    assert "Head of Finance at Acme" in store.get_subagent("finance-lead")["soul"]
    # the departments are the Office's rooms, with their head, mandate, desk and titles
    depts = {d["name"]: d for d in office.current(cfg)["departments"]}
    fin = depts["Finance"]
    assert fin["lead"] == "finance-lead" and fin["desk"] == "finance-desk"
    assert fin["titles"]["bookkeeper"] == "Bookkeeper" and fin["about"]
    assert "engineer" in depts["Tech"]["members"]
    assert cfg["company"]["name"] == "Acme"
    # the desks land OFF and hold nothing: enabling is the act of granting
    desk = store.get_flow("finance-desk")
    assert desk and not desk["enabled"]
    assert [r["subagent"] for r in desk["roster"]][0] == "finance-lead"
    assert not [g for g in store.list_grants() if g.get("source") == "definition"
                and "desk" in str(g.get("source_ref") or "")], "a disabled desk grants nothing"
    # talk cells are ordinary matrix rows, and the heads may ask each other
    cells = {(g["principal_id"], g["resource"]) for g in store.list_grants()
             if g.get("source") == "matrix" and g.get("action") == "agent.message"}
    assert ("finance-lead", "agent:subagent/tech-lead") in cells
    assert ("bookkeeper", "agent:subagent/finance-lead") in cells
    assert ("bookkeeper", "agent:subagent/tech-lead") not in cells, "staff ask their own department"
    assert rep["talk_cells"] == len(cells)
    # a second apply of the same plan makes nothing new and keeps the desks
    again = company.apply(cfg, store, plan, ALL_MAIL)
    assert again["made"] == [] and all(d["status"] == "exists" for d in again["desks"])


def test_no_talk_means_no_cells_and_accounts_decide_mail_tools(tmp_path):
    cfg, store = _world(tmp_path)
    plan, _ = company.normalize(company.template_plan(["admin"], "Acme"), _tools())
    pv = company.preview(cfg, store, plan, {"mail": False, "calendar": False}, talk=False)
    assert pv["talk_pairs"] == 0
    notes = " ".join(pv["notes"])
    assert "would also read your calendar once a calendar account is set up" in notes
    rep = company.apply(cfg, store, plan, {"mail": False, "calendar": False}, talk=False)
    assert rep["talk_cells"] == 0
    assert not [g for g in store.list_grants() if g.get("source") == "matrix"]
    tools = store.get_subagent("scheduler")["tools"]
    tools = tools if isinstance(tools, list) else __import__("json").loads(tools)
    assert "calendar_events" not in tools and "mail_search" not in tools


def test_a_company_that_does_not_fit_the_office_is_refused_in_a_sentence(tmp_path):
    cfg, store = _world(tmp_path, names=("a",))
    office.save(cfg, store, {"departments": [{"name": f"Room {i}", "members": []} for i in range(9)]})
    plan, _ = company.normalize(company.template_plan(["finance", "hr"]), _tools())
    with pytest.raises(ValueError, match="room for 10 departments"):
        company.apply(cfg, store, plan, ALL_MAIL)


# ---- what the departments are doing ----

def _run(store, kind, ref, status, flow="", parent="", task="t", age=0.0, out="said"):
    rid = store.fabric_run_start(kind, ref, task, parent_run=parent, flow=flow)
    if age:
        store.db.execute("UPDATE fabric_runs SET started_at=? WHERE id=?", (time.time() - age, rid))
        store.db.commit()
    if status != "running":
        store.fabric_run_finish(rid, status, output=out)
    return rid


def test_the_cards_count_runs_and_approvals_and_a_hand_over_is_not_a_task(tmp_path):
    cfg, store = _world(tmp_path)
    plan, _ = company.normalize(company.template_plan(["finance", "sales"], "Acme"), _tools())
    company.apply(cfg, store, plan, ALL_MAIL)
    done = _run(store, "flow", "finance-desk", "ok", flow="finance-desk", task="close the month")
    _run(store, "delegate", "bookkeeper", "ok", parent=done)
    _run(store, "delegate", "fin-analyst", "ok", parent=done)
    asked = _run(store, "flow", "finance-desk", "running", flow="finance-desk", task="pay the invoices")
    child = _run(store, "delegate", "bookkeeper", "running", parent=asked)
    _run(store, "delegate", "prospector", "running", task="find leads")          # straight from chat
    _run(store, "delegate", "sales-lead", "error", task="price the deal")
    _run(store, "delegate", "account-manager", "running", task="left over", age=7200)
    _run(store, "delegate", "researcher", "ok", task="not in any department")
    parked = _run(store, "flow", "sales-desk", "running", flow="sales-desk", task="renew the big client")
    store.db.execute("UPDATE fabric_runs SET status='parked' WHERE id=?", (parked,))
    store.db.commit()
    _run(store, "flow", "sales-desk", "interrupted", flow="sales-desk", task="cut off by a restart")
    waiting = [{"id": "ap1", "run_id": child, "flow": "finance-desk"}]
    st = {s["name"]: s for s in company.stats(cfg, store, waiting)}
    assert (st["Finance"]["done"], st["Finance"]["waiting"], st["Finance"]["doing"]) == (1, 1, 0)
    assert (st["Sales"]["doing"], st["Sales"]["failed"]) == (1, 1), "a crash's leftover is not work"
    assert st["Sales"]["waiting"] == 1, "a parked run waits for its answer in the Brief"
    assert st["Finance"]["people"] == 3 and st["Finance"]["lead"] == "finance-lead"
    assert not st["Finance"]["desk_on"] and st["Finance"]["next"] == 0
    b = company.board(cfg, store, waiting)
    tasks = {t["task"]: t for t in b["tasks"]}
    assert set(tasks) == {"close the month", "pay the invoices", "find leads", "price the deal", "left over",
                          "renew the big client", "cut off by a restart"}
    assert tasks["renew the big client"]["status"] == "waiting" and tasks["renew the big client"]["in_brief"]
    assert tasks["cut off by a restart"]["status"] == "stopped", "a restart is not the department failing"
    assert tasks["close the month"]["handoffs"] == 2 and tasks["close the month"]["status"] == "done"
    assert tasks["pay the invoices"]["status"] == "waiting" and tasks["pay the invoices"]["approvals"] == ["ap1"]
    assert tasks["left over"]["status"] == "stale"
    assert b["counts"]["waiting"] == 2 and b["counts"]["failed"] == 1 and b["counts"]["stopped"] == 1
    # the terminal says the same numbers
    txt = company.text(cfg, store, waiting)
    assert "Finance" in txt and "⚠ 1 waiting" in txt and "Acme" in txt
    with pytest.raises(ValueError, match="no department called 'Legal'"):
        company.desk_for(cfg, store, "Legal")
    assert company.desk_for(cfg, store, "finance")["name"] == "finance-desk"


def test_the_lead_is_told_how_the_team_is_organised(tmp_path):
    cfg, store = _world(tmp_path)
    assert company.note(cfg, store) == ""
    plan, _ = company.normalize(company.template_plan(["finance"], "Acme"), _tools())
    company.apply(cfg, store, plan, ALL_MAIL)
    n = company.note(cfg, store)
    assert "YOUR COMPANY (Acme)" in n and "Finance: head finance-lead" in n and "run_flow" in n
    door = company.note(cfg, store, desks=False)
    assert "run_flow" not in door and "Desk:" not in door, "a team door has no run_flow"
    assert "company.note(self.cfg, store)" in (ROOT / "agentos/agent.py").read_text()
    assert "company.note(cfg, store, desks=False)" in (ROOT / "agentos/executors.py").read_text()


def test_the_office_keeps_what_makes_a_room_a_department(tmp_path):
    cfg, store = _world(tmp_path, names=("a", "b"))
    got, _ = office.save(cfg, store, {"departments": [
        {"name": "Ops", "members": ["a", "b"], "lead": "b", "about": "runs\x1b things", "desk": "ops-desk",
         "titles": {"a": "Planner", "b": "Head of Ops", "ghost": "x"}},
        {"name": "Bad", "members": ["ghost"], "lead": "a", "desk": "no spaces allowed"}]})
    ops, bad = got["departments"]
    assert ops["lead"] == "b" and ops["about"] == "runs things" and ops["desk"] == "ops-desk"
    assert ops["titles"] == {"a": "Planner", "b": "Head of Ops"}
    assert "lead" not in bad and "desk" not in bad, "a head must be in the room, a desk must be a flow name"
    room = next(r for r in office.view(cfg, store)["rooms"] if r["name"] == "Ops")
    assert room["lead"] == "b" and room["desk"] == "ops-desk"
    assert office.MAX_DEPTS == 10
    # the Design panel's save keeps them: `...d` first, or renaming took the head away
    assert "return {...d,name:r.querySelector('.of-dn').value" in (JS / "24d-office.js").read_text()


def test_it_is_personal():
    assert "company" in users.USER_KEYS


# ---- the routes ----

def test_the_routes(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        d = cl.get("/api/company").json()
        assert len(d["catalogue"]) == len(company.ORDER) and d["max_departments"] == 10
        assert cl.post("/api/company/draft", json={}).status_code == 400
        r = cl.post("/api/company/draft", json={"departments": ["legal", "admin"]}).json()
        assert r["how"] == "words" and [x["name"] for x in r["plan"]["departments"]] == ["Admin", "Legal"]
        assert r["preview"]["desks"] == 2
        plan = r["plan"]
        plan["departments"][0]["people"] = plan["departments"][0]["people"][:1]
        pv = cl.post("/api/company/preview", json={"plan": plan}).json()["preview"]
        assert pv["new"] == 1 + len(plan["departments"][1]["people"]) - pv["existing"]
        a = cl.post("/api/company/apply", json={"plan": plan, "talk": False}).json()
        assert a["ok"] and a["departments"] == ["Admin", "Legal"] and a["talk_cells"] == 0
        assert {c["name"] for c in a["cards"]} >= {"Admin", "Legal"}
        after = cl.get("/api/company").json()
        assert {x["name"] for x in after["departments"]} >= {"Admin", "Legal"}
        assert cl.post("/api/company/task", json={"department": "Nope", "task": "do it"}).status_code == 400
        assert cl.post("/api/company/task", json={"department": "Admin", "task": ""}).status_code == 400
        audit = cl.get("/api/audit", params={"action": "company.write"})
        if audit.status_code == 200:
            assert "company set up" in audit.text


def test_the_terminal_shows_sets_up_and_says_what_it_needs(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "company", *a], cwd=ROOT,  # noqa: E731
                                    env=env, capture_output=True, text=True, timeout=90)
    r = run()
    assert r.returncode == 0 and "No company set up yet" in r.stdout
    assert "finance-lead (head)" in run("templates").stdout
    r = run("setup", "a tiny design studio called Pixel Pals", "--departments", "admin,marketing",
            "--words", "--yes", "--no-talk")
    assert r.returncode == 0, r.stderr
    assert "filled in from the catalogue, as asked" in r.stdout.lower()
    assert "✓ 2 departments" in r.stdout and "bento company task Admin" in r.stdout
    r = run()
    assert "Pixel Pals" in r.stdout and "Marketing" in r.stdout and "head marketing-lead" in r.stdout
    assert run("setup", "x", "--departments", "kitchen").returncode == 2
    r = run("task", "Admin", "do something")
    assert r.returncode == 1 and "start it with `bento serve`" in r.stdout


# ---- the page ----

def _js(name):
    return (JS / name).read_text()


def test_the_page_shows_everyone_before_saving_and_recounts_after_every_untick():
    src = _js("24g-company.js")
    assert "/api/company/draft" in src and "/api/company/apply" in src
    assert "companyRepreview()" in src and "/api/company/preview" in src, \
        "the button's count comes from the server, the save's own computation"
    assert "Persona and tools" in src and "co-soul" in src, "every persona is shown and editable"
    assert "already here" in src
    assert "companyWindow()" in src and "!OFFICE.w.scene" in src, "the desktop scene cannot be tapped"
    assert "companyReview" in src and "/api/fabric/approvals" in src and "approvalReveal" in src
    office_js = _js("24d-office.js")
    assert "officeCompany(!COMPANY.open)" in office_js and "companyCards();" in office_js
    assert "companySoon()" in office_js, "a run starting or ending recounts the cards"
    assert "p.head?'★ '" in office_js, "a department's head wears a star"
    assert "placeCompany()" in _js("05b-places.js")
    assert "officeCompany(true)" in _js("14b-onboarding.js"), "setup offers a whole company"
    css = (ROOT / "agentos/ui/src/css/23-office.css").read_text()
    assert "body.dev-touch .co-card{min-height:var(--tap)}" in css
    assert ".of-bar .endbtn{flex:none;scroll-snap-align:start}" in css
