"""What this OS costs a small machine — measured, then held to it.

A Raspberry Pi is the deployment where a standing agent earns its keep, and it is
also the one with 1 GB of RAM and an SD card that wears out. Three things here
were expensive for reasons that had nothing to do with the work being done:

  · the MCP catalogue — 21,811 servers, 11.9 MB of JSON, +35 MB of RSS once
    parsed — was downloaded at boot and held forever, for an app most installs
    never open, and re-synced daily with a full rewrite of the file AFTER EVERY
    PAGE (~1.3 GB written per sync)
  · every executor probe spawned `<exe> --version`, uncached, and every surface
    asks: 1.2s of wall time per `/api/executors` call on a fast machine
  · nothing in the database was ever deleted by age

None of these are leaks in the "objects pile up" sense — 1,300 turns against a
stub model settle at ~120 MB RSS and stay there. They are standing costs, which
is worse on a Pi, because they are paid whether or not anything is being used.
"""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import executors as execmod                   # noqa: E402
from agentos import mcp_store as mcp                       # noqa: E402
from agentos.memory import Store                           # noqa: E402


# --- the catalogue ---------------------------------------------------------

@pytest.fixture()
def index(tmp_path, monkeypatch):
    p = tmp_path / "mcp_index.json"
    monkeypatch.setattr(mcp, "INDEX_PATH", p)
    monkeypatch.setattr(mcp, "_index", None)
    monkeypatch.setattr(mcp, "_syncing", False)
    return p


def test_boot_does_not_fetch_a_catalogue_nobody_asked_for(index, monkeypatch):
    """`only_refresh` is what the server calls at startup. With no index on disk
    it must do nothing at all — no download, no 35 MB of parsed JSON."""
    started = []
    monkeypatch.setattr(mcp.asyncio, "create_task", lambda c: started.append(c))
    assert mcp.ensure_index(only_refresh=True) is False
    assert not started


def test_boot_does_not_even_parse_a_fresh_index(index, monkeypatch):
    """Deciding "is it stale?" by loading the file would allocate the whole
    catalogue at boot, which is the cost this path exists to avoid."""
    index.write_text(json.dumps({"updated_at": time.time(), "complete": True,
                                 "servers": [{"registry_name": "x"}]}))
    loaded = []
    monkeypatch.setattr(mcp, "_load_index", lambda: loaded.append(1) or {})
    assert mcp.ensure_index(only_refresh=True) is False
    assert not loaded, "the index was parsed just to decide it was fresh"


def test_a_search_still_syncs_on_first_use(index, monkeypatch):
    started = []
    monkeypatch.setattr(mcp.asyncio, "create_task", lambda c: started.append(c) or c)
    monkeypatch.setattr(mcp.asyncio, "get_running_loop", lambda: object())
    assert mcp.ensure_index() is True
    assert started
    for c in started:                       # never awaited — close the coroutine
        c.close()


def test_the_catalogue_is_released_when_nobody_is_searching(index):
    index.write_text(json.dumps({"updated_at": time.time(), "complete": True,
                                 "servers": [{"registry_name": f"s{i}"} for i in range(500)]}))
    assert len(mcp._load_index()["servers"]) == 500
    assert mcp.release_if_idle() == 0            # just used — kept
    mcp._touched -= mcp.IDLE_RELEASE + 1
    assert mcp.release_if_idle() == 500          # idle — dropped
    assert mcp._index is None
    assert len(mcp._load_index()["servers"]) == 500   # and read back on demand


