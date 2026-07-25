"""Compositor IPC — how AgentOS manages real windows in the DE session.

Wayland deliberately has no wmctrl: one client cannot see or control another's
windows. The compositor is the only party that can — so in the AgentOS session,
window management IS a conversation with the compositor. This module speaks the
sway/i3 IPC protocol over $SWAYSOCK and gives the rest of AgentOS a small,
compositor-agnostic surface: windows, workspaces, outputs, and a live event
stream.

sway is the engine today, but nothing above this module knows that. A future
in-house wlroots compositor only has to answer these calls.

Requests are synchronous — the platform contract is sync, and a round-trip on a
local unix socket is microseconds, so blocking the caller is cheaper than
threading an event loop through every layer. Only `subscribe()` is async: it
holds a connection open for the life of the session and feeds the WebSocket
pump that replaced the taskbar's polling.

Wire protocol (i3-ipc, unchanged since i3): every message is
    "i3-ipc" + u32 payload_length + u32 message_type + payload(JSON)
little-endian, both directions. Events arrive with the high bit of the type set.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct

MAGIC = b"i3-ipc"
_HEADER = struct.Struct("<6sII")

# message types (requests)
RUN_COMMAND = 0
GET_WORKSPACES = 1
SUBSCRIBE = 2
GET_OUTPUTS = 3
GET_TREE = 4
GET_VERSION = 7

_EVENT_BIT = 0x80000000
# event types (replies with the high bit set)
EVENT_NAMES = {0: "workspace", 3: "window", 4: "binding", 5: "shutdown", 21: "output"}


class CompositorError(Exception):
    pass


def socket_path() -> str:
    return os.environ.get("SWAYSOCK", "") or os.environ.get("I3SOCK", "")


def available() -> bool:
    p = socket_path()
    return bool(p) and os.path.exists(p)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise CompositorError("compositor closed the connection")
        buf += chunk
    return buf


class Compositor:
    """One request/response connection per call — the protocol is cheap and this
    dodges reply-interleaving bugs. `subscribe()` holds its own connection."""

    def __init__(self, sock: str = ""):
        self._sock = sock or socket_path()

    # ---- wire ------------------------------------------------------------

    def _request(self, msg_type: int, payload: str = "") -> object:
        if not self._sock:
            raise CompositorError("no compositor socket ($SWAYSOCK is not set)")
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect(self._sock)
        except OSError as e:
            raise CompositorError(f"cannot reach the compositor: {e}") from e
        try:
            data = payload.encode()
            s.sendall(_HEADER.pack(MAGIC, len(data), msg_type) + data)
            while True:
                magic, length, rtype = _HEADER.unpack(_recv_exact(s, _HEADER.size))
                if magic != MAGIC:
                    raise CompositorError("bad IPC magic — not a sway/i3 socket")
                body = _recv_exact(s, length)
                # An event racing ahead of our reply is legal; skip it.
                if rtype & _EVENT_BIT:
                    continue
                return json.loads(body) if body else None
        finally:
            s.close()

    def command(self, cmd: str) -> None:
        """Run a sway command; raise with sway's own message if it refuses."""
        results = self._request(RUN_COMMAND, cmd)
        for r in results or []:
            if not r.get("success"):
                raise CompositorError(r.get("error") or f"compositor rejected: {cmd}")

    # ---- windows ----------------------------------------------------------

    def windows(self) -> list[dict]:
        """Every real application window, flattened from the layout tree.

        The shape matches what /api/windows always returned (id/pid/app/title)
        so the taskbar renders identically in hosted and DE modes, plus the
        placement facts only a compositor can know.
        """
        tree = self._request(GET_TREE)
        wins: list[dict] = []

        def walk(node: dict, workspace: str):
            if node.get("type") == "workspace":
                workspace = node.get("name") or workspace
            for child in (node.get("nodes") or []) + (node.get("floating_nodes") or []):
                # A view (real window) has no child containers of its own.
                if not child.get("nodes") and not child.get("floating_nodes") and (
                        child.get("pid") or child.get("app_id") or
                        (child.get("window_properties") or {}).get("class")):
                    props = child.get("window_properties") or {}
                    app = child.get("app_id") or props.get("class") or ""
                    title = child.get("name") or props.get("title") or ""
                    if "agentos" in app.lower() or title.strip() == "AgentOS":
                        continue                       # never list our own shell
                    wins.append({
                        "id": str(child["id"]),
                        "pid": child.get("pid") or 0,
                        "app": app,
                        "title": title,
                        "workspace": workspace,
                        "focused": bool(child.get("focused")),
                        "floating": "on" in str(child.get("floating", "")),
                        "fullscreen": bool(child.get("fullscreen_mode")),
                    })
                else:
                    walk(child, workspace)

        walk(tree or {}, "")
        return wins

    def focus(self, win_id: str) -> None:
        self.command(f"[con_id={int(win_id)}] focus")

    def close(self, win_id: str) -> None:
        self.command(f"[con_id={int(win_id)}] kill")   # polite close, not SIGKILL

    def move_to_workspace(self, win_id: str, workspace: str) -> None:
        ws = str(workspace).replace('"', "")
        self.command(f'[con_id={int(win_id)}] move container to workspace "{ws}"')

    def set_floating(self, win_id: str, floating: bool) -> None:
        self.command(
            f"[con_id={int(win_id)}] floating {'enable' if floating else 'disable'}")

    # ---- workspaces --------------------------------------------------------

    def workspaces(self) -> list[dict]:
        raw = self._request(GET_WORKSPACES)
        return [{"name": w.get("name", ""), "num": w.get("num", -1),
                 "focused": bool(w.get("focused")), "output": w.get("output", ""),
                 "urgent": bool(w.get("urgent"))} for w in raw or []]

    def switch_workspace(self, workspace: str) -> None:
        ws = str(workspace).replace('"', "")
        self.command(f'workspace "{ws}"')

    # ---- outputs -----------------------------------------------------------

    def outputs(self) -> list[dict]:
        raw = self._request(GET_OUTPUTS)
        outs = []
        for o in raw or []:
            cur = o.get("current_mode") or {}
            outs.append({
                "name": o.get("name", ""),
                "make": o.get("make", ""), "model": o.get("model", ""),
                "serial": o.get("serial", ""),
                "active": bool(o.get("active")),
                "primary": bool(o.get("primary")),
                "scale": o.get("scale", 1),
                "transform": o.get("transform", "normal"),
                "position": o.get("rect") and {"x": o["rect"]["x"], "y": o["rect"]["y"]},
                "mode": cur and {"width": cur.get("width"), "height": cur.get("height"),
                                 "refresh": cur.get("refresh")},
                "modes": [{"width": m.get("width"), "height": m.get("height"),
                           "refresh": m.get("refresh")} for m in o.get("modes") or []],
            })
        return outs

    def configure_output(self, name: str, *, mode: str | None = None,
                         scale: float | None = None,
                         transform: str | None = None,
                         position: tuple[int, int] | None = None,
                         enabled: bool | None = None) -> None:
        """Apply one output change. sway validates values and we surface its
        error verbatim — no second list of legal modes to keep in sync."""
        name = str(name).replace('"', "")
        parts: list[str] = []
        if enabled is not None:
            parts.append("enable" if enabled else "disable")
        if mode:
            parts.append(f"mode {mode}")
        if scale is not None:
            parts.append(f"scale {scale}")
        if transform:
            parts.append(f"transform {transform}")
        if position is not None:
            parts.append(f"position {int(position[0])} {int(position[1])}")
        if not parts:
            return
        self.command(f'output "{name}" {" ".join(parts)}')

    # ---- events (async: one connection for the life of the session) --------

    async def subscribe(self, events: tuple[str, ...] = ("window", "workspace", "output")):
        """Yield {'event': ..., 'change': ...} as the compositor reports them.

        This replaces the taskbar's polling: the server pumps these onto its
        WebSocket, and the UI updates the moment a window opens, closes, or
        changes focus.
        """
        if not self._sock:
            raise CompositorError("no compositor socket ($SWAYSOCK is not set)")
        reader, writer = await asyncio.open_unix_connection(self._sock)
        try:
            payload = json.dumps(list(events)).encode()
            writer.write(_HEADER.pack(MAGIC, len(payload), SUBSCRIBE) + payload)
            await writer.drain()
            while True:
                magic, length, rtype = _HEADER.unpack(
                    await reader.readexactly(_HEADER.size))
                if magic != MAGIC:
                    raise CompositorError("bad IPC magic on event stream")
                body = json.loads(await reader.readexactly(length) or b"null")
                if not rtype & _EVENT_BIT:
                    if isinstance(body, dict) and not body.get("success", True):
                        raise CompositorError("compositor refused the subscription")
                    continue
                yield {"event": EVENT_NAMES.get(rtype & ~_EVENT_BIT, "unknown"),
                       "change": (body or {}).get("change", "")}
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
