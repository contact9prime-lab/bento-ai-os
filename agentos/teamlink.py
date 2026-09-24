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

Faces: Settings → AI providers → Team → Linked teams (GUI/SUI), ``bento link`` (TUI/CLI).
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
    return d


def _save(d: dict):
    now = time.time()
    d["invites"] = [i for i in d["invites"] if i.get("expires", 0) > now and not i.get("used")]
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

    def __init__(self, cfg: dict, on_ask=None, on_event=None):
        self.cfg = cfg
        self.on_ask = on_ask
        self.on_event = on_event
        self.server = None
        self.port = 0
        self._guess: dict = {}
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

    async def _handle(self, reader, writer):
        _ROOT.set(self.root)             # this task is this machine, whatever started it
        addr = (writer.get_extra_info("peername") or ("?",))[0]
        try:
            req = await _read_line(reader)
            out = await self._dispatch(req, _peer_fp(writer), addr)
        except Exception as e:           # a malformed request gets a sentence, never a trace
            out = {"ok": False, "error": f"bad request: {type(e).__name__}"}
        try:
            writer.write((json.dumps(out) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()

    async def _dispatch(self, req: dict, fp: str, addr: str) -> dict:
        op = str(req.get("op") or "")
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
                           url=f"{addr}:{int(req.get('port') or 0)}" if req.get("port") else "",
                           direction="they joined")
            _save(d)
            if self.on_event:
                await self.on_event("paired", lk)
            ident = ensure_pki()
            return {"ok": True, "name": machine_name(self.cfg), "ca": ident["ca"],
                    "host_fp": ident["host_fp"]}
        lk = _by_fp(fp) if fp else None
        if not lk:
            return {"ok": False, "error": "this machine does not know your certificate — pair first"}
        if op == "hello":
            return {"ok": True, "name": machine_name(self.cfg), "label_here": lk["label"]}
        if op in ("ask", "roster") and self.on_ask:
            return await self.on_ask(lk, req)
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
        return await _read_line(reader, timeout=timeout)
    except (OSError, asyncio.TimeoutError, ValueError) as e:
        return {"ok": False, "error": f"{lk.get('label')} did not answer ({type(e).__name__})"}
    finally:
        writer.close()


async def join(invite_str: str, owner: str, label: str = "", cfg: dict | None = None,
               my_port: int = 0) -> dict:
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
                                  "port": int(my_port or 0)}) + "\n").encode())
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
                   url=f"{inv['host']}:{inv['port']}", direction="you joined")
    _save(d)
    return {k: v for k, v in lk.items() if k != "peer_ca"}


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
