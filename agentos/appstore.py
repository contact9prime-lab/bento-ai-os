"""Installing native applications — the part of "being a desktop" that was missing.

AgentOS could already LIST the applications on the machine (`.desktop` entries)
and launch them through the compositor. It could not get you a new one. On a
Raspberry Pi or a fresh Ubuntu that is the difference between a desktop and a
demo: the first thing anyone does with a new machine is install something.

So this is a thin, honest front end onto the package manager the machine already
has. It does not invent a repository, mirror anything, or bundle software:

    appstreamcli   the distribution's own application catalogue — real
                   applications with names, summaries and categories, which is
                   what an app store should show rather than every library that
                   happens to match a word. Used for SEARCH when present.
    flatpak        installs per-user, so it needs no root at all. Preferred for
                   INSTALLING when the app is there.
    apt / dnf      the system package manager. Needs root, and gets it through
                   the same ladder as optional components: passwordless sudo,
                   then a polkit prompt, then handing you the exact command.

Nothing is installed without an explicit request naming that package, and the
command that will run is always returned so nothing changes invisibly. AgentOS
ships none of this software and redistributes none of it — it asks the machine's
own package manager, with the user's consent, exactly as a person would.
"""

from __future__ import annotations

import asyncio
import re
import shutil

TIMEOUT_SEARCH = 25.0
TIMEOUT_INSTALL = 900.0     # a large desktop app on a slow Pi SD card


async def _run(argv: list[str], timeout: float, stdin: bytes | None = None) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found"
    except Exception as e:                                    # noqa: BLE001
        return 1, str(e)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "timed out"
    return proc.returncode or 0, (out or b"").decode(errors="replace")


def backends() -> dict:
    """What this machine can actually install with."""
    apt = bool(shutil.which("apt-get"))
    return {
        "appstream": bool(shutil.which("appstreamcli")),
        "flatpak": bool(shutil.which("flatpak")),
        "apt": apt,
        "dnf": bool(shutil.which("dnf")),
        "pacman": bool(shutil.which("pacman")),
        # Per-user flatpak needs no authentication at all; everything else does.
        "needs_root": not bool(shutil.which("flatpak")) or apt,
    }


def available() -> bool:
    b = backends()
    return any(b[k] for k in ("flatpak", "apt", "dnf", "pacman"))


# =============================================================================
# search
# =============================================================================

#: apt sections that contain things a person would call an application. Searching
#: apt without this returns every -dev package and shared library that mentions
#: the word, which is not a store.
_APP_SECTIONS = ("editors", "gnome", "graphics", "kde", "mail", "math", "net",
                 "news", "science", "sound", "text", "video", "web", "x11",
                 "utils", "games", "education", "office")


