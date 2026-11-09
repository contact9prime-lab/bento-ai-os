"""The way in: who the server believes, on HTTP and on every socket.

Each test here failed before the fix it is named for. The ones that need a real peer (a child process, a
real Host header) start a real server on a throwaway home at the bottom of this file.
"""
import asyncio
import base64
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest
import websockets
from fastapi.testclient import TestClient

from agentos import config as cfgmod
from agentos import peercheck
from agentos import remote as remotemod
from agentos import secevents
from agentos import server as servermod
from agentos import users as usersmod

LAN = ("192.168.1.50", 51234)
PW = "correct horse battery"


@pytest.fixture()
def clean(tmp_path, monkeypatch):
    """A machine with no accounts and nothing armed, whatever an earlier test left behind."""
    secevents.forget_for_tests()
    remotemod.reset_failures()
    monkeypatch.setattr(usersmod, "_last_good", {})
    usersmod._unreadable[0] = False
    yield tmp_path
    secevents.forget_for_tests()
    remotemod.reset_failures()
    usersmod.reset_caches()


def _cfg():
    return servermod.state.machine_cfg()


class Peer:
    """One more browser, on the server `api` already started. Entering a TestClient re-runs startup,
    which replaces the machine's config this test just armed."""
    def __init__(self, **kw):
        self.c = TestClient(servermod.app, **kw)

    def __enter__(self):
        return self.c

    def __exit__(self, *a):
        self.c.close()


def arm(on=True):
    r = _cfg().setdefault("remote", {})
    r["pass_hash"], r["pass_salt"] = remotemod.hash_passphrase(PW)
    r["enabled"] = on
    r["trust_loopback"] = True


def disarm():
    r = _cfg().setdefault("remote", {})
    r.update(enabled=False, pass_hash="", pass_salt="", trust_loopback=True, allowed_hosts=[], sgen=0)


@pytest.fixture()
def api(clean):
    with TestClient(servermod.app) as c:
        disarm()
        yield c
        disarm()


def kinds():
    return {e["kind"] for e in secevents.recent(200)}


# ---- S-01 the name ---------------------------------------------------------------------------------

@pytest.mark.parametrize("host,ok", [
    ("127.0.0.1:8321", True), ("localhost:8321", True), ("[::1]:8321", True), ("LOCALHOST", True),
    ("192.168.1.5:8321", True), ("100.101.102.103", True), ("[fe80::1]:8321", True), ("0.0.0.0:8321", True),
    ("mypc.tailabc.ts.net", True), ("bento.localhost", True), ("", True),
    ("evil.example:8321", False), ("evil.local", False), ("127.0.0.1.evil.example", False),
    ("localhost.evil.example", False), ("a b", False), ("[::1", False), ("x:y", False),
])
def test_only_names_this_machine_has_are_answered(host, ok, monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "mypc")
    assert remotemod.host_allowed({}, host) is ok


@pytest.mark.parametrize("host", ["mypc", "mypc.local", "MyPC.local.", "mypc-2.local", "mypc.lan", "mypc.home",
                                  "mypc.fritz.box"])
def test_a_phone_reaching_this_machine_by_its_own_name_is_answered(host, monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "mypc")
    assert remotemod.host_allowed({}, host)
    monkeypatch.setattr(socket, "gethostname", lambda: "mypc.local")   # macOS says it in full
    assert remotemod.host_allowed({}, host)


def test_a_deployment_can_say_what_it_is_called(monkeypatch):
    monkeypatch.delenv("AGENTOS_ALLOWED_HOSTS", raising=False)
    assert not remotemod.host_allowed({}, "bento.example.com")
    assert remotemod.host_allowed({"remote": {"allowed_hosts": ["bento.example.com"]}}, "bento.example.com:443")
    assert remotemod.host_allowed({"remote": {"allowed_hosts": ["*.example.com"]}}, "a.example.com")
    assert not remotemod.host_allowed({"remote": {"allowed_hosts": ["*.example.com"]}}, "example.com.evil.net")
    assert remotemod.host_allowed({"remote": {"allowed_hosts": ["*"]}}, "anything.at.all")
    monkeypatch.setenv("AGENTOS_ALLOWED_HOSTS", "a.example.org, b.example.org")
    assert remotemod.host_allowed({}, "b.example.org")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://bento-x.onrender.com")
    assert remotemod.host_allowed({}, "bento-x.onrender.com")
    monkeypatch.setenv("FLY_APP_NAME", "mybento")
    assert remotemod.host_allowed({}, "mybento.fly.dev")


