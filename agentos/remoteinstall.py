"""Install Bento on another machine on this network, over SSH, with a person's yes.

The second half of "discover the devices in the network and ask if you would like to install
on it": netscan.py finds a machine that answers SSH (a Raspberry Pi, any Linux box); this
logs in, checks what it is, and runs the real installer there with the community's
enrolment key. The new machine then comes up waiting with that key, the leader hears it
(provision.py) and sets it up as a member with an agent, without a code. One road, end to
end: plugged in → seen → asked → installed → enabled.

Four rules:

  * IT IS A PERSON'S ACT. Logging into another machine and running an installer there is
    the largest thing this OS does to anything it does not own, so it is admin only, there
    is no agent tool, and every step is a ledger row. What will be run is shown before it
    runs (`plan()`), and the check (`check()`) says what the machine is first.
  * THE PASSWORD IS NEVER KEPT. It is handed to the system's own `ssh` through SSH_ASKPASS
    from an environment variable of that one child process, and dropped. Nothing writes it
    to disk, a log or the ledger. With "let this machine in from now on", the leader's own
    key (`ensure_key`) is added to the account instead, and later visits need no password.
  * THE OTHER MACHINE'S KEY IS PINNED. Bento keeps its own known_hosts; the first visit
    records the host key (`accept-new`) and a later visit to a machine whose key changed is
    refused by ssh itself. The fingerprint is shown with the check.
  * IT USES THE SYSTEM'S `ssh`. Python's SSH libraries are LGPL or EPL, and this project
    ships only permissive code (CLAUDE.md, Licensing); OpenSSH is on every Pi and nearly
    every Linux and Mac already. With no `ssh` here, the card says which package adds it.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

INSTALL_URL = "https://raw.githubusercontent.com/{repo}/master/install.sh"
CHECK_TIMEOUT = 25
INSTALL_TIMEOUT = 45 * 60          # a Pi Zero building the environment takes a while
USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")

# What the check runs on the other machine: read-only, one line per fact.
CHECK_SCRIPT = (
    "echo arch=$(uname -m); "
    "echo board=$(tr -d '\\0' </proc/device-tree/model 2>/dev/null); "
    "echo os=$(. /etc/os-release 2>/dev/null && echo \"$PRETTY_NAME\"); "
    "echo curl=$(command -v curl >/dev/null && echo yes || echo no); "
    "echo bento=$(test -x \"$HOME/.local/bin/bento\" -o -n \"$(command -v bento)\" && echo yes || echo no); "
    "echo free_kb=$(df -Pk \"$HOME\" | awk 'NR==2{print $4}'); "
    "echo ram_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null)"
)


class InstallError(Exception):
    """A sentence for the person."""


def _home() -> Path:
    from . import teamlink
    return teamlink.home()


def ssh_bin() -> str:
    return shutil.which("ssh") or ""


def missing() -> str:
    """'' when this machine can log into another, else what to install."""
    if not ssh_bin():
        return ("This machine has no ssh client. Install OpenSSH (on Debian or Raspberry Pi OS: "
                "sudo apt install openssh-client).")
    return ""


def key_path() -> Path:
    return _home() / "pki" / "ssh_ed25519"


def ensure_key(name: str = "") -> str:
    """This machine's own SSH key (made once, 0600) and its public half, which is what a
    person puts into Raspberry Pi Imager so the leader can reach a new Pi with no password."""
    p = key_path()
    if not p.exists():
        if not shutil.which("ssh-keygen"):
            raise InstallError(missing() or "There is no ssh-keygen here.")
        p.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(p.parent, 0o700)
        r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                            f"bento@{name or socket.gethostname()}", "-f", str(p)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise InstallError(f"could not make this machine's SSH key: {r.stderr.strip()[:200]}")
    return Path(str(p) + ".pub").read_text().strip()


def public_key() -> str:
    try:
        return Path(str(key_path()) + ".pub").read_text().strip()
    except OSError:
        return ""


def known_hosts() -> Path:
    return _home() / "pki" / "known_hosts"


def install_url(cfg: dict | None = None) -> str:
    """Where the installer comes from: this machine's own update source, so a fork installs
    itself. `AGENTOS_INSTALL_URL` points it elsewhere (a test, a mirror)."""
    env = os.environ.get("AGENTOS_INSTALL_URL")
    if env:
        return env
    try:
        from . import updates
        repo = updates.repo_of(cfg or {})
    except Exception:
        repo = ""
    return INSTALL_URL.format(repo=repo or "contact9prime-lab/bento-ai-os")


def valid_target(host: str, user: str) -> str:
    from . import netscan
    if not USER_RE.fullmatch(str(user or "")):
        return "that is not a user name (lower-case letters, digits, - and _)"
    if not netscan.allowed(str(host or "")):
        return "Bento installs only on a machine on this network (a private address)"
    return ""


def _base(host: str, user: str, port: int, password: str) -> tuple[list, dict, str]:
    """The ssh command line and environment for one call, and a scratch dir to remove."""
    kh = known_hosts()
    kh.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ssh_bin(), "-p", str(int(port or 22)), "-o", f"UserKnownHostsFile={kh}",
           "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
           "-o", "ServerAliveInterval=15", "-o", "LogLevel=ERROR"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("SSH_")}
    scratch = ""
    if password:
        # SSH_ASKPASS reads the password from this child's environment and nothing else;
        # it is never written to a file. The script itself holds no secret.
        scratch = tempfile.mkdtemp(prefix=".askpass-", dir=str(kh.parent))
        os.chmod(scratch, 0o700)
        ap = Path(scratch) / "askpass"
        ap.write_text('#!/bin/sh\nprintf "%s\\n" "$BENTO_SSH_PASSWORD"\n')
        os.chmod(ap, 0o700)
        env.update(SSH_ASKPASS=str(ap), SSH_ASKPASS_REQUIRE="force", DISPLAY=env.get("DISPLAY", ":0"),
                   BENTO_SSH_PASSWORD=password)
        cmd += ["-o", "PreferredAuthentications=password,keyboard-interactive",
                "-o", "PubkeyAuthentication=no", "-o", "NumberOfPasswordPrompts=1"]
    else:
        if not key_path().exists():
            raise InstallError("this machine has no SSH key yet, and no password was given")
        cmd += ["-i", str(key_path()), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes"]
    cmd += ["-T", f"{user}@{host}"]
    return cmd, env, scratch


def _why(stderr: str, code: int) -> str:
    s = (stderr or "").strip()
    low = s.lower()
    if "permission denied" in low:
        return "the user name or password was refused"
    if "host key verification failed" in low or "remote host identification has changed" in low:
        return ("that machine's key is not the one seen last time, so it was refused. If it was "
                "reinstalled, forget it in this machine's known hosts and try again")
    if "connection refused" in low:
        return "nothing answers SSH there (is SSH switched on for that machine?)"
    if "timed out" in low or "no route" in low:
        return "that machine did not answer"
    return (s.splitlines()[-1][:200] if s else f"ssh stopped with code {code}")


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def clean_line(ln: str) -> str:
    """One line of the other machine's output, as words: its colours dropped and any other
    control character removed, because it is shown in a toast and a terminal."""
    from . import teamlink
    return teamlink.plain(ANSI.sub("", ln or "").rstrip(), 300, newlines=False).strip()


def fingerprint(host: str, port: int = 22) -> str:
    """The pinned host key's SHA256 fingerprint, after a first visit."""
    target = host if int(port or 22) == 22 else f"[{host}]:{port}"
    try:
        r = subprocess.run(["ssh-keygen", "-l", "-F", target, "-f", str(known_hosts())],
                           capture_output=True, text=True, timeout=10)
        m = re.search(r"(SHA256:[A-Za-z0-9+/=]+)", r.stdout)
        return m.group(1) if m else ""
    except Exception:
        return ""


