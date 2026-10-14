"""Terminal sessions that outlive their window, shared by the person and the agent.

The Terminal used to be a shell that lived exactly as long as its window: close it and the
build you were watching died. Here a session is a real pseudo-terminal held by the server.
A window attaches to it (and gets the screen so far), closing the window detaches, and
opening the Terminal again reattaches, like tmux without tmux. The agent reads the same
session (`terminal_read`) and types into it (`terminal_send`) through the gate, so "look
at the error in my terminal" and "start the dev server and keep it running" are things it
can actually do, in the shell the person is watching.

Four rules:

- **The session's process is the Terminal's.** The server decides the argv (and on a
  machine with accounts, the per-account jail) exactly as the Terminal always did; this
  module only holds the fd. A session the agent starts is the same kind of shell.
- **Typing into a shell is a command, and is judged like one** (tools.risk_of): safe
  only when the shell itself is in the foreground (no editor, no ssh, no REPL) and the
  line is read-only by the shell classifier. Anything else asks, and the card says
  what is running in the foreground.
- **Bounded.** `MAX_SESSIONS` per person; `SCROLLBACK` bytes kept per session; a session
  nobody has watched for `DETACHED_TTL` is ended. Ending is SIGHUP to the shell, as
  closing a terminal emulator does.
- **Per person.** Sessions are keyed by account; a person only lists and attaches to
  their own.

Linux and macOS (pty). Windows has no pty module; `available()` says so.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import signal
import time

MAX_SESSIONS = 8
SCROLLBACK = 256 * 1024
DETACHED_TTL = 24 * 3600
READ_LINES, READ_MAX = 40, 400
SHELLS = {"bash", "sh", "zsh", "fish", "dash", "ksh", "mksh", "ash", "tcsh", "csh"}

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[@-Z\\-_]|\r")


def available() -> str:
    """'' when sessions can run here, else why not."""
    if os.name == "nt":
        return "Terminal sessions need a pseudo-terminal, which Windows does not have here."
    try:
        import pty  # noqa: F401
    except ImportError:
        return "This Python has no pty module."
    return ""


class Session:
    def __init__(self, uid: str, sid: str, name: str, pid: int, fd: int, by: str):
        self.uid, self.id, self.name, self.pid, self.fd, self.by = uid, sid, name, pid, fd, by
        self.buf = bytearray()
        self.subs: dict[int, object] = {}
        self._sub = 0
        self.started = self.last_seen = self.last_out = time.time()
        self.alive = True
        self.cols, self.rows = 80, 24

    # -- what is on the screen --
    def _out(self, data: bytes):
        self.last_out = time.time()
        self.buf += data
        if len(self.buf) > SCROLLBACK:
            del self.buf[:len(self.buf) - SCROLLBACK]
        for send in list(self.subs.values()):
            asyncio.ensure_future(_safe(send, data))

    def tail(self, lines: int = READ_LINES) -> str:
        """The last lines of the screen as plain text (escape codes removed)."""
        text = _ANSI.sub("", self.buf.decode("utf-8", "replace"))
        rows = [r.rstrip() for r in text.split("\n")]
        while rows and not rows[-1]:
            rows.pop()
        return "\n".join(rows[-max(1, min(READ_MAX, int(lines or READ_LINES))):])

    def foreground(self) -> str:
        """What is in the foreground: '' when it is the shell itself, else the program's
        name (vim, ssh, python…), read from the terminal's foreground process group."""
        if not self.alive:
            return "(ended)"
        try:
            fg = os.tcgetpgrp(self.fd)
            if fg == os.getpgid(self.pid):
                return ""
        except (OSError, ValueError):
            return "a program"      # cannot tell: never claim it is the shell
        try:
            with open(f"/proc/{fg}/comm") as f:
                name = f.read().strip()
        except OSError:
            name = _ps_comm(fg)     # macOS has no /proc
            if not name:
                return "a program"
        # inside the per-account jail the shell is bwrap's child, in its own process group,
        # so an idle prompt is a foreground "bash": a shell at its prompt is still the shell
        return "" if name in SHELLS else (name or "a program")

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "by": self.by, "alive": self.alive,
                "watching": len(self.subs), "started": self.started, "last_out": self.last_out,
                "foreground": self.foreground()}

    # -- input --
    def write(self, data: str):
        if self.alive:
            os.write(self.fd, data.encode())

    def resize(self, cols: int, rows: int):
        import fcntl
        import struct
        import termios
        self.cols, self.rows = max(10, int(cols)), max(3, int(rows))
        with contextlib.suppress(OSError):
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))

    def note(self, msg: dict):
        """A control message to every window on this session (the agent's hand): a leading
        NUL marks it as control, never screen output."""
        import json as _json
        data = ("\x00" + _json.dumps(msg)).encode()
        for send in list(self.subs.values()):
            asyncio.ensure_future(_safe(send, data))

    # -- watchers --
    def attach(self, send) -> int:
        self._sub += 1
        self.subs[self._sub] = send
        self.last_seen = time.time()
        return self._sub

    def detach(self, sub: int):
        self.subs.pop(sub, None)
        self.last_seen = time.time()

    def end(self):
        if self.alive:
            with contextlib.suppress(ProcessLookupError):
                os.kill(self.pid, signal.SIGHUP)
        self._closed()

    def _closed(self):
        if not self.alive:
            return
        self.alive = False
        with contextlib.suppress(Exception):
            asyncio.get_event_loop().remove_reader(self.fd)
        with contextlib.suppress(OSError):
            os.close(self.fd)
        with contextlib.suppress(ChildProcessError, OSError):
            os.waitpid(self.pid, os.WNOHANG)
        for send in list(self.subs.values()):
            asyncio.ensure_future(_safe(send, b"\r\n\x1b[90m[this session has ended]\x1b[0m\r\n"))


