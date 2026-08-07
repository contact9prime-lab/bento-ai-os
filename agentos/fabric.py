"""The fabric control plane (L0: in-process subagents & workflows).

Control plane vs data plane:
  - The CONTROL PLANE is this module + the server UI/API: it owns subagent and workflow
    definitions, resolves which model each data plane actually gets ("smartness" flows
    down, never up), starts/cancels runs, and collects telemetry.
  - A DATA PLANE is one executing subagent. Even at L0 (same process) each run gets a
    sidecar heartbeat task and a private event channel, so the contract is already the
    two-way one that L1–L3 will speak over mTLS:
        control → data : start, cancel, budgets, resolved model
        data → control : heartbeats, step events, logs, faults, usage
  - Model access belongs to the control plane. A subagent never holds provider keys; it
    asks for a model id and the control plane resolves it against its own provider
    config (step override → subagent model → default_model). That is what lets one
    workflow generate on Ollama and validate on Claude — or run everything on the same
    LLM — without the subagents knowing anything about providers.

Telemetry (faults / performance / logs) is recorded per run in fabric_runs/fabric_events,
which is the same place the Observability tab reads for the main agent (L0 "current
setup") via the existing turn/error logs.
"""

import asyncio
import time

from .agent import Agent, fence
from .policy import Principal

_AUTONOMY_ORDER = {"paranoid": 0, "balanced": 1, "full": 2}

# a subagent with an empty tools list gets this read-only set
SAFE_TOOLS = ["fetch_url", "read_file", "list_dir", "recall", "kg_query", "system_info"]

HEARTBEAT_SECS = 5          # sidecar beat + UI broadcast cadence
HEARTBEAT_PERSIST_EVERY = 6  # persist 1 of every N beats (avoid write spam)

# What the master orchestrator is allowed to hold itself (see _master_tools). It plans
# and aggregates; the roster acts. An orchestrator with hands does the work itself and
# the roster never runs.
MASTER_READONLY = ["recall", "kg_query"]
CONTEXT_BUDGET = 24_000     # chars of handle content handed to one child
BOARD_BUDGET = 1_200        # chars of board index appended to every tool result


def min_autonomy(a: str, b: str) -> str:
    order = sorted([a or "balanced", b or "balanced"], key=lambda x: _AUTONOMY_ORDER.get(x, 1))
    return order[0]


class Budget:
    """`max_seconds` is time spent WORKING, not wall clock.

    A run waiting for you to tap Allow is not burning its budget. The plain
    `asyncio.wait_for` this replaces could not tell the difference, which made asking a
    human a reliable way to kill a run: it would die at 300s having done 20s of work.
    """

    def __init__(self, limit: float):
        self.limit = float(limit)
        self.started = time.time()
        self.paused_total = 0.0
        self._paused_at = None

    def pause(self):
        if self._paused_at is None:
            self._paused_at = time.time()

    def resume(self):
        if self._paused_at is not None:
            self.paused_total += time.time() - self._paused_at
            self._paused_at = None

    def elapsed(self) -> float:
        held = self.paused_total + (time.time() - self._paused_at if self._paused_at else 0.0)
        return time.time() - self.started - held

    def remaining(self) -> float:
        return max(0.0, self.limit - self.elapsed())


async def _watchdog(agent, budget: Budget):
    """Stop a run that has spent its working budget. Cooperative: `aborted` is honoured
    at the agent's step boundaries, which is where stopping is safe."""
    while budget.elapsed() <= budget.limit:
        await asyncio.sleep(1)
    agent.aborted = True


class _RunToolbox:
    """The tool surface of exactly one flow run.

    Everything passes through to the real Toolbox except the run-scoped tools, which
    close over this run. That is deliberate and not merely tidy: a global
    `delegate(run_id=…, handle=…)` would take the run id as an argument, and an argument
    is something a model can invent. Closing over it means one flow reading another
    flow's blackboard is not a bug that can be written — it is a call that does not
    exist. It also keeps these four out of `/api/tools`, `TOOL_SCHEMAS` and the subagent
    wizard's tool picker, none of which should offer them.
    """

    def __init__(self, inner, extra_schemas: list, impls: dict, allow: list):
        self._inner = inner
        self._extra = extra_schemas
        self._impls = impls
        self._allow = set(allow)

    def __getattr__(self, k):           # store, pdp, mcp, telegram, fabric, …
        return getattr(self._inner, k)

    def schemas(self) -> list:
        return [t for t in self._inner.schemas() if t["name"] in self._allow] + self._extra

    def risk_of(self, name: str, args: dict):
        if name in self._impls:
            return "safe", ""           # the PDP still gates them: delegate → agent.invoke
        return self._inner.risk_of(name, args)

    async def execute(self, name: str, args: dict) -> str:
        if name in self._impls:
            return await self._impls[name](**{k: v for k, v in (args or {}).items()
                                              if not k.startswith("_")})
        return await self._inner.execute(name, args)