async def _run(host, user, port, password, remote: str, timeout: float, on_line=None) -> tuple[int, str, str]:
    cmd, env, scratch = _base(host, user, port, password)
    try:
        p = await asyncio.create_subprocess_exec(*cmd, remote, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                 stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
        out_lines: list = []

        async def pump():
            async for raw in p.stdout:
                ln = clean_line(raw.decode(errors="replace"))
                out_lines.append(ln)
                if on_line:
                    await on_line(ln)
        try:
            await asyncio.wait_for(asyncio.gather(pump(), p.wait()), timeout)
        except asyncio.TimeoutError:
            p.kill()
            raise InstallError("it took too long; nothing more was run")
        err = (await p.stderr.read()).decode(errors="replace")
        return p.returncode, "\n".join(out_lines), err
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)


async def check(host: str, user: str, password: str = "", port: int = 22) -> dict:
    """Log in and read what the machine is. Changes nothing there."""
    if missing():
        raise InstallError(missing())
    bad = valid_target(host, user)
    if bad:
        raise InstallError(bad)
    code, out, err = await _run(host, user, port, password, CHECK_SCRIPT, CHECK_TIMEOUT)
    if code != 0:
        raise InstallError(_why(err, code))
    facts = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
    from . import teamlink

    def num(k):
        try:
            return int(facts.get(k) or 0)
        except ValueError:
            return 0
    return {"host": host, "user": user, "arch": teamlink.plain(facts.get("arch"), 20, newlines=False),
            "board": teamlink.plain(facts.get("board"), 60, newlines=False),
            "os": teamlink.plain(facts.get("os"), 60, newlines=False),
            "curl": facts.get("curl") == "yes", "bento": facts.get("bento") == "yes",
            "free_mb": num("free_kb") // 1024, "ram_mb": num("ram_kb") // 1024,
            "host_key": fingerprint(host, port),
            "problems": problems({"curl": facts.get("curl") == "yes", "free_mb": num("free_kb") // 1024,
                                  "arch": facts.get("arch") or ""})}


