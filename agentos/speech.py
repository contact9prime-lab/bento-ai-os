"""Speech: which engine reads your agents' words aloud, and in which voice.

The desktop's voice used to be the browser's own speech (`speechSynthesis`), and it
still is the default: free, offline, nothing to set up. Asked for as "can we use some
system TTS, or ElevenLabs, or Google?", this is the other half: the server turns text
into audio with one of

- **system**: this computer's own voices. macOS `say`, Linux `piper` or `espeak-ng`,
  Windows' built-in speech through PowerShell. Offline and free; the voices are the
  machine's.
- **elevenlabs**, **openai**, **google**: the cloud voices. They need a key and cost
  money per character, so they are the MACHINE's setting (who pays), like a provider key.

Four things keep it honest:

- **Every agent keeps its own voice on every engine.** `pick` chooses from the
  engine's voice list by the agent's name, so the researcher sounds the same every time
  and different from the writer; the lead keeps the voice chosen in Settings, and a
  person can pin any agent to a voice (`speech.agents`).
- **Nothing is said twice for money.** The audio is cached by (engine, voice, text) in
  the home folder, bounded (`CACHE_FILES`), so a replayed thread costs nothing.
- **A key never leaves the server.** `/api/speech` says which keys are set,
  never their value, and the page plays bytes, never calls a provider itself.
- **An engine that cannot speak says why.** `status()` probes each one; the page falls
  back to the browser's voice with that sentence rather than going silent.

Kept free of the web framework: `bento voice` uses the same functions from a terminal.
"""

from __future__ import annotations

import base64
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

ENGINES = ("browser", "system", "elevenlabs", "openai", "google")
TITLES = {"browser": "This browser", "system": "This computer", "elevenlabs": "ElevenLabs",
          "openai": "OpenAI", "google": "Google Cloud"}
#: the model each cloud engine is asked for (checked against each provider's docs)
ELEVEN_MODEL = "eleven_multilingual_v2"
#: the low-latency model, for a line spoken while the reply is still arriving
ELEVEN_FAST_MODEL = "eleven_flash_v2_5"
#: engines whose audio can be played while the provider is still making it
STREAMING = ("elevenlabs", "openai")
OPENAI_MODEL = "gpt-4o-mini-tts"
OPENAI_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx",
                 "sage", "shimmer", "verse")
MAX_CHARS = 1200            # one line of an agent, not a document
CACHE_FILES = 300
TIMEOUT = 30.0


def conf(cfg: dict) -> dict:
    c = cfg.setdefault("speech", {})
    c.setdefault("engine", "browser")
    # The lead's voice is kept PER ENGINE (`speech.<engine>.voice`). It was one field for
    # every engine, so a voice picked on OpenAI ("nova") or this computer ("gmw/en-US")
    # was sent to ElevenLabs as a voice id, and ElevenLabs answered 400 "voice does not
    # exist". A top-level `voice` from before is only a candidate, used when the engine
    # actually lists it (`_usable`).
    c.setdefault("voice", "")
    c.setdefault("agents", {})              # name -> voice, pinned by a person
    c.setdefault("language", "en-US")
    return c


def lead_voice(cfg: dict, engine: str | None = None) -> str:
    """The lead's chosen voice on this engine ('' = pick one for me)."""
    c = conf(cfg)
    engine = engine or c["engine"]
    return str((c.get(engine) or {}).get("voice") or "") if isinstance(c.get(engine), dict) else ""


def _key(cfg: dict, engine: str) -> str:
    c = conf(cfg)
    k = str((c.get(engine) or {}).get("api_key") or "")
    if not k and engine == "openai":
        # the OpenAI provider's key is the same account: no second key to paste
        k = str(((cfg.get("providers") or {}).get("openai") or {}).get("api_key") or "")
    return k


def public(cfg: dict) -> dict:
    """The settings as the page may see them: which keys are set, never a value."""
    c = conf(cfg)
    return {"engine": c["engine"], "voice": lead_voice(cfg), "language": c.get("language", "en-US"),
            "agents": dict(c.get("agents") or {}),
            "keys": {e: bool(_key(cfg, e)) for e in ("elevenlabs", "openai", "google")},
            "openai_from_provider": bool(_key(cfg, "openai")) and not (c.get("openai") or {}).get("api_key")}


