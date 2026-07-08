"""The agent kernel: plan -> act (tools) -> observe -> respond, with approval gates."""

import time
from typing import Awaitable, Callable

from . import config as cfgmod
from . import providers
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
- Build your understanding over time: `remember` durable facts, `kg_add` structured relations
  (people, projects, tools and how they connect), `kg_query`/`recall` when past context might help,
  and `update_soul` when you learn something that should change how you behave.
- Tools named mcp_* come from connected MCP servers (external capabilities); use them like any other tool.
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
                 extra_system: str = "", tool_filter: list | None = None):
        """
        emit(event)                        -- streams events to the UI
        approver(name, args, reason) -> ok -- asks the user to approve a risky tool call
        extra_system                       -- appended to the system prompt (personas, e.g. App Builder)
        tool_filter                        -- if set, restrict tools to these names (keeps weak models focused)
        """
        self.cfg = cfg
        self.toolbox = toolbox
        self.model_id = model_id
        self.emit = emit
        self.approver = approver
        self.extra_system = extra_system
        self.tool_filter = tool_filter
        self.aborted = False

    def _tools(self) -> list:
        schemas = self.toolbox.schemas()
        if self.tool_filter is not None:
            keep = set(self.tool_filter)
            schemas = [t for t in schemas if t["name"] in keep]
        return schemas

    def _system(self) -> str:
        mems = self.toolbox.store.search_memories("", limit=10)
        mem_text = ""
        if mems:
            mem_text = "\nThings you remember about this user/machine:\n" + "\n".join(
                f"- {m['content']}" for m in mems)
        skills = self.toolbox.store.list_skills()
        if skills:
            mem_text += "\n\nSkills you can load with `use_skill(name)` when relevant:\n" + "\n".join(
                f"- {s['name']}: {s['description'] or '(no description)'}" for s in skills[:30])
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
        messages = [{"role": "system", "content": self._system()}] + history
        steps: list[dict] = []
        final_text = ""
        tokens = {"input": 0, "output": 0}

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
                level, reason = self.toolbox.risk_of(name, args)

                if level == "blocked":
                    output = f"[denied] {reason}"
                elif level == "risky" and self.cfg.get("autonomy") != "full":
                    await self.emit({"type": "tool_start", "call_id": call_id, "name": name,
                                     "args": args, "pending_approval": True})
                    approved = await self.approver(name, args, reason)
                    if approved:
                        output = await self.toolbox.execute(name, args)
                    else:
                        output = ("[denied] This risky action was not approved at the current "
                                  "autonomy level. Try a read-only alternative, or tell the user "
                                  "what you wanted to do and why.")
                else:
                    await self.emit({"type": "tool_start", "call_id": call_id, "name": name,
                                     "args": args, "pending_approval": False})
                    output = await self.toolbox.execute(name, args)

                ok = not output.startswith(("[error]", "[denied]", "[exit code"))
                self.toolbox.store.log("tool", name, {"args": args, "ok": ok, "level": level})
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
