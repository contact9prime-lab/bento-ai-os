"""The key that speaks is the key that hears, and setup installs what hearing needs.

Asked for as "if the voice is configured, then it should take it from there or configure
from voice, and if any dependency is needed it should do it at the time of onboarding",
with a screenshot: ElevenLabs set up under Voice, and the kiosk saying nothing here can
understand speech. hearing.py now hears with the voice service under Settings → Voice
(ElevenLabs Scribe, OpenAI, Google Cloud Speech-to-Text), and components.py offers
whisper.cpp and a recorder, which the setup step installs on a yes.
"""
import asyncio
import base64
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentos import components, hearing                         # noqa: E402

JS = ROOT / "agentos/ui/src/js"


@pytest.fixture(autouse=True)
def no_whisper(monkeypatch, tmp_path):
    monkeypatch.setattr(hearing.shutil, "which", lambda b: None)
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(hearing, "MODEL_DIR", tmp_path / "no-models")


class _R:
    def __init__(self, code, js=None, text=""):
        self.status_code, self._js, self.text = code, js or {}, text or str(js or "")

    def json(self):
        return self._js


def _client(monkeypatch, answer):
    """A stand-in httpx.AsyncClient: records what was sent, answers with `answer(sent)`."""
    calls = []

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            calls.append({"url": url, **kw})
            return answer(calls[-1])

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", C)
    return calls


def _voice(engine, **keys):
    return {"speech": {"engine": engine, **{k: {"api_key": v} for k, v in keys.items()}}}


def test_the_screenshot_an_elevenlabs_voice_hears_too():
    st = hearing.status(_voice("elevenlabs", elevenlabs="xi-key"))
    assert st["engine"] == "elevenlabs"
    assert st["line"] == ("Speech is understood by ElevenLabs, with the key under Voice. "
                          "It costs a little per minute of audio.")


def test_the_voice_engine_is_tried_first_and_whisper_before_it(tmp_path):
    cfg = _voice("google", elevenlabs="xi", google="g")
    assert hearing.status(cfg)["engine"] == "google", "the engine chosen for speaking hears first"
    cfg["speech"]["engine"] = "browser"
    assert hearing.status(cfg)["engine"] == "elevenlabs"
    exe = tmp_path / "whisper-cli"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"m")
    cfg["speech"]["hear"] = {"whisper_bin": str(exe), "whisper_model": str(model)}
    assert hearing.status(cfg)["engine"] == "whisper.cpp", "nothing leaves the machine when it need not"
    cfg["speech"]["hear"]["engine"] = "elevenlabs"
    assert hearing.status(cfg)["engine"] == "elevenlabs", "a person's choice wins"


def test_an_openai_key_under_voice_counts_as_well_as_the_provider_one():
    assert hearing.status(_voice("openai", openai="sk-voice"))["engine"] == "openai"
    assert hearing._openai(_voice("openai", openai="sk-voice")) == ("https://api.openai.com/v1", "sk-voice")
    assert "AI providers" in hearing.status({"providers": {"openai": {"api_key": "sk-p"}}})["line"]


def test_a_deaf_machine_names_both_fixes():
    st = hearing.status({})
    assert st["engine"] == "" and st["install"] == ["whisper-cpp"]
    assert "whisper.cpp" in st["line"] and "ElevenLabs, OpenAI or Google Cloud key under Voice" in st["line"]
    st = hearing.status({"speech": {"hear": {"engine": "elevenlabs"}}})
    assert st["line"] == "ElevenLabs cannot listen here: there is no ElevenLabs key under Voice."


def test_elevenlabs_is_sent_the_audio_and_an_older_model_is_tried(monkeypatch):
    def answer(sent):
        if sent["data"]["model_id"] == "scribe_v2":
            return _R(422, {"detail": {"message": "invalid model_id"}}, "invalid model_id")
        return _R(200, {"text": " Aria, lights on "})
    calls = _client(monkeypatch, answer)
    text = asyncio.run(hearing.transcribe(_voice("elevenlabs", elevenlabs="xi-key"), b"RIFFWAVE", "en-IN"))
    assert text == "Aria, lights on"
    assert [c["data"]["model_id"] for c in calls] == ["scribe_v2", "scribe_v1"]
    assert calls[0]["url"] == "https://api.elevenlabs.io/v1/speech-to-text"
    assert calls[0]["headers"] == {"xi-api-key": "xi-key"} and calls[0]["data"]["language_code"] == "en"
    assert calls[0]["files"]["file"][1] == b"RIFFWAVE"


