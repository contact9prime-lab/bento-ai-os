"""Semantic search over the things the OS can see.

Every search box in the shell was `String.includes()` while the OS carried a
resident LLM and a local embedding model — this module closes that gap. It
keeps a small SQLite-backed index (chunks of workspace files + generated docs)
with Ollama embeddings, refreshed lazily: a file is (re)embedded only when its
mtime changes, at query time or from the knowledge maintenance loop.

Degrades honestly: with no embedding model available, `query()` falls back to
plain substring scoring over the same corpus, so /api/search always answers.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path

from . import config as cfgmod
from . import knowledge

INDEXABLE = {".md", ".txt", ".py", ".js", ".html", ".css", ".json", ".yaml", ".yml",
             ".toml", ".sh", ".csv", ".log"}
MAX_FILE_BYTES = 512_000          # skip anything bigger — this is a desktop, not a data lake
CHUNK_CHARS = 1400
MAX_FILES_PER_PASS = 40           # lazy refresh budget per query/maintenance tick


def _ensure_table(store) -> None:
    store.db.execute("""CREATE TABLE IF NOT EXISTS search_index(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        chunk INTEGER NOT NULL,
        mtime REAL NOT NULL,
        text TEXT NOT NULL,
        embedding TEXT,
        UNIQUE(path, chunk))""")
    store.db.commit()


def shipped_docs_dir() -> Path | None:
    """The manual that ships with AgentOS (`docs/`), wherever it landed."""
    for cand in (Path(__file__).parent / "docs",          # packaged wheel
                 Path(__file__).parent.parent / "docs"):  # repo checkout
        if cand.is_dir():
            return cand
    return None


def _corpus_dirs(cfg: dict) -> list[Path]:
    dirs = []
    ws = cfg.get("workspace")
    if ws:
        dirs.append(Path(ws).expanduser())
    dirs.append(cfgmod.AGENTOS_HOME / "docs")
    # The OS's own manual. It was the one corpus missing, which is why "how do I
    # scope a grant to Telegram?" could only ever be answered from the model's
    # memory of a project it has never read — the answer is in docs/security.md,
    # on this disk, and now it is retrievable like anything else.
    shipped = shipped_docs_dir()
    if shipped:
        dirs.append(shipped)
    return [d for d in dirs if d.is_dir()]


def _iter_files(cfg: dict):
    for base in _corpus_dirs(cfg):
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in INDEXABLE:
                continue
            if any(part.startswith(".") for part in p.parts):
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield p


def _chunks(text: str) -> list[str]:
    out, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) > CHUNK_CHARS and buf:
            out.append(buf.strip())
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        out.append(buf.strip())
    return out[:64]


async def refresh(cfg: dict, store, budget: int = MAX_FILES_PER_PASS) -> int:
    """(Re)index files whose mtime moved. Cheap when nothing changed."""
    _ensure_table(store)
    known = {r["path"]: r["mtime"] for r in store.db.execute(
        "SELECT path, MAX(mtime) AS mtime FROM search_index GROUP BY path").fetchall()}
    seen, todo = set(), []
    for p in _iter_files(cfg):
        sp = str(p)
        seen.add(sp)
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if abs(known.get(sp, 0) - mt) > 1e-6:
            todo.append((p, mt))
        if len(todo) >= budget:
            break
    # drop rows for files that vanished
    for gone in set(known) - seen:
        store.db.execute("DELETE FROM search_index WHERE path=?", (gone,))
    changed = 0
    for p, mt in todo:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        store.db.execute("DELETE FROM search_index WHERE path=?", (str(p),))
        chunks = _chunks(text)
        vecs = await knowledge.embed_texts(cfg, chunks) if chunks else None
        for i, c in enumerate(chunks):
            store.db.execute(
                "INSERT OR REPLACE INTO search_index(path, chunk, mtime, text, embedding) "
                "VALUES(?,?,?,?,?)",
                (str(p), i, mt, c, json.dumps(vecs[i]) if vecs else None))
        changed += 1
    store.db.commit()
    return changed


def _cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(x * x for x in b)) or 1.0
    return num / (da * db)


async def query(cfg: dict, store, q: str, limit: int = 8) -> list[dict]:
    """Top chunks for q: semantic when embeddings exist, substring otherwise.
    Returns [{path, snippet, score, kind}]."""
    q = (q or "").strip()
    if not q:
        return []
    _ensure_table(store)
    try:
        await asyncio.wait_for(refresh(cfg, store), timeout=8)
    except Exception:
        pass
    rows = store.db.execute(
        "SELECT path, chunk, text, embedding FROM search_index").fetchall()
    if not rows:
        return []
    qv = None
    try:
        vecs = await asyncio.wait_for(knowledge.embed_texts(cfg, [q]), timeout=6)
        qv = vecs[0] if vecs else None
    except Exception:
        qv = None
    scored = []
    ql = q.lower()
    for r in rows:
        s = 0.0
        if qv is not None and r["embedding"]:
            try:
                s = _cos(qv, json.loads(r["embedding"]))
            except Exception:
                s = 0.0
        if ql in r["text"].lower():
            s += 0.25                                # exact mention still counts
        if s > 0.05:
            scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    out, seen_paths = [], set()
    for s, r in scored:
        if len(out) >= limit:
            break
        i = r["text"].lower().find(ql)
        snippet = (r["text"][max(0, i - 60):i + 160] if i >= 0 else r["text"][:220]).strip()
        out.append({"path": r["path"], "snippet": snippet,
                    "score": round(s, 3),
                    "kind": "doc" if "/docs/" in r["path"] else "file",
                    "duplicate": r["path"] in seen_paths})
        seen_paths.add(r["path"])
    return out


_index_ts = 0.0


async def maintenance_tick(cfg: dict, store) -> None:
    """Called from the knowledge maintenance loop: keep the index warm while idle."""
    global _index_ts
    if time.time() - _index_ts < 300:
        return
    _index_ts = time.time()
    try:
        await knowledge.wait_model_idle()
        await refresh(cfg, store)
    except Exception:
        pass
