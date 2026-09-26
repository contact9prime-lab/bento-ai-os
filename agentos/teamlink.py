"""Linked teams: your agents and somebody else's, across machines or accounts.

A link is two teams agreeing to reach each other. It comes in two kinds, and both end
in the same place — a message from THEIR agent to one of YOURS, decided by YOUR gate:

- **machine** — another Bento, anywhere the network reaches. The link is mutual TLS
  (mTLS): each install has its own certificate authority (``~/.agentos/pki``, created on
  first use, never leaves) and a host certificate it issued itself. Pairing exchanges
  the two CAs over a one-time code, and from then on each side accepts ONLY a
  certificate issued by a CA it paired with, and then checks the exact certificate
  against the fingerprint recorded at pairing (pinning). No shared password, no
  certificate authority either side does not control.
- **account** — another account on this same machine. No network and no certificate:
  the server already knows who each account is (the signed cookie), so the handshake is
  a one-time code created by one person and redeemed by the other while signed in.

**The pairing is a handshake, not a password.** The inviter makes a single-use code
(ten minutes, stored hashed) and hands over an invite that also carries the inviter's
host-certificate fingerprint. The joiner connects, checks the certificate it is shown
against that fingerprint BEFORE sending anything (so a machine in the middle cannot
pose as the inviter), then presents the code and its own CA; the inviter checks the
code and answers with its CA. Both sides record the other. A wrong code is refused and
counted: a source that keeps guessing is refused outright for a while, the webhook
ceiling's argument.

**A link grants NOTHING.** It says who the other side is; what their agents may ask
yours is the permission matrix, as grants on a ``team`` principal named
``<link>/<their agent>`` — refused by default, never asked (there is nobody at the other
end of a network call to wait for), never opened by swarm. Every answer that comes
back from a linked team is marked untrusted: it was not written on this machine.

Kept free of FastAPI. The listener is plain asyncio with an SSL context, because the
one thing a web server here would not give us is the peer's certificate, and the
certificate IS the identity. The wire is one JSON line each way.

Faces: Settings → Agents → Working together → Linked teams (GUI/SUI), ``bento link`` (TUI/CLI).
"""
from __future__ import annotations

import asyncio
import contextvars
import datetime
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import _ssl
import time
from pathlib import Path

from . import config as cfgmod

SNI = "bento-team"              # a fixed name, so SNI is sent even when dialling an IP
INVITE_TTL = 600                # seconds a pairing code lives
MAX_LINE = 256 * 1024           # one request or answer, in bytes
GUESS_LIMIT = 10                # wrong codes from one address before it is refused
GUESS_WINDOW = 600
ASK_TIMEOUT = 900               # how long an asker waits for the other team's answer
REQUEST_TTL = 600               # seconds a link request waits for somebody to answer it
REQUEST_LIMIT = 5               # link requests one address may make per GUESS_WINDOW
MAX_PENDING = 8                 # requests waiting on this machine at once
POLL_EVERY = 2.0                # seconds between the requester's "decided yet?"
MAX_OPEN = 64                   # connections handled at once; more are closed at the door
FIRST_LINE = 10.0               # seconds a connection has to say what it wants
PEER_CALLS = 240                # calls a minute from one linked machine, of every kind


_ROOT: "contextvars.ContextVar[Path | None]" = contextvars.ContextVar("teamlink_root", default=None)


def home() -> Path:
    """Where this machine's PKI and links live. A context variable can point it
    elsewhere — which is how the tests stand two machines up in one process — and the
    listener pins the one it was started with into every connection it handles."""
    return _ROOT.get() or Path(cfgmod.AGENTOS_HOME)


class at:
    """`with teamlink.at(path):` — act as the machine whose home is `path`."""
    def __init__(self, root):
        self.root = Path(root)

    def __enter__(self):
        self.tok = _ROOT.set(self.root)
        return self

    def __exit__(self, *a):
        _ROOT.reset(self.tok)


def pki_dir() -> Path:
    return home() / "pki"


def links_path() -> Path:
    return home() / "links.json"


# ---- the certificates ------------------------------------------------------------------

def _write_private(p: Path, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def fingerprint(pem_or_der) -> str:
    """sha256 of the certificate's DER bytes, hex — what a pin compares."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    if isinstance(pem_or_der, str):
        pem_or_der = pem_or_der.encode()
    if pem_or_der.startswith(b"-----"):
        cert = x509.load_pem_x509_certificate(pem_or_der)
        pem_or_der = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(pem_or_der).hexdigest()


def ensure_pki() -> dict:
    """This install's CA and host certificate, created on first use. The CA key never
    leaves this directory; the host key is what this machine proves itself with."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    d = pki_dir()
    ca_crt, ca_key, host_crt, host_key = (d / "ca.crt", d / "ca.key", d / "host.crt", d / "host.key")
    if not (ca_crt.exists() and ca_key.exists() and host_crt.exists() and host_key.exists()):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        install = secrets.token_hex(6)
        now = datetime.datetime.now(datetime.timezone.utc)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Bento team CA {install}")])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
              .public_key(key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - datetime.timedelta(minutes=5))
              .not_valid_after(now + datetime.timedelta(days=3650))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                           content_commitment=False, key_encipherment=False,
                                           data_encipherment=False, key_agreement=False,
                                           encipher_only=False, decipher_only=False), critical=True)
              .sign(key, hashes.SHA256()))
        hkey = ec.generate_private_key(ec.SECP256R1())
        hname = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"bento host {install}")])
        host = (x509.CertificateBuilder().subject_name(hname).issuer_name(name)
                .public_key(hkey.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5))
                .not_valid_after(now + datetime.timedelta(days=825))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH,
                                                      ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(SNI)]), critical=False)
                .sign(key, hashes.SHA256()))
        pem = serialization.Encoding.PEM
        raw = serialization.PrivateFormat.PKCS8
        nope = serialization.NoEncryption()
        _write_private(ca_key, key.private_bytes(pem, raw, nope))
        _write_private(host_key, hkey.private_bytes(pem, raw, nope))
        ca_crt.write_bytes(ca.public_bytes(pem))
        host_crt.write_bytes(host.public_bytes(pem))
    return {"ca": ca_crt.read_text(), "host": host_crt.read_text(),
            "host_fp": fingerprint(host_crt.read_text()), "ca_fp": fingerprint(ca_crt.read_text()),
            "host_crt": str(host_crt), "host_key": str(host_key)}


