"""Users: several people on one machine, and the claim is complete isolation.

Almost every test here is one shape — do a thing as A, prove B cannot see it. That
is deliberate. `space_id` is a column and its rule is deliberately leaky; users are
the opposite claim, and the only way to keep making it is to keep testing it from
both sides.

The other half is the seam. `state["store"]` is read in ~250 places and none of
them were changed, so what has to be proved is that the LOOKUP resolves — that a
service built once at startup reads the right person's data at request time.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod                                # noqa: E402
from agentos import users as usersmod                               # noqa: E402


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """A whole machine in a temp directory. Both modules have to be pointed at it:
    `users` derives every path from `config.AGENTOS_HOME`."""
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    usersmod.reset_caches()
    usersmod.set_current("")
    yield tmp_path
    usersmod.reset_caches()
    usersmod.set_current("")


@pytest.fixture()
def two(home):
    a = usersmod.create("ada", "hunter2hunter", role="admin")
    b = usersmod.create("bob", "hunter2hunter", role="executor")
    return a, b


# ---------------------------------------------------------------------------
# Off until you need it
# ---------------------------------------------------------------------------

def test_a_machine_with_nobody_added_is_not_a_multi_user_machine(home):
    """The whole module has to be invisible until somebody wants it: an install
    that never adds a user keeps using exactly the files it always used."""
    assert usersmod.enabled() is False
    assert usersmod.current() == ""
    assert usersmod.home_for("") == home


def test_the_only_user_of_a_single_user_machine_is_its_admin(home):
    """Getting this backwards locks somebody out of their own laptop the moment
    the module ships."""
    assert usersmod.is_admin("") is True


def test_adding_somebody_turns_it_on(two):
    assert usersmod.enabled() is True
    assert [u["name"] for u in usersmod.list_users()] == ["ada", "bob"]


def test_the_first_account_is_an_admin_whatever_was_asked_for(home):
    """A machine whose only account cannot administer it is a machine nobody can
    administer, and there is no second account to fix it from."""
    u = usersmod.create("solo", "hunter2hunter", role="executor")
    assert u["role"] == "admin"


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

def test_two_users_do_not_share_a_database(two):
    a, b = two
    assert usersmod.db_for(a["id"]) != usersmod.db_for(b["id"])
    usersmod.store_for(a["id"]).save_subagent({"name": "ada-secret", "soul": "x"})
    assert usersmod.store_for(a["id"]).get_subagent("ada-secret")
    assert usersmod.store_for(b["id"]).get_subagent("ada-secret") is None


def test_memory_does_not_cross(two):
    a, b = two
    usersmod.store_for(a["id"]).create_conversation("my divorce")
    assert usersmod.store_for(a["id"]).list_conversations()
    assert usersmod.store_for(b["id"]).list_conversations() == []


def test_grants_do_not_cross(two):
    """The one that matters most: a permission is a per-user fact, and the PDP
    reads it from a per-user table."""
    a, b = two
    usersmod.store_for(a["id"]).add_grant("app", "notes", "tool.use", "run_command")
    mine = lambda uid: [g for g in usersmod.store_for(uid).grants_live()
                        if g["principal_id"] == "notes"]
    assert mine(a["id"])
    assert mine(b["id"]) == []


def test_a_new_account_gets_the_same_starting_agents_a_fresh_install_does(two):
    """Otherwise a new person opens Workflows to an empty list, on a machine that
    demonstrably has specialists — belonging to somebody else."""
    _, b = two
    names = {s["name"] for s in usersmod.store_for(b["id"]).list_subagents()}
    assert {"researcher", "writer"} <= names


def test_the_first_account_is_not_re_seeded_over_what_it_inherited(home):
    (home / "agentos.db").write_bytes(b"not-a-database")
    u = usersmod.create("ada", "hunter2hunter")
    assert (usersmod.home_for(u["id"]) / "agentos.db").read_bytes() == b"not-a-database"


def test_a_seeded_agent_still_does_not_tick_the_onboarding_step(two):
    """A step ticked by something the installer put there teaches nothing and skips
    the one moment that explains what a specialist is."""
    from agentos import onboarding as ob
    _, b = two
    st = {s["id"]: s for s in ob.state({}, usersmod.store_for(b["id"]))["steps"]}
    assert st["agent"]["status"] == "todo" and st["flow"]["status"] == "todo"


def test_a_users_home_is_private_on_disk(two):
    a, _ = two
    assert (usersmod.home_for(a["id"]).stat().st_mode & 0o777) == 0o700


def test_a_users_config_is_not_world_readable(two):
    """It holds their channel tokens and their credentials."""
    a, _ = two
    assert (usersmod.cfg_path_for(a["id"]).stat().st_mode & 0o777) == 0o600


def test_the_registry_is_not_world_readable(two):
    assert (usersmod.registry_path().stat().st_mode & 0o777) == 0o600


# ---------------------------------------------------------------------------
# Config: what is mine, what is the machine's
# ---------------------------------------------------------------------------

def test_a_user_sees_the_machines_provider_keys(two):
    """Settings are shared on purpose — one API key for the machine, not one per
    person who would each have to go and get one."""
    machine = cfgmod.load_config()
    machine["providers"]["anthropic"] = {"enabled": True, "api_key": "sk-machine"}
    cfgmod.save_config(machine)
    a, _ = two
    assert usersmod.cfg_for(a["id"])["providers"]["anthropic"]["api_key"] == "sk-machine"


def test_channels_do_not_cross(two):
    a, b = two
    ca = usersmod.cfg_for(a["id"])
    ca.setdefault("telegram", {})["bot_token"] = "ada-token"
    usersmod.save_user_cfg(a["id"], ca)
    usersmod.reset_caches()
    assert usersmod.cfg_for(a["id"]).get("telegram", {}).get("bot_token") == "ada-token"
    assert usersmod.cfg_for(b["id"]).get("telegram", {}).get("bot_token") in ("", None)


def test_a_users_save_cannot_reach_the_machine_file(two):
    """Non-admins are refused at the route, but the storage layer must not depend
    on the route having remembered to check."""
    _, b = two
    with usersmod.as_user(b["id"]):
        cfg = usersmod.cfg_for(b["id"])
        cfg["providers"] = {"anthropic": {"api_key": "bob-stole-this"}}
        cfg["desktop"] = {"theme": "bento"}
        cfgmod.save_config(cfg)
    raw = json.loads(cfgmod.CONFIG_PATH.read_text()) if cfgmod.CONFIG_PATH.exists() else {}
    assert "bob-stole-this" not in json.dumps(raw)
    own = json.loads(usersmod.cfg_path_for(b["id"]).read_text())
    assert own["desktop"] == {"theme": "bento"}
    assert "providers" not in own


def test_an_admins_machine_save_does_not_carry_their_own_channels_into_it(two):
    """Everything in the machine file becomes the starting point for the next
    person created — a Telegram token left there is handed to a stranger."""
    a, _ = two
    with usersmod.as_user(a["id"]):
        cfg = usersmod.cfg_for(a["id"])
        cfg["telegram"] = {"bot_token": "ada-private"}
        cfg["providers"]["anthropic"] = {"api_key": "sk-shared"}
        cfgmod.save_config(cfg)
    raw = json.loads(cfgmod.CONFIG_PATH.read_text())
    assert "ada-private" not in json.dumps(raw)
    assert raw["providers"]["anthropic"]["api_key"] == "sk-shared"


def test_an_admin_change_reaches_everybody_without_a_restart(two):
    """A cached per-user config that never sees the new provider key reads as
    "the model does not work for me"."""
    a, b = two
    assert usersmod.cfg_for(b["id"])["providers"].get("openai", {}).get("api_key") in ("", None)
    with usersmod.as_user(a["id"]):
        cfg = usersmod.cfg_for(a["id"])
        cfg["providers"]["openai"] = {"enabled": True, "api_key": "sk-new"}
        cfgmod.save_config(cfg)
    assert usersmod.cfg_for(b["id"])["providers"]["openai"]["api_key"] == "sk-new"


def test_every_user_key_is_a_real_config_key_or_deliberately_new(home):
    """A typo in USER_KEYS is silent: the key simply never saves, and the setting
    appears to work until the next reload."""
    known = set(cfgmod.DEFAULTS) | {"whatsapp", "soul", "onboarding", "credentials",
                                    "spaces", "shortcuts"}
    assert set(usersmod.USER_KEYS) <= known


def test_a_new_user_starts_at_the_beginning_of_onboarding(two):
    """The arc is personal — name your agent, say hello to it, choose a look. A
    new account landing in somebody else's finished desktop skips all of it."""
    _, b = two
    with usersmod.as_user(b["id"]):
        assert cfgmod.is_first_run() is True


