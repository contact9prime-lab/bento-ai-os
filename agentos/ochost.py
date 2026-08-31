"""Hosting an OpenClaw plugin INSIDE AgentOS, behind this OS's PDP.

`ocplugins.py` governs plugins that run in OpenClaw's own gateway. It can decide
whether one is installed and enabled and nothing further, because the code
executes in another process — the boundary is stated honestly there and it is a
real ceiling.

This module removes that ceiling by changing who runs the plugin. AgentOS starts
the process, hands the plugin its `api` object (`ocp_host/host.js`), and the tools
it registers become tools in AgentOS's own loop under the name
``ocp_<plugin>_<tool>`` — exactly the shape MCP tools already arrive in. So every
call is a `PDP.decide`, an audit row, a tick on the rate meter, and something
quarantine can stop. The plugin ecosystem's reach, inside this OS's permissions.

WHAT IS ACTUALLY ENFORCED, measured rather than assumed:

- **Invoking a plugin tool** — fully gated. The call goes through the PDP like
  any other tool, as `plugin.tool` on `ocptool:<plugin>/<tool>`.
- **The plugin's own filesystem and subprocess access** — closed by Node's own
  permission model (`--permission`). Verified on Node 22: `fs.readFileSync` and
  `child_process.execSync` both raise `ERR_ACCESS_DENIED`.
- **The plugin's own NETWORK access** — *not* closed by Node. There is no
  `--allow-net`; `fetch()` from inside a permission-restricted process still
  reaches the network. Closing it needs an OS jail (`bwrap --unshare-net` on
  Linux, sandbox-exec on macOS), and where the machine has neither, this module
  SAYS SO rather than implying a boundary it does not have. `sandbox_report()`
  is that sentence and the consent screen must show it.
- **Anything the plugin asks the host for** (`api.host.fetch`, `readFile`,
  `writeFile`) — a round trip into Python and through the PDP. That inversion is
  the design: a capability a plugin takes is invisible, one it requests is
  governable, and denying it the ambient version is what forces the request.

WHAT THIS IS NOT: a reimplementation of OpenClaw. The host implements the part of
the plugin API AgentOS can host truthfully and refuses the rest out loud. A
refusal reaches `unsupported` in the ready frame and travels all the way to the
user, because the failure mode of every compatibility layer is a plugin that
installs, reports healthy, and silently does most of its job — and that is worse
than not supporting it.

The manifest is what keeps the shim honest. OpenClaw requires a plugin to declare
every registered tool in `contracts.tools`, so `discrepancy()` compares what the
host caught against what the plugin promised. A shim that missed a registration
becomes a visible gap instead of a tool that quietly does not exist.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

HOST_JS = Path(__file__).parent / "ocp_host" / "host.js"

#: How long one tool call may take before the host is considered wedged. A plugin
#: doing real work (an HTTP call, a slow API) needs more than a couple of seconds;
#: a plugin that never answers must not hold a turn open forever.
CALL_TIMEOUT = 60.0
START_TIMEOUT = 30.0

PRINCIPAL_KIND = "ocplugin"


# ---------------------------------------------------------------------------
# What this machine can actually enforce
# ---------------------------------------------------------------------------

def node_exe() -> str:
    from .mcp_client import _extended_path
    for d in (_extended_path() or "").split(os.pathsep):
        if d and os.path.isfile(os.path.join(d, "node")):
            return os.path.join(d, "node")
    return shutil.which("node") or ""


def _node_major(exe: str) -> int:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
        return int((out or "").strip().lstrip("v").split(".")[0])
    except Exception:                                              # noqa: BLE001
        return 0


def sandbox_report() -> dict:
    """What can and cannot be contained here, as facts plus one sentence each.

    This is the honesty rule applied to the only claim that matters: a consent
    screen saying "sandboxed" over a machine that cannot block the network would
    be worse than no sandbox at all, because somebody would believe it.
    """
    exe = node_exe()
    major = _node_major(exe) if exe else 0
    # Node's permission model: --experimental-permission from 20, --permission
    # accepted from 22. Below that there is no in-process containment at all.
    fs_ok = major >= 20
    from .tools import sandbox_mechanism
    jail = sandbox_mechanism()
    return {
        "node": exe, "node_major": major,
        "filesystem": fs_ok,
        "filesystem_note": (
            "the plugin cannot read or write files, or start a subprocess — Node refuses it"
            if fs_ok else
            f"Node {major or '?'} has no permission model, so the plugin can read and write "
            f"any file this server can. Upgrade to Node 20+ to close that."),
        "network": bool(jail),
        "network_note": (
            f"the plugin has no network of its own ({jail} denies it) — it can only reach "
            f"the web by asking AgentOS, which is gated"
            if jail else
            "THIS MACHINE CANNOT CONTAIN THE PLUGIN'S NETWORK. Node has no --allow-net, and "
            "there is no bwrap/sandbox-exec jail here, so the plugin can open its own "
            "connections and AgentOS cannot see them. Its tool calls are still gated; what "
            "it does inside one is not."),
        "jail": jail,
    }


def problem() -> str:
    """'' if a plugin can be hosted here, else the sentence saying why not."""
    if not HOST_JS.is_file():
        return f"the plugin host is missing ({HOST_JS})"
    if not node_exe():
        return ("hosting an OpenClaw plugin needs Node, which is not installed here. "
                "AgentOS does not install it for you.")
    return ""


# ---------------------------------------------------------------------------
# The host process
# ---------------------------------------------------------------------------

class PluginHost:
    """One Node process running one plugin. Not thread-safe by accident: a lock
    serialises calls, because two turns invoking the same plugin at once would
    otherwise interleave frames on one pipe."""

    def __init__(self, plugin_id: str, entry: str, config: dict | None = None,
                 host_call=None):
        self.plugin_id = plugin_id
        self.entry = str(entry)
        self.config = config or {}
        #: Called as host_call(name, args) -> (ok, value). This is where the PDP
        #: lives: everything the plugin asks AgentOS for goes through it. None
        #: means refuse everything, which is the safe default for a caller that
        #: forgot to wire it rather than an open door.
        self.host_call = host_call
        self.proc: subprocess.Popen | None = None
        self.registrations: list[dict] = []
        self.unsupported: list[dict] = []
        self.errors: list[str] = []
        self.logs: list[str] = []
        self._lock = threading.Lock()
        self._seq = 0

    # -- lifecycle ---------------------------------------------------------

    def _argv(self) -> list[str]:
        """Node, locked down as far as this machine allows.

        `--permission` needs explicit read grants or the plugin cannot even load
        its own code, so the plugin directory and Node's own installation are
        allowed and nothing else is. Write is never granted: a plugin that needs
        to write asks the host, which is the whole inversion.
        """
        exe = node_exe()
        rep = sandbox_report()
        argv = [exe]
        if rep["filesystem"]:
            entry_dir = str(Path(self.entry).resolve().parent)
            flag = "--permission" if rep["node_major"] >= 22 else "--experimental-permission"
            argv += [flag, f"--allow-fs-read={entry_dir}/*",
                     f"--allow-fs-read={os.path.dirname(os.path.dirname(exe))}/*"]
        argv.append(str(HOST_JS))
        jail = rep["jail"]
        if jail == "bwrap":
            # No network namespace of its own = no network. This is the only thing
            # that actually contains a plugin's own fetch(), and it is why the
            # report above refuses to claim containment without it.
            argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                    "--tmpfs", "/tmp", "--unshare-net", "--die-with-parent", *argv]
        return argv

    def start(self) -> dict:
        """Load the plugin and collect what it registered. Returns the ready frame."""
        if why := problem():
            self.errors = [why]
            return {"ok": False, "error": why}
        env = dict(os.environ)
        env.update(OCP_ENTRY=self.entry, OCP_PLUGIN_ID=self.plugin_id,
                   OCP_CONFIG=json.dumps(self.config))
        try:
            self.proc = subprocess.Popen(
                self._argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        except Exception as e:                                     # noqa: BLE001
            self.errors = [f"could not start the plugin host: {e}"]
            return {"ok": False, "error": self.errors[0]}

        frame = self._read_until("ready", START_TIMEOUT)
        if not frame:
            self.stop()
            self.errors = ["the plugin host did not report what it registered "
                           "(it may have crashed while loading the plugin)"]
            return {"ok": False, "error": self.errors[0]}
        self.registrations = frame.get("registrations") or []
        self.unsupported = frame.get("unsupported") or []
        self.errors = frame.get("errors") or []
        return {"ok": True, "registrations": self.registrations,
                "unsupported": self.unsupported, "errors": self.errors}

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if not p:
            return
        try:
            if p.stdin and not p.stdin.closed:
                p.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
                p.stdin.flush()
        except Exception:                                          # noqa: BLE001
            pass
        try:
            p.wait(timeout=3)
        except Exception:                                          # noqa: BLE001
            p.kill()

    @property
    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    # -- the wire ----------------------------------------------------------

    def _send(self, obj: dict) -> None:
        if not (self.proc and self.proc.stdin):
            raise RuntimeError("the plugin host is not running")
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _read_until(self, want: str, timeout: float, call_id: str = "") -> dict | None:
        """Next frame of type `want`, servicing the plugin's host calls meanwhile.

        A plugin that asks AgentOS for something mid-invocation is the normal
        case, not an interruption — it is exactly what the sandbox is designed to
        force — so those frames are answered here rather than deferred.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not (self.proc and self.proc.stdout):
                return None
            line = self.proc.stdout.readline()
            if not line:
                return None                       # pipe closed: the host is gone
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "log":
                self.logs.append(f"[{msg.get('level')}] {msg.get('message')}")
                self.logs[:] = self.logs[-200:]
                continue
            if kind == "host":
                self._answer_host(msg)
                continue
            if kind == want and (not call_id or msg.get("id") == call_id):
                return msg
        return None

    def _answer_host(self, msg: dict) -> None:
        """The plugin asked AgentOS for something. This is a PDP question.

        With no `host_call` wired the answer is always no. That is deliberate:
        an unwired embedding must not be an open door, and "refused" is a far
        better failure than a capability nobody decided to grant.
        """
        call, args = msg.get("call") or "", msg.get("args") or {}
        if not self.host_call:
            reply = (False, f"AgentOS refused '{call}': this plugin host was started "
                            f"without a capability bridge")
        else:
            try:
                reply = self.host_call(call, args)
            except Exception as e:                                 # noqa: BLE001
                reply = (False, str(e))
        ok, value = reply
        try:
            self._send({"type": "host_result", "id": msg.get("id"), "ok": bool(ok),
                        **({"value": value} if ok else {"error": str(value)})})
        except Exception:                                          # noqa: BLE001
            pass

    def call(self, tool: str, args: dict) -> tuple[bool, object]:
        """Invoke one registered tool. (ok, value_or_error).

        The PDP decision happens in the CALLER — this is the transport. Putting
        the gate here would make it something a second embedding could forget;
        keeping it out means the gate lives on the one path every surface uses.
        """
        with self._lock:
            if not self.alive:
                return False, "the plugin host is not running"
            self._seq += 1
            cid = f"c{self._seq}"
            try:
                self._send({"type": "invoke", "id": cid, "tool": tool, "args": args or {}})
            except Exception as e:                                 # noqa: BLE001
                return False, str(e)
            frame = self._read_until("result", CALL_TIMEOUT, call_id=cid)
        if frame is None:
            return False, (f"'{tool}' did not answer within {int(CALL_TIMEOUT)}s "
                           f"(the plugin may be hung; it has been left running)")
        if frame.get("ok"):
            return True, frame.get("value")
        return False, frame.get("error") or "the plugin's tool failed"

    # -- what the agent sees -----------------------------------------------

    def tool_schemas(self) -> list[dict]:
        """The plugin's tools, in the agent's schema shape.

        Named `ocp_<plugin>_<tool>` for the same reason MCP tools are
        `mcp_<server>_<tool>`: the prefix is what lets `policy.action_of` route
        the call to a plugin action without the tool loop knowing anything
        special, and what makes the origin of a tool readable in the ledger.
        """
        out = []
        for r in self.registrations:
            out.append({
                "name": f"ocp_{_safe(self.plugin_id)}_{_safe(r['name'])}"[:64],
                "description": f"[plugin:{self.plugin_id}] {r.get('description') or r['name']}"[:2000],
                "parameters": r.get("parameters") or {"type": "object", "properties": {}},
                "_ocp": (self.plugin_id, r["name"]),
            })
        return out