def problems(c: dict) -> list[str]:
    """What would stop the install, in sentences, before anything is run."""
    out = []
    if not c.get("curl"):
        out.append("curl is not installed there (sudo apt install curl)")
    if c.get("free_mb", 0) and c["free_mb"] < 1500:
        out.append(f"only {c['free_mb']} MB free there; Bento needs about 1.5 GB")
    if c.get("arch") and c["arch"] not in ("aarch64", "arm64", "x86_64", "amd64", "armv7l"):
        out.append(f"{c['arch']} is not a processor Bento runs on")
    return out


def plan(cfg: dict | None, key_text: str, authorize: bool = False) -> str:
    """The exact command that will run on the other machine: shown before it runs."""
    # No --yes: that answers yes to every OPTIONAL extra (Claude Code, Codex, a boot
    # splash…), which nobody agreed to on this consent screen. With no terminal the
    # installer installs Bento itself and only reports the extras. Found by the live run.
    flags = ["--lite"] + ([f"--enroll={key_text}"] if key_text else ["--wait"])
    cmd = f"curl -fsSL {shlex.quote(install_url(cfg))} | sh -s -- " + " ".join(shlex.quote(f) for f in flags)
    if authorize and not public_key():
        try:
            ensure_key()                # "let this machine in" needs this machine's key
        except InstallError:
            pass
    if authorize and public_key():
        pk = public_key()
        cmd = ("umask 077; mkdir -p ~/.ssh; grep -qxF " + shlex.quote(pk) + " ~/.ssh/authorized_keys 2>/dev/null"
               " || echo " + shlex.quote(pk) + " >> ~/.ssh/authorized_keys; " + cmd)
    repo = os.environ.get("AGENTOS_REPO")
    if repo:                      # a test or a mirror: the installer clones from here
        cmd = cmd.replace("| sh -s", f"| AGENTOS_REPO={shlex.quote(repo)} sh -s")
    return cmd


async def install(cfg: dict, host: str, user: str, password: str, key_text: str,
                  authorize: bool = False, port: int = 22,
                  on_line=None) -> dict:
    """Run the installer there, streaming its lines to `on_line`. Raises InstallError."""
    if missing():
        raise InstallError(missing())
    bad = valid_target(host, user)
    if bad:
        raise InstallError(bad)
    remote = plan(cfg, key_text, authorize)
    code, out, err = await _run(host, user, port, password, remote, INSTALL_TIMEOUT, on_line)
    if code != 0:
        said = [clean_line(ln) for ln in (err or "").splitlines() if clean_line(ln)]
        tail = [ln for ln in out.splitlines() if ln.strip()]
        if code == 255 or not (said or tail):
            raise InstallError(_why(err, code))     # ssh itself failed: it never ran
        raise InstallError(f"the installer stopped: {(said or tail)[-1][:200]}")
    return {"ok": True, "host": host, "host_key": fingerprint(host, port),
            "authorized": bool(authorize and public_key())}
