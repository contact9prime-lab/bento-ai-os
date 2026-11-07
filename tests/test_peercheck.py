"""Who is at the far end of a loopback connection? A jailed command must not arrive as the person.

Real sockets and real processes throughout: this module is about what /proc says, and a mock of /proc
would prove nothing. The server side is a plain listening socket owned by this test process, so "this
server" is the test process and a subprocess of it is the child.
"""
import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from agentos import peercheck

pytestmark = pytest.mark.skipif(not os.path.exists("/proc/net/tcp"), reason="needs Linux /proc")


@pytest.fixture()
def listener():
    peercheck.forget()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(16)
    s.settimeout(10)          # a child that died must fail the test, never hang it
    yield s
    s.close()


def _accept(listener):
    conn, peer = listener.accept()
    return conn, peer


def _child(code, port, **kw):
    """A subprocess that connects, prints READY, then waits on stdin."""
    full = ("import os, socket, sys\n" f"PORT = {port}\n" + textwrap.dedent(code).strip()
            + '\nprint("READY", flush=True)\nsys.stdin.readline()\n')
    return subprocess.Popen([sys.executable, "-c", full], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, **kw)


def _verdict(listener, peer):
    return peercheck.classify(peer[0], peer[1], "127.0.0.1", listener.getsockname()[1])


def test_a_child_process_is_recognised(listener):
    p = _child("c = socket.create_connection(('127.0.0.1', PORT))", listener.getsockname()[1])
    p.stdout.readline()
    conn, peer = _accept(listener)
    assert _verdict(listener, peer) == peercheck.CHILD
    p.kill(); p.wait(); conn.close()


def test_this_process_counts_as_ours(listener):
    """An agent's fetch runs in-process, and must not arrive as the person."""
    c = socket.create_connection(listener.getsockname())
    conn, peer = _accept(listener)
    assert _verdict(listener, peer) == peercheck.CHILD
    c.close(); conn.close()


def test_a_process_outside_the_tree_is_outside(listener):
    """Started by somebody else: a person's browser or terminal. `setsid` and a double fork orphan it
    to init here because this test process is not a subreaper."""
    port = listener.getsockname()[1]
    code = textwrap.dedent(f"""
        import os, socket, sys, time
        if os.fork(): os._exit(0)
        os.setsid()
        if os.fork(): os._exit(0)
        c = socket.create_connection(('127.0.0.1', {port}))
        time.sleep(6)
    """)
    subprocess.run([sys.executable, "-c", code], check=True)
    conn, peer = _accept(listener)
    time.sleep(.1)
    assert _verdict(listener, peer) == peercheck.OUTSIDE
    conn.close()


def test_a_connection_closed_before_we_look_is_refused(listener):
    """Send and close at once: the request is still in the server's buffer, its owner is gone. If that
    read as "not a child", closing quickly would be the way past this whole module."""
    c = socket.create_connection(listener.getsockname())
    conn, peer = _accept(listener)
    c.close()
    assert _verdict(listener, peer) == peercheck.GONE
    conn.close()


def test_an_aborted_connection_is_refused(listener):
    c = socket.create_connection(listener.getsockname())
    conn, peer = _accept(listener)
    import struct
    c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    c.close()
    assert _verdict(listener, peer) == peercheck.GONE
    conn.close()


def test_the_proc_table_gives_the_same_answers_where_sock_diag_is_missing(listener, monkeypatch):
    """A kernel with no inet_diag module, or a sandbox that refuses netlink."""
    monkeypatch.setattr(peercheck, "_diag", lambda *a: None)
    c = socket.create_connection(listener.getsockname())
    conn, peer = _accept(listener)
    assert _verdict(listener, peer) == peercheck.CHILD
    c.close()
    time.sleep(.05)
    assert _verdict(listener, peer) == peercheck.GONE
    conn.close()


def test_an_unknowable_table_does_not_shut_the_person_out(listener, monkeypatch):
    """A sandbox that fakes /proc: no listener in the table means the table says nothing."""
    monkeypatch.setattr(peercheck, "_diag", lambda *a: None)
    monkeypatch.setattr(peercheck, "_rows", lambda: b"  sl  local_address\n")
    assert peercheck.classify("127.0.0.1", 55555, "127.0.0.1", 8321) == peercheck.NO_ANSWER