def machine_name(cfg: dict | None = None) -> str:
    n = str(((cfg or {}).get("team") or {}).get("machine_name") or socket.gethostname() or "bento")
    return _label(n)


def _label(s: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", str(s or "").lower()).strip("-")[:32]
    return s or "team"


# ---- text from elsewhere ------------------------------------------------------------------
#
# Anything another team wrote — a message, a name, a question, an answer — reaches a
# terminal (`bento link chat`, the chat TUI) as well as a page. A page escapes HTML; a
# terminal obeys escape sequences: ESC ] 52 writes the clipboard, ESC ] 0 retitles the
# window, and a bidi override (U+202E) makes a line display as something it is not. So
# every such string passes `plain()` on the way IN, once, where it is received — not at
# each place it is shown, which is how one of them gets forgotten.

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def plain(s, limit: int = 4000, newlines: bool = True) -> str:
    """Text safe to show anywhere: control characters, C1 codes and bidi overrides
    removed, newlines kept (or folded) and the length cut."""
    t = _CONTROL.sub("", str(s if s is not None else ""))
    if not newlines:
        t = " ".join(t.split())
    return t[:limit].strip()


# ---- identity: who the other team IS, as they present themselves ---------------------------
#
# A link is a certificate, which is proof and says nothing a person can recognise. So
# every answer also carries the answering side's IDENTITY: its agent's name and look,
# and the name and look of the person there. It is cosmetic by construction — a name
# cut to 40 characters and a recipe from the closed set avatars.clean() allows, painted
# here by the one painter — so what a remote can claim is a face and a name, never
# markup and never a file.

def clean_identity(x) -> dict:
    from . import avatars
    x = x if isinstance(x, dict) else {}
    out = {"agent_name": plain(x.get("agent_name"), 40, newlines=False),
           "person": plain(x.get("person"), 40, newlines=False)}
    for k in ("agent", "me"):
        if isinstance(x.get(k), dict):
            out[k] = avatars.clean(x[k])
    return out


VISIT_ROWS = 24          # people drawn from one visit; an office is not a census


def clean_office(got) -> dict:
    """A linked team's office, as it ARRIVES: the style, pet and colours held to this
    machine's closed sets, every name through `plain`, every look through
    `avatars.clean`, and `working` only ever True, False or None (not shared). What the
    other side claimed beyond that is dropped — it is their answer, drawn by OUR
    painter, so nothing in it may reach the page as anything but a value."""
    from . import avatars, office
    g = got if isinstance(got, dict) else {}
    o = g.get("office") if isinstance(g.get("office"), dict) else {}
    rows = []
    for r in (g.get("rows") if isinstance(g.get("rows"), list) else [])[:VISIT_ROWS * 4]:
        if len(rows) >= VISIT_ROWS:
            break
        if not isinstance(r, dict):
            continue
        key = "@agent" if r.get("key") == "@agent" else re.sub(r"[^A-Za-z0-9_.-]", "", str(r.get("key") or ""))[:40]
        if not key:
            continue
        w = r.get("working")
        rows.append({"room": plain(r.get("room"), 24, newlines=False) or "Office",
                     "color": r["color"] if r.get("color") in office.COLORS else "slate",
                     "key": key, "label": plain(r.get("label"), 40, newlines=False) or key,
                     "working": w if w is True or w is False else None,
                     "recipe": avatars.clean(r["recipe"] if isinstance(r.get("recipe"), dict) else {})})
    return {"office": {"style": o["style"] if o.get("style") in office.STYLES else office.DEFAULT_STYLE,
                       "name": plain(o.get("name"), 24, newlines=False) or "Their office",
                       "pet": o["pet"] if o.get("pet") in office.PETS else "none"},
            "rows": rows}


def visit_text(label: str, v: dict) -> str:
    """A visit in words — `bento office visit` and the Visit route's `text`."""
    lines, room = [f"{v['office']['name']} — {label}'s office"], None
    for r in v["rows"]:
        if r["room"] != room:
            room = r["room"]
            lines.append(room)
        state = "busy" if r["working"] else "not shared" if r["working"] is None else "free"
        lines.append(f"  {r['label']}: {state}")
    if len(v["rows"]) <= 1:
        lines.append("Only their lead is shown: none of their agents may be asked over this link yet.")
    return "\n".join(lines)


def note_identity(owner: str, label: str, ident) -> None:
    """Record what a linked team says it looks like, when it changed. Written only on a
    difference, so a chatty link does not rewrite links.json on every message."""
    if not isinstance(ident, dict):
        return
    ident = clean_identity(ident)
    d = _load()
    for lk in d["links"]:
        if (lk.get("owner") or "") == (owner or "") and lk.get("label") == label:
            if lk.get("peer_identity") != ident:
                lk["peer_identity"] = ident
                _save(d)
            return


# ---- the registry ------------------------------------------------------------------------
#
# One machine-level file, because the listener is machine-level: an incoming certificate
# has to be matched to a link before anybody's account is known. Each link records its
# OWNER (the account whose agents it reaches; '' on a machine without accounts), and
# every view filters to the caller's own — the webhook's _hook_owner shape.

def _load() -> dict:
    try:
        d = json.loads(links_path().read_text())
    except Exception:
        d = {}
    d.setdefault("links", [])
    d.setdefault("invites", [])
    d.setdefault("requests", [])
    return d


def _save(d: dict):
    now = time.time()
    d["invites"] = [i for i in d["invites"] if i.get("expires", 0) > now and not i.get("used")]
    d["requests"] = [r for r in d.get("requests", []) if r.get("expires", 0) > now]
    _write_private(links_path(), json.dumps(d, indent=1).encode())


def links(owner: str | None = None) -> list[dict]:
    """Links, the caller's only when `owner` is given. PEMs stay out of views."""
    out = []
    for lk in _load()["links"]:
        if owner is not None and (lk.get("owner") or "") != (owner or ""):
            continue
        out.append({k: v for k, v in lk.items() if k not in ("peer_ca",)})
    return out


def find(owner: str, label: str) -> dict | None:
    for lk in _load()["links"]:
        if (lk.get("owner") or "") == (owner or "") and lk.get("label") == _label(label):
            return lk
    return None


def _by_fp(fp: str) -> dict | None:
    for lk in _load()["links"]:
        if lk.get("kind") == "machine" and lk.get("peer_host_fp") == fp:
            return lk
    return None


def _unique_label(d: dict, owner: str, want: str) -> str:
    base, n = _label(want), 1
    taken = {lk["label"] for lk in d["links"] if (lk.get("owner") or "") == (owner or "")}
    label = base
    while label in taken:
        n += 1
        label = f"{base}-{n}"
    return label


def _add_link(d: dict, **lk) -> dict:
    lk.setdefault("id", secrets.token_hex(6))
    lk.setdefault("created", time.time())
    lk["label"] = _unique_label(d, lk.get("owner") or "", lk.get("label") or "team")
    d["links"].append(lk)
    return lk


FLAGS = ("chat_muted",)


def set_flag(owner: str, label: str, key: str, value) -> dict | None:
    """A per-link switch this side owns (today: whether its person takes messages)."""
    if key not in FLAGS:
        raise ValueError(f"not a link setting: {key}")
    d = _load()
    for lk in d["links"]:
        if (lk.get("owner") or "") == (owner or "") and lk.get("label") == _label(label):
            lk[key] = bool(value)
            _save(d)
            return {k: v for k, v in lk.items() if k != "peer_ca"}
    return None


def remove(owner: str, label: str) -> bool:
    d = _load()
    keep = [lk for lk in d["links"]
            if not ((lk.get("owner") or "") == (owner or "") and lk.get("label") == _label(label))]
    if len(keep) == len(d["links"]):
        return False
    gone = [lk for lk in d["links"] if lk not in keep]
    d["links"] = keep
    # an account link is ONE agreement between two people: ending it ends both halves
    for lk in gone:
        if lk.get("kind") == "account":
            d["links"] = [x for x in d["links"] if not (
                x.get("kind") == "account" and x.get("pair_id") == lk.get("pair_id"))]
    _save(d)
    return True


# ---- invites -------------------------------------------------------------------------------

def _port(v) -> int:
    """A port the other side SAYS it listens on: a number in range, or none."""
    try:
        p = int(v or 0)
    except (TypeError, ValueError):
        return 0
    return p if 0 < p < 65536 else 0


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def invite(owner: str, kind: str = "machine", label: str = "", address: str = "",
           port: int = 0, cfg: dict | None = None) -> dict:
    """A single-use pairing code. For a machine link the invite also carries where to
    connect and the fingerprint of the certificate the joiner must be shown there."""
    if kind not in ("machine", "account"):
        raise ValueError("a link is to a machine or to an account")
    code = secrets.token_urlsafe(18)
    d = _load()
    d["invites"].append({"hash": _hash(code), "owner": owner or "", "kind": kind,
                         "label": _label(label) if label else "", "expires": time.time() + INVITE_TTL})
    _save(d)
    if kind == "account":
        return {"kind": "account", "code": code, "expires_in": INVITE_TTL}
    ident = ensure_pki()
    host = address or guess_address()
    port = int(port or team_port(cfg))
    return {"kind": "machine", "code": code, "expires_in": INVITE_TTL,
            "invite": f"bento://link/{host}:{port}/{code}#{ident['host_fp']}",
            "address": f"{host}:{port}", "fingerprint": ident["host_fp"]}


def parse_invite(s: str) -> dict:
    m = re.match(r"^bento://link/(\[[^\]]+\]|[^:/]+):(\d+)/([A-Za-z0-9_-]{16,})#([0-9a-f]{64})$",
                 (s or "").strip())
    if not m:
        raise ValueError("that is not an invite — it looks like "
                         "bento://link/HOST:PORT/CODE#FINGERPRINT")
    return {"host": m.group(1).strip("[]"), "port": int(m.group(2)), "code": m.group(3),
            "fp": m.group(4)}


def _take_invite(d: dict, code: str, kind: str) -> dict | None:
    h, now = _hash(code or ""), time.time()
    for inv in d["invites"]:
        if (secrets.compare_digest(inv["hash"], h) and inv["kind"] == kind
                and inv["expires"] > now and not inv.get("used")):
            inv["used"] = True
            return inv
    return None


def redeem_account(code: str, redeemer: str, names: dict | None = None) -> dict:
    """The other half of an account link, redeemed while signed in. Both people get a
    link row; ending it from either side ends both."""
    d = _load()
    inv = _take_invite(d, code, "account")
    if not inv:
        _save(d)
        raise ValueError("that code is wrong, used or expired — ask for a new one")
    if (inv["owner"] or "") == (redeemer or ""):
        raise ValueError("that is your own code — the other account redeems it")
    names = names or {}
    pair = secrets.token_hex(6)
    a = _add_link(d, kind="account", owner=inv["owner"], peer=redeemer, pair_id=pair,
                  label=inv.get("label") or names.get(redeemer) or "account")
    b = _add_link(d, kind="account", owner=redeemer, peer=inv["owner"], pair_id=pair,
                  label=names.get(inv["owner"]) or "account")
    _save(d)
    return {"mine": b, "theirs": a}


# ---- requests: the one-tap way in -------------------------------------------------------
#
# The invite above is a string one person copies to another. A REQUEST is the OAuth
# device flow instead: the side that wants the link types an address (or picks an
# account) and presses Request; the other side gets an Approve / Deny card; both
# screens show the same six digits. Nothing is copied by hand.
#
# The digits are the security, not decoration. They are computed on EACH side from the
# two certificates that side actually saw (`sas`), never sent — so a machine in the
# middle, which has to show each side its own certificate, makes the two screens
# disagree. It is Bluetooth's numeric comparison, for the same reason: the first
# contact between two machines that share nothing has no other way to be checked.

def sas(fp_a: str, fp_b: str) -> str:
    """Six digits both sides compute alone from the two certificate fingerprints."""
    a, b = sorted([str(fp_a), str(fp_b)])
    n = int(hashlib.sha256(f"bento-link:{a}:{b}".encode()).hexdigest(), 16) % 1_000_000
    t = f"{n:06d}"
    return f"{t[:3]} {t[3:]}"


def parse_address(s: str, cfg: dict | None = None) -> tuple[str, int]:
    """`office.local`, `office.local:8322`, `192.168.1.20`, `[fe80::1]:8322`, or the
    address the other desktop is open at (`http://office.local:8321` — the link port is
    one above it unless that machine chose another)."""
    raw = (s or "").strip()
    m = re.match(r"^https?://(\[[^\]]+\]|[^:/]+)(?::(\d+))?/?", raw)
    if m:
        web = int(m.group(2) or 8321)
        return m.group(1).strip("[]"), web + 1
    m = re.fullmatch(r"(\[[^\]]+\]|[A-Za-z0-9._-]+)(?::(\d{1,5}))?", raw)
    if not m:
        raise ValueError("type the other machine's name or address, e.g. office.local or "
                         "192.168.1.20 (add :PORT if it is not 8322)")
    return m.group(1).strip("[]"), int(m.group(2) or 8322)


def _chains(host_pem_or_der, ca_pem: str) -> bool:
    """Is this host certificate signed by this CA? Checked at the request so a
    mismatched pair is refused with a sentence, not at the first ask with a TLS error."""
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        raw = host_pem_or_der.encode() if isinstance(host_pem_or_der, str) else host_pem_or_der
        host = (x509.load_pem_x509_certificate(raw) if raw.startswith(b"-----")
                else x509.load_der_x509_certificate(raw))
        ca = x509.load_pem_x509_certificate(ca_pem.encode())
        ca.public_key().verify(host.signature, host.tbs_certificate_bytes,
                               ec.ECDSA(host.signature_hash_algorithm))
        return host.issuer == ca.subject
    except Exception:
        return False


def _req_view(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("token_hash", "peer_ca", "peer_host")}


def may_answer(r: dict, owner: str, who: dict | None = None) -> bool:
    """Who may see and answer a MACHINE's request. On a machine without accounts, the
    one person there. With accounts: the account the asker named (`ada@office.local`),
    or — when nobody was named — an admin, whose machine it is. Shown to everybody, the
    first person to tap Approve owned a link the asker meant for somebody else, and saw
    an address they had no business seeing."""
    who = who or {}
    if not who.get("multi"):
        return True
    want = (r.get("to_account") or "").lower()
    if want:
        return want in {(owner or "").lower(), str(who.get("name") or "").lower()}
    return bool(who.get("admin"))


def requests(owner: str | None, who: dict | None = None) -> dict:
    """What is waiting: requests from other MACHINES this person may answer (see
    `may_answer`; the link lands in whoever answers), and requests between ACCOUNTS —
    the ones asking you, and the ones you sent."""
    out = {"incoming": [], "outgoing": []}
    me = owner or ""
    for r in _load()["requests"]:
        if r.get("state") != "pending":
            continue
        if r["kind"] == "machine":
            if may_answer(r, me, who):
                out["incoming"].append(_req_view(r))
        elif r.get("to") == me:
            out["incoming"].append(_req_view(r))
        elif r.get("from") == me:
            out["outgoing"].append(_req_view(r))
    return out


def request_account(frm: str, to: str, names: dict | None = None) -> dict:
    """Ask another account on this machine to link. No code: the server already knows
    who both of you are (the signed cookie), so the only question left is whether THEY
    agree — and only they, signed in, can answer it."""
    names = names or {}
    if not to or to not in names:
        raise ValueError("there is no account by that name here")
    if (frm or "") == to:
        raise ValueError("that is you — pick another account")
    d = _load()
    if any(lk.get("kind") == "account" and (lk.get("owner") or "") == (frm or "") and lk.get("peer") == to
           for lk in d["links"]):
        raise ValueError(f"you are already linked with {names.get(to, to)}")
    d["requests"] = [r for r in d["requests"] if not (
        r["kind"] == "account" and r.get("from") == (frm or "") and r.get("to") == to)]
    r = {"id": secrets.token_hex(4), "kind": "account", "from": frm or "", "to": to,
         "name": names.get(frm or "", "") or "account", "to_name": names.get(to, to),
         "state": "pending", "created": time.time(), "expires": time.time() + REQUEST_TTL}
    d["requests"].append(r)
    _save(d)
    return _req_view(r)


def _take_request(d: dict, rid: str, owner: str, who: dict | None = None) -> dict:
    for r in d["requests"]:
        if r.get("id") == rid and r.get("state") == "pending":
            if r["kind"] == "account" and r.get("to") != (owner or ""):
                break                      # only the person asked may answer
            if r["kind"] == "machine" and not may_answer(r, owner, who):
                break                      # nor a machine's, unless it is theirs to answer
            return r
    raise ValueError("that request has been answered, withdrawn or has expired")


def approve(rid: str, owner: str, label: str = "", names: dict | None = None,
            who: dict | None = None) -> dict:
    """Say yes. A machine request becomes a link owned by whoever approved it (their
    agents are the ones it reaches); an account request becomes both halves at once."""
    d = _load()
    r = _take_request(d, rid, owner, who)
    if r["kind"] == "account":
        names = names or {}
        pair = secrets.token_hex(6)
        mine = _add_link(d, kind="account", owner=owner or "", peer=r["from"], pair_id=pair,
                         label=label or names.get(r["from"]) or r.get("name") or "account")
        theirs = _add_link(d, kind="account", owner=r["from"], peer=owner or "", pair_id=pair,
                           label=names.get(owner or "") or "account")
        d["requests"].remove(r)
        _save(d)
        return {"mine": mine, "theirs": theirs}
    if any(lk.get("peer_host_fp") == r["peer_host_fp"] for lk in d["links"]):
        d["requests"].remove(r)
        _save(d)
        raise ValueError("that machine is already linked here")
    # The link is written when the asker COLLECTS this answer (Listener._poll), not now:
    # an asker that went away would otherwise leave a half-link here, and its retry would
    # be refused as "already linked". Both halves appear together, or neither does.
    r["state"] = "approved"
    r["owner"] = owner or ""
    r["label"] = _label(label) if label else ""
    _save(d)
    return {"mine": None, "theirs": None, "pending": _req_view(r)}


def deny(rid: str, owner: str, who: dict | None = None) -> dict:
    d = _load()
    r = _take_request(d, rid, owner, who)
    if r["kind"] == "account":
        d["requests"].remove(r)
    else:
        r["state"] = "denied"              # the requester is told, then it goes
    _save(d)
    return _req_view(r)


def withdraw(rid: str, owner: str) -> bool:
    """The asker changed their mind (an account request; a machine request is withdrawn
    over the wire, by its token — `cancel_link`)."""
    d = _load()
    n = len(d["requests"])
    d["requests"] = [r for r in d["requests"] if not (
        r.get("id") == rid and r["kind"] == "account" and r.get("from") == (owner or ""))]
    _save(d)
    return len(d["requests"]) < n


# ---- TLS contexts -----------------------------------------------------------------------

def _SSLContext(proto: int) -> ssl.SSLContext:
    """The STDLIB context class, whatever has been injected over it. `bento` injects
    truststore into `ssl.SSLContext` so provider calls read the OS store — and a context
    that verifies against the OS store is exactly wrong here: a link trusts one pinned
    private CA and nothing else, and truststore's chain check cannot even read a peer
    that offers no certificate (the pairing joiner). Found by the full test suite.

    ssl.py's own setters call `super(SSLContext, …)` through the MODULE GLOBAL, which
    recurses once it has been replaced — so the few fields set here go through `_set`."""
    cls = next((c for c in ssl.SSLContext.__mro__
                if c.__module__ == "ssl" and c.__name__ == "SSLContext"), ssl.SSLContext)
    return cls(proto)


def _set(ctx: ssl.SSLContext, name: str, value) -> None:
    getattr(_ssl._SSLContext, name).__set__(ctx, value)


def _client_ctx(peer_ca: str | None, ident: dict) -> ssl.SSLContext:
    ctx = _SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    _set(ctx, "minimum_version", ssl.TLSVersion.TLSv1_2)
    ctx.check_hostname = False          # identity is the pinned certificate, not a DNS name
    if peer_ca:
        _set(ctx, "verify_mode", ssl.CERT_REQUIRED)
        ctx.load_verify_locations(cadata=peer_ca)
        ctx.load_cert_chain(ident["host_crt"], ident["host_key"])
    else:                                # pairing: no CA yet, the fingerprint is checked by hand
        _set(ctx, "verify_mode", ssl.CERT_NONE)
    return ctx


_trust_cache: dict = {}


def _server_ctx(ident: dict) -> ssl.SSLContext:
    """The listener's context. Client certificates are OPTIONAL at the TLS layer — the
    joiner of a pairing has none yet — and whatever is presented must chain to a CA this
    machine paired with. The trust store is rebuilt per connection when links.json has
    changed (an SNI callback swaps the context), so a link made from the CLI while the
    server runs is honoured without a restart."""
    root = home()

    def build():
        tok = _ROOT.set(root)
        try:
            return _build()
        finally:
            _ROOT.reset(tok)

    def _build():
        ctx = _SSLContext(ssl.PROTOCOL_TLS_SERVER)
        _set(ctx, "minimum_version", ssl.TLSVersion.TLSv1_2)
        ctx.load_cert_chain(ident["host_crt"], ident["host_key"])
        _set(ctx, "verify_mode", ssl.CERT_OPTIONAL)
        cas = [lk["peer_ca"] for lk in _load()["links"] if lk.get("kind") == "machine" and lk.get("peer_ca")]
        if cas:
            ctx.load_verify_locations(cadata="\n".join(cas))
        return ctx

    def current():
        try:
            m = (root / "links.json").stat().st_mtime
        except OSError:
            m = 0
        key = str(root)
        hit = _trust_cache.get(key)
        if not hit or hit[0] != m:
            hit = _trust_cache[key] = (m, build())
        return hit[1]

    base = build()

    def swap(sslobj, _name, _ctx):
        sslobj.context = current()
    base.sni_callback = swap
    return base


# ---- the wire: one JSON line each way ----------------------------------------------------

async def _read_line(reader, limit=MAX_LINE, timeout=30.0) -> dict:
    raw = await asyncio.wait_for(reader.readline(), timeout)
    if len(raw) > limit or not raw.endswith(b"\n"):
        raise ValueError("request too large or cut off")
    return json.loads(raw)


def _peer_fp(writer) -> str:
    obj = writer.get_extra_info("ssl_object")
    der = obj.getpeercert(binary_form=True) if obj else None
    return hashlib.sha256(der).hexdigest() if der else ""


class Listener:
    """The mTLS door. Only two things arrive here: a pairing (no certificate, a code) and
    a request from a linked team (a certificate this machine paired with, pinned).
    `on_ask(link, payload)` answers an ask; it is the server's, so this module knows
    nothing of stores or users."""

    def __init__(self, cfg: dict, on_ask=None, on_event=None, identity=None):
        self.cfg = cfg
        self.on_ask = on_ask
        self.on_event = on_event
        self.identity = identity             # owner -> who answers here (name, faces)
        self.server = None
        self.port = 0
        self._guess: dict = {}
        self._asks: dict = {}
        self._peer_calls: dict = {}
        self._open = 0
        self.root = home()

    async def start(self, host: str = "0.0.0.0", port: int | None = None):
        ident = ensure_pki()
        self.server = await asyncio.start_server(self._handle, host,
                                                 team_port(self.cfg) if port is None else port,
                                                 ssl=_server_ctx(ident), limit=MAX_LINE + 1)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    def _guessing(self, addr: str) -> bool:
        now = time.time()
        hits = [t for t in self._guess.get(addr, []) if t > now - GUESS_WINDOW]
        self._guess[addr] = hits
        return len(hits) >= GUESS_LIMIT

    def _asking_too_often(self, addr: str) -> bool:
        """A request puts a card on somebody's screen, so asking is metered apart from
        guessing: five an address per ten minutes is a person retrying, not a flood."""
        now = time.time()
        hits = [t for t in self._asks.get(addr, []) if t > now - GUESS_WINDOW]
        self._asks[addr] = hits
        if len(hits) >= REQUEST_LIMIT:
            return True
        hits.append(now)
        return False

    async def _request(self, req: dict, addr: str) -> dict:
        if self._asking_too_often(addr):
            return {"ok": False, "error": "too many link requests from this address — wait ten minutes"}
        ca, host = str(req.get("ca") or ""), str(req.get("host") or "")
        if not (ca.startswith("-----BEGIN CERTIFICATE") and host.startswith("-----BEGIN CERTIFICATE")):
            return {"ok": False, "error": "the asking machine sent no usable certificate"}
        fp = fingerprint(host)
        if not _chains(host, ca):
            return {"ok": False, "error": "the asking machine's certificate is not signed by its own CA"}
        d = _load()
        if any(lk.get("peer_host_fp") == fp for lk in d["links"]):
            return {"ok": False, "error": "that machine is already linked here"}
        # one waiting request per machine: asking again replaces the card, never stacks it
        d["requests"] = [r for r in d["requests"] if r.get("peer_host_fp") != fp]
        if sum(1 for r in d["requests"] if r["kind"] == "machine" and r.get("state") == "pending") >= MAX_PENDING:
            return {"ok": False, "error": "this machine has too many link requests waiting — try later"}
        token = secrets.token_urlsafe(24)
        ident = ensure_pki()
        r = {"id": secrets.token_hex(4), "kind": "machine", "token_hash": _hash(token),
             "name": _label(req.get("name")), "peer_ca": ca, "peer_host": host, "peer_host_fp": fp,
             "addr": addr, "port": _port(req.get("port")), "sas": sas(ident["host_fp"], fp),
             "identity": clean_identity(req.get("identity")),
             "to_account": re.sub(r"[^a-z0-9._-]", "", str(req.get("to") or "").lower())[:32],
             "state": "pending", "created": time.time(), "expires": time.time() + REQUEST_TTL}
        d["requests"].append(r)
        _save(d)
        if self.on_event:
            await self.on_event("request", _req_view(r))
        return {"ok": True, "token": token, "name": machine_name(self.cfg), "expires_in": REQUEST_TTL}

    async def _poll(self, req: dict, addr: str, cancel: bool = False) -> dict:
        if self._guessing(addr):
            return {"ok": False, "error": "too many wrong requests from this address — wait"}
        h = _hash(str(req.get("token") or ""))
        d = _load()
        r = next((x for x in d["requests"] if x.get("kind") == "machine"
                  and secrets.compare_digest(x.get("token_hash", ""), h)), None)
        if not r:
            self._guess.setdefault(addr, []).append(time.time())
            return {"ok": True, "state": "expired"}
        if cancel:
            d["requests"].remove(r)
            _save(d)
            return {"ok": True, "state": "withdrawn"}
        if r["state"] == "pending":
            return {"ok": True, "state": "pending", "expires_in": int(r["expires"] - time.time())}
        d["requests"].remove(r)            # an answer is collected once
        if r["state"] == "denied":
            _save(d)
            return {"ok": True, "state": "denied"}
        if any(lk.get("peer_host_fp") == r["peer_host_fp"] for lk in d["links"]):
            _save(d)
            return {"ok": False, "state": "error", "error": "that machine is already linked here"}
        lk = _add_link(d, kind="machine", owner=r.get("owner") or "",
                       label=r.get("label") or r.get("name") or "team", peer_ca=r["peer_ca"],
                       peer_host_fp=r["peer_host_fp"], peer_name=r.get("name") or "",
                       url=f"{r['addr']}:{r['port']}" if r.get("port") else "", direction="they asked",
                       peer_identity=r.get("identity") or {})
        _save(d)
        if self.on_event:
            await self.on_event("approved", {k: v for k, v in lk.items() if k != "peer_ca"})
        ident = ensure_pki()
        return {"ok": True, "state": "approved", "ca": ident["ca"], "host_fp": ident["host_fp"],
                "name": machine_name(self.cfg), "label_here": lk["label"],
                "identity": self._ident(r.get("owner") or "")}

    def _ident(self, owner: str) -> dict:
        try:
            return self.identity(owner or "") if self.identity else {}
        except Exception:
            return {}

    def _peer_busy(self, fp: str) -> bool:
        """A linked peer's calls, all kinds, per minute. Asks are also held by the PDP's
        own ceiling; this one covers what the PDP never sees (hello, roster, a pull)."""
        now = time.time()
        hits = [t for t in self._peer_calls.get(fp, []) if t > now - 60]
        if len(hits) >= PEER_CALLS:
            self._peer_calls[fp] = hits
            return True
        hits.append(now)
        self._peer_calls[fp] = hits
        return False

    async def _handle(self, reader, writer):
        _ROOT.set(self.root)             # this task is this machine, whatever started it
        addr = (writer.get_extra_info("peername") or ("?",))[0]
        if self._open >= MAX_OPEN:
            # at the ceiling: close at once rather than queue — a pile of half-open
            # connections is exactly what a flood is trying to build
            writer.close()
            return
        self._open += 1
        try:
            req = await _read_line(reader, timeout=FIRST_LINE)
            fp = _peer_fp(writer)
            if fp and _by_fp(fp) and self._peer_busy(fp):
                out = {"ok": False, "error": "too many requests from your team — slow down"}
            else:
                out = await self._dispatch(req, fp, addr)
        except Exception as e:           # a malformed request gets a sentence, never a trace
            out = {"ok": False, "error": f"bad request: {type(e).__name__}"}
        try:
            writer.write((json.dumps(out) + "\n").encode())
            await writer.drain()
        except Exception:
            pass
        finally:
            self._open -= 1
            writer.close()

    async def _dispatch(self, req: dict, fp: str, addr: str) -> dict:
        op = str(req.get("op") or "")
        if op == "request":
            return await self._request(req, addr)
        if op in ("poll", "cancel"):
            return await self._poll(req, addr, cancel=op == "cancel")
        if op == "pair":
            if self._guessing(addr):
                return {"ok": False, "error": "too many wrong codes from this address — wait and ask for a new one"}
            d = _load()
            inv = _take_invite(d, str(req.get("code") or ""), "machine")
            if not inv:
                self._guess.setdefault(addr, []).append(time.time())
                return {"ok": False, "error": "that code is wrong, used or expired"}
            peer_ca, peer_fp = str(req.get("ca") or ""), str(req.get("host_fp") or "")
            if not peer_ca.startswith("-----BEGIN CERTIFICATE") or not re.fullmatch(r"[0-9a-f]{64}", peer_fp):
                _save(d)
                return {"ok": False, "error": "the joining machine sent no usable certificate"}
            if any(lk.get("peer_host_fp") == peer_fp for lk in d["links"]):
                _save(d)
                return {"ok": False, "error": "that machine is already linked here"}
            lk = _add_link(d, kind="machine", owner=inv["owner"],
                           label=inv.get("label") or str(req.get("name") or "team"),
                           peer_ca=peer_ca, peer_host_fp=peer_fp, peer_name=_label(req.get("name")),
                           url=f"{addr}:{_port(req.get('port'))}" if _port(req.get("port")) else "",
                           direction="they joined", peer_identity=clean_identity(req.get("identity")))
            _save(d)
            if self.on_event:
                await self.on_event("paired", lk)
            ident = ensure_pki()
            return {"ok": True, "name": machine_name(self.cfg), "ca": ident["ca"],
                    "host_fp": ident["host_fp"], "identity": self._ident(inv["owner"])}
        lk = _by_fp(fp) if fp else None
        if not lk:
            return {"ok": False, "error": "this machine does not know your certificate — pair first"}
        if isinstance(req.get("identity"), dict):
            note_identity(lk.get("owner") or "", lk["label"], req["identity"])
        if op == "hello":
            return {"ok": True, "name": machine_name(self.cfg), "label_here": lk["label"],
                    "identity": self._ident(lk.get("owner") or "")}
        if op in ("ask", "roster", "mission", "chat", "chat_pull", "office") and self.on_ask:
            out = await self.on_ask(lk, req)
            if isinstance(out, dict) and "identity" not in out:
                out["identity"] = self._ident(lk.get("owner") or "")
            return out
        return {"ok": False, "error": f"unknown request '{op}'"}


async def call(lk: dict, req: dict, timeout: float = ASK_TIMEOUT) -> dict:
    """One request to a linked machine over mTLS, pinned to the certificate recorded at
    pairing. A certificate that chains to their CA but is not THE one paired with is
    refused before anything is sent."""
    host, _, port = str(lk.get("url") or "").rpartition(":")
    if not host or not port:
        return {"ok": False, "error": f"no address for {lk.get('label')} — they can reach you, "
                                      f"you cannot reach them (re-pair from this side to add one)"}
    ident = ensure_pki()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            host.strip("[]"), int(port), ssl=_client_ctx(lk["peer_ca"], ident),
            server_hostname=SNI, limit=MAX_LINE + 1), 15)
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as e:
        return {"ok": False, "error": f"could not reach {lk.get('label')} at {host}:{port} ({type(e).__name__})"}
    try:
        if _peer_fp(writer) != lk.get("peer_host_fp"):
            return {"ok": False, "error": f"{lk.get('label')} presented a different certificate "
                                          f"than the one paired with — refused"}
        writer.write((json.dumps(req) + "\n").encode())
        await writer.drain()
        got = await _read_line(reader, timeout=timeout)
        if isinstance(got, dict) and isinstance(got.get("identity"), dict):
            note_identity(lk.get("owner") or "", lk.get("label") or "", got["identity"])
        return got
    except (OSError, asyncio.TimeoutError, ValueError) as e:
        return {"ok": False, "error": f"{lk.get('label')} did not answer ({type(e).__name__})"}
    finally:
        writer.close()