def _safe(s: str) -> str:
    return "".join(c if (c.isalnum() or c == "_") else "_" for c in (s or "")).strip("_")


class HostSet:
    """Every hosted plugin on this machine, and the name→(plugin, tool) map.

    Deliberately the same shape as `mcp_client.MCP`: `tool_schemas()` for the
    agent loop and `resolve()` for `policy.action_of`. That is not tidiness —
    hosted plugin tools and MCP tools are the same KIND of thing (a third party's
    tool reachable through a gate), so giving them the same seams means the tool
    loop, the PDP and the ledger need no new special case for either.
    """

    def __init__(self):
        self.hosts: dict[str, PluginHost] = {}

    def add(self, host: PluginHost) -> None:
        self.hosts[host.plugin_id] = host

    def remove(self, plugin_id: str) -> None:
        h = self.hosts.pop(plugin_id, None)
        if h:
            h.stop()

    def stop_all(self) -> None:
        for h in list(self.hosts.values()):
            h.stop()
        self.hosts.clear()

    def tool_schemas(self) -> list[dict]:
        out = []
        for h in self.hosts.values():
            if h.alive:
                out += h.tool_schemas()
        return out

    def resolve(self, tool_name: str):
        """Agent tool name -> (plugin_id, real_tool), or None."""
        for t in self.tool_schemas():
            if t["name"] == tool_name:
                return t["_ocp"]
        return None

    def call(self, tool_name: str, args: dict) -> tuple[bool, object]:
        """Invoke by AGENT tool name. The caller must have asked the PDP first —
        this is transport, and keeping the gate out of it means the gate lives on
        the one path every surface shares rather than being something a second
        embedding could forget."""
        target = self.resolve(tool_name)
        if not target:
            return False, f"no hosted plugin offers '{tool_name}'"
        return self.hosts[target[0]].call(target[1], args)


