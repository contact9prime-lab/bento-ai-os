"""An account reaches its own home and what is shared with it, through every door.

A workspace is the root of the Files app, of a forwarded CLI's folder and of the agent's jail, and
it was saved unchecked. Setting it to `/` read the session key and every account's vault, and from
those an admin's session could be forged (S-03, S-21). These run through the real routes.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient                           # noqa: E402

from agentos import config as cfgmod                                # noqa: E402
from agentos import executors as execmod                            # noqa: E402
from agentos import outputs                                         # noqa: E402
from agentos import server as servermod                             # noqa: E402
from agentos import tools as toolsmod                               # noqa: E402
from agentos import users as usersmod                               # noqa: E402


@pytest.fixture()
def running():
    usersmod.reset_caches()
    with TestClient(servermod.app) as cl:
        yield cl
    usersmod.reset_caches()


def _login(name, pw):
    c = TestClient(servermod.app)
    assert c.post("/api/users/login", json={"name": name, "password": pw}).status_code == 200
    return c


@pytest.fixture()
def two(running):
    a = usersmod.create("ada", "ada-password-1", role="admin")
    b = usersmod.create("bob", "bob-password-1")
    return a, b, _login("ada", "ada-password-1"), _login("bob", "bob-password-1")


@pytest.mark.parametrize("where", ["/", "/etc", "..", "~", "/tmp"])
def test_a_non_admin_cannot_save_a_workspace_outside_their_home(two, where):
    a, b, _, bob = two
    r = bob.put("/api/config", json={"workspace": where})
    assert r.status_code == 403 and "inside your own home" in r.json()["error"]
    assert usersmod.cfg_for(b["id"])["workspace"].startswith(str(usersmod.home_for(b["id"])))


def test_their_own_home_itself_is_not_a_workspace(two):
    """It would hand the Files app their database and vault key."""
    a, b, _, bob = two
    assert bob.put("/api/config", json={"workspace": str(usersmod.home_for(b["id"]))}).status_code == 403
    assert bob.put("/api/config", json={"workspace": str(usersmod.home_for(b["id"]) / "pki")}).status_code == 403
    assert bob.put("/api/config", json={"workspace": str(usersmod.home_for(b["id"]) / "projects")}).status_code == 200


def test_another_accounts_home_is_not_a_workspace(two):
    a, b, _, bob = two
    assert bob.put("/api/config", json={"workspace": str(usersmod.home_for(a["id"]) / "workspace")}).status_code == 403


def test_a_symlink_does_not_make_a_folder_yours(two):
    a, b, _, bob = two
    link = usersmod.home_for(b["id"]) / "ws"
    link.symlink_to(usersmod.home_for(a["id"]))
    assert bob.put("/api/config", json={"workspace": str(link)}).status_code == 403


def test_a_workspace_already_stored_is_not_believed_when_it_is_read(two):
    """A value saved before this check, or written by a tool: read falls back to their own."""
    a, b, _, bob = two
    p = usersmod.cfg_path_for(b["id"])
    d = json.loads(p.read_text())
    d["workspace"] = "/"
    p.write_text(json.dumps(d))
    usersmod.reset_caches()
    cfg = usersmod.cfg_for(b["id"])
    assert cfg["workspace"] == str(usersmod.home_for(b["id"]) / "workspace")
    # and a write straight into the live view (the agent's tools hold this dict)
    cfg["workspace"] = "/"
    assert usersmod.workspace_of(cfg) == str(usersmod.home_for(b["id"]) / "workspace")
    assert os.path.realpath(toolsmod.sandbox_conf(cfg)[1]) == os.path.realpath(usersmod.home_for(b["id"]) / "workspace")
    assert execmod.default_workspace(cfg) == str(usersmod.home_for(b["id"]) / "workspace")
    assert all(str(r).startswith(str(usersmod.home_for(b["id"]))) for r in outputs.roots(cfg, admin=False))
    usersmod.save_user_cfg(b["id"], cfg)
    assert cfg["workspace"] == str(usersmod.home_for(b["id"]) / "workspace")
    assert json.loads(p.read_text())["workspace"] == cfg["workspace"]


def test_an_admin_and_the_machine_keep_any_workspace(two, tmp_path):
    a, b, ada, _ = two
    assert ada.put("/api/config", json={"workspace": str(tmp_path)}).status_code == 200
    assert usersmod.workspace_problem("", "/") == ""


def test_a_machine_with_no_accounts_is_unchanged(running, tmp_path):
    assert running.put("/api/config", json={"workspace": str(tmp_path)}).status_code == 200


def test_a_forwarded_cli_cannot_be_given_another_accounts_folder(two):
    """S-21: the folder becomes --add-dir and the child's working folder."""
    a, b, _, _ = two
    cfg = usersmod.cfg_for(b["id"])
    other = str(usersmod.home_for(a["id"]) / "workspace")
    own = str(usersmod.home_for(b["id"]) / "workspace")
    with usersmod.as_user(b["id"]):
        assert execmod.envelope_from(cfg, other).workspace == own
        cfg.setdefault("executors", {}).setdefault("claude_code", {})["workspace"] = other
        assert execmod.envelope_from(cfg, own).workspace == own
        cfg["executors"]["claude_code"]["workspace"] = "/"
        assert execmod.envelope_from(cfg, own).workspace == own


