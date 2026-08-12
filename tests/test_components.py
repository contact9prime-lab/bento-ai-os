"""Optional components — the consent gate's mechanics.

The promise: nothing installs invisibly, nothing installs without a detect()
check, every entry names its licence, and when root isn't available the user
gets the exact command instead of a silent failure. Also: every component id a
capability can point at must actually exist in the catalog, or the UI's
"Install …" button would dead-end.
"""

import asyncio

import pytest

from agentos import components, osdetect


@pytest.fixture
def as_family(monkeypatch):
    """Pretend to be a given distro family, for package-name assertions."""
    def use(family, manager, argv, pretty="Test Linux", os_name="linux", why=""):
        monkeypatch.setattr(osdetect, "_CACHE", [{
            "os": os_name, "id": family, "id_like": [], "version_id": "1",
            "pretty": pretty, "family": family, "manager": manager,
            "install_argv": list(argv), "refresh_argv": [],
            "session_capable": os_name == "linux", "why": why,
        }])
    return use


def test_catalog_entries_are_complete():
    for row in components.catalog():
        assert row["id"] and row["title"]
        assert row["licence"], f"{row['id']} has no licence to show in the consent dialog"
        assert row["unlocks"], f"{row['id']} doesn't say what it unlocks"
        assert row["method"] in ("system", "snap", "script")
        assert row["group"] in components.GROUPS
        assert isinstance(row["installed"], bool)
        if row["available"]:
            assert row["command"].startswith("sudo "), "the shown command must be runnable as-is"
        else:
            assert row["reason"], f"{row['id']} is unavailable without saying why"


def test_every_component_has_a_name_for_every_supported_family():
    """A missing spelling is not a crash — it is a component silently absent.

    Each family AgentOS claims to support must have a package name for every
    system component, or users of that distro are quietly offered less than
    users of Debian with no indication that anything is missing.
    """
    for cid, comp in components.CATALOG.items():
        if comp["method"] == "script":
            continue
        for family in components.FAMILIES:
            assert comp["packages"].get(family), (
                f"component '{cid}' has no {family} package name")


def test_install_command_is_the_running_distros_command(as_family):
    """The whole point: a Fedora user must never be shown an apt command."""
    ddcutil = components.CATALOG["ddcutil"]

    as_family("debian", "apt", ["apt-get", "install", "-y"])
    assert components.install_command(ddcutil) == "apt-get install -y ddcutil"

    as_family("rhel", "dnf", ["dnf", "install", "-y"])
    assert components.install_command(ddcutil) == "dnf install -y ddcutil"

    as_family("arch", "pacman", ["pacman", "-S", "--noconfirm", "--needed"])
    assert components.install_command(ddcutil) == "pacman -S --noconfirm --needed ddcutil"

    as_family("suse", "zypper", ["zypper", "--non-interactive", "install"])
    assert components.install_command(ddcutil) == "zypper --non-interactive install ddcutil"


def test_the_cairo_bridge_is_in_every_familys_session_ui(as_family):
    """The package whose absence was a black screen at login.

    python3-gi does not pull in the PyGObject<->cairo bridge on any distro, and
    without it the shell host dies building its first strut. Each family's
    spelling of that bridge must be present.
    """
    pkgs = components.CATALOG["session-ui"]["packages"]
    assert "python3-gi-cairo" in pkgs["debian"]
    assert "python3-cairo" in pkgs["rhel"]
    assert "python-cairo" in pkgs["arch"]
    assert "cairo" in pkgs["suse"]


def test_an_unknown_distro_is_told_so_rather_than_guessed_at(as_family):
    as_family("", "", [], pretty="Void Linux",
              why="AgentOS does not know how Void Linux installs packages.")
    ddcutil = components.CATALOG["ddcutil"]
    assert components.install_command(ddcutil) == ""
    assert "Void Linux" in components.unavailable_reason(ddcutil)
    row = next(r for r in components.catalog() if r["id"] == "ddcutil")
    assert row["available"] is False and row["command"] == "" and row["reason"]


def test_non_linux_gets_the_reason_that_actually_matters(as_family):
    """'no macos-family package name' is true and useless; the session is Linux-only."""
    as_family("macos", "brew", [], pretty="macOS 15.2", os_name="macos",
              why="The AgentOS login session is a Wayland session and exists only on Linux.")
    reason = components.unavailable_reason(components.CATALOG["compositor"])
    assert "Linux" in reason and "package name" not in reason


def test_installing_where_there_is_no_route_is_not_reported_as_failure(as_family):
    as_family("", "", [], pretty="Void Linux", why="no package manager known")
    r = asyncio.run(components.install("ddcutil"))
    assert r["ok"] is False
    assert r["needs_terminal"] is False, "there is no command to hand back"
    assert r["command"] == ""
    assert "cannot be installed here" in r["message"]


def test_install_command_shapes():
    cmd = components.install_command({"method": "script", "packages": {}})
    assert cmd.startswith("sh ") and cmd.endswith("install.sh")


