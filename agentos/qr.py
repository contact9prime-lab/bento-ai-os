"""A QR code, made here: the square an authenticator app scans.

Asked for as "there needs to be further instructions to build the code": the authenticator's
secret was shown as 32 letters and an otpauth:// link, and typing 32 letters into a phone is
where people give up. A scan is one tap.

Stdlib only (holdclear.py and the terminal verbs must work without the server, and no QR
library is a dependency). Byte mode, error correction M, versions 1 to 40, the mask chosen by
the standard's penalty score. A port of Project Nayuki's reference generator (MIT), checked
against a real decoder in tests/test_qr.py.

The page draws `path()` as one SVG path through text nodes and attributes; the terminal draws
`text()` with half blocks."""

from __future__ import annotations

# error correction M; index 0 is padding so a version is its own index
_ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26,
                  26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28]
_BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21,
           23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49]
_FORMAT_M = 0
_N1, _N2, _N3, _N4 = 3, 3, 40, 10


def _raw_modules(ver: int) -> int:
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        al = ver // 7 + 2
        n -= (25 * al - 10) * al - 55
        if ver >= 7:
            n -= 36
    return n


def _data_codewords(ver: int) -> int:
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ver] * _BLOCKS[ver]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree: int) -> list[int]:
    out = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            out[j] = _gf_mul(out[j], root)
            if j + 1 < degree:
                out[j] ^= out[j + 1]
        root = _gf_mul(root, 0x02)
    return out


def _rs_remainder(data: list[int], div: list[int]) -> list[int]:
    out = [0] * len(div)
    for b in data:
        factor = b ^ out.pop(0)
        out.append(0)
        for i, coef in enumerate(div):
            out[i] ^= _gf_mul(coef, factor)
    return out


def _interleave(data: list[int], ver: int) -> list[int]:
    nblocks, ecc = _BLOCKS[ver], _ECC_PER_BLOCK[ver]
    raw = _raw_modules(ver) // 8
    nshort = nblocks - raw % nblocks
    short_len = raw // nblocks
    div = _rs_divisor(ecc)
    blocks, k = [], 0
    for i in range(nblocks):
        dat = data[k:k + short_len - ecc + (0 if i < nshort else 1)]
        k += len(dat)
        rem = _rs_remainder(dat, div)
        if i < nshort:
            dat = dat + [0]
        blocks.append(dat + rem)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecc or j >= nshort:
                out.append(blk[i])
    return out


