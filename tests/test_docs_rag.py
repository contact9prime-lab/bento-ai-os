"""Answering questions about AgentOS from AgentOS's own manual.

The gap this closes: the manual shipped on disk and was readable in the Docs
app, but it was not in the retrieval corpus — so an agent asked "how do I scope
a grant to Telegram?" could only answer from its memory of projects it has read
elsewhere. The answer is in docs/security.md, on this machine.
"""

import asyncio
import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import search                     # noqa: E402
from agentos.memory import Store               # noqa: E402
from agentos.tools import TOOL_SCHEMAS, Toolbox  # noqa: E402


def test_the_manual_is_part_of_the_corpus(tmp_path):
    shipped = search.shipped_docs_dir()
    assert shipped and (shipped / "security.md").is_file(), shipped
    assert shipped in search._corpus_dirs({"workspace": str(tmp_path)})


def test_the_agent_is_given_a_way_to_read_it():
    schema = next((t for t in TOOL_SCHEMAS if t["name"] == "search_docs"), None)
    assert schema, "search_docs is not registered"
    assert "query" in schema["parameters"]["required"]
    # The description is the only thing steering the model toward retrieving
    # rather than recalling, so it has to actually say so.
    d = schema["description"].lower()
    assert "manual" in d and "memory" in d


def test_a_miss_says_so_instead_of_inventing(tmp_path, monkeypatch):
    """An unsourced answer about a permission model is worse than no answer, so a
    search that finds nothing must not read as an invitation to improvise."""
    async def nothing(cfg, store, q, limit=8):
        return []
    monkeypatch.setattr(search, "query", nothing)
    store = Store(tmp_path / "t.db")
    tb = Toolbox({"workspace": str(tmp_path), "policies": []}, store)
    out = asyncio.run(tb.search_docs("how do I fly to the moon"))
    assert out.startswith("[no match]")
    assert "not documented" in out


def test_passages_come_back_named_so_the_answer_can_be_checked(tmp_path, monkeypatch):
    async def hits(cfg, store, q, limit=8):
        return [{"path": "/x/docs/security.md", "snippet": "IO gates scope a grant",
                 "score": 0.9, "kind": "doc"},
                {"path": "/x/ws/notes.md", "snippet": "my own file", "score": 0.8,
                 "kind": "file"}]
    monkeypatch.setattr(search, "query", hits)
    store = Store(tmp_path / "t.db")
    tb = Toolbox({"workspace": str(tmp_path), "policies": []}, store)
    out = asyncio.run(tb.search_docs("io gates"))
    assert "security.md" in out and "IO gates scope a grant" in out
    assert "notes.md" not in out, "asking the manual must not return the user's own files"
