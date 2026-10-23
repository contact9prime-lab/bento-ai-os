"""A Zero sets up schedules on its hub (tools.schedule_task in a Zero's section, scheduler.zero_job,
server._zero_job / _zero_say_from_hub, Network → the Zero → Schedules). Asked for as "can the Pi
also set up scheduled jobs on the hub".

A schedule asked for at a Zero runs later exactly as that Zero's chat runs, never as the owner
with every tool: anybody standing at the Pi can talk to it, so a schedule must not be a way to
get more than its chat gives."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import provision, providers  # noqa: E402
from agentos.memory import Store           # noqa: E402
from agentos.scheduler import Scheduler    # noqa: E402
from agentos.tools import Toolbox          # noqa: E402

ROOT = Path(__file__).parent.parent


def _zero_section(monkeypatch, sid="s-kitchen"):
    monkeypatch.setattr(provision, "load", lambda: {"enabled": {"fp": {"label": "kitchen-pi", "space": sid,
                                                                       "execution": "hub"}}, "keys": [], "devices": {}})


def test_a_schedule_asked_at_a_zero_is_kept_in_its_section(tmp_path, monkeypatch):
    _zero_section(monkeypatch)
    st = Store(tmp_path / "a.db")
    tb = Toolbox({"workspace": str(tmp_path)}, st)

    async def bc(ev):
        pass
    tb.scheduler = Scheduler({}, st, tb, bc)
    said = asyncio.run(tb.schedule_task("Say: tea", "daily", at_time="08:00", space_id="s-kitchen"))
    assert said.startswith("scheduled")
    other = asyncio.run(tb.schedule_task("water the plants", "daily", at_time="09:00", space_id="s-work"))
    assert other.startswith("scheduled")
    rows = {r["prompt"]: r["space_id"] for r in st.db.execute("SELECT prompt, space_id FROM tasks")}
    assert rows == {"Say: tea": "s-kitchen", "water the plants": ""}, "only a Zero's section is recorded"


def test_a_zeros_schedule_runs_through_zero_job_never_as_the_owner(tmp_path, monkeypatch):
    st = Store(tmp_path / "a.db")
    events = []

    async def bc(ev):
        events.append(ev)
    sch = Scheduler({}, st, None, bc)
    ran = {}

    async def zero_job(task):
        ran["task"] = task["prompt"]
        return "c1", "It is time for tea."

    async def run_prompt(*a, **k):
        raise AssertionError("a Zero's schedule must not run as the owner")
    sch.zero_job, sch.run_prompt = zero_job, run_prompt
    tid = st.add_task("Say: tea", "once", None, None, 0, space_id="s-kitchen")
    asyncio.run(sch._run_task(st.get_task(tid) if hasattr(st, "get_task") else
                              dict(st.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())))
    assert ran["task"] == "Say: tea"
    assert any(e.get("type") == "task_finished" and "tea" in e.get("result", "") for e in events)


def test_a_scheduled_run_cannot_schedule_more_and_the_link_cannot_claim_to_be_one(monkeypatch):
    from test_zero_mind import _on, hz  # noqa: F401
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index('if req.get("op") == "zero_chat":'):]
    assert 'req.pop("_job", None)' in h[:300], "only this hub's scheduler says a turn is a job"
    fab = (ROOT / "agentos/fabric.py").read_text()
    assert 'tool == "schedule_task" and not needs_person() and not job' in fab
    say = srv[srv.index("async def _zero_say_from_hub"):]
    assert "is_my_hub" in say[:600], "only its own hub speaks on its screen"


def test_the_screen_and_the_hub_show_it():
    js = (ROOT / "agentos/ui/src/js/24h-kiosk.js").read_text()
    assert "function kioskScheduled" in js and "kioskSpeak(text)" in js
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'zero_say'" in ws
    from agentos import fabric, ties
    assert "schedule_task" in fabric.ZERO_CHAT_TOOLS and "schedules" in ties.VIEWS


def test_the_provision_row_lets_its_own_chat_schedule_and_nothing_else(tmp_path):
    """The real Pi's first try was refused: a Zero's chat is marked as from outside, and a risky
    step after outside content needs a person. Only a row provisioning wrote lifts it, only for
    schedule_task, only when every bit of outside content came from that one Zero."""
    from agentos import zero
    from agentos.policy import MAIN, PDP, Principal, standing_refusal
    from test_zero import _hub
    cfg, store = _hub(tmp_path)
    mine = [{"tool": "linked team", "source": "pi-kitchen"}]

    def decide(tool, taint=mine, who=MAIN):
        return PDP(cfg, store).decide(who, "tool.use", f"tool:{tool} {{}}",
                                      {"risk": "risky", "taint": taint, "reason": "x"}).effect
    assert decide("schedule_task") == "ask", "nothing standing yet"
    zero.zero_standing(store, cfg, "pi-kitchen")
    assert decide("schedule_task") == "allow"
    assert decide("run_command") == "ask", "only schedule_task"
    assert decide("schedule_task", taint=[{"tool": "linked team", "source": "office"}]) == "ask", "only its own Zero"
    assert decide("schedule_task", taint=mine + [{"tool": "fetch_url", "source": "x.com"}]) == "ask", \
        "a page read too puts the person back"
    assert standing_refusal("tool.use", "tool:schedule_task*"), "a person's own row may never cover it"
    assert not standing_refusal("tool.use", "tool:schedule_task*", "provision")
