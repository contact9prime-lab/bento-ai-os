"""A turn's live events belong to the account that started it, not to the machine.

On a box with accounts, `broadcast` fans an event out to EVERY connected socket.
That is right for a machine-wide fact (the wallpaper changed, an MCP server wants
consent) and wrong for a turn: a turn's working indicator, its streamed reply, its
queue and its approval card are one person's, and another account signed in on the
same machine must not see them. The symptom that this exists to prevent was a user
signing in and being shown a spinner — "getting started · 1m 17s" — that belonged
to somebody else's session, because `state_sync` handed every new socket the whole
`turns` map and every turn event went to every client.

The events are scoped by `broadcast_user(event, uid)`, which delivers only to the
sockets whose `client_uids` entry matches. On a single-user machine every uid is ''
and it is exactly `broadcast` — which is why the over-the-socket tests in
`test_queued_turns.py` still pass unchanged and are the no-regression half of this.
This file pins the multi-user half: the wiring that decides WHO an event reaches.
"""
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import server                                  # noqa: E402


def test_broadcast_user_reaches_only_the_owning_accounts_sockets():
    """The core contract, exercised directly: two sockets for two accounts, an
    event addressed to one, delivered to that one alone."""
    sent: dict = {}

    class FakeWS:
        def __init__(self, name):
            self.name = name
        async def send_text(self, text):
            sent.setdefault(self.name, []).append(text)

    ada_ws, bob_ws = FakeWS("ada"), FakeWS("bob")
    clients = {ada_ws, bob_ws}
    client_uids = {ada_ws: "ada", bob_ws: "bob"}

    # Rebuild broadcast_user's contract against these two maps. It is a closure in
    # create_app, so it cannot be imported; the behaviour it must have is small and
    # is asserted here and pinned against the source below so the two cannot drift.
    async def broadcast_user(event, uid):
        for ws in clients:
            if client_uids.get(ws, "") != uid:
                continue
            await ws.send_text(event)

    asyncio.run(broadcast_user("for-ada", "ada"))
    assert sent.get("ada") == ["for-ada"]
    assert "bob" not in sent, "bob saw a turn event addressed to ada"

    asyncio.run(broadcast_user("machine", ""))
    assert "ada" not in {k for k in sent if len(sent[k]) > 1}  # no extra to ada
    assert sent.get("bob") is None, "an event for uid '' reached nobody with a real uid"


def test_the_real_broadcast_user_matches_the_asserted_contract():
    """Guard against the closure above drifting from the shipped one."""
    src = inspect.getsource(server.startup)
    assert 'async def broadcast_user(event: dict, uid: str):' in src
    assert 'if client_uids.get(ws, "") != uid:' in src, \
        "broadcast_user must skip sockets whose account does not own the event"


def test_a_turn_carries_its_owner_and_events_are_scoped_to_it():
    """`_run_chat` must address the turn to its owner, not the whole machine."""
    src = inspect.getsource(server._run_chat)
    assert 'owner = str(data.get("uid", "") or "")' in src, \
        "the turn's owner is the server-set uid, never a client-supplied one"
    assert 'state["broadcast_user"]({**ev, "conversation_id": cid}, owner)' in src, \
        "every turn event goes through the user-scoped broadcast"
    # Every slot the turn claims records the owner, so a state_sync racing it scopes right.
    assert '"uid": owner' in src, "the turn slot must record its owning account"


def test_state_sync_only_reports_the_connecting_accounts_running_turns():
    """The exact leak from the bug report: a fresh login must not inherit another
    account's spinner."""
    src = inspect.getsource(server.ws_endpoint)
    assert 'state["client_uids"][ws] = ws_uid' in src, "the socket registers its account"
    assert '"running": [c for c, t in turns.items() if t.get("uid", "") == ws_uid]' in src, \
        "state_sync must filter running turns to the connecting account"


def test_the_queue_is_scoped_to_the_conversations_owner():
    src = inspect.getsource(server._queue_broadcast)
    assert 'broadcast_user' in src and 'turns' in src, \
        "a queue update belongs to the conversation's owner, not every client"
