"""When a foreign plugin does not fit: say so, then offer to build it properly.

Two integrations already exist. `ocplugins.py` leaves a plugin inside OpenClaw's
gateway and can gate only its lifecycle. `ochost.py` runs it here, behind the PDP,
but through a compatibility shim that hosts some of OpenClaw's API and refuses the
rest. Both are honest and both have gaps.

A gap used to be the end of the sentence. This module makes it a fork:

    install / enable a plugin
      → here is exactly what will NOT work on this machine, and why
      → [ proceed anyway ]  [ build it natively for Bento ]  [ cancel ]

and the second answer is the interesting one. AgentOS has an agent, and the
plugin's own manifest is a specification: it names the tools it provides, the MCP
servers it starts, the events it wants, and the config it needs. That is enough to
brief the agent to build the same capability out of primitives this OS already
governs — a flow, tools, an MCP server, a skill — where there is no shim, no
refused API and no ungoverned network, because every one of those runs behind the
PDP already.

Three rules keep this from becoming a machine for confident nonsense:

- **The brief is DERIVED, never invented.** Everything in it comes from the
  plugin's own manifest. Where the manifest says nothing, the brief says the
  manifest says nothing — it does not guess what a plugin called `voice-call`
  probably does. A fabricated spec would produce a fabricated implementation, and
  the user would have no way to tell.
- **A native build is a PROPOSAL.** It writes a flow, a skill or an MCP entry and
  leaves it DISABLED, exactly as `create_flow` does. Enabling is still the act of
  granting. Porting a plugin must not be a way to acquire permissions without
  being asked for them.
- **The same brief is the acceptance test.** `verify()` checks what got built
  against what was asked for, item by item. Building and checking from one
  document is what stops "done" from meaning "the agent said done" — the same
  reason `appcheck.py` exists for generated apps and the reason `preview()` and
  `enable_plugin()` share one computation in `ocplugins`.

HTTP-free and asyncio-free, like `jobs.py`: `bento openclaw` on a headless box
uses the same catalogue and the same checks as the desktop.
"""

from __future__ import annotations

#: OpenClaw concept -> what carries it in AgentOS. The intellectual content of
#: this module is this table, and its most important rows are the ones whose
#: target is None: a concept with no equivalent here must be reported as
#: unportable, not quietly mapped onto the nearest thing that compiles.
MAPPING: tuple[dict, ...] = (
    {"from": "contracts.tools", "to": "mcp",
     "what": "the tools it gives the agent",
     "how": "an MCP server AgentOS runs, whose tools arrive as mcp_<server>_<tool> "
            "and are gated per call by the PDP — the same door every other MCP tool uses"},
    {"from": "mcpServers", "to": "mcp",
     "what": "MCP servers it contributes",
     "how": "these port ACROSS UNCHANGED — an MCP server is an MCP server, and "
            "AgentOS already runs and gates them. Usually the cheapest win in a port"},
    {"from": "cliCommands", "to": "flow",
     "what": "commands it adds",
     "how": "a flow with a mission, runnable by name from chat, the CLI or a trigger"},
    {"from": "activation.onHooks", "to": "flow",
     "what": "events it wants to run on",
     "how": "a flow trigger (cron, message, webhook, os_event, flow_done) where the "
            "intent is event-driven. A hook that wanted to sit INSIDE a turn has no "
            "equivalent and is reported as such rather than approximated"},
    {"from": "configSchema", "to": "config",
     "what": "settings it needs",
     "how": "what the build asks you for once, stored in this OS's config"},
    {"from": "prompt/instructions", "to": "skill",
     "what": "know-how it carries",
     "how": "a skill — prose the agent loads when it is relevant, gated by skill.use"},

    # No equivalent. These rows exist to be reported, not to be satisfied.
    {"from": "contracts.trustedToolPolicies", "to": None,
     "what": "host-trusted pre-tool policies",
     "how": "AgentOS's PDP IS that tier and is not delegable to a plugin. If you want "
            "a budget or guardrail rule, write it as a grant or a deny policy"},
    {"from": "contracts.agentToolResultMiddleware", "to": None,
     "what": "rewriting tool results before the model sees them",
     "how": "not offered, deliberately: it sits between what happened and what the "
            "agent is told happened"},
    {"from": "providers", "to": None,
     "what": "model providers it owns",
     "how": "AgentOS has its own provider list — add the provider there instead"},
    {"from": "channels", "to": None,
     "what": "messaging channels it owns",
     "how": "a channel must be one AgentOS owns end to end (see CLAUDE.md); a ported "
            "one would be the carrier tier this OS deliberately removed"},
    {"from": "kind: memory | context-engine", "to": None,
     "what": "taking over memory or the context engine",
     "how": "AgentOS's memory is its own; there is no slot to hand over"},
)

