"""A chat is in the list the moment a person writes in it, and the list is open beside the chat.

Reported as "if it's stuck it doesn't come in the chat history; as soon as the chat comes in the chat
window or Telegram it should come in the chat history", and "the left panel should be open by
default in the chat but can be hidden". Every surface moved a chat up the list (`updated_at`) only
after the reply was saved, and the list is the newest 100, so a turn that stuck in an older chat was
nowhere. With the immersive look on (the default), the list was a drawer that started closed.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
CSS = ROOT / "agentos/ui/src/css"


def test_a_persons_message_puts_its_chat_first_before_any_reply(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    old = store.create_conversation("an old Telegram chat", origin="telegram")
    store.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time() - 86400 * 30, old))
    for i in range(120):
        store.create_conversation(f"newer {i}")
    store.db.commit()
    assert old not in [c["id"] for c in store.list_conversations()]
    store.add_message(old, "user", "run the backtest")      # and then the turn sticks: no reply
    assert store.list_conversations()[0]["id"] == old


def test_an_answer_alone_does_not_reorder():
    src = (ROOT / "agentos/memory.py").read_text()
    body = src[src.index("    def add_message("):][:1200]
    assert 'if role == "user":' in body


def test_a_desktop_turn_is_listed_at_its_start_and_the_page_asks_again():
    srv = (ROOT / "agentos/server.py").read_text()
    run = srv[srv.index("async def _run_chat("):]
    head = run[:run.index("_history_for(")]
    assert "store.touch_conversation(cid)" in head, "before the price card and the history rebuild"
    chat = (JS / "10-chat.js").read_text()
    send = chat[chat.index("function send(){"):][:1600]
    assert "setTimeout(loadConvs," in send


def test_the_list_is_open_by_default_and_hides():
    chat = (JS / "10-chat.js").read_text()
    assert "class=\"chatwrap${chatSideWanted()?' side':''}\"" in chat
    assert "localStorage.getItem('chat.side')!=='0'" in chat, "open unless the person hid it"
    assert 'onclick="chatSideToggle(this)"' in chat
    css = (CSS / "20-immersive.css").read_text()
    assert "body.immersive .chatwrap.side .cside{position:relative;transform:none" in css
    # a narrow window keeps the drawer: a 280px pane would leave the chat no room
    narrow = css[css.index("@container (max-width:639px)"):][:400]
    assert "translateX(-104%)" in narrow and ".chatwrap.side.drawer .cside{transform:none}" in narrow
    assert "CHAT_SIDE_MIN=640" in chat
