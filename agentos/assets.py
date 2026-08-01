"""The asset store — everything the agent made, or was handed.

Generated images, video an MCP server returned, uploads, rendered cuts, reports.
Until now the only picture AgentOS could keep was a wallpaper, and anything a
media MCP produced was discarded (see the bridge in mcp_client.py). This is
where those bytes land.

Three decisions worth knowing before changing anything here:

**Content addressing.** A file is stored under its own sha256, so the same bytes
arriving twice cost one row and one file. Re-running a generation, or a workflow
that fetches the same clip in three steps, is free. It also means the path is
never caller-supplied, which is what keeps `/api/assets/{id}/file` from being a
directory traversal with extra steps: the caller names a row, never a path.

**No new dependencies.** AgentOS ships only permissive software and this module
adds nothing at all: dimensions and durations come from ffmpeg *if the user has
chosen to install it* (see components.py), and when it is absent the fields stay
zero and the UI says why rather than guessing. Pillow, moviepy and opencv were
all considered and all rejected — the dependency that matters is the codec
binary, and that one is the user's call to make, not ours to bundle.

**The Store never touches the filesystem.** memory.py owns rows, this module owns
bytes, and `delete()` is the one place that does both — in that order, so a
crash leaves an orphan file (harmless, `gc()` sweeps it) rather than a row
pointing at nothing (a broken thumbnail in every gallery).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import mimetypes
import os
import shutil
import time
from pathlib import Path

from .config import AGENTOS_HOME

ASSETS_ROOT = AGENTOS_HOME / "assets"
THUMBS_ROOT = AGENTOS_HOME / "assets" / ".thumbs"

#: the biggest thing we will accept in one JSON body (data-URL uploads, MCP
#: payloads). Raw streaming uploads have their own, larger cap.
MAX_INLINE_BYTES = 24 * 1024 * 1024
MAX_STREAM_BYTES = 2 * 1024 * 1024 * 1024

#: mime prefix -> the `kind` the UI groups and filters by
_KINDS = (("image/", "image"), ("video/", "video"), ("audio/", "audio"),
          ("text/", "doc"), ("application/pdf", "doc"), ("application/json", "data"))

#: extensions mimetypes doesn't know or gets wrong for our purposes
_EXTRA_TYPES = {".webp": "image/webp", ".webm": "video/webm", ".mkv": "video/x-matroska",
                ".m4a": "audio/mp4", ".opus": "audio/opus", ".flac": "audio/flac",
                ".heic": "image/heic", ".avif": "image/avif", ".mov": "video/quicktime"}


def kind_of(mime: str) -> str:
    mime = (mime or "").lower()
    for prefix, kind in _KINDS:
        if mime.startswith(prefix):
            return kind
    return "other"


def ext_for(mime: str, fallback_name: str = "") -> str:
    """A sane extension for a mime type. The extension is cosmetic — the row's
    `mime` is what anything downstream trusts — but a file called `a1b2c3` with no
    suffix is hostile to anyone who opens the assets directory in a file manager."""
    if fallback_name:
        ext = os.path.splitext(fallback_name)[1].lower()
        if ext and len(ext) <= 6:
            return ext
    for e, m in _EXTRA_TYPES.items():
        if m == (mime or "").lower():
            return e
    return mimetypes.guess_extension(mime or "") or ".bin"


def mime_for(name: str, given: str = "") -> str:
    if given:
        return given
    ext = os.path.splitext(name or "")[1].lower()
    return _EXTRA_TYPES.get(ext) or mimetypes.guess_type(name or "")[0] or "application/octet-stream"


def _path_for(sha: str, ext: str) -> Path:
    """Content-addressed, sharded two levels so a directory listing stays usable
    after a few thousand generations."""
    when = time.gmtime()
    return (ASSETS_ROOT / f"{when.tm_year:04d}" / f"{when.tm_mon:02d}"
            / sha[:2] / f"{sha}{ext}")


def path_of(row: dict) -> Path | None:
    """The file behind an asset row, or None when it has gone missing underneath
    us. Callers must handle None — a user can always delete a file by hand, and
    an exception at that point would take the whole gallery down."""
    p = Path(row.get("path") or "")
    return p if p.is_file() else None


# ---------------------------------------------------------------------------
# ffmpeg — optional, never assumed
# ---------------------------------------------------------------------------

def ffmpeg_path() -> str:
    return shutil.which("ffmpeg") or ""


def ffprobe_path() -> str:
    return shutil.which("ffprobe") or ""


def capability() -> dict:
    """What this machine can do with media, and — when it cannot — the component
    that would fix it. Never a bare False: a dead control with no explanation is
    the exact failure the honesty rule exists to prevent."""
    ff = ffmpeg_path()
    if ff:
        return {"ffmpeg": True, "path": ff, "probe": bool(ffprobe_path()),
                "thumbnails": True, "why": "", "component": ""}
    return {
        "ffmpeg": False, "path": "", "probe": False, "thumbnails": False,
        "component": "ffmpeg",
        "why": ("ffmpeg is not installed, so AgentOS can receive and play media but "
                "cannot measure, thumbnail or cut it on this machine."),
    }


async def _run(argv: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, "not installed"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
        return 1, f"timed out after {timeout}s"
    return proc.returncode or 0, out.decode(errors="replace")


async def probe(path: Path) -> dict:
    """Width/height/duration via ffprobe. Returns zeros when ffprobe is absent —
    unknown is recorded as unknown, never as a plausible-looking guess."""
    probe_bin = ffprobe_path()
    if not probe_bin:
        return {"width": 0, "height": 0, "duration": 0.0}
    code, out = await _run([probe_bin, "-v", "quiet", "-print_format", "json",
                            "-show_format", "-show_streams", str(path)], timeout=30)
    if code != 0:
        return {"width": 0, "height": 0, "duration": 0.0}
    try:
        data = json.loads(out)
    except Exception:
        return {"width": 0, "height": 0, "duration": 0.0}
    width = height = 0
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video":
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            break
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {"width": width, "height": height, "duration": duration}


async def make_thumb(path: Path, kind: str, sha: str) -> str:
    """A 480px-wide JPEG preview, or '' when nothing could make one.

    '' is a first-class answer: the Gallery renders the original scaled by CSS
    for images, and a kind badge for video and audio, and says which component
    would give it real thumbnails.
    """
    ff = ffmpeg_path()
    if not ff or kind not in ("image", "video"):
        return ""
    THUMBS_ROOT.mkdir(parents=True, exist_ok=True)
    out = THUMBS_ROOT / f"{sha}.jpg"
    if out.is_file():
        return str(out)
    argv = [ff, "-y", "-loglevel", "error"]
    if kind == "video":
        # a frame one second in: frame zero is very often black
        argv += ["-ss", "1"]
    argv += ["-i", str(path), "-frames:v", "1",
             "-vf", "scale=480:-2", "-q:v", "5", str(out)]
    code, _ = await _run(argv, timeout=45)
    if code != 0 and kind == "video":
        # a clip shorter than the seek: take the very first frame instead
        code, _ = await _run([ff, "-y", "-loglevel", "error", "-i", str(path),
                              "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "5",
                              str(out)], timeout=45)
    return str(out) if code == 0 and out.is_file() else ""


# ---------------------------------------------------------------------------
# putting things in
# ---------------------------------------------------------------------------

async def put_bytes(store, data: bytes, *, name: str = "", mime: str = "", title: str = "",
                    prompt: str = "", source: str = "", origin_url: str = "",
                    conversation_id: str = "", run_id: str = "", space_id: str = "",
                    meta: dict | None = None) -> dict:
    """Store bytes and return the asset row. The single entry point every other
    producer (MCP bridge, upload, generator, download) funnels through, so
    provenance and thumbnailing can never be forgotten by one of them."""
    if not data:
        return {}
    mime = mime_for(name, mime)
    kind = kind_of(mime)
    sha = hashlib.sha256(data).hexdigest()

    existing = store.asset_by_sha(sha)
    if existing and path_of(existing):
        return existing  # identical bytes already here; nothing to write

    path = _path_for(sha, ext_for(mime, name))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)  # atomic: no half-written file is ever addressable

    info = await probe(path) if kind in ("image", "video", "audio") else {}
    thumb = await make_thumb(path, kind, sha)
    aid = store.asset_add(
        sha256=sha, path=str(path), kind=kind, mime=mime, size=len(data),
        title=title or name or f"{kind} {sha[:8]}", prompt=prompt, source=source,
        origin_url=origin_url, conversation_id=conversation_id, run_id=run_id,
        space_id=space_id, thumb=thumb, width=info.get("width", 0),
        height=info.get("height", 0), duration=info.get("duration", 0.0), meta=meta)
    return store.asset_get(aid) or {}


async def put_data_url(store, data_url: str, **kw) -> dict:
    """Accept a `data:<mime>;base64,…` string — what a paste, a drag-drop and most
    MCP image payloads look like."""
    if not data_url.startswith("data:"):
        return {}
    head, _, b64 = data_url.partition(",")
    mime = head[5:].split(";")[0] or ""
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return {}
    if len(raw) > MAX_INLINE_BYTES:
        return {}
    kw.setdefault("mime", mime)
    return await put_bytes(store, raw, **kw)


async def put_base64(store, b64: str, mime: str = "", **kw) -> dict:
    try:
        raw = base64.b64decode(b64 or "", validate=False)
    except Exception:
        return {}
    if not raw or len(raw) > MAX_INLINE_BYTES:
        return {}
    kw["mime"] = mime or kw.get("mime", "")
    return await put_bytes(store, raw, **kw)


async def put_stream(store, chunks, *, name: str = "", mime: str = "",
                     max_bytes: int = MAX_STREAM_BYTES, **kw) -> dict:
    """Stream a large upload straight to disk.

    Async-iterates the request body rather than buffering it: a 200 MB video
    should never exist twice in memory, and base64 in a JSON body would make it
    267 MB of string on top of that. This is why uploads are a raw-body PUT and
    not multipart — multipart would also mean adding python-multipart, and this
    module's whole point is adding nothing.
    """
    ASSETS_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = ASSETS_ROOT / f".incoming-{os.getpid()}-{time.time_ns()}.part"
    digest = hashlib.sha256()
    total = 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"upload exceeds the {max_bytes // (1024 * 1024)} MB limit")
                digest.update(chunk)
                fh.write(chunk)
        if not total:
            return {}
        sha = digest.hexdigest()
        existing = store.asset_by_sha(sha)
        if existing and path_of(existing):
            return existing
        mime = mime_for(name, mime)
        path = _path_for(sha, ext_for(mime, name))
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(path))
        kind = kind_of(mime)
        info = await probe(path) if kind in ("image", "video", "audio") else {}
        thumb = await make_thumb(path, kind, sha)
        aid = store.asset_add(
            sha256=sha, path=str(path), kind=kind, mime=mime, size=total,
            title=kw.pop("title", "") or name or f"{kind} {sha[:8]}", thumb=thumb,
            width=info.get("width", 0), height=info.get("height", 0),
            duration=info.get("duration", 0.0), **kw)
        return store.asset_get(aid) or {}
    finally:
        with contextlib.suppress(Exception):
            if tmp.exists():
                tmp.unlink()


def delete(store, aid: str) -> bool:
    """Row first, then bytes. The reverse order would leave a row pointing at a
    file that is gone, which is a broken tile in every gallery; this way a crash
    leaves an unreferenced file, which `gc()` sweeps and nobody ever sees."""
    row = store.asset_delete(aid)
    if not row:
        return False
    for p in (row.get("path"), row.get("thumb")):
        if p:
            with contextlib.suppress(Exception):
                Path(p).unlink()
    return True


def gc(store) -> dict:
    """Sweep files with no row (interrupted writes, deletes that half-finished)
    and rows with no file (someone cleaned the directory by hand)."""
    known = {r["path"] for r in store.asset_list(limit=100000)}
    thumbs = {r["thumb"] for r in store.asset_list(limit=100000) if r.get("thumb")}
    orphan_files = orphan_rows = 0
    if ASSETS_ROOT.is_dir():
        for path in ASSETS_ROOT.rglob("*"):
            if not path.is_file():
                continue
            sp = str(path)
            if sp in known or sp in thumbs:
                continue
            if path.name.endswith(".part") or THUMBS_ROOT in path.parents or path.parent == THUMBS_ROOT:
                if sp in thumbs:
                    continue
            with contextlib.suppress(Exception):
                path.unlink()
                orphan_files += 1
    for row in store.asset_list(limit=100000):
        if not path_of(row):
            store.asset_delete(row["id"])
            orphan_rows += 1
    return {"files_removed": orphan_files, "rows_removed": orphan_rows}


def purge_all() -> int:
    """Remove every stored file. Used by 'start fresh' — factory_reset wipes the
    tables, and without this the bytes would quietly survive a reset that told
    the user everything was gone."""
    n = 0
    if ASSETS_ROOT.is_dir():
        for path in ASSETS_ROOT.rglob("*"):
            if path.is_file():
                with contextlib.suppress(Exception):
                    path.unlink()
                    n += 1
        with contextlib.suppress(Exception):
            shutil.rmtree(ASSETS_ROOT)
    return n


def public(row: dict) -> dict:
    """The shape the UI and the agent see: no absolute paths (they mean nothing to
    a remote browser and leak the home directory), ids instead."""
    if not row:
        return {}
    return {
        "id": row.get("id", ""), "kind": row.get("kind", ""), "mime": row.get("mime", ""),
        "title": row.get("title", ""), "prompt": row.get("prompt", ""),
        "bytes": row.get("bytes", 0), "width": row.get("width", 0),
        "height": row.get("height", 0), "duration": row.get("duration", 0),
        "source": row.get("source", ""), "origin_url": row.get("origin_url", ""),
        "conversation_id": row.get("conversation_id", ""), "run_id": row.get("run_id", ""),
        "space_id": row.get("space_id", ""), "has_thumb": bool(row.get("thumb")),
        "created_at": row.get("created_at", 0),
        "url": f"/api/assets/{row.get('id','')}/file",
        "thumb_url": f"/api/assets/{row.get('id','')}/thumb" if row.get("thumb") else "",
    }
