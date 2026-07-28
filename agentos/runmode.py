"""Which desktop is AgentOS today?

AgentOS runs three ways on Linux, and switching between them must never be a
migration — install the desktop package and your GNOME session is still there,
untouched, one logout away.

    hosted   AgentOS is a window on someone else's desktop (GNOME, KDE, macOS,
             Windows). The original mode, and still the default.
    de       AgentOS *is* the session: our Wayland compositor, our settings, our
             notifications, our lock screen.
    kiosk    The older X11 session (openbox + fullscreen shell), kept working.

The mode is detected from the environment the session was started in, and can be
pinned in config with `desktop.mode`. Detection is deliberately based on what is
actually running, not on what is installed — having the AgentOS session
installed says nothing about whether you booted into it.
"""

from __future__ import annotations

import os
import sys

AUTO = "auto"
DE = "de"
KIOSK = "kiosk"
HOSTED = "hosted"

MODES = (DE, KIOSK, HOSTED)
CHOICES = (AUTO,) + MODES

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
IS_LINUX = not IS_MAC and not IS_WIN


def detect() -> str:
    """What we are actually running inside, right now.

    `AGENTOS_SESSION=1` is exported by the session launcher, so it is only set
    when the login screen (or autologin) started AgentOS as the session. The
    presence of `SWAYSOCK` then distinguishes the Wayland session from the older
    X11 kiosk one.
    """
    if not IS_LINUX:
        return HOSTED
    if os.environ.get("AGENTOS_SESSION") == "1":
        return DE if os.environ.get("SWAYSOCK") else KIOSK
    return _adopted_session()


def _adopted_session() -> str:
    """DE mode for a server that was NOT started by the session.

    The service is usually started by systemd at login, so it inherits neither
    AGENTOS_SESSION nor SWAYSOCK — and the AgentOS session reuses it rather than
    starting a second one. Such a server used to call itself `hosted` forever,
    which is why native windows never appeared in the shell. So: if a live
    compositor socket exists for this user AND that compositor was started as
    the AgentOS session (its own environment says so), we are in DE mode.
    """
    try:
        from . import compositor
        path = compositor.socket_path()
        if not path:
            return HOSTED
        pid = compositor.compositor_pid(path)
        if pid:
            with open(f"/proc/{pid}/environ", "rb") as fh:
                env = fh.read().split(b"\0")
            if b"AGENTOS_SESSION=1" in env:
                os.environ.setdefault("AGENTOS_SESSION", "1")
                return DE
    except Exception:
        pass
    return HOSTED


def resolve(cfg: dict | None = None) -> tuple[str, str]:
    """Return (effective_mode, detected_mode).

    A pinned mode wins over detection so the desktop can be forced either way
    for testing, but it can never promote a non-Linux machine into a session
    mode that cannot exist there.
    """
    detected = detect()
    want = ((cfg or {}).get("desktop") or {}).get("mode", AUTO)
    if want in MODES and IS_LINUX:
        return want, detected
    return detected, detected


def mode() -> str:
    """The effective mode right now, config included.

    Callers that only want to know "am I the desktop?" should use this rather
    than detect(), which ignores a pinned `desktop.mode`. The config import is
    local so this module stays importable from anywhere."""
    from . import config as cfgmod
    try:
        cfg = cfgmod.load_config()
    except Exception:
        cfg = {}
    return resolve(cfg)[0]


def describe(mode: str) -> str:
    return {
        DE: "AgentOS is your desktop session.",
        KIOSK: "AgentOS is running as a fullscreen X11 session.",
        HOSTED: "AgentOS is running as an app on your existing desktop.",
    }.get(mode, "Unknown mode.")
