"""Usage for every LLM and every account, and daily quotas on the LLMs a machine shares.

Asked for as "make sure the usage is available for all the LLMs and all the accounts, money and
tokens in, out and total; money may be estimated in many cases but try to be precise, and the
agents should be able to answer. Per account limits per day per LLM shared, like a quota, by
tokens or cost or both, and by default it's unlimited".
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

from agentos import config as cfgmod                                # noqa: E402
from agentos import providers                                       # noqa: E402
from agentos import usage                                           # noqa: E402
from agentos import users as usersmod                               # noqa: E402
from agentos import vault                                           # noqa: E402

PW = "correct horse 1"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cfgmod, "DB_PATH", tmp_path / "agentos.db")
    usersmod.reset_caches()
    usersmod.set_current("")
    vault.forget_held()
    yield tmp_path
    vault.forget_held()
    usersmod.reset_caches()
    usersmod.set_current("")


@pytest.fixture()
def brain(monkeypatch):
    """A provider that answers every call with 1,000 tokens in and 200 out, and optionally its
    own bill and a cached share, like OpenRouter and OpenAI do."""
    said = {"cost": None, "cache_read": 0}

    async def fake(base, key, model, messages, tools, options=None):
        yield {"type": "text", "text": "ok"}
        ev = {"type": "usage", "input": 1000, "output": 200}
        if said["cost"] is not None:
            ev["cost"] = said["cost"]
        if said["cache_read"]:
            ev["cache_read"] = said["cache_read"]
        yield ev
        yield {"type": "done"}
    monkeypatch.setattr(providers, "_chat_openai", fake)
    return said


def _call(cfg, model="openai/gpt-5.5"):
    async def go():
        async for _ in providers.chat(cfg, model, [{"role": "user", "content": "hi"}], []):
            pass
    asyncio.run(go())


def _rows(uid=""):
    return [dict(r) for r in usersmod.store_for(uid).db.execute(
        "SELECT model, tokens_in, tokens_out, cost_usd, cost_src, kind, principal FROM usage")]


def _machine():
    cfg = cfgmod.load_config()
    cfg["providers"]["openai"].update(api_key="sk-MACHINE", enabled=True)
    cfgmod.save_config(cfg)
    return cfg


def test_every_call_is_counted_once_at_the_door(home, brain):
    cfg = _machine()
    with usage.caller(kind="subagent", principal="subagent:researcher", surface="task"):
        _call(cfg)
    rows = _rows()
    assert len(rows) == 1 and rows[0]["tokens_in"] == 1000 and rows[0]["tokens_out"] == 200
    assert rows[0]["kind"] == "subagent" and rows[0]["principal"] == "subagent:researcher"
    # the turn's own bookkeeping after it ends must not count the same tokens again
    usage.turn(usersmod.store_for(""), cfg, "openai/gpt-5.5", {"input": 1000, "output": 200})
    assert len(_rows()) == 1
    # an agent CLI's turn never passes the door: its own bill is still recorded, as stated
    usage.turn(usersmod.store_for(""), cfg, "claude-code", {"input": 5, "output": 5}, cost_usd=0.02)
    assert [r["cost_src"] for r in _rows()] == ["estimated", "reported"]


def test_the_providers_own_bill_is_exact_and_ours_is_an_estimate(home, brain):
    cfg = _machine()
    _call(cfg)
    brain["cost"] = 0.0123
    _call(cfg)
    a, b = _rows()
    assert a["cost_src"] == "estimated" and a["cost_usd"] > 0
    assert b["cost_src"] == "reported" and b["cost_usd"] == pytest.approx(0.0123)
    rep = usage.by_llm(usersmod.store_for(""), cfg)
    assert rep[0]["usd_exact"] == pytest.approx(0.0123) and rep[0]["usd_estimated"] == pytest.approx(a["cost_usd"])
    assert rep[0]["in"] == 2000 and rep[0]["out"] == 400 and rep[0]["total"] == 2400
    # cached input is billed at a tenth, so the estimate follows it
    full = usage.cost(cfg, "openai/gpt-5.5", 1000, 200)
    cached = usage.cost(cfg, "openai/gpt-5.5", 1000, 200, cache_read=800)
    assert cached < full


def test_quotas_are_unlimited_until_an_admin_sets_one(home, brain):
    cfg = _machine()
    usersmod.create("ada", PW, role="admin")
    bob = usersmod.create("bob", PW)["id"]
    usersmod.set_current(bob)
    c = usersmod.cfg_for(bob)
    for _ in range(3):
        _call(c)
    assert len(_rows(bob)) == 3 and usage.quota_refusal(c, "openai/gpt-5.5") == ""


def test_a_token_quota_stops_the_next_call_and_says_why(home, brain):
    m = _machine()
    ada = usersmod.create("ada", PW, role="admin")["id"]
    bob = usersmod.create("bob", PW)["id"]
    m["llm_sharing"] = {"quota": {"*": {"openai": {"tokens": 2000}}}}
    usersmod.set_current(ada)
    cfgmod.save_config({**usersmod.cfg_for(ada), "llm_sharing": m["llm_sharing"]})
    usersmod.set_current(bob)
    c = usersmod.cfg_for(bob)
    _call(c)
    _call(c)
    with pytest.raises(providers.ProviderError, match="daily quota for OpenAI is used up: 2,400 of 2,000"):
        _call(c)
    assert len(_rows(bob)) == 2
    # the admin who set it is not held by everyone's quota
    usersmod.set_current(ada)
    for _ in range(3):
        _call(usersmod.cfg_for(ada))
    # a quota of bob's own wins over everyone's
    usersmod.set_current(ada)
    cfgmod.save_config({**usersmod.cfg_for(ada),
                        "llm_sharing": {"quota": {"*": {"openai": {"tokens": 2000}},
                                                  bob: {"openai": {"tokens": 10000}}}}})
    usersmod.set_current(bob)
    _call(usersmod.cfg_for(bob))


def test_a_dollar_quota_and_an_llm_that_is_not_shared(home, brain):
    _machine()
    ada = usersmod.create("ada", PW, role="admin")["id"]
    bob = usersmod.create("bob", PW)["id"]
    usersmod.set_current(ada)
    cfgmod.save_config({**usersmod.cfg_for(ada),
                        "llm_sharing": {"off": ["anthropic"], "quota": {bob: {"openai": {"usd": 0.01}}}}})
    usersmod.set_current(bob)
    c = usersmod.cfg_for(bob)
    brain["cost"] = 0.02
    _call(c)
    with pytest.raises(providers.ProviderError, match=r"\$0.02 of \$0.01"):
        _call(c)
    assert "isn't shared with your account" in usage.quota_refusal(c, "anthropic/claude-sonnet-5")
    assert usage.quota_refusal(c, "ollama/qwen3.5:9b") == ""          # a local model is free
    usersmod.set_current(ada)
    assert usage.quota_refusal(usersmod.cfg_for(ada), "anthropic/claude-sonnet-5") == ""


def test_an_account_cannot_price_its_way_under_a_dollar_quota(home, brain):
    m = _machine()
    ada = usersmod.create("ada", PW, role="admin")["id"]
    bob = usersmod.create("bob", PW)["id"]
    usersmod.set_current(ada)
    a = usersmod.cfg_for(ada)
    usage.set_price(a, "openai/gpt-5.5", 10, 40)
    a["llm_sharing"] = {"quota": {bob: {"openai": {"usd": 0.02}}}}
    cfgmod.save_config(a)
    was = usersmod._machine[0]
    usersmod.bind_machine(cfgmod.load_config())
    usersmod.set_current(bob)
    c = usersmod.cfg_for(bob)
    usage.set_price(c, "openai/gpt-5.5", 0, 0)            # his own view says it's free
    _call(c)                                               # 1000*10/1e6 + 200*40/1e6 = $0.018
    _call(c)
    with pytest.raises(providers.ProviderError, match="daily quota for OpenAI"):
        _call(c)
    usersmod.bind_machine(was)


def test_an_isolated_tenants_quotas_are_its_own(home, brain):
    _machine()
    ada = usersmod.create("ada", PW, role="admin")["id"]
    eve = usersmod.create("eve", PW, scope="isolated")
    finn = usersmod.create("finn", PW, scope="isolated", tenant=eve["tenant"])["id"]
    usersmod.set_current(ada)
    cfgmod.save_config({**usersmod.cfg_for(ada), "llm_sharing": {"quota": {"*": {"openai": {"tokens": 1}}}}})
    usersmod.set_current(eve["id"])
    t = usersmod.cfg_for(eve["id"])
    t["providers"]["openai"].update(api_key="sk-EVE", enabled=True)
    t["llm_sharing"] = {"quota": {finn: {"openai": {"tokens": 1000}}}}
    cfgmod.save_config(t)
    usersmod.set_current(finn)
    f = usersmod.cfg_for(finn)
    assert f["llm_sharing"]["quota"] == {finn: {"openai": {"tokens": 1000}}}  # not the machine's
    _call(f)
    with pytest.raises(providers.ProviderError, match="daily quota"):
        _call(f)


def test_clean_sharing_reads_field_by_field():
    provs = {"openai": {}, "anthropic": {}, "ollama": {}}
    got, dropped = usage.clean_sharing(
        {"off": ["openai", "ollama", "nope"],
         "quota": {"*": {"openai": {"tokens": "5000", "usd": -1}, "ollama": {"tokens": 5}},
                   "u1": {"anthropic/claude-sonnet-5": {"usd": 1.5}}, "stranger": {"openai": {"tokens": 1}}}},
        provs, {"u1"})
    assert got == {"off": ["openai"], "quota": {"*": {"openai": {"tokens": 5000}},
                                               "u1": {"anthropic/claude-sonnet-5": {"usd": 1.5}}}}
    assert any("ollama" in d for d in dropped) and any("unknown account" in d for d in dropped)


# ---- over HTTP, and the agent's tool ---------------------------------------------------------

@pytest.fixture()
def api(home, brain):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        yield c


def _sign_in(api, name):
    api.cookies.clear()
    assert api.post("/api/users/login", json={"name": name, "password": PW}).status_code == 200


def test_an_account_sees_its_own_and_an_admin_sees_everyone(api):
    _machine()
    api.post("/api/users", json={"name": "ada", "password": PW})
    api.post("/api/users", json={"name": "bob", "password": PW})
    bob = usersmod.by_name("bob")["id"]
    usersmod.set_current(bob)
    _call(usersmod.cfg_for(bob))
    usersmod.set_current("")
    _sign_in(api, "bob")
    me = api.get("/api/usage/llms").json()
    assert me["llms"][0]["total"] == 1200 and not me["admin"] and "everyone" not in me
    assert "OpenAI: 1 calls, 1,000 tokens in, 200 out, 1,200 in all" in me["words"]
    assert api.put("/api/usage/sharing", json={"quota": {"*": {"openai": {"tokens": 1}}}}).status_code == 403
    _sign_in(api, "ada")
    allx = api.get("/api/usage/llms?everyone=1").json()
    names = {a["name"]: a for a in allx["everyone"]}
    assert names["bob"]["llms"][0]["total"] == 1200 and names["ada"]["llms"] == []
    r = api.put("/api/usage/sharing", json={"quota": {bob: {"openai": {"tokens": 1000}}}})
    assert r.status_code == 200 and r.json()["sharing"]["quota"] == {bob: {"openai": {"tokens": 1000}}}
    rows = usersmod.store_for(usersmod.by_name("ada")["id"]).db.execute(
        "SELECT reason FROM audit WHERE action='usage.sharing'").fetchall()
    assert rows
    _sign_in(api, "bob")
    q = api.get("/api/usage/llms").json()["llms"][0]["quota"]
    assert q["tokens"] == 1000 and q["left_tokens"] == 0


def test_the_agent_can_answer_what_was_spent(home, brain):
    from agentos import tools as toolsmod
    from agentos.memory import Store
    cfg = _machine()
    _call(cfg)
    tb = toolsmod.Toolbox(cfg, Store(cfgmod.DB_PATH))
    out = asyncio.run(tb.usage_report())
    assert "OpenAI: 1 calls" in out and "estimated" in out
    assert "usage_report" in toolsmod.SAFE_TOOLS
    assert any(s["name"] == "usage_report" for s in toolsmod.TOOL_SCHEMAS)
