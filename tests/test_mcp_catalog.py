"""The curated catalogue and OAuth for remote MCP servers.

Offline by design: nothing here touches the network. The endpoints were probed live
before they were added, and `packaging/dev/probe-catalog.sh` re-probes them on
demand — a test suite that needed Canva to be up to pass would fail for reasons that
have nothing to do with this code.
"""

import json

import pytest

from agentos import mcp_catalog, mcp_oauth, mcp_store


# ---- the catalogue --------------------------------------------------------------

def test_catalogue_entries_are_complete_and_unique():
    keys, names = set(), set()
    for c in mcp_catalog.all_candidates():
        for field in ("key", "title", "description", "homepage", "remote_url",
                      "registry_name", "vendor", "category"):
            assert c[field], f"{c.get('key')}: {field} is empty"
        assert c["remote_url"].startswith("https://"), c["key"]
        assert c["category"] in dict(mcp_catalog.CATEGORIES), c["key"]
        assert c["key"] not in keys and c["registry_name"] not in names
        keys.add(c["key"])
        names.add(c["registry_name"])


def test_the_two_that_prompted_this_are_present():
    keys = {c["key"] for c in mcp_catalog.all_candidates()}
    assert {"canva", "higgsfield"} <= keys


def test_every_curated_entry_is_oauth():
    # A curated entry is offered as one click. Anything needing a pasted key belongs
    # in the preset list, not here — see the module docstring.
    for c in mcp_catalog.all_candidates():
        assert c["auth"] == "oauth", c["key"]
        assert c["env"] == [] and c["remote_headers"] == []


def test_search_matches_name_vendor_and_category():
    for q in ("canva", "Canva", "higgs", "media"):
        assert mcp_catalog.search(q), f"no catalogue hit for {q!r}"


def test_empty_query_returns_the_whole_storefront():
    assert len(mcp_catalog.search("")) == len(mcp_catalog.CATALOG)


def test_lookup_by_key_and_by_registry_name():
    assert mcp_catalog.get("canva")["key"] == "canva"
    assert mcp_catalog.get("com.canva/canva")["key"] == "canva"
    assert mcp_catalog.get("nope/nope") is None


# ---- merging into discovery -----------------------------------------------------

def test_curated_results_lead_the_registry(monkeypatch):
    """The registry's "canva" hits are knock-offs; the official one must rank above
    them, which is the entire reason for merging rather than appending."""
    monkeypatch.setattr(mcp_store, "_index", {
        "updated_at": 0.0, "complete": True,
        "servers": [{"registry_name": "com.mcparmory/canva", "description": "canva clone",
                     "key": "canva-clone", "identifier": "x", "remote_url": ""}]})
    out = mcp_store.search_local("canva", limit=10)
    assert out[0]["registry_name"] == "com.canva/canva"
    assert out[0].get("curated") is True
    assert any(c["registry_name"] == "com.mcparmory/canva" for c in out)


def test_search_local_respects_the_limit_with_curated_merged(monkeypatch):
    monkeypatch.setattr(mcp_store, "_index", {
        "updated_at": 0.0, "complete": True,
        "servers": [{"registry_name": f"x/s{i}", "description": "media thing",
                     "key": f"s{i}", "identifier": "x", "remote_url": ""}
                    for i in range(50)]})
    assert len(mcp_store.search_local("media", limit=3)) == 3


@pytest.mark.asyncio
async def test_lookup_resolves_curated_without_the_network():
    # No monkeypatching of httpx: if this reached the network the test would hang,
    # which is the assertion.
    cand = await mcp_store.lookup("com.higgsfield/higgsfield") \
        or await mcp_store.lookup("higgsfield")
    assert cand and cand["remote_url"].startswith("https://mcp.higgsfield.ai")


def test_to_conf_marks_curated_servers_oauth_and_enabled():
    conf, missing = mcp_store.to_conf(mcp_catalog.get("canva"))
    assert conf == {"transport": "http", "url": "https://mcp.canva.com/mcp",
                    "auth": "oauth", "enabled": True}
    assert missing == []      # nothing to paste, so nothing holds it disabled