# ---------------------------------------------------------------------------
# Their own files
# ---------------------------------------------------------------------------

def test_a_soul_is_not_shared(two):
    a, b = two
    with usersmod.as_user(a["id"]):
        cfgmod.save_soul("# Ada's agent\nterse")
        assert "Ada's agent" in cfgmod.load_soul()
    with usersmod.as_user(b["id"]):
        assert "Ada's agent" not in cfgmod.load_soul()


def test_a_gallery_is_not_shared(two):
    from agentos import assets as assetmod
    a, b = two
    with usersmod.as_user(a["id"]):
        one = assetmod.assets_root()
    with usersmod.as_user(b["id"]):
        assert assetmod.assets_root() != one


def test_a_workspace_is_their_own_directory(two):
    _, b = two
    assert usersmod.cfg_for(b["id"])["workspace"].endswith(f"{b['id']}/workspace")


def test_the_first_user_keeps_the_workspace_they_were_already_using(home):
    """Pointing somebody who has been working on this machine at a new empty
    directory would read as "it lost my files"."""
    cfgmod.save_config({**cfgmod.load_config(), "workspace": "/home/somebody/Projects"})
    u = usersmod.create("ada", "hunter2hunter")
    assert usersmod.cfg_for(u["id"])["workspace"] == "/home/somebody/Projects"


