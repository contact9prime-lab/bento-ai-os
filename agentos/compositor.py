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
    env = os.environ.get("SWAYSOCK", "") or os.environ.get("I3SOCK", "")
    if env and os.path.exists(env):
        return env
    return _discover_socket()


def _discover_socket() -> str:
    """Find the compositor socket when we did NOT inherit $SWAYSOCK.

    The server is often started by systemd at login — outside the compositor —
    and the AgentOS session then reuses that already-running server. Without
    this, such a server can never see a window: it reports `hosted` forever even
    while sitting inside the AgentOS session. sway names its socket
    /run/user/<uid>/sway-ipc.<uid>.<pid>.sock, so the running compositor of this
    very user is discoverable; we adopt the newest one that answers and export
    it so every later call (and subprocess) agrees."""
    import glob
    uid = os.getuid() if hasattr(os, "getuid") else 0
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    cands = sorted(glob.glob(f"{runtime}/sway-ipc.*.sock")
                   + glob.glob(f"{runtime}/i3/ipc-socket.*"),
                   key=lambda p: os.stat(p).st_mtime if os.path.exists(p) else 0,
                   reverse=True)
    for path in cands:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sk:
                sk.settimeout(0.4)
                sk.connect(path)
        except OSError:
            continue
        os.environ["SWAYSOCK"] = path      # everything downstream (incl. swaymsg) agrees
        return path
    return ""


def compositor_pid(path: str = "") -> int:
    """PID of the compositor owning the socket (encoded in sway's socket name)."""
    path = path or socket_path()
    try:
        return int(os.path.basename(path).split(".")[-2])
    except Exception:
        return 0


_SHELL_PORT = [0]
# True while the desktop has been deliberately brought to the front (Ctrl+Space,
# the Alt-Tab overlay). Read by anchor_shell, which must not undo it.
SHELL_RAISED = [False]


def shell_port() -> int:
    """The port the AgentOS shell is being served on.

    Needed because the shell CANNOT be recognised by app_id: Chromium only
    applies --class to XWayland, so under native Wayland our own desktop
    arrives looking like the browser. Its command line is the honest signal,
    and that needs the port."""
    if _SHELL_PORT[0]:
        return _SHELL_PORT[0]
    port = 0
    try:
        from . import config as cfgmod
        port = int((cfgmod.load_config().get("server") or {}).get("port") or 0)
    except Exception:
        port = 0
    _SHELL_PORT[0] = port or int(os.environ.get("AGENTOS_PORT") or 8321)
    return _SHELL_PORT[0]


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


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().decode(errors="replace")
    except Exception:
        return ""


