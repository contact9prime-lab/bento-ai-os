"""Surface-scoped permissions (IO gates) + the MCP Registry store."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP, Principal, surface_allows          # noqa: E402
from agentos import mcp_store                                      # noqa: E402


def _pdp(tmp_path, autonomy="balanced"):
    store = Store(tmp_path / "t.db")
    return PDP({"autonomy": autonomy}, store), store


def test_surface_allows():
    assert surface_allows("*", "gui")
    assert surface_allows("", "telegram")
    assert surface_allows("gui,tui", "tui")
    assert not surface_allows("gui,tui", "telegram")
    assert not surface_allows("gui", "")          # scoped grant never matches an unknown gate
    assert surface_allows("*", "")


def test_grant_applies_on_scoped_surface(tmp_path):
    pdp, store = _pdp(tmp_path)
    app = Principal("app", "a1")
    store.add_grant("app", "a1", "mcp.use", "mcp:github/*", surfaces="gui")
    ok = pdp.decide(app, "mcp.use", "mcp:github/create_issue",
                    {"risk": "risky", "surface": "gui"})
    assert ok.effect == "allow"


def test_io_gate_blocks_other_surfaces(tmp_path):
    pdp, store = _pdp(tmp_path)
    app = Principal("app", "a1")
    store.add_grant("app", "a1", "mcp.use", "mcp:github/*", surfaces="gui")
    dec = pdp.decide(app, "mcp.use", "mcp:github/create_issue",
                     {"risk": "risky", "surface": "telegram"})
    assert dec.effect == "deny"
    assert dec.rule == "io-gate"
    assert "telegram" in dec.reason


def test_unscoped_grant_covers_every_surface(tmp_path):
    pdp, store = _pdp(tmp_path)
    app = Principal("app", "a1")
    store.add_grant("app", "a1", "mcp.use", "mcp:github/*")  # default '*'
    for surface in ("gui", "tui", "telegram", "api", "task", ""):
        assert pdp.decide(app, "mcp.use", "mcp:github/create_issue",
                          {"risk": "risky", "surface": surface}).effect == "allow"


def test_scoped_deny_only_bites_its_surface(tmp_path):
    pdp, store = _pdp(tmp_path)
    app = Principal("app", "a1")
    store.add_grant("app", "a1", "mcp.use", "mcp:github/*")                  # allow anywhere
    store.add_grant("app", "a1", "mcp.use", "mcp:github/*", effect="deny",
                    surfaces="telegram")                                     # …but not telegram
    assert pdp.decide(app, "mcp.use", "mcp:github/x",
                      {"risk": "risky", "surface": "gui"}).effect == "allow"
    assert pdp.decide(app, "mcp.use", "mcp:github/x",
                      {"risk": "risky", "surface": "telegram"}).effect == "deny"


def test_no_grant_still_falls_to_defaults(tmp_path):
    """The IO gate only fires when consent exists elsewhere — no grants at all keeps
    today's default behavior (safe tools run, risky asks)."""
    pdp, _ = _pdp(tmp_path)
    dec = pdp.decide(Principal("user", ""), "tool.use", "tool:read_file x",
                     {"risk": "safe", "surface": "telegram"})
    assert dec.effect == "allow"
    assert dec.rule == "default"


def test_set_grant_surfaces(tmp_path):
    _, store = _pdp(tmp_path)
    gid = store.add_grant("app", "a1", "tool.use", "tool:notify*")
    assert store.set_grant_surfaces(gid, "gui,telegram")
    g = next(g for g in store.grants_live() if g["id"] == gid)
    assert g["surfaces"] == "gui,telegram"


def test_compose_app_page_fragment_and_fulldoc():
    from agentos.server import _compose_app_page, _lint_app_html
    rt = "<script>RT</script>"
    # fragment: shell + design system + runtime
    page = _compose_app_page("<h1>Hi</h1>", rt)
    assert page.startswith("<!DOCTYPE html>") and 'id="agentos-ui"' in page
    assert page.index(rt) < page.index("<h1>Hi</h1>")
    # full document: system css lands at the TOP of head (app's own styles override),
    # runtime right after <body>
    doc = "<!doctype html><html><head><style>button{color:red}</style></head><body><p>x</p></body></html>"
    page = _compose_app_page(doc, rt)
    assert page.count('id="agentos-ui"') == 1
    assert page.index('id="agentos-ui"') < page.index("button{color:red}")
    assert page.index("<body>") < page.index(rt) < page.index("<p>x</p>")
    # layout lint: the design-system contract bans absolute/fixed layout & rotated text
    bad = "<div style='position:fixed'></div>" + "<i style='position:absolute'></i>" * 3 \
          + "<b style='writing-mode:vertical-rl'>Find</b>"
    issues = " ".join(_lint_app_html(bad))
    assert "position:fixed" in issues and "position:absolute" in issues and "rotated" in issues


