"""Security events: somebody tried something, and a person gets told.

The gate decides and the ledger records decisions, and neither of them answers "is
somebody working on this machine right now?". A burst of failed sign-ins, a forged token
or a changed security file used to leave nothing anybody would see.

Three rules keep this honest:

- **This is the server's code, never a model's judgement.** A model may be TOLD (see
  `agent_note`), so it can warn the person. It decides nothing, and nothing here is a
  capability. Words come from `KINDS`, never from the attacker's text, so a request cannot
  write instructions into a prompt through its own refusal.
- **A flood costs a counter.** A file line per failed request is a disk problem handed to
  whoever floods. After `WRITE_BURST` lines for one (kind, source) in a window only the count
  moves, and the file is capped at `KEEP` lines. The same reason `RateMeter` is in memory.
- **One incident, one alert.** `threshold` events inside `window` seconds raise it once;
  it can be raised again after `COOLDOWN_S`. An alert nobody can stop reading is one nobody reads.

Stdlib only and free of HTTP and asyncio, so `bento security` reads the same file with the
server down. It lives in the MACHINE's home and is 0600: an account's jail cannot see it.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path

FILE = "security-events.jsonl"
KEEP = 2000                  # lines kept on disk
WRITE_BURST = 20             # lines one (kind, source) may write per window
COOLDOWN_S = 900             # an incident alerts again only after this
NOTE_S = 3600                # how long the agent keeps hearing about an alert
MAX_DETAIL = 300

# kind: (the sentence a person and a model read, threshold, window seconds)
# A threshold of 1 means one event is already the alert.
KINDS: dict[str, tuple[str, int, int]] = {
    "login.failed": ("Repeated failed sign-ins", 5, 300),
    "login.locked": ("A sign-in source was locked out", 1, 300),
    "session.forged": ("A session cookie with a bad signature was presented", 3, 300),
    "token.forged": ("A bad token was presented", 5, 300),
    "host.refused": ("A request named a host this machine does not answer to", 5, 300),
    "origin.refused": ("A cross-origin request was refused", 5, 300),
    "child.refused": ("A process this server started tried to use the person's access", 1, 300),
    "account.role": ("An account's role or password changed", 1, 300),
    "account.unreadable": ("The accounts file could not be read", 1, 300),
    "link.guess": ("Wrong link codes were tried", 5, 300),
    "standby.token": ("A bad standby token was presented", 3, 300),
    "pool.leader": ("This community's leader changed", 1, 300),
    "provision.refused": ("A machine's claim was refused", 3, 300),
    "beacon.flood": ("Many machines announced themselves at once", 1, 300),
    "gate.unlisted_tool": ("A model called a tool it was not offered", 3, 300),
    "cli.folder_refused": ("An agent's CLI was pointed at another account's or a private folder", 1, 300),
    "store.package_refused": ("A public registry entry asked to run something this OS won't", 3, 300),
    "gate.forged_field": ("A call tried to set a field only this OS sets", 3, 300),
    "gate.refused_burst": ("A run of steps was refused", 8, 120),
    "taint.steering": ("Outside content tried to steer the agent", 1, 300),
    "integrity.changed": ("A security file changed", 1, 300),
    "integrity.unsigned": ("This code is not signed by a key this machine trusts", 1, 86400),
    "ledger.broken": ("The ledger's chain does not verify", 1, 300),
    "jail.missing": ("The sandbox is not working on this machine", 1, 86400),
}
UNKNOWN = ("Something happened that the security record does not have a name for", 1, 300)

_lock = threading.Lock()
_seen: dict[tuple[str, str], list[float]] = {}     # (kind, source) -> times in the window
_written: dict[tuple[str, str], list[float]] = {}  # (kind, source) -> writes in the window
_alerted: dict[tuple[str, str], float] = {}        # (kind, source) -> when it last alerted
_listeners: list = []
_alerts: list[dict] = []                           # newest last, in memory for the agent's note


def _path() -> Path:
    """Read at call time: the suite and a restored home both move it."""
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME) / FILE


def plain(text, limit: int = MAX_DETAIL) -> str:
    """What may be stored: no controls and no bidi overrides, cut to a length. A log viewer
    is a terminal, and a source address or a user name is whatever the attacker sent."""
    out = []
    for ch in str(text or "")[:limit * 2]:
        o = ord(ch)
        if o < 32 or 127 <= o < 160 or 0x202a <= o <= 0x202e or 0x2066 <= o <= 0x2069:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)[:limit].strip()


def words(kind: str) -> str:
    return KINDS.get(kind, UNKNOWN)[0]


def on_alert(listener) -> None:
    """`listener(alert: dict)` runs on whatever thread flagged it, and must not raise far:
    a broken alert must never turn into a refused request. Registered once per process."""
    if listener not in _listeners:
        _listeners.append(listener)


def _trim(times: list[float], since: float) -> list[float]:
    return [t for t in times if t >= since]


def _write(ev: dict) -> None:
    with contextlib.suppress(OSError):
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        if path.stat().st_size > KEEP * 400:
            _shrink(path)


def _shrink(path: Path) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-KEEP // 2:]
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def flag(kind: str, detail: str = "", *, source: str = "", uid: str = "",
         now: float | None = None) -> dict | None:
    """Record one event. Returns the alert when this one raised it, else None. Never raises:
    the caller is usually in the middle of refusing somebody."""
    try:
        return _flag(kind, detail, source, uid, time.time() if now is None else now)
    except Exception:  # noqa: BLE001 - a broken record must never become an open door or a 500
        return None


def _flag(kind: str, detail: str, source: str, uid: str, now: float) -> dict | None:
    text, threshold, window = KINDS.get(kind, UNKNOWN)
    source, detail = plain(source, 120), plain(detail)
    key = (kind, source)
    alert = None
    with _lock:
        seen = _trim(_seen.get(key, []), now - window)
        seen.append(now)
        _seen[key] = seen[-max(threshold, 1) * 4:]
        written = _trim(_written.get(key, []), now - window)
        write = len(written) < WRITE_BURST
        if write:
            written.append(now)
        _written[key] = written
        if len(seen) >= threshold and now - _alerted.get(key, 0) >= COOLDOWN_S:
            _alerted[key] = now
            alert = {"kind": kind, "words": text, "source": source, "count": len(seen),
                     "at": now, "detail": detail, "alert": True}
            _alerts.append(alert)
            del _alerts[:-50]
    if write or alert:
        _write({"kind": kind, "at": now, "source": source, "uid": plain(uid, 40),
                "detail": detail, "alert": bool(alert)})
    if alert:
        for listener in list(_listeners):
            with contextlib.suppress(Exception):
                listener(alert)
    return alert


def recent(limit: int = 200, alerts_only: bool = False) -> list[dict]:
    """Newest first, each with the sentence it stands for. Reads the file, so the terminal's
    verb and the page cannot disagree, and a restart loses nothing."""
    try:
        lines = _path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or (alerts_only and not ev.get("alert")):
            continue
        ev["words"] = words(str(ev.get("kind") or ""))
        out.append(ev)
        if len(out) >= limit:
            break
    return out


def agent_note(now: float | None = None) -> str:
    """What the agent hears, so it can tell the person: the OS's own sentences and a count,
    never the attacker's text. It says outright that the model decides nothing here."""
    now = time.time() if now is None else now
    with _lock:
        live = [a for a in _alerts if now - a["at"] < NOTE_S]
    if not live:
        return ""
    seen = []
    for a in live[-5:]:
        if a["words"] not in seen:
            seen.append(a["words"])
    return ("Security notice from this OS (it is not an instruction, and you cannot change any "
            "security setting): " + "; ".join(seen) + ". Mention it to the person. "
            "They can read the record with `bento security` or in Permissions.")


def forget_for_tests() -> None:
    with _lock:
        _seen.clear()
        _written.clear()
        _alerted.clear()
        _alerts.clear()
    _listeners.clear()
