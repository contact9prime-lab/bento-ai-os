"""The agent kernel: plan -> act (tools) -> observe -> respond, with approval gates."""

import time
from typing import Awaitable, Callable

from . import config as cfgmod
from . import providers
from .policy import MAIN, Principal
from .tools import Toolbox

SYSTEM_PROMPT = """You are {name}, the resident agent of AgentOS — an agentic operating system running locally on the user's Linux machine.
You don't just answer — you *do things*, using your tools: run shell commands, read/write files,
browse the web, open apps, send notifications, save memories, and schedule background tasks.

Current time: {now}
Workspace directory: {workspace}
{sandbox}

Guidelines:
- FINISH THE JOB. Keep taking actions until the deliverable actually exists — do not stop after a single
  search or step. A research/analysis task is only done when you have gathered the data AND produced the
  output: for a report, call `save_report` (it writes an HTML file to the workspace 'reports' folder that
  the user can open in the File Manager / Browser, and can ship a summary to Telegram). Never end a turn
  having only searched — always turn findings into the concrete result the user asked for.
- Choose the right shape for what's asked: a one-off result → do it now and save_report; a recurring need
  ("every day…", "each morning…") → schedule_task (a headless JOB that runs on its own and should end by
  writing a report and/or telegram_send); an interactive tool the user will click → create_app (UI).
- Prefer acting over describing. If the user asks for something the machine can do, use tools and report the real result.
- Chain tools as needed; check results and adapt. Don't claim something worked without seeing its output.
- Some actions require the user's approval; if an action is denied, respect that and adjust.
- Build your understanding over time: `remember` durable facts (scope="user") or facts that only
  matter for this conversation (scope="session"), `kg_add` structured relations (people, projects,
  tools and how they connect), `kg_query`/`recall` when past context might help, `forget` when the
  user corrects or retracts something, and `update_soul` when you learn something that should
  change how you behave. A background process also learns from every turn automatically — the
  sections below reflect everything known so far; trust them as real context about this user.
- Tools named mcp_* come from connected MCP servers (external capabilities). When a task touches a
  connected server's domain — GitHub work → mcp_github_*, web research → the connected search server,
  Notion/Slack/Linear/databases likewise — reach for those tools FIRST instead of approximating with
  shell commands or generic fetches; they are authenticated and purpose-built. If a capability is
  missing, you can connect a well-known server yourself with `add_mcp_server` (the user approves it
  and supplies any API key).
- Skills are proven procedures. Before starting a task that matches an installed skill's description,
  load it with `use_skill(name)` and follow it — don't improvise a workflow a skill already encodes.
- You lead a team: `delegate(subagent, task)` hands a focused subtask to a specialist (each has
  its own model, tools, and budget), and `run_workflow(workflow, input)` runs a multi-step
  pipeline (e.g. draft on a local model, validate on a stronger one). Delegate when a subtask is
  self-contained, needs a different model's judgement, or can run while you do something else.
- You can reconfigure AgentOS itself with `configure_agentos` (autonomy, model, policies, MCP servers,
  Telegram, your own name) when the user asks for settings changes — no need to send them to Settings.
- You can build UI tools INTO this OS with `create_app` (self-contained HTML/CSS/JS rendered in a
  desktop window; it may call the AgentOS REST API). Use it when the user wants a new tool, widget,
  or dashboard — you are allowed and encouraged to improve your own OS.
- Be concise and concrete. Show real output, not guesses.

=== Your soul (persistent identity — written by you and your user) ===
{soul}
=== end soul ===
{memories}"""

# Emitted event types (mirrored to the UI):
#   text_delta, thinking_delta, tool_start, tool_end, approval_request (via approver), turn_end, error


