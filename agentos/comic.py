"""Comic panels as pictures: the Office, for places that cannot run the Office.

The desktop draws the playground live on a canvas. A Telegram chat cannot: it takes
text and pictures. So the moments the Office animates — one agent asking another, a
huddle, who is working right now — are drawn here as a comic STRIP, a PNG, and sent
as a photo with the full words in its caption.

Four rules, the same ones the rest of the playground keeps:

- **One painter of people.** Every character is `avatars.paint` — the stored recipe,
  the same person as in Chat, the Office and the terminal. This module paints panels,
  balloons, floors and lettering, and nobody's face.
- **The Office's look.** Panel floors, walls and trim are the person's office style
  (`office.STYLES`), so the strip on the phone is the office on the desk.
- **The picture never carries words the caption does not.** The pixel font is ASCII;
  a balloon whose text it cannot draw (another script, emoji) says "(below)" rather
  than printing boxes, and the caption always has every word. A comic nobody can
  read would be decoration pretending to be a message.
- **Nothing is loaded from anywhere.** No image library, no font file: the 5x7 font
  below is this file's own, the PNG is `avatars.png`, all standard library — the
  same argument avatars.py makes, and why this adds no dependency.

Everything is drawn at one logical pixel and scaled up whole at the end, so the
lettering and the people have the same chunky pixel.
"""
from __future__ import annotations

import unicodedata

from . import avatars, office

# ---- the font: 5x7, one row per byte, bit 4 is the leftmost column -----------------
# Drawn for this file to read at 5x7 (a character ROM's shapes were the reference, not
# the source); a glyph whose last byte is 00 simply sits a row higher.
_F = {
    " ": "00000000000000", "!": "04040404040004", '"': "0A0A0A00000000", "#": "0A0A1F0A1F0A0A",
    "$": "040F140E051E04", "%": "18190204081303", "&": "0C12140815120D", "'": "0C040800000000",
    "(": "02040808080402", ")": "08040202020408", "*": "0004150E150400", "+": "0004041F040400",
    ",": "000000000C0408", "-": "0000001F000000", ".": "00000000000C0C", "/": "00010204081000",
    "0": "0E11131519110E", "1": "040C040404040E", "2": "0E11010204081F", "3": "1F02040201110E",
    "4": "02060A121F0202", "5": "1F101E0101110E", "6": "0608101E11110E", "7": "1F010204080808",
    "8": "0E11110E11110E", "9": "0E11110F01020C", ":": "000C0C000C0C00", ";": "000C0C000C0408",
    "<": "02040810080402", "=": "00001F001F0000", ">": "08040201020408", "?": "0E110102040004",
    "@": "0E11010D15150E", "A": "0E1111111F1111", "B": "1E11111E11111E", "C": "0E11101010110E",
    "D": "1C12111111121C", "E": "1F10101E10101F", "F": "1F10101E101010", "G": "0E11101711110F",
    "H": "1111111F111111", "I": "0E04040404040E", "J": "0702020202120C", "K": "11121418141211",
    "L": "1010101010101F", "M": "111B1515111111", "N": "11111915131111", "O": "0E11111111110E",
    "P": "1E11111E101010", "Q": "0E11111115120D", "R": "1E11111E141211", "S": "0F10100E01011E",
    "T": "1F040404040404", "U": "1111111111110E", "V": "11111111110A04", "W": "1111111515150A",
    "X": "11110A040A1111", "Y": "1111110A040404", "Z": "1F01020408101F", "[": "0E08080808080E",
    "\\": "00100804020100", "]": "0E02020202020E", "^": "040A1100000000", "_": "0000000000001F",
    "`": "08040200000000", "a": "00000E010F110F", "b": "1010161911111E", "c": "00000E1010110E",
    "d": "01010D1311110F", "e": "00000E111F100E", "f": "0609081C080808", "g": "000F11110F010E",
    "h": "10101619111111", "i": "04000C0404040E", "j": "0200060202120C", "k": "10101214181412",
    "l": "0C04040404040E", "m": "00001A15151111", "n": "00001619111111", "o": "00000E1111110E",
    "p": "00001E111E1010", "q": "00000D130F0101", "r": "00001619101010", "s": "00000E100E011E",
    "t": "08081C08080906", "u": "0000111111130D", "v": "00001111110A04", "w": "0000111115150A",
    "x": "0000110A040A11", "y": "000011110F010E", "z": "00001F0204081F", "{": "02040408040402",
    "|": "04040404040404", "}": "08040402040408", "~": "00000815020000",
    "\u2713": "00010102141408",   # a tick, for "done"
    "\u00b7": "0000000C0C0000",   # the middle dot titles are joined with
}
GLYPH = {ch: [int(v[i:i + 2], 16) for i in range(0, 14, 2)] for ch, v in _F.items()}
ADV = 6                      # a glyph is 5 wide, plus one column of space
LINE = 9                     # 7 high, plus two rows of leading

