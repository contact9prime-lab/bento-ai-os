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
    action: str = ""    # stamped by decide() so enforcement sites can log verbosely
    resource: str = ""
    audit_id: str = ""  # the ledger row for this decision; stamp its outcome when the call returns


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
# Media is its own vocabulary rather than another `tool.use` string, because the
# three things it can do have genuinely different consequences: reading an asset
# is free, writing one fills a disk, and generating one spends money at somebody
# else's API. A single action could not express "may look at the gallery, may not
# bill my Higgsfield account".
_MEDIA = {"list_assets": ("media.read", "media:*"),
          "get_asset": ("media.read", ""),
          "save_asset": ("media.write", ""),
          "delete_asset": ("media.write", ""),
          "generate_image": ("media.generate", "media:image")}
_SPACE = {"list_spaces": ("space.read", "space:*"),
          "create_space": ("space.write", ""),
          "switch_space": ("space.write", ""),
          "timeline": ("space.read", "")}


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
        # Space-qualified so a grant can say "this subagent may write memory in the
        # marketing space and nowhere else" — the whole reason spaces are modelled
        # at the policy layer and not only in the UI.
        space = args.get("space_id") or args.get("space") or ""
        suffix = f"@{space}" if space else ""
        if action.startswith("memory"):
            return action, f"memory:{args.get('scope', 'user')}{suffix}"
        return action, f"kg:{space or '*'}"
    if name in _MEDIA:
        action, res = _MEDIA[name]
        if not res:
            res = f"media:{args.get('asset_id') or args.get('kind') or '*'}"
        return action, res
    if name in _SPACE:
        action, res = _SPACE[name]
        if not res:
            res = f"space:{args.get('name') or args.get('space_id') or '*'}"
        return action, res
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


# The IO gates: every capability call arrives via one of these surfaces. Grants may be
# scoped to a subset (grants.surfaces csv); '*' means all surfaces (the default).
SURFACES = ("gui", "tui", "telegram", "api", "task")


# How much a channel is trusted, independent of who is asking. This is a property
# of the WAY IN, not of the principal: the same person is more exposed over
# WhatsApp than sitting at the machine, and a channel with nobody watching cannot
# answer an approval prompt at all.
POSTURES = ("inherit", "read_only", "ask", "full")


# Where the content in this turn came from. The grants system answers "who is
# asking"; this answers "on whose say-so" — and they are different questions.
# A web page, an MCP server's reply or a document the agent was handed can all
# contain text shaped like an instruction, and the model has no reliable way to
# tell that apart from the user's own words. So the rule is not "detect the
# attack" (undecidable) but "a risky action whose turn has swallowed untrusted
# content is not something a machine gets to decide alone".
#
#   off    — no escalation (the old behaviour; explicit, not accidental)
#   ask    — a risky action after untrusted content asks, even at full autonomy
#   strict — it is refused outright
TAINT_MODES = ("off", "ask", "strict")


def taint_mode(cfg: dict) -> str:
    m = str(((cfg.get("security") or {}).get("taint")) or "ask")
    return m if m in TAINT_MODES else "ask"


def taint_summary(taint) -> str:
    """One readable phrase naming where the untrusted content came from."""
    srcs, seen = [], set()
    for t in taint or []:
        s = (t.get("source") if isinstance(t, dict) else str(t)) or "?"
        if s not in seen:
            seen.add(s)
            srcs.append(s)
    if not srcs:
        return "content from outside this machine"
    head = ", ".join(srcs[:3])
    return head + (f" (+{len(srcs) - 3} more)" if len(srcs) > 3 else "")


def channel_posture(cfg: dict, surface: str) -> str:
    """The posture configured for the gate a call arrived on ('inherit' if none)."""
    if not surface:
        return "inherit"
    conf = (cfg.get("channels") or {}).get(surface) or {}
    p = str(conf.get("posture") or "inherit")
    return p if p in POSTURES else "inherit"


