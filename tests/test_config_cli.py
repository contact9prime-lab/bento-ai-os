"""`bento config` — the settings file, from a terminal.

`~/.agentos/config.json` has always been there, and every documented way to change it
was either a GUI panel or a command that happened to own one key: "change the port"
lived under `bento remote`, which is filed under remote access and is not where
anybody looks for it. So people edited the JSON by hand, which works right up until a
missing comma makes the file unparseable — after which the server will not start and
the error names JSON, not the edit that caused it.

Two properties are load-bearing and both are about not making things worse than the
hand-editing they replace:

- **A broken edit is never saved.** `--edit` validates and rolls back.
- **Secrets are masked by default, deny-by-default on the key NAME.** `/api/config`
  uses an allowlist and it has already drifted — it masks provider keys, the Telegram
  token and the GitHub token while printing `remote.pass_hash` and every MCP server's
  credentials in full. An allowlist has to be updated by whoever adds the next
  provider; a name rule covers them without being asked.
"""

import argparse
import json

import pytest

from agentos import __main__ as m
from agentos import config as cfgmod


def _run(*argv, **kw):
    args = argparse.Namespace(key=kw.get("key", ""), value=kw.get("value"),
                              raw=kw.get("raw", False), path=kw.get("path", False),
                              edit=kw.get("edit", False))
    return m._config_cli(args)


# ------------------------------------------------------------------- reading

def test_path_prints_the_file(capsys):
    assert _run(path=True) == 0
    assert capsys.readouterr().out.strip() == str(cfgmod.CONFIG_PATH)


def test_a_missing_key_is_an_error_not_an_empty_line(capsys):
    """Printing nothing for a typo'd key reads as "that setting is empty", and the
    next move is to set a key that will never be read."""
    assert _run(key="nosuchthing") == 1
    assert "no such setting" in capsys.readouterr().out


def test_reading_a_nested_key(capsys):
    cfg = cfgmod.load_config()
    cfg.setdefault("remote", {})["bind"] = "0.0.0.0"
    cfgmod.save_config(cfg)
    assert _run(key="remote.bind") == 0
    assert capsys.readouterr().out.strip() == "0.0.0.0"


# ------------------------------------------------------------------- writing

def test_setting_a_value_persists_it(capsys):
    assert _run(key="autonomy", value="full") == 0
    assert cfgmod.load_config()["autonomy"] == "full"


def test_values_arrive_as_the_type_they_look_like():
    """`true` must not become the string "true" — a config full of truthy strings is
    a machine where every boolean is on."""
    _run(key="telegram.enabled", value="true")
    assert cfgmod.load_config()["telegram"]["enabled"] is True
    _run(key="port", value="8080")
    assert cfgmod.load_config()["port"] == 8080


def test_an_address_is_still_a_string():
    """0.0.0.0 is not valid JSON, and must not need quoting rules to set."""
    _run(key="remote.bind", value="0.0.0.0")
    assert cfgmod.load_config()["remote"]["bind"] == "0.0.0.0"


def test_a_nested_key_can_be_created_from_nothing():
    _run(key="a.b.c", value="1")
    assert cfgmod.load_config()["a"]["b"]["c"] == 1


def test_the_port_goes_through_the_same_check_as_remote_port(capsys):
    """One code path for both commands. Two would eventually disagree about whether
    a port is valid, or about warning that the boot service still holds the old one."""
    with pytest.raises(SystemExit):
        _run(key="port", value="99999")
    assert "1–65535" in capsys.readouterr().out


def test_a_non_numeric_port_is_refused(capsys):
    assert _run(key="port", value="abc") == 1
    assert "must be a number" in capsys.readouterr().out


# ------------------------------------------------------------------- secrets

def test_secrets_are_masked_by_default(capsys):
    cfg = cfgmod.load_config()
    cfg["providers"]["anthropic"]["api_key"] = "sk-ant-abcdefgh1234"
    cfgmod.save_config(cfg)
    _run(key="providers.anthropic.api_key")
    out = capsys.readouterr().out
    assert "sk-ant-abcdefgh1234" not in out
    assert "1234" in out, "masking should still show enough to recognise the key"


