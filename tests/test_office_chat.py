"""The Office's chat is the person's chat, not an app copilot.

Reported as "if I am typing in the Office it is not appearing in the chat; the chat
needs to be a seamless experience". The Office's panel sent every turn into a hidden
"✦ Office" thread (origin copilot:office), which Chat filed under Copilots, and framed
each turn as "the copilot panel INSIDE the Office app … keep replies short", so the
lead answered as an app helper rather than as the head of the team. Pinned here:

- the panel in `.of-chat` is shared: it sends with origin `user` into Chat's open
  conversation (`currentConv`), and a new one it starts becomes Chat's;
- Chat opening, starting or being handed a conversation moves the Office with it, and
  a message sent from Chat is mirrored into the Office's panel;
- the Office's context is a lead's, never the copilot preamble.
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def test_the_office_panel_sends_into_the_persons_chat():
    src = (JS / "04a-copilot.js").read_text()
    assert "const shared=!!panel.closest('.of-chat')" in src
    shared_go = src[src.index("if(shared){\n      const cid=currentConv||null;"):]
    shared_go = shared_go[:shared_go.index("return;")]
    assert "origin:'user'" in shared_go and "officeChatContext()" in shared_go
    assert "copilotContext(" not in shared_go, "the Office is not an app copilot"
    assert "onCid:id=>officeChatAdopt(id)" in shared_go
    assert "var OFFICE_CHAT=" in src, "read by 09 and 10 in either load order"
    assert "decide who does the work" in src


def test_chat_and_the_office_follow_each_other():
    chat = (JS / "10-chat.js").read_text()
    ws = (JS / "09-websocket.js").read_text()
    open_conv = chat[chat.index("async function openConv(cid){"):][:400]
    assert "officeChatFollow()" in open_conv
    new_chat = chat[chat.index("function newChat(){"):][:200]
    assert "officeChatFollow()" in new_chat
    send = chat[chat.index("function send(){"):][:1200]
    assert "officeChatMirror(currentConv,text)" in send
    assert "currentConv=ev.id; officeChatFollow();" in ws


def test_the_office_still_mounts_the_panel():
    office = (JS / "24d-office.js").read_text()
    assert "initCopilot(w,chat)" in office and '<div class="of-chat"></div>' in office


def test_a_departments_question_is_asked_in_the_chat_it_came_from():
    """Reported as "when the approval is given and it moves to the next thing it doesn't
    pop up": a desk's approval carried no conversation, so the page put it in whatever
    Chat had open. Driven in headless Chrome afterwards: every card of a Research task
    asked from the Office (department_task, delegate, 50+ run_python) was in the Office's
    chat and on screen."""
    src = (ROOT / "agentos/server.py").read_text()
    fa = src[src.index("async def _flow_approval("):][:2400]
    assert "conversation_id=_run_conversation(run)" in fa
    ra = src[src.index("async def request_approval("):][:2200]
    assert 'ev["conversation_id"] = conversation_id' in ra
    rc = src[src.index("def _run_conversation("):][:700]
    assert '"chat"' in rc and "get_conversation(cid)" in rc


def test_the_office_shows_a_turn_already_running():
    src = (JS / "04a-copilot.js").read_text()
    rp = src[src.index("async function replay(cid){"):][:2600]
    assert "STREAMS[cid]" in rp and "mf-so-far" in rp and "approvalWatch()" in rp
    assert "input.placeholder='Ask '+agentName()+'…'" in src