async def join(invite_str: str, owner: str, label: str = "", cfg: dict | None = None,
               my_port: int = 0, identity: dict | None = None) -> dict:
    """Redeem a machine invite: connect, check the certificate against the invite's
    fingerprint BEFORE sending the code, trade CAs, record the link."""
    inv = parse_invite(invite_str)
    ident = ensure_pki()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            inv["host"], inv["port"], ssl=_client_ctx(None, ident), server_hostname=SNI,
            limit=MAX_LINE + 1), 15)
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as e:
        raise ValueError(f"could not reach {inv['host']}:{inv['port']} ({type(e).__name__}) — "
                         f"is linking switched on there, and the port open?")
    try:
        if _peer_fp(writer) != inv["fp"]:
            raise ValueError("the machine at that address is not the one that made the invite "
                             "(its certificate does not match) — nothing was sent")
        writer.write((json.dumps({"op": "pair", "code": inv["code"], "name": machine_name(cfg),
                                  "ca": ident["ca"], "host_fp": ident["host_fp"],
                                  "port": int(my_port or 0), "identity": identity or {}}) + "\n").encode())
        await writer.drain()
        got = await _read_line(reader)
    finally:
        writer.close()
    if not got.get("ok"):
        raise ValueError(got.get("error") or "the other machine refused")
    if got.get("host_fp") != inv["fp"]:
        raise ValueError("the other machine answered with a different certificate — refused")
    d = _load()
    lk = _add_link(d, kind="machine", owner=owner or "", label=label or got.get("name") or "team",
                   peer_ca=got["ca"], peer_host_fp=got["host_fp"], peer_name=_label(got.get("name")),
                   url=f"{inv['host']}:{inv['port']}", direction="you joined",
                   peer_identity=clean_identity(got.get("identity")))
    _save(d)
    return {k: v for k, v in lk.items() if k != "peer_ca"}


