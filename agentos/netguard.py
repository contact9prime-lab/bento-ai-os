"""The one way this OS fetches an address somebody else named.

`fetch_url` is free for an app and safe for a model, so a stranger's app could ask this server
to read `http://127.0.0.1:8321/api/...` and get the body back: the request comes from loopback,
loopback is trusted on a machine with no accounts, and the opaque-origin sandbox is gone. The
same request reaches the LAN and a cloud's metadata address (169.254.169.254) on every install.

Five rules:

- **The address decides, never the name.** A name is resolved here, every answer must be public,
  and the connection goes to the address that was checked. DNS rebinding answers public to the
  check and private to the connection; with the address pinned there is no second answer to give.
  TLS still checks the certificate against the name (httpx's `sni_hostname`).
- **Every hop.** The check is a transport, so a redirect passes through it like the first request
  and no caller can forget.
- **A person may open a door, a model may not.** `security.fetch_allow` in the machine's config
  lists local hosts a person wants fetched (a NAS, a calendar server). `configure_agentos` cannot
  write it, and an app never gets it (`strict`), because an app is often a stranger's.
- **Two things no list opens.** Cloud metadata addresses, and loopback without a named port or on
  this server's own port. Those are the addresses the attack is after.
- **A provider is not a fetch.** Ollama's base_url, a provider's API, a pinned link and the
  loopback calls of the CLI are addresses the machine's owner configured or this code wrote. They
  do not come here.

Stdlib plus httpx. Free of the server, so a CLI verb can use it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import httpx

CONFIG_KEY = "fetch_allow"       # under `security` in the machine's config
ENV_ALLOW = "AGENTOS_FETCH_ALLOW"  # comma separated, for a test harness: set by whoever starts the server
RESOLVE_S = 10.0
MAX_ALLOW = 64

# Answer identity and credentials on the big clouds. 168.63.129.16 (Azure's wire server) is in a
# range that looks public, so looking public is not enough here.
_METADATA = frozenset(ipaddress.ip_address(a) for a in (
    "169.254.169.254", "169.254.170.2", "169.254.169.123", "100.100.100.200",
    "168.63.129.16", "192.0.0.192", "fd00:ec2::254", "fd00:ec2::23",
))
_METADATA_NAMES = ("metadata.google.internal", "metadata.goog", "instance-data")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V4_COMPAT = ipaddress.ip_network("::/96")


class Refused(httpx.TransportError):
    """Raised before a connection is made. A TransportError, so a caller that already says
    what went wrong with a fetch says this too."""

    def __init__(self, message: str, host: str = ""):
        super().__init__(message)
        self.host = host


def _unwrap(ip):
    """The IPv4 address hiding inside an IPv6 one. `::ffff:127.0.0.1` is loopback, and so are
    its 6to4, NAT64, Teredo and v4-compatible spellings."""
    if ip.version != 6:
        return ip
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in _NAT64 or (ip in _V4_COMPAT and int(ip) > 1):
        return ipaddress.ip_address(int(ip) & 0xffffffff)
    return ip


def kind_of(address: str) -> str:
    """'' for a public address, else 'metadata', 'loopback' or 'private'. Anything that cannot
    be read as an address is private: refused, never assumed fine."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return "private"
    outer, ip = ip, _unwrap(ip)
    if ip in _METADATA or outer in _METADATA:
        return "metadata"
    if ip.is_loopback or ip.is_unspecified:       # connecting to 0.0.0.0 reaches this machine
        return "loopback"
    if ip.is_multicast or ip.is_reserved or ip.is_link_local or not ip.is_global \
            or not outer.is_global or getattr(outer, "is_site_local", False):
        return "private"
    return ""


def _resolve(host: str, port: int) -> list[str]:
    """Every address the name has. A function of its own so a test can stand in for DNS."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out: list[str] = []
    for info in infos:
        a = str(info[4][0]).split("%", 1)[0]
        if a not in out:
            out.append(a)
    return out


def _machine_entries() -> list:
    """What a person listed, read from the machine's own file when a local address comes up:
    a public fetch never pays for it, and an account's view of the config cannot widen it."""
    from . import config as cfgmod
    try:
        cfg = json.loads(Path(cfgmod.CONFIG_PATH).read_text())
    except (OSError, ValueError):
        return []
    got = ((cfg.get("security") or {}).get(CONFIG_KEY)) if isinstance(cfg, dict) else None
    return list(got) if isinstance(got, list) else []


