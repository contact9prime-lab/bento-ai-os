"""Where an app may send a message: the person's own Telegram and WhatsApp, and the chats
and groups they already let in.

Asked for as "the channels have no hook into the apps: an app should report on these
channels too, Telegram's / buttons should ask the apps, and a schedule should give its data
to the channels or their groups". Three rules:

- **A destination is a chat the person already allowed.** The paired owner's chat, an
  allow-listed person, a group or channel the owner let in. An app never names a chat id
  of its own choosing; `resolve` refuses anything not in `destinations`, so an app cannot
  message a stranger, and a group the owner switched off is gone from the list at once.
- **Sending is the APP's permission, per destination** (`channel.send` on
  `channel:<telegram|whatsapp>/<id>`), decided as the app whoever runs the step
  (`agent.APP_SPEAKS`): its page, its job, or a schedule's agent working for it. The first
  send asks, with Remember; an app job's card asks for its destinations with the script.
- **Every message says which app sent it** (`framed`), because a group's members did not
  install the app and a bare "BTC down 4%" from the owner's bot reads as the owner talking.

Stdlib only, no HTTP or asyncio: the CLI and the tests read the same list.
"""
from __future__ import annotations

import re

CHANNELS = ("telegram", "whatsapp")
MAX_TEXT = 3500          # one Telegram message with room for the app's name
MAX_TARGETS = 5          # an app job's destinations
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f‪-‮⁦-⁩]")


def _tg(cfg: dict) -> dict:
    return (cfg or {}).get("telegram") or {}


def _wa(cfg: dict) -> dict:
    try:
        from .whatsapp import conf
        return conf(cfg or {})
    except Exception:
        return (cfg or {}).get("whatsapp") or {}


def destinations(store, cfg: dict) -> list[dict]:
    """Every chat an app may be allowed to send to, as {id, channel, label, kind}.
    kind is you, person or group. The owner's chat comes first on each channel."""
    out: list[dict] = []
    owner = _tg(cfg).get("owner_chat_id")
    if _tg(cfg).get("bot_token") and owner:
        out.append({"id": f"telegram:{owner}", "channel": "telegram", "label": "you on Telegram",
                    "kind": "you"})
        try:
            chats = store.tg_list_chats()
        except Exception:
            chats = []
        for c in chats:
            if not c.get("allowed") or str(c.get("chat_id")) == str(owner):
                continue
            group = (c.get("type") or "private") != "private"
            name = c.get("title") or (("@" + c["username"]) if c.get("username") else str(c["chat_id"]))
            out.append({"id": f"telegram:{c['chat_id']}", "channel": "telegram",
                        "label": f"{'the group' if group else ''} {name} on Telegram".strip(),
                        "name": name, "kind": "group" if group else "person"})
    wa = _wa(cfg)
    wowner = str(wa.get("owner_wa_id") or "")
    if wowner:
        out.append({"id": f"whatsapp:{wowner}", "channel": "whatsapp", "label": "you on WhatsApp",
                    "kind": "you"})
        try:
            chats = store.wa_list_chats()
        except Exception:
            chats = []
        for c in chats:
            if not c.get("allowed") or str(c.get("wa_id")) == wowner:
                continue
            group = str(c.get("wa_id") or "").endswith("@g.us")
            name = c.get("name") or str(c["wa_id"])
            out.append({"id": f"whatsapp:{c['wa_id']}", "channel": "whatsapp",
                        "label": f"{'the group' if group else ''} {name} on WhatsApp".strip(),
                        "name": name, "kind": "group" if group else "person"})
    return out


def resolve(store, cfg: dict, to: str) -> tuple[dict | None, str]:
    """(destination, refusal). `to` is an id from `destinations`, a channel's name alone (the
    owner there), or a chat's or group's name. Anything else is refused with the list."""
    to = " ".join(str(to or "").split())
    rows = destinations(store, cfg)
    if not rows:
        return None, ("[error] no channel is set up: pair Telegram or WhatsApp first "
                      "(Settings → Channels), then this app can send there")
    want = to.lower() or "telegram"
    if want in CHANNELS:
        hit = next((r for r in rows if r["channel"] == want and r["kind"] == "you"), None)
    else:
        hit = next((r for r in rows if r["id"].lower() == want), None) or next(
            (r for r in rows if (r.get("name") or "").lower().lstrip("@") == want.lstrip("@")), None)
    if hit:
        return hit, ""
    names = "; ".join(f"{r['id']} ({r['label']})" for r in rows[:10])
    return None, (f"[error] '{to}' is not a chat this app may send to. Only chats you already let "
                  f"in can be used: {names}")


def resource_of(dest: dict) -> str:
    chan, _, chat = dest["id"].partition(":")
    return f"channel:{chan}/{chat}"


def resource_for(to: str) -> str:
    """The gate's resource for a destination the call names, before it is resolved: the
    gate decides the exact chat, and an unresolvable name decides `channel:*` (refused in
    the tool after it)."""
    to = str(to or "").strip().lower()
    if ":" in to and to.split(":", 1)[0] in CHANNELS:
        chan, _, chat = to.partition(":")
        return f"channel:{chan}/{chat}"
    return f"channel:{to or 'telegram'}/*"


def clean(text) -> str:
    text = _CONTROLS.sub("", str(text or "")).strip()
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT].rsplit(" ", 1)[0] + " …"
    return text


def framed(app_name: str, text: str) -> str:
    """The message as it is sent: the app's name first, so anybody reading knows it is an
    app on this machine talking and not the person."""
    return f"▦ {app_name or 'an app'}\n{text}"


def clean_targets(store, cfg: dict, targets) -> tuple[list[dict], str]:
    """An app job's `send_to`, read item by item: each one resolved, duplicates dropped,
    at most MAX_TARGETS. A wrong one refuses the whole save, in words."""
    if targets in (None, "", []):
        return [], ""
    if isinstance(targets, str):
        targets = [t for t in re.split(r"[,\n]", targets) if t.strip()]
    if not isinstance(targets, list):
        return [], "[error] send_to is a list of chats, e.g. [\"telegram\"]"
    out: list[dict] = []
    for t in targets[:MAX_TARGETS + 1]:
        dest, err = resolve(store, cfg, str(t))
        if err:
            return [], err
        if all(d["id"] != dest["id"] for d in out):
            out.append(dest)
    if len(out) > MAX_TARGETS:
        return [], f"[error] at most {MAX_TARGETS} chats for one job"
    return out, ""


def label_of(store, dest_id: str) -> str:
    """A saved destination in words with only the database to hand (Missions, the terminal):
    the chat's title as Telegram or WhatsApp gave it."""
    chan, _, chat = str(dest_id or "").partition(":")
    try:
        rows = store.tg_list_chats() if chan == "telegram" else store.wa_list_chats() if chan == "whatsapp" else []
    except Exception:
        rows = []
    key = "chat_id" if chan == "telegram" else "wa_id"
    row = next((r for r in rows if str(r.get(key)) == chat), None)
    name = ((row or {}).get("title") or (row or {}).get("name") or "") if row else ""
    return f"{name or chat} on {chan.title() or 'a channel'}"


def words(dests: list[dict]) -> str:
    names = [d["label"] for d in dests]
    if len(names) > 1:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return names[0] if names else "nowhere"
