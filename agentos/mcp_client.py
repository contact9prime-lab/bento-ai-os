"""MCP client: connects AgentOS to Model Context Protocol servers (stdio or HTTP).

Each configured server gets an owner asyncio task that holds the connection
context for its whole life (the MCP SDK's cancel scopes must be entered and
exited in the same task). Tool calls from the agent hop through the session,
which is safe cross-task.

Tools are exposed to the agent as `mcp_<server>_<tool>`.
"""

import asyncio
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

_name_rx = re.compile(r"[^a-zA-Z0-9_-]+")


def _safe(name: str) -> str:
    return _name_rx.sub("_", name)[:24].strip("_") or "srv"


class MCPServer:
    def __init__(self, name: str, conf: dict):
        self.name = name
        self.conf = conf
        self.session = None
        self.tools: list[dict] = []       # raw MCP tool defs
        self.status = "connecting"        # connecting | connected | error | disabled
        self.error = ""
        self._closed = asyncio.Event()
        self.task: asyncio.Task | None = None

    async def _run(self, on_change):
        try:
            transport = self.conf.get("transport", "stdio")
            if transport == "http":
                ctx = streamablehttp_client(self.conf.get("url", ""))
                async with ctx as (read, write, _):
                    await self._serve(read, write, on_change)
            else:
                cmd = shlex.split(self.conf.get("command", ""))
                args = shlex.split(self.conf.get("args", "") or "")
                if not cmd:
                    raise ValueError("no command configured")
                env = None
                custom_env = self.conf.get("env") or {}
                if custom_env:
                    env = {**os.environ, **{k: str(v) for k, v in custom_env.items()}}
                params = StdioServerParameters(command=cmd[0], args=cmd[1:] + args, env=env)
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
            await asyncio.wait_for(session.initialize(), timeout=CONNECT_TIMEOUT)
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
        for srv in self.servers.values():
            if srv.status != "connected":
                continue
            for t in srv.tools:
                out.append({
                    "name": f"mcp_{_safe(srv.name)}_{_safe(t['name'])}"[:64],
                    "description": f"[MCP:{srv.name}] {t['description']}"[:1000],
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
                "enabled": srv.conf.get("enabled", True),
                "status": srv.status,
                "error": srv.error,
                "tools": [t["name"] for t in srv.tools],
            })
        return out