def save(cfg: dict, patch: dict) -> dict:
    """Change the speech settings. A key is written only when one is given, so saving
    the page without retyping it keeps the key."""
    c = conf(cfg)
    p = patch or {}
    if "engine" in p:
        if p["engine"] not in ENGINES:
            raise ValueError(f"engine is one of: {', '.join(ENGINES)}")
        c["engine"] = p["engine"]
    if "language" in p:
        c["language"] = str(p["language"] or "")[:120]
    if "voice" in p:
        # the voice belongs to the engine it was picked on
        c.setdefault(c["engine"], {})["voice"] = str(p["voice"] or "")[:120]
    if isinstance(p.get("agents"), dict):
        c["agents"] = {str(n)[:60]: str(v)[:120] for n, v in p["agents"].items() if v}
    for e in ("elevenlabs", "openai", "google"):
        k = (p.get("keys") or {}).get(e)
        if k is not None:
            if k == "":
                (c.setdefault(e, {})).pop("api_key", None)
            elif not str(k).startswith("•"):
                c.setdefault(e, {})["api_key"] = str(k).strip()[:300]
    return public(cfg)


# ------------------------------------------------------------------ the system's voices

def system_tool() -> tuple[str, str]:
    """(tool, why-not). The first of `say`, `piper`, `espeak-ng`, `espeak`, PowerShell."""
    sysname = platform.system()
    if sysname == "Darwin" and shutil.which("say"):
        return "say", ""
    if shutil.which("piper") and _piper_model():
        return "piper", ""
    for t in ("espeak-ng", "espeak"):
        if shutil.which(t):
            return t, ""
    if sysname == "Windows" and shutil.which("powershell"):
        return "powershell", ""
    if shutil.which("piper"):
        return "", "piper is installed but has no voice model. Set PIPER_MODEL to a .onnx voice."
    return "", ("This computer has no speech engine AgentOS can use. Install espeak-ng "
                "(System Settings → Components) or piper, or pick another engine.")


def _piper_model() -> str:
    m = os.environ.get("PIPER_MODEL", "")
    return m if m and Path(m).exists() else ""


def _run(args: list[str], stdin: str | None = None, timeout: float = TIMEOUT) -> tuple[bool, str]:
    try:
        r = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stderr or r.stdout or "")[-300:]
    except Exception as e:                                  # missing, timed out
        return False, str(e)[:300]


def system_voices() -> list[dict]:
    tool, _ = system_tool()
    out: list[dict] = []
    if tool == "say":
        try:
            lines = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                                   timeout=10).stdout.splitlines()
        except Exception:
            lines = []
        for ln in lines:
            # "Samantha            en_US    # Hello, my name is Samantha."
            head = ln.split("#", 1)[0].rstrip()
            parts = head.rsplit(None, 1)
            if len(parts) == 2:
                out.append({"id": parts[0].strip(), "name": parts[0].strip(),
                            "lang": parts[1].replace("_", "-")})
    elif tool in ("espeak-ng", "espeak"):
        try:
            lines = subprocess.run([tool, "--voices"], capture_output=True, text=True,
                                   timeout=10).stdout.splitlines()[1:]
        except Exception:
            lines = []
        for ln in lines:
            f = ln.split()
            if len(f) >= 4:
                out.append({"id": f[4] if len(f) > 4 else f[3], "name": f[3], "lang": f[1]})
        # espeak's variants make one voice several people
        out += [{"id": f"en+{v}", "name": f"English ({v})", "lang": "en"}
                for v in ("m1", "m3", "m7", "f2", "f4", "croak", "whisper")]
    elif tool == "piper":
        out.append({"id": "default", "name": Path(_piper_model()).stem, "lang": ""})
    elif tool == "powershell":
        ps = ("Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis."
              "SpeechSynthesizer).GetInstalledVoices() | % { $_.VoiceInfo.Name + '|' + "
              "$_.VoiceInfo.Culture }")
        try:
            lines = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                   capture_output=True, text=True, timeout=20).stdout.splitlines()
        except Exception:
            lines = []
        for ln in lines:
            if "|" in ln:
                n, lang = ln.split("|", 1)
                out.append({"id": n.strip(), "name": n.strip(), "lang": lang.strip()})
    return out


