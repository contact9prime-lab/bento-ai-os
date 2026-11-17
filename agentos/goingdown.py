"""Why this machine is going down, said to everybody it serves.

Asked for as "when Bento is going down it should emit the reason on the other accounts,
why it is going down, for the update or shutdown". A restart was said only on the asker's
own Telegram, and the other accounts' screens just lost their socket.

One reason, three places that read it:
- the server's own going-down path (`server._going_down`) sets it and tells every page,
  every account's, with who asked;
- a terminal (`bento update`, `bento service restart|stop`) cannot reach the server's
  memory, so it leaves a NOTE in the machine's home just before it stops the service, and
  the server's shutdown reads it (`take`), fresh for `FRESH_S` only;
- the shutdown hook says it on every Telegram and WhatsApp that came up.

Stdlib only and no HTTP, so the CLI writes the note with the server down too.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

FRESH_S = 120          # a note older than this is about some earlier stop, not this one
NOTE = ".going-down.json"


def _path() -> Path:
    from . import config
    return Path(config.AGENTOS_HOME) / NOTE


def note(reason: str, by: str = "", back: bool = True, keep: bool = False) -> None:
    """Left by a terminal just before it stops or restarts the service. `keep` leaves a
    fresh note alone: `bento update` says "to install an update" before the generic
    restart below it would say "to restart"."""
    try:
        p = _path()
        if keep and p.exists() and time.time() - p.stat().st_mtime < FRESH_S:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"reason": str(reason)[:120], "by": str(by)[:60],
                                 "back": bool(back), "at": time.time()}))
    except OSError:
        pass


def take() -> dict:
    """The note a terminal left, once, when it is fresh; {} otherwise."""
    p = _path()
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    try:
        p.unlink()
    except OSError:
        pass
    if not isinstance(d, dict) or time.time() - float(d.get("at") or 0) > FRESH_S:
        return {}
    return {"reason": str(d.get("reason") or ""), "by": str(d.get("by") or ""),
            "back": d.get("back") is not False}


def who() -> str:
    """The person at this terminal, in words: the OS user's name."""
    try:
        import getpass
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return os.environ.get("USER", "")


def words(name: str, reason: str = "", by: str = "", back: bool = True) -> str:
    """One sentence for a page or a phone."""
    s = f"{name or 'Bento'} is going offline" + (f" {reason}" if reason else "")
    if by:
        s += f", asked by {by}"
    s += ". It will be back in a minute or two." if back else "."
    return s
