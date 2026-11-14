"""A real model for a thing in a scene: found by words, kept with its credit, never by address.

Asked for with three.js's own example of an artist's model: "this is so so amazing … we have the
potential". What makes that example good is the model, not the renderer, so a scene built only
from Bento's solids cannot reach it however it is lit. A solid may now say `look_for` (words: "a
wooden armchair"). The server looks those words up in a library it trusts, downloads the model
once into the person's home with its licence and credit, and the page stands it where the solid
was (24x-model.js). The solid the agent gave stays as the drawing's plan and as the fallback.

Four rules, the blueprint picture's (bppicture.py):
- **Words in, never an address.** A model's address comes from the library's own answer and
  only from `HOSTS`. Nothing the agent wrote is fetched.
- **A free licence only, and the credit is kept.** Poly Haven is CC0 throughout; the maker's
  name, the licence and the page are stored beside the files and shown on the drawing.
- **Bounded.** `MAX` lookups a scene, `CAP_FILE` a file, `CAP_MODEL` a model, `TIMEOUT` a
  request, names read strictly (`_safe`), and a word match has to be about the thing (`pick`):
  a wrong model is worse than the plain solid.
- **Never fatal, and said.** No network, nothing that fits, a file too large: the solid stays
  as it was built and the tool's answer names what was not found.

The library is one today (Poly Haven: about 500 photo-scanned props, furniture, plants and
rocks). It has no buildings, vehicles or people; those stay built from solids until a second
library or a generated model fills them. `LIBRARIES` is where the next one goes.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

UA = "BentoStage/1.0"
API = "https://api.polyhaven.com"
HOSTS = ("api.polyhaven.com", "dl.polyhaven.org")
LIBRARIES = ("polyhaven",)
RES = "1k"                       # the textures' size: enough on a screen, a few hundred kB each
MAX = 8                          # lookups in one scene
CAP_FILE = 8 * 1024 * 1024
CAP_MODEL = 16 * 1024 * 1024
CAP_INDEX = 6 * 1024 * 1024
TIMEOUT = 25.0
SCENE_S = 45.0                   # all of a scene's lookups together
INDEX_TTL = 86400.0
TYPES = {".gltf": "model/gltf+json", ".bin": "application/octet-stream", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".png": "image/png"}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,80}$")
_STOP = {"a", "an", "the", "of", "with", "and", "in", "on", "for", "old", "new", "big", "small", "large"}


def root(store) -> Path:
    """Where this person's models are kept: beside their own database."""
    return Path(store.path).parent / "stage-models"


def _safe(rel: str) -> bool:
    """A file inside a model: plain names, at most one folder deep, a kind the page reads."""
    parts = str(rel).split("/")
    return (0 < len(parts) <= 2 and all(_NAME.match(p) and ".." not in p for p in parts)
            and Path(parts[-1]).suffix.lower() in TYPES)


def _ok_url(url: str) -> bool:
    u = urlsplit(str(url))
    return u.scheme == "https" and u.hostname in HOSTS


