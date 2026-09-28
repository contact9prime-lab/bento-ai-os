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


class _Eleven:
    """A stand-in for ElevenLabs: lists two voices, refuses any other id with the 400
    `voice_not_found` shape, and streams audio in chunks."""
    VOICES = ["v-rachel", "v-adam"]

    def __init__(self, calls):
        self.calls = calls

    def client(self):
        outer = self

        class Resp:
            def __init__(self, status, body=b"", js=None):
                self.status_code, self.content, self._js = status, body, js
                self.text = str(js or body)

            def json(self):
                if self._js is None:
                    raise ValueError("no json")
                return self._js

            async def aread(self):
                return self.content

            async def aclose(self):
                pass

            async def aiter_bytes(self):
                for i in range(0, len(self.content), 3):
                    yield self.content[i:i + 3]

        def answer(url, kw):
            outer.calls.append((url, kw))
            if url.endswith("/v1/voices"):
                return Resp(200, js={"voices": [{"voice_id": v, "name": v} for v in outer.VOICES]})
            voice = url.split("/text-to-speech/", 1)[1].split("/", 1)[0]
            if voice not in outer.VOICES:
                return Resp(400, js={"detail": {"status": "voice_not_found",
                                                "message": f"A voice with voice_id {voice} was not found."}})
            return Resp(200, body=b"MP3-" + voice.encode())

        class C:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aclose(self):
                pass

            async def get(self, url, **k):
                return answer(url, k)

            async def post(self, url, **k):
                return answer(url, k)

            def build_request(self, method, url, **k):
                return (url, k)

            async def send(self, req, stream=False):
                return answer(*req)
        return C


def test_a_voice_from_another_engine_is_never_sent_to_elevenlabs(monkeypatch, tmp_path):
    """Reported as "bad request 400 for ElevenLabs": the lead's voice was one field for
    every engine, so a voice picked on OpenAI or this computer went to ElevenLabs as an
    id, and ElevenLabs answered 400 voice_not_found."""
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    calls = []
    monkeypatch.setattr(speech.httpx, "AsyncClient", _Eleven(calls).client())
    cfg = {"providers": {}, "speech": {"engine": "elevenlabs", "voice": "nova",
                                       "agents": {"writer": "gmw/en-US"},
                                       "elevenlabs": {"api_key": "k"}}}
    data, _, who = asyncio.run(speech.speak(cfg, "hello", lead=True))
    assert who["voice"] in _Eleven.VOICES and data.startswith(b"MP3-")
    _, _, who = asyncio.run(speech.speak(cfg, "hello there", agent="writer"))
    assert who["voice"] in _Eleven.VOICES, "a pin from another engine is not an ElevenLabs id"
    # the lead's voice now belongs to the engine it was picked on
    speech.save(cfg, {"voice": "v-adam"})
    assert cfg["speech"]["elevenlabs"]["voice"] == "v-adam" and speech.public(cfg)["voice"] == "v-adam"
    speech.save(cfg, {"engine": "openai"})
    assert speech.public(cfg)["voice"] == "", "OpenAI does not inherit ElevenLabs' voice"


def test_a_voice_the_account_lost_is_replaced_and_a_refusal_reads(monkeypatch, tmp_path):
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    calls = []
    monkeypatch.setattr(speech.httpx, "AsyncClient", _Eleven(calls).client())
    cfg = {"providers": {}, "speech": {"engine": "elevenlabs", "elevenlabs": {"api_key": "k"}}}
    # asked for a voice the account does not have: the sentence, not a raw body
    with pytest.raises(speech.VoiceMissing, match="does not have that voice"):
        asyncio.run(speech.speak(cfg, "hi", voice="gone-voice"))
    # a pinned voice that has gone: said with another voice the account lists
    monkeypatch.setattr(speech, "_resolve", _pinned("gone-voice"))
    _, _, who = asyncio.run(speech.speak(cfg, "still said", agent="writer"))
    assert who["voice"] in _Eleven.VOICES

    class R:
        status_code = 401

        def json(self):
            return {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}
    e = speech._refusal("elevenlabs", R())
    assert "Invalid API key" in str(e) and "Paste it again" in str(e)
    R.status_code = 400
    R.json = lambda self: {"detail": {"status": "quota_exceeded", "message": "You have 3 credits left"}}
    assert "out of credits" in str(speech._refusal("elevenlabs", R()))
    R.json = lambda self: {"detail": {"status": "missing_permissions", "message": "needs text_to_speech"}}
    assert "Allow Text to Speech" in str(speech._refusal("elevenlabs", R()))