BY_SOURCE = {m["from"]: m for m in MAPPING}


def _nonempty(seq) -> list:
    return [x for x in (seq or []) if x]


def _contracts(manifest: dict) -> dict:
    c = (manifest or {}).get("contracts")
    return c if isinstance(c, dict) else {}


# ---------------------------------------------------------------------------
# Licensing: the same licence means two different things here
# ---------------------------------------------------------------------------
# AgentOS already refuses to SHIP anything non-permissive and states the licence
# of everything it merely offers (`components.py`). A plugin raises that question
# twice, and the two answers are genuinely different:
#
#   installing  you RUN it. Running someone's GPL software is what the GPL is for
#               and needs no permission from anybody. The licence still matters
#               for what you may do with it later, so it is stated, but it is
#               rarely a reason to stop.
#   porting     the agent reads the plugin's declarations and writes NEW code that
#               does the same job. For a copyleft plugin that raises a derivative-
#               work question, and that is a decision for the person, not for us.
#
# AgentOS is not qualified to answer the legal question and does not try. It
# states what the licence is, what the port would actually read, and why the
# combination is worth a look — then asks. Saying nothing would be worse: this is
# the one place where a wrong assumption costs somebody a licence violation
# rather than a broken feature.

#: klass -> (may we proceed without asking?, what it means for a PORT)
_PORT_POSITION = {
    "permissive": (
        True,
        "Permissive. Rebuilding its ideas as your own code is what this licence "
        "is for. Keep the attribution its terms ask for."),
    "weak-copyleft": (
        False,
        "Weak copyleft. Its terms generally attach to the file or library rather "
        "than to everything that touches it — but a rewrite that closely follows "
        "its source is a different question from merely using it."),
    "copyleft": (
        False,
        "Strong copyleft. If the port ends up a derivative of that source, its "
        "terms would attach to what AgentOS writes — which, for AGPL, can extend "
        "to software you only ever run as a service."),
    "proprietary": (
        False,
        "Not an open-source licence. Re-implementing it may be exactly what its "
        "terms forbid, and there is no public grant to fall back on."),
    "unknown": (
        False,
        "No licence is declared. That is not the same as permissive: with no "
        "grant, the default is that you have no rights to copy or adapt it."),
}

_INSTALL_POSITION = {
    "permissive": "Permissive — nothing here constrains you.",
    "weak-copyleft": "Weak copyleft. Running it is fine; redistributing a machine "
                     "image containing it carries its terms.",
    "copyleft": "Copyleft. Running it is fine and always has been; shipping it on "
                "to somebody else carries its terms with it.",
    "proprietary": "Not an open-source licence — check that your use is one its "
                   "terms allow.",
    "unknown": "No licence declared, so nothing states what you may do with it.",
}


