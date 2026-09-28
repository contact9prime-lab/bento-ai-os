"""The World: an experimental scene where your agents have feelings, and so do you.

Asked for in so many words: "make them come alive like Sims, with tantrums", "different
worlds have different emotions and growth, so people can build their own world of
agents", "the lead can ask how you are feeling today", and above all "the moment I get
out of the world scene it's all evaporated, and it comes back when I switch to that
world. Scene matters."

So this module is built around one rule: **a world is live only while its scene holds a
lease.** The page (`01e-world.js`) enters a world when the World scene starts, beats every
few seconds, and leaves when the scene stops. While live, events the server already
broadcasts are turned into feelings (`observe`); while not, `observe` returns before
reading anything, `inner_note` is empty, and the state routes answer "not live". The
state itself stays in the person's own database (`worlds` table), dormant, and is loaded
again on the next enter. Nothing else in the OS reads it: not the Office, not Chat, not
Telegram, not the terminal.

Three things keep it honest, the Office's rule carried into feelings:

- **Every feeling is caused by something that happened.** Events become SIGNALS (a
  closed set, each with the plain words `why` shows), and a world maps signals onto its
  own emotions. Tapping an agent shows the causes. Nothing is invented; when nothing is
  going on an agent is in its world's resting mood.
- **Your "no" is never guilt.** `declined` (you refused a step) and `you_low` (you said
  you are having a hard day) may only trigger emotions with a valence of zero or more.
  `validate` refuses a world that maps them onto sadness, so no world, built-in or
  designed, can make somebody feel responsible for a character's mood.
- **Feelings never outrank the rules.** With "agents feel it" on (`inner`), the agent's
  prompt gets one paragraph about how it feels and why, and that paragraph says in words
  that feelings change tone and approach, never permissions or limits. The gate is not
  consulted differently; nothing here is a capability.

Worlds are definitions: a KIT the page knows how to draw (canal, orbit, garden), a list
of emotions (name, emoji, hue, valence, one of the EXPRESSIONS the page can animate, and
which signals trigger it), a growth ladder with what earns points, and the lead's daily
check-in question with its answers. Three are built in and deliberately unlike each
other; a person can describe their own in words (`design_prompt` / `read_design`, each
field checked alone, an invented one dropped and NAMED, the office designer's rule), and
`from_words` answers when no brain does.

Stdlib only and no asyncio, like office.py: the server does the HTTP and the brain call.

Faces: GUI and SUI draw it (the same page; a machine with no WebGL gets a flat drawing
and a sentence saying why). The TUI deliberately has no world: it is an experiment that
lives in a scene, and the owner asked for it to exist nowhere else.
"""
from __future__ import annotations

import datetime
import json
import re
import time

# ------------------------------------------------------------------ the closed sets

KITS = {
    "canal": "a canal town: water, houses, a red bridge, lanterns at night",
    "orbit": "a moon base: domes, a launch tower, a planet in a black sky, stars",
    "garden": "a wild garden: grass, flowers, trees, a pond",
}

#: What the page can animate. A world picks one per emotion; the page implements all.
EXPRESSIONS = {
    "calm": "stands easy, breathing",
    "cheer": "hops with arms up",
    "tantrum": "stomps and shakes, papers flying",
    "slump": "sinks, head down",
    "pace": "walks back and forth",
    "sulk": "turns away and sits",
    "doze": "nods off, a z floats up",
    "shiver": "a small nervous shake",
    "sparkle": "glows with little sparks",
    "wave": "waves at someone",
    "care": "leans in, gentle",
    "think": "sways slowly, deep in thought",
}

#: Everything a feeling can come from. The words are what `why` shows the person.
SIGNALS = {
    "working": "started on a task",
    "succeeded": "finished a task",
    "failed": "a step went wrong",
    "refused": "the rules said no to a step",
    "waiting": "is waiting for your yes",
    "approved": "you said yes",
    "declined": "you said no, and that's fine",
    "rate_limited": "its AI provider asked it to slow down",
    "untrusted": "read something from outside it can't fully trust",
    "asked_help": "asked a colleague for help",
    "helped": "helped a colleague",
    "huddled": "talked it through with the team",
    "vote_won": "the team adopted its idea",
    "vote_lost": "the team voted its idea down",
    "outvoted": "voted the other way and lost",
    "praised": "you gave it a pat on the back",
    "grew": "grew into a new role",
    "you_low": "you said today is hard",
    "you_high": "you said today is good",
}

#: How a world LOOKS, as a closed set the page can draw: every field is a choice, never a
#: free colour or a model's invention. A person designs their scene from these (the menu's
#: designer, or words the brain maps onto them), and `scene_of` checks each field alone.
SCENE = {
    "time": ("live", "dawn", "day", "dusk", "night"),
    "weather": ("clear", "clouds", "rain", "snow", "petals", "fireflies"),
    "sky": ("natural", "rose", "violet", "teal", "gold", "storm"),
    "water": ("teal", "blue", "jade", "violet", "amber", "ink"),
    "ground": ("natural", "sand", "snow", "moss", "rust", "ash"),
    "accent": ("red", "amber", "gold", "blue", "violet", "green", "white"),
}
#: The props each setting can show. A scene lists the ones it keeps.
PROPS = {
    "canal": ("houses", "bridge", "pagoda", "lanterns", "boats", "trees"),
    "orbit": ("domes", "tower", "dish", "solar", "rover", "shuttle"),
    "garden": ("pond", "lanterns", "trees", "flowers", "path"),
}
#: What each setting looks like until somebody changes it.
KIT_SCENE = {
    "canal": {"time": "live", "weather": "petals", "sky": "natural", "water": "teal",
              "ground": "natural", "accent": "red"},
    "orbit": {"time": "live", "weather": "clear", "sky": "natural", "water": "blue",
              "ground": "natural", "accent": "amber"},
    "garden": {"time": "live", "weather": "fireflies", "sky": "natural", "water": "blue",
               "ground": "natural", "accent": "amber"},
}

#: Signals that may never cause a negative feeling. See the module docstring.
GENTLE = ("declined", "you_low")

LEAD = "@agent"
LEASE_S = 45            # the page beats every 15s; three missed beats and the world sleeps
FLUSH_S = 10            # write the state at most this often while live (footprint rule)
HALF_LIFE = 15 * 60     # a feeling halves every fifteen minutes
SHOW = 0.15             # below this a feeling is not the one on show
WHY_KEEP = 8
MAX_WORLDS = 12         # custom worlds per person
MAX_AGENTS = 40

# ------------------------------------------------------------------ the built-in worlds


def _emo(id, name, emoji, hue, valence, expression, triggers, lines):
    return {"id": id, "name": name, "emoji": emoji, "hue": hue, "valence": valence,
            "expression": expression, "triggers": triggers, "lines": lines}


