"""Holes the first security pass found outside its lists. Each test fails on the old code."""
import ast
import asyncio
from pathlib import Path

import agentos
from agentos import constcmp, knowledge, providers
from agentos.memory import Store
from agentos.tools import Toolbox

ROOT = Path(agentos.__file__).parent


def test_a_non_ascii_secret_is_a_plain_no():
    assert constcmp.same("abc", "abc")
    assert not constcmp.same("é", "abc")
    assert not constcmp.same("\ud800", "abc")


def test_no_secret_is_compared_with_a_bare_compare_digest():
    allowed = {"constcmp.py", "shellhost.py"}   # shellhost runs alone on a system python, and encodes
    bare = []
    for f in ROOT.rglob("*.py"):
        if f.name in allowed:
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Attribute) and n.attr == "compare_digest":
                bare.append(f"{f.name}:{n.lineno}")
    assert not bare, bare


def test_the_github_token_goes_only_to_its_own_host():
    box = Toolbox.__new__(Toolbox)
    box.cfg = {"github": {"token": "tok"}}
    assert box._git_auth_env("https://github.com/o/r.git")["AGENTOS_GIT_TOKEN"] == "tok"
    for url in ("https://evil.example/o/r.git", "http://github.com/o/r.git",
                "https://github.com@evil.example/r", "https://evil.example\\@github.com/r",
                "git@github.com:o/r.git", ""):
        assert box._git_auth_env(url) == {}, url
    box.cfg["github"]["host"] = "git.corp.example"
    assert box._git_auth_env("https://git.corp.example/o/r")["AGENTOS_GIT_HOST"] == "git.corp.example"


def _pin_and_plain(store):
    pinned = store.add_memory("the door code rule", scope="user", pinned=1, source="user")
    plain = store.add_memory("likes tea in the morning", scope="user", source="auto")
    return pinned, plain


CORRECT_BOTH = {"updates": [{"old": "the door code rule", "new": "rewritten by a model"},
                            {"old": "likes tea in the morning", "new": "likes coffee in the morning"}],
                "retractions": ["the door code rule"]}


def test_auto_learn_leaves_a_pinned_memory_alone(tmp_path, monkeypatch):
    """The real after-turn pass, with a model answer that corrects and retracts a pin."""
    import json as _json
    store = Store(tmp_path / "t.db")
    pinned, plain = _pin_and_plain(store)

    async def fake(cfg, model, prompt):
        return _json.dumps(CORRECT_BOTH)

    async def idle(model, max_wait=900):
        return None
    monkeypatch.setattr(providers, "complete", fake)
    monkeypatch.setattr(knowledge, "wait_model_idle", idle)
    monkeypatch.setattr(knowledge, "turn_tainted", lambda store, cid: False)
    cid = store.create_conversation("t")
    asyncio.run(knowledge.extract_from_turn({"default_model": "stand-in"}, store, cid, "hi", "hello"))
    mems = {m["id"]: m["content"] for m in store.search_memories("", limit=50, scope="user")}
    assert mems.get(pinned) == "the door code rule", "a pin is the person's"
    assert mems.get(plain) == "likes coffee in the morning", "the pass really ran"
    assert any("pinned memory alone" in (r.get("message") or "") for r in store.list_logs(limit=20))


def test_a_zeros_learning_on_its_hub_leaves_a_pin_alone(tmp_path, monkeypatch):
    from agentos import zero as zeromod
    from agentos import zeromind
    store = Store(tmp_path / "hub.db")
    sid = store.create_space("zero:pi", "") if hasattr(store, "create_space") else ""
    sid = sid.get("id") if isinstance(sid, dict) else sid
    monkeypatch.setattr(zeromod, "ships_to", lambda lk: True)
    monkeypatch.setattr(zeromind, "section", lambda store, lk: sid)
    pinned = store.add_memory("the door code rule", scope="user", pinned=1, source="zero:pi", space_id=sid)
    plain = store.add_memory("likes tea in the morning", scope="user", source="zero:pi", space_id=sid)
    out = asyncio.run(zeromind.answer(store, {}, {"label": "pi"}, {"action": "learn", **CORRECT_BOTH}))
    assert out.get("ok") is not False, out
    mems = {m["id"]: m["content"] for m in store.search_memories("", limit=50, space=store.only(sid))}
    assert mems.get(pinned) == "the door code rule"
    assert mems.get(plain) == "likes coffee in the morning"


