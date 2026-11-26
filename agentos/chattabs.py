"""Which tab of Chat a conversation is under: Desktop, Missions, Channels, Devices, Huddles, App builder.

Asked for as "the huddle must be recorded in the chat as a separate section, and the chat must
have tabs and search: Desktop, Channels, Devices, Huddles, App builder". One function decides it
for the page and the terminal, from what the conversation row and its messages already say:

  * Channels: a phone thread (Telegram, WhatsApp);
  * Devices: a Zero's screen or a linked team, worked here;
  * App builder: App Studio, or a chat that built or changed an app (app_versions names it);
  * Huddles: a free talk, or a conversation where agents huddled (a message with `huddle` meta).
    A huddle is ALSO listed under the tab it happened in, so it is never found in one place only;
  * Missions: what ran on its own, a scheduled prompt's run or the day's Brief. Asked for as
    "the prompt based chats are also coming in, that should have a separate section": a 5-minute
    scan made 98 of the newest 100 Desktop chats. Missions -> History has every run as well;
  * Desktop: everything a person started (Chat, the prompt bar, copilots, the kiosk).

Free of HTTP and asyncio.
"""
from __future__ import annotations

import re

TABS = ("desktop", "missions", "channels", "devices", "huddles", "apps")
NAMES = {"desktop": "Desktop", "missions": "Missions", "channels": "Channels", "devices": "Devices", "huddles": "Huddles",
         "apps": "App builder"}
# The list is read whole and cut PER TAB. Cut once at the newest 100 overall, a busy machine's
# schedules (147 on the owner's, firing all day) pushed every Telegram thread out of the list,
# and Channels read "Telegram and WhatsApp chats show here" over chats that were there.
PER_TAB = 100
SCAN = 5000
# What ran on its own: the scheduler's OS_ORIGINS (a scheduled prompt, a trigger, "while you were
# away", a suggestion) and the day's Brief. Its home is Missions.
AUTO = ("schedule", "trigger", "briefing", "suggestion", "brief")
# Under Missions the runs are grouped by the schedule that made them ("group these into individual
# missions"), and each group keeps its own newest PER_MISSION, so a 5-minute scan can't push a
# daily schedule out of the tab.
PER_MISSION = 30
_FIXED = {"brief": "Your Brief", "briefing": "While you were away", "suggestion": "Suggestions"}
_CHUNK = 500        # SQLite's variable limit can be 999 on an older build
_PHONE = re.compile(r"^(✈ )?(Telegram|WhatsApp) · ")


def home_of(c: dict, apps: set) -> str:
    origin, title = str(c.get("origin") or ""), str(c.get("title") or "")
    if origin in ("telegram", "whatsapp") or _PHONE.match(title):
        return "channels"
    if origin == "zero" or (origin == "team" and title.startswith("↔ ")):
        return "devices"
    if origin == "studio" or c.get("id") in apps or title.startswith("build: "):
        return "apps"
    if origin == "freetalk":
        return "huddles"
    if origin in AUTO:
        return "missions"
    return "desktop"


def marks(store, ids: list[str]) -> tuple[set, set]:
    """(conversations with a huddle in them, conversations that built an app), among `ids`."""
    if not ids:
        return set(), set()
    hud, apps = set(), set()
    for i in range(0, len(ids), _CHUNK):
        part = ids[i:i + _CHUNK]
        q = ",".join("?" * len(part))
        hud |= {r[0] for r in store.db.execute(
            f"SELECT DISTINCT conversation_id FROM messages WHERE conversation_id IN ({q}) "
            f"AND meta LIKE '%\"huddle\"%'", part).fetchall()}
        try:
            apps |= {r[0] for r in store.db.execute(
                f"SELECT DISTINCT conversation_id FROM app_versions WHERE conversation_id IN ({q})",
                part).fetchall()}
        except Exception:
            pass
    return hud, apps


def tag(store, convs: list[dict]) -> list[dict]:
    """Each conversation with `tab` (its home) and `tabs` (every tab it is listed under)."""
    hud, apps = marks(store, [c["id"] for c in convs])
    out = []
    for c in convs:
        home = home_of(c, apps)
        tabs = [home] + (["huddles"] if c["id"] in hud and home != "huddles" else [])
        if c.get("channel_ref") and "channels" not in tabs:
            tabs.append("channels")     # a desktop chat carried on from a phone is found there too
        out.append({**c, "tab": home, "tabs": tabs})
    return out


