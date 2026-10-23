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
    q = ",".join("?" * len(ids))
    hud = {r[0] for r in store.db.execute(
        f"SELECT DISTINCT conversation_id FROM messages WHERE conversation_id IN ({q}) "
        f"AND meta LIKE '%\"huddle\"%'", ids).fetchall()}
    try:
        apps = {r[0] for r in store.db.execute(
            f"SELECT DISTINCT conversation_id FROM app_versions WHERE conversation_id IN ({q})", ids).fetchall()}
    except Exception:
        apps = set()
    return hud, apps


def tag(store, convs: list[dict]) -> list[dict]:
    """Each conversation with `tab` (its home) and `tabs` (every tab it is listed under)."""
    hud, apps = marks(store, [c["id"] for c in convs])
    out = []
    for c in convs:
        home = home_of(c, apps)
        tabs = [home] + (["huddles"] if c["id"] in hud and home != "huddles" else [])
        out.append({**c, "tab": home, "tabs": tabs})
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