def _ps_comm(pid: int) -> str:
    import subprocess
    try:
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True,
                             text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return os.path.basename(out.lstrip("-"))


async def _safe(send, data):
    with contextlib.suppress(Exception):
        await send(data)


_SESSIONS: dict[str, dict[str, Session]] = {}   # uid -> id -> Session
_N: dict[str, int] = {}


def sessions(uid: str) -> list[Session]:
    _sweep(uid)
    return sorted(_SESSIONS.get(uid or "", {}).values(), key=lambda s: s.started)


def get(uid: str, key: str) -> Session | None:
    """A session by id or by name (case-insensitive), or the newest one for ''."""
    ss = sessions(uid)
    if not key:
        return ss[-1] if ss else None
    k = str(key).strip().lower()
    return next((s for s in ss if s.id == key or s.name.lower() == k), None)


def _sweep(uid: str):
    now = time.time()
    for sid, s in list(_SESSIONS.get(uid or "", {}).items()):
        if not s.alive or (not s.subs and now - s.last_seen > DETACHED_TTL):
            s.end()
            _SESSIONS[uid or ""].pop(sid, None)


def spawn(uid: str, argv: list[str], cwd: str = "", env: dict | None = None,
          name: str = "", by: str = "you") -> Session:
    """Start a shell on a new pseudo-terminal and hold it. `argv` is the Terminal's own
    (the server decides it, jail included)."""
    why = available()
    if why:
        raise RuntimeError(why)
    uid = uid or ""
    if len(sessions(uid)) >= MAX_SESSIONS:
        raise RuntimeError(f"{MAX_SESSIONS} terminal sessions are already running; end one first")
    import pty
    pid, fd = pty.fork()
    if pid == 0:   # the child: become the shell
        e = dict(env or os.environ)
        e["TERM"] = "xterm-256color"
        with contextlib.suppress(OSError):
            if cwd:
                os.chdir(cwd)
        try:
            os.execvpe(argv[0], argv, e)
        finally:
            os._exit(127)
    _N[uid] = _N.get(uid, 0) + 1
    sid = f"t{int(time.time() * 1000) % 10 ** 8:x}{_N[uid]}"
    s = Session(uid, sid, name or ("Terminal " + str(_N[uid])), pid, fd, by)
    _SESSIONS.setdefault(uid, {})[sid] = s
    loop = asyncio.get_event_loop()

    def readable():
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        if data:
            s._out(data)
        else:
            s._closed()
    loop.add_reader(fd, readable)
    s.resize(120, 32)
    return s


def end_all():
    for per in _SESSIONS.values():
        for s in list(per.values()):
            s.end()
    _SESSIONS.clear()
