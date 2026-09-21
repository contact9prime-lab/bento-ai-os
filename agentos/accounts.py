"""Accounts: the mail and calendar a person lets this machine read.

An account is NOT a channel. A channel brings a conversation to this agent
(Telegram, WhatsApp, the window); an account is something the agent reads on
the person's behalf, and the rules are the channel rules' mirror image: every
read is a decision in the ledger (`mail.read`, `calendar.read`), a credential is
personal (`mail` and `calendar` are USER_KEYS), it is masked on every read of
config, and "set up" is PROBED — the card shows the last real sign-in and what
it said, never a green dot for a filled-in form.

This module is the one shape both surfaces read: `state()` for the Settings
cards and the Missions catalogue's "needs a mail account" line, `save()` for
the form and `bento mail`/`bento calendar`, `readiness()` for every mission that
wants one. Kept free of HTTP; the probes are in mail.py and calendars.py.
"""

from __future__ import annotations

import time

from . import calendars as calmod
from . import mail as mailmod
from . import signin
from . import vault

IDS = ("mail", "calendar")

#: What each account exposes to the model, and what it never does — the sentence
#: on the card, because "reads your mail" must be said by the thing that does it.
ABOUT = {
    "mail": {"title": "Mail",
             "what": "Lets the agent SEARCH and READ this mailbox — never mark, move or "
                     "delete. Sending is a separate permission that always asks. Every "
                     "read is a `mail.read` decision in the ledger.",
             "fields": [
                 {"key": "preset", "label": "Provider", "kind": "select",
                  "options": [[k, v["label"]] for k, v in mailmod.PRESETS.items()]},
                 {"key": "user", "label": "Address / user name", "kind": "text",
                  "placeholder": "you@example.com"},
                 {"key": "password", "label": "App password", "kind": "secret",
                  "placeholder": "an app password, not your login password"},
                 {"key": "host", "label": "IMAP host", "kind": "text", "placeholder": "imap.example.com"},
                 {"key": "port", "label": "IMAP port", "kind": "number", "placeholder": "993"},
                 {"key": "smtp_host", "label": "SMTP host (only for sending)", "kind": "text",
                  "placeholder": "smtp.example.com"},
                 {"key": "smtp_port", "label": "SMTP port", "kind": "number", "placeholder": "587"},
             ]},
    "calendar": {"title": "Calendar",
                 "what": "Lets the agent READ the next days of this calendar — never create, "
                         "move or delete an event. Every read is a `calendar.read` decision "
                         "in the ledger.",
                 "fields": [
                     {"key": "preset", "label": "Provider", "kind": "select",
                      "options": [[k, v["label"]] for k, v in calmod.PRESETS.items()]},
                     {"key": "url", "label": "Address", "kind": "text",
                      "placeholder": "https://…/basic.ics  or a CalDAV URL"},
                     {"key": "user", "label": "User name (CalDAV)", "kind": "text",
                      "placeholder": "you@example.com"},
                     {"key": "password", "label": "App password (CalDAV)", "kind": "secret",
                      "placeholder": "an app password"},
                     {"key": "name", "label": "Call it", "kind": "text", "placeholder": "Work"},
                 ]},
}


def _mask(secret: str) -> str:
    s = str(secret or "")
    return ("•••" + s[-2:]) if len(s) > 6 else ("•••" if s else "")