def test_a_sync_writes_the_file_a_handful_of_times_not_once_per_page(index, monkeypatch):
    """The file is the whole accumulated list, so writing per page cost roughly
    (pages / 2 x final size) of disk — over a gigabyte on the real registry,
    daily, on storage that wears out."""
    import asyncio

    pages = 40
    writes = []

    class Resp:
        def raise_for_status(self):
            pass

        def __init__(self, n):
            self.n = n

        def json(self):
            return {"servers": [{"name": f"io.x/s{self.n}-{i}", "description": "d",
                                 "packages": [{"identifier": f"p{i}", "registryType": "npm"}]}
                                for i in range(100)],
                    "metadata": {"nextCursor": str(self.n + 1) if self.n + 1 < pages else ""}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            return Resp(int((params or {}).get("cursor") or 0))

    monkeypatch.setattr(mcp.httpx, "AsyncClient", lambda *a, **k: Client())
    real_write = mcp.INDEX_PATH.write_text

    def counting_write(text):
        writes.append(len(text))
        return real_write(text)

    monkeypatch.setattr(type(mcp.INDEX_PATH), "write_text",
                        lambda self, text: counting_write(text))
    asyncio.run(mcp._sync_index())
    assert len(writes) <= 5, f"{pages} pages caused {len(writes)} full-file writes"
    assert writes, "the finished catalogue must still be saved"
    assert len(mcp._load_index()["servers"]) == pages * 100


# --- the probes ------------------------------------------------------------

def test_a_probe_is_not_a_process_every_time(monkeypatch):
    calls = []
    monkeypatch.setattr(execmod, "_probe_now",
                        lambda eid: calls.append(eid) or {"id": eid, "installed": True})
    execmod.forget_probes()
    for _ in range(20):
        execmod.probe("claude-code")
    assert len(calls) == 1, f"{len(calls)} probes for 20 asks"


def test_installing_something_drops_the_cached_answer(monkeypatch):
    calls = []
    monkeypatch.setattr(execmod, "_probe_now",
                        lambda eid: calls.append(eid) or {"id": eid, "installed": False})
    execmod.forget_probes()
    execmod.probe("hermes")
    execmod.forget_probes()          # what components.install() does on the way out
    execmod.probe("hermes")
    assert len(calls) == 2, "a fresh install must not read a stale 'not installed'"


# --- retention -------------------------------------------------------------

def old(days):
    return time.time() - days * 86400


def test_telemetry_is_pruned_by_age(tmp_path):
    s = Store(tmp_path / "t.db")
    for i in range(100):
        s.db.execute("INSERT INTO logs (id,kind,message,created_at) VALUES (?,?,?,?)",
                     (f"l{i}", "system", "x" * 200, old(60 if i % 2 else 1)))
        s.db.execute("INSERT INTO fabric_events (id,run_id,ts,type,payload) VALUES (?,?,?,?,?)",
                     (f"e{i}", "r", old(60 if i % 2 else 1), "step", "y" * 200))
        s.db.execute("INSERT INTO usage (id,ts,model,tokens_in,tokens_out) VALUES (?,?,?,?,?)",
                     (f"u{i}", old(400 if i % 2 else 1), "m", 1, 1))
    s.db.commit()
    gone = s.prune()
    assert gone == {"logs": 50, "fabric_events": 50, "usage": 50}
    assert s.db.execute("SELECT count(*) FROM logs").fetchone()[0] == 50


def test_the_ledger_and_the_users_own_work_are_never_pruned(tmp_path):
    """`audit` is hash-chained: deleting rows is precisely what audit_verify()
    exists to detect. Messages, memories and assets are somebody's work, and age
    is not consent to delete it."""
    s = Store(tmp_path / "t.db")
    cid = s.create_conversation("old chat")
    s.db.execute("UPDATE conversations SET created_at=?, updated_at=?", (old(999), old(999)))
    s.add_message(cid, "user", "something I said in 2019")
    s.db.execute("UPDATE messages SET created_at=?", (old(999),))
    s.db.execute("INSERT INTO audit (id,ts,uid,seq,row_hash,principal_kind,principal_id,"
                 "action,resource,effect) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 ("a1", old(999), "", 1, "h", "user", "", "tool.use", "x", "allow"))
    s.db.commit()
    s.prune(logs_days=1, events_days=1, usage_days=1)
    assert s.db.execute("SELECT count(*) FROM audit").fetchone()[0] == 1
    assert s.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    assert s.db.execute("SELECT count(*) FROM conversations").fetchone()[0] == 1


def test_zero_days_means_keep_it_forever(tmp_path):
    """A machine somebody is debugging must be able to switch retention off
    without editing code."""
    s = Store(tmp_path / "t.db")
    s.db.execute("INSERT INTO logs (id,kind,message,created_at) VALUES ('l','system','x',?)",
                 (old(9999),))
    s.db.commit()
    assert s.prune(logs_days=0, events_days=0, usage_days=0) == {}
    assert s.db.execute("SELECT count(*) FROM logs").fetchone()[0] == 1


def test_a_prune_actually_gives_the_disk_back(tmp_path):
    """Deleting rows without checkpointing the WAL can leave the directory
    BIGGER than it was, which reads as retention doing nothing."""
    s = Store(tmp_path / "t.db")
    for i in range(4000):
        s.db.execute("INSERT INTO logs (id,kind,message,created_at) VALUES (?,?,?,?)",
                     (f"l{i}", "system", "x" * 600, old(60)))
    s.db.commit()
    before = s.db_bytes()
    assert s.prune()["logs"] == 4000
    assert s.db_bytes() < before
