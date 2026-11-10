"""The machine's routes refuse an account that is not an admin, from one table.

The audit's commonest finding was a route missing the check its neighbour had. These tests hold
the table against the real routing table, so a new route can't quietly be nobody's decision.
"""
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient                           # noqa: E402

from agentos import config as cfgmod                                # noqa: E402
from agentos import machineroutes as mr                             # noqa: E402
from agentos import server as servermod                             # noqa: E402
from agentos import users as usersmod                               # noqa: E402

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# The families where every route acts only on the signed-in account's own directory (usersmod.Scoped
# reads their store and config), so an account may use them. A new family has to be added here on
# purpose, or to machineroutes.MACHINE_ONLY: that decision is what this test exists to force.
ACCOUNT_ROUTES = (
    "/api/agent", "/api/agents", "/api/apps", "/api/arena", "/api/accounts", "/api/assets",
    "/api/automations", "/api/avatars", "/api/brain", "/api/brief", "/api/chat", "/api/channels",
    "/api/companies", "/api/company", "/api/conversations", "/api/devices/alarms",
    "/api/drama", "/api/evals", "/api/fabric", "/api/files/which", "/api/flows", "/api/freetalk",
    "/api/grants", "/api/hands", "/api/hooks", "/api/intent", "/api/jobs", "/api/kg", "/api/knowledge",
    "/api/logs", "/api/mcp", "/api/memories", "/api/office", "/api/onboarding", "/api/plane/llm",
    "/api/policy/trace", "/api/provision/zero", "/api/quarantine", "/api/remote/login",
    "/api/remote/logout", "/api/session", "/api/setup/say", "/api/shared", "/api/shell/result",
    "/api/shell/sui", "/api/skills", "/api/spaces", "/api/speech", "/api/stage", "/api/standby/peer",
    "/api/store", "/api/subagents", "/api/suggestions", "/api/tasks", "/api/team", "/api/telegram",
    "/api/terminal", "/api/themes", "/api/timetravel", "/api/tool", "/api/users/login",
    "/api/users/logout", "/api/wallpaper", "/api/wallpapers", "/api/whatsapp", "/api/widgets",
    "/api/world",
    # read and written per person after cfg_for's deep copy: a price set here goes nowhere else,
    # and the price card on an unpriced model must stay answerable by whoever is using it
    "/api/pricing",
)
# A handler that checks for itself. Named checks only, so a comment can't count.
SELF_CHECK = re.compile(r"_require_admin\(\)|usersmod\.is_admin\(|_backup_admin\(\)|_ocp_gate\(|_standby_do\(|"
                        r"_restore_refusal\(|_tie_mine\(")


def _routes():
    for r in servermod.app.routes:
        for m in sorted((getattr(r, "methods", None) or set()) & (MUTATING | {"GET"})):
            yield m, r.path, r.endpoint


@pytest.fixture()
def running():
    usersmod.reset_caches()
    with TestClient(servermod.app) as cl:
        yield cl
    usersmod.reset_caches()


@pytest.fixture()
def bob(running):
    usersmod.create("ada", "ada-password-1", role="admin")
    usersmod.create("bob", "bob-password-1")
    c = TestClient(servermod.app)
    assert c.post("/api/users/login", json={"name": "bob", "password": "bob-password-1"}).status_code == 200
    return c


@pytest.fixture()
def ada():
    c = TestClient(servermod.app)
    assert c.post("/api/users/login", json={"name": "ada", "password": "ada-password-1"}).status_code == 200
    return c


def test_every_mutating_route_is_somebodys_decision():
    """A new route that changes something has to be in the machine's table, check for itself, or
    be named as an account's own. Silence fails here, which is how the old gaps came about."""
    loose = []
    for method, path, fn in _routes():
        if method == "GET" or not path.startswith("/api/") and path != "/remote-desktop":
            continue
        if mr.machine_only(method, path) or SELF_CHECK.search(inspect.getsource(fn)):
            continue
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in ACCOUNT_ROUTES):
            continue
        loose.append(f"{method} {path}")
    assert not loose, "decide these in agentos/machineroutes.py or ACCOUNT_ROUTES: " + ", ".join(loose)


def test_every_route_the_table_names_exists():
    """A typo in the table would be a route everybody believes is guarded."""
    paths = [(m, p) for m, p, _ in _routes()]
    for methods, pat in mr.MACHINE_ONLY:
        base = pat[:-2] if pat.endswith("/*") else pat
        assert any(p == base or p.startswith(base + "/") for _, p in paths), pat


def test_a_non_admin_is_refused_on_every_machine_route(bob):
    """Against the real router: each route the table covers answers 403 before it runs."""
    hit = 0
    for method, path, _ in _routes():
        if not mr.machine_only(method, path):
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = bob.request(method, url, json={} if method != "GET" else None)
        assert r.status_code == 403 and r.headers.get("X-Bento-Admin-Only") == "1", (method, url, r.status_code)
        hit += 1
    assert hit > 40


