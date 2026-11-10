"""Filling a blueprint in, part by part, after its outline is on the Stage.

Asked for after the first live blueprints came back thin: "it's not detailed enough … the
output isn't good enough". Measured on them: 40 parts but about one fact each, no "how it
works", five links, and nothing looked up. One answer that has to name every part of a
jet engine trades depth for speed every time. So a blueprint is built in two stages: the
agent shows the outline (stage.BP_LINE asks for it quickly), and this module asks the
machine's brain for each top-level part on its own, in parallel, with the web allowed, and
merges each answer into the scene as it arrives. The page repaints on `stage_fill`.

Five rules:
- Everything that comes back goes through stage's own cleaner (`_bp_parts`, `_bp_link`), so
  a fill can add nothing the closed set would refuse from the agent.
- A part keeps what placed it: its id, name, heights, width, status and evidence are the
  outline's. Only what it says about itself and what is inside it are replaced.
- The scene's node cap is shared: each part gets an equal slice of what is left.
- A fill that fails leaves the outline's part as it was and is named in `fill.failed`, so the
  page can say which parts are still thin and why. Nothing is retried on its own.
- `filling.until` bounds the "filling in" mark: a server stopped mid-fill leaves no part
  saying it is being filled forever.

No HTTP here. The brain is asked through executors (Claude Code, Gemini CLI or Codex with only
their web tools, or a provider model with none), so the words fetched are display only: they
reach a closed-set scene and nothing that acts.
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from . import stage as stagemod

PARALLEL = 4             # brains asked at once; each CLI is a process of a few hundred MB
PART_S = 300             # one part's answer
PHONE_WAIT_S = 240       # how long a phone's pictures wait for a blueprint to fill in
WEB_TOOLS = ("WebSearch", "WebFetch")
LINKS_PER_PART = 14
_SEM: dict = {}
_LOCKS: dict = {}
_TASKS: dict = {}        # scene id -> task, so a test or a phone send can wait on it

SYSTEM = ("You fill in ONE part of a blueprint that is on a person's screen. Answer with ONE JSON "
          "object and nothing else: no prose before or after it, no code fence.")

SHAPE = ('{"name": "<the same name>", "role": "what it is for, one sentence", '
         '"how": "how it works, two or three sentences", "made_of": "materials or what it consists of", '
         '"limits": "its limits, or how it fails", "facts": [{"label": "...", "value": "...", "unit": "..."}], '
         '"certainty": "known|estimated|unclear", "source": "where the numbers come from", '
         '"unknowns": ["what nobody outside can know"], "form": "exploded|flow|tower", '
         '"parts": [ the same fields for each part inside it, and "parts" again for the ones worth opening ], '
         '"links": [{"from": "<a part inside>", "to": "<another>", "verb": "feeds", "kind": "<kind>"}]}')


def wants(scene: dict) -> list[dict]:
    """The top-level parts worth filling in: every one that is thin or has little inside."""
    if scene.get("kind") != "blueprint":
        return []
    out = []
    for p in scene.get("parts") or []:
        inside = sum(1 for _ in stagemod.bp_walk(p.get("parts") or []))
        thin_kids = sum(1 for k, _ in stagemod.bp_walk(p.get("parts") or []) if stagemod.bp_thin(k))
        if stagemod.bp_thin(p) or inside < 6 or thin_kids * 2 > inside:
            out.append(p)
    return out


def prompt_for(scene: dict, part: dict, budget: int, web: bool) -> str:
    outline = "\n".join(f"- {p['name']}" + (f": {p['role']}" if p.get("role") else "")
                        for p in scene.get("parts") or [])
    have = {k: part.get(k) for k in ("name", "role", "how", "facts", "made_of", "from", "to", "width")
            if part.get(k) not in (None, "", [])}
    have["parts"] = [k["name"] for k in part.get("parts") or []]
    kids_form = "tower" if scene.get("form") == "tower" and part.get("from") is not None else ""
    return (f"The blueprint is of: {scene.get('subject') or scene.get('title')}\n"
            f"Its parts:\n{outline}\n\n"
            f"Fill in this part: {part['name']}\nWhat the outline says about it: "
            f"{json.dumps(have, ensure_ascii=False)}\n\n"
            f"Take it apart properly. Give it five to ten parts inside, and give the ones worth "
            f"opening four to eight parts of their own: a third level. At most {budget} parts in all "
            f"inside it. Every part says what it is for, how it works, what it is made of, its "
            f"limits, and three to six facts: real numbers with units (sizes, ratings, quantities, "
            f"temperatures, speeds, costs, dates). Name where the numbers come from in source, and "
            f"mark a number you worked out or remember loosely as certainty estimated. Never "
            f"invent a figure to fill a field: leave it out. Add links between the parts inside it "
            f"that say what flows from one to the other, with kind one of "
            f"{', '.join(stagemod.BP_FLOWS)}. Keep how and role short. "
            + ("Look the facts up on the web first (search, then read the best pages) and name the "
               "pages in source. " if web else "")
            + (f"Its parts are layers along the height: give each from and to in "
               f"{scene.get('unit') or 'the scene unit'}. " if kids_form else "")
            + f"\n\nThe shape:\n{SHAPE}")


def _json_of(text: str):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("the answer had no JSON in it")
    return json.loads(t[a:b + 1])


async def ask(cfg: dict, prompt: str) -> tuple[str, str, int]:
    """(text, who answered, pages looked up). Raises with a sentence when nothing answered."""
    from . import executors
    engine = executors.resolve_engine(cfg)
    if engine != "aria" and executors.drives(engine):
        looked = [0]

        async def seen(ev):
            if ev.get("type") == "tool_start" and str(ev.get("name") or "") in WEB_TOOLS:
                looked[0] += 1
        reply, _run = await asyncio.wait_for(executors.forward(
            engine, SYSTEM + "\n\n" + prompt, cfg, executors.default_workspace(cfg),
            emit=seen, tools=WEB_TOOLS), PART_S)
        if (reply or "").startswith("[error]"):
            raise RuntimeError(reply[7:].strip() or f"{engine} could not answer")
        return reply or "", engine, looked[0]
    text, who, why = await executors.ask_brain(cfg, SYSTEM, prompt, timeout=PART_S)
    if why:
        raise RuntimeError(why)
    return text, who, 0


def _ids(parts: list, skip: str = "") -> set:
    out = set()
    for p, _ in stagemod.bp_walk(parts):
        out.add(p["id"])
    if skip:
        top = next((p for p in parts if p["id"] == skip), None)
        if top:
            out -= {k["id"] for k, _ in stagemod.bp_walk(top.get("parts") or [])}
    return out


def merge(scene: dict, pid: str, obj: dict, budget: int) -> list[str]:
    """Put a fill's answer into `scene` in place. Returns what was dropped, by path."""
    top = next((p for p in scene.get("parts") or [] if p["id"] == pid), None)
    if top is None:
        raise ValueError("that part is no longer in the blueprint")
    if not isinstance(obj, dict):
        raise ValueError("the answer was not an object")
    dropped: list[str] = []
    # the part's own words, read by the same cleaner as the agent's
    me = stagemod._bp_parts([{**{k: v for k, v in obj.items() if k not in ("parts", "links")},
                              "name": top["name"]}], 1, "part", set(), [0], dropped)
    seen = _ids(scene["parts"], skip=pid)
    count = [stagemod.BP_NODES - budget]
    kids = stagemod._bp_parts(obj.get("parts"), 2, "part.parts", seen, count, dropped)
    if not kids:
        raise ValueError("the answer had no parts inside it")
    if me:
        for k in ("role", "how", "made_of", "limits", "detail", "facts", "source", "unknowns"):
            if me[0].get(k):
                top[k] = me[0][k]
        if obj.get("certainty") in stagemod.BP_CERTAINTY:
            top["certainty"] = obj["certainty"]
    old = {k["id"] for k, _ in stagemod.bp_walk(top.get("parts") or [])}
    top["parts"] = kids
    form = str(obj.get("form") or "").strip().lower()
    top["form"] = form if form in stagemod.BP_FORMS else stagemod._bp_form_of(kids)
    mine = {k["id"] for k, _ in stagemod.bp_walk(kids)}
    links = [ln for ln in scene.get("links") or [] if ln["from"] not in old and ln["to"] not in old]
    for i, ln in enumerate(stagemod._list(obj.get("links"))[:LINKS_PER_PART]):
        if not isinstance(ln, dict):
            continue
        a, b = stagemod._bp_ref(ln.get("from"), mine), stagemod._bp_ref(ln.get("to"), mine)
        if a and b and a != b:
            links.append(stagemod._bp_link(ln, a, b, f"part.links[{i}]", dropped))
    scene["links"] = links[:stagemod.BP_LINKS]
    return dropped


