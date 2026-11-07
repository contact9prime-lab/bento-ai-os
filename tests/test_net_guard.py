"""S-26: a fetch cannot reach this machine, its network or a cloud's metadata address.

A stranger's app could ask `fetch_url` for http://127.0.0.1:8321/api/... and read the answer,
because this server's own request passes loopback trust. These run a real listener: a test that
only reads the code would prove nothing about a redirect or a name that lies.
"""
import asyncio
import http.server
import json
import threading

import httpx
import pytest

from agentos import calendars, netguard
from agentos import config as cfgmod
from agentos.memory import Store
from agentos.tools import APP_BOUND_TOOLS, Toolbox


class _H(http.server.BaseHTTPRequestHandler):
    seen: list = []
    location = ""

    def do_GET(self):
        _H.seen.append((self.path, self.headers.get("Host")))
        if self.path.startswith("/go") and _H.location:
            self.send_response(302)
            self.send_header("Location", _H.location)
            self.end_headers()
            return
        body = b"the secret body"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def listener():
    _H.seen, _H.location = [], ""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture()
def box(tmp_path):
    cfg = cfgmod.load_config()
    cfg["workspace"] = str(tmp_path)
    cfg["sandbox"] = {"enabled": False, "root": ""}
    return Toolbox(cfg, Store(tmp_path / "db.sqlite"))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _allow(*entries):
    cfgmod.CONFIG_PATH.write_text(json.dumps({"security": {netguard.CONFIG_KEY: list(entries)}}))


@pytest.mark.parametrize("address,kind", [
    ("127.0.0.1", "loopback"), ("127.8.8.8", "loopback"), ("::1", "loopback"), ("0.0.0.0", "loopback"), ("::", "loopback"),
    ("::ffff:127.0.0.1", "loopback"), ("2002:7f00:1::", "loopback"), ("64:ff9b::7f00:1", "loopback"),
    ("169.254.169.254", "metadata"), ("::ffff:169.254.169.254", "metadata"), ("fd00:ec2::254", "metadata"),
    ("168.63.129.16", "metadata"), ("100.100.100.200", "metadata"),
    ("10.0.0.1", "private"), ("172.16.0.1", "private"), ("192.168.1.1", "private"), ("::ffff:10.0.0.1", "private"),
    ("100.64.0.1", "private"), ("169.254.1.1", "private"), ("fe80::1", "private"), ("fc00::1", "private"),
    ("fec0::1", "private"), ("224.0.0.1", "private"), ("ff02::1", "private"), ("240.0.0.1", "private"),
    ("8.8.8.8", ""), ("2606:4700:4700::1111", ""),
])
def test_every_spelling_of_a_local_address_is_seen(address, kind):
    assert netguard.kind_of(address) == kind


def test_a_fetch_to_this_machine_is_refused_and_never_connects(box, listener):
    out = run(box.fetch_url(f"http://127.0.0.1:{listener}/api/config"))
    assert out.startswith("[denied]") and "fetched" in out
    assert _H.seen == [], "the request reached the listener"


def test_a_name_that_points_at_loopback_is_refused(box, listener, monkeypatch):
    monkeypatch.setattr(netguard, "_resolve", lambda h, p: ["127.0.0.1"])
    out = run(box.fetch_url(f"http://rebind.example:{listener}/x"))
    assert out.startswith("[denied]")
    assert _H.seen == []


def test_a_name_with_one_public_and_one_private_answer_is_refused(monkeypatch):
    with pytest.raises(netguard.Refused):
        netguard.judge("mixed.example", 80, ["8.8.8.8", "10.0.0.1"])


def test_a_redirect_to_metadata_is_refused_on_that_hop(box, listener):
    """Allowed first hop, and the redirect still dies: the check is per hop, in the transport."""
    _allow(f"127.0.0.1:{listener}")
    _H.location = "http://169.254.169.254/latest/meta-data/"
    out = run(box.fetch_url(f"http://127.0.0.1:{listener}/go"))
    assert out.startswith("[denied]") and "metadata" in out
    assert [p for p, _ in _H.seen] == ["/go"]


def test_the_connection_goes_to_the_address_that_was_checked(listener, monkeypatch):
    """DNS rebinding: the name answers once, and the Host header still names the name."""
    _allow(f"named.example:{listener}")
    answers = []

    def stub(host, port):
        answers.append(host)
        return ["127.0.0.1"]
    monkeypatch.setattr(netguard, "_resolve", stub)

    async def go():
        async with netguard.client(timeout=5) as c:
            return await c.get(f"http://named.example:{listener}/x")
    r = run(go())
    assert r.status_code == 200 and r.text == "the secret body"
    assert answers == ["named.example"], "resolved twice, so a second answer could be used"
    assert _H.seen[-1][1] == f"named.example:{listener}"
    assert str(r.url) == f"http://named.example:{listener}/x"


def test_tls_is_still_checked_against_the_name(monkeypatch):
    captured = {}

    class Inner:
        async def handle_async_request(self, request):
            captured["host"] = request.url.host
            captured["sni"] = request.extensions.get("sni_hostname")
            captured["header"] = request.headers.get("host")
            return httpx.Response(200, content=b"ok")

        async def aclose(self):
            pass
    monkeypatch.setattr(netguard, "_resolve", lambda h, p: ["93.184.216.34"])

    async def go():
        t = netguard.GuardTransport()
        t._inner = Inner()
        async with httpx.AsyncClient(transport=t) as c:
            return await c.get("https://example.com/x")
    assert run(go()).status_code == 200
    assert captured == {"host": "93.184.216.34", "sni": "example.com", "header": "example.com"}


