"""An account's tool servers run as that account, and a sign-in is that account's.

`PUT /api/mcp` used to start any program as the server's user with its whole environment, so a
non-admin read every home (S-05). OAuth tokens lived per machine by server name, so naming a
server after an admin's handed over their token (S-42). Real processes where it matters.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient                           # noqa: E402

from agentos import config as cfgmod                                # noqa: E402
from agentos import mcp_client, mcp_oauth                           # noqa: E402
from agentos import server as servermod                             # noqa: E402
from agentos import tools as toolsmod                               # noqa: E402
from agentos import users as usersmod                               # noqa: E402


@pytest.fixture()
def two(tmp_path):
    usersmod.reset_caches()
    a = usersmod.create("ada", "ada-password-1", role="admin")
    b = usersmod.create("bob", "bob-password-1")
    yield a, b
    usersmod.reset_caches()


@pytest.fixture()
def bob_client(two):
    with TestClient(servermod.app):
        c = TestClient(servermod.app)
        assert c.post("/api/users/login", json={"name": "bob", "password": "bob-password-1"}).status_code == 200
        yield c


def test_an_account_program_is_jailed(two, monkeypatch):
    a, b = two
    monkeypatch.setattr(toolsmod, "sandbox_mechanism", lambda: "bwrap")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-server")
    monkeypatch.setenv("BENTO_STORAGE_SECRET", "storage-secret")
    with usersmod.as_user(b["id"]):
        exe, argv, env = mcp_client.stdio_launch({"command": "/bin/sh", "args": "-c true",
                                                  "env": {"MINE": "1", "LD_PRELOAD": "/x/evil.so"}})
    assert exe.endswith("bwrap")
    assert "/bin/sh" in argv and "--tmpfs" in argv
    assert str(usersmod.home_for(b["id"]) / "workspace") in argv, "its own workspace, never its whole home"
    assert os.path.realpath(cfgmod.AGENTOS_HOME) in argv, "the machine's home is blanked"
    assert env.get("MINE") == "1"
    assert "LD_PRELOAD" not in env, "set on the jail program, it would run before the jail exists"
    assert "ANTHROPIC_API_KEY" not in env and "BENTO_STORAGE_SECRET" not in env


@pytest.mark.skipif(not shutil.which("bwrap"), reason="needs bubblewrap")
def test_a_jailed_program_gets_its_own_settings_and_none_of_them_on_a_command_line(two):
    """Its API key is what its settings are for. --clearenv would drop it, --setenv would show it."""
    a, b = two
    if not toolsmod.sandbox_mechanism():
        pytest.skip("this machine cannot enter a jail")
    with usersmod.as_user(b["id"]):
        exe, argv, env = mcp_client.stdio_launch({"command": "/bin/sh", "args": "-c 'echo got:$MINE:$HOME'",
                                                  "env": {"MINE": "s3cret"}})
    assert not any("s3cret" in a for a in argv)
    out = subprocess.run([exe, *argv], env=env, capture_output=True, text=True, timeout=20).stdout
    assert out.startswith("got:s3cret:") and out.strip().endswith("workspace")


def test_with_no_jail_an_account_program_does_not_start(two, monkeypatch):
    """Fail closed: there is no bare fallback, whichever door wrote the server."""
    a, b = two
    monkeypatch.setattr(toolsmod, "sandbox_mechanism", lambda: "")
    with usersmod.as_user(b["id"]):
        with pytest.raises(RuntimeError, match="bubblewrap"):
            mcp_client.stdio_launch({"command": "/bin/sh"})
        srv = mcp_client.MCPServer("x", {"command": "/bin/sh"})

        async def go():
            async def on(_s):
                pass
            await srv._run(on)
        asyncio.run(go())
    assert srv.status == "error" and "bubblewrap" in srv.error


def test_the_route_says_so_before_saving(bob_client, monkeypatch):
    monkeypatch.setattr(toolsmod, "sandbox_mechanism", lambda: "")
    r = bob_client.put("/api/mcp", json={"servers": {"x": {"command": "/bin/sh"}}})
    assert r.status_code == 403 and "bubblewrap" in r.json()["error"]
    b = usersmod.by_name("bob")
    assert not usersmod.cfg_for(b["id"]).get("mcp_servers")


@pytest.mark.skipif(not shutil.which("bwrap"), reason="needs bubblewrap")
def test_a_jailed_program_really_cannot_read_the_machine(two):
    """The real jail: what this finding's proof read, it now cannot."""
    a, b = two
    with usersmod.as_user(b["id"]):
        probe = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"],
                               capture_output=True)
        if probe.returncode:
            pytest.skip("unprivileged user namespaces are off here")
        vault = usersmod.home_for(a["id"]) / "vault.key"
        vault.write_text("ada's key")
        session = Path(cfgmod.AGENTOS_HOME) / "session.key"
        session.write_text("the session key")
        exe, argv, env = mcp_client.stdio_launch(
            {"command": "/bin/sh",
             "args": f"-c 'cat {vault} {session} 2>/dev/null; echo end; echo $HOME'"})
        out = subprocess.run([exe, *argv], env=env, capture_output=True, text=True, timeout=20)
    assert "ada's key" not in out.stdout and "the session key" not in out.stdout
    assert str(usersmod.home_for(b["id"])) in out.stdout


