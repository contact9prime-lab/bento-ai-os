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
import base64
import contextlib
import json
import os
import socket
import struct
import time

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
# True when the desktop is drawn by the native session host as a layer-shell
# surface instead of a Chromium window (see agentos/shellhost.py). Then there is
# no shell WINDOW: stacking is correct by construction, the chrome bands are
# reserved as exclusive zones, and every anchor/raise/lower below has nothing to
# do. The page tells us, because only the host injects the bridge that lets it.
SUI_HOST = [False]


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

        def walk(node: dict, workspace: str, floating: bool = False):
            if node.get("type") == "workspace":
                workspace = node.get("name") or workspace
            # Which ARRAY the child is in is the only thing sway tells us about
            # floating. It emits no "floating" key on window nodes at all (i3
            # does, which is where that read came from) — so the old check was
            # False for every window on every real session.
            for child, floats in ([(c, floating) for c in (node.get("nodes") or [])]
                                  + [(c, True) for c in (node.get("floating_nodes") or [])]):
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
                        # i3's own key first (it does send one), else the array
                        "floating": "on" in str(child.get("floating", "")) or floats,
                        "fullscreen": bool(child.get("fullscreen_mode")),
                        "minimized": workspace.startswith("__i3_scratch"),
                    }
                    if is_shell:
                        row["shell"] = True
                    wins.append(row)
                else:
                    walk(child, workspace, floats)

        walk(tree or {}, "")
        return wins

    def exec(self, cmd: str) -> None:
        """Have the COMPOSITOR spawn a process, byte for byte.

        The command is base64'd and decoded by the shell on the far side, because
        sway parses the rest of an `exec` line with its OWN tokenizer first: `,`
        and `;` are command separators, and quotes and angle brackets are eaten
        or rejected outright. Real `.desktop` Exec lines contain all of those —
        `Exec=chromium --app=data:text/html,<title>x</title>` came back as
        "Unknown/invalid command '<title>x</title>'" and the app never started.
        Base64's alphabet is inert to that parser, so what the app receives is
        exactly what the .desktop file said.

        This is how a GUI app gets launched correctly in the AgentOS session:
        the child inherits the compositor's own environment — WAYLAND_DISPLAY,
        XDG_RUNTIME_DIR, DISPLAY for XWayland, the session bus — none of which a
        server started by systemd at login has. Spawning from the server instead
        produces a process that dies the moment it tries to open a window, which
        looks exactly like "it says launching but nothing happens"."""
        blob = base64.b64encode(cmd.encode()).decode()
        self.command(f"exec sh -c 'echo {blob} | base64 -d | sh'")

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
            props = node.get("window_properties") or {}
            if node.get("pid") and (node.get("app_id") or props):
                # the SAME test windows() uses, so the taskbar and the raise/lower
                # logic can never disagree about which window is the desktop.
                # It falls back to app_id/class when /proc is unreadable, which is
                # what kept raise_shell silently doing nothing on those machines.
                app = node.get("app_id") or props.get("class") or ""
                title = node.get("name") or props.get("title") or ""
                if _is_shell_node(node, app, title, port):
                    found[0] = str(node.get("id"))
                    return
            for kid in (node.get("nodes") or []) + (node.get("floating_nodes") or []):
                walk(kid)

        walk(tree if isinstance(tree, dict) else {})
        return found[0]

    def anchor_shell(self, port: int) -> bool:
        # Under the session host there is nothing to anchor: the desktop is a
        # BACKGROUND-layer surface, which is below every window by definition.
        if SUI_HOST[0]:
            return True
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
        # Handing the screen to an app has to LOWER the desktop first. While the
        # shell is raised it is a floating window the size of the whole output,
        # and sway paints floating above tiled — so focusing an app without
        # lowering gives the keyboard to a window nobody can see. That is what
        # made session mode feel like a browser page that had eaten the screen:
        # the app really was running, behind the desktop.
        if SHELL_RAISED[0]:
            self.raise_shell(False)
        # A minimised window lives in the scratchpad; focusing it has to bring it
        # back first, or the click on its taskbar tile does nothing at all.
        cid = int(win_id)
        try:
            self.command(f"[con_id={cid}] scratchpad show")
        except CompositorError:
            pass                                  # not minimised — the normal case
        self.command(f"[con_id={cid}] focus")

    def launch_and_focus(self, cmd: str, timeout: float = 15.0,
                         poll: float = 0.15) -> dict:
        """Spawn an app through the compositor and hand it the screen.

        `exec` alone was never enough. It returns the instant sway forks, so the
        desktop said "launched" while the shell was still the full-screen window
        in front — and a GUI app that takes two seconds to map (anything
        LibreOffice-sized) appeared behind it, or never appeared at all if it
        died on startup. Both looked identical to the user: nothing happened.

        So: lower the desktop out of the way, watch the tree for a window that
        was not there before, and focus it. If nothing maps inside `timeout`,
        put the desktop back and say so — an app that failed to start must not
        leave the user staring at an empty screen wondering.
        """
        before = {w["id"] for w in self.windows()}
        self.raise_shell(False)                     # the app is about to own the screen
        self.exec(cmd)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(poll)
            try:
                fresh = [w for w in self.windows() if w["id"] not in before]
            except CompositorError:
                continue
            if fresh:
                win = fresh[0]
                with contextlib.suppress(CompositorError):
                    self.command(f"[con_id={int(win['id'])}] focus")
                return {"ok": True, "window": win["id"], "title": win.get("title", "")}
        # Nothing mapped in time — give the desktop back rather than stranding the
        # user on a blank screen. If the app was merely slow and turns up later,
        # it still ends in front: sway focuses a newly mapped window, the server's
        # event pump clears SHELL_RAISED on that focus, and the following window
        # event re-anchors the shell underneath it.
        with contextlib.suppress(CompositorError):
            self.raise_shell(True)
        return {"ok": False, "window": "",
                "reason": "no window appeared — the app may have failed to start "
                          "(see the Logs app), or it is still loading"}

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
        # The session host changes its own layer, atomically, from the page.
        if SUI_HOST[0]:
            return True
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
        """The usable screen — where a maximized window goes.

        Maximize and full screen are different things and people expect both: a
        maximized window fills the desk but leaves the menu bar and dock
        reachable; a full screen one covers everything.

        The compositor already knows the answer when the session host is running:
        the AgentOS menu bar and dock are declared as layer-shell exclusive
        zones, and sway subtracts those from the WORKSPACE rect. Using it means
        maximize lands exactly between our own chrome, for whatever height the
        current theme and device happen to give it — instead of the fixed 34px
        guess, which was wrong for every theme that resized the menu bar and knew
        nothing about the dock at all.

        `top` stays as the fallback for the Chromium session, where there are no
        exclusive zones to read.
        """
        ws = [w for w in (self._request(GET_WORKSPACES) or []) if w.get("focused")]
        rect = (ws[0].get("rect") if ws else None) or {}
        if rect.get("width") and rect.get("height"):
            return int(rect["x"]), int(rect["y"]), int(rect["width"]), int(rect["height"])
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

    #: Snap zones, as fractions of the usable area: (x, y, w, h).
    SNAP_ZONES = {
        "left":   (0.0, 0.0, 0.5, 1.0),
        "right":  (0.5, 0.0, 0.5, 1.0),
        "top":    (0.0, 0.0, 1.0, 0.5),
        "bottom": (0.0, 0.5, 1.0, 0.5),
        "tl":     (0.0, 0.0, 0.5, 0.5),
        "tr":     (0.5, 0.0, 0.5, 0.5),
        "bl":     (0.0, 0.5, 0.5, 0.5),
        "br":     (0.5, 0.5, 0.5, 0.5),
        "center": (0.18, 0.12, 0.64, 0.76),
        "full":   (0.0, 0.0, 1.0, 1.0),
    }

    def snap(self, win_id: str, zone: str) -> None:
        """Put a native window in half or a quarter of the screen.

        AgentOS's own windows have snapped to screen edges since the beginning;
        native ones could only be moved and resized by hand, which made them feel
        like second-class windows on their own desktop. The geometry comes from
        work_area(), so a snapped window lands between the menu bar and the dock
        rather than underneath them.
        """
        frac = self.SNAP_ZONES.get(zone)
        if not frac:
            raise CompositorError(
                f"unknown snap zone '{zone}' (try: {', '.join(self.SNAP_ZONES)})")
        x, y, w, h = self.work_area()
        fx, fy, fw, fh = frac
        nx, ny = int(x + w * fx), int(y + h * fy)
        nw, nh = int(w * fw), int(h * fh)
        cid = int(win_id)
        # One chained command: sent separately, sway acks the float before the
        # resize lands and the window flashes at its old size on the way.
        self.command(f"[con_id={cid}] floating enable, "
                     f"resize set width {nw} px height {nh} px, "
                     f"move absolute position {nx} {ny}")

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