def test_shellhost_hints_agree_with_the_catalogue():
    """The one duplicate list in the codebase must not be allowed to drift.

    shellhost.py cannot import from agentos — it has to be runnable by a bare
    system python — so its INSTALL_HINTS really is a second copy of the
    session-ui package list. That duplication is exactly how python3-gi-cairo
    ended up in one list and not the other, and which message a user happened to
    read decided whether their desktop worked. If you change one, change both.
    """
    from agentos import shellhost
    hints = dict(shellhost.INSTALL_HINTS)
    catalogue = components.CATALOG["session-ui"]["packages"]
    for mgr, family in (("apt", "debian"), ("dnf", "rhel"),
                        ("pacman", "arch"), ("zypper", "suse")):
        hinted = set(hints[mgr].split()) - {"sudo", mgr, "install", "-S"}
        assert set(catalogue[family].split()) == hinted, (
            f"shellhost's {mgr} hint and the catalogue's {family} packages disagree")


def test_unknown_component_is_refused():
    r = asyncio.run(components.install("definitely-not-a-thing"))
    assert r["ok"] is False and "unknown" in r["message"]
    assert r["needs_terminal"] is False


def test_already_installed_is_a_noop(monkeypatch):
    monkeypatch.setitem(components.CATALOG, "ddcutil",
                        {**components.CATALOG["ddcutil"], "detect": lambda: True})
    r = asyncio.run(components.install("ddcutil"))
    assert r == {"ok": True, "message": "already installed", "command": "",
                 "needs_terminal": False}


def test_no_root_hands_back_the_exact_command(monkeypatch, as_family):
    # Say which machine this is, like the package-name tests do. Without it the
    # answer depends on whoever ran pytest: on a Mac there is no apt to build an
    # argv from, so install() correctly stops at "cannot be installed here" and
    # never reaches the privilege ladder this test is about — a green tick on
    # Linux and a red one on macOS, for a function that behaved properly both times.
    as_family("debian", "apt", ["apt-get", "install", "-y"])
    monkeypatch.setitem(components.CATALOG, "ddcutil",
                        {**components.CATALOG["ddcutil"], "detect": lambda: False})
    monkeypatch.setattr(components.shutil, "which", lambda n: None)   # no pkexec

    async def fake_run_factory():
        async def fake(argv, timeout):
            return (1, "sudo: a password is required")   # sudo -n fails
        return fake

    # Patch subprocess by intercepting create_subprocess_exec via the sudo probe:
    # easier — patch asyncio.create_subprocess_exec wholesale.
    class FakeProc:
        returncode = 1
        async def communicate(self):
            return b"sudo: a password is required", b""
        def kill(self):
            pass

    async def fake_exec(*argv, **kw):
        return FakeProc()

    monkeypatch.setattr(components.asyncio, "create_subprocess_exec", fake_exec)
    r = asyncio.run(components.install("ddcutil"))
    assert r["ok"] is False
    assert r["needs_terminal"] is True
    assert r["command"] == "sudo apt-get install -y ddcutil"


def test_every_capability_component_reference_resolves():
    """A capability's `component` field must point at a real catalog entry."""
    from agentos.platform import get_platform
    ids = set(components.CATALOG)
    for cap in get_platform(refresh=True).capabilities().values():
        if cap.component:
            assert cap.component in ids, (
                f"capability {cap.id} points at unknown component '{cap.component}'")


def test_de_capability_component_references_resolve_too(monkeypatch):
    from agentos.platform.linux_de import LinuxDE
    ids = set(components.CATALOG)
    monkeypatch.delenv("SWAYSOCK", raising=False)
    for cap in LinuxDE().capabilities(refresh=True).values():
        if cap.component:
            assert cap.component in ids, (
                f"DE capability {cap.id} points at unknown component '{cap.component}'")


def test_a_user_space_install_never_asks_for_root(monkeypatch, as_family):
    """`npm install --prefix` into AgentOS's own directory needs no privilege.

    The ladder used to run for every component, so the WhatsApp bridge failed
    `sudo -n`, fell through to "Root access is needed", and handed back a
    `sudo npm install …` that would have left a root-owned node_modules in the
    user's tree. Nothing in the catalogue said the install was user-space, so
    nothing could tell the two cases apart.
    """
    as_family("debian", "apt", ["apt-get", "install", "-y"])
    ran: list = []

    async def fake_run(argv, timeout):
        ran.append(list(argv))
        return (0, "")

    monkeypatch.setitem(components.CATALOG, "whatsapp-bridge",
                        {**components.CATALOG["whatsapp-bridge"],
                         "detect": lambda: True,
                         "argv": lambda: ["/usr/bin/npm", "install", "--prefix", "/tmp/x"]})
    monkeypatch.setattr(components, "_run", fake_run)
    r = asyncio.run(components.install("whatsapp-bridge"))

    assert r["ok"] is True
    assert r["needs_terminal"] is False
    assert not r["command"].startswith("sudo"), "a user-space install must not suggest sudo"
    assert not any(a and a[0] in ("sudo", "pkexec") for a in ran), \
        f"escalated for a user-space install: {ran}"


def test_the_catalogue_defaults_to_needing_root():
    """Opt IN, so a new system package cannot silently lose its escalation."""
    for cid, comp in components.CATALOG.items():
        if comp["method"] == "system":
            assert comp.get("needs_root", True) is True, \
                f"{cid} installs a system package but is marked user-space"
