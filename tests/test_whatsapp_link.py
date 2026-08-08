"""The linked-device transport: the process, the state machine, and the refusals.

WhatsApp's own servers are not reachable from a test, and that is fine — nothing
here is about WhatsApp. What these tests defend is everything between the user and
Baileys: the state machine, the credentials being deleted rather than merely
disconnected, sends waiting for a real ack, a logout not being retried forever, and
the two transports never being confused for one another.

The bridge is replaced with a **fake** that speaks the same newline-delimited JSON
on stdout. That is the actual contract — if the Node script and this fake ever
disagree, the seam is what broke, and it is the seam these tests are for.
"""

import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import channels as ch                                 # noqa: E402
from agentos import whatsapp as wa                                 # noqa: E402
from agentos import whatsapp_link as wl                            # noqa: E402


# ---------------------------------------------------------------------------
# A stand-in for the Node bridge
# ---------------------------------------------------------------------------

FAKE = r'''
import json, os, sys, time
# argv[2] is the auth dir, exactly as the real bridge receives it — so this
# exercises the REAL _run_once rather than a reimplementation of it. The events
# to emit are read from a file beside this script.
here = os.path.dirname(os.path.abspath(__file__))
script = json.load(open(os.path.join(here, "events.json")))
for ev in script:
    if ev.get("_sleep"):
        time.sleep(ev["_sleep"]); continue
    if "_exit" in ev:
        raise SystemExit(ev["_exit"])       # exit having said nothing
    sys.stdout.write(json.dumps(ev) + "\n"); sys.stdout.flush()
# then act as a command echo, so sends get acked
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    c = json.loads(line)
    if c.get("t") == "send":
        sys.stdout.write(json.dumps({"t": "sent", "ref": c.get("ref", "")}) + "\n")
        sys.stdout.flush()
    elif c.get("t") == "logout":
        sys.stdout.write(json.dumps({"t": "closed", "code": 401,
                                     "logged_out": True}) + "\n")
        sys.stdout.flush()
        raise SystemExit(2)
raise SystemExit(0)
'''


class _Store:
    def __init__(self):
        self.logs = []

    def log(self, kind, msg, meta=None):
        self.logs.append((kind, msg))


def make_bridge(tmp_path, script, monkeypatch):
    """A LinkBridge whose 'node' is python running FAKE.

    Only `node_path` and `script_path` are substituted — everything else is the
    real thing, including `_run_once`, the NDJSON reader and the supervisor.
    """
    home = tmp_path / "wb"
    home.mkdir(parents=True, exist_ok=True)
    (home / "fake.py").write_text(FAKE)
    (home / "events.json").write_text(json.dumps(script))
    monkeypatch.setattr(wl, "home", lambda: home)
    monkeypatch.setattr(wl, "auth_dir", lambda: home / "auth")
    monkeypatch.setattr(wl, "node_path", lambda: sys.executable)
    monkeypatch.setattr(wl, "script_path", lambda: home / "fake.py")
    monkeypatch.setattr(wl, "installed", lambda: True)
    events = []

    async def broadcast(ev):
        events.append(ev)

    return wl.LinkBridge({}, _Store(), broadcast), events


