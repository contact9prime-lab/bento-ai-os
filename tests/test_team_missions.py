"""A mission on one machine that uses an agent on another is RECORDED on the other.

The parent (home) decided to put office's analyst on its mission's roster; that decision
lives in home's grants. Office does the work, so office holds its own record, and that
record is what makes it auditable and stoppable there. What these defend:

- saving a mission tells the linked team, which records it as grants rows (with what it
  is for and when it runs) and audit rows — and says which agents it has NOT let you ask;
- a mission whose announcement never arrived is recorded on its first question;
- the person on the working side can stop one mission: its questions are refused with a
  sentence that says so, the agent never runs, and Allow again undoes it — all audited;
- the record authorises nothing: unticking the agent stops the mission whatever it says;
- deleting the mission forgets the record there, and ending the link revokes it;
- the terminal lists, stops and resumes.
"""
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric, flows, providers, teamlink                # noqa: E402
from test_teamlink import pair                                        # noqa: E402,F401
from test_team_standing import _worker                                # noqa: E402

BODY = {"name": "weekly-report", "mission": "Have the office analyst file the weekly report.",
        "roster": ["analyst@office"], "permissions": {"tools": [], "memory": "none"}, "sinks": [],
        "triggers": [{"kind": "cron", "config": {"type": "weekly", "day": "mon", "at": "09:00"}}]}


def _office(A, tmp_path):
    A["store"].save_subagent({"name": "analyst", "soul": "SOUL-analyst", "autonomy_cap": "full",
                              "tools": ["write_file"]})
    A["store"].save_subagent({"name": "writer", "soul": "SOUL-writer"})
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["analyst"])
    shared = tmp_path / "office-shared"
    shared.mkdir(exist_ok=True)
    fabric.add_standing(A["store"], "home", "analyst", "fs.write", str(shared))
    return shared


def _save(B, loop, body=BODY, announce=True):
    async def go():
        with teamlink.at(B["home"]):
            flow, _ = flows.save(B["store"], body)
            flow = B["store"].get_flow(flow["name"])
            return flow, (await B["cp"].announce_mission(flow) if announce else {})
    return loop.run_until_complete(go())


def _run(B, loop, name="weekly-report"):
    async def go():
        with teamlink.at(B["home"]):
            return await B["cp"].run_flow(B["store"].get_flow(name) | {"enabled": 1}, "",
                                          origin={"surface": "task"})
    return loop.run_until_complete(go())


def _missions(A):
    return {m["mission"]: m for m in fabric.linked_missions(A["store"], "home")}


def _audit(store, action):
    return [tuple(r) for r in store.db.execute(
        "SELECT action, resource, detail FROM audit WHERE action=?", (action,)).fetchall()]


def test_saving_a_mission_records_it_on_the_team_that_does_the_work(pair, tmp_path):
    A, B, inv, loop = pair
    _office(A, tmp_path)
    _, told = _save(B, loop, {**BODY, "roster": ["analyst@office", "writer@office"]})
    assert told["office"]["ok"] and told["office"]["recorded"] == ["analyst"]
    assert told["office"]["not_allowed"] == ["writer"], "the editor can say so at save time"
    m = _missions(A)["weekly-report"]
    assert m["agents"] == ["analyst"] and not m["stopped"] and m["runs"] == 0
    assert m["schedule"] == "every Monday at 09:00" and "weekly report" in m["text"]
    rows = A["store"].list_grants(principal_kind="team", principal_id="home/weekly-report-master")
    assert [(g["action"], g["resource"]) for g in rows] == [("team.mission", "agent:subagent/analyst")]
    assert any("weekly-report" in r[2] for r in _audit(A["store"], "link.mission")), "the working side's ledger"
    assert any(r[1].startswith("team:home/weekly-report-master team.mission") for r in _audit(A["store"], "grant.write"))
    assert any("recorded there" in r[2] for r in _audit(B["store"], "link.mission")), "and the asking side's"


def test_a_mission_never_announced_is_recorded_on_its_first_question(pair, tmp_path, monkeypatch):
    A, B, inv, loop = pair
    shared = _office(A, tmp_path)
    monkeypatch.setattr(providers, "chat", _worker(lambda q: str(shared / "weekly.md")))
    _save(B, loop, announce=False)
    assert "weekly-report" not in _missions(A)
    _run(B, loop)
    m = _missions(A)["weekly-report"]
    assert m["how"] == "first question" and m["agents"] == ["analyst"]
    assert m["runs"] == 1 and m["last_used"], "use is read from the ledger, never kept apart from it"
    assert (shared / "weekly.md").exists()


