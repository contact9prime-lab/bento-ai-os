"""Jobs: the shortest path from a fresh install to something that runs by itself.

A **job is a flow**. This module invents nothing: it turns a recipe plus three or
four answers into a flow definition, and hands it to `flows.save`. The scheduler,
the permission gate, the audit ledger and the delivery sinks are the ones that
already exist. If a job could do something a flow cannot, that would be a second
permission system, and there is exactly one.

Why it exists at all: the gap between "installed" and "useful" is where this OS
is lost. A flow the user has to design themselves is a blank page; a flow they
pick from three and answer two questions about is a habit by Wednesday. The
catalogue below is deliberately tiny — three things that are unmistakably useful
on any machine, not a marketplace.

Two rules that are load-bearing:

- **Consent is shown before it is written, in the words of the thing being
  consented to.** `preview()` returns the exact `grants` rows saving would create
  (via `flows.declared_grants`, which is pure), and the folder question is asked
  as "which folder may I read", not as a text field that quietly becomes an
  `fs.read` grant. A job that reads ~/Downloads says so on the card.

- **Delivery is probed, never declared.** `deliveries()` asks the machine which
  ways out actually work right now. Offering Telegram on a machine with no bot
  token is how a first-run flow teaches somebody that this OS lies.

Three faces (per CLAUDE.md):
  GUI  the last beat of the first-run wizard, and the Jobs card in Workflows.
  TUI  `bento job` — list, `bento job add <recipe> ...`, `bento job run <name>`.
       This is the whole point of keeping the module HTTP-free and async-free.
  SUI  identical to GUI; a job is not a window, so there is nothing to reserve.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from . import flows as flowsmod

# ---------------------------------------------------------------------------
# What a recipe asks for
# ---------------------------------------------------------------------------


@dataclass
class Need:
    """One question a recipe asks before it can become a flow.

    `kind` is what the surface should draw, not what the value is: 'folder' is a
    string like every other answer, but a folder picker with the consent sentence
    beside it is a different thing from a text box, and the recipe is what knows
    which one this is.
    """

    key: str
    label: str
    kind: str = "text"            # text | folder | time | minutes | url | choice
    default: str = ""
    help: str = ""
    placeholder: str = ""
    choices: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "default": self.default, "help": self.help,
                "placeholder": self.placeholder, "choices": list(self.choices)}


@dataclass
class Recipe:
    id: str
    title: str                    # what it does, in the user's words
    blurb: str                    # one sentence, present tense
    example: str                  # what the first delivery actually looks like
    needs: list                   # list[Need] — always ends with the delivery question
    tools: list                   # tools the roster is granted
    roster: list                  # (subagent, why)
    mission: str                  # {answer} placeholders filled from the answers
    reads_path: str = ""          # which answer key is a folder that must be granted
    schedule: str = "daily"       # daily | interval | file_change
    icon: str = "◇"

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "blurb": self.blurb,
                "example": self.example, "icon": self.icon,
                "schedule": self.schedule, "reads_path": self.reads_path,
                "tools": list(self.tools),
                "roster": [r[0] for r in self.roster],
                "needs": [n.as_dict() for n in self.needs]}


# The delivery question every recipe ends with. Its choices are filtered by
# `deliveries()` against what this machine can actually do.
DELIVER = Need("deliver", "Where should it reach you?", kind="choice", default="report",
               help="You can change this later without touching the rest of the job.")

RECIPES: list[Recipe] = [
    Recipe(
        id="morning-brief",
        icon="☀",
        title="Brief me every morning",
        blurb="Reads up on the things you follow overnight and leaves one page waiting.",
        example="A page headed 'Tuesday' with four or five paragraphs — what moved, "
                "what is worth reading, and what needs you.",
        schedule="daily",
        needs=[
            Need("topics", "What should I keep an eye on?", kind="text",
                 placeholder="my industry, the two companies I compete with, rust releases",
                 help="Plain words. I will use what I already know about you to fill in "
                      "the rest."),
            Need("at", "When do you want it?", kind="time", default="08:00"),
            DELIVER,
        ],
        tools=["fetch_url", "save_report", "recall", "kg_query"],
        roster=[("researcher", "gathers and verifies the material"),
                ("writer", "writes the page itself")],
        mission="Every morning, produce ONE page for the user about: {topics}.\n\n"
                "Use `recall` and `kg_query` first to find out what they already care "
                "about, so this reads as if you know them. Then research: what actually "
                "changed since yesterday, what is worth their time, and anything that "
                "needs a decision from them. Verify before you write — an unsourced claim "
                "is worse than a shorter page.\n\n"
                "Keep it to one page. Lead with the thing that matters most. If nothing "
                "happened, say so in two lines rather than padding it out.",
    ),
    Recipe(
        id="folder-watch",
        icon="🗂",
        title="Watch a folder for me",
        blurb="Notices what lands in a folder you choose, works out what it is, and tells you.",
        example="'Three files arrived: an invoice from Acme (₹42,000, due 14 Aug), a "
                "signed contract, and a screenshot.'",
        schedule="file_change",
        reads_path="folder",
        needs=[
            Need("folder", "Which folder may I read?", kind="folder",
                 default="~/Downloads",
                 help="I am only granted permission to READ this one folder. Nothing "
                      "else on the machine, and nothing is moved or deleted."),
            DELIVER,
        ],
        tools=["read_file", "list_dir", "search_files"],
        roster=[("researcher", "reads what arrived and decides what it is")],
        mission="Something new appeared in {folder}. Work out what it is.\n\n"
                "Read the new files. For each one, say in a single line what it is and "
                "the one thing the user would want to know from it — a supplier, an "
                "amount and a due date for an invoice; the counterparty and the date for "
                "a contract; the subject for anything else.\n\n"
                "You may READ this folder and nothing else. Do not move, rename or delete "
                "anything. If a file is nothing worth mentioning, say nothing about it "
                "rather than describing it.",
    ),
    Recipe(
        id="page-watch",
        icon="◉",
        title="Tell me when a page changes",
        blurb="Checks a page you name and speaks up only when something real has changed.",
        example="'The pricing page changed: the Team plan went from $20 to $25 per seat.'",
        schedule="interval",
        needs=[
            Need("url", "Which page?", kind="url",
                 placeholder="https://example.com/pricing"),
            Need("minutes", "How often should I look?", kind="minutes", default="60",
                 help="Checking more often than the page changes just spends tokens."),
            DELIVER,
        ],
        tools=["fetch_url", "recall", "remember"],
        roster=[("researcher", "fetches the page and compares it to last time")],
        mission="Check {url} and report only REAL changes.\n\n"
                "Fetch the page. Use `recall` to find what it said last time you looked, "
                "and `remember` to store what it says now, so the next run has something "
                "to compare against.\n\n"
                "If nothing meaningful changed — a rotating banner, a timestamp, a "
                "different testimonial — finish silently and say 'no change'. Only speak "
                "up for something a person would want to know: a price, a term, a "
                "feature, an announcement. Quote the before and the after.",
    ),
]

BY_ID = {r.id: r for r in RECIPES}


# ---------------------------------------------------------------------------
# What this machine can actually do with a finished job
# ---------------------------------------------------------------------------

def deliveries(cfg: dict) -> list[dict]:
    """The ways out that work on THIS machine right now.

    Each entry carries `ready` and, when it is not, the sentence that says why and
    what would fix it. Nothing is hidden — a way out you cannot use yet is more
    useful shown greyed with its reason than absent, because absent reads as
    "this OS cannot do that".
    """
    tg = (cfg.get("telegram") or {})
    tg_ready = bool(tg.get("enabled") and tg.get("bot_token") and tg.get("owner_chat_id"))
    return [
        {"id": "report", "label": "Leave it in Reports",
         "detail": "Saved as a page in Files → reports. Always works.",
         "ready": True, "sink": "report", "tool": "save_report"},
        {"id": "notify", "label": "Notify me on this machine",
         "detail": "A desktop notification, if you are at the machine.",
         "ready": True, "sink": "notify", "tool": "notify"},
        {"id": "telegram", "label": "Message me on Telegram",
         "detail": "Reaches you wherever you are." if tg_ready else
                   "Needs a bot token and one /start — Settings → Channels → Telegram.",
         "ready": tg_ready, "sink": "telegram", "tool": "telegram_send"},
    ]


def delivery(cfg: dict, choice: str) -> dict:
    """One delivery option by id, falling back to Reports.

    Falling back rather than refusing is deliberate: a job whose Telegram was
    unpaired between the answer and the save should still exist and still deliver
    somewhere the user can find it. `install` reports the substitution.
    """
    opts = {d["id"]: d for d in deliveries(cfg)}
    d = opts.get(choice or "")
    if d and d["ready"]:
        return d
    return opts["report"]


# ---------------------------------------------------------------------------
# A recipe plus answers, as a flow definition
# ---------------------------------------------------------------------------

_SAFE_PATH = re.compile(r"^[^\0]{1,400}$")


def _folder(value: str) -> str:
    """A folder answer, as an absolute path, or ValueError with a sentence.

    Refused here rather than at grant time: `fs:` + a path that does not exist is
    a permission for nothing, and the person who could fix it is on the screen
    right now.
    """
    raw = (value or "").strip()
    if not raw or not _SAFE_PATH.match(raw):
        raise ValueError("pick a folder for me to watch")
    path = os.path.abspath(os.path.expanduser(raw))
    if not os.path.isdir(path):
        raise ValueError(f"there is no folder at {path} — pick one that exists")
    return path


def _minutes(value, default: int = 60) -> int:
    # `str(None)` is "None", which is truthy — so an unanswered question has to be
    # caught before the string, not after it, or the default never applies.
    raw = "" if value is None else str(value).strip()
    if not raw:
        return default
    try:
        n = int(float(raw))
    except ValueError:
        raise ValueError("how often, in minutes — a number like 60") from None
    return max(5, min(n, 60 * 24 * 7))


def _url(value: str) -> str:
    u = (value or "").strip()
    if not re.match(r"^https?://[^\s]+$", u):
        raise ValueError("that is not a web address — it should start with https://")
    return u[:500]


def _name_for(store, recipe: Recipe, answers: dict) -> str:
    """A flow name a person would recognise in a list of twenty."""
    hint = ""
    if recipe.reads_path:
        hint = os.path.basename(_folder(answers.get(recipe.reads_path, "")).rstrip("/"))
    elif recipe.id == "page-watch":
        hint = re.sub(r"^www\.", "", (_url(answers.get("url", "")).split("/")[2]))
    base = re.sub(r"[^A-Za-z0-9]+", "-", f"{recipe.id}-{hint}".strip("-")).strip("-").lower()[:44]
    base = base or recipe.id
    if store is not None and store.get_flow(base):
        return flowsmod._unique_name(store, base)
    return base


def build(cfg: dict, store, recipe_id: str, answers: dict) -> dict:
    """A complete, validated flow definition. Writes NOTHING.

    Pure enough to preview: this is what `preview()` runs the grant calculation
    over, so the consent shown on screen is computed from the same definition that
    is later saved rather than from a description of it.
    """
    recipe = BY_ID.get((recipe_id or "").strip())
    if not recipe:
        raise ValueError(f"no job recipe called '{recipe_id}'")
    answers = dict(answers or {})
    fill = {}
    perms: dict = {"tools": list(recipe.tools), "memory": "read-space",
                   "fs_read": [], "net": [], "skills": [], "fs_write": []}
    triggers: list[dict] = []

    if recipe.reads_path:
        folder = _folder(answers.get(recipe.reads_path, ""))
        fill[recipe.reads_path] = folder
        # The one grant the user was actually asked about, scoped to the folder they
        # picked and nothing above it.
        perms["fs_read"] = [os.path.join(folder, "*")]
        triggers.append({"kind": "os_event",
                         "config": {"event": "file_change", "path": folder},
                         "cooldown_secs": 120})
    if recipe.schedule == "daily":
        at = flowsmod._at_time(answers.get("at") or "08:00")
        triggers.append({"kind": "cron", "config": {"type": "daily", "at": at}})
    elif recipe.schedule == "interval":
        mins = _minutes(answers.get("minutes"), 60)
        fill["minutes"] = str(mins)
        triggers.append({"kind": "cron", "config": {"type": "interval", "minutes": mins}})

    if recipe.id == "page-watch":
        url = _url(answers.get("url", ""))
        fill["url"] = url
        perms["net"] = [url]
    if recipe.id == "morning-brief":
        topics = " ".join((answers.get("topics") or "").split())[:400]
        if not topics:
            raise ValueError("tell me what to keep an eye on — a few words is enough")
        fill["topics"] = topics
        perms["net"] = ["*"]      # research means the open web; say so on the card

    dev = delivery(cfg, answers.get("deliver") or "report")
    if dev["tool"] not in perms["tools"]:
        perms["tools"].append(dev["tool"])
    if dev["id"] == "telegram" and "save_report" not in perms["tools"]:
        # A page that will not fit in a message still has to land somewhere.
        perms["tools"].append("save_report")

    mission = recipe.mission.format(**fill)
    mission += f"\n\nDELIVER IT: {_deliver_line(dev)}"

    return {
        "name": _name_for(store, recipe, answers),
        "description": recipe.blurb,
        "mission": mission,
        "roster": [{"subagent": s, "why": why} for s, why in recipe.roster],
        "permissions": perms,
        "sinks": [{"kind": dev["sink"]}],
        "triggers": triggers,
        "max_steps": 20,
        "max_seconds": 900,
        "enabled": 1,
        "job": recipe.id,
    }


def _deliver_line(dev: dict) -> str:
    if dev["id"] == "telegram":
        return ("send it to the user's Telegram with `telegram_send`. If it is longer than "
                "a few paragraphs, `save_report` it and send a short summary with a "
                "pointer instead.")
    if dev["id"] == "notify":
        return ("call `notify` with a one-line headline. Keep it to one sentence — it is "
                "a notification, not the report.")
    return ("call `save_report` with the finished page. That is the deliverable; do not "
            "finish having only gathered material.")


# ---------------------------------------------------------------------------
# Preview, install, run
# ---------------------------------------------------------------------------

def ensure_roster(cfg: dict, store) -> None:
    """Make sure the specialists the recipes name actually exist.

    Normally the server seeds them at startup, so this is a no-op. It is here for the
    machine that has never had a server run on it — `bento job add` over SSH on a
    fresh Pi — where the alternative is "no subagent named 'researcher'", a true
    sentence that tells a new user nothing they can act on.
    """
    from . import fabric as fabricmod
    fabricmod.seed_builtins(cfg, store)


def preview(cfg: dict, store, recipe_id: str, answers: dict) -> dict:
    """Exactly what installing this would create — before anything is written.

    Same code path as `install`, one step short of the write, so the consent screen
    can never drift from what the save actually does.
    """
    ensure_roster(cfg, store)
    body = build(cfg, store, recipe_id, answers)
    d = flowsmod.validate(body, store)
    return {"flow": {k: body[k] for k in ("name", "description", "mission")},
            "grants": flowsmod.declared_grants(d),
            "triggers": d["triggers"],
            "delivery": delivery(cfg, answers.get("deliver") or "report"),
            "reads": (body.get("permissions") or {}).get("fs_read") or []}


def install(cfg: dict, store, recipe_id: str, answers: dict) -> dict:
    """Create the job, enabled, and say what it will do next.

    ENABLED on purpose, unlike a composed draft. A draft is a model's proposal
    that a person has not read; this is a person picking a named thing off a list
    and answering its questions — the consent already happened, and a job that
    arrives switched off is a job that never runs.
    """
    ensure_roster(cfg, store)
    body = build(cfg, store, recipe_id, answers)
    asked = answers.get("deliver") or "report"
    dev = delivery(cfg, asked)
    flow, report = flowsmod.save(store, body)
    out = {"ok": True, "flow": flow, "report": report,
           "recipe": recipe_id, "delivery": dev,
           "next_run": next_run(store, flow["name"]),
           "reads": (body.get("permissions") or {}).get("fs_read") or []}
    if asked != dev["id"]:
        out["substituted"] = (f"{asked} is not set up on this machine, so it will leave "
                              f"the results in Reports instead.")
    try:
        store.log("system", f"job '{flow['name']}' created from the '{recipe_id}' recipe — "
                            f"delivers via {dev['id']}",
                  {"flow": flow["name"], "recipe": recipe_id, "delivery": dev["id"]})
    except Exception:
        pass
    return out


def next_run(store, flow_name: str) -> float | None:
    """When the clock will next start this, or None when nothing polls a clock for it.

    Read off the `tasks` rows rather than recomputed, because the task row is what
    actually fires — a second calculation here would be a second answer, and the
    wrong one would be the one on screen.
    """
    best = None
    for t in store.flow_triggers(flow_name):
        if not t.get("task_id"):
            continue
        task = next((x for x in store.list_tasks() if x["id"] == t["task_id"]), None)
        nr = (task or {}).get("next_run")
        if nr and (best is None or nr < best):
            best = nr
    return best


def describe_next(store, flow_name: str, now: float | None = None) -> str:
    """'in about 3 hours' / 'when something lands in that folder' — the sentence the
    card ends with, so a freshly installed job says when it will prove itself."""
    trigs = store.flow_triggers(flow_name)
    nr = next_run(store, flow_name)
    if nr:
        secs = max(0, nr - (now if now is not None else time.time()))
        if secs < 90:
            return "in under a minute"
        mins = int(secs // 60)
        if mins < 90:
            return f"in about {mins} minutes"
        return f"in about {int(round(mins / 60))} hours"
    if any((t.get("config") or {}).get("event") == "file_change" for t in trigs):
        return "the next time something lands in that folder"
    return "when you run it"


def installed(store) -> list[dict]:
    """Every flow that came from a recipe, newest first — the 'what have I got
    running?' answer, for the wizard's last screen and for `bento job`."""
    out = []
    for f in store.list_flows():
        rid = f.get("job") or ""
        if not rid:
            continue
        out.append({"name": f["name"], "recipe": rid, "enabled": bool(f.get("enabled")),
                    "description": f.get("description") or "",
                    "next": describe_next(store, f["name"]),
                    "next_run": next_run(store, f["name"])})
    return out
