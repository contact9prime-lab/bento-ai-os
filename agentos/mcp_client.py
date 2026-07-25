"""MCP client: connects AgentOS to Model Context Protocol servers (stdio or HTTP).

Each configured server gets an owner asyncio task that holds the connection
context for its whole life (the MCP SDK's cancel scopes must be entered and
exited in the same task). Tool calls from the agent hop through the session,
which is safe cross-task.

Tools are exposed to the agent as `mcp_<server>_<tool>`.
"""

import asyncio
import logging
import os
import re
import shlex

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    MCP_AVAILABLE = False

CALL_TIMEOUT = 60
CONNECT_TIMEOUT = 30


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
            if transport == "http":
                headers = {k: str(v) for k, v in (self.conf.get("headers") or {}).items()}
                ctx = streamablehttp_client(self.conf.get("url", ""), headers=headers or None)
                async with ctx as (read, write, _):
                    await self._serve(read, write, on_change)
            else:
                cmd = shlex.split(self.conf.get("command", ""))
                args = shlex.split(self.conf.get("args", "") or "")
                if not cmd:
                    raise ValueError("no command configured")
                exe = _resolve_command(cmd[0])
                if os.path.sep not in exe:
                    raise FileNotFoundError(
                        f"'{cmd[0]}' not found — install it (node/npm for npx, uv for uvx) "
                        f"or use an absolute path in the server's command")
                # child processes (npx → node → the server) must inherit the SAME
                # extended PATH, or they fail even when npx itself resolved
                env = {**os.environ, "PATH": _extended_path(),
                       **{k: str(v) for k, v in (self.conf.get("env") or {}).items()}}
                params = StdioServerParameters(command=exe, args=cmd[1:] + args, env=env)
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


class MCPManager:
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

    async def call(self, server: str, tool: str, args: dict) -> str:
        srv = self.servers.get(server)
        if not srv or srv.status != "connected" or not srv.session:
            return f"[error] MCP server '{server}' is not connected"
        try:
            res = await asyncio.wait_for(srv.session.call_tool(tool, args or {}), timeout=CALL_TIMEOUT)
        except asyncio.TimeoutError:
            return f"[error] MCP call {server}/{tool} timed out after {CALL_TIMEOUT}s"
        except Exception as e:
            return f"[error] MCP call failed: {type(e).__name__}: {e}"
        parts = []
        for c in res.content or []:
            if getattr(c, "type", "") == "text":
                parts.append(c.text)
            else:
                parts.append(f"[{getattr(c, 'type', 'content')}]")
        text = "\n".join(parts) or "(no content)"
        if getattr(res, "isError", False):
            return f"[error] {text}"
        return text

    def status(self) -> list[dict]:
        out = []
        for name, srv in self.servers.items():
            out.append({
                "name": name,
                "transport": srv.conf.get("transport", "stdio"),
                "command": srv.conf.get("command", ""),
                "args": srv.conf.get("args", ""),
                "url": srv.conf.get("url", ""),
                "env": srv.conf.get("env") or {},
                "headers": srv.conf.get("headers") or {},
                "enabled": srv.conf.get("enabled", True),
                "status": srv.status,
                "error": srv.error,
                "instructions": srv.instructions,
                "tools": [{"name": t["name"],
                           "description": t["description"],
                           "params": list((t.get("parameters") or {}).get("properties", {}).keys())}
                          for t in srv.tools],
            })
        return out
