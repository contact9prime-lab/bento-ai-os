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


def test_settings_may_be_read_but_not_written():
    path = cfgmod.AGENTOS_HOME / "config.json"
    assert pr.secret(path) == ""
    assert pr.write_refused(path)


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
