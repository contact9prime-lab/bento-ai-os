"""A Zero's get and set: the one reader and the one setter its hub drives.

Asked for as "the Pi has two MCPs, get and set, the underlying functionality of the Pi … the hub
is responsible for executing, because Pis are Zeros … the hub can only use sensors where
permission was granted, at the tool level or the agent level … every set is asked". Full plan in
docs/design/devices.md (step 3).

The agents see two tools on the hub, `device_get` and `device_set` (tools.py), offered to a
forwarded brain through the team door, so Claude Code calls them as mcp__bento__device_get. Each
call is a decision of the hub's gate (`device.get` / `device.set` on `device:<machine>/<item>`),
then a request over the link, then a decision of the Pi's own. Five rules:

  * The Pi uses only what it was permitted (`permits()`, kept on the Pi, set from the hub's
    Devices). Something discovered but not permitted can't be read or set, and something
    permitted is only ever read or set by the code below: a closed set of readers (`GET_ID`) and
    one setter, a header pin's level through `pinctrl`. A sensor Bento has no reader for is
    listed in the inventory and can't be used, however it is permitted.
  * Only its own hub is answered (`zero.is_my_hub`), over the link's mutual TLS.
  * Every request carries who asked and why, in the agent's own words, and the Pi keeps its own
    diary line and ledger row for it (server._device_from_hub), so what happened on the Pi can be
    checked on the Pi.
  * A set changes something in the room, so the hub asks a person for every one (agent.py), and a
    set asked from the Pi's own screen goes to the owner's Telegram when it is connected
    (server._linked_approval): the person at the Pi asked, the owner says yes.
  * A set is read back. "Done" means the pin now reads what was asked; anything else is an error
    that says what it reads.

Free of HTTP and asyncio, like hardware.py: the link's ops, the routes, the tools and
`bento network get/set/permit` call into it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import hardware

# What Bento can read, by inventory id. Each has a reader below and was checked on a real Pi.
GET_ID = re.compile(r"(?:[a-z0-9_]+\.temp|power\.(?:throttle|core_volts)|system\.(?:load|memory_free|disk_free|uptime)"
                    r"|net\.[a-z0-9_.-]{1,30}|gpio\.(?:[0-9]|1[0-9]|2[0-7])|w1\.[a-z0-9_.-]{1,40}"
                    r"|esp\.[a-z0-9][a-z0-9-]{0,15}\.(?:sensor|binary_sensor|text_sensor|switch|light|fan)\.[a-z0-9_]{1,24})")
# What Bento can set: a header pin's level, and an ESP32 node's switch, light or fan (espnodes.py)
SET_ID = re.compile(r"gpio\.([0-9]|1[0-9]|2[0-7])|esp\.[a-z0-9][a-z0-9-]{0,15}\.(?:switch|light|fan)\.[a-z0-9_]{1,24}")
VERBS = ("get", "set")
MAX_PERMITS = 120
FILE = "devices.json"


def pinctrl() -> str:
    """The pin tool; a test points AGENTOS_PINCTRL at a stand-in that keeps its pins in a file."""
    return os.environ.get("AGENTOS_PINCTRL") or "pinctrl"


def _pin(*args: str) -> tuple[int, str]:
    tool = pinctrl()
    if not (shutil.which(tool) or Path(tool).is_file()):
        return 127, "pinctrl isn't installed on this machine"
    try:
        r = subprocess.run([tool, *args], capture_output=True, text=True, timeout=5,
                           env={**os.environ, "LC_ALL": "C"})
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


# ---- on the Pi: what it may use ------------------------------------------------------------

def _path() -> Path:
    from . import teamlink
    return teamlink.home() / FILE


def permits() -> dict:
    """What this machine lets its hub read and set: {"get": [...], "set": [...], "by", "at"}."""
    try:
        d = json.loads(_path().read_text())
    except (OSError, ValueError):
        d = {}
    return {"get": [i for i in d.get("get") or [] if isinstance(i, str)],
            "set": [i for i in d.get("set") or [] if isinstance(i, str)],
            "by": str(d.get("by") or ""), "at": float(d.get("at") or 0)}


def clean_permits(get, set_, dropped: list | None = None) -> tuple[list, list]:
    """Field by field: an id Bento has no reader for is dropped and named, a settable id is
    readable too (a set is read back), and the lists are bounded."""
    dropped = dropped if dropped is not None else []
    g, s = [], []
    for i in set_ or []:
        i = str(i).strip().lower()
        if SET_ID.fullmatch(i) and i not in s:
            s.append(i)
        elif i:
            dropped.append(f"{i[:40]} (Bento can't set it)")
    for i in list(get or []) + s:
        i = str(i).strip().lower()
        if GET_ID.fullmatch(i) and i not in g:
            g.append(i)
        elif i and i not in g:
            dropped.append(f"{i[:40]} (Bento has no reader for it)")
    return g[:MAX_PERMITS], s[:MAX_PERMITS]


def save_permits(get, set_, by: str = "") -> dict:
    dropped: list = []
    g, s = clean_permits(get, set_, dropped)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    tmp.write_text(json.dumps({"get": g, "set": s, "by": by[:60], "at": time.time()}, indent=1))
    os.replace(tmp, p)
    return {**permits(), "dropped": dropped}


def refusal(verb: str, item: str) -> str:
    """Why this machine won't do it, or '' when it will."""
    item = str(item or "").strip().lower()
    if verb == "set":
        if not SET_ID.fullmatch(item):
            return (f"Bento can't set '{item}' on this machine: only a header pin's level (gpio.N) or an "
                    f"ESP32 node's switch, light or fan")
    elif not GET_ID.fullmatch(item):
        return f"Bento has no reader for '{item}' yet, so it can't be used, only listed"
    if item not in permits()[verb]:
        return (f"'{item}' isn't permitted to be {'set' if verb == 'set' else 'read'} on this machine. "
                f"Allow it on the hub in Devices, under this machine's hardware")
    return ""


