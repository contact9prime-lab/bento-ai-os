"""Background scheduler: runs stored tasks as headless agent turns."""

import asyncio
import datetime
import time

from .agent import Agent


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
        self._stop = asyncio.Event()

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

    async def _run_task(self, task: dict):
        await self.broadcast({"type": "task_started", "task_id": task["id"], "prompt": task["prompt"]})

        async def emit(_ev):  # headless: step events are dropped
            pass

        async def approver(_name, _args, _reason) -> bool:
            # No one is watching: only 'full' autonomy may take risky actions.
            return self.cfg.get("autonomy") == "full"

        model = self.cfg.get("default_model") or ""
        result_text = ""
        try:
            agent = Agent(self.cfg, self.toolbox, model, emit, approver)
            prompt = (f"[Scheduled background JOB — no user is present, do not ask questions. Work until the "
                      f"deliverable exists. If it produces findings, call `save_report` to save an HTML report "
                      f"(and set to_telegram=true to deliver it), or use `telegram_send`/`notify` to alert the "
                      f"user. Don't stop after only gathering data.]\n\n{task['prompt']}")
            result = await agent.run([{"role": "user", "content": prompt}])
            result_text = result["content"] or "(no output)"
        except Exception as e:
            result_text = f"[error] {type(e).__name__}: {e}"

        now = time.time()
        updates = {"last_run": now, "last_result": result_text[:4000]}
        if task["schedule_type"] == "interval":
            updates["next_run"] = now + (task["interval_seconds"] or 3600)
        elif task["schedule_type"] == "daily":
            updates["next_run"] = _next_daily(task["at_time"] or "09:00", now)
        else:
            updates["next_run"] = None
            updates["enabled"] = 0
        self.store.update_task(task["id"], **updates)

        # log the run as a conversation so it shows up in the UI
        cid = self.store.create_conversation(f"⏱ {task['prompt'][:40]}")
        self.store.add_message(cid, "user", f"[scheduled task] {task['prompt']}")
        self.store.add_message(cid, "assistant", result_text)
        await self.broadcast({"type": "task_finished", "task_id": task["id"],
                              "conversation_id": cid, "result": result_text[:500]})

    async def run_forever(self):
        while not self._stop.is_set():
            try:
                for task in self.store.due_tasks(time.time()):
                    # claim it immediately so a slow run can't double-fire
                    self.store.update_task(task["id"], next_run=None)
                    asyncio.create_task(self._run_task(task))
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass

    def stop(self):
        self._stop.set()
