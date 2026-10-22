"""Switches for a machine running Bento, from the hub: Bento running, open on its screen,
listening (the kiosk), and Remove Bento. Asked for as "an option of removing it, I would like
to test on and off on a few things, and that should be in the inventory".

Over SSH, like harden.py and remoteinstall.py, and for the same reason: "Bento running: on"
must work on a machine whose Bento is stopped, and only a login reaches that. Three rules:

  * The state is READ, never remembered as true: `STATE_SCRIPT` is plain shell, so it reads any
    Bento version, an old one included. What it read is kept in the inventory with the time.
  * What runs is what was shown: `command()` is the line the tab shows and the one sent.
  * Remove takes the program off and keeps `~/.agentos` (memory, settings, keys), so putting
    Bento back picks up where it was. The hub then forgets its ties to it (`server`).

"Big code to the hub" is the hub's own grant (edgecode.py) and needs no login.
"""
from __future__ import annotations

import shlex

from . import remoteinstall as ri

B = '"$HOME/.local/bin/bento"'
SRC = '"$HOME/.local/src/agentic-os"'

# id, title, what it is for. Order is the order on screen.
SWITCHES = [
    {"id": "running", "title": "Bento running", "remote": True,
     "why": "Its background service. Off stops Bento there until it's switched on again."},
    {"id": "screen", "title": "Open on its screen", "remote": True,
     "why": "Bento full screen on the machine's display, now and at every start."},
    {"id": "listening", "title": "Listening", "remote": True,
     "why": "The kiosk face: the Office on its screen with the microphone on."},
    {"id": "code", "title": "Big code to the hub", "remote": False,
     "why": "Python too big for it runs here, in a sandbox. A permission on this computer."},
]
IDS = [s["id"] for s in SWITCHES]

STATE_SCRIPT = f"""B={B}; S={SRC}
echo "installed=$([ -x "$B" ] && [ -d "$S" ] && echo yes || echo no)"
echo "version=$(cat "$S/agentos/VERSION" 2>/dev/null)"
echo "running=$(systemctl --user is-active agentos 2>/dev/null | head -1)"
if [ -f "$HOME/.config/autostart/bento-screen.desktop" ] || systemctl is-enabled -q bento-screen.service 2>/dev/null; then echo screen=on; else echo screen=off; fi
if pgrep -f '[s]creen-profile' >/dev/null 2>&1; then echo showing=yes; else echo showing=no; fi
echo "listening=$(python3 -c 'import json,os
c=json.load(open(os.path.expanduser("~/.agentos/config.json")))
print("on" if (c.get("face") or {{}}).get("kiosk") else "off")' 2>/dev/null || echo off)"
python3 - <<'PYLOOK' 2>/dev/null || true
import json, os, sqlite3
h = os.path.expanduser("~/.agentos")
try:
    c = json.load(open(os.path.join(h, "config.json")))
except Exception:
    c = {{}}
print("agent=" + str(c.get("agent_name") or "").replace("\\n", " ")[:40])
try:
    db = sqlite3.connect("file:" + os.path.join(h, "agentos.db") + "?mode=ro", uri=True)
    row = db.execute("select recipe from avatars where key='@agent'").fetchone()
    print("look=" + (row[0] if row else "{{}}").replace("\\n", " "))
except Exception:
    print("look={{}}")
PYLOOK
echo "port=$(python3 -c 'import json,os
print(json.load(open(os.path.expanduser("~/.agentos/config.json"))).get("port") or 8321)' 2>/dev/null || echo 8321)"
"""


def parse_state(out: str) -> dict:
    f = dict(ln.split("=", 1) for ln in (out or "").splitlines() if "=" in ln)
    installed = f.get("installed") == "yes"
    return {"installed": installed, "version": f.get("version", "").strip(),
            "running": installed and f.get("running", "").strip() == "active",
            "screen": installed and f.get("screen") == "on",
            "listening": installed and f.get("listening") == "on",
            "showing": f.get("showing") == "yes",
            "port": int(f.get("port") or 8321) if str(f.get("port") or "").isdigit() else 8321,
            "agent": f.get("agent", "").strip(), "look": _look(f.get("look"))}


def _look(raw) -> dict:
    """Its lead agent's recipe, held to the closed set here before anything paints it."""
    import json
    from . import avatars
    try:
        rec = json.loads(raw or "{}")
    except ValueError:
        return {}
    return avatars.clean(rec) if isinstance(rec, dict) and rec else {}


LOOK_FIELDS = ("skin", "hair", "style", "pants", "outfit", "shirt", "glasses", "blush")


def look_patch(changes: dict) -> dict:
    """The changes as names in the closed set (avatars.validate refuses anything else, in a
    sentence). Names, not numbers, so the Pi's own validate reads them whatever its version."""
    from . import avatars
    out = {k: changes[k] for k in LOOK_FIELDS if k in (changes or {})}
    for k in ("glasses", "blush"):
        if k in out:
            out[k] = bool(out[k]) and str(out[k]).lower() not in ("0", "false", "no", "off")
    if not out:
        raise ValueError("choose what to change")
    avatars.validate(out)                  # raises ValueError naming the choices
    return out


def look_command(changes: dict, port: int = 8321) -> str:
    """Through the running server (its screen repaints at once), else the CLI."""
    import json
    patch = look_patch(changes)
    body = shlex.quote(json.dumps(patch))
    cli = " ".join(shlex.quote(f"{k}={'yes' if v is True else 'no' if v is False else v}") for k, v in patch.items())
    return (f"curl -fsS -X PUT -H 'Content-Type: application/json' -d {body} "
            f"http://127.0.0.1:{int(port)}/api/avatars/@agent >/dev/null 2>&1 || {B} avatar set agent {cli}")


