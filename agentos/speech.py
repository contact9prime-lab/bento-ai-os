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
OPENAI_MODEL = "gpt-4o-mini-tts"
OPENAI_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx",
                 "sage", "shimmer", "verse")
MAX_CHARS = 1200            # one line of an agent, not a document
CACHE_FILES = 300
TIMEOUT = 30.0


def conf(cfg: dict) -> dict:
    c = cfg.setdefault("speech", {})
    c.setdefault("engine", "browser")
    c.setdefault("voice", "")               # the lead's voice on that engine
    c.setdefault("agents", {})              # name -> voice, pinned by a person
    c.setdefault("language", "en-US")
    return c


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
    return {"engine": c["engine"], "voice": c.get("voice", ""), "language": c.get("language", "en-US"),
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
    for k in ("voice", "language"):
        if k in p:
            c[k] = str(p[k] or "")[:120]
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

async def cloud_voices(cfg: dict, engine: str) -> list[dict]:
    key = _key(cfg, engine)
    if engine == "openai":
        return [{"id": v, "name": v.capitalize(), "lang": ""} for v in OPENAI_VOICES]
    if not key:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        if engine == "elevenlabs":
            r = await c.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key})
            r.raise_for_status()
            return [{"id": v["voice_id"], "name": v.get("name") or v["voice_id"],
                     "lang": ((v.get("labels") or {}).get("accent") or "")}
                    for v in r.json().get("voices", [])]
        if engine == "google":
            lang = conf(cfg).get("language") or "en-US"
            r = await c.get("https://texttospeech.googleapis.com/v1/voices",
                            params={"key": key, "languageCode": lang})
            r.raise_for_status()
            return [{"id": v["name"], "name": v["name"], "lang": ",".join(v.get("languageCodes") or [])}
                    for v in r.json().get("voices", [])]
    return []


async def _cloud_speak(cfg: dict, engine: str, text: str, voice: str) -> tuple[bytes, str]:
    key = _key(cfg, engine)
    if not key:
        raise RuntimeError(f"{TITLES[engine]} needs an API key (Settings → Voice).")
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
            raise RuntimeError(f"{TITLES[engine]} refused ({r.status_code}): {r.text[:200]}")
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
    if voice is None:
        vs = await voices(cfg, engine)
        if engine == "system":
            # found by listening: a pool of every language made the lead Afrikaans and
            # the researcher Russian, both reading English. Only voices in the chosen
            # language; all of them if the machine has none in it.
            lang = (c.get("language") or "en").split("-")[0].lower()
            vs = [v for v in vs if str(v.get("lang", "")).lower().split("-")[0] == lang] or vs
            # the exact language first (en-us before en-029), so the lead's default is it
            full = (c.get("language") or "").lower()
            vs.sort(key=lambda v: str(v.get("lang", "")).lower() != full)
        voice = pick(agent, lead, [v["id"] for v in vs], c.get("voice", ""), c.get("agents") or {})
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


def status(cfg: dict) -> dict:
    """Which engines can speak here, and why not, for the Settings pane and `bento voice`."""
    tool, why = system_tool()
    out = {"browser": {"ok": True, "why": ""},
           "system": {"ok": bool(tool), "why": why, "tool": tool}}
    for e in ("elevenlabs", "openai", "google"):
        out[e] = {"ok": bool(_key(cfg, e)),
                  "why": "" if _key(cfg, e) else f"Add your {TITLES[e]} API key to use it."}
    return {"engine": conf(cfg)["engine"], "engines": out, "titles": TITLES}
