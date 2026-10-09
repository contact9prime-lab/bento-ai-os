"""Keep a free cloud Bento's memory in the person's own storage bucket, sealed.

Asked for as "ensure that you are able to deploy the agent in the cloud free and make it
work". Every free container host found (Render Free, Koyeb's free instance, Hugging Face's
free CPU) throws its disk away on a restart, and Render says it "might restart a Free web
service at any time". A Bento that forgets its chats, memory, accounts and vault on every
restart does not work, however free it is. So the home is kept elsewhere:

  * WHERE: a bucket the person owns on an S3-compatible storage service. Backblaze B2 is
    the one the docs walk through (10 GB free, no card, sign up with Google); Cloudflare R2,
    Tigris and any other S3-compatible service work the same way (`PROVIDERS`). The first
    cut used a secret gist on GitHub, and the owner's answer was "you can't be storing
    memories on GitHub": a code host is not a store for somebody's memory, whatever the
    sealing. Storage is the product these services sell, and its key reaches one bucket.
  * WHAT: the same sealed file a backup is (backup.py: AES-256-GCM under scrypt), sealed
    with the machine's password (AGENTOS_PASSPHRASE). The storage service holds noise.
  * WHEN: on start, only into an EMPTY home (a wiped disk), so a host that does keep its
    disk is never rolled back to an older copy; then whenever something changed (the
    standby's fingerprint, at most every `MIN_GAP_S`), and once more on shutdown, which
    is what Render's spin-down and redeploys send.

Layout in the bucket, under `PREFIX`: two slots (`a.bento`, `b.bento`) and `index.json`
naming the slot that is current with its SHA-256. A save writes the slot that is NOT
current and then the index, so the copy before always stays whole, and a save cut off
half-way leaves the index pointing at the last good one.

Three rules keep it honest:

  * Nothing is overwritten that could not be opened. A copy sealed with another password
    is left exactly as it is, the machine starts fresh, and its saves go under a NEW prefix;
    the status says which and why. Losing somebody's only copy to a password change would
    be the worst thing this module could do.
  * It says what it is not doing. With no storage on a host that forgets, `status()` says
    the machine forgets everything on a restart, in those words; Settings and `bento keep`
    show it.
  * The key never leaves the environment it was given in. It is not written to config,
    not shown, and not in the sealed home.

The S3 client is ours (`_sign`, AWS Signature Version 4, path-style), about eighty lines
of stdlib, because boto3 is a large dependency for four calls. It was checked against
botocore's signer and AWS's published example; `tests/test_keep.py` pins the example.

Kept free of asyncio, like backup.py: `bento keep` and the container's entrypoint call it
with the server down.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

ENV_ENDPOINT = "BENTO_STORAGE_ENDPOINT"
ENV_BUCKET = "BENTO_STORAGE_BUCKET"
ENV_KEY_ID = "BENTO_STORAGE_KEY_ID"
ENV_SECRET = "BENTO_STORAGE_SECRET"
ENV_REGION = "BENTO_STORAGE_REGION"     # optional: read from the endpoint when it names one
ENV_EPHEMERAL = "BENTO_EPHEMERAL"       # set by a blueprint whose host forgets its disk
ENV_AWAKE = "BENTO_KEEP_AWAKE"
ENV_URL = "RENDER_EXTERNAL_URL"         # what Render calls this service from outside
ENVS = (ENV_ENDPOINT, ENV_BUCKET, ENV_KEY_ID, ENV_SECRET)

PREFIX = "bento-home"
INDEX = "index.json"
SLOTS = ("a.bento", "b.bento")
CAP = 200 << 20                         # a sealed home over this leaves the workspace out
MIN_GAP_S = 120                         # at most one save every two minutes
CHECK_S = 30                            # how often the server looks for a change
AWAKE_S = 600                           # a visit every ten minutes keeps Render awake
DIR = ".keep"                           # a PRIVATE prefix in backup.py: never sealed, never moved
STATE = "state.json"

#: The storage services the card and the docs offer, easiest first. Each says what is free,
#: whether it asks for a card, and where its endpoint is shown, because those are the three
#: things a beginner gets stuck on. Facts as their own pages stated them in October 2026.
PROVIDERS = [
    {"id": "b2", "name": "Backblaze B2", "recommended": True,
     "free": "10 GB free, for good", "card": "No card. Sign up with Google or an email.",
     "signup": "https://www.backblaze.com/sign-up/cloud-storage",
     "endpoint": "s3.<region>.backblazeb2.com, shown on the bucket's page as Endpoint",
     "steps": ["Sign up for Backblaze B2 (choose a region; any is fine).",
               "Buckets → Create a Bucket: give it a unique name, keep it Private.",
               "Application Keys → Add a New Application Key: allow access to that bucket only, "
               "Read and Write. Copy the keyID and the applicationKey (shown once)."]},
    {"id": "r2", "name": "Cloudflare R2", "recommended": False,
     "free": "10 GB free a month", "card": "Asks for a card to switch R2 on; the free amount is not charged.",
     "signup": "https://dash.cloudflare.com/sign-up",
     "endpoint": "<account id>.r2.cloudflarestorage.com, shown under R2 → your bucket → Settings",
     "steps": ["R2 → Create bucket.",
               "R2 → Manage API tokens → Create API token: Object Read & Write, that bucket only.",
               "Copy the Access Key ID and Secret Access Key, and the S3 endpoint it shows."]},
    {"id": "tigris", "name": "Tigris", "recommended": False,
     "free": "5 GB free a month", "card": "No card to start.",
     "signup": "https://console.storage.dev",
     "endpoint": "t3.storage.dev",
     "steps": ["Create a bucket.", "Access Keys → Create: Editor on that bucket.",
               "Copy the Access Key ID and Secret Access Key."]},
    {"id": "s3", "name": "Any S3-compatible storage", "recommended": False,
     "free": "", "card": "",
     "signup": "",
     "endpoint": "the service's S3 endpoint (AWS S3, Wasabi, iDrive e2, MinIO, your own)",
     "steps": ["Make a private bucket and a key that can read and write only that bucket.",
               f"If the endpoint does not name its region, set {ENV_REGION} too."]},
]


class KeepError(Exception):
    """Something the person can act on, in a sentence."""


# ---- configuration ------------------------------------------------------------------

def _home(home=None) -> Path:
    if home:
        return Path(home)
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def storage() -> dict:
    """The bucket from the environment: endpoint (a base URL, path kept), bucket, region.
    Forgiving about what a person pastes: a bare host or a full URL, and an endpoint that
    already ends in the bucket's name (R2 shows it that way) with the bucket box empty."""
    raw = _env(ENV_ENDPOINT)
    if raw and "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw) if raw else None
    path = (parts.path if parts else "").rstrip("/")
    bucket = _env(ENV_BUCKET).strip("/")
    tail = path.rsplit("/", 1)[-1] if path else ""
    if tail and (tail == bucket or not bucket and path.count("/") == 1):
        bucket, path = tail, path[: -len(tail) - 1]
    base = f"{parts.scheme}://{parts.netloc}{path}" if parts and parts.netloc else ""
    host = parts.hostname or "" if parts else ""
    return {"base": base, "host": host, "bucket": bucket,
            "region": _env(ENV_REGION) or region_of(host)}