def words_of(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", str(text).lower()) if w not in _STOP and len(w) > 2]


def _stem(w: str) -> str:
    return w[:-1] if w.endswith("s") and len(w) > 3 else w


def pick(index: dict, words: str) -> str | None:
    """The model these words are about, or None. A word must name the thing: it counts in the
    model's own name (most), its tags, then its categories, and the first word asked for must
    be found somewhere. Ties go to the lighter model."""
    want = [_stem(w) for w in words_of(words)]
    if not want:
        return None
    best, best_score = None, 0.0
    for aid, a in index.items():
        if not isinstance(a, dict) or not _NAME.match(str(aid)):
            continue
        name = {_stem(w) for w in words_of(a.get("name", ""))}
        tags = {_stem(w) for t in a.get("tags") or [] for w in words_of(t)}
        cats = {_stem(w) for t in a.get("categories") or [] for w in words_of(t)}
        score = sum(3.0 if w in name else 1.5 if w in tags else 0.5 if w in cats else 0.0 for w in want)
        if want[-1] not in name | tags:           # the noun comes last: "a wooden armchair"
            continue
        score -= min(float(a.get("polycount") or 0), 400000.0) / 4e6
        if score > best_score:
            best, best_score = str(aid), score
    return best if best_score >= 1.5 else None


async def _get(url: str, cap: int) -> bytes | None:
    from . import netguard
    if not _ok_url(url):
        return None
    try:
        status, _ct, body = await netguard.read_capped(url, cap, timeout=TIMEOUT, headers={"User-Agent": UA})
    except Exception:
        return None
    return body if status == 200 else None


async def index(base: Path, get=_get) -> dict:
    """The library's list of models, kept for a day."""
    f = base / "index.json"
    try:
        if f.exists() and time.time() - f.stat().st_mtime < INDEX_TTL:
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    raw = await get(f"{API}/assets?t=models", CAP_INDEX)
    try:
        data = json.loads(raw or b"")
        assert isinstance(data, dict)
    except Exception:
        try:
            return json.loads(f.read_text(encoding="utf-8"))       # an old list beats none
        except Exception:
            return {}
    base.mkdir(parents=True, exist_ok=True)
    slim = {k: {"name": v.get("name"), "tags": v.get("tags"), "categories": v.get("categories"),
                "polycount": v.get("polycount"), "authors": v.get("authors")}
            for k, v in data.items() if isinstance(v, dict)}
    f.write_text(json.dumps(slim), encoding="utf-8")
    return slim


def kept(base: Path, aid: str) -> dict | None:
    try:
        meta = json.loads((base / aid / "meta.json").read_text(encoding="utf-8"))
        return meta if (base / aid / meta["file"]).exists() else None
    except Exception:
        return None


async def fetch(base: Path, aid: str, entry: dict, get=_get) -> dict | None:
    """Download one model's files (once), read strictly, and write what it is beside them."""
    if not _NAME.match(aid):
        return None
    have = kept(base, aid)
    if have:
        return have
    try:
        files = json.loads(await get(f"{API}/files/{aid}", 512 * 1024) or b"")
        g = files["gltf"][RES]["gltf"]
        main = g["url"].rsplit("/", 1)[-1]
        todo = [(main, g["url"])] + [(rel, inc["url"]) for rel, inc in (g.get("include") or {}).items()]
    except Exception:
        return None
    if not all(_safe(rel) and _ok_url(url) for rel, url in todo) or not main.lower().endswith(".gltf"):
        return None
    folder, total, got = base / aid, 0, {}
    for rel, url in todo:
        body = await get(url, CAP_FILE)
        if body is None:
            return None
        total += len(body)
        if total > CAP_MODEL:
            return None
        got[rel] = body
    for rel, body in got.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    authors = entry.get("authors") if isinstance(entry.get("authors"), dict) else {}
    meta = {"id": aid, "file": main, "name": str(entry.get("name") or aid)[:60],
            "credit": ", ".join(str(a)[:40] for a in list(authors)[:3]) or "Poly Haven",
            "licence": "CC0", "library": "Poly Haven", "source": f"https://polyhaven.com/a/{aid}", "bytes": total}
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


async def find(base: Path, words: str, get=_get) -> dict | None:
    idx = await index(base, get)
    aid = pick(idx, words)
    return await fetch(base, aid, idx.get(aid) or {}, get) if aid else None


def wanted(scene: dict) -> list[tuple[int, str]]:
    """(index, words) of the solids that ask for a real model, `MAX` at most."""
    solids = scene.get("solids") or scene.get("model") or []
    return [(i, so["look_for"]) for i, so in enumerate(solids) if so.get("look_for")][:MAX]


async def fill(store, row: dict, tell=None, get=_get) -> list[str]:
    """Look up every solid of a stored scene that asks for one, write what was found into the
    scene (`mesh` on the solid: the server's field, never the agent's) and tell the screens.
    Returns the words nothing was found for."""
    scene = row["scene"]
    asks = wanted(scene)
    if not asks:
        return []
    base = root(store)

    async def one(words):
        try:
            return await find(base, words, get)
        except Exception:
            return None
    try:
        found = await asyncio.wait_for(asyncio.gather(*(one(w) for _i, w in asks)), SCENE_S)
    except Exception:
        found = [None] * len(asks)
    solids = scene.get("solids") or scene.get("model") or []
    missing = []
    for (i, words), meta in zip(asks, found):
        if meta:
            solids[i]["mesh"] = {k: meta[k] for k in ("id", "file", "name", "credit", "licence", "library", "source")}
        else:
            missing.append(words)
    if len(missing) < len(asks):
        store.db.execute("UPDATE stage_scenes SET scene=? WHERE id=?", (json.dumps(scene), row["id"]))
        store.db.commit()
        if tell:
            try:
                await tell({"type": "stage_fill", "id": row["id"], "scene": scene, "models": True})
            except Exception:
                pass
    return missing


def file_of(store, aid: str, rel: str) -> tuple[Path, str] | None:
    """The file to serve, and its type: only a kept model's own files, by a plain name."""
    if not _NAME.match(str(aid)) or not _safe(rel):
        return None
    base = root(store).resolve()
    p = (base / aid / rel).resolve()
    if base not in p.parents or not p.is_file():
        return None
    return p, TYPES[p.suffix.lower()]