def test_a_non_ascii_bearer_at_the_run_bridge_is_a_401():
    from fastapi.testclient import TestClient
    from agentos import server
    with TestClient(server.app) as c:
        for bearer in ("é", "caf\u00e9-token", "\u00ff" * 40):
            # a header is bytes on the wire: latin-1 is what an HTTP client really sends for these
            r = c.post("/api/mcp/run/abc", headers={"Authorization": ("Bearer " + bearer).encode("latin-1")},
                       json={})
            assert r.status_code == 401, (bearer, r.status_code)


# -- item 1: a tool that reaches the host is an admin's --------------------------------------------
from agentos import config as cfgmod                     # noqa: E402
from agentos import fabric as fabricmod                  # noqa: E402
from agentos import policy as policymod                  # noqa: E402
from agentos import tools as toolsmod                    # noqa: E402
from agentos import users as usersmod                    # noqa: E402

import pytest                                            # noqa: E402

# What counts as reaching the host from a Toolbox method: these modules and server helpers.
_HOST_MODULES = {"host", "hostctl", "appstream", "compositor", "session", "desktop", "upower", "brightness", "audio"}
_HOST_SERVER = {"capture_screen", "power_exec"}
# A tool that touches one of those and is not in HOST_TOOLS has to say why it is fine here.
_NOT_HOST_TOOLS = {
    "notify": "a non-admin's goes to their own pages, tested below",
    "desktop_state": "a non-admin hears only their own pages, tested below",
    "control_desktop": "shell_command reaches only this account's own pages, tested below",
    "wifi": "its writes check is_admin themselves, and a status is a read",
    "bluetooth": "its writes check is_admin themselves, and a status is a read",
}


def _reaches_host(fn) -> set:
    hits = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.ImportFrom):
            hits |= {a.name for a in n.names if a.name in _HOST_MODULES}
            hits |= {n.module for _a in n.names if n.module in _HOST_MODULES}
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if n.value.id == "srv" and n.attr in _HOST_SERVER:
                hits.add(n.attr)
            if n.value.id == "self" and n.attr == "shell":
                hits.add("shell")
    return hits


def test_a_tool_that_reaches_the_host_says_who_may():
    src = (ROOT / "tools.py").read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Toolbox")
    named = {t["name"] for t in toolsmod.TOOL_SCHEMAS}
    unplaced = []
    for fn in cls.body:
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)) or fn.name not in named:
            continue
        if not _reaches_host(fn) or fn.name in toolsmod.HOST_TOOLS or fn.name in _NOT_HOST_TOOLS:
            continue
        if "_admin_only(" in ast.get_source_segment(src, fn):
            continue
        unplaced.append(fn.name)
    assert not unplaced, f"reach the host with no admin check: {unplaced}"
    assert set(toolsmod.HOST_TOOLS) <= named


@pytest.fixture()
def accounts():
    usersmod.reset_caches()
    usersmod.set_current("")
    ada = usersmod.create("ada", "hunter2hunter")["id"]
    bob = usersmod.create("bob", "hunter2hunter", role="executor")["id"]
    yield ada, bob
    usersmod.reset_caches()
    usersmod.set_current("")


