"""This machine's own firewall, as it affects machines set up from here.

Found on the owner's hub: ufw was on, and it dropped everything a Raspberry Pi sent it except
SSH and Bento's page. The Pi's announcement (UDP 8620) never arrived, and once set up the Pi
could not reach the link (TCP 8322) to join, hand over work or send code too big for it.

Without root, ufw's own config file says whether it is on, and firewalld answers systemctl.
Neither lets us read the rules, so we can't tell whether the ports are already open: the tab
says the firewall is on and which ports machines set up from here need, and offers to open
them. Opening goes through the privilege ladder (session._run_root); with no way to get root,
the answer is the exact commands. Opening is recorded so the line goes away.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

UFW_CONF = Path("/etc/ufw/ufw.conf")


def kind() -> str:
    """'ufw', 'firewalld', or '' when neither is on."""
    try:
        if shutil.which("ufw") and "ENABLED=yes" in UFW_CONF.read_text():
            return "ufw"
    except OSError:
        pass
    if shutil.which("firewall-cmd") and shutil.which("systemctl"):
        r = subprocess.run(["systemctl", "is-active", "--quiet", "firewalld"], capture_output=True)
        if r.returncode == 0:
            return "firewalld"
    return ""


def ports(cfg: dict) -> list[dict]:
    from . import provision, teamlink
    return [{"port": teamlink.team_port(cfg), "proto": "tcp",
             "for": "machines set up from here join and hand over work"},
            {"port": provision.udp_port(), "proto": "udp",
             "for": "a machine waiting to be set up is heard"}]


def commands(k: str, cfg: dict) -> list[list[str]]:
    ps = ports(cfg)
    if k == "ufw":
        return [["ufw", "allow", f"{p['port']}/{p['proto']}"] for p in ps]
    if k == "firewalld":
        return [["firewall-cmd", "--permanent", f"--add-port={p['port']}/{p['proto']}"] for p in ps] + \
               [["firewall-cmd", "--reload"]]
    return []


def _key(cfg: dict) -> str:
    return ",".join(f"{p['port']}/{p['proto']}" for p in ports(cfg))


def state(cfg: dict) -> dict:
    k = kind()
    opened = ((cfg or {}).get("network") or {}).get("firewall_opened") == _key(cfg)
    ps = ports(cfg)
    words = ""
    if k and not opened:
        words = (f"This computer's firewall ({k}) is on. Machines set up from here need "
                 + " and ".join(f"port {p['port']} ({p['proto'].upper()})" for p in ps) + " open.")
    return {"kind": k, "ports": ps, "opened": opened, "words": words,
            "commands": ["sudo " + " ".join(c) for c in commands(k, cfg)]}


def open_ports(cfg: dict) -> dict:
    """Open them, through the privilege ladder. {ok, error, needs}. Records success in cfg."""
    from . import session
    k = kind()
    if not k:
        return {"ok": True, "error": "", "needs": []}
    cmds = commands(k, cfg)
    for i, argv in enumerate(cmds):
        ok, out = session._run_root(argv, "Bento needs root to open ports in this computer's firewall.")
        if not ok:
            return {"ok": False, "error": (out or "root is needed").splitlines()[0][:200],
                    "needs": ["sudo " + " ".join(c) for c in cmds[i:]]}
    cfg.setdefault("network", {})["firewall_opened"] = _key(cfg)
    return {"ok": True, "error": "", "needs": []}


def mark_opened(cfg: dict, on: bool = True) -> None:
    """The person opened them by hand (or wants the line back)."""
    net = cfg.setdefault("network", {})
    if on:
        net["firewall_opened"] = _key(cfg)
    else:
        net.pop("firewall_opened", None)