_SUB = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
        "…": "...", " ": " ", "→": "->", "←": "<-", "•": "*", "×": "x",
        "✔": "✓", "✅": "✓"}


def drawable(text: str) -> tuple[str, bool]:
    """(what the font can draw, whether that is the whole text). Accents come off
    (é → e) because the word is still the word. A run the font cannot carry at all —
    another script, an emoji — becomes "..." rather than vanishing, so the balloon
    never reads as a DIFFERENT sentence; how much went missing is `lost_share`."""
    out, lost = [], 0
    for ch in str(text or ""):
        ch = _SUB.get(ch, ch)
        for c in ch:
            if c in GLYPH:
                out.append(c)
                continue
            base = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
            if base and all(b in GLYPH for b in base):
                out.append(base)
            elif c.isspace():
                out.append(" ")
            elif unicodedata.category(c) in ("Mn", "Mc", "Me", "Cf"):
                lost += 1                           # a vowel sign or joiner: part of the run
            else:
                lost += 1
                if not out or out[-1] != "\x00":
                    out.append("\x00")
    s = " ".join("".join(out).replace("\x00", "...").split())
    return s, lost == 0


def lost_share(text: str) -> float:
    """How much of `text` (ignoring spaces) the pixel font cannot draw."""
    t = [c for c in str(text or "") if not c.isspace()]
    if not t:
        return 0.0
    bad = 0
    for c in t:
        c = _SUB.get(c, c)[:1]
        base = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
        if not (c in GLYPH or (base and all(b in GLYPH for b in base))):
            bad += 1
    return bad / len(t)


def wrap(text: str, chars: int, lines: int) -> list[str]:
    words, rows, cur = text.split(), [], ""
    for w in words:
        while len(w) > chars:                      # a URL or a long id: cut it
            if cur:
                rows.append(cur)
                cur = ""
            rows.append(w[:chars])
            w = w[chars:]
        t = (cur + " " + w).strip()
        if len(t) > chars:
            rows.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        rows.append(cur)
    if len(rows) > lines:
        rows = rows[:lines]
        rows[-1] = rows[-1][:chars - 3].rstrip() + "..."
    return rows


def _rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


INK = (25, 24, 39)
WHITE = (255, 255, 255)


