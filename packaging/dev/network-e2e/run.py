"""Settings → Network, end to end, against a real machine: found, checked, secured, disconnected.

The stand-in Raspberry Pi is a container (build.sh) with a real OpenSSH server, sudo and
nftables: user `pi` with a password and passwordless sudo, as Raspberry Pi OS sets it up, and
an sshd_config with no Include line, as Buster ships it. It gets NET_ADMIN for its own network
namespace only, so its firewall is real and this machine's is not touched.

  1. Look at the network finds it (SSH open), and the list says "not checked"
  2. Check logs in with the password and reads all four steps as off, changing nothing
  3. Secure it runs the four steps: the key goes on, a key-only login is proved, password
     logins go off, the firewall goes on and is kept by a NEW login, and unattended-upgrades
     is installed from the distribution's mirror (with no mirror, that step fails in a
     sentence and the list records what was measured, 3 of 4)
  4. From outside, measured again: a password login is refused, the key gets in, a port the
     firewall doesn't keep (9999, a listener started before) no longer answers, SSH still does
  5. 95 seconds later the firewall is still on: the undo timer was stopped by the new login
  6. Disconnect is refused while this machine's key is the only way in, then works once the
     person's own key is there, and this machine's key no longer gets in
  7. every step is a ledger row

    .venv/bin/python packaging/dev/network-e2e/run.py [WORKDIR] [--keep]
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "") or tempfile.mkdtemp(prefix="net-e2e-"))
KEEP = "--keep" in sys.argv
WORK.mkdir(parents=True, exist_ok=True)
HTTP = 8581
BOX = "bento-netbox"
PW = "raspberry-test-2"
REPORT: dict = {"steps": []}
PROCS: list = []


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def step(title, **facts):
    say(f"✓ {title}" + "".join(f"\n     {k}: {v}" for k, v in facts.items()))
    REPORT["steps"].append({"step": title, **facts})


def sh(*cmd, check=True, **kw):
    r = subprocess.run(list(cmd), capture_output=True, text=True, **kw)
    if check and r.returncode:
        raise SystemExit(f"{' '.join(cmd)[:120]}: {r.stderr.strip()[:300]}")
    return r


def api(path, body=None, method=None):
    req = urllib.request.Request(f"http://127.0.0.1:{HTTP}{path}", method=method or ("POST" if body is not None else "GET"),
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def answers(ip, port, timeout=3.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    say(f"work dir {WORK}")
    if not sh("docker", "image", "inspect", BOX, check=False).returncode == 0:
        sh("sh", str(HERE / "build.sh"), str(WORK / "image"))
    sh("docker", "rm", "-f", BOX, check=False)
    sh("docker", "run", "-d", "--name", BOX, "--cap-add", "NET_ADMIN", BOX)
    ip = sh("docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", BOX).stdout.strip()
    # a service the firewall should stop answering: started before anything is secured
    sh("docker", "exec", "-d", BOX, "python3", "-m", "http.server", "9999")
    for _ in range(50):
        if answers(ip, 22, 1) and answers(ip, 9999, 1):
            break
        time.sleep(0.2)
    say(f"the stand-in Pi is at {ip}")

    home = WORK / "home"
    env = {**os.environ, "AGENTOS_HOME": str(home), "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1",
           "AGENTOS_SCAN_NETWORKS": f"{ip}/32", "AGENTOS_SCAN_PORTS": "22,8321",
           "NO_PROXY": f"127.0.0.1,localhost,{ip}", "no_proxy": f"127.0.0.1,localhost,{ip}"}
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(k, None)
    log = open(WORK / "lead.log", "w")
    PROCS.append(subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "agentos", "serve", "--port", str(HTTP)],
                                  cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT))
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{HTTP}/api/platform", timeout=2)
            break
        except Exception:
            time.sleep(0.3)
    api("/api/devices/sshkey", {})

    # 1. found
    code, d = api("/api/devices/scan", {})
    _, v = api("/api/network")
    row = next(r for r in v["rows"] if r["ip"] == ip)
    assert row["ssh"] and row["security_words"] == "not checked", row
    step("1. Look at the network found it, and it is not checked yet", found=d.get("found"),
         row={k: row[k] for k in ("ip", "bento", "security_words", "ssh")})

    # 2. checked, nothing changed
    code, c = api("/api/network/check", {"ip": ip, "user": "pi", "password": PW})
    assert code == 200 and not any(c["done"].values()), c
    step("2. Check read all four steps as off", done=c["done"], plan=[p["id"] for p in c["plan"]],
         host_key=c.get("host_key") or "(pinned)")

    # 3. secured
    code, s = api("/api/network/secure", {"ip": ip, "user": "pi", "password": PW,
                                          "steps": ["key", "passwords", "firewall", "updates"]})
    assert code == 200, s
    for _ in range(600):
        _, v = api("/api/network")
        run = v["secures"].get(ip) or {}
        if run.get("state") in ("done", "failed"):
            break
        time.sleep(0.5)
    row = next(r for r in v["rows"] if r["ip"] == ip)
    done = (row.get("security") or {}).get("done") or {}
    assert done.get("key") and done.get("passwords") and done.get("firewall"), (run, done)
    step("3. Secure it ran, and the list records what was measured", state=run.get("state"),
         error=run.get("error", ""), recorded=row["security_words"], lines=run.get("lines", [])[-8:])

    # 4. measured from outside, not from the run's word
    sys.path.insert(0, str(REPO))
    os.environ["AGENTOS_HOME"] = str(home)
    import asyncio

    from agentos import remoteinstall as ri
    from agentos import teamlink
    with teamlink.at(home):
        pw_code, _, pw_err = asyncio.run(ri._run(ip, "pi", 22, PW, "true", 20))
        key_code, _, _ = asyncio.run(ri._run(ip, "pi", 22, "", "true", 20))
    assert pw_code != 0 and "denied" in pw_err.lower(), pw_err
    assert key_code == 0
    nft = sh("docker", "exec", BOX, "nft", "list", "table", "inet", "bento").stdout
    assert "policy drop" in nft
    blocked = not answers(ip, 9999, 3)
    assert blocked and answers(ip, 22, 3)
    dropin = sh("docker", "exec", BOX, "cat", "/etc/ssh/sshd_config.d/10-bento.conf").stdout.split()
    step("4. From outside: passwords refused, the key gets in, 9999 is dropped and SSH answers",
         password_login=pw_err.strip().splitlines()[-1][:80], key_login="ok",
         port_9999="no answer" if blocked else "ANSWERS", port_22="answers", sshd_dropin=" ".join(dropin))

    # 5. the undo timer was stopped by the new login
    say("waiting 95 s for the firewall's undo timer…")
    time.sleep(95)
    still = sh("docker", "exec", BOX, "nft", "list", "table", "inet", "bento", check=False).returncode == 0
    assert still
    step("5. After 95 seconds the firewall is still on (kept by a new login)",
         kept_mark=sh("docker", "exec", BOX, "ls", "/run/bento-firewall-ok", check=False).stdout.strip())

    # 6. disconnect: refused while it is the only way in, then works
    _, v = api("/api/network")
    row = next(r for r in v["rows"] if r["ip"] == ip)
    code, d1 = api("/api/network/disconnect", {"key": row["key"], "what": ["key"], "user": "pi"})
    assert not d1.get("removed") and any("nobody able to log in" in f for f in d1.get("failed", [])), d1
    sh("docker", "exec", BOX, "sh", "-c",
       "echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPersonsOwnKeyForTheLiveRun00000000000 person@laptop' "
       ">> /home/pi/.ssh/authorized_keys")
    code, d2 = api("/api/network/disconnect", {"key": row["key"], "what": ["key"], "user": "pi"})
    assert d2.get("removed"), d2
    with teamlink.at(home):
        after, _, after_err = asyncio.run(ri._run(ip, "pi", 22, "", "true", 20))
    assert after != 0
    left = sh("docker", "exec", BOX, "cat", "/home/pi/.ssh/authorized_keys").stdout.strip().splitlines()
    step("6. Disconnect refused to lock everybody out, then took this machine's key off",
         first=d1.get("failed"), second=d2.get("removed"), key_login_now=after_err.strip().splitlines()[-1][:80],
         keys_left=[k.split()[-1] for k in left])

    # 7. the ledger
    db = sqlite3.connect(home / "agentos.db")
    rows = [r[0] for r in db.execute("SELECT action FROM audit WHERE action LIKE 'device.%' ORDER BY seq")]
    for a in ("device.scan", "device.check", "device.secure", "device.disconnect"):
        assert a in rows, (a, rows)
    assert "device.secured" in rows or "device.secure_failed" in rows, rows
    step("7. Every step is a ledger row", actions=rows)

    (WORK / "report.json").write_text(json.dumps(REPORT, indent=1))
    say(f"all steps passed; report {WORK / 'report.json'}")


if __name__ == "__main__":
    try:
        main()
    finally:
        if KEEP:
            say(f"left running: lead http://127.0.0.1:{HTTP}, the Pi container {BOX}")
        else:
            for p in PROCS:
                p.terminate()
            subprocess.run(["docker", "rm", "-f", BOX], capture_output=True)
