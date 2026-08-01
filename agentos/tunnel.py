"""Reaching this machine from anywhere, without opening a port on the router.

`remote.py` answers "may someone else use this AgentOS" — a passphrase, a bind
address, lockout on repeated failures. It cannot answer "and how do they get
here", which on a laptop behind NAT is the harder half: there is no public
address to type, and asking someone to forward a port on their home router is
not a feature.

This module is the second half. It drives a tunnel provider already on the
machine and hands back a URL that works from a phone on mobile data:

    tailscale   an encrypted network between your own devices. `serve` publishes
                AgentOS to your tailnet over HTTPS with a real certificate;
                `funnel` publishes it to the whole internet. Preferred, because
                the tailnet case is private by construction — only your devices.
    cloudflared a public HTTPS URL for anything, no account needed for a quick
                tunnel. The fallback when there is no tailnet.

**The passphrase gate applies here too, and that is the point.** A tunnel
proxies to 127.0.0.1, so it would otherwise sail straight past `remote.py`'s
rule that AgentOS must not be reachable off-loopback without a passphrase — we
would have built a hole around our own gate. Publishing is refused until remote
access is configured, and `funnel` (the public internet, not just your devices)
says plainly what it is before it starts.

Three faces (CLAUDE.md):
  GUI  Settings → System → Remote access, beside the passphrase it depends on.
  TUI  `agentos tunnel` / `--on [--public]` / `--off`; this is the face that
       matters on a headless box, which is exactly where you cannot walk over to
       the machine to read its address.
  SUI  identical to GUI. The URL is worth showing on the desktop because the
       thing you do next is type it into a different device.
"""

from __future__ import annotations

import asyncio
import json
import shutil

# Provider ids, in the order they are offered.
PROVIDERS = ("tailscale", "cloudflared")


def _which(name: str) -> str:
    from .mcp_client import _extended_path
    return shutil.which(name, path=_extended_path()) or ""


async def _run(argv: list[str], timeout: int = 25) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, (out or b"").decode(errors="replace")
    except asyncio.TimeoutError:
        return 124, "timed out"
    except Exception as exc:
        return 1, str(exc)


async def tailscale_state() -> dict:
    """Installed, logged in, and what this machine is called on the tailnet."""
    cli = _which("tailscale")
    if not cli:
        return {"installed": False, "reason": "Tailscale is not installed",
                "install": "https://tailscale.com/download"}
    code, out = await _run([cli, "status", "--json"], timeout=20)
    if code != 0:
        return {"installed": True, "running": False,
                "reason": "Tailscale is installed but not responding"}
    try:
        data = json.loads(out)
    except Exception:
        return {"installed": True, "running": False,
                "reason": "Tailscale returned something this build could not read"}
    state = str(data.get("BackendState") or "")
    self_ = data.get("Self") or {}
    host = str(self_.get("DNSName") or "").rstrip(".")
    if state != "Running":
        return {"installed": True, "running": False, "state": state,
                "reason": f"Tailscale is not connected ({state or 'stopped'}) — "
                          f"run `tailscale up` once to sign in"}
    peers = [p for p in (data.get("Peer") or {}).values()]
    # `serve`/`funnel` need an HTTPS certificate for this node, which is a
    # tailnet-wide switch in the admin console. Without it `tailscale serve`
    # blocks trying to provision a certificate that can never be issued — it
    # hung for 45s here with no output, which is worse than any error message.
    # Detected up front so the UI can state the one-time fix instead of freezing.
    certs = data.get("CertDomains") or []
    return {"installed": True, "running": True, "state": state, "host": host,
            "ips": self_.get("TailscaleIPs") or [],
            "https": bool(certs),
            "devices": [str(p.get("HostName") or "") for p in peers if p.get("HostName")],
            "reason": ""}


def _v4(ips) -> str:
    for ip in ips or []:
        if ":" not in str(ip):
            return str(ip)
    return ""


async def reachable(cfg: dict) -> list[dict]:
    """Addresses that work RIGHT NOW, from wherever those devices are.

    This is the part that was missing. AgentOS listed only LAN addresses, so a
    machine already reachable from a phone on mobile data — over a tailnet that
    was up, connected and carrying traffic — looked like it could only be used
    from the same room. The capability existed; nothing ever showed it.
    """
    port = int(cfg.get("port") or 8321)
    from . import remote
    if not remote.enabled(cfg):
        return []
    out: list[dict] = []
    ts = await tailscale_state()
    if ts.get("running"):
        host, ip = ts.get("host", ""), _v4(ts.get("ips"))
        if host:
            out.append({"url": f"http://{host}:{port}", "via": "Tailscale",
                        "who": "your devices, from anywhere",
                        "note": "needs MagicDNS; the address below always works"})
        if ip:
            out.append({"url": f"http://{ip}:{port}", "via": "Tailscale",
                        "who": "your devices, from anywhere",
                        "note": "encrypted end to end by Tailscale"})
    for addr in remote.lan_addresses(port):
        out.append({"url": addr, "via": "This network", "who": "devices on this Wi-Fi",
                    "note": ""})
    return out


