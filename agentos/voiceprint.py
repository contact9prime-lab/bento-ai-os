"""A person's voice print: only an enrolled voice wakes the screen.

Asked for as "ask the user to record the recognition word for waking, by getting the signature
voice print. This should be done by the system for the user signed in." The owner's two choices:
the print only FILTERS who can wake the screen, and the speaker model is an install the person
agrees to, never shipped.

What it is, and what it is not:

  * A FILTER, never a key. A voice can be recorded and played back, so a match signs nobody in,
    switches no account and lifts no approval. `users.current()` still comes from the signed
    cookie only. A screen with the filter on ignores a wake word said by a voice it does not
    know; everything an agent then does is gated as it always was.
  * The person's own. The print is a list of numbers made from their recordings, kept in THEIR
    home (`voiceprint.json`, 0600) and nowhere else. The recordings are not kept. No route, verb
    or tool returns the numbers; an agent cannot read the file (a home is closed by allow-list,
    protected.HOME_READABLE). `forget` deletes it.
  * Measured, not promised. The model is 3D-Speaker's CAM++ (Apache-2.0) run by sherpa-onnx
    (Apache-2.0), 192 numbers a recording, about 50 ms on a desktop CPU. On three public
    speakers the same voice scored 0.67 to 0.82 and different voices -0.02 to 0.46, so THRESHOLD
    sits between. A wake phrase is shorter than those recordings; `MIN_S` refuses one too short
    to judge, and a refusal says so instead of guessing.
  * Not available until installed (components `voice-print`). `status()` says so in a sentence;
    with the filter on and the model gone, nothing is filtered and the screen says that too.

Free of HTTP and asyncio: `bento face print` enrols and checks with the server down.
"""
from __future__ import annotations

import importlib.util
import io
import json
import math
import os
import struct
import sys
import time
import wave
from pathlib import Path

MODEL_NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
             + MODEL_NAME + ".onnx")
MODEL_BYTES = 28281164              # what the release serves; a short download is not a model
COMPONENT = "voice-print"
FILE = "voiceprint.json"
NEED = 3                            # recordings before a print counts
MAX_SAMPLES = 6
MIN_S = 1.2                         # seconds of sound a recording needs to be judged
MAX_S = 30.0
THRESHOLD = 0.55                    # cosine against the person's recordings (see the docstring)
OUTLIER = 0.35                      # a new recording this unlike the others is refused
MAX_BYTES = 4 << 20


class PrintError(Exception):
    """A sentence for the person: why a recording could not be used."""


def base() -> Path:
    return Path(os.environ.get("AGENTOS_VOICEPRINT_DIR") or (Path.home() / ".local/share/bento/voiceprint"))


def _lib() -> Path:
    return base() / "lib"


def model_path() -> Path:
    return base() / "model.onnx"


def _importable() -> bool:
    lib = str(_lib())
    if _lib().is_dir() and lib not in sys.path:
        sys.path.append(lib)
    try:
        return importlib.util.find_spec("sherpa_onnx") is not None
    except Exception:
        return False


def ready() -> bool:
    """Can this machine make a print right now: the library and the whole model are here."""
    try:
        return model_path().stat().st_size >= MODEL_BYTES and _importable()
    except OSError:
        return False


def why_not() -> str:
    """'' when ready, else the sentence that says what is missing."""
    if ready():
        return ""
    return ("Voice prints need a speaker model on this machine, about 70 MB. "
            "Install it from here, or run: bento face print install")


# ---- the recording -------------------------------------------------------------------------

def read_wav(wav: bytes) -> tuple[int, list[float]]:
    """16-bit PCM WAV to (rate, mono samples in -1..1). Anything else is a sentence."""
    if len(wav) > MAX_BYTES:
        raise PrintError("That recording is too long. A few seconds is enough.")
    try:
        with wave.open(io.BytesIO(wav)) as w:
            rate, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
            raw = w.readframes(n)
    except (wave.Error, EOFError, struct.error):
        raise PrintError("That was not a recording this machine can read.")
    if width != 2 or ch < 1 or rate < 8000:
        raise PrintError("That recording is in a format this machine cannot use for a voice print.")
    s = struct.unpack("<%dh" % (len(raw) // 2), raw[:len(raw) // 2 * 2])
    mono = s[::ch]
    secs = len(mono) / float(rate)
    if secs < MIN_S:
        raise PrintError(f"That was only {secs:.1f} seconds. Say the wake word and a short sentence.")
    if secs > MAX_S:
        raise PrintError("That recording is too long. A few seconds is enough.")
    loud = math.sqrt(sum(x * x for x in mono[::8]) / max(1, len(mono[::8]))) / 32768.0
    if loud < 0.004:
        raise PrintError("That was almost silent. Try again a little closer to the microphone.")
    return rate, [x / 32768.0 for x in mono]


_EXTRACTOR = [None]


def _extractor():
    if _EXTRACTOR[0] is None:
        if not ready():
            raise PrintError(why_not())
        import sherpa_onnx                                   # asked for, never shipped (components.py)
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path()), num_threads=1, debug=False, provider="cpu")
        _EXTRACTOR[0] = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    return _EXTRACTOR[0]


