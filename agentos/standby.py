"""Cloud standby: your agent runs on your machine, and a cloud machine takes over only
while yours cannot be reached.

Two Bentos are paired. The MAIN machine (the person's) does the work and sends the
STANDBY (a cloud box) a heartbeat every half minute and a sealed copy of its whole home
when something changed (`backup.create`, so the copy is the same encrypted file a backup
is). The standby does nothing with it: no scheduler, no Telegram, no missions, a page that
says who it is standing by for. When the heartbeat has been missing for `grace` seconds it
takes over: the newest copy is staged and checked, and on the next start it is swapped in
(`backup.apply_pending`), so your missions, channels and chats carry on from the cloud.
When your machine is back, it asks for its work back before it starts anything: the
standby hands over a fresh copy of what it did, goes quiet again, and your machine swaps
that copy in. That is the whole bargain, and every piece of it is a file somebody can read.

Rules that keep it honest (docs/standby.md, tests/test_standby.py):

  * ONE side acts at a time. A passive side starts none of the runners that act on
    somebody's behalf; the state file says which side is active and the epoch counts
    every change of hands.
  * The copy is sealed end to end with a secret only the two machines hold, so the
    transport is not what protects it. Pairing still wants HTTPS off a private network,
    because the bearer token travels in it.
  * Nothing is thrown away. A swap moves what was there aside (backup.py's rule); the
    standby's own automatic swaps keep the newest `KEEP_ASIDE`, because every one of them
    is also held by the other machine.
  * If BOTH sides worked while they could not reach each other, neither copy is merged
    into the other: your machine keeps its own, the cloud's is saved beside it, and the
    person is told how to switch to it (`adopt`).
  * The machine's own door (`LOCAL_KEYS`: remote access, port) never travels. The cloud
    keeps the lock that made it reachable, and your machine keeps its own.

Kept free of HTTP routes and asyncio: `bento standby` pairs, reads and acts with the
server down. The server's loops call these functions in a thread.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

DIR = ".standby"                   # starts with a PRIVATE prefix of backup.py: never copied or moved
STATE = "state.json"
OFFER = "offer.json"
DOOR = "door.json"
LATEST = "latest.bento"
PREVIOUS = "previous.bento"
OUTGOING = "outgoing.bento"
BEAT_S = 30                        # heartbeat
PUSH_S = 600                       # a copy at most this often, and only when something changed
GRACE_S = 300                      # silence before the standby takes over
MIN_GRACE = 90                     # a laptop's Wi-Fi reconnecting is not a failure
MAX_GRACE = 24 * 3600
CODE_TTL = 600
CODE_TRIES = 5
KEEP_ASIDE = 2
WORKSPACE_CAP = 1 << 30            # a workspace over 1 GB is left out of the copies, and said
LOCAL_KEYS = ("remote", "port")    # the machine's own door, never carried
BAD_LIMIT = 20                     # wrong tokens per address per window
BAD_WINDOW = 600
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class StandbyError(Exception):
    """Something the person can act on, in a sentence."""


# ---- where and what -----------------------------------------------------------------

def _home(home=None) -> Path:
    if home:
        return Path(home)
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME)


def _dir(home=None) -> Path:
    d = _home(home) / DIR
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def _write(p: Path, data: dict) -> None:
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def load(home=None) -> dict:
    return _read(_home(home) / DIR / STATE)


def save(st: dict, home=None) -> None:
    _write(_dir(home) / STATE, st)


def _update(home=None, **kw) -> dict:
    st = load(home)
    st.update(kw)
    save(st, home)
    return st


_PASSIVE_CACHE: dict = {}


def switching(home=None) -> bool:
    """A swap is staged and not yet in: the home here is about to be replaced."""
    from . import backup as bk
    return (_home(home) / bk.READY).exists()


def passive(home=None) -> bool:
    """Is this side paired and NOT the one acting, or about to swap its home? Read per
    request by the server's gate, so the state file is cached on its mtime.

    A staged swap counts: a takeover writes "active" and THEN restarts to swap the
    copy in, and for that second the cloud answered as you from its own empty home
    (found by the end-to-end run, which read that home). A request in that window
    could read or write a home that is about to be moved aside."""
    if switching(home) and load(home).get("role"):
        return True
    p = _home(home) / DIR / STATE
    try:
        m = p.stat().st_mtime_ns
    except OSError:
        return False
    key = str(p)
    hit = _PASSIVE_CACHE.get(key)
    if hit and hit[0] == m:
        return hit[1]
    st = _read(p)
    val = bool(st.get("role")) and not st.get("active")
    _PASSIVE_CACHE[key] = (m, val)
    return val


def role(home=None) -> str:
    return load(home).get("role", "")


def _host() -> str:
    return platform.node().split(".")[0] or "this machine"


def _version() -> str:
    try:
        return (Path(__file__).parent / "VERSION").read_text().strip()
    except OSError:
        return ""


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---- pairing ------------------------------------------------------------------------

def _code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]


def _norm_code(code: str) -> str:
    return "".join(c for c in (code or "").upper() if c.isalnum())


def offer(home=None) -> dict:
    """On the machine that will stand by: a one-time code the main machine pairs with.
    Single use, ten minutes, five tries, stored hashed."""
    st = load(home)
    if st.get("role") == "primary":
        raise StandbyError("This machine is paired as the main machine. Unpair it first "
                           "(bento standby off) to make it a standby.")
    if st.get("role") == "standby":
        raise StandbyError(f"This machine is already standing by for {st.get('peer_host') or 'a machine'}. "
                           "Unpair it first (bento standby off).")
    code = _code()
    _write(_dir(home) / OFFER, {"hash": _hash(_norm_code(code)), "until": time.time() + CODE_TTL,
                                "tries": 0})
    return {"code": code, "until": time.time() + CODE_TTL, "host": _host()}


def accept(body: dict, home=None) -> dict:
    """The standby's half of pairing: the main machine presents the code and hands over
    the token it will be known by and the secret its copies are sealed with."""
    p = _home(home) / DIR / OFFER
    off = _read(p)
    if not off:
        raise StandbyError("This machine is not waiting to be paired. Run `bento standby wait` "
                           "on it (or Settings → System → Cloud standby) for a code.")
    if time.time() > off.get("until", 0):
        p.unlink(missing_ok=True)
        raise StandbyError("That code has expired. Make a new one on the cloud machine.")
    off["tries"] = off.get("tries", 0) + 1
    if not hmac.compare_digest(_hash(_norm_code(body.get("code", ""))), off.get("hash", "")):
        if off["tries"] >= CODE_TRIES:
            p.unlink(missing_ok=True)
            raise StandbyError("Too many wrong codes. Make a new one on the cloud machine.")
        _write(p, off)
        raise StandbyError("That code is not right.")
    token, secret = str(body.get("token", "")), str(body.get("secret", ""))
    if len(token) < 32 or len(secret) < 32:
        raise StandbyError("The pairing request was incomplete.")
    p.unlink(missing_ok=True)
    save({"role": "standby", "active": False, "epoch": 0, "token_hash": _hash(token),
          "secret": secret, "peer_host": _clean(body.get("host", ""), 64) or "your machine",
          "peer_version": _clean(body.get("version", ""), 24), "paired_at": time.time(),
          "grace": GRACE_S, "auto": True, "last_beat": 0, "holds_work": False}, home)
    return {"ok": True, "host": _host(), "version": _version()}


def _clean(s, n: int) -> str:
    return "".join(c for c in str(s or "") if c.isprintable())[:n]


def token_ok(presented: str, home=None) -> bool:
    st = load(home)
    want = st.get("token_hash", "")
    if st.get("role") != "standby" or not want or not presented:
        return False
    return hmac.compare_digest(_hash(presented), want)


_BAD: dict[str, list] = {}


def too_many_bad(addr: str) -> bool:
    now = time.time()
    hits = [t for t in _BAD.get(addr, []) if now - t < BAD_WINDOW]
    _BAD[addr] = hits
    return len(hits) >= BAD_LIMIT


def note_bad(addr: str) -> None:
    _BAD.setdefault(addr, []).append(time.time())


def url_problem(url: str) -> str:
    """The standby's address must be HTTPS unless it is on a private network: the bearer
    token and the pairing secret travel in these requests."""
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return "Give the cloud machine's address, like https://bento.example.com."
    if u.scheme == "https":
        return ""
    h = u.hostname
    if h == "localhost" or h.endswith((".local", ".lan", ".internal", ".ts.net", ".home.arpa")):
        return ""
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_private or ip.is_loopback or ip.is_link_local or \
                ip in ipaddress.ip_network("100.64.0.0/10"):
            return ""
    except ValueError:
        pass
    return ("Use https:// for a machine on the internet. Plain http is only for a private "
            "network such as your LAN or Tailscale.")


def _client(timeout: float = 20.0):
    import httpx
    return httpx.Client(timeout=timeout, follow_redirects=False)


def _call(st: dict, method: str, path: str, *, timeout: float = 20.0, **kw):
    """One request to the paired standby, as the main machine."""
    import httpx
    url = st["url"].rstrip("/") + "/api/standby/peer/" + path
    try:
        with _client(timeout) as c:
            r = c.request(method, url, headers={"Authorization": f"Bearer {st['token']}"}, **kw)
    except httpx.HTTPError as e:
        raise StandbyError(f"Could not reach {st.get('peer_host') or st['url']}: {type(e).__name__}.")
    if r.status_code == 401:
        raise StandbyError("The cloud machine no longer knows this one. Pair them again.")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", "")
        except ValueError:
            msg = ""
        raise StandbyError(msg or f"The cloud machine answered {r.status_code}.")
    return r


def pair(url: str, code: str, home=None) -> dict:
    """The main machine's half: mint the token and the secret, present the code."""
    import httpx
    st = load(home)
    if st.get("role"):
        raise StandbyError("This machine is already paired. Unpair it first (bento standby off).")
    if (why := url_problem(url)):
        raise StandbyError(why)
    token, secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    base = url.strip().rstrip("/")
    try:
        with _client(20) as c:
            r = c.post(base + "/api/standby/peer/pair",
                       json={"code": code, "token": token, "secret": secret,
                             "host": _host(), "version": _version()})
    except httpx.HTTPError as e:
        raise StandbyError(f"Could not reach {base}: {type(e).__name__}.")
    try:
        ans = r.json()
    except ValueError:
        ans = {}
    if r.status_code != 200 or not ans.get("ok"):
        raise StandbyError(ans.get("error") or f"{base} answered {r.status_code}; is it a Bento?")
    st = {"role": "primary", "active": True, "epoch": 0, "url": base, "token": token,
          "secret": secret, "peer_host": _display_host(ans.get("host", ""), base),
          "peer_version": _clean(ans.get("version", ""), 24), "paired_at": time.time(),
          "interval": BEAT_S, "push_every": PUSH_S, "workspace": True,
          "last_contact": time.time(), "last_attempt": time.time(), "last_push": 0,
          "last_fp": "", "last_error": ""}
    save(st, home)
    return status(home)


