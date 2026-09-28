"""Speech engines: this browser, this computer, ElevenLabs, OpenAI or Google Cloud.

Asked for as "which TTS are they using? Can we use some system TTS, or ElevenLabs, or
Google?". What these defend:

- every agent keeps its own voice on every engine, the lead keeps the chosen one, and
  a person's pin wins;
- a key is saved but never shown back, and the OpenAI provider's key is reused;
- each cloud engine is asked in its own documented shape, and a refusal is a sentence;
- a line is cached, so a replay costs nothing;
- the system pool is the chosen language only (found by listening: the lead came out
  Afrikaans reading English);
- the page speaks through one door and falls back to the browser with the reason.
"""
import asyncio
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import speech                                  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "agentos" / "ui" / "src" / "js"


def test_each_agent_keeps_its_own_voice():
    pool = ["a", "b", "c", "d"]
    r1 = speech.pick("researcher", False, pool, "a", {})
    assert r1 == speech.pick("researcher", False, pool, "a", {}), "the same every time"
    assert r1 != "a", "a specialist never borrows the lead's voice while there are others"
    names = ["researcher", "writer", "validator", "analyst", "engineer"]
    assert len({speech.pick(n, False, pool, "a", {}) for n in names}) > 1
    assert speech.pick("", True, pool, "c", {}) == "c"
    assert speech.pick("writer", False, pool, "a", {"writer": "d"}) == "d"


def test_a_key_is_saved_and_never_shown():
    cfg = {"providers": {}}
    got = speech.save(cfg, {"engine": "elevenlabs", "keys": {"elevenlabs": "sk-secret-123"}})
    assert got["keys"]["elevenlabs"] is True and "sk-secret" not in str(got)
    assert cfg["speech"]["elevenlabs"]["api_key"] == "sk-secret-123"
    speech.save(cfg, {"keys": {"elevenlabs": "•••123"}})          # a mask sent back is not a key
    assert cfg["speech"]["elevenlabs"]["api_key"] == "sk-secret-123"
    speech.save(cfg, {"keys": {"elevenlabs": ""}})
    assert not speech.public(cfg)["keys"]["elevenlabs"]
    with pytest.raises(ValueError):
        speech.save(cfg, {"engine": "carrier-pigeon"})
    # the OpenAI provider's key is the same account
    cfg2 = {"providers": {"openai": {"api_key": "sk-prov"}}}
    assert speech._key(cfg2, "openai") == "sk-prov" and speech.public(cfg2)["openai_from_provider"]


class _Resp:
    def __init__(self, status=200, content=b"MP3", js=None):
        self.status_code, self.content, self._js, self.text = status, content, js or {}, "no"

    def json(self):
        return self._js

    def raise_for_status(self):
        pass


def _fake_client(calls, resp):
    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **k):
            calls.append((url, k))
            return resp

        async def get(self, url, **k):
            calls.append((url, k))
            return resp
    return C


def test_each_cloud_is_asked_in_its_own_shape(monkeypatch, tmp_path):
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    calls = []
    monkeypatch.setattr(speech.httpx, "AsyncClient", _fake_client(calls, _Resp()))
    cfg = {"providers": {}, "speech": {"engine": "elevenlabs", "elevenlabs": {"api_key": "k1"}}}
    data, mime, who = asyncio.run(speech.speak(cfg, "hello", voice="v-1"))
    assert data == b"MP3" and mime == "audio/mpeg" and who["engine"] == "elevenlabs"
    url, k = calls[-1]
    assert url.endswith("/v1/text-to-speech/v-1") and k["headers"]["xi-api-key"] == "k1"
    assert k["json"]["model_id"] == speech.ELEVEN_MODEL

    cfg["speech"] = {"engine": "openai", "openai": {"api_key": "k2"}}
    asyncio.run(speech.speak(cfg, "hi there", voice="nova"))
    url, k = calls[-1]
    assert url == "https://api.openai.com/v1/audio/speech"
    assert k["json"] == {"model": speech.OPENAI_MODEL, "voice": "nova", "input": "hi there",
                         "response_format": "mp3"}

    monkeypatch.setattr(speech.httpx, "AsyncClient", _fake_client(
        calls, _Resp(js={"audioContent": base64.b64encode(b"G").decode()})))
    cfg["speech"] = {"engine": "google", "google": {"api_key": "k3"}, "language": "en-GB"}
    data, _, _ = asyncio.run(speech.speak(cfg, "hello google", voice="en-GB-Neural2-A"))
    url, k = calls[-1]
    assert data == b"G" and url.endswith("/v1/text:synthesize") and k["params"]["key"] == "k3"
    assert k["json"]["voice"] == {"languageCode": "en-GB", "name": "en-GB-Neural2-A"}


