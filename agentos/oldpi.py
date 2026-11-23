"""32-bit Raspberry Pi OS: deprecated, and too old below Bullseye.

The owner's call, after the vulnerability scan (packaging/audit-vulns.py) found that 32-bit Pis
were held on cryptography 46.0.3 with a known advisory: "let's not support 32-bit Pi, or say it is
deprecated, and an older version, do you wish to continue".

What was measured: cryptography 50.0.2, the fixed version, ships a 32-bit ARM wheel
(manylinux_2_31_armv7l), so it installs on Raspberry Pi OS Bullseye (glibc 2.31) and Bookworm
(2.36). The old pin only ever served Buster (glibc 2.28), which is past its end of life. So:

  * 32-bit on Bullseye or newer: the current version, with the fix, and a sentence that 32-bit is
    being phased out and 64-bit is recommended.
  * 32-bit below glibc 2.31 (Buster): this version can't install. The installer says so and offers
    LAST_OLD (0.99.0, the last version that ran there, with the advisory) on a branch of its own;
    `bento update` refuses here in the same words rather than failing half-way.

One answer for install.sh's words (which repeats the rule in shell), `bento update`, Settings ->
Version and `bento doctor`. Stdlib only: the update path reads it before anything else loads.
"""
from __future__ import annotations

import platform
import struct

GLIBC_FLOOR = (2, 31)                 # cryptography 50's 32-bit ARM wheel
LAST_OLD = {"version": "0.99.0", "commit": "0eb62c88f0f859a999c762263fcac1dac3e70209",
            "branch": "buster-0.99.0"}


def facts(machine: str | None = None, bits: int | None = None, libc: tuple | None = None) -> dict:
    """{arm32, arch, glibc: (major, minor) or None}. The arguments stand in for a machine in tests.
    32-bit is the USERLAND's width: a 32-bit Pi OS on a Pi 4 boots a 64-bit kernel, so the
    kernel's `uname -m` says aarch64 while every wheel it needs is armv7."""
    arch = (machine or platform.machine() or "").lower()
    width = bits or struct.calcsize("P") * 8
    if libc is None:
        name, ver = platform.libc_ver()
        try:
            libc = tuple(int(x) for x in ver.split(".")[:2]) if name == "glibc" and ver else None
        except ValueError:
            libc = None
    arm32 = width == 32 and (arch.startswith("arm") or arch == "aarch64")
    return {"arm32": arm32, "arch": arch, "glibc": libc}


def state(**kw) -> dict:
    """{deprecated, too_old, line}. `line` is '' on any other machine."""
    f = facts(**kw)
    if not f["arm32"]:
        return {"deprecated": False, "too_old": False, "line": ""}
    g = f["glibc"]
    too_old = g is not None and tuple(g) < GLIBC_FLOOR
    if too_old:
        line = (f"This Pi's operating system is older than Raspberry Pi OS Bullseye (glibc {g[0]}.{g[1]}), so "
                "newer Bento versions can't install here: their security fix needs glibc 2.31. "
                f"{LAST_OLD['version']} is the last version that runs on it, with a known vulnerability. "
                "Move to 64-bit Raspberry Pi OS Bookworm to keep getting updates.")
    else:
        line = ("32-bit Raspberry Pi OS is deprecated. Bento runs here today, but a future version may not. "
                "64-bit Raspberry Pi OS is recommended on a Pi 3, 4, 5 or Zero 2 W.")
    return {"deprecated": True, "too_old": too_old, "line": line}
