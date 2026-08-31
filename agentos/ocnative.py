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


def verdict_line(v: dict) -> str:
    """One sentence for a terminal or a toast."""
    if not v.get("checked"):
        return "nothing to check — the build produced no reachable parts"
    if v["ok"]:
        return f"all {v['checked']} part(s) of the brief are in place ({v['note']})"
    missing = [r["item"] for r in v["results"] if not r["ok"]]
    return (f"{v['passed']} of {v['checked']} part(s) in place — still missing: "
            f"{', '.join(str(m) for m in missing)}")
