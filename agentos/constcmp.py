"""Comparing a secret in constant time, whatever the caller sent.

`hmac.compare_digest` raises TypeError on a str holding anything but ASCII, so a token with
one `é` in it turned a clean refusal into a 500, and an attacker could tell the two apart.
`.encode()` alone is not enough: JSON can carry a lone surrogate, which it raises on. Every
secret comparison in this OS goes through `same`; tests/test_followups_security.py fails on a
bare compare_digest anywhere else.
"""

from __future__ import annotations

import hmac


def _bytes(v) -> bytes:
    return v if isinstance(v, bytes) else str(v if v is not None else "").encode("utf-8", "surrogatepass")


def same(a, b) -> bool:
    """Do these two hold the same text or bytes? Never raises."""
    return hmac.compare_digest(_bytes(a), _bytes(b))
