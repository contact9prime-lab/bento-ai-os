"""The policy decision point (PDP): one gate for every capability in the OS.

Every surface that executes a capability — the main agent's tool loop, subagents,
user apps calling /api/tool, appData, model selection — asks this module first:

    decide(principal, action, resource, context) -> Decision(allow | deny | ask)

Principals are WHO is asking (the user's own agent, an app, a subagent). Grants are
persisted consent (see memory.Store grants table): principal-scoped allow/deny rules
written by install-time manifest approval, the runtime "allow & remember" prompt, or
the Permissions app — and revocable there at any time.

Evaluation order (first hit wins):
    1. hard blocks       — BLOCKED_PATTERNS / deny policies folded into risk="blocked";
                           never overridable by any grant
    2. built-in denies   — apps/subagents may never self-modify the OS or (subagents)
                           re-delegate, regardless of grants
    3. deny grants       — explicit revocations/restrictions; deny wins over allow
    4. allow grants      — persisted consent satisfies the approval requirement:
                           consent already happened when the grant was written
    5. kind defaults     — user: today's autonomy semantics (safe runs, risky asks
                           unless autonomy=full); app: safe runs, everything else asks

The legacy cfg["policies"] fnmatch rules keep working untouched: Toolbox.risk_of()
already folds them into the risk level (deny -> blocked, allow -> safe) before the
PDP runs, so they act as global rules for every principal — grants are the
principal-scoped superset layered on top.
"""

import fnmatch
import json
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Principal:
    kind: str  # "user" | "app" | "subagent" | "workflow" | "system"
    id: str = ""  # "" for the user; app id; subagent/workflow name

    @property
    def label(self) -> str:
        return self.kind if not self.id else f"{self.kind}:{self.id}"


MAIN = Principal("user", "")  # the main agent acts AS the user (today's semantics)


@dataclass
class Decision:
    effect: str  # "allow" | "deny" | "ask"
    reason: str = ""
    rule: str = ""  # grant id | "hard-block" | "builtin-deny" | "default"
    grant_offer: dict | None = field(default=None)  # ready-to-write grant for "allow & remember"


# Non-user principals may never do these, regardless of grants (same spirit as
# BLOCKED_PATTERNS: the framework itself is not up for negotiation).
_SELF_MOD = ["tool:configure_agentos*", "tool:update_soul*", "tool:develop_agentos*",
             "tool:restart_agentos*", "tool:snapshot_os*"]
BUILTIN_DENY = {
    "app": [("tool.use", p) for p in _SELF_MOD],
    "subagent": [("tool.use", p) for p in _SELF_MOD] + [("agent.invoke", "*")],
    "workflow": [("tool.use", p) for p in _SELF_MOD] + [("agent.invoke", "*")],
}

# tool name -> (action, resource template); anything unlisted is plain tool.use
_FS_READ = {"read_file", "list_dir"}
_MEM = {"remember": ("memory.write", ""), "forget": ("memory.write", ""),
        "recall": ("memory.read", ""), "kg_add": ("kg.write", ""), "kg_query": ("kg.read", "")}


def action_of(name: str, args: dict, mcp=None) -> tuple[str, str]:
    """Map a tool call to (action, resource) — the vocabulary grants are written in.

    Resources: tool:run_command git status · mcp:github/create_issue · skill:webapp-testing
    fs:/home/x/AgentOS/notes.md · net:https://api.github.com/repos · memory:user · kg:*
    agent:subagent/researcher · model:anthropic/claude-sonnet-5 · app:<id>/data
    """
    args = args or {}
    if name.startswith("mcp_"):
        target = mcp.resolve(name) if mcp else None
        res = f"mcp:{target[0]}/{target[1]}" if target else f"mcp:{name[4:]}"
        return "mcp.use", res
    if name in _FS_READ:
        return "fs.read", f"fs:{args.get('path', '') or '*'}"
    if name == "write_file":
        return "fs.write", f"fs:{args.get('path', '') or '*'}"
    if name == "fetch_url":
        return "net.fetch", f"net:{args.get('url', '') or '*'}"
    if name in _MEM:
        action = _MEM[name][0]
        scope = args.get("scope", "user") if action.startswith("memory") else "*"
        return action, (f"memory:{scope}" if action.startswith("memory") else "kg:*")
    if name == "use_skill":
        return "skill.use", f"skill:{args.get('name', '') or '*'}"
    if name == "delegate":
        return "agent.invoke", f"agent:subagent/{args.get('subagent', '') or '*'}"
    if name == "run_workflow":
        return "agent.invoke", f"agent:workflow/{args.get('workflow', '') or '*'}"
    # default: same "<tool> <command-or-args>" string the legacy Policies app matches,
    # so patterns like "tool:run_command git *" work the way users already expect
    desc = args.get("command", "") if name == "run_command" else json.dumps(args)
    return "tool.use", f"tool:{name} {desc}".strip()