def _display_host(host: str, url: str) -> str:
    """What to call the cloud on screen. A container's hostname is its id (twelve hex
    characters, `993d597ede9b` in the test run), which names nothing a person
    recognises; the address they paired with does."""
    host = _clean(host, 64)
    if not host or re.fullmatch(r"[0-9a-f]{12}", host):
        return urlparse(url).hostname or "the cloud"
    return host


def unpair(home=None) -> dict:
    """Forget the pairing on this side (and tell the other side when it answers)."""
    st = load(home)
    told = False
    if st.get("role") == "primary":
        try:
            _call(st, "POST", "unpair", timeout=8)
            told = True
        except StandbyError:
            pass
    d = _home(home) / DIR
    for n in (STATE, OFFER, LATEST, PREVIOUS, OUTGOING, DOOR):
        (d / n).unlink(missing_ok=True)
    _PASSIVE_CACHE.clear()
    return {"ok": True, "was": st.get("role", ""), "told": told}


def forget_peer(home=None) -> None:
    """The main machine unpaired; the standby lets go of its copies too."""
    unpair(home)


# ---- the copy -----------------------------------------------------------------------

def fingerprint(home=None, workspace: bool = True) -> str:
    """Has anything worth copying changed? Size and mtime of every file a backup would
    hold, plus each database's write-ahead log (a change sits there until a checkpoint)."""
    from . import backup as bk
    home = _home(home)
    h = hashlib.sha256()
    for rel, p in bk._walk(home):
        try:
            s = p.stat()
            h.update(f"{rel}\0{s.st_size}\0{s.st_mtime_ns}\n".encode())
            if rel.endswith(".db"):
                w = p.with_name(p.name + "-wal")
                if w.exists():
                    ws = w.stat()
                    h.update(f"{rel}-wal\0{ws.st_size}\0{ws.st_mtime_ns}\n".encode())
        except OSError:
            continue
    if workspace:
        ws_root = bk._workspace(home)
        if ws_root:
            for rel, p in bk._walk_plain(ws_root):
                try:
                    s = p.stat()
                    h.update(f"ws/{rel}\0{s.st_size}\0{s.st_mtime_ns}\n".encode())
                except OSError:
                    continue
    return h.hexdigest()