def test_a_refusal_is_a_sentence_and_a_replay_is_free(monkeypatch, tmp_path):
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    calls = []
    monkeypatch.setattr(speech.httpx, "AsyncClient", _fake_client(calls, _Resp(status=401)))
    cfg = {"providers": {}, "speech": {"engine": "openai", "openai": {"api_key": "bad"}}}
    with pytest.raises(RuntimeError, match="OpenAI refused"):
        asyncio.run(speech.speak(cfg, "hello", voice="alloy"))
    with pytest.raises(RuntimeError, match="needs an API key"):
        asyncio.run(speech.speak({"providers": {}, "speech": {"engine": "elevenlabs"}}, "hi", voice="x"))
    with pytest.raises(RuntimeError, match="browser speaks for itself"):
        asyncio.run(speech.speak({"speech": {"engine": "browser"}}, "hi"))

    monkeypatch.setattr(speech.httpx, "AsyncClient", _fake_client(calls, _Resp()))
    cfg["speech"]["openai"]["api_key"] = "good"
    n = len(calls)
    asyncio.run(speech.speak(cfg, "say it once", voice="alloy"))
    _, _, who = asyncio.run(speech.speak(cfg, "say it once", voice="alloy"))
    assert who["cached"] and len(calls) == n + 1, "the second time costs nothing"


def test_the_system_pool_is_the_chosen_language(monkeypatch, tmp_path):
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(speech, "system_voices", lambda: [
        {"id": "gmw/af", "lang": "af"}, {"id": "en-029", "lang": "en-029"},
        {"id": "gmw/en-US", "lang": "en-us"}, {"id": "en+m3", "lang": "en"}, {"id": "zle/ru", "lang": "ru"}])
    said = []
    monkeypatch.setattr(speech, "_system_speak", lambda text, voice: (said.append(voice) or (b"W", "audio/wav")))
    cfg = {"speech": {"engine": "system", "language": "en-US"}}
    asyncio.run(speech.speak(cfg, "one", lead=True))
    asyncio.run(speech.speak(cfg, "two", agent="researcher"))
    asyncio.run(speech.speak(cfg, "three", agent="writer"))
    assert said[0] == "gmw/en-US", "the lead speaks the exact language by default"
    assert all(v.startswith(("en", "gmw/en")) for v in said), said


def test_one_door_on_the_page_and_the_terminal():
    v = (JS / "08-wallpaper-jarvis-voice.js").read_text()
    door = v.split("function speakAs(", 1)[1].split("\n}", 1)[0]
    assert "/api/speech/say" in door and "browserSay(name,clean)" in door, "falls back to the browser"
    assert "speechSynthesis.cancel()" not in door
    core = (JS / "00-core.js").read_text()
    assert "speakAs('@agent'" in core.split("function jarvisSpeakAndListen(", 1)[1].split("\n}", 1)[0]
    srv = (ROOT / "agentos/server.py").read_text()
    for r in ('@app.get("/api/speech")', '@app.put("/api/speech")', '@app.get("/api/speech/voices")',
              '@app.post("/api/speech/say")'):
        assert r in srv, r
    put = srv.split('@app.put("/api/speech")', 1)[1].split("\n@app.", 1)[0]
    assert "is_admin" in put, "a cloud voice spends money: the machine's setting"
    assert (JS / "11f-speech.js").exists()
    main = (ROOT / "agentos/__main__.py").read_text()
    assert 'verb("voice"' in main and "speech.speak(cfg" in main
