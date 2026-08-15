"""`bento serve` opens the browser when the server is ready — not 1.2 seconds from now.

The old line was `threading.Timer(1.2, lambda: webbrowser.open(...))`. On the machine it
was written on the server was up inside 1.2s, so it looked correct forever. On a first
run — an empty database to create, a cold import, a Raspberry Pi, a machine that has just
finished `uv sync` — it is not, and the browser lands on connection-refused for a server
that comes up two seconds later and then works perfectly.

That failure is worse than it sounds, because nothing is broken: there is no error to
read, no log line, nothing to fix. The tab is simply wrong, and the only cure is knowing
to reload it — which is exactly the kind of thing a first-time user does not know.

The fix reads the same signal every other part of this codebase uses for "is it up":
a completed HTTP request. Uvicorn does not accept connections until the FastAPI startup
hook has finished, so an answer means the whole stack is live.
"""

import time

import pytest

from agentos import __main__ as m


@pytest.fixture()
def browser(monkeypatch):
    opened = []
    monkeypatch.setattr(m.webbrowser, "open", lambda u: opened.append(u))
    return opened


def test_it_does_not_open_before_the_server_answers(browser, monkeypatch):
    """The whole point. A fixed delay opens on hope; this opens on evidence."""
    monkeypatch.setattr(m, "_server_answers", lambda port, timeout=1.5: False)
    m._open_when_ready("http://127.0.0.1:8321", 8321, timeout=0.6)
    time.sleep(0.3)
    assert not browser, "opened a browser at a server that is not answering"


def test_it_opens_once_the_server_answers(browser, monkeypatch):
    ready = {"v": False}
    monkeypatch.setattr(m, "_server_answers", lambda port, timeout=1.5: ready["v"])
    m._open_when_ready("http://127.0.0.1:8321", 8321, timeout=5)
    time.sleep(0.4)
    assert not browser, "opened before the server was up"
    ready["v"] = True
    deadline = time.time() + 3
    while not browser and time.time() < deadline:
        time.sleep(0.05)
    assert browser == ["http://127.0.0.1:8321"]


def test_it_opens_exactly_once(browser, monkeypatch):
    """The waiter polls; a second open would put the user in two tabs."""
    monkeypatch.setattr(m, "_server_answers", lambda port, timeout=1.5: True)
    m._open_when_ready("http://127.0.0.1:8321", 8321, timeout=5)
    time.sleep(0.6)
    assert len(browser) == 1


def test_a_server_that_never_comes_up_opens_nothing_and_says_so(browser, monkeypatch,
                                                                capsys):
    """A tab showing an error reads as a verdict on the SERVER. It is a verdict on the
    waiting, and the difference is what sends somebody debugging the wrong thing."""
    monkeypatch.setattr(m, "_server_answers", lambda port, timeout=1.5: False)
    m._open_when_ready("http://127.0.0.1:8321", 8321, timeout=0.5)
    time.sleep(0.9)
    assert not browser
    out = capsys.readouterr().out
    assert "has not answered" in out
    assert "8321" in out, "it does not say where to look once it does come up"


def test_waiting_never_blocks_the_server(browser, monkeypatch):
    """`uvicorn.run` owns the main thread from the moment it is called, so the wait has
    to be a daemon thread — and returning promptly is what proves it is one."""
    monkeypatch.setattr(m, "_server_answers", lambda port, timeout=1.5: False)
    t0 = time.time()
    m._open_when_ready("http://127.0.0.1:8321", 8321, timeout=30)
    assert time.time() - t0 < 0.5, "the caller was blocked; uvicorn would never start"


# --------------------------------------------------------------- the readiness probe

def test_a_locked_machine_counts_as_ready(monkeypatch):
    """401 is a running server with accounts on it. Treating it as not-ready would mean
    the browser never opens on exactly the machines that have users."""
    import urllib.error
    import urllib.request

    def raise_401(*a, **k):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", raise_401)
    assert m._server_answers(8321) is True


def test_a_server_still_starting_does_not_count_as_ready(monkeypatch):
    """A 5xx is the stack not up yet. Opening on it is the original bug with extra steps."""
    import urllib.error
    import urllib.request

    def raise_502(*a, **k):
        raise urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", raise_502)
    assert m._server_answers(8321) is False


def test_nothing_listening_is_not_ready(monkeypatch):
    import urllib.request

    def refuse(*a, **k):
        raise ConnectionRefusedError()

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert m._server_answers(8321) is False


def test_serve_no_longer_opens_on_a_timer():
    """The shape of the bug, guarded directly: a delay-then-open anywhere in `serve`
    is the thing that looked right on one machine for the life of the file."""
    import inspect
    src = inspect.getsource(m.serve)
    assert "threading.Timer" not in src, "serve opens the browser on a timer again"
    assert "_open_when_ready" in src
