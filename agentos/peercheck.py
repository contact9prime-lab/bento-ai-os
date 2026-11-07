"""Is this loopback connection a process this server started?

Loopback used to mean "the person". It does not, because the agent's own commands run on this
machine and the jail keeps its network (agents need curl, pip and git): `curl 127.0.0.1:8321/api/grants`
from a jailed shell arrived as the person, wrote a grant recorded as the person's, and could answer its
own approval card. So every trust given to a loopback connection first asks here who is at the other end.

How it answers, on Linux: ask the kernel for the client's half of the connection (sock_diag, or the
/proc/net/tcp row where that is not available), which gives the socket's owner uid and its inode, then look for that inode among the file descriptors of this
server's descendants. Six things are load-bearing, and each is an attack somebody can write:

- **A connection with no owner is refused.** A process can send its request and close the socket before
  the server looks. Then the row is gone, or has inode 0. Trusting that would make "close it quickly" the
  way past this check. A real browser holds its socket until the answer arrives. The listener's own row
  proves the table is readable, so a table we cannot read (a sandbox that fakes /proc) is "no answer"
  rather than a refusal of everybody.
- **An orphan is still ours.** `(curl ... &)` makes a process whose parent has exited, and it used to
  reparent to init, out of this tree. `arm()` makes the server a subreaper, so orphans reparent here, and
  `reap()` collects the ones nobody waits for. A jail with `--unshare-pid` stays a descendant either way:
  /proc shows its processes under host pids. What still leaves the tree on purpose is asking somebody else
  to start it (systemd-run, cron, ssh to localhost). That needs the session bus, or a real shell outside
  the jail, and such a process could edit this OS's files anyway, as protected.py says.
- **A process that hides its fds does not get the benefit of the doubt.** `prctl(PR_SET_DUMPABLE, 0)`
  makes /proc/<pid>/fd unreadable. When a descendant cannot be read, the connection is ours unless the
  socket is found in a process outside the tree. sudo and ssh-agent are unreadable too, which is why this
  looks for a positive owner before refusing.
- **Each thread is read.** A thread that called `unshare(CLONE_FILES)` has a table of its own, and the
  process's /proc/<pid>/fd does not show it.
- **Another Unix user is not the person either**: the row carries the socket's uid. Root is allowed,
  because root could read every key on this machine regardless.
- **The server's own process counts as ours.** Agent tools that fetch run in-process, and a fetch of
  http://127.0.0.1:<port>/ must not arrive as the person.

Cost: the numbers are beside CACHE_S below. The lookup runs per
cookie-less request (a browser holding a cookie never comes here), the process walk once per connection
per CACHE_S. A cached answer is keyed on (port, inode), so a port somebody re-binds after the person's
browser closed it is a different key.

Not Linux: there is no /proc to read, so `classify` answers NO_ANSWER and the caller keeps its old
loopback trust. macOS has no jail with this property either; docs/remote-access.md says so.
"""

from __future__ import annotations

import contextlib
import errno
import ipaddress
import os
import socket
import struct
import time

OUTSIDE = "outside"        # a process that is not ours, and of this Unix user
CHILD = "child"            # a descendant of this server, or the server itself
OTHER_USER = "other-user"  # some other Unix user's process
GONE = "gone"              # a real connection whose client socket has no owner any more
NO_ANSWER = "no-answer"    # no real socket (an in-process test client), or no /proc to read

REFUSED = frozenset({CHILD, OTHER_USER, GONE})

# Measured on a desktop with ~550 processes and ~650 sockets: sock_diag lookup 0.012 ms, the /proc/net/tcp
# fallback 6 ms, the process walk 6.5 ms, the fd scan 0.1 ms with five descendants.
CACHE_S = 30.0             # who owns a live socket does not change, short of somebody passing the fd
CACHE_MAX = 256
ZOMBIE_GRACE_S = 30.0      # a child somebody is about to wait() on must keep its exit status

_cache: dict[tuple[int, int], tuple[str, float]] = {}
_armed = False
_zombies: dict[int, float] = {}