def surface_allows(grant_surfaces: str, surface: str) -> bool:
    """Does a grant's surface scope cover the surface this call arrived on?
    Unscoped grants ('*'/empty) cover everything; an unknown/blank surface only
    matches unscoped grants (a scoped grant never applies to an unidentified gate)."""
    gs = (grant_surfaces or "*").strip()
    if gs in ("", "*"):
        return True
    if not surface:
        return False
    return surface in {s.strip() for s in gs.split(",") if s.strip()}


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
        dec = self._decide(principal, action, resource, context)
        dec.action, dec.resource = action, resource
        dec.audit_id = self._record(principal, action, resource, context or {}, dec)
        return dec

    def _record(self, principal: Principal, action: str, resource: str,
                ctx: dict, dec: Decision) -> str:
        """Write the access ledger entry for this decision.

        Every capability call in the OS funnels through decide(), which makes this
        the one place where "who was allowed to do what, arriving on which
        surface, and under which rule" can be recorded without asking a dozen
        call sites to remember to. The operator log (`logs`) keeps its free-text
        diary; this is the structured record you can actually query.

        Never raises and never blocks a decision: a ledger that can take a turn
        down would be a worse problem than the one it solves. `Store.audit_add`
        already swallows and re-reports its own failures.
        """
        if ctx.get("audit") is False:  # internal probes ("could I?"), not accesses
            return ""
        store = getattr(self, "store", None)
        if store is None or not hasattr(store, "audit_add"):
            return ""
        try:
            return store.audit_add(
                principal_kind=principal.kind, principal_id=principal.id,
                surface=ctx.get("surface", ""), action=action, resource=resource,
                effect=dec.effect, rule=dec.rule, risk=ctx.get("risk", ""),
                reason=dec.reason or ctx.get("reason", ""),
                space_id=ctx.get("space_id", ""),
                conversation_id=ctx.get("conversation_id", ""),
                run_id=ctx.get("run_id", ""))
        except Exception:
            return ""

    def _decide(self, principal: Principal, action: str, resource: str,
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
        surface = ctx.get("surface", "")
        # 2b. the channel ceiling. A read-only channel refuses rather than asks,
        # and it is checked BEFORE grants on purpose: "read-only over Telegram"
        # has to mean it even when a grant says allow-everywhere. Narrowing a way
        # in should not be silently undone by a permission granted at the desk.
        if channel_posture(self.cfg, surface) == "read_only" and risk != "safe":
            return Decision("deny",
                            f"the {surface} channel is set to read-only, so it may look "
                            f"but not change anything (Settings → Channels)",
                            rule="channel-read-only")
        # 2c. the taint ceiling. Like the channel ceiling above it, this is checked
        # BEFORE grants, and for the same reason: "allow fetch_url everywhere" is
        # consent for the agent to fetch pages, not consent for a fetched page to
        # spend the grant on something else. A safe action is never escalated —
        # reading stays free, and only the steps that change something outside the
        # conversation are held back for a human.
        taint = ctx.get("taint") or []
        mode = taint_mode(self.cfg)
        if taint and risk != "safe" and mode != "off":
            where = taint_summary(taint)
            if mode == "strict":
                return Decision("deny",
                                f"this turn has read untrusted content ({where}) and "
                                f"security.taint is set to strict, so it may not take "
                                f"actions that change anything",
                                rule="taint")
            return Decision("ask",
                            f"{ctx.get('reason') or 'This changes something.'} This turn has "
                            f"also read untrusted content ({where}) — content from outside "
                            f"this machine can be written to look like an instruction, so "
                            f"this step is being shown to you rather than assumed.",
                            rule="taint")   # deliberately no grant_offer: "remember this"
                                            # would hand the next web page the same key
        # 3./4. grants — deny wins; each grant only applies on the surfaces it covers
        matched = self._matching(principal, action, resource)
        gated = [g for g in matched if surface_allows(g.get("surfaces"), surface)]
        for g in gated:
            if g.get("effect") == "deny":
                return Decision("deny", g.get("note") or
                                f"denied by a grant rule (see the Permissions app)", rule=g["id"])
        for g in gated:
            if g.get("effect", "allow") == "allow":
                # persisted consent satisfies the approval requirement
                return Decision("allow", rule=g["id"])
        # IO gate: consent exists but is scoped to OTHER surfaces — the call arriving
        # via this gate is not permitted; enforcement sites log this as an IO error
        if any(g.get("effect", "allow") == "allow" for g in matched):
            gate = surface or "unknown"
            return Decision("deny",
                            f"IO gate: {action} {resource} is granted, but not for the "
                            f"'{gate}' surface (see the grant's surfaces in the "
                            f"Permissions app)", rule="io-gate")
        # 5. defaults by principal kind
        return self._default(principal, action, resource, ctx)

    def decide_tool(self, principal: Principal, name: str, args: dict,
                    risk_level: str, reason: str = "", autonomy: str = "",
                    surface: str = "", space_id: str = "",
                    conversation_id: str = "", run_id: str = "",
                    taint: list | None = None, audit: bool = True) -> Decision:
        """The main entry for tool calls: maps the call to (action, resource) and decides.
        `surface` is the IO gate the call arrived on (gui | tui | telegram | api | task);
        the space/conversation/run are carried so the ledger entry says WHERE it happened,
        not just what was asked for. `taint` is what untrusted content this turn has
        already read (see the taint ceiling in `_decide`)."""
        action, resource = action_of(name, args, mcp=self.mcp)
        return self.decide(principal, action, resource,
                           {"risk": risk_level, "reason": reason, "autonomy": autonomy,
                            "tool": name, "args": args, "surface": surface,
                            "space_id": space_id, "conversation_id": conversation_id,
                            "run_id": run_id, "taint": taint or [],
                            # audit=False marks a "could this principal?" probe —
                            # filtering a tool list is one question, not ninety
                            # accesses, and the ledger is for what was done
                            "audit": audit})

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
        # A channel may set its own autonomy — deliberately in both directions.
        # "Act freely at the desk, ask over Telegram" and its reverse are both
        # things people mean; the machine default applies where nothing is set.
        posture = channel_posture(self.cfg, ctx.get("surface", ""))
        if posture == "ask":
            autonomy = "balanced"
        elif posture == "full":
            autonomy = "full"
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
