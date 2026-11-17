"""An update from a chat or a phone goes the way `bento update` goes, and going down says why.

Asked for as "when I tell the AI update bento via WhatsApp or via the settings, the update
should be carried the same way as bento update, only when the account asking is admin", and
"when Bento is going down it should emit the reason on the other accounts, for the update or
shutdown". What these defend:

- installing an update is a person's yes every time (checking is not), and the tool goes
  through the same door as Settings (`_update_everywhere`) and then restarts with a reason,
  after its reply is out;
- the other copies an update reaches are the same repository's, and never the person's own
  when the home is a test's;
- every way down says why on every account's pages, with who asked, and on every phone;
- a terminal that stops or restarts the service leaves the reason for the server to say.

No test calls the real restart: `desktop.restart_service` acts on the host.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import goingdown, policy, updates                          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_the_sentence_names_the_reason_and_who_asked():
    assert goingdown.words("Aria", "to install an update", "Piyush") == (
        "Aria is going offline to install an update, asked by Piyush. It will be back in a minute or two.")
    assert goingdown.words("", "", "", back=False) == "Bento is going offline."


def test_a_terminal_note_is_read_once_and_only_fresh(tmp_path, monkeypatch):
    from agentos import config
    monkeypatch.setattr(config, "AGENTOS_HOME", tmp_path)
    goingdown.note("to install an update", "piyush")
    goingdown.note("to restart", "piyush", keep=True)          # the specific reason wins
    got = goingdown.take()
    assert got == {"reason": "to install an update", "by": "piyush", "back": True}
    assert goingdown.take() == {}, "read once"
    goingdown.note("because it was stopped from a terminal", back=False)
    p = tmp_path / goingdown.NOTE
    d = json.loads(p.read_text())
    d["at"] = time.time() - goingdown.FRESH_S - 5
    p.write_text(json.dumps(d))
    assert goingdown.take() == {}, "an old note is about some earlier stop"


def test_installing_asks_a_person_every_time_and_checking_does_not():
    dec = policy.Decision("allow", "ok", rule="default")
    dec.action = "system.update"
    assert policy.person_rule(policy.MAIN, "update_agentos", {"apply": True}, dec, None)
    assert dec.effect == "ask"
    dec2 = policy.Decision("allow", "ok", rule="default")
    dec2.action = "system.update"
    assert not policy.person_rule(policy.MAIN, "update_agentos", {"apply": False}, dec2, None)
    assert dec2.effect == "allow"


def test_the_tool_goes_the_settings_way_and_down_after_its_reply(monkeypatch):
    from agentos.memory import Store
    from agentos.tools import Toolbox
    tb = Toolbox({"workspace": tempfile.mkdtemp()}, Store(Path(tempfile.mkdtemp()) / "a.db"))
    calls = {}

    async def everywhere():
        calls["everywhere"] = True
        return {"ok": True, "from": "aaaa", "to": "bbbb", "files": 3, "version": "0.9.31", "changes": [],
                "others": [{"root": "/x/other", "ok": False, "error": "a file is in the way"}]}

    async def down(reason, **kw):
        calls["down"] = (reason, kw)
    tb.update_everywhere, tb.going_down = everywhere, down

    async def go():
        out = await tb.update_agentos(apply=True)
        await asyncio.sleep(0)
        return out
    out = asyncio.run(go())
    assert calls["everywhere"] and calls["down"] == ("to install an update", {"wait_turns": True})
    assert "Restarting once this reply is out" in out and "/x/other was not updated" in out


def test_a_test_home_never_reaches_the_persons_copies(monkeypatch):
    from agentos import desktop
    monkeypatch.setattr(desktop, "served_root", lambda *a, **k: None)
    # the suite's home is not ~/.agentos, so the installer's clone is never offered
    assert updates.other_copies(ROOT) == []


def test_another_copy_must_be_the_same_repository(tmp_path, monkeypatch):
    from agentos import desktop

    def mk(d, url):
        d.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=d, check=True)
        (d / "agentos").mkdir()
        (d / "agentos" / "__init__.py").write_text("")
    here, same, other = tmp_path / "here", tmp_path / "same", tmp_path / "other"
    mk(here, "https://example.com/a.git")
    mk(same, "https://example.com/a.git")
    mk(other, "https://example.com/b.git")
    monkeypatch.setattr(desktop, "served_root", lambda *a, **k: same)
    assert updates.other_copies(here) == [same.resolve()]
    monkeypatch.setattr(desktop, "served_root", lambda *a, **k: other)
    assert updates.other_copies(here) == []
    monkeypatch.setattr(desktop, "served_root", lambda *a, **k: here)
    assert updates.other_copies(here) == [], "never itself"


def test_every_accounts_page_hears_why(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import desktop
    from agentos import server
    monkeypatch.setattr(desktop, "restart_service", lambda: "")
    with TestClient(server.app) as c:
        with c.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            assert ws.receive_json()["type"] == "state_sync"
            c.portal.call(server._announce_down, "to install an update")
            got = ws.receive_json()
            while got.get("type") != "going_down":
                got = ws.receive_json()
    assert got["reason"] == "to install an update" and "going offline to install an update" in got["text"]
    server.state.pop("down_said", None)
    server.state.pop("down_at", None)
    server.state["down_reason"] = ""


def test_every_way_down_says_why():
    srv = (ROOT / "agentos/server.py").read_text()
    # the routes and the restore, standby and snapshot paths go through one door
    assert srv.count('await _going_down("') >= 5
    assert '_going_down("to restore a backup")' in srv and '_going_down("for a cloud standby hand-over")' in srv
    assert '_going_down("to restore a snapshot")' in srv
    assert "because the computer is restarting" in srv, "a power action says so before the host goes"
    # the shutdown hook: a terminal's note, every page, and every Telegram AND WhatsApp
    hook = srv[srv.index("async def shutdown():"):]
    hook = hook[:hook.index("\n@app.")]
    assert "_gd.take()" in hook and '"type": "going_down"' in hook
    assert "say_down(" in hook and "wa.say_down(" in hook
    assert "toolbox.update_everywhere = _update_everywhere" in srv
    desk = (ROOT / "agentos/desktop.py").read_text()
    assert desk.count("goingdown.note(") >= 2, "service stop and restart leave the reason"
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert 'goingdown.note("to install an update"' in cli and "upd.other_copies(root)" in cli
    assert '"--only-here"' in cli
    js = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'going_down': goingDown(ev)" in js
    tg = (ROOT / "agentos/telegram.py").read_text()
    assert "asked by" in tg and "async def say_down(self, reason: str = \"\", by: str = \"\")" in tg
    wa = (ROOT / "agentos/whatsapp.py").read_text()
    assert "async def say_down(" in wa
