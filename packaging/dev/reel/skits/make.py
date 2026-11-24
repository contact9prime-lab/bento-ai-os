"""Make the ethical-AI skit reels: 1080x1920, 30 fps, voiced, with music and a caption file.

    REEL_TTS_DIR=/path/with/kokoro.onnx+voices.bin  python make.py OUT_DIR [reel-id ...]

Run it with a Python that has kokoro-onnx, soundfile, numpy and playwright (a throwaway
venv: none of them are Bento dependencies). The characters are painted by
agentos/avatars.py, the same painter as the desktop, at its "soft" drawing. Voices are
Kokoro (Apache-2.0, run here, nothing sent anywhere); the music and the sound effects are
synthesised below, so there is nothing to license.

What happens: every line is voiced first and measured, the beats are laid on that clock,
one HTML page draws any moment of the reel (`render(t)`), Chromium photographs it 30 times
a second, and ffmpeg puts the frames and the mixed audio together as H.264 + AAC at -14 LUFS.
Each reel also gets OUT_DIR/<id>.txt: its caption, five hashtags, cover and alt text and a first
comment, ready to paste (`post_text`).
"""
import base64
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from agentos import avatars  # noqa: E402
from reels import MAX_TAGS, REELS  # noqa: E402

FPS, SR = 30, 48000
W, H, SCALE = 540, 960, 2                  # 1080x1920
GAP = 0.2                                 # silence after a line
CHROME = os.environ.get("REEL_CHROME", "/opt/pw-browsers/chromium")
HOOK_LEN, OUTRO_PAD = 0.0, 1.6

_tts = None


def voice(text, name, speed):
    global _tts
    if _tts is None:
        from kokoro_onnx import Kokoro
        d = Path(os.environ.get("REEL_TTS_DIR", "."))
        _tts = Kokoro(str(d / "kokoro.onnx"), str(d / "voices.bin"))
    a, sr = _tts.create(text, voice=name, speed=speed, lang="en-us")
    a = np.asarray(a, dtype=np.float32)
    # resample to SR (linear is fine for speech at 24k -> 48k)
    n = int(len(a) * SR / sr)
    a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    # trim the model's own leading and trailing quiet
    idx = np.where(np.abs(a) > 0.01)[0]
    if len(idx):
        a = a[max(0, idx[0] - 600):idx[-1] + 2400]
    return a


def sprite(rec, frame):
    png = avatars.png_of(rec, frame=frame, draw="soft")
    return "data:image/png;base64," + base64.b64encode(png).decode()


# ---- the clock ------------------------------------------------------------------------

def timeline(reel):
    cast = reel["cast"]
    clips, beats = [], []
    t = 0.25
    hook = voice(reel["hook"] + " " + reel["hook_sub"], cast["bento"]["voice"], 1.0)
    clips.append((t, hook, "vo"))
    hook_end = t + len(hook) / SR + 0.45
    beats.append({"k": "hook", "t0": 0.0, "t1": hook_end})
    t = hook_end + 0.35
    for b in reel["beats"]:
        if "say" in b:
            c = cast[b["who"]]
            a = voice(b["say"], c["voice"], c.get("speed", 1.0))
            d = len(a) / SR
            clips.append((t, a, "vo"))
            clips.append((t - 0.04, sfx("pop"), "fx"))
            beats.append(dict(b, k="say", t0=t, t1=t + d))
            t += d + GAP
        elif "stamp" in b:
            clips.append((t, sfx("thud" if b.get("tone") == "bad" else "ding"), "fx"))
            beats.append(dict(b, k="stamp", t0=t, t1=t + .85))
            t += .85
        elif "type" in b:
            n = len(b["type"])
            for i in range(n):
                clips.append((t + b["secs"] * i / n, sfx("key"), "fx"))
            beats.append(dict(b, k="type", t0=t, t1=t + b["secs"]))
            t += b["secs"]
        elif "enter" in b or "exit" in b:
            clips.append((t, sfx("whoosh"), "fx"))
            beats.append(dict(b, k="move", t0=t, t1=t + 0.6))
            t += 0.5
        elif "pause" in b:
            t += b["pause"]
    t += 0.3
    clips.append((t, sfx("whoosh"), "fx"))
    out = voice(reel["outro"], cast["bento"]["voice"], 1.0)
    clips.append((t + 0.5, out, "vo"))
    end = t + 0.5 + len(out) / SR + OUTRO_PAD
    beats.append({"k": "outro", "t0": t, "t1": end})
    return beats, clips, end


