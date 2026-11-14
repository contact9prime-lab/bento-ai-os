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
CLIPS = 2                     # per story
FFMPEG_S = 120


def available(cfg: dict | None = None) -> bool:
    from . import cdpbrowser
    return bool(cdpbrowser.binary(cfg))


async def render(scene: dict, cfg: dict | None = None, narration: tuple | None = None) -> tuple | None:
    """(bytes, mime, seconds) for one scene, or None. `narration` is (audio bytes, mime)."""
    from . import cdpbrowser, stage
    binary = cdpbrowser.binary(cfg)
    if not binary or not stage.builds_3d(scene):
        return None
    tmp = Path(tempfile.mkdtemp(prefix="bento-clip-"))
    proc = None
    try:
        narr = ""
        if narration and narration[0]:
            narr = f"data:{narration[1] or 'audio/mpeg'};base64," + base64.b64encode(narration[0]).decode()
        page = tmp / "clip.html"
        page.write_text(stage.clip_html(scene, narr), encoding="utf-8")
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
        got = await asyncio.wait_for(_record(cdp, page.as_uri()), TIMEOUT)
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


async def _to_mp4(data: bytes, tmp: Path) -> bytes | None:
    """webm → mp4 (H.264 and AAC, the pair every phone plays), when ffmpeg is here."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    src, dst = tmp / "in.webm", tmp / "out.mp4"
    src.write_bytes(data)
    try:
        p = await asyncio.create_subprocess_exec(
            ff, "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(dst), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(p.wait(), FFMPEG_S)
        return dst.read_bytes() if p.returncode == 0 and dst.exists() and dst.stat().st_size > 2000 else None
    except Exception:
        return None
