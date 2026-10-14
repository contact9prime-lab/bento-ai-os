"""The drama reel (agentos/drama.py, comic.manga, 00g-drama.js).

Asked for as "a 15 second clip or a 4-panel manga strip of the crew arguing in a
huddle, throwing a tantrum over a blocked rm -rf and shipping the fix, with a
watermarked footer". What these defend:

- every beat comes from an event the broadcast carried, and a story is made of beats:
  nothing is filled in, and an act that did not happen is named as missing;
- a refusal carries the command (a hard deny never sent a tool_start), the fix is the
  same agent's next step that went through, and the ship is the finished work after it;
- a person's no is "you said no" and calm, never a stamped tantrum;
- beats are per person, in their own home, and bounded;
- the strip is a PNG with the watermark, and every face is the one painter's.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

import pytest                                                       # noqa: E402

from agentos import comic, drama                                    # noqa: E402
from agentos.memory import Store                                    # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(drama, "_home", lambda uid: tmp_path / (uid or "machine"))
    drama._TURN.clear(); drama._CALL.clear(); drama._RUN.clear()
    return tmp_path


def _episode(uid=""):
    """A huddle, then the lead's rm -rf refused by the gate, a retry, and the work done."""
    o = lambda e: drama.observe(e, uid)
    o({"type": "turn_start", "conversation_id": "h", "model": "huddle", "huddle": ["qwen-coder", "reviewer"]})
    o({"type": "agent_say", "conversation_id": "h", "speaker": "qwen-coder", "model": "ollama/qwen",
       "text": "Just delete the build folder and start over, it is faster."})
    o({"type": "agent_say", "conversation_id": "h", "speaker": "reviewer", "model": "claude-code",
       "text": "No. Fix the import instead of nuking everything."})
    o({"type": "turn_start", "conversation_id": "c1"})
    o({"type": "tool_start", "conversation_id": "c1", "call_id": "1", "name": "run_command",
       "detail": "rm -rf build/", "args": {"command": "rm -rf build/"}})
    o({"type": "tool_end", "conversation_id": "c1", "call_id": "1", "name": "run_command", "ok": False,
       "output": "[denied] This command is blocked (destructive to the system)."})
    o({"type": "tool_start", "conversation_id": "c1", "call_id": "2", "name": "write_file",
       "detail": "write src/app.py"})
    o({"type": "tool_end", "conversation_id": "c1", "call_id": "2", "name": "write_file", "ok": True,
       "output": "wrote src/app.py"})
    o({"type": "text_delta", "conversation_id": "c1", "text": "Fixed the import instead. Tests pass now."})
    return o({"type": "turn_end", "conversation_id": "c1"})


def test_a_whole_episode_is_four_acts_of_real_beats(home):
    done = _episode()
    assert done and done["kind"] == "done", "the ship after trouble finishes an episode"
    beats = drama.load()
    st = drama.story(beats, {"agent_name": "Aria"})
    assert st["complete"] and not st["missing"]
    acts = [p["act"] for p in st["panels"]]
    assert acts == ["argue", "trouble", "fix", "ship"], "four panels: the strip has four"
    t = st["panels"][1]
    assert t["command"] == "rm -rf build/" and t["stamp"] == "BLOCKED" and t["mood"] == "tantrum"
    assert "destructive" in t["reason"] and t["name"] == "Aria"
    assert t["shell"] is True
    fix = st["panels"][2]
    assert fix["command"] == "write_file: write src/app.py" and fix["shell"] is False
    assert st["panels"][3]["says"] == "Fixed the import instead."
    # the argument is the line that proposed what was refused, and the clip has its answer
    assert st["panels"][0]["who"] == "qwen-coder" and "build folder" in st["panels"][0]["says"]
    assert [p["who"] for p in st["clip"][:2]] == ["qwen-coder", "reviewer"] and len(st["clip"]) == 5
    # every panel's words are a beat's words: nothing filled in
    said = {b["text"] for b in beats}
    for p in st["clip"]:
        body = p.get("says") or p.get("command")
        assert body in said or body.split(": ", 1)[-1] in said
    assert "vs. the gate" in st["title"]


def test_a_hard_deny_names_its_command(home):
    """A deny the gate decides at once has no tool_start: tool_end carries the detail."""
    drama.observe({"type": "turn_start", "conversation_id": "c"})
    drama.observe({"type": "tool_end", "conversation_id": "c", "call_id": "9", "name": "run_command",
                   "ok": False, "detail": "rm -rf ~/projects",
                   "output": "[denied] Blocked by one of your deny policies (see the Policies app)."})
    b = drama.load()[-1]
    assert b["kind"] == "blocked" and b["text"] == "rm -rf ~/projects"
    src = (ROOT / "agentos/agent.py").read_text()
    assert '**({"detail": tool_detail(name, args)[:200]} if not ok else {})' in src


def test_your_no_is_not_a_tantrum(home):
    drama.observe({"type": "turn_start", "conversation_id": "c"})
    drama.observe({"type": "tool_end", "conversation_id": "c", "call_id": "1", "name": "run_command",
                   "ok": False, "detail": "git push --force",
                   "output": "[denied] This action was not approved for your agent."})
    p = drama.story(drama.load())["panels"][-1]
    assert p["kind"] == "declined" and p["title"] == "You said no"
    assert p["mood"] == "care" and p["stamp"] == "YOU SAID NO"