def _with_workspace(st: dict, home) -> tuple[bool, str]:
    if not st.get("workspace", True):
        return False, "Your workspace folder is left out of the copies (your choice)."
    from . import backup as bk
    try:
        p = bk.plan(home, True)
    except Exception:
        return True, ""
    if p.get("workspace_bytes", 0) > WORKSPACE_CAP:
        return False, (f"Your workspace is over {WORKSPACE_CAP >> 30} GB, so it is left out of the "
                       "copies. Files your agents make there stay on this machine.")
    return True, ""


def push(home=None, force: bool = False) -> dict:
    """Make a sealed copy of this home and send it to the standby, when something changed
    (or `force`). Returns what happened, in the state it also records."""
    from . import backup as bk
    home = _home(home)
    st = load(home)
    if st.get("role") != "primary" or not st.get("active"):
        raise StandbyError("Only the main machine, while it is the one working, sends copies.")
    ws, note = _with_workspace(st, home)
    fp = fingerprint(home, ws)
    if not force and fp == st.get("last_fp") and st.get("last_push"):
        return {"sent": False, "why": "nothing changed"}
    out = _dir(home) / f".backup-out-standby-{os.getpid()}.bento"
    t0 = time.time()
    try:
        m = bk.create(out, st["secret"], home=home, workspace=ws)
        size = out.stat().st_size
        with open(out, "rb") as f:
            r = _push_file(st, f)
        ans = r.json()
    finally:
        out.unlink(missing_ok=True)
    if ans.get("active") or ans.get("holds_work"):
        return {"sent": False, "why": "the cloud is the one working", "peer": ans}
    rec = {"last_push": time.time(), "last_fp": fp, "last_push_bytes": size,
           "last_push_s": round(time.time() - t0, 1), "workspace_note": note,
           "last_push_files": m.get("files", 0), "last_error": ""}
    _update(home, **rec)
    return {"sent": True, "bytes": size, "seconds": rec["last_push_s"]}


