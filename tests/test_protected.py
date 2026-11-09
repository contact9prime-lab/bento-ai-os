"""One list of what no agent may touch, and it does not read grants or autonomy."""

import os

import pytest

from agentos import config as cfgmod
from agentos import protected as pr


@pytest.mark.parametrize("name", sorted(pr.SECRET_FILES))
def test_secret_files_are_refused_in_any_home(name):
    home = cfgmod.AGENTOS_HOME
    assert pr.secret(home / name)
    assert pr.secret(home / "users" / "abc123" / name)
    assert pr.write_refused(home / "users" / "abc123" / name)


def test_the_pki_folder_is_secret_all_the_way_down():
    assert pr.secret(cfgmod.AGENTOS_HOME / "pki" / "ssh_ed25519")


def test_settings_are_neither_read_nor_written():
    """config.json holds provider keys and bot tokens in clear (S-16), so reading it is the attack."""
    path = cfgmod.AGENTOS_HOME / "config.json"
    assert pr.secret(path)
    assert pr.write_refused(path)


def test_a_project_in_the_workspace_may_have_files_with_those_names():
    ws = cfgmod.AGENTOS_HOME / "workspace" / "myproject"
    for name in ("config.json", "inventory.json", "users.json"):
        assert pr.secret(ws / name) == ""
        assert pr.write_refused(ws / name) == ""


def test_anything_in_a_home_not_named_as_open_is_closed():
    """The list of secrets is the belt. A file a later feature keeps in a home is closed until
    somebody opens it, so one forgotten line is not a model reading a sign-in."""
    home = cfgmod.AGENTOS_HOME
    assert pr.outside_agent_area(home / "some-new-feature" / "tokens.bin")
    assert pr.outside_agent_area(home / "users" / "abc" / "some-new-feature.db")
    assert pr.outside_agent_area(home / "assets" / "x.png") == ""
    assert pr.outside_agent_area(home / "assets" / "x.png", write=True)
    assert pr.outside_agent_area(home / "elsewhere", also=[home / "elsewhere"]) == ""


@pytest.mark.parametrize("path", ["/proc/self/environ", "/proc/1/environ", "/proc/self/cmdline"])
def test_a_process_environment_is_secret(path):
    assert pr.secret(path)


@pytest.mark.parametrize("name", ["oauth/x.json", "whatsapp/session/creds.json", "browser/profile/Cookies",
                                  "snapshots/1/config.json", ".timetravel/blobs/aa/aa",
                                  ".before-restore-1/vault.key", "screen-profile/Default/Cookies"])
def test_sign_ins_and_copies_of_a_home_are_secret(name):
    assert pr.secret(cfgmod.AGENTOS_HOME / name)


def test_the_code_is_refused_for_writes_and_not_for_reads():
    policy = pr._code_root() / "agentos" / "policy.py"
    assert pr.write_refused(policy)
    assert pr.secret(policy) == ""


def test_a_link_does_not_get_round_it(tmp_path):
    link = tmp_path / "harmless.txt"
    link.symlink_to(pr._code_root() / "agentos" / "policy.py")
    assert pr.write_refused(link)


def test_dotdot_does_not_get_round_it(tmp_path):
    sneaky = str(tmp_path) + "/" + os.path.relpath(pr._code_root() / "agentos" / "policy.py", tmp_path)
    assert ".." in sneaky
    assert pr.write_refused(sneaky)


@pytest.mark.parametrize("name", [".claude/settings.json", ".gemini/settings.json", ".mcp.json", ".codex/config.toml"])
def test_an_agent_cli_config_is_a_program(tmp_path, name):
    assert pr.write_refused(tmp_path / name)


def test_a_git_folder_is_a_program_too(tmp_path):
    assert pr.write_refused(tmp_path / ".git" / "hooks" / "pre-commit")
    assert pr.write_refused(tmp_path / ".git" / "config")


def test_an_ordinary_workspace_file_is_fine(tmp_path):
    assert pr.write_refused(tmp_path / "report.md") == ""
    assert pr.secret(tmp_path / "report.md") == ""


def test_security_modules_are_named_by_repo_path():
    assert pr.is_security_module("agentos/policy.py")
    assert pr.is_security_module("./agentos/policy.py")
    assert not pr.is_security_module("agentos/comic.py")
