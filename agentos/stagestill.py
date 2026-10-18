"""Each scene of a story as a picture, for a phone.

Telegram showed the Stage as an .html file: tapped, downloaded, opened in something else,
and on some phones opened in a viewer that runs no script, so the scenes never drew. Reported
as "the stage experience in Telegram is really bad". A chat shows pictures, so each scene is
drawn by the Stage's own code (stage.report_html in still mode) in a throwaway headless
Chromium and photographed card by card. One painter still: nothing here draws.

The browser is the one cdpbrowser finds, driven over a pipe (never a port), with a fresh
profile in a temporary folder that is removed afterwards. No browser means no pictures, and
the caller sends the page as before.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import shutil
import tempfile
from pathlib import Path

WIDTH = 540            # CSS pixels; photographed at 2x, so 1080 wide on the phone
SCALE = 2
MAX_H = 1600           # a card taller than this is cut, at 2x a 1080x3200 picture
TIMEOUT = 40


def available(cfg: dict | None = None) -> bool:
    from . import cdpbrowser
    return bool(cdpbrowser.binary(cfg))


async def render(html: str, cfg: dict | None = None) -> list[bytes]:
    """One PNG per scene card in `html` (a still-mode report). [] when it cannot."""
    from . import cdpbrowser
    binary = cdpbrowser.binary(cfg)
    if not binary:
        return []
    tmp = Path(tempfile.mkdtemp(prefix="bento-still-"))
    proc = None
    try:
        page = tmp / "story.html"
        page.write_text(html, encoding="utf-8")
        args = [binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={tmp / 'p'}",
                "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                "--disable-sync", "--mute-audio", "--hide-scrollbars", "--force-color-profile=srgb",
                f"--window-size={WIDTH},900", "about:blank"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(2, "--no-sandbox")
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", 'exec "$0" "$@" 3<&0 4>&1 0</dev/null 1>/dev/null', *args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=64 * 1024 * 1024)
        cdp = cdpbrowser.CDP(proc)
        return await asyncio.wait_for(_shoot(cdp, page.as_uri()), TIMEOUT)
    except Exception:
        return []
    finally:
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.kill()
                await proc.wait()
        shutil.rmtree(tmp, ignore_errors=True)


async def _shoot(cdp, url: str) -> list[bytes]:
    tgt = (await cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
    s = (await cdp.send("Target.attachToTarget", {"targetId": tgt, "flatten": True}))["sessionId"]
    await cdp.send("Page.enable", session=s)
    await cdp.send("Emulation.setDeviceMetricsOverride",
                   {"width": WIDTH, "height": 900, "deviceScaleFactor": SCALE, "mobile": True}, session=s)
    await cdp.send("Emulation.setEmulatedMedia", {"features": [
        {"name": "prefers-reduced-motion", "value": "reduce"},
        {"name": "prefers-color-scheme", "value": "dark"}]}, session=s)
    await cdp.send("Page.navigate", {"url": url}, session=s)

    async def ev(expr):
        r = await cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                "awaitPromise": True}, session=s)
        return (r.get("result") or {}).get("value")

    # drawn, its pictures loaded (or given up on) and its fonts in
    for _ in range(60):
        if await ev("window.STAGE_STILL_DONE===true"):
            break
        await asyncio.sleep(0.15)
    await ev("Promise.race([Promise.all([document.fonts.ready].concat(Array.from(document.images)"
             ".filter(i=>!i.complete).map(i=>new Promise(r=>{i.onload=i.onerror=r})))),"
             "new Promise(r=>setTimeout(r,6000))]).then(()=>1)")
    await asyncio.sleep(0.3)
    boxes = await ev("Array.from(document.querySelectorAll('.still-card')).map(e=>{const r=e.getBoundingClientRect();"
                     "return [r.left,r.top+scrollY,r.width,r.height]})") or []
    out = []
    for x, y, w, h in boxes:
        shot = await cdp.send("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True,
            "clip": {"x": x, "y": y, "width": w, "height": min(h, MAX_H), "scale": 1}}, session=s)
        out.append(base64.b64decode(shot["data"]))
    return out
