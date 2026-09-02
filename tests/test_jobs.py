"""Jobs: a recipe plus a few answers becomes something that actually fires.

The claim these tests defend is the one the onboarding screen makes to a new user:
"answer two questions and this machine will do that, by itself, from now on". So the
end of the file is not a unit test — it installs a job the way the wizard does, winds
its clock back, and asserts the scheduler really started the flow. Everything before
it is the consent and the honesty: what it will read, where it will deliver, and what
it says when a way out is not set up.
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric as fabricmod                            # noqa: E402
from agentos import jobs                                           # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.scheduler import Scheduler                            # noqa: E402
from agentos.tools import Toolbox                                  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    fabricmod.seed_builtins({}, s)
    return s


CFG_PLAIN: dict = {}
CFG_TELEGRAM = {"telegram": {"enabled": True, "bot_token": "1:abc", "owner_chat_id": 42}}


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

def test_every_recipe_ends_with_the_delivery_question():
    """A job that produces something nobody sees is the failure mode this whole
    module exists to avoid, so 'where should it reach you' is not optional."""
    for r in jobs.RECIPES:
        assert r.needs[-1].key == "deliver", r.id
        assert r.needs[-1].kind == "choice"


def test_a_recipe_serialises_everything_a_surface_needs_to_draw_it():
    d = jobs.BY_ID["folder-watch"].as_dict()
    assert d["reads_path"] == "folder"
    assert {n["key"] for n in d["needs"]} == {"folder", "deliver"}
    assert [n["kind"] for n in d["needs"] if n["key"] == "folder"] == ["folder"]


# ---------------------------------------------------------------------------
# Delivery is probed, not declared
# ---------------------------------------------------------------------------

def test_telegram_is_offered_only_when_it_is_actually_paired():
    off = {d["id"]: d for d in jobs.deliveries(CFG_PLAIN)}
    assert off["telegram"]["ready"] is False
    assert "Channels" in off["telegram"]["detail"]      # says what would fix it
    on = {d["id"]: d for d in jobs.deliveries(CFG_TELEGRAM)}
    assert on["telegram"]["ready"] is True


def test_a_token_without_a_paired_chat_is_not_a_working_telegram():
    """Half-configured is the common state, and it is the one that silently swallows
    a delivery: the bot exists, so `enabled` looks true, but nobody has said /start."""
    half = {"telegram": {"enabled": True, "bot_token": "1:abc"}}
    assert {d["id"]: d for d in jobs.deliveries(half)}["telegram"]["ready"] is False


def test_asking_for_a_way_out_that_does_not_work_falls_back_and_says_so(store, tmp_path):
    res = jobs.install(CFG_PLAIN, store, "folder-watch",
                       {"folder": str(tmp_path), "deliver": "telegram"})
    assert res["delivery"]["id"] == "report"
    assert "telegram" in res["substituted"]
    assert res["flow"]["sinks"] == [{"kind": "report"}]


def test_telegram_delivery_also_grants_save_report(store):
    """A page too long for a message still has to land somewhere findable."""
    body = jobs.build(CFG_TELEGRAM, store, "morning-brief",
                      {"topics": "rust", "deliver": "telegram"})
    tools = body["permissions"]["tools"]
    assert "telegram_send" in tools and "save_report" in tools


# ---------------------------------------------------------------------------
# Consent: what it will read is shown before it is granted
# ---------------------------------------------------------------------------

def test_the_folder_job_is_granted_that_folder_and_nothing_above_it(store, tmp_path):
    watched = tmp_path / "inbox"
    watched.mkdir()
    p = jobs.preview(CFG_PLAIN, store, "folder-watch", {"folder": str(watched)})
    assert p["reads"] == [str(watched) + "/*"]
    reads = [g for g in p["grants"] if g["action"] == "fs.read"]
    assert reads and all(g["resource"] == f"fs:{watched}/*" for g in reads)
    assert not [g for g in p["grants"] if g["action"] == "fs.write"]


def test_preview_writes_nothing(store, tmp_path):
    before = (len(store.list_flows()), len(store.list_grants()), len(store.list_tasks()))
    jobs.preview(CFG_PLAIN, store, "folder-watch", {"folder": str(tmp_path)})
    assert (len(store.list_flows()), len(store.list_grants()),
            len(store.list_tasks())) == before


def test_preview_shows_exactly_what_install_writes(store, tmp_path):
    """The consent screen and the save must be the same computation, or the sentence
    somebody agreed to is not the permission they got."""
    answers = {"folder": str(tmp_path), "deliver": "report"}
    predicted = jobs.preview(CFG_PLAIN, store, "folder-watch", answers)["grants"]
    name = jobs.install(CFG_PLAIN, store, "folder-watch", answers)["flow"]["name"]
    written = [g for g in store.list_grants()
               if (g.get("source_ref") or "") == f"flow:{name}"]
    key = lambda g: (g["principal_kind"], g["principal_id"], g["action"], g["resource"])  # noqa: E731
    assert sorted(map(key, predicted)) == sorted(map(key, written))


def test_a_folder_that_is_not_there_is_refused_with_a_sentence(store):
    with pytest.raises(ValueError) as e:
        jobs.build(CFG_PLAIN, store, "folder-watch", {"folder": "/no/such/place"})
    assert "no folder at" in str(e.value)


def test_a_page_watch_is_granted_only_that_page(store):
    body = jobs.build(CFG_PLAIN, store, "page-watch",
                      {"url": "https://example.com/pricing", "minutes": "30"})
    assert body["permissions"]["net"] == ["https://example.com/pricing"]


@pytest.mark.parametrize("recipe,answers,says", [
    ("page-watch", {"url": "not a url"}, "web address"),
    ("page-watch", {"url": "https://x.dev", "minutes": "soon"}, "minutes"),
    ("morning-brief", {"topics": "   "}, "keep an eye on"),
    ("morning-brief", {"topics": "x", "at": "quarter past"}, "time of day"),
    ("nope", {}, "no job recipe"),
])
def test_bad_answers_are_refused_in_words_a_person_can_act_on(store, recipe, answers, says):
    with pytest.raises(ValueError) as e:
        jobs.build(CFG_PLAIN, store, recipe, answers)
    assert says in str(e.value)


def test_an_unanswered_interval_takes_the_default_rather_than_exploding(store):
    """`str(None)` is 'None', which is truthy — the trap that made an unanswered
    question read as an unparseable one."""
    body = jobs.build(CFG_PLAIN, store, "page-watch", {"url": "https://x.dev"})
    assert body["triggers"][0]["config"]["minutes"] == 60


# ---------------------------------------------------------------------------
# Install: a real flow, enabled, with a real clock
# ---------------------------------------------------------------------------

def test_installing_gives_a_job_that_is_on(store):
    res = jobs.install(CFG_PLAIN, store, "morning-brief",
                       {"topics": "rust releases", "at": "7:30"})
    flow = store.get_flow(res["flow"]["name"])
    assert flow["enabled"] == 1
    assert flow["job"] == "morning-brief"
    # enabled means the grants are real, not merely declared
    assert [g for g in store.list_grants()
            if (g.get("source_ref") or "") == f"flow:{flow['name']}"]


def test_the_clock_row_exists_and_carries_the_time_that_was_asked_for(store):
    res = jobs.install(CFG_PLAIN, store, "morning-brief",
                       {"topics": "rust", "at": "7:30"})
    name = res["flow"]["name"]
    trig = store.flow_triggers(name)[0]
    task = [t for t in store.list_tasks() if t["id"] == trig["task_id"]][0]
    assert task["schedule_type"] == "daily" and task["at_time"] == "07:30"
    assert task["flow"] == name
    assert res["next_run"] == task["next_run"]


def test_two_jobs_from_one_recipe_get_distinct_names(store, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    n1 = jobs.install(CFG_PLAIN, store, "folder-watch", {"folder": str(a)})["flow"]["name"]
    n2 = jobs.install(CFG_PLAIN, store, "folder-watch", {"folder": str(b)})["flow"]["name"]
    assert n1 != n2 and {n1, n2} <= {f["name"] for f in store.list_flows()}


def test_installed_lists_only_jobs_not_every_flow(store):
    from agentos import flows as flowsmod
    flowsmod.save(store, {"name": "by-hand", "mission": "x", "roster": ["researcher"],
                          "permissions": {}})
    jobs.install(CFG_PLAIN, store, "morning-brief", {"topics": "rust"})
    assert [j["recipe"] for j in jobs.installed(store)] == ["morning-brief"]


def test_a_job_edited_and_re_saved_stays_a_job(store):
    """The recipe id lives on the row, so renaming a job in the editor does not
    orphan it from the list of things this machine is doing for you."""
    from agentos import flows as flowsmod
    name = jobs.install(CFG_PLAIN, store, "morning-brief", {"topics": "rust"})["flow"]["name"]
    flow = store.get_flow(name)
    flowsmod.save(store, {**flow, "mission": flow["mission"] + " Also mention the weather."})
    assert [j["recipe"] for j in jobs.installed(store)] == ["morning-brief"]


@pytest.mark.parametrize("recipe,answers,expect", [
    # "in about …" and not "hours": a daily job installed 64 minutes before its
    # fire hour truthfully says "in about 64 minutes", so pinning the unit made
    # this test red every day between 06:30 and 08:00 UTC. The promise being
    # tested is that the sentence is CONCRETE, not which unit it lands on.
    ("morning-brief", {"topics": "rust"}, "in about"),
    ("page-watch", {"url": "https://x.dev", "minutes": "30"}, "minutes"),
    ("folder-watch", None, "lands in that folder"),
])
def test_a_fresh_job_says_when_it_will_prove_itself(store, tmp_path, recipe, answers, expect):
    answers = {"folder": str(tmp_path)} if answers is None else answers
    name = jobs.install(CFG_PLAIN, store, recipe, answers)["flow"]["name"]
    assert expect in jobs.describe_next(store, name)


def test_the_roster_is_seeded_on_a_machine_that_never_ran_a_server(tmp_path):
    """`bento job add` over SSH on a fresh Pi. Without this the first thing a new
    user sees is 'no subagent named researcher', which is true and useless."""
    bare = Store(tmp_path / "bare.db")
    assert not bare.list_subagents()
    res = jobs.install(CFG_PLAIN, bare, "morning-brief", {"topics": "rust"})
    assert res["ok"] and {"researcher", "writer"} <= {s["name"] for s in bare.list_subagents()}


# ---------------------------------------------------------------------------
# End to end: the scheduler really starts it
# ---------------------------------------------------------------------------

class _FakeFabric:
    def __init__(self):
        self.calls = []

    async def run_flow(self, flow, text, **kw):
        self.calls.append((flow["name"], text, kw))
        return {"run_id": "r1", "content": "one page, as promised", "status": "ok"}


def test_a_job_installed_by_the_wizard_is_started_by_the_scheduler(tmp_path):
    """The whole promise, end to end: install exactly as the first-run screen does,
    wind the clock back, run one tick of the real scheduler loop, and assert the
    flow was started — and then rescheduled for tomorrow rather than left to
    re-fire in a loop."""
    cfg = {"autonomy": "balanced", "workspace": str(tmp_path), "providers": {}}
    store = Store(tmp_path / "e2e.db")
    events: list = []

    async def broadcast(ev):
        events.append(ev)

    sched = Scheduler(cfg, store, Toolbox(cfg, store), broadcast)
    sched.fabric = _FakeFabric()

    name = jobs.install(cfg, store, "morning-brief",
                        {"topics": "rust releases", "at": "07:30",
                         "deliver": "report"})["flow"]["name"]
    trig = store.flow_triggers(name)[0]
    tid = trig["task_id"]
    assert tid, "a daily job must have a clock row"

    # due, as it will be at 07:30 tomorrow
    store.update_task(tid, next_run=time.time() - 1)

    async def one_tick():
        for task in store.due_tasks(time.time()):
            store.update_task(task["id"], next_run=None)
            await sched._run_task(task, origin="schedule")

    asyncio.run(one_tick())

    assert [c[0] for c in sched.fabric.calls] == [name]
    assert sched.fabric.calls[0][2]["origin"]["surface"] == "task"
    assert {e["type"] for e in events} >= {"task_started", "task_finished"}

    after = [t for t in store.list_tasks() if t["id"] == tid][0]
    assert after["next_run"] > time.time(), "a daily job must be rearmed, not left due"
    assert "one page" in (after["last_result"] or "")


def test_a_disabled_job_is_a_job_that_does_not_fire(tmp_path):
    """Turning a job off has to take its clock away, not just its permissions —
    otherwise the scheduler wakes it every morning to be refused."""
    from agentos import flows as flowsmod
    store = Store(tmp_path / "off.db")
    name = jobs.install(CFG_PLAIN, store, "morning-brief",
                        {"topics": "rust"})["flow"]["name"]
    flowsmod.set_enabled(store, name, False)
    assert not [t for t in store.list_tasks() if t["flow"] == name]
    assert not [g for g in store.list_grants()
                if (g.get("source_ref") or "") == f"flow:{name}"]
    # and the declaration survives, so switching it back on restores what was written
    assert store.flow_triggers(name)
    flowsmod.set_enabled(store, name, True)
    assert [t for t in store.list_tasks() if t["flow"] == name]


# ---------------------------------------------------------------------------
# The HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        s = servermod.state["store"]
        for table in ("flows", "flow_triggers", "fabric_runs", "grants", "tasks", "logs"):
            s.db.execute(f"DELETE FROM {table}")
        s.db.commit()
        s.grants_version += 1
        yield c


def test_the_first_run_screen_gets_everything_it_needs_in_one_request(client):
    """Three waves of fetch is three frames of flicker on the screen that is
    supposed to be somebody's first impression."""
    d = client.get("/api/jobs").json()
    assert {r["id"] for r in d["recipes"]} == {r.id for r in jobs.RECIPES}
    assert {w["id"] for w in d["deliveries"]} == {"report", "notify", "telegram", "whatsapp"}
    assert d["installed"] == []


def test_preview_over_http_answers_with_the_grants_not_a_500(client, tmp_path):
    r = client.post("/api/jobs/preview",
                    json={"recipe": "folder-watch", "answers": {"folder": str(tmp_path)}})
    assert r.status_code == 200
    assert r.json()["reads"] == [str(tmp_path) + "/*"]


def test_a_bad_answer_comes_back_as_a_sentence_and_a_400(client):
    r = client.post("/api/jobs/preview",
                    json={"recipe": "folder-watch", "answers": {"folder": "/no/such"}})
    assert r.status_code == 400 and "no folder at" in r.json()["error"]


def test_installing_over_http_makes_it_appear_in_the_list(client):
    r = client.post("/api/jobs", json={"recipe": "morning-brief",
                                       "answers": {"topics": "rust", "at": "07:30"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["next"]
    listed = client.get("/api/jobs").json()["installed"]
    assert [j["name"] for j in listed] == [body["flow"]["name"]]


def test_running_a_job_that_does_not_exist_is_a_404_not_a_crash(client):
    assert client.post("/api/jobs/nope/run").status_code == 404
