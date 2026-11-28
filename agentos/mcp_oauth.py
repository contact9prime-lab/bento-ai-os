"""OAuth for remote MCP servers — the reason the popular ones could not be added.

Before this, `MCPServer._run` opened an HTTP transport with static `headers` and
nothing else. That is enough for a server that takes an API key and no more, which
is why the http servers already configured on this machine work. Every *first-party*
remote server — Canva, Higgsfield, Notion, Linear, Figma, Replicate, fal — answers
an unauthenticated `initialize` with:

    HTTP/2 401
    www-authenticate: Bearer resource_metadata="https://…/.well-known/oauth-protected-resource/mcp"

so adding one by URL alone produced a server stuck in `error` forever. A catalogue
entry without this module would have been a dead control, which the honesty rules
forbid, so the two shipped together.

The protocol work is entirely the SDK's: `mcp.client.auth.OAuthClientProvider` does
RFC 9728 resource discovery, RFC 8414 server metadata, RFC 7591 dynamic client
registration and PKCE, then refreshes the token when it expires. This module supplies
the three things the SDK cannot know:

- **where tokens live** (`_Storage`),
- **how a human is shown the consent page** (`_redirect`),
- **how the answer gets back** (`_callback`, resolved by the callback route).

## Why the redirect URI carries the server name

Every pending authorisation needs to be told apart, and the obvious discriminator —
the OAuth `state` parameter — is generated inside the SDK where we cannot see it.
So each server gets its own redirect path, `/api/mcp/oauth/callback/<name>`, which
is registered with the provider at DCR time. Correlation is then structural rather
than something this module has to track and could get wrong when two servers are
authorising at once.

## Three faces

- **GUI** — Store shows Connect; the browser opens on this machine.
- **SUI** — identical, because the browser *is* on this machine.
- **TUI / headless / a phone** — there is no browser to open here, so the URL is
  stated (`bento mcp connect <name>` prints it, the TUI shows it) and can be opened
  anywhere. The callback is an ordinary HTTP route, so finishing the flow from a
  laptop against a headless box works — the one requirement is that the machine is
  reachable at `oauth_redirect_base`, which is why that is a setting and not a
  hardcoded `localhost`.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import hashlib
import json
import os
import time
from pathlib import Path

from . import config as cfgmod
from . import users as usersmod

try:
    from mcp.client.auth import OAuthClientProvider, TokenStorage
    from mcp.shared.auth import (OAuthClientInformationFull, OAuthClientMetadata,
                                 OAuthToken)
    HAVE_OAUTH = True
    try:
        # mcp 2.x: the callback hands back a result object, with the issuer the redirect named
        from mcp.shared.auth import AuthorizationCodeResult
    except ImportError:
        AuthorizationCodeResult = None   # type: ignore[assignment,misc]   # mcp 1.x: a (code, state) tuple
except Exception:  # pragma: no cover - very old SDK
    OAuthClientProvider = None  # type: ignore
    TokenStorage = object       # type: ignore
    HAVE_OAUTH = False

# A token belongs to one account and one address. It lived here by server name alone, machine
# wide, so anyone who named a server `notion` and pointed it at their own URL was handed the
# admin's Notion token, and pointing it at the real URL gave them the admin's Notion.
# `_token_dir` is where it lives now; old files by name are moved on first use (`_read`).

#: How long a human has to finish the consent page before the attempt is abandoned.
#: Matches the SDK's own default; a shorter window punishes anyone who has to log in
#: and pick a workspace first.
AUTH_TIMEOUT = 300.0


# ---- pending authorisations -----------------------------------------------------
#
# One entry per server currently waiting for a human. The UI polls this (it is part
# of /api/mcp status) so a server mid-authorisation reads as "waiting for you" rather
# than as a connection that is simply slow.

class Pending:
    def __init__(self, name: str, url: str, uid: str = ""):
        self.name = name
        self.url = url
        self.uid = uid
        self.started = time.time()
        self.event = asyncio.Event()
        self.code = ""
        self.state: str | None = None
        self.iss: str | None = None       # RFC 9207: the issuer the redirect named, checked by mcp 2.x
        self.error = ""


_pending: dict[tuple[str, str], Pending] = {}     # (account, server name)
_notify = None    # async fn(dict) -> None — the websocket broadcast
_ui_probe = None  # fn() -> bool — is a UI actually watching right now?


def set_notifier(fn, ui_probe=None):
    """Wire in the websocket broadcast so the UI learns without polling.

    `ui_probe` answers "is anyone looking at a UI right now?", which decides who
    opens the consent tab. If a UI is connected it opens the page itself — it knows
    which machine the human is sitting at, and a phone driving a headless box must
    not have its consent page opened in another room. With nothing watching, this
    process is the only candidate and opens it here.
    """
    global _notify, _ui_probe
    _notify = fn
    _ui_probe = ui_probe


def _me() -> str:
    return usersmod.current() or ""


def pending_status() -> list[dict]:
    """What is waiting for this account right now. The URL carries the flow's `state`."""
    me = _me()
    return [{"name": p.name, "url": p.url, "waiting_for": int(time.time() - p.started)}
            for (uid, _n), p in _pending.items() if uid == me]


