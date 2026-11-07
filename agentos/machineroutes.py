"""What only an admin may touch on a machine with accounts: one table, one check.

Accounts are isolated by directory, but a host has one screen, one Wi-Fi radio, one
compositor, one set of installed packages and one code tree. A route that drives any of
those is the machine's, whoever is signed in. Those checks used to be written route by
route, and the audit found the neighbours of every checked route unchecked: `/api/wifi/connect`
was admin-only while `/api/net/wifi` joined networks for anyone.

So the rule is here, and `machine_only_gate` in server.py enforces it before a route runs.
An entry names a method set and a path; a path ending in `/*` covers the path and everything
under it, so a new route under a machine family is refused until somebody says otherwise.
`tests/test_machine_routes.py` fails on any mutating route that is neither here, nor checks
for itself, nor listed as an account's own in `ACCOUNT_ROUTES` there.

A machine with no accounts has nobody to refuse (`users.is_admin('')` is True).
Stdlib only and no state, so the test can read it without a server.
"""

from __future__ import annotations

ANY = frozenset({"*"})
WRITE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

REFUSAL = "Only an admin can do that on this machine."

MACHINE_ONLY: tuple[tuple[frozenset, str], ...] = (
    # the host's windows and workspaces (read too: a window title is somebody's work)
    (ANY, "/api/windows/*"),
    (ANY, "/api/wm/*"),
    # the host's screen, as pixels or as a keyboard and mouse
    (ANY, "/api/screen/*"),
    (ANY, "/remote-desktop"),
    (ANY, "/novnc/*"),
    (WRITE, "/api/screenshot"),
    # native apps run outside every account's jail
    (WRITE, "/api/native/launch"),
    (WRITE, "/api/native/store"),
    (ANY, "/api/appstreams/*"),
    (WRITE, "/api/open"),
    # the session: compositor config and the page drawn on its screen. /api/shell/result is an
    # account's page answering its own command, and /api/shell/sui is loopback and proves itself.
    (WRITE, "/api/shell/action"),
    (WRITE, "/api/shell/wake"),
    (WRITE, "/api/shell/reload"),
    (WRITE, "/api/shell/raise"),
    (WRITE, "/api/shortcuts/apply"),
    (WRITE, "/api/input"),
    (WRITE, "/api/nightlight"),
    (WRITE, "/api/locale/apply"),
    # radios, sound, power
    (WRITE, "/api/net/wifi"),
    (WRITE, "/api/wifi/connect"),
    (WRITE, "/api/bt"),
    (WRITE, "/api/brightness"),
    (WRITE, "/api/audio/devices"),
    (WRITE, "/api/power/*"),
    (WRITE, "/api/control"),
    (WRITE, "/api/notifications"),
    # software and what the machine answers on
    (WRITE, "/api/components/*"),
    (WRITE, "/api/models/*"),
    (WRITE, "/api/tunnel"),
    (WRITE, "/api/remote"),
    (WRITE, "/api/restart"),
    (WRITE, "/api/update/*"),
    (WRITE, "/api/train/service"),
    # the community is the machine's, and what its notes say reaches every member
    (WRITE, "/api/pool/notes/*"),
    # a snapshot is the machine's config, database and code
    (ANY, "/api/snapshots/*"),
)


def machine_only(method: str, path: str) -> bool:
    """Does this request need an admin? `path` is the path the router matches on."""
    m = (method or "").upper()
    for methods, pat in MACHINE_ONLY:
        if "*" not in methods and m not in methods:
            continue
        if pat.endswith("/*"):
            base = pat[:-2]
            if path == base or path.startswith(base + "/"):
                return True
        elif path == pat or path == pat + "/":
            return True
    return False