def _match(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(value, pattern or "*")


class PDP:
    """Holds the live grants (cached in memory, invalidated on any write) and decides."""

    def __init__(self, cfg: dict, store):
        self.cfg = cfg
        self.store = store
        self.mcp = None  # MCPManager, wired up in server startup (resolves mcp_* names)
        self._cache: list[dict] = []
        self._cache_version = -1

    def _grants(self) -> list[dict]:
        if self._cache_version != getattr(self.store, "grants_version", 0):
            self._cache = self.store.grants_live()
            self._cache_version = self.store.grants_version
        now = time.time()
        return [g for g in self._cache if not g.get("expires_at") or g["expires_at"] > now]

    def _matching(self, principal: Principal, action: str, resource: str) -> list[dict]:
        out = []
        for g in self._grants():
            if g["principal_kind"] not in (principal.kind, "*"):
                continue
            if not _match(g.get("principal_id") or "*", principal.id):
                continue
            if _match(g.get("action") or "*", action) and _match(g.get("resource") or "*", resource):
                out.append(g)
        return out

    def decide(self, principal: Principal, action: str, resource: str,
               context: dict | None = None) -> Decision:
        ctx = context or {}
        risk = ctx.get("risk", "safe")
        # 1. hard blocks (BLOCKED_PATTERNS + legacy deny policies, via risk_of)
        if risk == "blocked":
            return Decision("deny", ctx.get("reason") or "blocked", rule="hard-block")
        # 2. built-in denies for non-user principals
        for a, r in BUILTIN_DENY.get(principal.kind, ()):
            if _match(a, action) and _match(r, resource):
                return Decision("deny", f"{principal.label} may never do this "
                                        "(built-in protection of the OS itself)", rule="builtin-deny")
        # 3./4. grants — deny wins
        matched = self._matching(principal, action, resource)
        for g in matched:
            if g.get("effect") == "deny":
                return Decision("deny", g.get("note") or
                                f"denied by a grant rule (see the Permissions app)", rule=g["id"])
        for g in matched:
            if g.get("effect", "allow") == "allow":
                # persisted consent satisfies the approval requirement
                return Decision("allow", rule=g["id"])
        # 5. defaults by principal kind
        return self._default(principal, action, resource, ctx)

    def decide_tool(self, principal: Principal, name: str, args: dict,
                    risk_level: str, reason: str = "", autonomy: str = "") -> Decision:
        """The main entry for tool calls: maps the call to (action, resource) and decides."""
        action, resource = action_of(name, args, mcp=self.mcp)
        return self.decide(principal, action, resource,
                           {"risk": risk_level, "reason": reason, "autonomy": autonomy,
                            "tool": name, "args": args})

    def _default(self, principal: Principal, action: str, resource: str, ctx: dict) -> Decision:
        risk = ctx.get("risk", "safe")
        reason = ctx.get("reason", "")
        offer = self._offer(principal, action, resource, ctx)
        if action == "model.use":
            # models default open for everyone; restrict per principal with deny grants
            # (e.g. deny model.use model:anthropic/* for a subagent or app)
            return Decision("allow", rule="default")
        if principal.kind == "app":
            # an app always owns its own data store
            if action.startswith("app.data") and resource == f"app:{principal.id}/data":
                return Decision("allow", rule="default")
            if risk == "safe" and action not in ("model.use", "agent.invoke", "app.data.read",
                                                 "app.data.write"):
                return Decision("allow", rule="default")
            return Decision("ask", reason or "This app is asking to use a capability it has "
                                             "not been granted.", rule="default", grant_offer=offer)
        # user / subagent / workflow / system: today's autonomy semantics
        autonomy = ctx.get("autonomy") or self.cfg.get("autonomy", "balanced")
        if risk == "risky" and autonomy != "full":
            return Decision("ask", reason, rule="default",
                            grant_offer=offer if principal.kind != "user" else None)
        return Decision("allow", rule="default")

    def _offer(self, principal: Principal, action: str, resource: str, ctx: dict) -> dict:
        """A sensibly-generalized grant for the "allow & remember" button — broad enough
        to stop re-prompting for the same intent, narrow enough to stay meaningful."""
        name, args = ctx.get("tool") or "", ctx.get("args") or {}
        res = resource
        if name == "run_command":
            base = (args.get("command") or "").strip().split()
            res = f"tool:run_command {base[0]}*" if base else "tool:run_command*"
        elif action == "tool.use" and name:
            res = f"tool:{name}*"
        elif action in ("fs.read", "fs.write"):
            parent = os.path.dirname(resource[3:].rstrip("/"))
            res = f"fs:{parent}/*" if parent else resource
        elif action == "net.fetch":
            u = urlsplit(resource[4:])
            res = f"net:{u.scheme}://{u.netloc}/*" if u.netloc else resource
        return {"principal_kind": principal.kind, "principal_id": principal.id,
                "action": action, "resource": res}
