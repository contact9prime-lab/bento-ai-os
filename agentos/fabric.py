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

from .agent import Agent

_AUTONOMY_ORDER = {"paranoid": 0, "balanced": 1, "full": 2}

# a subagent with an empty tools list gets this read-only set
SAFE_TOOLS = ["fetch_url", "read_file", "list_dir", "recall", "kg_query", "system_info"]

HEARTBEAT_SECS = 5          # sidecar beat + UI broadcast cadence
HEARTBEAT_PERSIST_EVERY = 6  # persist 1 of every N beats (avoid write spam)


def min_autonomy(a: str, b: str) -> str:
    order = sorted([a or "balanced", b or "balanced"], key=lambda x: _AUTONOMY_ORDER.get(x, 1))
    return order[0]


class ControlPlane:
    def __init__(self, cfg: dict, store, toolbox, broadcast=None):
        self.cfg = cfg
        self.store = store
        self.toolbox = toolbox
        self.broadcast = broadcast
        # run_id -> live instance {"agent", "hb_task", "last_beat", "ref", "started"}
        self.instances: dict = {}

    # -- hierarchy: the control plane decides how smart each data plane is ----

    def resolve_model(self, defn: dict, step_override: str = "") -> str:
        return step_override or (defn.get("model") or "") or self.cfg.get("default_model", "")

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
            await self._emit(run_id, "heartbeat",
                             {"ref": inst["ref"], "age": round(time.time() - inst["started"], 1)},
                             persist=(beats % HEARTBEAT_PERSIST_EVERY == 1))
            await asyncio.sleep(HEARTBEAT_SECS)

    def live_instances(self) -> list[dict]:
        now = time.time()
        return [{"run_id": rid, "ref": i["ref"], "started": i["started"],
                 "last_beat": i["last_beat"], "stale": now - i["last_beat"] > 3 * HEARTBEAT_SECS}
                for rid, i in self.instances.items()]

    def cancel(self, run_id: str) -> bool:
        """Control → data: abort a run (and any of its workflow steps)."""
        hit = False
        for rid, inst in list(self.instances.items()):
            if rid == run_id or inst.get("parent") == run_id:
                inst["agent"].aborted = True
                hit = True
        return hit

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
                           conversation_id: str = "") -> dict:
        model = self.resolve_model(defn, model_override)
        run_id = self.store.fabric_run_start(kind, defn["name"], task,
                                             parent_run=parent_run, model=model)
        await self._emit(run_id, "status", {"status": "running", "ref": defn["name"],
                                            "model": model, "parent_run": parent_run})
        eff_autonomy = min_autonomy(self.cfg.get("autonomy", "balanced"),
                                    defn.get("autonomy_cap", "balanced"))
        child_cfg = {**self.cfg, "max_steps": int(defn.get("max_steps", 12)),
                     "autonomy": eff_autonomy}

        usage = {"in": 0, "out": 0}
        nsteps = {"n": 0}

        async def emit(ev):  # data → control: step telemetry
            if ev["type"] == "tool_start":
                nsteps["n"] += 1
                await self._emit(run_id, "step", {"tool": ev["name"], "status": "start"})
            elif ev["type"] == "tool_end":
                await self._emit(run_id, "step", {"tool": ev["name"], "status": "end",
                                                  "ok": ev.get("ok", True)})
            elif ev["type"] == "error":
                await self._emit(run_id, "fault", {"message": ev.get("message", "")[:500]})

        async def headless_approver(_n, _a, _r):
            # no human inside a data plane: risky actions need effective 'full'
            return eff_autonomy == "full"

        tools = defn.get("tools") or SAFE_TOOLS
        # subagents never manage the fabric or rewrite the OS/its identity
        tools = [t for t in tools if t not in
                 ("delegate", "run_workflow", "configure_agentos", "update_soul",
                  "develop_agentos", "restart_agentos")]
        # every data plane can stand on the OS's shoulders: skills + memory + knowledge
        for t in ("use_skill", "recall", "kg_query", "remember"):
            if t not in tools:
                tools.append(t)
        agent = Agent(child_cfg, self.toolbox, model, emit, approver or headless_approver,
                      extra_system=self._persona(defn, context), tool_filter=tools,
                      conversation_id=conversation_id)
        self.instances[run_id] = {"agent": agent, "ref": defn["name"], "parent": parent_run,
                                  "started": time.time(), "last_beat": time.time()}
        hb = asyncio.create_task(self._heartbeat_sidecar(run_id))
        status, content, fault = "ok", "", ""
        from . import knowledge as _k
        _k.turn_started()  # data planes are foreground work — background jobs must yield
        try:
            result = await asyncio.wait_for(
                agent.run([{"role": "user", "content": task}]),
                timeout=int(defn.get("max_seconds", 300)))
            content = result.get("content") or ""
            tk = result.get("tokens") or {}
            usage["in"], usage["out"] = tk.get("input", 0), tk.get("output", 0)
            if agent.aborted:
                status = "cancelled"
            elif any(s.get("type") == "error" for s in result.get("steps", [])):
                status, fault = "error", next((s["message"] for s in result["steps"]
                                               if s.get("type") == "error"), "")
        except asyncio.TimeoutError:
            agent.aborted = True
            status, fault = "timeout", f"exceeded max_seconds={defn.get('max_seconds', 300)}"
        except Exception as e:
            status, fault = "error", f"{type(e).__name__}: {e}"
        finally:
            _k.turn_ended()
            self.instances.pop(run_id, None)
            hb.cancel()
        self.store.fabric_run_finish(run_id, status, output=content, fault=fault,
                                     tokens_in=usage["in"], tokens_out=usage["out"],
                                     steps=nsteps["n"])
        await self._emit(run_id, "status",
                         {"status": status, "ref": defn["name"], "parent_run": parent_run,
                          "fault": fault[:300], "tokens": usage, "steps": nsteps["n"]})
        return {"run_id": run_id, "status": status, "content": content, "fault": fault,
                "model": model, "usage": usage}

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
    store.save_workflow({
        "name": "draft-and-validate", "builtin": 1,
        "description": "Generation and validation on different models: a writer drafts "
                       "(local model), a validator judges it (frontier model if configured).",
        "steps": [
            {"id": "draft", "name": "Draft", "subagent": "writer",
             "prompt": "{input}", "depends_on": []},
            {"id": "validate", "name": "Validate", "subagent": "validator",
             "prompt": "Validate the draft below against this request:\n{input}\n\n"
                       "=== draft ===\n{draft}", "depends_on": ["draft"]},
        ],
    })
    store.save_workflow({
        "name": "research-draft-validate", "builtin": 1,
        "description": "Research feeds a draft; a validator reviews the result.",
        "steps": [
            {"id": "research", "name": "Research", "subagent": "researcher",
             "prompt": "Research what is needed to fulfil: {input}", "depends_on": []},
            {"id": "draft", "name": "Draft", "subagent": "writer",
             "prompt": "Using the research provided in context, produce: {input}",
             "depends_on": ["research"]},
            {"id": "validate", "name": "Validate", "subagent": "validator",
             "prompt": "Validate the draft below against this request:\n{input}\n\n"
                       "=== draft ===\n{draft}", "depends_on": ["draft"]},
        ],
    })
    store.log("system", "fabric: seeded built-in subagents (researcher, writer, validator) "
                        "and workflows")
