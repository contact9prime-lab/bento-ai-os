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
pgrep -f '[a]gentos serve' >/dev/null 2>&1 && echo serving=yes
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
            # a server started by hand, or left running from deleted code, is running too
            "running": (installed and f.get("running", "").strip() == "active") or f.get("serving") == "yes",
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


# `bento screen on` needs root there once (the microphone policy, or the screen's unit), and a
# Pi's sudo wants a password nobody is at a terminal to type: it stopped with "it asks for your
# password" (found on the owner's Pi). The password the person typed here arrives on stdin, never
# argv, and a `sudo` in a private folder ahead of PATH hands it to the real one for this one
# command (`-n` dropped, so Bento's "passwordless?" probe says yes). Gone when the shell ends.
# No password (a key login) leaves sudo as it is.
WITH_SUDO = r"""IFS= read -r P || P=
if [ -n "$P" ] && R=$(command -v sudo); then
D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
cat > "$D/sudo" <<EOS
#!/bin/sh
for a; do shift; [ "\$a" = -n ] || set -- "\$@" "\$a"; done
printf '%s\n' "\$P" | $R -S -p '' "\$@"
EOS
chmod 700 "$D/sudo"; export P PATH="$D:$PATH"
fi
"""


def needs_root(switch: str, on: bool) -> bool:
    return on and switch in ("running", "screen")


def command(switch: str, on: bool, port: int = 8321) -> str:
    """The one line run there for a switch. Raises ValueError for one that is not run there."""
    if switch == "running":
        if on:      # back on, and back on its screen if that is what it was set to
            return (WITH_SUDO + f"{B} service start && {{ {SCREEN_ON} && {B} screen on --yes >/dev/null 2>&1; true; }}")
        return f"{B} service stop; {CLOSE}; true"
    if switch == "screen":
        return WITH_SUDO + f"{B} screen on --yes" if on else f"{B} screen off; {CLOSE}; true"
    if switch == "listening":
        return _face(on, port)
    raise ValueError(f"{switch} is not switched on that machine")


# Remove takes away everything Bento put there, checks, and names what is left. Reported as
# "when I remove it should remove and when I add it should add". The old one ran `bento
# uninstall` and deleted the code: a server started by hand (the installer does that when the
# service will not start) kept running, an autostart moved aside by `screen on`
# (agentos-app.desktop.bento-screen) still opened Bento at login, the installer's own screen
# stayed up, and ~/.agentos still said "set up by the hub", so a reinstall never waited to be
# set up again: the hub had forgotten it, the Pi had not. Its home is now MOVED aside, never
# deleted: a fresh install is a new machine to the hub, and nothing it knew is lost.
# Root (the screen's system unit, the mic policy) gets the typed password as Turn on does.
REMOVE = (WITH_SUDO + f"B={B}; S={SRC}; U=\"$HOME/.config/systemd/user\"; A=\"$HOME/.config/autostart\"\n"
          '[ -x "$B" ] && { "$B" screen off >/dev/null 2>&1; "$B" uninstall >/dev/null 2>&1; }\n'
          'systemctl --user disable --now agentos.service >/dev/null 2>&1\n'
          # $P is the password (WITH_SUDO): the installer's process is $I
          'I=$(cat "$HOME/.cache/bento-install/install.pid" 2>/dev/null); '
          '[ -n "$I" ] && kill -TERM -- "-$I" 2>/dev/null\n'
          f"{CLOSE}; pkill -f '[b]ento-install/browser' 2>/dev/null; "
          "pkill -f '[a]gentos serve' 2>/dev/null; sleep 1\n"
          'rm -rf "$U/agentos.service" "$U/agentos.service.d" "$U/default.target.wants/agentos.service" '
          '"$A/agentos-app.desktop" "$A/agentos-app.desktop.bento-screen" "$A/bento-screen.desktop" '
          '"$HOME/.local/share/applications/agentos.desktop" '
          '"$HOME/.local/share/icons/hicolor/scalable/apps/agentos.svg" '
          '"$HOME/.local/bin/agentos" "$HOME/.cache/bento-install" "$S" "$B"\n'
          'systemctl --user daemon-reload >/dev/null 2>&1\n'
          'if [ -d "$HOME/.agentos" ]; then K="$HOME/.agentos-removed-$(date +%Y%m%d-%H%M%S)"; '
          'mv "$HOME/.agentos" "$K" && echo "kept=$K"; fi\n'
          # what is still there, named: a remove that says "removed" over a running server is the bug
          'pgrep -f \'[a]gentos serve\' >/dev/null 2>&1 && echo "left=a Bento server is still running"\n'
          'for f in "$S" "$B" "$U/agentos.service" "$A/agentos-app.desktop.bento-screen" "$A/bento-screen.desktop"; do '
          '[ -e "$f" ] && echo "left=$f"; done\n'
          'systemctl is-enabled -q bento-screen.service 2>/dev/null && echo "left=the screen service (needs your password)"\n'
          'echo removed')


