"""Light mode: what a machine with 1 GB of RAM and an SD card must not pay for.

AgentOS is meant to run on a Raspberry Pi, and the measurements that came out of
the footprint pass said the same thing three times: the costs that hurt a small
machine are the ones paid for features nobody is using. The biggest of them is
the MCP catalogue — 21,811 servers, 11.9 MB on disk, +35 MB of RSS parsed — kept
so that a search is instant.

On a laptop that is a good trade. On a Pi it is a third of the memory and a
permanent file on a card with a write budget, for an app somebody opens twice a
year. So there is a profile:

    full   keep the catalogue, refresh it daily, release the memory when idle
    lite   fetch it when you search, answer from it while you are searching,
           and DELETE it — memory and file — when you stop

`auto` decides from the machine and then writes down what it decided, because a
profile that is inferred silently is a machine behaving differently from another
one for reasons nobody can see. Everything it changes is an ordinary config key
afterwards: the profile is an act that writes settings, not an invisible overlay
that argues with them.

Kept free of HTTP and asyncio so `bento profile`, the doctor, the installer and
the Settings panel all read the same answer.
"""

from __future__ import annotations

import os
import platform

PROFILES = ("auto", "full", "lite")

#: Below this much RAM, `auto` picks lite. A Pi 3 / Zero 2 W (0.5–1 GB) and a
#: 2 GB Pi 4 land in lite; a 4 GB board does not. Stated rather than tuned: the
#: point is a rule somebody can predict, not a benchmark.
LITE_RAM_MB = 2048

#: What each profile changes. Retention numbers are WRITTEN into config when a
#: profile is applied, so they stay visible and editable; the behaviour flags are
#: read live, because they are behaviour and not a number to tune.
EFFECTS = {
    "full": {
        "mcp_cache": "keep",        # catalogue stays on disk, refreshed daily
        "mcp_idle_release": 900.0,  # memory let go after 15 idle minutes
        "retention": {"enabled": True, "logs_days": 30, "events_days": 30,
                      "usage_days": 365},
    },
    "lite": {
        "mcp_cache": "discard",     # deleted — memory AND file — once you stop searching
        "mcp_idle_release": 300.0,
        "retention": {"enabled": True, "logs_days": 7, "events_days": 7,
                      "usage_days": 90},
    },
}


def machine() -> dict:
    """What this box actually is. Never raises — a missing /proc is not an error."""
    ram = 0
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    ram = int(line.split()[1]) // 1024
                    break
    except OSError:
        try:                                   # macOS and friends
            ram = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) // 1_048_576
        except (ValueError, OSError, AttributeError):
            ram = 0
    board = ""
    try:                                       # the Pi says so itself
        board = open("/proc/device-tree/model").read().strip("\x00").strip()
    except OSError:
        pass
    return {"ram_mb": ram, "cores": os.cpu_count() or 1,
            "arch": platform.machine(), "board": board}


def resolve(cfg: dict) -> str:
    """The profile in force: 'full' or 'lite'. `auto` is decided from the machine."""
    want = str((cfg or {}).get("profile") or "auto")
    if want in ("full", "lite"):
        return want
    m = machine()
    return "lite" if 0 < m["ram_mb"] <= LITE_RAM_MB else "full"


def settings(cfg: dict) -> dict:
    """The behaviour flags for the profile in force."""
    return EFFECTS[resolve(cfg)]


def apply(cfg: dict, want: str) -> tuple[bool, str]:
    """Write a profile's settings into config. Mutates `cfg`; the caller saves.

    The numbers land in config as ordinary keys, so `bento config` and the
    Settings panel can still argue with them afterwards — which is the point. A
    profile that could only be read would be a second, invisible configuration.
    """
    want = str(want or "").strip().lower()
    if want not in PROFILES:
        return False, f"a profile is one of {', '.join(PROFILES)}"
    cfg["profile"] = want
    eff = EFFECTS[resolve(cfg)]
    cfg.setdefault("retention", {}).update(eff["retention"])
    return True, describe(cfg)


def describe(cfg: dict) -> str:
    """One sentence, for the doctor, the CLI and the Settings panel."""
    p = resolve(cfg)
    m = machine()
    where = f"{m['ram_mb']} MB RAM, {m['cores']} core{'' if m['cores'] == 1 else 's'}"
    if m["board"]:
        where += f", {m['board']}"
    how = "chosen" if (cfg or {}).get("profile") in ("full", "lite") else f"auto from {where}"
    r = EFFECTS[p]["retention"]
    if p == "lite":
        what = ("the MCP catalogue is fetched when you search and deleted when you stop "
                f"(nothing kept on disk), telemetry kept {r['logs_days']} days")
    else:
        what = ("the MCP catalogue is kept on disk and refreshed daily, telemetry kept "
                f"{r['logs_days']} days")
    return f"{p} ({how}) — {what}"