# ---------------------------------------------------------------------------
# Is the shim telling the truth about this plugin?
# ---------------------------------------------------------------------------

def discrepancy(manifest: dict, registrations: list[dict]) -> str:
    """'' if what the host caught matches what the plugin declared, else the gap.

    OpenClaw requires a plugin's runtime `registerTool` calls to match
    `contracts.tools` in its manifest. That rule is what makes a compatibility
    shim auditable rather than hopeful: the manifest states what SHOULD have been
    registered, so a tool the shim failed to catch shows up here instead of
    silently not existing. Offering a plugin while quietly dropping half its tools
    is the exact failure this whole module is written to avoid.
    """
    declared = {str(t) for t in (((manifest or {}).get("contracts") or {}).get("tools") or []) if t}
    got = {r["name"] for r in (registrations or [])}
    missing = sorted(declared - got)
    extra = sorted(got - declared)
    bits = []
    if missing:
        bits.append(f"its manifest declares {', '.join(missing)}, which this host did not "
                    f"see registered — AgentOS cannot offer them, and that is a gap in this "
                    f"compatibility layer rather than a fault in the plugin")
    if extra:
        bits.append(f"it registered {', '.join(extra)}, which its manifest does not declare")
    return "; ".join(bits)


def hosting_report(manifest: dict, started: dict) -> dict:
    """One answer to 'what did AgentOS actually take on here?'.

    Everything a person needs before enabling: what works, what was refused, what
    could not be contained, and whether the shim and the manifest agree.
    """
    regs = started.get("registrations") or []
    return {
        "ok": bool(started.get("ok")),
        "error": started.get("error") or "",
        "tools": [r["name"] for r in regs],
        "unsupported": started.get("unsupported") or [],
        "errors": started.get("errors") or [],
        "discrepancy": discrepancy(manifest, regs),
        "sandbox": sandbox_report(),
    }