async def _tofu(host: str, port: int):
    """A first-contact connection: no CA yet, so the certificate is read, not trusted —
    the caller pins it, and the six digits are what a person checks it with."""
    ident = ensure_pki()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            host, port, ssl=_client_ctx(None, ident), server_hostname=SNI,
            limit=MAX_LINE + 1), 15)
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as e:
        raise ConnectionError(f"could not reach {host}:{port} ({type(e).__name__}) — is Bento "
                              f"running there with 'Accept linked teams' on, and the port open?")
    obj = writer.get_extra_info("ssl_object")
    der = obj.getpeercert(binary_form=True) if obj else b""
    return reader, writer, hashlib.sha256(der).hexdigest() if der else "", der


async def _once(host: str, port: int, payload: dict, pin: str = "") -> tuple[dict, str, bytes]:
    reader, writer, fp, der = await _tofu(host, port)
    try:
        if pin and fp != pin:
            raise ValueError("a different machine answered at that address than the one "
                             "you asked (its certificate changed) — nothing was sent")
        writer.write((json.dumps(payload) + "\n").encode())
        await writer.drain()
        return await _read_line(reader), fp, der
    finally:
        writer.close()


async def request_link(address: str, owner: str, cfg: dict | None = None, my_port: int = 0,
                       label: str = "", identity: dict | None = None) -> dict:
    """Ask the machine at `address` to link. `ada@office.local` addresses the request to
    Ada's account there (on a machine with accounts only she sees it; with no name, its
    admins do). Returns the pending request — including the six digits to compare — for
    `poll_link` / `wait_link` to follow."""
    rest, to = str(address or "").strip(), ""
    if "@" in rest and "://" not in rest:
        to, rest = rest.split("@", 1)
    host, port = parse_address(rest, cfg)
    ident = ensure_pki()
    got, fp, _ = await _once(host, port, {"op": "request", "name": machine_name(cfg),
                                          "ca": ident["ca"], "host": ident["host"],
                                          "port": int(my_port or 0), "identity": identity or {},
                                          "to": to.strip().lower()})
    if not got.get("ok"):
        raise ValueError(got.get("error") or "the other machine refused")
    if fp == ident["host_fp"]:
        raise ValueError("that address is this machine")
    return {"id": secrets.token_hex(4), "host": host, "port": port, "fp": fp,
            "token": got["token"], "name": _label(got.get("name")), "owner": owner or "",
            "label": label, "sas": sas(fp, ident["host_fp"]),
            "expires": time.time() + int(got.get("expires_in") or REQUEST_TTL)}


