"""A Pi whose address changed, end to end: two real `bento serve`s on throwaway homes.

Two machines are linked through a real invite over mTLS. Then the hub's record of the "Pi" is
pointed at an address where nothing answers (192.0.2.1, a documentation address): what DHCP
does to a Pi after a reboot. Checked, on the running servers:

  1. HEARD: the Pi's minute hello reaches the hub from its real address, and the hub's link
     follows it there (no restart, nothing typed).
  2. FOUND: the hub's link is broken again, with the Pi's last address remembered; the hub's
     own hello fails at the old address and finds it.
  3. EVENTS: Devices → Events (/api/network/events) says "moved" both times, with how.
  4. OFFLINE / ONLINE: the Pi is stopped, then started again; the events say so.

Run:  python packaging/dev/provision-e2e/dhcp_run.py   (about five minutes: the watch is a minute;
      KEEP=1 keeps both homes afterwards)
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable
HUB, PI = 8651, 8661
FINDINGS: list[str] = []


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    finally:
        s.close()


def api(port, path, body=None, method=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"},
                                 method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def start(home: Path, port: int, name: str) -> subprocess.Popen:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps({
        "setup_complete": True, "port": port, "team": {"machine_name": name, "listen": True},
        "providers": {"ollama": {"enabled": False}}}))
    env = {**os.environ, "AGENTOS_HOME": str(home), "AGENTOS_NO_AUTOPICK": "1", "AGENTOS_VAULT_KEYRING": "0"}
    p = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(port), "--if-running=fail"],
                         cwd=ROOT, env=env, stdout=open(home / "serve.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            api(port, "/api/platform")
            return p
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"{name} did not start: see {home / 'serve.log'}")


def links(home: Path) -> dict:
    return json.loads((home / "links.json").read_text())


def set_link(home: Path, label: str, **kv) -> None:
    d = links(home)
    for lk in d["links"]:
        if lk["label"] == label:
            lk.update(kv)
    (home / "links.json").write_text(json.dumps(d, indent=1))


def url_of(home: Path, label: str) -> str:
    return next(lk["url"] for lk in links(home)["links"] if lk["label"] == label)


def wait_for(what: str, fn, secs: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < secs:
        if fn():
            print(f"  ✓ {what} ({time.time() - t0:.0f}s)")
            return True
        time.sleep(2)
    FINDINGS.append(what)
    print(f"  ✗ {what}")
    return False


def events(port) -> list[dict]:
    return api(port, "/api/network/events")["events"]


def main():
    base = Path(tempfile.mkdtemp(prefix="bento-dhcp-"))
    me = lan_ip()
    hub_home, pi_home = base / "hub", base / "pi"
    print(f"homes under {base}; this machine is {me}")
    hub = start(hub_home, HUB, "hub")
    pi = start(pi_home, PI, "pi")
    try:
        api(HUB, "/api/team/listen", {"on": True}, "PUT")
        api(PI, "/api/team/listen", {"on": True}, "PUT")
        inv = api(HUB, "/api/team/links/invite", {"kind": "machine", "address": me})
        api(PI, "/api/team/links/join", {"invite": inv["invite"]})
        label = links(hub_home)["links"][0]["label"]
        real = url_of(hub_home, label)
        print(f"  linked: the hub reaches '{label}' at {real}")

        print("1. the Pi moved; its own hello tells the hub")
        set_link(hub_home, label, url=f"192.0.2.1:{real.rsplit(':', 1)[1]}")
        wait_for("the hub follows the Pi to the address it connected from",
                 lambda: url_of(hub_home, label) == real, 150)
        wait_for("Events says it moved, and how",
                 lambda: any(e["event"] == "moved" and "connected from there" in e["text"] for e in events(HUB)), 10)

        print("2. moved again; the hub's hello fails and it looks for it")
        pi.terminate()
        pi.wait(20)        # nothing from the Pi now: only the hub's own looking can find it
        set_link(hub_home, label, url=f"192.0.2.1:{real.rsplit(':', 1)[1]}", seen_from=me)
        pi = start(pi_home, PI, "pi")
        # its hello would also fix it; whichever comes first, the link must be right again
        wait_for("the hub finds the Pi where it is now", lambda: url_of(hub_home, label) == real, 150)
        print(f"     (found by: {links(hub_home)['links'][0]['moved'][-1]['how']})")

        print("3. stopped, and back")
        # the hub's watch must have seen it answering first, or stopping it is no change to see
        wait_for("the hub's watch sees the Pi answering",
                 lambda: any(t.get("answering") for t in api(HUB, "/api/network/ties")["ties"]), 150)
        pi.terminate()
        pi.wait(20)
        wait_for("Events says it stopped answering",
                 lambda: any(e["event"] == "offline" for e in events(HUB)), 200)
        down_at = max(e["at"] for e in events(HUB) if e["event"] == "offline")
        pi = start(pi_home, PI, "pi")
        wait_for("Events says it is answering again",
                 lambda: any(e["event"] == "online" and e["at"] > down_at for e in events(HUB)), 150)
        print("\nEvents on the hub:")
        for e in events(HUB)[:10]:
            print(f"  {time.strftime('%H:%M:%S', time.localtime(e['at']))}  {e['text']}")
    finally:
        for p in (hub, pi):
            p.terminate()
        for p in (hub, pi):
            try:
                p.wait(20)
            except subprocess.TimeoutExpired:
                p.kill()
    print("\nFINDINGS", FINDINGS)
    if not FINDINGS and not os.environ.get("KEEP"):
        shutil.rmtree(base, ignore_errors=True)       # KEEP=1 keeps the homes, for screenshots
    return 1 if FINDINGS else 0


if __name__ == "__main__":
    sys.exit(main())