def _chunks(f):
    while True:
        b = f.read(1 << 20)
        if not b:
            return
        yield b


def _push_file(st: dict, f):
    import httpx
    url = st["url"].rstrip("/") + "/api/standby/peer/push"
    try:
        with _client(600) as c:
            r = c.post(url, content=_chunks(f),
                       headers={"Authorization": f"Bearer {st['token']}",
                                "Content-Type": "application/octet-stream"})
    except httpx.HTTPError as e:
        raise StandbyError(f"Could not send the copy to {st.get('peer_host')}: {type(e).__name__}.")
    if r.status_code == 401:
        raise StandbyError("The cloud machine no longer knows this one. Pair them again.")
    if r.status_code >= 400 and r.status_code != 409:
        try:
            msg = r.json().get("error", "")
        except ValueError:
            msg = ""
        raise StandbyError(msg or f"The cloud machine refused the copy ({r.status_code}).")
    return r


def receive(chunks, home=None) -> dict:
    """The standby's half of a copy: written beside itself, checked in full with the
    shared secret, then made the newest (the one before it is kept as a fallback)."""
    from . import backup as bk
    st = load(home)
    if st.get("role") != "standby":
        raise StandbyError("This machine is not a standby.")
    if st.get("active") or st.get("holds_work"):
        return {"ok": False, "active": bool(st.get("active")), "holds_work": True}
    d = _dir(home)
    part = d / ".incoming.part"
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    size = 0
    try:
        with os.fdopen(fd, "wb") as w:
            for b in chunks:
                size += len(b)
                w.write(b)
        m = bk.verify(part, st["secret"])
    except bk.BackupError as e:
        part.unlink(missing_ok=True)
        raise StandbyError(f"The copy did not check out: {e}")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if (d / LATEST).exists():
        os.replace(d / LATEST, d / PREVIOUS)
    os.replace(part, d / LATEST)
    _update(home, copy_at=time.time(), copy_bytes=size, copy_created=m.get("created", 0),
            copy_engine=m.get("engine", ""), copy_model=m.get("default_model", ""),
            copy_accounts=len(m.get("accounts", [])), copy_telegram=bool(m.get("telegram")),
            copy_whatsapp=bool(m.get("whatsapp_linked")), copy_version=m.get("version", ""),
            copy_workspace=bool(m.get("workspace_included")))
    return {"ok": True, "bytes": size, "active": False}


# ---- heartbeat ----------------------------------------------------------------------

def beat(home=None) -> dict:
    """The main machine says it is here. Returns the standby's answer."""
    st = load(home)
    now = time.time()
    _update(home, last_attempt=now)
    try:
        r = _call(st, "POST", "beat", timeout=10,
                  json={"epoch": st.get("epoch", 0), "host": _host(), "version": _version(), "at": now})
    except StandbyError as e:
        # the other side restarts for a few seconds after every hand-over; a miss then
        # is expected, and a red line in Settings for it would be a false alarm
        if time.time() - max(st.get("came_back", 0), st.get("moved_at", 0), st.get("paired_at", 0)) > 60:
            _update(home, last_error=str(e))
        raise
    ans = r.json()
    rec = {"last_error": "", "peer_version": _clean(ans.get("version", ""), 24),
           "peer_copy_at": ans.get("copy_at", 0)}
    # `last_contact` means the last time the standby was heard QUIET. A beat that finds it
    # working must not move it: `come_back` asks what this machine did since then, and
    # stamping it now would make that window empty and hand the cloud's copy over ours.
    if not (ans.get("active") or ans.get("holds_work")):
        rec["last_contact"] = time.time()
    _update(home, **rec)
    return ans


