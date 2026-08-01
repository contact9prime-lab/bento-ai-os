"""Which machine is this, and how does software get installed on it?

The rule this module exists to enforce: AgentOS never shows a command from
somebody else's operating system. It either knows how this distro installs
packages, or it says it doesn't. There is no third behaviour, and in particular
there is no "assume apt" — which is what it used to do, silently, everywhere.
"""

import pytest

from agentos import osdetect


@pytest.fixture(autouse=True)
def clear_cache():
    osdetect._CACHE.clear()
    yield
    osdetect._CACHE.clear()


def _osr(tmp_path, text):
    p = tmp_path / "os-release"
    p.write_text(text)
    return p


def test_derivatives_resolve_through_id_like(tmp_path, monkeypatch):
    """Mint/Pop/Zorin never need an entry of their own — that is the point.

    ID_LIKE is why this table is short and why a distro released next year works
    without a code change.
    """
    monkeypatch.setattr(osdetect, "OS_RELEASE",
                        _osr(tmp_path, 'ID=linuxmint\nID_LIKE="ubuntu debian"\n'
                                       'PRETTY_NAME="Linux Mint 22"\n'))
    monkeypatch.setattr(osdetect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(osdetect.shutil, "which", lambda n: f"/usr/bin/{n}")
    d = osdetect.detect(refresh=True)
    assert d["family"] == "debian"
    assert d["manager"] == "apt"
    assert d["pretty"] == "Linux Mint 22"


@pytest.mark.parametrize("ident,family,manager", [
    ("ubuntu", "debian", "apt"),
    ("debian", "debian", "apt"),
    ("fedora", "rhel", "dnf"),
    ("rocky", "rhel", "dnf"),
    ("arch", "arch", "pacman"),
    ("manjaro", "arch", "pacman"),
    ("opensuse-tumbleweed", "suse", "zypper"),
])
def test_each_supported_distro_maps_to_its_package_manager(
        ident, family, manager, tmp_path, monkeypatch):
    monkeypatch.setattr(osdetect, "OS_RELEASE", _osr(tmp_path, f"ID={ident}\n"))
    monkeypatch.setattr(osdetect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(osdetect.shutil, "which", lambda n: f"/usr/bin/{n}")
    d = osdetect.detect(refresh=True)
    assert (d["family"], d["manager"]) == (family, manager)
    assert d["install_argv"], "a recognised family must produce an install command"


def test_an_unknown_distro_is_never_guessed_at(tmp_path, monkeypatch):
    monkeypatch.setattr(osdetect, "OS_RELEASE",
                        _osr(tmp_path, 'ID=void\nPRETTY_NAME="Void Linux"\n'))
    monkeypatch.setattr(osdetect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(osdetect.shutil, "which", lambda n: f"/usr/bin/{n}")
    d = osdetect.detect(refresh=True)
    assert d["family"] == ""
    assert d["install_argv"] == []
    assert "Void Linux" in d["why"], "it must name the distro it could not place"
    assert osdetect.install_argv("anything") == []


def test_a_known_family_without_its_package_manager_says_so(tmp_path, monkeypatch):
    """A Debian container with no apt-get is real. Claiming apt exists because
    the distro is Debian produces a command that fails at the worst moment."""
    monkeypatch.setattr(osdetect, "OS_RELEASE",
                        _osr(tmp_path, 'ID=debian\nPRETTY_NAME="Debian 13"\n'))
    monkeypatch.setattr(osdetect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(osdetect.shutil, "which", lambda n: None)
    d = osdetect.detect(refresh=True)
    assert d["family"] == "debian"
    assert d["manager"] == "" and d["install_argv"] == []
    assert "apt-get" in d["why"]


@pytest.mark.parametrize("system,label", [("Darwin", "macos"), ("Windows", "windows")])
def test_non_linux_is_honest_about_the_session(system, label, monkeypatch):
    monkeypatch.setattr(osdetect.platform, "system", lambda: system)
    d = osdetect.detect(refresh=True)
    assert d["os"] == label
    assert d["session_capable"] is False
    assert "Linux" in d["why"], "it must say why there is no session here"


def test_quoted_and_commented_os_release_parses(tmp_path, monkeypatch):
    monkeypatch.setattr(osdetect, "OS_RELEASE", _osr(tmp_path, "\n".join([
        "# a comment",
        'NAME="Ubuntu"',
        "ID=ubuntu",
        "VERSION_ID='25.10'",
        'PRETTY_NAME="Ubuntu 25.10"',
        "",
    ])))
    monkeypatch.setattr(osdetect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(osdetect.shutil, "which", lambda n: f"/usr/bin/{n}")
    d = osdetect.detect(refresh=True)
    assert d["version_id"] == "25.10"
    assert d["pretty"] == "Ubuntu 25.10"


def test_install_argv_never_builds_a_shell_string(tmp_path, monkeypatch):
    """Packages arrive as separate argv entries, so no shell is ever involved."""
    monkeypatch.setattr(osdetect, "OS_RELEASE", _osr(tmp_path, "ID=fedora\n"))
    monkeypatch.setattr(osdetect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(osdetect.shutil, "which", lambda n: f"/usr/bin/{n}")
    osdetect.detect(refresh=True)
    assert osdetect.install_argv("gtk3 gtk-layer-shell") == [
        "dnf", "install", "-y", "gtk3", "gtk-layer-shell"]


def test_arch_refresh_is_deliberately_empty(tmp_path, monkeypatch):
    """`pacman -Sy` before an install is a partial upgrade and breaks systems.

    The empty refresh list for arch is a decision, not an omission.
    """
    monkeypatch.setattr(osdetect, "OS_RELEASE", _osr(tmp_path, "ID=arch\n"))
    monkeypatch.setattr(osdetect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(osdetect.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert osdetect.detect(refresh=True)["refresh_argv"] == []
