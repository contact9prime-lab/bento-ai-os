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
from . import users as usersmod


@dataclass(frozen=True)
class Principal:
    kind: str  # "user" | "app" | "subagent" | "workflow" | "flow" | "system"
    id: str = ""  # "" for the user; app id; subagent/workflow/flow name

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
# Defining a flow writes grants, so anything that could define one could grant itself
# whatever it liked by writing a flow that says so. Only the user's own agent may, and even
# then the flow is created disabled — enabling is what grants, and that stays a human act.
_NO_FLOW_WRITE = [("flow.write", "*")]
# Defining a subagent is the same shape of decision as defining a flow: the
# definition IS a capability set (a model, a tool list, a skill list), so anything
# that could write one could hand itself capabilities by naming them in a new
# agent and then calling it. Only the user's own agent may define one — and
# defining grants nothing by itself, because `agent.invoke` is what asks.
_NO_AGENT_WRITE = [("agent.write", "*")]
_DEFINE = _NO_FLOW_WRITE + _NO_AGENT_WRITE
BUILTIN_DENY = {
    "app": [("tool.use", p) for p in _SELF_MOD] + _DEFINE,
    "subagent": [("tool.use", p) for p in _SELF_MOD] + [("agent.invoke", "*")] + _DEFINE,
    "workflow": [("tool.use", p) for p in _SELF_MOD] + [("agent.invoke", "*")] + _DEFINE,
    # A flow's master orchestrator is the one principal in the OS that exists to invoke
    # other agents, so the blanket agent.invoke deny above would defeat its purpose. It
    # is still barred from rewriting the OS, and delegation is not free: `_default` gives
    # a flow NO default for agent.invoke, so only a grant written from its own definition
    # (its roster) can satisfy one. The agents it starts run as `subagent`, which IS
    # denied above — which is what makes the tree exactly two deep, enforced by the gate
    # rather than by a counter somebody has to remember to increment.
    "flow": [("tool.use", p) for p in _SELF_MOD] + _DEFINE,
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
    # Writing a flow is its own capability, not another tool.use string: a flow definition
    # IS a set of standing permissions, so "may define a flow" and "may fetch a URL" are not
    # the same kind of question and must be grantable apart.
    if name in ("create_flow", "enable_flow"):
        return "flow.write", f"flow:{args.get('name', '') or '*'}"
    # Building an agent is not "using a tool". It writes a standing definition that
    # says which model, tools and skills that agent will hold, so it is grantable
    # (and deniable) apart from everything else — see _NO_AGENT_WRITE.
    if name == "create_subagent":
        return "agent.write", f"agent:subagent/{args.get('name', '') or '*'}"
    if name == "list_flows":
        return "flow.read", "flow:*"
    if name == "run_flow":
        return "agent.invoke", f"agent:flow/{args.get('flow', '') or '*'}"
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
# `webhook` is another service calling in over HTTP to start a flow — a gate with no
# human behind it at all, which is exactly why it is nameable in a grant.
SURFACES = ("gui", "tui", "telegram", "whatsapp", "api", "task", "webhook")


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


# How fast a principal may spend what it has been granted.
#
# Grants answer "may it?" and budgets answer "how long?" — neither answers "how often?".
# A subagent is bounded by max_steps and a flow by its delegation budget, but a user app
# runs in a browser tab and can loop for as long as the tab is open. A grant of fetch_url
# is consent to fetch pages, not consent to fetch six hundred a minute, and the difference
# between those two is the only thing standing between a bug in a refresh handler and a
# machine hammering somebody else's API all night.
#
# Two thresholds, because the two failures look different. A dashboard fetching a dozen
# tickers on refresh is a legitimate BURST; a runaway loop is SUSTAINED. Tripping the burst
# limit refuses that one call and nothing else. Tripping it over and over is what gets an
# app stopped.
# Calls are metered in CLASSES, because "too many" means different numbers for different
# things. Six model calls a minute from a dashboard is money leaving at a rate nobody asked
# for; six fetches is a page refreshing. Counting them together would either quarantine
# every working app or catch no runaway at all.
LLM_TOOLS = {"llm_generate", "generate_image", "appLLM.stream", "app→appLLM.stream",
             "generate_wallpaper", "create_theme", "create_app"}


def call_class(tool: str) -> str:
    t = (tool or "").split("→")[-1]
    if t in LLM_TOOLS:
        return "llm"
    return "tool"


# principal kind -> class -> (calls allowed, window seconds)
# Grounded in what this machine actually does: its busiest legitimate app burst was 25
# fetches in 10s on refresh, and no app has ever made more than a handful of model calls in
# a minute. So the tool limit sits above real bursts and the llm limit sits just above real
# use — a runaway loop passes both by an order of magnitude.
RATE_DEFAULTS = {
    "app":      {"llm": (6, 60), "tool": (60, 20)},
    "subagent": {"llm": (20, 60), "tool": (120, 20)},
    "flow":     {"llm": (20, 60), "tool": (120, 20)},
}


def rate_limits(cfg: dict, kind: str) -> dict | None:
    conf = (cfg.get("security") or {}).get("rate_limits")
    if conf is not None and not conf:
        return None                       # explicitly disabled
    table = {**RATE_DEFAULTS, **(conf or {})}
    lim = table.get(kind)
    return {k: tuple(v) for k, v in lim.items()} if lim else None


class RateMeter:
    """In-memory call history per principal. Never touches the database: this is consulted
    on every single capability call, and a gate that costs a write is a gate somebody will
    eventually be tempted to remove."""

    def __init__(self):
        self._calls: dict = {}   # label -> [timestamps]
        self._trips: dict = {}   # label -> [timestamps of burst trips]

    def record(self, label: str, now: float, keep: float):
        q = self._calls.setdefault(label, [])
        q.append(now)
        if len(q) > 512:                  # bounded: a runaway must not also eat memory
            del q[:-512]
        cut = now - keep
        while q and q[0] < cut:
            q.pop(0)

    def count(self, label: str, now: float, window: float) -> int:
        cut = now - window
        return sum(1 for t in self._calls.get(label, ()) if t >= cut)

    def trip(self, label: str, now: float, window: float) -> int:
        q = self._trips.setdefault(label, [])
        q.append(now)
        cut = now - window
        while q and q[0] < cut:
            q.pop(0)
        return len(q)

    def forget(self, label: str):
        self._calls.pop(label, None)
        self._trips.pop(label, None)


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


class PDP(usersmod.Scoped):
    """Holds the live grants (cached in memory, invalidated on any write) and decides."""

    def __init__(self, cfg: dict, store):
        self.cfg = cfg
        self.store = store
        self.mcp = None  # MCPManager, wired up in server startup (resolves mcp_* names)
        # Every in-memory cache below is keyed by WHO as well as by what. One PDP
        # serves every user on the machine, and a version counter is per-database:
        # two people can both be at grants_version 3, and without the prefix the
        # second would be decided against the first one's grants. `_skills` and the
        # rate meter collide the same way — two users may each own a subagent called
        # "researcher" or an app called "notes".
        self._cache: dict = {}    # uid -> (version, grants)
        self._skills: dict = {}   # uid|principal.label -> (expires_at, set(names))
        self._rate = RateMeter()
        self._q_cache: dict = {}  # uid|principal.label -> row or None
        self._q_version: dict = {}
        # on_rate_trip(principal, stats): wired in server startup. The PDP decides that
        # something has gone rogue; what happens then — writing the hold, telling the user —
        # belongs to the layer that owns apps and notifications, not to the gate.
        self.on_rate_trip = None

    def _who(self) -> str:
        """The prefix that keeps one person's cached decisions out of another's."""
        return usersmod.current() if usersmod.enabled() else ""

    def forget_rate(self, kind: str, pid: str) -> None:
        """Drop a principal's call history — what "release from quarantine" means.

        A method rather than three pokes at `_rate` from the server, because the
        meter's key now carries the user, and a key built by hand at a call site is
        a key that will eventually be built without it: the release would silently
        do nothing and the app would look permanently held.
        """
        label = Principal(kind, pid).label
        for cls in ("llm", "tool"):
            self._rate.forget(f"{self._who()}|{label}|{cls}")

    def _grants(self) -> list[dict]:
        uid = self._who()
        ver, cached = self._cache.get(uid, (-1, []))
        if ver != getattr(self.store, "grants_version", 0):
            cached = self.store.grants_live()
            self._cache[uid] = (self.store.grants_version, cached)
        now = time.time()
        return [g for g in cached if not g.get("expires_at") or g["expires_at"] > now]

    def _declared_skills(self, principal: Principal) -> set:
        """The skills a definition lists — an allow-list when non-empty, unrestricted when
        not. Memoised for a few seconds because a skill load is rare and an edit in the
        Workflows app should take effect without a restart."""
        key = self._who() + "|" + principal.label
        hit = self._skills.get(key)
        now = time.time()
        if hit and hit[0] > now:
            return hit[1]
        names: set = set()
        try:
            if principal.kind == "subagent":
                d = self.store.get_subagent(principal.id) or {}
                if d.get("skills_locked", 1):
                    names = {str(s) for s in (d.get("skills") or [])}
            elif principal.kind == "flow":
                d = self.store.get_flow(principal.id) or {}
                names = {str(s) for s in ((d.get("permissions") or {}).get("skills") or [])}
        except Exception:
            names = set()
        self._skills[key] = (now + 5, names)
        return names

    def _held(self, principal: Principal) -> dict | None:
        """Is this principal in quarantine? Cached against the store's version counter,
        because this is asked on every capability call."""
        if principal.kind not in ("app", "subagent", "flow"):
            return None
        uid = self._who()
        ver = getattr(self.store, "quarantine_version", 0)
        if self._q_version.get(uid) != ver:
            self._q_cache = {k: v for k, v in self._q_cache.items()
                             if not k.startswith(uid + "|")}
            self._q_version[uid] = ver
        key = uid + "|" + principal.label
        if key not in self._q_cache:
            try:
                self._q_cache[key] = self.store.quarantined(principal.kind, principal.id)
            except Exception:
                self._q_cache[key] = None
        return self._q_cache[key]

    def _rate_check(self, principal: Principal, ctx: dict) -> "Decision | None":
        """None to carry on; a Decision to refuse.

        Something already held is refused outright — that is what being held means. Anything
        else is metered per class of call, and going over puts it in quarantine: this is the
        one ceiling that decides, by itself, that something should stop.
        """
        if principal.kind not in ("app", "subagent", "flow"):
            return None
        held = self._held(principal)
        if held:
            why = held.get("reason") or "it was calling too fast"
            return Decision("deny",
                            f"{principal.label} is quarantined — {why}. Nothing it asks for "
                            f"runs until you let it out.",
                            rule="quarantined")
        lim = rate_limits(self.cfg, principal.kind)
        if not lim:
            return None
        try:
            if self.store.quarantine_exempt(principal.kind, principal.id):
                return None               # the user said "allow this forever"; honour it
        except Exception:
            pass
        cls = call_class(ctx.get("tool") or "")
        allowed, window = lim.get(cls) or lim.get("tool")
        label = f"{self._who()}|{principal.label}|{cls}"
        now = time.time()
        self._rate.record(label, now, window)
        n = self._rate.count(label, now, window)
        if n <= allowed:
            return None
        what = "model calls" if cls == "llm" else "tool calls"
        reason = (f"{n} {what} in {int(window)}s, over its limit of {allowed} — "
                  f"it was calling {ctx.get('tool') or 'tools'} in a loop")
        stats = {"count": n, "window": window, "allowed": allowed, "class": cls,
                 "tool": ctx.get("tool", ""), "reason": reason}
        # The hold is written HERE, not in the callback. The gate deciding something is
        # rogue and the thing actually being held must not be two facts that can disagree:
        # if nobody had wired a callback, the call would be refused, the next one metered
        # afresh, and it would let the loop through again a second later.
        try:
            self.store.quarantine_add(principal.kind, principal.id, reason,
                                      kind=cls, evidence=stats)
        except Exception:
            pass
        if self.on_rate_trip:
            try:
                self.on_rate_trip(principal, stats)   # telling the user is the caller's job
            except Exception:
                pass
        self._q_version.clear()           # the hold was just written; re-read it next call
        return Decision("deny",
                        f"{principal.label} was quarantined: {reason}.",
                        rule="quarantined")

    def _invoke_reason(self, resource: str) -> str:
        """What approving this invocation actually hands over.

        A subagent is a second actor with its own model, its own tools and its own
        spending, so "the assistant wants to delegate" is not enough to consent to.
        The card names the agent, what it runs on and what it may reach — the same
        list its definition will enforce — because a permission nobody can picture
        is one people click through.
        """
        kind, _, name = resource.partition(":")[2].partition("/")
        if kind != "subagent" or not name or not self.store:
            return f"Runs '{name or resource}' — a separate agent, with its own steps and budget."
        try:
            d = self.store.get_subagent(name) or {}
        except Exception:
            d = {}
        if not d:
            return f"Runs '{name}', a separate agent with its own steps and budget."
        tools = d.get("tools") or []
        skills = d.get("skills") or []
        bits = [f"Runs '{name}' as a separate agent",
                f"on {d.get('model') or 'the default model'}",
                f"capped at {d.get('max_steps', 12)} steps / {d.get('max_seconds', 300)}s"]
        line = ", ".join(bits) + "."
        line += (f" It may use: {', '.join(tools[:12])}."
                 if tools else " It gets the safe read-only tool set.")
        if skills:
            line += f" Skills: {', '.join(skills[:6])}."
        return line

    def _declared_roster(self, principal: Principal) -> set:
        """The agents a flow's definition lists. Memoised briefly, like the skills."""
        key = self._who() + "|roster:" + principal.label
        hit = self._skills.get(key)
        now = time.time()
        if hit and hit[0] > now:
            return hit[1]
        names: set = set()
        try:
            d = self.store.get_flow(principal.id) or {}
            names = {(r.get("subagent") if isinstance(r, dict) else str(r))
                     for r in (d.get("roster") or [])}
        except Exception:
            names = set()
        self._skills[key] = (now + 5, names)
        return names

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
        # 2d. the rate ceiling. Before grants, for the same reason as the two above:
        # "allow fetch_url" is consent to fetch pages, not consent to fetch them without
        # end. This is the only ceiling that can decide, by itself, to stop something.
        if ctx.get("audit") is not False:      # probes are not calls; do not meter them
            rl = self._rate_check(principal, ctx)
            if rl is not None:
                return rl
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
        if principal.kind == "flow" and action == "agent.invoke":
            # No default for a flow's delegation: `delegate` is not in risk_of's table, so
            # it arrives here as "safe" and would otherwise be allowed outright. The roster
            # is the whole boundary, and two different refusals hide behind it:
            #
            #   not on the roster at all       -> deny. Nothing to discuss.
            #   on the roster, not yet granted -> ASK. This is the flow you drafted and
            #        have not enabled, being tried by hand with you watching. Denying it
            #        would make a test run pointless — the master could never call anyone —
            #        so it escalates instead, down the same "grant, then escalate" path
            #        every other ungranted capability takes. Unattended, nobody answers and
            #        it still ends in a denial, so this loosens nothing that runs alone.
            want = resource.split("/", 1)[1] if "/" in resource else ""
            if want and want in self._declared_roster(principal):
                return Decision("ask",
                                f"'{principal.id}' wants to delegate to '{want}'. It is on the "
                                f"flow's roster, but the flow has not been enabled, so it has "
                                f"not been granted this yet.",
                                rule="roster-ungranted", grant_offer=offer)
            return Decision("deny",
                            f"'{principal.id}' may only delegate to the agents on its roster — "
                            f"add one in Workflows → Flows and save, which writes the grant",
                            rule="roster")
        if action == "skill.use" and principal.kind in ("subagent", "flow"):
            # An allow-list cannot be expressed as grants: deny is evaluated first and
            # returns immediately, so a blanket `deny skill:*` alongside per-skill allows
            # would refuse everything. It belongs here, where "what this definition lists"
            # is the question being asked.
            allow = self._declared_skills(principal)
            if allow:  # empty/absent = unrestricted, which is the pre-existing behaviour
                want = resource.split(":", 1)[1] if ":" in resource else "*"
                if want not in allow:
                    return Decision("deny",
                                    f"'{principal.id}' may only load the skills its definition "
                                    f"lists ({', '.join(sorted(allow))}) — add it in Team",
                                    rule="skill-allowlist")
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
        # Starting another agent is its own consent, asked ONCE per agent. It is not
        # covered by the risk table — `delegate` is absent from it and so arrives here
        # as "safe" — and it should not be: a turn that quietly starts a researcher
        # which reads forty pages and bills a cloud model is not the same event as a
        # turn that read one file. The offer is scoped to that one agent, so this is a
        # first-use question and never a per-call one.
        #
        # Unattended (a scheduled task, a webhook) nobody answers and it ends in a
        # denial with the reason in the ledger — the same shape a flow's ungranted
        # roster takes, and for the same reason: this must not become a way for
        # something running alone to acquire an actor the user never approved.
        if action == "agent.invoke" and autonomy != "full":
            return Decision("ask", reason or self._invoke_reason(resource),
                            rule="default", grant_offer=offer)
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
