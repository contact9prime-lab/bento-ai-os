"""The notification daemon.

Two layers: the daemon's behaviour (ids, replacement, DND, the center's
memory) tested directly, and the D-Bus surface tested over a real private bus
via dbus-daemon — the same wire path notify-send and Firefox use — so the
signature strings in the ServiceInterface are actually exercised, not assumed.
"""

import asyncio
import os
import shutil
import subprocess

import pytest

from agentos.notifications import MAX_KEPT, NotificationDaemon


class Collect:
    def __init__(self):
        self.events = []

    async def __call__(self, ev):
        self.events.append(ev)


@pytest.fixture
def daemon():
    return NotificationDaemon(Collect())


def test_ids_are_assigned_and_replacement_replaces(daemon):
    a = daemon.add("firefox", 0, "", "Download finished", "cat.png", {})
    b = daemon.add("firefox", 0, "", "Another", "", {})
    assert a != b
    assert daemon.add("firefox", a, "", "Download 99%", "", {}) == a
    items = {n["id"]: n for n in daemon.items}
    assert items[a]["summary"] == "Download 99%"
    assert len(daemon.items) == 2


def test_dnd_suppresses_toasts_but_critical_cuts_through():
    async def run():
        sink = Collect()
        d = NotificationDaemon(sink)
        d.dnd = True
        d.add("app", 0, "", "quiet", "", {})
        d.add("app", 0, "", "URGENT", "", {"urgency": 2})
        await asyncio.sleep(0)     # let the emit tasks run
        kinds = [(e["type"], e.get("summary")) for e in sink.events]
        assert ("notification_center", None) in kinds        # badge only
        assert ("notification", "URGENT") in kinds           # critical toast
        assert not any(e.get("summary") == "quiet" and e["type"] == "notification"
                       for e in sink.events)
    asyncio.run(run())


def test_center_memory_is_bounded(daemon):
    for i in range(MAX_KEPT + 50):
        daemon.add("spam", 0, "", f"n{i}", "", {})
    assert len(daemon.items) == MAX_KEPT
    assert daemon.items[0]["summary"] == f"n{MAX_KEPT + 49}"   # newest kept


def test_dismiss_and_clear_and_unread(daemon):
    a = daemon.add("app", 0, "", "one", "", {})
    daemon.add("app", 0, "", "two", "", {})
    assert daemon.state()["unread"] == 2
    daemon.dismiss(a)
    assert [n["summary"] for n in daemon.items] == ["two"]
    daemon.mark_read()
    assert daemon.state()["unread"] == 0
    daemon.clear()
    assert daemon.state()["items"] == []


def test_state_reports_claim_failure_reason(daemon):
    assert daemon.available is False
    assert daemon.state()["reason"]


@pytest.mark.skipif(not shutil.which("dbus-daemon"), reason="dbus-daemon not installed")
def test_over_a_real_bus_with_notify_send(tmp_path):
    """Full wire test: private session bus, claim the name, receive a real
    org.freedesktop.Notifications call, answer GetServerInformation."""
    # A private bus whose address we control.
    p = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1",
         f"--address=unix:path={tmp_path}/bus"],
        stdout=subprocess.PIPE, text=True)
    try:
        addr = p.stdout.readline().strip()
        assert addr
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = addr

        async def run():
            sink = Collect()
            d = NotificationDaemon(sink)
            assert await d.start() is True, d.reason
            # a second daemon must NOT be able to steal the name silently
            d2 = NotificationDaemon(Collect())
            # (dbus-fast raises on RequestName conflict → start() returns False)
            second = await d2.start()
            assert second is False or d2.available is False

            # Send through the standard client path.
            from dbus_fast.aio import MessageBus
            bus = await MessageBus(bus_address=addr).connect()
            intro = await bus.introspect("org.freedesktop.Notifications",
                                         "/org/freedesktop/Notifications")
            obj = bus.get_proxy_object("org.freedesktop.Notifications",
                                       "/org/freedesktop/Notifications", intro)
            iface = obj.get_interface("org.freedesktop.Notifications")
            nid = await iface.call_notify("pytest", 0, "", "Hello from D-Bus",
                                          "body text", [], {}, -1)
            assert nid >= 1
            info = await iface.call_get_server_information()
            assert info[0] == "AgentOS"
            await asyncio.sleep(0.1)
            assert any(e.get("summary") == "Hello from D-Bus" for e in sink.events)
            assert d.state()["items"][0]["app"] == "pytest"
            bus.disconnect()
            d.stop()

        asyncio.run(asyncio.wait_for(run(), timeout=15))
    finally:
        os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
        p.terminate()
        p.wait(timeout=5)
