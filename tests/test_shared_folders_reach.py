"""A folder an admin shares reaches the agent, whichever brain answers and whichever app looks.

Reported as "while I allow certain folders to be available to the users it doesn't
detect them". Five things were wrong, each found by following one share through:

- On a machine with accounts an admin's save never reached the server's own copy of
  the machine config, so `/api/folders` listed nothing after a successful save and
  the Users app showed the folder gone. The Terminal's jail reads the same copy.
- A share made by name (`bento folders add --users ada`) never matched: accounts are
  random hex ids and the check compared ids only.
- A forwarded turn (Claude Code, Gemini CLI, Codex) was given the workspace and
  nothing else, so the CLI could not open the folder at all.
- The built-in agent's prompt said "work inside that folder" and named no share.
- File chips, downloads, Telegram's send and the Files app knew only the workspace.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import executors as ex                                # noqa: E402
from agentos import outputs                                        # noqa: E402
from agentos import tools as toolsmod                              # noqa: E402
from agentos import users as usersmod                              # noqa: E402


def _cfg(tmp_path, shares):
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return {"workspace": str(ws), "autonomy": "balanced", "policies": [], "default_model": "m",
            "sandbox": {"enabled": True, "root": str(ws), "folders": shares}}


def _dirs(tmp_path):
    ro, rw = tmp_path / "reports", tmp_path / "drop box"
    ro.mkdir(); rw.mkdir()
    return str(ro), str(rw)


# ------------------------------------------------------------ saving and listing

def test_an_admins_share_is_listed_after_the_save(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    usersmod.create("ada", "ada-password-1", role="admin")
    bob = usersmod.create("bob", "bob-password-1")
    data = tmp_path / "reports"
    data.mkdir()
    with TestClient(servermod.app) as cl:
        assert cl.post("/api/users/login",
                       json={"name": "ada", "password": "ada-password-1"}).status_code == 200
        r = cl.put("/api/folders", json={"folders": [
            {"path": str(data), "mode": "ro", "users": ["bob"]}]}).json()
        assert r["ok"] and not r["refused"]
        listed = cl.get("/api/folders").json()["folders"]
        assert [s["path"] for s in listed] == [str(data.resolve())], \
            "the save worked and the list came back empty"
        # stored as the account's id, so a rename cannot move it to somebody else
        assert listed[0]["users"] == [bob["id"]]
        assert servermod.state.machine_cfg()["sandbox"]["folders"][0]["path"] == str(data.resolve())


def test_a_share_for_somebody_who_does_not_exist_is_refused(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    usersmod.create("ada", "ada-password-1", role="admin")
    data = tmp_path / "reports"
    data.mkdir()
    with TestClient(servermod.app) as cl:
        cl.post("/api/users/login", json={"name": "ada", "password": "ada-password-1"})
        r = cl.put("/api/folders", json={"folders": [
            {"path": str(data), "mode": "ro", "users": ["nobody"]}]}).json()
        assert r["refused"] and "nobody" in r["refused"][0]["why"]
        assert cl.get("/api/folders").json()["folders"] == []


def test_a_share_made_by_name_reaches_that_account(tmp_path):
    ada = usersmod.create("ada", "ada-password-1", role="admin")
    bob = usersmod.create("bob", "bob-password-1")
    ro, _ = _dirs(tmp_path)
    cfg = _cfg(tmp_path, [{"path": ro, "mode": "ro", "users": ["bob"]}])
    assert [s["path"] for s in toolsmod.shares_for(cfg, bob["id"])] == [ro]
    assert toolsmod.shares_for(cfg, ada["id"]) == []
    assert toolsmod.share_label(["bob"]) == "bob"
    assert toolsmod.share_label([bob["id"]]) == "bob"


def test_names_become_ids_and_strangers_are_named():
    bob = usersmod.create("bob", "bob-password-1")
    ids, unknown = toolsmod.share_users(["Bob", "zed", bob["id"]])
    assert ids == [bob["id"]] and unknown == ["zed"]


# ------------------------------------------------------------ forwarded turns

def test_claude_code_is_handed_every_share_and_keeps_read_only_ones_read_only(tmp_path):
    ro, rw = _dirs(tmp_path)
    cfg = _cfg(tmp_path, [{"path": ro, "mode": "ro", "users": []},
                          {"path": rw, "mode": "rw", "users": []}])
    cfg["executors"] = {"claude_code": {"tools": ["Read", "Write", "Edit"]}}
    env = ex.envelope_from(cfg, cfg["workspace"])
    assert env.shares == ((ro, "ro"), (rw, "rw"))
    cmd = ex.build_command("tidy the reports", env)
    dirs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--add-dir"]
    assert ro in dirs and rw in dirs
    deny = cmd[cmd.index("--disallowedTools") + 1]
    assert deny == f"Edit(/{ro}/**)", deny          # `//abs/path` is its absolute form
    assert not any(rw in a for a in cmd[cmd.index("--disallowedTools"):cmd.index("--disallowedTools") + 3])
    prompt = cmd[cmd.index("--append-system-prompt") + 1]
    assert f"{ro} (read only)" in prompt and f"{rw} (read and write)" in prompt
    assert "2 shared folders" in env.describe()


def test_a_read_only_run_needs_no_deny_rule(tmp_path):
    ro, _ = _dirs(tmp_path)
    cfg = _cfg(tmp_path, [{"path": ro, "mode": "ro", "users": []}])
    cmd = ex.build_command("read it", ex.envelope_from(cfg, cfg["workspace"]))
    assert ro in cmd and "--disallowedTools" not in cmd


def test_gemini_cannot_keep_a_folder_read_only_so_a_writing_run_says_so(tmp_path):
    ro, rw = _dirs(tmp_path)
    cfg = _cfg(tmp_path, [{"path": ro, "mode": "ro", "users": []},
                          {"path": rw, "mode": "rw", "users": []}])
    cfg["executors"] = {"claude_code": {"tools": ["Read", "Write"]}}
    cmd = ex.build_command("x", ex.envelope_from(cfg, cfg["workspace"], "gemini-cli"))
    inc = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--include-directories"]
    assert inc == [rw]
    prompt = cmd[cmd.index("--prompt") + 1]
    assert "Not available in this run" in prompt and ro in prompt
    # read-only, it gets both
    cfg["executors"] = {"claude_code": {"tools": ["Read"]}}
    cmd = ex.build_command("x", ex.envelope_from(cfg, cfg["workspace"], "gemini-cli"))
    assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "--include-directories"] == [ro, rw]


def test_codex_gets_the_writable_shares_when_it_may_write(tmp_path):
    ro, rw = _dirs(tmp_path)
    cfg = _cfg(tmp_path, [{"path": ro, "mode": "ro", "users": []},
                          {"path": rw, "mode": "rw", "users": []}])
    cfg["executors"] = {"claude_code": {"tools": ["Read", "Edit"]}}
    cmd = ex.build_command("x", ex.envelope_from(cfg, cfg["workspace"], "codex"))
    assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "--add-dir"] == [rw]
    assert ro in cmd[-1], "the prompt names the read-only share it can read"
    cfg["executors"] = {"claude_code": {"tools": ["Read"]}}
    cmd = ex.build_command("x", ex.envelope_from(cfg, cfg["workspace"], "codex"))
    assert "--add-dir" not in cmd


def test_a_share_for_somebody_else_is_not_handed_over(tmp_path):
    usersmod.create("ada", "ada-password-1", role="admin")
    bob = usersmod.create("bob", "bob-password-1")
    ro, _ = _dirs(tmp_path)
    cfg = _cfg(tmp_path, [{"path": ro, "mode": "ro", "users": ["ada"]}])
    with usersmod.as_user(bob["id"]):
        env = ex.envelope_from(cfg, cfg["workspace"])
    assert env.shares == () and ro not in ex.build_command("x", env)


# ------------------------------------------------------------ the built-in agent

def test_the_built_in_agent_is_told_its_shared_folders(tmp_path):
    from agentos.agent import Agent
    from agentos.memory import Store
    from agentos.policy import PDP
    ro, rw = _dirs(tmp_path)
    c = {**_cfg(tmp_path, [{"path": ro, "mode": "ro", "users": []},
                           {"path": rw, "mode": "rw", "users": []}]),
         "agent_name": "Arie", "max_steps": 4, "providers": {}, "port": 8321,
         "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = toolsmod.Toolbox(c, store)
    tb.pdp = PDP(c, store)

    async def emit(ev):
        pass

    async def approver(*a, **k):
        return True
    system = asyncio.run(Agent(c, tb, "ollama/x", emit, approver)._system("what is in reports?"))
    assert "SHARED FOLDERS" in system
    assert f"{ro} (read only)" in system and f"{rw} (read and write)" in system


# ------------------------------------------------------------ files people open

def test_a_file_in_a_share_can_be_handed_over(tmp_path):
    ro, _ = _dirs(tmp_path)
    (Path(ro) / "q3.csv").write_text("a,b\n")
    cfg = _cfg(tmp_path, [{"path": ro, "mode": "ro", "users": []}])
    rts = outputs.roots(cfg, admin=False)
    assert Path(ro) in rts
    assert outputs.reachable(str(Path(ro) / "q3.csv"), rts) is not None


def test_the_files_app_browses_a_share_and_nothing_else(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import config as cfgmod
    from agentos import server as servermod
    ro, _ = _dirs(tmp_path)
    (Path(ro) / "q3.csv").write_text("a,b\n")
    (Path(ro) / "sub").mkdir()
    other = tmp_path / "private"
    other.mkdir()
    with TestClient(servermod.app) as cl:
        cfg = servermod.state["cfg"]
        cfg.setdefault("sandbox", {})["folders"] = [{"path": ro, "mode": "ro", "users": []}]
        cfgmod.save_config(cfg)
        d = cl.get("/api/files").json()
        assert [p["root"] for p in d["places"]] == ["", ro]
        d = cl.get("/api/files", params={"root": ro}).json()
        assert {e["name"] for e in d["entries"]} == {"q3.csv", "sub"}
        assert d["mode"] == "ro"
        assert next(e for e in d["entries"] if e["name"] == "q3.csv")["full"] == str(Path(ro) / "q3.csv")
        # a folder that is not shared is refused, and climbing out stays inside
        assert cl.get("/api/files", params={"root": str(other)}).status_code == 404
        d = cl.get("/api/files", params={"root": ro, "path": "../private"}).json()
        assert d["path"] == "" and {e["name"] for e in d["entries"]} == {"q3.csv", "sub"}


def test_the_list_tool_shows_somebody_only_their_own_shares(tmp_path):
    usersmod.create("ada", "ada-password-1", role="admin")
    bob = usersmod.create("bob", "bob-password-1")
    ro, rw = _dirs(tmp_path)
    cfg = _cfg(tmp_path, [{"path": ro, "mode": "ro", "users": ["ada"]},
                          {"path": rw, "mode": "rw", "users": ["bob"]}])
    tb = toolsmod.Toolbox(cfg, None)
    with usersmod.as_user(bob["id"]):
        out = asyncio.run(tb.list_folders())
    assert rw in out and ro not in out and "(bob)" in out


@pytest.mark.parametrize("raw", [[("relative/path", "rw")], [("/x", "rw"), ("/x", "ro")], ["bad"]])
def test_the_envelope_keeps_only_sane_shares(raw):
    env = ex.Envelope(workspace="/tmp/ws", shares=tuple(raw)).sanitized()
    assert all(p.startswith("/") for p, _ in env.shares)
    assert len({p for p, _ in env.shares}) == len(env.shares)