async def until(pred, timeout=6.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return False


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

def test_a_qr_arrives_and_is_offered_to_the_card(tmp_path, monkeypatch):
    b, events = make_bridge(tmp_path, [{"t": "qr", "svg": "<svg/>", "payload": "2@abc"},
                                       {"_sleep": 5}], monkeypatch)

    async def go():
        await b.start()
        assert await until(lambda: b.state == "qr")
        st = b.status()
        assert st["qr_svg"] == "<svg/>" and st["qr_payload"] == "2@abc"
        assert not st["linked"]
        await b.stop()
    asyncio.run(go())
    assert any(e["type"] == "whatsapp_link" for e in events), \
        "every QR rotation must be announced, or the card shows a stale code"


def test_a_stale_qr_is_not_handed_back(tmp_path, monkeypatch):
    """A code that still renders after it has expired fails silently in the user's
    hand — an empty box at least says something is wrong."""
    b, _ = make_bridge(tmp_path, [{"t": "qr", "svg": "<svg/>", "payload": "2@abc"},
                                  {"_sleep": 5}], monkeypatch)

    async def go():
        await b.start()
        assert await until(lambda: b.state == "qr")
        b.qr_at -= wl.QR_TTL + 1
        assert b.status()["qr_svg"] == ""
        await b.stop()
    asyncio.run(go())


def test_scanning_moves_it_to_ready(tmp_path, monkeypatch):
    b, _ = make_bridge(tmp_path, [{"t": "qr", "svg": "<svg/>", "payload": "x"},
                                  {"t": "ready", "me": "919812345678:14@s.whatsapp.net"},
                                  {"_sleep": 5}], monkeypatch)

    async def go():
        await b.start()
        assert await until(lambda: b.state == "ready")
        st = b.status()
        assert st["linked"] and st["me"].startswith("919812345678")
        assert st["qr_svg"] == "", "the code must go when it has been used"
        await b.stop()
    asyncio.run(go())


def test_the_phone_revoking_the_device_deletes_the_credentials(tmp_path, monkeypatch):
    """'Unlinked' has to mean the keys are gone. A disconnected bridge whose auth
    is still on disk is still a linked device as far as the phone is concerned —
    and reconnecting with revoked credentials loops forever."""
    b, _ = make_bridge(tmp_path, [{"t": "ready", "me": "1:1@s.whatsapp.net"},
                                  {"_sleep": 1},   # give the test time to see `ready`
                                  {"t": "closed", "code": 401, "logged_out": True}],
                       monkeypatch)

    async def go():
        await b.start()
        assert await until(lambda: b.state == "ready")
        (wl.auth_dir() / "creds.json").write_text("{}")
        assert await until(lambda: b.state == "off", 8)
        assert not (wl.auth_dir() / "creds.json").exists()
        assert "unlinked this device" in b.error
        await b.stop()
    asyncio.run(go())


def test_a_logout_is_not_retried(tmp_path, monkeypatch):
    """Exit code 2 is a permanent state that needs a human with a phone. Retrying
    it reads as 'it keeps failing' rather than 'you need to scan again'."""
    b, _ = make_bridge(tmp_path, [{"t": "closed", "code": 401, "logged_out": True}],
                       monkeypatch)

    async def go():
        await b.start()
        await asyncio.sleep(1.2)
        assert b._task.done() or b.state == "off"
        assert b._tries == 0, "a logout must not enter the backoff loop"
        await b.stop()
    asyncio.run(go())


def test_the_credentials_directory_is_not_world_readable(tmp_path, monkeypatch):
    """It is a complete WhatsApp session — equivalent to the phone."""
    b, _ = make_bridge(tmp_path, [{"_sleep": 3}], monkeypatch)

    async def go():
        await b.start()
        assert await until(lambda: wl.auth_dir().is_dir())
        mode = stat.S_IMODE(os.stat(wl.auth_dir()).st_mode)
        assert mode == 0o700, oct(mode)
        await b.stop()
    asyncio.run(go())


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def test_a_send_waits_for_the_bridge_to_confirm(tmp_path, monkeypatch):
    """A write to a pipe succeeds long before WhatsApp accepts anything. 'Sent'
    that only means 'handed to a subprocess' makes a delivery bug unfindable."""
    b, _ = make_bridge(tmp_path, [{"t": "ready", "me": "1:1@s.whatsapp.net"}], monkeypatch)

    async def go():
        await b.start()
        assert await until(lambda: b.state == "ready")
        assert await b.send("919812345678", "hello") == ""
        await b.stop()
    asyncio.run(go())


def test_sending_before_it_is_linked_says_what_to_do(tmp_path, monkeypatch):
    b, _ = make_bridge(tmp_path, [{"_sleep": 3}], monkeypatch)

    async def go():
        out = await b.send("911", "hi")
        assert "not linked" in out and "QR" in out
    asyncio.run(go())


def test_a_bridge_that_never_acks_times_out_rather_than_hanging(tmp_path, monkeypatch):
    """A wedged bridge must not hold a turn open forever — a scheduled job that
    never returns holds knowledge.turn_started() and degrades the whole OS."""
    b, _ = make_bridge(tmp_path, [{"t": "ready", "me": "1:1@s.whatsapp.net"},
                                  {"_sleep": 10}], monkeypatch)

    async def go():
        await b.start()
        assert await until(lambda: b.state == "ready")
        # a send that the fake will never see: it is still sleeping through its
        # event script and has not reached its stdin loop
        out = await b.send("911", "x", timeout=0.4)
        assert "did not confirm" in out
        await b.stop()
    asyncio.run(go())


# ---------------------------------------------------------------------------
# Install and consent
# ---------------------------------------------------------------------------

def test_without_node_it_says_so_rather_than_offering_a_dead_button(monkeypatch):
    monkeypatch.setattr(wl, "node_path", lambda: "")
    assert "Node.js" in wl.why_not()


def test_the_component_entry_states_the_licence_and_the_warning():
    """Nothing installs without this screen. It has to carry the licence and the
    fact that WhatsApp bans accounts for it — buried, that is a trap."""
    from agentos import components
    c = components.CATALOG["whatsapp-bridge"]
    assert "MIT" in c["licence"] and "Baileys" in c["licence"]
    assert "UNOFFICIAL" in c["unlocks"] and "banned" in c["unlocks"]


def test_installing_the_bridge_needs_no_root():
    """Everything lands under the user's own AgentOS home, so it must not be
    routed through the sudo/pkexec ladder the system packages use."""
    import inspect

    from agentos import components
    src = inspect.getsource(components.install)
    i = src.index('if component_id == "whatsapp-bridge"')
    j = src.index('_run(["sudo", "-n", "true"]')      # the first rung of the ladder
    assert i < j, "the bridge must return before the privilege ladder"


# ---------------------------------------------------------------------------
# The two transports stay distinct
# ---------------------------------------------------------------------------

def test_link_is_the_default_because_it_is_the_one_you_can_finish():
    assert wa.conf({})["mode"] == "link"
    assert wa.conf({"channels": {"whatsapp": {"mode": "cloud"}}})["mode"] == "cloud"
    assert wa.conf({"channels": {"whatsapp": {"mode": "sideways"}}})["mode"] == "link"


def test_link_mode_does_not_demand_the_cloud_api_fields():
    """Holding the channel off for four boxes it will never read would be refusing
    to switch on for a reason that does not apply."""
    st = {c["id"]: c for c in ch.state({})}["whatsapp"]
    assert st["status"] != "needs", st["detail"]
    cloud = {"channels": {"whatsapp": {"mode": "cloud"}}}
    st2 = {c["id"]: c for c in ch.state(cloud)}["whatsapp"]
    assert st2["status"] == "needs" and "Phone number ID" in st2["detail"]


def test_a_linked_device_has_no_24_hour_window(tmp_path):
    """That restriction is a Cloud API rule about business-initiated messages, and
    it is the entire reason this transport is worth its unofficial status."""
    from agentos.memory import Store

    class _TB:
        fabric = None
    cfg = {"channels": {"whatsapp": {"mode": "link"}}}
    b = wa.WhatsAppBridge(cfg, Store(tmp_path / "w.db"), _TB(), lambda ev: asyncio.sleep(0))
    b.link.state = "ready"
    assert b.window_open("911") is True
    b.link.state = "off"
    assert b.window_open("911") is False


def test_an_unknown_mode_is_refused_by_name():
    cfg: dict = {}
    ok, msg = ch.save(cfg, "whatsapp", {"mode": "carrier-pigeon"})
    assert not ok and "link, cloud" in msg


def test_the_mode_reaches_the_block_the_bridge_reads():
    cfg: dict = {}
    assert ch.save(cfg, "whatsapp", {"mode": "cloud"})[0]
    assert cfg["whatsapp"]["mode"] == "cloud"
    assert wa.conf(cfg)["mode"] == "cloud"


def test_both_transports_reach_the_same_message_handler():
    """Pairing, the allow-list, the commands and the turn are properties of the
    channel, not of how the bytes arrived. Two copies would drift, and the half
    that drifted would be whichever one was not being demoed."""
    import inspect
    src = inspect.getsource(wa.WhatsAppBridge)
    assert "async def incoming" in src
    assert "await self.incoming(" in src.split("async def _one")[1][:900]
    assert "await self.incoming(" in src.split("async def on_link_message")[1][:700]


def test_the_generated_bridge_is_valid_javascript():
    """It is written from a string constant, so a typo in it is a runtime failure
    on somebody else's machine at scan time. `node --check` catches that here."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed on this machine")
    d = Path(tempfile.mkdtemp())
    f = d / "bridge.mjs"
    f.write_text(wl.BRIDGE_JS)
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_bridge_script_is_rewritten_on_every_install():
    """An upgraded AgentOS running last version's bridge is the stale-generated-
    file bug that CLAUDE.md is mostly about."""
    import inspect
    src = inspect.getsource(wl.install)
    assert "script_path().write_text(BRIDGE_JS)" in src


def test_group_messages_are_not_treated_as_a_paired_chat():
    """A group is not a person, and pairing the first one to speak would hand the
    machine to whoever added the number to a group."""
    assert "@g.us" in wl.BRIDGE_JS and "continue" in wl.BRIDGE_JS


def test_the_bridge_never_speaks_over_a_port():
    """stdio, not a socket: WhatsApp credentials behind an unauthenticated
    loopback port would be a full account takeover for anything on the machine."""
    for bad in ("listen(", "createServer", "express", "http.Server"):
        assert bad not in wl.BRIDGE_JS


def test_a_bridge_that_reaches_nothing_says_so_rather_than_reading_as_off(
        tmp_path, monkeypatch):
    """Found by running it: on a machine whose egress to web.whatsapp.com was
    blocked, the bridge sat silent for 25s and then exited 0. The card read that
    as "off" — the exact silent-failure mode this module is written against."""
    b, _ = make_bridge(tmp_path, [{"_exit": 0}], monkeypatch)   # says nothing, exits 0

    async def go():
        await b.start()
        assert await until(lambda: b.state == "error" and b.error, 8)
        assert "without reaching" in b.error or "could not reach" in b.error
        await b.stop()
    asyncio.run(go())


def test_the_bridge_has_a_connect_deadline():
    """The Node side needs its own, because a socket that never opens produces no
    event at all — there is nothing for Python to time out on."""
    assert "CONNECT_DEADLINE" in wl.BRIDGE_JS
    assert "fatal: true" in wl.BRIDGE_JS
