"""A linked WhatsApp device is one Node process per account, each with its own session folder
(agentos/wa_baileys.py). Asked for as "like how Telegram is separated, this is also separated
as a process per user"."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod                                # noqa: E402
from agentos import users as usersmod                               # noqa: E402
from agentos import wa_baileys                                      # noqa: E402


def test_each_account_has_its_own_process_and_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    usersmod.reset_caches()
    a = usersmod.create("ada", "correct horse 1", role="admin")["id"]
    b = usersmod.create("bob", "correct horse 2")["id"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setattr(wa_baileys, "why_not", lambda: "")
    monkeypatch.setattr(wa_baileys, "node_path", lambda: "/bin/true")
    started = []

    async def fake_exec(*argv, env=None, **kw):
        started.append(env)

        class P:
            returncode = 0
            stdout = stdin = stderr = None

            async def wait(self):
                return 0
        return P()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    async def go():
        ts = {}
        for uid in (a, b):
            with usersmod.as_user(uid):
                t = wa_baileys.BaileysTransport(on_message=lambda *x: None)
                t._pump = lambda: asyncio.sleep(0)
                await t.start()
                ts[uid] = t
        return ts
    ts = asyncio.run(go())
    try:
        assert ts[a].uid == a and ts[b].uid == b and len(started) == 2
        dirs = [e["WA_SESSION_DIR"] for e in started]
        assert dirs[0] != dirs[1] and a in dirs[0] and b in dirs[1]
        # the bridge gets a path and a proxy, never this server's keys
        assert all("ANTHROPIC_API_KEY" not in e for e in started)
        # forgetting bob's device, from any context, touches only bob's folder
        Path(dirs[0], "creds.json").write_text("{}")
        Path(dirs[1], "creds.json").write_text("{}")
        assert wa_baileys.forget_session(ts[b].uid)
        assert Path(dirs[0], "creds.json").exists() and not Path(dirs[1]).exists()
    finally:
        usersmod.reset_caches()
        usersmod.set_current("")
