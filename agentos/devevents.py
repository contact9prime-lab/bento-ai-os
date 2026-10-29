"""What happened to the machines on this network, newest first: Devices → Events.

Asked for as "in the devices section we need to have events". Nothing new is stored. Two
records already say it, and this reads them together:

  * the machine's diary, kind `device`: what the minute watch saw (server._ties_check): a
    machine moved to another address, stopped answering, answers again, is on a new version,
    its screen was refreshed;
  * the ledger rows about machines (`device.*`, `link.*`, `provision.*`, `zero.*`): scanned,
    installed, secured, switched, linked, set up, asked to update.

Both are read from the machine's database AND the person's own, because a step done from a
signed-in page is written in that account and one done by the server in the machine's.

Free of HTTP and asyncio: `bento network events` reads the same rows with the server down.
"""
from __future__ import annotations

import json

PREFIXES = ("device.", "link.", "provision.", "zero.")
LIMIT = 200

# the ledger's own words for a step, when its row has no sentence of its own
WORDS = {
    "device.seen": "heard on the network", "device.scan": "the network was scanned",
    "device.install": "installing Bento", "device.installed": "Bento installed",
    "device.failed": "the install stopped", "device.check": "security checked",
    "device.secure": "securing it", "device.secured": "secured", "device.secure_failed": "securing it failed",
    "device.update": "asked to update", "device.remove": "Bento removed", "device.disconnect": "disconnected",
    "device.switch": "a switch changed", "device.hardware": "its hardware was read", "device.look": "its agent's look changed",
    "device.get": "a reading was asked for", "device.set": "something was set", "device.permits": "what may be used changed",
    "link.write": "linked", "link.revoke": "link ended", "link.request": "asked to link",
    "provision.enable": "set up from here", "provision.claimed": "set up by its hub",
    "zero.update": "asked to update",
}


def _label(resource: str) -> str:
    r = str(resource or "")
    return r.split(":", 1)[1] if ":" in r else r


def _rows(store, limit: int) -> list[dict]:
    out = []
    for r in store.list_logs("device", limit):
        try:
            m = json.loads(r.get("meta") or "{}")
        except ValueError:
            m = {}
        out.append({"at": r.get("created_at") or 0, "event": m.get("event") or "note",
                    "label": m.get("link") or "", "text": r.get("message") or "", "from": "watch"})
    where = " OR ".join("action LIKE ?" for _ in PREFIXES)
    for r in store.db.execute(f"SELECT ts, action, resource, detail, reason, effect FROM audit "
                              f"WHERE ({where}) ORDER BY ts DESC LIMIT ?",
                              (*[p + "%" for p in PREFIXES], limit)).fetchall():
        r = dict(r)
        if r["action"] in ("device.moved", "device.hardware", "device.get", "device.set", "device.permits", "device.esp",
                           "device.trigger"):
            continue                    # the watch's own line says it (how it was found, what changed)
        out.append({"at": r["ts"] or 0, "event": r["action"].split(".", 1)[1], "action": r["action"],
                    "label": _label(r["resource"]),
                    "text": (r.get("detail") or r.get("reason") or WORDS.get(r["action"]) or r["action"])[:400],
                    "failed": r.get("effect") == "deny", "from": "ledger"})
    return out


def gather(stores, who: str = "", limit: int = LIMIT) -> list[dict]:
    """Events from these stores, newest first, once each. `who` (comma-separated) keeps the ones
    about one machine: its label, or an address or MAC its row names."""
    seen, out = set(), []
    for st in stores:
        if st is None:
            continue
        try:
            got = _rows(st, limit)
        except Exception:
            continue
        for e in got:
            k = (round(e["at"], 1), e["event"], e["text"])
            if k in seen:
                continue
            seen.add(k)
            out.append(e)
    ws = [x.strip() for x in str(who or "").lower().split(",") if x.strip()]
    if ws:
        out = [e for e in out if any(w == e["label"].lower() or w in e["text"].lower() for w in ws)]
    out.sort(key=lambda e: e["at"], reverse=True)
    return out[:limit]


def text(events: list[dict]) -> str:
    import time as _t
    if not events:
        return "  Nothing has happened to the machines here yet."
    return "\n".join(f"  {_t.strftime('%d %b %H:%M', _t.localtime(e['at']))}  "
                     f"{(e['label'] or '-')[:18]:<18}  {e['text']}" for e in events)