def _system_speak(text: str, voice: str) -> tuple[bytes, str]:
    tool, why = system_tool()
    if not tool:
        raise RuntimeError(why)
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "out.wav"
        if tool == "say":
            args = ["say", "-o", str(wav), "--file-format=WAVE", "--data-format=LEI16@22050"]
            ok, err = _run(args + (["-v", voice] if voice and voice != "default" else []) + [text])
        elif tool == "piper":
            ok, err = _run(["piper", "--model", _piper_model(), "--output_file", str(wav)], stdin=text)
        elif tool in ("espeak-ng", "espeak"):
            ok, err = _run([tool, "-w", str(wav)] + (["-v", voice] if voice and voice != "default" else [])
                           + [text])
        else:
            safe = text.replace("'", "''")
            v = (f"$s.SelectVoice('{voice.replace(chr(39), '')}');" if voice and voice != "default" else "")
            ps = (f"Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis."
                  f"SpeechSynthesizer; {v} $s.SetOutputToWaveFile('{wav}'); $s.Speak('{safe}'); $s.Dispose()")
            ok, err = _run(["powershell", "-NoProfile", "-Command", ps])
        if not ok or not wav.exists():
            raise RuntimeError(f"{tool} could not speak: {err}")
        return wav.read_bytes(), "audio/wav"


# ------------------------------------------------------------------ the cloud voices

class VoiceMissing(RuntimeError):
    """The provider does not have the voice it was asked for (so another one can be tried)."""


def _detail(r) -> tuple[str, str]:
    """(status, message) out of a provider's error body. ElevenLabs answers
    `{"detail": {"status": "voice_not_found", "message": "…"}}`, a validation error is
    `{"detail": [{"msg": …}]}`, OpenAI and Google say `{"error": {"message": …}}`."""
    try:
        js = r.json()
    except Exception:
        return "", " ".join(str(getattr(r, "text", "") or "").split())[:200]
    d = js.get("detail") if isinstance(js, dict) else None
    if isinstance(d, dict):
        return str(d.get("status") or d.get("code") or ""), str(d.get("message") or "")
    if isinstance(d, list) and d:
        return "invalid_request", "; ".join(str((x or {}).get("msg") or x) for x in d[:3])
    if isinstance(d, str):
        return "", d
    e = js.get("error") if isinstance(js, dict) else None
    if isinstance(e, dict):
        return str(e.get("status") or e.get("code") or e.get("type") or ""), str(e.get("message") or "")
    return "", " ".join(str(js).split())[:200]


def _refusal(engine: str, r) -> RuntimeError:
    """The provider's refusal as a sentence a person can act on, keeping its own words."""
    status, msg = _detail(r)
    st, code = status.lower(), r.status_code
    title = TITLES[engine]
    if "voice" in st and ("not_found" in st or "not_exist" in st or "does_not" in st):
        return VoiceMissing(f"{title} does not have that voice on this account ({msg or status}). "
                            "Pick one of your voices in Settings → Voice.")
    if "quota" in st or "credit" in st:
        hint = f"This {title} account is out of credits."
    elif "permission" in st:
        hint = (f"The {title} key is missing a permission. Allow Text to Speech and "
                "Voices (read) for it in your ElevenLabs API keys." if engine == "elevenlabs"
                else f"The {title} key is missing a permission.")
    elif code == 401 or "api_key" in st or "unauthorized" in st:
        hint = f"{title} did not accept the key. Paste it again in Settings → Voice."
    elif code == 402 or "payment" in st or "paid" in st or "free_user" in st:
        hint = f"That voice needs a paid {title} plan. Pick another voice in Settings → Voice."
    elif "unusual" in st:
        hint = f"{title} paused free use from this network. A paid plan lifts it."
    else:
        hint = ""
    said = msg or status or f"HTTP {code}"
    return RuntimeError(f"{title} refused ({code}): {said}" + (f". {hint}" if hint else ""))