def clean_entry(entry) -> tuple[str, str]:
    """(the entry as stored, why it was refused). A host, `host:port`, an address, or a CIDR."""
    e = str(entry or "").strip().lower()
    e = e.removeprefix("http://").removeprefix("https://").rstrip("/")
    if not e:
        return "", "it is empty"
    if any(c.isspace() for c in e) or "/" in e.replace("/", "", 1) or "*" in e or "@" in e:
        return "", f"{e[:40]} is not a host, a host:port or a network"
    host, port = _split_entry(e)
    if port is not None and not 0 < port < 65536:
        return "", f"{e[:40]} has a port that does not exist"
    if "/" in host:
        try:
            net = ipaddress.ip_network(host, strict=False)
        except ValueError:
            return "", f"{e[:40]} is not a network"
        if net.prefixlen < (8 if net.version == 4 else 32):
            return "", f"{e[:40]} is too wide. Name a smaller network."
        return e, ""
    if host.lower() in _METADATA_NAMES or kind_of(host) == "metadata":
        return "", f"{host} is a cloud metadata address, which can never be allowed"
    if host == "localhost" or kind_of(host) == "loopback":
        if port is None:
            return "", f"{host} needs a port, because this server answers on loopback too"
    return e, ""


def clean_entries(entries) -> tuple[list[str], list[str]]:
    """What is kept, and a sentence for each entry that was dropped."""
    kept, dropped = [], []
    for e in list(entries or [])[:MAX_ALLOW]:
        c, why = clean_entry(e)
        if why:
            dropped.append(why)
        elif c not in kept:
            kept.append(c)
    return kept, dropped


def _split_entry(e: str) -> tuple[str, int | None]:
    if e.startswith("["):                         # [v6] or [v6]:port
        h, _, rest = e[1:].partition("]")
        return h, int(rest[1:]) if rest[1:].isdigit() else None
    if e.count(":") == 1:
        h, _, p = e.partition(":")
        return h, int(p) if p.isdigit() else -1
    return e, None


def _own_port() -> int:
    try:
        from . import config as cfgmod
        return int(json.loads(Path(cfgmod.CONFIG_PATH).read_text()).get("port") or 8321)
    except (OSError, ValueError, TypeError):
        return 8321


def _listed(host: str, port: int, address: str, kind: str) -> bool:
    """Did a person open this door? Loopback only on a named port that is not this server's."""
    if kind == "loopback" and port in (_own_port(), int(os.environ.get("AGENTOS_PORT") or 0)):
        return False
    entries = [*_machine_entries(), *(os.environ.get(ENV_ALLOW, "").split(","))]
    for raw in entries:
        e, why = clean_entry(raw)
        if why:
            continue
        h, p = _split_entry(e)
        if p is not None and p != port:
            continue
        if "/" in h:
            try:
                if ipaddress.ip_address(address) in ipaddress.ip_network(h, strict=False):
                    return p is not None or kind != "loopback"
            except ValueError:
                continue
        elif h in (host.lower(), address):
            return p is not None or kind != "loopback"
    return False


def _words(host: str, kind: str, strict: bool) -> str:
    if kind == "metadata":
        return f"{host} is a cloud metadata address, so it was not fetched."
    where = "this machine" if kind == "loopback" else "a private network"
    if strict:
        return f"{host} is on {where}, so it was not fetched. An app can only reach public addresses."
    return (f"{host} is on {where}, so it was not fetched. An admin can allow it in "
            f"Settings → Permissions → Local addresses.")


def judge(host: str, port: int, addresses: list[str], strict: bool = False, local_ok: bool = False) -> str:
    """The address to connect to, or raises Refused. Every answer must pass: a name with one
    public and one private answer is what a rebinding attack serves."""
    if not addresses:
        raise Refused(f"{host} has no address.", host)
    if host.lower().rstrip(".") in _METADATA_NAMES:
        raise Refused(_words(host, "metadata", strict), host)
    for a in addresses:
        kind = kind_of(a)
        if not kind or (local_ok and kind != "metadata"):
            continue
        if kind == "metadata" or strict or not _listed(host, port, a, kind):
            raise Refused(_words(host, kind, strict), host)
    return addresses[0]


