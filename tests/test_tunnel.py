"""Reaching this machine from elsewhere.

The load-bearing assertion is the gate. A tunnel reaches AgentOS through
127.0.0.1, so without an explicit check it would sail straight past the rule
that AgentOS must not be reachable off-loopback without a passphrase — we would
have shipped a hole around our own front door.
"""

import asyncio

import pytest

from agentos import tunnel


def cfg_with(**over):
    cfg = {"port": 8321, "remote": {"enabled": True, "pass_hash": "x" * 20}}
    cfg["remote"].update(over.pop("remote", {}))
    cfg.update(over)
    return cfg


# ------------------------------------------------------------------ the gate

def test_publishing_is_refused_without_a_passphrase():
    """The whole point. A tunnel proxies to loopback, so it would otherwise put
    this machine on the internet with no sign-in at all."""
    cfg = cfg_with(remote={"pass_hash": "", "enabled": True})
    problem = tunnel.gate(cfg)
    assert problem and "passphrase" in problem
    ok, msg, url = asyncio.run(tunnel.start(cfg))
    assert not ok and not url and "passphrase" in msg


def test_publishing_is_refused_when_remote_access_is_off():
    cfg = cfg_with(remote={"enabled": False})
    assert "remote access" in tunnel.gate(cfg)


def test_gate_is_clear_once_remote_access_is_configured():
    assert tunnel.gate(cfg_with()) == ""


# ------------------------------------------------- addresses that really work

def _fake_ts(monkeypatch, **state):
    base = {"installed": True, "running": True, "host": "box.tail1234.ts.net",
            "ips": ["100.64.0.1", "fd7a:115c::1"], "https": False,
            "devices": ["laptop"], "reason": ""}
    base.update(state)

    async def fake():
        return base
    monkeypatch.setattr(tunnel, "tailscale_state", lambda *a, **k: fake())
    return base


def test_the_tailnet_address_is_listed(monkeypatch):
    """This was the actual gap: the machine was already reachable from anywhere
    over a connected tailnet, and AgentOS showed only LAN addresses — so it
    looked like it could only be used from the same room."""
    _fake_ts(monkeypatch)
    monkeypatch.setattr(tunnel, "_v4", tunnel._v4)
    urls = [r["url"] for r in asyncio.run(tunnel.reachable(cfg_with()))]
    assert "http://box.tail1234.ts.net:8321" in urls
    assert "http://100.64.0.1:8321" in urls, "the IP works even without MagicDNS"


def test_ipv6_is_not_offered_as_the_plain_address(monkeypatch):
    """A bare IPv6 in a URL needs brackets; handing someone an unusable address
    is worse than handing them none."""
    _fake_ts(monkeypatch)
    urls = [r["url"] for r in asyncio.run(tunnel.reachable(cfg_with()))]
    assert not any("fd7a" in u for u in urls)


def test_nothing_is_listed_when_remote_access_is_off(monkeypatch):
    _fake_ts(monkeypatch)
    assert asyncio.run(tunnel.reachable(cfg_with(remote={"enabled": False}))) == []


def test_tailnet_addresses_say_they_reach_from_anywhere(monkeypatch):
    _fake_ts(monkeypatch)
    reach = asyncio.run(tunnel.reachable(cfg_with()))
    ts = [r for r in reach if r["via"] == "Tailscale"]
    assert ts and all("anywhere" in r["who"] for r in ts)


# -------------------------------------------------------- serve preconditions

def test_serve_refuses_fast_when_the_tailnet_has_no_https(monkeypatch):
    """`tailscale serve` blocks trying to provision a certificate the tailnet
    cannot issue — it hung for 45 seconds with no output. Refusing with the
    one-time fix is strictly better than freezing."""
    _fake_ts(monkeypatch, https=False)
    ok, msg, url = asyncio.run(tunnel.start(cfg_with()))
    assert not ok and not url
    assert "HTTPS certificates" in msg
    assert "admin/dns" in msg, "name the one-time fix"
    assert "already listed works" in msg, "and what works meanwhile"


def test_provider_reports_the_precondition_rather_than_looking_ready(monkeypatch):
    _fake_ts(monkeypatch, https=False)
    ts = next(p for p in asyncio.run(tunnel.providers()) if p["id"] == "tailscale")
    assert ts["available"] is True          # it IS usable — the addresses work
    assert ts["needs"], "but serve needs something, and it must say so"
    assert ts["can_publish_publicly"] is False


def test_provider_is_ready_when_https_is_enabled(monkeypatch):
    _fake_ts(monkeypatch, https=True)
    ts = next(p for p in asyncio.run(tunnel.providers()) if p["id"] == "tailscale")
    assert ts["needs"] == "" and ts["can_publish_publicly"] is True


def test_unavailable_tailscale_reports_why_and_how(monkeypatch):
    async def fake():
        return {"installed": False, "reason": "Tailscale is not installed",
                "install": "https://tailscale.com/download"}
    monkeypatch.setattr(tunnel, "tailscale_state", lambda *a, **k: fake())
    ts = next(p for p in asyncio.run(tunnel.providers()) if p["id"] == "tailscale")
    assert not ts["available"] and ts["reason"] and ts["install"]


def test_unknown_provider_is_refused():
    ok, msg, _ = asyncio.run(tunnel.start(cfg_with(), provider="carrier-pigeon"))
    assert not ok and "unknown provider" in msg


# ------------------------------------------------- a public name, set up for you

def test_a_quick_tunnel_is_reported_as_the_live_address(monkeypatch):
    """cloudflared's URL exists only in its first burst of output — nothing can be
    queried for it afterwards, so status() has to read it from the live process."""
    _fake_ts(monkeypatch, running=False)
    monkeypatch.setitem(tunnel._CF, "url", "https://abc-def.trycloudflare.com")

    class _P:
        returncode = None
    monkeypatch.setitem(tunnel._CF, "proc", _P())
    st = asyncio.run(tunnel.status(cfg_with()))
    assert st["published"] and st["provider"] == "cloudflared"
    assert st["url"] == "https://abc-def.trycloudflare.com"
    assert st["kind"] == "public", "a public name must not read as private"


def test_a_dead_quick_tunnel_is_not_reported_as_live(monkeypatch):
    class _P:
        returncode = 0
    monkeypatch.setitem(tunnel._CF, "proc", _P())
    monkeypatch.setitem(tunnel._CF, "url", "https://gone.trycloudflare.com")
    assert tunnel.cloudflared_url() == ""


def test_publishing_publicly_still_needs_the_passphrase(monkeypatch):
    """The gate is checked before the provider, so no provider can route around it."""
    cfg = cfg_with(remote={"pass_hash": "", "enabled": True})
    ok, msg, url = asyncio.run(tunnel.start(cfg, provider="cloudflared"))
    assert not ok and not url and "passphrase" in msg


def test_missing_cloudflared_offers_the_exact_command(monkeypatch):
    monkeypatch.setattr(tunnel, "_which", lambda n: "" if n == "cloudflared" else "/usr/bin/" + n)
    cf = next(p for p in asyncio.run(tunnel.providers()) if p["id"] == "cloudflared")
    assert not cf["available"] and cf["install_cmd"] and cf["install_note"]


def test_only_cloudflared_can_be_installed_from_here():
    ok, msg = asyncio.run(tunnel.install("tailscale"))
    assert not ok and "cannot be installed from here" in msg
