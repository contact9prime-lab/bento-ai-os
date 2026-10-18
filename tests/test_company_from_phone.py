"""A company set up by the agent a phone is talking to (agentos/__main__.py `_company_cli`).

Reported from Telegram: the lead, forwarded to Claude Code, ran `bento company new` in
its shell. The company was written to the files, the running server kept its own copy
in memory ("restart AgentOS first"), and the Telegram chat stayed in the old company's
space because only the desktop's surface moved.

What these defend:

- a forwarded turn tells its shell where it was asked from (`AGENTOS_SURFACE`, set by
  the team door), and `bento company` passes that on, so Telegram moves to the new
  company;
- the company routes accept a phone's surface, and nothing else widens;
- with the server up, `bento company` goes through it even with `--user`, and a refusal
  from a machine with accounts says where to do it instead of writing behind it.
"""
import inspect
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import __main__ as cli, company, executors              # noqa: E402
from agentos.memory import Store                                     # noqa: E402


def test_the_team_door_tells_the_shell_where_the_person_is(tmp_path):
    env = executors.Envelope(workspace=str(tmp_path))
    executors.open_team_door(env, {}, None, None, None, None, surface="telegram")
    assert env.extra_env["AGENTOS_SURFACE"] == "telegram"
    env = executors.Envelope(workspace=str(tmp_path))
    executors.open_team_door(env, {}, None, None, None, None, surface="nonsense")
    assert env.extra_env["AGENTOS_SURFACE"] == "gui"


def test_the_terminal_acts_for_that_surface(monkeypatch):
    monkeypatch.setenv("AGENTOS_SURFACE", "telegram")
    assert cli._cli_surface() == "telegram"
    monkeypatch.setenv("AGENTOS_SURFACE", "../etc")
    assert cli._cli_surface() == "cli"
    monkeypatch.delenv("AGENTOS_SURFACE")
    assert cli._cli_surface() == "cli"


def test_a_company_started_from_telegram_moves_telegram(tmp_path):
    cfg, store = {"agent_name": "Aria"}, Store(tmp_path / "a.db")
    company.create(cfg, store, "Bhav Capital", surface="telegram")
    bhav = company.profile(cfg)["space_id"]
    cfg["spaces"]["active"]["gui"] = "desk-stays"
    company.create(cfg, store, "Bento Growth", surface="telegram")
    growth = company.profile(cfg)["space_id"]
    assert growth and growth != bhav
    assert cfg["spaces"]["active"]["telegram"] == growth
    assert cfg["spaces"]["active"]["gui"] == "desk-stays"


def test_the_routes_take_a_phone_surface_and_nothing_wider():
    from agentos import server
    assert server._client_surface("telegram", server.COMPANY_SURFACES) == "telegram"
    assert server._client_surface("whatsapp", server.COMPANY_SURFACES) == "whatsapp"
    assert server._client_surface("telegram") == "gui", "other routes are unchanged"
    assert server._client_surface("webhook", server.COMPANY_SURFACES) == "gui"
    src = inspect.getsource(server.api_companies_create) + inspect.getsource(server.api_companies_switch)
    assert src.count("COMPANY_SURFACES") == 2


def test_the_terminal_never_writes_behind_a_running_server():
    src = inspect.getsource(cli._company_cli)
    assert "up = _server_answers(port)\n" in src
    assert 'not getattr(args, "user"' not in src
    assert "Nothing was changed." in src and 'd.get("login")' in src
    several = src[src.index('if a in ("companies", "new", "open", "drop"):'):src.index('if a == "objective":')]
    assert '"cli"' not in several, "new and open act for the surface that asked"