def test_an_admins_executor_folder_still_wins_for_them(two, tmp_path):
    a, b, _, _ = two
    cfg = usersmod.cfg_for(a["id"])
    cfg.setdefault("executors", {}).setdefault("claude_code", {})["workspace"] = str(tmp_path)
    assert execmod.envelope_from(cfg, "/x").workspace == str(tmp_path)


def _secrets():
    from agentos import remote
    remote._machine_key()          # it signs the cookies these tests hold, so it is never rewritten
    return [Path(cfgmod.AGENTOS_HOME) / "session.key", usersmod.registry_path()]


def test_no_file_route_hands_over_the_keys_or_another_account(two):
    a, b, _, bob = two
    theirs = usersmod.home_for(a["id"]) / "workspace" / "private.txt"
    theirs.parent.mkdir(parents=True, exist_ok=True)
    theirs.write_text("ada's")
    for target in _secrets() + [theirs, usersmod.db_for(a["id"])]:
        r = bob.get("/api/files/get", params={"path": str(target)})
        assert r.status_code == 404, target
        assert bob.get("/api/files/raw", params={"path": str(target)}).status_code == 404, target
        assert bob.get("/api/files/raw", params={"path": "../../../" + target.name}).status_code == 404


def test_a_symlink_out_of_the_workspace_is_not_followed(two):
    a, b, _, bob = two
    ws = usersmod.home_for(b["id"]) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "out").symlink_to(_secrets()[0])
    assert bob.get("/api/files/raw", params={"path": "out"}).status_code == 404
    assert bob.get("/api/files/get", params={"path": str(ws / "out")}).status_code == 404


def test_a_person_still_gets_their_own_files_and_shared_ones(two, tmp_path):
    a, b, ada, bob = two
    ws = usersmod.home_for(b["id"]) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "mine.txt").write_text("bob's")
    assert bob.get("/api/files/get", params={"path": str(ws / "mine.txt")}).text == "bob's"
    assert bob.get("/api/files/raw", params={"path": "mine.txt"}).text == "bob's"
    assert any(e["name"] == "mine.txt" for e in bob.get("/api/files").json()["entries"])
    share = tmp_path / "team"
    share.mkdir()
    (share / "doc.txt").write_text("for bob")
    r = ada.put("/api/folders", json={"folders": [{"path": str(share), "mode": "ro", "users": [b["id"]]}]})
    assert r.status_code == 200, r.text
    assert bob.get("/api/files", params={"root": str(share.resolve())}).status_code == 200
    assert bob.get("/api/files/get", params={"path": str(share / "doc.txt")}).text == "for bob"


