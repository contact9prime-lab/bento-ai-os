"""What the end-to-end walk (packaging/dev/stitch-e2e) found, pinned.

The walk drives one person through the stitched experience on a machine with
accounts: chat asks for a risky step, hands work to a specialist, builds an app and
opens it from the chip, the app calls tools and the AI, a schedule is set for the app,
and a mission is drafted, enabled and run into the Brief. Five seams broke:

1. the first account's workspace (the machine's, adopted) was outside its home, so its
   agent was refused its own files after the person approved the write;
2. every app call carried no cookie (a sandboxed frame), so on a machine with accounts
   the sign-in gate refused it before the app token was looked at;
3. a window closed and reopened inside its closing animation bound the OLD elements,
   so a reopened Chat took your typing and sent nothing;
4. the Ledger counted permission changes as refusals ("Most refused" listed a mission's
   own deny rules);
5. an app's AI request read "llm_generate {}" on the approval card.
"""
import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "agentos/ui/src/js"


def _machine_with_workspace(tmp_path):
    from agentos import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["workspace"] = str(tmp_path / "AgentOS")
    cfgmod.save_config(cfg)
    return cfg["workspace"]


def test_the_first_accounts_workspace_stays_reachable(tmp_path):
    from agentos import config as cfgmod, users, tools
    ws = _machine_with_workspace(tmp_path)
    ada = users.create("ada", "ada-password-1", role="admin")
    shares = tools.folder_shares(cfgmod.load_config())
    assert shares == [{"path": os.path.realpath(ws), "mode": "rw", "users": [ada["id"]]}]
    # the agent can write a relative path into it, as the person approved
    with users.as_user(ada["id"]):
        cfg = users.cfg_for(ada["id"])
        tb = tools.Toolbox(cfg, users.store_for(ada["id"]))
        out = asyncio.run(tb.write_file("notes/hello.md", "hi"))
    assert out.startswith("wrote"), out
    assert (Path(ws) / "notes/hello.md").read_text() == "hi"
    # a second person starts in their own home, and is not handed the first one's folder
    bob = users.create("bob", "bob-password-1")
    assert not users.share_own_workspace(bob["id"])
    with users.as_user(bob["id"]):
        tb = tools.Toolbox(users.cfg_for(bob["id"]), users.store_for(bob["id"]))
        assert "another account" in asyncio.run(tb.write_file(os.path.join(ws, "x.md"), "no"))


def test_migrate_shares_an_adopted_workspace_once(tmp_path):
    """A machine that got accounts before this fix is repaired by `bento migrate`."""
    from agentos import config as cfgmod, migrate, users
    _machine_with_workspace(tmp_path)
    ada = users.create("ada", "ada-password-1", role="admin")
    m = cfgmod.load_config()
    m["sandbox"]["folders"] = []                    # as it was before the fix
    cfgmod.save_config(m)
    said = []
    migrate.everyone(log=said.append)
    assert any("workspace is shared" in s for s in said)
    assert len(cfgmod.load_config()["sandbox"]["folders"]) == 1
    said.clear()
    migrate.everyone(log=said.append)
    assert not any("workspace is shared" in s for s in said), "migrate must not add it twice"


def test_an_app_reaches_the_os_on_its_token_on_a_machine_with_accounts(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod, users
    _machine_with_workspace(tmp_path)
    users.create("ada", "ada-password-1", role="admin")
    with TestClient(servermod.app) as c:
        assert c.post("/api/users/login", json={"name": "ada", "password": "ada-password-1"}).status_code == 200
        r = c.post("/api/apps", json={"name": "Probe", "html": "<html><body>x</body></html>"})
        aid = r.json()["id"]
        page = c.get(f"/api/apps/{aid}/page").text
        tok = page.split("APP_TOKEN = '")[1].split("'")[0]
        entry = servermod.state["app_tokens"][tok]
        assert entry["uid"] == users.by_name("ada")["id"] and entry["sid"]
        # the sandboxed frame sends no cookie: a fresh client with only the token
        app = TestClient(servermod.app)
        h = {"Origin": "null", "X-App-Token": tok}
        assert app.options("/api/tool", headers={"Origin": "null"}).status_code == 204
        assert app.get(f"/api/apps/{aid}/data", headers=h).status_code == 200
        assert app.get("/api/apps/context", headers=h).json().get("app_id") == aid
        # the token is not a way past the gate anywhere else, and a stranger's is nothing
        assert app.get("/api/grants", headers=h).status_code == 401
        assert app.get(f"/api/apps/{aid}/data", headers={"Origin": "null", "X-App-Token": "nope"}).status_code == 401
        # locking the screen stops the apps open in that browser; unlocking resumes them
        assert c.post("/api/session/lock").status_code == 200
        assert app.get(f"/api/apps/{aid}/data", headers=h).status_code == 401
        assert c.post("/api/session/unlock", json={"password": "ada-password-1"}).status_code == 200
        assert app.get(f"/api/apps/{aid}/data", headers=h).status_code == 200
        # signing out drops them
        c.post("/api/users/logout")
        assert tok not in servermod.state["app_tokens"]
        assert app.get(f"/api/apps/{aid}/data", headers=h).status_code == 401


def test_a_closing_window_gives_up_its_ids():
    wm = (JS / "04-wm.js").read_text()
    close = wm[wm.index("function closeWin(w){"):][:1200]
    strip = close.index("removeAttribute('id')")
    assert strip < close.index("zoomWin(w.el"), "ids must go before the closing animation starts"
    assert "w.el.inert=true" in close


def test_the_ledger_does_not_count_permission_changes_as_refusals(tmp_path):
    from agentos.memory import Store
    s = Store(tmp_path / "a.db")
    s.add_grant("subagent", "researcher", "memory.write", "memory:*", effect="deny", source="definition",
                source_ref="flow:solar-news")
    s.audit_add(principal_kind="app", principal_id="x", action="fs.write", resource="fs:a.txt",
                effect="deny", rule="default")
    sm = s.audit_summary()
    assert sm["effects"].get("deny") == 1, "only the real refusal is counted"
    assert [t["resource"] for t in sm["top_denied"]] == ["fs:a.txt"]
    assert sm["changes"] >= 1
    assert not [t for t in sm["top_denied"] if t["action"].startswith("grant.")]
    assert sum(sm["effects"].values()) == sm["total"]
    page = (JS / "19a-audit.js").read_text()
    assert "startsWith('grant.')" in page and "'changed'" in page


def test_an_apps_ai_request_reads_in_words():
    act = (JS / "08b-activity.js").read_text()
    assert "name === 'llm_generate'" in act and "use the AI" in act
