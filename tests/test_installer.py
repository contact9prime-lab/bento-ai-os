"""The installer's promises, which are all about what it does NOT do.

It is the one piece of AgentOS whose whole job is changing the system, so the
guarantees worth testing are the restraints: nothing installs without a
keystroke agreeing to it, the licence and the exact command are on screen before
that keystroke, and a machine AgentOS cannot install on is told so rather than
shown buttons that would run somebody else's package manager.
"""

import io
from contextlib import redirect_stdout

import pytest

from agentos import components, installer, osdetect


@pytest.fixture(autouse=True)
def no_real_installs(monkeypatch):
    """Nothing in this file may touch the machine."""
    installed: list = []

    async def fake_install(cid):
        installed.append(cid)
        return {"ok": True, "message": f"{cid} installed.", "command": f"sudo install {cid}",
                "needs_terminal": False}

    async def fake_refresh():
        return True, ""

    monkeypatch.setattr(components, "install", fake_install)
    monkeypatch.setattr(components, "refresh_index", fake_refresh)
    monkeypatch.setattr(installer, "_offer_session", lambda d: None)
    return installed


@pytest.fixture
def as_linux(monkeypatch):
    """Pin the machine, because the offer now depends on it.

    These rows are a Linux catalogue — every one is `for_session` — and the
    installer no longer offers a session component on an OS that cannot host a
    session. Without saying which machine this is, the whole file quietly tested
    "macOS hides all of this" on a Mac and the selection logic on Linux, which is
    the sort of split that makes a green suite meaningless.
    """
    machine = {
        "os": "linux", "id": "debian", "id_like": [], "version_id": "12",
        "pretty": "Debian 12", "family": "debian", "manager": "apt",
        "install_argv": ["apt-get", "install", "-y"], "refresh_argv": [],
        "session_capable": True, "why": "",
    }
    # `detect`, not `_CACHE`: `_header()` calls `detect(refresh=True)`, which
    # rebuilds the cache from the real machine and throws a patched one away.
    monkeypatch.setattr(osdetect, "detect", lambda refresh=False: dict(machine))
    monkeypatch.setattr(osdetect, "describe", lambda: "Debian 12")
    return machine


@pytest.fixture
def catalogue(monkeypatch, as_linux):
    """A small, predictable catalogue: one missing required, one present."""
    rows = [
        {"id": "compositor", "title": "Compositor engine (sway)", "package": "sway",
         "method": "system", "manager": "apt", "licence": "MIT",
         "unlocks": "the compositor", "group": "required", "for_session": True,
         "installed": False, "available": True, "reason": "",
         "command": "sudo apt-get install -y sway"},
        {"id": "grim", "title": "Screenshots", "package": "grim slurp",
         "method": "system", "manager": "apt", "licence": "MIT",
         "unlocks": "capture", "group": "recommended", "for_session": True,
         "installed": True, "available": True, "reason": "",
         "command": "sudo apt-get install -y grim slurp"},
        {"id": "novnc", "title": "Remote Desktop in a browser", "package": "novnc",
         "method": "system", "manager": "", "licence": "MPL-2.0",
         "unlocks": "phone access", "group": "optional", "for_session": True,
         "installed": False, "available": False,
         "reason": "no rhel-family package name is known for this component",
         "command": ""},
    ]
    monkeypatch.setattr(components, "catalog", lambda session_only=False: list(rows))
    return rows


def _run(monkeypatch, answers, **kw) -> str:
    """Run the installer with canned keystrokes; return what it printed."""
    it = iter(answers)
    monkeypatch.setattr(installer, "_ask", lambda prompt, default="": next(it, default))
    buf = io.StringIO()
    with redirect_stdout(buf):
        installer.run(**kw)
    return buf.getvalue()


def test_answering_none_installs_nothing(monkeypatch, catalogue, no_real_installs):
    out = _run(monkeypatch, ["none"])
    assert no_real_installs == [], "a 'none' answer must not touch the machine"
    assert "Compositor engine" in out


def test_the_licence_and_command_are_shown_before_the_prompt(monkeypatch, catalogue,
                                                             no_real_installs):
    """Consent means informed consent: the licence and the exact command are on
    screen above the question, not behind it."""
    out = _run(monkeypatch, ["none"])
    prompt_at = out.index("Install which") if "Install which" in out else len(out)
    head = out[:prompt_at]
    assert "MIT" in head
    assert "sudo apt-get install -y sway" in head


def test_selecting_by_number_installs_only_that_one(monkeypatch, catalogue,
                                                    no_real_installs):
    out = _run(monkeypatch, ["1"])
    assert no_real_installs == ["compositor"]
    assert "done" in out


def test_all_installs_every_offered_component(monkeypatch, catalogue, no_real_installs):
    _run(monkeypatch, ["all"])
    assert no_real_installs == ["compositor"], "already-installed and unavailable are not offered"


def test_an_unavailable_component_is_explained_not_offered(monkeypatch, catalogue,
                                                           no_real_installs):
    """It must not be selectable, and the reason must be visible.

    Whitespace-normalised before matching: the reason is wrapped to the terminal
    width, so a line break can land in the middle of the sentence. Asserting the
    raw string tests where the wrap happened to fall, not whether the user was
    told why — and it fails the moment the surrounding text changes length.
    """
    out = " ".join(_run(monkeypatch, ["all"]).split())
    assert "no rhel-family package name is known" in out
    assert "novnc" not in no_real_installs


def test_garbage_input_selects_nothing_rather_than_something(monkeypatch, catalogue,
                                                             no_real_installs):
    out = _run(monkeypatch, ["99 banana"])
    assert no_real_installs == []
    assert "ignoring" in out


