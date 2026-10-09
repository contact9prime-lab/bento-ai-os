"""Speech to text on the server, for a screen whose browser cannot listen by itself.

The page's own recogniser (`webkitSpeechRecognition`) sends audio to Google, and the
Chromium that Raspberry Pi OS ships has no key for that service: it fails with
`network` on the first word. So the kiosk face records the voice itself (16 kHz mono
WAV, cut at the pauses) and posts it here, and this module turns it into text with
whatever this machine has:

  * `whisper.cpp`: a local `whisper-cli` and a model file. Nothing leaves the machine.
    It is MIT licensed and NOT shipped: the person installs it, Bento uses it (the
    OpenClaw rule for something it cannot state an install command for on every board).
  * the VOICE SERVICE already set up under Settings → Voice (speech.py): ElevenLabs
    (Scribe), OpenAI (also the key under AI providers) or Google Cloud (Speech-to-Text).
    Asked for as "if the voice is configured, it should take it from there": a key that
    makes the agents speak is the key that hears them, with no second box to fill. The
    engine chosen for speaking is tried first. Each costs a little per minute of audio,
    and the status says so.

`auto` prefers whisper.cpp (nothing leaves the machine), then the voice service, then
any other key that can hear. What would fix a deaf machine is named in `status()`
(`install`: the components.py entries), so onboarding can offer to install it.

`status()` is the one answer to "can this screen listen?", read by Settings, the kiosk
face and `bento face`, so a mic is never shown that cannot be understood. Kept free of
asyncio except `transcribe`, which the route awaits.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ENGINES = ("auto", "whisper.cpp", "elevenlabs", "openai", "google", "browser")
CLOUD = ("elevenlabs", "openai", "google")
TITLES = {"whisper.cpp": "whisper.cpp", "elevenlabs": "ElevenLabs", "openai": "OpenAI",
          "google": "Google Cloud"}
ELEVEN_MODELS = ("scribe_v2", "scribe_v1")     # newest first; an older account may lack one
MODEL_DIR = Path.home() / ".local/share/whisper.cpp/models"
MAX_BYTES = 4 << 20                 # about two minutes of 16 kHz mono 16-bit audio
WHISPER_BINS = ("whisper-cli", "whisper-cpp", "whisper")
OPENAI_MODEL = "whisper-1"
TIMEOUT_S = 60


class HearError(Exception):
    """Something the person can act on, in a sentence."""


def _conf(cfg: dict) -> dict:
    s = ((cfg or {}).get("speech") or {}).get("hear")
    return s if isinstance(s, dict) else {}


def _openai(cfg: dict) -> tuple[str, str]:
    """(base url, key): the key under Voice first, then the one under AI providers."""
    own = str((((cfg or {}).get("speech") or {}).get("openai") or {}).get("api_key") or "")
    if own and not own.startswith("vault:"):
        return "https://api.openai.com/v1", own
    p = ((cfg or {}).get("providers") or {}).get("openai") or {}
    key = str(p.get("api_key") or "")
    if not key or key.startswith("vault:"):
        return "", ""
    from . import providers
    base = providers.openai_base("openai", p) if p.get("base_url") else "https://api.openai.com/v1"
    return base.rstrip("/"), key


def _voice_key(cfg: dict, engine: str) -> str:
    """The key saved under Settings → Voice for ElevenLabs or Google Cloud."""
    k = str((((cfg or {}).get("speech") or {}).get(engine) or {}).get("api_key") or "")
    return "" if k.startswith("vault:") else k


def _whisper(cfg: dict) -> tuple[str, str]:
    """The binary and the model file, or ('', reason)."""
    c = _conf(cfg)
    exe = c.get("whisper_bin") or next((shutil.which(b) for b in WHISPER_BINS if shutil.which(b)), "")
    if not exe:
        # what components.py's install puts in ~/.local/bin, which a service's PATH may lack
        own = Path.home() / ".local/bin/whisper-cli"
        exe = str(own) if own.is_file() and os.access(own, os.X_OK) else ""
    if not exe:
        return "", "whisper.cpp is not installed"
    model = c.get("whisper_model") or os.environ.get("WHISPER_MODEL", "")
    if not model:
        for d in (MODEL_DIR, Path.home() / ".cache/whisper", Path.home() / "whisper.cpp/models",
                  Path.home() / ".local/src/whisper.cpp/models",
                  Path("/usr/share/whisper.cpp/models"), Path("/usr/local/share/whisper.cpp/models")):
            hits = sorted(d.glob("ggml-*.bin")) if d.is_dir() else []
            if hits:
                model = str(hits[0])
                break
    if not model or not Path(model).is_file():
        return "", "whisper.cpp is installed but no model file was found"
    return exe, model


def _order(cfg: dict, want: str) -> list[str]:
    if want != "auto":
        return [want]
    spoken = str(((cfg or {}).get("speech") or {}).get("engine") or "")
    cloud = ([spoken] if spoken in CLOUD else []) + [e for e in CLOUD if e != spoken]
    return ["whisper.cpp"] + cloud


def _line(e: str, cfg: dict) -> str:
    if e == "whisper.cpp":
        return "Speech is understood on this machine with whisper.cpp."
    where = "AI providers" if e == "openai" and not _voice_key(cfg, "openai") else "Voice"
    extra = " Its project needs the Speech-to-Text API turned on." if e == "google" else ""
    return (f"Speech is understood by {TITLES[e]}, with the key under {where}. "
            f"It costs a little per minute of audio.{extra}")


def status(cfg: dict) -> dict:
    """Which engine will hear, or why none can. `engine` is '' when nothing can.
    `install` names the components.py entries that would let this machine hear."""
    want = str(_conf(cfg).get("engine") or "auto").lower()
    want = want if want in ENGINES else "auto"
    exe, model_or_why = _whisper(cfg)
    have = {"whisper.cpp": bool(exe), "elevenlabs": bool(_voice_key(cfg, "elevenlabs")),
            "openai": bool(_openai(cfg)[1]), "google": bool(_voice_key(cfg, "google"))}
    install = [] if exe else ["whisper-cpp"]
    if want == "browser":
        return {"engine": "browser", "setting": want, "have": have, "install": [],
                "line": "This browser's own recogniser listens. On a Raspberry Pi it usually cannot."}
    for e in _order(cfg, want):
        if have.get(e):
            return {"engine": e, "setting": want, "have": have, "install": [], "line": _line(e, cfg)}
    if want == "whisper.cpp":
        why = f"whisper.cpp cannot listen here: {model_or_why}."
    elif want in CLOUD:
        why = f"{TITLES[want]} cannot listen here: there is no {TITLES[want]} key under Voice."
        install = []
    else:
        why = (f"Nothing here can understand speech yet: {model_or_why}, and no voice service is set up. "
               "Install whisper.cpp, or add an ElevenLabs, OpenAI or Google Cloud key under Voice.")
    return {"engine": "", "setting": want, "have": have, "install": install, "line": why}


async def transcribe(cfg: dict, wav: bytes, lang: str = "") -> str:
    """The words in one utterance. Raises HearError with the sentence to show."""
    if not wav:
        return ""
    if len(wav) > MAX_BYTES:
        raise HearError("That was too long to understand in one go. Say it in shorter pieces.")
    st = status(cfg)
    full = str(lang or (cfg.get("speech") or {}).get("language") or "")[:12]
    lang = full.split("-")[0].lower()[:5]
    if st["engine"] == "whisper.cpp":
        import asyncio
        return await asyncio.to_thread(_whisper_run, cfg, wav, lang)
    if st["engine"] == "openai":
        return await _openai_run(cfg, wav, lang)
    if st["engine"] == "elevenlabs":
        return await _eleven_run(cfg, wav, lang)
    if st["engine"] == "google":
        return await _google_run(cfg, wav, full or "en-US")
    raise HearError(st["line"])


def _whisper_run(cfg: dict, wav: bytes, lang: str) -> str:
    exe, model = _whisper(cfg)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "say.wav"
        f.write_bytes(wav)
        cmd = [exe, "-m", model, "-f", str(f), "-nt", "-np"]
        if lang:
            cmd += ["-l", lang]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise HearError("whisper.cpp took too long to understand that.") from e
        except OSError as e:
            raise HearError(f"whisper.cpp could not start: {e}") from e
    if r.returncode != 0:
        raise HearError(f"whisper.cpp could not understand that ({(r.stderr or '').strip()[-120:] or r.returncode}).")
    return " ".join(r.stdout.split()).strip()


async def _openai_run(cfg: dict, wav: bytes, lang: str) -> str:
    import httpx
    base, key = _openai(cfg)
    data = {"model": _conf(cfg).get("openai_model") or OPENAI_MODEL}
    if lang:
        data["language"] = lang
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
            r = await c.post(f"{base}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                             data=data, files={"file": ("say.wav", wav, "audio/wav")})
    except Exception as e:                                              # noqa: BLE001
        raise HearError(f"OpenAI could not be reached to understand that ({type(e).__name__}).") from e
    if r.status_code == 401:
        raise HearError("OpenAI refused the key under AI providers.")
    if r.status_code >= 400:
        try:
            msg = (r.json().get("error") or {}).get("message", "")
        except Exception:
            msg = ""
        raise HearError(f"OpenAI could not understand that ({r.status_code}{': ' + msg[:120] if msg else ''}).")
    try:
        return str(r.json().get("text") or "").strip()
    except Exception as e:
        raise HearError("OpenAI answered with something that was not a transcript.") from e


async def _eleven_run(cfg: dict, wav: bytes, lang: str) -> str:
    """ElevenLabs Scribe: the same key that gives the agents their voices."""
    import httpx
    key = _voice_key(cfg, "elevenlabs")
    models = [_conf(cfg).get("elevenlabs_model")] if _conf(cfg).get("elevenlabs_model") else list(ELEVEN_MODELS)
    r = None
    for model in models:
        data = {"model_id": model}
        if lang:
            data["language_code"] = lang
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
                r = await c.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": key},
                                 data=data, files={"file": ("say.wav", wav, "audio/wav")})
        except Exception as e:                                          # noqa: BLE001
            raise HearError(f"ElevenLabs could not be reached to understand that ({type(e).__name__}).") from e
        if r.status_code in (400, 422) and "model" in r.text.lower() and model != models[-1]:
            continue                                # this account has the older model only
        break
    if r.status_code == 401:
        raise HearError("ElevenLabs refused the key under Voice.")
    if r.status_code >= 400:
        raise HearError(f"ElevenLabs could not understand that ({r.status_code}{_said(r)}).")
    try:
        return str(r.json().get("text") or "").strip()
    except Exception as e:
        raise HearError("ElevenLabs answered with something that was not a transcript.") from e


async def _google_run(cfg: dict, wav: bytes, lang: str) -> str:
    """Google Cloud Speech-to-Text with the Google Cloud key under Voice. The encoding and
    rate are read from the WAV header, so only the language is sent."""
    import base64

    import httpx
    key = _voice_key(cfg, "google")
    body = {"config": {"languageCode": lang}, "audio": {"content": base64.b64encode(wav).decode()}}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
            r = await c.post("https://speech.googleapis.com/v1/speech:recognize", params={"key": key}, json=body)
    except Exception as e:                                              # noqa: BLE001
        raise HearError(f"Google could not be reached to understand that ({type(e).__name__}).") from e
    if r.status_code == 403 and ("SERVICE_DISABLED" in r.text or "has not been used" in r.text
                                 or "disabled" in r.text.lower()):
        raise HearError("Google refused: turn on the Cloud Speech-to-Text API for the project of the key under Voice.")
    if r.status_code in (400, 401, 403) and "API key" in r.text:
        raise HearError("Google refused the key under Voice.")
    if r.status_code >= 400:
        raise HearError(f"Google could not understand that ({r.status_code}{_said(r)}).")
    try:
        res = r.json().get("results") or []
        return " ".join(str(((x.get("alternatives") or [{}])[0]).get("transcript") or "").strip()
                        for x in res).strip()
    except Exception as e:
        raise HearError("Google answered with something that was not a transcript.") from e


def _said(r) -> str:
    """The provider's own reason, short, or ''."""
    try:
        j = r.json()
        msg = j.get("detail") or j.get("error") or j.get("message") or ""
        if isinstance(msg, dict):
            msg = msg.get("message") or msg.get("status") or ""
        msg = str(msg)
    except Exception:
        msg = ""
    return f": {msg[:120]}" if msg else ""