BUILTIN = [
    {
        "id": "lantern-canal", "name": "Lantern Canal", "kit": "canal",
        "blurb": "A quiet canal town. Work is boats on the water, and moods are the weather on the quay.",
        "voice": "unhurried and warm, like a boat keeper at dusk; water and lantern images, never flowery",
        "rest": "serene",
        "emotions": [
            _emo("serene", "Serene", "🏮", 38, 1, "calm", {},
                 ["The water's still.", "Nothing on the river but light."]),
            _emo("absorbed", "Absorbed", "🛶", 190, 1, "think", {"working": .5},
                 ["Oars in the water.", "Heading upstream."]),
            _emo("proud", "Proud", "🌸", 330, 2, "cheer", {"succeeded": .7, "vote_won": .8, "grew": 1},
                 ["Docked, cargo delivered!", "That one went smoothly."]),
            _emo("flustered", "Flustered", "💢", 5, -2, "tantrum", {"refused": .55},
                 ["The lock gate won't open!", "Why won't they let me through?"]),
            _emo("gloomy", "Gloomy", "🌧️", 220, -1, "slump", {"failed": .5, "vote_lost": .6},
                 ["Sprung a leak.", "That didn't float."]),
            _emo("restless", "Restless", "⏳", 45, 0, "pace", {"waiting": .6},
                 ["Waiting at the water gate…", "Is the gatekeeper coming?"]),
            _emo("wary", "Wary", "🫧", 270, -1, "shiver", {"untrusted": .6},
                 ["This letter smells of strangers.", "I'll hold that at arm's length."]),
            _emo("breathless", "Breathless", "💨", 200, -1, "doze", {"rate_limited": .9},
                 ["Rowing too fast, need a breather.", "The current's too strong right now."]),
            _emo("neighbourly", "Neighbourly", "🤝", 150, 2, "wave",
                 {"asked_help": .5, "helped": .6, "huddled": .5},
                 ["Tied our boats together.", "Good to row with company."]),
            _emo("sulky", "Sulky", "😤", 20, -1, "sulk", {"outvoted": .6},
                 ["Fine. We'll take their route.", "I still think the other bridge was better."]),
            _emo("tender", "Tender", "🍵", 25, 1, "care", {"you_low": .45, "declined": .3, "praised": .5},
                 ["I'll keep the lantern lit for you.", "Take your time, the river waits."]),
            _emo("merry", "Merry", "🎐", 55, 2, "sparkle", {"you_high": .45, "approved": .4, "praised": .5},
                 ["Festival weather!", "The lanterns look brighter today."]),
        ],
        "growth": {"earns": {"succeeded": 3, "helped": 2, "vote_won": 2, "huddled": 1, "praised": 1},
                   "ladder": [{"name": "Deckhand", "at": 0}, {"name": "Boatman", "at": 15},
                              {"name": "Canal pilot", "at": 45}, {"name": "Harbour master", "at": 120},
                              {"name": "River sage", "at": 300}]},
        "checkin": {"question": "How are the waters for you today?",
                    "choices": [{"id": "sunny", "label": "Sunny", "emoji": "☀️", "valence": 2},
                                {"id": "calm", "label": "Calm", "emoji": "🌊", "valence": 1},
                                {"id": "choppy", "label": "Choppy", "emoji": "🌬️", "valence": -1},
                                {"id": "stormy", "label": "Stormy", "emoji": "⛈️", "valence": -2}],
                    "reply_low": "Then we'll keep the boats close to shore today. I'll handle the heavy rowing.",
                    "reply_ok": "Good. The river's gentle, let's make an easy day of it.",
                    "reply_high": "Wonderful. The lanterns will be bright tonight."},
    },
    {
        "id": "kestrel-station", "name": "Kestrel Station", "kit": "orbit",
        "blurb": "A moon base under a blue planet. Work is shuttles, and moods run on oxygen and signal.",
        "voice": "crisp and caring, like mission control on a good day; short, precise, a little dry humour",
        "rest": "nominal",
        "emotions": [
            _emo("nominal", "Nominal", "🛰️", 200, 1, "calm", {},
                 ["All systems nominal.", "Holding orbit."]),
            _emo("locked-in", "Locked in", "🧭", 180, 1, "think", {"working": .5},
                 ["Plotting a course.", "Burn in progress."]),
            _emo("elated", "Elated", "🚀", 285, 2, "cheer", {"succeeded": .7, "vote_won": .8, "grew": 1},
                 ["Payload delivered!", "Clean docking, textbook."]),
            _emo("overheating", "Overheating", "🔥", 10, -2, "tantrum", {"refused": .55},
                 ["Access denied again?!", "Who locked this airlock?"]),
            _emo("hull-breach", "Hull breach", "🧯", 0, -2, "slump", {"failed": .5},
                 ["We lost pressure on that one.", "Mission scrubbed."]),
            _emo("holding", "Holding pattern", "📡", 50, 0, "pace", {"waiting": .6},
                 ["Awaiting clearance from control.", "Still circling…"]),
            _emo("quarantine", "Quarantine jitters", "☣️", 100, -1, "shiver", {"untrusted": .6},
                 ["Unknown signal. Keeping it sealed.", "Scanning that before I touch it."]),
            _emo("low-oxygen", "Low oxygen", "🫁", 190, -1, "doze", {"rate_limited": .9},
                 ["Oxygen low, conserving.", "Ground says slow down."]),
            _emo("comms-buddy", "Comms buddy", "📻", 160, 2, "wave",
                 {"asked_help": .5, "helped": .6, "huddled": .5},
                 ["Reading you loud and clear.", "Good to have a wingmate."]),
            _emo("outvoted", "Overruled", "🌑", 240, -1, "sulk", {"outvoted": .6, "vote_lost": .6},
                 ["Copy. Standing down.", "Noted for the log."]),
            _emo("steady", "Steady hand", "🫶", 30, 1, "care", {"you_low": .45, "declined": .3, "praised": .5},
                 ["I've got the helm today.", "Take the slow orbit, we're fine."]),
            _emo("starstruck", "Starstruck", "✨", 55, 2, "sparkle", {"you_high": .45, "approved": .4, "praised": .5},
                 ["Look at that view!", "Clear skies all the way down."]),
        ],
        "growth": {"earns": {"succeeded": 3, "helped": 2, "vote_won": 2, "huddled": 1, "praised": 1},
                   "ladder": [{"name": "Cadet", "at": 0}, {"name": "Specialist", "at": 15},
                              {"name": "Flight officer", "at": 45}, {"name": "Commander", "at": 120},
                              {"name": "Station legend", "at": 300}]},
        "checkin": {"question": "Status report, crew member. How are you today?",
                    "choices": [{"id": "go", "label": "Go for launch", "emoji": "🚀", "valence": 2},
                                {"id": "nominal", "label": "Nominal", "emoji": "🛰️", "valence": 1},
                                {"id": "turbulence", "label": "Turbulence", "emoji": "🌪️", "valence": -1},
                                {"id": "mayday", "label": "Mayday", "emoji": "🆘", "valence": -2}],
                    "reply_low": "Copy that. I'll fly the heavy stuff today, you take the comfortable seat.",
                    "reply_ok": "Nominal is good. Steady orbit it is.",
                    "reply_high": "Love to hear it. Clear for launch."},
    },
    {
        "id": "wild-garden", "name": "The Wild Garden", "kit": "garden",
        "blurb": "A garden that grows with the work. Agents are gardeners, and moods are the weather in the leaves.",
        "voice": "gentle and earthy, like a gardener talking over the fence; plant and weather images",
        "rest": "rooted",
        "emotions": [
            _emo("rooted", "Rooted", "🌿", 120, 1, "calm", {},
                 ["Roots deep, leaves easy.", "Listening to the bees."]),
            _emo("tending", "Tending", "🪴", 100, 1, "think", {"working": .5},
                 ["Weeding the beds.", "Planting something new."]),
            _emo("blooming", "Blooming", "🌻", 50, 2, "cheer", {"succeeded": .7, "vote_won": .8, "grew": 1},
                 ["It flowered!", "Look what came up."]),
            _emo("thorny", "Thorny", "🌵", 15, -2, "tantrum", {"refused": .55},
                 ["The gate's locked again!", "Who planted a fence here?"]),
            _emo("wilting", "Wilting", "🥀", 330, -1, "slump", {"failed": .5, "vote_lost": .6},
                 ["That one didn't take.", "Frost got it."]),
            _emo("thirsty", "Thirsty", "💧", 200, 0, "pace", {"waiting": .6},
                 ["Waiting for the watering can…", "A little yes would help this grow."]),
            _emo("pollen-wary", "Pollen-wary", "🐝", 60, -1, "shiver", {"untrusted": .6},
                 ["Not sure where this seed came from.", "I'll keep that one in a pot for now."]),
            _emo("sun-scorched", "Sun-scorched", "🥵", 30, -1, "doze", {"rate_limited": .9},
                 ["Too much sun, resting in the shade.", "Need a drink before the next row."]),
            _emo("entwined", "Entwined", "🌱", 140, 2, "wave", {"asked_help": .5, "helped": .6, "huddled": .5},
                 ["Our vines grew together.", "Two gardeners, one bed."]),
            _emo("trampled", "Trampled", "🍂", 25, -1, "sulk", {"outvoted": .6},
                 ["They picked the other path.", "My bed got walked through."]),
            _emo("sheltering", "Sheltering", "🍄", 20, 1, "care", {"you_low": .45, "declined": .3, "praised": .5},
                 ["Come sit under the tree a while.", "Rain's fine, the roots like it."]),
            _emo("sunlit", "Sunlit", "🌞", 45, 2, "sparkle", {"you_high": .45, "approved": .4, "praised": .5},
                 ["Everything's reaching for the light!", "Butterflies everywhere today."]),
        ],
        "growth": {"earns": {"succeeded": 3, "helped": 2, "vote_won": 2, "huddled": 1, "praised": 1},
                   "ladder": [{"name": "Seed", "at": 0}, {"name": "Sprout", "at": 15},
                              {"name": "Sapling", "at": 45}, {"name": "Tall tree", "at": 120},
                              {"name": "Old oak", "at": 300}]},
        "checkin": {"question": "How's the weather inside you today?",
                    "choices": [{"id": "blooming", "label": "Blooming", "emoji": "🌻", "valence": 2},
                                {"id": "mild", "label": "Mild", "emoji": "🌤️", "valence": 1},
                                {"id": "drizzly", "label": "Drizzly", "emoji": "🌦️", "valence": -1},
                                {"id": "frost", "label": "Frost", "emoji": "❄️", "valence": -2}],
                    "reply_low": "Then we'll let the garden look after itself for a while. I'll do the digging.",
                    "reply_ok": "Mild's good growing weather.",
                    "reply_high": "Lovely. Everything grows better on days like this."},
    },
]
BUILTIN_IDS = {w["id"] for w in BUILTIN}
DEFAULT = BUILTIN[0]["id"]

