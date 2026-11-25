"""Bento is where what a run acts on is decided (claudeconn.py).

Reported as "Claude is just the middleware … what it needs to act on is what Bento should be
controlling": a connector added at claude.ai was used from a Bento chat with none of Bento's
vault, gate or ledger, and departments and missions couldn't see it at all, so the lead set out
to build a replacement. Every Claude Code run is now --strict-mcp-config, and each connector is
brought into Bento's own MCP servers."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import claudeconn, executors  # noqa: E402

ROOT = Path(__file__).parent.parent

# The owner's `claude mcp list`, with the private parts swapped for look-alikes.
LISTED = """Checking MCP server health…

claude.ai Airtable: https://mcp.airtable.com/mcp - ✔ Connected
claude.ai SolarPlay: https://solar.example.com/mcp/t/spmcp_N6wAzz9dj1Swx14cemA11kLlvl - ✔ Connected
claude.ai Supermetrics Marketing Analytics: https://mcp.supermetrics.com/mcp - ✔ Connected
claude.ai Invideo: https://mcp.invideo.io/sse - ✘ Failed to connect — HTTP 410: gone
claude.ai Zerodha Kite: https://mcp.kite.trade/mcp - ! Needs authentication
claude.ai Zoho CRM: https://someone-mcp-claude-60067008028.zohomcp.in/mcp/message - ✔ Connected
claude.ai Saarrthi: https://dasha.example.com/api/v1/mcp-api/mcp - ✘ Failed to connect — HTTP 503: x
local-files: npx -y @modelcontextprotocol/server-filesystem /tmp - ✔ Connected
my-http: https://tools.example.org/mcp (HTTP) - ✔ Connected
"""


def _by(items):
    return {i["key"]: i for i in items}


def test_the_list_is_read_into_names_addresses_and_kinds():
    items = claudeconn.parse(LISTED)
    assert len(items) == 9
    sm = next(i for i in items if i["name"] == "Supermetrics Marketing Analytics")
    assert sm["from"] == "claude.ai" and sm["url"] == "https://mcp.supermetrics.com/mcp"
    assert next(i for i in items if i["name"] == "my-http")["url"] == "https://tools.example.org/mcp"
    prog = next(i for i in items if i["name"] == "local-files")
    assert prog["kind"] == "program" and prog["url"] == ""


def test_the_plan_says_what_each_one_needs():
    plan = _by(claudeconn.plan(claudeconn.parse(LISTED), {"airtable": {"url": "https://mcp.airtable.com/mcp"}}))
    assert plan["airtable"]["state"] == "in-bento"
    assert plan["supermetrics"]["state"] == "ready", "the catalogue's own key is used"
    assert plan["local-files"]["state"] == "program" and "command is shown" in plan["local-files"]["why"]
    assert plan["invideo"]["state"] == "not-answering"
    assert plan["saarrthi"]["state"] == "not-answering"
    assert plan["zerodha-kite"]["state"] == "ready", "needs sign-in in Claude, so it gets one here"
    for k in ("solarplay", "zoho-crm"):
        assert plan[k]["private"] and plan[k]["state"] == "ready" and "vault" in plan[k]["why"]
        assert "…" in plan[k]["shown"] and "spmcp" not in plan[k]["shown"] and "60067008028" not in plan[k]["shown"]
    assert not plan["supermetrics"]["private"]


def test_bringing_in_adds_bento_servers_and_vaults_a_private_address(tmp_path, monkeypatch):
    from agentos import config as cfgmod
    from agentos import mcp_client, vault
    from agentos.memory import Store
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    store = Store(str(tmp_path / "agentos.db"))
    cfg = {"mcp_servers": {}}
    out = claudeconn.bring(cfg, store, None, claudeconn.parse(LISTED))
    added = {a["key"] for a in out["added"]}
    assert added == {"airtable", "solarplay", "supermetrics", "zerodha-kite", "zoho-crm", "my-http"}
    assert {s["key"] for s in out["skipped"]} == {"invideo", "saarrthi", "local-files"}
    sm = cfg["mcp_servers"]["supermetrics"]
    assert sm == {"transport": "http", "enabled": True, "from": "claude",
                  "url": "https://mcp.supermetrics.com/mcp", "auth": "oauth"}
    sp = cfg["mcp_servers"]["solarplay"]
    assert vault.is_ref(sp["url"]) and "auth" not in sp, "a token address needs no sign-in"
    assert "spmcp" not in str(cfg), "the token is in the vault, not the config"
    assert mcp_client.opened_url(sp, "solarplay").endswith("spmcp_N6wAzz9dj1Swx14cemA11kLlvl")
    assert store.mcp_reg_get("supermetrics")["source"] == "claude"
    again = claudeconn.bring(cfg, store, ["supermetrics"], claudeconn.parse(LISTED))
    assert not again["added"] and again["skipped"][0]["why"] == "Already connected in Bento."


def test_no_claude_code_is_a_sentence():
    import agentos.executors as ex
    old = ex._find_bin
    ex._find_bin = lambda names: ""
    try:
        got = claudeconn.listed()
    finally:
        ex._find_bin = old
    assert not got["ok"] and "isn't installed" in got["why"]


def test_every_claude_code_run_has_only_bentos_servers():
    """Measured on 2.1.331: without --strict-mcp-config the claude.ai connectors load a few
    seconds into a run; with it, none do. The person's own chat used to go without it."""
    for person in (True, False):
        env = executors.Envelope(workspace="/tmp", tools=("Read",))
        env.person = person
        assert "--strict-mcp-config" in executors._settings_flags(env)
    note = executors.capability_note()
    assert "no connectors of your own" in note and "Never build a replacement" in note


def test_gemini_gets_only_the_bridge_in_a_chat_too(tmp_path):
    argv, envv = executors.bridge_parts("gemini-cli", "http://127.0.0.1:1/x", "t", scratch=str(tmp_path))
    assert argv[-2:] == ["--allowed-mcp-server-names", executors.BRIDGE_SERVER]
    import json
    assert json.loads((tmp_path / "gemini-settings.json").read_text())["mcp"] == {"allowed": ["bento"]}


def test_the_faces_and_the_door():
    srv = (ROOT / "agentos/server.py").read_text()
    for route in ("api_mcp_claude(", "api_mcp_claude_bring("):
        h = srv[srv.index("async def " + route):][:900]
        assert "_require_admin()" in h, "the CLI is signed in as the machine's owner"
    b = srv[srv.index("async def api_mcp_claude_bring("):srv.index('@app.get("/api/mcp/oauth/callback')]
    assert "claudeconn.listed" in b, "read again here, never taken from the page"
    assert '"mcp.import"' in b
    l = srv[srv.index("async def api_mcp_claude("):srv.index("async def api_mcp_claude_bring(")]
    assert 'pop("url"' in l and 'pop("command"' in l
    js = (ROOT / "agentos/ui/src/js/16-mcp-telegram-logs.js").read_text()
    assert "mcpClaudeLook" in js and "/api/mcp/claude/bring" in js
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"claude"])' in main and "def _mcp_claude_cli" in main
