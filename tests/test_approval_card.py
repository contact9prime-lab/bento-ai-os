"""A big approval fits on the screen and says what it is for (approvalcard.py).

Reported with a screenshot: a long command made the floating approval card taller than the
screen, so Allow and Deny were below its edge. Measured in Chromium at 1440x900 with a
59-line setup script: the card was 1,896px tall and Allow sat at y=1,894. Every surface
built its own line for the card, so each failed in its own way: the page dumped the
arguments, the TUI cut at 120 characters, Telegram at 300, WhatsApp's 1024-character
button body cut the reason off the end.
"""
import asyncio
import re
from pathlib import Path

import pytest

from agentos import approvalcard

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "agentos/ui/src/js"
CSS = ROOT / "agentos/ui/src/css"

LONG = "\n".join(["cat > setup.sh <<'EOF'"] + [f"echo 'step {i}'" for i in range(1, 58)]
                 + ["EOF", "sh setup.sh && rm -rf cache"])


def test_the_goal_is_the_agents_own_words_and_says_so():
    c = approvalcard.card("run_command", {"command": LONG},
                          "Sure.\n\nI'll set up the project now. First I write the script, then run it:")
    assert c["said"] is True
    assert c["goal"] == "I'll set up the project now. First I write the script, then run it"
    assert approvalcard.headline(c).startswith("“") and approvalcard.headline(c).endswith("”")
    assert c["body"] == LONG and c["lines"] == 60 and c["cut"] == 0


def test_without_words_the_goal_is_the_step_in_plain_words():
    c = approvalcard.card("create_app", {"name": "Big Board", "html": "<div>x</div>\n" * 400})
    assert c == {**c, "goal": "Build an app: Big Board", "said": False}
    assert approvalcard.headline(c) == "Build an app: Big Board"
    # code in the reply is not a goal; a reply of only code says nothing usable
    assert approvalcard.intent("```sh\nrm -rf /\n```") == ""
    assert approvalcard.card("export_app_to_git", {})["goal"] == "Export app to git"
    # Claude Code's Bash carries its own description
    assert approvalcard.card("Bash", {"command": "ls", "description": "List the files"})["goal"] == "List the files"


def test_the_loops_own_arguments_never_reach_the_card():
    c = approvalcard.card("create_app", {"name": "A", "_conv": "c1", "_run_id": "r"})
    assert "_conv" not in c["body"] and "_run_id" not in c["body"]


def test_a_shortened_body_always_says_how_much_is_not_shown():
    c = approvalcard.card("run_command", {"command": LONG})
    pv = approvalcard.preview(c)
    assert pv.splitlines()[:6] == LONG.splitlines()[:6]
    assert pv.endswith("(54 more lines not shown)")
    one = approvalcard.card("run_command", {"command": "x" * 5000})
    assert approvalcard.preview(one).endswith("(4400 more characters not shown)")
    short = approvalcard.card("run_command", {"command": "ls -la"})
    assert approvalcard.preview(short) == "ls -la"
    huge = approvalcard.card("write_file", {"path": "a", "content": "y" * 50_000})
    assert huge["cut"] > 0 and len(huge["body"]) == approvalcard.BODY_CAP


def test_a_capped_message_keeps_the_goal_and_the_reason():
    c = approvalcard.card("run_command", {"command": LONG}, "I'll set up the project.")
    reason = "Shell command that may modify the system."
    for limit in (1024, 400):
        m = approvalcard.message(c, reason, limit=limit)
        assert len(m) <= limit
        assert "I'll set up the project." in m and m.endswith(reason)
        assert "not shown)" in m


def test_the_agents_words_reach_the_approver(tmp_path):
    """The loop sets what the model said before the call; every approver reads it."""
    from agentos import policy
    from agentos.agent import Agent
    seen = {}

    async def approver(name, args, reason, offer=None):
        seen["said"] = policy.said()
        seen["card"] = approvalcard.card(name, args, policy.said())
        return False

    ag = Agent.__new__(Agent)
    ag._said = "I'll clean the cache folder."
    tok = policy._SAID.set(ag._said)
    try:
        asyncio.run(approver("run_command", {"command": "rm -rf cache"}, "r"))
    finally:
        policy._SAID.reset(tok)
    assert seen["card"]["goal"] == "I'll clean the cache folder." and seen["card"]["said"]
    assert policy.said() == ""
    src = (ROOT / "agentos/agent.py").read_text()
    assert "tok_said = _SAID.set(getattr(self, \"_said\"" in src and "self._said = text" in src