def licence_position(lic: dict, action: str = "port") -> dict:
    """What this licence means for what is about to happen. Never legal advice.

    Returns {klass, spdx, where, headline, implication, needs_ack, ask}. The
    `ask` is the sentence a person is answering — it names the licence and the
    act, because "would you like to continue?" on its own is a question nobody
    can answer well.
    """
    klass = (lic or {}).get("klass") or "unknown"
    spdx = (lic or {}).get("spdx") or ""
    where = (lic or {}).get("where") or ""
    named = spdx or "no declared licence"
    if action == "install":
        return {
            "klass": klass, "spdx": spdx, "where": where,
            "headline": f"Licence: {named}" + (f" (from {where})" if where else ""),
            "implication": _INSTALL_POSITION[klass],
            # Installing is running, and running is what a licence is for. Only a
            # complete absence of one is worth stopping a person over.
            "needs_ack": klass in ("proprietary", "unknown"),
            "ask": (f"This plugin declares {named}. Installing it means running it here. "
                    f"Continue?"),
        }
    ok, implication = _PORT_POSITION[klass]
    return {
        "klass": klass, "spdx": spdx, "where": where,
        "headline": f"Licence: {named}" + (f" (from {where})" if where else ""),
        "implication": implication,
        "needs_ack": not ok,
        "ask": (f"This plugin declares {named}. A native build reads what it DECLARES — "
                f"the names of its tools, MCP servers, events and settings — and writes "
                f"new code to do that job; it does not copy its source. Whether the "
                f"result is a derivative work is a judgement about your situation that "
                f"AgentOS cannot make for you. Continue?"),
    }


#: What a port actually reads, stated once so every surface says the same thing
#: and nobody has to infer it from the word "port".
PORT_READS = ("the plugin's own manifest — the names of the tools it provides, the MCP "
              "servers it starts, the events it wants and the settings it needs. It does "
              "not copy the plugin's source code.")


# ---------------------------------------------------------------------------
# The disclaimer: what will NOT work here, in the user's terms
# ---------------------------------------------------------------------------

def compatibility(manifest: dict, hosted: bool = False,
                  hosting: dict | None = None) -> dict:
    """What this machine cannot honestly do with this plugin.

    `hosted` picks which bargain is being described — left in OpenClaw's gateway
    (`ocplugins`) or run here behind the PDP (`ochost`) — because the gaps are
    genuinely different and describing the wrong set would be worse than
    describing none. `hosting` is `ochost.hosting_report()` when one has been
    taken, so the refusals and the sandbox verdict are the REAL ones from a real
    load rather than a prediction.

    Returns {gaps, verdict, portable, headline}. `verdict` is 'clean' | 'caveats'
    | 'partial': partial means something it declares simply will not happen here.
    """
    m = manifest or {}
    c = _contracts(m)
    gaps: list[dict] = []

    def gap(sev, what, why, remedy=""):
        gaps.append({"severity": sev, "what": what, "why": why, "remedy": remedy})

    if not hosted:
        # The gateway bargain. One gap, and it is the whole of it.
        gap("high", "AgentOS cannot refuse what this plugin does",
            "left in OpenClaw's gateway it runs in OpenClaw's process, so its calls "
            "never reach this OS's permission engine. AgentOS can decide whether it is "
            "installed and enabled, and nothing finer.",
            "build it natively instead, and every call goes through the PDP")
    else:
        for u in (hosting or {}).get("unsupported") or []:
            gap("high", f"{u['api']} is not hosted", u.get("detail") or "",
                "the native build has a real equivalent for some of these")
        if d := (hosting or {}).get("discrepancy"):
            gap("high", "a tool it declares did not register here", d,
                "a gap in the compatibility shim, not in the plugin")
        sb = (hosting or {}).get("sandbox") or {}
        if sb and not sb.get("network", True):
            gap("high", "its network cannot be contained on this machine",
                sb.get("network_note") or "", "install bwrap, or build it natively")
        if sb and not sb.get("filesystem", True):
            gap("high", "its filesystem access cannot be contained here",
                sb.get("filesystem_note") or "", "upgrade Node, or build it natively")

    # Declared things with no equivalent, hosted or not.
    for key, present in (
        ("contracts.trustedToolPolicies", _nonempty(c.get("trustedToolPolicies"))),
        ("contracts.agentToolResultMiddleware", _nonempty(c.get("agentToolResultMiddleware"))),
        ("providers", _nonempty(m.get("providers"))),
        ("channels", _nonempty(m.get("channels"))),
    ):
        if present:
            row = BY_SOURCE[key]
            gap("medium", f"it wants {row['what']}", row["how"],
                "not portable — leave it out, or reconsider the plugin")
    kinds = m.get("kind")
    kinds = [kinds] if isinstance(kinds, str) else list(kinds or [])
    if any(k in ("memory", "context-engine") for k in kinds):
        row = BY_SOURCE["kind: memory | context-engine"]
        gap("medium", f"it wants {row['what']}", row["how"], "not portable")

    port = portable(m)
    sev = {g["severity"] for g in gaps}
    verdict = "partial" if "high" in sev else ("caveats" if sev else "clean")
    return {
        "gaps": gaps, "verdict": verdict, "portable": port,
        "headline": _headline(verdict, gaps, port),
    }