async def cloud_voices(cfg: dict, engine: str) -> list[dict]:
    key = _key(cfg, engine)
    if engine == "openai":
        return [{"id": v, "name": v.capitalize(), "lang": ""} for v in OPENAI_VOICES]
    if not key:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        if engine == "elevenlabs":
            r = await c.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key})
            if r.status_code >= 400:
                raise _refusal(engine, r)
            return [{"id": v["voice_id"], "name": v.get("name") or v["voice_id"],
                     "lang": ((v.get("labels") or {}).get("accent") or "")}
                    for v in r.json().get("voices", [])]
        if engine == "google":
            lang = conf(cfg).get("language") or "en-US"
            r = await c.get("https://texttospeech.googleapis.com/v1/voices",
                            params={"key": key, "languageCode": lang})
            if r.status_code >= 400:
                raise _refusal(engine, r)
            return [{"id": v["name"], "name": v["name"], "lang": ",".join(v.get("languageCodes") or [])}
                    for v in r.json().get("voices", [])]
    return []


async def _cloud_speak(cfg: dict, engine: str, text: str, voice: str) -> tuple[bytes, str]:
    key = _key(cfg, engine)
    if not key:
        raise RuntimeError(f"{TITLES[engine]} needs an API key (Settings → Voice).")
    if engine == "elevenlabs" and not voice:
        # an empty id makes the URL /text-to-speech/, which ElevenLabs refuses
        raise RuntimeError("ElevenLabs lists no voices for this key, so there is nothing to "
                           "speak with. Add a voice in ElevenLabs, or allow the key to read "
                           "Voices.")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        if engine == "elevenlabs":
            r = await c.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                             params={"output_format": "mp3_44100_128"},
                             headers={"xi-api-key": key, "Content-Type": "application/json"},
                             json={"text": text, "model_id": ELEVEN_MODEL})
        elif engine == "openai":
            r = await c.post("https://api.openai.com/v1/audio/speech",
                             headers={"Authorization": f"Bearer {key}"},
                             json={"model": OPENAI_MODEL, "voice": voice or "alloy",
                                   "input": text, "response_format": "mp3"})
        else:
            lang = conf(cfg).get("language") or "en-US"
            body = {"input": {"text": text}, "audioConfig": {"audioEncoding": "MP3"},
                    "voice": {"languageCode": lang, **({"name": voice} if voice else {})}}
            r = await c.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                             params={"key": key}, json=body)
        if r.status_code >= 400:
            raise _refusal(engine, r)
        if engine == "google":
            return base64.b64decode(r.json().get("audioContent") or b""), "audio/mpeg"
        return r.content, "audio/mpeg"


# ------------------------------------------------------------------ one door

async def voices(cfg: dict, engine: str | None = None) -> list[dict]:
    engine = engine or conf(cfg)["engine"]
    if engine == "system":
        import asyncio
        return await asyncio.to_thread(system_voices)
    if engine in ("elevenlabs", "openai", "google"):
        return await cloud_voices(cfg, engine)
    return []


def pick(name: str, lead: bool, pool: list[str], lead_voice: str, pinned: dict) -> str:
    """The voice for this speaker: pinned by a person, the lead's chosen one, or picked
    from the pool by the name, so the same agent sounds the same every time and two
    agents sound different whenever the pool has more than one voice."""
    if name and pinned.get(name):
        return pinned[name]
    if lead:
        return lead_voice or (pool[0] if pool else "")
    rest = [v for v in pool if v != lead_voice] or pool
    if not rest:
        return lead_voice
    h = int(hashlib.sha1(str(name).encode()).hexdigest(), 16)
    return rest[h % len(rest)]


def _cache_dir() -> Path:
    from . import config as _cfg
    return Path(_cfg.AGENTOS_HOME) / "speech-cache"


def _cached(engine: str, voice: str, text: str) -> tuple[Path, Path]:
    h = hashlib.sha256(f"{engine}|{voice}|{text}".encode()).hexdigest()[:32]
    d = _cache_dir()
    return d / f"{h}.mp3", d / f"{h}.wav"