def heard(body: dict, home=None) -> dict:
    """The standby's half of a heartbeat."""
    st = load(home)
    if not st.get("active") and not st.get("holds_work"):
        st.update(last_beat=time.time(), peer_version=_clean(body.get("version", ""), 24),
                  peer_host=_clean(body.get("host", ""), 64) or st.get("peer_host", ""))
        save(st, home)
    return answer(home)


def answer(home=None) -> dict:
    st = load(home)
    return {"role": st.get("role", ""), "active": bool(st.get("active")),
            "holds_work": bool(st.get("holds_work")), "epoch": st.get("epoch", 0),
            "since": st.get("since", 0), "host": _host(), "version": _version(),
            "copy_at": st.get("copy_at", 0)}


def may_act(home=None) -> bool:
    """May the main machine's scheduler fire now? Not while it has been out of touch for
    longer than a few heartbeats (a laptop just woke up): the cloud may be the one
    working, and the next heartbeat, due within seconds, finds out. A cloud that cannot
    be reached does not hold anything up: the attempt itself is what is fresh."""
    st = load(home)
    if not st.get("role"):
        return True
    if not st.get("active"):
        return False
    if st.get("role") != "primary":
        return True
    return time.time() - st.get("last_attempt", 0) < 3 * st.get("interval", BEAT_S)


# ---- taking over (on the standby) ---------------------------------------------------

def due_takeover(home=None) -> str:
    """The sentence a takeover would be for, or '' while none is due."""
    st = load(home)
    if st.get("role") != "standby" or st.get("active") or st.get("holds_work"):
        return ""
    if not st.get("auto", True) or not st.get("last_beat"):
        return ""
    if not (_home(home) / DIR / LATEST).exists():
        return ""
    quiet = time.time() - st["last_beat"]
    if quiet < max(MIN_GRACE, st.get("grace", GRACE_S)):
        return ""
    return f"{st.get('peer_host') or 'Your machine'} has not been heard from for {int(quiet // 60)} minutes."


def takeover(reason: str, home=None) -> dict:
    """Stage the newest copy (the one before it if the newest will not open) and mark it
    to be swapped in at the next start. The caller restarts the server."""
    from . import backup as bk
    home = _home(home)
    st = load(home)
    if st.get("role") != "standby":
        raise StandbyError("This machine is not a standby.")
    if st.get("active"):
        raise StandbyError("This machine is already the one working.")
    d = _dir(home)
    last_err = "there is no copy yet"
    for name in (LATEST, PREVIOUS):
        f = d / name
        if not f.exists():
            continue
        try:
            m = bk.stage(f, st["secret"], home=home)
            break
        except bk.BackupError as e:
            last_err = str(e)
    else:
        raise StandbyError(f"Cannot take over: {last_err}.")
    keep_door(home)
    bk.mark_ready(m["staging"], home)
    st.update(active=True, holds_work=True, epoch=st.get("epoch", 0) + 1, since=time.time(),
              reason=reason, took_over=time.time(), copy_used=m.get("created", 0))
    save(st, home)
    return {"ok": True, "reason": reason, "copy_created": m.get("created", 0),
            "host": m.get("host", "")}


def release(home=None) -> dict:
    """The main machine wants its work back. This side stops being the one working and
    seals what it has into OUTGOING; the caller restarts the server (quiet), and the main
    machine fetches the file. Asked again before `done`, it answers with the same file."""
    from . import backup as bk
    home = _home(home)
    st = load(home)
    if st.get("role") != "standby" or not (st.get("active") or st.get("holds_work")):
        raise StandbyError("This machine is not holding any of your work.")
    if bk.pending(home):
        # a takeover is staged and not yet swapped in: the home here is not the work yet
        raise StandbyError("This machine is taking over right now. Ask again in a moment.")
    out = _dir(home) / OUTGOING
    if not st.get("active") and out.exists():
        return {"ok": True, "bytes": out.stat().st_size, "epoch": st.get("epoch", 0), "restart": False}
    st.update(active=False, holds_work=True, released_at=time.time())
    save(st, home)
    tmp = _dir(home) / f".backup-out-release-{os.getpid()}.bento"
    bk.create(tmp, st["secret"], home=home, workspace=True)
    os.replace(tmp, out)
    return {"ok": True, "bytes": out.stat().st_size, "epoch": st.get("epoch", 0), "restart": True}