def door(cfg: dict, aid: str) -> dict:
    """Which way this account is read, in a sentence: 'signed in with Google as
    x (mail, calendar)', 'through the gmail MCP server', 'IMAP at imap.example.com'."""
    raw = dict((cfg or {}).get(aid) or {})
    way = mailmod.via(cfg) if aid == "mail" else calmod.kind(cfg)
    if way in ("google", "microsoft"):
        rec = signin.signed_in(cfg, way)
        label = signin.PROVIDERS[way]["label"]
        if rec.get("problem"):
            return {"way": way, "label": label, "detail": f"signed in with {label} — {rec['problem']}"}
        uses = ", ".join(u for u in rec.get("uses") or [] if u != "send") or "nothing yet"
        send = " · can send" if aid == "mail" and "send" in (rec.get("uses") or []) else ""
        return {"way": way, "label": label,
                "detail": f"signed in with {label} as {rec.get('email') or '?'} ({uses}{send})"}
    if way == "mcp":
        return {"way": "mcp", "label": "MCP server",
                "detail": f"through the '{raw.get('mcp_server')}' MCP server" if raw.get("mcp_server")
                else "through an MCP server — none chosen yet"}
    if aid == "mail":
        return {"way": "imap", "label": "App password",
                "detail": f"IMAP at {raw.get('host')} as {raw.get('user')}" if raw.get("host") else "app password (not set up)"}
    if way == "caldav":
        return {"way": "caldav", "label": "App password", "detail": f"CalDAV at {raw.get('url')}"}
    return {"way": "ics", "label": "ICS address", "detail": f"ICS at {raw.get('url')}" if raw.get("url") else "ICS address (not set up)"}


def state(cfg: dict, mcp_servers: list[str] | None = None) -> list[dict]:
    """Both accounts for a Settings page: values (secrets masked, never echoed),
    whether each is set, the last probe, the door it reads through, and the
    sentence when it cannot be used. `mcp_servers` is what is connected right now
    — the route passes it, this module stays free of the MCP manager."""
    out = []
    for aid in IDS:
        mod = mailmod if aid == "mail" else calmod
        c = {**mod.DEFAULTS, **((cfg or {}).get(aid) or {})}   # raw: the secret stays a reference
        about = ABOUT[aid]
        values, is_set = {}, {}
        for f in about["fields"]:
            v = c.get(f["key"], "")
            if f["kind"] == "secret":
                values[f["key"]] = ""
                is_set[f["key"]] = bool(v)
            else:
                values[f["key"]] = v
        preset = c.get("preset") or ""
        presets = mod.PRESETS
        hint = presets.get(preset, {}).get("hint", "") if preset else ""
        lt = dict(c.get("last_test") or {})
        out.append({"id": aid, "title": about["title"], "what": about["what"],
                    "enabled": bool(c.get("enabled")), "configured": mod.configured(cfg),
                    "problem": mod.problem(cfg), "values": values, "set": is_set,
                    "masked": {"password": "in the vault" if vault.is_ref(c.get("password", ""))
                               else _mask(c.get("password", ""))},
                    "vault": vault.status(),
                    "door": door(cfg, aid), "via": mailmod.via(cfg) if aid == "mail" else calmod.kind(cfg),
                    "mcp_server": c.get("mcp_server", ""), "mcp_servers": list(mcp_servers or []),
                    "can_send": bool(c.get("can_send")) if aid == "mail" else False,
                    "fields": about["fields"], "presets": presets, "hint": hint,
                    "last_test": lt, "kind": c.get("kind", "") if aid == "calendar" else "imap"})
    return out