def test_rename_app(tmp_path):
    store = Store(tmp_path / "t.db")
    aid = store.save_app("Build An Application That Tr", "", "auto-named", "<h1>x</h1>" * 5)
    bid = store.save_app("Other", "", "", "<h1>y</h1>" * 5)
    assert store.rename_app(aid, "News Ticker") is None
    assert store.get_app(aid)["name"] == "News Ticker"
    assert "already exists" in store.rename_app(aid, "other")   # case-insensitive clash
    assert store.rename_app("nope", "X") == "app not found"
    assert store.rename_app(bid, "", description="tips") is None  # partial update
    assert store.get_app(bid)["description"] == "tips"
    assert store.get_app(bid)["name"] == "Other"


# ---- MCP Registry -----------------------------------------------------------

def test_mcp_registry_roundtrip(tmp_path):
    store = Store(tmp_path / "t.db")
    store.mcp_reg_upsert("github", title="GitHub", description="repo tools",
                         source="discovery", origin="io.github.github/github-mcp-server",
                         package={"registry_type": "npm", "identifier": "x"})
    row = store.mcp_reg_get("github")
    assert row and row["source"] == "discovery"
    assert row["package"]["registry_type"] == "npm"
    # partial upsert keeps existing fields
    store.mcp_reg_upsert("github", doc_file="mcp/github.md")
    row = store.mcp_reg_get("github")
    assert row["doc_file"] == "mcp/github.md" and row["title"] == "GitHub"
    assert row["source"] == "discovery"  # partial update must not reset to 'manual'
    store.mcp_reg_delete("github")
    assert store.mcp_reg_get("github") is None


def test_mcp_store_to_conf_npm_with_required_key():
    cand = {"remote_url": "", "registry_type": "npm", "identifier": "@x/server-y",
            "runtime_hint": "", "env": [{"name": "API_KEY", "required": True,
                                         "secret": True, "description": ""}]}
    conf, missing = mcp_store.to_conf(cand)
    assert conf["command"] == "npx" and "-y @x/server-y" == conf["args"]
    assert conf["enabled"] is False and missing == ["API_KEY"]
    conf2, missing2 = mcp_store.to_conf(cand, env_values={"API_KEY": "sk-1"})
    assert conf2["enabled"] is True and not missing2
    assert conf2["env"]["API_KEY"] == "sk-1"


def test_mcp_store_to_conf_remote():
    cand = {"remote_url": "https://mcp.example.com/mcp", "remote_type": "streamable-http",
            "registry_type": "", "identifier": "", "runtime_hint": "", "env": []}
    conf, missing = mcp_store.to_conf(cand)
    assert conf == {"transport": "http", "url": "https://mcp.example.com/mcp",
                    "enabled": True}


def test_mcp_store_to_conf_remote_headers():
    cand = {"remote_url": "https://server.smithery.ai/@x/y/mcp", "remote_type": "streamable-http",
            "registry_type": "", "identifier": "", "runtime_hint": "", "env": [],
            "remote_headers": [{"name": "Authorization", "value": "Bearer {smithery_api_key}",
                                "required": True, "secret": True, "description": ""}]}
    conf, missing = mcp_store.to_conf(cand)
    assert conf["headers"]["Authorization"] == "Bearer <YOUR_smithery_api_key>"
    assert conf["enabled"] is False and missing == ["smithery_api_key"]
    conf2, missing2 = mcp_store.to_conf(cand, env_values={"smithery_api_key": "sk-9"})
    assert conf2["headers"]["Authorization"] == "Bearer sk-9"
    assert conf2["enabled"] is True and not missing2


def test_mcp_doc_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_store, "USER_DOCS_DIR", tmp_path / "docs")
    store = Store(tmp_path / "t.db")
    mcp_store.record_install(store, "weather", title="Weather",
                             description="forecast tools", source="discovery",
                             origin="io.github.x/weather",
                             package={"registry_type": "pypi", "identifier": "weather-mcp",
                                      "env": [{"name": "WX_KEY", "required": True}]},
                             conf={"command": "uvx", "args": "weather-mcp",
                                   "env": {"WX_KEY": "<YOUR_WX_KEY>"}})
    row = store.mcp_reg_get("weather")
    assert row["doc_file"] == "mcp/weather.md"
    text = (tmp_path / "docs" / "mcp" / "weather.md").read_text()
    assert "mcp_weather_*" in text and "WX_KEY" in text and "mcp.use" in text
    # refresh with a live tool list adds the Tools section
    mcp_store.refresh_doc(store, "weather",
                          live={"status": "connected",
                                "tools": [{"name": "get_forecast", "description": "5-day"}]})
    text = (tmp_path / "docs" / "mcp" / "weather.md").read_text()
    assert "get_forecast" in text