class ControlPlane:
    def __init__(self, cfg: dict, store, toolbox, broadcast=None):
        self.cfg = cfg
        self.store = store
        self.toolbox = toolbox
        self.broadcast = broadcast
        # run_id -> live instance {"agent", "hb_task", "last_beat", "ref", "started", "state"}
        self.instances: dict = {}
        # Injected in server startup so this module keeps no knowledge of Telegram or of
        # the UI — the same shape as `broadcast` above.
        #   approvals(run_id, tool, args, reason, offer, origin) -> awaitable bool
        #   deliver(flow, run, origin, text) -> awaitable list[str]   (sink kinds done)
        self.approvals = None
        self.deliver = None

    # -- hierarchy: the control plane decides how smart each data plane is ----

    def resolve_model(self, defn: dict, step_override: str = "") -> str:
        model = step_override or (defn.get("model") or "") or self.cfg.get("default_model", "")
        pdp = getattr(self.toolbox, "pdp", None)
        if pdp and defn.get("name"):
            # per-subagent model restrictions (deny grants on model.use); a denied
            # override falls back to the default model when that one is permitted
            sub = Principal("subagent", defn["name"])
            if pdp.decide(sub, "model.use", f"model:{model}").effect == "deny":
                fallback = self.cfg.get("default_model", "")
                if fallback and fallback != model and \
                        pdp.decide(sub, "model.use", f"model:{fallback}").effect != "deny":
                    return fallback
        return model

    # -- telemetry --------------------------------------------------------------

    async def _emit(self, run_id: str, etype: str, payload: dict, persist: bool = True):
        if persist:
            self.store.fabric_event(run_id, etype, payload)
        if self.broadcast:
            await self.broadcast({"type": "fabric_event", "run_id": run_id,
                                  "event": etype, **payload})

    async def _heartbeat_sidecar(self, run_id: str):
        """Data-plane sidecar: proves liveness to the control plane while a run executes."""
        beats = 0
        while run_id in self.instances:
            inst = self.instances[run_id]
            inst["last_beat"] = time.time()
            beats += 1
            # A paused run keeps beating: it is waiting for a person, not dead. Without
            # the state the UI would flag it STALE and the operator would go looking for
            # a hang that is actually an unanswered question.
            await self._emit(run_id, "heartbeat",
                             {"ref": inst["ref"], "age": round(time.time() - inst["started"], 1),
                              "state": inst.get("state", "running")},
                             persist=(beats % HEARTBEAT_PERSIST_EVERY == 1))
            await asyncio.sleep(HEARTBEAT_SECS)

    def live_instances(self) -> list[dict]:
        now = time.time()
        return [{"run_id": rid, "ref": i["ref"], "started": i["started"],
                 "last_beat": i["last_beat"], "state": i.get("state", "running"),
                 "flow": i.get("flow", ""),
                 "stale": now - i["last_beat"] > 3 * HEARTBEAT_SECS}
                for rid, i in self.instances.items()]

    def cancel(self, run_id: str) -> bool:
        """Control → data: abort a run (and any of its workflow steps)."""
        hit = False
        for rid, inst in list(self.instances.items()):
            if rid == run_id or inst.get("parent") == run_id:
                inst["agent"].aborted = True
                hit = True
        return hit

    # -- approvals: pause rather than fail --------------------------------------

    def _approval_ceiling(self) -> int:
        """How long an unanswered question may hold a run open. It is added to the outer
        timeout so a paused run outlives its working budget, and it is finite so an
        unanswered one does not outlive the day."""
        return int((self.cfg.get("fabric") or {}).get("approval_timeout", 900))

    def _approver(self, run_id: str, ref: str, origin: dict, budget: Budget,
                  eff_autonomy: str):
        """The gate's last mile for an unattended run.

        It does NOT consult grants. It is only reached once the PDP has already returned
        `ask`, which means the grants were checked, the ledger row was written, and
        `audit_finish` will stamp the outcome. A second check here would be a silent
        second gate, and the PDP is the one place.
        """
        async def ask(name, args, reason, offer=None) -> bool:
            if not self.approvals:
                # nobody to ask: the historical behaviour, made explicit
                return eff_autonomy == "full"
            inst = self.instances.get(run_id) or {}
            inst["state"] = "paused"
            budget.pause()
            await self._emit(run_id, "approval",
                             {"state": "asked", "node_id": run_id, "ref": ref, "tool": name,
                              "reason": (reason or "")[:300],
                              "via": (origin or {}).get("surface") or "gui"})
            ok = False
            try:
                ok = bool(await self.approvals(run_id, name, args, reason, offer, origin or {}))
            except Exception:
                ok = False
            finally:
                budget.resume()
                inst["state"] = "running"
                await self._emit(run_id, "approval",
                                 {"state": "allowed" if ok else "denied", "node_id": run_id,
                                  "ref": ref, "tool": name})
            return ok
        return ask

    # -- data plane execution (L0) ----------------------------------------------

    def _persona(self, defn: dict, context: str) -> str:
        parts = ["=== You are a SUBAGENT ===",
                 f"You are '{defn['name']}', a specialist subagent of AgentOS. Do ONLY the task "
                 "you are given and return the result as your final message. No small talk. "
                 "You cannot ask the user questions — decide and proceed.",
                 "Build on what the OS already knows: the memory sections above are real context "
                 "about this user — use them. `recall`/`kg_query` fetch more when the task touches "
                 "the user's world, and if an installed skill matches the task, load it with "
                 "`use_skill(name)` and follow it instead of improvising.",
                 defn.get("soul") or ""]
        for sname in (defn.get("skills") or [])[:5]:
            sk = self.store.get_skill(sname)
            if sk:
                parts.append(f"=== skill: {sk['name']} ===\n{sk['content'][:4000]}")
        if context:
            parts.append(f"=== context from the control plane ===\n{context[:6000]}")
        return "\n\n".join(p for p in parts if p)

    async def run_subagent(self, defn: dict, task: str, context: str = "",
                           parent_run: str = "", model_override: str = "",
                           approver=None, kind: str = "delegate",
                           conversation_id: str = "", ui_emit=None,
                           agent_slot: dict | None = None, space_id: str = "",
                           flow: str = "", origin: dict | None = None,
                           escalate: bool = False, taint: list | None = None) -> dict:
        """ui_emit: optional passthrough for the agent's live events (text/tool/error) —
        set when a subagent runs inside a chat so the user watches it work inline.
        agent_slot: optional dict that receives {"agent": <Agent>} so the caller's
        stop button can abort the data plane directly.
        space_id: the space the delegating turn was in. A specialist working on a
        launch must see the launch's memory, not three clients' at once."""
        model = self.resolve_model(defn, model_override)
        # a child that was not told its space inherits the delegating conversation's
        if not space_id and conversation_id:
            try:
                space_id = (self.store.get_conversation(conversation_id) or {}).get("space_id") or ""
            except Exception:
                space_id = ""
        origin = origin or {}
        run_id = self.store.fabric_run_start(kind, defn["name"], task,
                                             parent_run=parent_run, model=model,
                                             space_id=space_id,
                                             conversation_id=conversation_id, flow=flow,
                                             origin_surface=origin.get("surface", ""),
                                             origin_ref=str(origin.get("ref", "") or
                                                            origin.get("chat_id", "") or ""))
        await self._emit(run_id, "status", {"status": "running", "ref": defn["name"],
                                            "model": model, "parent_run": parent_run})
        eff_autonomy = min_autonomy(self.cfg.get("autonomy", "balanced"),
                                    defn.get("autonomy_cap", "balanced"))
        child_cfg = {**self.cfg, "max_steps": int(defn.get("max_steps", 12)),
                     "autonomy": eff_autonomy}
        budget = Budget(int(defn.get("max_seconds", 300)))

        usage = {"in": 0, "out": 0}
        nsteps = {"n": 0}

        async def emit(ev):  # data → control: step telemetry (+ live mirror into a chat)
            if ui_emit:
                try:
                    await ui_emit(ev)
                except Exception:
                    pass
            if ev["type"] == "tool_start":
                nsteps["n"] += 1
                await self._emit(run_id, "step", {"tool": ev["name"], "status": "start"})
            elif ev["type"] == "tool_end":
                await self._emit(run_id, "step", {"tool": ev["name"], "status": "end",
                                                  "ok": ev.get("ok", True)})
            elif ev["type"] == "error":
                await self._emit(run_id, "fault", {"message": ev.get("message", "")[:500]})

        async def headless_approver(_n, _a, _r, _offer=None):
            # no human inside a data plane: gated actions need effective 'full'
            return eff_autonomy == "full"

        if approver is None and escalate:
            # inside a flow, a gated action is worth interrupting a person for — the run
            # pauses (and stops spending its budget) rather than quietly failing
            approver = self._approver(run_id, defn["name"], origin, budget, eff_autonomy)

        tools = defn.get("tools") or SAFE_TOOLS
        # subagents never manage the fabric or rewrite the OS/its identity
        # (also enforced as built-in denies in policy.py — this keeps the schemas clean)
        tools = [t for t in tools if t not in
                 ("delegate", "run_workflow", "configure_agentos", "update_soul",
                  "develop_agentos", "restart_agentos")]
        # every data plane can stand on the OS's shoulders: skills + memory + knowledge
        for t in ("use_skill", "recall", "kg_query", "remember"):
            if t not in tools:
                tools.append(t)
        agent = Agent(child_cfg, self.toolbox, model, emit, approver or headless_approver,
                      extra_system=self._persona(defn, context), tool_filter=tools,
                      conversation_id=conversation_id, space_id=space_id,
                      principal=Principal("subagent", defn["name"]))
        if taint:
            # a child handed untrusted material inherits the ceiling that came with it:
            # the page does not become trustworthy by being passed along
            agent.taint.extend(taint)
        if agent_slot is not None:
            agent_slot["agent"] = agent
        self.instances[run_id] = {"agent": agent, "ref": defn["name"], "parent": parent_run,
                                  "started": time.time(), "last_beat": time.time(),
                                  "state": "running", "flow": flow}
        hb = asyncio.create_task(self._heartbeat_sidecar(run_id))
        wd = asyncio.create_task(_watchdog(agent, budget))
        status, content, fault, trace = "ok", "", "", []
        from . import knowledge as _k
        _k.turn_started()  # data planes are foreground work — background jobs must yield
        try:
            # The watchdog gives the nicer working-seconds semantics; this outer wait_for
            # stays as the guaranteed upper bound. If the watchdog task ever dies — or the
            # run is wedged inside a provider call, where `aborted` is not read until the
            # call returns — it must still terminate: a hung run holds turn_started(),
            # which suppresses background maintenance for the whole OS, not just itself.
            # The approval window is only added when this run can actually pause; a run
            # that cannot ask a human keeps its old, tighter ceiling.
            result = await asyncio.wait_for(
                agent.run([{"role": "user", "content": task}]),
                timeout=budget.limit + (self._approval_ceiling() if escalate else 0) + 60)
            content = result.get("content") or ""
            trace = result.get("steps") or []
            tk = result.get("tokens") or {}
            usage["in"], usage["out"] = tk.get("input", 0), tk.get("output", 0)
            if agent.aborted and budget.remaining() <= 0:
                status, fault = "timeout", (f"exceeded max_seconds={int(budget.limit)} of "
                                            f"working time")
            elif agent.aborted:
                status = "cancelled"
            elif any(s.get("type") == "error" for s in result.get("steps", [])):
                status, fault = "error", next((s["message"] for s in result["steps"]
                                               if s.get("type") == "error"), "")
        except asyncio.TimeoutError:
            agent.aborted = True
            status, fault = "timeout", f"exceeded max_seconds={int(budget.limit)}"
        except Exception as e:
            status, fault = "error", f"{type(e).__name__}: {e}"
        finally:
            _k.turn_ended()
            self.instances.pop(run_id, None)
            hb.cancel()
            wd.cancel()
        self.store.fabric_run_finish(run_id, status, output=content, fault=fault,
                                     tokens_in=usage["in"], tokens_out=usage["out"],
                                     steps=nsteps["n"])
        await self._emit(run_id, "status",
                         {"status": status, "ref": defn["name"], "parent_run": parent_run,
                          "fault": fault[:300], "tokens": usage, "steps": nsteps["n"]})
        return {"run_id": run_id, "status": status, "content": content, "fault": fault,
                "model": model, "usage": usage, "steps": trace}

    # -- workflows: a DAG of subagent steps ---------------------------------------

    @staticmethod
    def _layers(steps: list[dict]) -> list[list[dict]]:
        """Topological layers (steps whose deps are all satisfied run in parallel)."""
        done: set = set()
        remaining = list(steps)
        layers = []
        while remaining:
            layer = [s for s in remaining
                     if all(d in done for d in (s.get("depends_on") or []))]
            if not layer:  # cycle or dangling dep — run the rest sequentially
                layer = [remaining[0]]
            for s in layer:
                done.add(s["id"])
            remaining = [s for s in remaining if s not in layer]
            layers.append(layer)
        return layers

    async def run_workflow(self, wf: dict, input_text: str, approver=None,
                           conversation_id: str = "") -> dict:
        run_id = self.store.fabric_run_start("workflow", wf["name"], input_text)
        await self._emit(run_id, "status", {"status": "running", "ref": wf["name"],
                                            "workflow": True})
        outputs: dict[str, str] = {}
        totals = {"in": 0, "out": 0, "steps": 0}
        status, fault, final = "ok", "", ""
        for layer in self._layers(wf.get("steps") or []):
            async def run_step(step):
                defn = self.store.get_subagent(step.get("subagent", ""))
                if not defn:
                    return step, {"status": "error", "content": "",
                                  "fault": f"unknown subagent: {step.get('subagent')}",
                                  "usage": {"in": 0, "out": 0}}
                prompt = step.get("prompt") or "{input}"
                prompt = prompt.replace("{input}", input_text)
                for sid, out in outputs.items():
                    prompt = prompt.replace("{" + sid + "}", out)
                deps = step.get("depends_on") or []
                ctx = "\n\n".join(f"--- output of step '{d}' ---\n{outputs.get(d, '')[:5000]}"
                                  for d in deps if d in outputs)
                await self._emit(run_id, "step", {"wf_step": step["id"], "status": "start",
                                                  "subagent": step.get("subagent")})
                res = await self.run_subagent(defn, prompt, context=ctx, parent_run=run_id,
                                              model_override=step.get("model", ""),
                                              approver=approver, kind="step",
                                              conversation_id=conversation_id)
                await self._emit(run_id, "step", {"wf_step": step["id"], "status": res["status"],
                                                  "run_id_step": res["run_id"]})
                return step, res
            results = await asyncio.gather(*(run_step(s) for s in layer))
            for step, res in results:
                outputs[step["id"]] = res["content"]
                totals["in"] += res["usage"]["in"]
                totals["out"] += res["usage"]["out"]
                if res["status"] != "ok" and status == "ok":
                    status, fault = res["status"], f"step '{step['id']}': {res['fault']}"
                final = res["content"] or final
            if status != "ok":
                break
        self.store.fabric_run_finish(run_id, status, output=final, fault=fault,
                                     tokens_in=totals["in"], tokens_out=totals["out"],
                                     steps=len(outputs))
        await self._emit(run_id, "status", {"status": status, "ref": wf["name"],
                                            "workflow": True, "fault": fault[:300]})
        return {"run_id": run_id, "status": status, "content": final, "fault": fault,
                "outputs": outputs, "usage": totals}


    # -- flows: a master orchestrator with a roster and a blackboard --------------

    def _board(self, run_id: str, limit_chars: int = BOARD_BUDGET) -> str:
        """The index the orchestrator reads. Never the contents — that is what handles
        are for, and a board that inlined outputs would spend the context window on the
        work instead of on deciding what to do next."""
        rows = self.store.artifact_index(run_id)
        if not rows:
            return "--- board --- (empty: nothing delegated yet)"
        lines, total, shown = [], 0, 0
        for r in reversed(rows):                      # newest first, then re-reversed
            tok = (r["tokens_in"] or 0) + (r["tokens_out"] or 0)
            line = (f"{r['handle']:<4} {(r['agent'] or r['kind'])[:12]:<12} "
                    f"{r['status']:<8} {tok or '—':>6}tok {r['bytes']:>7}B  "
                    f"{(r['preview'] or '')[:70]}"
                    + ("  [tainted]" if r.get("tainted") else ""))
            if total + len(line) > limit_chars and shown >= 4:
                break
            lines.append(line)
            total += len(line)
            shown += 1
        older = len(rows) - shown
        out = ["--- board ---"] + list(reversed(lines))
        if older > 0:
            out.append(f"+{older} older (read_handle to open)")
        return "\n".join(out)

    def _master_tools(self, flow: dict, run_id: str, state: dict, origin: dict,
                      space_id: str, conversation_id: str, approver, taint: list):
        """The four run-scoped tools, closed over this run. See _RunToolbox."""
        roster = [r["subagent"] if isinstance(r, dict) else str(r)
                  for r in (flow.get("roster") or [])]

        def receipt(head: str) -> str:
            return f"{head}\n\n{self._board(run_id)}"

        # `conversation_id` shadows the closure's on purpose: agent.py injects the turn's
        # conversation into `delegate`'s args, and the child should inherit that one.
        async def t_delegate(subagent: str = "", task: str = "", context_handles=None,
                             model: str = "", conversation_id: str = "") -> str:
            sub = (subagent or "").strip()
            if sub not in roster:
                # a sentence the model can act on, before the PDP's flatter denial
                return receipt(f"[denied] '{sub}' is not on this flow's roster. You may "
                               f"delegate to: {', '.join(roster) or '(none)'}.")
            if state["delegations"] >= int(flow.get("max_delegations", 12)):
                return receipt(f"[denied] this flow's delegation budget "
                               f"({flow.get('max_delegations', 12)}) is spent. Summarise what "
                               f"you have with `finish`.")
            defn = self.store.get_subagent(sub)
            if not defn:
                return receipt(f"[error] subagent '{sub}' no longer exists")
            handles = [str(h) for h in (context_handles or [])]
            parts, used, missing, inherited = [], 0, [], []
            for h in handles:
                art = self.store.artifact_get(run_id, h)
                if not art:
                    missing.append(h)
                    continue
                body = art["content"] or ""
                room = CONTEXT_BUDGET - used
                if len(body) > room:
                    body = body[:max(0, room)] + \
                        f"\n[handle {h} truncated at {CONTEXT_BUDGET} chars — narrow the task]"
                used += len(body)
                parts.append(f"--- {h} · from {art['agent'] or art['kind']} ---\n{body}")
                if art.get("tainted"):
                    inherited.append({"tool": "flow", "source": f"handle {h}"})
            ctx = "\n\n".join(parts)
            state["delegations"] += 1
            # The graph node is identified by its place in the flow, not by the child's
            # run id: the node has to appear the moment the work starts, and the run id
            # does not exist until run_subagent has written its row.
            node = f"d{state['delegations']}"
            await self._emit(run_id, "node_add",
                             {"node_id": node, "agent": sub, "task": (task or "")[:140],
                              "deps": handles, "parent": run_id, "seq": state["delegations"]})
            res = await self.run_subagent(
                defn, task or flow.get("mission", ""), context=ctx, parent_run=run_id,
                model_override=model or "", approver=approver, kind="delegate",
                conversation_id=conversation_id, space_id=space_id, flow=flow["name"],
                origin=origin, escalate=True, taint=(taint + inherited) or None)
            handle = self.store.next_handle(run_id, "a")
            self.store.artifact_add(
                run_id, handle, res["content"] or res["fault"] or "", kind="output",
                agent=sub, child_run=res["run_id"], task=task or "", status=res["status"],
                tokens_in=res["usage"]["in"], tokens_out=res["usage"]["out"],
                tainted=1 if inherited else 0, deps=handles, space_id=space_id)
            await self._emit(run_id, "node_status",
                             {"node_id": node, "status": res["status"], "tokens": res["usage"],
                              "fault": (res["fault"] or "")[:300], "handle": handle,
                              "child_run": res["run_id"], "model": res["model"]})
            art = self.store.artifact_get(run_id, handle) or {}
            await self._emit(run_id, "artifact",
                             {"handle": handle, "node_id": node, "agent": sub,
                              "kind": "output", "status": res["status"],
                              "bytes": art.get("bytes", 0), "preview": art.get("preview", ""),
                              "deps": handles, "tainted": art.get("tainted", 0)})
            head = (f"[{sub} · {res['status']} · {res['usage']['in'] + res['usage']['out']} tok "
                    f"· model {res['model']}]\nhandle {handle} — {art.get('bytes', 0)} chars"
                    + (f"\npreview: {art.get('preview', '')}" if art.get("preview") else "")
                    + (f"\n[missing handles ignored: {', '.join(missing)}]" if missing else "")
                    + (f"\nfault: {res['fault'][:300]}" if res["fault"] else ""))
            return receipt(head)

        async def t_read_handle(handle: str = "", offset: int = 0, limit: int = 6000) -> str:
            art = self.store.artifact_get(run_id, str(handle or ""))
            if not art:
                return receipt(f"[error] no handle '{handle}' on this board")
            body = art["content"] or ""
            off, lim = max(0, int(offset or 0)), max(200, min(int(limit or 6000), 20000))
            chunk = body[off:off + lim]
            left = max(0, len(body) - (off + len(chunk)))
            return (f"--- {handle} · {art['agent'] or art['kind']} · chars {off}-{off + len(chunk)} "
                    f"of {len(body)} ---\n{chunk}"
                    + (f"\n\n[{left} chars remain — read_handle(offset={off + len(chunk)})]"
                       if left else ""))

        async def t_note(text: str = "") -> str:
            handle = self.store.next_handle(run_id, "n")
            self.store.artifact_add(run_id, handle, text or "", kind="note", agent="master",
                                    space_id=space_id)
            await self._emit(run_id, "artifact",
                             {"handle": handle, "node_id": run_id, "agent": "master",
                              "kind": "note", "status": "ok", "bytes": len(text or ""),
                              "preview": " ".join((text or "").split())[:180], "deps": []})
            await self._emit(run_id, "log", {"node_id": run_id, "level": "info",
                                             "text": (text or "")[:240]})
            return receipt(f"[noted as {handle}]")

        async def t_finish(summary: str = "", handles=None) -> str:
            state["final"] = summary or ""
            state["final_handles"] = [str(h) for h in (handles or [])]
            state["finished"] = True
            # End the turn here rather than asking the model to please stop talking. A
            # model that obeys "say nothing further" produces an empty reply, and the
            # agent's empty-turn guard would correctly call that a failure — so a
            # perfectly good flow would report `error` for having finished politely.
            if state.get("agent") is not None:
                state["agent"].aborted = True
            await self._emit(run_id, "log", {"node_id": run_id, "level": "info",
                                             "text": f"finished · {len(summary or '')} chars"})
            return "Deliverable recorded. This run is complete."

        schemas = [
            {"name": "delegate",
             "description": "Hand ONE concrete task to an agent on your roster. Returns a "
                            "receipt with a handle for its full output — read it with "
                            "read_handle, or pass it to the next agent with context_handles. "
                            "You never see the whole output inline; that is what handles are "
                            "for.",
             "parameters": {"type": "object", "properties": {
                 "subagent": {"type": "string",
                              "description": f"one of: {', '.join(roster) or '(none)'}"},
                 "task": {"type": "string",
                          "description": "what this agent must produce, in full — it cannot "
                                         "see the mission or the board"},
                 "context_handles": {"type": "array", "items": {"type": "string"},
                                     "description": "handles whose FULL contents this agent "
                                                    "should be given"},
                 "model": {"type": "string", "description": "optional model override"}},
                 "required": ["subagent", "task"]}},
            {"name": "read_handle",
             "description": "Read an artefact on the board in full (paged).",
             "parameters": {"type": "object", "properties": {
                 "handle": {"type": "string"},
                 "offset": {"type": "integer"},
                 "limit": {"type": "integer"}},
                 "required": ["handle"]}},
            {"name": "note",
             "description": "Record a finding or a decision on the board so it survives and "
                            "shows on the control-plane graph.",
             "parameters": {"type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"]}},
            {"name": "finish",
             "description": "You are satisfied the mission is done. Write the deliverable and "
                            "stop.",
             "parameters": {"type": "object", "properties": {
                 "summary": {"type": "string", "description": "the deliverable itself, in full"},
                 "handles": {"type": "array", "items": {"type": "string"},
                             "description": "the handles it was built from"}},
                 "required": ["summary"]}},
        ]
        impls = {"delegate": t_delegate, "read_handle": t_read_handle,
                 "note": t_note, "finish": t_finish}
        return schemas, impls

    def _master_persona(self, flow: dict) -> str:
        roster = flow.get("roster") or []
        lines = []
        for r in roster:
            if isinstance(r, str):
                r = {"subagent": r}
            defn = self.store.get_subagent(r["subagent"]) or {}
            soul = " ".join((defn.get("soul") or "").split())[:200]
            why = r.get("why") or ""
            lines.append(f"  - {r['subagent']}: {soul}" + (f"  (use it for: {why})" if why else ""))
        return "\n\n".join([
            "=== You are the MASTER ORCHESTRATOR of a flow ===",
            f"Flow '{flow['name']}'. Mission:\n{flow.get('mission') or ''}",
            "Your roster — these are the only agents you may use:\n" + ("\n".join(lines) or "  (none)"),
            "How you work:\n"
            "  1. Decide what has to be true for the mission to be done.\n"
            "  2. `delegate` one concrete task at a time to the right specialist. Give it "
            "everything it needs in the task text — it cannot see the mission, the board, or "
            "anything you have not passed it.\n"
            "  3. Pass earlier work forward with `context_handles` rather than retyping it.\n"
            "  4. `read_handle` when you need to actually read an output; `note` anything worth "
            "keeping.\n"
            "  5. `finish` with the deliverable when the mission is met — or when a step has "
            "failed and it cannot be.\n\n"
            "You plan and aggregate. You do NOT do the work yourself: you have no tools for "
            "fetching, writing files or running commands, on purpose. If something cannot be "
            "delegated to anyone on the roster, say so in `finish` rather than improvising.\n"
            "A denied or failed step is information, not the end: route around it if you can, "
            "and report it plainly if you cannot.",
        ])

    async def run_flow(self, flow: dict, input_text: str = "", origin: dict | None = None,
                       conversation_id: str = "", space_id: str = "", trigger_id: str = "",
                       tainted: bool = False, approver=None, ui_emit=None,
                       agent_slot: dict | None = None, run_id_out=None) -> dict:
        """One mission, one master, one blackboard. The graph the UI draws is this run's
        event stream — nodes appear as the master delegates, which is why there is no DAG
        to author: the plan is made while it runs."""
        origin = origin or {}
        name = flow["name"]
        space_id = space_id or flow.get("space_id") or ""
        if not space_id and conversation_id:
            try:
                space_id = (self.store.get_conversation(conversation_id) or {}).get("space_id") or ""
            except Exception:
                space_id = ""
        model = self.resolve_model({"name": name, "model": flow.get("model") or ""})
        run_id = self.store.fabric_run_start(
            "flow", name, input_text or flow.get("mission", ""), model=model, space_id=space_id,
            conversation_id=conversation_id, flow=name,
            origin_surface=origin.get("surface", ""),
            origin_ref=str(origin.get("ref", "") or origin.get("chat_id", "") or ""))
        if run_id_out is not None and not run_id_out.done():
            # the caller gets the id before the work starts, so it can subscribe to this
            # run rather than guess which of the recent ones was theirs
            run_id_out.set_result(run_id)
        roster = [r["subagent"] if isinstance(r, dict) else str(r) for r in (flow.get("roster") or [])]
        await self._emit(run_id, "flow_start",
                         {"flow": name, "mission": (flow.get("mission") or "")[:200],
                          "origin": {"surface": origin.get("surface", ""),
                                     "ref": str(origin.get("ref", "") or "")},
                          "roster": roster, "space_id": space_id,
                          "input": (input_text or "")[:200], "tainted": bool(tainted)})

        # the trigger's own payload is the first thing on the board
        taint: list = []
        raw = input_text or ""
        if raw:
            self.store.artifact_add(run_id, "in1", raw, kind="input",
                                    agent="", task="what started this run",
                                    tainted=1 if tainted else 0, space_id=space_id)
            art = self.store.artifact_get(run_id, "in1") or {}
            await self._emit(run_id, "artifact",
                             {"handle": "in1", "node_id": run_id, "agent": "", "kind": "input",
                              "status": "ok", "bytes": art.get("bytes", 0),
                              "preview": art.get("preview", ""), "deps": [],
                              "tainted": 1 if tainted else 0})
        if tainted:
            # Content from outside this machine. Everything downstream is existing
            # machinery: the PDP's taint ceiling escalates risky steps to `ask` (or
            # refuses them under `strict`) and deliberately offers no "remember", so
            # "Always" cannot hand the next payload the same key.
            taint.append({"tool": "webhook", "source": f"the {name} hook"})

        eff_autonomy = min_autonomy(self.cfg.get("autonomy", "balanced"),
                                    flow.get("autonomy_cap", "balanced"))
        child_cfg = {**self.cfg, "max_steps": int(flow.get("max_steps", 24)),
                     "autonomy": eff_autonomy}
        budget = Budget(int(flow.get("max_seconds", 1800)))
        state = {"delegations": 0, "final": "", "final_handles": []}
        master_approver = approver or self._approver(run_id, name, origin, budget, eff_autonomy)
        schemas, impls = self._master_tools(flow, run_id, state, origin, space_id,
                                            conversation_id, approver, taint)
        toolbox = _RunToolbox(self.toolbox, schemas, impls, MASTER_READONLY)
        tool_names = MASTER_READONLY + [s["name"] for s in schemas]

        usage = {"in": 0, "out": 0}

        async def emit(ev):
            if ui_emit:
                try:
                    await ui_emit(ev)
                except Exception:
                    pass
            if ev["type"] == "error":
                await self._emit(run_id, "log", {"node_id": run_id, "level": "error",
                                                 "text": ev.get("message", "")[:240]})

        mission = flow.get("mission") or ""
        opening = mission if not raw else (
            f"{mission}\n\n=== what started this run ({origin.get('surface') or 'manual'}) ===\n"
            + (fence(f"the {name} hook", raw[:6000]) if tainted else raw[:6000])
            + "\n\n(the full payload is on the board as handle `in1`)")
        agent = Agent(child_cfg, toolbox, model, emit, master_approver,
                      extra_system=self._master_persona(flow), tool_filter=tool_names,
                      conversation_id=conversation_id, space_id=space_id,
                      principal=Principal("flow", name),
                      surface=origin.get("surface") or "gui")
        agent.taint.extend(taint)
        state["agent"] = agent          # so `finish` can end the turn (see t_finish)
        if agent_slot is not None:
            agent_slot["agent"] = agent
        self.instances[run_id] = {"agent": agent, "ref": name, "parent": "",
                                  "started": time.time(), "last_beat": time.time(),
                                  "state": "running", "flow": name}
        hb = asyncio.create_task(self._heartbeat_sidecar(run_id))
        wd = asyncio.create_task(_watchdog(agent, budget))
        status, fault, content = "ok", "", ""
        from . import knowledge as _k
        _k.turn_started()
        try:
            result = await asyncio.wait_for(
                agent.run([{"role": "user", "content": opening}]),
                timeout=budget.limit + self._approval_ceiling() + 60)
            content = state["final"] or result.get("content") or ""
            tk = result.get("tokens") or {}
            usage["in"], usage["out"] = tk.get("input", 0), tk.get("output", 0)
            if state.get("finished"):
                status = "ok"           # it said it was done; a child's failure is folded in below
            elif budget.remaining() <= 0:
                status, fault = "timeout", f"exceeded max_seconds={int(budget.limit)} of working time"
            elif agent.aborted:
                status = "cancelled"
            elif any(s.get("type") == "error" for s in result.get("steps", [])):
                status, fault = "error", next((s["message"] for s in result["steps"]
                                               if s.get("type") == "error"), "")
        except asyncio.TimeoutError:
            agent.aborted = True
            status, fault = "timeout", f"exceeded max_seconds={int(budget.limit)}"
        except Exception as e:
            status, fault = "error", f"{type(e).__name__}: {e}"
        finally:
            _k.turn_ended()
            self.instances.pop(run_id, None)
            hb.cancel()
            wd.cancel()
        # a flow whose children all failed did not succeed, whatever the master says
        kids = self.store.fabric_runs(parent_run=run_id)
        if status == "ok" and kids and all(k["status"] != "ok" for k in kids):
            status, fault = "error", fault or "every delegated step failed"
        for k in (kids if status == "ok" else []):
            if k["status"] != "ok":
                status = "partial"
                fault = fault or f"step '{k['ref']}' {k['status']}"
        self.store.fabric_run_finish(run_id, status, output=content, fault=fault,
                                     tokens_in=usage["in"], tokens_out=usage["out"],
                                     steps=state["delegations"])
        delivered: list = []
        if self.deliver and content:
            try:
                delivered = await self.deliver(flow, self.store.fabric_run(run_id) or {},
                                               origin, content) or []
            except Exception as e:
                await self._emit(run_id, "log", {"node_id": run_id, "level": "error",
                                                 "text": f"delivery failed: {e}"[:240]})
        await self._emit(run_id, "flow_end",
                         {"status": status, "ref": name, "flow": name,
                          "tokens": usage, "steps": state["delegations"],
                          "preview": content[:400], "delivered": delivered,
                          "fault": fault[:300]})
        return {"run_id": run_id, "status": status, "content": content, "fault": fault,
                "model": model, "usage": usage, "delegations": state["delegations"],
                "delivered": delivered,
                "board": self.store.artifact_index(run_id)}