def _headline(verdict: str, gaps: list[dict], port: dict) -> str:
    if verdict == "clean":
        return "Nothing about this plugin is a problem on this machine."
    n = len(gaps)
    carried = sum(len(v) for v in port.values())
    tail = (f" AgentOS could rebuild {carried} of the things it declares out of its own "
            f"parts instead." if carried else "")
    return (f"{n} thing{'s' if n != 1 else ''} about this plugin "
            f"{'will not work' if verdict == 'partial' else 'need care'} here.{tail}")


# ---------------------------------------------------------------------------
# The brief: what the agent is asked to build, derived from the manifest
# ---------------------------------------------------------------------------

def portable(manifest: dict) -> dict:
    """What of this plugin CAN be carried, grouped by the Bento primitive."""
    m = manifest or {}
    c = _contracts(m)
    mcp = m.get("mcpServers") if isinstance(m.get("mcpServers"), dict) else {}
    hooks = list((m.get("activation") or {}).get("onHooks") or []) \
        if isinstance(m.get("activation"), dict) else []
    # A hook that wanted to sit INSIDE a turn has no equivalent here, so it is not
    # portable and must not become a checkable item — a brief that asked for a
    # flow named `llm_output` would fail its own acceptance test forever, which is
    # how a verification step stops being believed.
    from .ocplugins import CONVERSATION_HOOKS
    return {
        "mcp": sorted(mcp),
        "tools": [str(t) for t in _nonempty(c.get("tools"))],
        "commands": [str(x.get("name") if isinstance(x, dict) else x)
                     for x in _nonempty(m.get("cliCommands"))],
        "events": [str(h) for h in hooks if h not in CONVERSATION_HOOKS],
        "in_turn_hooks": [str(h) for h in hooks if h in CONVERSATION_HOOKS],
    }