def _appstream_parse(text: str) -> list[dict]:
    """appstreamcli's human output, one component per stanza.

    It has a --format=yaml but not everywhere, and no JSON on Ubuntu 22.04, so
    the stable interface really is the indented "Key: value" listing.
    """
    apps, cur = [], {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")) and line.endswith(":"):
            if cur.get("id"):
                apps.append(cur)
            cur = {"id": line[:-1].strip()}
            continue
        m = re.match(r"\s*([A-Za-z ]+):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1).strip().lower(), m.group(2).strip()
        if key in ("name", "summary", "package", "bundle"):
            cur[key] = val
    if cur.get("id"):
        apps.append(cur)
    return apps


async def search(query: str, limit: int = 40) -> dict:
    """Applications matching `query`, best source first.

    Deliberately returns a flat list with an explicit `backend` on each row: the
    UI shows where a thing comes from, because "install Firefox" from apt and
    from flatpak are different decisions with different update paths.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return {"results": [], "backends": backends(),
                "message": "type at least two characters"}
    b = backends()
    if not available():
        return {"results": [], "backends": b,
                "message": "no package manager found on this machine"}

    rows: list[dict] = []
    have = await installed_ids()

    # 1) the distribution's application catalogue: real apps, with summaries.
    if b["appstream"]:
        rc, out = await _run(["appstreamcli", "search", q], TIMEOUT_SEARCH)
        if rc == 0:
            for c in _appstream_parse(out):
                pkg = c.get("package") or ""
                if not pkg:
                    continue
                rows.append({"id": pkg, "name": c.get("name") or pkg,
                             "summary": c.get("summary") or "",
                             "backend": "apt" if b["apt"] else "dnf",
                             "installed": pkg in have, "source": "appstream"})

    # 2) flatpak, which can install without root.
    if b["flatpak"]:
        rc, out = await _run(
            ["flatpak", "search", "--columns=application,name,description", q],
            TIMEOUT_SEARCH)
        if rc == 0 and "No matches" not in out:
            for line in out.splitlines():
                parts = [p.strip() for p in line.split("\t")]
                if len(parts) < 2 or not parts[0] or "." not in parts[0]:
                    continue
                rows.append({"id": parts[0], "name": parts[1] or parts[0],
                             "summary": parts[2] if len(parts) > 2 else "",
                             "backend": "flatpak", "installed": parts[0] in have,
                             "source": "flathub"})

    # 3) plain package search — the fallback, filtered to app-ish sections so it
    #    is a list of programs rather than a list of libraries.
    if not rows and b["apt"]:
        rc, out = await _run(["apt-cache", "search", "--names-only", q], TIMEOUT_SEARCH)
        if rc == 0:
            for line in out.splitlines()[:200]:
                name, _, summary = line.partition(" - ")
                name = name.strip()
                if not name or name.endswith(("-dev", "-doc", "-dbg", "-common")):
                    continue
                rows.append({"id": name, "name": name, "summary": summary.strip(),
                             "backend": "apt", "installed": name in have,
                             "source": "apt"})

    # Prefer flatpak when both offer the same app: it installs per-user, needs no
    # password, and cannot break the system's own packages.
    seen: dict[str, dict] = {}
    for r in rows:
        key = re.sub(r"[^a-z0-9]", "", r["name"].lower())
        old = seen.get(key)
        if old is None or (r["backend"] == "flatpak" and old["backend"] != "flatpak"):
            seen[key] = r
    out_rows = sorted(seen.values(),
                      key=lambda r: (not r["installed"], r["source"] != "appstream",
                                     r["name"].lower()))[:limit]
    return {"results": out_rows, "backends": b, "message": ""}


async def installed_ids() -> set[str]:
    """Package/app ids already present, so the store never offers to re-install."""
    ids: set[str] = set()
    b = backends()
    if b["flatpak"]:
        rc, out = await _run(["flatpak", "list", "--columns=application"], TIMEOUT_SEARCH)
        if rc == 0:
            ids |= {l.strip() for l in out.splitlines() if l.strip()}
    if b["apt"]:
        rc, out = await _run(["dpkg-query", "-f", "${Package}\\n", "-W"], TIMEOUT_SEARCH)
        if rc == 0:
            ids |= {l.strip() for l in out.splitlines() if l.strip()}
    return ids


# =============================================================================
# install / remove
# =============================================================================

def _argv(action: str, pkg: str, backend: str) -> list[str]:
    if backend == "flatpak":
        # --user: installs into the user's own home, so no authentication at all.
        return (["flatpak", action, "--user", "--assumeyes", "--noninteractive"]
                + (["flathub"] if action == "install" else []) + [pkg])
    if backend == "dnf":
        return ["dnf", "-y", "install" if action == "install" else "remove", pkg]
    if backend == "pacman":
        return ["pacman", "--noconfirm", "-S" if action == "install" else "-R", pkg]
    return ["apt-get", "install" if action == "install" else "remove", "-y", pkg]


_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _valid(pkg: str) -> bool:
    """A package name, and nothing that could become a second command.

    This string reaches a privileged process. It is validated rather than
    escaped, because the set of legal package names is small and known and
    "escaped correctly" is a claim that has to be re-earned on every edit.
    """
    return bool(pkg) and len(pkg) < 200 and bool(_SAFE.match(pkg))


async def act(action: str, pkg: str, backend: str = "") -> dict:
    """install or remove one application, with consent already given.

    Returns {ok, message, command, needs_terminal}. `command` is always the exact
    thing that ran (or that you should run) — installing software on someone's
    machine is not a thing to do invisibly.
    """
    if action not in ("install", "remove"):
        return {"ok": False, "message": "unknown action", "command": "",
                "needs_terminal": False}
    if not _valid(pkg):
        return {"ok": False, "message": f"'{pkg}' is not a valid package name",
                "command": "", "needs_terminal": False}
    b = backends()
    backend = backend or ("flatpak" if b["flatpak"] else
                          "apt" if b["apt"] else
                          "dnf" if b["dnf"] else
                          "pacman" if b["pacman"] else "")
    if not backend or not b.get(backend):
        return {"ok": False, "message": "no package manager available for that",
                "command": "", "needs_terminal": False}

    argv = _argv(action, pkg, backend)
    shown = " ".join(argv)

    # flatpak --user is the whole reason to prefer it: no root, no prompt.
    if backend == "flatpak":
        rc, out = await _run(argv, TIMEOUT_INSTALL)
        ok = rc == 0
        return {"ok": ok, "command": shown, "needs_terminal": False,
                "message": (f"{pkg} {action}ed." if ok else out[-500:] or "failed")}

    manual = {"ok": False, "needs_terminal": True, "command": f"sudo {shown}",
              "message": "Root access is needed — run this in the Terminal:"}

    rc, _ = await _run(["sudo", "-n", "true"], 10)
    if rc == 0:
        rc, out = await _run(["sudo", "-n"] + argv, TIMEOUT_INSTALL)
        if rc == 0:
            return {"ok": True, "message": f"{pkg} {action}ed.",
                    "command": f"sudo {shown}", "needs_terminal": False}
        return {**manual, "message": out[-500:] or manual["message"]}

    if shutil.which("pkexec"):
        rc, out = await _run(["pkexec"] + argv, TIMEOUT_INSTALL)
        if rc == 0:
            return {"ok": True, "message": f"{pkg} {action}ed.",
                    "command": f"pkexec {shown}", "needs_terminal": False}
        if rc in (126, 127):        # prompt dismissed, or no polkit agent running
            return manual
        return {**manual, "message": out[-500:] or manual["message"]}

    return manual