def pending_url(name: str) -> str:
    p = _pending.get((_me(), name))
    return p.url if p else ""


def resolve(name: str, code: str, state: str | None, error: str = "", iss: str | None = None) -> bool:
    """Called by the callback route, as whoever the browser is signed in as. True if a flow
    of THEIRS was waiting: another account's browser finishes nothing."""
    p = _pending.get((_me(), name))
    if not p:
        return False
    p.code, p.state, p.error, p.iss = code, state, error, (str(iss)[:500] if iss else None)
    p.event.set()
    return True


def cancel(name: str) -> bool:
    """Abandon a pending authorisation (the user closed the tab, or changed their mind)."""
    p = _pending.get((_me(), name))
    if not p:
        return False
    p.error = "cancelled"
    p.event.set()
    return True


# ---- token storage --------------------------------------------------------------

def _safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_.")[:64] or "server"


def _token_dir(uid: str) -> Path:
    # read at call time: tests and a restore move the home
    return usersmod.home_for(uid) / "oauth"


def _legacy_path(name: str) -> Path:
    return cfgmod.AGENTOS_HOME / "oauth" / f"{_safe(name)}.json"


def _token_path(name: str, url: str, uid: str | None = None) -> Path:
    who = _me() if uid is None else uid
    tag = hashlib.sha256(url.strip().encode()).hexdigest()[:16]
    return _token_dir(who) / f"{_safe(name)}-{tag}.json"


def _heir(uid: str) -> bool:
    """Who a token saved by name alone belongs to: the machine's owner. Without accounts that
    is the machine; with them, the first admin, who is the person the machine was adopted by."""
    if not usersmod.enabled():
        return not uid
    admins = [u["id"] for u in usersmod._read()["users"] if u.get("role") == "admin"]
    return bool(admins) and uid == admins[0]


def _read(name: str, url: str, uid: str | None = None) -> dict:
    who = _me() if uid is None else uid
    p = _token_path(name, url, who)
    old = _legacy_path(name)
    # An old file records no address, so it goes to the owner's server of this name once, and
    # to nobody else's. The first read under its new name is what keeps the connection.
    if not p.exists() and old.exists() and _heir(who):
        p.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            p.parent.chmod(0o700)
        with contextlib.suppress(OSError):
            os.replace(old, p)
    try:
        raw = json.loads(p.read_text())
    except Exception:
        return {}
    ref = raw.get("vault") if isinstance(raw, dict) else None
    if not ref:
        if raw.get("tokens") or raw.get("client"):
            # a file from before the vault held these: moved in now, the file keeps a marker
            with contextlib.suppress(Exception):
                _write(name, url, raw, who)
        return raw
    from . import vault
    try:
        with usersmod.as_user(who):
            return json.loads(vault.get(ref, f"MCP server {name}") or "{}")
    except Exception:
        return {}


def _vault_name(p: Path) -> str:
    return "mcp.oauth." + p.stem


def _write(name: str, url: str, data: dict, uid: str | None = None):
    """The sign-in (tokens and the registered client) goes into the account's vault; the file
    keeps only a reference and whether there are tokens, so a listing never opens the vault."""
    who = _me() if uid is None else uid
    p = _token_path(name, url, who)
    p.parent.mkdir(parents=True, exist_ok=True)
    from . import vault
    with usersmod.as_user(who):
        ref = vault.put(_vault_name(p), json.dumps(data))
    marker = {"vault": ref, "has_tokens": bool(data.get("tokens")),
              "updated_at": data.get("updated_at") or time.time()}
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(marker, f)
    os.replace(tmp, p)
    try:
        p.parent.chmod(0o700)
    except OSError:
        pass


def has_tokens(name: str, url: str) -> bool:
    try:
        raw = json.loads(_token_path(name, url).read_text())
    except Exception:
        raw = None
    if isinstance(raw, dict) and raw.get("vault"):
        return bool(raw.get("has_tokens"))
    return bool(_read(name, url).get("tokens"))


def forget(name: str) -> bool:
    """Disconnect: drop tokens AND the registered client.

    Both, deliberately. Keeping the DCR client registration would silently re-use an
    authorisation the user just asked to end — "Disconnect" has to mean the next
    connect asks again.
    """
    who = _me()
    gone = list(_token_dir(who).glob(f"{glob.escape(_safe(name))}-*.json"))
    # this name's old file is the owner's to forget, and nobody else's
    if _heir(who) and _legacy_path(name).exists():
        gone.append(_legacy_path(name))
    from . import vault
    for p in gone:
        with contextlib.suppress(Exception):
            with usersmod.as_user(who):
                vault.forget(_vault_name(p))
        with contextlib.suppress(OSError):
            p.unlink()
    return bool(gone)