def test_a_key_based_remote_still_writes_headers_and_no_auth():
    """The change must not have altered how an API-key server is configured."""
    conf, missing = mcp_store.to_conf({
        "remote_url": "https://example.test/mcp", "remote_type": "streamable-http",
        "remote_headers": [{"name": "Authorization", "value": "{token}", "required": True}],
        "env": []})
    assert "auth" not in conf
    assert conf["enabled"] is False and missing == ["token"]


# ---- token storage --------------------------------------------------------------

def test_tokens_round_trip_and_are_not_world_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_oauth, "TOKEN_DIR", tmp_path / "oauth")
    assert not mcp_oauth.has_tokens("canva")
    mcp_oauth._write("canva", {"tokens": {"access_token": "secret"}})
    assert mcp_oauth.has_tokens("canva")
    mode = (tmp_path / "oauth" / "canva.json").stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)   # a refresh token is a standing credential
    assert mcp_oauth.forget("canva") is True
    assert not mcp_oauth.has_tokens("canva")
    assert mcp_oauth.forget("canva") is False


def test_token_filename_cannot_escape_the_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_oauth, "TOKEN_DIR", tmp_path / "oauth")
    p = mcp_oauth._token_path("../../etc/passwd")
    assert p.parent == tmp_path / "oauth" and "/" not in p.name


def test_forget_drops_the_client_registration_too(tmp_path, monkeypatch):
    """Keeping the DCR client would silently reuse an authorisation the user just
    ended, so Disconnect has to remove both halves."""
    monkeypatch.setattr(mcp_oauth, "TOKEN_DIR", tmp_path / "oauth")
    mcp_oauth._write("canva", {"tokens": {"access_token": "a"},
                               "client": {"client_id": "c"}})
    mcp_oauth.forget("canva")
    assert mcp_oauth._read("canva") == {}


# ---- the pending-authorisation handshake ----------------------------------------

def test_resolve_reports_whether_anything_was_waiting():
    assert mcp_oauth.resolve("nobody", "code", None) is False


@pytest.mark.asyncio
async def test_callback_wakes_the_waiting_connection():
    p = mcp_oauth.Pending("canva", "https://auth.test/x")
    mcp_oauth._pending["canva"] = p
    try:
        assert [x["name"] for x in mcp_oauth.pending_status()] == ["canva"]
        assert mcp_oauth.pending_url("canva") == "https://auth.test/x"
        assert mcp_oauth.resolve("canva", "the-code", "the-state") is True
        assert p.event.is_set() and p.code == "the-code" and p.state == "the-state"
    finally:
        mcp_oauth._pending.pop("canva", None)


@pytest.mark.asyncio
async def test_cancel_unblocks_with_an_error():
    p = mcp_oauth.Pending("canva", "https://auth.test/x")
    mcp_oauth._pending["canva"] = p
    try:
        assert mcp_oauth.cancel("canva") is True
        assert p.event.is_set() and p.error == "cancelled"
    finally:
        mcp_oauth._pending.pop("canva", None)


def test_redirect_uri_is_per_server(monkeypatch):
    """Correlation is structural: two servers authorising at once must not be able to
    resolve each other's flow."""
    monkeypatch.setattr(mcp_oauth, "redirect_base", lambda: "http://127.0.0.1:8321")
    a, b = mcp_oauth.redirect_uri("canva"), mcp_oauth.redirect_uri("higgsfield")
    assert a != b and a.endswith("/api/mcp/oauth/callback/canva")


def test_redirect_base_is_configurable(monkeypatch):
    monkeypatch.setattr(mcp_oauth.cfgmod, "load_config",
                        lambda: {"mcp_oauth": {"redirect_base": "https://box.tail/"}})
    assert mcp_oauth.redirect_base() == "https://box.tail"


def test_redirect_base_defaults_to_the_configured_port(monkeypatch):
    monkeypatch.setattr(mcp_oauth.cfgmod, "load_config", lambda: {"port": 9999})
    assert mcp_oauth.redirect_base() == "http://127.0.0.1:9999"