def test_no_socket_at_all_is_no_answer():
    """Starlette's TestClient: there is no peer to look for, and the suite's loopback stands."""
    assert peercheck.classify("testclient", 50000, "testserver", 80) == peercheck.NO_ANSWER


def test_a_child_that_hides_its_fds_is_still_ours(listener):
    """PR_SET_DUMPABLE 0 makes /proc/<pid>/fd unreadable. That must not read as "not found"."""
    p = _child("""
        import ctypes
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)
        c = socket.create_connection(('127.0.0.1', PORT))
    """, listener.getsockname()[1])
    p.stdout.readline()
    conn, peer = _accept(listener)
    assert not os.access(f"/proc/{p.pid}/fd", os.R_OK)
    assert _verdict(listener, peer) == peercheck.CHILD
    p.kill(); p.wait(); conn.close()


def test_a_thread_with_its_own_fd_table_is_still_seen(listener):
    p = _child("""
        import ctypes, threading, time
        def work():
            ctypes.CDLL(None).unshare(0x00000400)   # CLONE_FILES: this thread's table is its own
            global c
            c = socket.create_connection(('127.0.0.1', PORT))
            time.sleep(30)
        threading.Thread(target=work, daemon=True).start()
        time.sleep(.3)
    """, listener.getsockname()[1])
    p.stdout.readline()
    conn, peer = _accept(listener)
    assert _verdict(listener, peer) == peercheck.CHILD
    p.kill(); p.wait(); conn.close()


def test_a_grandchild_is_ours(listener):
    port = listener.getsockname()[1]
    p = _child(f"""
        import subprocess
        g = subprocess.Popen([sys.executable, '-c', "import socket,time; c=socket.create_connection(('127.0.0.1',{port})); time.sleep(30)"])
        import time; time.sleep(.4)
    """, port)
    p.stdout.readline()
    conn, peer = _accept(listener)
    assert _verdict(listener, peer) == peercheck.CHILD
    subprocess.run(["pkill", "-P", str(p.pid)], check=False)
    p.kill(); p.wait(); conn.close()


def test_an_orphan_stays_ours_once_armed():
    """`(curl ... &)`: its parent exits, and without a subreaper it reparents to init and looks like a
    stranger. Run in a child of its own, because arming changes the whole process."""
    code = textwrap.dedent("""
        import os, socket, subprocess, sys, time
        sys.path.insert(0, sys.argv[1])
        from agentos import peercheck
        assert peercheck.arm()
        s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(4)
        port = s.getsockname()[1]
        orphan = f"import socket,time; c=socket.create_connection(('127.0.0.1',{port})); time.sleep(20)"
        # sh forks python into the background and exits: python is now an orphan
        subprocess.run(["sh", "-c", f'{sys.executable} -c "{orphan}" >/dev/null 2>&1 &'], check=True)
        conn, peer = s.accept()
        time.sleep(.2)
        print(peercheck.classify(peer[0], peer[1], "127.0.0.1", port))
        subprocess.run(["pkill", "-f", f"create_connection..'127.0.0.1',{port}"], check=False)
    """)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-c", code, root], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == peercheck.CHILD, out.stderr


def test_reap_collects_only_a_zombie_left_past_the_grace(monkeypatch):
    """A zombie seen once is somebody's child about to be waited on. Seen again later, it is an orphan
    nobody will ever ask about."""
    monkeypatch.setattr(peercheck, "_armed", True)
    monkeypatch.setattr(peercheck, "_zombies", {})
    p = subprocess.Popen(["true"])
    time.sleep(.3)
    assert peercheck.reap(now=100.0) == 0
    assert os.path.exists(f"/proc/{p.pid}")
    assert peercheck.reap(now=100.0 + peercheck.ZOMBIE_GRACE_S) == 1
    assert not os.path.exists(f"/proc/{p.pid}")
    assert p.poll() is not None        # Popen copes with a status somebody else collected