# `bento update` alone only checks (installing is --apply), so without it this said "✓ 0.6.85 →
# 0.6.85" over a list of the changes it had not installed (found updating a Pi from the hub).
# --no-tests: the code was tested where it was built; four thousand tests on a Pi 3 hold its
# screen down for the better part of an hour, and the update still rolls back on a failed migrate.
UPDATE = f"{B} update --apply --no-tests"


async def update(host: str, user: str, password: str = "", port: int = 22) -> dict:
    """`bento update` there (it restarts itself when something moved), then read it again."""
    _guard(host, user)
    code, out, err, via = await ri.login_run(host, user, port, password, UPDATE, 900)
    after = await state(host, user, "" if via == "key" else password, port)
    tail = [ri.clean_line(x) for x in (out + "\n" + err).strip().splitlines() if x.strip()][-6:]
    # changes still listed as waiting were not installed, whatever the exit code says
    waiting = "install it: bento update --apply" in out or "changes waiting" in out and "--apply" in out
    return {"ok": code == 0 and not waiting, "ran": UPDATE, "said": tail, "state": after,
            **({"error": "the update was checked there but not installed"} if waiting else {})}


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
    code, out, err, via = await ri.login_run(host, user, port, password, cmd, 120,
                                             stdin=(password + "\n") if needs_root(which, on) else None)
    after = await state(host, user, "" if via == "key" else password, port)
    said = ri.clean_line((err or out or "").strip().splitlines()[-1]) if (err or out).strip() else ""
    return {"ok": code == 0, "ran": cmd, "said": said, "state": after}


def end_ties(row: dict) -> list[str]:
    """This computer's half of a removed machine: its links (and the cells that named them),
    its place in the community, and what was heard and set up at its address. One function
    for the Remove button and `bento network remove`, so the terminal ends them too: it used
    to leave them to "the running server", and nothing ever asked that server to."""
    from . import fabric, pool, provision, teamlink
    from . import users as usersmod
    ended = []
    for c in row.get("connections") or []:
        try:
            if c["kind"] == "link":
                owner = c.get("owner") or ""
                if teamlink.remove(owner, c["label"]):
                    st = usersmod.store_for(owner)
                    n = fabric.forget_link_grants(st, c["label"])
                    with usersmod.as_user(owner):
                        fabric.audit_team(st, "link.revoke", f"link:{c['label']}",
                                          f"Bento was removed there; {n} permission(s) that named it revoked")
                    ended.append(c["words"])
            elif c["kind"] == "community" and row.get("fp"):
                with usersmod.as_user(""):
                    pool.remove(usersmod.store_for(""), row["fp"])
                ended.append(c["words"])
        except Exception:
            continue
    with usersmod.as_user(""):
        if row.get("ip") and provision.forget_at(row["ip"]):
            ended.append("what this computer heard and set up there")
    return ended


async def remove(host: str, user: str, password: str = "", port: int = 22) -> dict:
    _guard(host, user)
    code, out, err, via = await ri.login_run(host, user, port, password, REMOVE, 120,
                                             stdin=(password + "\n") if password else None)
    if "removed" not in out:
        raise ri.InstallError("it could not be removed there: "
                              + (ri.clean_line((err or out).strip().splitlines()[-1]) if (err or out).strip() else
                                 f"exit {code}"))
    f = [ln.split("=", 1) for ln in out.splitlines() if "=" in ln]
    left = [ri.clean_line(v) for k, v in f if k == "left"]
    kept = next((ri.clean_line(v) for k, v in f if k == "kept"), "")
    after = await state(host, user, "" if via == "key" else password, port)
    return {"ok": not after["installed"] and not after["running"] and not left, "ran": REMOVE,
            "left": left, "kept": kept, "state": after}


def _guard(host: str, user: str) -> None:
    if ri.missing():
        raise ri.InstallError(ri.missing())
    bad = ri.valid_target(host, user)
    if bad:
        raise ri.InstallError(bad)
