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
def catalogue(monkeypatch):
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
    """It must not be selectable, and the reason must be visible."""
    out = _run(monkeypatch, ["all"])
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