def _pinned(voice):
    async def resolve(cfg, engine, agent, lead, v):
        return voice, list(_Eleven.VOICES) + [voice]
    return resolve


def test_a_line_streams_while_it_is_made(monkeypatch, tmp_path):
    """Speaking as it answers: the provider's stream is opened and checked first, then
    handed on chunk by chunk, and kept so a replay costs nothing."""
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    calls = []
    monkeypatch.setattr(speech.httpx, "AsyncClient", _Eleven(calls).client())
    cfg = {"providers": {}, "speech": {"engine": "elevenlabs", "elevenlabs": {"api_key": "k"}}}

    async def take(st):
        return [c async for c in st["chunks"]]
    st = asyncio.run(speech.open_stream(cfg, "first sentence.", lead=True))
    url, kw = calls[-1]
    assert url.endswith("/stream") and kw["json"]["model_id"] == speech.ELEVEN_FAST_MODEL
    parts = asyncio.run(take(st))
    assert len(parts) > 1 and b"".join(parts).startswith(b"MP3-")
    said = lambda: sum(1 for u, _ in calls if "/text-to-speech/" in u)      # noqa: E731
    n = said()
    again = asyncio.run(speech.open_stream(cfg, "first sentence.", lead=True))
    assert again["who"]["cached"] and said() == n, "a replay costs nothing"
    cfg["speech"]["elevenlabs"]["voice"] = "missing"
    monkeypatch.setattr(speech, "voices", lambda *a, **k: _raise())
    with pytest.raises(speech.VoiceMissing):
        asyncio.run(speech.open_stream(cfg, "another line.", lead=True))


async def _raise():
    raise RuntimeError("cannot read voices")


def test_the_page_speaks_as_it_answers():
    v = (JS / "08-wallpaper-jarvis-voice.js").read_text()
    door = v.split("function speakAs(", 1)[1].split("\n}", 1)[0]
    assert "/api/speech/line" in door and "/api/speech/stream/" in door
    ws = (JS / "09-websocket.js").read_text()
    assert "speechLiveFeed(_cid,curText)" in ws and "speechLiveTool(_cid,ev)" in ws
    assert "speechLiveEnd(_cid,reply" in ws
    srv = (ROOT / "agentos/server.py").read_text()
    assert '@app.post("/api/speech/line")' in srv and '@app.get("/api/speech/stream/{lid}")' in srv
    stream = srv.split('@app.get("/api/speech/stream/{lid}")', 1)[1].split("\n@app.", 1)[0]
    assert 't["uid"] != (usersmod.current()' in stream, "only its owner may collect a line"
    settings = (JS / "11-settings.js").read_text()
    assert "pSwitch('v-live'" in settings


def test_live_sentences_in_node():
    """speechLiveFeed says whole sentences only, waits for a code block to close, and
    speechLiveEnd says what is left."""
    import json
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    v = (JS / "08-wallpaper-jarvis-voice.js").read_text()
    body = "\n".join(v.split("\n")[v.split("\n").index(next(l for l in v.split("\n")
                     if l.startswith("var SPEECH_LIVE="))):])
    body = body.split("\nvar VOICE_AGENTS=", 1)[0]
    js = ("var said=[];var VOICE={tts:true};var JARVIS={on:false,busy:false};"
          "var SPEECH={gen:0,pending:0,chain:Promise.resolve()};function speechStop(){}"
          "function speakAs(n,t){said.push(t.trim())}\n" + body +
          "\nspeechLiveFeed('c','Hello there, I found three things. The first one is");
    js += ("');speechLiveFeed('c','Hello there, I found three things. The first one is big. ```py\\nx=1');"
           "speechLiveFeed('c','Hello there, I found three things. The first one is big. ```py\\nx=1\\n``` Done now.');"
           "speechLiveEnd('c','Hello there, I found three things. The first one is big. ```py\\nx=1\\n``` Done now. Bye');"
           "console.log(JSON.stringify(said))")
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    said = json.loads(out.stdout)
    assert said[0] == "Hello there, I found three things."
    # a short sentence waits for company; the code block is read as words, never as code
    assert said[1].startswith("The first one is big.") and "code block" in said[1]
    assert "x=1" not in " ".join(said)
    assert said[-1].endswith("Bye")
