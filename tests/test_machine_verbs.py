"""The things Settings can do, sayable in a sentence.

Every one of these already had a control and an HTTP route, and no way to ask for
it — so "update bento" in chat could not work and the answer was always "open
Settings and click", which on a headless box is not an answer.

Two properties matter more than the plumbing, and both are what these test:

  · ADMIN ONLY, from the same check /api/config uses. These are machine keys; a
    non-admin is refused with the reason rather than silently changing nothing.
  · EACH HAS ITS OWN ACTION. "May update my machine" and "may read a file" have to
    be grantable apart, which is the whole reason the action vocabulary exists
    rather than one `tool.use` string per tool name.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import config as cfgmod                       # noqa: E402
from agentos import users as usersmod                      # noqa: E402
from agentos.policy import action_of                       # noqa: E402
from agentos.tools import TOOL_SCHEMAS, Toolbox            # noqa: E402


def _tb(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    cfg = {"workspace": str(ws), "autonomy": "balanced", "policies": [],
           "default_model": "m", "sandbox": {"enabled": True, "root": str(ws),
                                             "folders": []}}
    return Toolbox(cfg, None), cfg


# ------------------------------------------------------- their own actions

@pytest.mark.parametrize("name,args,action", [
    ("update_agentos", {}, "system.update"),
    ("set_engine", {"engine": "hermes"}, "system.engine"),
    ("share_folder", {"path": "/data"}, "folder.share"),
    ("list_folders", {}, "folder.read"),
])
def test_each_verb_has_its_own_action(name, args, action):
    """Another `tool.use` string would mean a grant written for one silently
    carries the others."""
    assert action_of(name, args)[0] == action


def test_the_resource_names_what_is_being_touched():
    """A grant has to be able to say WHICH folder, not just 'folders'."""
    assert action_of("share_folder", {"path": "/data"})[1] == "fs:/data"
    assert action_of("set_engine", {"engine": "hermes"})[1] == "engine:hermes"


def test_every_verb_is_declared_to_the_model():
    """A method the model cannot see is a method that cannot be asked for."""
    names = {s["name"] for s in TOOL_SCHEMAS}
    for n in ("update_agentos", "share_folder", "list_folders", "set_engine"):
        assert n in names, f"{n} exists but is not in TOOL_SCHEMAS"


# ------------------------------------------------------------- admin only

@pytest.mark.asyncio
async def test_a_non_admin_is_refused_with_a_reason(tmp_path, monkeypatch):
    """Refused, not silently ignored — the difference between "you cannot" and a
    control that appears to work and does nothing."""
    tb, _ = _tb(tmp_path, monkeypatch)
    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "is_admin", lambda uid: False)
    d = tmp_path / "d"
    d.mkdir()
    with usersmod.as_user("bob"):
        assert "[denied]" in await tb.share_folder(str(d), "ro")
        assert "[denied]" in await tb.set_engine("aria")
        assert "[denied]" in await tb.update_agentos()


@pytest.mark.asyncio
async def test_an_admin_may(tmp_path, monkeypatch):
    tb, cfg = _tb(tmp_path, monkeypatch)
    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "is_admin", lambda uid: True)
    monkeypatch.setattr(usersmod, "users_root", lambda: tmp_path / "users")
    d = tmp_path / "d"
    d.mkdir()
    with usersmod.as_user("ada"):
        assert "[denied]" not in await tb.share_folder(str(d), "ro")
    assert cfg["sandbox"]["folders"][0]["path"] == str(d)


@pytest.mark.asyncio
async def test_reading_is_not_gated(tmp_path, monkeypatch):
    """Knowing which folders are open is not a machine change, and refusing it
    would leave an executor unable to find out what they may reach."""
    tb, _ = _tb(tmp_path, monkeypatch)
    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "is_admin", lambda uid: False)
    with usersmod.as_user("bob"):
        assert "[denied]" not in await tb.list_folders()


@pytest.mark.asyncio
async def test_a_machine_with_no_accounts_refuses_nobody(tmp_path, monkeypatch):
    """`is_admin('')` is True for the same reason it is everywhere else: a machine
    with no accounts has nobody to refuse."""
    tb, _ = _tb(tmp_path, monkeypatch)
    d = tmp_path / "d"
    d.mkdir()
    assert "[denied]" not in await tb.share_folder(str(d), "ro")


# --------------------------------------------------- they refuse the same way

@pytest.mark.asyncio
async def test_share_folder_refuses_what_the_ui_refuses(tmp_path, monkeypatch):
    """One validator, so the answer cannot differ by which face asked."""
    tb, _ = _tb(tmp_path, monkeypatch)
    assert "[denied]" in await tb.share_folder("/")
    assert "[denied]" in await tb.share_folder(str(tmp_path / "ghost"))


@pytest.mark.asyncio
async def test_share_folder_carries_the_caution(tmp_path, monkeypatch):
    """The same sentence the picker shows while you type it."""
    tb, _ = _tb(tmp_path, monkeypatch)
    assert "operating system" in await tb.share_folder("/etc", "rw")


@pytest.mark.asyncio
async def test_set_engine_refuses_one_that_is_not_installed(tmp_path, monkeypatch):
    tb, _ = _tb(tmp_path, monkeypatch)
    from agentos import executors as execmod
    monkeypatch.setattr(execmod, "probe", lambda eid: {"installed": False,
                                                       "why_not": "not installed"})
    assert "[denied]" in await tb.set_engine("hermes")


@pytest.mark.asyncio
async def test_set_engine_refuses_a_name_that_is_not_an_engine(tmp_path, monkeypatch):
    tb, _ = _tb(tmp_path, monkeypatch)
    assert "[error]" in await tb.set_engine("nonsense")