def region_of(host: str) -> str:
    """The signing region a host implies. R2 and Tigris sign with `auto`; B2, AWS, Wasabi
    and iDrive put the region in the host name; anything else is us-east-1, which is what
    most S3-compatible servers accept."""
    host = (host or "").lower()
    if host.endswith((".r2.cloudflarestorage.com", "storage.dev", "tigris.dev")):
        return "auto"
    m = re.match(r"^s3[.-]([a-z]{2}-[a-z]+-\d+)\.", host)
    if m:
        return m.group(1)
    m = re.match(r"^[^.]+\.([a-z]{2}-[a-z]+-?\d*)\.idrivee2", host)
    return m.group(1) if m else "us-east-1"


def provider_of(host: str) -> str:
    host = (host or "").lower()
    for suffix, name in ((".backblazeb2.com", "Backblaze B2"), (".r2.cloudflarestorage.com", "Cloudflare R2"),
                         ("storage.dev", "Tigris"), ("tigris.dev", "Tigris"), (".amazonaws.com", "Amazon S3"),
                         (".wasabisys.com", "Wasabi"), ("idrivee2", "iDrive e2"), (".supabase.co", "Supabase")):
        if suffix in host:
            return name
    return "your storage"


def _who() -> str:
    name = provider_of(storage()["host"])
    return name[0].upper() + name[1:]