def _trim_cache() -> None:
    try:
        files = sorted(_cache_dir().glob("*.*"), key=lambda p: p.stat().st_mtime)
        for p in files[:-CACHE_FILES]:
            p.unlink(missing_ok=True)
    except OSError:
        pass


async def speak(cfg: dict, text: str, agent: str = "", lead: bool = False,
                engine: str | None = None, voice: str | None = None) -> tuple[bytes, str, dict]:
    """Audio for one line, and which engine and voice said it. RuntimeError with a
    sentence when it cannot (no key, no tool, the provider refused)."""
    c = conf(cfg)
    engine = engine or c["engine"]
    if engine == "browser":
        raise RuntimeError("This browser speaks for itself; the server has nothing to do.")
    if engine not in ENGINES:
        raise RuntimeError(f"no speech engine called {engine!r}")
    text = " ".join(str(text or "").split())[:MAX_CHARS]
    if not text:
        raise RuntimeError("nothing to say")
    voice, ids = await _resolve(cfg, engine, agent, lead, voice)
    try:
        return await _say(cfg, engine, text, voice)
    except VoiceMissing:
        # the chosen or pinned voice is gone from the account: say it with another one
        # it lists rather than going silent, and the next pick sees the same list
        rest = [v for v in ids if v != voice]
        if not rest:
            raise
        return await _say(cfg, engine, text, pick(agent, lead, rest, "", {}))


async def _resolve(cfg: dict, engine: str, agent: str, lead: bool,
                   voice: str | None) -> tuple[str, list[str]]:
    """(the voice this speaker uses on this engine, the voices the engine lists)."""
    c = conf(cfg)
    if voice is None:
        try:
            vs = await voices(cfg, engine)
        except RuntimeError:
            # a key that may speak but not read the voice list still has the voice
            # the person picked for this engine; without one, the reason stands
            if not lead_voice(cfg, engine):
                raise
            vs = []
        if engine == "system":
            # found by listening: a pool of every language made the lead Afrikaans and
            # the researcher Russian, both reading English. Only voices in the chosen
            # language; all of them if the machine has none in it.
            lang = (c.get("language") or "en").split("-")[0].lower()
            vs = [v for v in vs if str(v.get("lang", "")).lower().split("-")[0] == lang] or vs
            # the exact language first (en-us before en-029), so the lead's default is it
            full = (c.get("language") or "").lower()
            vs.sort(key=lambda v: str(v.get("lang", "")).lower() != full)
        ids = [v["id"] for v in vs]
        voice = pick(agent, lead, ids, _usable(ids, lead_voice(cfg, engine), c.get("voice", "")),
                     {n: v for n, v in (c.get("agents") or {}).items() if not ids or v in ids})
    else:
        ids = []
    return voice, ids


def _usable(ids: list[str], *choices: str) -> str:
    """The first chosen voice this engine actually lists. With no list (it could not be
    read) the engine's own choice is still tried; an old top-level voice is not."""
    for i, v in enumerate(choices):
        if v and (v in ids or (not ids and i == 0)):
            return v
    return ""


async def _say(cfg: dict, engine: str, text: str, voice: str) -> tuple[bytes, str, dict]:
    mp3, wav = _cached(engine, voice, text)
    for p, mime in ((mp3, "audio/mpeg"), (wav, "audio/wav")):
        if p.exists():
            return p.read_bytes(), mime, {"engine": engine, "voice": voice, "cached": True}
    if engine == "system":
        import asyncio
        data, mime = await asyncio.to_thread(_system_speak, text, voice)
    else:
        data, mime = await _cloud_speak(cfg, engine, text, voice)
    try:
        _cache_dir().mkdir(parents=True, exist_ok=True)
        (mp3 if mime == "audio/mpeg" else wav).write_bytes(data)
        _trim_cache()
    except OSError:
        pass
    return data, mime, {"engine": engine, "voice": voice, "cached": False}


