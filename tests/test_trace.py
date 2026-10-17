"""One execution as one JSON file (agentos/trace.py).

Asked for as "for every execution I should be able to get the json file to see what
happened, what was the office and what executed, so I can send it to the AI to analyse
and fix the problem". Pinned: everything a chat started is in it (the run tree, each
run's events, the gate's decisions, the logs, the setting), nothing secret leaves, and
it is reachable from Chat, Missions → History, a route and `bento trace`.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import trace  # noqa: E402

ROOT = Path(__file__).parent.parent


def _seed(store):
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "ask Research")
    store.add_message(cid, "assistant", "done", {"steps": [{"type": "tool", "name": "department_task"}]})
    now = time.time()
    store.db.execute("INSERT INTO fabric_runs (id, kind, ref, parent_run, status, conversation_id, started_at) "
                     "VALUES ('r1','flow','desk','', 'ok', ?, ?)", (cid, now))
    store.db.execute("INSERT INTO fabric_runs (id, kind, ref, parent_run, status, started_at) "
                     "VALUES ('r2','delegate','quant','r1','ok', ?)", (now + 1,))
    store.db.execute("INSERT INTO fabric_runs (id, kind, ref, parent_run, status, started_at) "
                     "VALUES ('r3','audit','auditor','r1','ok', ?)", (now + 2,))
    store.db.commit()
    return cid


def test_a_chat_comes_with_everything_it_started(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = _seed(store)
    cfg = {"engine": "claude-code", "autonomy": "balanced",
           "providers": {"openai": {"api_key": "sk-abcdefghijklmnop1234"}},
           "telegram": {"bot_token": "123456:ABCDEFGHIJKLMNOP"},
           "mcp_servers": {"x": {"env": {"GITHUB_TOKEN": "ghp_secretsecretsecret"}}}}
    d = trace.conversation(store, cfg, cid)
    assert d["format"] == "bento-trace/1" and "how_to_read" in d
    assert [m["role"] for m in d["conversation"]["messages"]] == ["user", "assistant"]
    assert d["conversation"]["messages"][1]["meta"]["steps"][0]["name"] == "department_task"
    assert [r["id"] for r in d["runs"]] == ["r1", "r2", "r3"], "the whole tree, oldest first"
    text = trace.dumps(d)
    for secret in ("sk-abcdefghijklmnop1234", "123456:ABCDEFGHIJKLMNOP", "ghp_secretsecretsecret"):
        assert secret not in text
    assert "•••1234" in text
    assert d["setting"]["engine"] == "claude-code"
    # a run, asked by any of its runs, is the whole task from its top
    r = trace.run(store, cfg, "r2")
    assert r["ref"] == "r1" and len(r["runs"]) == 3 and r["conversation"]["id"] == cid


def test_it_is_reachable_everywhere():
    srv = (ROOT / "agentos/server.py").read_text()
    assert '@app.get("/api/trace/conversation/{cid}")' in srv and '@app.get("/api/trace/run/{rid}")' in srv
    assert "Content-Disposition" in srv[srv.index("def _trace_response("):][:400]
    chat = (ROOT / "agentos/ui/src/js/10-chat.js").read_text()
    assert 'onclick="chatTrace()"' in chat
    hist = (ROOT / "agentos/ui/src/js/14c-history.js").read_text()
    assert "/api/trace/run/" in hist and "${tr}" in hist
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert 'verb("trace"' in cli and "def _trace_cli(" in cli
    src = (ROOT / "agentos/trace.py").read_text()
    assert "import asyncio" not in src and "fastapi" not in src, "works with the server down"