def outgoing(home=None) -> Path | None:
    p = _home(home) / DIR / OUTGOING
    return p if p.exists() else None


def done(body: dict, home=None) -> dict:
    """The main machine has the work. Stand by again, heard from just now."""
    st = load(home)
    (_home(home) / DIR / OUTGOING).unlink(missing_ok=True)
    st.update(active=False, holds_work=False, epoch=max(int(body.get("epoch", 0) or 0), st.get("epoch", 0)),
              last_beat=time.time(), since=0, reason="")
    save(st, home)
    return {"ok": True}


def peer_takeover(body: dict, home=None) -> dict:
    """The main machine is handing over on purpose (`move`)."""
    st = load(home)
    who = st.get("peer_host") or "your machine"
    return takeover(f"{who} handed over to this machine.", home)


# ---- coming back (on the main machine) ----------------------------------------------

def worked_since(t: float, home=None) -> int:
    """How much this machine did after `t`: messages people sent, runs and scheduled
    firings, across every account's database. Read-only."""
    home = _home(home)
    dbs = [home / "agentos.db"] + sorted((home / "users").glob("*/agentos.db"))
    n = 0
    for db in dbs:
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            continue
        try:
            for q in ("SELECT COUNT(*) FROM messages WHERE role='user' AND created_at > ?",
                      "SELECT COUNT(*) FROM fabric_runs WHERE started_at > ?",
                      "SELECT COUNT(*) FROM task_runs WHERE started_at > ?"):
                try:
                    n += con.execute(q, (t,)).fetchone()[0] or 0
                except sqlite3.Error:
                    pass
        finally:
            con.close()
    return n


def _fetch(st: dict, dest: Path, wait: float = 120.0) -> int:
    """Download the standby's OUTGOING file. It restarts right after `release`, so this
    retries until it answers."""
    import httpx
    url = st["url"].rstrip("/") + "/api/standby/peer/outgoing"
    deadline = time.time() + wait
    last = ""
    while time.time() < deadline:
        try:
            with _client(600) as c, c.stream("GET", url, headers={"Authorization": f"Bearer {st['token']}"}) as r:
                if r.status_code == 200:
                    part = dest.with_name(dest.name + ".part")
                    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    size = 0
                    with os.fdopen(fd, "wb") as w:
                        for b in r.iter_bytes(1 << 20):
                            size += len(b)
                            w.write(b)
                    os.replace(part, dest)
                    return size
                last = f"it answered {r.status_code}"
        except httpx.HTTPError as e:
            last = type(e).__name__
        time.sleep(2)
    raise StandbyError(f"Could not fetch the work back from {st.get('peer_host')}: {last}.")


def come_back(home=None, echo=None, check_work: bool = True) -> dict:
    """The cloud is the one working (or holds work). Take it back:

      * nothing happened here since we lost touch → fetch the cloud's copy, stage it and
        mark it for the next start (`restart: True`);
      * this machine ALSO worked → keep ours, save the cloud's beside it, tell the person
        (`split`).

    Either way the standby is told it may stand by again."""
    from . import backup as bk
    home = _home(home)
    st = load(home)
    say = echo or (lambda m: None)
    if st.get("role") != "primary":
        raise StandbyError("Only the main machine brings work back.")
    since = st.get("last_contact", 0)
    # a machine that handed over on purpose did nothing meanwhile: the cloud's copy wins
    worked = worked_since(since, home) if check_work and not st.get("moved") else 0
    say(f"  ▲ {st.get('peer_host')} has been working for you. Bringing the work back…")
    r = _call(st, "POST", "release", timeout=600).json()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = _dir(home) / (f"cloud-{stamp}.bento" if worked else f"back-{stamp}.bento")
    size = _fetch(st, dest)
    epoch = int(r.get("epoch", 0) or 0) + 1
    if worked:
        _call(st, "POST", "done", json={"epoch": epoch}, timeout=15)
        st = _update(home, active=True, moved=False, epoch=epoch, last_contact=time.time(),
                     split={"path": str(dest), "at": time.time(), "bytes": size, "worked": worked,
                            "host": st.get("peer_host", "")})
        return {"ok": True, "split": True, "path": str(dest), "restart": False,
                "message": (f"This machine and {st.get('peer_host')} both worked while they could not "
                            f"reach each other. This machine kept its own. The cloud's work is saved "
                            f"and one click away (Settings → System → Cloud standby, or "
                            f"`bento standby adopt`).")}
    try:
        m = bk.stage(dest, st["secret"], home=home)
    except bk.BackupError as e:
        raise StandbyError(f"The work from {st.get('peer_host')} did not check out: {e}. It is "
                           f"kept at {dest}, and the cloud still holds it.")
    keep_door(home)
    bk.mark_ready(m["staging"], home)
    _call(st, "POST", "done", json={"epoch": epoch}, timeout=15)
    dest.unlink(missing_ok=True)
    _update(home, active=True, moved=False, epoch=epoch, last_contact=time.time(),
            last_attempt=time.time(), came_back=time.time(), last_fp="")
    return {"ok": True, "split": False, "restart": True,
            "message": f"The work {st.get('peer_host')} did is back on this machine."}


