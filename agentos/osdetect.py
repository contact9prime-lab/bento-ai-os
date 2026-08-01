"""What machine is this, and how does software get installed on it?

WHY THIS EXISTS
===============
Until now AgentOS assumed apt. Not as a fallback — as the only possibility.
`components.py` built every install command with `apt-get install -y`, the
catalogue held Debian package names (`gir1.2-gtklayershell-0.1`) with no other
spelling, and `install.sh` skipped its entire session-dependency step behind
`command -v apt-get`. The result on Fedora or Arch was not an error. It was
worse than an error: Settings → Components cheerfully printed a command that
does not exist on the machine, and the one-command installer silently offered
nothing at all, so the user was told everything was fine and got a desktop that
could not draw itself.

An honest system has to be able to say three different things:

    "here is the command for YOUR machine"      — family is known, pm is present
    "this piece has no package on YOUR distro"  — family known, no mapping
    "AgentOS cannot be a session on this OS"    — macOS, Windows

This module answers the question everything else branches on, once, and is the
only place a distro name is turned into a package manager.

WHAT IT DELIBERATELY DOES NOT DO
================================
It does not branch on operating system for *capabilities* — CLAUDE.md is clear
that `/api/platform` is how the UI discovers what it can do, and that branching
belongs on the capability, not the OS name. This module answers a narrower
question: which package manager installs things here, and what are the packages
called. Those genuinely are per-distro facts and nothing else can derive them.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

OS_RELEASE = Path("/etc/os-release")

#: distro id (or an entry in ID_LIKE) → the family whose package names apply.
#: ID_LIKE is what makes this short: Mint/Pop/Zorin/Raspbian all say
#: `ID_LIKE=debian`, so they need no entry of their own and a distro released
#: next year works without a code change.
FAMILY_BY_ID = {
    "debian": "debian", "ubuntu": "debian", "raspbian": "debian", "devuan": "debian",
    "linuxmint": "debian", "pop": "debian", "elementary": "debian", "zorin": "debian",
    "kali": "debian", "neon": "debian",
    "fedora": "rhel", "rhel": "rhel", "centos": "rhel", "rocky": "rhel",
    "almalinux": "rhel", "ol": "rhel", "nobara": "rhel",
    "arch": "arch", "manjaro": "arch", "endeavouros": "arch", "garuda": "arch",
    "cachyos": "arch", "artix": "arch",
    "opensuse": "suse", "opensuse-leap": "suse", "opensuse-tumbleweed": "suse",
    "sles": "suse", "suse": "suse", "sled": "suse",
    "alpine": "alpine",
}

#: family → (package manager binary we require on PATH, human name)
PM_BY_FAMILY = {
    "debian": "apt-get",
    "rhel": "dnf",
    "arch": "pacman",
    "suse": "zypper",
    "alpine": "apk",
}

#: family → argv template for a non-interactive install of one or more packages.
#: Kept as a list so nothing is ever built by string concatenation and no shell
#: is involved; `packages` is appended as separate argv entries.
INSTALL_ARGV = {
    "debian": ["apt-get", "install", "-y"],
    "rhel": ["dnf", "install", "-y"],
    "arch": ["pacman", "-S", "--noconfirm", "--needed"],
    "suse": ["zypper", "--non-interactive", "install"],
    "alpine": ["apk", "add"],
}

#: family → argv that refreshes the package index, or [] where installing
#: already does it. On Debian, installing without an update is the single most
#: common "package not found" on a machine that has been off for a while.
REFRESH_ARGV = {
    "debian": ["apt-get", "update"],
    "suse": ["zypper", "--non-interactive", "refresh"],
    "alpine": ["apk", "update"],
    "rhel": [],      # dnf refreshes per its own metadata policy
    "arch": [],      # -Sy inside the install would be a partial upgrade: don't
}

_CACHE: list = []


def _read_os_release() -> dict:
    """Parse /etc/os-release into a plain dict. Never raises."""
    data: dict[str, str] = {}
    for path in (OS_RELEASE, Path("/usr/lib/os-release")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            data[k.strip()] = v
        if data:
            break
    return data


def _family(rel: dict) -> str:
    """ID first, then each ID_LIKE token. Unknown is '' — never a guess."""
    ident = (rel.get("ID") or "").strip().lower()
    if ident in FAMILY_BY_ID:
        return FAMILY_BY_ID[ident]
    for token in (rel.get("ID_LIKE") or "").lower().split():
        if token in FAMILY_BY_ID:
            return FAMILY_BY_ID[token]
    return ""


def detect(refresh: bool = False) -> dict:
    """Everything the installer and the component catalogue need, memoised.

    Memoised for the same reason `shellhost.python_with_gi` is: /api/components
    is called on every settings page load, and this reads files and stats the
    filesystem. The answer only changes when someone installs a package
    manager, which is not a thing that happens while the page is open.
    """
    if _CACHE and not refresh:
        return _CACHE[0]

    system = platform.system()
    info = {
        "os": {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(system, system.lower()),
        "id": "", "id_like": [], "version_id": "", "pretty": "", "family": "",
        "manager": "", "install_argv": [], "refresh_argv": [],
        "session_capable": False, "why": "",
    }

    if info["os"] == "macos":
        info["pretty"] = f"macOS {platform.mac_ver()[0]}".strip()
        info["family"] = "macos"
        info["manager"] = "brew" if shutil.which("brew") else ""
        info["why"] = ("The AgentOS login session is a Wayland session and exists only on "
                       "Linux. AgentOS itself runs here as an app window.")
        _CACHE[:] = [info]
        return info

    if info["os"] == "windows":
        info["pretty"] = f"Windows {platform.release()}".strip()
        info["family"] = "windows"
        info["manager"] = "winget" if shutil.which("winget") else ""
        info["why"] = ("The AgentOS login session is a Wayland session and exists only on "
                       "Linux. AgentOS itself runs here as an app window.")
        _CACHE[:] = [info]
        return info

    rel = _read_os_release()
    info["id"] = (rel.get("ID") or "").lower()
    info["id_like"] = (rel.get("ID_LIKE") or "").lower().split()
    info["version_id"] = rel.get("VERSION_ID") or ""
    info["pretty"] = rel.get("PRETTY_NAME") or rel.get("NAME") or "Linux"
    info["family"] = _family(rel)

    if not info["family"]:
        info["why"] = (f"AgentOS does not know how {info['pretty']} installs packages, so it "
                       f"will not guess at a command. Install the listed packages with your "
                       f"own package manager and everything else works normally.")
    else:
        binary = PM_BY_FAMILY.get(info["family"], "")
        if binary and shutil.which(binary):
            info["manager"] = {"apt-get": "apt"}.get(binary, binary)
            info["install_argv"] = list(INSTALL_ARGV.get(info["family"], []))
            info["refresh_argv"] = list(REFRESH_ARGV.get(info["family"], []))
        else:
            # The family is recognised but its package manager is not here. This
            # is a real configuration (a container, a stripped image), and
            # claiming apt exists because the distro is Debian would produce a
            # command that fails at the worst moment.
            info["why"] = (f"{info['pretty']} is a {info['family']}-family system but "
                           f"'{binary}' is not on PATH, so AgentOS cannot install packages "
                           f"for you here.")

    info["session_capable"] = info["os"] == "linux"
    _CACHE[:] = [info]
    return info


def family(refresh: bool = False) -> str:
    return detect(refresh)["family"]


def manager(refresh: bool = False) -> str:
    """The package manager's human name ('apt', 'dnf', …), or '' if unusable."""
    return detect(refresh)["manager"]


def can_install(refresh: bool = False) -> bool:
    return bool(detect(refresh)["install_argv"])


def install_argv(packages: str | list[str], refresh: bool = False) -> list[str]:
    """Full argv to install `packages` here, or [] when we cannot say.

    Returns argv rather than a string so callers never build a shell command by
    concatenation — the privilege ladder in components.py execs this directly.
    """
    base = detect(refresh)["install_argv"]
    if not base:
        return []
    names = packages.split() if isinstance(packages, str) else list(packages)
    return base + [n for n in names if n]


def describe() -> str:
    """One line for the installer header and `agentos doctor`."""
    d = detect()
    if d["os"] != "linux":
        return f"{d['pretty']} — the login session is Linux-only"
    fam = d["family"] or "unknown family"
    pm = d["manager"] or "no usable package manager"
    return f"{d['pretty']} ({fam}) · {pm}"


def is_wayland_session() -> bool:
    """Are we inside a Wayland session right now? (Not 'could we be'.)"""
    return bool(os.environ.get("WAYLAND_DISPLAY")) or \
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