@pytest.fixture()
def box(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = cfgmod.load_config()
    cfg["workspace"] = str(ws)
    return Toolbox(cfg, Store(tmp_path / "db.sqlite"))


def run(c):
    return asyncio.run(c)


HOST_ARGS = {"take_screenshot": {}, "open_app": {"target": "/etc/passwd"}, "launch_native_app": {"name": "xterm"},
             "list_windows": {}, "focus_window": {"title": "x"}, "manage_window": {"window_id": "1", "action": "close"},
             "system_control": {"action": "mute"}, "set_brightness": {"percent": 1}, "audio": {},
             "power_profile": {}, "lock_screen": {}, "power_action": {"action": "reboot"},
             "list_notifications": {}, "app_windows": {}, "app_window_open": {"app": "xterm"},
             "app_window_look": {}, "app_window_act": {}}


def test_a_non_admins_agent_cannot_reach_the_host(box, accounts, monkeypatch):
    assert set(HOST_ARGS) == set(toolsmod.HOST_TOOLS)
    ran = []
    for name in HOST_ARGS:
        async def spy(*a, _n=name, **k):
            ran.append(_n)
            return "ran"
        monkeypatch.setattr(box, name, spy)
    with usersmod.as_user(accounts[1]):
        for name, args in HOST_ARGS.items():
            out = run(box.execute(name, args))
            assert out.startswith("[denied]"), (name, out)
    assert not ran
    with usersmod.as_user(accounts[0]):
        for name, args in HOST_ARGS.items():
            assert run(box.execute(name, args)) == "ran", name


def test_a_machine_with_no_accounts_is_unchanged(box, monkeypatch):
    async def spy(*a, **k):
        return "ran"
    monkeypatch.setattr(box, "take_screenshot", spy)
    usersmod.reset_caches()
    assert run(box.execute("take_screenshot", {})) == "ran"


def test_desktop_state_tells_a_non_admin_nothing_about_the_host(box, accounts, monkeypatch):
    from agentos import host
    monkeypatch.setattr(host, "list_windows", lambda: {"available": True, "windows": [
        {"id": "1", "app": "x", "title": "admin's secret doc", "focused": True}]})
    with usersmod.as_user(accounts[1]):
        assert "secret doc" not in run(box.execute("desktop_state", {}))
    with usersmod.as_user(accounts[0]):
        assert "secret doc" in run(box.execute("desktop_state", {}))


def test_a_non_admins_notify_stays_off_the_hosts_desktop(box, accounts, monkeypatch):
    from agentos import desktop, server as srv
    popped, heard = [], []
    monkeypatch.setattr(desktop, "send_notification", lambda t, m="": popped.append(t) or True)

    async def fake(ev, uid):
        heard.append((ev, uid))
    monkeypatch.setitem(srv.state, "broadcast_user", fake)
    with usersmod.as_user(accounts[1]):
        run(box.execute("notify", {"title": "hi"}))
    assert not popped and heard[0][1] == accounts[1]
    with usersmod.as_user(accounts[0]):
        run(box.execute("notify", {"title": "hi"}))
    assert popped == ["hi"]


def test_a_shell_command_reaches_only_the_asking_accounts_pages(accounts, monkeypatch):
    from agentos import server as srv
    ada, bob = accounts
    sent = []

    async def fake(ev, uid):
        sent.append(uid)
        srv.state["shell_pending"][ev["id"]].set_result({"ok": True, "data": "mine"})
    monkeypatch.setitem(srv.state, "broadcast_user", fake)
    monkeypatch.setitem(srv.state, "clients", {"ws-ada"})
    monkeypatch.setitem(srv.state, "client_uids", {"ws-ada": ada})
    monkeypatch.setitem(srv.state, "shell_pending", {})
    monkeypatch.setitem(srv.state, "shell_owner", {})
    with usersmod.as_user(bob):
        ok, why = run(srv.shell_command("list_open_apps"))
    assert not ok and "no desktop shell" in why and not sent, "bob's agent heard ada's browser"
    with usersmod.as_user(ada):
        assert run(srv.shell_command("list_open_apps")) == (True, "mine")
    assert sent == [ada]


def test_another_accounts_page_cannot_answer_a_shell_command(accounts, monkeypatch):
    from agentos import server as srv
    ada, bob = accounts

    async def main():
        fut = asyncio.get_event_loop().create_future()
        monkeypatch.setitem(srv.state, "shell_pending", {"c1": fut})
        monkeypatch.setitem(srv.state, "shell_owner", {"c1": ada})
        with usersmod.as_user(bob):
            r = await srv.api_shell_result({"id": "c1", "ok": True, "data": "forged"})
        assert getattr(r, "status_code", 200) == 404 and not fut.done()
        with usersmod.as_user(ada):
            await srv.api_shell_result({"id": "c1", "ok": True, "data": "real"})
        assert fut.result()["data"] == "real"
    run(main())


# -- item 2: a pin to an agent CLI is the machine's login -----------------------------------------
def test_a_non_admin_cannot_pin_an_agent_to_a_cli(box, accounts, monkeypatch):
    from agentos import executors
    monkeypatch.setattr(executors, "probe", lambda e: {"installed": True})
    monkeypatch.setattr(usersmod, "_machine", [{"engine": "aria"}])
    d = {"name": "res", "model": "claude-code/default"}
    with usersmod.as_user(accounts[1]):
        box.store.save_subagent({"name": "res", "persona": "x", "tools": []})
        with pytest.raises(ValueError):
            fabricmod.set_agent_model(box.store, box.cfg, "res", "claude-code/default")
        b = fabricmod.agent_brain(box.cfg, d)
        assert not b.get("own") and "admin" in b["note"]
    with usersmod.as_user(accounts[0]):
        assert fabricmod.agent_brain(box.cfg, d).get("own")
    # the brain the admin already chose is one everybody rides
    monkeypatch.setattr(usersmod, "_machine", [{"engine": "claude-code"}])
    with usersmod.as_user(accounts[1]):
        assert fabricmod.agent_brain(box.cfg, d).get("own")


# -- item 3: full autonomy doesn't answer for an empty cell ----------------------------------------
@pytest.mark.parametrize("action", ["agent.message", "device.get"])
def test_an_undecided_ask_needs_a_person_at_full_autonomy(action):
    dec = policymod.Decision("ask", "why", rule="default", grant_offer={"x": 1})
    dec.action = action
    assert policymod.person_rule(policymod.MAIN, "ask_agent", {}, dec, None)
    assert dec.grant_offer, "the card still offers to fill the cell"


def test_an_ordinary_ask_is_still_autonomys():
    dec = policymod.Decision("ask", "why", rule="default")
    dec.action = "fs.write"
    assert not policymod.person_rule(policymod.MAIN, "write_file", {}, dec, None)


# -- item 4: losing a config key must not hand out the machine --------------------------------------
def test_a_config_that_lost_its_migration_key_grants_no_app_everything(monkeypatch):
    import json
    from fastapi.testclient import TestClient
    srv = _srv()
    monkeypatch.setattr(srv, "_propose_manifest", lambda *a: None)
    with TestClient(srv.app):
        aid = srv.state["store"].save_app("old-app", "", "", "<html></html>")
        srv.state["store"].db.execute("UPDATE user_apps SET manifest_status='none' WHERE id=?", (aid,))
        srv.state["store"].db.commit()
    data = json.loads(cfgmod.CONFIG_PATH.read_text())
    data.pop("permissions_migrated", None)
    cfgmod.CONFIG_PATH.write_text(json.dumps(data))
    with TestClient(srv.app):
        rows = srv.state["store"].db.execute(
            "SELECT * FROM grants WHERE principal_kind='app' AND principal_id=? AND action='*'", (aid,)).fetchall()
    assert not rows, "losing one config key gave an app the whole machine"


# -- item 9: a credential inside a value with an innocent name ---------------------------------------
def _srv():
    from agentos import server
    return server


def test_a_credential_inside_a_tool_servers_address_or_args_is_masked():
    m = _srv()._mask_secrets
    conf = {"url": "https://u:hunter2@x.example/sse?token=abc123&v=1", "command": "npx foo --api-key sk-zzz",
            "args": ["--api-key", "tok-999", "--port", "80", "--token=tok-888", "https://tok777@x.example/"]}
    shown = m({"mcp_servers": {"s": conf}})["mcp_servers"]["s"]
    text = str(shown)
    for secret in ("hunter2", "abc123", "sk-zzz", "tok-999", "tok-888", "tok777"):
        assert secret not in text, secret
    assert "x.example" in shown["url"] and shown["args"][1] == "•••" and shown["args"][3] == "80"


def test_a_masked_address_sent_back_keeps_the_real_one():
    srv = _srv()
    old = {"s": {"url": "https://u:hunter2@x.example/sse", "args": ["--api-key", "tok-999", "--port", "80"],
                 "command": "npx foo --token abc"}}
    shown = srv._mask_secrets(old)
    assert srv._keep_masked(shown, old) == old
    # a changed port is kept, the secret beside it comes back
    shown["s"]["args"][3] = "81"
    assert srv._keep_masked(shown, old)["s"]["args"] == ["--api-key", "tok-999", "--port", "81"]
    # a mask carried to a new host must not take the secret with it
    shown["s"]["url"] = "https://u:•••@evil.example/sse"
    assert srv._keep_masked(shown, old)["s"]["url"] == old["s"]["url"]


# -- item 10: spending on the machine's providers goes through the gate -------------------------------
def test_the_model_plane_is_decided_and_on_the_ledger(tmp_path, monkeypatch):
    srv = _srv()
    from agentos.policy import PDP
    store = Store(tmp_path / "db.sqlite")
    cfg = cfgmod.load_config()
    pdp = PDP(cfg, store)
    monkeypatch.setitem(srv.state, "pdp", pdp)
    monkeypatch.setitem(srv.state, "store", store)
    monkeypatch.setitem(srv.state, "cfg", cfg)

    async def chat(*a, **k):
        yield {"type": "text", "text": "hi"}
    monkeypatch.setattr(srv.providers, "chat", chat)
    out = run(srv.api_plane_llm({"model": "openai/x", "messages": []}))
    assert out["content"] == "hi"
    rows = store.db.execute("SELECT * FROM audit WHERE action='model.use'").fetchall()
    assert rows and dict(rows[-1])["resource"] == "model:openai/x"
    store.add_grant("user", "", "model.use", "model:openai/*", effect="deny", source="user")
    assert run(srv.api_plane_llm({"model": "openai/x", "messages": []})).status_code == 403
    r = run(srv.api_evals_run({"models": ["openai/x"]}))
    assert r.status_code == 403


# -- item 11: a font this desktop will refuse is said ------------------------------------------------
def test_a_font_the_csp_refuses_is_said(box):
    out = run(box.execute("create_theme", {"name": "T", "font_url": "https://fonts.example.com/a.css", "font_family": "A"}))
    assert "fonts.googleapis.com" in out
    ok = run(box.execute("create_theme", {"name": "U", "font_url": "https://fonts.googleapis.com/css2?family=A"}))
    assert "won't load" not in ok
    js = (ROOT / "ui/src/js/18-themes-personalize.js").read_text()
    assert "function themeFontNote" in js and "tb-fnote" in js


# -- item 12: the Remote Desktop app frames its own page ---------------------------------------------
def test_only_the_desktop_may_frame_remote_desktop():
    from fastapi.testclient import TestClient
    srv = _srv()
    with TestClient(srv.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 5000)) as c:
        r = c.get("/remote-desktop")
        csp = r.headers["content-security-policy"]
        assert "frame-ancestors 'self'" in csp and r.headers["x-frame-options"] == "SAMEORIGIN"
        d = c.get("/login")
        assert "frame-ancestors 'none'" in d.headers["content-security-policy"]