def test_a_reply_cannot_name_a_key_file_into_a_chip(two):
    home = Path(cfgmod.AGENTOS_HOME)
    _secrets()
    assert outputs.reachable(str(home / "session.key"), [home.resolve()]) is None


# --- one person's nested write stays theirs (S-31) ---------------------------------------------

def test_a_non_admins_setup_cannot_change_a_provider_key_for_everyone(two):
    a, b, ada, bob = two
    machine = servermod.state.machine_cfg()
    was = machine["providers"]["openai"].get("api_key", "")
    r = bob.post("/api/setup", json={"providers": {"openai": {"api_key": "sk-bobs-own-server"}}})
    assert r.status_code == 200
    assert "admin" in r.json()["report"]["held"]
    assert machine["providers"]["openai"].get("api_key", "") == was
    assert usersmod.cfg_for(a["id"])["providers"]["openai"].get("api_key", "") == was
    assert usersmod.cfg_for(b["id"])["providers"]["openai"].get("api_key", "") == was


def test_a_new_account_finishes_the_wizard(two):
    a, b, _, bob = two
    assert bob.post("/api/setup", json={"agent_name": "Bobby", "default_model": "x/y"}).status_code == 200
    assert usersmod.cfg_for(b["id"])["agent_name"] == "Bobby"


def test_views_share_no_nested_dict_with_the_machine_or_each_other(two):
    a, b, _, _ = two
    machine = servermod.state.machine_cfg()
    ca, cb = usersmod.cfg_for(a["id"]), usersmod.cfg_for(b["id"])
    cb["providers"]["openai"]["base_url"] = "https://evil.example"
    assert machine["providers"]["openai"]["base_url"] != "https://evil.example"
    assert ca["providers"]["openai"]["base_url"] != "https://evil.example"


def test_an_admins_machine_save_reaches_everyone_and_still_no_alias(two):
    """CLAUDE.md: an admin's machine save must reach the server's own machine dict."""
    a, b, ada, _ = two
    machine = servermod.state.machine_cfg()
    ca, cb = usersmod.cfg_for(a["id"]), usersmod.cfg_for(b["id"])
    with usersmod.as_user(a["id"]):
        ca["providers"]["openai"]["api_key"] = "sk-admins"
        cfgmod.save_config(ca)
    assert machine["providers"]["openai"]["api_key"] == "sk-admins"
    assert cb["providers"]["openai"]["api_key"] == "sk-admins"
    # the push must not leave them sharing the object again
    cb["providers"]["openai"]["api_key"] = "sk-bobs"
    assert machine["providers"]["openai"]["api_key"] == "sk-admins"
    assert ca["providers"]["openai"]["api_key"] == "sk-admins"
    # a section the admin's code still holds stays live: a later write through it is saved
    held = ca.setdefault("team", {})
    with usersmod.as_user(a["id"]):
        cfgmod.save_config(ca)
    held["talk"] = "swarm"
    assert ca["team"]["talk"] == "swarm"
    with usersmod.as_user(a["id"]):
        cfgmod.save_config(ca)
    assert machine["team"]["talk"] == "swarm" and cb["team"]["talk"] == "swarm"


def test_the_machines_own_save_reaches_the_accounts(two):
    a, b, _, _ = two
    machine = servermod.state.machine_cfg()
    cb = usersmod.cfg_for(b["id"])
    with usersmod.as_user(""):
        machine.setdefault("team", {})["listen"] = True
        cfgmod.save_config(machine)
    assert cb["team"]["listen"] is True
    assert cb["team"] is not machine["team"]


# --- what /api/config says (S-38) ---------------------------------------------------------------

