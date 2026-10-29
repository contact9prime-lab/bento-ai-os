"""Film the warehouse run working, for a reel: 1080x1920, with sound.

Drives the hub's own desktop in Chrome at a phone's size (540x960 at 2x) while `run.py --keep`
(or `--setup-only`) is running: the device map, "walk me through the warehouse", cold room B's
compressor tripping on the stand-in node, the agent finding it and asking, a person tapping Allow
on the card, and the compressor read back from the node. Nothing is mocked here: every number on
screen came from esp_sim.py's nodes through the zone Pis. Captions are laid over the page; the
frames are the page as it was.

    uv run --no-project --with playwright python packaging/dev/warehouse/film.py [OUT.mp4]

Needs Chrome and ffmpeg. The music is the reel's own chiptune (reel/render.py), nothing licensed.
"""
import asyncio
import json
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
HUB = "http://127.0.0.1:8581"
CONTROL = {"zone-cold": 18817, "zone-dock": 18827, "zone-aisle": 18837}
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Videos" / "bento-warehouse.mp4"
CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
WORK = OUT.parent / (OUT.stem + "-frames")

CSS = """
#reel-cap{position:fixed;left:16px;right:16px;top:64px;z-index:2147483000;padding:12px 16px;border-radius:16px;
  background:rgba(8,8,20,.86);border:1px solid rgba(160,140,255,.45);color:#fff;font:600 19px/1.3 system-ui,sans-serif;
  box-shadow:0 10px 30px rgba(0,0,0,.5);transition:opacity .35s;pointer-events:none}
#reel-cap small{display:block;font:700 11px/1.4 system-ui;letter-spacing:.14em;color:#b9a8ff;margin-bottom:3px}
#reel-card{position:fixed;inset:0;z-index:2147483001;display:flex;flex-direction:column;justify-content:center;
  align-items:center;text-align:center;padding:40px;background:radial-gradient(circle at 50% 40%,#2b1d63,#07070f 70%);
  color:#fff;font:800 40px/1.15 system-ui,sans-serif;transition:opacity .5s;pointer-events:none}
#reel-card small{font:700 13px/1.4 system-ui;letter-spacing:.2em;color:#b9a8ff;margin-bottom:22px}
#reel-card p{font:500 19px/1.45 system-ui;color:#cfcbe8;margin-top:24px;max-width:420px}
"""


def poke(zone, node, entity, value):
    req = urllib.request.Request(f"http://127.0.0.1:{CONTROL[zone]}/", method="POST",
                                 data=json.dumps({"node": node, "entity": entity, "value": value}).encode())
    urllib.request.urlopen(req, timeout=5).read()


def sim(zone):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CONTROL[zone]}/", timeout=5).read())


class Camera:
    """Frames with the time each was taken, so the video runs at the real pace."""

    def __init__(self, page):
        self.page, self.shots, self.on = page, [], True

    async def roll(self):
        WORK.mkdir(parents=True, exist_ok=True)
        while self.on:
            t = time.monotonic()
            p = WORK / f"{len(self.shots):05d}.jpg"
            try:
                await self.page.screenshot(path=str(p), type="jpeg", quality=92)
                self.shots.append((t, p))
            except Exception:
                pass
            await asyncio.sleep(max(0.0, 0.1 - (time.monotonic() - t)))


async def caption(page, kicker, text):
    await page.evaluate("""([k,t])=>{let c=document.getElementById('reel-cap');
      if(!c){c=document.createElement('div');c.id='reel-cap';document.body.appendChild(c)}
      c.style.opacity=t?1:0;c.innerHTML=t?`<small>${k}</small>${t}`:''}""", [kicker, text])


async def card(page, kicker, title, sub=""):
    await page.evaluate("""([k,t,s])=>{let c=document.getElementById('reel-card');
      if(!c){c=document.createElement('div');c.id='reel-card';document.body.appendChild(c)}
      c.style.opacity=t?1:0;c.innerHTML=t?`<small>${k}</small><div>${t}</div>${s?`<p>${s}</p>`:''}`:''}""",
                        [kicker, title, sub])


async def ask(page, text, allow=False, timeout=120):
    box = page.locator("#input")
    await box.click()
    await box.type(text, delay=38)
    await page.wait_for_timeout(500)
    await page.keyboard.press("Enter")
    t0 = time.time()
    clicked = False
    while time.time() - t0 < timeout:
        if allow and not clicked:
            btn = page.locator(".approval button.allow, button.allow").locator("visible=true").first
            if await btn.count():
                await page.wait_for_timeout(2600)      # long enough to read the card
                await btn.click()
                clicked = True
        busy = await page.evaluate("typeof RUNNING!=='undefined' && RUNNING && RUNNING.size>0")
        if not busy and time.time() - t0 > 4 and (clicked or not allow):
            return clicked
        await page.wait_for_timeout(250)
    return clicked


