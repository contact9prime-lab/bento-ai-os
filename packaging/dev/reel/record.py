"""Record a remove-and-reinstall of a machine with Bento's own commands, for a reel.

Runs `bento network remove`, then `bento network install`, then `bento network controls`
against a real machine, and keeps every line each command prints with its time
(lines.jsonl), plus that machine's own screen every few seconds (pi/NNNN.png, through
`grim` over this computer's SSH key). Nothing here decides anything: it only runs the CLI
and watches. render.py turns the folder into a 9:16 video.

    python packaging/dev/reel/record.py OUT_DIR HOST [--user pi] [--agent-name "Mr. Pi"]

AGENTOS_INSTALL_URL in the environment is passed on (to install a branch's installer).
Kept in the repo because a scratch copy was lost with /tmp after a restart.
"""
import argparse
import json
import os
import pty
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
GRAB = ('export XDG_RUNTIME_DIR=/run/user/$(id -u); W=$(ls $XDG_RUNTIME_DIR | grep -m1 "^wayland-[0-9]$"); '
        'WAYLAND_DISPLAY=$W grim -s 0.5 -t png -')      # some grim builds have no JPEG


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("host")
    ap.add_argument("--user", default="pi")
    ap.add_argument("--agent-name", default="Mr. Pi")
    ap.add_argument("--every", type=float, default=8.0, help="seconds between screen grabs")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "pi").mkdir(parents=True, exist_ok=True)
    home = Path(os.environ.get("AGENTOS_HOME") or Path.home() / ".agentos")
    key, kh = home / "pki" / "ssh_ed25519", home / "pki" / "known_hosts"
    t0 = time.time()
    log = open(out / "lines.jsonl", "w")
    stop = threading.Event()

    def note(kind, text):
        log.write(json.dumps({"t": round(time.time() - t0, 2), "kind": kind, "text": text}) + "\n")
        log.flush()

    def grab():
        n = 0
        while not stop.is_set():
            try:
                png = subprocess.run(["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                                      "-o", f"UserKnownHostsFile={kh}", f"{a.user}@{a.host}", GRAB],
                                     capture_output=True, timeout=20).stdout
                if len(png) > 2000:
                    n += 1
                    (out / "pi" / f"{n:04d}.png").write_bytes(png)
                    note("pi", f"{n:04d}.png")
            except Exception:
                pass
            stop.wait(a.every)

    def run(argv):
        note("cmd", "$ bento " + " ".join(argv))
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(REPO)
            os.execvp("uv", ["uv", "run", "bento", *argv])
        buf = b""
        while True:
            try:
                d = os.read(fd, 4096)
            except OSError:
                break
            if not d:
                break
            buf += d
            while b"\n" in buf:
                ln, buf = buf.split(b"\n", 1)
                # a terminal ends lines with \r\n, and a progress bar redraws with \r: keep the
                # last part that says something (taking the last part blindly dropped every line)
                parts = ANSI.sub("", ln.decode(errors="replace")).split("\r")
                t = next((x for x in reversed(parts) if x.strip()), "").rstrip()
                if t.strip() and "VIRTUAL_ENV" not in t:     # uv's note about this shell, not Bento's
                    note("out", t)
                    print(t, flush=True)
        _, st = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(st)
        note("exit", str(code))
        return code

    th = threading.Thread(target=grab, daemon=True)
    th.start()
    net = ["network"]
    if run(net + ["remove", a.host, "--user", a.user, "--key-only", "--yes"]) != 0:
        stop.set()
        note("end", "remove failed")
        sys.exit(1)
    time.sleep(10)
    run(net + ["install", a.host, "--user", a.user, "--key-only", "--kiosk", "--agent-name", a.agent_name, "--yes"])
    for _ in range(36):                       # the hub sets it up when it hears it
        got = subprocess.run(["uv", "run", "bento", *net, "controls", a.host, "--user", a.user, "--key-only"],
                             cwd=REPO, capture_output=True, text=True).stdout
        if "running: on" in got:
            break
        time.sleep(10)
    time.sleep(40)
    run(net + ["controls", a.host, "--user", a.user, "--key-only"])
    time.sleep(20)
    stop.set()
    th.join(30)
    note("end", "")


if __name__ == "__main__":
    main()