def _diag(client_ip: str, client_port: int, server_ip: str, server_port: int) -> tuple[int, int] | None:
    """(uid, inode) of the client's socket, by asking the kernel for that one connection over sock_diag:
    (-1, -1) when it says there is no such socket, None when this kernel will not say (no inet_diag, a
    sandbox), and the caller reads /proc/net/tcp instead. The table costs ~6.5 ms per read on a desktop
    with ~500 sockets, because the kernel formats every row, and this runs per cookie-less request."""
    NETLINK_SOCK_DIAG, SOCK_DIAG_BY_FAMILY, NLM_F_REQUEST, NLMSG_ERROR = 4, 20, 1, 2
    try:
        cli = ipaddress.ip_address(client_ip.split("%")[0])
        srv = ipaddress.ip_address(server_ip.split("%")[0])
        if cli.version == 6 and cli.ipv4_mapped:
            cli = cli.ipv4_mapped
        if srv.version == 6 and srv.ipv4_mapped:
            srv = srv.ipv4_mapped
        if cli.version != srv.version:
            return None
        fam = socket.AF_INET if cli.version == 4 else socket.AF_INET6
        idbytes = (struct.pack("!HH", client_port, server_port)
                   + cli.packed.ljust(16, b"\0") + srv.packed.ljust(16, b"\0")
                   + struct.pack("=III", 0, 0xffffffff, 0xffffffff))
        req = struct.pack("=BBBBI", fam, socket.IPPROTO_TCP, 0, 0, 0xffffffff) + idbytes
        head = struct.pack("=IHHII", 16 + len(req), SOCK_DIAG_BY_FAMILY, NLM_F_REQUEST, 1, 0)
        with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_SOCK_DIAG) as s:
            s.settimeout(1)
            s.send(head + req)
            got = s.recv(8192)
        if len(got) < 20:
            return None
        kind = struct.unpack_from("=H", got, 4)[0]
        if kind == NLMSG_ERROR:
            err = -struct.unpack_from("=i", got, 16)[0]
            return (-1, -1) if err == errno.ENOENT else None
        if kind != SOCK_DIAG_BY_FAMILY or len(got) < 16 + 72:
            return None
        # inet_diag_msg: 4 bytes, the 48-byte id, then expires rqueue wqueue uid inode
        return struct.unpack_from("=II", got, 16 + 4 + 48 + 12)
    except (OSError, ValueError, AttributeError, struct.error):
        return None             # AF_NETLINK is Linux only


def _rows() -> bytes:
    """Both tables: a server bound to `::` lists its listener in tcp6 while a v4 client's half of the
    same connection is in tcp."""
    out = b""
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        with contextlib.suppress(FileNotFoundError), open(name, "rb") as f:
            out += f.read()
    if not out:
        raise OSError("no tcp table")
    return out


def _find(table: bytes, client_port: int, server_port: int) -> tuple[bool, int, int] | None:
    """(the listener is in the table, uid, inode) for the client's half of this connection. uid and
    inode are -1 when that half is not there. None when the table is unreadable as a table."""
    want = f":{client_port:04X} ".encode()
    rem = f":{server_port:04X} ".encode()
    listen = f":{server_port:04X} ".encode()
    listening, uid, inode = False, -1, -1
    for line in table.split(b"\n"):
        parts = line.split()
        if len(parts) < 10 or parts[0] == b"sl":
            continue
        local, remote, st = parts[1] + b" ", parts[2] + b" ", parts[3]
        if st == b"0A" and local.endswith(listen):
            listening = True
        elif local.endswith(want) and remote.endswith(rem):
            try:
                uid, inode = int(parts[7]), int(parts[9])
            except ValueError:
                return None
    return listening, uid, inode


def _tree(me: int) -> tuple[list[int], list[int]]:
    """(our descendants, every other live process), read from /proc/*/stat. Zombies hold no fds. The
    walk covers host pids, which is how a jail's processes stay visible behind --unshare-pid."""
    kids: dict[int, list[int]] = {}
    alive: set[int] = set()
    with os.scandir("/proc") as it:
        for e in it:
            if not e.name.isdigit():
                continue
            try:
                with open(f"/proc/{e.name}/stat", "rb") as f:
                    raw = f.read()
            except OSError:
                continue
            tail = raw[raw.rfind(b")") + 2:].split(None, 2)
            if len(tail) < 2 or tail[0] in (b"Z", b"X"):
                continue
            pid = int(e.name)
            alive.add(pid)
            kids.setdefault(int(tail[1]), []).append(pid)
    ours, stack = [], list(kids.get(me, []))
    while stack:
        pid = stack.pop()
        ours.append(pid)
        stack.extend(kids.get(pid, []))
    seen = set(ours) | {me}
    return ours, [p for p in alive if p not in seen]


def _holds(pid: int, needle: str, threads: bool = True) -> bool | None:
    """Does this process hold the socket? None when something of it could not be read."""
    unread = False
    try:
        tasks = os.listdir(f"/proc/{pid}/task") if threads else [str(pid)]
    except PermissionError:
        return None
    except OSError:
        return False
    for tid in tasks:
        try:
            with os.scandir(f"/proc/{pid}/task/{tid}/fd") as it:
                for e in it:
                    with contextlib.suppress(OSError):
                        if os.readlink(e.path) == needle:
                            return True
        except PermissionError:
            unread = True
        except OSError:
            continue
    return None if unread else False


