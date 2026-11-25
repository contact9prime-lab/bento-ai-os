"""The teacher's desk: the parts of Train that need a brain and time (slm.py has neither).

Three long things run here as tasks of the server, each for the account that started it:
a teacher WRITING examples for a task (synthetic data), a teacher ANSWERING prompts that
came without answers, and a RUN that takes a goal in words all the way to a checked model
(doneitrightai's Autopilot, with a teacher where it had keyword rules).

The teacher is `executors.ask_fenced`: the machine's brain with none of its tools, or a
provider model the person named. A dataset from the Hub is other people's words, and they
reach a model that can do nothing but write an answer. Every call is counted in Usage at
the door like any other.

Nothing threads a user through: a task is created inside the request (or the tool call)
that asked, so it inherits that account, and `self.base()` resolves its home each time.
"""

import asyncio
import contextlib
import time

from . import slm
from . import users as usersmod

POLL_S = 3


class Desk:
    def __init__(self, cfg, toolbox, tell=None, ask=None):
        self._cfg = cfg                  # a callable: the CURRENT account's config
        self._ask = ask                  # a terminal's own asker (no server, so no fenced run)
        self.toolbox = toolbox
        self.tell = tell                 # async (event, uid)
        self.tasks: dict[tuple, asyncio.Task] = {}
        self.stops: set[tuple] = set()

    # ---- plumbing --------------------------------------------------------------------

    def base(self):
        return slm.root(usersmod.home_for(usersmod.current() or ""))

    def _key(self, ident: str) -> tuple:
        return (usersmod.current() or "", ident)

    def working(self, ident: str) -> bool:
        t = self.tasks.get(self._key(ident))
        return bool(t and not t.done())

    async def _say(self, what: str, ident: str, **more):
        if self.tell:
            with contextlib.suppress(Exception):
                await self.tell({"type": "train", "what": what, "id": ident, **more}, usersmod.current() or "")

    def _start(self, ident: str, coro) -> None:
        key = self._key(ident)
        self.stops.discard(key)
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks[key] = task
        task.add_done_callback(lambda _t: (self.tasks.pop(key, None), self.stops.discard(key)))

    def stop(self, ident: str) -> bool:
        """Ask a writing, answering or run task to stop after the call it is in."""
        key = self._key(ident)
        if key in self.tasks:
            self.stops.add(key)
            return True
        return False

    def asker(self, teacher: str = ""):
        """`ask(system, prompt) -> (text, why_not)` for slm's teaching functions."""
        if self._ask:
            return self._ask
        from . import executors
        cfg, box = self._cfg(), self.toolbox

        async def ask(system: str, prompt: str):
            text, _who, why = await executors.ask_fenced(
                cfg, box, [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                model=teacher or "", surface="train", timeout=300)
            return text, why
        return ask

    def teacher_name(self, teacher: str = "") -> tuple[str, str]:
        """(who would teach, why nobody can)."""
        from . import executors
        engine, model, why = executors.fenced_brain(self._cfg(), teacher or "")
        if why:
            return "", why
        return (model if engine == "aria" else f"{engine}" + (f" ({model})" if model else "")), ""

    # ---- what the lists show ---------------------------------------------------------

    def datasets(self) -> list[dict]:
        """Datasets, with one a stop of the server left half-made shown as it is."""
        out = []
        base = self.base()
        for d in slm.datasets(base):
            if d.get("state") in ("writing", "answering") and not self.working(d["id"]):
                d = slm.update_dataset(base, d["id"], state="ready",
                                       note=d.get("note") or "Bento stopped while the teacher was at work. What it had made is kept.")
            out.append(d)
        return out

    def runs(self) -> list[dict]:
        base = self.base()
        out = []
        for r in slm.runs(base):
            if r.get("state") == "running" and not self.working(r["id"]):
                r = slm.run_step(base, r["id"], "Interrupted", "Bento stopped while this was under way.", state="stopped")
            out.append(r)
        return out

    # ---- a teacher writes examples ---------------------------------------------------

    def synth(self, name: str, task: str, n: int, examples: list[dict] | None = None,
              teacher: str = "") -> dict:
        task = slm.plain(task, 4000)
        if not task:
            raise ValueError("Say what the model should learn to do.")
        who, why = self.teacher_name(teacher)
        if why:
            raise ValueError("No teacher can write examples: " + why)
        n = max(1, min(int(n or 100), slm.MAX_TEACH))
        base = self.base()
        ds = slm.add_dataset(base, name or "written examples", list(examples or []), "synthetic", who,
                             system=task, state="writing")
        slm.update_dataset(base, ds["id"], teacher=who, progress={"done": 0, "want": n})
        self._start(ds["id"], self._synth(ds["id"], task, n, list(examples or []), teacher))
        return slm.dataset(base, ds["id"])

    async def _synth(self, ident: str, task: str, n: int, examples: list[dict], teacher: str) -> dict:
        base, key = self.base(), self._key(ident)
        made = list(examples)

        def on_rows(new):
            made.extend(new)
            slm.update_dataset(base, ident, made, progress={"done": len(made) - len(examples), "want": n})
            asyncio.get_running_loop().create_task(self._say("dataset", ident))
        note = ""
        try:
            got = await slm.synth(task, n, self.asker(teacher), examples, on_rows, lambda: key in self.stops)
            note = ("" if not got["why"] else "Stopped." if got["why"] == "stopped" else
                    "The teacher stopped early: " + got["why"])
        except Exception as e:
            note = f"The teacher stopped early: {type(e).__name__}: {e}"[:300]
        ds = slm.update_dataset(base, ident, state="ready", note=note, progress={})
        await self._say("dataset", ident)
        return ds

    # ---- a teacher answers prompts ---------------------------------------------------

    def label(self, ident: str, teacher: str = "", redo: bool = False, task: str | None = None) -> dict:
        base = self.base()
        ds = slm.dataset(base, ident)
        if ds.get("state") != "ready":
            raise ValueError("The teacher is already at work on that dataset.")
        who, why = self.teacher_name(teacher)
        if why:
            raise ValueError("No teacher can answer them: " + why)
        if task is not None:
            ds = slm.update_dataset(base, ident, system=slm.plain(task, 4000))
        todo = ds["rows"] if redo else ds["rows"] - ds.get("answers", 0)
        if todo <= 0:
            raise ValueError("Every prompt in that dataset already has an answer.")
        slm.update_dataset(base, ident, state="answering", teacher=who,
                           progress={"done": 0, "want": min(todo, slm.MAX_TEACH)})
        self._start(ident, self._label(ident, teacher, redo))
        return slm.dataset(base, ident)

    async def _label(self, ident: str, teacher: str, redo: bool) -> dict:
        base, key = self.base(), self._key(ident)
        rows = slm.rows(base, ident)
        ds = slm.dataset(base, ident)
        last = {"at": 0.0}

        def on_row(done, want):
            if time.time() - last["at"] > 2 or done == want:       # a file write per answer wears a card out
                last["at"] = time.time()
                slm.update_dataset(base, ident, rows, progress={"done": done, "want": want})
                asyncio.get_running_loop().create_task(self._say("dataset", ident))
        note = ""
        try:
            got = await slm.label(rows, ds.get("system", ""), self.asker(teacher), on_row,
                                  lambda: key in self.stops, redo)
            note = ("" if not got["why"] else "Stopped." if got["why"] == "stopped" else
                    "The teacher stopped early: " + got["why"])
        except Exception as e:
            note = f"The teacher stopped early: {type(e).__name__}: {e}"[:300]
        out = slm.update_dataset(base, ident, rows, state="ready", note=note, progress={})
        await self._say("dataset", ident)
        return out

    # ---- a goal, taken all the way ---------------------------------------------------

    async def plan(self, goal: str, teacher: str = "") -> dict:
        """What a run for this goal would do, before anything is spent. The teacher drafts
        it; with no teacher, the words do, and `how` says which happened."""
        goal = slm.plain(goal, 2000)
        if not goal:
            raise ValueError("Say what the model should do.")
        who, why = self.teacher_name(teacher)
        plan = slm.plan_from_words(goal)
        if not why:
            text, err = await self.asker(teacher)(slm.PLAN_SYSTEM, slm.plan_prompt(goal))
            if not err:
                plan = slm.read_plan(text, goal)
        plan["teacher"] = who
        plan["teacher_missing"] = why
        plan["base"] = slm.base_for(plan)
        plan["calls"] = (plan["examples"] + slm.TEACH_BATCH - 1) // slm.TEACH_BATCH if plan["source"] == "synthetic" else 0
        return plan

    def run(self, goal: str, plan: dict, teacher: str = "") -> dict:
        """Start a run from a plan the person has seen. Raises ValueError when it can't."""
        if not slm.ready():
            raise ValueError(slm.why_not())
        if (b := slm.busy()):
            raise ValueError(f"Another training is running on this machine ({b.get('name') or 'a job'}). It finishes first.")
        who, why = self.teacher_name(teacher)
        if why:
            raise ValueError("A run needs a teacher, and none can answer: " + why)
        clean = {"name": slm.name_of(plan.get("name"), "my model"), "task": slm.plain(plan.get("task"), 2000),
                 "source": "hub" if plan.get("source") == "hub" else "synthetic",
                 "hub_query": slm.plain(plan.get("hub_query"), 80), "hub_repo": slm.plain(plan.get("hub_repo"), 120),
                 "examples": min(max(int(plan.get("examples") or 200), 20), 1000),
                 "size": plan.get("size") if plan.get("size") in slm.SIZES else "small",
                 "seeds": [slm.plain(s, 400) for s in (plan.get("seeds") or []) if isinstance(s, str)][:5],
                 "base": plan.get("base") if not slm.base_problem(plan.get("base") or "") else "",
                 "teacher": who, "epochs": slm.clean_hp({"epochs": plan.get("epochs")})["epochs"]}
        if not clean["task"]:
            raise ValueError("The plan has no task.")
        clean["base"] = clean["base"] or slm.base_for(clean)
        base = self.base()
        r = slm.run_new(base, goal, clean)
        self._start(r["id"], self._run(r["id"], clean, teacher))
        return r

    async def _run(self, rid: str, plan: dict, teacher: str) -> None:
        base, key = self.base(), self._key(rid)
        stopped = lambda: key in self.stops          # noqa: E731

        async def step(title, detail="", **f):
            slm.run_step(base, rid, title, detail, **f)
            await self._say("run", rid)
        try:
            await step("Planned", f"{plan['name']}: {plan['task']}  Student: {plan['base']}. Teacher: {plan['teacher']}.")
            ds = None
            if plan["source"] == "hub":
                ds = await self._from_hub(plan, step, stopped, teacher)
            if ds is None:
                seeds = [{"prompt": s, "response": ""} for s in plan["seeds"]]
                await step("Writing examples", f"The teacher writes {plan['examples']} examples of the task.")
                made: list[dict] = []
                did = slm.add_dataset(base, plan["name"], [], "synthetic", plan["teacher"], system=plan["task"],
                                      state="writing")["id"]
                slm.run_step(base, rid, "", dataset=did)

                def on_rows(new):
                    made.extend(new)
                    slm.update_dataset(base, did, made, progress={"done": len(made), "want": plan["examples"]})
                    slm.run_step(base, rid, "Writing examples", f"{len(made)} of {plan['examples']} written.", same=True)
                    asyncio.get_running_loop().create_task(self._say("run", rid))
                got = await slm.synth(plan["task"], plan["examples"], self.asker(teacher), seeds, on_rows, stopped)
                ds = slm.update_dataset(base, did, state="ready", progress={},
                                        note="" if not got["why"] or got["why"] == "stopped" else "The teacher stopped early: " + got["why"])
                if len(made) < slm.MIN_ROWS + 1:
                    raise RuntimeError("The teacher wrote too few examples to train on" +
                                       (": " + got["why"] if got["why"] and got["why"] != "stopped" else "."))
                await step("Wrote examples", f"{len(made)} examples in {got["calls"]} calls to the teacher.", same=True)
            if stopped():
                raise asyncio.CancelledError()
            job = slm.start_job(base, plan["name"], ds["id"], plan["base"], {"epochs": plan["epochs"]},
                                owner=usersmod.current() or "")
            await step("Training", f"{job['rows']} examples to learn from, {job['held']} held back.", job=job["id"])
            while True:
                await asyncio.sleep(POLL_S)
                job = slm.job(base, job["id"])
                if job["state"] != "running":
                    break
                if stopped():
                    slm.stop_job(base, job["id"])
                    raise asyncio.CancelledError()
                slm.run_step(base, rid, "Training", job["phase"] + (f", step {job['step']} of {job['total']}" if job["total"] else ""), same=True)
                await self._say("run", rid)
            if job["state"] != "done":
                raise RuntimeError("Training " + job["state"] + (": " + job["error"] if job["error"] else "."))
            m = slm.model(base, job["id"])
            await step("Checked", m["verdict"]["words"], model=m["id"], state="done")
        except asyncio.CancelledError:
            slm.run_step(base, rid, "Stopped", "You stopped it. What was made so far is kept.", state="stopped")
            await self._say("run", rid)
        except Exception as e:
            slm.run_step(base, rid, "Stopped", str(e)[:500] or type(e).__name__, state="failed")
            await self._say("run", rid)

    async def _from_hub(self, plan: dict, step, stopped, teacher: str = ""):
        """A public dataset for the plan, or None (the run then has examples written).
        The first few search results are tried; one whose rows don't read as prompts, or
        that the Hub can't serve, is passed over and named."""
        base = self.base()
        try:
            found = ([{"repo": plan["hub_repo"]}] if plan.get("hub_repo") else
                     await asyncio.to_thread(slm.hub_search, plan["hub_query"], 6))
        except Exception as e:
            await step("Searched the Hub", f"The search failed ({str(e)[:160]}), so examples are written.")
            return None
        skipped = []
        for cand in [c for c in found if not c.get("gated")][:4]:
            if stopped():
                return None
            try:
                ds = await asyncio.to_thread(slm.import_hub, base, cand["repo"], plan["name"], "", "",
                                             plan["examples"], None, plan["task"])
            except Exception as e:
                skipped.append(f"{cand['repo']} ({str(e)[:80]})")
                continue
            if ds["rows"] < slm.MIN_ROWS + 1:
                slm.delete_dataset(base, ds["id"])
                skipped.append(f"{cand['repo']} (too few rows)")
                continue
            await step("Imported from the Hub", f"{cand['repo']}: {ds['rows']} rows, {ds['answers']} with an answer."
                       + (" Passed over: " + "; ".join(skipped[:3]) + "." if skipped else ""), dataset=ds["id"])
            if ds["answers"] < ds["rows"]:
                await step("Answering", f"The teacher answers {ds['rows'] - ds['answers']} prompts.")
                rows = slm.rows(base, ds["id"])
                got = await slm.label(rows, plan["task"], self.asker(teacher), None, stopped)
                ds = slm.update_dataset(base, ds["id"], rows)
                await step("Answered", f"{got['answered']} of {got['asked']} prompts answered by the teacher."
                           + (" It stopped early: " + got["why"] if got["why"] and got["why"] != "stopped" else ""))
            return ds
        await step("Searched the Hub", "No public dataset fitted" + (" (" + "; ".join(skipped[:3]) + ")" if skipped else "")
                   + ", so examples are written.")
        return None
