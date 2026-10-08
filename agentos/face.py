"""How this machine's own screen looks: one agent (buddy) and the kiosk face.

Asked for as "a single buddy / agent ui interface option for Light mode so that shows
just one agent in the office and desktop face for raspi interface, there will be a kiosk
mode as well where mic would be on and agents would be working in the office".

  * BUDDY: the Office and the desktop's Crew stage draw only your lead agent. Specialists
    still exist and still work; their work lights the lead's desk, because on a 7-inch
    screen a room of eight figures is a wall of names. `auto` follows Light mode
    (profile.resolve == "lite"), so a Pi gets it without being told.
  * KIOSK: the machine's own screen becomes the Office, full screen, with the mic
    listening for the agent's name (or for everything) and the answer spoken. It is a
    FACE, not a run mode: `runmode.KIOSK` is how the session is launched (an X11 app
    window), this is what that window shows. A phone looking at the same machine never
    gets the kiosk face; only the screen attached to it does, or a browser opened with
    `#kiosk`.

Both are the MACHINE's (a screen belongs to the box it is plugged into), so neither is a
USER_KEY. Kept free of HTTP and asyncio: `bento face` reads and writes the same settings
with the server down.
"""
from __future__ import annotations

BUDDY = ("auto", "on", "off")
WAKE = ("name", "always")


def _face(cfg: dict) -> dict:
    f = (cfg or {}).get("face")
    return f if isinstance(f, dict) else {}


def buddy_setting(cfg: dict) -> str:
    v = str(_face(cfg).get("buddy") or "auto").lower()
    return v if v in BUDDY else "auto"


def buddy(cfg: dict) -> bool:
    """Is only the lead drawn? `auto` means: in Light mode."""
    v = buddy_setting(cfg)
    if v != "auto":
        return v == "on"
    from . import profile
    return profile.resolve(cfg) == "lite"


def kiosk(cfg: dict) -> bool:
    return bool(_face(cfg).get("kiosk"))


def wake(cfg: dict) -> str:
    v = str(_face(cfg).get("wake") or "name").lower()
    return v if v in WAKE else "name"


def state(cfg: dict) -> dict:
    """What the page and the CLI read: one answer for both."""
    from . import hearing
    return {"buddy": buddy(cfg), "buddy_setting": buddy_setting(cfg),
            "kiosk": kiosk(cfg), "wake": wake(cfg),
            "hear": hearing.status(cfg)}


def set_face(cfg: dict, buddy: str | None = None, kiosk: bool | None = None,
             wake: str | None = None) -> tuple[bool, str]:
    """Change the face. Mutates `cfg`; the caller saves. Refuses an unknown value by
    naming the choices, so a typo is a sentence and not a silently ignored setting."""
    f = dict(_face(cfg))
    if buddy is not None:
        b = str(buddy).strip().lower()
        if b not in BUDDY:
            return False, f"one agent on screen is one of {', '.join(BUDDY)}"
        f["buddy"] = b
    if kiosk is not None:
        f["kiosk"] = bool(kiosk)
    if wake is not None:
        w = str(wake).strip().lower()
        if w not in WAKE:
            return False, f"the kiosk listens for one of {', '.join(WAKE)}"
        f["wake"] = w
    cfg["face"] = f
    return True, describe(cfg)


def describe(cfg: dict) -> str:
    """One sentence per setting, for the CLI and the doctor."""
    s = buddy_setting(cfg)
    one = ("Only your agent is drawn in the Office and on the desktop"
           if buddy(cfg) else "Every agent is drawn in the Office and on the desktop")
    why = " (Light mode)" if s == "auto" and buddy(cfg) else ""
    kio = ("The kiosk face is on: this machine's screen shows the Office and listens "
           + ("for everything." if wake(cfg) == "always" else "for your agent's name.")
           if kiosk(cfg) else "The kiosk face is off.")
    return f"{one}{why}. {kio}"


def record(store, detail: str) -> None:
    """A person's change to the screen is a ledger row, like every change to the machine."""
    try:
        from . import users as _users
        uid = _users.current() or ""
    except Exception:
        uid = ""
    try:
        store.audit_add(uid=uid, principal_kind="user", principal_id="", action="face.write",
                        resource="face:screen", effect="allow", rule="person", outcome="ok",
                        detail=str(detail)[:1000])
    except Exception:
        pass
