"""Semantic search index — lazy refresh, ranking, and honest degradation."""

import asyncio
import os
import tempfile

import pytest

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import search, knowledge          # noqa: E402
from agentos.memory import Store               # noqa: E402


def _cfg(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return {"workspace": str(ws)}, ws


@pytest.fixture(autouse=True)
def _only_the_workspace(monkeypatch):
    """These tests are about indexing mechanics — chunking, mtime, eviction — so
    they count rows and need a corpus they control. The shipped manual is a real
    part of the corpus (see test_the_manual_is_part_of_the_corpus below); it just
    is not what any of these are measuring."""
    monkeypatch.setattr(search, "shipped_docs_dir", lambda: None)



def test_refresh_indexes_and_reindexes_on_mtime(tmp_path, monkeypatch):
    async def fake_embed(cfg, texts):
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(knowledge, "embed_texts", fake_embed)
    cfg, ws = _cfg(tmp_path)
    store = Store(tmp_path / "t.db")
    (ws / "notes.md").write_text("the quarterly invoice from march")
    assert asyncio.run(search.refresh(cfg, store)) == 1
    assert asyncio.run(search.refresh(cfg, store)) == 0          # unchanged → no work
    (ws / "notes.md").write_text("updated content entirely")
    os.utime(ws / "notes.md", (1e9, 2e9))
    assert asyncio.run(search.refresh(cfg, store)) == 1


def test_query_semantic_ranking(tmp_path, monkeypatch):
    vecs = {"about cats and pets": [1.0, 0.0], "about tax invoices": [0.0, 1.0]}
    async def fake_embed(cfg, texts):
        return [vecs.get(t, [0.0, 1.0]) for t in texts]
    monkeypatch.setattr(knowledge, "embed_texts", fake_embed)
    cfg, ws = _cfg(tmp_path)
    store = Store(tmp_path / "t.db")
    (ws / "cats.txt").write_text("about cats and pets")
    (ws / "tax.txt").write_text("about tax invoices")
    res = asyncio.run(search.query(cfg, store, "about tax invoices"))
    assert res and res[0]["path"].endswith("tax.txt")


def test_query_degrades_without_embeddings(tmp_path, monkeypatch):
    async def no_embed(cfg, texts):
        return None
    monkeypatch.setattr(knowledge, "embed_texts", no_embed)
    cfg, ws = _cfg(tmp_path)
    store = Store(tmp_path / "t.db")
    (ws / "plan.md").write_text("the march invoice is in this file")
    res = asyncio.run(search.query(cfg, store, "march invoice"))
    assert res and res[0]["path"].endswith("plan.md")            # substring fallback


def test_vanished_files_leave_the_index(tmp_path, monkeypatch):
    async def fake_embed(cfg, texts):
        return [[1.0] for _ in texts]
    monkeypatch.setattr(knowledge, "embed_texts", fake_embed)
    cfg, ws = _cfg(tmp_path)
    store = Store(tmp_path / "t.db")
    f = ws / "gone.txt"
    f.write_text("temporary")
    asyncio.run(search.refresh(cfg, store))
    f.unlink()
    asyncio.run(search.refresh(cfg, store))
    rows = store.db.execute("SELECT COUNT(*) c FROM search_index").fetchone()
    assert rows["c"] == 0