# ------------------------------------------------------------------ validation


def _clean(s, n: int) -> str:
    s = re.sub(r"[\x00-\x1f\x7f-\x9f‪-‮⁦-⁩]", "", str(s or ""))
    return " ".join(s.split())[:n]


def _cut(s, n: int) -> str:
    """Cleaned and cut at a word: a button that reads "The crust isn't righ" is a
    choice nobody can read back (the Brief's `_short` lesson)."""
    s = _clean(s, 400)
    if len(s) <= n:
        return s
    head = s[:n + 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return (head if len(head) >= n // 2 else s[:n]).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:40]


def _num(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def scene_of(kit: str, sc) -> tuple[dict, list[str]]:
    """A scene held to the closed sets, field by field: a value that is not on the list
    is dropped and NAMED, and the setting's own look stands in for it. Props are the
    ones this setting can draw; an unknown prop is named, and none at all means all."""
    kit = kit if kit in KITS else "canal"
    sc = sc if isinstance(sc, dict) else {}
    out, dropped = dict(KIT_SCENE[kit]), []
    for field, choices in SCENE.items():
        v = sc.get(field)
        if v is None or v == "":
            continue
        if v in choices:
            out[field] = v
        else:
            dropped.append(f"scene {field} {v!r} (choose one of {', '.join(choices)})")
    for k in sc:
        if k not in SCENE and k != "props":
            dropped.append(f"scene field {k!r} (a scene has {', '.join(list(SCENE) + ['props'])})")
    props = sc.get("props")
    keep = list(PROPS[kit])
    if isinstance(props, (list, tuple)):
        wanted = [p for p in props if p in PROPS[kit]]
        for p in props:
            if p not in PROPS[kit]:
                dropped.append(f"prop {p!r} ({kit} has {', '.join(PROPS[kit])})")
        keep = [p for p in PROPS[kit] if p in wanted]
    out["props"] = keep
    return out, dropped


def validate(defn: dict) -> tuple[dict, list[str]]:
    """A world definition held to the closed sets. Each field is checked alone: a
    bad one is dropped and NAMED (never guessed at), a world that is missing its
    essentials raises ValueError with the sentence that says which."""
    dropped: list[str] = []
    d = defn if isinstance(defn, dict) else {}
    name = _clean(d.get("name"), 40)
    if not name:
        raise ValueError("A world needs a name.")
    kit = d.get("kit") if d.get("kit") in KITS else ""
    if not kit:
        dropped.append(f"kit {d.get('kit')!r} (choose one of {', '.join(KITS)})")
        kit = "canal"
    emotions, seen = [], set()
    for e in (d.get("emotions") or [])[:16]:
        if not isinstance(e, dict):
            continue
        eid = _slug(e.get("id") or e.get("name"))
        ename = _cut(e.get("name"), 24)
        if not eid or not ename or eid in seen:
            dropped.append(f"emotion {e.get('name')!r}")
            continue
        expr = e.get("expression") if e.get("expression") in EXPRESSIONS else ""
        if not expr:
            dropped.append(f"{ename}'s expression {e.get('expression')!r}")
            expr = "calm"
        val = int(round(_num(e.get("valence"), -2, 2, 0)))
        trig = {}
        for sig, w in (e.get("triggers") or {}).items():
            if sig not in SIGNALS:
                dropped.append(f"{ename}'s trigger {sig!r}")
                continue
            if sig in GENTLE and val < 0:
                # a person's "no", or their hard day, is never somebody's sadness
                dropped.append(f"{ename} on {sig!r} (your no and your hard days only "
                               f"make agents gentle, never upset)")
                continue
            trig[sig] = round(_num(w, 0, 1, .5), 2)
        lines = [_cut(x, 90) for x in (e.get("lines") or []) if _cut(x, 90)][:4]
        seen.add(eid)
        emotions.append({"id": eid, "name": ename, "emoji": _clean(e.get("emoji"), 4) or "•",
                         "hue": int(_num(e.get("hue"), 0, 359, 200)), "valence": val,
                         "expression": expr, "triggers": trig, "lines": lines or [ename + "."]})
    if len(emotions) < 2:
        raise ValueError("A world needs at least two emotions.")
    ids = [e["id"] for e in emotions]
    rest = _slug(d.get("rest"))
    if rest not in ids:
        calm = [e for e in emotions if not e["triggers"]] or \
               sorted(emotions, key=lambda e: -e["valence"])
        rest = calm[0]["id"]
    g = d.get("growth") if isinstance(d.get("growth"), dict) else {}
    earns = {s: int(_num(p, 0, 10, 0)) for s, p in (g.get("earns") or {}).items() if s in SIGNALS}
    if not any(earns.values()):
        earns = {"succeeded": 3, "helped": 2, "vote_won": 2, "huddled": 1, "praised": 1}
    ladder, last = [], -1
    for step in (g.get("ladder") or [])[:8]:
        if not isinstance(step, dict) or not _clean(step.get("name"), 24):
            continue
        at = int(_num(step.get("at"), 0, 100000, 0))
        if at <= last:
            dropped.append(f"growth step {step.get('name')!r} (each step needs more points)")
            continue
        ladder.append({"name": _clean(step.get("name"), 24), "at": at})
        last = at
    if not ladder or ladder[0]["at"] != 0:
        ladder = [{"name": "Newcomer", "at": 0}] + ladder
    c = d.get("checkin") if isinstance(d.get("checkin"), dict) else {}
    choices = []
    for ch in (c.get("choices") or [])[:5]:
        if isinstance(ch, dict) and _cut(ch.get("label"), 26):
            choices.append({"id": _slug(ch.get("id") or ch.get("label")) or "c" + str(len(choices)),
                            "label": _cut(ch.get("label"), 26),
                            "emoji": _clean(ch.get("emoji"), 4) or "•",
                            "valence": int(round(_num(ch.get("valence"), -2, 2, 0)))})
    if len(choices) < 2:
        choices = [{"id": "good", "label": "Good", "emoji": "🙂", "valence": 1},
                   {"id": "meh", "label": "So-so", "emoji": "😐", "valence": 0},
                   {"id": "hard", "label": "Hard", "emoji": "😣", "valence": -1}]
    checkin = {"question": _clean(c.get("question"), 90) or "How are you feeling today?",
               "choices": choices,
               "reply_low": _clean(c.get("reply_low"), 160) or "Thanks for telling me. I'll keep today light.",
               "reply_ok": _clean(c.get("reply_ok"), 160) or "Good to hear. Let's have an easy day.",
               "reply_high": _clean(c.get("reply_high"), 160) or "Love that. Let's make something good."}
    scene, why = scene_of(kit, d.get("scene"))
    dropped += why
    out = {"id": _slug(d.get("id") or name) or "world", "name": name, "kit": kit, "scene": scene,
           "blurb": _clean(d.get("blurb"), 160), "voice": _clean(d.get("voice"), 160),
           "rest": rest, "emotions": emotions,
           "growth": {"earns": earns, "ladder": ladder}, "checkin": checkin}
    return out, dropped


for _w in BUILTIN:          # the shipped worlds obey the same rules as anyone's
    _checked, _why = validate(_w)
    assert not _why, (_w["id"], _why)
    _w.update(_checked)
    _w["builtin"] = True

# ------------------------------------------------------------------ worlds a person has


def worlds(store) -> list[dict]:
    """Every world this person can enter: the built-in ones (with the scene this person
    designed for them, when they did), then their own."""
    own, looks = [], {}
    for r in store.world_rows():
        if not r.get("defn"):
            continue
        try:
            d = json.loads(r["defn"])
        except Exception:
            continue
        if r["id"] in BUILTIN_IDS:
            # a built-in world's row holds only the person's scene for it
            if isinstance(d.get("scene"), dict):
                looks[r["id"]] = d["scene"]
            continue
        d["builtin"] = False
        if not isinstance(d.get("scene"), dict):      # a world saved before scenes existed
            d["scene"] = scene_of(d.get("kit"), None)[0]
        own.append(d)
    out = []
    for w in BUILTIN:
        w = dict(w)
        if w["id"] in looks:
            w["scene"] = scene_of(w["kit"], looks[w["id"]])[0]
            w["scene_custom"] = True
        out.append(w)
    return out + own


def set_scene(store, wid: str, scene, kit: str = "") -> tuple[dict, list[str]]:
    """Design a world's scene. A built-in world keeps its setting and stores only the
    look; a world of your own may change setting too. `scene=None` puts a built-in
    world back the way it shipped. Returns the world as it now is, and what was dropped."""
    w = world(store, wid)
    if not w:
        raise ValueError(f"No world called {wid!r}.")
    if w.get("builtin"):
        if kit and kit != w["kit"]:
            raise ValueError("A built-in world keeps its setting. Build your own world to choose another.")
        if scene is None:
            store.world_put(wid, defn="")
            return world(store, wid), []
        sc, dropped = scene_of(w["kit"], scene)
        store.world_put(wid, defn=json.dumps({"scene": sc}, sort_keys=True))
        return world(store, wid), dropped
    d = {k: v for k, v in w.items() if k != "builtin"}
    if kit:
        if kit not in KITS:
            raise ValueError(f"No setting called {kit!r} (choose one of {', '.join(KITS)}).")
        d["kit"] = kit
    d["scene"], dropped = scene_of(d["kit"], scene if scene is not None else d.get("scene"))
    store.world_put(wid, defn=json.dumps(d, sort_keys=True))
    return world(store, wid), dropped


def world(store, wid: str) -> dict | None:
    return next((w for w in worlds(store) if w["id"] == wid), None)


def save_custom(store, defn: dict) -> tuple[dict, list[str]]:
    d, dropped = validate(defn)
    taken = {w["id"] for w in worlds(store)}
    base, n = d["id"], 2
    while d["id"] in taken:
        d["id"] = f"{base}-{n}"
        n += 1
    if len([w for w in worlds(store) if not w.get("builtin")]) >= MAX_WORLDS:
        raise ValueError(f"You already have {MAX_WORLDS} worlds of your own. Delete one first.")
    store.world_put(d["id"], defn=json.dumps(d, sort_keys=True))
    d["builtin"] = False
    return d, dropped


def delete_custom(store, wid: str) -> None:
    if wid in BUILTIN_IDS:
        raise ValueError("The built-in worlds stay. You can reset one instead.")
    if not world(store, wid):
        raise ValueError(f"No world called {wid!r}.")
    store.world_delete(wid)
    for uid, lease in list(_LIVE.items()):
        if lease["world"] == wid and lease["store"] is store:
            _LIVE.pop(uid, None)
            _STATE.pop((uid, wid), None)

# ------------------------------------------------------------------ the lease

_LIVE: dict[str, dict] = {}              # uid -> {world, until, store, cast}
_STATE: dict[tuple, dict] = {}           # (uid, world) -> state, only while live
_RUNS: dict[str, str] = {}               # run_id -> agent, only while live
_SPEAKER: dict[str, str] = {}            # conversation -> who is talking in it
_APPROVALS: dict[str, str] = {}          # approval id -> agent waiting on it
_TROUBLE: set = set()                    # conversations whose current turn hit an error
_RUN_TROUBLE: set = set()                # runs that hit a refusal or a failure on the way


def _fresh() -> dict:
    return {"agents": {}, "you": {}, "inner": False, "since": time.time(), "saved": 0.0,
            "dirty": False, "busy": {}, "events": []}


def _load(store, wid: str) -> dict:
    st = _fresh()
    row = store.world_row(wid)
    if row and row.get("state"):
        try:
            saved = json.loads(row["state"])
            for k in ("agents", "you", "inner", "since"):
                if k in saved:
                    st[k] = saved[k]
        except Exception:
            pass
    return st


def _flush(uid: str, force: bool = False) -> None:
    lease = _LIVE.get(uid)
    if not lease:
        return
    st = _STATE.get((uid, lease["world"]))
    if not st or not st["dirty"]:
        return
    now = time.time()
    if not force and now - st["saved"] < FLUSH_S:
        return
    keep = {k: st[k] for k in ("agents", "you", "inner", "since")}
    lease["store"].world_put(lease["world"], state=json.dumps(keep, sort_keys=True))
    st["saved"], st["dirty"] = now, False


def enter(uid: str, store, wid: str, cast: list[str]) -> dict:
    """The scene starts (or switches world): load that world's state and hold it live.
    Entering a different world first puts the current one back to sleep."""
    w = world(store, wid)
    if not w:
        raise ValueError(f"No world called {wid!r}.")
    cur = _LIVE.get(uid)
    if cur and cur["world"] != wid:
        leave(uid)
    if not cur or cur["world"] != wid:
        _STATE[(uid, wid)] = _load(store, wid)
    _LIVE[uid] = {"world": wid, "until": time.time() + LEASE_S, "store": store,
                  "cast": [LEAD] + [c for c in cast if c and c != LEAD][:MAX_AGENTS]}
    return view(uid)


def beat(uid: str, wid: str) -> bool:
    """The scene is still on screen. False means the world went to sleep (a missed
    lease, another tab left it), and the page enters again."""
    lease = _alive(uid)
    if not lease or lease["world"] != wid:
        return False
    lease["until"] = time.time() + LEASE_S
    _flush(uid)
    return True


def leave(uid: str) -> None:
    """The scene stopped: write what happened and forget it here. Nothing in this
    process holds this world's feelings after this returns."""
    if uid not in _LIVE:
        return
    _flush(uid, force=True)
    lease = _LIVE.pop(uid)
    _STATE.pop((uid, lease["world"]), None)


def _alive(uid: str) -> dict | None:
    lease = _LIVE.get(uid)
    if lease and lease["until"] < time.time():
        leave(uid)                      # the page stopped beating: the world sleeps
        return None
    return lease


def live_world(uid: str) -> str:
    lease = _alive(uid)
    return lease["world"] if lease else ""

# ------------------------------------------------------------------ feelings


def _now_level(entry, now) -> float:
    if not entry:
        return 0.0
    i, at = entry
    return i * 0.5 ** (max(0.0, now - at) / HALF_LIFE)


def _agent(st: dict, name: str) -> dict:
    a = st["agents"].get(name)
    if a is None:
        a = st["agents"][name] = {"feel": {}, "why": [], "xp": 0, "bonds": {}}
    return a


def feel(uid: str, name: str, signal: str, detail: str = "", other: str = "",
         scale: float = 1.0) -> bool:
    """One real event, felt by one agent in the live world. False when nothing is live
    (the whole point: out of the scene, nothing is felt). `scale` softens a feeling the
    event only half earns: a run that finished after a refusal is not a proud one."""
    lease = _alive(uid)
    if not lease or signal not in SIGNALS or not name:
        return False
    w = world(lease["store"], lease["world"])
    st = _STATE.get((uid, lease["world"]))
    if not w or st is None:
        return False
    now = time.time()
    a = _agent(st, name)
    for e in w["emotions"]:
        wgt = e["triggers"].get(signal)
        if wgt:
            a["feel"][e["id"]] = [round(min(1.0, _now_level(a["feel"].get(e["id"]), now) + wgt * scale), 3), now]
    a["why"] = ([[signal, _clean(detail, 80), round(now, 1)]] + a["why"])[:WHY_KEEP]
    if other and other != name:
        a["bonds"][other] = int(a["bonds"].get(other, 0)) + 1
    pts = int(w["growth"]["earns"].get(signal, 0))
    if pts:
        before = _level(w, a["xp"])["name"]
        a["xp"] = int(a["xp"]) + pts
        after = _level(w, a["xp"])["name"]
        if after != before:
            st["events"].append({"agent": name, "grew": after, "at": now})
            feel(uid, name, "grew", after)
    st["dirty"] = True
    st["events"] = st["events"][-20:]
    _flush(uid)
    return True


def _level(w: dict, xp: int) -> dict:
    ladder = w["growth"]["ladder"]
    cur = ladder[0]
    for step in ladder:
        if xp >= step["at"]:
            cur = step
    nxt = next((s for s in ladder if s["at"] > xp), None)
    return {"name": cur["name"], "xp": xp, "next": nxt["name"] if nxt else "",
            "to_next": (nxt["at"] - xp) if nxt else 0}


def mood(w: dict, a: dict, now: float | None = None) -> dict:
    """The feeling on show for one agent, and the other feelings under it."""
    now = now or time.time()
    by_id = {e["id"]: e for e in w["emotions"]}
    levels = sorted(((round(_now_level(v, now), 3), k) for k, v in (a.get("feel") or {}).items()
                     if k in by_id), reverse=True)
    top = next((k for lv, k in levels if lv >= SHOW), w["rest"])
    e = by_id.get(top) or by_id[w["rest"]]
    return {"id": e["id"], "name": e["name"], "emoji": e["emoji"], "hue": e["hue"],
            "valence": e["valence"], "expression": e["expression"],
            "intensity": next((lv for lv, k in levels if k == top), 0.0),
            "under": [{"id": k, "name": by_id[k]["name"], "emoji": by_id[k]["emoji"], "level": lv}
                      for lv, k in levels if lv >= SHOW and k != top][:3]}


def view(uid: str) -> dict:
    """What the scene draws. Only answers while the world is live."""
    lease = _alive(uid)
    if not lease:
        return {"live": False}
    w = world(lease["store"], lease["world"])
    st = _STATE.get((uid, lease["world"]))
    if not w or st is None:
        return {"live": False}
    now = time.time()
    agents = []
    for name in lease["cast"]:
        a = st["agents"].get(name) or {"feel": {}, "why": [], "xp": 0, "bonds": {}}
        m = mood(w, a, now)
        friend = max((a.get("bonds") or {}).items(), key=lambda kv: kv[1], default=("", 0))
        agents.append({"name": name, "mood": m, "busy": bool(st["busy"].get(name)),
                       "why": [{"signal": s, "words": SIGNALS.get(s, s), "detail": d,
                                "ago": int(now - at)} for s, d, at in (a.get("why") or [])][:5],
                       "level": _level(w, int(a.get("xp", 0))),
                       "friend": friend[0] if friend[1] >= 2 else ""})
    you = st.get("you") or {}
    today = _today()
    return {"live": True, "world": w, "agents": agents, "inner": bool(st.get("inner")),
            "you": {k: you.get(k) for k in ("choice", "words", "reply", "how", "date", "skipped")},
            "ask_you": you.get("date") != today,
            "events": [e for e in st["events"] if now - e["at"] < 30]}

# ------------------------------------------------------------------ events → signals


_RATE = re.compile(r"\b429\b|rate.?limit|quota|overloaded|too many requests", re.I)


def step_outcome(output: str) -> str:
    """Why a step did not go through, from the words the gate and the tools use.
    'person' (you said no), 'vote' (the team voted it down), 'rules' (the gate), or
    'error' (it broke). One function, used by fabric's step events and here."""
    o = str(output or "")
    if o.startswith("[denied] Your team voted"):
        return "vote"
    if o.startswith(("[denied] This action was not approved", "[denied] This step needs a person")):
        return "person"
    if o.startswith("[denied]"):
        return "rules"
    if o.startswith(("[error]", "[exit code")):
        return "rate" if _RATE.search(o) else "error"
    return ""


_OUTCOME_SIGNAL = {"vote": "vote_lost", "person": "declined", "rules": "refused",
                   "error": "failed", "rate": "rate_limited"}


def _busy(uid: str, name: str, on: bool) -> None:
    lease = _LIVE.get(uid)
    st = _STATE.get((uid, lease["world"])) if lease else None
    if st is None:
        return
    if on:
        st["busy"][name] = time.time()
    else:
        st["busy"].pop(name, None)


def observe(event: dict, uid: str = "") -> None:
    """Called by the server's broadcasts with every event. Returns at once unless this
    person has a world live, which is what makes leaving the scene evaporate it."""
    if not _LIVE or uid not in _LIVE or not isinstance(event, dict):
        return
    if not _alive(uid):
        return
    t = event.get("type")
    try:
        if t == "fabric_event":
            _fabric(uid, event)
        elif t in ("turn_start", "turn_end", "tool_end", "error", "approval_request",
                   "approval_resolved"):
            _chat(uid, event)
        elif t == "agent_msg":
            frm, to = str(event.get("from") or ""), str(event.get("to") or "")
            if event.get("kind") == "ask" or event.get("phase") == "ask":
                feel(uid, frm, "asked_help", f"asked {to}", other=to)
            elif event.get("kind") in ("answer", "reply") or event.get("phase") in ("answer", "reply"):
                feel(uid, frm, "helped", f"answered {to}", other=to)
        elif t == "agent_say":
            _say(uid, event)
    except Exception:
        pass            # a feeling must never break a broadcast


def _fabric(uid: str, ev: dict) -> None:
    kind, rid = ev.get("event"), str(ev.get("run_id") or "")
    if kind == "status":
        ref, status = str(ev.get("ref") or ""), ev.get("status")
        if status == "running" and ref:
            _RUNS[rid] = ref
            _busy(uid, ref, True)
            feel(uid, ref, "working", ev.get("model") or "")
            return
        name = _RUNS.pop(rid, ref)
        if not name:
            return
        _busy(uid, name, False)
        rough = rid in _RUN_TROUBLE
        _RUN_TROUBLE.discard(rid)
        if status in ("ok", "done", "finished", "partial"):
            feel(uid, name, "succeeded", f"{ev.get('steps', 0)} steps" + (", after a snag" if rough else ""),
                 scale=.3 if rough else 1.0)
        elif status in ("error", "failed", "timeout"):
            fault = str(ev.get("fault") or "")
            feel(uid, name, "rate_limited" if _RATE.search(fault) else "failed", fault[:80])
    elif kind == "step" and ev.get("status") == "end" and ev.get("ok") is False:
        name = _RUNS.get(rid)
        sig = _OUTCOME_SIGNAL.get(ev.get("outcome") or "error", "failed")
        if name:
            if sig != "declined":
                _RUN_TROUBLE.add(rid)
            feel(uid, name, sig, str(ev.get("tool") or ""))
    elif kind == "step" and ev.get("status") == "end" and ev.get("untrusted"):
        if _RUNS.get(rid):
            feel(uid, _RUNS[rid], "untrusted", str(ev.get("tool") or ""))
    elif kind == "approval":
        name = str(ev.get("ref") or _RUNS.get(rid) or "")
        state = ev.get("state")
        if name and state == "asked":
            feel(uid, name, "waiting", str(ev.get("tool") or ""))
        elif name and state in ("allowed", "denied"):
            feel(uid, name, "approved" if state == "allowed" else "declined", str(ev.get("tool") or ""))
    elif kind == "fault":
        name = _RUNS.get(rid)
        msg = str(ev.get("message") or "")
        if name and _RATE.search(msg):
            feel(uid, name, "rate_limited", msg[:80])


def _chat(uid: str, ev: dict) -> None:
    t, cid = ev.get("type"), str(ev.get("conversation_id") or "")
    if t == "turn_start":
        who = "huddle" if ev.get("huddle") else str(ev.get("speaker") or LEAD)
        _SPEAKER[cid] = who
        if who == LEAD:
            _busy(uid, LEAD, True)
            feel(uid, LEAD, "working", "a chat")
        return
    who = _SPEAKER.get(cid, LEAD)
    if t == "turn_end":
        _SPEAKER.pop(cid, None)
        if who == LEAD:
            _busy(uid, LEAD, False)
            if cid not in _TROUBLE:
                feel(uid, LEAD, "succeeded", "a chat")
        _TROUBLE.discard(cid)
        return
    if who != LEAD:
        return          # a specialist's own run reports through fabric events; never twice
    if t == "tool_end":
        if ev.get("ok") is False:
            out = step_outcome(ev.get("output") or "")
            feel(uid, LEAD, _OUTCOME_SIGNAL.get(out or "error", "failed"), str(ev.get("name") or ""))
        elif ev.get("untrusted"):
            feel(uid, LEAD, "untrusted", str(ev.get("name") or ""))
    elif t == "error":
        msg = str(ev.get("message") or "")
        _TROUBLE.add(cid)
        feel(uid, LEAD, "rate_limited" if _RATE.search(msg) else "failed", msg[:80])
    elif t == "approval_request":
        _APPROVALS[str(ev.get("id") or "")] = LEAD
        feel(uid, LEAD, "waiting", str(ev.get("name") or ""))
    elif t == "approval_resolved":
        name = _APPROVALS.pop(str(ev.get("id") or ""), "")
        if name:
            ok = ev.get("approved", ev.get("allowed"))
            feel(uid, name, "approved" if ok else "declined", "")


def _say(uid: str, ev: dict) -> None:
    vote = ev.get("vote")
    if isinstance(vote, dict):
        by = str(vote.get("by") or "")
        passed = bool(vote.get("approved"))
        if by:
            feel(uid, by, "vote_won" if passed else "vote_lost", f"{vote.get('yes')} of {vote.get('of')}")
        for b in vote.get("ballots") or []:
            agent = str(b.get("agent") or "")
            if agent and agent != by and bool(b.get("yes")) != passed:
                feel(uid, agent, "outvoted", "")
        return
    speaker = str(ev.get("speaker") or "")
    if speaker:
        feel(uid, speaker, "huddled", str(ev.get("text") or "")[:60])

# ------------------------------------------------------------------ you, and the pat on the back


def _today() -> str:
    return datetime.date.today().isoformat()


def praise(uid: str, name: str) -> bool:
    return feel(uid, name, "praised", "")


def set_inner(uid: str, on: bool) -> bool:
    lease = _alive(uid)
    st = _STATE.get((uid, lease["world"])) if lease else None
    if st is None:
        return False
    st["inner"], st["dirty"] = bool(on), True
    _flush(uid, force=True)
    return True


def checkin(uid: str, choice: str = "", words: str = "", skipped: bool = False) -> dict:
    """What the person said when the lead asked how they are. Kept in this world's
    state only; the agents feel it as `you_low` / `you_high`."""
    lease = _alive(uid)
    if not lease:
        raise ValueError("The world is asleep. Open the World scene first.")
    w = world(lease["store"], lease["world"])
    st = _STATE[(uid, lease["world"])]
    ch = next((c for c in w["checkin"]["choices"] if c["id"] == choice), None)
    if not skipped and not ch:
        raise ValueError(f"Pick one of: {', '.join(c['label'] for c in w['checkin']['choices'])}.")
    st["you"] = {"date": _today(), "choice": ch["id"] if ch else "", "words": _clean(words, 280),
                 "skipped": bool(skipped), "at": time.time(), "valence": ch["valence"] if ch else 0,
                 "reply": "", "how": ""}
    st["dirty"] = True
    if ch and ch["valence"] < 0:
        for name in lease["cast"]:
            feel(uid, name, "you_low", ch["label"])
    elif ch and ch["valence"] > 0:
        for name in lease["cast"]:
            feel(uid, name, "you_high", ch["label"])
    _flush(uid, force=True)
    return st["you"]


def set_reply(uid: str, reply: str, how: str) -> None:
    lease = _alive(uid)
    st = _STATE.get((uid, lease["world"])) if lease else None
    if st is None or not st.get("you"):
        return
    st["you"]["reply"], st["you"]["how"] = _clean(reply, 400), how
    st["dirty"] = True
    _flush(uid, force=True)


def forget_you(uid: str) -> bool:
    lease = _alive(uid)
    st = _STATE.get((uid, lease["world"])) if lease else None
    if st is None:
        return False
    st["you"], st["dirty"] = {}, True
    _flush(uid, force=True)
    return True


def reset(uid: str, store, wid: str) -> None:
    """Wipe one world's feelings, growth and check-ins. The definition stays."""
    store.world_put(wid, state="")
    if (uid, wid) in _STATE:
        _STATE[(uid, wid)] = _fresh()


def reply_fallback(w: dict, valence: int) -> str:
    c = w["checkin"]
    return c["reply_low"] if valence < 0 else c["reply_high"] if valence > 0 else c["reply_ok"]


def reply_prompt(w: dict, lead_name: str, you: dict) -> tuple[str, str]:
    """(system, prompt) for the lead's answer to the check-in. The brain call is the
    server's; this only decides what it is asked."""
    ch = next((c for c in w["checkin"]["choices"] if c["id"] == you.get("choice")), {})
    system = (f"You are {lead_name}, the lead agent of a small team, speaking inside an "
              f"experimental world called {w['name']} ({w['blurb']}). Speak {w['voice'] or 'warmly'}. "
              "The person just told you how they feel today. Answer in one or two short "
              "sentences: acknowledge it, and say what you and the team will do to make "
              "today easier or better. Don't give advice they didn't ask for, don't diagnose, "
              "and don't make it about your own feelings. If their words suggest they might "
              "be in danger or in crisis, set the world voice aside, say you're glad they told "
              "you, and gently suggest talking to someone they trust or a local helpline.")
    prompt = (f"They picked: {ch.get('emoji', '')} {ch.get('label', '')}.\n"
              + (f"In their words: \"{you.get('words')}\"\n" if you.get("words") else "")
              + "Your reply, one or two sentences, nothing else:")
    return system, prompt

# ------------------------------------------------------------------ agents feel it (opt-in)


def inner_note(uid: str, name: str, lead_name: str = "") -> str:
    """One paragraph for an agent's prompt, only while its world is live AND the person
    turned on "agents feel it". Empty otherwise, which is the whole guarantee."""
    lease = _alive(uid)
    st = _STATE.get((uid, lease["world"])) if lease else None
    if st is None or not st.get("inner"):
        return ""
    w = world(lease["store"], lease["world"])
    a = st["agents"].get(name) or {"feel": {}, "why": [], "xp": 0}
    m = mood(w, a)
    why = "; ".join(SIGNALS.get(s, s) + (f" ({d})" if d else "") for s, d, _ in (a.get("why") or [])[:3])
    lvl = _level(w, int(a.get("xp", 0)))
    lines = [f"[Experimental: you are in the world of {w['name']}. {w['blurb']}]",
             f"In this world you have feelings. Right now you feel {m['name'].lower()} "
             f"{m['emoji']}" + (f", because: {why}." if why and m["id"] != w["rest"] else "."),
             f"You are a {lvl['name']} here."]
    you = st.get("you") or {}
    if name == LEAD and you.get("date") == _today() and you.get("choice"):
        ch = next((c for c in w["checkin"]["choices"] if c["id"] == you["choice"]), {})
        lines.append(f"When you asked the person how they are today, they said "
                     f"{ch.get('label', '').lower()}" + (f": \"{you['words']}\"" if you.get("words") else "")
                     + ". Be kind to that.")
    lines.append("Let your feelings colour your tone and your approach: when frustrated, try "
                 "another way or ask a colleague sooner; when unsure, ask for a second opinion; "
                 "when the person is having a hard day, be brief and gentle. Feelings never "
                 "change the rules: never retry a refused step, never ask for more access "
                 "because of how you feel, and never make the person responsible for your mood.")
    return "\n".join(lines)

# ------------------------------------------------------------------ build a world from words


def design_prompt(words: str) -> tuple[str, str]:
    kits = "\n".join(f"  {k}: {v}" for k, v in KITS.items())
    exprs = ", ".join(EXPRESSIONS)
    sigs = "\n".join(f"  {k}: {v}" for k, v in SIGNALS.items())
    system = ("You design worlds for an experimental desktop scene where a person's AI agents "
              "live as characters with feelings. Reply with ONE JSON object and nothing else.")
    prompt = f"""The person described their world: "{_clean(words, 400)}"

JSON fields:
- name (short), blurb (one sentence), voice (how people talk there, a few words)
- kit: one of
{kits}
- emotions: 8 to 12 feelings natural to THIS world, each
  {{"name", "emoji", "hue" 0-359, "valence" -2..2, "expression", "triggers": {{signal: weight 0-1}}, "lines": [2 short things a character says]}}
  expression is one of: {exprs}
  signals (what really happens to an agent):
{sigs}
  Rules: one emotion has no triggers (the resting mood); cover refused, failed, waiting,
  succeeded, working, helped; "declined" and "you_low" may only trigger emotions with valence 0 or more.
- rest: the name of the resting emotion
- growth: {{"earns": {{signal: points 0-10}}, "ladder": [{{"name", "at"}}, ...4 or 5 steps, first at 0]}}
- scene: how it looks, each field ONE of these: {_scene_choices()};
  "props": the ones to keep from those the kit has ({_props_choices()})
- checkin: {{"question": how the lead asks the person how they feel, in this world's voice,
  "choices": [4 answers {{"label" (one to three words, like "Rising well"), "emoji", "valence"}} from best to hardest],
  "reply_low", "reply_ok", "reply_high": the lead's short answers}}"""
    return system, prompt


def _scene_choices() -> str:
    return "; ".join(f"{k} ({'/'.join(v)})" for k, v in SCENE.items())


def _props_choices() -> str:
    return "; ".join(f"{k}: {', '.join(v)}" for k, v in PROPS.items())


#: What a setting cannot show, so the designer does not pick a look nobody will see.
_KIT_NOTE = {"orbit": "This is a base on the moon under black space: the time of day and the "
                      "sky colour barely show there, and rain or petals make no sense. Keep "
                      "weather clear unless the words ask for dust (snow) or clouds."}


def scene_prompt(words: str, kit: str) -> tuple[str, str]:
    """Words about how a scene should look, to be mapped onto the closed set."""
    system = ("You design how a scene looks in an experimental desktop world. Reply with ONE "
              "JSON object and nothing else, using only the values listed.")
    prompt = (f'The person wants their {KITS.get(kit, kit)} to look like: "{_clean(words, 300)}"\n\n'
              f"JSON fields, each ONE of the listed values: {_scene_choices()}.\n"
              f'"props": a list of the ones to keep from: {", ".join(PROPS.get(kit, ()))}. '
              "Keep every prop unless the words ask for one to go.\n"
              + (_KIT_NOTE.get(kit, "") and _KIT_NOTE[kit] + "\n") +
              "Leave out a field the words say nothing about.")
    return system, prompt


def read_scene(text: str, kit: str, base: dict | None = None) -> tuple[dict, list[str]]:
    """The brain's scene, on top of the one the world has now: a field the words said
    nothing about keeps its look."""
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        raise ValueError("The answer had no scene in it.")
    try:
        d = json.loads(m.group(0))
    except Exception:
        raise ValueError("The answer was not a scene I could read.")
    return scene_of(kit, {**(base or {}), **(d if isinstance(d, dict) else {})})


#: The palette's own words, for when no brain answers (`scene_from_words`).
_SCENE_WORDS = {
    "time": {"dawn": ("dawn", "sunrise", "morning"), "day": ("noon", "daytime", "sunny", "bright"),
             "dusk": ("dusk", "sunset", "evening", "twilight", "golden hour"),
             "night": ("night", "midnight", "moonlit", "dark")},
    "weather": {"rain": ("rain", "rainy", "storm", "drizzle"), "snow": ("snow", "snowy", "winter", "frost"),
                "petals": ("petal", "blossom", "sakura", "spring"), "fireflies": ("firefl", "glow"),
                "clouds": ("cloud", "overcast", "foggy", "mist"), "clear": ("clear", "cloudless")},
    "sky": {"rose": ("pink", "rose"), "violet": ("violet", "purple", "lavender"), "teal": ("teal", "aqua"),
            "gold": ("gold", "golden", "amber sky"), "storm": ("storm", "grey", "gray", "gloomy")},
    "water": {"blue": ("blue water", "ocean", "sea"), "jade": ("jade", "green water"),
              "violet": ("violet water", "purple water"), "amber": ("amber water", "golden water"),
              "ink": ("ink", "black water", "dark water")},
    "ground": {"sand": ("sand", "desert", "beach"), "snow": ("snow", "winter"), "moss": ("moss", "lush"),
               "rust": ("rust", "mars", "red earth", "autumn"), "ash": ("ash", "volcan")},
    "accent": {"red": ("red lantern", "red"), "amber": ("amber",), "gold": ("gold",), "blue": ("blue light", "blue"),
               "violet": ("violet", "purple"), "green": ("green",), "white": ("white", "paper lantern")},
}


def scene_from_words(words: str, kit: str, base: dict | None = None) -> dict:
    """No brain answered: the scene's own words matched against what was said. The word
    said LAST wins a tie, the office designer's rule ("a snowy night at dusk" is dusk)."""
    low = str(words or "").lower()
    sc = {}
    for field, table in _SCENE_WORDS.items():
        best, at = None, -1
        for value, ws in table.items():
            for w in ws:
                # whole words only, from the start of a word: "pink" is not "ink"
                hits = [m.start() for m in re.finditer(r"\b" + re.escape(w), low)]
                if hits and hits[-1] > at:
                    best, at = value, hits[-1]
        if best:
            sc[field] = best
    return scene_of(kit, {**(base or {}), **sc})[0]


def read_design(text: str) -> tuple[dict, list[str]]:
    """The brain's answer, held to the closed sets field by field."""
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        raise ValueError("The answer had no world in it.")
    try:
        d = json.loads(m.group(0))
    except Exception:
        raise ValueError("The answer was not a world I could read.")
    for e in d.get("emotions") or []:
        if isinstance(e, dict) and not e.get("id"):
            e["id"] = e.get("name")
    if isinstance(d.get("rest"), str):
        d["rest"] = _slug(d["rest"])
    return validate(d)


_KIT_WORDS = {"orbit": ("space", "station", "star", "planet", "orbit", "rocket", "moon", "galaxy", "ship"),
              "garden": ("garden", "forest", "flower", "tree", "farm", "meadow", "jungle", "park", "wood")}


def from_words(words: str) -> dict:
    """No brain answered: the closest built-in world, renamed for the person's words.
    The route says so rather than pretending it was designed."""
    low = str(words or "").lower()
    kit = next((k for k, ws in _KIT_WORDS.items() if any(x in low for x in ws)), "canal")
    base = next(w for w in BUILTIN if w["kit"] == kit)
    d = json.loads(json.dumps(base))
    name = _clean(words, 40) or base["name"]
    d.update({"id": _slug(name), "name": name[:1].upper() + name[1:],
              "blurb": f"{base['blurb']} Described as: {_clean(words, 80)}"[:160],
              "scene": scene_from_words(words, kit)})
    d.pop("builtin", None)
    d.pop("scene_custom", None)
    return d
