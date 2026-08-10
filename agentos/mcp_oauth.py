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
import json
import os
import time
from pathlib import Path

from . import config as cfgmod

try:
    from mcp.client.auth import OAuthClientProvider, TokenStorage
    from mcp.shared.auth import (OAuthClientInformationFull, OAuthClientMetadata,
                                 OAuthToken)
    HAVE_OAUTH = True
except Exception:  # pragma: no cover - very old SDK
    OAuthClientProvider = None  # type: ignore
    TokenStorage = object       # type: ignore
    HAVE_OAUTH = False

TOKEN_DIR = cfgmod.AGENTOS_HOME / "oauth"

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
    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url
        self.started = time.time()
        self.event = asyncio.Event()
        self.code = ""
        self.state: str | None = None
        self.error = ""


_pending: dict[str, Pending] = {}
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


def pending_status() -> list[dict]:
    """What is waiting for a human right now."""
    return [{"name": p.name, "url": p.url, "waiting_for": int(time.time() - p.started)}
            for p in _pending.values()]


def pending_url(name: str) -> str:
    p = _pending.get(name)
    return p.url if p else ""


def resolve(name: str, code: str, state: str | None, error: str = "") -> bool:
    """Called by the callback route. True if a flow was actually waiting."""
    p = _pending.get(name)
    if not p:
        return False
    p.code, p.state, p.error = code, state, error
    p.event.set()
    return True


def cancel(name: str) -> bool:
    """Abandon a pending authorisation (the user closed the tab, or changed their mind)."""
    p = _pending.get(name)
    if not p:
        return False
    p.error = "cancelled"
    p.event.set()
    return True


# ---- token storage --------------------------------------------------------------

def _token_path(name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in "-_.")[:64] or "server"
    return TOKEN_DIR / f"{safe}.json"


def _read(name: str) -> dict:
    try:
        return json.loads(_token_path(name).read_text())
    except Exception:
        return {}


def _write(name: str, data: dict):
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    p = _token_path(name)
    tmp = p.with_suffix(".tmp")
    # 0600 before any content is written: a refresh token is a standing credential,
    # and the window between create and chmod is the one an attacker gets.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, p)
    try:
        TOKEN_DIR.chmod(0o700)
    except OSError:
        pass


def has_tokens(name: str) -> bool:
    return bool(_read(name).get("tokens"))


def forget(name: str) -> bool:
    """Disconnect: drop tokens AND the registered client.

    Both, deliberately. Keeping the DCR client registration would silently re-use an
    authorisation the user just asked to end — "Disconnect" has to mean the next
    connect asks again.
    """
    p = _token_path(name)
    existed = p.exists()
    try:
        p.unlink()
    except OSError:
        pass
    return existed


class _Storage(TokenStorage):  # type: ignore[misc]
    """Per-server token + client-registration storage, one JSON file each."""

    def __init__(self, name: str):
        self.name = name

    async def get_tokens(self):
        raw = _read(self.name).get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens) -> None:
        data = _read(self.name)
        data["tokens"] = json.loads(tokens.model_dump_json(exclude_none=True))
        data["updated_at"] = time.time()
        _write(self.name, data)

    async def get_client_info(self):
        raw = _read(self.name).get("client")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, client_info) -> None:
        data = _read(self.name)
        data["client"] = json.loads(client_info.model_dump_json(exclude_none=True))
        _write(self.name, data)


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


def provider_for(name: str, url: str, scope: str = ""):
    """An `httpx.Auth` that authorises this server, or None if unsupported."""
    if not HAVE_OAUTH:
        return None

    async def _redirect(auth_url: str) -> None:
        p = Pending(name, auth_url)
        _pending[name] = p
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
        p = _pending.get(name)
        if p is None:  # _redirect always runs first; be defensive rather than hang
            raise RuntimeError("no pending authorisation")
        try:
            await asyncio.wait_for(p.event.wait(), timeout=AUTH_TIMEOUT)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"nobody finished signing in to '{name}' within "
                f"{int(AUTH_TIMEOUT)}s — press Connect to try again")
        finally:
            _pending.pop(name, None)
            if _notify:
                try:
                    await _notify({"type": "mcp_oauth_done", "name": name})
                except Exception:
                    pass
        if p.error:
            raise RuntimeError(f"authorisation failed: {p.error}")
        return p.code, p.state

    meta = OAuthClientMetadata(
        redirect_uris=[redirect_uri(name)],
        client_name="AgentOS",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",   # a desktop app keeps no client secret
        scope=scope or None,
    )
    return OAuthClientProvider(
        server_url=url,
        client_metadata=meta,
        storage=_Storage(name),
        redirect_handler=_redirect,
        callback_handler=_callback,
        timeout=AUTH_TIMEOUT,
    )
