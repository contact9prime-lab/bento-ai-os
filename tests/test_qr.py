"""The QR code the authenticator setup shows (agentos/qr.py).

Reported as "there needs to be further instructions to build the code": the secret was 32
letters and a link. These pin the encoder. It was checked against a real decoder (zxing-cpp)
for 1 to 2,300 characters when it was written; the fingerprints below are those verified
codes, so a change to the encoder that a scanner would no longer read fails here."""

import hashlib
import re
from pathlib import Path

from agentos import qr

ROOT = Path(__file__).parent.parent
URI = ("otpauth://totp/Bento%20security%20(ada)?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
       "&issuer=Bento&digits=6&period=30")


def _print(m):
    return hashlib.sha256("".join("1" if c else "0" for r in m for c in r).encode()).hexdigest()[:16]


def test_the_codes_a_decoder_read_are_unchanged():
    assert _print(qr.encode("HELLO")) == "32fbc389880456d5"
    m = qr.encode(URI)
    assert len(m) == 45 and _print(m) == "d7a974432c9aca85"


def test_every_size_has_its_finders_and_timing():
    for n in (1, 40, 300, 1200, 2300):
        m = qr.encode("x" * n)
        s = len(m)
        assert (s - 17) % 4 == 0 and 21 <= s <= 177
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):
            assert m[cy][cx] and m[cy - 3][cx] and not m[cy - 2][cx]
        assert all(m[6][x] == (x % 2 == 0) for x in range(8, s - 8))
        assert m[s - 8][8], "the dark module"


def test_the_page_and_the_terminal_get_the_same_code():
    p = qr.path(URI)
    assert p["size"] == 45 + 8
    assert len(re.findall(r"M\d+,\d+h1v1h-1z", p["d"])) == sum(map(sum, qr.encode(URI)))
    t = qr.text(URI).splitlines()
    assert len(t) == (45 + 4 + 1) // 2 and all(len(line) == 49 for line in t)


def test_too_long_is_said():
    try:
        qr.encode("x" * 3000)
    except ValueError as e:
        assert "too long" in str(e)
    else:
        raise AssertionError("3000 bytes don't fit")


def test_qr_is_stdlib_only():
    src = (ROOT / "agentos/qr.py").read_text()
    assert not re.search(r"^\s*(import|from)\s+(?!__future__)", src, re.M)
