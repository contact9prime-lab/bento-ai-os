"""Onboarding: the arc, and the three rules that keep it honest.

The claim this defends is that setup can be re-run on day 300 and tell the truth.
That only works if every step is PROBED — so most of these tests are about a step
going green because the thing exists, and going back to todo when it stops existing.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric as fabricmod                            # noqa: E402
from agentos import flows as flowsmod                              # noqa: E402
from agentos import onboarding as ob                               # noqa: E402
from agentos.memory import Store                                   # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "ob.db")


def by_id(st):
    return {s["id"]: s for s in st["steps"]}


# ---------------------------------------------------------------------------
# The shape of the arc
# ---------------------------------------------------------------------------

def test_every_step_says_what_it_will_produce():
    """The line that turns 'fill in a field' into 'here is what you will have'.
    A step without one is a step nobody has a reason to complete."""
    for s in ob.STEPS:
        assert s.produces.strip(), s.id
        assert s.blurb.strip(), s.id


def test_the_account_step_is_last_because_the_first_one_inherits_everything(store):
    """Asking "who are you?" first would mean asking it of a machine that does not
    yet do anything, and then handing the result to an account nobody had a reason
    to want. So it comes after there is something worth owning."""
    assert ob.STEPS[-1].id == "account"
    assert ob.BY_ID["account"].optional


def test_an_account_ticks_the_step_and_removing_it_unticks_it(store, tmp_path,
                                                              monkeypatch):
    from agentos import config as cfgmod
    from agentos import users as usersmod
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path / "m")
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "m" / "config.json")
    usersmod.reset_caches()
    assert by_id(ob.state({}, store))["account"]["status"] == "todo"
    u = usersmod.create("ada", "hunter2hunter")
    assert by_id(ob.state({}, store))["account"]["status"] == "done"
    usersmod.registry_path().unlink()
    assert by_id(ob.state({}, store))["account"]["status"] == "todo"
    usersmod.reset_caches()


def test_the_two_steps_the_machine_cannot_work_without_are_not_skippable():
    assert not ob.BY_ID["name"].optional
    assert not ob.BY_ID["model"].optional
    assert all(s.optional for s in ob.STEPS if s.id not in ("name", "model"))


def test_prerequisites_point_at_steps_that_exist():
    for s in ob.STEPS:
        for n in s.needs:
            assert n in ob.BY_ID, f"{s.id} needs unknown step {n!r}"


def test_a_step_whose_prerequisite_is_missing_is_not_offered(store):
    st = ob.state({}, store)
    assert by_id(st)["flow"]["blocked"] == ["agent"]
    assert st["next"] == "name", "the next thing to do is never a blocked step"


# ---------------------------------------------------------------------------
# Probed, never remembered
# ---------------------------------------------------------------------------

def test_a_fresh_machine_has_nothing_done(store):
    st = ob.state({}, store)
    assert st["done"] == 0
    assert not st["finished"]
    assert all(s["status"] == "todo" for s in st["steps"])


def test_the_shipped_default_name_is_not_evidence_anybody_chose_it(store):
    assert by_id(ob.state({"agent_name": "Aria"}, store))["name"]["status"] == "todo"
    assert by_id(ob.state({"agent_name": "Bento"}, store))["name"]["status"] == "done"


def test_the_seeded_agents_and_flow_do_not_tick_their_steps(store):
    """A step ticked by something the installer put there teaches nothing and skips
    the one moment that explains what a specialist or a flow is."""
    fabricmod.seed_builtins({}, store)
    flowsmod.seed_builtin(store)
    st = by_id(ob.state({}, store))
    assert st["agent"]["status"] == "todo", "researcher/writer are shipped, not chosen"
    assert st["flow"]["status"] == "todo", "daily-briefing is shipped, not chosen"


def test_building_an_agent_ticks_the_step(store):
    store.save_subagent({"name": "mine", "soul": "x"})
    assert by_id(ob.state({}, store))["agent"]["status"] == "done"


def test_deleting_the_thing_untick_the_step(store):
    """The whole reason for probing: a stored flag would still say done, and setup
    would lie to the next person who opened it."""
    sid = store.save_subagent({"name": "mine", "soul": "x"})
    assert by_id(ob.state({}, store))["agent"]["status"] == "done"
    store.delete_subagent(sid)
    assert by_id(ob.state({}, store))["agent"]["status"] == "todo"


def test_a_conversation_is_the_evidence_that_the_model_answered(store):
    assert by_id(ob.state({}, store))["hello"]["status"] == "todo"
    store.create_conversation("first")
    assert by_id(ob.state({}, store))["hello"]["status"] == "done"


def test_a_scheduled_task_ticks_the_schedule_step(store):
    import time
    assert by_id(ob.state({}, store))["schedule"]["status"] == "todo"
    store.add_task("do it", "daily", None, "08:00", time.time() + 60)
    assert by_id(ob.state({}, store))["schedule"]["status"] == "done"


@pytest.mark.parametrize("cfg,expect", [
    ({}, "todo"),
    ({"telegram": {"enabled": True, "bot_token": "t"}}, "todo"),          # nobody paired
    ({"telegram": {"enabled": True, "bot_token": "t", "owner_chat_id": 1}}, "done"),
])
def test_a_channel_counts_only_when_it_would_reach_somebody(store, cfg, expect):
    """Configured and working are different things, and the step is about the second:
    a bot token with no paired chat reaches no one."""
    assert by_id(ob.state(cfg, store))["channel"]["status"] == expect


def test_the_model_step_accepts_a_provider_without_a_default_model(store):
    """Half-configured is still progress, and saying so beats sending somebody back
    to a step they already did."""
    cfg = {"providers": {"anthropic": {"enabled": True, "api_key": "sk-x"}}}
    s = by_id(ob.state(cfg, store))["model"]
    assert s["status"] == "done" and "no default model" in s["detail"]


# ---------------------------------------------------------------------------
# Skipping is a decision, and it is the one thing that IS remembered
# ---------------------------------------------------------------------------

def test_skipping_is_stored_because_it_cannot_be_probed(store):
    """An unpaired channel and a channel somebody decided against look identical
    from the machine's point of view."""
    cfg: dict = {}
    ob.skip(cfg, "channel")
    st = by_id(ob.state(cfg, store))
    assert st["channel"]["status"] == "skipped"
    assert cfg["onboarding"]["skipped"] == ["channel"]


