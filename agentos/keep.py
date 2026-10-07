"""Keep a free cloud Bento's memory in the person's own GitHub, sealed.

Asked for as "ensure that you are able to deploy the agent in the cloud free and make it
work". Every free container host found (Render Free, Koyeb's free instance, Hugging Face's
free CPU) throws its disk away on a restart, and Render says it "might restart a Free web
service at any time". A Bento that forgets its chats, memory, accounts and vault on every
restart does not work, however free it is. So the home is kept elsewhere:

  * WHERE: a secret gist on the person's own GitHub account (the account they just signed
    in to Render with). The key they make has the `gist` scope and nothing else, and the
    link that makes it is prefilled (`token_link`). No second service, nothing to pay.
  * WHAT: the same sealed file a backup is (backup.py: AES-256-GCM under scrypt), sealed
    with the machine's password (AGENTOS_PASSPHRASE). A secret gist is unlisted, not
    private, so the sealing is what protects it, not the URL.
  * WHEN: on start, only into an EMPTY home (a wiped disk), so a host that does keep its
    disk is never rolled back to an older copy; then whenever something changed (the
    standby's fingerprint, at most every `MIN_GAP_S`), and once more on shutdown, which
    is what Render's spin-down and redeploys send.

Three rules keep it honest:

  * Nothing is overwritten that could not be opened. A gist sealed with another password
    is left exactly as it is, the machine starts fresh, and its saves go to a NEW gist; the
    status says which and why. Losing somebody's only copy to a password change would be
    the worst thing this module could do.
  * It says what it is not doing. With no key on a host that forgets, `status()` says the
    machine forgets everything on a restart, in those words; Settings and `bento keep`
    show it.
  * The token never leaves the environment it was given in. It is not written to config,
    not shown, and not in the sealed home.

Kept free of asyncio, like backup.py: `bento keep` and the container's entrypoint call it
with the server down.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path

ENV_TOKEN = "BENTO_KEEP_GITHUB_TOKEN"
ENV_API = "AGENTOS_GITHUB_API"          # a stand-in API in tests, or GitHub Enterprise
ENV_EPHEMERAL = "BENTO_EPHEMERAL"       # set by a blueprint whose host forgets its disk
ENV_AWAKE = "BENTO_KEEP_AWAKE"
ENV_URL = "RENDER_EXTERNAL_URL"         # what Render calls this service from outside

DESC = "Bento home, sealed. Only your Bento password opens it."
INDEX = "bento-home.json"
PART_RAW = 3 << 20                      # 3 MiB per part: ~4 MiB of base64, under the
                                        # 10 MB a gist's raw file serves without a clone
CAP = 60 << 20                          # a sealed home over this is not kept, and said
MIN_GAP_S = 120                         # at most one save every two minutes
CHECK_S = 30                            # how often the server looks for a change
AWAKE_S = 600                           # a visit every ten minutes keeps Render awake
DIR = ".keep"                           # a PRIVATE prefix in backup.py: never sealed, never moved
STATE = "state.json"


class KeepError(Exception):
    """Something the person can act on, in a sentence."""


# ---- configuration ------------------------------------------------------------------

def _home(home=None) -> Path:
    if home:
        return Path(home)
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME)


def token() -> str:
    return (os.environ.get(ENV_TOKEN) or "").strip()


def passphrase() -> str:
    p = os.environ.get("AGENTOS_PASSPHRASE_FILE")
    if p:
        try:
            return Path(p).read_text().strip()
        except OSError:
            return ""
    return os.environ.get("AGENTOS_PASSPHRASE") or ""


def api() -> str:
    return (os.environ.get(ENV_API) or "https://api.github.com").rstrip("/")


def enabled() -> bool:
    return bool(token())


def ephemeral() -> bool:
    return (os.environ.get(ENV_EPHEMERAL) or "").strip().lower() in ("1", "true", "yes")


def token_link() -> str:
    """GitHub's new-token page with only the gist box ticked and a name filled in."""
    return "https://github.com/settings/tokens/new?scopes=gist&description=Bento%20cloud%20memory"


def awake_url() -> str:
    """Where to send the keep-awake visit, or '' when it is off. Opt-in by the blueprint:
    a visit through the host's own front door is the traffic its free tier counts."""
    if (os.environ.get(ENV_AWAKE) or "").strip().lower() not in ("1", "true", "yes"):
        return ""
    base = (os.environ.get(ENV_URL) or os.environ.get("BENTO_PUBLIC_URL") or "").rstrip("/")
    return base + "/login" if base.startswith(("http://", "https://")) else ""


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


# ---- GitHub ---------------------------------------------------------------------------

def _client(timeout: float = 60.0):
    import httpx
    return httpx.Client(timeout=timeout, follow_redirects=True)