async def open_stream(cfg: dict, text: str, agent: str = "", lead: bool = False,
                      fast: bool = True) -> dict:
    """One line as audio that can be PLAYED WHILE IT IS MADE, for speaking a reply as it
    arrives. The provider's stream is opened here and its answer checked before any byte
    is handed on, so a refusal is still a sentence and not a dead audio element.
    Returns {"mime", "who", "chunks" (async iterator of bytes), "close" (coroutine)}.
    An engine that cannot stream (this computer, Google) or a cached line comes back
    whole, as one chunk."""
    c = conf(cfg)
    engine = c["engine"]
    text = " ".join(str(text or "").split())[:MAX_CHARS]

    async def _one(data: bytes):
        yield data

    async def _nothing():
        return None

    if engine not in STREAMING:
        data, mime, who = await speak(cfg, text, agent=agent, lead=lead)
        return {"mime": mime, "who": who, "chunks": _one(data), "close": _nothing}
    if not text:
        raise RuntimeError("nothing to say")
    voice, ids = await _resolve(cfg, engine, agent, lead, None)
    tried = []
    while True:
        mp3, _wav = _cached(engine, voice, text)
        if mp3.exists():
            return {"mime": "audio/mpeg", "who": {"engine": engine, "voice": voice, "cached": True},
                    "chunks": _one(mp3.read_bytes()), "close": _nothing}
        try:
            return await _open(cfg, engine, text, voice, fast, mp3)
        except VoiceMissing:
            tried.append(voice)
            rest = [v for v in ids if v not in tried]
            if not rest:
                raise
            voice = pick(agent, lead, rest, "", {})


async def _open(cfg: dict, engine: str, text: str, voice: str, fast: bool, keep: Path) -> dict:
    key = _key(cfg, engine)
    if not key:
        raise RuntimeError(f"{TITLES[engine]} needs an API key (Settings → Voice).")
    if engine == "elevenlabs":
        if not voice:
            raise RuntimeError("ElevenLabs lists no voices for this key, so there is nothing to "
                               "speak with. Add a voice in ElevenLabs, or allow the key to read "
                               "Voices.")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
        kw = {"params": {"output_format": "mp3_44100_128"},
              "headers": {"xi-api-key": key, "Content-Type": "application/json"},
              "json": {"text": text, "model_id": ELEVEN_FAST_MODEL if fast else ELEVEN_MODEL}}
    else:
        url = "https://api.openai.com/v1/audio/speech"
        kw = {"headers": {"Authorization": f"Bearer {key}"},
              "json": {"model": OPENAI_MODEL, "voice": voice or "alloy", "input": text,
                       "response_format": "mp3"}}
    client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, read=60.0))
    try:
        r = await client.send(client.build_request("POST", url, **kw), stream=True)
    except Exception as e:
        await client.aclose()
        raise RuntimeError(f"{TITLES[engine]} could not be reached: {str(e)[:160]}")
    if r.status_code >= 400:
        await r.aread()
        await r.aclose()
        await client.aclose()
        raise _refusal(engine, r)

    async def close():
        await r.aclose()
        await client.aclose()

    async def chunks():
        got, whole = [], False
        try:
            async for b in r.aiter_bytes():
                got.append(b)
                yield b
            whole = True
        finally:
            await close()
            if whole and got:
                try:
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    keep.write_bytes(b"".join(got))
                    _trim_cache()
                except OSError:
                    pass

    return {"mime": "audio/mpeg", "who": {"engine": engine, "voice": voice, "cached": False},
            "chunks": chunks(), "close": close}


def status(cfg: dict) -> dict:
    """Which engines can speak here, and why not, for the Settings pane and `bento voice`."""
    tool, why = system_tool()
    out = {"browser": {"ok": True, "why": ""},
           "system": {"ok": bool(tool), "why": why, "tool": tool}}
    for e in ("elevenlabs", "openai", "google"):
        out[e] = {"ok": bool(_key(cfg, e)),
                  "why": "" if _key(cfg, e) else f"Add your {TITLES[e]} API key to use it."}
    return {"engine": conf(cfg)["engine"], "engines": out, "titles": TITLES}