def describe_command(words: str, port: int = 8321) -> str:
    import json
    from . import teamlink
    w = teamlink.plain(str(words or ""), 200, newlines=False).strip()
    if not w:
        raise ValueError("say what it should look like")
    body = shlex.quote(json.dumps({"description": w}))
    return (f"curl -fsS -X POST -H 'Content-Type: application/json' -d {body} "
            f"http://127.0.0.1:{int(port)}/api/avatars/@agent/design >/dev/null 2>&1 || "
            f"{B} avatar design agent {shlex.quote(w)}")


async def look(host: str, user: str, password: str, port: int, changes: dict | None = None,
               words: str = "", bento_port: int = 8321) -> dict:
    """Change its lead agent's look there, then read it back."""
    _guard(host, user)
    cmd = describe_command(words, bento_port) if words else look_command(changes or {}, bento_port)
    code, out, err, via = await ri.login_run(host, user, port, password, cmd, 120)
    after = await state(host, user, "" if via == "key" else password, port)
    said = ri.clean_line((err or out).strip().splitlines()[-1]) if (err or out).strip() else ""
    return {"ok": code == 0, "ran": cmd, "said": said, "state": after}


def _face(on: bool, port: int) -> str:
    # through the running server when there is one (it repaints the screen at once), else the file
    body = shlex.quote('{"kiosk": %s}' % ("true" if on else "false"))
    return (f"curl -fsS -X PUT -H 'Content-Type: application/json' -d {body} "
            f"http://127.0.0.1:{int(port)}/api/face >/dev/null 2>&1 || {B} face kiosk {'on' if on else 'off'}")


# Close the screen's window now, whatever version is there: an old Bento's `screen off` only
# removed the entry for the next start, and a stopped Bento left the Office frozen on the screen
# (found on the owner's Pi). The bracket keeps the pattern from matching this very shell.
CLOSE = "pkill -f '[s]creen-profile' 2>/dev/null"
SCREEN_ON = ('{ [ -f "$HOME/.config/autostart/bento-screen.desktop" ] || '
             'systemctl is-enabled -q bento-screen.service 2>/dev/null; }')


def command(switch: str, on: bool, port: int = 8321) -> str:
    """The one line run there for a switch. Raises ValueError for one that is not run there."""
    if switch == "running":
        if on:      # back on, and back on its screen if that is what it was set to
            return f"{B} service start && {{ {SCREEN_ON} && {B} screen on --yes >/dev/null 2>&1; true; }}"
        return f"{B} service stop; {CLOSE}; true"
    if switch == "screen":
        return f"{B} screen on --yes" if on else f"{B} screen off; {CLOSE}; true"
    if switch == "listening":
        return _face(on, port)
    raise ValueError(f"{switch} is not switched on that machine")


REMOVE = (f"B={B}; S={SRC}; "
          '"$B" screen off >/dev/null 2>&1; "$B" uninstall; '
          f"{CLOSE}; "
          'rm -rf "$S" "$B"; echo removed')


UPDATE = f"{B} update"


async def update(host: str, user: str, password: str = "", port: int = 22) -> dict:
    """`bento update` there (it restarts itself when something moved), then read it again."""
    _guard(host, user)
    code, out, err, via = await ri.login_run(host, user, port, password, UPDATE, 900)
    after = await state(host, user, "" if via == "key" else password, port)
    tail = [ri.clean_line(x) for x in (out + "\n" + err).strip().splitlines() if x.strip()][-6:]
    return {"ok": code == 0, "ran": UPDATE, "said": tail, "state": after}


def remove_plan() -> str:
    return REMOVE


async def state(host: str, user: str, password: str = "", port: int = 22) -> dict:
    """What is on there now. Changes nothing."""
    _guard(host, user)
    code, out, err, via = await ri.login_run(host, user, port, password, STATE_SCRIPT, ri.CHECK_TIMEOUT)
    if code != 0:
        raise ri.InstallError(ri._why(err, code, bool(password)))
    return {**parse_state(out), "login": via}


async def switch(host: str, user: str, password: str, port: int, which: str, on: bool, bento_port: int = 8321) -> dict:
    """Run one switch there, then read the state again: the answer is what is TRUE after."""
    _guard(host, user)
    cmd = command(which, on, bento_port)
    code, out, err, via = await ri.login_run(host, user, port, password, cmd, 120)
    after = await state(host, user, "" if via == "key" else password, port)
    said = ri.clean_line((err or out or "").strip().splitlines()[-1]) if (err or out).strip() else ""
    return {"ok": code == 0, "ran": cmd, "said": said, "state": after}


async def remove(host: str, user: str, password: str = "", port: int = 22) -> dict:
    _guard(host, user)
    code, out, err, via = await ri.login_run(host, user, port, password, REMOVE, 120)
    if code != 0 or "removed" not in out:
        raise ri.InstallError("it could not be removed there: "
                              + (ri.clean_line((err or out).strip().splitlines()[-1]) if (err or out).strip() else
                                 f"exit {code}"))
    after = await state(host, user, "" if via == "key" else password, port)
    return {"ok": not after["installed"], "ran": REMOVE, "state": after}


def _guard(host: str, user: str) -> None:
    if ri.missing():
        raise ri.InstallError(ri.missing())
    bad = ri.valid_target(host, user)
    if bad:
        raise ri.InstallError(bad)