def brief(pid: str, manifest: dict, source: str = "") -> dict:
    """The build specification handed to the agent. Pure, and derived only.

    Every field traces to something the plugin actually declared. A manifest that
    declares nothing produces a brief that says so — guessing what a plugin called
    'voice-call' probably does would produce a plausible implementation of
    something nobody asked for, and nothing downstream could tell the difference.
    """
    m = manifest or {}
    port = portable(m)
    steps: list[dict] = []

    if port["mcp"]:
        steps.append({
            "target": "mcp", "items": port["mcp"],
            "do": (f"The plugin contributes {len(port['mcp'])} MCP server(s): "
                   f"{', '.join(port['mcp'])}. These port across unchanged — add them "
                   f"to AgentOS's own MCP config, where their tools are already gated "
                   f"per call. Copy the command/args from the plugin's manifest; never "
                   f"copy a secret, ask for it."),
            "verify": "the server connects and its tools appear in the agent's tool list",
        })
    if port["tools"]:
        steps.append({
            "target": "mcp", "items": port["tools"],
            "do": (f"It provides these tools: {', '.join(port['tools'])}. Where an MCP "
                   f"server above already offers one, that is done. For any that remain, "
                   f"provide the same capability the honest Bento way — an MCP server if "
                   f"one exists for this job, otherwise a flow whose mission does it. Do "
                   f"NOT invent behaviour: if the manifest does not say what a tool does, "
                   f"say so and ask."),
            "verify": "each named capability is reachable as a tool or a runnable flow",
        })
    if port["commands"] or port["events"]:
        # The ITEMS are the flows to create — named after the commands, or after the
        # plugin when it only has events. The events are how those flows START, and
        # are carried as trigger intent rather than as things to look up by name.
        flows = port["commands"] or [pid]
        steps.append({
            "target": "flow", "items": flows,
            "triggers": port["events"],
            "do": (f"Write {'a flow' if len(flows) == 1 else 'flows'} named "
                   f"{', '.join(flows)} with a clear mission"
                   + (f", started by {', '.join(port['events'])} — use the matching "
                      f"AgentOS trigger (cron / message / webhook / os_event) only where the "
                      f"event is genuinely event-driven." if port["events"] else ".")),
            "verify": "the flow exists, is disabled, and every trigger can fire on this machine",
        })
    schema = m.get("configSchema") if isinstance(m.get("configSchema"), dict) else {}
    if (schema.get("properties") or {}):
        steps.append({
            "target": "config", "items": sorted(schema["properties"]),
            "do": (f"It needs settings: {', '.join(sorted(schema['properties']))}. Ask the "
                   f"user for each one before building anything that depends on it. Never "
                   f"invent a credential or a default for a secret."),
            "verify": "nothing was assumed — each setting was asked for or is absent by choice",
        })

    unportable = [g for g in compatibility(m)["gaps"] if g["severity"] == "medium"]
    if port["in_turn_hooks"]:
        # Dropped from the buildable steps above, so it MUST surface here. A
        # capability that silently vanishes between the plugin and the port is the
        # same failure the compatibility shim's `discrepancy()` exists to catch.
        unportable.append({
            "what": f"it wants to run inside the turn ({', '.join(port['in_turn_hooks'])})",
            "why": "AgentOS has no hook point inside a turn for third-party code to sit in, "
                   "so there is nothing to port this onto — a flow trigger fires around a "
                   "turn, not within one",
        })
    return {
        "plugin": pid,
        "source": source,
        "goal": (str(m.get("description") or "").strip()
                 or f"provide, natively, what the '{pid}' OpenClaw plugin provides"),
        "declared": port,
        "steps": steps,
        "not_portable": [{"what": g["what"], "why": g["why"]} for g in unportable],
        "rules": [
            "Build ONLY what the manifest declares. If it does not say, ask — do not guess.",
            "Everything you create lands DISABLED. Enabling is the user's decision.",
            "Use this OS's primitives: MCP for tools, a flow for standing work, a skill "
            "for know-how. Do not shell out to `openclaw`.",
            "Never copy a secret out of a manifest or a config file. Ask for it.",
            "When you are done, verify it and report honestly what does and does not work.",
        ],
        "buildable": bool(steps),
    }