def adopt(home=None) -> dict:
    """After a split: switch to the cloud's copy. What is here now is moved aside."""
    from . import backup as bk
    home = _home(home)
    st = load(home)
    sp = st.get("split") or {}
    p = Path(sp.get("path", ""))
    if not sp or not p.exists():
        raise StandbyError("There is no copy from the cloud waiting.")
    m = bk.stage(p, st["secret"], home=home)
    keep_door(home)
    bk.mark_ready(m["staging"], home)
    st.pop("split", None)
    st["last_fp"] = ""
    save(st, home)
    p.unlink(missing_ok=True)
    return {"ok": True, "restart": True}


def dismiss_split(home=None) -> dict:
    """Keep this machine's work; the cloud's copy is deleted."""
    st = load(home)
    sp = st.pop("split", None) or {}
    if sp.get("path"):
        Path(sp["path"]).unlink(missing_ok=True)
    save(st, home)
    return {"ok": True}


def move(home=None) -> dict:
    """Hand over to the cloud on purpose: a fresh copy, the standby takes it, and this
    machine stands down until `back`. The caller restarts the server (quiet)."""
    st = load(home)
    if st.get("role") != "primary" or not st.get("active"):
        raise StandbyError("Only the main machine, while it is working, can hand over.")
    push(home, force=True)
    _call(st, "POST", "takeover", json={"epoch": st.get("epoch", 0)}, timeout=600)
    _update(home, active=False, moved=True, moved_at=time.time())
    return {"ok": True, "restart": True, "url": st["url"]}


def back(home=None, echo=None) -> dict:
    """Bring it back after `move` (or whenever the cloud holds the work)."""
    st = load(home)
    if st.get("role") != "primary":
        raise StandbyError("Only the main machine brings work back.")
    ans = _call(st, "GET", "state", timeout=10).json()
    if not (ans.get("active") or ans.get("holds_work")):
        _update(home, active=True, moved=False, last_contact=time.time())
        return {"ok": True, "restart": True, "message": "Nothing was waiting in the cloud."}
    return come_back(home, echo, check_work=not st.get("moved"))


def boot(home=None, echo=print) -> dict:
    """Called by `serve` before the home opens, on the main machine: if the cloud took
    over while this machine was off, bring the work back before anything starts."""
    st = load(home)
    if st.get("role") != "primary" or not st.get("active"):
        return {}
    try:
        ans = _call(st, "GET", "state", timeout=5).json()
    except StandbyError as e:
        _update(home, last_attempt=time.time(), last_error=str(e))
        return {}
    _update(home, last_attempt=time.time())
    if not (ans.get("active") or ans.get("holds_work")):
        _update(home, last_contact=time.time())
        return {}
    r = come_back(home, echo)
    if echo:
        echo(f"  {r['message']}")
    return r


# ---- the machine's own door ---------------------------------------------------------

def keep_door(home=None) -> None:
    """Before a swap: remember this machine's own door, so the copy's does not replace it."""
    cfg = _read(_home(home) / "config.json")
    _write(_dir(home) / DOOR, {k: cfg[k] for k in LOCAL_KEYS if k in cfg})


def after_swap(report: dict, home=None) -> dict:
    """After `backup.apply_pending`, when a standby swap caused it: put this machine's
    door back and keep only the newest automatic asides."""
    home = _home(home)
    door_p = home / DIR / DOOR
    if not door_p.exists():
        return {}
    door = _read(door_p)
    cp = home / "config.json"
    cfg = _read(cp)
    for k in LOCAL_KEYS:
        if k in door:
            cfg[k] = door[k]
        else:
            cfg.pop(k, None)
    if cfg:
        _write(cp, cfg)
    door_p.unlink(missing_ok=True)
    st = load(home)
    swaps = [w for w in st.get("asides", []) if isinstance(w, list)]
    this = [a for a in (report.get("previous"), report.get("workspace_previous")) if a]
    if this:
        swaps.append(this)
    for old in swaps[:-KEEP_ASIDE]:
        for a in old:
            shutil.rmtree(a, ignore_errors=True)
    keep = swaps[-KEEP_ASIDE:]
    # the one-machine-answers warnings are this module's job, and the asides are pruned
    skip = ("Telegram:", "WhatsApp:", "Linked teams", "What was here before", "Your workspace is back")
    notes = [n for n in report.get("attention", []) if not n.startswith(skip)]
    st.update(asides=keep, last_swap={"at": time.time(),
                                      "from": st.get("peer_host") or report.get("from_host", ""),
                                      "notes": notes[:6]})
    save(st, home)
    return st["last_swap"]