def _budgets(scene: dict, ids: list[str]) -> int:
    parts = scene.get("parts") or []
    fixed = sum(1 + sum(1 for _ in stagemod.bp_walk(p.get("parts") or []))
                for p in parts if p["id"] not in ids) + len(ids)
    return max(4, (stagemod.BP_NODES - fixed) // max(1, len(ids)))


def _save(store, sid: str, scene: dict) -> bool:
    cur = store.db.execute("UPDATE stage_scenes SET scene=? WHERE id=?", (json.dumps(scene), sid))
    store.db.commit()
    return cur.rowcount > 0


def _load(store, sid: str) -> dict | None:
    r = store.db.execute("SELECT scene FROM stage_scenes WHERE id=?", (sid,)).fetchone()
    return json.loads(r[0]) if r else None


def _sem() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _SEM:
        _SEM.clear()
        _SEM[loop] = asyncio.Semaphore(PARALLEL)
    return _SEM[loop]


def begin(store, row: dict) -> list[str]:
    """Mark what will be filled, on the stored scene and on `row`, before the page sees it.
    Returns the part ids; [] when there is nothing to fill."""
    scene = row["scene"]
    ids = [p["id"] for p in wants(scene)]
    if not ids:
        return []
    scene["filling"] = {"ids": ids, "until": round(time.time() + PART_S * (1 + len(ids) // PARALLEL) + 30)}
    scene["fill"] = {"done": [], "failed": [], "by": "", "looked_up": 0}
    _save(store, row["id"], scene)
    return ids


async def fill(store, cfg: dict, row: dict, send=None, asker=None) -> dict:
    """Fill in every part `begin` marked, each on its own, merging as each one lands.
    `send(event)` tells the screens; `asker(cfg, prompt)` stands in for the brain in tests."""
    sid = row["id"]
    scene = _load(store, sid) or row["scene"]
    ids = list((scene.get("filling") or {}).get("ids") or [])
    if not ids:
        return scene
    budget = _budgets(scene, ids)
    lock = _LOCKS.setdefault(sid, asyncio.Lock())
    asker = asker or ask

    async def one(pid: str):
        async with _sem():
            cur = _load(store, sid)
            part = next((p for p in (cur or {}).get("parts") or [] if p["id"] == pid), None)
            if cur is None or part is None:
                return
            why, got = "", None
            try:
                text, who, looked = await asker(cfg, prompt_for(cur, part, budget, True))
                got = (_json_of(text), who, looked)
            except asyncio.TimeoutError:
                why = f"took longer than {PART_S}s"
            except Exception as e:
                why = str(e) or type(e).__name__
        async with lock:
            cur = _load(store, sid)
            if cur is None:
                return
            if got:
                try:
                    merge(cur, pid, got[0], budget)
                    cur["fill"]["done"].append(pid)
                    cur["fill"]["by"] = got[1] or cur["fill"]["by"]
                    cur["fill"]["looked_up"] += got[2]
                except ValueError as e:
                    why = str(e)
            if why:
                cur["fill"]["failed"].append({"id": pid, "why": stagemod._s(why, 160)})
            fl = cur.get("filling") or {}
            fl["ids"] = [x for x in fl.get("ids") or [] if x != pid]
            if not fl["ids"]:
                cur.pop("filling", None)
            _save(store, sid, cur)
            if send:
                try:
                    await send({"type": "stage_fill", **{k: row[k] for k in
                                ("id", "conversation_id", "answer_to", "seq")}, "scene": cur})
                except Exception:
                    pass

    await asyncio.gather(*(one(pid) for pid in ids))
    _LOCKS.pop(sid, None)
    return _load(store, sid) or scene


def start(store, cfg: dict, row: dict, send=None) -> list[str]:
    """Begin filling in the background and return the part ids being filled. Called before
    the scene is sent, so the row the page gets already says which parts are filling."""
    ids = begin(store, row)
    if not ids:
        return []
    task = asyncio.create_task(fill(store, cfg, row, send))
    _TASKS[row["id"]] = task
    task.add_done_callback(lambda _t, sid=row["id"]: _TASKS.pop(sid, None))
    return ids


async def settle(scene_ids: list[str], timeout: float) -> None:
    """Wait up to `timeout` for these scenes to finish filling (a phone send waits on it)."""
    tasks = [_TASKS[s] for s in scene_ids if s in _TASKS]
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
