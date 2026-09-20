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
# both accounts set up and tested, so every recipe in the catalogue can be built
CFG_ACCOUNTS = {"mail": {"enabled": True, "host": "imap.example.com", "port": 993, "user": "me@example.com",
                         "password": "app-pass", "last_test": {"ok": True, "detail": "signed in"}},
                "calendar": {"enabled": True, "kind": "ics", "url": "https://example.com/basic.ics",
                             "last_test": {"ok": True, "detail": "3 events"}}}


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
    ("nope", {}, "no mission recipe"),
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
    ("morning-brief", {"topics": "rust"}, "hours"),
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


# ---------------------------------------------------------------------------
# Missions: who is asking, and a catalogue that is honest about what it can do
# ---------------------------------------------------------------------------

def test_every_recipe_names_only_tools_this_machine_has():
    """A recipe granting a tool that does not exist is a mission that fails at its
    first step with a sentence the user cannot act on."""
    from agentos.tools import TOOL_SCHEMAS
    known = {t["name"] for t in TOOL_SCHEMAS}
    for r in jobs.RECIPES:
        missing = [t for t in r.tools if t not in known]
        assert not missing, f"{r.id} names tools that do not exist: {missing}"


def test_every_recipe_s_specialists_exist_after_ensure_roster_and_hold_its_tools(store):
    """The flow grants the roster the recipe's tools — but a subagent only USES the
    tools on its own list, so a recipe whose specialist lacks `git_log` would be
    granted git and never call it. Both halves have to agree, per recipe."""
    jobs.ensure_roster({}, store)
    for r in jobs.RECIPES:
        union: set = set()
        for name, _why in r.roster:
            sub = store.get_subagent(name)
            assert sub, f"{r.id} rosters '{name}', which does not exist after ensure_roster"
            union |= set(sub.get("tools") or [])
        gap = [t for t in r.tools if t not in union and t != "save_report"]
        assert not gap, f"{r.id} grants {gap} but none of its specialists can call them"


def test_ensure_roster_creates_the_catalogue_s_specialists_once_and_never_overwrites(store):
    """`seed_builtins` returns early once ANY subagent exists, so a machine that has
    run for a year would never get `engineer` from it. And an engineer somebody
    designed must survive — a catalogue must not rewrite a person's agent."""
    made = jobs.ensure_roster({}, store)
    assert set(made) == {"engineer", "analyst", "watcher", "assistant"}
    assert jobs.ensure_roster({}, store) == []
    store.save_subagent({"name": "engineer", "soul": "MINE", "tools": ["read_file"]})
    jobs.ensure_roster({}, store)
    assert store.get_subagent("engineer")["soul"] == "MINE"


def test_a_recipe_that_remembers_runs_with_a_memory_it_may_write(store):
    """The first cut of page-watch granted `remember` under memory='read-space',
    which declares a memory.write DENY for the roster — so every write was refused
    and 'compare with last time' compared against nothing. A recipe that uses
    `remember` must not carry that deny."""
    jobs.ensure_roster({}, store)
    for r in jobs.RECIPES:
        if "remember" not in r.tools:
            continue
        body = jobs.build(CFG_ACCOUNTS, store, r.id, _answers_for(r, store))
        d = jobs.flowsmod.validate(body, store)
        denies = [g for g in jobs.flowsmod.declared_grants(d)
                  if g["action"] == "memory.write" and g["effect"] == "deny"]
        assert not denies, f"{r.id} uses remember but its memory scope denies writes"


def _answers_for(r, store, tmp=None):
    """Plausible answers for any recipe, so every one can be built in a test."""
    import tempfile
    folder = tmp or tempfile.mkdtemp(prefix="agentos-job-")
    a = {"deliver": "report"}
    for n in r.needs:
        a.setdefault(n.key, {"folder": folder, "url": "https://example.com/p",
                             "urls": "https://a.example/x\nhttps://b.example/y",
                             "names": "Acme\nBolt", "client": "Acme", "topics": "rust",
                             "at": "08:00", "day": "friday", "minutes": "60"}.get(n.key, "x"))
    return a


