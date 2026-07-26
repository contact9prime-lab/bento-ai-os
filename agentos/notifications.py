"""The AgentOS notification daemon — org.freedesktop.Notifications.

In DE mode there is no GNOME to receive desktop notifications, so AgentOS must
BE the daemon: Firefox download finished, calendar reminder, battery warning —
they all arrive as D-Bus calls to this name. We claim it, store what arrives,
push it onto the UI WebSocket as a toast, and keep a persistent center with
Do-Not-Disturb.

This service is claimed ONLY when AgentOS owns the session. In hosted mode the
host desktop holds the bus name, and requesting it would either fail or — worse
— steal notifications from the desktop the user is actually using. runmode is
the guard, not a config flag, so it cannot be misconfigured into fighting GNOME.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections import deque

from dbus_fast import BusType, NameFlag, RequestNameReply, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method, signal

BUS_NAME = "org.freedesktop.Notifications"
OBJECT_PATH = "/org/freedesktop/Notifications"

MAX_KEPT = 200        # the notification center's memory


class _Iface(ServiceInterface):
    """The wire protocol (Desktop Notifications Specification 1.2)."""

    def __init__(self, daemon: "NotificationDaemon"):
        super().__init__(BUS_NAME)
        self._d = daemon

    @method()
    def Notify(self, app_name: "s", replaces_id: "u", app_icon: "s",   # noqa: N802,F821
               summary: "s", body: "s", actions: "as",                  # noqa: F821
               hints: "a{sv}", expire_timeout: "i") -> "u":             # noqa: F821
        return self._d.add(app_name, replaces_id, app_icon, summary, body, hints)

    @method()
    def CloseNotification(self, id: "u"):                               # noqa: N802,A002,F821
        self._d.dismiss(id, reason=3)     # 3 = closed by a CloseNotification call

    @method()
    def GetCapabilities(self) -> "as":                                  # noqa: N802,F821
        return ["body", "persistence", "icon-static"]

    @method()
    def GetServerInformation(self) -> "ssss":                           # noqa: N802,F821
        return ["AgentOS", "AgentOS", "1.0", "1.2"]

    @signal()
    def NotificationClosed(self, id: "u", reason: "u") -> "uu":         # noqa: N802,A002,F821
        return [id, reason]

    @signal()
    def ActionInvoked(self, id: "u", action_key: "s") -> "us":          # noqa: N802,A002,F821
        return [id, action_key]


class NotificationDaemon:
    """Owns the bus name; keeps the center's history; feeds the UI."""

    def __init__(self, broadcast):
        self._broadcast = broadcast          # server's WebSocket fan-out
        self._bus: MessageBus | None = None
        self._iface: _Iface | None = None
        self._ids = itertools.count(1)
        self.items: deque[dict] = deque(maxlen=MAX_KEPT)
        self.dnd = False
        self.available = False
        self.reason = "not started"
        # proactivity hook: every arriving notification is offered here (the
        # server wires this to Scheduler.offer_notification). Sync, must not raise.
        self.on_notification = None

    async def start(self) -> bool:
        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
            self._iface = _Iface(self)
            self._bus.export(OBJECT_PATH, self._iface)
            # DO_NOT_QUEUE, and check the reply: the default is to wait in line
            # for the name, which would leave two daemons both believing they
            # own notifications. If anyone (GNOME) holds it, we must not run.
            reply = await self._bus.request_name(BUS_NAME, NameFlag.DO_NOT_QUEUE)
            if reply != RequestNameReply.PRIMARY_OWNER:
                raise RuntimeError("another notification daemon owns the name")
            self.available, self.reason = True, ""
            return True
        except Exception as e:
            self.available = False
            self.reason = f"could not claim {BUS_NAME}: {e}"
            if self._bus:
                self._bus.disconnect()
                self._bus = None
            return False

    def stop(self):
        if self._bus:
            self._bus.disconnect()
            self._bus = None
        self.available = False
        self.reason = "stopped"

    # ---- daemon behaviour ---------------------------------------------------

    def add(self, app_name: str, replaces_id: int, app_icon: str,
            summary: str, body: str, hints: dict) -> int:
        nid = int(replaces_id) or next(self._ids)
        urgency = hints.get("urgency")
        if isinstance(urgency, Variant):
            urgency = urgency.value
        item = {
            "id": nid,
            "app": str(app_name or ""),
            "icon": str(app_icon or ""),
            "summary": str(summary or ""),
            "body": str(body or ""),
            "urgency": int(urgency) if urgency is not None else 1,   # 0 low 1 normal 2 critical
            "time": time.time(),
            "read": False,
        }
        if replaces_id:
            self.items = deque((item if n["id"] == nid else n for n in self.items),
                               maxlen=MAX_KEPT)
            if not any(n["id"] == nid for n in self.items):
                self.items.appendleft(item)
        else:
            self.items.appendleft(item)
        # offer it to the trigger engine — this is how a notification can start
        # an OS-initiated turn (rate-limited by each trigger's cooldown)
        if self.on_notification:
            try:
                self.on_notification(item)
            except Exception:
                pass
        # DND: keep it in the center, don't pop a toast — critical cuts through.
        if not self.dnd or item["urgency"] >= 2:
            self._emit({"type": "notification", **item})
        else:
            self._emit({"type": "notification_center"})   # badge count only
        return nid

    def dismiss(self, nid: int, reason: int = 2):
        self.items = deque((n for n in self.items if n["id"] != int(nid)), maxlen=MAX_KEPT)
        if self._iface:
            try:
                self._iface.NotificationClosed(int(nid), int(reason))
            except Exception:
                pass
        self._emit({"type": "notification_center"})

    def clear(self):
        self.items.clear()
        self._emit({"type": "notification_center"})

    def mark_read(self):
        for n in self.items:
            n["read"] = True

    def recent(self, limit: int = 20, unread_only: bool = False) -> list[dict]:
        """Newest-first slice of the center — the queryable surface behind the
        agent's list_notifications tool (app, summary, body, time, read)."""
        items = [n for n in self.items if not (unread_only and n["read"])]
        return items[:max(1, int(limit))]

    def state(self) -> dict:
        return {"available": self.available, "reason": self.reason, "dnd": self.dnd,
                "unread": sum(1 for n in self.items if not n["read"]),
                "items": list(self.items)}

    def _emit(self, event: dict):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._broadcast(event))
