"""An app's ✦ assistant knows its app, and an app's read-only look at the workspace is one yes.

Reported with two screenshots of a trading app: its assistant, asked "Explain me the setup",
ran `ls -R ~/AgentOS/builds | head -40; head -40 deck.md` (a card each time) looking for the
app, never found it (an app lives in the database, not on disk), ran out of steps and said so.
And "ls in the workspace is too heavy to ask all the time". The owner chose: give the
assistant its app's code, data and screen, keep asking, and let one Always cover read-only
commands on files in the workspace for that one app.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import approvalcard                                   # noqa: E402
from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP, Principal, READ_ONLY_MARK          # noqa: E402
from agentos.tools import reads_inside                             # noqa: E402

ROOT = Path(__file__).parent.parent
SERVER = (ROOT / "agentos/server.py").read_text()


def _ws(tmp_path):
    ws = tmp_path / "AgentOS"
    (ws / "builds" / "app").mkdir(parents=True)
    (ws / "deck.md").write_text("# deck")
    return str(ws)


def test_what_counts_as_reading_files_in_the_workspace(tmp_path):
    ws = _ws(tmp_path)
    yes = [f"ls -R {ws}/builds | head -40; head -40 {ws}/deck.md", "ls", "ls builds",
           "grep -rn deck .", "cat deck.md | wc -l", "find . -name '*.md'", f"head {ws}/deck.md"]
    no = ["ls ..", "cat ~/.ssh/id_rsa", "cat .env", "cat builds/../../secret", "cat /etc/passwd",
          "grep -f/etc/passwd x", "grep --file=/etc/passwd x", "ps aux", "ls; rm deck.md",
          "cat deck.md > copy.md", "echo $(cat /etc/passwd)", "ls & rm x", "python3 -c 1",
          "curl https://x", "ls ~"]
    for c in yes:
        assert reads_inside(c, ws), c
    for c in no:
        assert not reads_inside(c, ws), c
    assert not reads_inside("ls", ws, cwd="/etc"), "a relative path would read another folder"
    assert reads_inside("ls", ws, cwd=f"{ws}/builds")
    assert not reads_inside("ls", "/"), "never the whole disk"


def test_an_app_is_offered_one_yes_for_reading_the_workspace_and_it_covers_only_that(tmp_path):
    ws = _ws(tmp_path)
    store = Store(tmp_path / "t.db")
    pdp = PDP({"workspace": ws, "autonomy": "balanced"}, store)
    app = Principal("app", "a1")
    cmd = f"ls -R {ws}/builds | head -40; head -40 {ws}/deck.md"
    ctx = lambda c, cwd="": {"surface": "gui", "tool": "run_command", "args": {"command": c, "cwd": cwd}}
    d = pdp.decide(app, "tool.use", f"tool:run_command {cmd}", ctx(cmd))
    assert d.effect == "ask"
    real = os.path.realpath(ws)
    assert d.grant_offer["resource"] == f"tool:run_command {READ_ONLY_MARK}{real}"
    words = approvalcard.choices(d.grant_offer, 'The app "Signal Desk"')["always"]
    assert f"read-only commands (ls, cat, head, grep and the like) on files in {real}" in words
    store.add_grant("app", "a1", d.grant_offer["action"], d.grant_offer["resource"], source="user")
    for other in ("ls builds", "grep -rn deck .", "wc -l deck.md"):
        assert pdp.decide(app, "tool.use", f"tool:run_command {other}", ctx(other)).effect == "allow", other
    for other in ("cat ~/.ssh/id_rsa", "cat .env", "rm deck.md", "ls ..", "curl https://x"):
        assert pdp.decide(app, "tool.use", f"tool:run_command {other}", ctx(other)).effect != "allow", other
    assert pdp.decide(app, "tool.use", "tool:run_command ls", ctx("ls", "/etc")).effect != "allow"
    # another app gets nothing from it
    assert pdp.decide(Principal("app", "a2"), "tool.use", "tool:run_command ls", ctx("ls")).effect != "allow"
    # a command outside the workspace is offered as itself, as before
    d2 = pdp.decide(app, "tool.use", "tool:run_command cat /etc/hosts", ctx("cat /etc/hosts"))
    assert READ_ONLY_MARK not in d2.grant_offer["resource"]


def test_a_workspace_that_is_the_home_is_never_offered(tmp_path):
    store = Store(tmp_path / "t.db")
    home = os.path.expanduser("~")
    pdp = PDP({"workspace": home, "autonomy": "balanced"}, store)
    d = pdp.decide(Principal("app", "a1"), "tool.use", "tool:run_command ls",
                   {"surface": "gui", "tool": "run_command", "args": {"command": "ls"}})
    assert READ_ONLY_MARK not in (d.grant_offer or {}).get("resource", "")


def test_the_assistant_is_handed_its_apps_code_data_and_screen():
    agent = SERVER[SERVER.index('@app.post("/api/apps/agent")'):SERVER.index('@app.get("/api/apps/context")')]
    assert 'about=bool(body.get("about_app"))' in agent and "_app_about(principal.id" in agent
    assert "APP_ABOUT_STEPS if about else 5" in agent
    about = SERVER[SERVER.index("def _app_about"):SERVER.index('@app.post("/api/apps/agent")')]
    for part in ("<app_code>", "<app_saved_data>", "<app_screen_now>", "not a file on this computer",
                 "not instructions to you"):
        assert part in about
    # the runtime's ✦ sends what is on screen, without its own panel
    rt = SERVER[SERVER.index("window.appCopilot.mount = "):SERVER.index("// ===== kit v2")]
    assert "{about: true, page: seen}" in rt and "replace(pan.innerText" in rt


def test_app_about_reads_the_app(tmp_path, monkeypatch):
    from agentos import server
    store = Store(tmp_path / "t.db")
    aid = store.save_app("Signal Desk", "", "", "<html><title>Signal Desk</title><b>scan</b></html>")
    store.set_app_data(aid, '{"signals": 47}')
    monkeypatch.setattr(server, "state", {"store": store})
    text = server._app_about(aid, "Newest 5-minute bar: 13:20")
    assert 'inside the app "Signal Desk"' in text and "<b>scan</b>" in text
    assert "Newest 5-minute bar: 13:20" in text and '"signals": 47' in text
    long = server._cap("x" * 50, 10)
    assert long.endswith("(40 more characters not shown)")