class _Grid:
    def __init__(self, ver: int):
        self.ver = ver
        self.size = ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def put(self, x: int, y: int, dark: bool) -> None:
        self.m[y][x] = dark
        self.fn[y][x] = True

    def _align_positions(self) -> list[int]:
        if self.ver == 1:
            return []
        al = self.ver // 7 + 2
        step = (self.ver * 8 + al * 3 + 5) // (al * 4 - 4) * 2
        out, i = [], self.size - 7
        while len(out) < al - 1:
            out.insert(0, i)
            i -= step
        return [6] + out

    def functions(self) -> None:
        s = self.size
        for i in range(s):
            self.put(6, i, i % 2 == 0)
            self.put(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < s and 0 <= y < s:
                        self.put(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self._align_positions()
        last = len(pos) - 1
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.put(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits(0)
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = s - 11 + i % 3, i // 3
                self.put(a, b, bit)
                self.put(b, a, bit)

    def format_bits(self, mask: int) -> None:
        data = _FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        s = self.size

        def bit(i):
            return (bits >> i) & 1 == 1
        for i in range(6):
            self.put(8, i, bit(i))
        self.put(8, 7, bit(6))
        self.put(8, 8, bit(7))
        self.put(7, 8, bit(8))
        for i in range(9, 15):
            self.put(14 - i, 8, bit(i))
        for i in range(8):
            self.put(s - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.put(8, s - 15 + i, bit(i))
        self.put(8, s - 8, True)

    def codewords(self, data: list[int]) -> None:
        s, i, right = self.size, 0, self.size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(s):
                for j in range(2):
                    x = right - j
                    up = ((right + 1) & 2) == 0
                    y = s - 1 - vert if up else vert
                    if not self.fn[y][x] and i < len(data) * 8:
                        self.m[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.fn[y][x]:
                    continue
                inv = (
                    (x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0,
                    (x // 3 + y // 2) % 2 == 0, x * y % 2 + x * y % 3 == 0,
                    (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0,
                )[mask]
                if inv:
                    self.m[y][x] = not self.m[y][x]

    # ---- the penalty score, so the mask chosen is the one scanners read best
    def _hist_add(self, run: int, h: list[int]) -> None:
        if h[0] == 0:
            run += self.size
        h.pop()
        h.insert(0, run)

    @staticmethod
    def _finder_count(h: list[int]) -> int:
        n = h[1]
        core = n > 0 and h[2] == h[4] == h[5] == n and h[3] == n * 3
        return (1 if core and h[0] >= n * 4 and h[6] >= n else 0) + \
               (1 if core and h[6] >= n * 4 and h[0] >= n else 0)

    def _line_penalty(self, cells: list[bool]) -> int:
        score, color, run, h = 0, False, 0, [0] * 7
        for c in cells:
            if c == color:
                run += 1
                if run == 5:
                    score += _N1
                elif run > 5:
                    score += 1
            else:
                self._hist_add(run, h)
                if not color:
                    score += self._finder_count(h) * _N3
                color, run = c, 1
        if color:
            self._hist_add(run, h)
            run = 0
        run += self.size
        self._hist_add(run, h)
        return score + self._finder_count(h) * _N3

    def penalty(self) -> int:
        s, m = self.size, self.m
        score = sum(self._line_penalty(row) for row in m)
        score += sum(self._line_penalty([m[y][x] for y in range(s)]) for x in range(s))
        for y in range(s - 1):
            for x in range(s - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += _N2
        dark = sum(sum(row) for row in m)
        total = s * s
        k = -(-abs(dark * 20 - total * 10) // total) - 1
        return score + k * _N4


def encode(text: str) -> list[list[bool]]:
    """The modules of a QR code for `text`, True for dark, without the quiet zone."""
    data = text.encode("utf-8")
    for ver in range(1, 41):
        cap = _data_codewords(ver) * 8
        if 4 + (8 if ver < 10 else 16) + len(data) * 8 <= cap:
            break
    else:
        raise ValueError("too long for a QR code")
    bits: list[int] = []

    def add(val: int, n: int):
        bits.extend((val >> i) & 1 for i in reversed(range(n)))
    add(0b0100, 4)
    add(len(data), 8 if ver < 10 else 16)
    for b in data:
        add(b, 8)
    add(0, min(4, cap - len(bits)))
    add(0, -len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < cap // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    g = _Grid(ver)
    g.functions()
    g.codewords(_interleave(words, ver))
    best, best_score = 0, None
    for mask in range(8):
        g.apply_mask(mask)
        g.format_bits(mask)
        score = g.penalty()
        if best_score is None or score < best_score:
            best, best_score = mask, score
        g.apply_mask(mask)           # XOR undoes it
    g.apply_mask(best)
    g.format_bits(best)
    return g.m


def path(text: str, border: int = 4) -> dict:
    """One SVG path of unit squares, and the side of the square it fills, quiet zone included."""
    m = encode(text)
    parts = [f"M{x + border},{y + border}h1v1h-1z"
             for y, row in enumerate(m) for x, dark in enumerate(row) if dark]
    return {"d": "".join(parts), "size": len(m) + 2 * border}


def text(value: str, border: int = 2) -> str:
    """The code in half blocks for a terminal, light on dark like most terminals draw."""
    m = encode(value)
    s = len(m)

    def dark(x, y):
        return 0 <= x < s and 0 <= y < s and m[y][x]
    lines = []
    for y in range(-border, s + border, 2):
        row = []
        for x in range(-border, s + border):
            top, bot = not dark(x, y), not dark(x, y + 1)      # a light module is drawn
            row.append("█" if top and bot else "▀" if top else "▄" if bot else " ")
        lines.append("".join(row))
    return "\n".join(lines)
