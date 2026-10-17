"""An update must not freeze the server it updates, and a terminal must drive only its
own server.

Found on the reporting machine: the desktop said "0.3.0 → 0.6.30, Updating…" and then
nothing answered. `updates.apply` was an async function doing blocking work (git, uv,
the whole suite for minutes) on the server's loop, so every request queued behind it,
and the suite's CLI tests, which look for a server on 8321, found that frozen server
and hung against it. Pinned here:

- `apply` runs its work on a worker thread, so the loop keeps answering;
- the server names its home in `X-Bento-Home` on every answer, a locked 401 too, and
  `bento` uses a server only when the home is its own (an older server, with no
  header, is trusted as before).
"""
import asyncio
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import __main__ as cli, config as cfgmod, updates   # noqa: E402

ROOT = Path(__file__).parent.parent


def test_apply_leaves_the_loop_free(monkeypatch):
    def slow(cfg, run_tests=True, log=None, switch=False):
        if log:
            log("working")
        time.sleep(0.6)
        return {"ok": True}
    monkeypatch.setattr(updates, "_apply", slow)

    async def main():
        ticks, said = [], []
        task = asyncio.create_task(updates.apply({}, log=said.append))
        while not task.done():
            ticks.append(time.monotonic())
            await asyncio.sleep(0.05)
        return await task, len(ticks), said
    res, ticks, said = asyncio.run(main())
    assert res == {"ok": True} and said == ["working"]
    assert ticks >= 8, "the loop kept running while the update worked"
    src = (ROOT / "agentos/server.py").read_text()
    assert "loop.call_soon_threadsafe(asyncio.ensure_future, say(m))" in src


def _serve(header: str | None, status: int = 200):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(status)
            if header is not None:
                self.send_header("X-Bento-Home", header)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_a_terminal_uses_only_its_own_server():
    mine = cfgmod.home_id()
    for header, status, expect in ((mine, 200, True), (mine, 401, True),
                                   ("0123456789abcdef", 200, False),
                                   ("0123456789abcdef", 401, False),
                                   (None, 200, True)):
        srv = _serve(header, status)
        try:
            assert cli._server_answers(srv.server_address[1]) is expect, (header, status)
        finally:
            srv.shutdown()


def test_the_server_names_its_home_on_every_answer():
    src = (ROOT / "agentos/server.py").read_text()
    sh = src[src.index("async def security_headers("):][:3000]
    assert 'resp.headers.setdefault("X-Bento-Home", _HOME_ID)' in sh
    assert cfgmod.home_id(Path("/a")) != cfgmod.home_id(Path("/b"))
    assert len(cfgmod.home_id()) == 16 and os.sep not in cfgmod.home_id()