# ---- on the Pi: reading and setting --------------------------------------------------------

def read(item: str) -> dict:
    """One item's value now, with its unit, by the reader Bento has for it."""
    item = str(item or "").strip().lower()
    if item.startswith("esp."):
        from . import espnodes
        return espnodes.read(item)
    if item.startswith("gpio."):
        code, out = _pin("get", item.split(".", 1)[1])
        got = hardware.gpio_items(out)
        if not got:
            return {"ok": False, "error": f"couldn't read {item}: {out.strip()[:160] or 'pinctrl said nothing'}"}
        it = got[0]
    else:
        group = (hardware._temperatures if item.endswith(".temp") else hardware._power if item.startswith("power.")
                 else hardware._system if item.startswith("system.") else hardware._network if item.startswith("net.")
                 else hardware._sensors)
        it = next((x for x in group() if x.get("id") == item), None)
        if not it:
            return {"ok": False, "error": f"{item} isn't on this machine now"}
    out = {"ok": True, "item": item, "name": it.get("name") or item, "at": time.time()}
    for k in ("value", "unit", "detail", "flags"):
        if it.get(k) not in (None, ""):
            out[k] = it[k]
    return out


def level(value) -> int | None:
    """1 or 0 from what a person or a model may say for a pin, else None."""
    v = str(value).strip().lower()
    if v in ("1", "on", "high", "hi", "true", "yes"):
        return 1
    if v in ("0", "off", "low", "lo", "false", "no"):
        return 0
    return None


def write(item: str, value) -> dict:
    """Set a header pin to a level and read it back. A pin lent to a bus (I2C, SPI, a UART) is
    refused: driving it would talk over whatever is on that bus."""
    item = str(item or "").strip().lower()
    if item.startswith("esp."):
        from . import espnodes
        return espnodes.write(item, value)
    m = SET_ID.fullmatch(item)
    want = level(value)
    if not m or want is None:
        return {"ok": False, "error": f"a pin is set to 1 or 0 (on or off), not '{str(value)[:20]}'"}
    n = m.group(1)
    before = read(item)
    if not before.get("ok"):
        return before
    if before.get("detail") not in ("input", "output"):
        return {"ok": False, "error": f"GPIO {n} is in use as {before.get('detail')}, so Bento won't drive it"}
    code, out = _pin("set", n, "op", "dh" if want else "dl")
    if code:
        return {"ok": False, "error": f"pinctrl refused: {out.strip()[:160]}"}
    after = read(item)
    if not after.get("ok") or after.get("value") != want:
        return {"ok": False, "error": f"GPIO {n} reads {after.get('value')} after setting it to {want}"}
    return {**after, "was": before.get("value"), "was_mode": before.get("detail"), "read_back": "the pin"}


def answer(cfg: dict, lk: dict, req: dict) -> dict:
    """On the machine: its hub asks (wire ops device_get, device_set, device_permits). Only its
    own hub, and only what this machine permits."""
    from . import teamlink
    from . import zero as zeromod
    if not zeromod.is_my_hub(cfg, lk):
        return {"ok": False, "error": "only the hub that set this machine up can use its hardware"}
    op = req.get("op")
    if op == "device_permits":
        if isinstance(req.get("permits"), dict):
            p = req["permits"]
            return {"ok": True, **save_permits(p.get("get"), p.get("set"), by=str(lk.get("label") or ""))}
        return {"ok": True, **permits()}
    verb = "set" if op == "device_set" else "get"
    item = teamlink.plain(req.get("item"), 64, newlines=False).strip().lower()
    if (why := refusal(verb, item)):
        return {"ok": False, "error": why, "refused": True}
    return write(item, req.get("value")) if verb == "set" else read(item)


