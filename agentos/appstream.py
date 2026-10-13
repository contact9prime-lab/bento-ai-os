"""Native apps projected into a Bento window: a real program, drawn here, steered from here.

A remote browser could never see a native window: the compositor draws it on the host's
own screen (docs/remote-access.md). Host Screen streams the WHOLE screen over VNC. This
streams ONE app into ONE Bento window, from a phone or a laptop in another room, and the
agent can look at it and use it through the gate like any other window.

Each app gets its own nested, headless display, so it never needs the host's screen, a
portal consent dialog or a GPU:

- **wayland**: `sway` on the headless wlroots backend with the pixman renderer, the app
  started inside it (`exec`), frames by `grim`, the pointer by `swaymsg seat … cursor`,
  keys by `wtype`. XWayland comes along when it is installed, so X11 apps run too.
- **x11**: `Xvfb`, frames by `ffmpeg -f x11grab` as an MJPEG stream, input by `xdotool`.

Why not waypipe or PipeWire: waypipe forwards a Wayland app to ANOTHER compositor (it is
the transport for running an app on a different machine, and the nested compositor here
is what it would need on this side anyway); PipeWire screen capture goes through the
desktop portal, which asks the person to pick a window every time and does not exist on a
headless box. Both are noted in `status()` so the answer is a sentence, not silence.

Rules:

- **Installed apps only**, by their desktop-entry id (`host.list_apps`), as the launcher
  already does. A free command line is a shell, and the Terminal is where a shell lives.
- **Each display is private**: its sockets live in a 0700 runtime folder of its own, so
  another local user cannot connect to the app's display and read or type into it.
- **Bounded**: `MAX_STREAMS` per person, a frame rate cap, and a stream nobody watches for
  `IDLE_S` is ended (the app with it: it was started for this window).
- **The agent's hand is drawn** in the window like the browser's (`agent` events).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path

MAX_STREAMS = 4
FPS = 8
IDLE_S = 30 * 60
SIZE = (1280, 800)
MIN_SIZE, MAX_SIZE = (320, 240), (2560, 1600)
NEED = {"wayland": ("sway", "swaymsg", "grim", "wtype"), "x11": ("Xvfb", "xdotool", "ffmpeg")}
KEYNAMES = {"Enter": ("Return", "Return"), "Tab": ("Tab", "Tab"), "Escape": ("Escape", "Escape"),
            "Backspace": ("BackSpace", "BackSpace"), "Delete": ("Delete", "Delete"),
            "ArrowUp": ("Up", "Up"), "ArrowDown": ("Down", "Down"), "ArrowLeft": ("Left", "Left"),
            "ArrowRight": ("Right", "Right"), "Home": ("Home", "Home"), "End": ("End", "End"),
            "PageUp": ("Prior", "Page_Up"), "PageDown": ("Next", "Page_Down"), " ": ("space", "space")}


def _ffmpeg() -> str:
    return os.environ.get("AGENTOS_FFMPEG") or shutil.which("ffmpeg") or ""


def _have(tool: str) -> bool:
    return bool(_ffmpeg()) if tool == "ffmpeg" else bool(shutil.which(tool))


def status() -> dict:
    """Which backend can run here, or why none can and what to install."""
    if not sys_ok():
        return {"ok": False, "backend": "", "missing": [],
                "why": "Projecting native apps into a window works on Linux.",
                "notes": ""}
    # X11 first: nearly every app (GTK, Qt, Electron, xterm) can draw on X11, while a
    # nested Wayland display shows X11-only apps only when Xwayland is installed
    for b in ("x11", "wayland"):
        if all(_have(t) for t in NEED[b]):
            return {"ok": True, "backend": b, "missing": [], "why": "", "notes": _notes()}
    miss_w = [t for t in NEED["wayland"] if not _have(t)]
    miss_x = [t for t in NEED["x11"] if not _have(t)]
    miss = miss_w if len(miss_w) <= len(miss_x) else miss_x
    comp = sorted({COMPONENT.get(t, t) for t in miss})
    return {"ok": False, "backend": "", "missing": miss, "components": comp,
            "why": f"To show a native app inside a window, install {', '.join(miss)}.",
            "notes": _notes()}


#: which component offer (components.py) brings each missing tool
COMPONENT = {"Xvfb": "app-windows", "xdotool": "app-windows", "ffmpeg": "ffmpeg",
             "sway": "compositor", "swaymsg": "compositor", "grim": "grim", "wtype": "wtype"}


def sys_ok() -> bool:
    import sys
    return sys.platform.startswith("linux")


def _notes() -> str:
    return ("Each app runs in its own headless display. waypipe and PipeWire are not used: "
            "waypipe needs a compositor on this side anyway, and PipeWire capture asks you to "
            "pick a window through a portal every time.")


async def _run(*argv, env=None, timeout: float = 5.0, data: bytes | None = None) -> tuple[int, bytes]:
    p = await asyncio.create_subprocess_exec(*argv, env=env, stdin=asyncio.subprocess.PIPE if data else None,
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(p.communicate(data), timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            p.kill()
        return -1, b""
    return p.returncode or 0, out or b""


class Stream:
    def __init__(self, uid: str, sid: str, title: str, argv: list[str], backend: str, size=SIZE):
        self.uid, self.id, self.title, self.argv, self.backend = uid or "", sid, title, argv, backend
        self.size = tuple(size)
        self.dir = Path(tempfile.mkdtemp(prefix="bento-app-"))
        os.chmod(self.dir, 0o700)
        self.procs: list = []
        self.viewers: dict[int, dict] = {}
        self._vid = 0
        self.task = None
        self.alive = False
        self.started = self.last_seen = time.time()
        self.env: dict = {}
        self.last_frame = b""
        self.grim_fmt = "jpeg"

    # -- life --
    async def start(self):
        w, h = self.size
        base = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY", "SWAYSOCK")}
        if self.backend == "wayland":
            conf = self.dir / "sway.conf"
            conf.write_text(
                f"output HEADLESS-1 resolution {w}x{h} position 0 0\n"
                "default_border none\ndefault_floating_border none\nfocus_follows_mouse no\n"
                "seat * hide_cursor 0\nxwayland enable\n"
                f"for_window [all] fullscreen enable\n")
            env = {**base, "XDG_RUNTIME_DIR": str(self.dir), "WLR_BACKENDS": "headless",
                   "WLR_LIBINPUT_NO_DEVICES": "1", "WLR_RENDERER": "pixman",
                   "SWAYSOCK": str(self.dir / "sway.sock")}
            self.procs.append(await asyncio.create_subprocess_exec(
                "sway", "-c", str(conf), env=env, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True))
            for _ in range(60):
                await asyncio.sleep(0.1)
                sock = next(iter(sorted(self.dir.glob("wayland-*[0-9]"))), None)
                if sock and (self.dir / "sway.sock").exists():
                    break
            else:
                await self.stop()
                raise RuntimeError("the nested display did not start (sway)")
            self.env = {**env, "WAYLAND_DISPLAY": sock.name, "GDK_BACKEND": "wayland,x11",
                        "QT_QPA_PLATFORM": "wayland;xcb", "MOZ_ENABLE_WAYLAND": "1"}
            self.env.pop("WLR_BACKENDS", None)
            self.env.pop("WLR_RENDERER", None)
            # the app, inside the nested display (never on the host's own screen)
            await _run("swaymsg", "exec", " ".join(_q(a) for a in self.argv), env=self.env)
        else:
            disp = self._free_display()
            self.procs.append(await asyncio.create_subprocess_exec(
                "Xvfb", disp, "-screen", "0", f"{w}x{h}x24", "-nolisten", "tcp",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True))
            await asyncio.sleep(0.6)
            self.env = {**base, "DISPLAY": disp}
            self.procs.append(await asyncio.create_subprocess_exec(
                *self.argv, env=self.env, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True))
        self.alive = True
        self.task = asyncio.create_task(self._frames())
        if self.backend == "x11":
            self.fit_task = asyncio.create_task(self._x11_fit())

    async def _x11_fit(self):
        """A bare Xvfb has no window manager, so nobody sizes or focuses the app: an xterm
        came up 80x24 in a corner and typing went to the root window. Fill the display with
        each top-level window the app opens, and give it the keyboard. Checked for a while
        after start, since an app may open its window late or open a second one."""
        w, h = self.size
        done: set[str] = set()
        for _ in range(20):
            if not self.alive:
                return
            await asyncio.sleep(0.5 if not done else 2)
            _, out = await _run("xdotool", "search", "--onlyvisible", "--maxdepth", "1", "--name", "", env=self.env)
            for wid in out.decode(errors="replace").split():
                if wid in done:
                    continue
                done.add(wid)
                await _run("xdotool", "windowmove", wid, "0", "0", "windowsize", wid, str(w), str(h),
                           "windowfocus", wid, env=self.env)

    def _free_display(self) -> str:
        for n in range(80, 160):
            if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not os.path.exists(f"/tmp/.X{n}-lock"):
                return f":{n}"
        raise RuntimeError("no free X display number")

    async def stop(self):
        self.alive = False
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
        for p in reversed(self.procs):
            if p.returncode is None:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(p.pid, signal.SIGTERM)
        await asyncio.sleep(0.3)
        for p in self.procs:
            if p.returncode is None:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(p.pid, signal.SIGKILL)
        shutil.rmtree(self.dir, ignore_errors=True)
        await self._tell({"type": "ended"})

    # -- frames --
    async def _frames(self):
        try:
            if self.backend == "x11":
                await self._x11_frames()
            else:
                while self.alive:
                    t0 = time.time()
                    if self.viewers:
                        frame = await self.grab()
                        if frame:
                            self._push(frame)
                    elif time.time() - self.last_seen > IDLE_S:
                        return await self.stop()
                    await asyncio.sleep(max(0.02, 1 / FPS - (time.time() - t0)))
        except asyncio.CancelledError:
            pass

    async def grab(self) -> bytes:
        if self.backend == "wayland":
            # some grim builds have no JPEG; PNG at the fastest compression is the fallback
            args = ["-t", "jpeg", "-q", "70"] if self.grim_fmt == "jpeg" else ["-t", "png", "-l", "1"]
            rc, out = await _run("grim", *args, "-", env=self.env, timeout=4)
            if rc != 0 and self.grim_fmt == "jpeg":
                self.grim_fmt = "png"
                return await self.grab()
            return out if rc == 0 else b""
        return self.last_frame

    async def _x11_frames(self):
        w, h = self.size
        p = await asyncio.create_subprocess_exec(
            _ffmpeg(), "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "1", "-framerate", str(FPS),
            "-video_size", f"{w}x{h}", "-i", self.env["DISPLAY"], "-f", "mjpeg", "-q:v", "6", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        buf = b""
        while self.alive:
            chunk = await p.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                s = buf.find(b"\xff\xd8")
                e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                if s < 0 or e < 0:
                    break
                self.last_frame = buf[s:e + 2]
                buf = buf[e + 2:]
                if self.viewers:
                    self._push(self.last_frame)
            if not self.viewers and time.time() - self.last_seen > IDLE_S:
                return await self.stop()

    def _push(self, frame: bytes):
        for v in list(self.viewers.values()):
            v["frame"] = frame
            if not v["busy"]:
                asyncio.create_task(self._flush(v))

    async def _flush(self, v):
        v["busy"] = True
        try:
            while v["frame"] is not None:
                f, v["frame"] = v["frame"], None
                await v["bytes"](f)
        except Exception:
            pass
        finally:
            v["busy"] = False

    async def _tell(self, msg: dict):
        for v in list(self.viewers.values()):
            with contextlib.suppress(Exception):
                await v["json"](msg)

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "backend": self.backend, "alive": self.alive,
                "watching": len(self.viewers), "size": list(self.size), "started": self.started}

    # -- viewers --
    async def add_viewer(self, send_bytes, send_json) -> int:
        self._vid += 1
        self.viewers[self._vid] = {"bytes": send_bytes, "json": send_json, "frame": None, "busy": False}
        self.last_seen = time.time()
        await send_json({"type": "state", **self.summary()})
        return self._vid

    def drop_viewer(self, vid: int):
        self.viewers.pop(vid, None)
        self.last_seen = time.time()

    # -- input: the person's and the agent's --
    async def person(self, op: dict):
        self.last_seen = time.time()
        k = op.get("type")
        if k == "mouse":
            x, y = int(op.get("x", 0)), int(op.get("y", 0))
            kind = op.get("kind")
            btn = {"left": 1, "middle": 2, "right": 3}.get(op.get("button") or "left", 1)
            if kind == "mouseMoved":
                await self.move(x, y)
            elif kind == "mousePressed":
                await self.move(x, y)
                await self.button(btn, True)
            elif kind == "mouseReleased":
                await self.button(btn, False)
        elif k == "wheel":
            await self.scroll(float(op.get("dy", 0)))
        elif k == "key":
            await self.key(str(op.get("key") or ""), int(op.get("mods") or 0))
        elif k == "text":
            await self.type(str(op.get("text") or "")[:2000])

    async def move(self, x: int, y: int):
        if self.backend == "wayland":
            await _run("swaymsg", "seat", "-", "cursor", "set", str(x), str(y), env=self.env)
        else:
            await _run("xdotool", "mousemove", str(x), str(y), env=self.env)

    async def button(self, btn: int, down: bool):
        if self.backend == "wayland":
            await _run("swaymsg", "seat", "-", "cursor", "press" if down else "release",
                       f"button{btn}", env=self.env)
        else:
            await _run("xdotool", "mousedown" if down else "mouseup", str(btn), env=self.env)

    async def click(self, x: int, y: int, btn: int = 1):
        await self.move(x, y)
        await self.button(btn, True)
        await self.button(btn, False)

    async def scroll(self, dy: float):
        n = max(1, min(10, int(abs(dy) // 60) or 1))
        btn = 5 if dy > 0 else 4
        for _ in range(n):
            if self.backend == "wayland":
                await _run("swaymsg", "seat", "-", "cursor", "press", f"button{btn}", env=self.env)
                await _run("swaymsg", "seat", "-", "cursor", "release", f"button{btn}", env=self.env)
            else:
                await _run("xdotool", "click", str(btn), env=self.env)

    async def type(self, text: str):
        if not text:
            return
        if self.backend == "wayland":
            await _run("wtype", "-s", "60", "--", text, env=self.env, timeout=10)
        else:
            # xdotool remaps a spare keycode per character; on a bare Xvfb a short delay
            # drops characters while the keymap settles (measured: most of a line lost at 8 ms)
            await _run("xdotool", "type", "--clearmodifiers", "--delay", "35", "--", text, env=self.env,
                       timeout=max(10, len(text) * 0.08))

    async def key(self, key: str, mods: int = 0):
        names = KEYNAMES.get(key)
        mod = [m for bit, m in ((2, "ctrl"), (1, "alt"), (8, "shift"), (4, "super")) if mods & bit]
        if self.backend == "wayland":
            # each wtype is a new virtual keyboard, and the compositor can drop its first
            # event while the keymap loads: a short pause first (measured: Enter was lost)
            argv = ["wtype", "-s", "60"]
            for m in mod:
                argv += ["-M", m if m != "super" else "logo"]
            if names:
                argv += ["-k", names[0]]
            elif len(key) == 1:
                argv += [key]
            else:
                return
            for m in reversed(mod):
                argv += ["-m", m if m != "super" else "logo"]
            await _run(*argv, env=self.env)
        else:
            k = names[1] if names else (key if len(key) == 1 else "")
            if not k:
                return
            await _run("xdotool", "key", "+".join(mod + [k]), env=self.env)

    async def agent_hand(self, kind: str, who: str, x=None, y=None, label: str = "", text: str = ""):
        await self._tell({"type": "agent", "kind": kind, "who": who, "x": x, "y": y,
                          "label": label, "text": text})


def _q(a: str) -> str:
    import shlex
    return shlex.quote(a)


_STREAMS: dict[str, dict[str, Stream]] = {}
_N = [0]


def streams(uid: str) -> list[Stream]:
    per = _STREAMS.get(uid or "", {})
    for k, s in list(per.items()):
        if not s.alive:
            per.pop(k, None)
    return sorted(per.values(), key=lambda s: s.started)


def get(uid: str, sid: str) -> Stream | None:
    ss = streams(uid)
    if not sid:
        return ss[-1] if ss else None
    k = str(sid).lower()
    return next((s for s in ss if s.id == sid or s.title.lower() == k), None)


def resolve(app: str) -> tuple[str, list[str]]:
    """An installed app's (name, argv) by desktop-entry id or by its name."""
    import shlex
    from . import host
    want = str(app or "").strip().lower()
    for a in host.list_apps():
        if want in (str(a.get("id", "")).lower(), str(a.get("name", "")).lower()):
            argv = shlex.split(a.get("exec") or "")
            if argv:
                return a.get("name") or a["id"], argv
    raise RuntimeError(f"no installed app called '{app}'; the Apps launcher lists them")


async def open_app(uid: str, app: str, size=SIZE, argv: list[str] | None = None, title: str = "") -> Stream:
    st = status()
    if not st["ok"]:
        raise RuntimeError(st["why"])
    if len(streams(uid)) >= MAX_STREAMS:
        raise RuntimeError(f"{MAX_STREAMS} apps are already open in windows; close one first")
    if argv is None:
        title, argv = resolve(app)
    w = max(MIN_SIZE[0], min(MAX_SIZE[0], int(size[0]))) // 2 * 2
    h = max(MIN_SIZE[1], min(MAX_SIZE[1], int(size[1]))) // 2 * 2
    _N[0] += 1
    s = Stream(uid, f"a{_N[0]}{int(time.time()) % 10000}", title or app, argv, st["backend"], (w, h))
    await s.start()
    _STREAMS.setdefault(uid or "", {})[s.id] = s
    return s


async def stop_all():
    for per in list(_STREAMS.values()):
        for s in list(per.values()):
            with contextlib.suppress(Exception):
                await s.stop()
    _STREAMS.clear()
