"""A machine WITHOUT Bento joins the network, is heard, and gets Bento installed over SSH.

The POAP road for a machine that runs nothing of ours yet, walked end to end on one box. Run
as root in a throwaway container (it adds a user and starts an SSH server):

  1. a stand-in Pi: a user `pi` with a password, a real OpenSSH server on 127.0.0.2:2222
     and nothing of Bento on it
  2. the Pi says its name on the network the way avahi does on a booted Raspberry Pi (an
     mDNS answer: raspberrypi.local is 127.0.0.2); the leader hears it, knocks on SSH, and
     writes the toast's ledger row
  3. Look at the network finds it with its SSH banner
  4. Check logs in with the password and reads what the machine is, changing nothing
  5. Install runs the REAL installer there (install.sh, cloning a local mirror of this
     repository, building its environment from PyPI) with a key made for that one machine,
     and lets the leader's SSH key in for next time
  6. Bento starts on the Pi (as its boot service would), carries the key, is heard, and is
     set up as a member with its agent; it thinks with the leader's brain
  7. the leader can now reach it with its own key, no password

    sudo .venv/bin/python packaging/dev/provision-e2e/install_over_ssh.py [WORKDIR] [--keep]
"""
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="ssh-e2e-"))
KEEP = "--keep" in sys.argv
WORK.mkdir(parents=True, exist_ok=True)
PI_IP, SSH_PORT, PI_HTTP, PI_DOOR, MDNS = "127.0.0.2", 2222, 8572, 8772, 15353
LEAD_HTTP, LEAD_LINK, BRAIN = 8571, 8671, 9471
PI_PASSWORD = "raspberry-test-1"
ENV = {**os.environ, "NO_PROXY": "127.0.0.1,localhost,127.0.0.2", "no_proxy": "127.0.0.1,localhost,127.0.0.2",
       "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1",
       "AGENTOS_DISCOVER_UDP": "18630", "AGENTOS_DISCOVER_TARGETS": "127.255.255.255",
       "AGENTOS_SCAN_NETWORKS": f"{PI_IP}/32", "AGENTOS_SCAN_PORTS": f"{SSH_PORT},{PI_HTTP}",
       "AGENTOS_MDNS_PORT": str(MDNS), "AGENTOS_REPO": "/srv/bento.git",
       "AGENTOS_INSTALL_URL": "file:///srv/install.sh"}
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    ENV.pop(k, None)
PROCS: dict = {}
PLACED: list = []
REPORT: dict = {"steps": []}


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def step(title, **facts):
    say(f"✓ {title}" + "".join(f"\n     {k}: {v}" for k, v in facts.items()))
    REPORT["steps"].append({"step": title, **facts})


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, **kw).stdout


