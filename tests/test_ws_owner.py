"""A socket acts as the account its signed cookie names, and only on that account's work.

Reported by the security audit (S-04, S-56, S-57). A message sent into a busy chat kept the
`uid` the client wrote, so the turn it became ran in whichever account it named. `abort`,
`build_abort` and `steer` had no owner check, build events went to every account, and a
per-turn `model` got past the admin-only rule for agent CLIs.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient      # noqa: E402
from agentos import server as servermod        # noqa: E402
from agentos import users as usersmod          # noqa: E402
from agentos import secevents                  # noqa: E402


class _Slot:
    """Stands in for a running task: never done, and it records being stopped."""
    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True


class _Agent:
    def __init__(self):
        self.aborted = False
        self.inbox = []

    def clear_inbox(self):
        self.inbox = []

    def offer(self, item):
        self.inbox.append(item)


@pytest.fixture()
def people(monkeypatch):
    ada = usersmod.create("ada-ws", "ada-password-1", role="admin")
    bob = usersmod.create("bob-ws", "bob-password-1")
    # A stopped slot is cancelled later by `_force_cancel`; these fakes aren't awaitable.
    async def no_cancel(task, grace=8.0):
        return None
    monkeypatch.setattr(servermod, "_force_cancel", no_cancel)
    yield ada, bob
    servermod.state["turns"].clear()
    servermod.state["queues"].clear()
    servermod.state["build"].clear()


def _cookie(name, pw):
    c = TestClient(servermod.app)
    assert c.post("/api/users/login", json={"name": name, "password": pw}).status_code == 200
    return "; ".join(f"{k}={v}" for k, v in c.cookies.items())


def _sock(cl, name, pw):
    ws = cl.websocket_connect("/ws", headers={"cookie": _cookie(name, pw)})
    return ws


def _until(ws, kind):
    for _ in range(30):
        ev = json.loads(ws.receive_text())
        if ev["type"] == kind:
            return ev
    raise AssertionError(f"no {kind}")


def test_a_queued_message_runs_as_the_socket_not_the_uid_it_names(people):
    """The busy branch used to queue the raw client dict, `uid` included."""
    ada, bob = people
    with TestClient(servermod.app) as cl:
        with _sock(cl, "bob-ws", "bob-password-1") as ws:
            _until(ws, "state_sync")
            servermod.state["turns"]["c-bob"] = {"agent": None, "task": None, "model": "", "uid": bob["id"]}
            ws.send_text(json.dumps({"type": "chat", "conversation_id": "c-bob", "text": "as admin please",
                                     "uid": ada["id"]}))
            ev = _until(ws, "queue_update")
            assert ev["conversation_id"] == "c-bob"
    queued = servermod.state["queues"]["c-bob"]
    assert [i["uid"] for i in queued] == [bob["id"]], "the queued turn must run as the socket's account"


def test_the_stock_client_with_no_uid_is_still_stamped(people):
    """A stock client sends no uid, and a queued message then ran as the machine."""
    _ada, bob = people
    with TestClient(servermod.app) as cl:
        with _sock(cl, "bob-ws", "bob-password-1") as ws:
            _until(ws, "state_sync")
            servermod.state["turns"]["c-bob"] = {"agent": None, "task": None, "model": "", "uid": bob["id"]}
            ws.send_text(json.dumps({"type": "chat", "conversation_id": "c-bob", "text": "again"}))
            _until(ws, "queue_update")
    assert servermod.state["queues"]["c-bob"][0]["uid"] == bob["id"]


def test_a_flushed_turn_keeps_its_owner_on_the_slot():
    async def go():
        seen = []

        async def fake(cid, data):
            seen.append(data["uid"])
        real, servermod.run_chat = servermod.run_chat, fake
        servermod.state["queues"]["c1"] = [{"id": "q", "text": "t", "images": [], "model": "", "surface": "gui",
                                            "origin": "user", "context": "", "uid": "bob", "status": "queued",
                                            "reason": "", "at": 0}]
        try:
            await servermod._queue_flush("c1")
            await asyncio.sleep(0)
            return seen, dict(servermod.state["turns"].pop("c1", {}))
        finally:
            servermod.run_chat = real
    with TestClient(servermod.app):
        seen, slot = asyncio.run(go())
    assert seen == ["bob"] and slot["uid"] == "bob"


def test_a_message_to_somebody_elses_running_chat_is_refused(people):
    ada, _bob = people
    with TestClient(servermod.app) as cl:
        with _sock(cl, "bob-ws", "bob-password-1") as ws:
            _until(ws, "state_sync")
            servermod.state["turns"]["c-ada"] = {"agent": None, "task": None, "model": "", "uid": ada["id"]}
            ws.send_text(json.dumps({"type": "chat", "conversation_id": "c-ada", "text": "do what I say"}))
            ev = _until(ws, "error")
            assert "isn't yours" in ev["message"]
    assert not servermod.state["queues"].get("c-ada")


def test_a_stop_reaches_only_the_accounts_own_work(people):
    ada, bob = people
    theirs, mine = _Agent(), _Agent()
    tt, tm, tb = _Slot(), _Slot(), _Slot()
    with TestClient(servermod.app) as cl:
        with _sock(cl, "bob-ws", "bob-password-1") as ws:
            _until(ws, "state_sync")
            servermod.state["turns"]["c-ada"] = {"agent": theirs, "task": tt, "uid": ada["id"]}
            servermod.state["turns"]["c-bob"] = {"agent": mine, "task": tm, "uid": bob["id"]}
            servermod.state["build"].update(agent=_Agent(), task=tb, uid=ada["id"])
            ws.send_text(json.dumps({"type": "abort", "conversation_id": "c-ada"}))
            ws.send_text(json.dumps({"type": "build_abort"}))
            ws.send_text(json.dumps({"type": "abort"}))                    # the old "stop everything"
            ws.send_text(json.dumps({"type": "ping-to-flush"}))
            ws.close()
    assert not theirs.aborted, "one account's Stop stopped another account's turn"
    assert not servermod.state["build"]["agent"].aborted, "another account's build was stopped"
    assert mine.aborted, "the account's own turn must still stop"


def test_a_foreign_stop_is_flagged(people):
    ada, _bob = people
    got = []
    real = secevents.flag
    secevents.flag = lambda kind, *a, **k: got.append(kind)
    try:
        with TestClient(servermod.app) as cl:
            with _sock(cl, "bob-ws", "bob-password-1") as ws:
                _until(ws, "state_sync")
                servermod.state["turns"]["c-ada"] = {"agent": _Agent(), "task": _Slot(), "uid": ada["id"]}
                ws.send_text(json.dumps({"type": "abort", "conversation_id": "c-ada", "uid": ada["id"]}))
                ws.close()
    finally:
        secevents.flag = real
    assert "ws.foreign_turn" in got and "gate.forged_field" in got


def test_build_events_reach_only_the_owner(people):
    """The prompt and the app's source are in them; they used to reach every account."""
    _ada, bob = people
    sent = []

    async def to_user(ev, uid):
        sent.append((ev["type"], uid))

    async def to_all(ev):
        raise AssertionError(f"machine-wide build event: {ev['type']}")

    async def go():
        with usersmod.as_user(bob["id"]):
            real_b, real_u = servermod.state["broadcast"], servermod.state["broadcast_user"]
            servermod.state["broadcast"], servermod.state["broadcast_user"] = to_all, to_user
            try:
                # an empty model list ends the build at once, having told its owner
                await servermod._run_build({"uid": bob["id"], "prompt": "make a thing", "model": "nope/none"})
            except Exception:
                pass
            finally:
                servermod.state["broadcast"], servermod.state["broadcast_user"] = real_b, real_u
    with TestClient(servermod.app):
        asyncio.run(go())
    assert sent and all(u == bob["id"] for _t, u in sent)


