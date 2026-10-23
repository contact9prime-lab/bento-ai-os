"""Wi-Fi on this machine, from its own screen: is it on a network, what is in range, join one.

Asked for from a Raspberry Pi whose kiosk fills the screen: "I am not able to connect to wifi
when it loads". The desktop's network menu sits under the kiosk, and a Pi that boots without
its Wi-Fi has no other way back. Three rules:

  * NetworkManager does the work (`nmcli`, which Raspberry Pi OS and most desktops run). A
    machine without it gets a sentence, never a dead button.
  * A password never goes on a command line, where any process here could read it. The
    connection is added without its secret and brought up with `passwd-file`, a 0600 file
    in a private folder that is removed at once. The secret is stored by NetworkManager
    (psk-flags 0), so the machine joins again on its own at the next boot.
  * What is in range is somebody else's words: names are cleaned (controls and bidi
    stripped) before any screen shows them.

No HTTP or asyncio here, so `bento wifi` works with the server down.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

NMCLI_TIMEOUT = 40
MAX_NETWORKS = 30


def available() -> str:
    """'' when Wi-Fi can be managed here, else the sentence saying why not."""
    if not shutil.which("nmcli"):
        return "NetworkManager (nmcli) isn't on this machine, so Wi-Fi can't be set from here"
    return ""


def _nm(args: list[str], timeout: float = NMCLI_TIMEOUT) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "NetworkManager took too long to answer"
    except OSError as e:
        return 127, "", str(e)


def _split(line: str) -> list[str]:
    """nmcli -t escapes ':' inside a field as '\\:'."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _plain(s: str) -> str:
    from . import teamlink
    return teamlink.plain(str(s or ""), 64, newlines=False).strip()


def status() -> dict:
    """On a network or not, and which. Never raises."""
    why = available()
    if why:
        return {"ok": False, "why": why, "online": False, "wifi": None, "devices": []}
    code, out, err = _nm(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], 10)
    devices = []
    for ln in out.splitlines():
        f = _split(ln)
        if len(f) >= 4 and f[1] in ("wifi", "ethernet"):
            devices.append({"device": f[0], "type": f[1], "state": f[2], "connection": _plain(f[3])})
    _, conn, _ = _nm(["networking", "connectivity"], 10)
    level = conn.strip() or "unknown"
    wifi = next((d for d in devices if d["type"] == "wifi"), None)
    wired = any(d["type"] == "ethernet" and d["state"] == "connected" for d in devices)
    signal = None
    if wifi and wifi["state"] == "connected":
        signal = next((n["signal"] for n in networks(rescan=False) if n["in_use"]), None)
    # NetworkManager's internet check is often off (Raspberry Pi OS ships it so), which answers
    # "unknown" while online: then a connected device is the best answer there is
    up = any(d["state"] == "connected" for d in devices)
    online = level == "full" or (level == "unknown" and up)
    return {"ok": code == 0, "why": "" if code == 0 else (err.strip().splitlines() or [""])[-1],
            "online": online, "connectivity": level, "wired": wired,
            "wifi": ({**wifi, "signal": signal} if wifi else None), "devices": devices}


def networks(rescan: bool = True) -> list[dict]:
    """What is in range, strongest first, one row per name."""
    if available():
        return []
    code, out, _ = _nm(["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                        "--rescan", "yes" if rescan else "no"], 30)
    best: dict[str, dict] = {}
    for ln in out.splitlines():
        f = _split(ln)
        if len(f) < 4 or not f[1].strip():
            continue                               # a hidden network has no name to show
        name = _plain(f[1])
        try:
            sig = int(f[2] or 0)
        except ValueError:
            sig = 0
        row = {"ssid": name, "signal": sig, "secure": bool(f[3].strip() and f[3].strip() != "--"),
               "in_use": f[0].strip() == "*"}
        old = best.get(name)
        if not old or row["in_use"] or (sig > old["signal"] and not old["in_use"]):
            best[name] = row
    return sorted(best.values(), key=lambda r: (not r["in_use"], -r["signal"]))[:MAX_NETWORKS]


def _known(ssid: str) -> str:
    """The name of a saved connection for this network, if there is one."""
    _, out, _ = _nm(["-t", "-f", "NAME,TYPE", "connection", "show"], 10)
    for ln in out.splitlines():
        f = _split(ln)
        if len(f) >= 2 and f[1] in ("802-11-wireless", "wifi"):
            _, s, _ = _nm(["-t", "-g", "802-11-wireless.ssid", "connection", "show", f[0]], 10)
            if s.strip() == ssid:
                return f[0]
    return ""


def connect(ssid: str, password: str = "") -> dict:
    """Join a network and keep it for the next boot. Raises ValueError with a sentence."""
    why = available()
    if why:
        raise ValueError(why)
    ssid = str(ssid or "").strip()
    if not ssid or len(ssid) > 32 or any(ord(c) < 32 for c in ssid):
        raise ValueError("choose a network from the list")
    if password and not (8 <= len(password) <= 63):
        raise ValueError("a Wi-Fi password is 8 to 63 characters")
    name = _known(ssid)
    if not name:
        name = "bento-" + "".join(c if c.isalnum() or c in "-_" else "-" for c in ssid)[:40]
        args = ["connection", "add", "type", "wifi", "con-name", name, "ssid", ssid,
                "connection.autoconnect", "yes"]
        if password:
            args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk-flags", "0"]
        code, _, err = _nm(args)
        if code != 0:
            raise ValueError(_refusal(err) or "NetworkManager would not add that network")
    if not password:
        code, _, err = _nm(["--wait", "30", "connection", "up", name])
    else:
        d = tempfile.mkdtemp(prefix="bento-wifi-")
        os.chmod(d, 0o700)
        f = os.path.join(d, "secret")
        try:
            fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(f"802-11-wireless-security.psk:{password}\n")
            # the secret goes to NetworkManager as an agent's answer; with psk-flags 0 it keeps it
            code, _, err = _nm(["--wait", "30", "connection", "up", name, "passwd-file", f])
        finally:
            shutil.rmtree(d, ignore_errors=True)
    if code != 0:
        raise ValueError(_refusal(err) or f"could not join {ssid}")
    return {"ok": True, "ssid": ssid, "connection": name, "status": status()}


def _refusal(err: str) -> str:
    e = (err or "").strip()
    low = e.lower()
    if "secrets were required" in low or "802-1x" in low or "wrong" in low and "password" in low:
        return "the password was not accepted"
    if "not authorized" in low or "insufficient privileges" in low or "permission" in low:
        return ("this machine's NetworkManager won't let Bento change Wi-Fi. Join it once from a "
                "terminal there: nmcli device wifi connect '<name>' --ask")
    if "no network with ssid" in low:
        return "that network is out of range now"
    return (e.splitlines() or [""])[-1].replace("Error: ", "")[:200]