def test_the_working_side_can_stop_one_mission_and_allow_it_again(pair, tmp_path, monkeypatch):
    A, B, inv, loop = pair
    shared = _office(A, tmp_path)
    monkeypatch.setattr(providers, "chat", _worker(lambda q: str(shared / "weekly.md")))
    _save(B, loop)
    fabric.stop_mission(A["store"], "home", "weekly-report")
    assert _missions(A)["weekly-report"]["stopped"]
    res = _run(B, loop)
    assert not (shared / "weekly.md").exists(), "a stopped mission's task never reached the agent"
    board = [a for a in B["store"].artifact_index(res["run_id"]) if a.get("agent") == "analyst@office"]
    body = B["store"].artifact_get(res["run_id"], board[0]["handle"])["content"]
    assert "stopped your mission 'weekly-report'" in body, "the asking side is told, in words"
    assert any(r[1] == "team:home/weekly-report-master agent.message agent:subagent/*"
               for r in _audit(A["store"], "grant.write"))
    _, told = _save(B, loop)
    assert told["office"]["stopped"], "a re-save does not undo a stop"
    fabric.stop_mission(A["store"], "home", "weekly-report", stop=False)
    _run(B, loop)
    assert (shared / "weekly.md").exists()
    assert _audit(A["store"], "grant.revoke"), "allowing again is in the ledger too"


def test_the_record_grants_nothing(pair, tmp_path, monkeypatch):
    A, B, inv, loop = pair
    shared = _office(A, tmp_path)
    monkeypatch.setattr(providers, "chat", _worker(lambda q: str(shared / "weekly.md")))
    _save(B, loop)
    fabric.set_link_access(A["store"], "home", theirs_may_ask=[])
    _run(B, loop)
    assert not (shared / "weekly.md").exists(), "unticking the agent stops every mission at once"


def test_deleting_forgets_it_there_and_ending_the_link_revokes_it(pair, tmp_path):
    A, B, inv, loop = pair
    _office(A, tmp_path)
    flow, _ = _save(B, loop)

    async def gone():
        with teamlink.at(B["home"]):
            return await B["cp"].announce_mission(flow, deleted=True)
    assert loop.run_until_complete(gone())["office"]["ok"]
    assert "weekly-report" not in _missions(A)
    _save(B, loop)
    assert "weekly-report" in _missions(A)
    fabric.forget_link_grants(A["store"], "home")
    assert _missions(A) == {}


def test_a_team_can_not_fill_the_records_without_end(pair, tmp_path, monkeypatch):
    A, B, inv, loop = pair
    _office(A, tmp_path)
    monkeypatch.setattr(fabric, "MAX_LINKED_MISSIONS", 3)
    for i in range(3):
        assert fabric.record_mission(A["store"], "home", {"name": f"m{i}", "agents": ["analyst"]})["ok"]
    got = fabric.record_mission(A["store"], "home", {"name": "m9", "agents": ["analyst"]})
    assert not got["ok"] and "already records" in got["error"]
    assert fabric.record_mission(A["store"], "home", {"name": "m1", "agents": ["analyst"], "enabled": False})["ok"], \
        "updating one it already holds is not a new record"


def test_the_terminal_lists_stops_and_resumes(pair, tmp_path):
    A, B, inv, loop = pair
    _office(A, tmp_path)
    _save(B, loop)
    env = {**os.environ, "AGENTOS_HOME": str(A["home"]), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "link", *a],  # noqa: E731
                                    cwd=Path(__file__).parent.parent, env=env,
                                    capture_output=True, text=True, timeout=60)
    r = run("missions", "home")
    assert "weekly-report" in r.stdout and "every Monday at 09:00" in r.stdout and "analyst" in r.stdout
    assert "is stopped" in run("stop", "home", "weekly-report").stdout
    assert "STOPPED" in run("missions", "home").stdout
    assert run("resume", "home", "weekly-report").returncode == 0
    assert run("stop", "home", "nothing-here").returncode == 2


def test_settings_shows_them_with_a_stop():
    js = (Path(__file__).parent.parent / "agentos/ui/src/js/11-settings.js").read_text()
    assert "tlMissionsHTML" in js and "/missions/" in js and "Allow again" in js
    fab = (Path(__file__).parent.parent / "agentos/ui/src/js/13-fabric.js").read_text()
    assert "flwLinkedToast(r.linked)" in fab, "the editor says what the other side answered"
