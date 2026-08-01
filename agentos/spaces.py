"""Spaces — the things the user is working on.

A space is a launch, a client, a channel, a side project. Conversations, assets,
memories, knowledge-graph assertions, runs and scheduled jobs each belong to one
— or to the global scope, which is spelled `''` everywhere in the database.

The one rule worth memorising, because every read path in the OS implements it:

    a space sees ITS OWN rows and the GLOBAL ones.

Not "only its own" (you would lose your own name the moment you switched to a
project) and not "everything" (which is what we had, and is why the graph filled
up with three clients' deadlines competing to answer one question). It is
`space_id IN ('', :active)`, and it is in `memory.Store._space_clause` so there
is exactly one copy of it.

**Where the active space lives.** Two answers, deliberately:

  * `conversations.space_id` is authoritative for a turn. A conversation started
    inside a space stays in it forever, including when it is reopened next month
    from a phone. Scrollback that changes meaning depending on what you clicked
    last would be worse than no spaces at all.
  * `cfg["spaces"]["active"][<surface>]` is only the default for the NEXT new
    conversation on that surface, and it is per-surface on purpose. One global
    "current space" would have the desktop, the TUI and Telegram fighting over a
    single value — you would switch to a client at your desk and silently move
    what your phone does next.

API callers pass `X-AgentOS-Space` and get neither default, because a script has
no "current" anything.
"""

from __future__ import annotations

from .policy import SURFACES

#: the global scope, in the one spelling everything agrees on
GLOBAL = ""


def conf(cfg: dict) -> dict:
    return (cfg or {}).get("spaces") or {}


def active_for(cfg: dict, surface: str = "", store=None,
               conversation_id: str = "") -> str:
    """Which space a turn happens in.

    The conversation wins when it has one — see the module docstring. Falls back
    to the surface's default, and finally to global. A space id that no longer
    exists resolves to global rather than to a dangling filter that would hide
    everything the user has.
    """
    if conversation_id and store is not None:
        row = store.get_conversation(conversation_id) if hasattr(store, "get_conversation") else None
        sid = (row or {}).get("space_id") or ""
        if sid:
            return sid if _exists(store, sid) else GLOBAL
    sid = str((conf(cfg).get("active") or {}).get(surface or "gui") or "")
    if sid and store is not None and not _exists(store, sid):
        return GLOBAL
    return sid


def _exists(store, sid: str) -> bool:
    try:
        return bool(store.get_space(sid))
    except Exception:
        return False


def set_active(cfg: dict, surface: str, space_id: str) -> str:
    """Point one surface at a space. Returns the value actually set."""
    if surface and surface not in SURFACES:
        surface = "gui"
    spaces = cfg.setdefault("spaces", {})
    active = spaces.setdefault("active", {})
    active[surface or "gui"] = space_id or ""
    return active[surface or "gui"]


def label(store, space_id: str) -> str:
    """A human name for a space id — 'Everywhere' for global, because 'no space'
    reads like a missing value and this is a real, meaningful scope."""
    if not space_id:
        return "Everywhere"
    row = store.get_space(space_id)
    return (row or {}).get("name") or "Everywhere"


def describe(store, space_id: str) -> dict:
    """What the extraction model and the UI are told about the current space."""
    if not space_id:
        return {"id": "", "name": "Everywhere", "description":
                "no particular project — facts here are true no matter what the user is doing",
                "icon": "", "colour": ""}
    row = store.get_space(space_id) or {}
    return {"id": row.get("id", ""), "name": row.get("name", "Everywhere"),
            "description": row.get("description", ""), "icon": row.get("icon", ""),
            "colour": row.get("colour", "")}


def public(store, cfg: dict) -> dict:
    """Everything the UI needs to draw a space switcher in one request."""
    rows = store.list_spaces()
    return {
        "spaces": [{"id": r["id"], "name": r["name"], "icon": r.get("icon", ""),
                    "colour": r.get("colour", ""), "description": r.get("description", ""),
                    "workspace": r.get("workspace", ""),
                    "updated_at": r.get("updated_at", 0)} for r in rows],
        "active": (conf(cfg).get("active") or {}),
        "global_label": "Everywhere",
    }