def test_the_desktops_approval_event_carries_the_card():
    from agentos import policy, server

    async def go():
        sent = []

        async def evsend(ev):
            sent.append(ev)
        tok = policy._SAID.set("I'll set up the project.")
        try:
            await server.request_approval("run_command", {"command": LONG}, "risky",
                                          evsend=evsend, timeout=0.05)
        finally:
            policy._SAID.reset(tok)
        return sent
    from fastapi.testclient import TestClient
    with TestClient(server.app):           # startup makes the broker's state
        ev = asyncio.run(go())[0]
    assert ev["type"] == "approval_request"
    assert ev["card"]["goal"] == "I'll set up the project." and ev["card"]["lines"] == 60


@pytest.mark.asyncio
async def test_telegram_sends_the_goal_and_a_capped_preview(tmp_path, monkeypatch):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    from agentos.tools import Toolbox
    store = Store(tmp_path / "t.db")
    cfg = {"policies": [], "workspace": str(tmp_path / "ws"), "telegram": {"bot_token": "x"}}

    async def _b(_ev):
        pass
    tg = TelegramBridge(cfg, store, Toolbox(cfg, store), _b)
    calls = []

    async def _api(method, **params):
        calls.append((method, params))
        return {}
    monkeypatch.setattr(tg, "_api", _api)
    huge = LONG + "\n" + "z" * 9000
    ok = await tg.ask_approval(1, "run_command", {"command": huge}, "Shell command.", timeout=0.05)
    assert ok is False
    text = next(p["text"] for m, p in calls if m == "sendMessage" and "Approval needed" in p["text"])
    assert len(text) <= 4000 and "Run a command on this machine" in text
    assert "not shown)" in text and text.endswith("Shell command.")


def test_the_card_on_the_page_is_shortened_and_never_taller_than_the_screen():
    ws = (JS / "09-websocket.js").read_text()
    build = ws[ws.index("function buildApprovalBox"):][:4000]
    assert "apCard(ev)" in build and "agoal" in build and "amore" in build
    assert "JSON.stringify(ev.args" not in build, "the card must not dump the arguments"
    css = (CSS / "09-chat-team-docs.css").read_text()
    fl = re.search(r"\.approval\.ap-float\{([^}]*)\}", css).group(1)
    assert "max-height:calc(100dvh" in fl and "overflow-y:auto" in fl
    assert ".approval.ap-float .btns{position:sticky" in css
    assert re.search(r"\.approval \.acmd\.clip\{[^}]*max-height", css)
    # above the toast stack: on a phone a toast sat over the card's own Allow
    toasts = int(re.search(r"#toasts\{[^}]*z-index:(\d+)", (CSS / "13-motion.css").read_text()).group(1))
    assert int(re.search(r"z-index:(\d+)", fl).group(1)) > toasts
    # the approval's toast goes once its card is on screen
    assert "if(tt&&approvalVisible(ev.id))tt.remove()" in ws


def test_the_tui_card_scrolls_and_keeps_its_buttons_on_screen():
    from textual.app import App
    from textual.widgets import Button
    from agentos.tui_app import ApprovalScreen
    card = approvalcard.card("run_command", {"command": LONG}, "I'll set up the project.")

    class Host(App):
        CSS = __import__("agentos.tui_app", fromlist=["AgentTUI"]).AgentTUI.CSS

    async def walk():
        app = Host()
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ApprovalScreen("run_command", "", "Shell command.", None, card))
            await pilot.pause(0.3)
            scr = app.screen
            assert "set up the project" in str(scr.query_one("#ap-goal").render())
            allow = scr.query_one("#ap-allow", Button).region
            assert allow.height and allow.y + allow.height <= 24, allow
    asyncio.run(walk())
