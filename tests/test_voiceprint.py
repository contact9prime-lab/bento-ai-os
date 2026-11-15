"""A person's voice print (voiceprint.py): only an enrolled voice wakes the screen, and onboarding
names the agent Bento. Asked for as "when onboarding change the name from Aria to Bento, also ask
the user to record the recognition word for waking, by getting the signature voice print. This
should be done by the system for the user signed in." The owner chose: a filter, never a key, and
the speaker model as an install."""
import io
import json
import math
import struct
import wave
from pathlib import Path

import pytest

from agentos import components, config as cfgmod, onboarding, users, voiceprint

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _wav(seconds=2.0, hz=180.0, amp=0.3, rate=16000):
    n = int(seconds * rate)
    raw = struct.pack("<%dh" % n, *(int(32767 * amp * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)))
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(raw)
    return b.getvalue()


@pytest.fixture
def model(monkeypatch):
    """The model stands in as: the tone's pitch decides the direction of the numbers, so two
    recordings of one 'voice' are alike and two voices are not."""
    def embed(wav):
        rate, s = voiceprint.read_wav(wav)
        crossings = sum(1 for a, b in zip(s, s[1:]) if a < 0 <= b)
        hz = crossings / (len(s) / rate)
        ang = (hz - 100) / 400 * (math.pi / 2)
        return [math.cos(ang), math.sin(ang), 0.01]
    monkeypatch.setattr(voiceprint, "embed", embed)
    monkeypatch.setattr(voiceprint, "ready", lambda: True)


def test_three_recordings_make_a_print_and_only_that_voice_matches(tmp_path, model):
    assert voiceprint.match(tmp_path, _wav())["match"] is None, "no print: no verdict, never a guess"
    for i, hz in enumerate((180, 184, 178), 1):
        got = voiceprint.enroll(tmp_path, _wav(hz=hz))
        assert got["samples"] == i and got["enrolled"] == (i >= voiceprint.NEED)
    assert voiceprint.enrolled(tmp_path)
    assert voiceprint.match(tmp_path, _wav(hz=182))["match"] is True
    other = voiceprint.match(tmp_path, _wav(hz=460))
    assert other["match"] is False and other["score"] < voiceprint.THRESHOLD
    f = tmp_path / voiceprint.FILE
    assert f.stat().st_mode & 0o777 == 0o600, "the print is the person's: nobody else on the machine reads it"
    assert set(json.loads(f.read_text())) == {"v", "model", "vectors", "at"}, "numbers only: no recording is kept"
    assert voiceprint.forget(tmp_path) and not voiceprint.enrolled(tmp_path)


def test_somebody_else_speaking_during_enrolment_is_refused_not_averaged_in(tmp_path, model):
    voiceprint.enroll(tmp_path, _wav(hz=180))
    with pytest.raises(voiceprint.PrintError, match="did not sound like your earlier recordings"):
        voiceprint.enroll(tmp_path, _wav(hz=499))
    assert len(json.loads((tmp_path / voiceprint.FILE).read_text())["vectors"]) == 1


def test_a_recording_that_cannot_be_judged_says_why(tmp_path):
    for wav, says in ((_wav(seconds=0.5), "seconds"), (_wav(amp=0.0005), "almost silent"),
                      (b"not a wav at all", "not a recording"), (_wav(seconds=40), "too long")):
        with pytest.raises(voiceprint.PrintError, match=says):
            voiceprint.read_wav(wav)


def test_the_status_never_claims_a_filter_that_is_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(voiceprint, "ready", lambda: False)
    st = voiceprint.status({"voiceprint": {"only": True}}, tmp_path)
    assert not st["available"] and st["install"] == voiceprint.COMPONENT and st["idle"]
    assert "speaker model" in st["line"] and "vectors" not in st
    assert not voiceprint.filtering({"voiceprint": {"only": True}}, tmp_path)
    monkeypatch.setattr(voiceprint, "ready", lambda: True)
    assert "3 times" in voiceprint.status({}, tmp_path)["line"]


def test_the_model_is_asked_for_never_shipped():
    row = next(r for r in components.catalog() if r["id"] == voiceprint.COMPONENT)
    assert "Apache-2.0" in row["licence"] and not row.get("needs_root")
    assert "never signs anybody in" in row["unlocks"]
    script = components._voiceprint_script()
    assert "--target" in script and str(voiceprint.base()) in script and voiceprint.MODEL_URL in script
    assert ".part" in script, "a download cut short never becomes the model"
    # a dependency of the program it is not: uv sync would remove it, and the licence audit never sees it
    assert "sherpa" not in (ROOT / "pyproject.toml").read_text().lower()


