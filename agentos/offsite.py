"""Is a copy of this machine kept anywhere else? One answer for Settings, setup and `bento doctor`.

Asked for after a reel of incidents (ransomware at seventeen hospitals in one day, a supercomputer
dark for days): a backup on the same disk is lost with the disk, and one that ransomware can reach
is encrypted with everything else. Bento already has three ways to keep a copy off the machine:

  * a cloud standby (standby.py): a second Bento that holds a sealed copy and takes over
  * a storage bucket (keep.py): the home kept sealed in an S3-compatible bucket you own
  * a backup file (backup.py): sealed with a passphrase, downloaded to wherever you put it

Nothing said whether any of them was in use, so the commonest state was none and nobody knew.
`state()` reads what each one recorded and says it in one sentence, with the doors to the others.

Three rules:

  * Measured, not assumed. A standby counts once it has received a copy, a bucket once a save
    worked, and both go to a warning when the last one is older than FRESH_S or failed.
  * A downloaded file is the weakest of the three and is said so: Bento can't see where it went.
    It counts for STALE_S, then asks for a new one.
  * It never makes anything. Making a copy is the person's act, through its own door.

Free of HTTP and asyncio, like backup.py: `bento doctor` reads it with the server down.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

FILE = ".offsite.json"          # in backup.PRIVATE: a fact about this computer, never carried
FRESH_S = 2 * 86400             # a standby or a bucket that hasn't had a copy in this long is a warning
STALE_S = 30 * 86400            # a downloaded backup older than this asks for a new one

DOORS = [
    {"id": "standby", "label": "Cloud standby", "why": "A second Bento keeps a sealed copy and takes over if this one stops."},
    {"id": "cloud", "label": "Put Bento in the cloud", "why": "Your memory is kept sealed in a storage bucket you own."},
    {"id": "backup", "label": "Download a backup", "why": "One sealed file. Keep it on another disk."},
]


def _home(home=None) -> Path:
    if home:
        return Path(home)
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME)


def note_made(size: int = 0, where: str = "download", home=None) -> None:
    """A backup of this machine was just made (the route and `bento backup` call this)."""
    p = _home(home) / FILE
    try:
        p.write_text(json.dumps({"made_at": time.time(), "size": int(size or 0), "where": str(where)[:200]}))
        p.chmod(0o600)
    except OSError:
        pass


def _made(home=None) -> dict:
    try:
        return json.loads((_home(home) / FILE).read_text())
    except (OSError, ValueError):
        return {}


def _ago(s: float) -> str:
    s = max(0, s)
    if s < 3600:
        return f"{max(1, round(s / 60))} min ago"
    if s < 86400 * 2:
        return f"{round(s / 3600)} hours ago"
    return f"{round(s / 86400)} days ago"


def state(home=None, cfg: dict | None = None, now: float | None = None) -> dict:
    """{kind, level ok|warn|bad, line, at, doors}. kind: standby, bucket, hub, copy (this IS the
    standby), file, none."""
    now = now or time.time()
    out = {"kind": "none", "level": "bad", "at": 0, "doors": DOORS,
           "line": "Nothing of this machine is kept anywhere else. If this disk fails, or ransomware "
                   "locks it, everything here is lost."}
    try:
        from . import zeromind
        if cfg is not None and zeromind.on_hub(cfg):
            return {**out, "kind": "hub", "level": "ok", "doors": [],
                    "line": "This machine's memory is kept on its hub, so its hub's copies cover it."}
    except Exception:
        pass
    try:
        from . import standby
        st = standby.status(home)
    except Exception:
        st = {}
    if st.get("role") == "standby":
        return {**out, "kind": "copy", "level": "ok", "doors": [],
                "line": f"This machine is the standby: it holds the copy of {st.get('peer_host') or 'the main machine'}."}
    if st.get("role") == "primary":
        at = float(st.get("last_push") or st.get("sync_at") or 0)
        host = st.get("peer_host") or "the standby"
        if at and now - at < FRESH_S and not st.get("last_error"):
            return {**out, "kind": "standby", "level": "ok", "at": at,
                    "line": f"A sealed copy is kept on {host}, the cloud standby. The last one went {_ago(now - at)}."}
        why = st.get("last_error") or ("it hasn't had a copy yet" if not at else f"the last copy went {_ago(now - at)}")
        return {**out, "kind": "standby", "level": "warn", "at": at,
                "line": f"{host} is paired as the standby, but {why}."}
    try:
        from . import keep
        ks = keep.status(home)
    except Exception:
        ks = {}
    if ks.get("enabled"):
        at = float(ks.get("saved_at") or 0)
        if at and not ks.get("kind") == "err" and now - at < FRESH_S:
            return {**out, "kind": "bucket", "level": "ok", "at": at, "line": ks.get("line") or "Kept in your bucket."}
        return {**out, "kind": "bucket", "level": "warn", "at": at,
                "line": ks.get("line") or "Your bucket is set, but nothing has been saved to it yet."}
    made = _made(home)
    at = float(made.get("made_at") or 0)
    if at:
        old = now - at > STALE_S
        return {**out, "kind": "file", "level": "warn", "at": at,
                "line": (f"The last backup was made {_ago(now - at)}. " if old else f"A backup was made {_ago(now - at)}. ")
                        + ("Make a new one, or keep a copy that updates itself. " if old else
                           "Keep it on another disk. ")
                        + "Bento can't see where the file went."}
    return out


def done(home=None, cfg: dict | None = None, now: float | None = None) -> tuple[bool, str]:
    """For setup: a copy exists somewhere else (a fresh file counts), and its words."""
    s = state(home, cfg, now)
    if s["kind"] in ("standby", "bucket", "hub", "copy"):
        return True, {"standby": "cloud standby", "bucket": "storage bucket", "hub": "on its hub",
                      "copy": "this is the standby"}[s["kind"]]
    if s["kind"] == "file" and (now or time.time()) - s["at"] <= STALE_S:
        return True, "a backup file"
    return False, ""
