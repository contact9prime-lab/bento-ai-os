"""The agent kernel: plan -> act (tools) -> observe -> respond, with approval gates."""

import asyncio
import base64
import contextlib
import json
import time
from pathlib import Path
from typing import Awaitable, Callable

from . import config as cfgmod
from . import providers
from .policy import MAIN, Principal
from .tools import ALWAYS_ASK, Toolbox

SYSTEM_PROMPT = """You are {name}, the resident agent of AgentOS — an agentic operating system running locally on the user's Linux machine.
You don't just answer — you *do things*, using your tools: run shell commands, read/write files,
browse the web, open apps, send notifications, save memories, and schedule background tasks.

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
- Ship what you build: the `git_*` tools version and publish work. Projects in the workspace can be
  git repos (git_init/git_commit as you go); `export_app_to_git` turns an app you built into a real
  project folder, and `git_push` (with create_github_repo) publishes to the user's GitHub using the
  token from Settings. Prefer these structured tools over raw `git` shell commands.
- Be concise and concrete. Show real output, not guesses.

=== Your soul (persistent identity — written by you and your user) ===
{soul}
=== end soul ===
{memories}

{machine}Current time: {now}"""
# NOTE: the timestamp deliberately sits at the very END of the system prompt — as the
# first line it changed every turn and busted the provider's prompt-prefix cache,
# forcing local models to re-evaluate the entire (large) prompt from scratch each turn.
# The machine-state line lives down here with it for the same reason: it is volatile.


# ---- Machine state for the system prompt ------------------------------------------
# A one-line live snapshot (focused window, battery, network, …) so the agent knows
# what it's standing on without a tool call. It must be CHEAP: a short-TTL cache, a
# hard time budget (slow probes are skipped, keeping the last snapshot), and every
# probe swallows its own errors. Full detail stays behind the desktop_state tool.

_MSTATE = {"at": 0.0, "text": ""}
_MSTATE_TTL = 5.0      # seconds a snapshot is reused
_MSTATE_BUDGET = 0.5   # seconds the gather may take before we give up


def _machine_state_gather(toolbox: Toolbox) -> str:
    from . import host
    parts: list[str] = []
    try:
        w = host.list_windows()
        if w.get("available") and w["windows"]:
            line = f"{len(w['windows'])} native windows open"
            foc = next((x for x in w["windows"] if x.get("focused")), None)
            if foc:
                line += f", focused: {foc.get('title', '')} ({foc.get('app', '')})"
            parts.append(line)
    except Exception:
        pass
    try:
        ws = host.workspaces()
        cur = next((x["name"] for x in ws.get("workspaces", []) if x.get("focused")), "")
        if cur:
            parts.append(f"workspace {cur}")
    except Exception:
        pass
    try:
        b = host.get_battery()
        if b.get("percent") is not None:
            parts.append(f"battery {b['percent']}%"
                         + (f" ({b['state']})" if b.get("state") else ""))
    except Exception:
        pass
    try:
        n = host.get_network()
        conns = n.get("connections") or []
        if conns:
            parts.append("online via " + ", ".join(c["name"] for c in conns[:2]))
        elif n and n.get("online") is False:
            parts.append("offline")
    except Exception:
        pass
    try:
        v = host.get_volume()
        if v.get("volume") is not None:
            parts.append(f"volume {v['volume']}%" + (" (muted)" if v.get("muted") else ""))
    except Exception:
        pass
    try:
        from .hostctl import brightness
        if (bl := brightness.backlights()):
            parts.append(f"brightness {bl[0]['percent']}%")
    except Exception:
        pass
    try:
        if toolbox.notifd is not None:
            st = toolbox.notifd.state()
            if st["unread"]:
                parts.append(f"{st['unread']} unread notifications"
                             + (" (DND on)" if st["dnd"] else ""))
            elif st["dnd"]:
                parts.append("DND on")
    except Exception:
        pass
    if not parts:
        return ""
    return ("=== Machine state (live — full detail via desktop_state) ===\n"
            + " · ".join(parts) + "\n=== end machine state ===\n\n")


async def _machine_state(toolbox: Toolbox) -> str:
    now = time.monotonic()
    if now - _MSTATE["at"] < _MSTATE_TTL:
        return _MSTATE["text"]
    _MSTATE["at"] = now      # claim the slot first: a slow probe must not rerun every turn
    try:
        _MSTATE["text"] = await asyncio.wait_for(
            asyncio.to_thread(_machine_state_gather, toolbox), timeout=_MSTATE_BUDGET)
    except Exception:
        pass                 # over budget / broken probe: keep the last snapshot
    return _MSTATE["text"]


# ---- Image tool-results (vision) --------------------------------------------------