class Agent:
    def __init__(self, cfg: dict, toolbox: Toolbox, model_id: str,
                 emit: Callable[[dict], Awaitable[None]],
                 approver: Callable[[str, dict, str], Awaitable[bool]],
                 extra_system: str = "", tool_filter: list | None = None,
                 conversation_id: str = "", principal: Principal = MAIN):
        """
        emit(event)                        -- streams events to the UI
        approver(name, args, reason, offer=None) -> ok
                                           -- asks the user to approve a gated tool call;
                                              `offer` is a ready-to-write grant for "allow & remember"
        extra_system                       -- appended to the system prompt (personas, e.g. App Builder)
        tool_filter                        -- if set, restrict tools to these names (keeps weak models focused)
        conversation_id                    -- enables session memory (injection + scope="session" saves)
        principal                          -- WHO this agent acts as (policy.MAIN = the user's own agent;
                                              subagents/apps get their own identity for the permission gate)
        """
        self.cfg = cfg
        self.toolbox = toolbox
        self.model_id = model_id
        self.emit = emit
        self.approver = approver
        self.extra_system = extra_system
        self.tool_filter = tool_filter
        self.conversation_id = conversation_id
        self.principal = principal
        self.aborted = False

    def _tools(self) -> list:
        schemas = self.toolbox.schemas()
        if self.tool_filter is not None:
            keep = set(self.tool_filter)
            schemas = [t for t in schemas if t["name"] in keep]
        if self.toolbox.pdp and self.principal.kind in ("app", "subagent", "workflow"):
            # hide tools this principal can never use (built-in denies / deny grants) —
            # the model shouldn't even see them; ask-able tools stay visible
            schemas = [t for t in schemas
                       if self.toolbox.pdp.decide_tool(self.principal, t["name"], {},
                                                       "safe").effect != "deny"]
        return schemas

    async def _system(self, query: str = "") -> str:
        store = self.toolbox.store
        mc = self.cfg.get("memory") or {}
        mem_text = ""
        n_user = int(mc.get("inject_user", 15))
        user_mems = store.search_memories("", limit=500, scope="user")
        if len(user_mems) > n_user:
            # over budget: pinned always make the cut; the rest of the slots go to the
            # memories most relevant to the user's message (semantic), else most recent
            pinned = [m for m in user_mems if m.get("pinned")]
            rest = [m for m in user_mems if not m.get("pinned")]
            take = max(0, n_user - len(pinned))
            picked = rest[:take]
            if query and take > 0:
                try:
                    from . import knowledge
                    ranked = await knowledge.semantic_rank(self.cfg, rest, query)
                    if ranked is not None:
                        picked = ranked[:take]
                except Exception:
                    pass
            user_mems = pinned + picked
        if user_mems:
            mem_text += "\n=== User memory (durable facts about your user & machine) ===\n" + "\n".join(
                f"- {'📌 ' if m.get('pinned') else ''}{m['content']}" for m in user_mems) + \
                "\n=== end user memory ===\n"
        if self.conversation_id:
            sess_mems = store.search_memories("", limit=int(mc.get("inject_session", 10)),
                                              scope="session", conversation_id=self.conversation_id)
            if sess_mems:
                mem_text += "\n=== Session memory (context of THIS conversation) ===\n" + "\n".join(
                    f"- {m['content']}" for m in sess_mems) + "\n=== end session memory ===\n"
        n_facts = int(mc.get("inject_facts", 12))
        if n_facts > 0:
            facts = store.kg_query("", limit=10**6)
            if facts:
                mem_text += ("\n=== Knowledge graph highlights (query more with kg_query) ===\n"
                             + "\n".join(f"- {f}" for f in facts[-n_facts:])
                             + "\n=== end knowledge graph ===\n")
        skills = self.toolbox.store.list_skills()
        if skills:
            mem_text += ("\n\nSkills — proven procedures. Load one with `use_skill(name)` BEFORE starting "
                         "a task that matches its description, and follow it:\n" + "\n".join(
                f"- {s['name']}: {s['description'] or '(no description)'}" for s in skills[:30]))
        if self.toolbox.mcp:
            conn = [s for s in self.toolbox.mcp.status() if s["status"] == "connected"]
            if conn:
                lines = []
                for s in conn:
                    lines.append(f"- {s['name']} ({len(s['tools'])} tools):")
                    for t in s["tools"][:12]:
                        desc = (t["description"] or "").split("\n")[0][:110]
                        lines.append(f"    · {t['name']}" + (f" — {desc}" if desc else ""))
                    if len(s["tools"]) > 12:
                        lines.append(f"    · … {len(s['tools']) - 12} more (all available as native tools)")
                    if s.get("instructions"):
                        lines.append(f"    usage notes: {s['instructions'][:400]}")
                mem_text += ("\n\nConnected MCP servers — prefer their tools (mcp_<server>_<tool>) whenever "
                             "a task touches their domain:\n" + "\n".join(lines))
        from .tools import sandbox_conf
        sb_on, sb_root = sandbox_conf(self.cfg)
        sb_text = (f"SANDBOX: you are confined to {sb_root} — commands run jailed there, the rest of the "
                   f"filesystem is read-only and other home files are hidden. Work inside that folder."
                   if sb_on else "")
        base = SYSTEM_PROMPT.format(
            name=self.cfg.get("agent_name") or "Aria",
            now=time.strftime("%A %Y-%m-%d %H:%M %Z"),
            workspace=self.cfg["workspace"],
            sandbox=sb_text,
            soul=cfgmod.load_soul()[:4000],
            memories=mem_text,
        )
        return (base + "\n\n" + self.extra_system) if self.extra_system else base

    async def run(self, history: list[dict]) -> dict:
        """history: prior messages (user/assistant, internal format), last one the new user msg.
        Returns {'content': final_text, 'steps': [...]} — steps are the tool trace for persistence."""
        last_user = next((m.get("content", "") for m in reversed(history)
                          if m.get("role") == "user"), "")
        steps: list[dict] = []
        final_text = ""
        tokens = {"input": 0, "output": 0}
        if self.toolbox.pdp:
            mdec = self.toolbox.pdp.decide(self.principal, "model.use",
                                           f"model:{self.model_id}",
                                           {"autonomy": self.cfg.get("autonomy", "")})
            if mdec.effect == "deny":
                msg = (f"[denied] {self.principal.label} may not use model "
                       f"{self.model_id} — {mdec.reason or 'denied by a grant rule'}")
                await self.emit({"type": "error", "message": msg})
                return {"content": msg, "steps": [{"type": "error", "message": msg}],
                        "tokens": tokens}
        messages = [{"role": "system", "content": await self._system(last_user)}] + history

        for _ in range(int(self.cfg.get("max_steps", 25))):
            if self.aborted:
                break
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            try:
                async for ev in providers.chat(self.cfg, self.model_id, messages, self._tools()):
                    if self.aborted:
                        break
                    if ev["type"] == "text":
                        text_parts.append(ev["text"])
                        await self.emit({"type": "text_delta", "text": ev["text"]})
                    elif ev["type"] == "thinking":
                        await self.emit({"type": "thinking_delta", "text": ev["text"]})
                    elif ev["type"] == "tool_call":
                        tool_calls.append(ev)
                    elif ev["type"] == "usage":
                        tokens["input"] += ev.get("input", 0) or 0
                        tokens["output"] += ev.get("output", 0) or 0
            except providers.ProviderError as e:
                await self.emit({"type": "error", "message": str(e)})
                steps.append({"type": "error", "message": str(e)})
                break

            text = "".join(text_parts)
            if text:
                final_text = text
                steps.append({"type": "text", "text": text})

            if not tool_calls or self.aborted:
                break

            messages.append({
                "role": "assistant",
                "content": text,
                "tool_calls": [{"id": t["id"], "name": t["name"], "args": t["args"]} for t in tool_calls],
            })

            for tc in tool_calls:
                if self.aborted:
                    break
                name, args, call_id = tc["name"], tc["args"], tc["id"]
                if name in ("remember", "delegate", "run_workflow") and self.conversation_id:
                    # session scope flows through: saves attach to this conversation and
                    # delegated subagents inherit its session memory
                    args = {**args, "conversation_id": self.conversation_id}
                level, reason = self.toolbox.risk_of(name, args)
                if self.toolbox.pdp:
                    dec = self.toolbox.pdp.decide_tool(
                        self.principal, name, args, level, reason=reason,
                        autonomy=self.cfg.get("autonomy", ""))
                else:  # no policy engine wired (tests / embedding): legacy autonomy gate
                    from .policy import Decision
                    if level == "blocked":
                        dec = Decision("deny", reason)
                    elif level == "risky" and self.cfg.get("autonomy") != "full":
                        dec = Decision("ask", reason)
                    else:
                        dec = Decision("allow")

                approved = None
                if dec.effect == "deny":
                    output = f"[denied] {dec.reason or reason}"
                elif dec.effect == "ask":
                    await self.emit({"type": "tool_start", "call_id": call_id, "name": name,
                                     "args": args, "pending_approval": True})
                    approved = await self.approver(name, args, dec.reason or reason,
                                                   dec.grant_offer)
                    if approved:
                        output = await self.toolbox.execute(name, args)
                    else:
                        output = ("[denied] This action was not approved for "
                                  f"{self.principal.label} at the current autonomy level. Try a "
                                  "read-only alternative, or tell the user what you wanted to do "
                                  "and why.")
                else:
                    await self.emit({"type": "tool_start", "call_id": call_id, "name": name,
                                     "args": args, "pending_approval": False})
                    output = await self.toolbox.execute(name, args)
                if dec.effect != "allow":  # every gate decision is auditable in Logs
                    self.toolbox.store.log(
                        "policy",
                        f"{dec.effect}: {self.principal.label} → {dec.action} {dec.resource}"[:400],
                        {"principal": self.principal.label, "action": dec.action,
                         "resource": dec.resource, "effect": dec.effect, "rule": dec.rule,
                         "reason": dec.reason or reason, "tool": name, "approved": approved})

                ok = not output.startswith(("[error]", "[denied]", "[exit code"))
                self.toolbox.store.log("tool", name, {"args": args, "ok": ok, "level": level,
                                                      "principal": self.principal.label,
                                                      "decision": dec.rule})
                await self.emit({"type": "tool_end", "call_id": call_id, "name": name,
                                 "output": output[:4000], "ok": ok})
                steps.append({"type": "tool", "name": name, "args": args,
                              "output": output[:4000], "ok": ok})
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "name": name, "content": output})
        else:
            note = "\n\n*(stopped: reached the max step limit)*"
            final_text += note
            await self.emit({"type": "text_delta", "text": note})

        return {"content": final_text, "steps": steps, "tokens": tokens}