def test_a_skipped_step_does_not_show_a_tick(store):
    """Pretending it was completed is how somebody ends up hunting for a channel
    they never set up."""
    cfg: dict = {}
    ob.skip(cfg, "channel")
    st = ob.state(cfg, store)
    assert st["done"] == 0
    assert st["finished"] is False or by_id(st)["channel"]["status"] == "skipped"


def test_a_required_step_cannot_be_skipped(store):
    with pytest.raises(ValueError) as e:
        ob.skip({}, "model")
    assert "cannot work without" in str(e.value)


def test_unskipping_offers_it_again(store):
    cfg: dict = {}
    ob.skip(cfg, "look")
    ob.unskip(cfg, "look")
    assert by_id(ob.state(cfg, store))["look"]["status"] == "todo"


def test_everything_answered_counts_as_finished(store):
    cfg = {"agent_name": "Bento", "default_model": "ollama/x",
           "telegram": {"enabled": True, "bot_token": "t", "owner_chat_id": 1},
           "desktop": {"theme": "bento"}}
    # A machine that stays single-user is a finished machine, not an unfinished
    # one — which is the whole reason the account step is optional.
    ob.skip(cfg, "account")
    # Same shape: a machine that built everything itself never forked anybody's
    # agent, and that is a finished life for the step, said deliberately.
    ob.skip(cfg, "fork")
    store.create_conversation("hi")
    store.save_app("Scratchpad", "", "notes that stay", "<p>notes</p>")
    store.save_subagent({"name": "mine"})
    flowsmod.save(store, {"name": "f", "mission": "m", "roster": ["mine"],
                          "permissions": {}})
    import time
    store.add_task("x", "daily", None, "08:00", time.time() + 60)
    assert ob.state(cfg, store)["finished"] is True


# ---------------------------------------------------------------------------
# Re-running
# ---------------------------------------------------------------------------

def test_restarting_setup_does_not_wipe_anything(store):
    """'Run setup again' almost always means 'I want to change something and cannot
    remember where it lives'. Answering that by deleting their memory would be a
    catastrophe with a friendly button."""
    store.save_subagent({"name": "mine"})
    store.create_conversation("keep me")
    cfg = {"agent_name": "Bento", "setup_complete": True}
    ob.restart(cfg)
    assert cfg["setup_complete"] is False
    assert store.list_subagents(), "agents must survive"
    assert store.list_conversations(), "conversations must survive"
    # and the steps already satisfied still read as done
    assert by_id(ob.state(cfg, store))["agent"]["status"] == "done"


def test_restarting_offers_previously_skipped_steps_again(store):
    cfg: dict = {}
    ob.skip(cfg, "channel")
    ob.restart(cfg)
    assert by_id(ob.state(cfg, store))["channel"]["status"] == "todo"


def test_every_optional_step_says_where_it_lives_afterwards_or_is_self_contained():
    """A wizard that is the only way to reach a setting is a wizard people are
    afraid to leave. Steps with no panel create a thing (an agent, a flow, a job)
    that has its own app."""
    homeless = [s.id for s in ob.STEPS if not s.panel]
    assert set(homeless) <= {"agent", "flow", "schedule"}, homeless