async def providers() -> list[dict]:
    """Every way out of this machine, and whether it can be used right now."""
    out = []
    ts = await tailscale_state()
    out.append({
        "id": "tailscale", "title": "Tailscale",
        "what": "A private network between your own devices. AgentOS appears at an "
                "HTTPS address only your devices can reach.",
        "available": bool(ts.get("running")),
        "reason": ts.get("reason", ""),
        "install": ts.get("install", ""),
        "host": ts.get("host", ""),
        "devices": ts.get("devices", []),
        # Funnel is the same machinery pointed at the whole internet, so it is
        # offered as a choice ON this provider rather than as a separate one.
        "can_publish_publicly": bool(ts.get("running") and ts.get("https")),
        # Stated rather than discovered by hanging: serve/funnel cannot work
        # without a certificate, and that is a one-time tailnet-wide switch.
        "needs": ("" if ts.get("https") or not ts.get("running") else
                  "Enable HTTPS certificates for your tailnet (one switch, once) "
                  "to get a proper https:// address"),
        "needs_url": ("" if ts.get("https") or not ts.get("running")
                      else "https://login.tailscale.com/admin/dns"),
    })
    cf = _which("cloudflared")
    out.append({
        "id": "cloudflared", "title": "Cloudflare Tunnel",
        "what": "A public HTTPS address for this machine, no account needed. "
                "Anyone with the link can reach the sign-in page.",
        "available": bool(cf),
        "reason": "" if cf else "cloudflared is not installed",
        "install": "" if cf else "https://developers.cloudflare.com/cloudflare-one/"
                                 "connections/connect-networks/downloads/",
        "install_cmd": "" if cf else CF_INSTALL_CMD,
        "install_note": "" if cf else (
            "Cloudflare's tunnel client. Gives this machine a public https:// name "
            "with no account and nothing opened on your router."),
        "host": "", "devices": [], "can_publish_publicly": bool(cf),
    })
    return out


def gate(cfg: dict) -> str:
    """Why publishing must not start yet, or "" when it may.

    The same rule `remote.py` enforces for binding off-loopback. A tunnel reaches
    AgentOS through 127.0.0.1, so without this check it would be a way around the
    passphrase rather than a way to it.
    """
    from . import remote
    r = cfg.get("remote") or {}
    if not r.get("pass_hash"):
        return ("set a remote-access passphrase first — a tunnel would otherwise "
                "put this machine online with no sign-in at all "
                "(Settings → System → Remote access)")
    if not remote.enabled(cfg):
        return "turn remote access on first — a tunnel to a closed door is not useful"
    return ""


async def status(cfg: dict) -> dict:
    """Is anything published right now, and at what address."""
    port = int(cfg.get("port") or 8321)
    ts = await tailscale_state()
    url, kind, provider = "", "", ""
    if ts.get("running"):
        cli = _which("tailscale")
        code, out = await _run([cli, "serve", "status", "--json"], timeout=20)
        if code == 0 and out.strip() and out.strip() != "null":
            try:
                conf = json.loads(out)
            except Exception:
                conf = {}
            host = ts.get("host", "")
            # AllowFunnel present and true => reachable from the public internet
            funnel = any(bool(v) for v in (conf.get("AllowFunnel") or {}).values())
            if conf.get("TCP") or conf.get("Web"):
                provider, url = "tailscale", f"https://{host}/" if host else ""
                kind = "public" if funnel else "tailnet"
    cf = cloudflared_url()
    if cf and not url:
        url, kind, provider = cf, "public", "cloudflared"
    return {"published": bool(url), "url": url, "kind": kind, "provider": provider,
            "port": port, "gate": gate(cfg),
            "reachable": await reachable(cfg),
            "providers": await providers()}