async def main():
    # a clean starting floor: fans off, both compressors running
    poke("zone-aisle", "aisle-2", "Ceiling fan", False)
    poke("zone-cold", "cold-2", "Compressor", True)
    poke("zone-dock", "charge-1", "Forklift battery", 78.0)      # a long --keep run drains it
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME)
        ctx = await b.new_context(viewport={"width": 540, "height": 960}, device_scale_factor=2,
                                  has_touch=True, is_mobile=True)
        page = await ctx.new_page()
        await page.goto(HUB + "/")
        await page.add_style_tag(content=CSS)
        # the brain list can arrive after the first paint; start once the chip names one
        for _ in range(60):
            if await page.evaluate("!!(typeof BRAINS!=='undefined'&&BRAINS.executors&&curExecutor())"):
                break
            await page.wait_for_timeout(500)
        await page.evaluate("typeof paintForwardChip==='function'&&paintForwardChip()")
        await card(page, "BENTO · ONE HUB", "One hub.<br>Three Pis.<br>Six ESP32s.",
                   "A warehouse run from one place, in a simulation built on ESPHome's own protocol.")
        cam = Camera(page)
        roll = asyncio.create_task(cam.roll())
        await page.wait_for_timeout(3200)

        await page.evaluate("openApp('devices')")
        await page.wait_for_timeout(1500)
        await card(page, "", "")
        await caption(page, "THE DEVICE MAP", "The hub and the three zone Pis it set up. Each Pi looks after two ESP32 nodes.")
        await page.wait_for_timeout(5000)

        await page.evaluate("openApp('chat')")
        await page.wait_for_timeout(1200)
        await caption(page, "LIVE FROM THE NODES", "Ask the hub's agent how the floor is.")
        await page.wait_for_timeout(1600)
        await ask(page, "Morning. Walk me through the warehouse.")
        await caption(page, "READ, NOT GUESSED", "Seven readings across three zones, straight from the ESP32s.")
        await page.wait_for_timeout(4500)

        await caption(page, "SOMETHING BREAKS", "Cold room B's compressor trips. The room starts to warm.")
        poke("zone-cold", "cold-2", "Compressor", False)
        t0 = time.time()
        while sim("zone-cold")["cold-2"]["ents"]["Cold room temperature"] < -15 and time.time() - t0 < 90:
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(1200)
        await caption(page, "IT FINDS IT", "It reads the room, the door and the compressor. To switch something on, it asks you.")
        await ask(page, "Cold room B looks warm. What's going on?", allow=True)
        on = sim("zone-cold")["cold-2"]["ents"]["Compressor"]
        await caption(page, "READ BACK FROM THE NODE", "You said yes. The compressor is on again: " + ("confirmed by the node." if on else "not confirmed."))
        await page.wait_for_timeout(5500)

        await caption(page, "", "")
        await card(page, "BENTO BOX AI", "Every read logged.<br>Every switch asked.",
                   "Open source. Runs on your hub, your Pis and a few cheap ESP32 boards.")
        await page.wait_for_timeout(4000)
        cam.on = False
        await roll
        await b.close()
    if not on:
        sys.exit("the compressor was not read back on; not making the video")
    render(cam.shots)


# the reel's own music (reel/render.py), copied: importing that file runs it
def chiptune(path, secs, rate=22050):
    notes = [0, 4, 7, 12, 7, 4, 0, 4, 5, 9, 12, 17, 12, 9, 5, 9, 7, 11, 14, 19, 14, 11, 7, 11, 0, 4, 7, 12, 16, 12, 7, 4]
    bass, step = [0, 0, 5, 5, 7, 7, 0, 0], 0.15
    w = wave.open(str(path), "w")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    buf = bytearray()
    for i in range(int(secs * rate)):
        t = i / rate
        k = int(t / step)
        f = 440 * 2 ** ((notes[k % len(notes)] - 9) / 12)
        fb = 110 * 2 ** ((bass[(k // 4) % len(bass)] - 9) / 12)
        env = max(0.0, 1 - ((t % step) / step) * 1.6)
        lead = (1 if (t * f) % 1 < 0.5 else -1) * 0.16 * env
        b = (1 if (t * fb) % 1 < 0.25 else -1) * 0.10
        fade = min(1.0, t / 1.5, (secs - t) / 2.0)
        buf += struct.pack("<h", int(max(-1, min(1, (lead + b) * fade)) * 30000))
    w.writeframes(bytes(buf))
    w.close()


def render(shots):
    lst = WORK / "frames.txt"
    with open(lst, "w") as f:
        for (t, pth), nxt in zip(shots, shots[1:] + [(shots[-1][0] + 0.1, None)]):
            f.write(f"file '{pth}'\nduration {max(0.04, nxt[0] - t):.3f}\n")
        f.write(f"file '{shots[-1][1]}'\n")
    secs = shots[-1][0] - shots[0][0] + 0.1
    chiptune(WORK / "music.wav", secs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-i", str(WORK / "music.wav"), "-vf", "scale=1080:1920,fps=30,format=yuv420p",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", "-movflags", "+faststart", str(OUT)], check=True)
    print(OUT, f"{secs:.1f}s, {len(shots)} frames")


if __name__ == "__main__":
    asyncio.run(main())