def missing() -> list[str]:
    """The settings that are not filled in, by their environment names."""
    s = storage()
    out = [ENV_ENDPOINT] if not s["base"] else []
    if not s["bucket"]:
        out.append(ENV_BUCKET)
    return out + [n for n in (ENV_KEY_ID, ENV_SECRET) if not _env(n)]


def enabled() -> bool:
    return not missing()


def started() -> bool:
    """Some of it was filled in: then a missing piece is an error, not a choice."""
    return any(_env(n) for n in ENVS)


def passphrase() -> str:
    p = os.environ.get("AGENTOS_PASSPHRASE_FILE")
    if p:
        try:
            return Path(p).read_text().strip()
        except OSError:
            return ""
    return os.environ.get("AGENTOS_PASSPHRASE") or ""


def ephemeral() -> bool:
    return _env(ENV_EPHEMERAL).lower() in ("1", "true", "yes")


def awake_url() -> str:
    """Where to send the keep-awake visit, or '' when it is off. Opt-in by the blueprint:
    a visit through the host's own front door is the traffic its free tier counts."""
    if _env(ENV_AWAKE).lower() not in ("1", "true", "yes"):
        return ""
    base = (os.environ.get(ENV_URL) or os.environ.get("BENTO_PUBLIC_URL") or "").rstrip("/")
    return base + "/login" if base.startswith(("http://", "https://")) else ""


def where() -> str:
    """'your Backblaze B2 bucket bento-ada', for the sentences."""
    s = storage()
    name = provider_of(s["host"])
    return f"your {name} bucket {s['bucket']}" if name != "your storage" else f"your bucket {s['bucket']}"


# ---- state ----------------------------------------------------------------------------

def _dir(home=None) -> Path:
    d = _home(home) / DIR
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def load(home=None) -> dict:
    try:
        return json.loads((_home(home) / DIR / STATE).read_text())
    except Exception:
        return {}


def _update(home=None, **kw) -> dict:
    st = load(home)
    st.update(kw)
    p = _dir(home) / STATE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2))
    os.replace(tmp, p)
    return st


# ---- S3, signed by hand -----------------------------------------------------------------

EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _sign(method: str, url: str, headers: dict, payload_sha: str, key_id: str, secret: str,
          region: str, when: _dt.datetime | None = None, service: str = "s3") -> dict:
    """AWS Signature Version 4. Returns the headers to send: the ones given, plus host,
    x-amz-date, x-amz-content-sha256 and Authorization. Every header given is signed."""
    when = when or _dt.datetime.now(_dt.timezone.utc)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    u = urlsplit(url)
    host = u.netloc
    out = {**headers, "host": host, "x-amz-date": stamp, "x-amz-content-sha256": payload_sha}
    canon_h = {k.lower().strip(): " ".join(str(v).split()) for k, v in out.items()}
    signed = ";".join(sorted(canon_h))
    query = []
    for pair in filter(None, u.query.split("&")):
        k, _, v = pair.partition("=")
        query.append((quote(_unq(k), safe="-_.~"), quote(_unq(v), safe="-_.~")))
    canonical = "\n".join([
        method, quote(_unq(u.path) or "/", safe="/-_.~"), "&".join(f"{k}={v}" for k, v in sorted(query)),
        "".join(f"{k}:{canon_h[k]}\n" for k in sorted(canon_h)), signed, payload_sha])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret).encode(), day), region), service), "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    out["Authorization"] = f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={signed}, Signature={sig}"
    del out["host"]                      # the HTTP client sends it; signing it is what counts
    return out


