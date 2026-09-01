"""Onboarding: the arc from a fresh install to a machine that is actually working for you.

The old first run asked four questions and opened onto an empty desktop. Everything
this OS can do was still one click away, in an app nobody had a reason to open yet —
and a capability you have not seen work is indistinguishable from one that does not
exist.

So this is not a settings form with a progress bar. Every step **produces something
real on the machine** and shows it happening: a model that answers, an agent that
exists, a flow that runs, a schedule that fires, a channel that reaches your phone.
By the end there is a machine doing things, not a machine configured to.

THREE RULES THAT KEEP IT HONEST
===============================

1. **Every step is probed, never remembered.** `state()` asks the machine what is
   true right now — is there a model, does a subagent exist, is a flow scheduled.
   A stored "step 4 complete" flag drifts the moment somebody deletes the thing it
   was about, and then setup lies to the next person who opens it.

2. **Re-running is the same code.** There is no "first run" path and "settings"
   path. `agentos setup` on day 300 walks the same steps, finds most of them
   already satisfied, and shows them ticked. That is what makes it safe to send
   somebody back here when something is misconfigured.

3. **Every step can be skipped, and says where it lives.** `panel` names the
   Settings page that owns the same setting, so nothing is only reachable during
   onboarding. A wizard that is the only way to configure something is a wizard
   people are afraid to leave.

Three faces (per CLAUDE.md):
  GUI  the first-run wizard, and Settings → "Run setup again".
  TUI  `bento setup` walks the same catalogue; steps that genuinely need a pointer
       (wallpaper) print what they would set and how to set it.
  SUI  identical to GUI — it is a full-screen overlay either way.

Kept free of HTTP and asyncio for the same reason as jobs.py: a headless Pi runs
the same arc over SSH.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The three-way answer every step gives about itself. `done` and `skipped` both
#: mean "do not stop here"; only `done` shows a tick, because pretending a skipped
#: step was completed is how somebody ends up looking for a channel they never set up.
STATUS = ("todo", "done", "skipped")


@dataclass
class Step:
    id: str
    title: str                  # imperative, in the user's words
    blurb: str                  # one sentence: what this is for
    produces: str               # what will EXIST when it is done — the whole point
    panel: str = ""             # the Settings tab that owns the same setting, later
    optional: bool = True       # can it be skipped? (name and model cannot)
    needs: tuple = ()           # step ids that must be done first
    icon: str = "◇"

    def as_dict(self, status: str = "todo", detail: str = "") -> dict:
        return {"id": self.id, "title": self.title, "blurb": self.blurb,
                "produces": self.produces, "panel": self.panel, "icon": self.icon,
                "optional": self.optional, "needs": list(self.needs),
                "status": status, "detail": detail}


STEPS: list[Step] = [
    Step("name", "Name your agent", icon="▲", optional=False,
         blurb="What you will call it, and what it calls itself.",
         produces="the name on the menu bar and in every reply",
         panel="agent"),
    Step("model", "Give it a brain", icon="✦", optional=False,
         blurb="A model on this machine, or a key to one in the cloud.",
         produces="a model this machine can actually reach",
         panel="ai"),
    Step("hello", "Watch it answer", icon="◉", needs=("model",),
         blurb="One real question, answered by the model you just chose. This is the "
               "step that turns a configuration into a machine that works.",
         produces="a real reply, from your model, in front of you",
         panel="ai"),
    # Right after the machine first works, because this is the moment somebody
    # who ARRIVED WITH A LINK is here for: a friend's "fork my agent", a team's
    # shared setup. Optional and skippable — most machines start from nothing —
    # but offered before the build steps, since a fork can satisfy several of
    # them at once (the skills, agents, flows and apps it brings tick their own
    # steps through the same probes).
    Step("fork", "Start from a shared agent", icon="⑂",
         blurb="Somebody shared their agent? Point at it — a file, a link, "
               "owner/repo, or their hosted share with the key they minted. "
               "Everything arrives disabled and nothing is granted.",
         produces="their skills, teammates, flows and apps on your machine — "
                  "off, ungranted, and yours to switch on",
         panel="agent"),
    # Third on purpose, right after the first real answer. Everything below it is
    # about work the machine does WITHOUT you watching — an agent, a mission, a
    # schedule — and none of that is a thing you can point at on a screen. An app is:
    # it appears on the desktop, it is yours, and building one is the fastest way to
    # learn that this OS writes its own software rather than only talking about it.
    Step("app", "Build something you can open", icon="▦", needs=("model",),
         blurb="Describe a small tool in a sentence and watch the agent write it — "
               "it lands on your desktop as a real app you can open, keep and edit.",
         produces="an app with your name on it, on the desktop",
         panel="studio"),
    Step("agent", "Build a specialist", icon="◈", needs=("model",),
         blurb="A named agent with its own persona and its own short list of tools. "
               "This is the unit everything else is assembled from.",
         produces="an agent you can call by name with @",
         panel=""),
    Step("flow", "Give the specialist a mission", icon="⚙", needs=("agent",),
         blurb="A flow is a standing mission and a roster. The orchestrator decides "
               "who does what while it runs — you do not draw the steps.",
         produces="a flow you can run, and watch run",
         panel=""),
    Step("schedule", "Let it run without you", icon="◷", needs=("flow",),
         blurb="A time, or something happening on this machine. This is the whole "
               "difference between a chat window and an operating system.",
         produces="something on the clock, with a next run time",
         panel=""),
    Step("channel", "Reach it from your phone", icon="◐",
         blurb="Telegram or WhatsApp — the same conversation, the same memory, the "
               "same approval prompts, on the app you already have open.",
         produces="a paired chat that answers as your agent",
         panel="channels"),
    Step("look", "Make it yours", icon="◧",
         blurb="A theme, a wallpaper, and whether it speaks out loud.",
         produces="a desktop that looks like your machine",
         panel="look"),
    # Last on purpose. Everything above is somebody setting up THEIR machine, and
    # the first account inherits all of it — so asking this first would mean
    # asking "who are you?" of a machine that does not yet do anything, and then
    # handing the result to an account nobody had a reason to want yet.
    Step("account", "Add the people who will use it", icon="◱",
         blurb="An account gives somebody their own home on this machine — their "
               "own memory, agents, channels and credentials — and it is the same "
               "username and password they will use from their phone.",
         produces="an account that can sign in, here and from anywhere",
         panel="users"),
]

BY_ID = {s.id: s for s in STEPS}


# ---------------------------------------------------------------------------
# What is already true
# ---------------------------------------------------------------------------

def _has_model(cfg: dict) -> tuple[bool, str]:
    m = (cfg.get("default_model") or "").strip()
    if m:
        return True, m
    for name, p in (cfg.get("providers") or {}).items():
        if isinstance(p, dict) and p.get("enabled") and p.get("api_key"):
            return True, f"{name} configured, no default model picked"
    return False, ""


DEFAULT_NAME = "Aria"


def _confirmed(cfg: dict) -> set:
    return set((cfg.get("onboarding") or {}).get("confirmed") or [])


def _named(cfg: dict) -> tuple[bool, str]:
    n = (cfg.get("agent_name") or "").strip()
    # "Aria" is the shipped default, so it is not evidence that anybody chose it —
    # but it is a perfectly good name, and pressing Save on it IS choosing it. Config
    # alone cannot tell "never touched" from "looked at it and kept it", which is the
    # same blind spot `skipped` exists for, so it is recorded the same way.
    #
    # Without this the step was a dead end you could only leave by disliking the
    # default: Save wrote the name, the probe still said todo, the arc did not
    # advance, and nothing on screen said why.
    return (bool(n) and (n != DEFAULT_NAME or "name" in _confirmed(cfg))), n


def state(cfg: dict, store=None) -> dict:
    """Every step, and whether the machine already satisfies it.

    Probed, never remembered — see rule 1 in the module docstring. The only stored
    thing is which steps were deliberately SKIPPED, because "I do not want a
    channel" is a decision the machine cannot infer by looking at itself.
    """
    skipped = set((cfg.get("onboarding") or {}).get("skipped") or [])
    out, done_ids = [], set()

    def probe(sid: str) -> tuple[str, str]:
        if sid == "name":
            ok, n = _named(cfg)
            return ("done", n) if ok else ("todo", "")
        if sid == "model":
            ok, d = _has_model(cfg)
            return ("done", d) if ok else ("todo", "")
        if sid == "hello":
            # Evidence, not a flag: a conversation exists because a turn happened.
            n = _count(store, "conversations")
            return ("done", f"{n} conversation{'' if n == 1 else 's'}") if n else ("todo", "")
        if sid == "fork":
            # Evidence: a fork records a pin under registry.agents (whom I took
            # from), so the step is done exactly when an import ever happened.
            pins = (cfg.get("registry") or {}).get("agents") or {}
            return ("done", ", ".join(sorted(pins)[:3])) if pins else ("todo", "")
        if sid == "app":
            # Evidence, like every other step: an app exists because one was built.
            # Nothing ships pre-installed in `user_apps`, so any row here is theirs.
            names = [a["name"] for a in _list(store, "list_apps") if a.get("name")]
            return ("done", ", ".join(names[:3])) if names else ("todo", "")
        if sid == "agent":
            names = [s["name"] for s in _list(store, "list_subagents")
                     if not s.get("builtin")]
            return ("done", ", ".join(names[:3])) if names else ("todo", "")
        if sid == "flow":
            # The shipped `daily-briefing` does not count, the same way the shipped
            # researcher/writer do not: a step ticked by something the installer put
            # there teaches nothing and skips the one moment that explains flows.
            names = [f["name"] for f in _list(store, "list_flows") if not f.get("builtin")]
            return ("done", ", ".join(names[:3])) if names else ("todo", "")
        if sid == "schedule":
            n = sum(1 for t in _list(store, "list_tasks") if t.get("enabled"))
            return ("done", f"{n} scheduled") if n else ("todo", "")
        if sid == "channel":
            live = _live_channels(cfg)
            return ("done", ", ".join(live)) if live else ("todo", "")
        if sid == "account":
            # Probed like everything else: accounts exist or they do not. The
            # single-user machine this ships as is a legitimate finished state,
            # which is why the step is optional and skipping it is remembered.
            try:
                from . import users as usersmod
                people = usersmod.list_users()
            except Exception:
                people = []
            if not people:
                return "todo", ""
            return "done", ", ".join(u["name"] for u in people[:3])
        if sid == "look":
            d = cfg.get("desktop") or {}
            if d.get("wallpaper_preset") or d.get("theme") or "voice_tts" in d:
                return "done", d.get("theme") or d.get("wallpaper_preset") or "set"
            return "todo", ""
        return "todo", ""

    for s in STEPS:
        status, detail = probe(s.id)
        if status == "todo" and s.id in skipped:
            status = "skipped"
        if status == "done":
            done_ids.add(s.id)
        out.append(s.as_dict(status, detail))

    # A step whose prerequisite is not met is not offered as the next thing to do —
    # "build a flow" before there is an agent is a dead end with a confusing error.
    for d in out:
        d["blocked"] = [n for n in d["needs"] if n not in done_ids]

    remaining = [d for d in out if d["status"] == "todo" and not d["blocked"]]
    return {"steps": out,
            "next": remaining[0]["id"] if remaining else "",
            "done": len(done_ids), "total": len(STEPS),
            "complete": bool(cfg.get("setup_complete")),
            # every step either done or deliberately skipped
            "finished": all(d["status"] != "todo" for d in out)}


def _count(store, table: str) -> int:
    if store is None:
        return 0
    try:
        return store.db.execute(f"select count(*) c from {table}").fetchone()["c"]
    except Exception:
        return 0


def _list(store, method: str) -> list:
    if store is None:
        return []
    try:
        return getattr(store, method)() or []
    except Exception:
        return []


def _live_channels(cfg: dict) -> list[str]:
    """Channels that would actually carry a message right now.

    Configured and working are different things, and the step is about the second:
    a bot token with nobody paired reaches no one.
    """
    live = []
    tg = cfg.get("telegram") or {}
    if tg.get("enabled") and tg.get("bot_token") and tg.get("owner_chat_id"):
        live.append("Telegram")
    try:
        from . import whatsapp as wamod
        wa = wamod.conf(cfg)
        if wa.get("enabled") and wa.get("owner_wa_id"):
            live.append("WhatsApp")
    except Exception:
        pass
    return live


# ---------------------------------------------------------------------------
# Decisions the machine cannot infer
# ---------------------------------------------------------------------------

def skip(cfg: dict, step_id: str) -> dict:
    """Record that a step was deliberately passed over.

    Stored rather than probed because it is the one thing looking at the machine
    cannot tell you: an unpaired channel and a channel somebody decided against
    look identical from here.
    """
    if step_id not in BY_ID:
        raise ValueError(f"no onboarding step '{step_id}'")
    if not BY_ID[step_id].optional:
        raise ValueError(f"'{BY_ID[step_id].title}' is not optional — the machine "
                         f"cannot work without it")
    ob = cfg.setdefault("onboarding", {})
    ob["skipped"] = sorted(set(ob.get("skipped") or []) | {step_id})
    return {"ok": True, "skipped": ob["skipped"]}


def unskip(cfg: dict, step_id: str) -> dict:
    """Coming back to a step you skipped. Re-running setup should offer it again."""
    ob = cfg.setdefault("onboarding", {})
    ob["skipped"] = [s for s in (ob.get("skipped") or []) if s != step_id]
    return {"ok": True, "skipped": ob["skipped"]}


def confirm(cfg: dict, step_id: str) -> dict:
    """Record that a step's CURRENT state is what the user wants.

    The sibling of `skip`, for the opposite answer. `skip` says "not this, ever";
    this says "yes, exactly what is already there" — and it is needed for the same
    reason: some steps are satisfied by a value the machine cannot distinguish from
    the one it shipped with.

    Only the name step reads it today. Kept general rather than a `name_confirmed`
    boolean because the shape recurs the moment any other step has a usable default.
    """
    if step_id not in BY_ID:
        raise ValueError(f"no onboarding step '{step_id}'")
    ob = cfg.setdefault("onboarding", {})
    ob["confirmed"] = sorted(set(ob.get("confirmed") or []) | {step_id})
    return {"ok": True, "confirmed": ob["confirmed"]}


def restart(cfg: dict) -> dict:
    """Walk the whole arc again without wiping anything.

    Deliberately NOT a factory reset: "run setup again" almost always means "I want
    to change something and I do not remember where it lives", and answering that
    by deleting their memory would be a catastrophe with a friendly button.
    """
    ob = cfg.setdefault("onboarding", {})
    ob["skipped"] = []
    # Confirmations go too, for the same reason skips do: walking the arc again means
    # being asked again. Leaving them would tick the name step from a decision made
    # on a machine the user is now deliberately reconsidering.
    ob["confirmed"] = []
    cfg["setup_complete"] = False
    return {"ok": True}


# ---------------------------------------------------------------------------
# What each step actually creates
# ---------------------------------------------------------------------------

#: The specialist offered at the "build an agent" step. One, not a menu: the point
#: of the step is to see an agent exist and answer, and three choices at that moment
#: is a decision nobody has the context to make yet. It is editable immediately after.
STARTER_AGENT = {
    "name": "researcher-plus",
    "soul": "You research. Gather real information with your tools, verify it against "
            "a second source where you can, and return a dense, sourced summary. "
            "Never pad, never invent, and say plainly when you could not find "
            "something rather than filling the gap.",
    "tools": ["fetch_url", "read_file", "list_dir", "recall", "kg_query", "save_report"],
    "max_steps": 14, "max_seconds": 420, "autonomy_cap": "balanced",
}

#: The app offered at the "build something you can open" step IN A TERMINAL.
#:
#: The desktop hands this step to App Studio and lets you watch the agent write the
#: thing from a sentence, which is the better lesson. Over SSH there is no Studio and
#: no preview to watch, so the terminal offers a real, finished app instead — it
#: needs no model, no key and no network, and the step's promise ("an app with your
#: name on it") is kept either way. That is the three-faces rule working: the same
#: step, honestly different where the surface differs.
STARTER_APP = {
    "name": "Scratchpad",
    "description": "Notes that survive a reload, with a word count.",
    "html": """<style>
  .sp{display:flex;flex-direction:column;gap:8px;height:100%;padding:12px;box-sizing:border-box}
  .sp textarea{flex:1;width:100%;resize:none;font:14px/1.6 ui-monospace,monospace;
    padding:12px;border-radius:10px;border:1px solid #2a3240;background:#12161d;color:#e6edf3}
  .sp .bar{display:flex;gap:14px;font:12px system-ui;color:#8b97a8}
</style>
<div class="sp">
  <textarea id="pad" placeholder="Type. It saves itself."></textarea>
  <div class="bar"><span id="w">0 words</span><span id="c">0 characters</span>
    <span id="s"></span></div>
</div>
<script>
  const pad=document.getElementById('pad');
  const count=()=>{const t=pad.value;
    document.getElementById('w').textContent=(t.trim()?t.trim().split(/\\s+/).length:0)+' words';
    document.getElementById('c').textContent=t.length+' characters'};
  // appData is the app's own private store — nothing else on this machine reads it.
  (async()=>{try{const d=await appData.get('note');pad.value=(d&&d.text)||''}catch(e){}
    count()})();
  let t=null;
  pad.addEventListener('input',()=>{count();clearTimeout(t);
    t=setTimeout(async()=>{try{await appData.set('note',{text:pad.value});
      document.getElementById('s').textContent='saved'}catch(e){}},400)});
</script>""",
}


def starter_app(store) -> dict:
    """The app to create, under a name nothing else is using."""
    d = dict(STARTER_APP)
    base, n = d["name"], 2
    existing = {a.get("name") for a in _list(store, "list_apps")}
    while d["name"] in existing:
        d["name"] = f"{base} {n}"
        n += 1
    return d


#: The flow offered at the "give it a mission" step. Its roster is whatever the
#: previous step created, so the two steps visibly connect.
STARTER_FLOW = {
    "name": "first-flow",
    "description": "Look something up properly and write it down.",
    "mission": "Research the topic the user names and produce a short, sourced "
               "briefing on it. Check what you already know about them with `recall` "
               "first so it is written for this person. Verify before you write — an "
               "unsourced claim is worse than a shorter page. Finish by calling "
               "`save_report` with the result; do not stop having only gathered "
               "material.",
    "permissions": {"tools": ["fetch_url", "save_report", "recall", "kg_query"],
                    "net": ["*"], "memory": "read-space"},
    "sinks": [{"kind": "report"}],
}


def starter_agent(store) -> dict:
    """The agent definition to create, with a name nothing else is using."""
    d = dict(STARTER_AGENT)
    base = d["name"]
    n = 2
    while store is not None and store.get_subagent(d["name"]):
        d["name"] = f"{base}-{n}"
        n += 1
    return d


def starter_flow(store, roster: list) -> dict:
    """The flow definition to create, rostered with the agents that exist."""
    d = dict(STARTER_FLOW)
    d["roster"] = [{"subagent": r, "why": "researches and writes the briefing"}
                   for r in roster[:2]]
    base = d["name"]
    n = 2
    while store is not None and store.get_flow(d["name"]):
        d["name"] = f"{base}-{n}"
        n += 1
    return d