# ---- sound ----------------------------------------------------------------------------

def _env(n, a=0.002, r=0.08):
    x = np.arange(n) / SR
    return np.minimum(1, x / a) * np.exp(-x / r)


def sfx(kind):
    rng = np.random.default_rng({"pop": 1, "thud": 2, "ding": 3, "key": 4, "whoosh": 5}[kind])
    if kind == "pop":
        n = int(.09 * SR); x = np.arange(n) / SR
        return (np.sin(2 * np.pi * (520 + 900 * x / .09) * x) * _env(n, .002, .03) * .25).astype(np.float32)
    if kind == "thud":
        n = int(.5 * SR); x = np.arange(n) / SR
        body = np.sin(2 * np.pi * (110 * np.exp(-x * 8) + 45) * x) * _env(n, .001, .16)
        crack = rng.standard_normal(n) * _env(n, .0005, .02) * .5
        return ((body + crack) * .55).astype(np.float32)
    if kind == "ding":
        n = int(.9 * SR); x = np.arange(n) / SR
        v = sum(np.sin(2 * np.pi * f * x) * g for f, g in ((880, 1), (1320, .5), (1760, .25)))
        return (v * _env(n, .002, .25) * .18).astype(np.float32)
    if kind == "key":
        n = int(.03 * SR)
        return (rng.standard_normal(n) * _env(n, .0003, .006) * .25).astype(np.float32)
    n = int(.5 * SR); x = np.arange(n) / SR
    noise = rng.standard_normal(n)
    # a sweep: noise through a moving one-pole low-pass
    out, y, k = np.zeros(n, np.float32), 0.0, 0
    for i in range(n):
        a = .02 + .25 * math.sin(math.pi * x[i] / .5)
        y += a * (noise[i] - y)
        out[i] = y
    return (out * np.sin(np.pi * x / .5) * .5).astype(np.float32)


def music(secs, seed):
    """A light 100 bpm loop: soft kick, hats, a bass line and warm chords. Made here."""
    n = int(secs * SR)
    x = np.arange(n) / SR
    beat = 60 / 100
    out = np.zeros(n, np.float32)
    rng = np.random.default_rng(seed)
    prog = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]     # Am F C G
    if seed % 2:
        prog = [(50, 53, 57), (58, 62, 65), (53, 57, 60), (52, 55, 59)]  # Dm Bb F E
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)  # noqa: E731
    bar = beat * 4
    for b in range(int(secs / beat) + 1):
        s = int(b * beat * SR)
        if s >= n:
            break
        # kick on 1 and 3, hat on every off-beat
        if b % 2 == 0:
            k = int(.25 * SR); kx = np.arange(k) / SR
            kick = np.sin(2 * np.pi * (60 + 90 * np.exp(-kx * 30)) * kx) * np.exp(-kx * 14) * .5
            out[s:s + k] += kick[:max(0, min(k, n - s))]
        h = s + int(beat / 2 * SR)
        if h < n:
            hk = int(.04 * SR)
            hat = rng.standard_normal(hk) * np.exp(-np.arange(hk) / SR * 120) * .06
            out[h:h + hk] += hat[:max(0, min(hk, n - h))]
    for i in range(int(secs / bar) + 1):
        ch = prog[i % len(prog)]
        s, e = int(i * bar * SR), min(n, int((i + 1) * bar * SR))
        if s >= n:
            break
        cx = x[s:e] - x[s]
        env = np.minimum(1, cx / .4) * np.minimum(1, (bar - cx) / .3)
        pad = sum(np.sin(2 * np.pi * hz(m) * cx) + .25 * np.sin(2 * np.pi * hz(m) * 2.002 * cx) for m in ch)
        out[s:e] += (pad * env * .035).astype(np.float32)
        # bass: root on each beat, plucked
        for q in range(4):
            bs = s + int(q * beat * SR)
            bl = min(int(beat * SR), n - bs)
            if bl <= 0:
                continue
            bx = np.arange(bl) / SR
            f = hz(ch[0] - 12 + (7 if q == 2 else 0))
            out[bs:bs + bl] += (np.sin(2 * np.pi * f * bx) * np.exp(-bx * 5) * .16).astype(np.float32)
    fade = np.minimum(1, np.minimum(x / 1.0, (secs - x) / 1.5))
    return out * fade


