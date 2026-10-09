"""This machine's own screen: one agent drawn (buddy), and the kiosk face that listens.

Asked for as "a single buddy / agent ui interface option for Light mode so that shows
just one agent in the office and desktop face for raspi interface, there will be a kiosk
mode as well where mic would be on and agents would be working in the office".
face.py holds the settings, hearing.py turns speech into text on the server (Chromium on
a Pi cannot), and 24h-kiosk.js is the face. These pin what each promises.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentos import face, hearing, office                       # noqa: E402
from agentos.memory import Store                                # noqa: E402

JS = ROOT / "agentos/ui/src/js"


# ---------------- face.py ----------------

def test_one_agent_follows_light_mode_unless_somebody_chose(monkeypatch):
    from agentos import profile
    monkeypatch.setattr(profile, "resolve", lambda cfg: (cfg or {}).get("profile", "full"))
    assert face.buddy({"profile": "lite"}) is True, "a Pi in Light mode gets one agent without being told"
    assert face.buddy({"profile": "full"}) is False
    assert face.buddy({"profile": "lite", "face": {"buddy": "off"}}) is False, "a choice wins over Light mode"
    assert face.buddy({"profile": "full", "face": {"buddy": "on"}}) is True
    assert face.buddy_setting({"face": {"buddy": "sideways"}}) == "auto", "an unknown stored value reads as auto"


def test_a_typo_is_a_sentence_naming_the_choices():
    cfg = {}
    ok, msg = face.set_face(cfg, buddy="maybe")
    assert not ok and "auto, on, off" in msg and "face" not in cfg
    ok, msg = face.set_face(cfg, wake="clap")
    assert not ok and "name, always" in msg
    ok, msg = face.set_face(cfg, buddy="ON", kiosk=True, wake="always")
    assert ok and cfg["face"] == {"buddy": "on", "kiosk": True, "wake": "always"}
    assert "listens for everything" in msg


def test_one_agent_draws_only_the_lead_and_keeps_the_team(tmp_path):
    store = Store(tmp_path / "a.db")
    for n in ("researcher", "analyst"):
        store.save_subagent({"name": n, "soul": n})
    cfg = {"agent_name": "Aria", "face": {"buddy": "on"}}
    v = office.view(cfg, store)
    assert v["buddy"] is True
    assert {r["kind"] for r in v["rooms"]} <= {"lead", "lounge"}, "no desks for specialists on screen"
    assert sorted(v["agents"]) == ["analyst", "researcher"], "the specialists still exist and still work"
    cfg["face"]["buddy"] = "off"
    v = office.view(cfg, store)
    assert v["buddy"] is False and any(r["kind"] in ("dept", "floor") for r in v["rooms"])


# ---------------- hearing.py ----------------

def _no_whisper(monkeypatch):
    monkeypatch.setattr(hearing.shutil, "which", lambda b: None)
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home-for-test")


def test_nothing_that_can_hear_is_said_plainly(monkeypatch):
    _no_whisper(monkeypatch)
    st = hearing.status({})
    assert st["engine"] == "" and "OpenAI key" in st["line"] and "whisper.cpp" in st["line"]
    assert "whisper.cpp cannot listen here" in hearing.status({"speech": {"hear": {"engine": "whisper.cpp"}}})["line"]
    assert hearing.status({"providers": {"openai": {"api_key": "sk-x"}}})["engine"] == "openai"
    # a key that is a vault reference is not a key this module can send
    assert hearing.status({"providers": {"openai": {"api_key": "vault:openai"}}})["engine"] == ""


def _fake_whisper(tmp_path):
    exe = tmp_path / "whisper-cli"
    exe.write_text("#!/bin/sh\n# prints what it was asked, so the test can see the arguments\n"
                   "echo \"  heard you \"\necho \"$@\" > \"$(dirname \"$0\")/args\"\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    model = tmp_path / "ggml-base.en.bin"
    model.write_bytes(b"model")
    return exe, model


def test_whisper_cpp_is_preferred_and_keeps_the_voice_on_the_machine(tmp_path, monkeypatch):
    import asyncio
    exe, model = _fake_whisper(tmp_path)
    cfg = {"speech": {"hear": {"whisper_bin": str(exe), "whisper_model": str(model)}},
           "providers": {"openai": {"api_key": "sk-x"}}}
    st = hearing.status(cfg)
    assert st["engine"] == "whisper.cpp" and "on this machine" in st["line"]
    text = asyncio.run(hearing.transcribe(cfg, b"RIFF....WAVE", "en-IN"))
    assert text == "heard you"
    args = (tmp_path / "args").read_text().split()
    assert args[args.index("-m") + 1] == str(model) and args[args.index("-l") + 1] == "en"


def test_openai_is_sent_the_audio_and_a_refusal_is_a_sentence(monkeypatch):
    import asyncio
    _no_whisper(monkeypatch)
    sent = {}

    class R:
        def __init__(self, code, js):
            self.status_code, self._js = code, js

        def json(self):
            return self._js

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, data=None, files=None):
            sent.update(url=url, auth=headers["Authorization"], data=data, file=files["file"])
            if headers["Authorization"].endswith("bad"):
                return R(401, {})
            return R(200, {"text": " turn on the lights "})

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", C)
    cfg = {"providers": {"openai": {"api_key": "sk-good"}}}
    assert asyncio.run(hearing.transcribe(cfg, b"WAV", "hi-IN")) == "turn on the lights"
    assert sent["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert sent["data"] == {"model": "whisper-1", "language": "hi"} and sent["file"][1] == b"WAV"
    with pytest.raises(hearing.HearError, match="refused the key"):
        asyncio.run(hearing.transcribe({"providers": {"openai": {"api_key": "sk-bad"}}}, b"WAV"))
    with pytest.raises(hearing.HearError, match="too long"):
        asyncio.run(hearing.transcribe(cfg, b"x" * (hearing.MAX_BYTES + 1)))


# ---------------- the routes ----------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    _no_whisper(monkeypatch)
    with TestClient(servermod.app) as cl:
        yield cl, servermod


def test_the_face_routes_save_audit_and_tell_every_screen(client):
    cl, servermod = client
    assert "face" in cl.get("/api/platform").json(), "the page learns its face with the platform"
    r = cl.put("/api/face", json={"buddy": "on", "kiosk": True, "wake": "name", "hear": "openai"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["buddy"] is True and d["kiosk"] is True and d["hear"]["setting"] == "openai"
    assert cl.get("/api/face").json()["kiosk"] is True
    assert cl.get("/api/platform").json()["face"]["buddy"] is True
    rows = servermod.state["store"].audit_list(action="face.write")
    assert rows, "a change to the screen is a ledger row"
    assert cl.put("/api/face", json={"buddy": "loud"}).status_code == 400
    assert cl.put("/api/face", json={"hear": "parrot"}).status_code == 400
    cl.put("/api/face", json={"buddy": "auto", "kiosk": False, "hear": "auto"})


def test_hearing_with_nothing_to_hear_with_says_what_to_do(client):
    cl, _ = client
    r = cl.post("/api/speech/hear", content=b"RIFF0000WAVE", headers={"Content-Type": "audio/wav"})
    assert r.status_code == 400 and "OpenAI key" in r.json()["error"]
    r = cl.post("/api/speech/hear", content=b"x" * (hearing.MAX_BYTES + 10), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 413


def test_the_terminal_sets_the_face_and_says_it_cannot_draw_it(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path)}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "face", *a], env=env,   # noqa: E731
                                    capture_output=True, text=True, cwd=ROOT)
    r = run("kiosk", "on")
    assert r.returncode == 0 and "kiosk face is on" in r.stdout
    r = run("buddy", "sideways")
    assert r.returncode != 0 and "auto, on, off" in (r.stderr + r.stdout)
    r = run()
    assert "A terminal has no office" in r.stdout
    assert json.loads((tmp_path / "config.json").read_text())["face"]["kiosk"] is True


# ---------------- the page ----------------

def _node(script):
    return subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)


def test_the_name_wakes_it_and_nothing_else_does():
    src = (JS / "24h-kiosk.js").read_text()
    fn = src[src.index("function kioskAddressed"):src.index("function kioskHeard")]
    r = _node(fn + """