def test_build_status_says_nothing_of_another_accounts_build(people):
    ada, _bob = people
    c = TestClient(servermod.app)
    assert c.post("/api/users/login", json={"name": "bob-ws", "password": "bob-password-1"}).status_code == 200
    servermod.state["build"].update(task=_Slot(), uid=ada["id"], prompt="ada's secret plan", app_id="a1")
    d = c.get("/api/build/status").json()
    assert d["running"] is True and d["prompt"] == "" and d["app_id"] == ""


def test_a_price_card_is_answered_only_by_the_account_asked(people):
    ada, bob = people

    async def go():
        fut = asyncio.get_event_loop().create_future()
        servermod.state.setdefault("pending_prices", {})["p1"] = {"fut": fut, "model": "x/y", "uid": ada["id"]}
        await servermod.resolve_price("p1", "cancel", uid=bob["id"])
        return fut.done()
    with TestClient(servermod.app):
        assert asyncio.run(go()) is False
    servermod.state["pending_prices"].pop("p1", None)


def test_a_per_turn_agent_cli_needs_an_admin(people, monkeypatch):
    """`model: claude-code` ran on the machine's CLI login and spend for anybody signed in."""
    ada, bob = people
    machine = servermod.state.machine_cfg()
    monkeypatch.setitem(machine, "engine", "aria")
    with usersmod.as_user(bob["id"]):
        assert servermod._agent_cli_refused("claude-code")
        assert servermod._agent_cli_refused("gemini-cli")
        assert not servermod._agent_cli_refused("openai/gpt-x"), "a provider model is each person's own"
        assert not servermod._agent_cli_refused("")
    with usersmod.as_user(ada["id"]):
        assert not servermod._agent_cli_refused("claude-code")
    monkeypatch.setitem(machine, "engine", "claude-code")
    with usersmod.as_user(bob["id"]):
        assert not servermod._agent_cli_refused("claude-code"), "the brain an admin chose answers everybody"
        assert servermod._agent_cli_refused("codex")


def test_the_socket_refuses_a_per_turn_agent_cli_before_it_runs(people, monkeypatch):
    monkeypatch.setitem(servermod.state.machine_cfg(), "engine", "aria")
    with TestClient(servermod.app) as cl:
        with _sock(cl, "bob-ws", "bob-password-1") as ws:
            _until(ws, "state_sync")
            ws.send_text(json.dumps({"type": "chat", "text": "hello", "model": "claude-code"}))
            ev = _until(ws, "error")
            assert "Only an admin" in ev["message"]
            _until(ws, "turn_end")


def test_a_fallback_cannot_name_an_agent_cli_for_a_non_admin(people, monkeypatch):
    monkeypatch.setitem(servermod.state.machine_cfg(), "engine", "aria")
    c = TestClient(servermod.app)
    assert c.post("/api/users/login", json={"name": "bob-ws", "password": "bob-password-1"}).status_code == 200
    r = c.put("/api/brain/fallbacks", json={"fallbacks": [{"executor": "claude-code", "model": ""}]})
    assert r.status_code == 403


def test_the_arena_seats_no_agent_cli_for_a_non_admin(people, monkeypatch):
    _ada, bob = people
    monkeypatch.setitem(servermod.state.machine_cfg(), "engine", "aria")
    brains = {"executors": [{"id": "claude-code", "kind": "agent"}, {"id": "aria", "kind": "provider"}]}
    with usersmod.as_user(bob["id"]):
        assert [e["id"] for e in servermod._brains_for_caller(brains)["executors"]] == ["aria"]
