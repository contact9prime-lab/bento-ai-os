"""Video from a description: the provider, the request, the price, read in one place.

Asked for as "voice and image and video agents should also be added in AI Providers in their
own section". Checked against the providers' own pages on 2026-11-17 before anything was
written, because the obvious two were gone:

  * OpenAI shut Sora 2 and its Videos API down on 2026-09-24, with no replacement API.
  * Google shut the Veo 3.1 preview models down in the Gemini API on 2026-10-22. What the Gemini
    API offers for video now is Gemini Omni Flash, `gemini-omni-1.2-flash`, on the Interactions
    endpoint: one synchronous request, 3 to 15 seconds, 16:9 or 9:16, 360p to 4K, the MP4 back
    inline as base64. It is billed per second of video and has no free tier.

So there is one provider here, Google, and it uses the Google key already in AI providers. A
provider that is gone is never offered (the honesty rule: a dead choice is worse than none);
`GONE` says why, and Settings and the tool say it in words.

Free of asyncio and HTTP (the tool makes the call), so the price and the request can be shown
on the approval card and in `bento video` before anything is spent.
"""
from __future__ import annotations

import base64

MODEL = "gemini-omni-1.2-flash"
ENDPOINT = "/v1beta/interactions"
RESOLUTIONS = ("360p", "720p", "1080p", "4k")
ASPECTS = ("16:9", "9:16")
MIN_S, MAX_S, DEFAULT_S = 3, 15, 8
# USD per second of video, from Google's pricing page (Standard), checked 2026-11-17.
# 720p is billed at 5,792 output tokens a second at $12 per million.
PRICE = {"360p": 0.023, "720p": 0.07, "1080p": 0.104, "4k": 0.209}
CHECKED = "2026-11-17"
GONE = {
    "openai": "OpenAI shut down Sora and its Videos API on 24 September 2026.",
    "veo": "Google shut down Veo 3.1 in the Gemini API on 22 October 2026; Gemini Omni Flash replaced it.",
}


def conf(cfg: dict) -> dict:
    """The person's video settings, every field checked."""
    raw = (cfg or {}).get("video") or {}
    prov = str(raw.get("provider") or "auto").lower()
    res = str(raw.get("resolution") or "720p").lower()
    return {"provider": prov if prov in ("auto", "google", "off") else "auto",
            "model": str(raw.get("model") or "").strip() or MODEL,
            "resolution": res if res in RESOLUTIONS else "720p"}


def ready(cfg: dict) -> tuple[bool, str]:
    """Can a video be made here, and if not, the sentence that would fix it."""
    c = conf(cfg)
    if c["provider"] == "off":
        return False, "Video is switched off in Settings → AI providers → Video."
    google = ((cfg or {}).get("providers") or {}).get("google") or {}
    if not google.get("api_key"):
        return False, ("Video uses Google's Gemini Omni Flash. Add a Google key in Settings → AI "
                       "providers (aistudio.google.com); video has no free tier.")
    return True, ""


def seconds_of(seconds) -> int:
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        s = DEFAULT_S
    return max(MIN_S, min(MAX_S, s))


def cost(seconds, resolution: str = "720p") -> float:
    """What a clip costs at Google's listed price, in US dollars."""
    return round(seconds_of(seconds) * PRICE.get(resolution, PRICE["720p"]), 3)


def cost_words(seconds, resolution: str = "720p") -> str:
    return (f"about ${cost(seconds, resolution):.2f} ({seconds_of(seconds)} s at {resolution}, "
            f"Google's price as of {CHECKED})")


def request(prompt: str, seconds, aspect: str, resolution: str, model: str = MODEL) -> dict:
    """The Interactions request body for one clip."""
    return {"model": model or MODEL, "input": str(prompt or "")[:4000],
            "response_format": {"type": "video",
                                "aspect_ratio": aspect if aspect in ASPECTS else "16:9",
                                "resolution": resolution if resolution in RESOLUTIONS else "720p",
                                "duration": f"{seconds_of(seconds)}s"},
            "store": False, "background": False, "stream": False}


def video_of(answer: dict) -> bytes | None:
    """The MP4 in an Interactions answer: a `video` content item, inline base64, in a
    `model_output` step. None when the answer carries none."""
    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "video" and x.get("data"):
                return x["data"]
            for v in x.values():
                got = walk(v)
                if got:
                    return got
        elif isinstance(x, list):
            for v in x:
                got = walk(v)
                if got:
                    return got
        return None
    data = walk((answer or {}).get("steps") or answer or {})
    if not data:
        return None
    try:
        return base64.b64decode(data)
    except (ValueError, TypeError):
        return None


def refusal(status: int, body: dict | str) -> str:
    """The provider's own explanation, in a sentence."""
    msg = ""
    if isinstance(body, dict):
        e = body.get("error") or body
        msg = str((e or {}).get("message") or "") if isinstance(e, dict) else str(e)
    else:
        msg = str(body or "")
    msg = msg.strip()[:220]
    if status in (401, 403):
        return f"Google refused the key ({status}). {msg}".strip()
    if status == 429:
        return f"Google's limit was reached; try again in a minute. {msg}".strip()
    return f"Google answered {status}. {msg}".strip()
