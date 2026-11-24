"""Is the disk Bento's home is on encrypted? Read, never assumed.

dbcrypt.py encrypts the databases with the machine's key. Where that key is a file beside them (a
headless Pi with no keyring), a stolen disk carries both, and only full-disk encryption protects
it: the workspace, the logs and soul.md too, which dbcrypt never covers. So the faces that say
the databases are encrypted also say whether the disk is.

How it is read, and only read (no root, nothing changed):
  * Linux: the device the home is mounted from (`findmnt`), then the layers under it (`lsblk -s`).
    A `crypt` layer is LUKS / dm-crypt. A home on overlay, tmpfs, 9p or a network share (a
    container, a VM's shared folder) is `unknown`: the host decides, and this can't see it.
  * macOS: `fdesetup status` says whether FileVault is on.
  * Anything else (Windows: BitLocker needs an administrator to ask): `unknown`, said as such.
Kept free of HTTP and asyncio. The answer is kept for an hour: a disk doesn't change often.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path

TTL = 3600.0
_SEEN: dict = {}

HOW = {
    "luks": "LUKS",
    "filevault": "FileVault",
}


def _run(argv, timeout=5) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _linux(path: Path) -> dict:
    if not shutil.which("findmnt") or not shutil.which("lsblk"):
        return {"state": "unknown", "how": "", "why": "findmnt and lsblk aren't installed"}
    out = _run(["findmnt", "-no", "SOURCE,FSTYPE", "--target", str(path)]).split()
    if not out:
        return {"state": "unknown", "how": "", "why": "the mount couldn't be read"}
    source, fstype = out[0], (out[1] if len(out) > 1 else "")
    source = source.split("[", 1)[0]          # btrfs subvolumes: /dev/x[/@home]
    if not source.startswith("/dev/"):
        return {"state": "unknown", "how": "",
                "why": f"Bento's home is on {fstype or source} (a container or a shared folder), "
                       "so the host decides whether it is encrypted"}
    layers = _run(["lsblk", "-s", "-no", "TYPE", source]).split()
    if not layers:
        return {"state": "unknown", "how": "", "why": f"{source}'s layers couldn't be read"}
    if "crypt" in layers:
        return {"state": "on", "how": "luks", "why": ""}
    return {"state": "off", "how": "", "why": ""}


def _mac() -> dict:
    out = _run(["fdesetup", "status"])
    if "FileVault is On" in out:
        return {"state": "on", "how": "filevault", "why": ""}
    if "FileVault is Off" in out:
        return {"state": "off", "how": "", "why": ""}
    return {"state": "unknown", "how": "", "why": "fdesetup didn't answer"}


def state(path=None, fresh: bool = False) -> dict:
    """{state: on|off|unknown, how, why, line}: whether the disk under `path` (Bento's home by
    default) is encrypted, and the one sentence every face shows."""
    if path is None:
        from . import config as cfgmod
        path = cfgmod.AGENTOS_HOME
    path = Path(path)
    hit = _SEEN.get(str(path))
    if hit and not fresh and time.time() - hit[0] < TTL:
        return dict(hit[1])
    system = platform.system()
    if system == "Linux":
        r = _linux(path)
    elif system == "Darwin":
        r = _mac()
    else:
        r = {"state": "unknown", "how": "",
             "why": "only an administrator can ask Windows whether BitLocker is on"}
    if r["state"] == "on":
        r["line"] = f"The disk is encrypted ({HOW.get(r['how'], r['how'])}), so files outside the databases are covered too."
    elif r["state"] == "off":
        r["line"] = ("The disk isn't encrypted. Your workspace and logs are plain files, and a stolen "
                     "disk carries the database key too unless it's in a keyring. Full-disk "
                     "encryption covers all of it.")
    else:
        r["line"] = f"Bento can't tell whether the disk is encrypted: {r['why']}."
    _SEEN[str(path)] = (time.time(), dict(r))
    return r