def _headers() -> dict:
    return {"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "bento-keep"}


def _call(method: str, path: str, **kw):
    try:
        with _client() as c:
            r = c.request(method, api() + path, headers=_headers(), **kw)
    except Exception as e:                                              # noqa: BLE001
        raise KeepError(f"GitHub could not be reached: {type(e).__name__}.") from e
    if r.status_code == 401:
        raise KeepError("GitHub refused the key. It may have expired: make a new one "
                        f"({token_link()}) and put it in {ENV_TOKEN}.")
    if r.status_code == 403 or r.status_code == 404 and path.startswith("/gists") and method != "GET":
        raise KeepError("The GitHub key cannot write gists. Make one with the gist box "
                        f"ticked ({token_link()}).")
    if r.status_code >= 400:
        raise KeepError(f"GitHub answered {r.status_code}.")
    return r


def find() -> dict:
    """The newest gist of ours on this account, or {}."""
    best: dict = {}
    for page in range(1, 11):
        r = _call("GET", f"/gists?per_page=100&page={page}")
        got = r.json() or []
        for g in got:
            if INDEX in (g.get("files") or {}) and str(g.get("description", "")).startswith(DESC):
                if not best or str(g.get("updated_at", "")) > str(best.get("updated_at", "")):
                    best = g
        if len(got) < 100:
            break
    return best


def _file_text(f: dict) -> str:
    if not f.get("truncated") and f.get("content") is not None:
        return f["content"]
    url = f.get("raw_url") or ""
    if not url:
        raise KeepError("A part of the kept copy has no address on GitHub.")
    try:
        with _client() as c:
            r = c.get(url, headers={"Authorization": f"Bearer {token()}", "User-Agent": "bento-keep"})
    except Exception as e:                                              # noqa: BLE001
        raise KeepError(f"GitHub could not be reached: {type(e).__name__}.") from e
    if r.status_code >= 400:
        raise KeepError(f"GitHub answered {r.status_code} for a part of the kept copy.")
    return r.text


def download(gist_id: str) -> tuple[bytes, dict]:
    """The sealed bytes and the index, checked against the index's hash."""
    g = _call("GET", f"/gists/{gist_id}").json()
    files = g.get("files") or {}
    try:
        index = json.loads(_file_text(files[INDEX]))
    except (KeyError, ValueError) as e:
        raise KeepError("The kept copy on GitHub has no readable index.") from e
    data = b"".join(base64.b64decode(_file_text(files[name])) for name in index.get("parts", []))
    if hashlib.sha256(data).hexdigest() != index.get("sha256"):
        raise KeepError("The kept copy on GitHub is incomplete or was changed, so it was not used.")
    return data, index


def upload(data: bytes, index: dict, gist_id: str = "", old_parts=()) -> dict:
    parts = [data[i:i + PART_RAW] for i in range(0, len(data), PART_RAW)] or [b""]
    names = [f"part-{i:03d}.b64" for i in range(len(parts))]
    index = {**index, "parts": names, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    files: dict = {INDEX: {"content": json.dumps(index, indent=2)}}
    for name, chunk in zip(names, parts):
        files[name] = {"content": base64.b64encode(chunk).decode()}
    for name in old_parts:
        if name not in names:
            files[name] = None                       # a part the copy no longer has
    if gist_id:
        g = _call("PATCH", f"/gists/{gist_id}", json={"files": files}).json()
    else:
        g = _call("POST", "/gists", json={"description": f"{DESC} ({time.strftime('%Y-%m-%d')})",
                                          "public": False, "files": files}).json()
    return {"id": g.get("id", gist_id), "url": g.get("html_url", ""), "parts": names}


# ---- the two moves --------------------------------------------------------------------

def _empty(home: Path) -> bool:
    """A wiped disk: nothing a person made is here yet. The entrypoint writes config.json
    (the remote lock) before the server starts, so that alone does not count."""
    from . import backup as bk
    for rel, _p in bk._walk(home):
        if rel != "config.json" and not rel.startswith("session.key"):
            return False
    return True


def restore(home=None, echo=print) -> dict:
    """Bring the kept home back into an empty one. Called before the server starts."""
    from . import backup as bk
    home = _home(home)
    if not enabled():
        return {"restored": False, "why": "no GitHub key"}
    if not _empty(home):
        _update(home, restore_note="This machine already had its files, so nothing was restored.")
        return {"restored": False, "why": "this home is not empty"}
    pw = passphrase()
    if len(pw) < bk.MIN_PASSPHRASE:
        raise KeepError("Set AGENTOS_PASSPHRASE (8 characters or more): it seals the kept copy.")
    g = find()
    if not g:
        _update(home, gist="", restore_note="Nothing kept on GitHub yet. The first save makes it.")
        return {"restored": False, "why": "nothing kept yet"}
    t0 = time.time()
    data, index = download(g["id"])
    tmp = _dir(home) / f".backup-tmp-keep-{os.getpid()}.bento"
    tmp.write_bytes(data)
    try:
        staged = bk.stage(tmp, pw, home=home)
    except bk.BackupError as e:
        # Never overwrite what could not be opened: this machine starts fresh and saves
        # to a new gist, and the old one stays exactly as it is.
        _update(home, gist="", locked=g["id"], locked_url=g.get("html_url", ""),
                restore_note=("The kept copy on GitHub is sealed with another password, so it was "
                              "left as it is and this machine starts fresh. Put the old password "
                              "back in AGENTOS_PASSPHRASE and restart to use it."))
        if echo:
            echo(f"  ✗ kept copy not opened: {e}")
        return {"restored": False, "why": "another password", "gist": g["id"]}
    finally:
        tmp.unlink(missing_ok=True)
    report = bk.apply(staged["staging"], home=home, keyring=False)
    secs = round(time.time() - t0, 1)
    _update(home, gist=g["id"], url=g.get("html_url", ""), parts=index.get("parts", []),
            restored_at=time.time(), restored_bytes=len(data), restored_s=secs, locked="",
            restore_note=f"Restored from GitHub ({_size(len(data))}) in {secs}s.")
    if echo:
        echo(f"  ✓ restored this machine's memory from GitHub ({_size(len(data))}, {secs}s)")
    return {"restored": True, "bytes": len(data), "seconds": secs, "report": report}


_SAVING = threading.Lock()                 # the loop and the shutdown save never overlap


def save(home=None, force: bool = False, final: bool = False) -> dict:
    """Seal the home and put it on GitHub, if it changed since the last save. `final` is
    the shutdown save: it skips the two-minute gap, never the "nothing changed" check."""
    with _SAVING:
        return _save(home, force, final)


def _save(home, force: bool, final: bool) -> dict:
    from . import backup as bk
    from . import standby as standbymod
    home = _home(home)
    if not enabled():
        return {"saved": False, "why": "no GitHub key"}
    pw = passphrase()
    if len(pw) < bk.MIN_PASSPHRASE:
        raise KeepError("Set AGENTOS_PASSPHRASE (8 characters or more): it seals the kept copy.")
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
        data = out.read_bytes()
    finally:
        out.unlink(missing_ok=True)
    if len(data) > CAP:
        _update(home, error=f"The sealed home is {_size(len(data))}, over the {_size(CAP)} kept on GitHub.")
        raise KeepError(f"This machine is {_size(len(data))} sealed, too big to keep on GitHub ({_size(CAP)} at most).")
    index = {"format": "bento-keep/1", "created": time.time(), "host": m.get("host", ""),
             "version": m.get("version", ""), "workspace": ws}
    try:
        r = upload(data, index, st.get("gist", ""), st.get("parts", []))
    except KeepError as e:
        _update(home, error=str(e), error_at=time.time())
        raise
    secs = round(time.time() - t0, 1)
    _update(home, gist=r["id"], url=r["url"] or st.get("url", ""), parts=r["parts"], fp=fp,
            saved_at=time.time(), saved_bytes=len(data), saved_s=secs, workspace=ws,
            error="", error_at=0)
    return {"saved": True, "bytes": len(data), "seconds": secs, "url": r["url"]}


def status(home=None) -> dict:
    """What a person should know about this machine's memory, in one place."""
    st = load(home)
    on = enabled()
    if on and st.get("error"):
        line = f"Your memory is kept on GitHub, but the last save failed: {st['error']}"
        kind = "err"
    elif on and st.get("saved_at"):
        line = "Your memory is kept on GitHub, sealed with your password."
        kind = "ok"
    elif on:
        line = "Your memory will be kept on GitHub, sealed with your password, from the first change."
        kind = "ok"
    elif ephemeral():
        line = ("This cloud Bento forgets everything when it restarts. Add a GitHub key "
                f"in {ENV_TOKEN} to keep it.")
        kind = "warn"
    else:
        line = ""
        kind = ""
    return {"enabled": on, "ephemeral": ephemeral(), "line": line, "kind": kind,
            "token_link": token_link(), "env": ENV_TOKEN,
            "url": st.get("url", ""), "saved_at": st.get("saved_at", 0),
            "saved_bytes": st.get("saved_bytes", 0), "restored_at": st.get("restored_at", 0),
            "restore_note": st.get("restore_note", ""), "locked_url": st.get("locked_url", ""),
            "awake": bool(awake_url())}


def _size(n: int) -> str:
    return f"{n / (1 << 20):.1f} MB" if n >= 1 << 20 else f"{max(1, n >> 10)} KB"