def mix(clips, end, seed, speech_spans):
    n = int(end * SR) + SR
    vo, fx = np.zeros(n, np.float32), np.zeros(n, np.float32)
    for t, a, kind in clips:
        s = max(0, int(t * SR))
        e = min(n, s + len(a))
        (vo if kind == "vo" else fx)[s:e] += a[:e - s]
    bed = music(n / SR, seed)
    # duck the music under speech, with a smooth gain curve
    g = np.full(n, 1.0, np.float32)
    for t0, t1 in speech_spans:
        g[int(t0 * SR):int(t1 * SR)] = 0.45
    k = int(.15 * SR)
    g = np.convolve(g, np.ones(k) / k, mode="same").astype(np.float32)
    return np.clip(vo * 1.0 + fx * .8 + bed * g * .9, -1, 1)


# ---- the page -------------------------------------------------------------------------

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0}
html,body{width:540px;height:960px;overflow:hidden;background:#05060f;font-family:Inter,'DejaVu Sans',sans-serif;color:#fff}
#scene{position:absolute;inset:0;overflow:hidden}
.bg{position:absolute;inset:0;background:radial-gradient(120% 70% at 50% 18%,hsl(var(--h) 60% 30%) 0%,hsl(var(--h) 55% 12%) 52%,#05060f 100%)}
.win{position:absolute;left:46px;top:170px;width:150px;height:190px;border-radius:14px;background:linear-gradient(160deg,hsl(var(--h) 70% 70%/.25),hsl(var(--h) 60% 40%/.08));border:2px solid hsl(var(--h) 60% 70%/.18)}
.win:after{content:"";position:absolute;left:50%;top:0;bottom:0;width:2px;background:hsl(var(--h) 60% 70%/.18)}
.win2{left:auto;right:46px;top:150px;width:110px;height:140px}
.floor{position:absolute;left:0;right:0;top:806px;bottom:0;background:linear-gradient(180deg,hsl(var(--h) 40% 16%),hsl(var(--h) 40% 7%))}
.floor:before{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:hsl(var(--h) 60% 70%/.25)}
.dots{position:absolute;inset:0;background-image:radial-gradient(hsl(var(--h) 80% 80%/.08) 1px,transparent 1.5px);background-size:22px 22px}
#top{position:absolute;left:0;right:0;top:0;padding:30px 28px 0;text-align:center;z-index:5}
#top .k{font:800 12px/1 Inter;letter-spacing:.24em;color:hsl(var(--h) 90% 80%)}
.ch{position:absolute;bottom:148px;width:180px;margin-left:-90px;transform-origin:50% 100%;z-index:3}
.ch img{width:180px;height:292px;image-rendering:pixelated;display:block;filter:drop-shadow(0 14px 18px rgba(0,0,0,.5))}
.ch .tag{position:absolute;left:50%;bottom:-36px;transform:translateX(-50%);padding:5px 12px;border-radius:999px;
  background:rgba(5,6,15,.7);border:1px solid rgba(255,255,255,.18);font:700 14px/1 Inter;white-space:nowrap}
.ch.villain img{filter:drop-shadow(0 0 18px rgba(255,60,90,.75)) hue-rotate(-10deg) saturate(1.3)}
.ch .halo{position:absolute;left:50%;top:40%;width:300px;height:300px;margin:-150px 0 0 -150px;border-radius:50%;
  background:radial-gradient(circle,hsl(172 90% 60%/.55),transparent 65%);opacity:0}
.shadow{position:absolute;bottom:136px;width:150px;height:26px;margin-left:-75px;border-radius:50%;background:rgba(0,0,0,.45);filter:blur(5px);z-index:2}
#bubble{position:absolute;bottom:462px;left:24px;right:24px;z-index:6;padding:16px 20px 18px;border-radius:24px;
  background:#fff;color:#11131f;box-shadow:0 18px 40px rgba(0,0,0,.45);transform-origin:50% 100%}
#bubble .n{font:800 13px/1 Inter;letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px}
#bubble .tx{font:700 25px/1.22 Inter;letter-spacing:-.01em}
#bubble .tx .w{opacity:.14}
#bubble .tx .w.on{opacity:1}
#bubble:after{content:"";position:absolute;bottom:-16px;left:var(--tail);width:32px;height:32px;margin-left:-16px;background:#fff;transform:rotate(45deg);border-radius:4px}
#bubble.villain{background:#1a0a12;color:#ffd6de;border:2px solid #ff4d6d}
#bubble.villain:after{background:#1a0a12;border-right:2px solid #ff4d6d;border-bottom:2px solid #ff4d6d}
#prop{position:absolute;left:34px;right:34px;top:96px;z-index:4;border-radius:22px;padding:18px 20px;
  background:rgba(12,14,30,.86);border:1px solid rgba(255,255,255,.14);box-shadow:0 24px 60px rgba(0,0,0,.5);
  border-left:6px solid var(--c)}
#prop .t{display:flex;align-items:center;gap:10px;font:800 21px/1.1 Inter;color:var(--c)}
#prop .t .i{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;background:var(--c);color:#0b0d1a;font-size:18px}
#prop .cmd{margin-top:12px;padding:10px 12px;border-radius:10px;background:#05060d;font:600 16px/1.3 'DejaVu Sans Mono',monospace;color:#9ff0d0}
#prop .l{margin-top:10px;font:600 17px/1.3 Inter;color:#dfe2ff;display:flex;gap:8px}
#prop .l:before{content:"•";color:var(--c)}
#prop .from{margin-top:8px;font:600 14px/1.2 Inter;color:#9aa0c8}
#prop .body{margin-top:10px;padding:12px;border-radius:12px;background:rgba(255,77,109,.12);border:1px dashed #ff4d6d;font:600 17px/1.35 Inter;color:#ffd6de}
#prop .box{margin-top:14px;padding:12px 14px;border-radius:12px;background:#05060d;border:2px solid var(--c);font:600 19px/1 'DejaVu Sans Mono',monospace;color:#fff;min-height:46px}
#prop .box .ph{color:#5b6190}
#prop .box .cur{display:inline-block;width:10px;height:20px;background:var(--c);vertical-align:-3px;margin-left:2px}
#prop .btns{display:flex;gap:10px;margin-top:14px}
#prop .btns span{flex:1;text-align:center;padding:11px;border-radius:12px;font:800 16px/1 Inter}
#prop .btns .y{background:var(--c);color:#0b0d1a}#prop .btns .n{background:rgba(255,255,255,.1)}
#prop .row{margin-top:8px;padding:9px 12px;border-radius:10px;background:rgba(255,255,255,.06);font:600 16px/1.2 Inter;color:#dfe2ff}
#prop .row.bad{background:rgba(255,77,109,.14);color:#ffd6de;border:1px solid rgba(255,77,109,.5)}
#stamp{position:absolute;left:0;right:0;top:400px;z-index:8;text-align:center;font:900 76px/1 Inter;letter-spacing:-.02em;
  -webkit-text-stroke:3px rgba(0,0,0,.35);text-shadow:0 10px 40px rgba(0,0,0,.6)}
#foot{position:absolute;left:0;right:0;bottom:26px;text-align:center;font:600 12px/1.3 Inter;color:rgba(255,255,255,.5);z-index:5}
#card{position:absolute;inset:0;z-index:20;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:20px;padding:40px 34px;text-align:center;background:radial-gradient(120% 80% at 50% 25%,hsl(var(--h) 60% 32%) 0%,#0b0d1f 58%,#05060f 100%)}
#card .face{width:150px;height:150px;border-radius:40px;background:rgba(255,255,255,.08);border:2px solid rgba(255,255,255,.15);
  display:grid;place-items:center;overflow:hidden}