def test_elevenlabs_refusals_are_sentences(monkeypatch):
    _client(monkeypatch, lambda s: _R(401, {}))
    with pytest.raises(hearing.HearError, match="refused the key under Voice"):
        asyncio.run(hearing.transcribe(_voice("elevenlabs", elevenlabs="bad"), b"W"))
    _client(monkeypatch, lambda s: _R(429, {"detail": {"message": "quota exceeded"}}))
    with pytest.raises(hearing.HearError, match="429: quota exceeded"):
        asyncio.run(hearing.transcribe(_voice("elevenlabs", elevenlabs="k"), b"W"))


def test_google_reads_the_wav_header_and_joins_the_results(monkeypatch):
    calls = _client(monkeypatch, lambda s: _R(200, {"results": [
        {"alternatives": [{"transcript": "Aria what"}]}, {"alternatives": [{"transcript": " time is it"}]}]}))
    cfg = _voice("google", google="g-key")
    cfg["speech"]["language"] = "en-IN"
    assert asyncio.run(hearing.transcribe(cfg, b"RIFFWAVE")) == "Aria what time is it"
    c = calls[0]
    assert c["url"] == "https://speech.googleapis.com/v1/speech:recognize" and c["params"] == {"key": "g-key"}
    assert c["json"]["config"] == {"languageCode": "en-IN"}, "encoding and rate come from the WAV header"
    assert base64.b64decode(c["json"]["audio"]["content"]) == b"RIFFWAVE"
    _client(monkeypatch, lambda s: _R(403, {}, "Cloud Speech-to-Text API has not been used in project 1 "
                                                "before or it is disabled. SERVICE_DISABLED"))
    with pytest.raises(hearing.HearError, match="turn on the Cloud Speech-to-Text API"):
        asyncio.run(hearing.transcribe(cfg, b"W"))


# ---- what setup installs ------------------------------------------------------------------

def test_whisper_cpp_is_offered_with_its_licence_and_built_in_your_home(monkeypatch):
    c = components.CATALOG["whisper-cpp"]
    assert c["licence"].startswith("MIT") and c["needs_root"] is False and c["group"] == "optional"
    script = components.WHISPER_SCRIPT
    assert "github.com/ggml-org/whisper.cpp" in script and "brew install whisper.cpp" in script
    assert "--target whisper-cli" in script and ".part" in script, "a cut download is never a model"
    assert '$HOME/.local/share/whisper.cpp/models' in script


def test_no_build_tools_means_a_sentence_not_a_button(monkeypatch):
    monkeypatch.setattr(components.shutil, "which", lambda b: "/usr/bin/curl" if b == "curl" else None)
    c = components.CATALOG["whisper-cpp"]
    assert components.install_argv(c) == []
    assert "sudo apt install git cmake build-essential" in components.unavailable_reason(c)
    monkeypatch.setattr(components.shutil, "which", lambda b: f"/usr/bin/{b}")
    assert components.install_argv(c)[:2] == ["sh", "-c"]


def test_whisper_installed_by_the_component_is_found_off_the_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    exe = home / ".local/bin/whisper-cli"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    models = tmp_path / "models"
    models.mkdir()
    (models / "ggml-base.bin").write_bytes(b"m")
    monkeypatch.setattr(hearing, "MODEL_DIR", models)
    assert hearing._whisper({}) == (str(exe), str(models / "ggml-base.bin"))
    assert components._whisper_ready()


def test_a_recorder_is_a_component_for_the_terminal_check():
    c = components.CATALOG["alsa-utils"]
    assert all(c["packages"].get(f) == "alsa-utils" for f in components.FAMILIES)


def test_setup_offers_the_fixes_on_every_face():
    page = (JS / "14b-onboarding.js").read_text()
    assert "installComponent('whisper-cpp')" in page and "'/api/speech'" in page
    assert "hearChoices()" in page
    kiosk = (JS / "24h-kiosk.js").read_text()
    assert "function hearChoices" in kiosk and "'elevenlabs','ElevenLabs'" in kiosk
    assert "hearFixHTML" in kiosk
    tui = (ROOT / "agentos/setup_tui.py").read_text()
    assert '_offer_component("whisper-cpp")' in tui and '_offer_component("alsa-utils")' in tui


def test_the_terminal_step_saves_a_voice_key_and_then_hears(tmp_path, monkeypatch):
    from agentos import setup_tui
    cfg = {"agent_name": "Aria"}
    answers = iter(["", "1", "1"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    monkeypatch.setattr(setup_tui.getpass, "getpass", lambda *_: "xi-typed")
    monkeypatch.setattr(setup_tui, "_save", lambda c: None)
    monkeypatch.setattr(hearing, "recorder", lambda: "")
    monkeypatch.setattr(setup_tui, "_offer_component", lambda cid: False)
    from agentos.memory import Store
    setup_tui._step_voice(cfg, Store(tmp_path / "a.db"))
    assert cfg["speech"]["elevenlabs"]["api_key"] == "xi-typed" and cfg["speech"]["engine"] == "elevenlabs"
    assert hearing.status(cfg)["engine"] == "elevenlabs"