def test_a_rebinding_page_is_refused_before_anything_trusts_loopback(api):
    with Peer( base_url="http://evil.example:8321", client=("127.0.0.1", 5000)) as c:
        r = c.post("/api/grants", json={"principal_kind": "app", "principal_id": "x", "action": "tool.use"},
                   headers={"Origin": "http://evil.example:8321"})
        assert r.status_code == 421 and "--allow-host evil.example" in r.json()["error"]
        assert c.get("/").status_code == 421
    assert "host.refused" in kinds()


@pytest.mark.parametrize("path", ["/ws", "/ws/terminal", "/ws/vnc", "/ws/browser", "/ws/appstream"])
def test_a_rebinding_page_cannot_open_any_socket(api, path):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e, api.websocket_connect(
            path, headers={"host": "evil.example:8321", "origin": "http://evil.example:8321"}) as ws:
        ws.receive_text()
    assert e.value.code == 4421


def test_a_door_with_its_own_secret_does_not_care_about_the_name(api):
    with Peer( base_url="http://hooks.example", client=LAN) as c:
        assert c.post("/api/hooks/nope/nope?k=x", json={}).status_code != 421


def test_a_cross_origin_request_is_on_the_record(api):
    assert api.post("/api/grants", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert "origin.refused" in kinds()


# ---- S-02 off means off ----------------------------------------------------------------------------

def test_turning_remote_off_gives_the_network_nothing(api):
    arm()
    with Peer( client=LAN) as lan:
        assert lan.get("/api/config").status_code == 401
        disarm()
        assert lan.get("/api/config").status_code == 401, "remote off used to read as nothing to gate"
        assert lan.post("/api/grants", json={"principal_kind": "user", "principal_id": "x",
                                             "action": "tool.use"}).status_code == 401
    assert api.get("/api/config").status_code == 200, "somebody at the machine is unchanged"


def test_a_good_cookie_is_refused_too_once_remote_is_off(api):
    arm()
    cookie = remotemod.issue_session(_cfg())
    with Peer( client=LAN, cookies={remotemod.COOKIE: cookie}) as lan:
        assert lan.get("/api/config").status_code == 200
        _cfg()["remote"]["enabled"] = False
        assert lan.get("/api/config").status_code == 401


def test_switching_it_off_stops_tunnels_and_says_what_is_still_bound(api, monkeypatch):
    from agentos import tunnel
    stopped = []

    async def stop(cfg):
        stopped.append(True)
        return ["cloudflared"]
    monkeypatch.setattr(tunnel, "stop_published", stop)
    monkeypatch.setenv("AGENTOS_BOUND_HOST", "0.0.0.0")
    arm()
    d = api.post("/api/remote", json={"enabled": False}).json()
    assert stopped and d["tunnels_stopped"] == ["cloudflared"]
    assert d["still_bound"] == "0.0.0.0" and d["restart_required"] and "0.0.0.0" in d["note"]


def test_tailscale_is_stopped_only_when_it_publishes_this_port(monkeypatch):
    import asyncio

    from agentos import tunnel
    calls = []

    async def run(argv, timeout=25):
        calls.append(argv)
        return 0, '{"TCP":{"443":{}},"Web":{"x":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:9999"}}}}}'
    monkeypatch.setattr(tunnel, "_which", lambda n: "/x/tailscale")
    monkeypatch.setattr(tunnel, "_run", run)
    assert asyncio.run(tunnel.stop_published({"port": 8321})) == []
    assert not any("reset" in c for c in calls), "somebody's other service must survive this"
    assert asyncio.run(tunnel.stop_published({"port": 9999})) == ["tailscale"]


# ---- S-50 a proxy --------------------------------------------------------------------------------

@pytest.mark.parametrize("h", [{"X-Forwarded-For": "8.8.8.8"}, {"X-Forwarded-For": "127.0.0.1"},
                               {"Forwarded": "for=8.8.8.8"}, {"X-Real-IP": "8.8.8.8"}, {"CF-Connecting-IP": "8.8.8.8"},
                               {"X-Forwarded-Proto": "https"}])
def test_a_proxied_visitor_is_never_local(api, h):
    arm()
    with Peer( client=("127.0.0.1", 5000)) as c:
        assert c.get("/api/config").status_code == 200, "the same peer with no headers is the person"
        assert c.get("/api/config", headers=h).status_code == 401


def test_a_spoofed_forwarded_header_cannot_claim_loopback(api):
    assert remotemod.client_addr("127.0.0.1", {"x-forwarded-for": "127.0.0.1"}) == "forwarded"
    assert remotemod.client_addr("127.0.0.1", {"x-forwarded-for": "127.0.0.1, 9.9.9.9"}) == "9.9.9.9"
    assert remotemod.client_addr("10.0.0.2", {"x-forwarded-for": "127.0.0.1"}) == "10.0.0.2"


def test_uvicorn_is_pinned_not_to_believe_proxy_headers():
    import inspect

    from agentos import __main__ as m
    from agentos import desktop
    assert "proxy_headers=False" in inspect.getsource(m.serve)
    assert "proxy_headers=False" in inspect.getsource(desktop._start_server_thread)


def test_trust_loopback_off_needs_a_sign_in_at_the_machine(api):
    arm()
    _cfg()["remote"]["trust_loopback"] = False
    assert api.get("/api/config").status_code == 401
    disarm()
    assert api.get("/api/config").status_code == 200, "with remote off there may be no key to sign in with"


# ---- S-13 the checks a child meets ---------------------------------------------------------------

def test_a_child_is_refused_with_a_sentence_and_flagged(api, monkeypatch):
    monkeypatch.setattr(peercheck, "classify", lambda *a: peercheck.CHILD)
    with Peer( base_url="http://127.0.0.1:8321", client=("127.0.0.1", 5000)) as c:
        # TestClient's own scope has server=("127.0.0.1", 8321) with this base_url
        r = c.post("/api/grants", json={"principal_kind": "user", "principal_id": "x", "action": "tool.use"})
        assert r.status_code == 401 and "running inside Bento" in r.json()["error"]
        assert c.get("/api/users/who").status_code == 200, "what is open to everybody stays open"
    assert "child.refused" in kinds()


def test_a_token_route_does_not_rest_on_that_trust(api, monkeypatch):
    monkeypatch.setattr(peercheck, "classify", lambda *a: peercheck.CHILD)
    with Peer( base_url="http://127.0.0.1:8321", client=("127.0.0.1", 5000)) as c:
        got = c.post("/api/mcp/run/not-a-token", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert "inside Bento" not in got.text, "it reaches the bridge, which refuses the token itself"
        assert c.post("/api/hooks/nope/nope?k=x", json={}).status_code != 401


def test_another_unix_users_process_is_not_the_person(api, monkeypatch):
    monkeypatch.setattr(peercheck, "classify", lambda *a: peercheck.OTHER_USER)
    with Peer( base_url="http://127.0.0.1:8321", client=("127.0.0.1", 5000)) as c:
        r = c.get("/api/config")
        assert r.status_code == 401 and "Another user" in r.json()["error"]
    assert "peer.other_user" in kinds()


def test_a_card_that_must_be_a_persons_is_not_answered_by_an_app_token(api):
    import asyncio
    fut = asyncio.new_event_loop().create_future()
    servermod.state["pending_approvals"]["t1"] = {"fut": fut, "uid": "", "must_person": True, "offer": None}
    servermod.state["app_tokens"]["tok"] = {"app_id": "a", "uid": ""}
    try:
        r = api.post("/api/fabric/approvals/t1", json={"approved": True}, headers={"X-App-Token": "tok"})
        assert r.status_code == 403 and not fut.done()
    finally:
        servermod.state["pending_approvals"].pop("t1", None)
        servermod.state["app_tokens"].pop("tok", None)


# ---- a browser Bento starts ----------------------------------------------------------------------

def test_a_browser_started_by_the_server_trades_a_ticket_for_a_cookie(api, monkeypatch):
    t = remotemod.mint_ticket()
    monkeypatch.setattr(peercheck, "classify", lambda *a: peercheck.CHILD)
    with Peer( base_url="http://127.0.0.1:8321", client=("127.0.0.1", 5000),
                    follow_redirects=False) as c:
        assert c.get("/api/config").status_code == 401
        r = c.get(f"/?desk={t}")
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert c.get("/api/config").status_code == 200, "the cookie is what makes it the person's"
        c.cookies.clear()
        assert c.get(f"/?desk={t}").status_code != 303, "a ticket works once"


def test_a_ticket_is_no_way_round_a_lock(api):
    arm(on=False)
    remotemod.set_desk_locked(True)
    try:
        with Peer(follow_redirects=False) as c:
            assert c.get(f"/?desk={remotemod.mint_ticket()}").status_code != 303
    finally:
        remotemod.set_desk_locked(False)


def test_a_forged_or_expired_ticket_opens_nothing(monkeypatch):
    t = remotemod.mint_ticket()
    assert not remotemod.spend_ticket(t[:-1] + ("0" if t[-1] != "0" else "1"))
    assert not remotemod.spend_ticket("garbage")
    monkeypatch.setattr(remotemod, "TICKET_S", -1)
    assert not remotemod.spend_ticket(remotemod.mint_ticket())


def test_a_ticket_is_no_way_in_from_the_network(api):
    arm()
    with Peer( client=LAN, follow_redirects=False) as lan:
        assert lan.get(f"/?desk={remotemod.mint_ticket()}").status_code != 303


# ---- S-49 ------------------------------------------------------------------------------------------

def test_an_unreadable_accounts_file_refuses_the_network_and_is_flagged(api):
    usersmod.registry_path().parent.mkdir(parents=True, exist_ok=True)
    usersmod.registry_path().write_text("{ not json")
    try:
        assert usersmod.unreadable() and not usersmod.enabled()
        arm()
        cookie = remotemod.issue_session(_cfg())
        with Peer( client=LAN, cookies={remotemod.COOKIE: cookie}) as lan:
            assert lan.get("/api/config").status_code == 401
        assert api.get("/api/config").status_code == 200, "somebody at the machine can still repair it"
        assert "account.unreadable" in kinds()
        with pytest.raises(ValueError, match="left alone"):
            usersmod.create("ada", "a long password")
        assert usersmod.registry_path().read_text() == "{ not json"
    finally:
        usersmod.registry_path().unlink()
    assert not usersmod.unreadable(), "absent is a machine with no accounts"


def test_a_passing_fault_keeps_the_accounts_this_process_knows(api, monkeypatch):
    usersmod.create("ada", "a long password")
    assert usersmod.enabled()
    real = type(usersmod.registry_path()).read_text

    def boom(self, *a, **k):
        if self.name == "users.json":
            raise OSError(24, "Too many open files")
        return real(self, *a, **k)
    monkeypatch.setattr(type(usersmod.registry_path()), "read_text", boom)
    assert usersmod.enabled() and not usersmod.unreadable(), "out of descriptors must not open the machine"
    monkeypatch.undo()


# ---- S-51 S-52 sessions ---------------------------------------------------------------------------

def _users(n=2):
    a = usersmod.create("ada", "a long password")
    b = usersmod.create("bob", "another long password") if n > 1 else None
    return a, b


def _signed_in(uid_cookie, client=None):
    return Peer(client=client or ("testclient", 50000), cookies={remotemod.COOKIE: uid_cookie})


def test_a_password_change_ends_every_other_session_and_keeps_this_one(api):
    a, _ = _users()
    old = remotemod.issue_session(_cfg(), a["id"])
    copy = remotemod.issue_session(_cfg(), a["id"])
    with _signed_in(old) as c:
        r = c.put(f"/api/users/{a['id']}", json={"password": "a third long password",
                                                 "current": "a long password"})
        assert r.status_code == 200
        assert c.get("/api/config").status_code == 200, "this browser was handed a new cookie"
    with _signed_in(copy) as stolen:
        assert stolen.get("/api/config").status_code == 401
    assert "account.role" in kinds()


def test_a_role_change_ends_that_accounts_sessions(api):
    a, b = _users()
    bobs = remotemod.issue_session(_cfg(), b["id"])
    with _signed_in(remotemod.issue_session(_cfg(), a["id"])) as admin:
        assert admin.put(f"/api/users/{b['id']}", json={"role": "admin"}).status_code == 200
    with _signed_in(bobs) as c:
        assert c.get("/api/config").status_code == 401


def test_a_cookie_from_before_the_upgrade_works_for_an_account_that_has_not_changed(api):
    a, _ = _users()
    claims = {"exp": int(time.time()) + 999, "uid": a["id"], "jti": "old"}      # no "g": what 0.6 issued
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    import hashlib
    import hmac
    sig = hmac.new(remotemod._secret(_cfg()), body.encode(), hashlib.sha256).hexdigest()[:32]
    old = f"{body}.{sig}"
    assert remotemod.session_user(_cfg(), old) == a["id"]
    usersmod.end_sessions(a["id"])
    assert remotemod.session_user(_cfg(), old) is None
    assert remotemod.session_user(_cfg(), remotemod.issue_session(_cfg(), a["id"])) == a["id"]


def test_signing_out_ends_any_copy_of_that_cookie_and_only_that_one(api):
    a, _ = _users()
    this, other = remotemod.issue_session(_cfg(), a["id"]), remotemod.issue_session(_cfg(), a["id"])
    with _signed_in(this) as c:
        assert c.post("/api/users/logout").status_code == 200
    assert remotemod.session_claims(_cfg(), this) is None
    assert remotemod.session_claims(_cfg(), other) is not None


def test_sign_out_everywhere_is_the_account_and_an_admins_to_use(api):
    a, b = _users()
    bobs = remotemod.issue_session(_cfg(), b["id"])
    with _signed_in(bobs) as c:
        assert c.post("/api/session/everywhere", json={"uid": a["id"]}).status_code == 403
    with _signed_in(remotemod.issue_session(_cfg(), a["id"])) as admin:
        assert admin.post("/api/session/everywhere", json={"uid": b["id"]}).status_code == 200
    assert remotemod.session_claims(_cfg(), bobs) is None


def test_the_cookie_from_before_a_lock_cannot_open_the_screen(api):
    a, _ = _users()
    before = remotemod.issue_session(_cfg(), a["id"])
    with _signed_in(before) as c:
        assert c.post("/api/session/lock").status_code == 200
    assert remotemod.session_claims(_cfg(), before) is None, "it verified by the same path before"


def test_an_ended_session_survives_a_restart(api):
    a, _ = _users()
    tok = remotemod.issue_session(_cfg(), a["id"])
    remotemod.end_session(remotemod.session_claims(_cfg(), tok))
    remotemod._denied_cache.update(path="", mtime=-1, ids={})
    assert remotemod.session_claims(_cfg(), tok) is None
    assert stat.S_IMODE(os.stat(remotemod._denied_path()).st_mode) == 0o600


class _FakeSocket:
    """Enough of a WebSocket for the recheck, on a real cookie."""
    def __init__(self, token):
        from starlette.websockets import WebSocketState
        self.application_state = self.client_state = WebSocketState.CONNECTED
        self.cookies = {remotemod.COOKIE: token}
        self.headers = {}
        self.scope = {}
        self.client = type("c", (), {"host": "127.0.0.1", "port": 1})()
        self.closed = None

    async def close(self, code=1000):
        self.closed = code


def _open(token):
    ws = _FakeSocket(token)
    servermod._WS_LIVE.add(ws)
    return ws


def test_a_lock_a_sign_out_and_a_deleted_account_close_open_sockets(api):
    a, b = _users()
    locked_one = remotemod.issue_session(_cfg(), a["id"])
    signed_out = remotemod.issue_session(_cfg(), a["id"])
    deleted = remotemod.issue_session(_cfg(), b["id"])
    still_fine = remotemod.issue_session(_cfg(), a["id"])
    s1, s2, s3, s4 = _open(locked_one), _open(signed_out), _open(deleted), _open(still_fine)
    with _signed_in(locked_one) as c:
        assert c.post("/api/session/lock").status_code == 200
    assert s1.closed == 4401 and s2.closed is None
    with _signed_in(signed_out) as c:
        c.post("/api/users/logout")
    assert s2.closed == 4401 and s3.closed is None
    with _signed_in(still_fine) as admin:
        assert admin.delete(f"/api/users/{b['id']}").status_code == 200
    assert s3.closed == 4401 and s4.closed is None
    servermod._WS_LIVE.discard(s4)


# ---- S-53 S-85 S-48 sign-in ------------------------------------------------------------------------

def _try(c, name, pw):
    return c.post("/api/users/login", json={"name": name, "password": pw})


def test_your_own_good_sign_in_does_not_buy_guesses_at_somebody_else(api):
    usersmod.create("ada", "a long password")
    usersmod.create("mallory", "mallorys long password", role="executor")
    with Peer( client=LAN) as c:
        arm()
        got_locked = False
        for _ in range(4):
            for _ in range(4):
                r = _try(c, "ada", "wrong guess")
                got_locked = got_locked or r.status_code == 429
            assert _try(c, "mallory", "mallorys long password").status_code in (200, 429)
        assert got_locked or remotemod.target_locked_for("ada") > 0, "20 guesses used to lock nothing"
        # and she herself is not cleared by anybody else's success
        assert remotemod.target_locked_for("ada") > 0
    remotemod.note_target_success("ada")
    assert remotemod.target_locked_for("ada") == 0


def test_the_person_at_the_machine_is_not_locked_out_by_a_stranger_guessing(api):
    usersmod.create("ada", "a long password")
    for _ in range(remotemod.TARGET_AFTER + 2):
        remotemod.note_target_failure("ada")
    assert remotemod.target_locked_for("ada") > 0
    assert _try(api, "ada", "a long password").status_code == 200


def test_being_locked_says_nothing_about_whether_a_name_exists(api):
    usersmod.create("ada", "a long password")
    for _ in range(remotemod.TARGET_AFTER):
        remotemod.note_target_failure("nobody-by-this-name")
    with Peer( client=LAN) as c:
        arm()
        assert _try(c, "nobody-by-this-name", "x").status_code == 429


def test_the_target_table_is_bounded(api):
    for i in range(remotemod.TARGET_KEEP + 50):
        remotemod.note_target_failure(f"name{i}")
    assert len(remotemod._target_fails) <= remotemod.TARGET_KEEP


def test_a_name_nobody_has_costs_as_much_as_one_somebody_has(api):
    usersmod.create("ada", "a long password")

    def clock(name):
        best = 9.0
        for _ in range(3):
            t = time.perf_counter()
            usersmod.verify_login(name, "wrong guess")
            best = min(best, time.perf_counter() - t)
        return best
    known, unknown = clock("ada"), clock("nobody")
    assert abs(known - unknown) < max(known, unknown) * .6
    assert unknown > .002, "the hash ran"


def test_failed_sign_ins_are_on_the_record_and_a_burst_alerts(api):
    usersmod.create("ada", "a long password")
    with Peer( client=LAN) as c:
        arm()
        for _ in range(remotemod.LOCKOUT_AFTER):
            _try(c, "ada", "wrong")
    evs = secevents.recent(100)
    assert any(e["kind"] == "login.failed" and e.get("alert") for e in evs)
    assert any(e["kind"] == "login.locked" for e in evs)
    assert not any("wrong" in json.dumps(e) for e in evs), "a guess may be somebody's real password"


def test_a_forged_cookie_is_on_the_record_and_an_expired_one_is_not(api):
    arm()
    with Peer( client=LAN, cookies={remotemod.COOKIE: "forged.forged"}) as c:
        assert c.get("/api/config").status_code == 401
    assert "session.forged" in kinds()
    secevents.forget_for_tests()
    secevents._path().unlink(missing_ok=True)
    old = remotemod.issue_session(_cfg())
    remotemod._forgery_quiet[0] = 0
    assert not remotemod.cookie_forged(_cfg(), old)
    remotemod.quiet_forgeries(60)
    assert not remotemod.cookie_forged(_cfg(), "forged.forged")
    remotemod._forgery_quiet[0] = 0


# ---- S-54 --------------------------------------------------------------------------------------------

ROUTES = [("post", "/api/update"), ("post", "/api/update/rollback"), ("post", "/api/update/restart"),
          ("post", "/api/remote"), ("post", "/api/components/x/install")]


@pytest.mark.parametrize("method,path", ROUTES[:4])
def test_loopback_alone_is_not_an_admin_on_a_machine_with_accounts(api, method, path):
    usersmod.create("ada", "a long password")
    b = usersmod.create("bob", "another long password", role="executor")
    with _signed_in(remotemod.issue_session(_cfg(), b["id"])) as c:
        r = getattr(c, method)(path, json={})
        assert r.status_code == 403 and "admin" in r.json()["error"]


def test_a_non_admin_cannot_turn_remote_access_on_from_the_keyboard(api):
    usersmod.create("ada", "a long password")
    b = usersmod.create("bob", "another long password", role="executor")
    with _signed_in(remotemod.issue_session(_cfg(), b["id"])) as c:
        assert c.post("/api/remote", json={"enabled": True}).status_code == 403
        assert c.put("/api/channels/remote", json={"enabled": True}).status_code == 403
    assert not _cfg()["remote"].get("enabled")


# ---- S-83 S-97 files --------------------------------------------------------------------------------

def test_a_secret_file_is_private_from_its_first_byte(tmp_path):
    tmp_path = tmp_path / "d"
    p = tmp_path / "secret.json"
    old = os.umask(0)
    try:
        cfgmod.write_private(p, "x")
    finally:
        os.umask(old)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and p.read_text() == "x"
    assert [f.name for f in tmp_path.iterdir()] == ["secret.json"], "no temporary file left"


def test_a_write_that_fails_leaves_the_old_file_and_no_temporary(tmp_path, monkeypatch):
    tmp_path = tmp_path / "d"
    p = tmp_path / "s"
    cfgmod.write_private(p, "old")
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError):
        cfgmod.write_private(p, "new")
    assert p.read_text() == "old" and [f.name for f in tmp_path.iterdir()] == ["s"]


def test_config_keys_and_accounts_are_0600_whatever_the_umask(clean):
    old = os.umask(0o002)
    try:
        cfgmod.save_config({"a": 1})
        key = cfgmod.AGENTOS_HOME / "session.key"
        key.unlink(missing_ok=True)
        remotemod._machine_key()
        u = usersmod.create("ada", "a long password")
        usersmod.save_user_cfg(u["id"], {"theme": "x"})
    finally:
        os.umask(old)
    for f in (cfgmod.CONFIG_PATH, key, usersmod.registry_path(), usersmod.cfg_path_for(u["id"])):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600, f
    assert stat.S_IMODE(cfgmod.AGENTOS_HOME.stat().st_mode) == 0o700


def test_two_starts_at_once_agree_on_one_session_key(clean):
    (cfgmod.AGENTOS_HOME / "session.key").unlink(missing_ok=True)
    a = remotemod._machine_key()
    b = remotemod._machine_key()
    assert a == b


# ---- S-84 --------------------------------------------------------------------------------------------

def test_a_window_with_no_cookie_cannot_walk_round_a_lock(api):
    arm(on=False)
    with Peer() as locker:
        assert locker.post("/api/session/lock").status_code == 200
    try:
        with Peer() as private:
            r = private.get("/api/config")
            assert r.status_code == 401 and "locked" in r.json()["error"]
            # the key opens it from there too, because the browser that locked it may be gone
            assert private.post("/api/remote/login", json={"passphrase": "wrong"}).status_code == 401
            assert private.post("/api/remote/login", json={"passphrase": PW}).status_code == 200
        with Peer() as after:
            assert after.get("/api/config").status_code == 200
    finally:
        remotemod.set_desk_locked(False)


def test_a_machine_with_no_key_is_never_held_by_the_flag(api):
    remotemod.set_desk_locked(True)
    try:
        assert not remotemod.desk_locked(_cfg())
        assert api.get("/api/config").status_code == 200
    finally:
        remotemod.set_desk_locked(False)


# ---- S-41 --------------------------------------------------------------------------------------------

def test_a_server_with_an_entry_key_trusts_loopback_for_nothing(api):
    (cfgmod.AGENTOS_HOME / remotemod.ENTRY_FILE).write_text("the-key")
    remotemod._entry_cache.pop(str(cfgmod.AGENTOS_HOME), None)
    try:
        assert api.get("/api/config").status_code == 401
        assert api.put("/api/config", json={"sandbox": {"enabled": False}}).status_code == 401
        assert api.get("/api/config", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert api.get("/api/config", headers={"Authorization": "Bearer the-key"}).status_code == 200
        with Peer( follow_redirects=False) as browser:
            assert browser.get("/?entry=nope").status_code != 303
            assert browser.get("/?entry=the-key").status_code == 303
            assert browser.get("/api/config").status_code == 200, "its own page keeps working"
    finally:
        remotemod._entry_cache.pop(str(cfgmod.AGENTOS_HOME), None)


def test_the_entry_key_is_not_in_status_or_the_environment(tmp_path, monkeypatch):
    from agentos.demos import warehouse as wh
    monkeypatch.setenv("AGENTOS_DEMO_DIR", str(tmp_path))
    key = wh._mint_entry()
    assert key not in json.dumps(wh.status())
    assert key in wh.keyed_urls()["hub"] and key in wh.keyed_urls()["floor"]
    assert stat.S_IMODE((tmp_path / wh.ENTRY).stat().st_mode) == 0o600
    assert key not in json.dumps(wh._env(wh.HUB))
    assert wh._env(wh.HUB)["AGENTOS_SESSION_COOKIE"] != "agentos_session", "cookies ignore ports"


def test_only_the_demos_own_user_or_an_admin_is_given_its_key(api, monkeypatch, tmp_path):
    from agentos.demos import warehouse as wh
    monkeypatch.setenv("AGENTOS_DEMO_DIR", str(tmp_path))
    key = wh._mint_entry()
    a, b = _users()
    with _signed_in(remotemod.issue_session(_cfg(), b["id"])) as nobody:
        assert key not in nobody.get("/api/demo/warehouse").text
    with _signed_in(remotemod.issue_session(_cfg(), a["id"])) as admin:
        assert key in admin.get("/api/demo/warehouse").text


def test_the_floor_wants_the_key(tmp_path, monkeypatch):
    from agentos.demos import warehouse as wh
    monkeypatch.setenv("AGENTOS_DEMO_DIR", str(tmp_path))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(wh, "FLOOR", port)
    key = wh._mint_entry()
    sup = wh._Supervisor()
    import threading
    threading.Thread(target=sup.floor_server, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        with __import__("contextlib").suppress(OSError):
            urllib.request.urlopen(base + "/", timeout=1)
            break
        time.sleep(.05)

    def code(path, data=None):
        try:
            return urllib.request.urlopen(urllib.request.Request(base + path, data=data), timeout=3).status
        except urllib.error.HTTPError as e:
            return e.code
    assert code("/") == 200, "the page itself holds nothing"
    assert code("/state") == 403 and code("/poke", b"{}") == 403
    assert code(f"/state?k={key}") == 200


# ---- a real server, real sockets, real children --------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def real_server(tmp_path_factory):
    """`python -m agentos serve` on a throwaway home. This test process is NOT its parent's child, so it
    plays the person's own terminal only if it starts the server itself: it IS the parent here, and a
    parent is not a descendant."""
    home = tmp_path_factory.mktemp("real")
    port = _free_port()
    (home / "a").mkdir()
    (home / "a" / "config.json").write_text(json.dumps({"port": port}))   # never the machine's real 8321
    env = {**os.environ, "AGENTOS_HOME": str(home / "a"), "HOME": str(home), "AGENTOS_VAULT_KEYRING": "0",
           "AGENTOS_PORT": str(port),
           "AGENTOS_NO_AUTOPICK": "1", "PYTHONUNBUFFERED": "1", "AGENTOS_ALLOWED_HOSTS": ""}
    p = subprocess.Popen([sys.executable, "-m", "agentos", "serve", "--port", str(port), "--no-browser",
                          "--if-running", "fail"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for _ in range(240):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=1)
            break
        except urllib.error.HTTPError:
            break
        except OSError:
            time.sleep(.25)
    yield port, p
    p.terminate()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()


def _get(port, path="/api/config", host=None, method="GET", data=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


@pytest.mark.skipif(not os.path.exists("/proc/net/tcp"), reason="needs Linux /proc")
def test_on_a_real_server_the_person_is_let_in_and_a_rebinding_host_is_not(real_server):
    port, _ = real_server
    assert _get(port) == 200
    assert _get(port, host=f"evil.example:{port}") == 421
    assert _get(port, host=f"localhost:{port}") == 200


def _terminal(port):
    return websockets.connect(f"ws://127.0.0.1:{port}/ws/terminal", open_timeout=15)


async def _run_in_terminal(port, line):
    async with _terminal(port) as ws:
        await ws.send(json.dumps({"type": "input", "data": line + "\n"}))
        got, end = "", time.time() + 25
        # the shell echoes the command with %{http_code} in it, so only a real number ends this
        while not re.search(r"RE\d{3}SULT", got) and time.time() < end:
            try:
                got += await asyncio.wait_for(ws.recv(), 3)
            except asyncio.TimeoutError:
                pass
        return got


@pytest.mark.skipif(not os.path.exists("/proc/net/tcp"), reason="needs Linux /proc")
def test_on_a_real_server_a_shell_it_started_is_refused_and_flagged(real_server):
    """The whole of S-13, end to end: the Terminal's shell is the jail an agent's command runs in, with its
    network. The person's own curl a moment ago got 200 from the same address."""
    port, _ = real_server
    if not shutil.which("curl"):
        pytest.skip("no curl")
    assert _get(port) == 200
    line = (f"curl -s -o /dev/null -w 'RE%{{http_code}}SULT' -X POST -H 'Content-Type: application/json' "
            f"-d '{{}}' http://127.0.0.1:{port}/api/grants")
    out = asyncio.run(_run_in_terminal(port, line))
    assert "RE401SULT" in out, out[-400:]
    # so is one that orphans itself, which used to reparent out of the tree
    line = (f"(curl -s -o /tmp/o -w 'RE%{{http_code}}SULT' http://127.0.0.1:{port}/api/config &) ; sleep 2")
    out = asyncio.run(_run_in_terminal(port, line))
    assert "RE401SULT" in out, out[-400:]
    assert _get(port) == 200, "and the person is not locked out by it"


@pytest.mark.skipif(not os.path.exists("/proc/net/tcp"), reason="needs Linux /proc")
def test_on_a_real_server_a_lock_closes_the_terminal_socket(real_server):
    """Last in this file: it leaves the passphrase set. The socket has no cookie, like a browser on a
    machine with no accounts, and the lock must reach it."""
    port, _ = real_server

    async def walk():
        async with _terminal(port) as ws:
            await ws.recv()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/remote", method="POST",
                                         data=json.dumps({"passphrase": PW}).encode(),
                                         headers={"Content-Type": "application/json"})
            await asyncio.to_thread(urllib.request.urlopen, req, timeout=10)
            lock = urllib.request.Request(f"http://127.0.0.1:{port}/api/session/lock", method="POST", data=b"{}",
                                          headers={"Content-Type": "application/json"})
            await asyncio.to_thread(urllib.request.urlopen, lock, timeout=10)
            for _ in range(40):
                try:
                    await asyncio.wait_for(ws.recv(), 1)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed as e:
                    return e.rcvd.code if e.rcvd else None
            return "still open"
    assert asyncio.run(walk()) == 4401
    assert _get(port) == 401, "and a cookie-less request is held too"