# ---------------------------------------------------------------------------
# The first user inherits the machine — the migration nobody would forgive
# ---------------------------------------------------------------------------

def test_the_first_user_keeps_everything_that_was_already_there(home):
    """Somebody has been using this machine. Adding the first account must not
    look to them like a fresh install."""
    (home / "agentos.db").write_bytes(b"pretend-database")
    (home / "soul.md").write_text("# the soul they wrote")
    cfgmod.save_config({**cfgmod.load_config(), "telegram": {"bot_token": "theirs"},
                        "setup_complete": True})
    u = usersmod.create("ada", "hunter2hunter")
    assert (usersmod.home_for(u["id"]) / "agentos.db").read_bytes() == b"pretend-database"
    with usersmod.as_user(u["id"]):
        assert cfgmod.load_soul() == "# the soul they wrote"
        assert cfgmod.is_first_run() is False, "they already set this machine up"
    assert usersmod.cfg_for(u["id"])["telegram"]["bot_token"] == "theirs"


def test_what_the_first_user_inherited_is_not_left_lying_in_the_machine_file(home):
    """Every user created afterwards layers their config over the machine's, so a
    token left behind is a token handed to the next person who signs up."""
    cfgmod.save_config({**cfgmod.load_config(), "telegram": {"bot_token": "theirs"}})
    usersmod.create("ada", "hunter2hunter")
    b = usersmod.create("bob", "hunter2hunter")
    assert "theirs" not in cfgmod.CONFIG_PATH.read_text()
    assert usersmod.cfg_for(b["id"]).get("telegram", {}).get("bot_token") in ("", None)


# ---------------------------------------------------------------------------
# Two roles, and they are only about the machine
# ---------------------------------------------------------------------------

def test_there_are_exactly_two_roles(home):
    assert usersmod.ROLES == ("admin", "executor")


def test_an_executor_is_not_an_admin(two):
    a, b = two
    assert usersmod.is_admin(a["id"]) is True
    assert usersmod.is_admin(b["id"]) is False


def test_an_unknown_id_is_not_an_admin(two):
    assert usersmod.is_admin("deadbeef") is False