def test_every_recipe_builds_previews_and_installs(store):
    """The whole catalogue, end to end: each recipe becomes a valid flow with at
    least one trigger, its grants preview cleanly, and it installs enabled."""
    for r in jobs.RECIPES:
        body = jobs.build(CFG_ACCOUNTS, store, r.id, _answers_for(r, store))
        assert body["job"] == r.id and body["enabled"] == 1 and body["triggers"], r.id
        assert "{" not in body["mission"], f"{r.id} left a placeholder unfilled"
        p = jobs.preview(CFG_ACCOUNTS, store, r.id, _answers_for(r, store))
        assert p["grants"], r.id
        res = jobs.install(CFG_ACCOUNTS, store, r.id, _answers_for(r, store))
        assert res["ok"] and store.get_flow(res["flow"]["name"])["enabled"]


def test_the_personas_are_a_closed_set_and_every_recipe_belongs_to_one():
    ids = {p["id"] for p in jobs.PERSONAS}
    assert ids == {"founder", "coder", "consultant", "everyone"}
    for r in jobs.RECIPES:
        assert r.for_ and set(r.for_) <= ids, r.id
    # each persona has missions written FOR it — a persona with none is a chip that
    # filters the catalogue to somebody else's list
    for p in ("founder", "coder", "consultant"):
        assert sum(1 for r in jobs.RECIPES if p in r.for_) >= 3, p


def test_a_persona_reorders_the_catalogue_and_never_shortens_it():
    """Theirs first, then everybody's, then the rest — the WHOLE catalogue, because
    a consultant who also writes code must be able to reach the coder's missions."""
    for p in ("founder", "coder", "consultant"):
        rows = jobs.recipes_for(p)
        assert {r.id for r in rows} == {r.id for r in jobs.RECIPES}
        first = [r for r in rows if p in r.for_]
        assert rows[:len(first)] == first, f"{p}'s missions are not first"
    assert [r.id for r in jobs.recipes_for("")] == [r.id for r in jobs.RECIPES]


def test_a_persona_is_recorded_per_person_and_refused_when_unknown():
    from agentos import users as usersmod
    assert "persona" in usersmod.USER_KEYS       # it is about the person, not the machine
    cfg = {}
    assert jobs.set_persona(cfg, "Founder") == "founder" and jobs.persona_of(cfg) == "founder"
    assert jobs.set_persona(cfg, "") == "" and jobs.persona_of(cfg) == ""
    with pytest.raises(ValueError, match="not one of"):
        jobs.set_persona(cfg, "wizard")


def test_the_web_a_mission_may_reach_is_exactly_the_addresses_it_was_given(store):
    """A competitor watch is granted its three pages, not the open web; a news watch
    is granted the news feed and nothing else."""
    body = jobs.build(CFG_PLAIN, store, "competitor-watch",
                      {"urls": "https://acme.com/pricing\nhttps://acme.com/changelog", "at": "08:00"})
    assert body["permissions"]["net"] == ["https://acme.com/pricing", "https://acme.com/changelog"]
    assert "- https://acme.com/pricing" in body["mission"]
    news = jobs.build(CFG_PLAIN, store, "news-watch", {"names": "Acme Corp, Bolt"})
    assert news["permissions"]["net"] == [jobs.NEWS_NET]
    assert "q=Acme+Corp" in news["mission"] and "Bolt" in news["mission"]
    with pytest.raises(ValueError, match="one per line"):
        jobs.build(CFG_PLAIN, store, "competitor-watch", {"urls": ""})


