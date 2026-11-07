"""MCP client: connects AgentOS to Model Context Protocol servers (stdio or HTTP).

Each configured server gets an owner asyncio task that holds the connection
context for its whole life (the MCP SDK's cancel scopes must be entered and
exited in the same task). Tool calls from the agent hop through the session,
which is safe cross-task.

Tools are exposed to the agent as `mcp_<server>_<tool>`.
"""

import asyncio
import ipaddress
import json
import logging
import os
import re
import shlex
import shutil
import socket
from urllib.parse import urlsplit

from . import config as cfgmod
from . import users as usersmod

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    MCP_AVAILABLE = False

CALL_TIMEOUT = 60
CONNECT_TIMEOUT = 30


def _resolves_public(url: str) -> None:
    """Raise when a name resolves to an address only this machine can reach. A name that does
    not resolve is left for the connection to report. This narrows DNS rebinding and does not
    close it: the SDK resolves again when it connects."""
    host = urlsplit(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return
    for info in infos:
        if (why := _address_refused(str(info[4][0]).split("%")[0])):
            raise RuntimeError(why)


class _NonJsonStdoutFilter(logging.Filter):
    """Some community MCP servers print banners / console.table boxes to STDOUT,
    corrupting their own JSON-RPC stream. The SDK skips those lines but logs a full
    traceback PER LINE ("Failed to parse JSONRPC message") — a table dump becomes a
    wall of scary errors. The stream self-recovers, so drop that specific noise and
    keep everything else the SDK logs."""
    dropped = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if "Failed to parse JSONRPC message" in record.getMessage():
            _NonJsonStdoutFilter.dropped += 1
            return False
        return True


logging.getLogger("mcp.client.stdio").addFilter(_NonJsonStdoutFilter())

_name_rx = re.compile(r"[^a-zA-Z0-9_-]+")


def _safe(name: str) -> str:
    return _name_rx.sub("_", name)[:24].strip("_") or "srv"


def _extended_path() -> str:
    """PATH for spawning MCP servers. A GUI-launched AgentOS (macOS LaunchAgent,
    Linux systemd) inherits a minimal PATH where npx/uvx don't exist — extend it
    with the places node/uv actually live."""
    import glob
    home = os.path.expanduser("~")
    extra = [
        f"{home}/.local/bin",            # uv / uvx / pipx
        "/opt/homebrew/bin",             # Homebrew (Apple Silicon)
        "/usr/local/bin",                # Homebrew (Intel) / system node
        f"{home}/.cargo/bin",
        f"{home}/Library/pnpm",
        f"{home}/.bun/bin",
        "/snap/bin",
    ]
    # nvm installs node under versioned dirs — take the newest
    nvm = sorted(glob.glob(f"{home}/.nvm/versions/node/*/bin"), reverse=True)
    extra += nvm[:1]
    cur = os.environ.get("PATH", "")
    parts = [p for p in cur.split(os.pathsep) if p]
    for p in extra:
        if p not in parts and os.path.isdir(p):
            parts.append(p)
    return os.pathsep.join(parts)


def _resolve_command(cmd: str) -> str:
    """Absolute path for an MCP server command, searched over the extended PATH."""
    import shutil
    if os.path.sep in cmd:
        return cmd
    return shutil.which(cmd, path=_extended_path()) or cmd


# What a tool server is never handed from this server's own environment. Provider keys and
# the home's storage key sit there (cloud hosts put them there), and a stranger's package
# has no use for them. An admin's server keeps the rest, because npx and uvx read proxies,
# caches and NODE_* settings. Anything it really needs goes in the server's own `env`.
_ENV_SECRET = re.compile(r"(KEY|TOKEN|SECRET|PASS|AUTH|CRED|COOKIE|SESSION|PRIVATE)", re.I)
_ENV_KEEP = {"XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "SSH_AUTH_SOCK"}
_ENV_OURS = ("AGENTOS_", "BENTO_", "CLAUDE", "ANTHROPIC_", "OPENAI_", "GEMINI_", "GOOGLE_")
# Set on the jail program itself, so they'd run before it has jailed anything: the account
# chooses `env`, and LD_PRELOAD from there would be its code outside the jail.
_ENV_LOADER = re.compile(r"^(LD_|DYLD_|GCONV_PATH$|GETCONF_DIR$|LOCPATH$|NLSPATH$|MALLOC_|GLIBC_TUNABLES$|"
                         r"HOSTALIASES$|RESOLV_HOST_CONF$|TMPDIR$|BASH_ENV$|ENV$)")


def _restricted() -> bool:
    """Is this server being started for an account that is not an admin? '' is the machine."""
    uid = usersmod.current() or ""
    return bool(uid) and usersmod.enabled() and not usersmod.is_admin(uid)


def _address_refused(host: str) -> str:
    """Why an account may not point a server at this host, or ''. The connection is made from
    this machine, so an address only it can reach would be read on the account's behalf."""
    h = (host or "").strip().strip("[]").rstrip(".").lower()
    if not h:
        return "That server has no address."
    bad = "A tool server has to be on the public internet. Ask an admin to add one on this network."
    if h == "localhost" or h.endswith((".localhost", ".local", ".lan", ".internal")):
        return bad
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return ""
    # an IPv4 address written as IPv6 is the same machine
    ip = getattr(ip, "ipv4_mapped", None) or ip
    return "" if ip.is_global else bad


def refusal(conf: dict) -> str:
    """Why this account may not have this server, in a sentence, or ''. An admin may have any.
    Checked when it is saved, for the sentence, and again when it starts, because the agent's
    tools, the Store and an app import all write this list."""
    if not _restricted():
        return ""
    if (conf.get("transport") or "stdio") == "http":
        u = urlsplit(str(conf.get("url") or ""))
        if u.scheme not in ("http", "https"):
            return "A tool server's address has to start with http or https."
        return _address_refused(u.hostname or "")
    from .tools import sandbox_mechanism
    if not sandbox_mechanism():
        return ("A program as a tool server needs bubblewrap on this machine, so it can run "
                "inside your account. Ask an admin to install it, or use a server with a URL.")
    return ""


def stdio_launch(conf: dict, name: str = "") -> tuple[str, list[str], dict]:
    """(program, arguments, environment) for a stdio server, jailed for an account.

    An account's program runs in the same jail as its Terminal: its own home, everyone
    else's hidden, nothing of the machine's secrets, no fallback to running it bare. It
    used to run as the server's user with the whole environment, and read every home.
    """
    cmd = shlex.split(conf.get("command", ""))
    args = shlex.split(conf.get("args", "") or "")
    if not cmd:
        raise ValueError("no command configured")
    exe = _resolve_command(cmd[0])
    if os.path.sep not in exe:
        raise FileNotFoundError(
            f"'{cmd[0]}' not found — install it (node/npm for npx, uv for uvx) "
            f"or use an absolute path in the server's command")
    own = {k: str(v) for k, v in (conf.get("env") or {}).items()}
    if not _restricted():
        # An allow-list: this process holds provider keys, and a server gets what its own settings
        # name and nothing else of ours. npx -> node -> the server must inherit the SAME extended
        # PATH, or they fail even when npx itself resolved.
        from . import executors
        env = {**{k: v for k, v in os.environ.items() if k in executors.ENV_KEEP or k.startswith("LC_")},
               "PATH": _extended_path(), **own}
        argv = [exe, *cmd[1:], *args]
        # a server from the public registry is somebody else's program: jailed where a jail can start
        if conf.get("jail") and executors.JAIL_ENFORCED and executors.jail_ready():
            argv = executors.jail_server(argv, name or "server")
        return argv[0], argv[1:], env
    if (why := refusal(conf)):
        raise RuntimeError(why)
    from .tools import bwrap_argv, folder_binds, sandbox_exec_argv, sandbox_mechanism
    uid = usersmod.current() or ""
    home = os.path.realpath(str(usersmod.home_for(uid)))
    os.makedirs(home, exist_ok=True)
    real_exe = os.path.realpath(exe)
    host_home = os.path.realpath(os.path.expanduser("~"))
    if real_exe.startswith(host_home + os.sep):
        raise RuntimeError(f"{cmd[0]} is installed in a home folder, so it can't run inside your "
                           "account. Ask an admin to install it for everyone.")
    ro, rw = folder_binds(usersmod.cfg_for(uid), uid)
    if sandbox_mechanism() == "bwrap":
        # the whole machine home is blanked, not only users/: where it sits outside /home
        # (a container's /data) its session key would otherwise be readable from here
        # own_env: a server's own settings often hold its API key, which --setenv would put on a
        # command line. The environment below is the program's whole environment.
        argv = bwrap_argv(home, [exe, *cmd[1:], *args], chdir=home, extra=rw, ro_extra=ro,
                          hide=[os.path.realpath(str(cfgmod.AGENTOS_HOME))], own_env=True)
    else:
        argv = sandbox_exec_argv(home, shlex.join([exe, *cmd[1:], *args]), chdir=home, extra=rw, ro_extra=ro,
                                 hide=[os.path.realpath(str(cfgmod.AGENTOS_HOME))])
    argv[0] = shutil.which(argv[0]) or argv[0]
    from .tools import jail_env, jail_root
    env = {**jail_env(jail_root(home)), "PATH": _extended_path(),
           **{k: v for k, v in own.items() if not _ENV_LOADER.match(k)}}
    return argv[0], argv[1:], env


class MCPServer:
    def __init__(self, name: str, conf: dict):
        self.name = name
        self.conf = conf
        self.session = None
        self.tools: list[dict] = []       # raw MCP tool defs
        self.instructions = ""            # server-provided usage guidance (from initialize)
        self.status = "connecting"        # connecting | connected | error | disabled
        self.error = ""
        self._closed = asyncio.Event()
        self.task: asyncio.Task | None = None

    async def _run(self, on_change):
        try:
            transport = self.conf.get("transport", "stdio")
            if (why := refusal(self.conf)):
                raise RuntimeError(why)
            if transport == "http":
                headers = {k: str(v) for k, v in (self.conf.get("headers") or {}).items()}
                url = self.conf.get("url", "")
                if _restricted():
                    # the name's answer, right before connecting: the save only saw the name
                    await asyncio.to_thread(_resolves_public, url)
                # `auth: "oauth"` is the whole configuration for a first-party remote
                # server — no key to paste, because the token is obtained by asking
                # the user once and then refreshed. Without this the connection gets
                # a 401 it cannot answer; see mcp_oauth.py.
                auth = None
                if (self.conf.get("auth") or "") == "oauth":
                    from . import mcp_oauth
                    auth = mcp_oauth.provider_for(
                        self.name, url, scope=self.conf.get("scope", "") or "")
                    if auth is None:
                        raise RuntimeError(
                            "this server needs OAuth, which this MCP SDK is too old "
                            "to do — upgrade the 'mcp' package")
                    self.status = "authorizing" if not mcp_oauth.has_tokens(self.name, url) \
                        else self.status
                ctx = streamablehttp_client(url, headers=headers or None, auth=auth,
                                            **_guarded_for_account())
                async with ctx as (read, write, _):
                    await self._serve(read, write, on_change)
            else:
                exe, argv, env = stdio_launch(self.conf, self.name)
                params = StdioServerParameters(command=exe, args=argv, env=env)
                async with stdio_client(params) as (read, write):
                    await self._serve(read, write, on_change)
        except asyncio.CancelledError:
            raise
        except BaseException as e:  # anyio may raise ExceptionGroup
            self.status = "error"
            self.error = f"{type(e).__name__}: {str(e)[:300]}"
            self.session = None
            await on_change(self)

    async def _serve(self, read, write, on_change):
        async with ClientSession(read, write) as session:
            init = await asyncio.wait_for(session.initialize(), timeout=CONNECT_TIMEOUT)
            self.instructions = (getattr(init, "instructions", "") or "").strip()
            resp = await asyncio.wait_for(session.list_tools(), timeout=CONNECT_TIMEOUT)
            self.tools = [
                {"name": t.name, "description": t.description or "",
                 "parameters": t.inputSchema or {"type": "object", "properties": {}}}
                for t in resp.tools
            ]
            self.session = session
            self.status = "connected"
            self.error = ""
            await on_change(self)
            await self._closed.wait()
        self.session = None

    def close(self):
        self._closed.set()
        if self.task and not self.task.done():
            self.task.cancel()


def _guarded_for_account() -> dict:
    """An account that isn't an admin chooses its own server address, and this machine connects
    to it: the guarded client, every hop. An admin's or a single user's local MCP server is theirs
    to run on this machine, so that path keeps working, minus the metadata addresses."""
    from . import netguard
    from . import users as usersmod

    local_ok = not usersmod.enabled() or usersmod.is_admin(usersmod.current() or "")

    def factory(headers=None, timeout=None, auth=None):
        return netguard.client(local_ok=local_ok, follow_redirects=True, headers=headers, timeout=timeout, auth=auth)
    return {"httpx_client_factory": factory}


class MCPManager(usersmod.Scoped):
    def __init__(self, cfg: dict, store=None):
        self.cfg = cfg
        self.store = store
        self.servers: dict[str, MCPServer] = {}

    async def _on_change(self, srv: MCPServer):
        if self.store:
            msg = (f"MCP '{srv.name}' connected ({len(srv.tools)} tools)"
                   if srv.status == "connected" else f"MCP '{srv.name}' failed: {srv.error}")
            self.store.log("mcp", msg)
            if srv.status == "connected":
                # a registered server's manual page learns its real tool list on connect
                try:
                    from . import mcp_store
                    mcp_store.refresh_doc(self.store, srv.name, conf=srv.conf,
                                          live={"status": "connected", "tools": srv.tools,
                                                "instructions": srv.instructions})
                except Exception:
                    pass

    async def start(self):
        await self.reload()

    async def reload(self):
        """(Re)connect to match the current config."""
        for srv in list(self.servers.values()):
            srv.close()
        self.servers = {}
        if not MCP_AVAILABLE:
            return
        for name, conf in (self.cfg.get("mcp_servers") or {}).items():
            if not conf.get("enabled", True):
                srv = MCPServer(name, conf)
                srv.status = "disabled"
                self.servers[name] = srv
                continue
            srv = MCPServer(name, conf)
            self.servers[name] = srv
            srv.task = asyncio.create_task(srv._run(self._on_change))

    async def stop(self):
        for srv in self.servers.values():
            srv.close()

    # -- agent-facing surface -------------------------------------------------

    def tool_schemas(self) -> list[dict]:
        out = []
        seen: set[str] = set()
        for srv in self.servers.values():
            if srv.status != "connected":
                continue
            for t in srv.tools:
                name = f"mcp_{_safe(srv.name)}_{_safe(t['name'])}"[:64]
                if name in seen:  # truncation collision — disambiguate deterministically
                    import hashlib
                    suffix = hashlib.sha1(f"{srv.name}/{t['name']}".encode()).hexdigest()[:6]
                    name = f"{name[:57]}_{suffix}"
                seen.add(name)
                out.append({
                    "name": name,
                    "description": f"[MCP:{srv.name}] {t['description']}"[:2000],
                    "parameters": t["parameters"],
                    "_mcp": (srv.name, t["name"]),
                })
        return out

    def resolve(self, tool_name: str):
        """Map an agent tool name back to (server, real_tool) or None."""
        for t in self.tool_schemas():
            if t["name"] == tool_name:
                return t["_mcp"]
        return None

    @staticmethod
    def _payload(block) -> tuple[str, str]:
        """(base64 data, mime) out of an MCP content block, or ('', '').

        Handles the three shapes servers actually send: ImageContent/AudioContent
        (`.data` + `.mimeType`), EmbeddedResource (`.resource.blob`), and a bare
        BlobResourceContents. Text resources are left to the text path.
        """
        data = getattr(block, "data", None)
        if isinstance(data, str) and data:
            return data, getattr(block, "mimeType", "") or ""
        resource = getattr(block, "resource", None)
        if resource is not None:
            blob = getattr(resource, "blob", None)
            if isinstance(blob, str) and blob:
                return blob, getattr(resource, "mimeType", "") or ""
        return "", ""

    async def call(self, server: str, tool: str, args: dict,
                   context: dict | None = None) -> str:
        """Call an MCP tool and keep everything it returns.

        This used to throw away every non-text block, rendering an image, a video
        or a voice clip as the literal string "[image]" — which made every media
        MCP (Higgsfield, Canva, ElevenLabs, anything that draws or speaks)
        useless: the agent would report success and hold nothing.

        Non-text blocks are now written into the asset store and reported in a
        JSON envelope:

            {"text": "...", "__media__": [{"asset_id", "kind", "mime", "title"}],
             "__image__": "<path>"}

        `__image__` is the shape agent.py has always understood for vision, and it
        is populated only for images, because no provider path accepts video or
        audio bytes — those travel as asset ids the agent can act on, which is
        true, rather than as an attachment that would silently not arrive.
        """
        srv = self.servers.get(server)
        if not srv or srv.status != "connected" or not srv.session:
            return f"[error] MCP server '{server}' is not connected"
        try:
            res = await asyncio.wait_for(srv.session.call_tool(tool, args or {}), timeout=CALL_TIMEOUT)
        except asyncio.TimeoutError:
            return f"[error] MCP call {server}/{tool} timed out after {CALL_TIMEOUT}s"
        except Exception as e:
            return f"[error] MCP call failed: {type(e).__name__}: {e}"

        ctx = context or {}
        parts: list[str] = []
        media: list[dict] = []
        first_image_path = ""
        for c in res.content or []:
            ctype = getattr(c, "type", "")
            if ctype == "text":
                parts.append(c.text)
                continue
            b64, mime = self._payload(c)
            if not b64:
                # a block with no payload at all — say what it was rather than
                # implying content arrived
                parts.append(f"[{ctype or 'content'} with no data]")
                continue
            if not self.store:
                parts.append(f"[{ctype or 'content'}: {mime or 'unknown type'}, "
                             f"not stored — no asset store on this instance]")
                continue
            try:
                from . import assets as assetmod
                row = await assetmod.put_base64(
                    self.store, b64, mime=mime,
                    name=f"{tool}{assetmod.ext_for(mime)}",
                    title=f"{tool} · {server}",
                    prompt=str(args.get("prompt") or "")[:1000],
                    source=f"mcp:{server}/{tool}",
                    conversation_id=str(ctx.get("conversation_id") or ""),
                    run_id=str(ctx.get("run_id") or ""),
                    space_id=str(ctx.get("space_id") or ""))
            except Exception as e:  # storing must never lose the whole tool result
                parts.append(f"[{ctype or 'content'} received but could not be stored: {e}]")
                continue
            if not row:
                parts.append(f"[{ctype or 'content'} received but was empty or too large to store]")
                continue
            media.append({"asset_id": row["id"], "kind": row["kind"], "mime": row["mime"],
                          "title": row.get("title", ""), "bytes": row.get("bytes", 0)})
            if row["kind"] == "image" and not first_image_path:
                first_image_path = row.get("path") or ""
            parts.append(f"[{row['kind']} saved as asset {row['id']}"
                         f"{' · ' + row['mime'] if row.get('mime') else ''}]")

        text = "\n".join(p for p in parts if p) or "(no content)"
        if getattr(res, "isError", False):
            return f"[error] {text}"
        if not media:
            return text
        envelope = {"text": text, "__media__": media}
        if first_image_path:
            envelope["__image__"] = first_image_path
        return json.dumps(envelope)

    def status(self) -> list[dict]:
        from . import mcp_oauth
        waiting = {p["name"]: p for p in mcp_oauth.pending_status()}   # this account's
        out = []
        for name, srv in self.servers.items():
            auth = srv.conf.get("auth", "") or ""
            pend = waiting.get(name)
            out.append({
                "name": name,
                "transport": srv.conf.get("transport", "stdio"),
                "command": srv.conf.get("command", ""),
                "args": srv.conf.get("args", ""),
                "url": srv.conf.get("url", ""),
                "env": srv.conf.get("env") or {},
                "headers": srv.conf.get("headers") or {},
                "enabled": srv.conf.get("enabled", True),
                # An OAuth server has three states a key-based one does not: never
                # signed in, waiting for the human, and signed in. The UI needs all
                # three to avoid calling "waiting for you" an error.
                "auth": auth,
                "authorized": mcp_oauth.has_tokens(name, srv.conf.get("url", "")) if auth == "oauth" else True,
                "auth_url": (pend or {}).get("url", ""),
                "status": "authorizing" if pend else srv.status,
                "error": srv.error,
                "instructions": srv.instructions,
                "tools": [{"name": t["name"],
                           "description": t["description"],
                           "params": list((t.get("parameters") or {}).get("properties", {}).keys())}
                          for t in srv.tools],
            })
        return out