def test_the_last_admin_cannot_be_demoted(two):
    """Nothing in the UI could rescue a machine with no admin — the only way back
    would be editing JSON by hand."""
    a, b = two
    with pytest.raises(ValueError) as e:
        usersmod.set_role(a["id"], "executor")
    assert "last admin" in str(e.value)
    usersmod.set_role(b["id"], "admin")
    assert usersmod.set_role(a["id"], "executor")["role"] == "executor"


def test_the_last_admin_cannot_be_deleted(two):
    a, _ = two
    with pytest.raises(ValueError):
        usersmod.delete(a["id"])


def test_an_unknown_role_is_refused(two):
    _, b = two
    with pytest.raises(ValueError):
        usersmod.set_role(b["id"], "superuser")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def test_a_password_is_not_stored(two):
    raw = usersmod.registry_path().read_text()
    assert "hunter2hunter" not in raw


def test_the_right_password_verifies_and_a_wrong_one_does_not(two):
    a, _ = two
    assert usersmod.check_password(a["id"], "hunter2hunter") is True
    assert usersmod.check_password(a["id"], "hunter2hunter ") is False
    assert usersmod.check_password(a["id"], "") is False


def test_a_short_password_is_refused(home):
    with pytest.raises(ValueError):
        usersmod.create("ada", "short")


def test_changing_a_password_invalidates_the_old_one(two):
    a, _ = two
    usersmod.set_password(a["id"], "a-longer-one")
    assert usersmod.check_password(a["id"], "hunter2hunter") is False
    assert usersmod.check_password(a["id"], "a-longer-one") is True


@pytest.mark.parametrize("name", ["", "a", "ada bell", "ada/../root", "x" * 40, "ada@x"])
def test_a_bad_username_is_refused(home, name):
    assert usersmod.name_problem(name)


def test_a_username_is_case_insensitive(home):
    """Somebody typing their own name with a capital at the login page is not
    somebody with a different account."""
    usersmod.create("Ada", "hunter2hunter")
    assert usersmod.by_name("ADA")["name"] == "ada"
    assert "already a user" in usersmod.name_problem("ADA")


def test_a_duplicate_username_is_refused(two):
    assert "already a user" in usersmod.name_problem("ada")


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------

def test_deleting_an_account_keeps_their_work_by_default(two):
    """Removing somebody's access and destroying what they made are two different
    decisions, and one mis-click must not make them the same one."""
    _, b = two
    usersmod.store_for(b["id"]).create_conversation("bob's notes")
    home = usersmod.home_for(b["id"])
    usersmod.delete(b["id"])
    assert usersmod.get(b["id"]) is None
    assert (home / "agentos.db").exists()


def test_wiping_is_a_separate_and_explicit_decision(two):
    _, b = two
    home = usersmod.home_for(b["id"])
    usersmod.delete(b["id"], wipe=True)
    assert not home.exists()


def test_deleting_forgets_the_cached_store(two):
    """A cached Store outliving its account is a live handle on a directory the
    machine has just been told to forget."""
    _, b = two
    usersmod.store_for(b["id"])
    usersmod.delete(b["id"])
    assert b["id"] not in usersmod._stores


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------

def test_as_user_puts_it_back(two):
    a, _ = two
    assert usersmod.current() == ""
    with usersmod.as_user(a["id"]):
        assert usersmod.current() == a["id"]
    assert usersmod.current() == ""


def test_as_user_puts_it_back_even_when_the_block_raises(two):
    a, _ = two
    with pytest.raises(RuntimeError):
        with usersmod.as_user(a["id"]):
            raise RuntimeError("boom")
    assert usersmod.current() == ""


def test_a_scoped_service_reads_whoever_the_turn_belongs_to(two):
    """The whole design in one test: an object built once, at startup, with the
    machine's store, reading the right person's data at call time."""
    from agentos.memory import Store

    class Service(usersmod.Scoped):
        def __init__(self, cfg, store):
            self.cfg, self.store = cfg, store

    machine = Store(usersmod.db_for(""))
    svc = Service({"agent_name": "machine"}, machine)
    a, b = two
    usersmod.store_for(a["id"]).save_subagent({"name": "ada-only", "soul": "x"})
    with usersmod.as_user(a["id"]):
        assert svc.store.get_subagent("ada-only")
    with usersmod.as_user(b["id"]):
        assert svc.store.get_subagent("ada-only") is None