def test_an_admin_program_still_runs_bare_without_the_servers_secrets(two, monkeypatch):
    a, b = two
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server")
    monkeypatch.setenv("BENTO_STORAGE_KEY", "x")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy")
    for uid in (a["id"], ""):
        with usersmod.as_user(uid):
            exe, argv, env = mcp_client.stdio_launch({"command": "/bin/sh", "args": "-c true", "env": {"MINE": "1"}})
        assert exe == "/bin/sh" and argv == ["-c", "true"]
        assert env["MINE"] == "1" and env["HTTPS_PROXY"] == "http://proxy"
        assert "OPENAI_API_KEY" not in env and "BENTO_STORAGE_KEY" not in env


@pytest.mark.parametrize("url", ["http://127.0.0.1:8321/api", "http://localhost/", "http://[::1]/",
                                 "http://169.254.169.254/latest", "http://10.0.0.5/", "http://192.168.1.1/",
                                 "http://[::ffff:127.0.0.1]/", "http://printer.local/", "ftp://x.example/", "file:///etc/passwd"])
def test_an_account_cannot_point_a_server_inside_this_network(two, url):
    a, b = two
    with usersmod.as_user(b["id"]):
        assert mcp_client.refusal({"transport": "http", "url": url})
    with usersmod.as_user(a["id"]):
        assert mcp_client.refusal({"transport": "http", "url": url}) == ""


def test_a_public_server_is_fine_for_an_account(two):
    a, b = two
    with usersmod.as_user(b["id"]):
        assert mcp_client.refusal({"transport": "http", "url": "https://mcp.notion.com/mcp"}) == ""


def test_a_name_that_resolves_inside_is_refused_when_it_connects(two, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))])
    with pytest.raises(RuntimeError):
        mcp_client._resolves_public("https://looks-public.example/")


# --- tokens ---------------------------------------------------------------------------------------

NOTION = "https://mcp.notion.com/mcp"


def _tokens(name, url, uid, value="tok"):
    mcp_oauth._write(name, url, {"tokens": {"access_token": value, "token_type": "Bearer"}}, uid)


def test_another_account_naming_the_server_gets_no_token(two):
    a, b = two
    _tokens("notion", NOTION, a["id"], "ada-token")
    with usersmod.as_user(a["id"]):
        assert mcp_oauth.has_tokens("notion", NOTION)
    with usersmod.as_user(b["id"]):
        assert not mcp_oauth.has_tokens("notion", NOTION), "the real URL gave them her Notion"
        assert not mcp_oauth.has_tokens("notion", "https://bobs.example/mcp")
        assert not mcp_oauth.forget("notion"), "forgetting is not theirs either"
    with usersmod.as_user(a["id"]):
        assert mcp_oauth.has_tokens("notion", NOTION)


def test_her_own_server_at_another_address_gets_no_token(two):
    """A token goes where it was issued: the SDK would add it before any discovery."""
    a, b = two
    _tokens("notion", NOTION, a["id"])
    with usersmod.as_user(a["id"]):
        assert not mcp_oauth.has_tokens("notion", "https://evil.example/mcp")


def test_the_storage_the_sdk_uses_is_the_same_path(two):
    if not mcp_oauth.HAVE_OAUTH:
        pytest.skip("old SDK")
    from mcp.shared.auth import OAuthToken
    a, b = two
    st = mcp_oauth._Storage("notion", NOTION, a["id"])
    asyncio.run(st.set_tokens(OAuthToken(access_token="x", token_type="Bearer")))
    assert asyncio.run(st.get_tokens()).access_token == "x"
    assert asyncio.run(mcp_oauth._Storage("notion", NOTION, b["id"]).get_tokens()) is None
    assert asyncio.run(mcp_oauth._Storage("notion", "https://e.example", a["id"]).get_tokens()) is None
    p = mcp_oauth._token_path("notion", NOTION, a["id"])
    assert str(p).startswith(str(usersmod.home_for(a["id"])))
    assert (p.stat().st_mode & 0o777) == 0o600


def _legacy(name="notion"):
    p = Path(cfgmod.AGENTOS_HOME) / "oauth" / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"tokens": {"access_token": "old", "token_type": "Bearer"}}))
    return p


def test_an_old_token_goes_to_the_owner_and_keeps_the_connection(two):
    a, b = two
    old = _legacy()
    with usersmod.as_user(b["id"]):
        assert not mcp_oauth.has_tokens("notion", NOTION), "not a later account's"
    assert old.exists()
    with usersmod.as_user(a["id"]):
        assert mcp_oauth.has_tokens("notion", NOTION)
    assert not old.exists(), "moved once"
    with usersmod.as_user(a["id"]):
        assert mcp_oauth.has_tokens("notion", NOTION)


def test_an_old_token_on_a_machine_with_no_accounts_stays_connected():
    usersmod.reset_caches()
    assert not usersmod.enabled()
    _legacy()
    assert mcp_oauth.has_tokens("notion", NOTION)
    assert mcp_oauth.forget("notion")
    assert not mcp_oauth.has_tokens("notion", NOTION)


def test_a_consent_in_progress_is_its_owners(two):
    a, b = two
    p = mcp_oauth.Pending("notion", "https://consent/?state=abc", a["id"])
    mcp_oauth._pending[(a["id"], "notion")] = p
    try:
        with usersmod.as_user(a["id"]):
            assert mcp_oauth.pending_url("notion")
            assert mcp_oauth.pending_status()[0]["name"] == "notion"
        with usersmod.as_user(b["id"]):
            assert not mcp_oauth.pending_url("notion")
            assert mcp_oauth.pending_status() == []
            assert not mcp_oauth.resolve("notion", "bobs-code", "abc"), "their browser finishes nothing"
            assert not mcp_oauth.cancel("notion")
        assert not p.event.is_set()
    finally:
        mcp_oauth._pending.clear()