# ---------------------------------------------------------------------------
# What the steps create
# ---------------------------------------------------------------------------

def test_the_starter_agent_does_not_overwrite_one_you_already_have(store):
    a = ob.starter_agent(store)
    store.save_subagent(a)
    b = ob.starter_agent(store)
    assert b["name"] != a["name"], "running setup twice must not silently overwrite"


def test_the_starter_flow_is_rostered_with_the_agent_that_was_just_made(store):
    store.save_subagent({"name": "researcher-plus", "soul": "x"})
    f = ob.starter_flow(store, ["researcher-plus"])
    assert f["roster"][0]["subagent"] == "researcher-plus"
    flow, report = flowsmod.save(store, f)
    assert flow["enabled"] and report["grants"]["added"] > 0


def test_the_starter_flow_only_asks_for_what_it_uses(store):
    """The first flow somebody sees is also the first permission screen somebody
    reads. It should not be asking for the machine."""
    perms = ob.STARTER_FLOW["permissions"]
    assert "run_command" not in perms["tools"]
    assert not perms.get("fs_write")
    assert perms["memory"] == "read-space"


# ---------------------------------------------------------------------------
# The HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture()
def api():
    from fastapi.testclient import TestClient

    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        s = servermod.state["store"]
        for t in ("subagents", "flows", "conversations", "tasks", "grants"):
            s.db.execute(f"DELETE FROM {t}")
        s.db.commit()
        yield c, servermod.state


def test_the_state_route_answers_with_the_whole_arc(api):
    c, _ = api
    d = c.get("/api/onboarding").json()
    assert {s["id"] for s in d["steps"]} == {s.id for s in ob.STEPS}
    assert d["total"] == len(ob.STEPS)


def test_skipping_over_http_comes_back_with_fresh_state(api):
    c, _ = api
    d = c.post("/api/onboarding/skip", json={"step": "channel"}).json()
    assert by_id(d)["channel"]["status"] == "skipped"


def test_skipping_a_required_step_over_http_is_a_400(api):
    c, _ = api
    assert c.post("/api/onboarding/skip", json={"step": "name"}).status_code == 400


def test_creating_the_agent_over_http_makes_a_real_one(api):
    c, st = api
    d = c.post("/api/onboarding/agent", json={}).json()
    assert d["ok"] and st["store"].get_subagent(d["agent"]["name"])


def test_creating_a_flow_before_an_agent_refuses_with_the_reason(api):
    c, st = api
    for s in st["store"].list_subagents():
        st["store"].delete_subagent(s["id"])
    r = c.post("/api/onboarding/flow", json={})
    assert r.status_code == 400 and "build an agent first" in r.json()["error"]


def test_the_flow_route_rosters_the_agent_that_exists(api):
    c, st = api
    c.post("/api/onboarding/agent", json={})
    d = c.post("/api/onboarding/flow", json={}).json()
    assert d["ok"] and d["flow"]["roster"]


def test_hello_without_a_model_says_so_rather_than_failing_obscurely(api):
    c, st = api
    st["cfg"]["default_model"] = ""
    r = c.post("/api/onboarding/hello", json={})
    assert r.status_code == 400 and "no model" in r.json()["error"]


def test_a_config_written_before_setup_finishes_does_not_skip_onboarding():
    """`is_first_run()` reads the RAW file, so anything calling save_config() early
    used to leave a config with no key at all — which the grandfather clause reads
    as 'an old install, already set up'. Seeding it in DEFAULTS says so out loud."""
    from agentos import config as cfgmod
    assert cfgmod.DEFAULTS.get("setup_complete") is False


def test_a_machine_that_is_not_set_up_says_so_when_the_server_starts(monkeypatch, capsys):
    """The browser wizard opens itself; the headless half had nothing.

    On a machine nobody is sitting in front of, "it is set up when you open it" is
    not true — there is no browser to open it in, and the arc's terminal entry point
    (`bento setup`) was named only in the last lines of the installer, minutes of log
    scroll earlier. It belongs next to the URL, on every start, until it is done.
    """
    import uvicorn

    from agentos import __main__ as cli
    from agentos import config as cfgmod

    monkeypatch.setattr(cli, "_bind_problem", lambda h, p: ("free", ""))
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)

    monkeypatch.setattr(cfgmod, "is_first_run", lambda: True)
    cli.serve("127.0.0.1", 8399, False, "fail")
    assert "bento setup" in capsys.readouterr().out

    monkeypatch.setattr(cfgmod, "is_first_run", lambda: False)
    cli.serve("127.0.0.1", 8399, False, "fail")
    assert "bento setup" not in capsys.readouterr().out, (
        "a machine that has been set up is still being told to set itself up")