def test_a_secret_named_key_is_masked_at_any_depth(two):
    a, b, _, bob = two
    cfg = usersmod.cfg_for(b["id"])
    cfg["tools"] = {"deep": {"deeper": {"some_api_key": "sk-nested-secret-1234", "label": "fine"}}}
    cfg["mcp_servers"] = {"x": {"transport": "http", "url": "https://x.example/", "auth": "oauth",
                                "env": {"PLAIN_NAME": "value-with-no-tell"},
                                "headers": {"X-Whatever": "h-value-secret"}}}
    got = bob.get("/api/config").json()
    text = json.dumps(got)
    assert "sk-nested-secret" not in text and "value-with-no-tell" not in text and "h-value-secret" not in text
    assert got["tools"]["deep"]["deeper"]["label"] == "fine"
    assert got["mcp_servers"]["x"]["auth"] == "oauth", "how a server signs in is not a secret"


def test_the_speech_key_and_password_hash_never_leave(two):
    a, b, ada, bob = two
    machine = servermod.state.machine_cfg()
    machine["remote"] = {**(machine.get("remote") or {}), "pass_hash": "HASH-VALUE", "pass_salt": "SALT-VALUE"}
    machine["speech"] = {"elevenlabs": {"api_key": "el-secret-12345678"}}
    with usersmod.as_user(a["id"]):
        cfgmod.save_config(usersmod.cfg_for(a["id"]))
    usersmod.machine_changed(machine)
    for c in (ada, bob):
        text = c.get("/api/config").text
        assert "HASH-VALUE" not in text and "SALT-VALUE" not in text and "el-secret" not in text
        assert "pass_hash" not in text


def test_a_single_user_box_masks_channels_and_peer_keys_too(running):
    cfg = servermod.state.machine_cfg()
    cfg["channels"] = {"x": {"webhook_secret": "shh-this-is-secret"}}
    cfg["agent_share"] = {"peers": {"p": {"key": "peer-key-long-value"}}}
    text = running.get("/api/config").text
    assert "shh-this-is-secret" not in text and "peer-key-long-value" not in text


def test_the_settings_page_can_send_back_what_it_read(running):
    """The page holds masks. A provider's and a tool server's must not overwrite the real value."""
    cfg = servermod.state.machine_cfg()
    cfg["providers"]["openai"]["api_key"] = "sk-the-real-provider-key"
    cfg["mcp_servers"] = {"x": {"transport": "http", "url": "https://x.example/", "enabled": False,
                                "env": {"NAME": "real-env-value-long"},
                                "headers": {"Authorization": "Bearer real-token-long"}}}
    got = running.get("/api/config").json()
    assert running.put("/api/config", json={"providers": {"openai": got["providers"]["openai"]}}).status_code == 200
    assert cfg["providers"]["openai"]["api_key"] == "sk-the-real-provider-key"
    sent = {"x": {**got["mcp_servers"]["x"], "enabled": False}}
    sent["x"]["env"] = {**sent["x"]["env"], "ADDED": "new-value"}
    assert running.put("/api/mcp", json={"servers": sent}).status_code == 200
    now = cfg["mcp_servers"]["x"]
    assert now["env"] == {"NAME": "real-env-value-long", "ADDED": "new-value"}
    assert now["headers"]["Authorization"] == "Bearer real-token-long"
    # the MCP app reads /api/mcp, and the same rule covers what it shows
    status = running.get("/api/mcp").json()["servers"][0]
    assert "real-env-value" not in json.dumps(status)


# --- sign-ins in progress (S-80) -----------------------------------------------------------------

def test_a_pending_sign_in_is_shown_only_to_its_own_account(two):
    from agentos import signin
    a, b, ada, bob = two
    signin._pending["st8"] = {"provider": "google", "verifier": "v", "uses": ["mail"], "uid": a["id"],
                              "started": __import__("time").time(), "url": "https://consent/?state=st8"}
    try:
        assert ada.get("/api/accounts").json()["pending"][0]["url"].endswith("st8")
        assert bob.get("/api/accounts").json()["pending"] == []
        with usersmod.as_user(b["id"]):
            bob.delete("/api/accounts/oauth/google")
        assert "st8" in signin._pending, "another account's sign-out cancelled it"
    finally:
        signin._pending.pop("st8", None)