class Canvas:
    """RGBA pixels and the handful of shapes a comic needs."""

    def __init__(self, w: int, h: int, bg: tuple = WHITE):
        self.w, self.h = w, h
        self.px = bytearray(bytes((*bg, 255)) * (w * h))

    def put(self, x: int, y: int, c: tuple):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 4
            self.px[i:i + 4] = bytes((*c[:3], 255))

    def rect(self, x: int, y: int, w: int, h: int, c: tuple):
        x0, y0, x1, y1 = max(0, x), max(0, y), min(self.w, x + w), min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes((*c[:3], 255)) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 4
            self.px[i:i + len(row)] = row

    def box(self, x: int, y: int, w: int, h: int, c: tuple, t: int = 1):
        self.rect(x, y, w, t, c)
        self.rect(x, y + h - t, w, t, c)
        self.rect(x, y, t, h, c)
        self.rect(x + w - t, y, t, h, c)

    def round(self, x: int, y: int, w: int, h: int, fill: tuple, ink: tuple = INK):
        """A rounded box with a one-pixel ink outline: corners cut by two pixels, which
        at this scale reads as round."""
        self.rect(x + 2, y, w - 4, h, fill)
        self.rect(x, y + 2, w, h - 4, fill)
        self.rect(x + 1, y + 1, w - 2, h - 2, fill)
        self.rect(x + 2, y, w - 4, 1, ink)
        self.rect(x + 2, y + h - 1, w - 4, 1, ink)
        self.rect(x, y + 2, 1, h - 4, ink)
        self.rect(x + w - 1, y + 2, 1, h - 4, ink)
        for dx, dy in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)):
            self.put(x + dx, y + dy, ink)

    def dots(self, x: int, y: int, w: int, h: int, c: tuple, step: int = 4):
        """Halftone: the comic printer's dot, one pixel each, offset every other row."""
        for j, yy in enumerate(range(y, y + h, step)):
            for xx in range(x + (step // 2 if j % 2 else 0), x + w, step):
                self.put(xx, yy, c)

    def blit(self, w: int, h: int, px: bytes, x: int, y: int, scale: int = 1):
        for sy in range(h):
            for sx in range(w):
                i = (sy * w + sx) * 4
                if px[i + 3]:
                    c = (px[i], px[i + 1], px[i + 2])
                    if scale == 1:
                        self.put(x + sx, y + sy, c)
                    else:
                        self.rect(x + sx * scale, y + sy * scale, scale, scale, c)

    def text(self, x: int, y: int, s: str, c: tuple = INK) -> int:
        for n, ch in enumerate(s):
            g = GLYPH.get(ch) or GLYPH["?"]
            for r, bits in enumerate(g):
                for col in range(5):
                    if bits & (0x10 >> col):
                        self.put(x + n * ADV + col, y + r, c)
        return len(s) * ADV

    def scaled(self, k: int) -> tuple[int, int, bytes]:
        if k <= 1:
            return self.w, self.h, bytes(self.px)
        out = bytearray()
        for y in range(self.h):
            line = bytearray()
            src = self.px[y * self.w * 4:(y + 1) * self.w * 4]
            for x in range(self.w):
                line += src[x * 4:x * 4 + 4] * k
            out += bytes(line) * k
        return self.w * k, self.h * k, bytes(out)


# ---- panels --------------------------------------------------------------------------

PW, PH = 184, 132            # one panel, in logical pixels
GUTTER = 6
SCALE = 3                    # the whole strip, scaled up whole: 552 x 396 per panel
PER_ROW = 3
MAX_PANELS = 9               # a strip, not a transcript — the caption has the rest


def _style(cfg: dict) -> dict:
    return office.STYLES[office.current(cfg)["style"]]


def _person(store, key: str, frame: int = 0) -> tuple[int, int, bytes]:
    rec = avatars.recipe_for(store, key)
    return avatars.W, avatars.H, bytes(avatars.paint(rec, frame))


def _floor(cv: Canvas, x: int, y: int, w: int, h: int, st: dict):
    wall = _rgb(st["wall"])
    a, b = _rgb(st["floor"][0]), _rgb(st["floor"][1])
    cv.rect(x, y, w, h, a)
    cv.dots(x + 1, y + 20, w - 2, h - 21, b, 4)
    cv.rect(x, y, w, 18, wall)
    cv.rect(x, y, w, 2, _mix(wall, WHITE, .25))
    # two windows on the wall, the Office's: sky by day, deep blue on a dark wall
    dark = sum(wall) < 250
    for wx in (x + w - 58, x + w - 30):         # the right end: the sign has the left
        cv.rect(wx, y + 4, 22, 10, (30, 27, 75) if dark else (191, 232, 255))
        cv.box(wx, y + 4, 22, 10, INK)
        cv.rect(wx + 11, y + 4, 1, 10, INK)
    cv.rect(x, y + 18, w, 1, INK)
    cv.dots(x + 1, y + 19, w - 2, 5, _mix(a, INK, .35), 3)


def _label(cv: Canvas, cx: int, y: int, name: str, lo: int = 0, hi: int = 10 ** 6,
           fill: tuple = WHITE, ink: tuple = INK, room: int = 0):
    """A name tag under somebody's feet, kept inside its panel [lo, hi) and, when
    several stand side by side, inside their own share of it (`room` pixels) — four
    tags at full length ran into each other and named nobody."""
    most = max(3, (room - 5) // ADV) if room else 14
    s = name[:14] if len(name) <= most else name[:most - 1] + "."
    w = len(s) * ADV + 5
    x = max(lo + 3, min(hi - w - 3, cx - w // 2))
    cv.round(x, y, w, 11, fill, INK)
    cv.text(x + 3, y + 2, s, ink)


def _balloon(cv: Canvas, x: int, y: int, w: int, lines: list[str], tail_x: int, tail_y: int,
             fill: tuple = WHITE):
    h = len(lines) * LINE + 7
    cv.round(x, y, w, h, fill)
    # the tail: a short stepped wedge from the balloon's bottom edge toward the head
    tx = max(x + 6, min(x + w - 10, tail_x - 2))
    for i in range(max(2, min(10, tail_y - (y + h)))):
        half = max(0, 3 - i // 3)
        cv.rect(tx - half + i // 3, y + h - 1 + i, half * 2 + 1, 1, fill)
        cv.put(tx - half - 1 + i // 3, y + h - 1 + i, INK)
        cv.put(tx + half + 1 + i // 3, y + h - 1 + i, INK)
    for n, ln in enumerate(lines):
        cv.text(x + 5, y + 4 + n * LINE, ln)
    return h


def _say_lines(text: str, chars: int, lines: int) -> list[str]:
    """A balloon's lines. Mostly another script → "(below)": the caption carries it,
    and a balloon of dots would be a message pretending to be read."""
    s, _ = drawable(text)
    if not s.strip(". ") or lost_share(text) > 0.3:
        return ["(below)"]
    return wrap(s, chars, lines)


def talk_panel(cv: Canvas, px: int, py: int, store, st: dict, speaker: str, text: str,
               to: str = "", accent: tuple = (255, 77, 77)):
    """One line of a conversation: the speaker on the left with the balloon, the one
    being spoken to on the right when there is one."""
    _floor(cv, px, py, PW, PH, st)
    feet = py + PH - 16
    w, h, spx = _person(store, speaker, 2)
    cv.blit(w, h, spx, px + 14, feet - h * 2, 2)
    _label(cv, px + 30, feet + 3, _name(speaker), px, px + PW)
    if to:
        w2, h2, tpx = _person(store, to, 0)
        cv.blit(w2, h2, tpx, px + PW - 46, feet - h2 * 2, 2)
        _label(cv, px + PW - 30, feet + 3, _name(to), px, px + PW)
    lines = _say_lines(text, (PW - 20) // ADV, 4)
    _balloon(cv, px + 6, py + 22, PW - 12, lines, px + 30, feet - h * 2 - 2)
    cv.box(px, py, PW, PH, INK, 2)


def _name(key: str) -> str:
    return "you" if key == avatars.ME else ("agent" if key == avatars.AGENT else key)


def strip(store, cfg: dict, turns: list[dict], title: str = "") -> bytes:
    """A comic strip of agents talking: one panel per line said, in order, at most
    MAX_PANELS (the caption carries every word). `turns` are the talk events the
    playground tap collected: {speaker, text, to?}."""
    turns = [t for t in turns if t.get("speaker") and (t.get("text") or "").strip()][:MAX_PANELS]
    st = _style(cfg)
    accent = _rgb(st["accent"])
    n = max(1, len(turns))
    cols = min(PER_ROW, n)
    rows = (n + cols - 1) // cols
    head = 14
    W = GUTTER + cols * (PW + GUTTER)
    H = head + GUTTER + rows * (PH + GUTTER)
    cv = Canvas(W, H, _mix(_rgb(st["wall"]), INK, .6))
    cv.rect(0, 0, W, head, accent)
    s, _ = drawable(title or office.current(cfg)["name"])
    cv.text(GUTTER, 4, s[:(W - 12) // ADV].upper(), WHITE)
    for i, t in enumerate(turns):
        c, r = i % cols, i // cols
        talk_panel(cv, GUTTER + c * (PW + GUTTER), head + GUTTER + r * (PH + GUTTER), store, st,
                   t["speaker"], t["text"], t.get("to") or "", accent)
    return avatars.png(*cv.scaled(SCALE))


def rollcall_image(store, cfg: dict, rows: list[dict], title: str = "") -> bytes:
    """Who is where and what they are doing: one panel per room, its people standing,
    a WORKING tag over whoever has a run open, and what that run is doing written at
    the bottom. Drawn from `playground.rollcall` — the same rows the terminal prints."""
    st = _style(cfg)
    colors = {k: _rgb(v) for k, v in office.COLORS.items()}
    rooms: list[tuple[str, str, list]] = []
    for r in rows:
        if not rooms or rooms[-1][0] != r["room"]:
            rooms.append((r["room"], r.get("color") or "slate", []))
        rooms[-1][2].append(r)
    n = max(1, len(rooms))
    cols = min(PER_ROW, n)
    rws = (n + cols - 1) // cols
    head = 14
    W = GUTTER + cols * (PW + GUTTER)
    H = head + GUTTER + rws * (PH + GUTTER)
    cv = Canvas(W, H, _mix(_rgb(st["wall"]), INK, .6))
    cv.rect(0, 0, W, head, _rgb(st["accent"]))
    s, _ = drawable(title or office.current(cfg)["name"])
    cv.text(GUTTER, 4, s[:(W - 12) // ADV].upper(), WHITE)
    for i, (room, color, people) in enumerate(rooms):
        px = GUTTER + (i % cols) * (PW + GUTTER)
        py = head + GUTTER + (i // cols) * (PH + GUTTER)
        _floor(cv, px, py, PW, PH, st)
        rn, _ = drawable(room)
        tw = min(PW - 12, len(rn) * ADV + 6)
        cv.round(px + 4, py + 4, tw, 11, colors.get(color, colors["slate"]))
        cv.text(px + 7, py + 6, rn.upper()[:(tw - 6) // ADV], WHITE)
        shown = people[:4]
        slot = (PW - 8) // max(1, len(shown))
        feet = py + PH - 34
        notes = []
        for j, p in enumerate(shown):
            cx = px + 4 + slot * j + slot // 2
            w, h, spx = _person(store, p["key"], 2 if p["working"] else 0)
            cv.blit(w, h, spx, cx - 16, feet - h * 2, 2)
            _label(cv, cx, feet + 2, _name(p["key"]) if p["key"] != avatars.AGENT else p["label"], px, px + PW,
                   room=slot - 2 if len(shown) > 1 else 0)
            if p["working"]:
                cv.round(cx - 17, feet - h * 2 - 13, 35, 11, _rgb(st["accent"]))
                cv.text(cx - 14, feet - h * 2 - 11, "BUSY", WHITE)
                if p.get("doing"):
                    d, _ = drawable(p["doing"])
                    notes.append(f"{_name(p['key'])}: {d}")
        if len(people) > len(shown):             # more than fit: said, on a tag of its own
            more = f"+{len(people) - len(shown)} more"
            mw = len(more) * ADV + 5
            cv.round(px + PW - mw - 4, py + 23, mw, 11, WHITE)
            cv.text(px + PW - mw - 1, py + 25, more)
        if not people:
            cv.text(px + 10, py + 60, "nobody here yet")
        for k, ln in enumerate(wrap(" / ".join(notes), (PW - 12) // ADV, 2) if notes else []):
            cv.rect(px + 2, py + PH - 20 + k * LINE, PW - 4, LINE, WHITE)
            cv.text(px + 6, py + PH - 19 + k * LINE, ln)
        cv.box(px, py, PW, PH, INK, 2)
    return avatars.png(*cv.scaled(SCALE))