def test_a_scoped_service_on_a_single_user_machine_is_untouched(home):
    from agentos.memory import Store

    class Service(usersmod.Scoped):
        def __init__(self, cfg, store):
            self.cfg, self.store = cfg, store

    machine = Store(home / "agentos.db")
    svc = Service({"agent_name": "machine"}, machine)
    assert svc.store is machine
    assert svc.cfg == {"agent_name": "machine"}


def test_a_per_user_service_is_built_once_per_person(two):
    a, b = two
    made = []
    usersmod.set_service_factory(lambda uid: (made.append(uid), {"telegram": uid})[1])
    try:
        class Holder:
            telegram = usersmod.PerUser("telegram")
        h = Holder()
        with usersmod.as_user(a["id"]):
            assert h.telegram == a["id"]
            assert h.telegram == a["id"]
        with usersmod.as_user(b["id"]):
            assert h.telegram == b["id"]
        assert made == [a["id"], b["id"]], "one build each, not one per lookup"
    finally:
        usersmod.set_service_factory(None)


def test_a_per_user_attribute_falls_back_to_the_startup_instance(home):
    class Holder:
        telegram = usersmod.PerUser("telegram")
    h = Holder()
    h.telegram = "the-one-and-only"
    assert h.telegram == "the-one-and-only"


# ---------------------------------------------------------------------------
# The policy caches, which are keyed on names and version counters
# ---------------------------------------------------------------------------

def test_one_pdp_does_not_decide_one_user_against_anothers_grants(two):
    """Two people can both be at grants_version 3. Without the user in the cache
    key, the second is decided against the first one's permissions — which is the
    exact failure this whole module exists to prevent."""
    from agentos.policy import PDP, Principal
    a, b = two
    usersmod.store_for(a["id"]).add_grant("app", "notes", "tool.use", "run_command")
    pdp = PDP(usersmod.cfg_for(a["id"]), usersmod.store_for(a["id"]))
    hers = lambda: [g for g in pdp._grants() if g["principal_id"] == "notes"]
    with usersmod.as_user(a["id"]):
        assert hers(), "ada wrote one"
    with usersmod.as_user(b["id"]):
        assert hers() == [], "bob wrote none"
    with usersmod.as_user(a["id"]):
        assert hers(), "and ada's did not get evicted by the lookup"
    assert Principal("app", "notes").label


def test_the_rate_meter_does_not_throttle_one_user_for_anothers_runaway(two):
    """Two people can each own an app called 'notes'. Sharing the budget means one
    person's loop holds the other's app — and releasing one releases both."""
    from agentos.policy import PDP, Principal
    a, b = two
    pdp = PDP(usersmod.cfg_for(a["id"]), usersmod.store_for(a["id"]))
    p = Principal("app", "notes")
    with usersmod.as_user(a["id"]):
        for _ in range(50):
            pdp._rate.record(f"{pdp._who()}|{p.label}|tool", 1000.0, 60)
        assert pdp._rate.count(f"{pdp._who()}|{p.label}|tool", 1000.0, 60) == 50
    with usersmod.as_user(b["id"]):
        assert pdp._rate.count(f"{pdp._who()}|{p.label}|tool", 1000.0, 60) == 0


def test_releasing_a_hold_uses_the_key_the_meter_actually_has(two):
    """A key built by hand at a call site is a key that gets built without the
    user, and the release then silently does nothing."""
    from agentos.policy import PDP, Principal
    a, _ = two
    pdp = PDP(usersmod.cfg_for(a["id"]), usersmod.store_for(a["id"]))
    p = Principal("app", "notes")
    with usersmod.as_user(a["id"]):
        pdp._rate.record(f"{pdp._who()}|{p.label}|tool", 1000.0, 60)
        pdp.forget_rate("app", "notes")
        assert pdp._rate.count(f"{pdp._who()}|{p.label}|tool", 1000.0, 60) == 0