class _Storage(TokenStorage):  # type: ignore[misc]
    """Token + client-registration storage, one JSON file per (account, server, address).
    The account is fixed when the connection starts, because the SDK calls back later."""

    def __init__(self, name: str, url: str, uid: str):
        self.name, self.url, self.uid = name, url, uid

    async def get_tokens(self):
        raw = _read(self.name, self.url, self.uid).get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens) -> None:
        data = _read(self.name, self.url, self.uid)
        data["tokens"] = json.loads(tokens.model_dump_json(exclude_none=True))
        data["updated_at"] = time.time()
        _write(self.name, self.url, data, self.uid)

    async def get_client_info(self):
        raw = _read(self.name, self.url, self.uid).get("client")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, client_info) -> None:
        data = _read(self.name, self.url, self.uid)
        data["client"] = json.loads(client_info.model_dump_json(exclude_none=True))
        _write(self.name, self.url, data, self.uid)


# ---- the provider ---------------------------------------------------------------

def redirect_base() -> str:
    """Where the authorisation server sends the browser back to.

    Configurable because the default is only right when the browser and the server
    are on the same machine. On a headless box you finish the flow from a laptop, and
    the address that box is reachable at is something only the operator knows.
    """
    cfg = cfgmod.load_config()
    base = str((cfg.get("mcp_oauth") or {}).get("redirect_base") or "").strip()
    if base:
        return base.rstrip("/")
    return f"http://127.0.0.1:{cfg.get('port', 8321)}"


def redirect_uri(name: str) -> str:
    return f"{redirect_base()}/api/mcp/oauth/callback/{name}"


def _open_browser(url: str) -> bool:
    """Open the consent page here, if there is a here to open it on.

    Never fatal: a machine with no browser is the normal headless case, and the URL
    has already been recorded for the TUI and the API to state.
    """
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return False
    try:
        import webbrowser
        return webbrowser.open(url)
    except Exception:
        return False


async def asks_sign_in(url: str) -> bool:
    """Does this address answer like a sign-in server (401 + `resource_metadata`)?

    A server added by URL alone (the MCP app's form, `add_mcp_server` from a README) was saved
    without `auth`, so one that wants OAuth sat in `error` with "ExceptionGroup" forever. Found
    with Zerodha's hosted Kite server. One unauthenticated `initialize`, through the guarded
    client, the same request the connection makes first. Unsure is False: nothing changes."""
    from . import netguard
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "bento", "version": "1"}}}
    try:
        async with netguard.client(timeout=8.0) as c:
            r = await c.post(url, json=body, headers={"Accept": "application/json, text/event-stream"})
    except Exception:
        return False
    www = r.headers.get("www-authenticate", "")
    return r.status_code == 401 and "resource_metadata" in www


def needs_probe(conf: dict) -> bool:
    """An http server with no way in of its own: no `auth`, no Authorization header."""
    if not isinstance(conf, dict) or conf.get("transport") != "http" or conf.get("auth"):
        return False
    heads = {str(k).lower() for k in (conf.get("headers") or {})}
    url = str(conf.get("url") or "")
    return "authorization" not in heads and url.startswith("https://")


def provider_for(name: str, url: str, scope: str = ""):
    """An `httpx.Auth` that authorises this server, or None if unsupported."""
    if not HAVE_OAUTH:
        return None
    uid = _me()
    slot = (uid, name)

    async def _redirect(auth_url: str) -> None:
        p = Pending(name, auth_url, uid)
        _pending[slot] = p
        watching = False
        try:
            watching = bool(_ui_probe and _ui_probe())
        except Exception:
            watching = False
        opened = False if watching else _open_browser(auth_url)
        if _notify:
            try:
                await _notify({"type": "mcp_oauth", "name": name, "url": auth_url,
                               "opened": opened})
            except Exception:
                pass

    async def _callback() -> tuple[str, str | None]:
        p = _pending.get(slot)
        if p is None:  # _redirect always runs first; be defensive rather than hang
            raise RuntimeError("no pending authorisation")
        try:
            await asyncio.wait_for(p.event.wait(), timeout=AUTH_TIMEOUT)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"nobody finished signing in to '{name}' within "
                f"{int(AUTH_TIMEOUT)}s — press Connect to try again")
        finally:
            _pending.pop(slot, None)
            if _notify:
                try:
                    await _notify({"type": "mcp_oauth_done", "name": name})
                except Exception:
                    pass
        if p.error:
            raise RuntimeError(f"authorisation failed: {p.error}")
        if AuthorizationCodeResult is not None:
            return AuthorizationCodeResult(code=p.code, state=p.state, iss=p.iss)
        return p.code, p.state

    meta = OAuthClientMetadata(
        redirect_uris=[redirect_uri(name)],
        client_name="AgentOS",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",   # a desktop app keeps no client secret
        scope=scope or None,
    )
    kw = {} if AuthorizationCodeResult is not None else {"timeout": AUTH_TIMEOUT}   # 2.x dropped it
    return OAuthClientProvider(
        server_url=url,
        client_metadata=meta,
        storage=_Storage(name, url, uid),
        redirect_handler=_redirect,
        callback_handler=_callback,
        **kw,
    )