#card .face img{width:120px;image-rendering:pixelated;margin-top:30px}
#card .k{font:800 13px/1 Inter;letter-spacing:.24em;color:hsl(var(--h) 90% 82%)}
#card .h{font:900 46px/1.05 Inter;letter-spacing:-.03em}
#card .s{font:800 26px/1.2 Inter;color:hsl(var(--h) 95% 75%)}
#card .pill{margin-top:6px;padding:12px 20px;border-radius:999px;background:#fff;color:#0b0d1a;font:800 16px/1 Inter}
#card .small{font:600 15px/1.4 Inter;color:#cfd3ff;max-width:420px}
</style></head><body>
<div id="scene"><div class="bg"></div><div class="dots"></div><div class="win"></div><div class="win win2"></div><div class="floor"></div></div>
<div id="top"><div class="k" id="kick"></div></div>
<div id="prop" style="display:none"></div>
<div id="bubble" style="display:none"><div class="n"></div><div class="tx"></div></div>
<div id="stamp" style="display:none"></div>
<div id="foot">Dramatised · the checks shown are real Bento behaviour</div>
<div id="card"></div>
<script>
const R = __DATA__;
document.documentElement.style.setProperty('--h', R.hue);
document.getElementById('kick').textContent = R.kicker;
const $ = id => document.getElementById(id);
const CH = {};
for (const [id, c] of Object.entries(R.cast)) {
  const sh = document.createElement('div'); sh.className = 'shadow'; document.body.appendChild(sh);
  const d = document.createElement('div'); d.className = 'ch' + (c.villain ? ' villain' : '');
  d.innerHTML = '<div class="halo"></div><img><div class="tag"></div>';
  d.querySelector('.tag').textContent = c.name;
  document.body.appendChild(d);
  CH[id] = {el: d, img: d.querySelector('img'), halo: d.querySelector('.halo'), sh, c, src: ''};
}
const esc = s => String(s).replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const ease = x => x < 0 ? 0 : x > 1 ? 1 : 1 - Math.pow(1 - x, 3);
const back = x => { x = Math.max(0, Math.min(1, x)); const c = 1.7; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
const COL = {refuse:'#ff4d6d', alert:'#ffb347', code:'#8b93ff', ok:'#3ee0a0', confirm:'#ffd166', email:'#ff4d6d', inbox:'#7cc4ff'};
const ICON = {refuse:'✕', alert:'!', code:'{}', ok:'✓', confirm:'⌨', email:'✉', inbox:'✉'};
function propHTML(p, typed, cursor) {
  let h = `<div class="t"><span class="i">${ICON[p.kind]}</span>${esc(p.title)}</div>`;
  if (p.cmd) h += `<div class="cmd">$ ${esc(p.cmd)}</div>`;
  if (p.from) h += `<div class="from">From: ${esc(p.from)}</div>`;
  if (p.body) h += `<div class="body">${esc(p.body)}</div>`;
  if (p.kind === 'inbox') h += (p.lines||[]).map((l, i) => `<div class="row${i === p.lines.length - 1 ? ' bad' : ''}">${esc(l)}</div>`).join('');
  else h += (p.lines||[]).map(l => `<div class="l">${esc(l)}</div>`).join('');
  if (p.phrase) h += `<div class="box">${typed ? esc(typed) : `<span class="ph">${esc(p.phrase)}</span>`}${cursor ? '<span class="cur"></span>' : ''}</div>`;
  if (p.buttons || p.phrase) h += `<div class="btns"><span class="n">Cancel</span><span class="y">${p.phrase ? 'Delete' : 'Send'}</span></div>`;
  return h;
}
let lastProp = '';
function render(t) {
  const B = R.beats;
  // the cards: hook and outro
  const hook = B.find(b => b.k === 'hook'), outro = B.find(b => b.k === 'outro');
  const card = $('card');
  if (t < hook.t1 + .35) {
    const o = t < hook.t1 ? 1 : 1 - (t - hook.t1) / .35;
    card.style.opacity = o; card.style.display = 'flex';
    if (card.dataset.k !== 'hook') {
      card.dataset.k = 'hook';
      card.innerHTML = `<div class="face"><img src="${R.cast.bento.f[0]}"></div><div class="k">${esc(R.kicker)}</div>
        <div class="h">${esc(R.hook)}</div><div class="s">${esc(R.hook_sub)}</div>`;
    }
    const s = back(t / .5);
    card.querySelector('.h').style.transform = `scale(${.85 + .15 * s})`;
    card.querySelector('.s').style.opacity = ease((t - .9) / .4);
    card.querySelector('.face img').src = R.cast.bento.f[(Math.floor(t * 2) % 7 === 3) ? 1 : 0];
  } else if (t >= outro.t0) {
    const o = ease((t - outro.t0) / .4);
    card.style.opacity = o; card.style.display = 'flex';
    if (card.dataset.k !== 'outro') {
      card.dataset.k = 'outro';
      card.innerHTML = `<div class="face"><img src="${R.cast.bento.f[2]}"></div><div class="h">Bento Box AI</div>
        <div class="small">${esc(R.outro.replace(/^Bento Box AI\.\s*/, ''))}</div>
        <div class="small">Ethics checks are plain code, not a prompt. You stay in charge.</div>
        <div class="pill">Open source · link in bio</div>`;
    }
    card.querySelector('.face img').src = R.cast.bento.f[2 + (Math.floor(t * 3) % 2)];
  } else { card.style.display = 'none'; }

  // who is on stage
  const vis = {};
  for (const [id, c] of Object.entries(R.cast)) vis[id] = c.hidden ? 0 : 1;
  for (const b of B) {
    if (b.k !== 'move' || b.t0 > t) continue;
    const p = ease((t - b.t0) / .5);
    if (b.enter) vis[b.enter] = p; if (b.exit) vis[b.exit] = 1 - p;
  }
  // the line being said (or the last one, while it lingers)
  let say = null;
  for (const b of B) if (b.k === 'say' && b.t0 - .05 <= t) say = b;
  const live = say && t <= say.t1 + .25;
  // the prop: the last `show` set before now
  let prop = null, typed = '', typing = false;
  for (const b of B) {
    if (b.t0 > t) break;
    if ('show' in b) prop = b.show ? {p: b.show, t0: b.t0} : null;
    if (b.k === 'type') { const n = Math.floor(b.type.length * Math.min(1, (t - b.t0) / b.secs)); typed = b.type.slice(0, n); typing = t < b.t1 + .8; }
  }
  const pe = $('prop');
  if (prop && !card.style.display.includes('flex')) {
    const key = JSON.stringify(prop.p) + typed + (typing && Math.floor(t * 3) % 2);
    if (key !== lastProp) { pe.innerHTML = propHTML(prop.p, typed, typing && Math.floor(t * 3) % 2 === 0); lastProp = key; }
    pe.style.setProperty('--c', COL[prop.p.kind] || '#8b93ff');
    const k = back((t - prop.t0) / .45);
    pe.style.display = 'block'; pe.style.opacity = Math.min(1, (t - prop.t0) / .2);
    pe.style.transform = `translateY(${(1 - k) * 30}px) scale(${.92 + .08 * k})`;
  } else pe.style.display = 'none';

  // characters
  for (const [id, o] of Object.entries(CH)) {
    const c = o.c, v = vis[id];
    const speaking = live && say.who === id && t <= say.t1;
    let x = c.x * 540, y = 0, rot = 0, sc = 1, frame = (Math.floor(t * 1.7 + c.x * 7) % 9 === 0) ? 1 : 0;
    y -= Math.sin(t * 2.2 + c.x * 5) * 3;                         // breathing
    if (speaking) { y -= Math.abs(Math.sin((t - say.t0) * 9)) * 9; sc = 1.04; }
    const act = say && say.who === id && t <= say.t1 + .4 ? say.act : '';
    const at = say ? t - say.t0 : 0;
    if (act === 'wave') frame = 2 + (Math.floor(at * 4) % 2);
    if (act === 'shake') x += Math.sin(at * 40) * 7 * Math.max(0, 1 - at / 1.2);
    if (act === 'lean') rot = (c.x < .5 ? 1 : -1) * 6 * ease(at / .3);
    if (act === 'shrug') { frame = at < 1 ? 2 : 0; rot = Math.sin(at * 6) * 3; }
    if (act === 'slump') { y += 14 * ease(at / .4); rot = (c.x < .5 ? -1 : 1) * 4; sc = .97; }
    o.halo.style.opacity = act === 'glow' ? (.5 + .3 * Math.sin(at * 6)) * ease(at / .3) : 0;
    const enter = (1 - v) * (c.x < .5 ? -1 : 1) * 380;
    o.el.style.left = (x + enter) + 'px'; o.sh.style.left = (x + enter) + 'px';
    o.el.style.transform = `translateY(${y}px) rotate(${rot}deg) scale(${sc})`;
    o.el.style.opacity = v; o.sh.style.opacity = v * .9;
    o.el.style.filter = live && !speaking ? 'brightness(.72)' : '';
    const src = c.f[frame];
    if (o.src !== src) { o.img.src = src; o.src = src; }
  }

  // the bubble
  const bu = $('bubble');
  if (live && card.style.display === 'none') {
    const c = R.cast[say.who];
    bu.style.display = 'block';
    bu.className = c.villain ? 'villain' : '';
    bu.style.setProperty('--tail', Math.max(50, Math.min(442, c.x * 540 - 24)) + 'px');
    const n = bu.querySelector('.n'); n.textContent = c.name; n.style.color = c.villain ? '#ff7d94' : `hsl(${c.rec.hue} 70% 38%)`;
    const words = say.say.split(' ');
    const p = (t - say.t0) / Math.max(.3, (say.t1 - say.t0) * .92);
    const on = Math.ceil(words.length * Math.min(1, Math.max(0, p)));
    const key = say.t0 + ':' + on;
    if (bu.dataset.key !== key) {
      bu.dataset.key = key;
      bu.querySelector('.tx').innerHTML = words.map((w, i) => `<span class="w${i < on ? ' on' : ''}">${esc(w)}</span>`).join(' ');
    }
    const k = back((t - say.t0 + .05) / .3), out = t > say.t1 ? 1 - (t - say.t1) / .25 : 1;
    bu.style.transform = `scale(${(.85 + .15 * k)})`; bu.style.opacity = Math.max(0, out);
  } else bu.style.display = 'none';

  // stamps
  const st = $('stamp');
  const sb = B.find(b => b.k === 'stamp' && b.t0 <= t && t <= b.t1);
  if (sb) {
    const a = t - sb.t0;
    st.style.display = 'block'; st.textContent = sb.stamp;
    st.style.color = sb.tone === 'bad' ? '#ff4d6d' : '#3ee0a0';
    const s = a < .18 ? 2.2 - 1.2 * (a / .18) : 1 + .03 * Math.sin(a * 20) * Math.max(0, 1 - a);
    st.style.transform = `scale(${s}) rotate(-8deg)`; st.style.opacity = a > .8 ? 1 - (a - .8) / .2 : 1;
    document.body.style.transform = a < .25 ? `translate(${Math.sin(a * 90) * 6 * (1 - a / .25)}px,0)` : '';
  } else { st.style.display = 'none'; document.body.style.transform = ''; }
}
window.render = render;
</script></body></html>"""


def build_page(reel, beats):
    cast = {}
    for cid, c in reel["cast"].items():
        cast[cid] = {"name": c["name"], "x": c["x"], "hidden": c.get("hidden", False),
                     "villain": c.get("villain", False), "rec": c["rec"],
                     "f": [sprite(c["rec"], f) for f in range(4)]}
    data = {"hue": reel["hue"], "kicker": reel["kicker"], "hook": reel["hook"], "hook_sub": reel["hook_sub"],
            "outro": reel["outro"], "cast": cast, "beats": beats}
    return PAGE.replace("__DATA__", json.dumps(data))


def shoot(html_path, frames_dir, end, stills):
    from playwright.sync_api import sync_playwright
    frames_dir.mkdir(parents=True, exist_ok=True)
    for f in frames_dir.glob("*.jpg"):
        f.unlink()
    n = 0 if os.environ.get("REEL_STILLS") else int(math.ceil(end * FPS))
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME)
        p = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=SCALE)
        errs = []
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(html_path.as_uri())
        p.wait_for_timeout(600)
        for i in range(n):
            t = i / FPS
            p.evaluate(f"render({t:.4f})")
            p.screenshot(path=str(frames_dir / f"{i:05d}.jpg"), type="jpeg", quality=92)
        for name, t in stills.items():
            p.evaluate(f"render({t:.4f})")
            p.screenshot(path=str(frames_dir.parent / f"{name}.png"))
        b.close()
        if errs:
            raise SystemExit("page errors: " + "; ".join(errs[:3]))
    return n


def post_text(reel):
    """What goes on Instagram with the reel, in the order it is pasted. Five hashtags at most,
    because Instagram takes five per post and the first comment shares them."""
    p = reel["post"]
    tags = p["tags"]
    if len(tags) > MAX_TAGS or len(set(tags)) != len(tags) or not all(t.startswith("#") for t in tags):
        raise SystemExit(f"{reel['id']}: {len(tags)} hashtags; Instagram takes {MAX_TAGS}, each starting with #")
    if "#" in p["first_comment"]:
        raise SystemExit(f"{reel['id']}: a hashtag in the first comment counts against the same {MAX_TAGS}")
    return (f"CAPTION\n{p['caption']}\n\n{' '.join(tags)}\n\n"
            f"COVER TEXT\n{p['cover']}\n\n"
            f"ALT TEXT (Advanced settings)\n{p['alt']}\n\n"
            f"FIRST COMMENT (pin it)\n{p['first_comment']}\n\n"
            f"KEYWORDS (what people search for: say them in the caption and on screen)\n{', '.join(p['keywords'])}\n")


def make(reel, out: Path):
    work = out / reel["id"]
    work.mkdir(parents=True, exist_ok=True)
    print(f"[{reel['id']}] voicing")
    beats, clips, end = timeline(reel)
    spans = [(b["t0"], b["t1"]) for b in beats if b["k"] == "say"]
    hook = next(b for b in beats if b["k"] == "hook")
    spans += [(0.2, hook["t1"]), (beats[-1]["t0"] + .4, end)]
    seed = REELS.index(reel)
    sf.write(work / "audio.wav", mix(clips, end, seed, spans), SR, subtype="PCM_16")
    page = work / "reel.html"
    page.write_text(build_page(reel, beats))
    # stills worth looking at: the cover, each prop's first full second, the outro
    stills = {"cover": 0.8, "outro": end - 0.8}
    for i, b in enumerate(beats):
        if b.get("show"):
            stills[f"beat{i:02d}"] = b["t0"] + 1.2
        if b["k"] == "stamp":
            stills[f"stamp{i:02d}"] = b["t0"] + .4
    print(f"[{reel['id']}] filming {end:.1f} s")
    shoot(page, work / "frames", end, stills)
    if os.environ.get("REEL_STILLS"):
        return None
    mp4 = out / f"bento-ethics-{reel['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-framerate", str(FPS), "-i", str(work / "frames" / "%05d.jpg"),
                    "-i", str(work / "audio.wav"),
                    "-filter_complex", "[0:v]format=yuv420p[v];[1:a]loudnorm=I=-14:TP=-1.5:LRA=9[a]",
                    "-map", "[v]", "-map", "[a]", "-t", f"{end:.2f}",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-r", str(FPS),
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(mp4)], check=True)
    (out / f"bento-ethics-{reel['id']}.txt").write_text(post_text(reel))
    print(f"[{reel['id']}] {mp4} ({end:.1f} s)")
    return mp4


def main():
    out = Path(sys.argv[1])
    want = set(sys.argv[2:])
    for reel in REELS:
        if not want or reel["id"] in want:
            make(reel, out)


if __name__ == "__main__":
    main()
