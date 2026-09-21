"""The bridge: this OS's tools, served to an executor over MCP, one session per run.

Why it exists. An executor such as Claude Code answers this OS's turns, but it
runs its OWN tool loop — Read, Bash, WebFetch — and none of those calls reach
this PDP. That was fine for a chat turn fenced by an envelope, and it is not
fine for a mission: a mission's consent block says "reads this folder and
nothing else", which is a promise about every step, and only a loop whose every
step passes the gate can keep it. So a mission on an executor brain used to be
impossible, and the surfaces said so.

What this does. When a flow's master or one of its specialists is run on an
executor, the executor is started with its native tools switched OFF and exactly
one MCP server allowed: this bridge, bound to that one run. Every tool the
executor can see is one of ours — the flow's own `delegate`/`finish`, or the
tools the flow granted — and every call it makes arrives here and goes through
`Agent.call_tool`, which is the same gate, ledger row, log line and taint mark a
built-in turn gets. The model is the executor's; the hands are this OS's.

The session is the whole security story, so its rules are short:

- **A token is minted per run, never chosen** (`token_urlsafe(24)`), carried in
  the URL AND as a Bearer header, and forgotten the moment the run ends. It
  names an in-process Agent; there is nothing to look up in a database and
  nothing to replay after `close`.
- **The route is loopback-only.** The executor is a child process of this
  server; a bridge reachable from the LAN would be a way to drive somebody's
  agent with their permissions.
- **The tool list is the Agent's own** (`agent._tools()`), so the flow's
  `tool_filter` and the PDP's "could I?" visibility check decide what the
  executor even sees. A call for a tool not on the list is refused by name.
- **There is a step ceiling** (`max_calls`, the flow's `max_steps`), because the
  executor's loop is not ours to bound: without it a model in a groove could
  call `recall` six hundred times inside one budget.

Kept free of HTTP: `handle()` takes and returns JSON-RPC dicts, and the server
route is a thin door. That is what lets the tests drive a whole flow through
the bridge with no socket and no CLI.

Three faces: this is server plumbing, the same on GUI and SUI; the TUI reaches
it through `bento job run`, which starts the same flow the same way.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field

from . import users as usersmod

PROTOCOL = "2025-06-18"
SERVER_NAME = "bento"          # the MCP server name the executor sees: mcp__bento__<tool>

#: token -> Session. In memory on purpose: a session is an Agent object.
SESSIONS: dict[str, "Session"] = {}


@dataclass
class Session:
    token: str
    agent: object                       # agent.Agent — the gate
    schemas: list                       # our schemas, as the Agent offered them
    uid: str = ""                       # whose store this run reads (users.as_user)
    run_id: str = ""
    label: str = ""
    max_calls: int = 25
    calls: int = 0
    created: float = field(default_factory=time.time)
    last: float = field(default_factory=time.time)
    seen: list = field(default_factory=list)      # tool names, in order — for the tests and the log


def open_session(agent, schemas: list, run_id: str = "", label: str = "",
                 max_calls: int = 25) -> str:
    """Mint a token for one run and remember its Agent. Returns the token."""
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = Session(token=token, agent=agent, schemas=list(schemas or []),
                              uid=usersmod.current() or "", run_id=run_id, label=label,
                              max_calls=max(1, int(max_calls or 25)))
    return token


def close_session(token: str) -> Session | None:
    """Forget a run's token. A token that has been closed answers nothing."""
    return SESSIONS.pop(token or "", None)


def get(token: str) -> Session | None:
    return SESSIONS.get(token or "")


def mcp_tools(schemas: list) -> list[dict]:
    """Our tool schemas in MCP's shape: `parameters` becomes `inputSchema`."""
    out = []
    for t in schemas or []:
        params = t.get("parameters") or {"type": "object", "properties": {}}
        out.append({"name": t["name"],
                    "description": (t.get("description") or "")[:2000],
                    "inputSchema": params})
    return out


def _err(rid, code: int, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": text}}


def _text(rid, text: str, is_error: bool = False) -> dict:
    return {"jsonrpc": "2.0", "id": rid,
            "result": {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}}


async def handle(token: str, msg: dict) -> tuple[int, dict | None]:
    """One JSON-RPC message for one session. Returns (http_status, body).

    Bodies follow MCP over Streamable HTTP: a notification (no id) gets 202 and
    no body; everything else a JSON-RPC response. An unknown token is 401 with a
    sentence, before anything else is looked at.
    """
    s = SESSIONS.get(token or "")
    if s is None:
        return 401, {"error": "unknown or expired run token — this bridge answers only "
                              "the run it was minted for, and only while it runs"}
    s.last = time.time()
    if not isinstance(msg, dict):
        return 200, _err(None, -32700, "not a JSON-RPC message")
    rid = msg.get("id")
    method = str(msg.get("method") or "")
    if rid is None:                                    # a notification asks for no answer
        return 202, None
    if method == "initialize":
        return 200, {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "1"},
            "instructions": ("These are the ONLY tools of this run. They belong to the "
                             "operating system that started you; every call is checked "
                             "against its permissions and recorded. Call them by name.")}}
    if method == "ping":
        return 200, {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return 200, {"jsonrpc": "2.0", "id": rid, "result": {"tools": mcp_tools(s.schemas)}}
    if method != "tools/call":
        return 200, _err(rid, -32601, f"unknown method '{method}'")

    params = msg.get("params") or {}
    name = str(params.get("name") or "")
    args = params.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    offered = {t["name"] for t in s.schemas}
    if name not in offered:
        # By name, so the model can correct itself; the flow's tool_filter and the
        # PDP's visibility check are what decided the list, not this line.
        return 200, _text(rid, f"[denied] no tool called '{name}' in this run — you have: "
                               f"{', '.join(sorted(offered)) or '(none)'}", is_error=True)
    if s.calls >= s.max_calls:
        return 200, _text(rid, f"[denied] this run's step limit ({s.max_calls} tool calls) "
                               f"is spent — finish with what you have", is_error=True)
    if getattr(s.agent, "aborted", False):
        return 200, _text(rid, "[denied] this run has been stopped", is_error=True)
    s.calls += 1
    s.seen.append(name)
    call_id = f"mcp{s.calls}"
    with usersmod.as_user(s.uid):
        output, ok, _image, _untrusted = await s.agent.call_tool(name, args, call_id)
    return 200, _text(rid, str(output or ""), is_error=not ok)


def stats() -> dict:
    """For the doctor: how many bridges are open and for whom."""
    return {"open": len(SESSIONS),
            "runs": [{"run_id": s.run_id, "label": s.label, "calls": s.calls,
                      "age_s": int(time.time() - s.created)} for s in SESSIONS.values()]}