def _unq(s: str) -> str:
    from urllib.parse import unquote
    return unquote(s)


def _url(key: str = "", query: str = "") -> str:
    s = storage()
    path = "/" + quote(s["bucket"], safe="") + ("/" + quote(key, safe="/-_.~") if key else "")
    return s["base"] + path + (("?" + query) if query else "")


def _code(text: str) -> str:
    m = re.search(r"<Code>([^<]+)</Code>", text or "")
    return m.group(1) if m else ""


def _request(method: str, key: str = "", query: str = "", body=None, sha: str = EMPTY_SHA,
             length: int | None = None, stream_to: Path | None = None, timeout: float = 120.0):
    import httpx
    s = storage()
    url = _url(key, query)
    headers = {}
    if length is not None:
        headers["content-length"] = str(length)
    headers = _sign(method, url, headers, sha, _env(ENV_KEY_ID), _env(ENV_SECRET), s["region"])
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as c:
            if stream_to is not None:
                with c.stream(method, url, headers=headers) as r:
                    if r.status_code < 300:
                        h = hashlib.sha256()
                        with open(stream_to, "wb") as f:
                            for chunk in r.iter_bytes(1 << 20):
                                f.write(chunk)
                                h.update(chunk)
                        return r.status_code, h.hexdigest()
                    r.read()
                    _raise(r.status_code, r.text, key)
            r = c.request(method, url, headers=headers, content=body)
    except KeepError:
        raise
    except Exception as e:                                              # noqa: BLE001
        raise KeepError(f"{_who()} could not be reached: {type(e).__name__}.") from e
    if r.status_code >= 300:
        _raise(r.status_code, r.text, key)
    return r.status_code, r


def _raise(status: int, text: str, key: str):
    code = _code(text)
    s = storage()
    who = _who()
    if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "InvalidToken", "ExpiredToken") or status == 401:
        raise KeepError(f"{who} refused the key. Check {ENV_KEY_ID} and {ENV_SECRET}, or make a new key "
                        "that can read and write the bucket.")
    if code == "NoSuchBucket":
        raise KeepError(f"{who} has no bucket named {s['bucket']}. Check {ENV_BUCKET}.")
    if code == "AuthorizationHeaderMalformed" or code == "IllegalLocationConstraintException":
        raise KeepError(f"{who} wants another region. Set {ENV_REGION} to the bucket's region.")
    if status == 403:
        raise KeepError(f"The key cannot {'write to' if key else 'list'} the bucket {s['bucket']}. "
                        "Give it Read and Write on that bucket.")
    raise KeepError(f"{who} answered {status}{f' ({code})' if code else ''}.")


def _list(prefix: str) -> list[str]:
    keys: list[str] = []
    token = ""
    for _ in range(20):
        q = "list-type=2&prefix=" + quote(prefix, safe="")
        if token:
            q += "&continuation-token=" + quote(token, safe="")
        _, r = _request("GET", "", q)
        keys += [_xml_unescape(k) for k in re.findall(r"<Key>([^<]+)</Key>", r.text)]
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", r.text)
        if "<IsTruncated>true</IsTruncated>" not in r.text or not m:
            break
        token = _xml_unescape(m.group(1))
    return keys