async def start(cfg: dict, provider: str = "tailscale", public: bool = False) -> tuple[bool, str, str]:
    """Publish AgentOS. Returns (ok, message, url)."""
    blocked = gate(cfg)
    if blocked:
        return False, blocked, ""
    port = int(cfg.get("port") or 8321)

    if provider == "tailscale":
        ts = await tailscale_state()
        if not ts.get("running"):
            return False, ts.get("reason", "Tailscale is not available"), ""
        if not ts.get("https"):
            # Refuse rather than hang. `tailscale serve` blocks indefinitely
            # trying to provision a certificate the tailnet cannot issue.
            return False, ("your tailnet does not have HTTPS certificates enabled, "
                           "which serve needs — turn it on once at "
                           "login.tailscale.com/admin/dns. Meanwhile the Tailscale "
                           "address already listed works from all your devices."), ""
        cli = _which("tailscale")
        verb = "funnel" if public else "serve"
        code, out = await _run([cli, verb, "--bg", str(port)], timeout=45)
        if code != 0:
            return False, (out.strip() or f"tailscale {verb} failed")[:400], ""
        url = f"https://{ts.get('host', '')}/"
        where = ("the public internet — anyone with the link reaches your sign-in page"
                 if public else "your tailnet — only your own devices")
        return True, f"published to {where}", url

    if provider == "cloudflared":
        return await _start_cloudflared(port)

    return False, f"unknown provider: {provider}", ""


# A quick tunnel is a long-lived child that prints its own hostname, so unlike
# `tailscale serve` there is nothing to query afterwards — the URL exists only in
# that first burst of output, and the tunnel dies with the process. It is kept
# here so status() can report it and stop() can end it.
_CF: dict = {"proc": None, "url": ""}

_CF_URL_RE = r"https://[a-z0-9-]+\.trycloudflare\.com"


async def _start_cloudflared(port: int) -> tuple[bool, str, str]:
    """A public HTTPS name for this machine, with no account and no DNS to set up.

    This is the answer to "it should just work from anywhere": Cloudflare issues
    a hostname and a certificate, and the connection is made outbound from here,
    so nothing is forwarded on the router and no port is opened. The name is
    random and lasts as long as the tunnel — a stable name is what Tailscale, or
    a named Cloudflare tunnel with your own domain, is for.
    """
    import re

    cli = _which("cloudflared")
    if not cli:
        return False, "cloudflared is not installed", ""
    if _CF["proc"] and _CF["proc"].returncode is None:
        return True, "already published", _CF["url"]
    try:
        proc = await asyncio.create_subprocess_exec(
            cli, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except Exception as exc:
        return False, f"could not start cloudflared: {exc}", ""
    _CF["proc"], _CF["url"] = proc, ""

    async def _read_url() -> str:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                return ""
            m = re.search(_CF_URL_RE, line.decode(errors="replace"))
            if m:
                return m.group(0)

    try:
        url = await asyncio.wait_for(_read_url(), timeout=45)
    except asyncio.TimeoutError:
        url = ""
    if not url:
        with __import__("contextlib").suppress(Exception):
            proc.terminate()
        _CF["proc"] = None
        return False, "cloudflared started but never reported a URL", ""
    _CF["url"] = url
    return True, ("published to the public internet — anyone with this link reaches "
                  "your sign-in page"), url


def cloudflared_url() -> str:
    """The live quick-tunnel URL, or "" when nothing is running."""
    proc = _CF.get("proc")
    if proc is not None and proc.returncode is None:
        return str(_CF.get("url") or "")
    return ""


async def _stop_cloudflared() -> bool:
    proc = _CF.get("proc")
    if proc is None or proc.returncode is not None:
        return False
    with __import__("contextlib").suppress(Exception):
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=10)
    _CF["proc"], _CF["url"] = None, ""
    return True


async def stop(cfg: dict) -> tuple[bool, str]:
    """Take it offline again, whichever provider is publishing."""
    if await _stop_cloudflared():
        return True, "no longer published — this machine is private again"
    cli = _which("tailscale")
    if not cli:
        return False, "nothing to stop"
    code, out = await _run([cli, "serve", "reset"], timeout=30)
    if code != 0:
        return False, (out.strip() or "could not reset")[:300]
    return True, "no longer published — this machine is private again"


# Kept as data so the exact command can be shown before anything runs — the same
# contract components.py keeps for every optional piece.
CF_INSTALL_CMD = (
    "curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-amd64 -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared"
)


async def install(provider: str, note=None) -> tuple[bool, str]:
    """Install a tunnel provider into the user's own account. Never elevated."""
    if provider != "cloudflared":
        return False, (f"{provider} cannot be installed from here — "
                       "see the link beside it")
    if _which("cloudflared"):
        return True, "cloudflared is already installed"
    import os
    os.makedirs(os.path.expanduser("~/.local/bin"), exist_ok=True)
    try:
        proc = await asyncio.create_subprocess_shell(
            CF_INSTALL_CMD, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except Exception as exc:
        return False, f"could not install cloudflared: {exc}"
    if note:
        await note((out or b"").decode(errors="replace")[-400:])
    if proc.returncode != 0 or not _which("cloudflared"):
        return False, "the download failed — install it by hand from the link beside it"
    return True, "cloudflared installed"