def http(port, method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait(what, fn, limit=120, every=1.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        got = fn()
        if got:
            return round(time.time() - t0, 1), got
        time.sleep(every)
    raise SystemExit(f"timed out waiting for: {what}")


def stand_in_pi():
    sh("id pi >/dev/null 2>&1 || useradd -m -s /bin/bash pi")
    sh(f"echo 'pi:{PI_PASSWORD}' | chpasswd")
    sh("rm -rf /home/pi/.local /home/pi/.agentos /home/pi/AgentOS /home/pi/.ssh /home/pi/.cache/uv")
    # the stand-in Pi needs uv where its user can run it; put back afterwards (cleanup), because a
    # uv left in /usr/local/bin changes what this box's own update tests see
    if not os.path.exists("/usr/local/bin/uv"):
        sh("cp /root/.local/bin/uv /root/.local/bin/uvx /usr/local/bin/ 2>/dev/null || true")
        PLACED.extend(["/usr/local/bin/uv", "/usr/local/bin/uvx"])
    sh(f"rm -rf /srv/bento.git && git clone -q --bare {REPO} /srv/bento.git && chown -R pi /srv/bento.git")
    sh(f"cp {REPO}/install.sh /srv/install.sh && chmod a+r /srv/install.sh")
    # a sandbox that intercepts TLS: the stand-in Pi trusts the sandbox's CA, as the box does
    ca = Path("/root/.ccr/ca-bundle.crt")
    if ca.exists():
        sh(f"cp {ca} /usr/local/share/ca-certificates/sandbox-proxy.crt && update-ca-certificates >/dev/null 2>&1 || true")
    conf = WORK / "sshd.conf"
    conf.write_text(f"Port {SSH_PORT}\nListenAddress {PI_IP}\nPasswordAuthentication yes\n"
                    "KbdInteractiveAuthentication no\nPubkeyAuthentication yes\nUsePAM yes\n"
                    f"PermitRootLogin no\nPidFile {WORK}/sshd.pid\n"
                    + ("SetEnv SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt\n" if ca.exists() else ""))
    sh("mkdir -p /run/sshd; ssh-keygen -A >/dev/null 2>&1 || true")
    pid = WORK / "sshd.pid"
    if pid.exists():
        sh(f"kill $(cat {pid}) 2>/dev/null || true")
    sh(f"/usr/sbin/sshd -f {conf}")
    time.sleep(1)


def mdns_answer(name: str, ip: str) -> bytes:
    """What avahi sends when a Pi gets its address: an unsolicited answer, one A record."""
    def qname(n):
        return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\0"
    head = struct.pack("!6H", 0, 0x8400, 0, 1, 0, 0)
    rr = qname(name) + struct.pack("!HHIH", 1, 0x8001, 120, 4) + socket.inet_aton(ip)
    return head + rr


def start_leader():
    home = WORK / "big-box"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Aria", "setup_complete": True, "default_model": "custom/fake-1",
        "pricing_skip": ["custom/fake-1"], "team": {"link_port": LEAD_LINK, "machine_name": "big-box"},
        "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1",
                                 "models": ["fake-1"]}}}))
    PROCS["brain"] = subprocess.Popen([sys.executable, str(REPO / "packaging/dev/pool-e2e/fake_brain.py"),
                                       str(BRAIN), "big-box's brain"], env=ENV,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS["big-box"] = subprocess.Popen([sys.executable, "-m", "agentos", "serve", "--port", str(LEAD_HTTP),
                                         "--no-browser", "--if-running", "fail"], cwd=REPO,
                                        env={**ENV, "AGENTOS_HOME": str(home)},
                                        stdout=open(home / "server.log", "a"), stderr=subprocess.STDOUT)
    return wait("the leader", lambda: http(LEAD_HTTP, "GET", "/api/provision", timeout=3)[0] == 200
                if _up(LEAD_HTTP) else None, limit=60, every=0.5)[0]


def _up(port):
    try:
        socket.create_connection(("127.0.0.1", port), 0.5).close()
        return True
    except OSError:
        return False


def ledger(prefix):
    import sqlite3
    con = sqlite3.connect(WORK / "big-box" / "agentos.db")
    rows = con.execute("select action, coalesce(reason,'') || coalesce(detail,'') from audit where action like ? "
                       "order by rowid", (prefix + "%",)).fetchall()
    con.close()
    return rows


def main():
    say(f"work dir {WORK}")
    try:
        stand_in_pi()
        step("1. a stand-in Pi with a real SSH server and no Bento",
             banner=sh(f"timeout 3 bash -c 'exec 3<>/dev/tcp/{PI_IP}/{SSH_PORT}; head -1 <&3'").strip(),
             bento_there=os.path.exists("/home/pi/.local/bin/bento"))
        up = start_leader()

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(mdns_answer("raspberrypi.local", PI_IP), ("127.0.0.1", MDNS))
        took, dev = wait("the leader hears the Pi's name", lambda: next(
            (d for d in http(LEAD_HTTP, "GET", "/api/provision")[1].get("devices") or [] if d.get("ip") == PI_IP
             and "ssh" in d), None), limit=20, every=0.3)
        step("2. the Pi said its name on the network and the leader asked", leader_up_s=up, heard_in_s=took,
             device={k: dev.get(k) for k in ("name", "ip", "ssh", "pi", "os")},
             toast_row=[d for a, d in ledger("device.seen")][:1])

        st, v = http(LEAD_HTTP, "POST", "/api/devices/scan")
        found = [d for d in v["devices"] if d["ip"] == PI_IP]
        step("3. Look at the network found it", networks=v["networks"], answered=v["found"],
             row={k: found[0].get(k) for k in ("ip", "name", "ssh", "banner")})

        st, c = http(LEAD_HTTP, "POST", "/api/devices/check", {"ip": PI_IP, "port": SSH_PORT, "user": "pi",
                                                               "password": "wrong"})
        assert st == 400, c
        st, c = http(LEAD_HTTP, "POST", "/api/devices/check", {"ip": PI_IP, "port": SSH_PORT, "user": "pi",
                                                               "password": PI_PASSWORD, "authorize": True})
        assert st == 200 and not c["problems"], c
        step("4. Check logged in and read the machine, changing nothing", wrong_password=st and "refused",
             facts={k: c[k] for k in ("os", "arch", "ram_mb", "free_mb", "bento", "host_key")}, plan=c["plan"])

        t0 = time.time()
        st, r = http(LEAD_HTTP, "POST", "/api/devices/install", {"ip": PI_IP, "port": SSH_PORT, "user": "pi",
                                                                 "password": PI_PASSWORD, "authorize": True,
                                                                 "profile": {"kiosk": True, "agent_name": "Pip"}})
        assert st == 200, r
        took, run = wait("the install", lambda: (lambda i: i if i.get("state") in ("done", "failed") else None)(
            (http(LEAD_HTTP, "GET", "/api/provision")[1].get("installs") or {}).get(PI_IP) or {}),
            limit=1800, every=3)
        assert run["state"] == "done", run
        step("5. the real installer ran there over SSH", seconds=round(time.time() - t0, 1),
             last_lines=run["lines"][-4:], bento_there=os.path.exists("/home/pi/.local/bin/bento"),
             key_carried=json.loads(Path("/home/pi/.agentos/provision.json").read_text()).get("key", "")[:24] + "…")

        # what the Pi's boot service does: start Bento as the user it was installed for
        pi_env = " ".join(f"{k}={v}" for k, v in {
            "AGENTOS_DISCOVER_UDP": ENV["AGENTOS_DISCOVER_UDP"], "AGENTOS_DISCOVER_TARGETS": "127.255.255.255",
            "AGENTOS_DISCOVER_PORT": PI_DOOR, "AGENTOS_PI_MODEL": "'Raspberry Pi 5 Model B Rev 1.0'",
            "AGENTOS_VAULT_KEYRING": "0", "NO_PROXY": "127.0.0.1,localhost"}.items())
        t1 = time.time()
        PROCS["pi"] = subprocess.Popen(["su", "-", "pi", "-c",
                                        f"cd ~/.local/src/agentic-os && {pi_env} ~/.local/bin/bento serve "
                                        f"--port {PI_HTTP} --no-browser >~/server.log 2>&1"])
        took, ms = wait("the Pi is a member", lambda: (lambda m: m if any(
            x.get("state") == "member" and not x.get("here") for x in m) else None)(
            http(LEAD_HTTP, "GET", "/api/pool")[1].get("machines") or []), limit=180, every=2)
        st, ans = http(PI_HTTP, "POST", "/api/chat", {"text": "hello from the new Pi"}, timeout=120)
        pcfg = json.loads(Path("/home/pi/.agentos/config.json").read_text())
        step("6. Bento started on the Pi, was heard, and was set up with its agent",
             member_after_s=round(time.time() - t1, 1), machines=[f"{x['name']}: {x.get('state')}" for x in ms],
             pi={"agent": pcfg.get("agent_name"), "kiosk": (pcfg.get("face") or {}).get("kiosk"),
                 "model": pcfg.get("default_model")},
             answer=(ans.get("content") or ans)[:80] if isinstance(ans, dict) else ans)

        st, c2 = http(LEAD_HTTP, "POST", "/api/devices/check", {"ip": PI_IP, "port": SSH_PORT, "user": "pi"})
        assert st == 200, c2
        step("7. the leader reaches it with its own key now, no password", bento_there=c2["bento"],
             ledger=[f"{a}: {d[:70]}" for a, d in ledger("device.")])
        REPORT["ok"] = True
    finally:
        (WORK / "report.json").write_text(json.dumps(REPORT, indent=1))
        if not KEEP:
            for p in PROCS.values():
                p.terminate()
            stop_pi_servers()
            for f in PLACED:
                Path(f).unlink(missing_ok=True)
            pid = WORK / "sshd.pid"
            if pid.exists():
                subprocess.run(f"kill $(cat {pid}) 2>/dev/null; true", shell=True)



def stop_pi_servers():
    """Stop the Pi's `bento serve` by reading /proc, never a pattern kill (which can match
    the shell running it)."""
    import pwd
    import signal
    try:
        uid = pwd.getpwnam("pi").pw_uid
    except KeyError:
        return
    mine = {os.getpid(), os.getppid()}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) in mine:
            continue
        try:
            if d.stat().st_uid != uid:
                continue
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if "bento" in cmd and " serve" in cmd:
            try:
                os.kill(int(d.name), signal.SIGTERM)
            except OSError:
                pass


if __name__ == "__main__":
    main()
