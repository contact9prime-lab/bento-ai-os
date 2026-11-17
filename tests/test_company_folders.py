"""A company's folders: its own list, or the account's.

"Every company can have its own set of folders that it can work upon along with the
permissions, or it can inherit the default one from the account level." What these defend:

- a company that says nothing changes nothing: its people reach what the account reaches;
- a company with folders of its own holds its department's agents, its desk's master and
  every run of its desks and missions to them, read-only or read-write, open or parked;
- the lead keeps the account's folders, and an agent outside every company too;
- no grant reaches past the list, and `..` or a link cannot leave it;
- the save refuses a folder the account cannot reach, a home, a relative path, and a
  read-only share asked for read-write;
- a company agent's code writes only in its read-write folders, and with no jail on the
  machine it does not run;
- the agent is told its folders, and every change is a ledger row.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import company, policy, tools                            # noqa: E402
from agentos.memory import Store                                      # noqa: E402
from agentos.policy import MAIN, PDP, Principal                       # noqa: E402

ROOT = Path(__file__).parent.parent
AN = Principal("subagent", "analyst")


def _world(tmp_path, folders=None, **cfg):
    ws = tmp_path / "ws"
    for d in ("ws", "clients", "archive", "elsewhere"):
        (tmp_path / d).mkdir(exist_ok=True)
    co = {"id": "a1b2c3d4", "name": "Forge"}
    if folders is not None:
        co["folders"] = folders
    c = {"agent_name": "Aria", "autonomy": "full", "workspace": str(ws),
         "default_model": "openai/gpt-4o", "providers": {"openai": {"enabled": True, "api_key": "k"}},
         "company": co,
         "office": {"departments": [{"name": "Research", "members": ["analyst"], "desk": "forge-research-desk"}]}}
    c.update(cfg)
    store = Store(tmp_path / "a.db")
    store.save_subagent({"name": "analyst", "soul": "numbers", "tools": ["read_file", "write_file"]})
    store.save_subagent({"name": "loner", "soul": "outside", "tools": ["read_file", "write_file"]})
    return c, store, PDP(c, store)


def _tool(pdp, who, name, args, flow=""):
    return pdp.decide_tool(who, name, args, "risky", reason="test", autonomy="full", flow=flow)


def _own(tmp_path):
    return [{"path": str(tmp_path / "clients"), "mode": "rw"},
            {"path": str(tmp_path / "archive"), "mode": "ro"}]


def test_a_company_that_says_nothing_uses_the_accounts_folders(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    assert company.folders_for(cfg, "subagent", "analyst") is None
    for path in (tmp_path / "elsewhere" / "x.md", tmp_path / "ws" / "y.md"):
        assert _tool(pdp, AN, "write_file", {"path": str(path)}).rule != "company-folders"


def test_its_own_folders_are_a_ceiling_with_their_modes(tmp_path):
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    ok = _tool(pdp, AN, "write_file", {"path": str(tmp_path / "clients" / "acme.md")})
    assert ok.rule != "company-folders"
    assert _tool(pdp, AN, "read_file", {"path": str(tmp_path / "archive" / "old.md")}).rule != "company-folders"
    ro = _tool(pdp, AN, "write_file", {"path": str(tmp_path / "archive" / "old.md")})
    assert ro.effect == "deny" and ro.rule == "company-folders" and "read-only for Forge" in ro.reason
    out = _tool(pdp, AN, "read_file", {"path": str(tmp_path / "elsewhere" / "x.md")})
    assert out.effect == "deny" and "outside Forge's folders" in out.reason
    # the workspace is the account's, not the company's, unless the list names it
    assert _tool(pdp, AN, "list_dir", {}).rule == "company-folders"
    # a way out by .. or by a link is judged on the real path
    esc = _tool(pdp, AN, "read_file", {"path": str(tmp_path / "clients" / ".." / "elsewhere" / "x.md")})
    assert esc.rule == "company-folders"
    os.symlink(tmp_path / "elsewhere", tmp_path / "clients" / "link")
    assert _tool(pdp, AN, "read_file", {"path": str(tmp_path / "clients" / "link" / "x.md")}).rule == "company-folders"


def test_the_lead_and_people_outside_the_company_keep_the_accounts(tmp_path):
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    far = {"path": str(tmp_path / "elsewhere" / "x.md")}
    assert _tool(pdp, MAIN, "write_file", far).rule != "company-folders"
    assert _tool(pdp, Principal("subagent", "loner"), "write_file", far).rule != "company-folders"


def test_its_desks_and_missions_are_held_too(tmp_path):
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    cfg["company"]["work"] = [{"flow": "forge-weekly", "department": "Research"}]
    far = {"path": str(tmp_path / "elsewhere" / "x.md")}
    assert _tool(pdp, Principal("flow", "forge-research-desk"), "read_file", far).rule == "company-folders"
    assert _tool(pdp, Principal("flow", "forge-weekly"), "read_file", far).rule == "company-folders"
    # somebody from outside the company working inside one of its runs is the company's there
    loner = Principal("subagent", "loner")
    assert _tool(pdp, loner, "read_file", far, flow="forge-research-desk").rule == "company-folders"
    assert _tool(pdp, loner, "read_file", far, flow="someone-elses-mission").rule != "company-folders"
    assert _tool(pdp, Principal("flow", "someone-elses-mission"), "read_file", far).rule != "company-folders"


def test_a_parked_company_keeps_its_own_folders(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    cfg["companies"] = {"0f0f0f0f": {
        "company": {"id": "0f0f0f0f", "name": "Mill", "folders": [{"path": str(tmp_path / "clients"), "mode": "ro"}]},
        "office": {"departments": [{"name": "Plant", "members": ["loner"], "desk": "mill-plant-desk"}]}}}
    loner = Principal("subagent", "loner")
    w = _tool(pdp, loner, "write_file", {"path": str(tmp_path / "clients" / "a.md")})
    assert w.rule == "company-folders" and "read-only for Mill" in w.reason
    assert _tool(pdp, Principal("flow", "mill-plant-desk"), "read_file",
                 {"path": str(tmp_path / "elsewhere" / "a")}).rule == "company-folders"
    # the open company still says nothing
    assert _tool(pdp, AN, "write_file", {"path": str(tmp_path / "elsewhere" / "a")}).rule != "company-folders"


def test_no_grant_reaches_past_the_list(tmp_path):
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    store.add_grant(principal_kind="subagent", principal_id="analyst", action="fs.write",
                    resource="fs:*", effect="allow", source="user")
    pdp = PDP(cfg, store)
    d = _tool(pdp, AN, "write_file", {"path": str(tmp_path / "elsewhere" / "x.md")})
    assert d.effect == "deny" and d.rule == "company-folders"
    assert policy.stage_of("company-folders") == "folders"


def test_the_tool_list_still_offers_the_file_tools(tmp_path):
    # the "could it ever?" probe has no path: the tools stay on offer, each call is judged
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    for name in ("read_file", "list_dir", "write_file", "git_status"):
        d = pdp.decide_tool(AN, name, {}, "safe", audit=False)
        assert d.rule != "company-folders", name
    # a search always covers the workspace, which this company does not list: never usable
    for name in ("search_files", "terminal_send"):
        assert pdp.decide_tool(AN, name, {}, "safe", audit=False).rule == "company-folders"


def test_folder_tools_search_and_the_shared_terminal(tmp_path):
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    assert _tool(pdp, AN, "git_status", {"path": str(tmp_path / "elsewhere")}).rule == "company-folders"
    assert _tool(pdp, AN, "git_log", {"path": str(tmp_path / "archive")}).rule != "company-folders"
    assert _tool(pdp, AN, "run_tests", {"path": str(tmp_path / "archive")}).rule == "company-folders"
    assert _tool(pdp, AN, "search_files", {"query": "q"}).rule == "company-folders"
    assert _tool(pdp, AN, "terminal_send", {"session": "s", "text": "ls"}).rule == "company-folders"
    # a company that lists the workspace may search it
    cfg["company"]["folders"].append({"path": "@workspace", "mode": "ro"})
    assert _tool(pdp, AN, "search_files", {"query": "q"}).rule != "company-folders"


def test_the_save_reads_each_folder(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    good, refused = company.clean_folders(cfg, [
        {"path": str(tmp_path / "clients"), "mode": "rw"}, f"{tmp_path / 'archive'}:ro",
        "@workspace", "relative/place", str(tmp_path / "nope"), {"path": str(tmp_path / "clients")}])
    assert good == [{"path": str(tmp_path / "clients"), "mode": "rw"},
                    {"path": str(tmp_path / "archive"), "mode": "ro"},
                    {"path": "@workspace", "mode": "rw"}]
    assert any("full path" in r for r in refused) and any("no such folder" in r for r in refused)
    from agentos import config
    _, refused = company.clean_folders(cfg, [str(config.AGENTOS_HOME), "/"])
    assert len(refused) == 2 and "home" in refused[0]


def test_a_company_never_reaches_past_its_account(tmp_path):
    # the sandbox on: only its root and the shares, and a read-only share stays read-only
    cfg, store, pdp = _world(tmp_path, sandbox={
        "enabled": True, "root": str(tmp_path / "ws"),
        "folders": [{"path": str(tmp_path / "archive"), "mode": "ro"}]})
    good, refused = company.clean_folders(cfg, [
        {"path": str(tmp_path / "ws"), "mode": "rw"}, {"path": str(tmp_path / "archive"), "mode": "rw"},
        {"path": str(tmp_path / "elsewhere"), "mode": "ro"}])
    assert good == [{"path": str(tmp_path / "ws"), "mode": "rw"}]
    assert company.clean_folders(cfg, [f"{tmp_path / 'archive'}:ro"])[0] == [
        {"path": str(tmp_path / "archive"), "mode": "ro"}]
    assert any("read-only" in r for r in refused) and any("elsewhere" in r for r in refused)
    with pytest.raises(ValueError):
        company.set_folders(cfg, store, [{"path": str(tmp_path / "elsewhere"), "mode": "rw"}])
    assert "folders" not in cfg["company"]


def test_set_folders_is_a_ledger_row_and_none_inherits(tmp_path):
    cfg, store, pdp = _world(tmp_path)
    st = company.set_folders(cfg, store, [], make=True)
    made = company.own_folder(cfg)
    assert os.path.isdir(made) and made.endswith("/Forge")
    assert st["inherit"] is False and [f["path"] for f in st["folders"]] == [made]
    assert company.set_folders(cfg, store, None)["inherit"] is True
    rows = [dict(r) for r in store.db.execute(
        "SELECT detail FROM audit WHERE action='company.folders' ORDER BY seq")]
    assert len(rows) == 2 and "works in" in rows[0]["detail"] and "account's folders" in rows[1]["detail"]
    # a parked company is set by its id and stays parked
    cfg["companies"] = {"0f0f0f0f": {"company": {"id": "0f0f0f0f", "name": "Mill"}, "office": {}}}
    company.set_folders(cfg, store, [{"path": str(tmp_path / "clients"), "mode": "ro"}], cid="0f0f0f0f")
    assert cfg["companies"]["0f0f0f0f"]["company"]["folders"][0]["mode"] == "ro"
    assert "folders" not in cfg["company"]
    with pytest.raises(KeyError):
        company.set_folders(cfg, store, None, cid="deadbeef")


def test_the_agent_is_told_its_folders(tmp_path):
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    note = company.folders_note(cfg, "subagent", "analyst")
    assert str(tmp_path / "clients") + " (read and write)" in note
    assert str(tmp_path / "archive") + " (read only)" in note
    assert company.folders_note(cfg, "subagent", "loner") == ""
    cfg["company"]["folders"] = []
    assert "cannot read or write files" in company.folders_note(cfg, "subagent", "analyst")


def _run(cfg, store, cj, code):
    tb = tools.Toolbox(cfg, store)
    tok = tools.company_jail.set(cj)
    try:
        return asyncio.run(tb.run_python(code))
    finally:
        tools.company_jail.reset(tok)


@pytest.mark.skipif(tools.sandbox_mechanism() != "bwrap", reason="needs bubblewrap")
def test_a_company_agents_code_writes_only_in_its_read_write_folders(tmp_path):
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    rw, ro = company.folder_places(cfg, cfg["company"]["folders"])
    cj = {"name": "Forge", "rw": rw, "ro": ro}
    (tmp_path / "archive" / "old.txt").write_text("kept")
    out = _run(cfg, store, cj, "open('acme.txt','w').write('hi'); print(open('%s').read())"
               % (tmp_path / "archive" / "old.txt"))
    assert "kept" in out and (tmp_path / "clients" / "acme.txt").read_text() == "hi"
    out = _run(cfg, store, cj, "open('%s','w').write('x')" % (tmp_path / "archive" / "new.txt"))
    assert "Read-only file system" in out and not (tmp_path / "archive" / "new.txt").exists()
    out = _run(cfg, store, cj, "open('%s','w').write('x')" % (tmp_path / "elsewhere" / "x.txt"))
    assert "[exit code" in out and not (tmp_path / "elsewhere" / "x.txt").exists()
    # the workspace is not the company's here, so it is not written either
    out = _run(cfg, store, cj, "open('%s','w').write('x')" % (tmp_path / "ws" / "x.txt"))
    assert not (tmp_path / "ws" / "x.txt").exists()


def test_with_no_jail_a_company_agents_code_does_not_run(tmp_path, monkeypatch):
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    monkeypatch.setattr(tools, "sandbox_mechanism", lambda: None)
    out = _run(cfg, store, {"name": "Forge", "rw": [str(tmp_path / "clients")], "ro": []},
               "open('/tmp/x','w')")
    assert out.startswith("[denied] Forge works only in its own folders")


def test_the_agent_loop_sets_the_jail_from_who_it_is(tmp_path):
    from agentos.agent import Agent
    cfg, store, pdp = _world(tmp_path, folders=_own(tmp_path))
    tb = tools.Toolbox(cfg, store)

    def make(principal, flow=""):
        return Agent(cfg, tb, "openai/gpt-4o", None, None, principal=principal, flow=flow)
    cj = make(AN)._company_jail()
    assert cj["name"] == "Forge" and cj["rw"] == [os.path.realpath(tmp_path / "clients")]
    assert make(MAIN)._company_jail() is None
    assert make(Principal("subagent", "loner"))._company_jail() is None
    assert make(Principal("subagent", "loner"), flow="forge-research-desk")._company_jail() is not None


def test_no_agent_can_set_it():
    src = (ROOT / "agentos" / "tools.py").read_text()
    assert "def set_company_folders" not in src and "company_folders" not in src.split("TOOL_SCHEMAS", 1)[-1]
    assert "company" not in getattr(tools, "CONFIG_SAFE_KEYS", ())


def test_the_routes(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        had = dict(servermod.state["cfg"].get("company") or {})
        try:
            st = cl.get("/api/company/folders").json()
            assert "inherit" in st and st["say"]
            assert cl.get("/api/company/folders?company=deadbeef").status_code == 404
            r = cl.put("/api/company/folders", json={"folders": [{"path": "relative", "mode": "rw"}]})
            assert r.status_code == 400 and "full path" in r.json()["error"]
            r = cl.put("/api/company/folders", json={"folders": [], "make": True})
            assert r.status_code == 200 and r.json()["inherit"] is False and len(r.json()["folders"]) == 1
            assert cl.get("/api/company").json()["folders"]["inherit"] is False
            r = cl.put("/api/company/folders", json={"inherit": True})
            assert r.status_code == 200 and r.json()["inherit"] is True
        finally:
            servermod.state["cfg"]["company"] = had


def test_the_terminal(tmp_path):
    import subprocess
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text('{"workspace": "%s", "setup_complete": true, "port": 8997,'
                                      ' "company": {"name": "Forge"}}' % (tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    env = {**os.environ, "AGENTOS_HOME": str(home), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "company", "folders", *a], cwd=ROOT,  # noqa: E731
                                    env=env, capture_output=True, text=True, timeout=60)
    assert "uses your account's folders" in run().stdout
    r = run("make")
    assert r.returncode == 0 and "read and write" in r.stdout and "workspace/Forge" in r.stdout, r.stdout + r.stderr
    (tmp_path / "ws" / "old").mkdir()
    assert "read only" in run("add", str(tmp_path / "ws" / "old"), "ro").stdout
    r = run("add", "/nowhere/at/all")
    assert r.returncode == 1 and "no such folder" in r.stdout
    assert run("rw", str(tmp_path / "ws" / "old")).stdout.count("read and write") == 2
    assert "uses your account's folders" in run("inherit").stdout