def save(cfg: dict, aid: str, patch: dict) -> tuple[bool, str]:
    """Apply a form or CLI change. A blank secret means leave it alone — the card
    shows a saved secret as a chip with no input, so '' is its normal state."""
    if aid not in IDS:
        return False, f"no such account: {aid}"
    mod = mailmod if aid == "mail" else calmod
    conf = cfg.setdefault(aid, {})
    for k, v in dict(mod.DEFAULTS).items():
        conf.setdefault(k, v if not isinstance(v, dict) else dict(v))
    patch = dict(patch or {})
    preset = str(patch.get("preset") or "").strip()
    if "preset" in patch:
        if preset and preset not in mod.PRESETS:
            return False, f"'{preset}' is not a known provider"
        conf["preset"] = preset
        p = mod.PRESETS.get(preset) or {}
        # a preset fills the technical fields the person did not type
        if aid == "mail":
            if p.get("host") and not patch.get("host"):
                conf["host"] = p["host"]
                conf["port"] = p["port"]
            if p.get("smtp_host") and not patch.get("smtp_host"):
                conf["smtp_host"] = p["smtp_host"]
                conf["smtp_port"] = p["smtp_port"]
        else:
            if p.get("kind"):
                conf["kind"] = p["kind"]
            if p.get("url") and not patch.get("url") and not conf.get("url"):
                conf["url"] = p["url"]
    for key in ("user", "host", "smtp_host", "url", "name", "from"):
        if key in patch:
            conf[key] = str(patch[key] or "").strip()[:300]
    for key in ("port", "smtp_port"):
        if key in patch and str(patch[key]).strip():
            try:
                conf[key] = int(patch[key])
            except (TypeError, ValueError):
                return False, f"{key} must be a number"
    if "ssl" in patch and aid == "mail":
        # not on the form: a plain server on loopback (a Proton bridge, a test)
        conf["ssl"] = None if patch["ssl"] in (None, "", "auto") else bool(patch["ssl"])
    if "kind" in patch and aid == "calendar":
        k = str(patch["kind"] or "ics")
        if k not in calmod.KINDS:
            return False, f"kind is one of {', '.join(calmod.KINDS)}"
        if k in ("google", "microsoft") and not signin.signed_in(cfg, k):
            return False, f"sign in with {signin.PROVIDERS[k]['label']} first — the button on this card"
        conf["kind"] = k
    if "via" in patch and aid == "mail":
        v = str(patch["via"] or "imap")
        if v not in mailmod.VIAS:
            return False, f"via is one of {', '.join(mailmod.VIAS)}"
        if v in ("google", "microsoft") and not signin.signed_in(cfg, v):
            return False, f"sign in with {signin.PROVIDERS[v]['label']} first — the button on this card"
        conf["via"] = v
    if "mcp_server" in patch:
        conf["mcp_server"] = str(patch["mcp_server"] or "").strip()[:64]
    if patch.get("password"):
        conf["password"] = vault.put(f"{aid}.password", str(patch["password"]))
    if aid == "calendar" and "url" in patch and conf.get("url"):
        u = conf["url"].lower()
        if "kind" not in patch and "preset" not in patch:
            conf["kind"] = "ics" if u.endswith(".ics") or "/ical/" in u or "basic.ics" in u \
                else conf.get("kind") or "ics"
    if aid == "mail" and not conf.get("preset") and conf.get("user"):
        g = mailmod.guess_preset(conf["user"], conf.get("host", ""))
        if g and not conf.get("host"):
            conf["preset"] = g
            conf["host"], conf["port"] = mailmod.PRESETS[g]["host"], mailmod.PRESETS[g]["port"]
            conf["smtp_host"], conf["smtp_port"] = mailmod.PRESETS[g]["smtp_host"], mailmod.PRESETS[g]["smtp_port"]
    if "enabled" in patch:
        if patch["enabled"] and not mod.configured(cfg):
            return False, f"{ABOUT[aid]['title']} cannot be switched on until it is set up"
        conf["enabled"] = bool(patch["enabled"])
    elif mod.configured(cfg) and any(k in patch for k in ("password", "url", "user", "mcp_server")):
        conf["enabled"] = True            # filling the form in IS switching it on
    # anything changed: the last probe no longer describes this configuration
    if any(k in patch for k in ("user", "password", "host", "port", "url", "kind", "preset", "via", "mcp_server")):
        conf["last_test"] = {}
    return True, "saved"


def record_test(cfg: dict, aid: str, result: dict) -> None:
    conf = cfg.setdefault(aid, {})
    conf["last_test"] = {"ok": bool(result.get("ok")), "detail": str(result.get("detail", ""))[:300],
                         "at": float(result.get("at") or time.time())}


def readiness(cfg: dict) -> dict:
    """For the Missions catalogue: per account, can a mission use it, and if not,
    the sentence that would fix it."""
    return {aid: {"ready": not (mailmod if aid == "mail" else calmod).problem(cfg),
                  "detail": (mailmod if aid == "mail" else calmod).problem(cfg)
                  or f"{ABOUT[aid]['title']} is set up"}
            for aid in IDS}