async def pin(host: str, port: int, strict: bool = False, local_ok: bool = False) -> str:
    """Resolve and judge. A resolver that hangs is a refusal with a reason."""
    try:
        addresses = await asyncio.wait_for(asyncio.to_thread(_resolve, host, port), RESOLVE_S)
    except (OSError, UnicodeError, asyncio.TimeoutError) as e:
        raise httpx.ConnectError(f"could not resolve {host}: {type(e).__name__}") from e
    return judge(host, port, addresses, strict, local_ok)


def _proxy_for(scheme: str) -> str:
    return urllib.request.getproxies().get(scheme, "")


class GuardTransport(httpx.AsyncBaseTransport):
    """Every request this client makes, redirects included, passes `handle_async_request`."""

    def __init__(self, strict: bool = False, local_ok: bool = False):
        self.strict, self.local_ok = strict, local_ok
        self._inner = httpx.AsyncHTTPTransport()
        self._proxied: dict[str, httpx.AsyncHTTPTransport] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        host = url.raw_host.decode("ascii", "replace")
        port = url.port or (443 if url.scheme == "https" else 80)
        proxy = _proxy_for(url.scheme)
        if proxy and not urllib.request.proxy_bypass(host):
            # A proxy resolves for itself, so there is nothing to pin. An address it was named
            # directly is still judged here, and a name that resolves here is judged too.
            try:
                await pin(host, port, self.strict, self.local_ok)
            except httpx.ConnectError:
                pass
            t = self._proxied.setdefault(url.scheme, httpx.AsyncHTTPTransport(proxy=proxy))
            return await t.handle_async_request(request)
        address = await pin(host, port, self.strict, self.local_ok)
        extensions = dict(request.extensions)
        if url.scheme == "https":
            extensions["sni_hostname"] = host     # the certificate is checked against the name
        pinned = httpx.Request(request.method, url.copy_with(host=address), headers=request.headers,
                               stream=request.stream, extensions=extensions)
        return await self._inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._inner.aclose()
        for t in self._proxied.values():
            await t.aclose()


def client(*, strict: bool = False, local_ok: bool = False, **kw) -> httpx.AsyncClient:
    """An AsyncClient that can only reach what `judge` lets through. `strict` is an app's: no
    allow-list. `local_ok` keeps the metadata refusal and nothing else, for an address a person
    with the machine's authority typed themselves."""
    return httpx.AsyncClient(transport=GuardTransport(strict=strict, local_ok=local_ok), **kw)


async def read_capped(url: str, cap: int, *, strict: bool = False, timeout: float = 60.0,
                      headers: dict | None = None) -> tuple[int, str, bytes]:
    """(status, content type, body) of a GET, refused past `cap` bytes so a page cannot fill a
    disk or the server's memory by being long."""
    async with client(strict=strict, timeout=timeout, follow_redirects=True, headers=headers) as c:
        async with c.stream("GET", url) as r:
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > cap:
                    raise Refused(f"that file is larger than {cap // (1024 * 1024)} MB.", "")
            return r.status_code, r.headers.get("content-type", ""), bytes(body)


def host_port(url: str) -> tuple[str, int]:
    p = urlsplit(str(url or ""))
    if p.scheme not in ("http", "https") or not p.hostname:
        raise Refused("only http and https addresses can be fetched.", "")
    try:
        port = p.port or (443 if p.scheme == "https" else 80)
    except ValueError as e:
        raise Refused("that address has a port that does not exist.", p.hostname) from e
    return p.hostname, port


async def check_url(url: str, *, strict: bool = False, local_ok: bool = False) -> None:
    """For an address handed to something else that connects (git, the training service, the
    shared browser, an MCP client). It says no to what it can see now; only `client` holds
    against a redirect or a name that changes its answer afterwards."""
    host, port = host_port(url)
    await pin(host, port, strict, local_ok)


def refuse_loopback(url: str) -> None:
    """For `local_ok` callers that still must not touch this machine: a literal or a name."""
    host, port = host_port(url)
    try:
        addresses = _resolve(host, port)
    except (OSError, UnicodeError):
        addresses = [host] if host != "localhost" else ["127.0.0.1"]
    if any(kind_of(a) == "loopback" for a in addresses) and not _listed(host, port, addresses[0], "loopback"):
        raise Refused(_words(host, "loopback", False), host)


def check_url_sync(url: str, *, strict: bool = False, local_ok: bool = False) -> None:
    host, port = host_port(url)
    try:
        addresses = _resolve(host, port)
    except (OSError, UnicodeError) as e:
        raise httpx.ConnectError(f"could not resolve {host}: {type(e).__name__}") from e
    judge(host, port, addresses, strict, local_ok)
