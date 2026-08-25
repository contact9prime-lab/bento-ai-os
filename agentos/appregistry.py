"""The app registry: packages, checksums, signatures, and the security scan.

The registry is a GIT REPOSITORY of ``.agentapp.json`` packages — the exact format
this OS already exports and imports — not a second format invented for the store.
That one decision does most of the work:

- **Propagation is GitHub.** A package's raw URL is installable TODAY through the
  Store's Import tab, which already fetches a URL, verifies the checksum, diffs
  prerequisites and stages every grant for the user to review. The registry adds
  an index and a signature on top; it does not add a new install path.
- **Publishing is a pull request.** Fork, add ``apps/<id>/<id>.agentapp.json``,
  open a PR. CI validates the schema, recomputes the checksum and runs the same
  security scan this module ships — one implementation, run in both places.
- **"Verified" is a signature, not a vibe.** The package format has carried
  ``"signature": None`` since export existed. The registry fills it: Ed25519 over
  the package checksum. The checksum covers the canonical manifest AND the HTML,
  and the security block lives INSIDE the manifest — so a signature vouches for
  the code *and* the scan verdict together, and editing either kills it.

Why a signature and not just the sha: a checksum proves the bytes are the bytes —
anyone can compute one over anything, including malware. Only a signature proves
*who* said those bytes are fine. The public keys are pinned here (plus any the
user adds in config); the private key is minted by the registry owner with
``bento registry keygen`` and NEVER ships in this repository or its history.

Kept free of HTTP and asyncio on purpose, like jobs.py: the registry's CI runs
``scan`` and ``verify`` on a runner with no AgentOS server, and a headless machine
verifies a download with the server down.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path

PACKAGE_FORMAT = "agentos-app/1"

#: Where the official registry lives, and the raw base a package installs from.
#: The Import tab takes any URL, so these are defaults, not a lock-in.
REGISTRY_REPO = "contact9prime-lab/bento-app-registry"
REGISTRY_RAW = f"https://raw.githubusercontent.com/{REGISTRY_REPO}/main"
REGISTRY_INDEX_URL = f"{REGISTRY_RAW}/index.json"

#: Pinned publisher keys: key_id -> base64 raw Ed25519 public key. Deliberately
#: EMPTY in source until the registry owner mints theirs (`bento registry keygen`
#: prints the line to add). Shipping a key whose private half ever existed on a
#: build machine would make "verified" mean "somebody once had a laptop" — the
#: trust root must only ever exist where the owner made it.
BUILTIN_KEYS: dict[str, str] = {}

SIGNING_KEY_PATH = Path.home() / ".agentos" / "registry_signing.key"


# ---------------------------------------------------------------------------
# Canonical form and checksum — THE definition, shared with the server
# ---------------------------------------------------------------------------

def canonical(obj) -> str:
    """One byte-stable JSON form. The checksum and the signature both depend on
    every producer agreeing on this, so there is exactly one copy of it."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def package_checksum(manifest: dict, html: str) -> str:
    return "sha256:" + hashlib.sha256((canonical(manifest) + "\n" + html).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Keys and signatures
# ---------------------------------------------------------------------------

def keygen(path: Path | None = None) -> tuple[Path, str, str]:
    """Mint a signing keypair. Returns (private_key_path, key_id, public_b64).

    The private key is written 0600 to the owner's home and nowhere else. The
    key_id is derived from the public key, so two keys can never claim one name.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption,
                                                              PrivateFormat, PublicFormat)
    path = path or SIGNING_KEY_PATH
    if path.exists():
        raise FileExistsError(f"{path} already exists — delete it first if you really "
                              f"mean to replace the registry's identity")
    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64encode(raw_priv))
    path.chmod(0o600)
    pub_b64 = base64.b64encode(raw_pub).decode()
    key_id = "reg-" + hashlib.sha256(raw_pub).hexdigest()[:8]
    return path, key_id, pub_b64


def sign_package(pkg: dict, key_path: Path | None = None) -> dict:
    """Fill the package's ``signature`` slot: Ed25519 over the checksum string.

    The checksum is recomputed here rather than trusted from the file — signing a
    stale checksum would be vouching for bytes nobody looked at.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key_path = key_path or SIGNING_KEY_PATH
    raw = base64.b64decode(key_path.read_bytes())
    priv = Ed25519PrivateKey.from_private_bytes(raw)
    raw_pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    checksum = package_checksum(pkg.get("manifest") or {}, pkg.get("html") or "")
    pkg = dict(pkg)
    pkg["checksum"] = checksum
    pkg["signature"] = {
        "alg": "ed25519",
        "key_id": "reg-" + hashlib.sha256(raw_pub).hexdigest()[:8],
        "sig": base64.b64encode(priv.sign(checksum.encode())).decode(),
        "signed_at": time.time(),
    }
    return pkg


def trusted_keys(cfg: dict | None = None) -> dict[str, str]:
    """Built-in keys plus any the user pinned in config (``registry.keys``).

    Config ADDS keys — it cannot remove a built-in, so a compromised config
    cannot silently un-trust the official publisher and substitute its own only.
    """
    out = dict(BUILTIN_KEYS)
    for k, v in (((cfg or {}).get("registry") or {}).get("keys") or {}).items():
        out.setdefault(str(k), str(v))
    return out


def verify_package(pkg: dict, keys: dict[str, str] | None = None) -> tuple[str, str]:
    """(status, sentence). Status is one of:

    ``verified``          — checksum matches AND the signature validates against a
                            trusted key. The strongest claim this OS can make.
    ``unsigned``          — checksum matches; nobody has vouched for it. Fine for
                            your own exports; the Store shows it as unverified.
    ``unknown-key``       — signed, but by a key this machine does not trust.
    ``bad-signature``     — the signature does not match the bytes. Treat as hostile.
    ``checksum-mismatch`` — the bytes changed after packaging. Treat as hostile.

    The checksum is checked FIRST: a valid signature over a wrong checksum is a
    signature over something other than this package.
    """
    manifest, html = pkg.get("manifest") or {}, pkg.get("html") or ""
    want = package_checksum(manifest, html)
    if pkg.get("checksum") != want:
        return "checksum-mismatch", "the package was modified after it was built"
    sig = pkg.get("signature")
    if not sig:
        return "unsigned", "integrity checks out, but nobody has signed it"
    if sig.get("alg") != "ed25519":
        return "unknown-key", f"unsupported signature algorithm '{sig.get('alg')}'"
    pub_b64 = (keys if keys is not None else trusted_keys()).get(sig.get("key_id") or "")
    if not pub_b64:
        return "unknown-key", (f"signed by '{sig.get('key_id')}', which this machine "
                               f"does not trust")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
        pub.verify(base64.b64decode(sig.get("sig") or ""), want.encode())
    except InvalidSignature:
        return "bad-signature", "the signature does not match this package"
    except Exception as e:                                        # noqa: BLE001
        return "bad-signature", f"the signature could not be checked: {e}"
    return "verified", f"signed by {sig.get('key_id')}"


# ---------------------------------------------------------------------------
# The security scan
# ---------------------------------------------------------------------------
# Two layers, honestly labelled. The STATIC layer is deterministic, needs no
# model and no server, and runs identically in the registry's CI and on this
# machine — it is the floor every package must clear. The AI layer reads the
# code with the machine's own brain and is recorded with the model's name, so
# "scanned" always says scanned BY WHAT. The verdict lives inside the manifest,
# which puts it under the checksum and therefore under the signature: a verdict
# cannot be edited without re-signing.

#: (severity, pattern, what it means). Patterns are matched on the app's HTML.
_SCAN_RULES: tuple[tuple[str, str, str], ...] = (
    ("high", r"window\.(?:parent|top)\s*[.\[]",
     "reaches for window.parent/top — a sandbox-escape attempt; the app iframe is "
     "deliberately opaque-origin and has no business up there"),
    ("high", r"\beval\s*\(|new\s+Function\s*\(",
     "builds code from strings (eval / new Function) — the classic way a payload "
     "hides from every reader, including this scan"),
    ("high", r"\batob\s*\([^)]*\)\s*(?:\)|,)?\s*(?:.{0,40})?\beval",
     "decodes base64 straight into eval — obfuscated executable payload"),
    ("high", r"appTool\(\s*['\"]run_command['\"]",
     "asks for a shell (run_command) — legitimate for a dev tool, but the single "
     "most powerful capability an app can request; the permission review must say so"),
    ("medium", r"(?:fetch|XMLHttpRequest|WebSocket)\s*\(\s*['\"`]https?://",
     "talks to an external host by URL — the channel an app would use to exfiltrate "
     "the data it is trusted with; verify the destination is what the app claims"),
    ("medium", r"<script[^>]+src\s*=\s*['\"]https?://",
     "loads script from an external host — the app's behaviour can change after "
     "review, which is exactly what review exists to prevent"),
    ("medium", r"appTool\(\s*['\"](?:write_file|delete_file|move_file)['\"]",
     "writes or deletes files — fine when that is the app's stated job"),
    ("info", r"appTool\(\s*['\"]fetch_url['\"]",
     "fetches web pages through the agent (rate-limited and policy-gated)"),
    ("info", r"localStorage|sessionStorage",
     "keeps per-browser state (invisible to other users, lost on a cleared browser)"),
)

_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{2048,}={0,2}")


def static_scan(html: str) -> list[dict]:
    """Deterministic findings over the app source. Same output everywhere it runs."""
    findings = []
    lines = (html or "").split("\n")
    for sev, pat, why in _SCAN_RULES:
        rx = re.compile(pat)
        for i, ln in enumerate(lines, 1):
            if rx.search(ln):
                findings.append({"severity": sev, "line": i, "rule": pat[:40], "note": why})
                break                       # one report per rule, first sighting
    if _B64_BLOB.search(html or ""):
        findings.append({"severity": "medium", "line": 0, "rule": "base64-blob",
                         "note": "contains a large base64 blob — could be an asset, "
                                 "could be a hidden payload; look at it"})
    return findings


def verdict_of(findings: list[dict]) -> str:
    sevs = {f["severity"] for f in findings}
    if "high" in sevs:
        return "caution"        # a finding is a sentence for a human, not a ban —
    if "medium" in sevs:        # refusal stays a person's decision, as everywhere
        return "caution"        # else in this OS. 'fail' is reserved for the
    return "pass"               # registry maintainer's judgement, not a regex's.


def scan_block(html: str, scanner: str = "static/1", extra: list[dict] | None = None) -> dict:
    """The ``security`` block that goes INSIDE the manifest, under the signature."""
    findings = static_scan(html) + list(extra or [])
    return {"scanner": scanner, "scanned_at": time.time(),
            "verdict": verdict_of(findings), "findings": findings}


AI_SCAN_PROMPT = """You are auditing a single-file HTML app that will run inside AgentOS's \
sandboxed app iframe (opaque origin, no cookies, tool access only through appTool/appData \
with per-app permissions). Report ONLY genuine security concerns: data exfiltration, \
permission overreach relative to the app's stated purpose, obfuscated code, sandbox-escape \
attempts, or deceptive UI (fake system prompts, credential harvesting). For each concern \
give severity high/medium, the line, and one sentence a non-programmer can act on. If the \
app is clean, say exactly: CLEAN. App description: {desc}

```html
{html}
```"""


# ---------------------------------------------------------------------------
# Index entries — what the registry's index.json is built from
# ---------------------------------------------------------------------------

def index_entry(pkg: dict, path: str, keys: dict[str, str] | None = None) -> dict:
    """One index.json row for a package file at repo-relative ``path``."""
    man = pkg.get("manifest") or {}
    status, _ = verify_package(pkg, keys)
    sec = man.get("security") or {}
    return {"id": Path(path).stem.replace(".agentapp", ""),
            "name": man.get("name") or "",
            "description": (man.get("description") or "")[:200],
            "icon": man.get("icon") or "",
            "version": man.get("version") or "1",
            "checksum": pkg.get("checksum") or "",
            "verified": status == "verified",
            "security": {"verdict": sec.get("verdict") or "unscanned",
                         "scanner": sec.get("scanner") or ""},
            "permissions": sorted({p.get("action") or "" for p in man.get("permissions") or []
                                   if p.get("action")}),
            "url": f"{REGISTRY_RAW}/{path}"}
