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

    def set_window_floating(self, win_id: str, floating: bool) -> tuple[bool, str]:
        if not str(win_id).isdigit():
            return False, "invalid window id"
        try:
            self._comp.set_floating(win_id, floating)
            return True, "ok"
        except comp.CompositorError as e:
            return False, str(e)

    def cycle_focus(self, direction: str = "next") -> tuple[bool, str]:
        """Alt-Tab: shell → native windows in order → back to the shell.

        Bound in the generated sway config, so it works no matter which window
        holds the keyboard — the compositor sees the chord before any client.
        """
        try:
            wins = self._comp.windows(include_shell=True)
        except comp.CompositorError as e:
            return False, str(e)
        natives = [w for w in wins if not w.get("shell")]
        if not natives:
            return True, "no native windows"
        step = -1 if direction == "prev" else 1
        cur = next((i for i, w in enumerate(natives) if w["focused"]), None)
        if cur is None:                       # on the shell (or nowhere): enter the ring
            target = natives[0] if step > 0 else natives[-1]
        else:
            nxt = cur + step
            if 0 <= nxt < len(natives):
                target = natives[nxt]
            else:                             # walked off the end: back to the shell
                for crit in ('[app_id="^agentos$"] focus', '[class="^agentos$"] focus'):
                    try:
                        self._comp.command(crit)
                        return True, "shell"
                    except comp.CompositorError:
                        continue
                return False, "could not focus the shell"
        try:
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