def brief_prompt(b: dict) -> str:
    """The brief as the message that starts the build turn.

    Text rather than a tool schema because the builder is the ordinary agent using
    the ordinary tools (`create_flow`, `add_mcp_server`, `save_skill`) — a second
    build path would be a second set of bugs, which is the argument `jobs.py`
    makes about not having a job engine.
    """
    if not b.get("buildable"):
        return (f"The '{b['plugin']}' plugin's manifest declares nothing that can be "
                f"rebuilt from it. Tell the user that, and that they would need to say "
                f"what they want it to do before anything can be built.")
    lines = [
        f"Rebuild the capability of the OpenClaw plugin '{b['plugin']}' using this OS's "
        f"own parts, so it runs behind the permission engine instead of beside it.",
        "", f"What it is for: {b['goal']}", "", "Build this:",
    ]
    for i, s in enumerate(b["steps"], 1):
        lines.append(f"  {i}. [{s['target']}] {s['do']}")
    if b["not_portable"]:
        lines += ["", "Do NOT try to reproduce these — tell the user they are out of scope:"]
        lines += [f"  · {g['what']} — {g['why']}" for g in b["not_portable"]]
    lines += ["", "Rules:"] + [f"  · {r}" for r in b["rules"]]
    lines += ["", "Then verify what you built and report, item by item, what works and "
                  "what does not. Do not report success for anything you did not check."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The acceptance test: did the build deliver the brief?
# ---------------------------------------------------------------------------

def verify(brief_doc: dict, store, cfg: dict, mcp=None) -> dict:
    """Check what exists against what the brief asked for, item by item.

    Built and checked from ONE document, which is what stops "done" meaning "the
    agent said done". The checks are deliberately about REACHABILITY rather than
    behaviour: this can prove a flow exists and an MCP tool is offered, and it
    cannot prove the tool does the right thing — so it says which it checked.
    """
    results: list[dict] = []

    flows = {f["name"].lower() for f in (store.list_flows() or [])}
    skills = {s["name"].lower() for s in (store.list_skills() or [])}
    servers = set((cfg or {}).get("mcp_servers") or {})
    live_tools = set()
    if mcp is not None:
        try:
            live_tools = {t["name"] for t in mcp.tool_schemas()}
        except Exception:                                          # noqa: BLE001
            pass

    def add(target, item, ok, note):
        results.append({"target": target, "item": item, "ok": bool(ok), "note": note})

    for step in brief_doc.get("steps") or []:
        t = step.get("target")
        for item in step.get("items") or []:
            key = str(item).lower()
            if t == "mcp":
                if key in {s.lower() for s in servers}:
                    hit = [n for n in live_tools if n.lower().startswith(f"mcp_{key}")]
                    add(t, item, True,
                        f"configured as an MCP server; {len(hit)} tool(s) live"
                        if hit else "configured, but no tools are live yet — is it connected?")
                elif any(key in n.lower() for n in live_tools):
                    add(t, item, True, "reachable as an MCP tool")
                elif key in flows:
                    add(t, item, True, "provided by a flow of the same name")
                else:
                    add(t, item, False, "nothing here provides this yet")
            elif t == "flow":
                add(t, item, key in flows,
                    "a flow of this name exists" if key in flows else "no flow of this name")
            elif t == "skill":
                add(t, item, key in skills,
                    "saved as a skill" if key in skills else "no skill of this name")
            elif t == "config":
                # Deliberately NOT a pass/fail on presence: a setting the user chose
                # not to give is a decision, not a defect, and failing it would push
                # the agent to invent one — the exact thing the brief forbids.
                add(t, item, True, "asked for at build time; not checked here on purpose")

    checked = [r for r in results if r["target"] != "config"]
    passed = [r for r in checked if r["ok"]]
    return {
        "results": results,
        "passed": len(passed), "checked": len(checked),
        "ok": bool(checked) and len(passed) == len(checked),
        "note": ("this checks that each thing is REACHABLE — that a flow exists, that an "
                 "MCP tool is offered. It does not prove the tool does the right thing; "
                 "run it once and look."),
    }


def report(pid: str, brief_doc: dict, verification: dict, lic: dict,
           compat: dict | None = None) -> dict:
    """The report: what came across, what did not, and what to do next.

    This is the document somebody moving off OpenClaw actually needs, and the
    reason it is one function rather than three surfaces each summarising: a move
    where the desktop and the terminal disagree about what got carried is one
    nobody can sign off.

    ONE name for one thing. `bento openclaw report`, `openclaw_report` and the
    GUI's Report button all print this — calling it something else on any surface
    would be a second name for a document people have to compare across
    machines.

    It ends in a PROPOSAL rather than a result. Three answers, and the middle one
    is why this exists — a gap is not a verdict, it is a thing somebody can decide
    to have built.
    """
    v, b = verification or {}, brief_doc or {}
    ported = [{"target": r["target"], "item": r["item"], "note": r["note"]}
              for r in v.get("results", []) if r["ok"] and r["target"] != "config"]
    outstanding = [{"target": r["target"], "item": r["item"], "note": r["note"]}
                   for r in v.get("results", []) if not r["ok"]]

    # What could never be carried, each with what LOSING it actually costs. A list
    # of names with no consequence attached is a list people skim.
    not_portable = []
    for g in b.get("not_portable") or []:
        not_portable.append({"what": g["what"], "why": g["why"],
                             "implication": _implication(g["what"])})

    lp = licence_position(lic, "port")
    done = bool(ported) and not outstanding
    return {
        "plugin": pid,
        "licence": lp,
        "ported": ported,
        "outstanding": outstanding,
        "not_portable": not_portable,
        "complete": done,
        "headline": _report_headline(pid, ported, outstanding, not_portable),
        # The proposal. `continue_as_is` is always available because a partial
        # port that covers what somebody actually uses is a fine place to stop.
        "proposal": {
            "build_the_rest": bool(outstanding),
            "continue_as_is": True,
            "keep_the_plugin": bool(not_portable) or bool(outstanding),
        },
    }


#: What losing an unportable concept COSTS, in the user's terms. Keyed on the
#: leading words of the `what` sentence rather than an id, because these come
#: from `compatibility()` and one table of prose beats two ids to keep in step.
_IMPLICATIONS = (
    ("host-trusted pre-tool policies",
     "any budget or guardrail rule it enforced is gone — write it as a grant or a "
     "deny policy in Permissions instead, where it is enforced for everything, not "
     "just for this plugin"),
    ("rewriting tool results",
     "anything it did to tool output before the model saw it no longer happens; if "
     "that was formatting or redaction, it has to move into the tool itself"),
    ("model providers",
     "the models it offered are not available under this name — add the provider in "
     "Settings → AI providers, where AgentOS manages its keys and its budget"),
    ("messaging channels",
     "conversations will not arrive over that channel. AgentOS carries Telegram and "
     "WhatsApp itself; anything else is not reachable this way"),
    ("memory or the context engine",
     "it no longer decides what is remembered. AgentOS's own memory and spaces take "
     "that over, which is what makes memory visible in the Memory app and scoped by "
     "space"),
    ("inside the turn",
     "it cannot see or alter a turn as it happens. Work that has to react to a "
     "conversation must become a flow that runs around the turn instead of within it"),
)


def _implication(what: str) -> str:
    low = (what or "").lower()
    for needle, says in _IMPLICATIONS:
        if needle in low:
            return says
    return "this capability has no equivalent here and is simply not carried across"


def _report_headline(pid, ported, outstanding, not_portable) -> str:
    if not ported and not outstanding:
        return f"Nothing of '{pid}' has been rebuilt yet."
    bits = [f"{len(ported)} of {len(ported) + len(outstanding)} part(s) of '{pid}' "
            f"are in place"]
    if outstanding:
        bits.append(f"{len(outstanding)} still to build")
    if not_portable:
        bits.append(f"{len(not_portable)} cannot be carried at all")
    return " · ".join(bits) + "."


def report_text(r: dict) -> str:
    """The report as it reads in a terminal. Same content as the GUI's, one source."""
    out = [f"Report — {r['plugin']}", "=" * (9 + len(r["plugin"])), "",
           r["headline"], "",
           f"  {r['licence']['headline']}", f"  {r['licence']['implication']}", ""]
    if r["ported"]:
        out.append("Ported and reachable:")
        out += [f"  ✓ [{p['target']:5}] {p['item']} — {p['note']}" for p in r["ported"]]
        out.append("")
    if r["outstanding"]:
        out.append("Declared, not built yet:")
        out += [f"  ✗ [{o['target']:5}] {o['item']} — {o['note']}" for o in r["outstanding"]]
        out.append("")
    if r["not_portable"]:
        out.append("Cannot be carried across, and what that costs:")
        for g in r["not_portable"]:
            out += [f"  · {g['what']}", f"      why:  {g['why']}",
                    f"      cost: {g['implication']}"]
        out.append("")
    out.append("What would you like to do?")
    if r["proposal"]["build_the_rest"]:
        out.append(f"  · have the agent build the rest   "
                   f"bento openclaw native {r['plugin']} --yes")
    out.append("  · continue as it is — a partial port that covers what you use is "
               "a fine place to stop")
    if r["proposal"]["keep_the_plugin"]:
        out.append(f"  · keep running the original alongside it   "
                   f"bento openclaw enable {r['plugin']} --yes")
    return "\n".join(out)


def verdict_line(v: dict) -> str:
    """One sentence for a terminal or a toast."""
    if not v.get("checked"):
        return "nothing to check — the build produced no reachable parts"
    if v["ok"]:
        return f"all {v['checked']} part(s) of the brief are in place ({v['note']})"
    missing = [r["item"] for r in v["results"] if not r["ok"]]
    return (f"{v['passed']} of {v['checked']} part(s) in place — still missing: "
            f"{', '.join(str(m) for m in missing)}")
