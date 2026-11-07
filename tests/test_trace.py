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


def _leaky_cfg():
    return {"mcp_servers": {"p": {"command": "x", "args": ["--api-key", "sk-abcdefgh12345abcdefgh12345"],
                                  "url": "https://h/x?key=abc12345678",
                                  "env": {"DATABASE_URL": "postgres://u:pw1234567@h/db",
                                          "GITHUB_PAT": "ghp_abcdefghijklmnopqrstuvwx", "MY_THING": "plainsecretvalue"},
                                  "headers": {"X-Custom": "headersecretvalue"}}}}


def test_an_mcp_server_goes_as_its_shape():
    """Masking went by key name, so DATABASE_URL, MY_THING and --api-key in args stayed clear."""
    view = json.dumps(trace._finished({"config": trace.mask(trace._config_view(_leaky_cfg()))}), ensure_ascii=False)
    for secret in ("sk-abcdefgh12345", "abc12345678", "pw1234567", "ghp_abcdefgh", "plainsecretvalue", "headersecretvalue"):
        assert secret not in view, secret
    assert "env_template" in view and "DATABASE_URL" in view      # the shape stays: it is the useful part


def test_a_credential_pasted_into_a_chat_does_not_leave_either(tmp_path):
    from agentos.agentbundle import leak_scan
    from agentos.memory import Store
    store = Store(tmp_path / "t.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "use sk-ant-abcdefghijklmnop1234 and postgres://me:hunter2hunter@db/x "
                                   "and curl https://h/a?token=abcdef123456 --password hunter3hunter")
    store.add_message(cid, "assistant", "ok", {"token": "a-long-token-value-1234"})
    doc = trace.conversation(store, {"workspace": "/tmp/x"}, cid)
    out = trace.dumps(doc)
    for secret in ("sk-ant-abcdef", "hunter2hunter", "abcdef123456", "hunter3hunter", "a-long-token-value"):
        assert secret not in out, secret
    assert not leak_scan(out)


def test_prose_is_left_alone():
    assert trace.scrub("the well-known-key value is fine, see ?author=bob") == "the well-known-key value is fine, see ?author=bob"
