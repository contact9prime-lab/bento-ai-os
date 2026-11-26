"""Which tab of Chat a conversation is under: Desktop, Channels, Devices, Huddles, App builder.

Asked for as "the huddle must be recorded in the chat as a separate section, and the chat must
have tabs and search: Desktop, Channels, Devices, Huddles, App builder". One function decides it
for the page and the terminal, from what the conversation row and its messages already say:

  * Channels: a phone thread (Telegram, WhatsApp);
  * Devices: a Zero's screen or a linked team, worked here;
  * App builder: App Studio, or a chat that built or changed an app (app_versions names it);
  * Huddles: a free talk, or a conversation where agents huddled (a message with `huddle` meta).
    A huddle is ALSO listed under the tab it happened in, so it is never found in one place only;
  * Desktop: everything else (Chat, the prompt bar, copilots, the kiosk, schedules).

Free of HTTP and asyncio.
"""
from __future__ import annotations

import re

TABS = ("desktop", "channels", "devices", "huddles", "apps")
NAMES = {"desktop": "Desktop", "channels": "Channels", "devices": "Devices", "huddles": "Huddles",
         "apps": "App builder"}
# The list is read whole and cut PER TAB. Cut once at the newest 100 overall, a busy machine's
# schedules (147 on the owner's, firing all day) pushed every Telegram thread out of the list,
# and Channels read "Telegram and WhatsApp chats show here" over chats that were there.
PER_TAB = 100
SCAN = 5000
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


def counts(convs: list[dict]) -> dict:
    """How many conversations each tab holds, over the tagged list before it is cut."""
    out = {t: 0 for t in TABS}
    for c in convs:
        for t in c.get("tabs") or [c.get("tab")]:
            if t in out:
                out[t] += 1
    return out


def newest_per_tab(convs: list[dict], n: int = PER_TAB) -> list[dict]:
    """The newest `n` of EACH tab, in the order given (newest first). A conversation listed
    under two tabs stays if either keeps it."""
    seen = {t: 0 for t in TABS}
    out = []
    for c in convs:
        keep = False
        for t in c.get("tabs") or [c.get("tab")]:
            if t in seen and seen[t] < n:
                seen[t] += 1
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