def release() -> None:
    """Let the model go (about 100 MB of memory, measured): after an enrolment on a machine that does
    not filter, nothing needs it loaded."""
    _EXTRACTOR[0] = None


def embed(wav: bytes) -> list[float]:
    """The numbers for one recording. The one place the model runs; tests replace it."""
    rate, samples = read_wav(wav)
    ex = _extractor()
    st = ex.create_stream()
    st.accept_waveform(rate, samples)
    st.input_finished()
    return [float(x) for x in ex.compute(st)]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    den = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / den if den else 0.0


# ---- the person's print --------------------------------------------------------------------

def _path(home) -> Path:
    return Path(home) / FILE


def _load(home) -> dict:
    try:
        d = json.loads(_path(home).read_text())
    except (OSError, ValueError):
        return {}
    vs = [v for v in (d.get("vectors") or []) if isinstance(v, list) and v
          and all(isinstance(x, (int, float)) for x in v)]
    return {"model": str(d.get("model") or ""), "vectors": vs[:MAX_SAMPLES], "at": d.get("at") or 0}


def _save(home, d: dict) -> None:
    p = _path(home)
    tmp = p.with_suffix(".part")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"v": 1, "model": MODEL_NAME, "vectors": d["vectors"], "at": time.time()}, f)
    os.replace(tmp, p)


def enrolled(home) -> bool:
    d = _load(home)
    return len(d.get("vectors") or []) >= NEED and d.get("model") == MODEL_NAME


def _score(vectors: list, vec: list[float]) -> float:
    """How like the person's recordings this one is: the mean of its two best matches, so one
    odd recording neither lets a stranger in nor keeps the person out."""
    scores = sorted((cosine(v, vec) for v in vectors), reverse=True)
    top = scores[:2]
    return sum(top) / len(top) if top else 0.0


def enroll(home, wav: bytes) -> dict:
    """Add one recording to the person's print. A recording unlike the ones already kept is
    refused, never averaged in: somebody else speaking during enrolment would otherwise
    become part of the print."""
    vec = embed(wav)
    d = _load(home)
    if d.get("model") and d["model"] != MODEL_NAME:
        d = {}                                               # another model's numbers mean nothing here
    vs = list(d.get("vectors") or [])
    score = _score(vs, vec) if vs else 1.0
    if vs and score < OUTLIER:
        raise PrintError("That did not sound like your earlier recordings. Try again, or start over.")
    vs = (vs + [vec])[-MAX_SAMPLES:]
    _save(home, {"vectors": vs})
    return {"samples": len(vs), "need": NEED, "enrolled": len(vs) >= NEED, "score": round(score, 2)}


def match(home, wav: bytes) -> dict:
    """Does this recording sound like the person? {"match", "score"}; a recording that cannot
    be judged (too short, silent) is `match: None` with the reason, never a guess."""
    d = _load(home)
    if len(d.get("vectors") or []) < NEED or d.get("model") != MODEL_NAME:
        return {"match": None, "score": 0.0, "why": "no voice print is saved"}
    try:
        vec = embed(wav)
    except PrintError as e:
        return {"match": None, "score": 0.0, "why": str(e)}
    score = _score(d["vectors"], vec)
    return {"match": score >= THRESHOLD, "score": round(score, 2)}


def forget(home) -> bool:
    try:
        _path(home).unlink()
        return True
    except OSError:
        return False


def only(cfg: dict) -> bool:
    """Is the filter on for this person: only their voice wakes the screen."""
    v = (cfg or {}).get("voiceprint")
    return bool(isinstance(v, dict) and v.get("only"))


def filtering(cfg: dict, home) -> bool:
    """The filter is on AND can be applied: switched on, a print saved, the model here."""
    return only(cfg) and enrolled(home) and ready()


def status(cfg: dict, home) -> dict:
    """What every face shows. Never the numbers."""
    d = _load(home)
    n = len(d.get("vectors") or []) if d.get("model") in ("", MODEL_NAME) else 0
    ok = ready()
    on = only(cfg)
    if not ok:
        line = why_not()
    elif n >= NEED:
        line = ("Only your voice wakes this screen." if on
                else "Your voice print is saved. Any voice still wakes this screen.")
    else:
        line = f"Say the wake word {NEED} times to save your voice print."
    return {"available": ok, "install": "" if ok else COMPONENT, "samples": n, "need": NEED,
            "enrolled": n >= NEED, "only": on, "at": d.get("at") or 0, "line": line,
            # the filter is switched on but cannot run: said, so nobody believes it is filtering
            "idle": bool(on and not (ok and n >= NEED))}