def _owner(inode: int) -> str:
    me = os.getpid()
    needle = f"socket:[{inode}]"
    # our own threads share one table and our own code does not unshare it
    if _holds(me, needle, threads=False):
        return CHILD
    ours, others = _tree(me)
    unread = False
    for pid in ours:
        held = _holds(pid, needle)
        if held:
            return CHILD
        if held is None:
            unread = True
    if not unread:
        return OUTSIDE
    # a descendant we cannot read could be the one: it is the person only if we can see who is
    for pid in others:
        if _holds(pid, needle, threads=False):
            return OUTSIDE
    return CHILD


def classify(client_ip: str, client_port: int, server_ip: str, server_port: int) -> str:
    """Who is at the far end of this connection. See the module's docstring. Never raises: a failure
    to look is NO_ANSWER only where looking is impossible, and refused where looking found nothing."""
    try:
        ipaddress.ip_address((client_ip or "").split("%")[0])
        ipaddress.ip_address((server_ip or "").split("%")[0])
    except ValueError:
        return NO_ANSWER        # TestClient's "testclient"/"testserver": there is no socket at all
    try:
        client_port, server_port = int(client_port), int(server_port)
    except (ValueError, TypeError):
        return NO_ANSWER
    asked = _diag(client_ip, client_port, server_ip, server_port)
    if asked is not None:
        uid, inode = asked
        if uid < 0 or inode <= 0:       # the kernel looked: no such socket, or one with no owner
            return GONE
    else:
        try:
            got = _find(_rows(), client_port, server_port)
        except (OSError, ValueError):
            return NO_ANSWER    # not Linux, or no /proc
        if got is None:
            return NO_ANSWER
        listening, uid, inode = got
        if uid < 0 or inode <= 0:
            # the row is gone, or the kernel keeps it with no owner (TIME_WAIT, FIN_WAIT2)
            return GONE if listening else NO_ANSWER
    if uid not in (os.geteuid(), 0):
        return OTHER_USER
    now = time.monotonic()
    hit = _cache.get((client_port, inode))
    if hit and now - hit[1] < CACHE_S:
        return hit[0]
    try:
        verdict = _owner(inode)
    except OSError:
        return CHILD            # /proc went away in the middle of looking: nothing was established
    if len(_cache) >= CACHE_MAX:
        for k, v in sorted(_cache.items(), key=lambda kv: kv[1][1])[:CACHE_MAX // 2]:
            _cache.pop(k, None)
    _cache[(client_port, inode)] = (verdict, now)
    return verdict


def forget() -> None:
    _cache.clear()


def arm() -> bool:
    """Make this process the parent of its orphans, so `(curl ... &)` stays in the tree. Called by the
    real server only, not by a test's in-process app: a subreaper changes who reaps what in that process.
    Linux only, and a failure leaves the check working for everything that keeps its parent."""
    global _armed
    if not os.path.exists("/proc/self/stat"):
        return False
    with contextlib.suppress(Exception):
        import ctypes
        PR_SET_CHILD_SUBREAPER = 36
        if ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0:
            _armed = True
    return _armed


def reap(now: float | None = None) -> int:
    """Collect zombies that have been left past ZOMBIE_GRACE_S. Being a subreaper means an orphan's
    exit status comes here, and nobody else will ever ask for it. Waiting at once would take the status
    of a child that code in this process is about to wait() on, so only a zombie seen twice, long enough
    apart, is collected."""
    if not _armed:
        return 0
    now = time.monotonic() if now is None else now
    me = os.getpid()
    live: set[int] = set()
    with contextlib.suppress(OSError):
        for tid in os.listdir(f"/proc/{me}/task"):
            with contextlib.suppress(OSError), open(f"/proc/{me}/task/{tid}/children") as f:
                for word in f.read().split():
                    pid = int(word)
                    with contextlib.suppress(OSError), open(f"/proc/{pid}/stat", "rb") as s:
                        raw = s.read()
                        if raw[raw.rfind(b")") + 2:].split(None, 1)[0] == b"Z":
                            live.add(pid)
    done = 0
    for pid in live:
        first = _zombies.setdefault(pid, now)
        if now - first >= ZOMBIE_GRACE_S:
            with contextlib.suppress(OSError):
                os.waitpid(pid, os.WNOHANG)
                done += 1
            _zombies.pop(pid, None)
    for pid in list(_zombies):
        if pid not in live:
            _zombies.pop(pid, None)
    return done
