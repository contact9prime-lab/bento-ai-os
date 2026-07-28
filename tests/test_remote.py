"""Remote access: the gate that decides whether this machine is on the network.

AgentOS hands whoever loads it a real shell, so these tests pin the invariants
rather than the happy path: enabled-without-a-passphrase is not a reachable
state, loopback keeps working untouched, a network client without a session gets
nothing (REST, websocket, or desktop HTML), and the switch itself cannot be
thrown from off-machine.
"""

import contextlib
import os
import tempfile

import pytest

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from fastapi.testclient import TestClient          # noqa: E402

from agentos import config as cfgmod               # noqa: E402
from agentos import remote as remotemod           # noqa: E402
from agentos import server as servermod            # noqa: E402

PASS = "correct horse battery staple"


LAN_ADDR = ("192.168.1.50", 51234)


@pytest.fixture()
def cfg():
    """A locked-down remote block, restored afterwards so tests stay independent.

    Note this is NOT yet the server's live config: the app's startup hook loads
    its own, so anything that goes through TestClient must arm
    ``servermod.state["cfg"]`` from inside the context — which is what
    ``client()`` below does.
    """
    original = servermod.state.get("cfg")
    c = cfgmod.load_config()
    c["remote"] = {"enabled": False, "bind": "0.0.0.0", "pass_hash": "", "pass_salt": "",
                   "session_days": 30, "trust_loopback": True}
    servermod.state["cfg"] = c
    remotemod.reset_failures()
    yield c
    servermod.state["cfg"] = original
    remotemod.reset_failures()


def arm(cfg, passphrase=PASS):
    cfg["remote"]["pass_hash"], cfg["remote"]["pass_salt"] = remotemod.hash_passphrase(passphrase)
    cfg["remote"]["enabled"] = True
    return cfg


@contextlib.contextmanager
def client(addr=None, armed=True):
    """A TestClient whose source address is a LAN one by default, with the LIVE
    config armed after startup has replaced it."""
    with TestClient(servermod.app, client=addr or LAN_ADDR) as c:
        live = servermod.state["cfg"]
        live.setdefault("remote", {}).update(
            {"enabled": False, "bind": "0.0.0.0", "pass_hash": "", "pass_salt": "",
             "session_days": 30, "trust_loopback": True})
        if armed:
            arm(live)
        remotemod.reset_failures()
        yield c


def lan():
    return client()


# ---------------------------------------------------------------------------
# the invariant
# ---------------------------------------------------------------------------

def test_enabled_without_a_passphrase_is_not_a_state(cfg):
    cfg["remote"]["enabled"] = True                      # e.g. hand-edited config.json
    assert remotemod.enabled(cfg) is False
    remotemod.sanitize_remote(cfg)
    assert cfg["remote"]["enabled"] is False


def test_bind_host_stays_loopback_until_properly_armed(cfg):
    assert remotemod.bind_host(cfg) == "127.0.0.1"
    cfg["remote"]["enabled"] = True
    assert remotemod.bind_host(cfg) == "127.0.0.1"       # still no passphrase
    arm(cfg)
    assert remotemod.bind_host(cfg) == "0.0.0.0"


# ---------------------------------------------------------------------------
# passphrase + session
# ---------------------------------------------------------------------------

def test_passphrase_round_trip_and_rejection(cfg):
    arm(cfg)
    assert remotemod.check_passphrase(cfg, PASS)
    assert not remotemod.check_passphrase(cfg, PASS + "!")
    assert not remotemod.check_passphrase(cfg, "")


def test_the_passphrase_itself_is_never_stored(cfg):
    arm(cfg)
    assert PASS not in str(cfg["remote"])


@pytest.mark.parametrize("weak", ["", "short", "password", "12345678"])
def test_weak_passphrases_are_refused(weak):
    assert remotemod.passphrase_problem(weak)


def test_a_session_survives_a_round_trip_but_not_a_new_passphrase(cfg):
    arm(cfg)
    tok = remotemod.issue_session(cfg)
    assert remotemod.valid_session(cfg, tok)
    arm(cfg, "a different long passphrase")
    assert not remotemod.valid_session(cfg, tok)          # every device signs in again


@pytest.mark.parametrize("bad", ["", "junk", "a.b", "eyJhIjoxfQ.deadbeef"])
def test_forged_sessions_are_rejected(cfg, bad):
    arm(cfg)
    assert not remotemod.valid_session(cfg, bad)


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

def test_loopback_is_untouched_when_remote_is_off(cfg):
    with client(addr=("127.0.0.1", 5000), armed=False) as c:
        assert c.get("/api/remote").status_code == 200


def test_loopback_still_walks_straight_in_when_remote_is_on(cfg):
    with client(addr=("127.0.0.1", 5000)) as c:
        assert c.get("/api/remote").status_code == 200


def test_a_network_client_is_stopped_at_the_door(cfg):
    with lan() as c:
        assert c.get("/api/automations").status_code == 401
        assert c.get("/api/themes").status_code == 401
        # a browser asking for the desktop gets the sign-in page, not the desktop
        r = c.get("/")
        assert r.status_code == 200 and "sign in" in r.text.lower()
        assert "id=\"desktop\"" not in r.text


def test_the_sign_in_surface_itself_stays_reachable(cfg):
    with lan() as c:
        assert c.get("/login").status_code == 200
        assert c.get("/manifest.webmanifest").status_code == 200


def test_signing_in_opens_the_door(cfg):
    with lan() as c:
        assert c.post("/api/remote/login", json={"passphrase": "nope"}).status_code == 401
        assert c.post("/api/remote/login", json={"passphrase": PASS}).status_code == 200
        assert c.get("/api/automations").status_code == 200      # cookie now held
        c.post("/api/remote/logout")
        assert c.get("/api/automations").status_code == 401


def test_repeated_failures_back_off(cfg):
    with lan() as c:
        codes = [c.post("/api/remote/login", json={"passphrase": "x"}).status_code
                 for _ in range(7)]
    assert 429 in codes, "a wrong passphrase should stop being answerable at network speed"


def test_the_websocket_is_gated_too(cfg):
    with lan() as c:
        with pytest.raises(Exception):
            with c.websocket_connect("/ws"):
                pass


# ---------------------------------------------------------------------------
# who may throw the switch
# ---------------------------------------------------------------------------

def test_remote_access_cannot_be_widened_from_off_machine(cfg):
    with lan() as c:
        c.post("/api/remote/login", json={"passphrase": PASS})
        r = c.post("/api/remote", json={"enabled": True, "bind": "0.0.0.0"})
    assert r.status_code == 403, "only the machine itself may change its own exposure"


def test_enabling_without_a_passphrase_is_refused_by_the_api(cfg):
    with client(addr=("127.0.0.1", 5000), armed=False) as c:
        r = c.post("/api/remote", json={"enabled": True})
    assert r.status_code == 400


def test_clearing_the_passphrase_disarms_it(cfg):
    with client(addr=("127.0.0.1", 5000)) as c:
        c.post("/api/remote", json={"passphrase": ""})
    assert remotemod.enabled(servermod.state["cfg"]) is False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host,want", [
    ("127.0.0.1", True), ("::1", True), ("localhost", True),
    ("192.168.1.10", False), ("10.0.0.4", False), ("", False), ("not-an-ip", False),
])
def test_loopback_detection(host, want):
    assert remotemod.is_loopback(host) is want