# ---- a microphone from a terminal ---------------------------------------------------------
#
# `bento face test` and `bento setup`'s voice step, on a Pi over SSH with a USB microphone:
# the same evidence the page gathers (a recording understood here, checked for the wake
# word), recorded by whichever recorder the machine already has. Raspberry Pi OS ships
# `arecord` (alsa-utils); sox's `rec` and PulseAudio's `parecord` are the others. None is
# installed for you.

RECORDERS = (
    ("arecord", lambda secs, out: ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1",
                                   "-d", str(secs), out]),
    ("rec", lambda secs, out: ["rec", "-q", "-r", "16000", "-c", "1", "-b", "16", out,
                               "trim", "0", str(secs)]),
    ("parecord", lambda secs, out: ["timeout", str(secs), "parecord", "--rate=16000",
                                    "--channels=1", "--format=s16le", "--file-format=wav", out]),
)


def recorder() -> str:
    """The recorder this machine has, or ''."""
    return next((name for name, _ in RECORDERS if shutil.which(name)), "")


def record(seconds: int = 5) -> bytes:
    """`seconds` of 16 kHz mono WAV from the default microphone. Raises HearError with
    the sentence to show: no recorder, no microphone, or a recording that is silent."""
    name = recorder()
    if not name:
        raise HearError("There is no recorder here (arecord, rec or parecord). On a Raspberry Pi: "
                        "sudo apt install alsa-utils")
    build = dict(RECORDERS)[name]
    with tempfile.TemporaryDirectory() as d:
        out = str(Path(d) / "say.wav")
        try:
            r = subprocess.run(build(int(seconds), out), capture_output=True, text=True,
                               timeout=int(seconds) + 10)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise HearError(f"{name} could not record: {e}") from e
        try:
            wav = Path(out).read_bytes()
        except OSError:
            wav = b""
        if not wav or len(wav) <= 44:
            err = (r.stderr or "").strip().splitlines()[-1:] or ["no sound came in"]
            raise HearError(f"{name} recorded nothing ({err[0][:120]}). Is a microphone plugged in?")
        return wav