# ---------------------------------------------------------------------------
# Sharing: the one place data crosses, and it crosses as a copy
# ---------------------------------------------------------------------------

def test_publishing_puts_a_copy_where_everybody_can_see_it(two):
    a, _ = two
    usersmod.publish("agent", "researcher-plus", {"name": "researcher-plus",
                                                  "soul": "s"}, by="ada")
    assert [s["name"] for s in usersmod.shared()] == ["researcher-plus"]
    assert usersmod.take("agent", "researcher-plus")["soul"] == "s"


def test_taking_a_share_is_a_copy_not_a_link(two):
    """A shared app that changes under the people using it is a supply-chain
    problem living in a filesystem — and the publisher would not know they shipped
    a change."""
    a, _ = two
    usersmod.publish("agent", "r", {"name": "r", "soul": "one"}, by="ada")
    got = usersmod.take("agent", "r")
    got["soul"] = "edited by whoever took it"
    assert usersmod.take("agent", "r")["soul"] == "one"


def test_only_the_publisher_or_an_admin_can_take_it_down(two):
    usersmod.publish("agent", "r", {"name": "r"}, by="ada")
    with pytest.raises(ValueError):
        usersmod.unpublish("agent", "r", by="bob")
    assert usersmod.unpublish("agent", "r", by="bob", admin=True)["ok"]


def test_only_agents_and_apps_can_be_shared(two):
    """Sharing a conversation or a memory would make `shared/` a second, quieter
    way out of the isolation everything else here is for."""
    assert usersmod.SHAREABLE == ("app", "agent")
    with pytest.raises(ValueError):
        usersmod.publish("conversation", "x", {}, by="ada")


def test_taking_something_that_is_not_there_says_so(two):
    with pytest.raises(ValueError):
        usersmod.take("agent", "never-existed")


# ---------------------------------------------------------------------------
# The HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture()
def api(home):
    """A running server whose machine home is this test's tmp_path.

    Startup happens first and against the real home — that is fine and is what
    every other test file does. What matters is that `users` derives every path
    from `config.AGENTOS_HOME` at CALL time, so redirecting it afterwards is
    enough to give the routes a machine of their own.
    """
    from fastapi.testclient import TestClient

    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        yield c


def test_a_single_user_machine_is_not_asked_to_sign_in(api):
    d = api.get("/api/users/who").json()
    assert d["any"] is False and d["admin"] is True and d["multiuser"] is False


def test_creating_the_first_account_signs_that_person_in(api):
    """Otherwise the admin's own next click bounces them to a login page they have
    just, by this action, created."""
    r = api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    assert r.status_code == 200 and r.json()["signed_in"] is True
    who = api.get("/api/users/who").json()
    assert who["name"] == "ada" and who["admin"] is True and who["multiuser"] is True


def test_without_a_session_a_multi_user_machine_refuses(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.cookies.clear()
    assert api.get("/api/config").status_code == 401


def test_loopback_trust_does_not_survive_adding_users(api):
    """"Whoever is sitting here" is exactly the thing that has to stop being an
    identity once there is more than one identity."""
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.cookies.clear()
    assert api.get("/api/users").status_code == 401
    assert api.get("/api/users/who").status_code == 200, "the login page has to ask"


def test_signing_in_gets_the_desktop_back(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.cookies.clear()
    r = api.post("/api/users/login", json={"name": "ada", "password": "hunter2hunter"})
    assert r.status_code == 200
    assert api.get("/api/config").status_code == 200


def test_a_wrong_password_does_not_say_whether_the_name_exists(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.cookies.clear()
    a = api.post("/api/users/login", json={"name": "ada", "password": "nope-nope-nope"})
    b = api.post("/api/users/login", json={"name": "nobody", "password": "nope-nope-nope"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"] == b.json()["error"]


def test_signing_out_locks_it_again(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.post("/api/users/logout")
    assert api.get("/api/config").status_code == 401


def test_an_executor_cannot_add_users(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                 "role": "executor"})
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    r = api.post("/api/users", json={"name": "eve", "password": "hunter2hunter"})
    assert r.status_code == 403


def test_an_executor_cannot_change_machine_settings(api):
    """And is told so. A Settings page that appears to work and silently drops the
    save is the version somebody reports as a bug six months later."""
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                 "role": "executor"})
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    r = api.put("/api/config", json={"providers": {"anthropic": {"api_key": "x"}}})
    assert r.status_code == 403 and "admin" in r.json()["error"]


def test_an_executor_can_change_their_own_settings(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                 "role": "executor"})
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    assert api.put("/api/config", json={"agent_name": "Bob's agent"}).status_code == 200
    assert api.get("/api/config").json()["agent_name"] == "Bob's agent"


def test_two_signed_in_users_do_not_see_each_others_agents(api):
    """The claim, over HTTP, through the seam, with no route having been told
    about users."""
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                 "role": "executor"})
    api.post("/api/subagents", json={"name": "ada-only", "soul": "x"})
    assert any(s["name"] == "ada-only" for s in api.get("/api/subagents").json()["subagents"])
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    assert not any(s["name"] == "ada-only" for s in api.get("/api/subagents").json()["subagents"])