def _image_result(output: str) -> tuple[str, str]:
    """A tool result carrying {"__image__": <path>} splits into (text fallback, path).
    The text goes into the tool message (what non-vision models see); the image is
    attached as a user image part — the same shape user-uploaded chat images use, so
    every provider path (Ollama/OpenAI/Anthropic) already renders it."""
    if '"__image__"' not in output:
        return output, ""
    try:
        d = json.loads(output)
        path = d.get("__image__") or ""
        if path:
            return d.get("text") or f"image saved to {path}", path
    except Exception:
        pass
    return output, ""


def _image_data_url(path: str, limit: int = 8_000_000) -> str:
    """File → data URL for the provider image parts; '' when unreadable or oversized."""
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > limit:
            return ""
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}.get(
                    p.suffix.lstrip(".").lower(), "image/png")
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    except Exception:
        return ""

# Emitted event types (mirrored to the UI):
#   text_delta, thinking_delta, tool_start, tool_end, approval_request (via approver), turn_end, error


class Agent:
    def __init__(self, cfg: dict, toolbox: Toolbox, model_id: str,
                 emit: Callable[[dict], Awaitable[None]],
                 approver: Callable[[str, dict, str], Awaitable[bool]],
                 extra_system: str = "", tool_filter: list | None = None,
                 conversation_id: str = "", principal: Principal = MAIN,
                 surface: str = "gui"):
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
        surface                            -- WHICH IO gate the turn arrived on (gui | tui | telegram |
                                              api | task) — surface-scoped grants only apply on their gates
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
        self.surface = surface
        self.aborted = False
        # live partial results: if this turn is force-cancelled (user stop, shutdown),
        # the caller can still persist whatever streamed so far
        self._text_buf: list[str] = []
        self._final_text = ""
        self.partial_steps: list[dict] = []

    @property
    def partial_text(self) -> str:
        return self._final_text or "".join(self._text_buf)

    def _gen_options(self) -> dict:
        # num_ctx must comfortably exceed the system prompt (memories + KG + skills +
        # MCP catalog + tool schemas can reach ~15k tokens) PLUS the reply
        opts = {
            "num_ctx": int(self.cfg.get("ollama_num_ctx", 24576)),
            "max_tokens": int(self.cfg.get("max_output_tokens", 16384)),
        }
        if self.cfg.get("ollama_think") is not None:
            opts["think"] = bool(self.cfg["ollama_think"])
        return opts

    async def _stream(self, messages: list):
        """providers.chat with a first-token watchdog. Local models can spend minutes
        loading / evaluating a large prompt while producing zero events — during that
        window this emits heartbeat `status` events (so the UI shows life, and abort
        stays responsive), and after `first_token_timeout` it fails loudly instead of
        leaving the user staring at dead air."""
        gen = providers.chat(self.cfg, self.model_id, messages, self._tools(),
                             options=self._gen_options())
        it = gen.__aiter__()
        timeout = float(self.cfg.get("first_token_timeout", 180))
        nxt = asyncio.ensure_future(it.__anext__())
        waited = 0.0
        try:
            while True:  # heartbeat until the first event lands
                done, _ = await asyncio.wait({nxt}, timeout=10)
                if done:
                    break
                waited += 10
                if self.aborted:
                    return
                await self.emit({"type": "status",
                                 "message": f"waiting for {self.model_id.split('/')[-1]} — "
                                            f"{int(waited)}s (loading model / evaluating prompt)"})
                if waited >= timeout:
                    raise providers.ProviderError(
                        f"no response from {self.model_id} after {int(waited)}s — the model may "
                        f"still be loading, out of memory, or the provider may be down. "
                        f"Check the Models app, or try a smaller/different model.")
            try:
                ev = nxt.result()
            except StopAsyncIteration:
                return
            if waited:
                await self.emit({"type": "status", "message": ""})  # clear the heartbeat line
            yield ev
            async for ev in it:
                yield ev
        finally:
            if not nxt.done():
                nxt.cancel()
            with contextlib.suppress(Exception):
                await gen.aclose()

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
            machine=await _machine_state(self.toolbox),
        )
        return (base + "\n\n" + self.extra_system) if self.extra_system else base

    async def run(self, history: list[dict]) -> dict:
        """history: prior messages (user/assistant, internal format), last one the new user msg.
        Returns {'content': final_text, 'steps': [...]} — steps are the tool trace for persistence."""
        last_user = next((m.get("content", "") for m in reversed(history)
                          if m.get("role") == "user"), "")
        steps: list[dict] = []
        self.partial_steps = steps  # same list object: mutations are visible to a canceller
        final_text = ""
        tokens = {"input": 0, "output": 0}
        carry = ""       # accumulated text across token-limit continuations
        cont_rounds = 0  # bounded: never chase a runaway continuation loop
        if self.toolbox.pdp:
            mdec = self.toolbox.pdp.decide(self.principal, "model.use",
                                           f"model:{self.model_id}",
                                           {"autonomy": self.cfg.get("autonomy", ""),
                                            "surface": self.surface})
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
            self._text_buf = text_parts  # live buffer for partial_text
            tool_calls: list[dict] = []
            finish_reason = ""
            try:
                async for ev in self._stream(messages):
                    if self.aborted:
                        break
                    if ev["type"] == "text":
                        text_parts.append(ev["text"])
                        await self.emit({"type": "text_delta", "text": ev["text"]})
                    elif ev["type"] == "thinking":
                        await self.emit({"type": "thinking_delta", "text": ev["text"]})
                    elif ev["type"] == "tool_call":
                        tool_calls.append(ev)
                    elif ev["type"] == "finish":
                        finish_reason = ev.get("reason", "")
                    elif ev["type"] == "usage":
                        tokens["input"] += ev.get("input", 0) or 0
                        tokens["output"] += ev.get("output", 0) or 0
            except providers.ProviderError as e:
                await self.emit({"type": "error", "message": str(e)})
                steps.append({"type": "error", "message": str(e)})
                break

            text = "".join(text_parts)

            # Zero progress at the token limit = the context window itself is full
            # (prompt ≈ num_ctx): continuing would loop forever. Fail loudly instead.
            if finish_reason == "length" and not tool_calls and not (text.strip() or carry):
                msg = ("the model hit its token limit before producing any output — it either "
                       "spent the whole budget in its thinking channel, or the prompt fills its "
                       "context window. Try again, disable thinking (`ollama_think: false`), "
                       "raise `ollama_num_ctx`, or pick a stronger model.")
                await self.emit({"type": "error", "message": msg})
                steps.append({"type": "error", "message": msg})
                break

            # Output was cut at the token limit mid-text: ask the model to continue
            # where it stopped instead of shipping a truncated answer. Bounded to 3
            # continuations; tool-call rounds are excluded (their recovery path is the
            # `_raw`-args error message the toolbox returns).
            if finish_reason == "length" and not tool_calls and not self.aborted and cont_rounds < 3:
                cont_rounds += 1
                carry += text
                await self.emit({"type": "status",
                                 "message": f"output hit the token limit — continuing (part {cont_rounds + 1})…"})
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content":
                                 "Your previous output was cut off at the token limit. Continue "
                                 "EXACTLY where you left off — no preamble, no repetition."})
                continue

            if carry:
                text = carry + text
                carry = ""
            if text:
                final_text = text
                self._final_text = text
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
                        autonomy=self.cfg.get("autonomy", ""), surface=self.surface)
                else:  # no policy engine wired (tests / embedding): legacy autonomy gate
                    from .policy import Decision
                    if level == "blocked":
                        dec = Decision("deny", reason)
                    elif level == "risky" and self.cfg.get("autonomy") != "full":
                        dec = Decision("ask", reason)
                    else:
                        dec = Decision("allow")
                if name in ALWAYS_ASK and dec.effect == "allow" and dec.rule in ("default", ""):
                    # power/session actions confirm EVERY time — full autonomy included;
                    # only an explicit user-written grant (rule != default) skips the ask
                    dec.effect = "ask"

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
                         "reason": dec.reason or reason, "tool": name, "approved": approved,
                         "surface": self.surface})
                if dec.rule == "io-gate":  # surface-blocked IO is an explicit error entry
                    self.toolbox.store.log(
                        "error", f"IO gate blocked {dec.action} {dec.resource} on "
                                 f"'{self.surface}'"[:400],
                        {"principal": self.principal.label, "surface": self.surface,
                         "rule": "io-gate"})

                output, image_path = _image_result(output)
                ok = not output.startswith(("[error]", "[denied]", "[exit code"))
                self.toolbox.store.log("tool", name, {"args": args, "ok": ok, "level": level,
                                                      "principal": self.principal.label,
                                                      "decision": dec.rule})
                await self.emit({"type": "tool_end", "call_id": call_id, "name": name,
                                 "output": output[:4000], "ok": ok,
                                 **({"image": image_path} if image_path else {})})
                steps.append({"type": "tool", "name": name, "args": args,
                              "output": output[:4000], "ok": ok})
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "name": name, "content": output})
                if image_path and (img := _image_data_url(image_path)):
                    # vision plumbing: the image rides a user message (providers turn
                    # `images` into real image parts); text-only models still have the
                    # saved path in the tool result above
                    messages.append({"role": "user",
                                     "content": f"(the image from {name}: {image_path})",
                                     "images": [img]})
        else:
            note = "\n\n*(stopped: reached the max step limit)*"
            final_text += note
            await self.emit({"type": "text_delta", "text": note})

        return {"content": final_text, "steps": steps, "tokens": tokens}
