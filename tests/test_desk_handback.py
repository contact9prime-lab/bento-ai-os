"""What comes back from delegated work is whole, and a run that stops keeps what it finished
(tools.handed_back, fabric._salvage, company._shown). Reported as "the company delegation is not
very great, the answers fall short". Read from the owner's own record: every desk deliverable
(4,140 to 5,759 characters) reached the lead cut at 3,500 with no mark, bosses read 6,000, and a
Research desk that worked 39 minutes handed back nothing when its master's process was killed."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import company, fabric, providers, tools        # noqa: E402
from test_flow_run import _call, _flow, _script, _world      # noqa: E402

ROOT = Path(__file__).parent.parent


def test_an_answer_is_handed_back_whole_and_a_cut_is_said():
    body = "A paragraph of findings.\n\n" * 300                       # 7,800 characters
    assert tools.handed_back(body) == body, "what used to be cut at 3,500 now arrives whole"
    long = "A paragraph of findings.\n\n" * 2000
    got = tools.handed_back(long, "abc123")
    assert len(got) < tools.HANDBACK + 300
    assert "more characters are not shown here" in got and "run abc123" in got
    kept = got.split("\n\n[…")[0]
    assert kept.endswith("findings."), "cut at a paragraph, never mid-sentence"
    assert tools.handed_back("") == "" and tools.handed_back(None) == ""


def test_the_three_doors_back_to_the_lead_use_it():
    src = (ROOT / "agentos/tools.py").read_text()
    assert "[:3500]" not in src, "a silent cut on what a lead reads back"
    assert src.count("handed_back(res['content'] or res['fault']") == 2      # run_flow, department_task
    assert "handed_back(body, res.get('run_id')" in src                      # delegate
    fab = (ROOT / "agentos/fabric.py").read_text()
    assert "[:3500]" not in fab and fab.count("handed_back(text") == 2      # a colleague's answer, a linked team's


def test_a_boss_reads_the_whole_deliverable_or_is_told_what_it_did_not_see():
    text = "finding " * 1500                                             # 12,000 characters
    parts = company._work_parts("the task", text, "ok", "", [], [])
    assert text.strip() in parts[1], "6,000 characters used to be all a boss or the auditor read"
    cut = company._shown("x" * (company.REVIEW_CHARS + 500))
    assert "500 more characters of it are not shown to you" in cut
    back = fabric.ControlPlane._rework_text("the ask", text, {"sent_back": [{"who": "boss", "notes": ["fix x"]}]}, 1)
    assert text.strip() in back, "a send-back shows the master its whole last answer"


def test_a_run_that_stops_hands_back_what_its_steps_finished(tmp_path, monkeypatch):
    cfg, store, cp, events = _world(tmp_path)
    flow = _flow(store)
    findings = "The spread closed at 2.41 after 14 sessions. " * 40
    chat, _ = _script([
        [_call("delegate", {"subagent": "researcher", "task": "audit the data and say if it can be trusted"})],
        [{"type": "text", "text": findings}],
        [_call("note", {"text": "data audit passed, policy dates still to build"}, cid="c2")],
        [{"type": "error", "message": "the executor exited with 143"}],
    ])
    monkeypatch.setattr(providers, "chat", chat)
    delivered = []

    async def deliver(flow, run, origin, said):
        delivered.append(said)
        return ["test"]
    cp.deliver = deliver
    res = asyncio.run(cp.run_flow(flow, "go"))
    assert res["status"] == "error", "it is still a run that failed, and says so"
    assert "stopped before it was finished" in res["content"] and res["fault"] and res["fault"] in res["content"]
    assert findings.strip() in res["content"], "the finished step is handed back in full"
    assert "data audit passed" in res["content"], "and the note its lead kept"
    assert "Nobody put the pieces together and nobody checked them" in res["content"]
    assert delivered and findings.strip() in delivered[0], "it reaches the person, where the fault alone used to"
    assert res["audit"] is None or res["audit"].get("verdict") in (None, "skipped"), "nobody signs unfinished work"


def test_a_run_that_did_nothing_still_hands_back_only_its_fault(tmp_path, monkeypatch):
    cfg, store, cp, events = _world(tmp_path)
    flow = _flow(store)
    chat, _ = _script([[{"type": "error", "message": "no model answered"}]])
    monkeypatch.setattr(providers, "chat", chat)
    res = asyncio.run(cp.run_flow(flow, "go"))
    assert res["status"] == "error" and res["content"] == ""