def _name(text: str) -> str:
    """A schedule's name, from the start of what it asks: up to the first bracket, colon or full stop."""
    t = re.sub(r"^\[[^\]]*\]\s*", "", str(text or "").strip().lstrip("⏱⚡ ").strip())
    t = t.splitlines()[0] if t else ""
    t = re.split(r"\s\(|:\s|\.\s|…", t, maxsplit=1)[0].strip()
    if len(t) > 60:
        t = t[:60].rsplit(" ", 1)[0] + "…"
    return t or "A scheduled prompt"


def missions(store, convs: list[dict]) -> list[dict]:
    """Each conversation under Missions gets `mission` = {key, name}: the schedule it is a run of
    (task_runs names it), else one group per kind (the Brief) or per title."""
    ids = [c["id"] for c in convs if "missions" in (c.get("tabs") or [])]
    task_of: dict = {}
    for i in range(0, len(ids), _CHUNK):
        part = ids[i:i + _CHUNK]
        q = ",".join("?" * len(part))
        try:
            for cid, tid, prompt in store.db.execute(
                    f"SELECT r.conversation_id, r.task_id, COALESCE(t.prompt, r.prompt) FROM task_runs r "
                    f"LEFT JOIN tasks t ON t.id = r.task_id WHERE r.conversation_id IN ({q})", part).fetchall():
                task_of[cid] = (tid, prompt)
        except Exception:
            pass
    out = []
    for c in convs:
        if "missions" in (c.get("tabs") or []):
            origin = str(c.get("origin") or "")
            if origin in _FIXED:
                m = {"key": origin, "name": _FIXED[origin]}
            elif c["id"] in task_of and task_of[c["id"]][0]:
                tid, prompt = task_of[c["id"]]
                m = {"key": "task:" + str(tid), "name": _name(prompt or c.get("title"))}
            else:
                n = _name(c.get("title"))
                m = {"key": "title:" + n, "name": n}
            c = {**c, "mission": {**m, "kind": origin}}
        out.append(c)
    return out


def mission_counts(convs: list[dict]) -> dict:
    """How many runs each mission group has, before the list is cut."""
    out: dict = {}
    for c in convs:
        k = (c.get("mission") or {}).get("key")
        if k:
            out[k] = out.get(k, 0) + 1
    return out


def counts(convs: list[dict]) -> dict:
    """How many conversations each tab holds, over the tagged list before it is cut."""
    out = {t: 0 for t in TABS}
    for c in convs:
        for t in c.get("tabs") or [c.get("tab")]:
            if t in out:
                out[t] += 1
    return out


def newest_per_tab(convs: list[dict], n: int = PER_TAB) -> list[dict]:
    """The newest `n` of EACH tab, in the order given (newest first); under Missions, the newest
    PER_MISSION of each mission. A conversation listed under two tabs stays if either keeps it."""
    seen: dict = {}
    out = []
    for c in convs:
        keep = False
        for t in c.get("tabs") or [c.get("tab")]:
            if t not in TABS:
                continue
            key, cap = t, n
            if t == "missions" and c.get("mission"):
                key, cap = (t, c["mission"]["key"]), min(n, PER_MISSION)
            if seen.get(key, 0) < cap:
                seen[key] = seen.get(key, 0) + 1
                keep = True
        if keep:
            out.append(c)
    return out


def search(store, q: str, limit: int = 100) -> set:
    """Ids of conversations whose title or any message says `q`."""
    q = str(q or "").strip()
    if not q:
        return set()
    like = f"%{q}%"
    ids = {r[0] for r in store.db.execute(
        "SELECT id FROM conversations WHERE title LIKE ? LIMIT ?", (like, limit)).fetchall()}
    ids |= {r[0] for r in store.db.execute(
        "SELECT DISTINCT conversation_id FROM messages WHERE content LIKE ? LIMIT ?", (like, limit)).fetchall()}
    return ids
