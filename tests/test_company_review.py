"""The review chain: a department's finished task goes up to its head, the head of each
department it reports to, and the lead, and each boss approves it, sends it back or
escalates a decision (company.chain / review_task / read_review / review_state,
ControlPlane.review in run_flow).

What these defend:

- reporting lines are part of the office: a name that is not a department falls back to
  the lead, a loop or a line deeper than MAX_REPORT_DEPTH is refused in a sentence;
- the control plane walks the chain after the master finishes and before anything is
  delivered, so a desk cannot skip it; each boss is its own run (kind `review`) with
  read-only tools, the lead answers with none, and every answer is a ledger row;
- a send-back is reworked by the SAME run, with the boss's notes, at most REWORK_MAX
  times; then it is the person's, in the Brief, and the line says so;
- an escalation goes to the next boss with the note, and from the lead to the person;
- an answer that is not approve, send back or escalate is never a sign-off;
- the auditor still checks the final work afterwards.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import company, fabric, flows, office, providers        # noqa: E402
from agentos.memory import Store                                     # noqa: E402
from agentos.policy import PDP                                       # noqa: E402
from agentos.tools import Toolbox                                    # noqa: E402

ROOT = Path(__file__).parent.parent
ASK = "Reply with APPROVE, SEND BACK or ESCALATE"


class Brain:
    """A provider that plays every part from what it is handed: the master delegates,
    then finishes (or fixes, when sent back); a specialist works; each boss answers from
    its own queue; the auditor passes."""

    def __init__(self, answers):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.asked: list[tuple[str, str, list]] = []      # (who, prompt, tools offered)
        self.master: list[str] = []

    def who(self, text):
        if "the lead agent. Every department reports" in text:
            return "lead"
        for d in ("Tech", "Ops", "Board"):
            if f"You head {d}." in text:
                return d
        return "?"

    def reply(self, messages, tools):
        sysp = " ".join(m.get("content") or "" for m in messages if m.get("role") == "system")
        users = [m.get("content") or "" for m in messages if m.get("role") == "user"]
        first = users[0] if users else ""
        names = [t.get("name") or (t.get("function") or {}).get("name") for t in (tools or [])]
        if ASK in first:
            w = self.who(first)
            self.asked.append((w, first, names))
            q = self.answers.get(w) or ["APPROVE"]
            return [{"type": "text", "text": q.pop(0) if len(q) > 1 else q[0]}]
        if "Reply with PASS, CONCERNS or FAIL" in first:
            return [{"type": "text", "text": "PASS"}]
        if "MASTER ORCHESTRATOR" in sysp:
            last = messages[-1]
            if last.get("role") == "user":
                self.master.append(last.get("content") or "")
                if "wants fixed" in (last.get("content") or ""):
                    return [_call("finish", {"summary": "Shipped v2, files: a.py, b.py.",
                                             "handles": ["a1"]}, cid="f2")]
                return [_call("delegate", {"subagent": "tech-lead", "task": "ship the fix"})]
            if last.get("role") == "tool" and last.get("name") == "delegate":
                return [_call("finish", {"summary": "Shipped the fix.", "handles": ["a1"]},
                              cid="f1")]
            return [{"type": "text", "text": ""}]
        return [{"type": "text", "text": "Fixed the bug in a.py and b.py; tests pass."}]

    def chat(self, cfg, model, messages, tools, options=None):
        evs = self.reply(messages, tools)

        async def gen():
            for ev in evs:
                yield ev
            yield {"type": "finish", "reason": "stop"}
        return gen()


def _call(name, args, cid="c1"):
    return {"type": "tool_call", "id": cid, "name": name, "args": args}


def _world(tmp_path, review="lead", tech_reports="Ops", **cfg):
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 8, "default_model": "ollama/x",
         "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0},
         "company": {"review": review}}
    c.update(cfg)
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    events = []

    async def broadcast(ev):
        events.append(ev)

    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    for n in ("tech-lead", "coder", "ops-lead"):
        store.save_subagent({"name": n, "soul": f"{n} at work",
                             "tools": ["recall", "read_file", "write_file", "remember"]})
    flow, _ = flows.save(store, {"name": "tech-desk", "mission": "You run the Tech department.",
                                 "roster": ["tech-lead", "coder"],
                                 "permissions": {"tools": [], "memory": "read-space"}, "sinks": []})
    office.save(c, store, {"departments": [
        {"name": "Tech", "color": "sky", "members": ["tech-lead", "coder"], "lead": "tech-lead",
         "desk": "tech-desk", **({"reports_to": tech_reports} if tech_reports else {})},
        {"name": "Ops", "color": "amber", "members": ["ops-lead"], "lead": "ops-lead"}]})
    handed = {}

    async def deliver(fl, run, origin, text):
        handed["text"] = text
        return ["chat"]
    cp.deliver = deliver
    return c, store, cp, events, flow, handed


def _run(cp, flow, monkeypatch, brain, task="Fix the login bug"):
    monkeypatch.setattr(providers, "chat", brain.chat)
    return asyncio.run(cp.run_flow(flow, task, origin={"surface": "gui"}))


# ---- reporting lines are part of the office ----

def test_reporting_lines_are_kept_and_a_loop_or_a_deep_line_is_refused(tmp_path):
    cfg, store = {}, Store(tmp_path / "t.db")
    for n in "abcdef":
        store.save_subagent({"name": n, "soul": n, "tools": []})
    got, _ = office.save(cfg, store, {"departments": [
        {"name": "Tech", "members": ["a"], "reports_to": "ops"},
        {"name": "Ops", "members": ["b"], "reports_to": "Nowhere"},
        {"name": "Sales", "members": ["c"], "reports_to": "Sales"}]})
    by = {d["name"]: d for d in got["departments"]}
    assert by["Tech"]["reports_to"] == "Ops", "matched whatever the case"
    assert "reports_to" not in by["Ops"], "a department that is not here means the lead"
    assert "reports_to" not in by["Sales"], "reporting to yourself means the lead"
    rooms = {r["name"]: r for r in office.view(cfg, store)["rooms"]}
    assert rooms["Tech"]["reports_to"] == "Ops"

    with pytest.raises(ValueError, match="loop"):
        office.save(cfg, store, {"departments": [
            {"name": "Tech", "members": ["a"], "reports_to": "Ops"},
            {"name": "Ops", "members": ["b"], "reports_to": "Tech"}]})
    names = ["D1", "D2", "D3", "D4", "D5"]
    with pytest.raises(ValueError, match="deep"):
        office.save(cfg, store, {"departments": [
            {"name": n, "members": [m], **({"reports_to": names[i + 1]} if i < 4 else {})}
            for i, (n, m) in enumerate(zip(names, "abcde"))]})
    assert office.current(cfg)["departments"][0]["name"] == "Tech", "a refused save changes nothing"


def test_a_plan_carries_reporting_lines_and_drops_a_loop_by_name():
    plan = {"departments": [
        {"name": "Tech", "reports_to": "ops", "people": [{"name": "t", "soul": "x", "lead": True}]},
        {"name": "Ops", "people": [{"name": "o", "soul": "x", "lead": True}]}]}
    got, dropped = company.normalize(plan)
    assert got["departments"][0]["reports_to"] == "Ops" and not dropped
    plan["departments"][1]["reports_to"] = "Tech"
    got, dropped = company.normalize(plan)
    assert not any(d.get("reports_to") for d in got["departments"])
    assert any("reporting lines" in d and "loop" in d for d in dropped)
    sysp, prompt = company.design_prompt("a startup")
    assert "reports_to" in prompt


def test_the_chain_is_the_head_then_each_boss_above_then_the_lead(tmp_path):
    cfg, store, *_ = _world(tmp_path)
    who = [g["who"] for g in company.chain(cfg, store, "Tech")]
    assert who == ["tech-lead", "ops-lead", "Aria"]
    assert [g["who"] for g in company.chain(cfg, store, "Tech", "heads")] == ["tech-lead"]
    assert company.chain(cfg, store, "Tech", "off") == []
    assert company.review_mode({}) == "lead", "on, up to the lead, unless the person says otherwise"
    # a room filled by hand has a first person, not a head: nobody can sign off there
    office.save(cfg, store, {"departments": [
        {"name": "Tech", "members": ["tech-lead"], "desk": "tech-desk", "reports_to": "Ops"},
        {"name": "Ops", "members": ["ops-lead"], "lead": "ops-lead"}]})
    gates = company.chain(cfg, store, "Tech")
    assert gates[0]["who"] == "" and "no head" in gates[0]["why"]
    assert [g["who"] for g in gates[1:]] == ["ops-lead", "Aria"]


@pytest.mark.parametrize("text,answer", [
    ("APPROVE", "approve"), ("Approved. Looks right.", "approve"), ("**Sign off**", "approve"),
    ("SEND BACK\n- name the files", "send_back"), ("Sent back: no tests", "send_back"),
    ("ESCALATE\n- pricing is not mine", "escalate"), ("Escalated", "escalate"),
    ("Looks good to me", ""), ("I would approve this", ""), ("", ""),
])
def test_an_answer_is_read_strictly(text, answer):
    assert company.read_review(text)[0] == answer


# ---- the chain runs by itself, between the work and the hand-over ----

def test_a_department_task_is_signed_off_up_to_the_lead_before_it_is_handed_over(tmp_path, monkeypatch):
    cfg, store, cp, events, flow, handed = _world(tmp_path)
    brain = Brain({"Tech": ["APPROVE"], "Ops": ["APPROVE"], "lead": ["APPROVE\n- ready"]})
    res = _run(cp, flow, monkeypatch, brain)

    assert res["status"] == "ok"
    rv = res["review"]
    assert rv["outcome"] == "approved" and rv["rounds"] == 0
    assert [g["who"] for g in rv["gates"]] == ["tech-lead", "ops-lead", "Aria"]
    assert [w for w, _p, _t in brain.asked] == ["Tech", "Ops", "lead"]
    assert handed["text"].startswith("Shipped the fix.")
    assert "Signed off by tech-lead → ops-lead → Aria." in handed["text"]
    assert "independent auditor" in handed["text"], "the auditor still checks the final work"

    # each boss read the task and the work, and the one above heard who signed below
    _w, ops_prompt, _t = brain.asked[1]
    assert "Fix the login bug" in ops_prompt and "Shipped the fix." in ops_prompt
    assert "Tech reports to you" in ops_prompt and "tech-lead: approved" in ops_prompt
    # a head signs off with read-only tools; the lead with none
    assert set(brain.asked[0][2]) <= set(company.AUDIT_TOOLS)
    assert "write_file" not in brain.asked[0][2] and "remember" not in brain.asked[0][2]
    assert brain.asked[2][2] == []

    kids = store.fabric_runs(parent_run=res["run_id"])
    reviews = sorted([k for k in kids if k["kind"] == "review"], key=lambda k: k["started_at"])
    assert [k["ref"] for k in reviews] == ["tech-lead", "ops-lead", "Aria"]
    assert reviews[-1]["model"] == "ollama/x", "the lead's row says what answered"
    rows = [dict(r) for r in store.db.execute("SELECT * FROM audit WHERE action='company.review'")]
    assert len(rows) == 3 and all(r["outcome"] == "approve" for r in rows)
    assert {r["principal_id"] for r in rows} == {"tech-lead", "ops-lead", ""}

    ev = [(e["event"], (e.get("data") or e).get("phase"), (e.get("data") or e).get("reviewer"))
          for e in events if e.get("type") == "fabric_event" and e.get("run_id") == res["run_id"]]
    names = [x[0] for x in ev]
    assert ("review", "start", "tech-lead") in ev and ("review", "done", "Aria") in ev
    assert names.index("review") < names.index("audit") < names.index("flow_end")
    end = next(e for e in events if e.get("type") == "fabric_event" and e.get("event") == "flow_end")
    assert (end.get("data") or end)["review"]["outcome"] == "approved"


def test_a_send_back_is_reworked_by_the_same_run_with_the_bosses_notes(tmp_path, monkeypatch):
    cfg, store, cp, _ev, flow, handed = _world(tmp_path)
    brain = Brain({"Tech": ["SEND BACK\n- name the files you changed", "APPROVE"],
                   "Ops": ["APPROVE"], "lead": ["APPROVE"]})
    res = _run(cp, flow, monkeypatch, brain)
    rv = res["review"]
    assert rv["outcome"] == "approved" and rv["rounds"] == 1
    assert "after 1 round of fixes" in handed["text"]
    assert handed["text"].startswith("Shipped v2, files: a.py, b.py.")
    assert len(brain.master) == 2, "one more go for the same master"
    again = brain.master[1]
    assert "name the files you changed" in again and "Fix the login bug" in again
    assert "Shipped the fix." in again, "it sees the answer that was sent back"
    assert [w for w, _p, _t in brain.asked] == ["Tech", "Tech", "Ops", "lead"], \
        "a fixed task starts at the bottom of the chain again"
    assert "name the files you changed" in brain.asked[1][1], "the head checks its own ask"
    assert len(store.fabric_runs(limit=50, kind="flow") if False else
               [r for r in store.fabric_runs(limit=50) if r["kind"] == "flow"]) == 1


def test_sent_back_every_time_is_the_persons_after_the_last_round(tmp_path, monkeypatch):
    cfg, store, cp, _ev, flow, handed = _world(tmp_path)
    brain = Brain({"Tech": ["SEND BACK\n- still no tests"]})
    res = _run(cp, flow, monkeypatch, brain)
    rv = res["review"]
    assert rv["outcome"] == "sent_back" and rv["rounds"] == company.REWORK_MAX
    assert len(rv["sent_back"]) == company.REWORK_MAX + 1
    assert len(brain.master) == company.REWORK_MAX + 1
    assert [w for w, _p, _t in brain.asked] == ["Tech"] * (company.REWORK_MAX + 1), \
        "nobody above signs what its own head would not"
    assert f"after {company.REWORK_MAX} rounds of fixes, so it needs you: still no tests" \
        in handed["text"]
    item = next(b for b in store.brief_items(limit=50) if b["key"] == f"review-{res['run_id']}")
    assert item["kind"] == "needs_you" and "sent Tech's task back 3 times" in item["title"]
    row = next(t for t in company.board(cfg, store)["tasks"] if t["run_id"] == res["run_id"])
    assert row["review"]["outcome"] == "sent_back"


def test_an_escalation_goes_up_with_its_note_and_from_the_lead_to_the_person(tmp_path, monkeypatch):
    cfg, store, cp, _ev, flow, handed = _world(tmp_path)
    brain = Brain({"Tech": ["APPROVE"], "Ops": ["ESCALATE\n- the price is not mine to set"],
                   "lead": ["ESCALATE\n- the person must pick the price"]})
    res = _run(cp, flow, monkeypatch, brain)
    assert res["review"]["outcome"] == "escalated"
    assert "the price is not mine to set" in brain.asked[2][1], "the lead hears why it came up"
    assert "Aria needs you to decide: the person must pick the price" in handed["text"]
    item = next(b for b in store.brief_items(limit=50) if b["key"] == f"review-{res['run_id']}")
    assert item["kind"] == "needs_you" and "Aria needs you to decide" in item["title"]
    # an escalation the next boss answers is that boss's decision
    cfg2, store2, cp2, _e, flow2, handed2 = _world(tmp_path / "b")
    res2 = _run(cp2, flow2, monkeypatch, Brain({"Ops": ["ESCALATE\n- budget"], "lead": ["APPROVE"]}))
    assert res2["review"]["outcome"] == "approved"


def test_an_unclear_answer_is_never_a_sign_off(tmp_path, monkeypatch):
    cfg, store, cp, _ev, flow, handed = _world(tmp_path)
    res = _run(cp, flow, monkeypatch, Brain({"Ops": ["Looks fine to me"]}))
    rv = res["review"]
    assert rv["outcome"] == "unchecked"
    assert [g["who"] for g in rv["gates"]] == ["tech-lead", "ops-lead"], "the chain stops there"
    assert "Not signed off" in handed["text"]
    assert any(b["key"] == f"review-{res['run_id']}" for b in store.brief_items(limit=50))


def test_a_department_with_no_head_is_a_hole_in_the_record_not_a_sign_off(tmp_path, monkeypatch):
    cfg, store, cp, _ev, flow, handed = _world(tmp_path)
    store.delete_subagent(store.get_subagent("ops-lead")["id"])
    res = _run(cp, flow, monkeypatch, Brain({}))
    rv = res["review"]
    assert [g["answer"] for g in rv["gates"]] == ["approve", "skipped", "approve"]
    assert rv["outcome"] == "approved", "the bosses above still sign it"
    assert "Ops has no head, so nobody signed off there" in handed["text"]


def test_heads_only_and_off(tmp_path, monkeypatch):
    cfg, store, cp, _ev, flow, handed = _world(tmp_path, review="heads")
    brain = Brain({})
    res = _run(cp, flow, monkeypatch, brain)
    assert [w for w, _p, _t in brain.asked] == ["Tech"]
    assert "Signed off by tech-lead." in handed["text"]
    cfg, store, cp, _ev, flow, handed = _world(tmp_path / "off", review="off")
    brain = Brain({})
    res = _run(cp, flow, monkeypatch, brain)
    assert brain.asked == [] and res["review"] is None
    assert not [k for k in store.fabric_runs(parent_run=res["run_id"]) if k["kind"] == "review"]


def test_a_flow_that_is_not_a_desk_is_not_reviewed(tmp_path, monkeypatch):
    cfg, store, cp, _ev, _flow, handed = _world(tmp_path)
    flow, _ = flows.save(store, {"name": "other", "mission": "x", "roster": ["tech-lead"],
                                 "permissions": {"tools": [], "memory": "read-space"}, "sinks": []})
    brain = Brain({})
    res = _run(cp, flow, monkeypatch, brain)
    assert res["review"] is None and brain.asked == []


def test_the_board_and_the_terminal_read_the_chain_back_from_the_runs(tmp_path, monkeypatch):
    cfg, store, cp, _ev, flow, _h = _world(tmp_path)
    res = _run(cp, flow, monkeypatch, Brain({"Tech": ["SEND BACK\n- tests", "APPROVE"]}))
    row = next(t for t in company.board(cfg, store)["tasks"] if t["run_id"] == res["run_id"])
    assert row["review"]["outcome"] == "approved" and row["review"]["rounds"] == 1
    assert row["who"] == "tech-lead", "a boss signing off is not a hand-over"
    assert row["handoffs"] == 1, "the fix round finished without handing anything over"
    text = company.text(cfg, store)
    assert "Tech reports to Ops · 1 signed off" in text and "Ops reports to Aria" in text
    assert "signed off by each boss, up to Aria" in text


# ---- the doors: routes, the terminal and the page ----

def test_the_routes_set_the_mode_and_a_reporting_line_and_refuse_a_loop(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        assert cl.put("/api/company", json={"review": "sideways"}).status_code == 400
        assert cl.put("/api/company", json={"review": "heads"}).json()["ok"]
        assert cl.get("/api/company").json()["board"]["review"] == "heads"
        cl.put("/api/company", json={"review": "lead"})
        assert cl.put("/api/company/reports", json={"department": "Nope"}).status_code == 404
        cl.put("/api/office", json={"departments": [{"name": "Tech", "members": []},
                                                     {"name": "Ops", "members": []}]})
        r = cl.put("/api/company/reports", json={"department": "tech", "reports_to": "Ops"}).json()
        assert r["ok"] and r["reports_to"] == "Ops"
        r = cl.put("/api/company/reports", json={"department": "Ops", "reports_to": "Tech"})
        assert r.status_code == 400 and "loop" in r.json()["error"]
        r = cl.put("/api/company/reports", json={"department": "Tech", "reports_to": "Moon"})
        assert r.status_code == 400 and "Ops" in r.json()["error"], "the refusal names the choices"
        r = cl.put("/api/company/reports", json={"department": "Tech", "reports_to": "lead"}).json()
        assert r["ok"] and r["reports_to"] == company.lead_name(servermod.state["cfg"])
        tech = next(d for d in office.current(servermod.state["cfg"])["departments"] if d["name"] == "Tech")
        assert "reports_to" not in tech, "the lead is the default, so nothing is stored"


def test_the_terminal_sets_the_mode_and_the_lines_with_the_server_down(tmp_path):
    import subprocess
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "company", *a], cwd=ROOT,  # noqa: E731
                                    env=env, capture_output=True, text=True, timeout=90)
    assert "up to" in run("review").stdout
    r = run("review", "heads")
    assert r.returncode == 0 and "own head" in r.stdout
    r = run("setup", "a shop", "--departments", "tech,admin", "--words", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    r = run("chain", "tech", "admin")
    assert r.returncode == 0 and "Tech           reports to Admin" in r.stdout
    r = run("chain", "admin", "tech")
    assert r.returncode == 1 and "loop" in r.stdout
    assert "Tech reports to Admin" in run("show").stdout


def test_the_page_draws_the_chain_from_the_server_and_queues_the_walks():
    js = (ROOT / "agentos/ui/src/js/24g-company.js").read_text()
    assert "function companyReviewHTML" in js and "t.review" in js
    assert "'/api/company/reports'" in js and "review:v" in js
    assert "chip('held'" in js and "function companyHeld" in js
    off = (ROOT / "agentos/ui/src/js/24d-office.js").read_text()
    body = off[off.index("function officeReview("):off.index("/* The result comes back")]
    assert "R.q.push(ev)" in body and "officeReviewNext" in body, "a run's review events are played in order"
    assert "if(ev.kind==='review')return;" in off, "a sign-off run's own status draws nothing twice"
    fab = (ROOT / "agentos/fabric.py").read_text()
    assert fab.count('"kind": kind') >= 2 and '"kind": "review"' in fab
