"""A company's objective, the work it calls for, and several companies (agentos/company.py).

Asked for as: "when I'm building the company there has to be an objective, defined by
the user, and it would require missions, schedules and tasks … it should all open up when
the companies are defined. Also that user may have different offices … a complete
different setup altogether within the same user: a services company and a manufacturing
company."

What these defend:

- the drafted work is read field by field: a piece for a department that is not there,
  a schedule that is not daily or weekly, a time that is not a time, is dropped or
  corrected and NAMED;
- the work's preview and its save are one computation, every mission lands OFF (its
  schedule declared, nothing armed), a mission that exists is kept, and tasks wait as
  to-dos until somebody starts one;
- a mission is its department's work: the board counts it and the auditor and the
  review chain find its department;
- several companies are apart: each its own office, look, desks and missions (named for
  it), space and people, a person in one is never drafted into another, the open floor
  leaves them out, and switching moves only the surface that asked;
- a parked company's mission is signed off by its own bosses (`cfg_for`);
- the lead is told the objective; the routes, the terminal and the page all reach it.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import company, office, users                          # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
CSS = ROOT / "agentos/ui/src/css/23-office.css"
GOAL = "Sign ten new clinic clients this quarter"


def _tools():
    from agentos import tools
    return [t["name"] for t in tools.TOOL_SCHEMAS]


def _world(tmp_path):
    return {"agent_name": "Aria"}, Store(tmp_path / "a.db")


def _setup(cfg, store, ids, name, goal=GOAL, words=None):
    raw = company.from_words(words or name, ids)
    raw["company"].update(name=name, objective=goal)
    if goal:
        raw["work"] = company.work_from_words(goal, raw["departments"])
    plan, _ = company.normalize(raw, _tools())
    return company.apply(cfg, store, plan, {"mail": True, "calendar": True}, talk=False)


# ---- the work, read through the closed set ----

def test_the_work_is_read_field_by_field_and_what_is_dropped_is_named():
    work, dropped = company.normalize_work({
        "missions": [
            {"department": "sales", "title": "Clinic pipeline", "what": "Find five clinics a day.",
             "every": "every day", "at": "8.30"},
            {"department": "Kitchen", "title": "Soup", "what": "Make soup.", "every": "daily"},
            {"department": "Sales", "title": "Clinic pipeline", "what": "again"},
            {"department": "Sales", "title": "Hourly", "what": "x", "every": "hourly"},
            {"department": "Sales", "title": "Bad time", "what": "x", "every": "daily", "at": "25:99"},
            {"department": "Sales", "title": "Bad day", "what": "x", "every": "weekly", "day": "funday"},
            {"department": "Sales", "title": "Nothing"}],
        "tasks": [{"department": "Sales", "text": "List twenty clinics."},
                  {"department": "Moon", "text": "Fly."}, {"department": "Sales", "text": ""}]},
        ["Sales", "Delivery"])
    said = " | ".join(dropped)
    ms = {m["title"]: m for m in work["missions"]}
    assert ms["Clinic pipeline"]["department"] == "Sales" and ms["Clinic pipeline"]["every"] == "daily"
    assert ms["Clinic pipeline"]["at"] == "08:30"
    assert ms["Hourly"]["every"] == "" and "'hourly'" in said, "an unknown schedule starts by hand, and says so"
    assert ms["Bad time"]["at"] == "08:00" and "25:99" in said
    assert ms["Bad day"]["day"] == 4 and "funday" in said
    assert "Soup" not in ms and "Kitchen" in said
    assert "named twice" in said and "Nothing" in said
    assert [t["text"] for t in work["tasks"]] == ["List twenty clinics."] and "Moon" in said
    big, dropped = company.normalize_work(
        {"missions": [{"department": "Sales", "title": f"m{i}", "what": "x"} for i in range(20)],
         "tasks": [{"department": "Sales", "text": f"t{i}"} for i in range(20)]}, ["Sales"])
    assert len(big["missions"]) == company.MAX_MISSIONS and len(big["tasks"]) == company.MAX_TODO
    assert any("at most" in d for d in dropped)


def test_with_no_brain_the_catalogue_drafts_work_pointed_at_the_objective():
    plan = company.from_words("x", ["sales", "production", "quality"])
    plan["departments"].append({"name": "Research", "people": [{"name": "r", "lead": True}]})
    work = company.work_from_words("Cut defects in half", plan["departments"])
    by = {m["department"]: m for m in work["missions"]}
    assert set(by) == {"Sales", "Production", "Quality", "Research"}
    assert all("Cut defects in half" in m["what"] for m in work["missions"])
    assert by["Sales"]["every"] == "daily" and by["Quality"]["every"] == "weekly"
    assert by["Research"]["title"] == "Research progress"
    assert {t["department"] for t in work["tasks"]} == {"Sales", "Production", "Quality"}
    # the catalogue has rooms a maker and a services firm need
    for k in ("production", "quality", "delivery"):
        assert k in company.ORDER and company.DEPARTMENTS[k]["people"][0]["lead"]


def test_the_brain_is_asked_for_the_work_and_its_answer_is_read_strictly():
    system, prompt = company.design_prompt("a clinic consultancy", _tools(), GOAL)
    assert GOAL in prompt and '"work"' in prompt and "missions" in prompt
    assert '"work"' not in company.design_prompt("a clinic consultancy", _tools())[1]
    s, p = company.work_prompt({"name": "Brightdesk"}, GOAL, [{"name": "Sales", "about": "sells"}])
    assert "ONE JSON object" in s and GOAL in p and "Sales" in p
    w, _ = company.read_work('{"missions":[{"department":"Sales","title":"A","what":"b"}]}', ["Sales"])
    assert w["missions"][0]["title"] == "A"
    assert company.read_work("sure! here you go", ["Sales"]) == ({"missions": [], "tasks": []}, [])


# ---- preview and save, one computation ----

def test_the_work_is_made_off_as_shown_and_kept_when_it_exists(tmp_path):
    from agentos import flows
    cfg, store = _world(tmp_path)
    rep = _setup(cfg, store, ["sales", "delivery"], "Brightdesk")
    w = rep["work"]
    assert len(w["missions"]) == 2 and w["tasks"] == 2 and w["scheduled"] == 2 and not w["errors"]
    assert company.objective(cfg) == GOAL and company.profile(cfg)["objective"] == GOAL
    for name in w["missions"]:
        f = store.get_flow(name)
        assert f["enabled"] == 0, "a mission lands off: switching it on is the act of granting"
        trig = store.flow_triggers(name)
        assert trig and trig[0]["kind"] == "cron"
        assert not [t for t in store.list_tasks() if t.get("name", "").startswith(name)], \
            "nothing is armed while it is off"
        assert GOAL in f["mission"]
    sales = store.get_flow("sales-pipeline")
    assert {r["subagent"] for r in sales["roster"]} == set(
        next(d for d in company.departments(cfg, store) if d["name"] == "Sales")["members"])
    # preview and save agree, and a second go keeps what is there
    again = company.work_from_words(GOAL, [{"name": "Sales"}, {"name": "Delivery"}])
    pv = company.preview_work(cfg, store, again)
    assert {m["status"] for m in pv["missions"]} == {"exists"} and pv["new_missions"] == 0
    store.db.execute("UPDATE flows SET mission='mine now' WHERE name='sales-pipeline'")
    store.db.commit()
    r2 = company.apply_work(cfg, store, again)
    assert r2["missions"] == [] and set(r2["kept"]) == set(w["missions"])
    assert store.get_flow("sales-pipeline")["mission"] == "mine now", "never replaced"
    assert r2["tasks"] == 0, "the same to-do is not added twice"
    on, _ = flows.set_enabled(store, "sales-pipeline", True)
    assert on["enabled"] == 1


def test_a_task_waits_on_the_board_until_it_is_started(tmp_path):
    cfg, store = _world(tmp_path)
    _setup(cfg, store, ["sales"], "Brightdesk")
    b = company.board(cfg, store)
    todo = [t for t in b["tasks"] if t["status"] == "todo"]
    assert len(todo) == b["counts"]["todo"] == 1 and todo[0]["department"] == "Sales"
    tid = todo[0]["todo"]
    assert company.take_todo(cfg, tid)["text"]
    company.mark_todo(cfg, tid, "run-1")
    assert company.todo(cfg) == [] and company.board(cfg, store)["counts"]["todo"] == 0
    with pytest.raises(ValueError):
        company.take_todo(cfg, tid)


def test_a_mission_is_its_departments_work(tmp_path):
    cfg, store = _world(tmp_path)
    _setup(cfg, store, ["sales"], "Brightdesk")
    assert company.audit_scope(cfg, store, "sales-pipeline")["name"] == "Sales"
    rid = store.fabric_run_start("flow", "sales-pipeline", "", flow="sales-pipeline")
    store.fabric_run_finish(rid, "ok", output="five clinics found")
    rows = company.board(cfg, store)["tasks"]
    row = next(r for r in rows if r.get("run_id") == rid)
    assert row["department"] == "Sales" and row["task"] == "Sales pipeline"
    card = next(s for s in company.stats(cfg, store) if s["name"] == "Sales")
    assert card["done"] == 1 and card["missions"][0]["flow"] == "sales-pipeline"
    assert card["missions"][0]["on"] is False


# ---- several companies ----

def test_two_companies_are_two_setups(tmp_path):
    cfg, store = _world(tmp_path)
    _setup(cfg, store, ["sales", "finance"], "Brightdesk")
    first = company.profile(cfg)
    assert company.companies(cfg)[0]["name"] == "Brightdesk" and not first["space_id"]
    made = company.create(cfg, store, "Forgeline", "a metal parts maker", "Cut defects in half",
                          surface="gui")
    rows = company.companies(cfg)
    assert [c["name"] for c in rows] == ["Forgeline", "Brightdesk"] and rows[0]["active"]
    bright = rows[1]
    assert bright["id"] and bright["space_id"] and bright["space_id"] != made["space_id"]
    # the first company's desks and missions moved into its own space
    assert store.get_flow("sales-desk")["space_id"] == bright["space_id"]
    assert store.get_flow("sales-pipeline")["space_id"] == bright["space_id"]
    # the new one is empty, in its own look, and its objective carries
    assert company.departments(cfg, store) == [] and company.objective(cfg) == "Cut defects in half"
    assert office.current(cfg)["style"] != rows[1]["style"]
    assert cfg["spaces"]["active"]["gui"] == made["space_id"]
    # the same catalogue department makes new people, desks and missions named for it
    rep = _setup(cfg, store, ["sales", "production"], "Forgeline", "Cut defects in half")
    assert not rep["joined"], "nobody from Brightdesk is drafted into Forgeline"
    assert "sales-lead-forgeline" in rep["made"]
    assert {d["desk"] for d in company.departments(cfg, store)} == {"forgeline-sales-desk",
                                                                   "forgeline-production-desk"}
    assert "forgeline-sales-pipeline" in rep["work"]["missions"]
    assert store.get_flow("forgeline-sales-desk")["space_id"] == made["space_id"]
    assert store.get_flow("sales-desk")["roster"][0]["subagent"] == "sales-lead", "untouched"
    # each office shows its own people; the other company's are not on this floor
    v = office.view(cfg, store)
    seen = {m for r in v["rooms"] for m in r["members"]}
    assert "sales-lead" not in seen and "sales-lead" not in v["agents"]
    assert "sales-lead-forgeline" in seen


def test_switching_brings_a_company_back_whole(tmp_path):
    cfg, store = _world(tmp_path)
    _setup(cfg, store, ["sales"], "Brightdesk")
    cfg.setdefault("spaces", {})["active"] = {"telegram": "phone-stays"}
    company.create(cfg, store, "Forgeline", surface="gui")
    _setup(cfg, store, ["production"], "Forgeline", "")
    bright = next(c for c in company.companies(cfg) if c["name"] == "Brightdesk")
    company.switch(cfg, store, bright["id"], surface="gui")
    assert company.profile(cfg)["name"] == "Brightdesk" and company.objective(cfg) == GOAL
    assert [d["name"] for d in company.departments(cfg, store)] == ["Sales"]
    assert cfg["spaces"]["active"]["gui"] == bright["space_id"]
    assert cfg["spaces"]["active"]["telegram"] == "phone-stays", "a phone keeps its own space"
    assert len(company.todo(cfg)) == 1, "its to-dos came back with it"
    # a parked company's mission is signed off by its own bosses
    forge = next(c for c in company.companies(cfg) if c["name"] == "Forgeline")
    assert not forge["active"]
    view = company.cfg_for(cfg, "forgeline-production-desk")
    assert company.profile(view)["name"] == "Forgeline"
    assert company.audit_scope(view, store, "forgeline-production-desk")["name"] == "Production"
    assert company.cfg_for(cfg, "sales-desk") is cfg and company.cfg_for(cfg, "nobodys") is cfg
    with pytest.raises(ValueError):
        company.switch(cfg, store, "00000000")


def test_a_company_is_named_once_capped_and_removed_with_its_missions_off(tmp_path):
    from agentos import flows
    cfg, store = _world(tmp_path)
    _setup(cfg, store, ["sales"], "Brightdesk")
    with pytest.raises(ValueError):
        company.create(cfg, store, "brightdesk")
    with pytest.raises(ValueError):
        company.create(cfg, store, "  ")
    company.create(cfg, store, "Forgeline")
    bright = next(c for c in company.companies(cfg) if c["name"] == "Brightdesk")
    with pytest.raises(ValueError):
        company.remove(cfg, store, company.profile(cfg)["id"])      # the open one
    company.switch(cfg, store, bright["id"])
    flows.set_enabled(store, "sales-pipeline", True)
    company.switch(cfg, store, next(c["id"] for c in company.companies(cfg) if c["name"] == "Forgeline"))
    rep = company.remove(cfg, store, bright["id"])
    assert "sales-pipeline" in rep["switched_off"] and not store.get_flow("sales-pipeline")["enabled"]
    assert store.get_subagent("sales-lead"), "its agents stay"
    assert [c["name"] for c in company.companies(cfg)] == ["Forgeline"]
    for i in range(company.MAX_COMPANIES - 1):
        company.create(cfg, store, f"Co {i}")
    with pytest.raises(ValueError):
        company.create(cfg, store, "One too many")


def test_the_lead_hears_the_objective_and_the_other_companies(tmp_path):
    cfg, store = _world(tmp_path)
    _setup(cfg, store, ["sales"], "Brightdesk")
    assert GOAL in company.note(cfg, store)
    company.create(cfg, store, "Forgeline")
    _setup(cfg, store, ["production"], "Forgeline", "Cut defects in half")
    n = company.note(cfg, store)
    assert "Cut defects in half" in n and "Brightdesk" in n and GOAL not in n


def test_it_is_personal_and_the_control_plane_asks_whose_flow_it_is():
    assert "companies" in users.USER_KEYS
    src = (ROOT / "agentos/fabric.py").read_text()
    assert src.count("companymod.cfg_for(self.cfg, flow[\"name\"])") == 2, \
        "the review chain and the auditor both read the flow's own company"


# ---- the routes ----

def test_the_routes(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    import copy
    from agentos import config as cfgmod
    with TestClient(servermod.app) as cl:
        cfg = servermod.state["cfg"]
        keep = {k: copy.deepcopy(cfg.get(k)) for k in ("company", "office", "companies", "spaces")}
        r = cl.post("/api/companies", json={"name": "Forge Test Co", "about": "makes parts",
                                            "objective": "Cut defects in half"}).json()
        assert r["ok"] and r["company"]["active"] and r["company"]["space_id"]
        try:
            d = cl.get("/api/company").json()
            assert d["company"]["objective"] == "Cut defects in half" and d["departments"] == []
            assert cl.post("/api/company/work/draft", json={}).status_code == 400   # no departments
            dr = cl.post("/api/company/draft", json={"departments": ["production", "quality"]}).json()
            assert dr["plan"]["company"]["objective"] == "Cut defects in half", "the new company's objective carries"
            assert dr["preview"]["work"]["new_missions"] == 2
            a = cl.post("/api/company/apply", json={"plan": dr["plan"], "talk": False}).json()
            assert a["ok"] and len(a["work"]["missions"]) == 2 and a["work"]["tasks"] == 2
            wd = cl.post("/api/company/work/draft", json={"objective": "Ship on time"}).json()
            assert wd["how"] == "words" and wd["preview"]["missions"]
            # the catalogue drafts the same missions for any objective: they are kept, not replaced
            assert {m["status"] for m in wd["preview"]["missions"]} == {"exists"}
            pv = cl.post("/api/company/work/preview", json={"work": wd["work"], "objective": "Ship on time"}).json()
            assert pv["preview"]["new_missions"] == wd["preview"]["new_missions"] == 0
            assert cl.post("/api/company/work/apply", json={"work": {}}).status_code == 400
            ap = cl.post("/api/company/work/apply", json={"work": wd["work"], "objective": "Ship on time"}).json()
            assert ap["ok"] and ap["missions"] == [] and ap["company"]["objective"] == "Ship on time"
            board = cl.get("/api/company").json()["board"]
            tid = next(t["todo"] for t in board["tasks"] if t["status"] == "todo")
            assert cl.delete(f"/api/company/todo/{tid}").json()["ok"]
            assert cl.delete(f"/api/company/todo/{tid}").status_code == 404
            assert cl.post("/api/company/todo/nope/start", json={}).status_code == 400
            assert cl.put("/api/companies/active", json={"id": "nope"}).status_code == 404
            assert cl.get("/api/companies").json()["companies"][0]["about"] == "makes parts", \
                "setting it up from ticked departments keeps the line it was started with"
        finally:
            # leave the shared test home as it was for the files that run after this one
            for k, v in keep.items():
                if v is None:
                    cfg.pop(k, None)
                else:
                    cfg[k] = v
            cfgmod.save_config(cfg)


def test_the_terminal(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "company", *a], cwd=ROOT,  # noqa: E731
                                    env=env, capture_output=True, text=True, timeout=90)
    r = run("setup", "a clinic consultancy called Brightdesk", "--departments", "sales,delivery",
            "--objective", GOAL, "--words", "--yes", "--no-talk")
    assert r.returncode == 0, r.stderr
    assert "Objective: " + GOAL in r.stdout and "Missions (each starts off" in r.stdout
    assert "Sales pipeline" in r.stdout and "every day at 08:30" in r.stdout
    t = run("todo")
    assert "Sales" in t.stdout and "bento company start ID" in t.stdout
    r = run("new", "Forgeline", "--objective", "Cut defects in half")
    assert r.returncode == 0 and "Forgeline is open" in r.stdout
    r = run("setup", "a machine shop", "--departments", "production", "--words", "--yes", "--no-talk")
    assert "Cut defects in half" in r.stdout, "the objective given at `new` carries into setup"
    c = run("companies").stdout
    assert "▸ Forgeline" in c and "Brightdesk" in c
    assert run("open", "Brightdesk").returncode == 0
    assert "▸ Brightdesk" in run("companies").stdout
    assert run("open", "Nowhere").returncode == 1
    r = run("start", "abcd1234")
    assert r.returncode == 1 and "bento serve" in r.stdout
    r = run("drop", "Forgeline", "--yes")
    assert r.returncode == 0 and "off your list" in r.stdout


# ---- the page ----

def test_the_page_shows_all_of_it_before_making_it_and_switches_through_the_server():
    js = (JS / "24g-company.js").read_text()
    assert "objective:goal" in js and "/api/company/work/draft" in js and "/api/company/work/apply" in js
    assert "/api/companies/active" in js and "'/api/companies'" in js
    # the work's ticks are sent, and the recount is asked for after each one
    assert "companyWorkNow(" in js and "companyWorkRepreview" in js and "companyRepreview" in js
    assert "/start`" in js and "method:'DELETE'" in js
    # the page keeps no copy of a company: after a switch it reloads the office and the panel
    assert "await officeLoad();await companyLoad()" in js
    css = CSS.read_text()
    for sel in (".co-cosl select", ".co-newco", ".co-plan", ".co-tdo .endbtn", ".co-wrow"):
        assert f"body.dev-touch {sel}" in css, f"{sel} is a fingertip on a phone"