async def poll_link(p: dict) -> dict:
    """Has the other side answered? On yes, the link is recorded HERE, pinned to the
    certificate seen when the request was made — the one the digits were computed from."""
    try:
        got, fp, der = await _once(p["host"], p["port"], {"op": "poll", "token": p["token"]}, pin=p["fp"])
    except ConnectionError as e:
        return {"state": "pending", "note": str(e)}      # a blip is not an answer; keep asking
    except ValueError as e:
        return {"state": "error", "error": str(e)}
    st = got.get("state") or ("error" if not got.get("ok") else "pending")
    if st != "approved":
        return {"state": st, "error": got.get("error", "")}
    if got.get("host_fp") != p["fp"] or not _chains(der, str(got.get("ca") or "")):
        return {"state": "error", "error": "the other machine's answer does not match its certificate — refused"}
    d = _load()
    lk = _add_link(d, kind="machine", owner=p.get("owner") or "",
                   label=p.get("label") or got.get("name") or "team", peer_ca=got["ca"],
                   peer_host_fp=p["fp"], peer_name=_label(got.get("name")),
                   url=f"{p['host']}:{p['port']}", direction="you asked",
                   peer_identity=clean_identity(got.get("identity")))
    _save(d)
    return {"state": "approved", "link": {k: v for k, v in lk.items() if k != "peer_ca"}}


