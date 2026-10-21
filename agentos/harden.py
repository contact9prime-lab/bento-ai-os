"""Secure a machine on this network: key-only SSH, a firewall, security updates by themselves.

Asked for as "the discovery of the devices should be another tab … it should install and also
make sure it maintains the inventory and secures the box too". A Pi comes out of Imager with
password logins on, no firewall and updates left to whoever remembers. This is the same road
as remoteinstall.py (the system's `ssh`, Bento's own known_hosts, the password only in that one
child's environment or on its stdin for sudo), and keeps its rules, plus three of its own:

  * WHAT RUNS IS WHAT WAS SHOWN. `plan()` is what the consent screen shows and `secure()`
    sends, step by step. Each step is a closed set below; nothing is composed from what the
    other machine says.
  * PASSWORDS GO OFF ONLY AFTER THE KEY HAS WORKED ON ITS OWN. `secure()` logs in again with
    the key alone (BatchMode) before the password step, and stops if that fails. Turning
    passwords off first is how somebody locks themselves out of a box with no screen.
  * THE FIREWALL KEEPS THE DOORS YOU AND BENTO USE. SSH and Bento's ports are allowed from
    private networks and Tailscale; anything else coming in is refused. A machine reached over
    SSH from the open internet would lose that, and the plan's own words say so.

`check()` reads which steps are in place and changes nothing. Its answer is what the inventory
records, so "secured" is always measured on the machine, never a note that a run once ended.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
from pathlib import Path

from . import remoteinstall as ri

SUDO_TIMEOUT = 20 * 60          # apt on a Pi Zero takes a while
RELOAD_TRIES, RELOAD_WAIT_S = 12, 1.5   # sshd re-executes on reload; a Pi Zero takes a few seconds
PRIVATE = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
# Bento's page, its link listener, setup's door (TCP claim, UDP beacon) and mDNS
BENTO_PORTS = (("8321", "tcp"), ("8322", "tcp"), ("8620", "tcp"), ("8620", "udp"), ("5353", "udp"))
DROPIN = "/etc/ssh/sshd_config.d/10-bento.conf"
AUTO = "/etc/apt/apt.conf.d/20auto-upgrades"

STEPS = (
    {"id": "key", "title": "Log in with this machine's key",
     "why": "Bento can reach it with no password, which lets passwords be turned off.",
     "check": "grep -qxF {pk} ~/.ssh/authorized_keys 2>/dev/null && echo ok || echo no"},
    {"id": "passwords", "title": "Turn off password logins",
     "why": "A guessed or default password no longer gets anybody in, and root can't log in over SSH. "
            "Your own password login stops too, so let your own key in first.",
     "check": ("if grep -qi '^PasswordAuthentication no' " + DROPIN + " 2>/dev/null"
               " && grep -qiE '^Include /etc/ssh/sshd_config.d' /etc/ssh/sshd_config 2>/dev/null;"
               " then echo ok; else echo no; fi")},
    {"id": "firewall", "title": "Turn on a firewall",
     "why": "Only SSH and Bento answer, and only from your network and Tailscale. "
            "If you reach this machine over SSH from the internet, that stops working.",
     "check": ("if grep -q 'table inet bento' /etc/bento-firewall.nft 2>/dev/null"
               " && grep -qF 'bento-firewall.nft' /etc/nftables.conf 2>/dev/null"
               " && {{ ! sudo -n true 2>/dev/null || sudo -n nft list table inet bento >/dev/null 2>&1; }};"
               " then echo ok; else echo no; fi")},
    {"id": "updates", "title": "Install security updates by itself",
     "why": "Security fixes are installed every day without anybody remembering to.",
     "check": ("if dpkg-query -W -f='${{Status}}' unattended-upgrades 2>/dev/null | grep -q 'ok installed'"
               " && grep -q 'Unattended-Upgrade \"1\"' " + AUTO + " 2>/dev/null; then echo ok; else echo no; fi")},
)
IDS = tuple(s["id"] for s in STEPS)
TITLES = {s["id"]: s["title"] for s in STEPS}

PASSWORDS_ROOT = (
    "mkdir -p /etc/ssh/sshd_config.d; "
    "grep -qiE '^Include /etc/ssh/sshd_config.d' /etc/ssh/sshd_config || "
    "sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config; "
    "printf 'PasswordAuthentication no\\nKbdInteractiveAuthentication no\\nPermitRootLogin no\\n' > " + DROPIN + "; "
    "if ! sshd -t; then rm -f " + DROPIN + "; echo 'sshd refused the change, so nothing was kept' >&2; exit 3; fi; "
    "systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || "
    "service ssh reload 2>/dev/null || pkill -HUP -x sshd")
UPDATES_ROOT = (
    "export DEBIAN_FRONTEND=noninteractive; "
    "dpkg-query -W -f='${Status}' unattended-upgrades 2>/dev/null | grep -q 'ok installed' || "
    "{ apt-get update -q && apt-get install -y -q unattended-upgrades; }; "
    "printf 'APT::Periodic::Update-Package-Lists \"1\";\\nAPT::Periodic::Unattended-Upgrade \"1\";\\n' > " + AUTO)


NFT_FILE = "/etc/bento-firewall.nft"
OK_MARK = "/run/bento-firewall-ok"
UNDO_S = 90          # the firewall removes itself unless a NEW login proves Bento still gets in


def nft_rules(ssh_port: int) -> str:
    """The table, written once and loaded by nftables at boot. Its own table, so a person's
    rules (or Docker's) are left alone; created, emptied and redefined, so loading it twice
    is the same as once."""
    v4 = ", ".join(PRIVATE + ("169.254.0.0/16",))
    v6 = "fe80::/10, fc00::/7, fd7a:115c:a1e0::/48"
    tcp = ", ".join(sorted({str(int(ssh_port))} | {p for p, pr in BENTO_PORTS if pr == "tcp"}, key=int))
    udp = ", ".join(sorted({p for p, pr in BENTO_PORTS if pr == "udp"}, key=int))
    return ("table inet bento\n"
            "delete table inet bento\n"
            "table inet bento {\n"
            "  chain input {\n"
            "    type filter hook input priority 0; policy drop;\n"
            "    ct state established,related accept\n"
            "    ct state invalid drop\n"
            "    iif lo accept\n"
            "    meta l4proto { icmp, ipv6-icmp } accept\n"
            "    udp dport { 68, 546 } accept\n"
            "    iifname \"tailscale0\" accept\n"
            f"    ip saddr {{ {v4} }} tcp dport {{ {tcp} }} accept\n"
            f"    ip saddr {{ {v4} }} udp dport {{ {udp} }} accept\n"
            f"    ip6 saddr {{ {v6} }} tcp dport {{ {tcp} }} accept\n"
            f"    ip6 saddr {{ {v6} }} udp dport {{ {udp} }} accept\n"
            "  }\n"
            "}\n")


def _firewall(ssh_port: int) -> str:
    """nftables, which Debian and Raspberry Pi OS install by default (installed here if not).
    Refused when the login itself comes from an address the firewall would drop; otherwise
    loaded with an undo timer that `secure()` stops from a fresh login."""
    return ("export DEBIAN_FRONTEND=noninteractive; "
            "command -v nft >/dev/null || { apt-get update -q && apt-get install -y -q nftables; }; "
            # who is logging in: the firewall must not drop the very address doing this
            "from=${SSH_CLIENT%% *}; "
            "case \"$from\" in 10.*|192.168.*|169.254.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|"
            "100.6[4-9].*|100.[7-9][0-9].*|100.1[01][0-9].*|100.12[0-7].*|fe80:*|fd*|fc*|::1|127.*|'') ;; "
            "*) echo \"you are reaching this machine from $from, which this firewall would refuse; "
            "nothing was changed\" >&2; exit 4;; esac; "
            "printf %s " + shlex.quote(nft_rules(ssh_port)) + " > " + NFT_FILE + "; "
            "nft -c -f " + NFT_FILE + " || { echo 'nftables refused the rules, so nothing was loaded' >&2; exit 3; }; "
            "rm -f " + OK_MARK + "; nft -f " + NFT_FILE + "; "
            "(setsid sh -c 'sleep " + str(UNDO_S) + "; [ -f " + OK_MARK + " ] || nft delete table inet bento' "
            ">/dev/null 2>&1 </dev/null &); "
            "touch /etc/nftables.conf; grep -qF 'include \"" + NFT_FILE + "\"' /etc/nftables.conf || "
            "echo 'include \"" + NFT_FILE + "\"' >> /etc/nftables.conf; "
            "systemctl enable nftables >/dev/null 2>&1 || true; "
            "echo 'firewall on; it switches itself off in " + str(UNDO_S) + "s unless Bento can still log in'")


KEY_RE = re.compile(r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com|"
                    r"sk-ecdsa-sha2-nistp256@openssh\.com) ([A-Za-z0-9+/]{40,}={0,3})(?: ([\w.@:+-]{1,100}))?")


def your_key(text: str) -> str:
    """A person's own public key, as one clean line, or ''. Only the key type, the key and a
    plain comment: an authorized_keys line can also carry options (command=…, from=…), and a
    pasted line must never smuggle one in."""
    t = " ".join(str(text or "").split())
    m = KEY_RE.fullmatch(t)
    if not m:
        return ""
    return " ".join(x for x in m.groups() if x)


def local_key() -> str:
    """This person's own key on the machine the terminal runs on, when there is one."""
    for n in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub"):
        try:
            k = your_key((Path(os.path.expanduser("~/.ssh")) / n).read_text())
        except OSError:
            continue
        if k:
            return k
    return ""


YOURKEY = {"id": "yourkey", "title": "Let your own key in",
           "why": "You can still log in with your own key once password logins are off."}
PASSWORDS_BACK = (
    "rm -f " + DROPIN + "; sshd -t || { echo 'sshd refused its own configuration' >&2; exit 3; }; "
    "systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || "
    "service ssh reload 2>/dev/null || pkill -HUP -x sshd")


def _key_snippet(pk: str) -> str:
    return ("umask 077; mkdir -p ~/.ssh; grep -qxF " + shlex.quote(pk) + " ~/.ssh/authorized_keys 2>/dev/null"
            " || echo " + shlex.quote(pk) + " >> ~/.ssh/authorized_keys")


def clean_steps(steps) -> list[str]:
    """The steps asked for, in their own order; an unknown one is dropped."""
    asked = set(IDS if steps is None else steps)
    return [s for s in IDS if s in asked]


def remote_for(step: str, pk: str, ssh_port: int = 22, sudo_pw: bool = False) -> str:
    """The exact command one step sends. Root steps go through sudo: `-n` when the user needs
    no password for it (a Pi's first user), `-S` reading the password from stdin otherwise."""
    if step == "key":
        return _key_snippet(pk)
    body = {"passwords": PASSWORDS_ROOT, "firewall": _firewall(ssh_port), "updates": UPDATES_ROOT}[step]
    return ("sudo -S -p '' " if sudo_pw else "sudo -n ") + "sh -c " + shlex.quote(body)


def plan(steps, ssh_port: int = 22, sudo_pw: bool = False, mine: str = "") -> list[dict]:
    """What will run there, step by step, shown before it runs. `mine` is the person's own
    public key, let in first, so turning password logins off never shuts them out."""
    pk = ri.public_key() or "<this machine's key>"
    first = [{**YOURKEY, "runs": _key_snippet(mine)}] if mine else []
    return first + [{"id": s["id"], "title": s["title"], "why": s["why"],
                     "runs": remote_for(s["id"], pk, ssh_port, sudo_pw)}
                    for s in STEPS if s["id"] in clean_steps(steps)]


def _check_script(pk: str) -> str:
    parts = [f"echo {s['id']}=$({s['check'].format(pk=shlex.quote(pk))})" for s in STEPS]
    parts.append("echo sudo=$(sudo -n true 2>/dev/null && echo ok || echo no)")
    parts.append("echo apt=$(command -v apt-get >/dev/null && echo ok || echo no)")
    return "; ".join(parts)


def _pk() -> str:
    return ri.public_key() or ri.ensure_key()


def _guard(host: str, user: str) -> None:
    if ri.missing():
        raise ri.InstallError(ri.missing())
    bad = ri.valid_target(host, user)
    if bad:
        raise ri.InstallError(bad)


async def check(host: str, user: str, password: str = "", port: int = 22) -> dict:
    """Which steps are already in place there. Changes nothing."""
    _guard(host, user)
    password_ok = bool(password)
    script = _check_script(_pk())
    code, out, err = await ri._run(host, user, port, password, script, ri.CHECK_TIMEOUT)
    if code != 0 and password and "permission denied" in (err or "").lower():
        # password logins may already be off there; this machine's key may still get in
        code, out, err2 = await ri._run(host, user, port, "", script, ri.CHECK_TIMEOUT)
        if code == 0:
            password_ok = False
        else:
            err = err or err2
    if code != 0:
        raise ri.InstallError(ri._why(err, code, bool(password)))
    facts = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
    done = {s: facts.get(s) == "ok" for s in IDS}
    sudo, apt = facts.get("sudo") == "ok", facts.get("apt") == "ok"
    problems = []
    if not apt:
        problems.append("it isn't Debian or Raspberry Pi OS, so the firewall and updates steps can't run")
    if not sudo and not password:
        problems.append(f"{user} needs a password for sudo there; type it and check again")
    todo = [s for s in IDS if not done[s]]
    return {"host": host, "user": user, "done": done, "sudo": sudo, "apt": apt, "problems": problems,
            "login": "password" if password_ok else "key",
            "host_key": ri.fingerprint(host, port), "plan": plan(todo, port, not sudo)}


async def secure(host: str, user: str, password: str = "", port: int = 22, steps=None,
                 on_line=None, mine: str = "") -> dict:
    """Run the chosen steps there, in order, then read the machine back with `check()`.
    Raises InstallError on the first step that fails; what ran before it stays done."""
    _guard(host, user)
    pk = _pk()
    want = clean_steps(steps)
    before = await check(host, user, password, port)
    sudo_pw = not before["sudo"]
    if sudo_pw and not password and any(s != "key" for s in want if not before["done"][s]):
        raise ri.InstallError(f"{user} needs a password for sudo there; type it and try again")
    if not before["apt"]:
        want = [s for s in want if s not in ("firewall", "updates")]

    async def say(ln):
        if on_line:
            await on_line(ln)
    ran = []
    # how to log in: the password until password logins are off, the key after that. sudo
    # may still want the password on stdin; that is the account's, not the SSH login's.
    login = password if before["login"] == "password" else ""
    if mine:
        await say(f"→ {YOURKEY['title']}")
        code, _, err = await ri._run(host, user, port, login, _key_snippet(mine), ri.CHECK_TIMEOUT)
        if code != 0:
            raise ri.InstallError(f"{YOURKEY['title']} stopped: {ri._why(err, code, bool(login))}")
        ran.append("yourkey")
        await say(f"✓ {YOURKEY['title']}")
    for sid in want:
        if before["done"].get(sid):
            await say(f"✓ {TITLES[sid]}: already done")
            continue
        if sid == "passwords":
            await say("checking this machine's key gets in on its own…")
            code, _, err = await ri._run(host, user, port, "", "true", ri.CHECK_TIMEOUT)
            if code != 0:
                raise ri.InstallError("this machine's key didn't get in on its own, so password logins "
                                      "were left on (" + ri._why(err, code) + ")")
        await say(f"→ {TITLES[sid]}")
        feed = (password + "\n") if (sudo_pw and sid != "key") else None
        code, out, err = await ri._run(host, user, port, login, remote_for(sid, pk, port, sudo_pw),
                                       SUDO_TIMEOUT, on_line, stdin=feed)
        if code != 0:
            said = [ri.clean_line(ln) for ln in (err or "").splitlines() if ri.clean_line(ln)]
            if code == 255 and not said:
                raise ri.InstallError(ri._why(err, code))
            raise ri.InstallError(f"{TITLES[sid]} stopped: {(said or ['code ' + str(code)])[-1][:200]}")
        if sid == "firewall":
            # a NEW login through the firewall is the proof; it stops the undo timer
            keep = ("sudo -S -p '' " if sudo_pw else "sudo -n ") + "sh -c " + shlex.quote("touch " + OK_MARK)
            code, _, err = await ri._run(host, user, port, login, keep, ri.CHECK_TIMEOUT,
                                         stdin=(password + "\n") if sudo_pw else None)
            if code != 0:
                raise ri.InstallError(f"after the firewall went on, Bento couldn't log in again, so it "
                                      f"switches itself off within {UNDO_S} seconds ({ri._why(err, code)})")
        if sid == "passwords":
            login = ""
            # reloading sshd re-executes it, and for a moment it refuses connections; found by
            # the live run, where the firewall's login landed in that moment. Wait for a
            # key-only login to get in again, which also proves the key works after the change.
            await say("waiting for SSH to take the change…")
            for _ in range(RELOAD_TRIES):
                code, _, err = await ri._run(host, user, port, "", "true", ri.CHECK_TIMEOUT)
                if code == 0:
                    break
                await asyncio.sleep(RELOAD_WAIT_S)
            else:
                raise ri.InstallError("after password logins went off, SSH did not let this machine's key "
                                      "back in (" + ri._why(err, code) + ")")
        ran.append(sid)
        await say(f"✓ {TITLES[sid]}")
    after = await check(host, user, login, port)
    return {"ok": True, "ran": ran, "done": after["done"], "host_key": after["host_key"]}


async def let_in(host: str, user: str, password: str = "", port: int = 22, mine: str = "",
                 passwords_on: bool = False) -> dict:
    """Let a person back in after Secure it: their own key added, and/or password logins on
    again (Bento's file in sshd_config.d removed, the rest of sshd's settings as they were).
    Logs in with this machine's key when the password no longer works."""
    _guard(host, user)
    if not mine and not passwords_on:
        raise ri.InstallError("nothing to do: paste your own key, or ask for password logins back")
    before = await check(host, user, password, port)
    login = password if before["login"] == "password" else ""
    done = []
    if mine:
        code, _, err = await ri._run(host, user, port, login, _key_snippet(mine), ri.CHECK_TIMEOUT)
        if code != 0:
            raise ri.InstallError(f"your key was not added: {ri._why(err, code, bool(login))}")
        done.append("yourkey")
    if passwords_on and before["done"].get("passwords"):
        if not before["sudo"] and not password:
            raise ri.InstallError(f"{user} needs a password for sudo there; type it and try again")
        cmd = ("sudo -S -p '' " if not before["sudo"] else "sudo -n ") + "sh -c " + shlex.quote(PASSWORDS_BACK)
        code, _, err = await ri._run(host, user, port, login, cmd, ri.CHECK_TIMEOUT,
                                     stdin=(password + "\n") if not before["sudo"] else None)
        if code != 0:
            said = [ri.clean_line(ln) for ln in (err or "").splitlines() if ri.clean_line(ln)]
            raise ri.InstallError("password logins were not turned back on: "
                                  + ((said or [ri._why(err, code)])[-1][:200]))
        done.append("passwords_on")
        for _ in range(RELOAD_TRIES):      # sshd re-executes on reload, as in secure()
            code, _, _ = await ri._run(host, user, port, "", "true", ri.CHECK_TIMEOUT)
            if code == 0:
                break
            await asyncio.sleep(RELOAD_WAIT_S)
    after = await check(host, user, "", port)
    return {"ok": True, "done": done, "security": after["done"]}


async def remove_key(host: str, user: str, password: str = "", port: int = 22, force: bool = False) -> dict:
    """Take this machine's SSH key off that machine (Disconnect). Refused when it is the only
    key there and password logins are off: that would leave nobody able to log in over SSH,
    and a Pi with no screen is then a reflash. `force` is the person saying they have another
    way in."""
    _guard(host, user)
    pk = ri.public_key()
    if not pk:
        return {"ok": True, "removed": False, "why": "this machine has no SSH key, so there is nothing to take off"}
    q = shlex.quote(pk)
    probe = ("f=~/.ssh/authorized_keys; "
             "echo ours=$(grep -cxF " + q + " $f 2>/dev/null || true); "
             "echo others=$(grep -vxF " + q + " $f 2>/dev/null | grep -cE '^(ssh-|ecdsa-|sk-)' || true); "
             "echo pwoff=$(grep -qi '^PasswordAuthentication no' " + DROPIN + " 2>/dev/null && echo yes || echo no)")
    code, out, err = await ri._run(host, user, port, password, probe, ri.CHECK_TIMEOUT)
    if code != 0:
        raise ri.InstallError(ri._why(err, code, bool(password)))
    f = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
    if (f.get("ours") or "0").strip() in ("", "0"):
        return {"ok": True, "removed": False, "why": "this machine's key is not on it"}
    if (f.get("others") or "0").strip() in ("", "0") and f.get("pwoff") == "yes" and not force:
        raise ri.InstallError("this machine's key is the only one there and password logins are off, so "
                              "taking it off would leave nobody able to log in over SSH. Turn password "
                              "logins back on there, or add your own key first")
    cmd = ("f=~/.ssh/authorized_keys; t=$(mktemp ~/.ssh/.ak.XXXXXX) && grep -vxF " + q + " $f > $t; "
           "chmod 600 $t && mv $t $f")
    code, out, err = await ri._run(host, user, port, password, cmd, ri.CHECK_TIMEOUT)
    if code != 0:
        raise ri.InstallError(ri._why(err, code, bool(password)))
    return {"ok": True, "removed": True}