# ---- what the person reads ----------------------------------------------------------

def carry_notes(st: dict) -> list[str]:
    """What a takeover will NOT bring along, from the newest copy's manifest."""
    notes = []
    eng = st.get("copy_engine", "")
    if eng and eng != "aria":
        from . import executors as ex
        try:
            here = bool(ex.probe(eng).get("installed"))
        except Exception:
            here = False
        if not here:
            notes.append(f"Your machine answers with {eng}, which is not installed here. The cloud "
                         "would answer with an AI provider key from your settings instead.")
        else:
            notes.append(f"{eng} is installed here but signs in separately. Sign it in on this "
                         "machine once so a takeover can use it.")
    model = st.get("copy_model", "")
    if model.startswith(("ollama/", "lmstudio/", "local/")):
        notes.append(f"Your model {model} runs on your machine. Pick a cloud model for when "
                     "this one is working.")
    if st.get("copy_whatsapp"):
        notes.append("A WhatsApp link may ask to be scanned again from a new address.")
    return notes


def status(home=None) -> dict:
    """Everything the Settings pane, the standby page and `bento standby` show. No token,
    no secret."""
    st = load(home)
    home_p = _home(home)
    now = time.time()
    out = {"role": st.get("role", ""), "active": bool(st.get("active")), "epoch": st.get("epoch", 0),
           "peer_host": st.get("peer_host", ""), "peer_version": st.get("peer_version", ""),
           "version": _version(), "host": _host(), "paired_at": st.get("paired_at", 0), "now": now}
    off = _read(home_p / DIR / OFFER)
    out["waiting_code"] = bool(off) and now < off.get("until", 0)
    if st.get("role") == "primary":
        out.update(url=st.get("url", ""), moved=bool(st.get("moved")),
                   last_contact=st.get("last_contact", 0), last_attempt=st.get("last_attempt", 0),
                   last_push=st.get("last_push", 0), last_push_bytes=st.get("last_push_bytes", 0),
                   last_push_s=st.get("last_push_s", 0), last_error=st.get("last_error", ""),
                   workspace=bool(st.get("workspace", True)), workspace_note=st.get("workspace_note", ""),
                   interval=st.get("interval", BEAT_S), push_every=st.get("push_every", PUSH_S),
                   split=st.get("split") or {}, last_swap=st.get("last_swap") or {})
    elif st.get("role") == "standby":
        out.update(last_beat=st.get("last_beat", 0), grace=st.get("grace", GRACE_S),
                   auto=bool(st.get("auto", True)), holds_work=bool(st.get("holds_work")),
                   copy_at=st.get("copy_at", 0), copy_bytes=st.get("copy_bytes", 0),
                   copy_created=st.get("copy_created", 0), copy_version=st.get("copy_version", ""),
                   copy_workspace=bool(st.get("copy_workspace")), since=st.get("since", 0),
                   reason=st.get("reason", ""), due=due_takeover(home),
                   notes=carry_notes(st), last_swap=st.get("last_swap") or {})
    if out["peer_version"] and out["peer_version"] != out["version"]:
        out["version_note"] = (f"This machine runs {out['version']} and {out['peer_host']} runs "
                               f"{out['peer_version']}. Keep them on the same version.")
    return out


def settings(body: dict, home=None) -> dict:
    """The few knobs: how long the standby waits, whether it takes over by itself, and
    whether the main machine includes its workspace."""
    st = load(home)
    if st.get("role") == "standby":
        if "grace" in body:
            st["grace"] = max(MIN_GRACE, min(MAX_GRACE, int(body["grace"])))
        if "auto" in body:
            st["auto"] = bool(body["auto"])
    elif st.get("role") == "primary":
        if "workspace" in body:
            st["workspace"] = bool(body["workspace"])
            st["last_fp"] = ""
    else:
        raise StandbyError("This machine is not paired.")
    save(st, home)
    return status(home)


def ago(t: float) -> str:
    if not t:
        return "never"
    s = max(0, int(time.time() - t))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


def size(n: int) -> str:
    n = int(n or 0)
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(1, n // 1000)} KB"
