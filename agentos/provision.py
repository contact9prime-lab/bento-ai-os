"""New machines on the network: noticed, asked about, and set up from the one that leads.

Asked for as "in case of Pi mode, the system should be able to provision multiple pi agents,
so it's more like POAP: it should be able to identify and discover pi(s) and ask for it to be
enabled with agent", and then "whenever a new machine is turned on and discovered on the
network, we should be able to check if we need to provision it".

Two sides, one file each way:

  * A machine WAITING to be set up (a fresh Raspberry Pi, or anything told `bento pool wait
    on`) says so on the local network: it announces itself on a UDP broadcast when it starts
    and every so often after, answers a "who is there?" probe, and opens a small TLS door
    that takes exactly one thing, a claim. It shows a six-digit code on its own screen, in
    `bento pool wait` and in its log, unless it carries an enrolment key.
  * A machine that leads a community, or could lead one, LISTENS. A new machine heard for
    the first time is a toast with Review on its admin's screens and a row in Settings →
    Agents → Community. Enabling it is a person's act: the code from the new machine's
    screen, or the community's enrolment key, proves the claim. Machines that carry an
    enrolment key marked automatic are enabled the moment they are heard, which is the
    zero-touch case: flash the SD card with the key on it, plug the Pi in, walk away.

What a claim does is small and stated. The new machine writes a machine link to the
leader (the same kind a person makes with the six digits), takes the profile it was sent
(its name, its agent's name, kiosk, one agent on screen, Light mode, all from a CLOSED set
read field by field), finishes setup, switches its link door on and asks to join the
community. The leader recorded the claim, so that join is let in at once. From then on it
is an ordinary member: one grant each way (pool.py), revocable in Permissions.

Four rules keep it honest:

  * THE DOOR IS OPEN ONLY WHILE WAITING. A machine that was set up, joined, or told
    `wait off` answers nothing and binds nothing. A claim closes the door for good.
  * A CLAIM IS PROVEN, NEVER ASSUMED. The proof is an HMAC over both machines' certificate
    fingerprints and a fresh nonce, keyed by the code or the key, so it cannot be replayed
    to another machine. Five wrong codes and the code changes; three changes and the door
    shuts for ten minutes. A keyed claim is proven BOTH ways (the new machine answers with
    its own HMAC), because an automatic key must not enable a device that only copied a key
    id out of a broadcast.
  * WHAT IS HEARD IS SOMEBODY ELSE'S WORDS. A beacon is unauthenticated: its fields pass
    `clean_beacon` (a closed set, `teamlink.plain`, bounded), the list is capped, and nothing
    is ever enabled because a beacon said so, except a machine that proves the key.
  * IT IS THE MACHINE'S. Provisioning is admin-only on a machine with accounts, every step
    is a ledger row on both sides, and there is deliberately no agent tool: enabling a
    machine spends this machine's model budget on it, which is a person's decision.

The PIN's limit is said out loud (docs/pool.md): a six-digit code is checked by the person
who reads it off the new machine's screen and compares the machine id shown on both
screens. On a network you do not trust, use the enrolment key, whose secret never travels.

Kept free of HTTP. The network parts are asyncio and take everything they need as
arguments, so `bento pool discover` / `enable` work with the server down.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import socket
import ssl
import struct
import time
from pathlib import Path

MAGIC = "bento-provision/1"
UDP_PORT = 8620                 # announcements and "who is there?" (one port, every machine)
TCP_PORT = 8620                 # the waiting machine's claim door (TLS)
ANNOUNCE_FAST_S = 10            # how often a waiting machine says so, at first
ANNOUNCE_FAST_FOR = 600         # …for this long after it starts
ANNOUNCE_SLOW_S = 60            # then this often
PIN_TRIES = 5                   # wrong codes before the code changes
PIN_ROUNDS = 3                  # changes before the door shuts for LOCK_S
LOCK_S = 600
MAX_SEEN = 64                   # machines remembered as heard
REPLIES_PER_MIN = 30            # answers one address gets to "who is there?"
NONCE_TTL = 60
RESAVE_S = 300                  # a machine heard again unchanged is written down this often
BEACON_MAX = 4096
BOOT_KEY_FILES = ("/boot/firmware/bento-enroll.txt", "/boot/bento-enroll.txt")
KEY_PREFIX = "bento-enroll-1"


# ---- the file ------------------------------------------------------------------------

def _home() -> Path:
    from . import teamlink
    return teamlink.home()


def path() -> Path:
    return _home() / "provision.json"


def _blank() -> dict:
    return {"wait": None, "pin": "", "pin_bad": 0, "pin_rounds": 0, "locked_until": 0.0,
            "key": "", "claimed": {}, "watch": None, "keys": [], "seen": {}, "enabled": {},
            "devices": {}}


def load() -> dict:
    try:
        d = json.loads(path().read_text())
    except Exception:
        d = {}
    out = _blank()
    out.update({k: v for k, v in d.items() if k in out})
    return out


def save(d: dict) -> None:
    from . import teamlink
    teamlink._write_private(path(), json.dumps(d, indent=1).encode())


# ---- this machine ------------------------------------------------------------------------

def udp_port() -> int:
    try:
        return int(os.environ.get("AGENTOS_DISCOVER_UDP") or UDP_PORT)
    except ValueError:
        return UDP_PORT


def tcp_port(cfg: dict | None = None) -> int:
    """The claim door's port. `AGENTOS_DISCOVER_PORT` exists so several stand-in Pis can
    wait on one test box (packaging/dev/provision-e2e); a real Pi uses the default."""
    v = os.environ.get("AGENTOS_DISCOVER_PORT") or ((cfg or {}).get("provision") or {}).get("port")
    try:
        p = int(v or TCP_PORT)
    except (TypeError, ValueError):
        p = TCP_PORT
    return p if 0 < p < 65536 else TCP_PORT


def board() -> str:
    """'Raspberry Pi 5 Model B Rev 1.0', or '' on anything that is not a Pi. The device
    tree is where the board says what it is; `AGENTOS_PI_MODEL` stands in for it in tests."""
    fake = os.environ.get("AGENTOS_PI_MODEL")
    if fake is not None:
        return fake.strip()
    try:
        m = Path("/proc/device-tree/model").read_bytes().rstrip(b"\x00").decode(errors="replace").strip()
    except OSError:
        return ""
    return m if "raspberry pi" in m.lower() else ""


def hardware() -> dict:
    ram = 0
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("MemTotal:"):
                ram = int(ln.split()[1]) // 1024
                break
    except Exception:
        pass
    return {"board": board(), "arch": platform.machine(), "ram_mb": ram,
            "cores": os.cpu_count() or 0, "host": socket.gethostname()[:63]}


def id_code(fp: str) -> str:
    """The machine id a person compares on two screens: 4F2A-91C0."""
    h = str(fp or "")[:8].upper()
    return f"{h[:4]}-{h[4:]}" if h else ""


def _my_fp() -> str:
    from . import teamlink
    return teamlink.ensure_pki()["host_fp"]


# ---- enrolment keys ------------------------------------------------------------------------

def parse_key(text: str) -> dict | None:
    """`bento-enroll-1.<id>.<secret>.<ca fingerprint prefix>` → its parts, or None."""
    parts = str(text or "").strip().split(".")
    if len(parts) != 4 or parts[0] != KEY_PREFIX:
        return None
    _, kid, secret, cafp = parts
    if not (re.fullmatch(r"[0-9a-f]{8}", kid) and re.fullmatch(r"[A-Za-z0-9_-]{24,64}", secret)
            and re.fullmatch(r"[0-9a-f]{16}", cafp)):
        return None
    return {"id": kid, "secret": secret, "cafp": cafp}


def key_text(k: dict) -> str:
    return f"{KEY_PREFIX}.{k['id']}.{k['secret']}.{k['cafp']}"


def make_key(label: str = "", auto: bool = False, profile: dict | None = None,
             single: bool = False) -> dict:
    """A new enrolment key for this machine's community. The secret is kept here (0600)
    because the leader has to prove the claim with it; it is shown once, to put on cards."""
    from . import teamlink
    ident = teamlink.ensure_pki()
    d = load()
    k = {"id": secrets.token_hex(4), "secret": secrets.token_urlsafe(24), "cafp": ident["ca_fp"][:16],
         "label": teamlink.plain(label, 40, newlines=False).strip() or "Pis",
         "auto": bool(auto), "profile": clean_profile(profile or {}), "created": time.time(),
         "single": bool(single)}
    d["keys"].append(k)
    save(d)
    return {**key_view(k), "text": key_text(k)}


def key_view(k: dict) -> dict:
    return {"id": k["id"], "label": k.get("label", ""), "auto": bool(k.get("auto")),
            "profile": k.get("profile") or {}, "created": k.get("created", 0),
            "single": bool(k.get("single"))}


def keys() -> list[dict]:
    return [key_view(k) for k in load()["keys"]]


def drop_key(kid: str) -> bool:
    d = load()
    keep = [k for k in d["keys"] if k["id"] != kid]
    if len(keep) == len(d["keys"]):
        return False
    d["keys"] = keep
    save(d)
    return True


def set_key_auto(kid: str, on: bool) -> dict | None:
    d = load()
    for k in d["keys"]:
        if k["id"] == kid:
            k["auto"] = bool(on)
            save(d)
            return key_view(k)
    return None


def adopt_key(text: str) -> dict:
    """Carry an enrolment key on THIS machine (it is waiting to be set up)."""
    k = parse_key(text)
    if not k:
        raise ValueError("that is not an enrolment key (it starts with bento-enroll-1.)")
    d = load()
    d["key"] = key_text(k)
    save(d)
    return {"id": k["id"]}


def boot_key() -> str:
    """A key put on the SD card's boot partition (or AGENTOS_ENROLL), adopted at start:
    the zero-touch road. The file is left where it is; it is read, never written."""
    for src in ([os.environ.get("AGENTOS_ENROLL", "")] + [p for p in BOOT_KEY_FILES]):
        try:
            text = src if src.startswith(KEY_PREFIX) else (Path(src).read_text() if src else "")
        except OSError:
            continue
        for ln in text.splitlines():
            if parse_key(ln.strip()):
                return ln.strip()
    return ""


def adopt_boot_key() -> bool:
    k = boot_key()
    if not k:
        return False
    d = load()
    if d["claimed"] or d["key"] == k:
        return False
    d["key"] = k
    save(d)
    return True


# ---- the profile a new machine is set up with -------------------------------------------

PROFILE_KEYS = ("name", "agent_name", "kiosk", "buddy", "lite", "wake_word")


def clean_profile(p) -> dict:
    """The closed set a claim may carry, read field by field. An unknown field is dropped;
    what is kept is bounded and plain, because the new machine writes it into its config."""
    from . import face as facemod
    from . import teamlink
    p = p if isinstance(p, dict) else {}
    out: dict = {}
    if p.get("name"):
        out["name"] = teamlink._label(p["name"])
    if p.get("agent_name"):
        n = teamlink.plain(p["agent_name"], 32, newlines=False).strip()
        if n:
            out["agent_name"] = n
    if "kiosk" in p:
        out["kiosk"] = bool(p["kiosk"])
    if str(p.get("buddy") or "") in facemod.BUDDY:
        out["buddy"] = str(p["buddy"])
    if "lite" in p:
        out["lite"] = bool(p["lite"])
    if p.get("wake_word") and not facemod.wake_word_problem(str(p["wake_word"])):
        out["wake_word"] = " ".join(str(p["wake_word"]).split())
    return out


# ---- the waiting side ----------------------------------------------------------------------

def waiting(cfg: dict) -> tuple[bool, str]:
    """Is this machine waiting to be set up by another, and why. Read at start and after
    every change; the door and the announcements follow it."""
    from . import pool as poolmod
    d = load()
    if d["claimed"]:
        return False, "set up by " + str(d["claimed"].get("by") or "another machine")
    if poolmod.load().get("role"):
        return False, "already in a community"
    if d["wait"] is False:
        return False, "told not to wait"
    if d["wait"] is True:
        return True, "asked to wait"
    if d["key"]:
        return True, "carries an enrolment key"
    if board() and not (cfg or {}).get("setup_complete"):
        return True, "a Raspberry Pi that has not been set up"
    return False, ""


def set_wait(on: bool | None) -> dict:
    d = load()
    d["wait"] = on
    if on:
        d["claimed"] = {}
    save(d)
    return d


def pin() -> str:
    """The code shown on this machine's screen. Made once, changed after PIN_TRIES wrong."""
    d = load()
    if not re.fullmatch(r"\d{6}", d.get("pin") or ""):
        d["pin"] = f"{secrets.randbelow(10**6):06d}"
        save(d)
    return d["pin"]


