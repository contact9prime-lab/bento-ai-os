"""Background scheduler: runs stored tasks as headless agent turns.

Two kinds of task share one table and one execution path:
  - time-based ('once' | 'interval' | 'daily') — picked up by next_run,
  - event-based ('trigger') — fired by the OS itself: a matching desktop
    notification, a watched file changing, session start (login), or the user
    going idle. Triggers are the proactivity layer: they are how AgentOS starts
    a turn nobody asked for, so every run is tagged with its origin and
    rate-limited by a per-task cooldown.
"""

import asyncio
import datetime
import json
import os
import re
import time
from pathlib import Path

from .agent import Agent

TRIGGER_KINDS = ("notification", "file_change", "login", "idle")
OS_ORIGINS = ("schedule", "trigger", "briefing", "suggestion")


def _next_daily(at_time: str, after: float) -> float:
    try:
        hh, mm = (int(x) for x in at_time.split(":"))
    except Exception:
        hh, mm = 9, 0
    dt = datetime.datetime.fromtimestamp(after).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if dt.timestamp() <= after:
        dt += datetime.timedelta(days=1)
    return dt.timestamp()


class Scheduler:
    def __init__(self, cfg: dict, store, toolbox, broadcast):
        """broadcast(event) -> awaitable: pushes events to all connected UI clients."""
        self.cfg = cfg
        self.store = store
        self.toolbox = toolbox
        self.broadcast = broadcast
        self.fabric = None            # ControlPlane, wired in server startup — a task that
                                      # names a flow runs the flow instead of a bare prompt
        self._stop = asyncio.Event()
        self._file_state: dict = {}   # trigger task id -> {path: mtime} snapshot
        self._idle_fired: dict = {}   # trigger task id -> last-turn ts it fired against

    def create_task(self, prompt: str, schedule_type: str, interval_minutes: int = 0,
                    at_time: str = "", delay_minutes: int = 0) -> str:
        now = time.time()
        if schedule_type == "interval":
            interval = max(1, int(interval_minutes)) * 60
            tid = self.store.add_task(prompt, "interval", interval, None, now + interval)
            return f"scheduled task {tid}: every {interval // 60} min"
        if schedule_type == "daily":
            at_time = at_time or "09:00"
            tid = self.store.add_task(prompt, "daily", None, at_time, _next_daily(at_time, now))
            return f"scheduled task {tid}: daily at {at_time}"
        delay = max(0, int(delay_minutes)) * 60
        tid = self.store.add_task(prompt, "once", None, None, now + delay)
        return f"scheduled task {tid}: once, in {delay // 60} min"

    # ---- triggers (event-driven tasks) --------------------------------------

    def create_trigger(self, trigger: str, prompt: str, match: str = "", path: str = "",
                       glob: str = "", minutes: float = 30, cooldown_secs: int = 300) -> str:
        trigger = (trigger or "").strip()
        if trigger not in TRIGGER_KINDS:
            return f"[error] trigger must be one of {', '.join(TRIGGER_KINDS)}"
        if not (prompt or "").strip():
            return "[error] a trigger needs a prompt to run when it fires"
        conf: dict = {}
        if trigger == "notification":
            if not (match or "").strip():
                return "[error] a notification trigger needs `match` (substring or regex)"
            conf["match"] = match.strip()
        elif trigger == "file_change":
            if not (path or "").strip():
                return "[error] a file_change trigger needs `path`"
            conf["path"] = path.strip()
            if (glob or "").strip():
                conf["glob"] = glob.strip()
        elif trigger == "idle":
            conf["minutes"] = max(1, float(minutes or 30))
        tid = self.store.add_task(prompt, "trigger", None, None, None, trigger=trigger,
                                  trigger_config=json.dumps(conf),
                                  cooldown_secs=max(0, int(cooldown_secs)))
        detail = conf.get("match") or conf.get("path") or \
            (f"{conf['minutes']:g} min" if trigger == "idle" else "session start")
        return f"trigger {tid}: on {trigger} ({detail}), cooldown {int(cooldown_secs)}s"

    def _trigger_tasks(self, kind: str) -> list[dict]:
        return [t for t in self.store.list_tasks()
                if t.get("enabled") and t.get("schedule_type") == "trigger"
                and t.get("trigger") == kind]

    def _fire(self, task: dict, context: str = "") -> bool:
        """Fire one trigger task, respecting its cooldown. Returns whether it fired."""
        now = time.time()
        if now - (task.get("last_fired") or 0) < (task.get("cooldown_secs") or 300):
            return False
        self.store.update_task(task["id"], last_fired=now)
        prompt = task["prompt"] + (f"\n\n[Trigger context] {context}" if context else "")
        self._launch({**task, "prompt": prompt}, origin="trigger",
                     title=f"⚡ {task['prompt'][:40]}")
        return True

    def _launch(self, task: dict, origin: str, title: str = ""):
        try:
            asyncio.create_task(self._run_task(task, origin=origin, title=title))
        except RuntimeError:
            pass  # no running loop (tests / shutdown) — the firing itself is still recorded

    def offer_notification(self, item: dict) -> list[str]:
        """Every notification the daemon receives passes through here — the hook
        the NotificationDaemon calls. Returns the ids of triggers that fired."""
        fired = []
        try:
            for t in self._trigger_tasks("notification"):
                conf = json.loads(t.get("trigger_config") or "{}")
                if self._notif_matches(conf.get("match", ""), item):
                    ctx = (f"notification from {item.get('app') or 'system'}: "
                           f"{item.get('summary') or ''}"
                           + (f" — {item['body']}" if item.get("body") else ""))
                    if self._fire(t, ctx):
                        fired.append(t["id"])
        except Exception:
            pass
        return fired

    @staticmethod
    def _notif_matches(match: str, item: dict) -> bool:
        """Case-insensitive substring, or regex when the pattern is one."""
        m = (match or "").strip()
        if not m:
            return False
        text = " ".join(str(item.get(k) or "") for k in ("app", "summary", "body"))
        if m.lower() in text.lower():
            return True
        try:
            return re.search(m, text, re.IGNORECASE) is not None
        except re.error:
            return False

    def _poll_file_triggers(self):
        """Compare watched paths' mtimes against the last snapshot (~20s cadence).
        The first poll only records the baseline — it never fires."""
        for t in self._trigger_tasks("file_change"):
            conf = json.loads(t.get("trigger_config") or "{}")
            base = Path(os.path.expanduser(conf.get("path") or ""))
            try:
                if conf.get("glob") and base.is_dir():
                    files = list(base.glob(conf["glob"]))
                elif base.is_dir():
                    files = [p for p in base.iterdir() if p.is_file()]
                else:
                    files = [base] if base.exists() else []
                cur = {str(p): p.stat().st_mtime for p in files}
            except Exception:
                continue
            prev = self._file_state.get(t["id"])
            self._file_state[t["id"]] = cur
            if prev is None or cur == prev:
                continue
            changed = [p for p in cur if prev.get(p) != cur[p]] + [p for p in prev if p not in cur]
            self._fire(t, "changed: " + ", ".join(sorted(changed)[:5]))

    def _poll_idle_triggers(self):
        """Fire idle triggers when no chat turn has happened for N minutes —
        at most once per idle period (re-armed by the next turn)."""
        from . import knowledge
        last = knowledge.last_turn_ts()
        now = time.time()
        for t in self._trigger_tasks("idle"):
            conf = json.loads(t.get("trigger_config") or "{}")
            mins = float(conf.get("minutes") or 30)
            if now - last < mins * 60 or self._idle_fired.get(t["id"]) == last:
                continue
            if self._fire(t, f"no user activity for {int((now - last) // 60)} min"):
                self._idle_fired[t["id"]] = last

    async def fire_login(self):
        """Session start ≈ login (called by the server in de/kiosk mode)."""
        for t in self._trigger_tasks("login"):
            self._fire(t, "session start (login)")

    # ---- execution ----------------------------------------------------------

    async def run_prompt(self, prompt: str, origin: str = "schedule",
                         title: str = "", space_id: str = "") -> tuple[str, str]:
        """The background-chat path: one headless agent turn, persisted as a
        conversation tagged with its origin so OS-initiated turns are countable.
        A job that belongs to a project runs inside it, so what it learns and
        produces is filed there rather than in the user's global memory.
        Returns (conversation_id, result_text)."""
        async def emit(_ev):  # headless: step events are dropped
            pass

        async def approver(_name, _args, _reason, _offer=None) -> bool:
            # No one is watching: only 'full' autonomy may take risky actions.
            return self.cfg.get("autonomy") == "full"

        model = self.cfg.get("default_model") or ""
        result_text = ""
        tokens = {"input": 0, "output": 0}
        steps = 0
        try:
            from . import config as _cfgmod
            from . import executors as execmod
            engine = execmod.resolve_engine(self.cfg)
            if engine != "aria":
                # Scheduled and proactive turns are work this machine was asked to
                # do, so a forwarder forwards them too — otherwise "forward
                # everything" would quietly exclude everything that runs unattended.
                result_text, _run = await execmod.forward(
                    engine, prompt, self.cfg, str(_cfgmod.AGENTOS_HOME / "workspace"))
                result_text = result_text or "(no output)"
                steps = 1
            else:
                agent = Agent(self.cfg, self.toolbox, model, emit, approver,
                              surface="task", space_id=space_id)
                result = await agent.run([{"role": "user", "content": prompt}])
                result_text = result["content"] or "(no output)"
                tokens = result.get("tokens") or tokens
                steps = len(result.get("steps") or [])
        except Exception as e:
            result_text = f"[error] {type(e).__name__}: {e}"

        # log the run as a conversation so it shows up in the UI — tagged with its
        # origin, which is what "% of turns initiated by the OS" counts
        cid = self.store.create_conversation(title or f"⏱ {prompt[:40]}", origin=origin,
                                             space_id=space_id)
        self.store.add_message(cid, "user", f"[{origin}] {prompt}")
        self.store.add_message(cid, "assistant", result_text)
        try:
            self.store.log("turn", prompt[:200],
                           {"conversation_id": cid, "model": model, "origin": origin,
                            "steps": steps, "in": tokens.get("input", 0),
                            "out": tokens.get("output", 0)})
        except Exception:
            pass
        return cid, result_text

    def _reschedule(self, task: dict, result_text: str):
        now = time.time()
        updates = {"last_run": now, "last_result": (result_text or "")[:4000]}
        if task["schedule_type"] == "interval":
            updates["next_run"] = now + (task["interval_seconds"] or 3600)
        elif task["schedule_type"] == "daily":
            updates["next_run"] = _next_daily(task["at_time"] or "09:00", now)
        elif task["schedule_type"] == "trigger":
            pass  # event-driven: stays enabled, next_run stays NULL
        else:
            updates["next_run"] = None
            updates["enabled"] = 0
        self.store.update_task(task["id"], **updates)

    async def _run_task(self, task: dict, origin: str = "schedule", title: str = ""):
        await self.broadcast({"type": "task_started", "task_id": task["id"], "prompt": task["prompt"]})

        # A task that names a flow starts that flow's master orchestrator instead of a
        # bare headless turn. The clock, the claim-on-fire and the cooldown above are the
        # same ones every other scheduled thing uses — only the thing being started differs.
        if (task.get("flow") or "") and self.fabric:
            flow = self.store.get_flow(task["flow"])
            if flow and flow.get("enabled"):
                res = await self.fabric.run_flow(
                    flow, task.get("prompt") or flow.get("mission", ""),
                    origin={"surface": "task", "ref": task["id"]},
                    space_id=task.get("space_id") or flow.get("space_id") or "")
                self._reschedule(task, res.get("content", ""))
                await self.broadcast({"type": "task_finished", "task_id": task["id"],
                                      "conversation_id": "", "run_id": res.get("run_id", ""),
                                      "result": (res.get("content") or "")[:500]})
                return
            self.store.log("error",
                           f"task {task['id']} names flow '{task['flow']}', which is gone or "
                           f"disabled — nothing ran", {"task": task["id"], "flow": task["flow"]})
            self._reschedule(task, f"[skipped] flow '{task['flow']}' is gone or disabled")
            return

        prompt = (f"[Scheduled background JOB — no user is present, do not ask questions. Work until the "
                  f"deliverable exists. If it produces findings, call `save_report` to save an HTML report "
                  f"(and set to_telegram=true to deliver it), or use `telegram_send`/`notify` to alert the "
                  f"user. Don't stop after only gathering data.]\n\n{task['prompt']}")
        cid, result_text = await self.run_prompt(prompt, origin=origin,
                                                 title=title or f"⏱ {task['prompt'][:40]}",
                                                 space_id=task.get("space_id") or "")

        self._reschedule(task, result_text)
        await self.broadcast({"type": "task_finished", "task_id": task["id"],
                              "conversation_id": cid, "result": result_text[:500]})

    async def run_forever(self):
        while not self._stop.is_set():
            try:
                for task in self.store.due_tasks(time.time()):
                    # claim it immediately so a slow run can't double-fire
                    self.store.update_task(task["id"], next_run=None)
                    self._launch(task, origin="schedule")
                self._poll_file_triggers()
                self._poll_idle_triggers()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass

    def stop(self):
        self._stop.set()