def test_a_deleted_account_cannot_keep_using_its_cookie(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    b = api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                     "role": "executor"}).json()["user"]
    admin = dict(api.cookies)
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    bob = dict(api.cookies)
    api.cookies.clear()
    api.cookies.update(admin)
    assert api.delete(f"/api/users/{b['id']}").status_code == 200
    api.cookies.clear()
    api.cookies.update(bob)
    assert api.get("/api/config").status_code == 401


def test_you_cannot_delete_the_account_you_are_signed_in_as(api):
    d = api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"}).json()
    r = api.delete(f"/api/users/{d['user']['id']}")
    assert r.status_code == 400 and "using" in r.json()["error"]


def test_anybody_can_change_their_own_password(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    b = api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                     "role": "executor"}).json()["user"]
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    assert api.put(f"/api/users/{b['id']}", json={"password": "a-new-one!!"}).status_code == 200
    api.post("/api/users/logout")
    assert api.post("/api/users/login",
                    json={"name": "bob", "password": "a-new-one!!"}).status_code == 200


def test_nobody_can_change_somebody_elses(api):
    a = api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"}).json()["user"]
    api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                 "role": "executor"})
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    assert api.put(f"/api/users/{a['id']}", json={"password": "gotcha!!!"}).status_code == 403


def test_an_executor_cannot_promote_themselves(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    b = api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                     "role": "executor"}).json()["user"]
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    r = api.put(f"/api/users/{b['id']}", json={"role": "admin"})
    assert r.status_code == 403


