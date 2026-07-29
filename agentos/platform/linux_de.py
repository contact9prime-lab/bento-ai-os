"""Linux, with AgentOS as the session — the desktop environment mode.

Here AgentOS is not a guest: our compositor draws the screen, our panels are the
settings, our daemon receives notifications. Everything the hosted backend has to
hand off to GNOME, this one owns.

It subclasses LinuxHosted deliberately. Reading .desktop files, launching apps
and reading volume work identically whoever runs the session, so they are
inherited rather than duplicated; this class only overrides what genuinely
differs when we are in charge.

Window, workspace and display management go through the compositor IPC client
(agentos/compositor.py) — that is what replaces wmctrl, which Wayland made
impossible for guests. The D-Bus system controls (wifi join, bluetooth,
brightness…) land in W4; until each backend is connected, its capability
reports unavailable with the reason why. That is the contract working as
intended: the UI greys the control and explains, rather than offering a button
that throws.
"""

from __future__ import annotations

from .. import compositor as comp
from . import caps as C
from .base import Capability, missing, ok
from .linux_hosted import LinuxHosted


class LinuxDE(LinuxHosted):
    name = "AgentOS"
    # --- launching ---------------------------------------------------------

    def launch_app(self, app_id: str) -> tuple[bool, str]:
        """Launch through the compositor, not from this process.

        The server is normally started by systemd at login, so its environment
        has no WAYLAND_DISPLAY / DISPLAY / session bus — a GUI app spawned from
        here connects to nothing and exits immediately ("launching…" and then
        nothing appears). Asking sway to exec it gives the child the session's
        own environment and puts the window on the current workspace."""
        import re
        import shutil
        from pathlib import Path
        from ..session import APP_ID
        from .linux_hosted import APP_DIRS
        if not re.fullmatch(r"[\w .+()&,'-]+", app_id or ""):
            return False, "invalid app id"
        # AgentOS inside AgentOS is not a window, it is a second desktop session
        # fighting this one for the compositor, the notification bus and the
        # port. You are already in it.
        if app_id.lower() in (APP_ID, f"{APP_ID}-wayland", f"{APP_ID}-session"):
            return False, ("AgentOS is already running — this session IS AgentOS. "
                           "Opening a second one would fight this one for the "
                           "screen, the notification bus and the port.")
        if comp.available():
            # Fastest first: we already parsed this .desktop file, so run its
            # command directly instead of spawning gtk-launch to read the very
            # same file again. gtk-launch stays as the fallback because it also
            # handles DBusActivatable entries and terminal apps.
            cmd = ""
            entry = next((a for a in self.list_apps() if a["id"] == app_id), None)
            if entry and entry.get("exec") and not entry.get("terminal") and not entry.get("dbus"):
                cmd = entry["exec"]
            elif shutil.which("gtk-launch"):
                cmd = f"gtk-launch '{app_id}'"
            elif shutil.which("gio"):
                path = next((str(Path(d) / f"{app_id}.desktop") for d in APP_DIRS
                             if (Path(d) / f"{app_id}.desktop").is_file()), "")
                if path:
                    cmd = f"gio launch '{path}'"
            if cmd:
                try:
                    # launch_and_focus, not exec: the desktop has to get out of
                    # the way and the app has to actually appear before we call
                    # this a success. `exec` returned the instant sway forked,
                    # which is how "launched" could be true while nothing was on
                    # screen — see compositor.launch_and_focus.
                    res = comp.Compositor().launch_and_focus(cmd)
                    if res.get("ok"):
                        return True, "launched"
                    return False, res.get("reason") or "the app did not open a window"
                except Exception:
                    pass          # sway said no — fall through to the plain spawn
        return super().launch_app(app_id)


    def __init__(self, mode: str = "de"):
        super().__init__(mode=mode)
        self.name = "AgentOS"
        self._comp = comp.Compositor()

    def _probe(self) -> dict[str, Capability]:
        # Start from the hosted probe so shared things (apps, volume, battery,
        # network status) keep exactly one implementation.
        caps = super()._probe()

        # --- window & display management: compositor IPC --------------------
        if comp.available():
            for cap_id in (C.WINDOWS_LIST, C.WINDOWS_MANAGE, C.WINDOWS_ARRANGE,
                           C.WORKSPACES, C.DISPLAY_LIST, C.DISPLAY_CONFIGURE):
                caps[cap_id] = ok(cap_id)
        else:
            why = "The compositor isn't reachable — $SWAYSOCK is not set in this session."
            for cap_id in (C.WINDOWS_LIST, C.WINDOWS_MANAGE, C.WINDOWS_ARRANGE,
                           C.WORKSPACES, C.DISPLAY_LIST, C.DISPLAY_CONFIGURE):
                caps[cap_id] = missing(cap_id, why)

        # --- system controls: D-Bus daemons + PipeWire ----------------------
        from .. import hostctl
        from ..hostctl import audio as hc_audio
        from ..hostctl import bluetooth as hc_bt
        from ..hostctl import brightness as hc_bright
        from ..hostctl import network as hc_net
        from ..hostctl import upower as hc_up

        if not hostctl.system_bus_present():
            bus_gone = "The system D-Bus is not reachable."
            for cap_id in (C.NET_WIFI_SCAN, C.NET_WIFI_JOIN, C.NET_AIRPLANE,
                           C.BT_STATUS, C.BT_MANAGE, C.POWER_PROFILE):
                caps[cap_id] = missing(cap_id, bus_gone)
        else:
            net_ok, net_why, net_comp = hc_net.available()
            for cap_id in (C.NET_WIFI_SCAN, C.NET_WIFI_JOIN, C.NET_AIRPLANE):
                caps[cap_id] = ok(cap_id) if net_ok else missing(cap_id, net_why, net_comp)
            bt_ok, bt_why, bt_comp = hc_bt.available()
            for cap_id in (C.BT_STATUS, C.BT_MANAGE):
                caps[cap_id] = ok(cap_id) if bt_ok else missing(cap_id, bt_why, bt_comp)
            prof_ok, prof_why, prof_comp = hc_up.profiles_available()
            caps[C.POWER_PROFILE] = (ok(C.POWER_PROFILE) if prof_ok
                                     else missing(C.POWER_PROFILE, prof_why, prof_comp))

        bright_ok, bright_why, bright_comp = hc_bright.available()
        for cap_id in (C.BRIGHTNESS_GET, C.BRIGHTNESS_SET):
            caps[cap_id] = (ok(cap_id) if bright_ok
                            else missing(cap_id, bright_why, bright_comp))

        audio_ok, audio_why = hc_audio.available()
        for cap_id in (C.AUDIO_DEVICES, C.AUDIO_PER_APP):
            caps[cap_id] = ok(cap_id) if audio_ok else missing(cap_id, audio_why)

        # --- session services -----------------------------------------------
        import shutil as _sh

        # The server claims org.freedesktop.Notifications at startup in this
        # mode; /api/notifications reports the live claim state.
        caps[C.NOTIFY_DAEMON] = ok(C.NOTIFY_DAEMON)
        caps[C.SCREEN_CAPTURE] = (
            ok(C.SCREEN_CAPTURE) if _sh.which("grim")
            else missing(C.SCREEN_CAPTURE,
                         "Screenshots need grim (part of the agentos-desktop package).",
                         "grim"))
        caps[C.SESSION_LOCK] = (
            ok(C.SESSION_LOCK) if _sh.which("swaylock")
            else missing(C.SESSION_LOCK,
                         "Locking needs swaylock (part of the agentos-desktop package).",
                         "swaylock"))

        # --- what is true the moment AgentOS owns the session --------------
        # No host desktop to hand off to, and the wallpaper is ours.
        caps[C.SETTINGS_OPEN] = Capability(
            C.SETTINGS_OPEN, False, False,
            "AgentOS is the desktop — there's no other settings app to open.")
        caps[C.WALLPAPER_SET] = ok(C.WALLPAPER_SET)
        caps[C.SETTINGS_NATIVE] = missing(
            C.SETTINGS_NATIVE, "The built-in settings panels aren't wired up yet.")
        return caps

    def open_settings(self, panel: str = "") -> tuple[bool, str]:
        """No gnome-control-center to fall back on when we are the desktop."""
        return False, "AgentOS is the desktop — settings are built in."

    # --- windows, through the compositor -----------------------------------

    def list_windows(self) -> dict:
        if not comp.available():
            return {"available": False, "windows": [],
                    "reason": "The compositor isn't reachable in this session."}
        try:
            return {"available": True, "windows": self._comp.windows()}
        except comp.CompositorError as e:
            return {"available": False, "windows": [], "reason": str(e)}

    def _win(self, action, win_id: str) -> tuple[bool, str]:
        if not str(win_id).isdigit():
            return False, "invalid window id"
        try:
            action(win_id)
            return True, "ok"
        except comp.CompositorError as e:
            return False, str(e)

    def focus_window(self, win_id: str) -> tuple[bool, str]:
        return self._win(self._comp.focus, win_id)

    def close_window(self, win_id: str) -> tuple[bool, str]:
        return self._win(self._comp.close, win_id)

    def move_window_to_workspace(self, win_id: str, workspace: str) -> tuple[bool, str]:
        if not str(win_id).isdigit():
            return False, "invalid window id"
        try:
            self._comp.move_to_workspace(win_id, workspace)
            return True, "ok"
        except comp.CompositorError as e:
            return False, str(e)

    def minimize_window(self, win_id: str) -> tuple[bool, str]:
        return self._win(self._comp.minimize, win_id)

    def restore_window(self, win_id: str) -> tuple[bool, str]:
        return self._win(self._comp.unminimize, win_id)

    def maximize_window(self, win_id: str, on: bool = True) -> tuple[bool, str]:
        return self._win(lambda i: (self._comp.maximize(i) if on
                                    else self._comp.unmaximize(i)), win_id)

    def fullscreen_window(self, win_id: str, on: bool | None = None) -> tuple[bool, str]:
        return self._win(lambda i: self._comp.set_fullscreen(i, on), win_id)

    def goto_desktop(self, n: int) -> tuple[bool, str]:
        try:
            self._comp.goto_desktop(n)
            return True, f"desktop {n}"
        except comp.CompositorError as e:
            return False, str(e)

    def raise_shell(self, on: bool = True) -> tuple[bool, str]:
        try:
            return (True, "ok") if self._comp.raise_shell(on) else (False, "shell not found")
        except comp.CompositorError as e:
            return False, str(e)

    def show_desktop(self) -> tuple[bool, str]:
        try:
            n = self._comp.show_desktop()
            return True, f"{n} window{'' if n == 1 else 's'} minimised"
        except comp.CompositorError as e:
            return False, str(e)

    def set_window_floating(self, win_id: str, floating: bool) -> tuple[bool, str]:
        if not str(win_id).isdigit():
            return False, "invalid window id"
        try:
            self._comp.set_floating(win_id, floating)
            return True, "ok"
        except comp.CompositorError as e:
            return False, str(e)

    def cycle_focus(self, direction: str = "next") -> tuple[bool, str]:
        """Alt-Tab over one ring: the AgentOS desktop, then every native window.

        The desktop is a stop on the ring rather than a special case, so pressing
        Alt-Tab repeatedly visits everything exactly once and comes back — which
        is the only behaviour that feels right with three windows open. Minimised
        windows are skipped; they are reached from the taskbar.

        Bound in the generated sway config, so it works no matter which window
        holds the keyboard — the compositor sees the chord before any client.
        """
        try:
            wins = self._comp.windows(include_shell=True)
        except comp.CompositorError as e:
            return False, str(e)
        # Sorted by con_id, not by tree order: sway moves the focused floating
        # window to the end of its parent's list, so a tree-order ring reshuffles
        # under you and Alt-Tab ping-pongs between two windows instead of walking
        # through them all.
        ring = [w for w in wins if w.get("shell")][:1]
        ring += sorted((w for w in wins if not w.get("shell") and not w.get("minimized")),
                       key=lambda w: int(w["id"]))
        if len(ring) < 2:
            return True, "nothing to switch to"
        step = -1 if direction == "prev" else 1
        cur = next((i for i, w in enumerate(ring) if w["focused"]), 0)
        target = ring[(cur + step) % len(ring)]
        try:
            if target.get("shell"):
                if self._comp.focus_shell():
                    return True, "shell"
                return False, "could not focus the shell"
            self._comp.focus(target["id"])
            return True, target["app"] or target["title"]
        except comp.CompositorError as e:
            return False, str(e)

    # --- workspaces & outputs ----------------------------------------------

    def workspaces(self) -> dict:
        try:
            return {"available": True, "workspaces": self._comp.workspaces()}
        except comp.CompositorError as e:
            return {"available": False, "workspaces": [], "reason": str(e)}

    def switch_workspace(self, workspace: str) -> tuple[bool, str]:
        try:
            self._comp.switch_workspace(workspace)
            return True, "ok"
        except comp.CompositorError as e:
            return False, str(e)

    def outputs(self) -> dict:
        try:
            return {"available": True, "outputs": self._comp.outputs()}
        except comp.CompositorError as e:
            return {"available": False, "outputs": [], "reason": str(e)}

    def configure_output(self, name: str, **kw) -> tuple[bool, str]:
        try:
            self._comp.configure_output(name, **kw)
            return True, "ok"
        except (comp.CompositorError, TypeError, ValueError) as e:
            return False, str(e)
