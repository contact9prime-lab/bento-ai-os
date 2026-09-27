"""What your agents made, reachable from where you read about it.

Reported as: "it created the deck but I can't open it from the chat" and "it said it
created the file but it isn't in Files". Two causes, both pinned here. A turn forwarded
to Claude Code was handed the MACHINE's workspace, so a signed-in person's deck landed
in a folder their Files app never shows. And a reply that named a file gave nothing to
click, nothing on the phone, nothing in the Office.
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors, outputs                          # noqa: E402

ROOT = Path(__file__).parent.parent


def _ws(tmp_path):
    ws = tmp_path / "me" / "workspace"
    (ws / "decks").mkdir(parents=True)
    (ws / "decks" / "Quantum_Computing_101.pptx").write_bytes(b"PK" + b"x" * 100)
    (ws / "notes.md").write_text("hi")
    return ws


def test_a_forwarded_turn_works_in_the_persons_own_workspace(tmp_path):
    ws = _ws(tmp_path)
    assert executors.default_workspace({"workspace": str(ws)}) == str(ws)
    # a folder set in Settings -> Executors still wins (the envelope reads it first)
    env = executors.envelope_from({"workspace": str(ws), "executors": {"claude_code": {"workspace": str(tmp_path)}}},
                                  executors.default_workspace({"workspace": str(ws)}))
    assert env.workspace == str(tmp_path)
    # and no surface hands the machine's folder over any more
    import re
    for f in ("server.py", "telegram.py", "whatsapp.py", "scheduler.py", "executors.py"):
        src = (ROOT / "agentos" / f).read_text()
        calls = re.findall(r"(?:forward|envelope_from)\((?:[^()]|\([^()]*\))*\)", src)
        assert calls and not [c for c in calls if 'AGENTOS_HOME / "workspace"' in c], f


def test_a_reply_that_names_a_file_gets_the_file(tmp_path):
    ws = _ws(tmp_path)
    rts = [ws.resolve()]
    text = (f"The deck is ready.\n\nFile: `{ws}/decks/Quantum_Computing_101.pptx` (12 slides)\n"
            "Notes are in notes.md, and e.g. this is not a file. See also `missing.pdf`.")
    got = outputs.mentioned(text, rts)
    assert [f["name"] for f in got] == ["Quantum_Computing_101.pptx", "notes.md"]
    assert got[0]["rel"] == "decks/Quantum_Computing_101.pptx" and got[0]["ext"] == "pptx"
    # relative names are found under the workspace too
    assert outputs.mentioned("saved to decks/Quantum_Computing_101.pptx", rts)[0]["name"].endswith(".pptx")


def test_a_name_outside_your_folders_stays_text(tmp_path):
    ws = _ws(tmp_path)
    secret = tmp_path / "other" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("no")
    rts = [ws.resolve()]
    assert outputs.mentioned(f"look at `{secret}` and `/etc/passwd`", rts) == []
    # a symlink out of the workspace does not become a way out
    (ws / "link.txt").symlink_to(secret)
    assert outputs.reachable("link.txt", rts) is None
    assert outputs.reachable("../other/secret.txt", rts) is None


def test_the_machines_folders_are_for_its_owner_only(tmp_path, monkeypatch):
    from agentos import config as cfgmod
    ws = _ws(tmp_path)
    machine = tmp_path / "home"
    (machine / "workspace").mkdir(parents=True)
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", machine)
    cfg = {"workspace": str(ws)}
    assert outputs.roots(cfg, admin=False) == [ws.resolve()]
    assert (machine / "workspace").resolve() in outputs.roots(cfg, admin=True)


def test_recent_is_newest_first_and_skips_caches(tmp_path):
    ws = _ws(tmp_path)
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "x.js").write_text("x")
    (ws / ".hidden").write_text("x")
    old = time.time() - 3600
    os.utime(ws / "notes.md", (old, old))
    got = [f["name"] for f in outputs.recent([ws.resolve()])]
    assert got == ["Quantum_Computing_101.pptx", "notes.md"]


def test_telegram_sends_the_files_a_reply_names(tmp_path, monkeypatch):
    from agentos import telegram
    ws = _ws(tmp_path)
    sent, said = [], []
    bridge = telegram.TelegramBridge.__new__(telegram.TelegramBridge)
    bridge.cfg = {"workspace": str(ws), "telegram": {"bot_token": "t", "owner_chat_id": 1}}
    bridge._t = lambda: bridge.cfg["telegram"]

    async def doc(path, caption="", chat_id=None):
        sent.append(Path(path).name)
        return "sent via Telegram"

    async def send(text, chat_id=None):
        said.append(text)
    bridge.send_document, bridge.send = doc, send
    asyncio.run(bridge.send_files(f"Deck: `{ws}/decks/Quantum_Computing_101.pptx`", 1))
    assert sent == ["Quantum_Computing_101.pptx"] and not said
    bridge.cfg["telegram"]["files"] = False
    asyncio.run(bridge.send_files(f"Deck: `{ws}/decks/Quantum_Computing_101.pptx`", 1))
    assert sent == ["Quantum_Computing_101.pptx"], "telegram.files = false switches it off"


def test_every_chat_surface_offers_open_and_download():
    js = ROOT / "agentos" / "ui" / "src" / "js"
    fc = (js / "10c-filechips.js").read_text()
    assert "/api/files/which" in fc and "fc-open" in fc and "fc-dl" in fc
    # from a phone, opening on the host would start an app in another room
    assert "remoteClient()" in fc.split("async function fileOpen(")[1][:400]
    assert "fileChips(curBody)" in (js / "09-websocket.js").read_text()
    assert "fileChips(feed)" in (js / "10-chat.js").read_text()
    cp = (js / "04a-copilot.js").read_text()
    assert "fileChips(body)" in cp and "fileChips(feedEl)" in cp
    of = (js / "24d-office.js").read_text()
    assert "/api/files/recent" in of and "officeCabinetBg" in of and "OF_WRITES" in of
    css = (ROOT / "agentos/ui/src/css/24b-filechips.css").read_text()
    assert "body.dev-touch .fc-main" in css and "var(--tap)" in css