def test_sharing_an_agent_hands_a_copy_to_somebody_else(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.post("/api/users", json={"name": "bob", "password": "hunter2hunter",
                                 "role": "executor"})
    api.post("/api/subagents", json={"name": "shareable", "soul": "be terse"})
    assert api.post("/api/shared", json={"kind": "agent", "name": "shareable"}).status_code == 200
    api.post("/api/users/login", json={"name": "bob", "password": "hunter2hunter"})
    assert [s["name"] for s in api.get("/api/shared").json()["shared"]] == ["shareable"]
    assert not any(s["name"] == "shareable" for s in api.get("/api/subagents").json()["subagents"])
    r = api.post("/api/shared/take", json={"kind": "agent", "slug": "shareable"})
    assert r.status_code == 200
    got = [s for s in api.get("/api/subagents").json()["subagents"] if s["name"] == "shareable"]
    assert got and got[0]["soul"] == "be terse"


def test_taking_a_share_twice_does_not_overwrite_what_you_already_had(api):
    """`save_subagent` keys on the name, so an unqualified install would silently
    replace an agent of mine that happens to share one."""
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    api.post("/api/subagents", json={"name": "twin", "soul": "the original"})
    api.post("/api/shared", json={"kind": "agent", "name": "twin"})
    api.post("/api/shared/take", json={"kind": "agent", "slug": "twin"})
    names = [s["name"] for s in api.get("/api/subagents").json()["subagents"]]
    assert "twin" in names and any(n.startswith("twin-") for n in names)
    orig = [s for s in api.get("/api/subagents").json()["subagents"] if s["name"] == "twin"][0]
    assert orig["soul"] == "the original"


def test_sharing_something_that_is_not_yours_to_share_is_a_404(api):
    api.post("/api/users", json={"name": "ada", "password": "hunter2hunter"})
    assert api.post("/api/shared", json={"kind": "agent", "name": "ghost"}).status_code == 404


# ---------------------------------------------------------------------------
# The rest of the machine
# ---------------------------------------------------------------------------

def test_background_work_visits_everybody(two):
    """One place that answers "whose turn is it" for every loop. A subsystem that
    swept only the machine store would leave every real account unserved —
    silently, which is how it would stay."""
    a, b = two
    assert set(usersmod.sweep()) == {a["id"], b["id"]}


def test_background_work_on_a_single_user_machine_still_runs_once(home):
    assert usersmod.sweep() == [""]


def test_resolve_falls_back_to_the_machine_pair(home):
    cfg, store = {"x": 1}, object()
    assert usersmod.resolve(cfg, store) == (cfg, store)


def test_a_factory_reset_does_not_leave_accounts_behind(two):
    """"Back to day one" that left three private databases on the machine — and
    left it demanding a sign-in nobody has the password for — would be the most
    misleading button in the OS."""
    from agentos import setup as setupmod
    from agentos.memory import Store
    a, _ = two
    homes = [usersmod.home_for(u["id"]) for u in usersmod.list_users()]
    usersmod.publish("agent", "r", {"name": "r"}, by="ada")
    setupmod.factory_reset(cfgmod.load_config(), Store(cfgmod.AGENTOS_HOME / "agentos.db"))
    assert usersmod.enabled() is False
    assert not any(h.exists() for h in homes)
    assert usersmod.shared() == []
    assert usersmod.is_admin("") is True, "and the machine is usable again"


def test_a_session_cookie_is_not_signed_with_a_constant(home):
    """The cookie carries the uid that decides which private directory is opened.
    A machine that never turned remote access on used to sign it with a fixed,
    public string — which is a forgeable identity."""
    from agentos import remote as remotemod
    key = remotemod._machine_key()
    assert len(key) >= 32 and b"unset" not in key
    assert (cfgmod.AGENTOS_HOME / "session.key").stat().st_mode & 0o777 == 0o600
    assert remotemod._machine_key() == key, "and it is stable across calls"


def test_a_cookie_from_another_machine_does_not_verify(home):
    from agentos import remote as remotemod
    cfg = {"remote": {}}
    tok = remotemod.issue_session(cfg, "somebody")
    assert remotemod.session_user(cfg, tok) == "somebody"
    (cfgmod.AGENTOS_HOME / "session.key").unlink()      # a different machine
    assert remotemod.session_user(cfg, tok) is None


def test_a_tampered_uid_does_not_verify(home):
    from agentos import remote as remotemod
    cfg = {"remote": {}}
    body, _, sig = remotemod.issue_session(cfg, "aaa").rpartition(".")
    assert remotemod.session_user(cfg, body[:-2] + "XX." + sig) is None


def test_the_cli_says_who_to_choose_between_rather_than_guessing(two, capsys):
    """A `bento job add` that silently landed in the wrong person's database would
    be discovered weeks later by whoever did not get their briefing."""
    from agentos import __main__ as cli
    with pytest.raises(SystemExit):
        cli._open_store("")
    out = capsys.readouterr().out
    assert "ada" in out and "bob" in out and "--user" in out


def test_the_cli_opens_the_named_persons_database(two):
    from agentos import __main__ as cli
    a, _ = two
    usersmod.store_for(a["id"]).save_subagent({"name": "ada-only", "soul": "x"})
    cfg, store = cli._open_store("ada")
    assert store.get_subagent("ada-only")
    cfg, store = cli._open_store("bob")
    assert store.get_subagent("ada-only") is None


def test_the_cli_needs_no_user_on_a_single_user_machine(home):
    from agentos import __main__ as cli
    cfg, store = cli._open_store("")
    assert store is not None and "providers" in cfg