def parse_mention(store, text: str):
    """'@researcher find X' → (subagent_defn, 'find X') when the name matches a
    subagent; None otherwise. Lets any chat surface (web, Telegram, TUI) address a
    team member directly instead of going through the main agent."""
    import re
    m = re.match(r"@([A-Za-z0-9_-]+)\s+(.+)", (text or "").strip(), re.S)
    if not m:
        return None
    defn = store.get_subagent(m.group(1))
    return (defn, m.group(2).strip()) if defn else None


# ---------------------------------------------------------------------------
# Built-ins: seeded once so the fabric is usable (and demoable) out of the box
# ---------------------------------------------------------------------------

def seed_builtins(cfg: dict, store):
    if store.list_subagents():
        return
    anthropic_on = (cfg.get("providers", {}).get("anthropic") or {}).get("enabled")
    validator_model = "anthropic/claude-sonnet-5" if anthropic_on else ""
    store.save_subagent({
        "name": "researcher", "builtin": 1,
        "soul": "You research. Gather real information with your tools, verify it, and return "
                "a dense, sourced summary. Never pad; never invent.",
        "model": "",  # inherit — the control plane decides
        "tools": ["fetch_url", "read_file", "list_dir", "recall", "kg_query", "save_report"],
        "max_steps": 15, "max_seconds": 420,
    })
    store.save_subagent({
        "name": "writer", "builtin": 1,
        "soul": "You draft. Turn the task and any provided context into clear, well-structured "
                "prose or code. Return only the deliverable.",
        "model": "", "tools": [], "max_steps": 6, "max_seconds": 240,
    })
    store.save_subagent({
        "name": "validator", "builtin": 1,
        "soul": "You validate. Check the provided work for factual errors, logical gaps, unmet "
                "requirements, and unsafe advice. Return a verdict line (APPROVED or NEEDS-WORK) "
                "followed by numbered findings. Be strict; do not rewrite the work.",
        "model": validator_model,  # heterogeneous smartness: e.g. Claude judges Ollama
        "tools": ["recall", "kg_query", "read_file"], "max_steps": 6, "max_seconds": 240,
    })
    # No built-in workflows are seeded any more. The static-DAG engine, its API and the
    # `run_workflow` tool all still work for anything that already uses them — but a
    # flow does the same job and decides at run time, so seeding two DAGs nobody ran
    # was furnishing every new machine with dead examples.
    store.log("system", "fabric: seeded built-in subagents (researcher, writer, validator)")
