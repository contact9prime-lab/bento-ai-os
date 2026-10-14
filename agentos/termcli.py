"""`bento terminal`, `bento browser` and `bento windows`: the live windows from a terminal.

The three kinds of live window (ptyhub sessions, the shared browser, native apps in a
window) are held by the running server, so these verbs talk to it on loopback, signing in
first on a machine with accounts, the way the TUI does. The useful one over SSH is
`bento terminal attach`: the same session the desktop's Terminal window shows, with the
same scrollback, so a build started on the desktop can be watched from a phone's SSH app
and the agent's typing is seen in both places. Ctrl+] detaches and leaves it running.

The browser and app windows are pictures, so a terminal can list them, end them and say
where they are, but not draw them: that is said rather than left as a gap.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

DETACH = b"\x1d"   # Ctrl+]


def _base(cfg: dict) -> str:
    return f"http://127.0.0.1:{cfg.get('port', 8321)}"


def _login(base: str) -> dict:
    """Headers for the running server: none on a machine without accounts, else a signed
    cookie from a name and password typed here. {} with 'error' when it is not running."""
    import httpx
    from .remote import COOKIE
    try:
        who = httpx.get(base + "/api/users/who", timeout=4).json()
    except Exception:
        return {"error": "AgentOS is not running here. Start it with `bento serve`."}
    if not who.get("any"):
        return {}
    import getpass
    for _ in range(3):
        try:
            name = input("  name: ").strip()
            pw = getpass.getpass("  password: ")
        except (EOFError, KeyboardInterrupt):
            return {"error": "not signed in"}
        r = httpx.post(base + "/api/users/login", json={"name": name, "password": pw}, timeout=8)
        tok = r.cookies.get(COOKIE) if r.status_code == 200 else ""
        if tok:
            return {"Cookie": f"{COOKIE}={tok}"}
        print("  " + ((r.json() if r.content else {}).get("error") or "that did not work"))
    return {"error": "not signed in"}


def _get(base, hdrs, path, method="GET"):
    import httpx
    r = httpx.request(method, base + path, headers=hdrs, timeout=10)
    try:
        return r.json()
    except ValueError:
        return {"error": f"HTTP {r.status_code}"}


def _ago(t: float) -> str:
    s = max(0, int(time.time() - (t or 0)))
    return f"{s}s" if s < 60 else f"{s // 60}m" if s < 3600 else f"{s // 3600}h"


def terminal_cli(args) -> int:
    from . import config as cfgmod
    cfg = cfgmod.load_config()
    base = _base(cfg)
    hdrs = _login(base)
    if "error" in hdrs:
        print(hdrs["error"])
        return 1
    act = args.action or "list"
    if act == "list":
        d = _get(base, hdrs, "/api/terminal/sessions")
        if d.get("error"):
            print(d["error"])
            return 1
        ss = d.get("sessions") or []
        if not ss:
            print("  no terminal sessions. `bento terminal attach new` starts one.")
        for s in ss:
            fg = s.get("foreground") or "shell"
            print(f"  {s['id']:<14} {s['name'][:24]:<24} by {s.get('by', 'you'):<6} "
                  f"{'running ' + fg:<20} {s.get('watching', 0)} watching, last output {_ago(s.get('last_out'))} ago")
        return 0
    if act == "end":
        if not args.id:
            print("which session? (bento terminal list)")
            return 2
        d = _get(base, hdrs, f"/api/terminal/sessions/{args.id}", "DELETE")
        print("  ended" if d.get("ok") else "  " + (d.get("error") or "could not end it"))
        return 0 if d.get("ok") else 1
    if act == "attach":
        if not sys.stdin.isatty():
            print("attach needs a real terminal (an SSH session or a shell).")
            return 2
        return asyncio.run(_attach(base, hdrs, args.id or ""))
    print("bento terminal list | attach [id|name|new] | end <id>")
    return 2


async def _attach(base: str, hdrs: dict, want: str) -> int:
    import termios
    import tty

    import websockets
    from urllib.parse import quote
    url = base.replace("http://", "ws://") + "/ws/terminal?session=" + quote(want or _newest(base, hdrs))
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    loop = asyncio.get_running_loop()
    out = sys.stdout.buffer
    done = asyncio.Event()
    async with websockets.connect(url, max_size=None, additional_headers=hdrs or None) as ws:
        cols, rows = os.get_terminal_size()
        await ws.send(json.dumps({"type": "resize", "cols": cols, "rows": rows}))
        tty.setraw(fd)

        def keys():
            data = os.read(fd, 4096)
            if not data or DETACH in data:
                done.set()
                return
            asyncio.ensure_future(ws.send(json.dumps({"type": "input", "data": data.decode("utf-8", "replace")})))
        loop.add_reader(fd, keys)

        async def screen():
            try:
                async for msg in ws:
                    if isinstance(msg, str) and msg.startswith("\x00"):
                        m = json.loads(msg[1:])
                        if m.get("type") == "session":
                            out.write(f"\x1b[90m[attached to {m.get('name')}, Ctrl+] leaves it running]\x1b[0m\r\n".encode())
                        elif m.get("type") == "agent":
                            out.write(f"\x1b[90m[your agent typed: {m.get('text', '')[:80]}]\x1b[0m\r\n".encode())
                    else:
                        out.write(msg.encode() if isinstance(msg, str) else msg)
                    out.flush()
            finally:
                done.set()
        task = asyncio.create_task(screen())
        try:
            await done.wait()
        finally:
            loop.remove_reader(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            task.cancel()
    print("\r\ndetached; the session is still running (bento terminal list)")
    return 0


def _newest(base, hdrs) -> str:
    ss = (_get(base, hdrs, "/api/terminal/sessions").get("sessions") or [])
    return ss[-1]["id"] if ss else "new"


def windows_cli(args) -> int:
    """`bento windows`: every live window, and `bento windows end <id>` for an app."""
    from . import config as cfgmod
    cfg = cfgmod.load_config()
    base = _base(cfg)
    hdrs = _login(base)
    if "error" in hdrs:
        print(hdrs["error"])
        return 1
    if (args.action or "list") == "end":
        if not args.id:
            print("which one? (bento windows)")
            return 2
        path = (f"/api/terminal/sessions/{args.id}" if args.id.startswith("t")
                else f"/api/appstreams/{args.id}")
        d = _get(base, hdrs, path, "DELETE")
        print("  closed" if d.get("ok") else "  " + (d.get("error") or "could not close it"))
        return 0 if d.get("ok") else 1
    b = _get(base, hdrs, "/api/browser")
    print("Browser")
    if not b.get("ok", True) and b.get("why"):
        print("  " + b["why"])
    elif b.get("running"):
        st = b.get("state") or {}
        for t in st.get("tabs") or []:
            mark = "›" if t.get("active") else " "
            print(f"  {mark} {(t.get('title') or '')[:40]:<40} {t.get('url', '')[:60]}")
        if st.get("attention"):
            a = st["attention"]
            print(f"  needs you on {a.get('site') or 'a page'}: {a.get('reason') or a.get('kind')}. "
                  "Open Web on the desktop or a phone to answer it.")
    else:
        print("  not open. It starts when you or your agent opens a page.")
    print("Terminal sessions")
    ss = _get(base, hdrs, "/api/terminal/sessions").get("sessions") or []
    for s in ss:
        print(f"  {s['id']:<14} {s['name'][:24]:<24} {('running ' + s['foreground']) if s.get('foreground') else 'shell'}")
    if not ss:
        print("  none")
    print("Apps in windows")
    a = _get(base, hdrs, "/api/appstreams")
    if not a.get("ok") and a.get("why"):
        print("  " + a["why"])
    for s in a.get("streams") or []:
        print(f"  {s['id']:<14} {s.get('title', '')[:30]:<30} {s.get('backend', '')}")
    if a.get("ok") and not a.get("streams"):
        print("  none")
    print("A browser page or an app is a picture: open it on the desktop or a phone to see it.")
    return 0