def test_it_is_a_filter_and_the_print_is_the_persons():
    assert "voiceprint" in users.USER_KEYS and cfgmod.DEFAULTS["voiceprint"] == {"only": False}
    src = (ROOT / "agentos/server.py").read_text()
    hear = src.split('@app.post("/api/speech/hear")')[1].split("\n@app.")[0]
    assert "voiceprint.filtering(state[\"cfg\"], home)" in hear and 'out["voice"]' in hear
    block = src.split("# ---- a person's voice print")[1].split('@app.post("/api/speech/hear")')[0]
    assert "usersmod.home_for(usersmod.current() or \"\")" in block, "whoever is signed in, never a name in the request"
    for word in ("login", "set_cookie", "as_user(uid", "add_grant"):
        assert word not in block, "a voice never signs anybody in or grants anything"
    assert '"vectors"' not in block, "no route returns the print"
    kiosk = (JS / "24h-kiosk.js").read_text()
    assert "d.voice&&d.voice.match!==true&&text" in kiosk and "not a voice I know" in kiosk
    from agentos import protected
    assert voiceprint.FILE not in protected.HOME_READABLE, "an agent cannot read it: the home is closed by allow-list"


def test_the_routes_enrol_whoever_is_signed_in(model, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from agentos import hearing, server
    monkeypatch.setattr(server, "_voice_home", lambda: tmp_path)
    monkeypatch.setattr(hearing, "status", lambda cfg: {"engine": ""})          # nothing here understands speech
    with TestClient(server.app) as c:
        assert c.put("/api/voiceprint", json={"only": True}).status_code == 400, "no print to filter with"
        for i in range(3):
            r = c.post("/api/voiceprint/enroll", content=_wav(hz=180 + i), headers={"Content-Type": "audio/wav"})
            assert r.status_code == 200 and r.json()["samples"] == i + 1
        st = c.get("/api/voiceprint").json()
        assert st["enrolled"] and st["only"], "the third recording switches the filter on"
        assert "vectors" not in json.dumps(st)
        assert c.put("/api/voiceprint", json={"only": False}).json()["only"] is False
        assert c.delete("/api/voiceprint").json()["samples"] == 0
        c.put("/api/voiceprint", json={"only": False})


def test_a_recording_without_the_wake_word_is_not_enrolled(model, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from agentos import hearing, server
    monkeypatch.setattr(server, "_voice_home", lambda: tmp_path)
    monkeypatch.setattr(hearing, "status", lambda cfg: {"engine": "whisper.cpp"})

    async def heard(cfg, wav, lang=""):
        return "what is the weather"
    monkeypatch.setattr(hearing, "transcribe", heard)
    with TestClient(server.app) as c:
        r = c.post("/api/voiceprint/enroll", content=_wav(), headers={"Content-Type": "audio/wav"})
        assert r.status_code == 400 and "but not" in r.json()["error"]
    assert not (tmp_path / voiceprint.FILE).exists()


# ---- the name ------------------------------------------------------------------------------

def test_a_new_machine_is_bento_and_one_already_set_up_keeps_its_name(tmp_path, monkeypatch):
    assert cfgmod.DEFAULTS["agent_name"] == "Bento" and onboarding.DEFAULT_NAME == "Bento"
    p = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", p)
    assert cfgmod.load_config()["agent_name"] == "Bento", "nothing saved yet: the new default"
    p.write_text(json.dumps({"setup_complete": True}))
    assert cfgmod.load_config()["agent_name"] == "Aria", "set up before the change and never renamed: still Aria"
    p.write_text(json.dumps({"agent_name": "Juno"}))
    assert cfgmod.load_config()["agent_name"] == "Juno"


def test_every_face_offers_the_voice_print():
    kiosk = (JS / "24h-kiosk.js").read_text()
    assert "function voicePrintHTML(" in kiosk and "/api/voiceprint/enroll" in kiosk
    assert "It never signs anybody in" in kiosk, "the limit is said where the print is offered"
    assert "voicePrintHTML(await voicePrintLoad()" in (JS / "14b-onboarding.js").read_text()
    assert "id=\"s-vp\"" in kiosk
    main = (ROOT / "agentos/__main__.py").read_text()
    assert "def _voiceprint_cli(cfg, rest):" in main and '"print"' in main
    assert "def _voice_print(cfg, word: str)" in (ROOT / "agentos/setup_tui.py").read_text()