def test_a_weekly_mission_lands_on_the_day_it_was_asked_for(store, tmp_path):
    body = jobs.build(CFG_PLAIN, store, "investor-update",
                      {"folder": str(tmp_path), "day": "monday", "at": "16:00"})
    trig = [t for t in body["triggers"] if t["kind"] == "cron"][0]
    assert trig["config"] == {"type": "weekly", "at": "16:00", "day": 0}
    res = jobs.install(CFG_PLAIN, store, "investor-update",
                       {"folder": str(tmp_path), "day": "monday", "at": "16:00"})
    assert "day" in res["flow"]["name"] or res["flow"]["name"].startswith("investor-update")
    assert jobs.describe_next(store, res["flow"]["name"])


def test_the_coder_missions_read_the_code_folder_and_nothing_above_it(store, tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    for rid in ("standup", "nightly-review", "test-guard"):
        body = jobs.build(CFG_PLAIN, store, rid, {"folder": str(code), "at": "09:00"})
        assert body["permissions"]["fs_read"] == [str(code) + "/*"], rid
        assert body["permissions"]["fs_write"] == [], f"{rid} must never be able to write"
        assert not [t for t in body["triggers"] if t["kind"] == "os_event"], \
            f"{rid} is on the clock, not on every file save"


def test_installed_says_what_each_mission_did_and_summary_agrees(store, tmp_path):
    """The value surface: last outcome in words, this week's runs and tokens, and
    the permissions it holds — with the header derived from the same rows."""
    name = jobs.install(CFG_PLAIN, store, "morning-brief",
                        {"topics": "rust", "at": "07:30"})["flow"]["name"]
    rid = store.fabric_run_start("flow", name, "go", flow=name)
    store.fabric_run_finish(rid, "ok", output="Tuesday: two things moved.", tokens_in=900,
                            tokens_out=100)
    bad = store.fabric_run_start("flow", name, "go", flow=name)
    store.fabric_run_finish(bad, "error", fault="model refused", tokens_in=50)
    row = jobs.installed(store)[0]
    assert row["title"] == "Brief me every morning"
    assert row["last"]["status"] == "error" and "model refused" in row["last"]["said"]
    assert row["runs_7d"] == 2 and row["ok_7d"] == 1 and row["tokens_7d"] == 1050
    assert row["grants"] >= 1
    s = jobs.summary(store)
    assert s == {"missions": 1, "enabled": 1, "runs_7d": 2, "ok_7d": 1, "failed_7d": 1,
                 "tokens_7d": 1050, "grants": row["grants"]}


def test_the_persona_route_reorders_the_catalogue_over_http(client):
    d = client.get("/api/jobs").json()
    assert {p["id"] for p in d["personas"]} == {"founder", "coder", "consultant", "everyone"}
    assert "summary" in d and d["summary"]["missions"] == 0
    r = client.put("/api/jobs/persona", json={"persona": "coder"})
    assert r.status_code == 200 and r.json()["persona"] == "coder"
    first = client.get("/api/jobs").json()["recipes"][0]
    assert "coder" in first["for"]
    assert client.put("/api/jobs/persona", json={"persona": "wizard"}).status_code == 400
    client.put("/api/jobs/persona", json={"persona": ""})


def test_readiness_says_when_the_brain_cannot_run_a_mission():
    """Found on a machine whose brain was Claude Code with no provider: every
    mission's row said 'ConnectError'. A flow runs on the built-in loop only, so
    the surface has to say so BEFORE the Run button, with the fix."""
    ok = jobs.readiness({"default_model": "ollama/qwen3:8b",
                         "providers": {"ollama": {"enabled": True}}, "engine": "aria"})
    assert ok["ok"] and ok["model"] == "ollama/qwen3:8b" and not ok["fix"]
    none = jobs.readiness({"default_model": "", "providers": {}, "engine": "aria"})
    assert none["ok"] is False and "No provider model" in none["note"] and "AI providers" in none["fix"]
    off = jobs.readiness({"default_model": "openai/gpt-4o",
                          "providers": {"openai": {"enabled": False}}, "engine": "aria"})
    assert off["ok"] is False and "not enabled" in off["note"]