def words(req: dict, got: dict, frm: str) -> str:
    """The diary line both sides write: what, for whom, why, and what came of it."""
    from . import teamlink
    op, item = req.get("op"), teamlink.plain(req.get("item"), 64, newlines=False)
    who = teamlink.plain(req.get("who"), 60, newlines=False) or "the hub"
    why = " ".join(teamlink.plain(req.get("why"), 200, newlines=False).split())
    if op == "device_permits":
        p = got if got.get("ok") else {}
        head = (f"{frm} set what may be used here: read {len(p.get('get') or [])}, set {len(p.get('set') or [])}"
                if isinstance(req.get("permits"), dict) else f"{frm} read what may be used here")
    elif op == "device_set":
        head = f"{frm} set {item} to {req.get('value')} for {who}"
    else:
        head = f"{frm} read {item} for {who}"
    shown = got.get("detail") if str(item).startswith("esp.") and got.get("detail") in ("on", "off") else got.get("value")
    tail = (f": {shown}{(' ' + got['unit']) if got.get('unit') else ''}" if got.get("ok") and "value" in got
            else "" if got.get("ok") else f", refused: {got.get('error')}")
    return head + tail + (f" (\"{why}\")" if why else "")


# ---- on the hub ----------------------------------------------------------------------------

def resource(machine: str, item: str = "") -> str:
    """What the hub's gate decides on: device:<machine>/<item>, both as the Devices list names
    them (lower case, so a grant and a call can't differ by a capital)."""
    m = str(machine or "").strip().lower() or "*"
    return f"device:{m}/{str(item or '').strip().lower() or '*'}"


def sync_grants(store, machine: str, get: list, set_: list) -> dict:
    """Permitting an item in Devices is also the hub's grant for your own agent (the lead, and a
    Zero's chat, which runs as it): device.get for each readable item, device.set for each
    settable one. Specialists, apps and missions get theirs from an approval card or Permissions.
    Only rows this wrote (source device, source_ref device:<machine>) are ever revoked here."""
    ref = f"device:{str(machine).strip().lower()}"
    want = {("device.get", resource(machine, i)) for i in get} | {("device.set", resource(machine, i)) for i in set_}
    have = {(g["action"], g["resource"]): g["id"] for g in store.list_grants("user", "")
            if g.get("source") == "device" and g.get("source_ref") == ref and not g.get("principal_id")}
    added = removed = 0
    for key, gid in have.items():
        if key not in want:
            store.revoke_grant(gid)
            removed += 1
    for action, res in want - set(have):
        store.add_grant("user", "", action, res, source="device", source_ref=ref,
                        note="permitted in Devices")
        added += 1
    return {"added": added, "removed": removed}


def mark(item: str, row: dict) -> str:
    """What may be done with one item from the hub: 'read, set', 'read', 'not permitted'
    (Bento has a reader, nobody allowed it) or 'listed only' (no reader)."""
    p = row.get("device_permits") or {}
    if re.fullmatch(r"esp\.[a-z0-9-]+", item):
        return "an ESP32 node: its things follow"
    if item in (p.get("set") or []):
        return "read, set"
    if item in (p.get("get") or []):
        return "read"
    return "not permitted" if GET_ID.fullmatch(item) else "listed only"


def list_words(name: str, row: dict) -> str:
    """Everything a Zero has, each item marked with what may be done with it from here. The
    agents' device_get and `bento network get MACHINE` both print this."""
    hw = row.get("hardware") or {}
    if not hw.get("items"):
        return f"{name}'s hardware hasn't been read yet. Devices → its row → Hardware → Check now."
    lines = [f"{name} ({(hw.get('board') or {}).get('model') or 'a machine'}), as read "
             f"{time.strftime('%d %b %H:%M', time.localtime(hw.get('at') or 0))}. Item ids are what device_get and "
             f"device_set take. [read] / [read, set] = permitted; [not permitted] = allowed in Devices first; "
             f"[listed only] = Bento has no reader for it."]
    for kind, items in hardware.by_kind(hw["items"]):
        lines.append(f"{hardware.KIND_WORDS.get(kind, kind)}:")
        for it in items:
            val = hardware.value_words(it)
            lines.append(f"  {it['id']}  {it.get('name') or ''}{(' = ' + val) if val else ''}  [{mark(it['id'], row)}]")
    return "\n".join(lines)
