"""Account scope: Shared Tenant (the default) or Isolated Tenant (agentos/users.py).

Asked for as "by default Shared-Tenant, so everyone shares the keys but the data is kept separate.
Isolated Tenant means everything is done ground up, and a new admin being added would have their
own account management and keys to be set up", with "don't share MCP and data between the
accounts in any case, only the keys", and "the machine admin decides, and can change it".
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import config as cfgmod                                # noqa: E402
from agentos import users as usersmod                               # noqa: E402
from agentos import vault                                           # noqa: E402

PW = "correct horse 1"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    usersmod.reset_caches()
    usersmod.set_current("")
    vault.forget_held()
    yield tmp_path
    vault.forget_held()
    usersmod.reset_caches()
    usersmod.set_current("")


def _machine_with_key():
    cfg = cfgmod.load_config()
    cfg["providers"]["anthropic"].update(api_key="sk-ant-MACHINE", enabled=True)
    cfgmod.save_config(cfg)
    return cfg


def test_an_account_is_shared_by_default_and_spends_the_machines_keys(home):
    _machine_with_key()
    usersmod.create("ada", PW, role="admin")
    bob = usersmod.create("bob", PW)["id"]
    assert usersmod.scope_of(bob) == "shared"
    from agentos import providers
    c = usersmod.cfg_for(bob)
    assert providers._key(c["providers"]["anthropic"]) == "sk-ant-MACHINE"


def test_an_isolated_tenant_has_none_of_the_machines_keys(home):
    _machine_with_key()
    usersmod.create("ada", PW, role="admin")
    eve = usersmod.create("eve", PW, scope="isolated")
    assert eve["tenant"] and eve["role"] == "admin"          # a new tenant's first person runs it
    c = usersmod.cfg_for(eve["id"])
    assert c["_tenant"] == eve["tenant"]
    assert all(not (p or {}).get("api_key") for p in c["providers"].values())
    assert "sk-ant-MACHINE" not in json.dumps(c)


def test_a_tenant_admin_is_not_the_machines_admin(home):
    ada = usersmod.create("ada", PW, role="admin")["id"]
    eve = usersmod.create("eve", PW, scope="isolated")
    finn = usersmod.create("finn", PW, scope="isolated", tenant=eve["tenant"])["id"]
    bob = usersmod.create("bob", PW)["id"]
    assert usersmod.is_admin(ada) and not usersmod.is_admin(eve["id"])
    assert usersmod.is_tenant_admin(eve["id"]) and not usersmod.is_tenant_admin(finn)
    assert usersmod.can_manage(eve["id"], finn) and not usersmod.can_manage(eve["id"], bob)
    assert not usersmod.can_manage(eve["id"], ada) and usersmod.can_manage(ada, finn)
    assert usersmod.admin_count() == 1                        # the machine's admins only


def test_a_tenants_keys_are_its_own_and_reach_its_people(home):
    _machine_with_key()
    usersmod.create("ada", PW, role="admin")
    eve = usersmod.create("eve", PW, scope="isolated")
    finn = usersmod.create("finn", PW, scope="isolated", tenant=eve["tenant"])["id"]
    usersmod.set_current(eve["id"])
    c = usersmod.cfg_for(eve["id"])
    c["providers"]["openai"].update(api_key="sk-EVE-TENANT", enabled=True)
    cfgmod.save_config(c)
    usersmod.set_current("")
    tfile = usersmod.tenant_home(eve["tenant"]) / "config.json"
    assert "sk-EVE-TENANT" not in tfile.read_text()
    assert "sk-EVE-TENANT" not in (home / "config.json").read_text()
    from agentos import providers
    f = usersmod.cfg_for(finn)
    assert providers._key(f["providers"]["openai"]) == "sk-EVE-TENANT"
    # the machine's view is untouched, and an admin's machine save never reaches the tenant
    m = cfgmod.load_config()
    assert not providers._key(m["providers"]["openai"])
    usersmod.machine_changed(m)
    assert providers._key(usersmod.cfg_for(finn)["providers"]["openai"]) == "sk-EVE-TENANT"


def test_an_isolated_tenant_cannot_use_the_machines_agents_or_community(home):
    from agentos import executors, providers
    usersmod.create("ada", PW, role="admin")
    eve = usersmod.create("eve", PW, scope="isolated")
    c = usersmod.cfg_for(eve["id"])
    assert executors.switched_off(c, "claude-code")
    assert executors.resolve_engine({**c, "engine": "claude-code"}) == "aria"
    with pytest.raises(providers.ProviderError, match="Isolated Tenant"):
        import asyncio

        async def go():
            async for _ in providers.chat(c, "pool/default", [], []):
                pass
        asyncio.run(go())


def test_moving_between_tenants(home):
    usersmod.create("ada", PW, role="admin")
    bob = usersmod.create("bob", PW)["id"]
    r = usersmod.set_scope(bob, "isolated")
    assert r["tenant"] and r["role"] == "admin"
    tid = r["tenant"]
    assert usersmod.would_drop(bob, "shared") == tid
    r = usersmod.set_scope(bob, "shared")
    assert r["role"] == "executor" and r["dropped"]          # never the machine's admin by a move
    assert not usersmod.tenant_home(tid).exists() and not usersmod.tenants()


def test_the_last_machine_admin_cannot_move_away(home):
    ada = usersmod.create("ada", PW, role="admin")["id"]
    with pytest.raises(ValueError, match="last admin"):
        usersmod.set_scope(ada, "isolated")


def test_shared_copies_and_account_links_stay_inside_a_tenant(home):
    from agentos import teamlink
    usersmod.create("ada", PW, role="admin")
    bob = usersmod.create("bob", PW)["id"]
    eve = usersmod.create("eve", PW, scope="isolated")["id"]
    usersmod.set_current(bob)
    usersmod.publish("app", "notes", {"html": "x"}, by="bob")
    assert [x["slug"] for x in usersmod.shared()] == ["notes"]
    usersmod.set_current(eve)
    assert usersmod.shared() == []
    with pytest.raises(ValueError):
        usersmod.take("app", "notes")
    with pytest.raises(ValueError, match="another tenant"):
        teamlink.request_account(eve, bob, {bob: "bob", eve: "eve"})
    usersmod.set_current("")


# ---- over HTTP -----------------------------------------------------------------------------

@pytest.fixture()
def api(home):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        yield c


def _sign_in(api, name, pw=PW):
    api.cookies.clear()
    assert api.post("/api/users/login", json={"name": name, "password": pw}).status_code == 200


def test_the_machine_admin_makes_an_isolated_tenant_and_its_admin_runs_it(api):
    api.post("/api/users", json={"name": "ada", "password": PW})
    api.post("/api/users", json={"name": "bob", "password": PW})
    r = api.post("/api/users", json={"name": "eve", "password": PW, "scope": "isolated"})
    assert r.status_code == 200 and r.json()["user"]["tenant"]
    _sign_in(api, "eve")
    me = api.get("/api/users").json()
    assert [u["name"] for u in me["users"]] == ["eve"] and me["me"]["tenant_admin"]
    assert "tenants" not in me                                   # the machine's list isn't hers
    # she adds somebody: to her own tenant, whatever she asks for
    r = api.post("/api/users", json={"name": "finn", "password": PW, "scope": "shared"})
    assert r.status_code == 200 and r.json()["user"]["tenant"] == me["me"]["tenant"]
    # her tenant's keys, and nothing of the machine's
    assert api.put("/api/config", json={"providers": {"openai": {"api_key": "sk-EVE"}}}).status_code == 200
    assert api.put("/api/config", json={"sandbox": {"enabled": False}}).status_code == 403
    bob = usersmod.by_name("bob")["id"]
    assert api.delete(f"/api/users/{bob}").status_code == 403
    assert api.put(f"/api/users/{bob}", json={"password": "hijacked-pw"}).status_code == 403
    assert api.put(f"/api/users/{usersmod.by_name('finn')['id']}", json={"scope": "shared"}).status_code == 403


def test_moving_somebody_out_of_their_tenant_asks_before_dropping_its_keys(api):
    api.post("/api/users", json={"name": "ada", "password": PW})
    api.post("/api/users", json={"name": "eve", "password": PW, "scope": "isolated"})
    eve = usersmod.by_name("eve")["id"]
    r = api.put(f"/api/users/{eve}", json={"scope": "shared"})
    assert r.status_code == 409 and r.json()["confirm"]
    r = api.put(f"/api/users/{eve}", json={"scope": "shared", "confirm": True})
    assert r.status_code == 200 and usersmod.scope_of(eve) == "shared"
    rows = usersmod.store_for(usersmod.by_name("ada")["id"]).db.execute(
        "SELECT reason FROM audit WHERE action='account.scope'").fetchall()
    assert rows
