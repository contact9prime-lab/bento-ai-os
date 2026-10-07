"""A free cloud machine keeps its memory in the person's own GitHub, sealed.

Asked for as "ensure that you are able to deploy the agent in the cloud free and make it
work". Render's free plan wipes the disk on every restart, so keep.py seals the home (the
backup format) into a secret gist and brings it back into an empty home on start. These
run against packaging/dev/free-cloud/fake_github.py, which truncates large files the way
GitHub's API does, so the raw-file path is exercised too.
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentos import keep                                           # noqa: E402

PW = "indigo-tundra-harbor-saffron-46"


@pytest.fixture()
def gh(monkeypatch):
    spec = importlib.util.spec_from_file_location("fake_github", ROOT / "packaging/dev/free-cloud/fake_github.py")
    fake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fake)
    srv = fake.serve(0)
    monkeypatch.setenv(keep.ENV_API, f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv(keep.ENV_TOKEN, fake.TOKEN)
    monkeypatch.setenv("AGENTOS_PASSPHRASE", PW)
    monkeypatch.delenv("AGENTOS_PASSPHRASE_FILE", raising=False)
    yield fake
    srv.shutdown()


def _home(tmp_path, name, memory=""):
    h = tmp_path / name
    h.mkdir()
    (h / "config.json").write_text(json.dumps({"agent_name": "Aria", "setup_complete": True}))
    if memory:
        con = sqlite3.connect(h / "agentos.db")
        con.execute("create table memories (content text)")
        con.execute("insert into memories values (?)", (memory,))
        con.commit()
        con.close()
    return h


def _memories(h):
    con = sqlite3.connect(h / "agentos.db")
    try:
        return [r[0] for r in con.execute("select content from memories")]
    finally:
        con.close()


def test_a_wiped_disk_gets_its_memory_back(tmp_path, gh):
    first = _home(tmp_path, "first", "my favourite colour is teal")
    r = keep.save(first)
    assert r["saved"] and r["bytes"] > 0
    (g,) = gh.GISTS.values()
    assert g["public"] is False and g["description"].startswith(keep.DESC)
    assert "teal" not in json.dumps(g["files"]), "the gist holds the sealed file, never the memory itself"

    fresh = tmp_path / "fresh"          # the next start on Render: an empty disk
    fresh.mkdir()
    (fresh / "config.json").write_text("{}")     # the entrypoint's remote lock, written first
    r = keep.restore(fresh, echo=None)
    assert r["restored"]
    assert _memories(fresh) == ["my favourite colour is teal"]
    assert keep.status(fresh)["restored_at"]


def test_a_home_that_kept_its_disk_is_never_rolled_back(tmp_path, gh):
    keep.save(_home(tmp_path, "old", "old memory"))
    here = _home(tmp_path, "here", "newer memory on a disk that survived")
    assert keep.restore(here, echo=None) == {"restored": False, "why": "this home is not empty"}
    assert _memories(here) == ["newer memory on a disk that survived"]


def test_nothing_changed_means_nothing_sent_and_a_change_updates_the_same_gist(tmp_path, gh, monkeypatch):
    h = _home(tmp_path, "h", "one")
    keep.save(h)
    assert keep.save(h) == {"saved": False, "why": "nothing changed"}
    con = sqlite3.connect(h / "agentos.db")
    con.execute("insert into memories values ('two')")
    con.commit()
    con.close()
    monkeypatch.setattr(keep, "MIN_GAP_S", 0)
    assert keep.save(h)["saved"]
    assert len(gh.GISTS) == 1, "a change patches the gist it already has"


def test_a_big_home_goes_in_parts_and_comes_back_through_the_raw_files(tmp_path, gh, monkeypatch):
    monkeypatch.setattr(keep, "PART_RAW", 900 * 1024)       # several parts, each over the 1 MB API cut once encoded
    h = _home(tmp_path, "big", "big one")
    ws = h / "workspace"
    ws.mkdir()
    import os
    (ws / "deck.bin").write_bytes(os.urandom(3 << 20))
    cfg = json.loads((h / "config.json").read_text())
    cfg["workspace"] = str(ws)
    (h / "config.json").write_text(json.dumps(cfg))
    r = keep.save(h)
    (g,) = gh.GISTS.values()
    parts = [n for n in g["files"] if n.startswith("part-")]
    assert len(parts) >= 3 and any(len(c) > gh.TRUNC for c in g["files"].values())
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert keep.restore(fresh, echo=None)["restored"]
    assert _memories(fresh) == ["big one"]
    # a smaller save afterwards removes the parts it no longer has
    (ws / "deck.bin").unlink()
    monkeypatch.setattr(keep, "MIN_GAP_S", 0)
    keep.save(h)
    assert len([n for n in g["files"] if n.startswith("part-")]) < len(parts)
    assert r["saved"]


def test_a_copy_sealed_with_another_password_is_left_alone(tmp_path, gh, monkeypatch):
    keep.save(_home(tmp_path, "old", "sealed with the old password"))
    (old,) = gh.GISTS.values()
    before = json.dumps(old["files"])
    monkeypatch.setenv("AGENTOS_PASSPHRASE", "a-brand-new-passphrase-99")
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    r = keep.restore(fresh, echo=None)
    assert r == {"restored": False, "why": "another password", "gist": old["id"]}
    assert "another password" in keep.status(fresh)["restore_note"]
    (fresh / "agentos.db").write_bytes(b"")
    keep.save(fresh, force=True)
    assert len(gh.GISTS) == 2, "the next save makes a new gist"
    assert json.dumps(old["files"]) == before, "the copy that could not be opened is untouched"


def test_a_bad_key_says_so_in_words(tmp_path, gh, monkeypatch):
    monkeypatch.setenv(keep.ENV_TOKEN, "expired")
    with pytest.raises(keep.KeepError, match="refused the key"):
        keep.save(_home(tmp_path, "h", "x"))
    assert "refused the key" in keep.status(tmp_path / "h")["line"]


def test_no_key_on_a_host_that_forgets_is_said_plainly(tmp_path, monkeypatch):
    monkeypatch.delenv(keep.ENV_TOKEN, raising=False)
    monkeypatch.setenv(keep.ENV_EPHEMERAL, "1")
    st = keep.status(tmp_path)
    assert st["kind"] == "warn" and "forgets everything when it restarts" in st["line"]
    assert st["token_link"].endswith("scopes=gist&description=Bento%20cloud%20memory")
    monkeypatch.delenv(keep.ENV_EPHEMERAL)
    assert keep.status(tmp_path)["line"] == ""


def test_keep_awake_is_opt_in_and_goes_through_the_front_door(monkeypatch):
    monkeypatch.delenv(keep.ENV_AWAKE, raising=False)
    monkeypatch.setenv(keep.ENV_URL, "https://bento-x.onrender.com")
    assert keep.awake_url() == ""
    monkeypatch.setenv(keep.ENV_AWAKE, "1")
    assert keep.awake_url() == "https://bento-x.onrender.com/login"


def test_the_keep_folder_is_never_sealed_or_moved():
    from agentos import backup
    assert backup._private(keep.DIR)


def test_the_free_blueprint_keeps_the_memory_and_says_it_forgets_otherwise():
    import yaml
    (svc,) = yaml.safe_load((ROOT / "render.yaml").read_text())["services"]
    assert svc["plan"] == "free" and "disk" not in svc
    env = {e["key"]: e for e in svc["envVars"]}
    assert env[keep.ENV_TOKEN].get("sync") is False and "value" not in env[keep.ENV_TOKEN]
    assert env[keep.ENV_EPHEMERAL]["value"] == "1" and env[keep.ENV_AWAKE]["value"] == "1"
    sh = (ROOT / "packaging/docker-entrypoint.sh").read_text()
    assert sh.index("bento keep restore") < sh.index("bento remote --on"), \
        "the memory comes back before anything else writes to the home"