def _xml_unescape(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&apos;", "'").replace("&amp;", "&"))


def _get_json(key: str) -> dict:
    _, r = _request("GET", key)
    try:
        return json.loads(r.text)
    except ValueError as e:
        raise KeepError(f"The kept index at {key} cannot be read.") from e


def _put_bytes(key: str, data: bytes):
    _request("PUT", key, body=data, sha=hashlib.sha256(data).hexdigest(), length=len(data))


def _put_file(key: str, path: Path, sha: str):
    size = path.stat().st_size
    with open(path, "rb") as f:
        _request("PUT", key, body=_chunks(f), sha=sha, length=size, timeout=600)


def _chunks(f):
    while True:
        b = f.read(1 << 20)
        if not b:
            return
        yield b


def find() -> dict:
    """The newest index of ours in the bucket, with its prefix, or {}."""
    best: dict = {}
    for key in _list(PREFIX):
        if not key.endswith("/" + INDEX):
            continue
        try:
            idx = _get_json(key)
        except KeepError:
            continue
        if idx.get("format") == "bento-keep/2" and idx.get("created", 0) > best.get("created", 0):
            best = {**idx, "prefix": key[: -len(INDEX) - 1]}
    return best


def download(index: dict, to: Path) -> int:
    """The current slot into `to`, checked against the index's hash. Returns its size."""
    key = f"{index['prefix']}/{index['slot']}"
    _, sha = _request("GET", key, stream_to=to, timeout=600)
    if sha != index.get("sha256"):
        to.unlink(missing_ok=True)
        raise KeepError("The kept copy is incomplete or was changed, so it was not used.")
    return to.stat().st_size


def upload(path: Path, index: dict, prefix: str, current_slot: str = "") -> dict:
    """The sealed file into the slot that is not current, then the index that names it."""
    slot = SLOTS[1] if current_slot == SLOTS[0] else SLOTS[0]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in _chunks(f):
            h.update(b)
    sha = h.hexdigest()
    _put_file(f"{prefix}/{slot}", path, sha)
    index = {**index, "format": "bento-keep/2", "slot": slot, "sha256": sha,
             "bytes": path.stat().st_size, "created": time.time()}
    _put_bytes(f"{prefix}/{INDEX}", json.dumps(index, indent=2).encode())
    return {"prefix": prefix, "slot": slot}


# ---- the two moves --------------------------------------------------------------------

def _empty(home: Path) -> bool:
    """A wiped disk: nothing a person made is here yet. The entrypoint writes config.json
    (the remote lock) before the server starts, so that alone does not count."""
    from . import backup as bk
    for rel, _p in bk._walk(home):
        if rel != "config.json" and not rel.startswith("session.key"):
            return False
    return True


def _need_passphrase() -> str:
    from . import backup as bk
    pw = passphrase()
    if len(pw) < bk.MIN_PASSPHRASE:
        raise KeepError("Set AGENTOS_PASSPHRASE (8 characters or more): it seals the kept copy.")
    return pw


def _need_storage():
    if started() and not enabled():
        raise KeepError("The storage is not fully set: " + ", ".join(missing()) + " missing.")


def restore(home=None, echo=print) -> dict:
    """Bring the kept home back into an empty one. Called before the server starts."""
    from . import backup as bk
    home = _home(home)
    _need_storage()
    if not enabled():
        return {"restored": False, "why": "no storage"}
    if not _empty(home):
        _update(home, restore_note="This machine already had its files, so nothing was restored.")
        return {"restored": False, "why": "this home is not empty"}
    pw = _need_passphrase()
    idx = find()
    if not idx:
        _update(home, prefix=PREFIX, slot="",
                restore_note=f"Nothing kept in {where()} yet. The first save makes it.")
        return {"restored": False, "why": "nothing kept yet"}
    t0 = time.time()
    tmp = _dir(home) / f".backup-tmp-keep-{os.getpid()}.bento"
    try:
        size = download(idx, tmp)
        staged = bk.stage(tmp, pw, home=home)
    except bk.BackupError as e:
        # Never overwrite what could not be opened: this machine starts fresh and saves
        # under a new prefix, and the old copy stays exactly as it is.
        new = f"{PREFIX}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
        _update(home, prefix=new, slot="", locked=idx["prefix"],
                restore_note=(f"The kept copy in {where()} is sealed with another password, so it "
                              "was left as it is and this machine starts fresh. Put the old password "
                              "back in AGENTOS_PASSPHRASE and restart to use it."))
        if echo:
            echo(f"  ✗ kept copy not opened: {e}")
        return {"restored": False, "why": "another password", "prefix": idx["prefix"]}
    finally:
        tmp.unlink(missing_ok=True)
    report = bk.apply(staged["staging"], home=home, keyring=False)
    secs = round(time.time() - t0, 1)
    _update(home, prefix=idx["prefix"], slot=idx["slot"], restored_at=time.time(),
            restored_bytes=size, restored_s=secs, locked="",
            restore_note=f"Restored from {where()} ({_size(size)}) in {secs}s.")
    if echo:
        echo(f"  ✓ restored this machine's memory from {where()} ({_size(size)}, {secs}s)")
    return {"restored": True, "bytes": size, "seconds": secs, "report": report}


_SAVING = threading.Lock()                 # the loop and the shutdown save never overlap


def save(home=None, force: bool = False, final: bool = False) -> dict:
    """Seal the home and put it in the bucket, if it changed since the last save. `final`
    is the shutdown save: it skips the two-minute gap, never the "nothing changed" check."""
    with _SAVING:
        return _save(home, force, final)


def _save(home, force: bool, final: bool) -> dict:
    from . import backup as bk
    from . import standby as standbymod
    home = _home(home)
    _need_storage()
    if not enabled():
        return {"saved": False, "why": "no storage"}
    pw = _need_passphrase()
    st = load(home)
    ws = True
    try:
        if bk.plan(home, True).get("workspace_bytes", 0) > CAP:
            ws = False
    except Exception:
        pass
    fp = standbymod.fingerprint(home, ws)
    if not force and fp == st.get("fp") and st.get("saved_at"):
        return {"saved": False, "why": "nothing changed"}
    if not (force or final) and time.time() - st.get("saved_at", 0) < MIN_GAP_S and st.get("saved_at"):
        return {"saved": False, "why": "saved a moment ago"}
    out = _dir(home) / f".backup-out-keep-{os.getpid()}.bento"
    t0 = time.time()
    try:
        m = bk.create(out, pw, home=home, workspace=ws)
        size = out.stat().st_size
        if size > CAP:
            _update(home, error=f"The sealed home is {_size(size)}, over the {_size(CAP)} kept in storage.")
            raise KeepError(f"This machine is {_size(size)} sealed, too big to keep ({_size(CAP)} at most).")
        index = {"host": m.get("host", ""), "version": m.get("version", ""), "workspace": ws}
        try:
            r = upload(out, index, st.get("prefix") or PREFIX, st.get("slot", ""))
        except KeepError as e:
            _update(home, error=str(e), error_at=time.time())
            raise
    finally:
        out.unlink(missing_ok=True)
    secs = round(time.time() - t0, 1)
    _update(home, prefix=r["prefix"], slot=r["slot"], fp=fp, saved_at=time.time(),
            saved_bytes=size, saved_s=secs, workspace=ws, error="", error_at=0)
    return {"saved": True, "bytes": size, "seconds": secs, "where": where()}


def status(home=None) -> dict:
    """What a person should know about this machine's memory, in one place."""
    st = load(home)
    on = enabled()
    half = started() and not on
    if half:
        line = "The storage is not fully set: " + ", ".join(missing()) + " missing."
        kind = "err"
    elif on and st.get("error"):
        line = f"Your memory is kept in {where()}, but the last save failed: {st['error']}"
        kind = "err"
    elif on and st.get("saved_at"):
        line = f"Your memory is kept in {where()}, sealed with your password."
        kind = "ok"
    elif on:
        line = f"Your memory will be kept in {where()}, sealed with your password, from the first change."
        kind = "ok"
    elif ephemeral():
        line = "This cloud Bento forgets everything when it restarts. Add a storage bucket to keep it."
        kind = "warn"
    else:
        line = ""
        kind = ""
    s = storage()
    return {"enabled": on, "ephemeral": ephemeral(), "line": line, "kind": kind,
            "provider": provider_of(s["host"]) if s["host"] else "", "bucket": s["bucket"],
            "env": list(ENVS), "missing": missing() if started() else [],
            "prefix": st.get("prefix", ""), "saved_at": st.get("saved_at", 0),
            "saved_bytes": st.get("saved_bytes", 0), "restored_at": st.get("restored_at", 0),
            "restore_note": st.get("restore_note", ""), "locked": st.get("locked", ""),
            "awake": bool(awake_url())}


def _size(n: int) -> str:
    return f"{n / (1 << 20):.1f} MB" if n >= 1 << 20 else f"{max(1, n >> 10)} KB"