# -- item 13: the rules at the end of a forwarded lead's note survive --------------------------------
def test_a_forwarded_leads_whole_note_reaches_it(tmp_path):
    from agentos import executors as ex
    subs = [{"name": f"agent{i}", "description": "does a real job with several words in it", "tools": [],
             "enabled": True} for i in range(12)]
    note = ex.context_for("") + "\n\n" + "s" * 3000 + ex.team_note(subs) + ex.workspace_note() + ex.capability_note()
    kept = ex.Envelope(workspace=str(tmp_path), context=note).sanitized().context
    assert ex.capability_note().strip() in kept, "the rule to use this OS's doors was cut off"
    assert ex.team_note(subs).strip() in kept, "half the team list was cut off"


# -- item 14: a jailed CLI has no `bento`, so the note says where a company is made --------------------
def test_the_door_says_a_company_is_not_made_from_here():
    from agentos import executors as ex
    src = (ROOT / "executors.py").read_text()
    door = src[src.index("def open_team_door("):src.index("def _pool_note(")]
    assert "dept_note + COMPANY_DOOR_LINE" in door
    assert "can't set up" in ex.COMPANY_DOOR_LINE and "Office" in ex.COMPANY_DOOR_LINE


# ---- a browser you start through Bento is let in; one Bento starts for itself is told why (item 15) ----