def test_raw_shows_them(capsys):
    cfg = cfgmod.load_config()
    cfg["providers"]["anthropic"]["api_key"] = "sk-ant-abcdefgh1234"
    cfgmod.save_config(cfg)
    _run(key="providers.anthropic.api_key", raw=True)
    assert "sk-ant-abcdefgh1234" in capsys.readouterr().out


def test_the_whole_dump_leaks_no_secret(capsys):
    cfg = cfgmod.load_config()
    cfg["providers"]["openai"]["api_key"] = "sk-openai-SECRETVALUE"
    cfg.setdefault("telegram", {})["bot_token"] = "12345:BOTTOKENSECRET"
    cfg.setdefault("remote", {})["pass_hash"] = "PASSHASHSECRET"
    cfg.setdefault("mcp", {})["servers"] = [{"name": "x", "auth_token": "MCPSECRET"}]
    cfgmod.save_config(cfg)
    _run()
    out = capsys.readouterr().out
    for secret in ("sk-openai-SECRETVALUE", "BOTTOKENSECRET", "PASSHASHSECRET",
                   "MCPSECRET"):
        assert secret not in out, f"{secret} was printed in full"


def test_masking_is_deny_by_default_on_the_key_name():
    """The property, not a fixed list: a provider added next week is covered without
    anybody editing this file or the redaction."""
    for name in ("api_key", "bot_token", "pass_hash", "client_secret",
                 "refresh_token", "PASSWORD", "someCredential"):
        assert m._looks_secret(name), f"{name} would be printed in full"
    for name in ("port", "bind", "enabled", "model", "autonomy"):
        assert not m._looks_secret(name), f"{name} is masked for no reason"


def test_setting_a_secret_does_not_echo_it_back(capsys):
    _run(key="providers.openai.api_key", value="sk-openai-BRANDNEW")
    assert "sk-openai-BRANDNEW" not in capsys.readouterr().out


# --------------------------------------------------------------------- --edit

def test_edit_rolls_back_an_edit_that_left_invalid_json(monkeypatch, capsys):
    """The whole reason to wrap $EDITOR rather than just print the path."""
    cfgmod.save_config(cfgmod.load_config())      # load_config reads; it does not write
    good = cfgmod.CONFIG_PATH.read_text()

    def wreck(cmd, **kw):
        cfgmod.CONFIG_PATH.write_text('{"port": 8080,,,}')

    monkeypatch.setattr(m.subprocess, "run", wreck)
    monkeypatch.setattr(m.shutil, "which", lambda x: "/usr/bin/vi")
    monkeypatch.setenv("EDITOR", "vi")

    assert _run(edit=True) == 1
    assert cfgmod.CONFIG_PATH.read_text() == good, "the broken edit was kept"
    out = capsys.readouterr().out
    assert "invalid JSON" in out and "NOT kept" in out
    json.loads(cfgmod.CONFIG_PATH.read_text())      # still parseable


def test_edit_keeps_a_valid_change(monkeypatch, capsys):
    cfgmod.save_config(cfgmod.load_config())

    def edit(cmd, **kw):
        cfgmod.CONFIG_PATH.write_text(json.dumps({"port": 8123}))

    monkeypatch.setattr(m.subprocess, "run", edit)
    monkeypatch.setattr(m.shutil, "which", lambda x: "/usr/bin/vi")
    monkeypatch.setenv("EDITOR", "vi")

    assert _run(edit=True) == 0
    assert json.loads(cfgmod.CONFIG_PATH.read_text())["port"] == 8123


# ------------------------------------------------------------------ the CLI wiring

def test_config_is_a_registered_subcommand():
    seen = {}
    real = argparse.ArgumentParser.parse_args

    def capture(self, *a, **k):
        seen["p"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        with pytest.raises(SystemExit):
            m.main()
    finally:
        argparse.ArgumentParser.parse_args = real
    sub = next(x for x in seen["p"]._actions
               if isinstance(x, argparse._SubParsersAction))
    assert "config" in sub.choices
    dests = {x.dest for x in sub.choices["config"]._actions}
    assert {"key", "value", "raw", "path", "edit"} <= dests
