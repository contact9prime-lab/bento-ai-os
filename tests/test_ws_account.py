"""A chat started over the socket belongs to the account that started it.

The socket has no HTTP middleware, so `resolve_user` never runs for it, and the receive
loop read `state["store"]` itself before any turn entered `users.as_user`: a NEW chat's
conversation row (titled with the first message) was created in the MACHINE's database
while its messages went into the person's. On a machine with accounts a new chat never
appeared in its owner's list, and every account's titles piled up in one shared file.
Found by the cloud-standby end-to-end run (two accounts moved to a container).
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _titles(db: Path):
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    try:
        return [r[0] for r in con.execute("select title from conversations")]
    finally:
        con.close()


def test_a_new_chat_is_created_in_its_owners_home(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import config as cfgmod
    from agentos import server as servermod
    from agentos import users as usersmod
    ada = usersmod.create("ada", "ada-password-1", role="admin")
    bob = usersmod.create("bob", "bob-password-1")
    with TestClient(servermod.app) as cl:
        for who, pw in (("ada", "ada-password-1"), ("bob", "bob-password-1")):
            c = TestClient(servermod.app)
            assert c.post("/api/users/login", json={"name": who, "password": pw}).status_code == 200
            cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
            with cl.websocket_connect("/ws", headers={"cookie": cookie}) as ws:
                ws.send_text(json.dumps({"type": "chat", "text": f"{who}'s private question"}))
                seen = []
                for _ in range(20):
                    ev = json.loads(ws.receive_text())
                    seen.append(ev["type"])
                    if ev["type"] == "turn_end":
                        break
                assert "conversation" in seen
    machine = Path(cfgmod.AGENTOS_HOME) / "agentos.db"
    assert _titles(usersmod.db_for(ada["id"])) == ["ada's private question"]
    assert _titles(usersmod.db_for(bob["id"])) == ["bob's private question"]
    assert not [t for t in _titles(machine) if "private question" in t], \
        "a person's chat title landed in the machine's shared database"
