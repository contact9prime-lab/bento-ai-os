"""Optional components — the consent gate's mechanics.

The promise: nothing installs invisibly, nothing installs without a detect()
check, every entry names its licence, and when root isn't available the user
gets the exact command instead of a silent failure. Also: every component id a
capability can point at must actually exist in the catalog, or the UI's
"Install …" button would dead-end.
"""

import asyncio

from agentos import components


def test_catalog_entries_are_complete():
    for row in components.catalog():
        assert row["id"] and row["title"] and row["package"]
        assert row["licence"], f"{row['id']} has no licence to show in the consent dialog"
        assert row["unlocks"], f"{row['id']} doesn't say what it unlocks"
        assert row["method"] in ("apt", "snap", "script")
        assert row["command"].startswith("sudo "), "the shown command must be runnable as-is"
        assert isinstance(row["installed"], bool)


def test_install_command_shapes():
    assert components.install_command(
        {"method": "apt", "package": "ddcutil"}) == "apt-get install -y ddcutil"
    assert components.install_command(
        {"method": "snap", "package": "chromium"}) == "snap install chromium"
    cmd = components.install_command({"method": "script", "package": "agentos boot theme"})
    assert cmd.startswith("sh ") and cmd.endswith("install.sh")


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


def test_no_root_hands_back_the_exact_command(monkeypatch):
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