def _opened(monkeypatch):
    from agentos import desktop
    seen = []
    monkeypatch.setattr(desktop, "open_path", lambda target: seen.append(target) or "")
    return seen


def test_a_person_opening_this_desktop_in_the_hosts_browser_gets_a_ticket(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import remote, server
    seen = _opened(monkeypatch)
    from agentos import config as cfgmod
    port = server._port_of(cfgmod.load_config())
    with TestClient(server.app) as c:
        assert c.post("/api/open", json={"url": f"http://127.0.0.1:{port}/"}).status_code == 200
        assert c.post("/api/open", json={"url": "https://example.com/x"}).status_code == 200
        assert c.post("/api/open", json={"url": f"http://127.0.0.1:{port}/api/config"}).status_code == 200
    own, other, api = seen
    assert "desk=" in own and remote.spend_ticket(own.split("desk=")[1])
    assert other == "https://example.com/x", "only this desktop's own page gets one"
    assert "desk=" not in api, "an API address is not a page to be let into"


def test_an_agent_opening_this_desktop_gets_no_ticket(tmp_path, monkeypatch):
    from agentos import server
    seen = _opened(monkeypatch)
    from agentos import config as cfgmod
    port = server._port_of(cfgmod.load_config())
    tb = Toolbox({"workspace": str(tmp_path)}, Store(str(tmp_path / "a.db")))
    asyncio.run(tb.open_app(f"http://127.0.0.1:{port}/"))
    assert seen and "desk=" not in seen[0]


def test_a_browser_bento_started_is_told_why_and_asked_nothing(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import peercheck, server
    monkeypatch.setattr(server, "_peer_verdict", lambda conn: peercheck.CHILD)
    with TestClient(server.app) as c:
        d = c.get("/api/users/who").json()
    assert d["refused"] == server.CHILD_PAGE_WORDS
    page = (Path(agentos.__file__).parent / "ui" / "login.html").read_text()
    assert "d.refused" in page and "f.hidden=true" in page