def locked() -> int:
    """Seconds the door stays shut after too many wrong codes, or 0."""
    left = load().get("locked_until", 0) - time.time()
    return int(left) if left > 0 else 0


def here(cfg: dict) -> dict:
    """What a waiting machine says about itself. Nothing in it is a secret."""
    from . import teamlink
    from . import __version__ as ver
    d = load()
    kid = (parse_key(d["key"]) or {}).get("id", "") if d["key"] else ""
    ok, why = waiting(cfg)
    return {"m": MAGIC, "op": "here", "name": teamlink.machine_name(cfg), "hw": hardware(),
            "fp": _my_fp(), "port": tcp_port(cfg), "version": ver, "waiting": ok, "why": why,
            "key_id": kid, "code": not kid}


def status(cfg: dict) -> dict:
    """The waiting machine's own view: shown on its screen and by `bento pool wait`."""
    ok, why = waiting(cfg)
    d = load()
    fp = _my_fp()
    kid = (parse_key(d["key"]) or {}).get("id", "") if d["key"] else ""
    return {"waiting": ok, "why": why, "pin": pin() if ok and not kid else "",
            "key_id": kid, "id": id_code(fp), "locked": locked(),
            "claimed": d["claimed"], "port": tcp_port(cfg), "hw": hardware()}


