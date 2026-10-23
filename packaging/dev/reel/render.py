"""Turn a record.py folder into a 1080x1920 video with sound, for a reel.

The top is the terminal (exactly what the commands printed), the bottom the machine's own
screen (exactly what it showed). Real time is squeezed: each event gets at most MAX_GAP of
video, so a twenty-minute install fits in about a minute and every line is still shown. The
music is a square-wave chiptune made here, so there is nothing to license.

    uv run --no-project --with playwright python packaging/dev/reel/render.py REC_DIR [OUT.mp4]

Needs Chrome (or Chromium) and ffmpeg. The default output is ~/Videos/<folder name>.mp4.
"""
import asyncio
import base64
import html
import json
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

from playwright.async_api import async_playwright

R = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "Videos" / f"{R.name}.mp4"
FPS, MAX_GAP, MIN_GAP, LINES, HOLD_END = 12, 0.55, 0.12, 19, 4.0
TITLE = os.environ.get("REEL_TITLE", "Remove it. Add it back.<br>One command each.")
KICKER = os.environ.get("REEL_KICKER", "BENTO · FROM THE HUB")
CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")

ev = [json.loads(x) for x in (R / "lines.jsonl").read_text().splitlines() if x.strip()]
vt, last, t = [], 0.0, 1.2
for e in ev:
    gap = e["t"] - last
    t += max(MIN_GAP if e["kind"] != "pi" else 0.0, min(MAX_GAP, gap * 0.05 + (0.18 if e["kind"] == "out" else 0)))
    if e["kind"] == "cmd":
        t += 1.0
    vt.append(t)
    last = e["t"]
DUR = vt[-1] + HOLD_END


def phase(lines):
    cmd = next((x for x in reversed(lines) if x.startswith("$ ")), "")
    text = " ".join(lines[-12:]).lower()
    if " remove " in cmd:
        return "1 · Remove Bento from the Pi"
    if " install " in cmd:
        return "2 · Installed. The hub sets it up" if "bento is installed" in text else "2 · Install it again"
    if " controls " in cmd:
        return "3 · Read back from the Pi"
    return ""


def page(lines, pi, clock, ph):
    def row(x):
        s = x.lstrip("│ ").lstrip()
        cls = ("cmd" if x.startswith("$ ") else "ok" if s.startswith(("✓", "·", "●")) else
               "bad" if s.startswith(("✗", "!")) else "step" if s.startswith(("▲", "──")) else "")
        return f'<div class="l {cls}">{html.escape(x[:58])}</div>'
    img = f'<img src="{pi}">' if pi else '<div class="nopi">the Pi\'s screen</div>'
    return f"""<html><head><style>
    *{{box-sizing:border-box}}body{{margin:0;width:1080px;height:1920px;background:#0b0d1a;color:#e8eaf6;
      font-family:'DejaVu Sans',sans-serif;overflow:hidden;position:relative}}
    .top{{padding:70px 64px 26px}}.k{{font:600 30px 'DejaVu Sans Mono',monospace;color:#8b93ff;letter-spacing:.06em}}
    .h{{font:800 62px/1.08 'DejaVu Sans',sans-serif;margin-top:12px}}
    .ph{{margin:22px 64px 0;font:700 34px 'DejaVu Sans',sans-serif;color:#ffd166}}
    .term{{margin:22px 40px 0;height:820px;border-radius:26px;background:#05060d;border:3px solid #2a2f55;padding:26px 30px;overflow:hidden}}
    .l{{font:26px/1.55 'DejaVu Sans Mono',monospace;color:#b8bdd9;white-space:pre}}
    .cmd{{color:#7ee787;font-weight:700}}.ok{{color:#7ee787}}.bad{{color:#ffb86b}}.step{{color:#e8eaf6}}
    .pi{{margin:26px 40px 0;height:560px;border-radius:26px;background:#000;border:3px solid #2a2f55;overflow:hidden;position:relative}}
    .pi img{{width:100%;height:100%;object-fit:cover}}
    .tag{{position:absolute;left:18px;top:16px;background:#0b0d1acc;padding:8px 16px;border-radius:999px;font:600 24px 'DejaVu Sans',sans-serif}}
    .nopi{{display:grid;place-items:center;height:100%;color:#555b80;font-size:30px}}
    .clock{{position:absolute;right:64px;top:74px;font:600 28px 'DejaVu Sans Mono',monospace;color:#555b80}}
    </style></head><body>
    <div class="top"><div class="k">{KICKER}</div><div class="h">{TITLE}</div></div>
    <div class="clock">{clock}</div><div class="ph">{html.escape(ph)}</div>
    <div class="term">{"".join(row(x) for x in lines[-LINES:])}</div>
    <div class="pi">{img}<div class="tag">the Pi's own screen</div></div></body></html>"""


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


async def main():
    frames = R / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1080, "height": 1920})
        lines, pi, j, cache, prev = [], "", 0, {}, None
        n = int(DUR * FPS)
        for fi in range(n):
            now = fi / FPS
            while j < len(ev) and vt[j] <= now:
                e = ev[j]
                if e["kind"] in ("cmd", "out"):
                    lines.append(e["text"])
                elif e["kind"] == "pi":
                    name = os.path.basename(e["text"])
                    if name not in cache:
                        cache[name] = "data:image/png;base64," + base64.b64encode((R / "pi" / name).read_bytes()).decode()
                    pi = cache[name]
                j += 1
            real = ev[max(0, j - 1)]["t"] if j else 0
            doc = page(lines, pi, f"{int(real // 60):02d}:{int(real % 60):02d}", phase(lines))
            if doc != prev:
                await pg.set_content(doc)
                await pg.screenshot(path=str(frames / f"{fi:05d}.png"))
                prev = doc
            else:
                os.link(frames / f"{fi - 1:05d}.png", frames / f"{fi:05d}.png")
        await b.close()
    chiptune(R / "music.wav", DUR)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "%05d.png"),
                    "-i", str(R / "music.wav"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(OUT)], check=True)
    shutil.rmtree(frames, ignore_errors=True)
    print(f"{OUT}: {DUR:.1f} s")


asyncio.run(main())