@pytest.mark.parametrize("sid", ["..", "%2e%2e", "1", "..%2f.."])
def test_a_non_admin_cannot_wipe_the_machine_through_a_snapshot(bob, sid):
    """`snapshots/..` is AGENTOS_HOME, and DELETE emptied every account (S-29)."""
    canary = Path(cfgmod.AGENTOS_HOME) / "canary"
    canary.write_text("still here")
    bob.delete(f"/api/snapshots/{sid}")
    assert canary.read_text() == "still here"
    assert usersmod.registry_path().exists()


def test_a_snapshot_id_is_digits_even_for_an_admin(bob, ada):
    canary = Path(cfgmod.AGENTOS_HOME) / "canary"
    canary.write_text("still here")
    for sid in ("..", "%2e%2e", "a"):
        assert ada.delete(f"/api/snapshots/{sid}").status_code in (404, 405)
    # a client library tidies `..` out of a URL before sending it; a raw request does not
    for sid in ("..", "../..", "a", "", "1/.."):
        assert servermod._snap_of(sid) is None, sid
    assert canary.exists()


def test_a_non_admin_cannot_watch_or_type_on_the_host_over_a_socket(bob):
    """Middleware never sees a socket, so the two that reach the host check by hand (S-30)."""
    from starlette.websockets import WebSocketDisconnect
    cookie = "; ".join(f"{k}={v}" for k, v in bob.cookies.items())
    for path in ("/ws/vnc", "/ws/appstream?id=x"):
        with pytest.raises(WebSocketDisconnect) as e:
            with TestClient(servermod.app).websocket_connect(path, headers={"cookie": cookie}):
                pass
        assert e.value.code == 4403


def test_a_non_admin_reads_as_a_remote_client_so_files_open_in_the_browser(bob):
    """The page's own rule for "the host's screen is not where you are": the chip downloads
    rather than calling /api/open, and native apps say why they can't open (S-89)."""
    assert bob.get("/api/platform").json()["remote_client"] is True


def test_a_machine_with_no_accounts_refuses_nobody(running):
    """is_admin('') is True: nothing changes on a single-person install."""
    assert not usersmod.enabled()
    c = running
    assert c.get("/api/snapshots").status_code == 200
    assert "X-Bento-Admin-Only" not in c.post("/api/open", json={}).headers
    assert "X-Bento-Admin-Only" not in c.post("/api/notifications", json={"action": "x"}).headers


def test_an_admin_passes_the_table(bob, ada):
    assert ada.get("/api/snapshots").status_code == 200
    assert "X-Bento-Admin-Only" not in ada.post("/api/open", json={}).headers


def test_the_wifi_and_bluetooth_tools_ask_and_are_an_admins(bob):
    """The route's twins: `risk_of` says a change is risky, the loop asks at every autonomy
    level (RADIO_TOOLS), and a non-admin's turn is refused in the tool (S-31)."""
    import asyncio

    from agentos import tools as toolsmod
    from agentos import policy as policymod
    assert "name in RADIO_TOOLS and level == \"risky\"" in inspect.getsource(policymod.person_rule)
    box = toolsmod.Toolbox.__new__(toolsmod.Toolbox)
    u = usersmod.by_name("bob")
    with usersmod.as_user(u["id"]):
        assert "only an admin" in asyncio.run(box.wifi("connect", ssid="evil"))
        assert "only an admin" in asyncio.run(box.bluetooth("pair", device="kbd"))


@pytest.fixture()
def bob_first_zero(bob, monkeypatch):
    dict.__setitem__(servermod.state, "team_listener", None)
    return bob


def test_a_non_admins_zero_waits_for_an_admin_to_open_the_port(bob_first_zero, monkeypatch):
    """Anyone may make their own Zero. Being the first thing to open this machine's link port
    and start a community is the machine's, so it is held (S-76)."""
    import asyncio

    from agentos import provision as provmod
    r = bob_first_zero.post("/api/provision/zero", json={})
    assert r.status_code == 200, r.text
    assert "admin" in r.json()["held"]
    key = next(k for k in provmod.load()["keys"] if k.get("zero"))
    assert key["owner"] == usersmod.by_name("bob")["id"]

    started = []

    async def enable(*a, **k):
        started.append(a)
        return {"results": [{"ok": True}]}

    async def told(ev):
        told.ev = ev
    monkeypatch.setattr(servermod, "_provision_enable", enable)
    monkeypatch.setattr(servermod, "_provision_admins", told)
    b = {"fp": "ab" * 16, "name": "pi", "key_id": key["id"], "hw": {}, "addr": "10.0.0.9"}
    asyncio.run(servermod._provision_new(b))
    assert not started, "a non-admin's line opened the link port"
    assert told.ev["kind"] == "new"           # the admin is asked instead

    # once the door is open, an account's Zero is set up on its own, as before
    dict.__setitem__(servermod.state, "team_listener", object())
    try:
        asyncio.run(servermod._provision_new(b))
    finally:
        dict.__setitem__(servermod.state, "team_listener", None)
    assert started


def test_an_admins_zero_is_not_held(bob, ada):
    from agentos import provision as provmod
    dict.__setitem__(servermod.state, "team_listener", None)
    assert ada.post("/api/provision/zero", json={}).json()["held"] == ""
    k = next(k for k in provmod.load()["keys"] if k.get("zero"))
    assert not servermod._zero_waits_for_admin(k)