def test_already_installed_components_are_not_offered(monkeypatch, catalogue,
                                                      no_real_installs):
    _run(monkeypatch, ["all"])
    assert "grim" not in no_real_installs


def test_yes_still_prints_every_package_and_licence(monkeypatch, catalogue,
                                                    no_real_installs):
    """Unattended must not mean invisible — the record of what was installed,
    and under which licence, is printed either way."""
    out = _run(monkeypatch, [], assume_yes=True)
    assert no_real_installs == ["compositor"]
    assert "MIT" in out and "sudo apt-get install -y sway" in out


def test_no_terminal_installs_nothing_and_does_not_hang(monkeypatch, catalogue,
                                                        no_real_installs):
    """No stdin is NOT a silent yes.

    The default answer when something required is missing is "all", so an
    installer that fell back to its default on EOF would install packages nobody
    agreed to the moment it was piped into a script. It must return promptly
    having changed nothing, and say how to actually proceed.
    """
    def raise_eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = installer.run()
    out = buf.getvalue()
    assert rc == 0
    assert no_real_installs == [], "EOF must never be read as consent"
    assert "No terminal to ask on" in out
    assert "--yes" in out, "it must say how to proceed deliberately"


def test_a_machine_with_nothing_missing_says_so(monkeypatch, no_real_installs):
    monkeypatch.setattr(components, "catalog", lambda session_only=False: [
        {"id": "grim", "title": "Screenshots", "package": "grim", "method": "system",
         "manager": "apt", "licence": "MIT", "unlocks": "capture", "group": "required",
         "for_session": True, "installed": True, "available": True, "reason": "",
         "command": "sudo apt-get install -y grim"}])
    out = _run(monkeypatch, [])
    assert "Nothing left to install" in out
    assert no_real_installs == []


def test_the_header_names_the_detected_system(monkeypatch, catalogue, no_real_installs):
    monkeypatch.setattr(osdetect, "describe", lambda: "Fedora 42 (rhel) · dnf")
    out = _run(monkeypatch, ["none"])
    assert "Fedora 42 (rhel) · dnf" in out


# ---------------------------------------------------------------------------
# The offer follows the OS
# ---------------------------------------------------------------------------

@pytest.fixture
def as_macos(monkeypatch):
    machine = {
        "os": "macos", "id": "", "id_like": [], "version_id": "",
        "pretty": "macOS 26.3", "family": "macos", "manager": "brew",
        "install_argv": [], "refresh_argv": [], "session_capable": False,
        "why": "The AgentOS login session is a Wayland session and exists only on Linux.",
    }
    monkeypatch.setattr(osdetect, "detect", lambda refresh=False: dict(machine))
    monkeypatch.setattr(osdetect, "describe", lambda: "macOS 26.3")
    return machine


def test_a_session_component_is_not_offered_where_there_is_no_session(monkeypatch,
                                                                      as_macos,
                                                                      no_real_installs):
    """macOS listed eleven Linux-only components, two of them under "Required —
    without these there is no session". That reads as a broken install on a machine
    that works perfectly, and it buried the things that ARE installable."""
    rows = [
        {"id": "compositor", "title": "Compositor engine (sway)", "package": "sway",
         "method": "system", "manager": "", "licence": "MIT", "unlocks": "the compositor",
         "group": "required", "for_session": True, "installed": False,
         "available": False, "reason": "Linux only", "command": ""},
        {"id": "ollama", "title": "Ollama (local models)", "package": "ollama",
         "method": "script", "manager": "script", "licence": "MIT",
         "unlocks": "local models", "group": "recommended", "for_session": False,
         "installed": False, "available": True, "reason": "",
         "command": "sh install.sh"},
    ]
    monkeypatch.setattr(components, "catalog", lambda session_only=False: list(rows))
    out = " ".join(_run(monkeypatch, ["none"]).split())

    assert "Ollama" in out, "what IS installable here must still be offered"
    assert "Required — without these there is no session" not in out
    assert "Compositor engine" not in out


def test_the_session_list_is_still_shown_when_it_was_asked_for(monkeypatch, as_macos,
                                                               no_real_installs):
    """`--session` is an explicit question. Answering it with silence would be a
    different lie from the one above."""
    rows = [
        {"id": "compositor", "title": "Compositor engine (sway)", "package": "sway",
         "method": "system", "manager": "", "licence": "MIT", "unlocks": "the compositor",
         "group": "required", "for_session": True, "installed": False,
         "available": False, "reason": "Linux only", "command": ""},
    ]
    monkeypatch.setattr(components, "catalog", lambda session_only=False: list(rows))
    out = " ".join(_run(monkeypatch, ["none"], session_only=True).split())
    assert "Compositor engine" in out


def test_what_has_no_route_here_is_counted_with_its_own_reason(monkeypatch, as_linux,
                                                               no_real_installs):
    """Grouped by reason, so a component missing a package name for THIS family
    keeps its own explanation instead of a blanket sentence that would be false."""
    rows = [
        {"id": "novnc", "title": "Remote Desktop", "package": "novnc", "method": "system",
         "manager": "", "licence": "MPL", "unlocks": "phone access", "group": "optional",
         "for_session": False, "installed": False, "available": False,
         "reason": "no debian-family package name is known", "command": ""},
    ]
    monkeypatch.setattr(components, "catalog", lambda session_only=False: list(rows))
    out = " ".join(_run(monkeypatch, ["none"]).split())
    assert "Remote Desktop" in out and "no debian-family package name is known" in out
