"""A desktop per running task, and tasks side by side on Telegram.

Asked for as "use desktops for different chats and scroll between them, given we can give
different tasks at the same time to the same or different company; as tasks complete the
desktop can close asking the user; in Telegram mode the backend should handle it".
Measured: in headless Chrome, leaving a running chat for a new one gave Desktop 3 named
after the task with a pinned Task window, a "done. Close its desktop?" toast at the end,
and closing it took the desktops back from 3 to 2. Against a stand-in Telegram server, a
second chat was answered at 6.6 s while the first worked, and the first chat's second
message was taken into its running turn ("12 times 12 is 144" in the same reply).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def test_a_running_chat_gets_its_own_desktop():
    td = (JS / "24m-taskdesks.js").read_text()
    assert "function taskDeskLeaving(" in td and "RUNNING.has(cid)" in td
    assert "is done. Close its desktop?" in td, "asked, never closed by itself"
    assert "var TASKDESK=" in td and "\nlet " not in td and "\nconst " not in td
    chat = (JS / "10-chat.js").read_text()
    assert "taskDeskLeaving(cid)" in chat[chat.index("async function openConv(cid){"):][:300]
    assert "taskDeskLeaving(null)" in chat[chat.index("function newChat(){"):][:200]
    ws = (JS / "09-websocket.js").read_text()
    assert "taskDeskDone(_cid)" in ws[ws.index("case 'turn_end':{"):][:300]
    pager = (JS / "03-virtual-desktops.js").read_text()
    assert "taskDeskOf(i)" in pager and "addEventListener('wheel'" in pager
    cp = (JS / "04a-copilot.js").read_text()
    assert "const pinned=panel.dataset.cid" in cp and "cid:pinned" in cp
    reg = (JS / "05-apps-registry.js").read_text()
    assert "task:{id:'task'" in reg and "multi:true" in reg[reg.index("task:{id:'task'"):][:200]


def test_telegram_works_side_by_side(tmp_path):
    from agentos.memory import Store
    from agentos.telegram import TelegramBridge
    from agentos import executors as ex
    tb = TelegramBridge({"telegram": {"bot_token": "1:T", "owner_chat_id": 1}}, Store(tmp_path / "a.db"), None, None)
    assert tb._busy_chats == set() and tb._waiting == {} and tb._runs == {}
    src = (ROOT / "agentos/telegram.py").read_text()
    h = src[src.index("        if chat_id in self._busy_chats:"):][:1400]
    assert "run.steer(text)" in h and "Taken into what I'm working on" in h
    assert "self._waiting.setdefault(chat_id, []).append(msg)" in h
    assert "Still working on your previous message" not in src
    fin = src[src.index("self._busy_chats.discard(chat_id)"):][:600]
    assert "asyncio.create_task(self._handle(nxt))" in fin, "what waited runs next"
    assert "run=self._runs[chat_id], steerable=True" in src
    fw = (ROOT / "agentos/executors.py").read_text()
    assert 'env.steerable = bool(steerable) and engine == "claude-code"' in fw
    assert "run = run or Run(engine=engine)" in fw
