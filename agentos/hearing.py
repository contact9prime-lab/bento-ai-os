"""Speech to text on the server, for a screen whose browser cannot listen by itself.

The page's own recogniser (`webkitSpeechRecognition`) sends audio to Google, and the
Chromium that Raspberry Pi OS ships has no key for that service: it fails with
`network` on the first word. So the kiosk face records the voice itself (16 kHz mono
WAV, cut at the pauses) and posts it here, and this module turns it into text with
whatever this machine has:

  * `whisper.cpp`: a local `whisper-cli` and a model file. Nothing leaves the machine.
    It is MIT licensed and NOT shipped: the person installs it, Bento uses it (the
    OpenClaw rule for something it cannot state an install command for on every board).
  * `openai`: the OpenAI key already set under AI providers, the same key the voices
    reuse (speech.py). It costs a little per minute of audio, and the status says so.

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

ENGINES = ("auto", "whisper.cpp", "openai", "browser")
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
    p = ((cfg or {}).get("providers") or {}).get("openai") or {}
    key = str(p.get("api_key") or "")
    if not key or key.startswith("vault:"):
        return "", ""
    from . import providers
    base = providers.openai_base("openai", p) if p.get("base_url") else "https://api.openai.com/v1"
    return base.rstrip("/"), key


def _whisper(cfg: dict) -> tuple[str, str]:
    """The binary and the model file, or ('', reason)."""
    c = _conf(cfg)
    exe = c.get("whisper_bin") or next((shutil.which(b) for b in WHISPER_BINS if shutil.which(b)), "")
    if not exe:
        return "", "whisper.cpp is not installed"
    model = c.get("whisper_model") or os.environ.get("WHISPER_MODEL", "")
    if not model:
        for d in (Path.home() / ".cache/whisper", Path.home() / "whisper.cpp/models",
                  Path("/usr/share/whisper.cpp/models"), Path("/usr/local/share/whisper.cpp/models")):
            hits = sorted(d.glob("ggml-*.bin")) if d.is_dir() else []
            if hits:
                model = str(hits[0])
                break
    if not model or not Path(model).is_file():
        return "", "whisper.cpp is installed but no model file was found"
    return exe, model


def status(cfg: dict) -> dict:
    """Which engine will hear, or why none can. `engine` is '' when nothing can."""
    want = str(_conf(cfg).get("engine") or "auto").lower()
    want = want if want in ENGINES else "auto"
    exe, model_or_why = _whisper(cfg)
    base, key = _openai(cfg)
    have = {"whisper.cpp": bool(exe), "openai": bool(key)}
    if want == "browser":
        return {"engine": "browser", "setting": want, "have": have,
                "line": "This browser's own recogniser listens. On a Raspberry Pi it usually cannot."}
    order = ["whisper.cpp", "openai"] if want == "auto" else [want]
    for e in order:
        if have.get(e):
            line = ("Speech is understood on this machine with whisper.cpp."
                    if e == "whisper.cpp" else
                    "Speech is understood with your OpenAI key. It costs a little per minute of audio.")
            return {"engine": e, "setting": want, "have": have, "line": line}
    if want == "whisper.cpp":
        why = f"whisper.cpp cannot listen here: {model_or_why}."
    elif want == "openai":
        why = "OpenAI cannot listen here: there is no OpenAI key under AI providers."
    else:
        why = (f"Nothing here can understand speech yet: {model_or_why}, and there is no OpenAI key. "
               "Add an OpenAI key under AI providers, or install whisper.cpp.")
    return {"engine": "", "setting": want, "have": have, "line": why}


async def transcribe(cfg: dict, wav: bytes, lang: str = "") -> str:
    """The words in one utterance. Raises HearError with the sentence to show."""
    if not wav:
        return ""
    if len(wav) > MAX_BYTES:
        raise HearError("That was too long to understand in one go. Say it in shorter pieces.")
    st = status(cfg)
    lang = (lang or "").split("-")[0].lower()[:5]
    if st["engine"] == "whisper.cpp":
        import asyncio
        return await asyncio.to_thread(_whisper_run, cfg, wav, lang)
    if st["engine"] == "openai":
        return await _openai_run(cfg, wav, lang)
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