def proof(secret: str, leader_fp: str, member_fp: str, nonce: str, side: str = "claim") -> str:
    msg = f"{MAGIC}|{side}|{leader_fp}|{member_fp}|{nonce}".encode()
    return hmac.new(str(secret).encode(), msg, hashlib.sha256).hexdigest()


def check_claim(req: dict, nonce: str) -> tuple[bool, str, str]:
    """(ok, error, secret used) for a claim on this waiting machine. Counts wrong codes."""
    d = load()
    if locked():
        return False, f"too many wrong codes — this machine takes no claim for {locked() // 60 + 1} minutes", ""
    leader_fp = str((req.get("leader") or {}).get("host_fp") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", leader_fp):
        return False, "the claim names no leader certificate", ""
    mine = _my_fp()
    got = str(req.get("proof") or "")
    if req.get("how") == "key":
        k = parse_key(d["key"]) if d["key"] else None
        if not k or k["id"] != str(req.get("key_id") or ""):
            return False, "this machine does not carry that enrolment key", ""
        from . import teamlink
        ca = str((req.get("leader") or {}).get("ca") or "")
        try:
            ca_ok = ca.startswith("-----BEGIN CERTIFICATE") and teamlink.fingerprint(ca)[:16] == k["cafp"]
        except Exception:
            ca_ok = False
        if not ca_ok:
            return False, "the claim comes from a different community than this machine's key", ""
        if not hmac.compare_digest(got, proof(k["secret"], leader_fp, mine, nonce)):
            return False, "the enrolment key did not match", ""
        return True, "", k["secret"]
    code = pin()
    if hmac.compare_digest(got, proof(code, leader_fp, mine, nonce)):
        return True, "", code
    d = load()
    d["pin_bad"] = int(d.get("pin_bad") or 0) + 1
    if d["pin_bad"] >= PIN_TRIES:
        d["pin_bad"], d["pin"] = 0, ""
        d["pin_rounds"] = int(d.get("pin_rounds") or 0) + 1
        if d["pin_rounds"] >= PIN_ROUNDS:
            d["pin_rounds"], d["locked_until"] = 0, time.time() + LOCK_S
    save(d)
    return False, "that code is not the one on this machine's screen", ""


def apply_claim(cfg: dict, req: dict, peer_addr: str) -> dict:
    """Take the claim: a machine link to the leader, the profile, setup done. Mutates and
    the caller saves `cfg`. Returns what the leader needs to link back."""
    from . import teamlink
    from . import face as facemod
    leader = req.get("leader") or {}
    ca, lfp = str(leader.get("ca") or ""), str(leader.get("host_fp") or "")
    if not ca.startswith("-----BEGIN CERTIFICATE"):
        raise ValueError("the claim carries no certificate for its leader")
    lport = teamlink._port(leader.get("port"))
    td = teamlink._load()
    td["links"] = [lk for lk in td["links"] if lk.get("peer_host_fp") != lfp]
    lk = teamlink._add_link(td, kind="machine", owner="",
                            label=teamlink._label(leader.get("name") or "leader"), peer_ca=ca,
                            peer_host_fp=lfp, peer_name=teamlink._label(leader.get("name") or "leader"),
                            url=f"{peer_addr}:{lport}" if lport else "",
                            direction="set this machine up")
    teamlink._save(td)
    prof = clean_profile(req.get("profile"))
    team = cfg.setdefault("team", {})
    team["listen"] = True
    if prof.get("name"):
        team["machine_name"] = prof["name"]
    if prof.get("agent_name"):
        cfg["agent_name"] = prof["agent_name"]
        cfg.setdefault("onboarding", {}).setdefault("confirmed", [])
        if "name" not in cfg["onboarding"]["confirmed"]:
            cfg["onboarding"]["confirmed"].append("name")
    if prof.get("lite"):
        cfg["profile"] = "lite"
    facemod.set_face(cfg, kiosk=prof.get("kiosk") if "kiosk" in prof else None,
                     buddy=prof.get("buddy"), wake_word=prof.get("wake_word"))
    cfg["setup_complete"] = True
    d = load()
    d["claimed"] = {"at": time.time(), "by": lk.get("peer_name") or "", "leader_fp": lfp,
                    "link": lk["label"], "how": str(req.get("how") or ""),
                    "pool": teamlink.plain(((req.get("pool") or {}).get("name")) or "", 40, newlines=False)}
    d["wait"] = None
    d["pin"] = ""
    save(d)
    return {"link": lk["label"], "profile": prof}


def clean_beacon(b, addr: str = "") -> dict | None:
    """A beacon is a stranger's words: the closed set, plain and bounded, or None."""
    from . import teamlink
    if not isinstance(b, dict) or b.get("m") != MAGIC:
        return None
    fp = str(b.get("fp") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", fp):
        return None
    hw = b.get("hw") if isinstance(b.get("hw"), dict) else {}

    def num(v, hi):
        try:
            return max(0, min(int(v), hi))
        except (TypeError, ValueError):
            return 0
    return {"fp": fp, "name": teamlink._label(b.get("name") or "machine"),
            "addr": addr, "port": teamlink._port(b.get("port")),
            "hw": {"board": teamlink.plain(hw.get("board") or "", 60, newlines=False),
                   "arch": teamlink.plain(hw.get("arch") or "", 16, newlines=False),
                   "ram_mb": num(hw.get("ram_mb"), 1 << 22), "cores": num(hw.get("cores"), 1024),
                   "host": teamlink.plain(hw.get("host") or "", 63, newlines=False)},
            "version": teamlink.plain(b.get("version") or "", 20, newlines=False),
            "waiting": bool(b.get("waiting")),
            "key_id": str(b.get("key_id") or "") if re.fullmatch(r"[0-9a-f]{8}", str(b.get("key_id") or "")) else "",
            "id": id_code(fp)}


# ---- the listening side -----------------------------------------------------------------------

def watching(cfg: dict) -> bool:
    """Does this machine listen for new machines? A leader does, and so does a machine that
    could lead (a brain of its own, not a member), unless its admin said not to."""
    from . import pool as poolmod
    d = load()
    if d["watch"] is False:
        return False
    if waiting(cfg)[0]:
        return False
    role = poolmod.load().get("role")
    if role == "leader":
        return True
    if role in ("member", "pending"):
        return bool(d["watch"])
    return bool(d["watch"]) or poolmod.has_brain(cfg)


def note_seen(b: dict) -> bool:
    """Remember a machine heard on the network. True the FIRST time it is heard waiting
    (that is when somebody is asked), never again for the same machine."""
    d = load()
    seen = d["seen"]
    e = seen.get(b["fp"])
    now = time.time()
    new = False
    if e is None:
        if not b["waiting"]:
            return False
        e = seen[b["fp"]] = {"first": now, "state": "new"}
        new = True
    elif e.get("state") == "enabled" and b["waiting"]:
        e["state"] = "new"                # set up again from scratch: ask again
        new = True
    fields = {k: b[k] for k in ("name", "addr", "port", "hw", "version", "waiting", "key_id", "id")}
    if not new and all(e.get(k) == v for k, v in fields.items()) and now - e.get("last", 0) < RESAVE_S:
        return False          # heard again, nothing changed: no write (an SD card wears out)
    e.update(fields)
    e["last"] = now
    if len(seen) > MAX_SEEN:
        for fp, _ in sorted(seen.items(), key=lambda kv: kv[1].get("last", 0))[:len(seen) - MAX_SEEN]:
            seen.pop(fp, None)
    save(d)
    return new


def seen_list() -> list[dict]:
    """Machines heard, newest first, with whether each carries one of this machine's keys."""
    d = load()
    mine = {k["id"]: k for k in d["keys"]}
    out = []
    for fp, e in d["seen"].items():
        k = mine.get(e.get("key_id") or "")
        out.append({**e, "fp": fp, "age": int(time.time() - e.get("last", 0)),
                    "our_key": bool(k), "key_label": (k or {}).get("label", ""),
                    "auto": bool(k and k.get("auto"))})
    return sorted(out, key=lambda x: -x.get("last", 0))


def ignore(fp_or_name: str) -> dict | None:
    d = load()
    e = _find_seen(d, fp_or_name)
    if not e:
        return None
    d["seen"][e]["state"] = "ignored"
    save(d)
    return d["seen"][e]


def _find_seen(d: dict, key: str) -> str:
    k = str(key or "").strip().lower()
    for fp, e in d["seen"].items():
        if k and (fp == k or fp.startswith(k) or e.get("name") == k or e.get("id", "").lower() == k):
            return fp
    return ""


def find_seen(key: str) -> dict | None:
    d = load()
    fp = _find_seen(d, key)
    return {**d["seen"][fp], "fp": fp} if fp else None


def was_enabled_here(fp: str) -> bool:
    """A machine this one set up: its request to join is let in at once (pool.py)."""
    return fp in load()["enabled"]


# ---- the network -------------------------------------------------------------------------

def broadcast_addresses() -> list[str]:
    """Where a broadcast goes: the limited broadcast, plus each interface's own (a router
    may drop 255.255.255.255 where it carries 192.168.1.255). Read with the SIOCGIFBRDADDR
    ioctl, so there is no `ip` to depend on. `AGENTOS_DISCOVER_TARGETS` (comma-separated)
    replaces the list, for a network that drops broadcasts between its parts: name each
    part's broadcast address, or the machines themselves."""
    env = [a.strip() for a in os.environ.get("AGENTOS_DISCOVER_TARGETS", "").split(",") if a.strip()]
    if env:
        return env
    out = ["255.255.255.255"]
    try:
        import fcntl
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for _, name in socket.if_nameindex():
                try:
                    r = fcntl.ioctl(s.fileno(), 0x8919, struct.pack("256s", name[:15].encode()))
                    a = socket.inet_ntoa(r[20:24])
                    if a not in ("0.0.0.0",) and a not in out:
                        out.append(a)
                except OSError:
                    pass
        finally:
            s.close()
    except Exception:
        pass
    return out


def _udp_socket(bind_port: int | None = None) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setblocking(False)
    s.bind(("0.0.0.0", bind_port or 0))
    return s


def _send_all(sock: socket.socket, msg: dict, targets: list[str] | None = None) -> None:
    raw = json.dumps(msg).encode()
    for a in (targets or broadcast_addresses()):
        try:
            sock.sendto(raw, (a, udp_port()))
        except OSError:
            pass


class _UDP(asyncio.DatagramProtocol):
    def __init__(self, on, root=None):
        self.on = on
        self.root = root
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if len(data) > BEACON_MAX:
            return
        try:
            msg = json.loads(data)
        except Exception:
            return
        if isinstance(msg, dict) and msg.get("m") == MAGIC:
            from . import teamlink
            tok = teamlink._ROOT.set(self.root) if self.root else None
            try:
                self.on(msg, addr)
            except Exception:
                pass
            finally:
                if tok is not None:
                    teamlink._ROOT.reset(tok)


def _server_ctx() -> ssl.SSLContext:
    """The claim door: this machine's own certificate, no client certificate asked for.
    The leader pins this certificate's fingerprint from the beacon; the claim's proof
    binds both fingerprints."""
    from . import teamlink
    ident = teamlink.ensure_pki()
    ctx = teamlink._SSLContext(ssl.PROTOCOL_TLS_SERVER)
    teamlink._set(ctx, "minimum_version", ssl.TLSVersion.TLSv1_2)
    ctx.load_cert_chain(ident["host_crt"], ident["host_key"])
    teamlink._set(ctx, "verify_mode", ssl.CERT_NONE)
    return ctx


def _client_ctx() -> ssl.SSLContext:
    from . import teamlink
    ctx = teamlink._SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    teamlink._set(ctx, "minimum_version", ssl.TLSVersion.TLSv1_2)
    ctx.check_hostname = False
    teamlink._set(ctx, "verify_mode", ssl.CERT_NONE)
    return ctx


class Door:
    """A waiting machine's side: announcements, answers to "who is there?", and the claim
    door. `cfg` is a callable returning the machine config; `on_claimed(reply)` runs after
    a claim was taken and answered (the server starts its link door and joins)."""

    def __init__(self, cfg, on_claimed=None, audit=None):
        from . import teamlink
        self.root = teamlink.home()     # whose machine this is, pinned into every callback
        self.cfg = cfg
        self.on_claimed = on_claimed
        self.audit = audit or (lambda *a: None)
        self.udp = None
        self.tcp = None
        self.started = 0.0
        self._task = None
        self._nonces: dict = {}
        self._replies: dict = {}

    async def start(self):
        loop = asyncio.get_running_loop()
        self.udp, _ = await loop.create_datagram_endpoint(lambda: _UDP(self._datagram, self.root),
                                                          sock=_udp_socket(udp_port()))
        self.tcp = await asyncio.start_server(self._handle, "0.0.0.0", tcp_port(self.cfg()),
                                              ssl=_server_ctx(), limit=64 * 1024)
        self.started = time.time()
        self._task = asyncio.create_task(self._announce_loop())
        return self

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
        if self.udp:
            self.udp.close()
            self.udp = None
        if self.tcp:
            self.tcp.close()
            await self.tcp.wait_closed()
            self.tcp = None

    def announce(self):
        if self.udp:
            msg = here(self.cfg())
            msg["op"] = "announce"
            raw = json.dumps(msg).encode()
            for a in broadcast_addresses():
                try:
                    self.udp.sendto(raw, (a, udp_port()))
                except OSError:
                    pass

    async def _announce_loop(self):
        while True:
            if waiting(self.cfg())[0]:
                self.announce()
            fast = time.time() - self.started < ANNOUNCE_FAST_FOR
            await asyncio.sleep(ANNOUNCE_FAST_S if fast else ANNOUNCE_SLOW_S)

    def _datagram(self, msg, addr):
        if msg.get("op") != "look" or not waiting(self.cfg())[0]:
            return
        now = time.time()
        hits = [t for t in self._replies.get(addr[0], []) if t > now - 60]
        if len(hits) >= REPLIES_PER_MIN:
            return
        hits.append(now)
        self._replies[addr[0]] = hits
        out = here(self.cfg())
        out["nonce"] = str(msg.get("nonce") or "")[:32]
        try:
            self.udp.sendto(json.dumps(out).encode(), addr)
        except OSError:
            pass

    async def _handle(self, reader, writer):
        from . import teamlink
        teamlink._ROOT.set(self.root)    # this task is this machine, whatever started it
        addr = (writer.get_extra_info("peername") or ("?",))[0]
        try:
            for _ in range(2):            # hello, then claim: one connection, two lines
                req = await teamlink._read_line(reader, limit=64 * 1024, timeout=20)
                out = await self._dispatch(req, addr)
                writer.write((json.dumps(out) + "\n").encode())
                await writer.drain()
                if req.get("op") != "hello" or not out.get("ok"):
                    break
        except Exception:
            pass
        finally:
            writer.close()

    async def _dispatch(self, req: dict, addr: str) -> dict:
        cfg = self.cfg()
        if not waiting(cfg)[0]:
            return {"ok": False, "error": "this machine is not waiting to be set up"}
        op = req.get("op")
        if op == "hello":
            nonce = secrets.token_hex(16)
            now = time.time()
            self._nonces = {n: t for n, t in self._nonces.items() if t > now - NONCE_TTL}
            self._nonces[nonce] = now
            return {"ok": True, **here(cfg), "nonce": nonce}
        if op != "claim":
            return {"ok": False, "error": f"unknown request '{op}'"}
        nonce = str(req.get("nonce") or "")
        if nonce not in self._nonces:
            return {"ok": False, "error": "that claim is too old — start again"}
        self._nonces.pop(nonce, None)
        ok, err, secret = check_claim(req, nonce)
        leader = req.get("leader") or {}
        if not ok:
            self.audit("provision.refused", f"from {addr}: {err}")
            return {"ok": False, "error": err}
        got = apply_claim(cfg, req, addr)
        from . import teamlink
        ident = teamlink.ensure_pki()
        reply = {"ok": True, "name": teamlink.machine_name(cfg), "ca": ident["ca"],
                 "host_fp": ident["host_fp"], "port": teamlink.team_port(cfg), "hw": hardware()}
        if req.get("how") == "key":
            reply["proof_back"] = proof(secret, str(leader.get("host_fp")), ident["host_fp"],
                                        str(req.get("nonce2") or ""), side="member")
        self.audit("provision.claimed",
                   f"set up by {leader.get('name') or 'a leader'} at {addr} ({req.get('how')}); "
                   f"profile {json.dumps(got['profile'])}")
        if self.on_claimed:
            asyncio.get_running_loop().call_later(0.5, lambda: asyncio.ensure_future(self.on_claimed(got)))
        return reply


class Watch:
    """The listening side: announcements from new machines, and scans."""

    def __init__(self, on_new=None):
        from . import teamlink
        self.root = teamlink.home()
        self.on_new = on_new
        self.udp = None

    async def start(self):
        loop = asyncio.get_running_loop()
        self.udp, _ = await loop.create_datagram_endpoint(lambda: _UDP(self._datagram, self.root),
                                                          sock=_udp_socket(udp_port()))
        return self

    async def stop(self):
        if self.udp:
            self.udp.close()
            self.udp = None

    def _datagram(self, msg, addr):
        if msg.get("op") not in ("announce", "here"):
            return
        b = clean_beacon(msg, addr[0])
        if not b or b["fp"] == _my_fp():
            return
        if note_seen(b) and self.on_new:
            asyncio.ensure_future(self.on_new(b))


async def scan(wait: float = 2.0, targets: list[str] | None = None) -> list[dict]:
    """Ask the network who is waiting, and wait `wait` seconds for answers. What answers is
    remembered (note_seen), so the list in Settings fills from a scan as from announcements."""
    loop = asyncio.get_running_loop()
    got: dict = {}
    nonce = secrets.token_hex(8)

    def on(msg, addr):
        if msg.get("op") == "here" and msg.get("nonce") == nonce:
            b = clean_beacon(msg, addr[0])
            if b:
                got[b["fp"]] = b

    tr, _ = await loop.create_datagram_endpoint(lambda: _UDP(on), sock=_udp_socket(None))
    try:
        raw = json.dumps({"m": MAGIC, "op": "look", "nonce": nonce}).encode()
        for _ in range(2):                 # UDP drops: say it twice
            for a in (targets or broadcast_addresses()):
                try:
                    tr.sendto(raw, (a, udp_port()))
                except OSError:
                    pass
            await asyncio.sleep(wait / 2)
    finally:
        tr.close()
    mine = _my_fp()
    out = [b for b in got.values() if b["fp"] != mine]
    for b in out:
        note_seen(b)
    return out


async def enable(cfg: dict, target: dict, profile: dict | None = None, code: str = "",
                 pool_info: dict | None = None, timeout: float = 20) -> dict:
    """Set up one waiting machine from here. `target` is a seen entry (addr, port, fp).
    Proves the claim with this machine's enrolment key when the target carries one, else
    with `code`. Writes this side's link to it and records it as set up here, so its
    request to join is let in at once. Raises ValueError with the sentence to show."""
    from . import teamlink
    ident = teamlink.ensure_pki()
    addr, port, fp = target.get("addr"), int(target.get("port") or 0), target.get("fp")
    if not (addr and port and fp):
        raise ValueError("that machine has not said where it can be reached — look again")
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            addr, port, ssl=_client_ctx(), server_hostname=teamlink.SNI, limit=64 * 1024), timeout)
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as e:
        raise ValueError(f"could not reach {target.get('name') or addr} at {addr}:{port} ({type(e).__name__})")
    try:
        if teamlink._peer_fp(writer) != fp:
            raise ValueError("a different machine answered at that address than the one that was "
                             "heard — refused")

        async def say(msg):
            writer.write((json.dumps(msg) + "\n").encode())
            await writer.drain()
            return await teamlink._read_line(reader, limit=64 * 1024, timeout=timeout)

        hello = await say({"op": "hello"})
        if not hello.get("ok"):
            raise ValueError(hello.get("error") or "it did not answer")
        nonce = str(hello.get("nonce") or "")
        d = load()
        key = next((k for k in d["keys"] if k["id"] == hello.get("key_id")), None)
        nonce2 = secrets.token_hex(16)
        if key:
            how, secret = "key", key["secret"]
            prof = clean_profile({**(key.get("profile") or {}), **(profile or {})})
        else:
            code = re.sub(r"\D", "", str(code or ""))
            if len(code) != 6:
                raise ValueError(f"{target.get('name') or 'that machine'} shows a six-digit code on its "
                                 f"screen (or `bento pool wait` there) — type it in")
            how, secret, prof = "code", code, clean_profile(profile or {})
        out = await say({"op": "claim", "nonce": nonce, "nonce2": nonce2, "how": how,
                         "key_id": key["id"] if key else "",
                         "proof": proof(secret, ident["host_fp"], fp, nonce),
                         "leader": {"name": teamlink.machine_name(cfg), "ca": ident["ca"],
                                    "host_fp": ident["host_fp"], "port": teamlink.team_port(cfg)},
                         "pool": pool_info or {}, "profile": prof})
    finally:
        writer.close()
    if not out.get("ok"):
        raise ValueError(out.get("error") or "it refused")
    if out.get("host_fp") != fp or not str(out.get("ca") or "").startswith("-----BEGIN CERTIFICATE"):
        raise ValueError("it answered with a different certificate — refused")
    if key and not hmac.compare_digest(str(out.get("proof_back") or ""),
                                       proof(secret, ident["host_fp"], fp, nonce2, side="member")):
        raise ValueError("it does not really hold the enrolment key — refused")
    td = teamlink._load()
    td["links"] = [lk for lk in td["links"] if lk.get("peer_host_fp") != fp]
    name = teamlink._label(out.get("name") or target.get("name") or "machine")
    lk = teamlink._add_link(td, kind="machine", owner="", label=name, peer_ca=out["ca"], peer_host_fp=fp,
                            peer_name=name, url=f"{addr}:{teamlink._port(out.get('port'))}",
                            direction="set up from here")
    teamlink._save(td)
    d = load()
    d["enabled"][fp] = {"name": name, "at": time.time(), "how": how}
    if key and key.get("single"):
        # a key made for one machine (an SSH install, one SD card) is spent on it
        d["keys"] = [k for k in d["keys"] if k["id"] != key["id"]]
    if fp in d["seen"]:
        d["seen"][fp].update(state="enabled", name=name)
    save(d)
    return {"ok": True, "name": name, "label": lk["label"], "how": how, "profile": prof,
            "hw": out.get("hw") or {}}