def _is_shell_node(node: dict, app: str, title: str, port: int) -> bool:
    """Is this window the AgentOS desktop itself?

    The command line first, because app_id lies under Wayland (Chromium applies
    --class only to XWayland). Name matching stays as a fallback for the X11
    kiosk mode, where WM_CLASS really is "agentos".
    """
    cmd = _cmdline(node.get("pid") or 0)
    if cmd and (f"127.0.0.1:{port}" in cmd or "agentos/boot.html" in cmd):
        return True
    return "agentos" in (app or "").lower() or (title or "").strip() == "AgentOS"


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

    def windows(self, include_shell: bool = False) -> list[dict]:
        """Every real application window, flattened from the layout tree.

        The shape matches what /api/windows always returned (id/pid/app/title)
        so the taskbar renders identically in hosted and DE modes, plus the
        placement facts only a compositor can know. The AgentOS shell itself is
        excluded (a taskbar must not list its own desktop); pass
        include_shell=True to get it too, flagged {"shell": True} — the focus
        cycler needs to know where the user is.

        Minimised windows are the ones parked in sway's scratchpad — sway has no
        minimise of its own, and the scratchpad is exactly "hidden but alive".
        They are still listed, flagged {"minimized": True}, because a taskbar
        that drops a window on minimise leaves no way to bring it back.
        """
        tree = self._request(GET_TREE)
        port = shell_port()
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
                    is_shell = _is_shell_node(child, app, title, port)
                    if is_shell and not include_shell:
                        continue                       # never list our own shell
                    row = {
                        "id": str(child["id"]),
                        "pid": child.get("pid") or 0,
                        "app": app,
                        "title": title,
                        "workspace": workspace,
                        "focused": bool(child.get("focused")),
                        "floating": "on" in str(child.get("floating", "")),
                        "fullscreen": bool(child.get("fullscreen_mode")),
                        "minimized": workspace.startswith("__i3_scratch"),
                    }
                    if is_shell:
                        row["shell"] = True
                    wins.append(row)
                else:
                    walk(child, workspace)

        walk(tree or {}, "")
        return wins

    def exec(self, cmd: str) -> None:
        """Have the COMPOSITOR spawn a process.

        This is how a GUI app gets launched correctly in the AgentOS session:
        the child inherits the compositor's own environment — WAYLAND_DISPLAY,
        XDG_RUNTIME_DIR, DISPLAY for XWayland, the session bus — none of which a
        server started by systemd at login has. Spawning from the server instead
        produces a process that dies the moment it tries to open a window, which
        looks exactly like "it says launching but nothing happens"."""
        self.command(f"exec {cmd}")

    def find_by_pid(self, pid: int) -> str:
        """con_id of the window belonging to a process (its whole tree), or ''."""
        tree = self._request(GET_TREE)
        found = [""]

        def walk(node):
            if found[0]:
                return
            if node.get("pid") == pid and node.get("type") in ("con", "floating_con") \
                    and (node.get("app_id") or node.get("window_properties")):
                found[0] = str(node.get("id"))
                return
            for kid in (node.get("nodes") or []) + (node.get("floating_nodes") or []):
                walk(kid)

        walk(tree if isinstance(tree, dict) else {})
        return found[0]

    def find_shell(self, port: int) -> str:
        """con_id of the AgentOS shell window itself.

        Matching on app_id/class is unreliable: Chromium only applies --class to
        XWayland's WM_CLASS, so under native Wayland the shell arrives with the
        browser's own app_id and misses every rule written for "agentos" — which
        left it FLOATING at a default size instead of filling the screen. The
        command line is unambiguous: our renderer is the process pointed at our
        own port."""
        tree = self._request(GET_TREE)
        found = [""]

        def walk(node):
            if found[0]:
                return
            pid = node.get("pid")
            if pid and (node.get("app_id") or node.get("window_properties")):
                cmd = _cmdline(pid)
                if f"127.0.0.1:{port}" in cmd or "agentos/boot.html" in cmd:
                    found[0] = str(node.get("id"))
                    return
            for kid in (node.get("nodes") or []) + (node.get("floating_nodes") or []):
                walk(kid)

        walk(tree if isinstance(tree, dict) else {})
        return found[0]

    def anchor_shell(self, port: int) -> bool:
        # Never fight a deliberate summon. anchor_shell runs on every window
        # event, and it does `floating disable` — which used to drop the shell
        # straight back behind the apps the instant Ctrl+Space raised it.
        if SHELL_RAISED[0]:
            return True
        """Make the shell the full-screen base layer: tiled, borderless, behind
        every app window (which all float). Idempotent — safe to call whenever
        the compositor reports a change."""
        cid = self.find_shell(port)
        if not cid:
            return False
        self.command(f"[con_id={cid}] floating disable")
        self.command(f"[con_id={cid}] border none")
        self.command(f"[con_id={cid}] fullscreen disable")
        return True

    def focus(self, win_id: str) -> None:
        # A minimised window lives in the scratchpad; focusing it has to bring it
        # back first, or the click on its taskbar tile does nothing at all.
        cid = int(win_id)
        try:
            self.command(f"[con_id={cid}] scratchpad show")
        except CompositorError:
            pass                                  # not minimised — the normal case
        self.command(f"[con_id={cid}] focus")

    def focus_shell(self, port: int = 0) -> bool:
        """Put the keyboard back on the AgentOS desktop.

        By con_id when the command-line probe finds it, falling back to the
        app_id/class criteria — which is what actually matches under XWayland
        and in the older X11 kiosk mode.
        """
        cid = self.find_shell(port or shell_port())
        if cid:
            self.command(f"[con_id={int(cid)}] focus")
            return True
        for crit in ('[app_id="^agentos$"] focus', '[class="^agentos$"] focus'):
            try:
                self.command(crit)
                return True
            except CompositorError:
                continue
        return False

    def raise_shell(self, on: bool, port: int = 0) -> bool:
        """Bring the AgentOS desktop in front of the native windows, or send it
        back behind them.

        Focus alone is not enough: the shell is the tiled base layer and sway
        always paints floating windows above tiled ones, so Ctrl+Space would
        summon a prompt bar the user cannot see. Full screen is the one state
        that outranks floating, so summoning fullscreens the shell and releasing
        puts it straight back to being the layer everything else sits on.
        """
        cid = self.find_shell(port or shell_port())
        if not cid:
            return False
        SHELL_RAISED[0] = bool(on)
        if on:
            # Floating, not fullscreen. Both put the shell above the native
            # windows, but sway's fullscreen makes Chromium believe the PAGE went
            # full screen, so it flashes "To exit full screen, press and hold Esc"
            # every single time you summon the prompt bar. Floating + sized to the
            # output looks identical and says nothing.
            x, y, w, h = self.work_area(top=0)
            # ONE chained command, not four. Sent separately, sway floats the
            # window at its remembered size and Chromium acks that before the
            # resize lands — the desktop came forward at half width. Chained,
            # sway applies the lot atomically. The explicit `width N px` form
            # matters too: the bare `resize set W H` does not take here.
            self.command(f"[con_id={int(cid)}] floating enable, "
                         f"resize set width {w} px height {h} px, "
                         f"move absolute position {x} {y}, focus")
        else:
            # back to being the layer everything else sits on
            self.command(f"[con_id={int(cid)}] floating disable, border none")
        return True

    def minimize(self, win_id: str) -> None:
        """sway has no minimise; the scratchpad IS minimise — hidden, alive, and
        listed in our taskbar so it can be brought back."""
        self.command(f"[con_id={int(win_id)}] move scratchpad")

    def unminimize(self, win_id: str) -> None:
        cid = int(win_id)
        self.command(f"[con_id={cid}] scratchpad show")
        self.command(f"[con_id={cid}] focus")

    def work_area(self, top: int = 34) -> tuple[int, int, int, int]:
        """The screen minus the AgentOS menu bar — where a maximized window goes.

        Maximize and full screen are different things and people expect both: a
        maximized window fills the desk but leaves the menu bar reachable; a full
        screen one covers everything."""
        outs = [o for o in (self._request(GET_OUTPUTS) or []) if o.get("active")]
        focused = next((o for o in outs if o.get("focused")), None) or (outs[0] if outs else None)
        r = (focused or {}).get("rect") or {"x": 0, "y": 0, "width": 1920, "height": 1080}
        return int(r["x"]), int(r["y"]) + top, int(r["width"]), int(r["height"]) - top

    def maximize(self, win_id: str, top: int = 34) -> None:
        cid = int(win_id)
        x, y, w, h = self.work_area(top)
        self.command(f"[con_id={cid}] floating enable")
        self.command(f"[con_id={cid}] resize set width {w} px height {h} px")
        self.command(f"[con_id={cid}] move absolute position {x} {y}")

    def unmaximize(self, win_id: str, top: int = 34) -> None:
        """Back to a window-sized window, centred — sway does not remember the
        pre-maximize geometry for us, so a sensible default beats nothing."""
        cid = int(win_id)
        x, y, w, h = self.work_area(top)
        nw, nh = int(w * 0.62), int(h * 0.68)
        self.command(f"[con_id={cid}] resize set width {nw} px height {nh} px")
        self.command(f"[con_id={cid}] move absolute position {x + (w - nw) // 2} {y + (h - nh) // 3}")

    def set_fullscreen(self, win_id: str, on: bool | None = None) -> None:
        arg = "toggle" if on is None else ("enable" if on else "disable")
        self.command(f"[con_id={int(win_id)}] fullscreen {arg}")

    def show_desktop(self, port: int = 0) -> int:
        """Clear the screen down to the AgentOS desktop — the escape hatch when a
        native window is covering everything. Returns how many were hidden."""
        n = 0
        for w in self.windows():
            if not w.get("minimized"):
                try:
                    self.minimize(w["id"])
                    n += 1
                except CompositorError:
                    pass
        self.focus_shell(port)
        return n

    def move_window(self, win_id: str, x: int, y: int) -> None:
        self.command(f"[con_id={int(win_id)}] move absolute position {int(x)} {int(y)}")

    def resize_window(self, win_id: str, w: int, h: int) -> None:
        self.command(f"[con_id={int(win_id)}] resize set width {int(w)} px height {int(h)} px")

    def close(self, win_id: str) -> None:
        self.command(f"[con_id={int(win_id)}] kill")   # polite close, not SIGKILL

    def move_to_workspace(self, win_id: str, workspace: str) -> None:
        ws = str(workspace).replace('"', "")
        self.command(f'[con_id={int(win_id)}] move container to workspace "{ws}"')

    def set_floating(self, win_id: str, floating: bool) -> None:
        self.command(
            f"[con_id={int(win_id)}] floating {'enable' if floating else 'disable'}")

    # ---- workspaces --------------------------------------------------------

    def goto_desktop(self, n: int, port: int = 0) -> None:
        """Switch to desktop N and take the AgentOS shell with you.

        AgentOS desktops used to be a purely in-page idea while native windows
        lived on sway workspaces — which is why every external app appeared on
        every desktop. Binding the two together is what makes a desktop mean the
        same thing to both. The shell moves along because it IS the desktop: it
        has to be there whichever space you are on.
        """
        ws = str(int(n))
        cid = self.find_shell(port or shell_port())
        if cid:
            self.command(f"[con_id={int(cid)}] move container to workspace {ws}")
        self.command(f"workspace {ws}")
        if cid:
            self.command(f"[con_id={int(cid)}] floating disable")

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
