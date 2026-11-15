"""A scene's build as a video with sound, for a phone.

Asked for as "in case of Telegram it should not just send a diagram … for 3D it needs to send a
working feed with audio". A picture of a model shows where it ended; the point of one is watching
it drawn, raised and brought to life. So the page's own painter builds the scene in a throwaway
headless Chromium (the still pictures' browser: cdpbrowser's binary over the CDP pipe, a temp
profile, software WebGL), goes round its named things, and records its own canvas and its own
soundtrack with MediaRecorder (24x-model.js `mdlClip`). Nothing is drawn here.

Three rules:
- **Real time.** A clip of thirty seconds takes thirty seconds: the caller shows "sending a
  video" meanwhile, and a story gets at most `CLIPS` of them.
- **mp4 when it can be.** Chrome records mp4 itself; a browser that only makes webm has it
  turned into mp4 by ffmpeg when ffmpeg is on this machine (it is offered in components, never
  shipped), and is sent as a file otherwise. Telegram plays only mp4 in place.
- **Never fatal.** No browser, no WebGL, a timeout: the pictures already went, and the diary
  says why there was no video.

Three faces: this is the phone's face of a 3D scene. The desktop has the live drawing and its
own Clip button (the same recorder); a terminal has the scene in words (stage.model_line).
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import shutil
import tempfile
from pathlib import Path

WIDTH, HEIGHT = 720, 1280     # 9:16, for a phone held upright
TIMEOUT = 110                 # seconds for one clip, build and tour and all
WALK_TIMEOUT = 170            # a walk-through: seven pictures, each read aloud
CLIPS = 2                     # per story
FFMPEG_S = 120


def available(cfg: dict | None = None) -> bool:
    from . import cdpbrowser
    return bool(cdpbrowser.binary(cfg))


async def render(scene: dict, cfg: dict | None = None, narration: tuple | None = None) -> tuple | None:
    """(bytes, mime, seconds) for one scene built in 3D, or None. `narration` is (audio bytes, mime)."""
    from . import stage
    if not stage.builds_3d(scene):
        return None
    return await _film(stage.clip_html(scene, _data_url(narration)), cfg, TIMEOUT)


async def walk(title: str, slides: list, cfg: dict | None = None) -> tuple | None:
    """(bytes, mime, seconds) for a blueprint walked through picture by picture, or None.
    `slides` is [{png, head, text, narration}], narration (audio bytes, mime) or None."""
    from . import stage
    page = [{"img": "data:image/png;base64," + base64.b64encode(sl["png"]).decode(),
             "head": sl.get("head") or "", "text": sl.get("text") or "",
             "narr": _data_url(sl.get("narration"))} for sl in slides if sl.get("png")]
    if not page:
        return None
    return await _film(stage.walk_html(title, page), cfg, WALK_TIMEOUT)


def _data_url(narration) -> str:
    if not narration or not narration[0]:
        return ""
    return f"data:{narration[1] or 'audio/mpeg'};base64," + base64.b64encode(narration[0]).decode()


def plan(scenes: list, items: list | None = None, pngs: list | None = None) -> list:
    """The videos a story gets, at most CLIPS, in the story's order: {how: "3d", scene} for what
    the page builds in 3D, {how: "walk", scene, slides: [(view, png)]} for a blueprint with no
    3D form, made from the pictures the phone was already sent. Telegram and WhatsApp both
    send what this says, so they cannot come apart."""
    from . import stage
    out = []
    pairs = list(zip(items or [], pngs or [])) if items and pngs and len(items) == len(pngs) else []
    for sc in scenes:
        if stage.builds_3d(sc):
            out.append({"how": "3d", "scene": sc})
        elif sc.get("kind") == "blueprint":
            mine = [(v, png) for (s2, v), png in pairs if s2 is sc][:stage.WALK_SLIDES]
            if len(mine) >= 2:
                out.append({"how": "walk", "scene": sc, "slides": mine})
    return out[:CLIPS]


def caption(job: dict) -> str:
    sc = job["scene"]
    name = sc.get("title") or sc.get("subject") or "Watch it built"
    return (f"▶ {name}: the walk-through" if job["how"] == "walk" else f"▶ {name}")[:1024]


async def make(job: dict, cfg: dict | None = None, voice: bool = True, agent: str = "",
               log=None) -> tuple | None:
    """One planned video: (bytes, mime, seconds) or None. Read aloud when this machine has a
    server voice and `voice`; a line that could not be spoken is shown and not said."""
    from . import speech, stage
    sc = job["scene"]
    speaks = voice and speech.conf(cfg or {}).get("engine") not in ("", "browser", None)

    async def say(text: str):
        if not speaks or not text:
            return None
        try:
            audio, mime, _i = await speech.speak(cfg, text, agent=agent, lead=True)
            return (audio, mime)
        except Exception as e:
            if log:
                log(f"a clip without a voice: {e}")
            return None
    if job["how"] == "3d":
        return await render(sc, cfg, await say(stage.clip_words(sc)))
    slides = []
    for view, png in job["slides"]:
        head, text = stage.walk_text(sc, view)
        slides.append({"png": png, "head": head, "text": text,
                       "narration": await say(f"{head}. {text}" if view and view.get("path") else text)})
    return await walk(sc.get("title") or sc.get("subject") or "", slides, cfg)


async def fit(data: bytes, mime: str, limit: int) -> tuple | None:
    """The same video under `limit` bytes (WhatsApp takes 16 MB), re-encoded smaller with ffmpeg
    when it is over and ffmpeg is here; None when it cannot be made to fit."""
    if len(data) <= limit:
        return data, mime
    tmp = Path(tempfile.mkdtemp(prefix="bento-clip-"))
    try:
        small = await _to_mp4(data, tmp, crf=31, src_name="in.mp4" if "mp4" in mime else "in.webm")
        return (small, "video/mp4") if small and len(small) <= limit else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _film(html: str, cfg: dict | None, timeout: float) -> tuple | None:
    """Open `html` in a throwaway headless browser, wait for its recording, and bring it back."""
    from . import cdpbrowser
    binary = cdpbrowser.binary(cfg)
    if not binary:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="bento-clip-"))
    proc = None
    try:
        page = tmp / "clip.html"
        page.write_text(html, encoding="utf-8")
        args = [binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={tmp / 'p'}",
                "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                "--disable-sync", "--hide-scrollbars", "--force-color-profile=srgb",
                "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
                "--autoplay-policy=no-user-gesture-required",
                f"--window-size={WIDTH},{HEIGHT}", "about:blank"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(2, "--no-sandbox")
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", 'exec "$0" "$@" 3<&0 4>&1 0</dev/null 1>/dev/null', *args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=256 * 1024 * 1024)
        cdp = cdpbrowser.CDP(proc)
        got = await asyncio.wait_for(_record(cdp, page.as_uri()), timeout)
        if not got:
            return None
        data, mime, secs = got
        if "mp4" not in mime:
            mp4 = await _to_mp4(data, tmp)
            if mp4:
                data, mime = mp4, "video/mp4"
        return data, mime, secs
    except Exception:
        return None
    finally:
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.kill()
                await proc.wait()
        shutil.rmtree(tmp, ignore_errors=True)


async def _record(cdp, url: str):
    tgt = (await cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
    s = (await cdp.send("Target.attachToTarget", {"targetId": tgt, "flatten": True}))["sessionId"]
    await cdp.send("Page.enable", session=s)
    await cdp.send("Emulation.setDeviceMetricsOverride",
                   {"width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False}, session=s)
    await cdp.send("Page.navigate", {"url": url}, session=s)

    async def ev(expr):
        r = await cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True}, session=s)
        return (r.get("result") or {}).get("value")

    while True:
        state = await ev("window.STAGE_CLIP_DONE||''")
        if state == "none":
            return None
        if state == "ok":
            break
        await asyncio.sleep(0.5)
    mime = await ev("window.STAGE_CLIP_DATA.mime") or "video/webm"
    secs = float(await ev("window.STAGE_CLIP_DATA.seconds") or 0)
    n = int(await ev("window.STAGE_CLIP_DATA.b64.length") or 0)
    parts, step = [], 4 * 1024 * 1024          # in pieces: one answer on the pipe stays small
    for at in range(0, n, step):
        parts.append(await ev(f"window.STAGE_CLIP_DATA.b64.slice({at},{at + step})") or "")
    data = base64.b64decode("".join(parts))
    return (data, mime, secs) if len(data) > 2000 else None


async def _to_mp4(data: bytes, tmp: Path, crf: int = 23, src_name: str = "in.webm") -> bytes | None:
    """webm → mp4 (H.264 and AAC, the pair every phone plays), when ffmpeg is here."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    src, dst = tmp / src_name, tmp / "out.mp4"
    src.write_bytes(data)
    try:
        p = await asyncio.create_subprocess_exec(
            ff, "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-crf", str(crf), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(dst), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(p.wait(), FFMPEG_S)
        return dst.read_bytes() if p.returncode == 0 and dst.exists() and dst.stat().st_size > 2000 else None
    except Exception:
        return None