async def cancel_link(p: dict) -> None:
    try:
        await _once(p["host"], p["port"], {"op": "cancel", "token": p["token"]}, pin=p["fp"])
    except Exception:
        pass                                             # it expires on its own anyway


async def wait_link(p: dict, every: float = POLL_EVERY, on_tick=None) -> dict:
    """Poll until the other side answers or the request expires — the device flow's
    loop, shared by the server's background task and `bento link request`."""
    while True:
        got = await poll_link(p)
        if got["state"] != "pending":
            return got
        if time.time() > p["expires"]:
            await cancel_link(p)
            return {"state": "expired"}
        if on_tick:
            on_tick(got)
        await asyncio.sleep(every)


# ---- addresses ---------------------------------------------------------------------------

def team_port(cfg: dict | None) -> int:
    t = (cfg or {}).get("team") or {}
    return int(t.get("link_port") or (int((cfg or {}).get("port") or 8321) + 1))


def guess_address() -> str:
    """The address another machine would dial: the interface the default route leaves by
    (no packet is sent), else the host name. The invite says it, and a person can type a
    better one (a tailnet name) when the guess is wrong."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
        s.close()
        if not ipaddress.ip_address(ip).is_loopback:
            return ip
    except Exception:
        pass
    return socket.gethostname() or "127.0.0.1"