def test_a_person_can_allow_a_local_host_and_only_that_host(box, listener):
    _allow(f"127.0.0.1:{listener}")
    out = run(box.fetch_url(f"http://127.0.0.1:{listener}/ok"))
    assert "the secret body" in out
    assert run(box.fetch_url(f"http://127.0.0.1:{listener + 1 if listener < 65000 else listener - 1}/ok")).startswith("[denied]")


@pytest.mark.parametrize("entry", ["169.254.169.254", "metadata.google.internal", "127.0.0.1", "localhost",
                                   "0.0.0.0/0", "*", "::1"])
def test_no_list_opens_metadata_or_a_portless_loopback(entry):
    assert netguard.clean_entry(entry)[1], f"{entry} was accepted"


def test_this_servers_own_port_cannot_be_allowed(box):
    cfgmod.CONFIG_PATH.write_text(json.dumps({"port": 8123, "security": {netguard.CONFIG_KEY: ["127.0.0.1:8123"]}}))
    assert run(box.fetch_url("http://127.0.0.1:8123/api/config")).startswith("[denied]")


def test_metadata_is_refused_even_if_someone_wrote_it_into_the_file(box):
    _allow("169.254.169.254")
    assert run(box.fetch_url("http://169.254.169.254/")).startswith("[denied]")


def test_an_app_never_gets_the_allow_list(box, listener):
    """An app's fetch is free, so what a person opened for their agents is not for a stranger's app."""
    assert "fetch_url" in APP_BOUND_TOOLS
    _allow(f"127.0.0.1:{listener}")
    out = run(box.execute("fetch_url", {"url": f"http://127.0.0.1:{listener}/ok", "_app": "someapp"}))
    assert out.startswith("[denied]") and "An app" in out
    assert _H.seen == []


def test_an_apps_fetch_reaches_the_guard_through_the_real_route(listener):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    from agentos.policy import Principal
    _allow(f"127.0.0.1:{listener}")
    orig = servermod._principal_of
    servermod._principal_of = lambda r: Principal("app", "strangers-app")
    try:
        with TestClient(servermod.app, base_url="http://127.0.0.1") as c:
            r = c.post("/api/tool", json={"name": "fetch_url", "args": {"url": f"http://127.0.0.1:{listener}/ok", "_app": ""}})
    finally:
        servermod._principal_of = orig
    assert r.status_code == 200 and r.json()["output"].startswith("[denied]"), r.text
    assert _H.seen == []


def test_a_model_cannot_write_the_allow_list(box):
    out = run(box.configure_agentos(json.dumps({"security": {netguard.CONFIG_KEY: ["10.0.0.1"]}})))
    assert out.startswith("[denied]")
    assert netguard.CONFIG_KEY not in (box.cfg.get("security") or {})


def test_the_settings_route_keeps_a_good_list_and_refuses_a_bad_one():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app, base_url="http://127.0.0.1") as c:
        ok = c.put("/api/config", json={"security": {netguard.CONFIG_KEY: ["nas.local", "192.168.1.20:8080"]}})
        assert ok.status_code == 200, ok.text
        assert servermod.state["cfg"]["security"][netguard.CONFIG_KEY] == ["nas.local", "192.168.1.20:8080"]
        bad = c.put("/api/config", json={"security": {netguard.CONFIG_KEY: ["169.254.169.254"]}})
        assert bad.status_code == 400 and "metadata" in bad.json()["error"]
        c.put("/api/config", json={"security": {netguard.CONFIG_KEY: []}})


def test_a_calendar_address_is_guarded(listener):
    c = {"url": f"http://127.0.0.1:{listener}/cal.ics", "user": "", "password": ""}
    with pytest.raises(netguard.Refused):
        run(calendars._get_ics(c))
    assert _H.seen == []


def test_the_routes_that_import_a_package_are_guarded():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app, base_url="http://127.0.0.1") as c:
        for path, body in (("/api/apps/import", {"source": "http://169.254.169.254/x.json"}),
                           ("/api/agent/fork/preview", {"source": "http://169.254.169.254/x.json"})):
            r = c.post(path, json=body)
            assert r.status_code == 400 and "metadata" in r.json()["error"], (path, r.text)


def test_the_agents_browser_cannot_be_sent_to_this_machine(box):
    for url in ("http://127.0.0.1:8321/", "http://localhost/", "http://169.254.169.254/"):
        assert run(box.browser_open(url)).startswith("[denied]"), url


def test_a_model_supplied_dataset_address_is_guarded(box):
    class TF:
        async def api(self, *a, **k):
            raise AssertionError("the address reached the training service")
    box.trainforge = TF()
    assert run(box.train_datasets(action="import_url", url="http://127.0.0.1:5000/x.csv")).startswith("[denied]")


def test_a_big_image_is_refused_while_it_downloads(listener, monkeypatch):
    _allow(f"127.0.0.1:{listener}")
    with pytest.raises(netguard.Refused):
        run(netguard.read_capped(f"http://127.0.0.1:{listener}/x", 4))


def test_an_account_that_is_not_an_admin_gets_the_guard_on_an_mcp_address(tmp_path, monkeypatch):
    from agentos import mcp_client
    from agentos import users as usersmod
    usersmod.reset_caches()
    usersmod.set_current("")
    usersmod.create("ada", "hunter2hunter")
    bob = usersmod.create("bob", "hunter2hunter", role="executor")["id"]
    try:
        with usersmod.as_user(bob):
            c = mcp_client._guarded_for_account()["httpx_client_factory"]()
        assert isinstance(c._transport, netguard.GuardTransport) and not c._transport.local_ok
    finally:
        usersmod.reset_caches()
        usersmod.set_current("")