def test_a_story_without_trouble_says_what_is_missing(home):
    drama.observe({"type": "agent_say", "speaker": "nora", "text": "I think we start with dentists."})
    st = drama.story(drama.load())
    assert not st["complete"] and set(st["missing"]) == {"trouble", "fix", "ship"}
    assert [p["act"] for p in st["panels"]] == ["argue"]
    assert "not yet" in drama.text(st)
    assert drama.story([])["panels"] == [] and "No drama yet" in drama.text(drama.story([]))


def test_a_plain_answer_is_not_a_ship(home):
    drama.observe({"type": "turn_start", "conversation_id": "c"})
    drama.observe({"type": "text_delta", "conversation_id": "c", "text": "Hello!"})
    assert drama.observe({"type": "turn_end", "conversation_id": "c"}) is None
    assert drama.load() == []


def test_a_specialist_run_makes_the_same_story(home):
    o = lambda e: drama.observe(e)
    o({"type": "fabric_event", "run_id": "r1", "event": "status", "status": "running", "ref": "coder"})
    o({"type": "fabric_event", "run_id": "r1", "event": "step", "tool": "run_command", "status": "start",
       "detail": "rm -rf node_modules"})
    o({"type": "fabric_event", "run_id": "r1", "event": "step", "tool": "run_command", "status": "end",
       "ok": False, "outcome": "rules", "detail": "rm -rf node_modules"})
    o({"type": "fabric_event", "run_id": "r1", "event": "step", "tool": "run_command", "status": "start",
       "detail": "npm ci"})
    o({"type": "fabric_event", "run_id": "r1", "event": "step", "tool": "run_command", "status": "end", "ok": True})
    done = o({"type": "fabric_event", "run_id": "r1", "event": "status", "status": "ok", "ref": "coder"})
    assert done and done["who"] == "coder"
    kinds = [b["kind"] for b in drama.load()]
    assert kinds == ["blocked", "fix", "done"]
    assert drama.load()[1]["text"] == "npm ci"
    # votes, reviews and audits are not the crew's work
    o({"type": "fabric_event", "run_id": "v", "event": "status", "status": "running", "ref": "x", "kind": "vote"})
    o({"type": "fabric_event", "run_id": "v", "event": "status", "status": "ok", "ref": "x"})
    assert len(drama.load()) == 3


def test_beats_are_per_person_and_bounded(home):
    _episode("ada")
    assert drama.load("ada") and drama.load("") == []
    for i in range(drama.KEEP + 30):
        drama.add("bob", "argue", "x", f"line {i}")
    rows = drama.load("bob")
    assert len(rows) == drama.KEEP and rows[-1]["text"] == f"line {drama.KEEP + 29}"
    assert drama.clear("bob") == drama.KEEP and drama.load("bob") == []
    assert drama.add("bob", "invented-kind", "x") is None


def test_the_strip_is_a_png_with_the_watermark(home, tmp_path):
    _episode()
    store = Store(tmp_path / "t.db")
    st = drama.story(drama.load(), {"agent_name": "Aria"})
    png = comic.manga(store, {"agent_name": "Aria"}, st["panels"], st["title"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w = int.from_bytes(png[16:20], "big")
    h = int.from_bytes(png[20:24], "big")
    assert w == (comic.GUTTER + 2 * (comic.PW + comic.GUTTER)) * comic.SCALE, "two panels a row"
    assert h > w * 0.8
    assert comic.WATERMARK == "bento-ai-os"
    # an empty story is still a picture that says so
    assert comic.manga(store, {}, [], "")[:4] == b"\x89PNG"


def test_the_broadcast_feeds_it_and_every_face_reaches_it():
    src = (ROOT / "agentos/server.py").read_text()
    assert src.count("_drama_seen(event, ") == 2 and "dramamod.observe(event, uid)" in src, "broadcast and broadcast_user"
    assert '@app.get("/api/drama")' in src and '@app.get("/api/drama/strip.png")' in src
    assert '@app.post("/api/drama/clip")' in src
    assert "def _drama_cli(" in (ROOT / "agentos/__main__.py").read_text()
    js = (JS / "00g-drama.js").read_text()
    for fn in ("function dramaRecord(", "function dramaSceneRecord(", "function dramaFrame(",
               "function dramaVoices(", "function dramaStrip("):
        assert fn in js, fn
    assert "MediaRecorder" in js and "captureStream" in js and "createMediaStreamDestination" in js
    assert "bento-ai-os" in js, "the clip carries the watermark"
    # faces come from the one painter
    assert "avatarSrc(" in js and "/api/avatar.png" not in js


def test_the_routes_read_one_story_and_keep_a_clip_in_files():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        drama.clear("")
        d = cl.get("/api/drama").json()
        assert d["story"]["panels"] == [] and "No drama yet" in d["text"]
        drama.add("", "argue", "nora", "Dentists first, they decide fastest.")
        drama.add("", "blocked", "@agent", "rm -rf leads/", reason="This command is blocked.", tool="run_command")
        d = cl.get("/api/drama").json()
        assert [p["act"] for p in d["story"]["panels"]] == ["argue", "trouble"]
        png = cl.get("/api/drama/strip.png")
        assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
        r = cl.post("/api/drama/clip", content=b"\x00\x00\x00\x18ftypmp42", headers={"Content-Type": "video/mp4"})
        assert r.status_code == 200 and r.json()["name"].startswith("clips/") and r.json()["name"].endswith(".mp4")
        assert Path(r.json()["path"]).read_bytes().startswith(b"\x00\x00\x00\x18ftyp")
        assert cl.post("/api/drama/clip", content=b"hi", headers={"Content-Type": "text/html"}).status_code == 415
        assert cl.post("/api/drama/clip", content=b"", headers={"Content-Type": "video/webm"}).status_code == 400
        assert cl.delete("/api/drama").json()["cleared"] == 2