def test_search_local_ranking(monkeypatch):
    servers = [
        {"registry_name": "io.github.a/weather-extras", "description": "misc tools"},
        {"registry_name": "io.github.b/weather", "description": "forecasts"},
        {"registry_name": "io.github.c/tools", "description": "includes weather data"},
        {"registry_name": "io.github.d/unrelated", "description": "nothing here"},
    ]
    monkeypatch.setattr(mcp_store, "_index",
                        {"updated_at": 1.0, "complete": True, "servers": servers})
    got = [c["registry_name"] for c in mcp_store.search_local("weather")]
    # exact tail match first, then tail prefix, then description-only match
    assert got == ["io.github.b/weather", "io.github.a/weather-extras",
                   "io.github.c/tools"]
    assert mcp_store.search_local("weather forecasts") == [servers[1]]
    # An empty query lists everything, curated storefront first — the curated
    # catalogue is merged ahead of the index (see mcp_catalog.py). None of the
    # rankings above are affected, because no curated entry matches "weather".
    from agentos import mcp_catalog
    empty = mcp_store.search_local("", limit=100)
    assert [c["registry_name"] for c in empty[:len(mcp_catalog.CATALOG)]] == \
        [c["registry_name"] for c in mcp_catalog.search("")]
    assert empty[len(mcp_catalog.CATALOG):] == servers


def test_index_status_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_store, "INDEX_PATH", tmp_path / "mcp_index.json")
    monkeypatch.setattr(mcp_store, "_index", None)
    st = mcp_store.index_status()
    assert st == {"count": 0, "complete": False, "syncing": False, "updated_at": 0}
    mcp_store._save_index({"updated_at": 5.0, "complete": True,
                           "servers": [{"registry_name": "x/y", "description": ""}]})
    monkeypatch.setattr(mcp_store, "_index", None)  # force re-read from disk
    st = mcp_store.index_status()
    assert st["count"] == 1 and st["complete"] is True


def test_ensure_index_without_loop_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_store, "INDEX_PATH", tmp_path / "mcp_index.json")
    monkeypatch.setattr(mcp_store, "_index", None)
    assert mcp_store.ensure_index() is False  # no running loop: nothing crashes


def test_npm_candidates_filter_and_shape():
    data = {"objects": [
        {"package": {"name": "acme-weather-mcp", "version": "2.1.0",
                     "description": "Weather MCP server", "keywords": ["mcp", "weather"],
                     "links": {"repository": "https://github.com/acme/weather-mcp"}}},
        {"package": {"name": "weather-utils",  # mentions nothing MCP — filtered out
                     "description": "generic weather helpers", "keywords": ["weather"]}},
        {"package": {"name": "mcp-unrelated", "description": "notes tool",
                     "keywords": ["mcp"]}},  # doesn't match the query — filtered out
    ]}
    got = mcp_store._npm_candidates(data, "weather")
    assert [c["registry_name"] for c in got] == ["npm:acme-weather-mcp"]
    c = got[0]
    assert c["registry_type"] == "npm" and c["identifier"] == "acme-weather-mcp"
    assert c["origin_source"] == "npm" and not c.get("agentic")
    conf, missing = mcp_store.to_conf(c)   # installs through the normal path
    assert conf["command"] == "npx" and conf["enabled"] is True and not missing


def test_github_candidates_are_agentic():
    data = {"items": [
        {"full_name": "acme/cool-mcp", "html_url": "https://github.com/acme/cool-mcp",
         "description": "an MCP server", "stargazers_count": 42, "archived": False},
        {"full_name": "acme/old-mcp", "html_url": "x", "archived": True},  # skipped
    ]}
    got = mcp_store._github_candidates(data)
    assert len(got) == 1
    c = got[0]
    assert c["registry_name"] == "github:acme/cool-mcp" and c["agentic"] is True
    assert "★42" in c["description"]


def test_normalize_handles_both_casings():
    item = {"server": {"name": "io.github.a/b", "description": "d", "version": "1.0",
                       "packages": [{"registryType": "npm", "identifier": "b",
                                     "environmentVariables": [{"name": "K",
                                                               "isRequired": True}]}]}}
    c = mcp_store._normalize(item)
    assert c["registry_type"] == "npm" and c["env"][0]["required"] is True
    item2 = {"name": "io.github.a/b", "description": "d",
             "packages": [{"registry_type": "pypi", "identifier": "b",
                           "environment_variables": [{"name": "K", "is_required": True}]}]}
    c2 = mcp_store._normalize(item2)
    assert c2["registry_type"] == "pypi" and c2["env"][0]["required"] is True
