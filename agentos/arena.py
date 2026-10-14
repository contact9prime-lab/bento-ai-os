"""The Arena: one task, two or four brains, side by side, and what each one cost.

Every brain this machine can run is already in one list (`executors.brains`): local and
cloud models, and the agent CLIs installed here. The Arena hands the SAME task to two or
four of them at once and shows each one working in its own pane, with a live HUD —
tokens a second, tokens, money, refusals by the gate, steps and time. It is the honest
way to answer "which model should run this?" on this machine, with these tools.

Five rules keep it honest:

- **A contender is a brain from the list, never free text.** `contenders()` reads each
  pick against `brains()` (an available executor and one of ITS models), the closed-set
  rule `set_brain` keeps; a pick that is not there is refused in a sentence.
- **Each contender works in its own folder** (`<workspace>/arena/<id>/<slot>-<name>`), so
  two answers never write over each other. A folder is not a jail: a shell command
  reaches what the machine's sandbox allows, and the window says so (the hands rule).
- **Every tool call still passes the gate**, under the person's own autonomy, because an
  arena run is the person's act. Refusals are counted from what the gate said
  (`[denied]` on the step, and an agent CLI's own denials), never guessed.
- **The HUD measures; it never judges.** Speed, cost and refusals are numbers; which
  answer is BETTER is the person's call, and `summary()` never names a winner on quality.
- **Kept per person and bounded**: `KEEP` arenas in `arena/` in their own home, with each
  contender's transcript in its own conversation, so it can be opened in Chat.

Stdlib only, no HTTP and no asyncio: the server runs the contenders, `bento arena` reads
the same records.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

MIN, MAX = 2, 4
KEEP = 20
TASK_MAX = 4000
LOG_KEEP = 40               # steps kept per contender in the record
STATUS = ("waiting", "running", "done", "error", "stopped")


class ArenaError(ValueError):
    """Refused in a sentence the person can act on."""


def _home(uid: str) -> Path:
    from . import users as usersmod
    return usersmod.home_for(uid or "")


def dir_for(uid: str = "") -> Path:
    return _home(uid) / "arena"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:32] or "brain"


def choices(brains: dict) -> list[dict]:
    """Every brain the Arena can seat: one row per available executor and model."""
    out = []
    for ex in (brains or {}).get("executors") or []:
        if not ex.get("available"):
            continue
        for m in ex.get("models") or []:
            mid = m.get("id", "")
            if ex.get("kind") == "provider" and not mid:
                continue
            out.append({"executor": ex["id"], "model": mid, "kind": ex.get("kind", ""),
                        "engine": ex.get("engine") or ("aria" if ex.get("kind") == "provider" else ex["id"]),
                        "label": label(ex.get("name") or ex["id"], m.get("name") or mid)})
    return out


def label(name: str, model: str) -> str:
    model = str(model or "")
    short = model.split("/", 1)[-1] if "/" in model else model
    return f"{name} · {short}" if short else f"{name} · its own setting"


def contenders(brains: dict, picks: list) -> list[dict]:
    """Read the picks against the machine's brains. Two to four; each one available.
    The same brain twice is allowed (it shows how much a run varies) and numbered."""
    if not isinstance(picks, list) or not (MIN <= len(picks) <= MAX):
        raise ArenaError(f"An arena seats {MIN} to {MAX} brains.")
    have = {(c["executor"], c["model"]): c for c in choices(brains)}
    out, seen = [], {}
    for i, p in enumerate(picks):
        key = (str((p or {}).get("executor", "")), str((p or {}).get("model", "")))
        c = have.get(key)
        if not c:
            names = ", ".join(sorted({x["label"] for x in have.values()})[:8]) or "none"
            raise ArenaError(f"Brain {i + 1} ({key[1] or key[0] or 'empty'}) is not one this machine can "
                             f"run right now. Available: {names}.")
        seen[c["label"]] = seen.get(c["label"], 0) + 1
        lab = c["label"] + (f" #{seen[c['label']]}" if seen[c["label"]] > 1 else "")
        out.append({**c, "label": lab, "slot": i})
    return out


def new(task: str, seats: list[dict], workspace: str) -> dict:
    task = " ".join(str(task or "").split()) if "\n" not in str(task or "") else str(task).strip()
    if not task:
        raise ArenaError("Give the arena a task: every brain gets the same one.")
    if len(task) > TASK_MAX:
        raise ArenaError(f"Keep the task under {TASK_MAX} characters.")
    aid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    root = Path(workspace).expanduser() / "arena" / aid
    seats = [{**s, "folder": str(root / f"{s['slot'] + 1}-{_slug(s['label'])}"), "status": "waiting",
              "conversation_id": "", "started": 0.0, "first_token": 0.0, "finished": 0.0,
              "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "priced": True, "refused": 0,
              "asked": 0, "steps": 0, "answer": "", "error": "", "files": []} for s in seats]
    return {"id": aid, "task": task, "created": time.time(), "folder": str(root),
            "contenders": seats, "status": "running"}


def save(uid: str, arena: dict) -> None:
    d = dir_for(uid)
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{arena['id']}.tmp"
        tmp.write_text(json.dumps(arena))
        tmp.replace(d / f"{arena['id']}.json")
        for old in sorted(d.glob("*.json"))[:-KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def load(uid: str, aid: str) -> dict | None:
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", str(aid or "")):
        return None
    try:
        return json.loads((dir_for(uid) / f"{aid}.json").read_text())
    except (OSError, ValueError):
        return None


def recent(uid: str = "", n: int = 10) -> list[dict]:
    rows = []
    for p in sorted(dir_for(uid).glob("*.json"), reverse=True)[:n]:
        try:
            a = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        rows.append({"id": a["id"], "task": a["task"][:140], "created": a["created"], "status": a.get("status"),
                     "brains": [c["label"] for c in a.get("contenders", [])]})
    return rows


def hud(c: dict, now: float | None = None) -> dict:
    """The numbers a pane shows. Tokens a second counts output tokens over the time since
    the brain's first output (a word or a tool call), so a slow start is time, not speed."""
    now = now or time.time()
    end = c.get("finished") or now
    start = c.get("started") or end
    gen_from = c.get("first_token") or start
    gen_s = max(0.0, end - gen_from)
    out = int(c.get("tokens_out") or 0)
    return {"seconds": round(max(0.0, end - start), 1),
            "first_token_s": round(c["first_token"] - start, 1) if c.get("first_token") and start else None,
            "tok_s": round(out / gen_s, 1) if out and gen_s >= 0.5 else None,
            "tokens_in": int(c.get("tokens_in") or 0), "tokens_out": out,
            "cost": round(float(c.get("cost") or 0), 4), "priced": bool(c.get("priced", True)),
            "refused": int(c.get("refused") or 0), "asked": int(c.get("asked") or 0),
            "steps": int(c.get("steps") or 0), "files": len(c.get("files") or [])}