const cases=[['Hey Aria, what is on today','Aria'],['aria','Aria'],['Ariadne is here','Aria'],
  ['ok ARIA turn the lights off','Aria'],['nothing to do with you','Aria'],['Hé Zoë, ça va','Zoe']];
console.log(JSON.stringify(cases.map(([t,n])=>kioskAddressed(t,n))));""")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["what is on today", "", None, "turn the lights off", None, "ça va"]


def test_the_recording_is_16khz_mono_wav():
    src = (JS / "24h-kiosk.js").read_text()
    fn = src[src.index("function kioskWav"):src.index("async function kioskSend")]
    r = _node("var KIOSK_RATE=16000;" + fn + """
const a=new Float32Array(48000);for(let i=0;i<a.length;i++)a[i]=Math.sin(i/10)*0.5;
kioskWav([a],48000).arrayBuffer().then(b=>{const d=new DataView(b);
  const s=(o,n)=>String.fromCharCode(...new Uint8Array(b,o,n));
  console.log(JSON.stringify([s(0,4),s(8,4),d.getUint16(22,true),d.getUint32(24,true),d.getUint16(34,true),d.getUint32(40,true)]))});""")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["RIFF", "WAVE", 1, 16000, 16, 32000], "one second at 48 kHz is 16000 samples"


def test_the_kiosk_is_for_the_attached_screen_and_keeps_the_gate_in_view():
    src = (JS / "24h-kiosk.js").read_text()
    wanted = src[src.index("function kioskWanted"):src.index("function kioskApply")]
    assert "remoteClient" in wanted and "#kiosk" in wanted, "a phone keeps its desktop"
    assert "origin:'kiosk'" in src and "type:'chat'" in src, "a kiosk turn is an ordinary gated chat turn"
    assert "speakAs('@agent'" in src, "spoken through the one voice door"
    css = (ROOT / "agentos/ui/src/css/27-kiosk.css").read_text()
    hidden = css[css.index("*/"):css.index("{display:none!important}")]
    assert "ap-float" not in hidden and "toast" not in hidden, "an approval card still shows over the kiosk"
    assert "if(document.body.classList.contains('kiosk')) return {top: 0, bottom: 0};" in (JS / "00-sui.js").read_text()


def test_one_agent_lights_the_lead_for_the_whole_team():
    office_js = (JS / "24d-office.js").read_text()
    m = office_js[office_js.index("function officeMatch"):office_js.index("function officeSay")]
    assert "faceBuddy()" in m and "OFFICE.people['@agent']" in m
    crew = (JS / "01d-crew.js").read_text()
    assert "if(faceBuddy())CREW.cast=[];" in crew
    assert "if(!hit&&faceBuddy())return '@agent';" in crew


def test_the_session_host_grants_the_microphone_and_nothing_else():
    src = (ROOT / "agentos/shellhost.py").read_text()
    h = src[src.index("def on_permission"):src.index('view.connect("permission-request"')]
    assert "UserMediaPermissionRequest" in h and "is-for-audio-device" in h
    assert "not req.get_property(\"is-for-video-device\")" in h and "ours" in h


# ---------------- onboarding: the screen and the wake command ----------------
#
# Asked for as "Kiosk Mode has to be checked at the time of onboarding, also we need to do
# the onboarding of Audio on wake up command". Two steps in the one arc (onboarding.py),
# each ticked on evidence: a decision written down, and a wake word really heard.

def test_python_and_the_page_agree_on_what_wakes_it():
    cases = [("Hey Aria, what is on today", "Aria"), ("aria", "Aria"), ("Ariadne is here", "Aria"),
             ("ok ARIA turn the lights off", "Aria"), ("nothing to do with you", "Aria"),
             ("hey bento, lights", "Hey Bento")]
    src = (JS / "24h-kiosk.js").read_text()
    fn = src[src.index("function kioskAddressed"):src.index("function kioskWakeWords")]
    r = _node(fn + f"console.log(JSON.stringify({json.dumps(cases)}.map(([t,n])=>kioskAddressed(t,n))));")
    assert r.returncode == 0, r.stderr
    page = json.loads(r.stdout)
    server = [(face.addressed(t, [n]) or (None, None))[1] for t, n in cases]
    assert page == server == ["what is on today", "", None, "turn the lights off", None, "lights"]


def test_a_wake_word_of_your_own_and_the_name_both_wake_it():
    cfg = {"agent_name": "Pip"}
    ok, msg = face.set_face(cfg, wake_word="  Hey   Bento ", kiosk=True)
    assert ok and face.wake_words(cfg) == ["Hey Bento", "Pip"] and "“Hey Bento” or “Pip”" in msg
    assert face.addressed("pip, what time is it", face.wake_words(cfg)) == ("Pip", "what time is it")
    assert face.addressed("so hey bento play music", face.wake_words(cfg)) == ("Hey Bento", "play music")
    for bad in ("a whole long sentence that goes on", "1234", "<script>"):
        ok, msg = face.set_face(cfg, wake_word=bad)
        assert not ok and "wake word" in msg
    assert face.set_face(cfg, wake_word="")[0] and face.wake_words(cfg) == ["Pip"]


def test_the_screen_step_is_a_decision_either_way():
    from agentos import onboarding as ob
    st = lambda c: {s["id"]: s for s in ob.state(c)["steps"]}       # noqa: E731
    assert st({})["screen"]["status"] == "todo"
    assert st({"face": {"kiosk": False}})["screen"]["detail"] == "desktop", "the desktop is an answer too"
    assert st({"face": {"kiosk": True, "buddy": "on"}})["screen"]["detail"] == "kiosk · one agent"
    assert [s.id for s in ob.STEPS].index("screen") == [s.id for s in ob.STEPS].index("crew") + 1, \
        "the kiosk IS the office, so it is chosen right after the office"


def test_the_voice_step_ticks_only_when_the_wake_word_was_really_heard(client, monkeypatch):
    cl, servermod = client
    from agentos import onboarding as ob
    servermod.state.machine_cfg().get("face", {}).pop("heard", None)
    r = cl.post("/api/face/wake-test", json={"text": "turn on the lights"})
    assert r.status_code == 200 and r.json()["matched"] is False
    assert not face.heard(servermod.state.machine_cfg()), "words without the wake word prove nothing"
    # the audio road: this machine's speech-to-text understands the recording
    async def fake(cfg, wav, lang=""):
        assert wav.startswith(b"RIFF")
        return "Aria, what time is it?"
    monkeypatch.setattr(hearing, "transcribe", fake)
    monkeypatch.setattr(hearing, "status", lambda cfg: {"engine": "openai", "line": "", "setting": "auto", "have": {}})
    r = cl.post("/api/face/wake-test", content=b"RIFF....WAVEfmt ", headers={"Content-Type": "audio/wav"})
    d = r.json()
    assert d["matched"] and d["word"] == "Aria" and d["after"] == "what time is it?" and d["engine"] == "openai"
    h = face.heard(servermod.state.machine_cfg())
    assert h["word"] == "Aria" and h["engine"] == "openai"
    steps = {s["id"]: s for s in ob.state(servermod.state.machine_cfg())["steps"]}
    assert steps["voice"]["status"] == "done"
    assert servermod.state["store"].audit_list(action="face.write"), "hearing it is a ledger row"
    servermod.state.machine_cfg()["face"].pop("heard", None)


def test_the_terminal_voice_step_records_understands_and_checks(tmp_path, monkeypatch):
    from agentos import setup_tui
    cfg = {"agent_name": "Aria", "providers": {"openai": {"api_key": "k"}}}
    store = Store(tmp_path / "a.db")
    answers = iter(["", "y"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    monkeypatch.setattr(setup_tui, "_save", lambda c: None)
    monkeypatch.setattr(hearing, "recorder", lambda: "arecord")
    monkeypatch.setattr(hearing, "record", lambda secs=5: b"RIFFxxxxWAVE")

    async def fake(c, wav, lang=""):
        return "Aria what time is it"
    monkeypatch.setattr(hearing, "transcribe", fake)
    setup_tui._step_voice(cfg, store)
    assert face.heard(cfg)["word"] == "Aria" and face.heard(cfg)["engine"] == "openai"
    assert "screen" in setup_tui.HANDLERS and "voice" in setup_tui.HANDLERS


def test_the_kiosk_answers_to_every_wake_word():
    src = (JS / "24h-kiosk.js").read_text()
    heard = src[src.index("function kioskHeard"):src.index("async function kioskThread")]
    assert "kioskAddressedAny(text)" in heard and "kioskAddressed(text,name)" not in heard
    one = (JS / "14b-onboarding.js").read_text()
    assert "voiceWakeTest(" in one and "/api/face/wake-test" in src, "the step and Settings prove the same thing"
