"""The Platform contract.

One interface, four backends (`linux_de`, `linux_hosted`, `macos`, `windows`).
Everything above this line — the REST API, the agent tools, the UI — is written
once against this contract, so a change to the desktop lands on every platform
at once and no caller ever branches on `sys.platform`.

Two rules hold every backend together:

  1. Nothing raises NotImplementedError. A backend that can't do something
     returns an empty/false result and says why, so the UI can grey the control
     and explain itself rather than break.
  2. `capabilities()` is the truth. If a capability says unavailable, calling the
     matching method is expected to fail gracefully — callers are free to try.

(`agentos.platform` shadows no stdlib import: Python 3 resolves `import platform`
absolutely, so modules here and elsewhere still get the standard library one.)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from . import caps as C


@dataclass(frozen=True)
class Capability:
    """What the UI needs to decide how to render one control.

    `supported` — this platform could do this at all, given the right pieces.
    `available` — it can do it right now.
    `reason`    — a sentence shown to the user when it can't. Always set when
                  unavailable; never a stack trace, never "not implemented".
    `component` — id of an optional download that would make it available
                  (see agentos/components.py). Empty when nothing would help.
    """
    id: str
    supported: bool
    available: bool
    reason: str = ""
    component: str = ""

    def as_dict(self) -> dict:
        title, when_missing = C.CAPS.get(self.id, (self.id, ""))
        return {
            "id": self.id, "title": title,
            "supported": self.supported, "available": self.available,
            "reason": self.reason, "component": self.component,
            "impact": "" if self.available else when_missing,
        }


def ok(cap_id: str) -> Capability:
    return Capability(cap_id, True, True)


def missing(cap_id: str, reason: str, component: str = "") -> Capability:
    """Supported here in principle, but not usable right now — usually a
    package that isn't installed. `component` points at the fix."""
    return Capability(cap_id, True, False, reason, component)


def unsupported(cap_id: str, reason: str) -> Capability:
    """This platform can't do it at all, and no download changes that."""
    return Capability(cap_id, False, False, reason)


def run(cmd: list[str], timeout: float = 5) -> str:
    """Shared best-effort subprocess helper — empty string on any failure.

    Moved here verbatim from host.py so every backend keeps the same
    swallow-everything behaviour the desktop already relies on.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


@dataclass
class Platform:
    """Default backend: knows nothing, breaks nothing.

    Every method returns the shape callers expect with an empty payload, so a
    partially-implemented backend degrades instead of raising.
    """

    mode: str = "hosted"          # see agentos/runmode.py
    name: str = "generic"
    _cap_cache: dict = field(default_factory=dict, repr=False, compare=False)

    # --- capabilities ------------------------------------------------------

    def _probe(self) -> dict[str, Capability]:
        """Backends override this and return only the capabilities they claim."""
        return {}

    def capabilities(self, refresh: bool = False) -> dict[str, Capability]:
        """Every capability id, always — unclaimed ones report unsupported."""
        if refresh or not self._cap_cache:
            probed = self._probe()
            self._cap_cache = {
                cid: probed.get(cid) or unsupported(cid, f"Not available on {self.name}.")
                for cid in C.ALL
            }
        return self._cap_cache

    def can(self, cap_id: str) -> bool:
        cap = self.capabilities().get(cap_id)
        return bool(cap and cap.available)

    def describe(self) -> dict:
        return {
            "platform": self.name,
            "mode": self.mode,
            "capabilities": {cid: c.as_dict() for cid, c in self.capabilities().items()},
        }

    # --- native applications ----------------------------------------------

    def list_apps(self) -> list[dict]:
        return []

    def resolve_icon(self, name: str) -> str | None:
        return None

    def launch_app(self, app_id: str) -> tuple[bool, str]:
        return False, f"Launching apps isn't available on {self.name}."

    # --- system controls ---------------------------------------------------

    def get_volume(self) -> dict:
        return {"volume": None, "muted": False}

    def set_volume(self, percent: int | None = None, mute: bool | None = None) -> bool:
        return False

    def get_battery(self) -> dict:
        return {}

    def get_network(self) -> dict:
        return {}

    def open_settings(self, panel: str = "") -> tuple[bool, str]:
        return False, f"No system settings app to open on {self.name}."

    def control_state(self) -> dict:
        return {"audio": self.get_volume(), "battery": self.get_battery(),
                "network": self.get_network()}

    # --- windows -----------------------------------------------------------

    def list_windows(self) -> dict:
        return {"available": False, "windows": [],
                "reason": f"Native window control isn't available on {self.name}."}

    def focus_window(self, win_id: str) -> tuple[bool, str]:
        return False, "Window control isn't available here."

    def close_window(self, win_id: str) -> tuple[bool, str]:
        return False, "Window control isn't available here."

    def move_window_to_workspace(self, win_id: str, workspace: str) -> tuple[bool, str]:
        return False, "Window arrangement isn't available here."

    def set_window_floating(self, win_id: str, floating: bool) -> tuple[bool, str]:
        return False, "Window arrangement isn't available here."

    def cycle_focus(self, direction: str = "next") -> tuple[bool, str]:
        return False, "Window cycling isn't available here."

    def minimize_window(self, win_id: str) -> tuple[bool, str]:
        return False, "Window control isn't available here."

    def restore_window(self, win_id: str) -> tuple[bool, str]:
        return False, "Window control isn't available here."

    def maximize_window(self, win_id: str, on: bool = True) -> tuple[bool, str]:
        return False, "Window control isn't available here."

    def fullscreen_window(self, win_id: str, on: bool | None = None) -> tuple[bool, str]:
        return False, "Window control isn't available here."

    def show_desktop(self) -> tuple[bool, str]:
        return False, "Window control isn't available here."

    def goto_desktop(self, n: int) -> tuple[bool, str]:
        """Only the session owns real workspaces; elsewhere desktops are ours
        alone and the shell already handles them."""
        return False, "Not applicable — AgentOS isn't the desktop here."

    def raise_shell(self, on: bool = True) -> tuple[bool, str]:
        """Only meaningful when AgentOS owns the session; elsewhere the shell is
        an ordinary window and the host desktop decides its stacking."""
        return False, "Not applicable — AgentOS isn't the desktop here."

    # --- workspaces & displays (compositor-backed; DE mode only) ------------

    def workspaces(self) -> dict:
        return {"available": False, "workspaces": [],
                "reason": f"Host workspaces aren't manageable on {self.name}."}

    def switch_workspace(self, workspace: str) -> tuple[bool, str]:
        return False, "Workspace switching isn't available here."

    def outputs(self) -> dict:
        return {"available": False, "outputs": [],
                "reason": f"Display configuration isn't available on {self.name}."}

    def configure_output(self, name: str, **kw) -> tuple[bool, str]:
        return False, "Display configuration isn't available here."