def files_in(folder: str, limit: int = 40) -> list[str]:
    root = Path(folder)
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
            out.append(str(p.relative_to(root)))
            if len(out) >= limit:
                break
    return out


def summary(arena: dict) -> dict:
    """Who finished first, who spent least, who was refused least. Numbers only: the
    better answer is the person's call, so no line here says "won"."""
    done = [c for c in arena.get("contenders", []) if c.get("status") == "done"]
    lines = []
    if done:
        fast = min(done, key=lambda c: hud(c)["seconds"])
        lines.append(f"First to finish: {fast['label']} ({hud(fast)['seconds']} s)")
        priced = [c for c in done if c.get("priced", True)]
        if priced:
            cheap = min(priced, key=lambda c: c.get("cost") or 0)
            lines.append(f"Spent least: {cheap['label']} (${(cheap.get('cost') or 0):.4f})")
        quick = [c for c in done if hud(c)["tok_s"]]
        if quick:
            q = max(quick, key=lambda c: hud(c)["tok_s"])
            lines.append(f"Fastest output: {q['label']} ({hud(q)['tok_s']} tok/s)")
        least = min(done, key=lambda c: c.get("refused") or 0)
        if any((c.get("refused") or 0) for c in done):
            lines.append(f"Fewest refusals: {least['label']} ({least.get('refused') or 0})")
    return {"lines": lines, "done": len(done), "of": len(arena.get("contenders", []))}


def text(arena: dict) -> str:
    rows = [f"Arena {arena['id']}: {arena['task'][:120]}"]
    for c in arena.get("contenders", []):
        h = hud(c)
        cost = f"${h['cost']:.4f}" if h["priced"] else "unpriced"
        rows.append(f"  {c['slot'] + 1}. {c['label']:<34} {c['status']:<8} {h['seconds']:>6}s "
                    f"{(str(h['tok_s']) + ' tok/s') if h['tok_s'] else '—':>12} {h['tokens_out']:>6} out "
                    f"{cost:>10}  refused {h['refused']}  steps {h['steps']}")
        if c.get("error"):
            rows.append(f"     {c['error'][:160]}")
    for ln in summary(arena)["lines"]:
        rows.append("  " + ln)
    return "\n".join(rows)
