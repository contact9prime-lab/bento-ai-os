"""A free cloud machine keeps its memory in the person's own storage bucket, sealed.

Asked for as "ensure that you are able to deploy the agent in the cloud free and make it
work", and then: "you can't be storing memories on GitHub". Render's free plan wipes the
disk on every restart, so keep.py seals the home (the backup format) and puts it in an
S3-compatible bucket the person owns (Backblaze B2, Cloudflare R2, Tigris…), bringing it
back into an empty home on start. These run against packaging/dev/free-cloud/fake_s3.py,
which checks every request's signature the way a real service does.
"""
import datetime as dt
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
def s3(monkeypatch):
    spec = importlib.util.spec_from_file_location("fake_s3", ROOT / "packaging/dev/free-cloud/fake_s3.py")
    fake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fake)
    srv = fake.serve(0)
    monkeypatch.setenv(keep.ENV_ENDPOINT, f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv(keep.ENV_BUCKET, "bento-test")
    monkeypatch.setenv(keep.ENV_KEY_ID, fake.KEY_ID)
    monkeypatch.setenv(keep.ENV_SECRET, fake.SECRET)
    monkeypatch.delenv(keep.ENV_REGION, raising=False)
    monkeypatch.setenv("AGENTOS_PASSPHRASE", PW)
    monkeypatch.delenv("AGENTOS_PASSPHRASE_FILE", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
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


def test_the_signature_is_aws_signature_version_4():
    # AWS's own published example (S3 API reference, "GET Object"), so the signer is not
    # only checked against a stand-in written by the same hand.
    h = keep._sign("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"range": "bytes=0-9"},
                   keep.EMPTY_SHA, "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                   "us-east-1", dt.datetime(2013, 5, 24, tzinfo=dt.timezone.utc))
    assert h["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")


def test_a_wiped_disk_gets_its_memory_back(tmp_path, s3):
    first = _home(tmp_path, "first", "my favourite colour is teal")
    r = keep.save(first)
    assert r["saved"] and r["bytes"] > 0
    objs = s3.BUCKETS["bento-test"]
    assert set(objs) == {"bento-home/index.json", "bento-home/a.bento"}
    assert all(b"teal" not in v for v in objs.values()), "the bucket holds the sealed file, never the memory"

    fresh = tmp_path / "fresh"          # the next start on Render: an empty disk
    fresh.mkdir()
    (fresh / "config.json").write_text("{}")     # the entrypoint's remote lock, written first
    r = keep.restore(fresh, echo=None)
    assert r["restored"]
    assert _memories(fresh) == ["my favourite colour is teal"]
    assert keep.status(fresh)["restored_at"]


def test_a_save_writes_the_other_slot_so_the_copy_before_stays_whole(tmp_path, s3, monkeypatch):
    h = _home(tmp_path, "h", "one")
    keep.save(h)
    assert keep.save(h) == {"saved": False, "why": "nothing changed"}
    before = s3.BUCKETS["bento-test"]["bento-home/a.bento"]
    con = sqlite3.connect(h / "agentos.db")
    con.execute("insert into memories values ('two')")
    con.commit()
    con.close()
    monkeypatch.setattr(keep, "MIN_GAP_S", 0)
    assert keep.save(h)["saved"]
    objs = s3.BUCKETS["bento-test"]
    assert objs["bento-home/a.bento"] == before, "the previous copy is left as it was"
    assert json.loads(objs["bento-home/index.json"])["slot"] == "b.bento"
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    keep.restore(fresh, echo=None)
    assert _memories(fresh) == ["one", "two"]


def test_a_home_that_kept_its_disk_is_never_rolled_back(tmp_path, s3):
    keep.save(_home(tmp_path, "old", "old memory"))
    here = _home(tmp_path, "here", "newer memory on a disk that survived")
    assert keep.restore(here, echo=None) == {"restored": False, "why": "this home is not empty"}
    assert _memories(here) == ["newer memory on a disk that survived"]


def test_a_copy_sealed_with_another_password_is_left_alone(tmp_path, s3, monkeypatch):
    keep.save(_home(tmp_path, "old", "sealed with the old password"))
    before = dict(s3.BUCKETS["bento-test"])
    monkeypatch.setenv("AGENTOS_PASSPHRASE", "a-brand-new-passphrase-99")
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    r = keep.restore(fresh, echo=None)
    assert r == {"restored": False, "why": "another password", "prefix": "bento-home"}
    assert "another password" in keep.status(fresh)["restore_note"]
    (fresh / "agentos.db").write_bytes(b"")
    keep.save(fresh, force=True)
    objs = s3.BUCKETS["bento-test"]
    assert {k: objs[k] for k in before} == before, "the copy that could not be opened is untouched"
    assert any(k.startswith("bento-home-") and k.endswith("/index.json") for k in objs), "saves go to a new place"
    # and the next start finds the newer one, which this password opens
    again = tmp_path / "again"
    again.mkdir()
    assert keep.restore(again, echo=None)["restored"]


def test_listing_follows_the_pages(tmp_path, s3):
    for i in range(5):                                # more objects than one page of the stand-in
        s3.BUCKETS["bento-test"][f"bento-home-other/{i}.txt"] = b"x"
    keep.save(_home(tmp_path, "h", "paged"))
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert keep.restore(fresh, echo=None)["restored"]


def test_each_refusal_says_what_to_fix(tmp_path, s3, monkeypatch):
    h = _home(tmp_path, "h", "x")
    monkeypatch.setenv(keep.ENV_SECRET, "wrong")
    with pytest.raises(keep.KeepError, match="refused the key"):
        keep.save(h)
    assert "refused the key" in keep.status(h)["line"]
    monkeypatch.setenv(keep.ENV_SECRET, s3.SECRET)
    monkeypatch.setenv(keep.ENV_BUCKET, "not-there")
    with pytest.raises(keep.KeepError, match="no bucket named not-there"):
        keep.save(h, force=True)
    monkeypatch.delenv(keep.ENV_KEY_ID)
    st = keep.status(h)
    assert st["kind"] == "err" and keep.ENV_KEY_ID in st["line"]
    with pytest.raises(keep.KeepError, match="not fully set"):
        keep.restore(tmp_path / "h", echo=None)


def test_what_a_person_pastes_is_read_kindly(monkeypatch):
    for name in keep.ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(keep.ENV_ENDPOINT, "s3.us-west-004.backblazeb2.com")
    monkeypatch.setenv(keep.ENV_BUCKET, "bento-ada")
    s = keep.storage()
    assert s["base"] == "https://s3.us-west-004.backblazeb2.com" and s["region"] == "us-west-004"
    assert keep.where() == "your Backblaze B2 bucket bento-ada"
    # R2 shows its endpoint with the bucket on the end
    monkeypatch.setenv(keep.ENV_ENDPOINT, "https://abc123.r2.cloudflarestorage.com/bento-ada")
    s = keep.storage()
    assert (s["base"], s["bucket"], s["region"]) == ("https://abc123.r2.cloudflarestorage.com", "bento-ada", "auto")
    monkeypatch.delenv(keep.ENV_BUCKET)
    assert keep.storage()["bucket"] == "bento-ada"
    # Supabase's endpoint has a path of its own, which is kept
    monkeypatch.setenv(keep.ENV_ENDPOINT, "https://ref.storage.supabase.co/storage/v1/s3")
    monkeypatch.setenv(keep.ENV_BUCKET, "b")
    assert keep.storage()["base"] == "https://ref.storage.supabase.co/storage/v1/s3"


def test_no_storage_on_a_host_that_forgets_is_said_plainly(tmp_path, monkeypatch):
    for name in keep.ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(keep.ENV_EPHEMERAL, "1")
    st = keep.status(tmp_path)
    assert st["kind"] == "warn" and "forgets everything when it restarts" in st["line"]
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


def test_the_providers_say_what_is_free_and_where_the_endpoint_is():
    assert keep.PROVIDERS[0]["id"] == "b2" and keep.PROVIDERS[0]["recommended"]
    for p in keep.PROVIDERS:
        assert p["name"] and p["endpoint"] and p["steps"]
    assert not any("github" in json.dumps(p).lower() for p in keep.PROVIDERS)


def test_the_free_blueprint_asks_for_the_bucket_and_says_it_forgets_otherwise():
    import yaml
    (svc,) = yaml.safe_load((ROOT / "render.yaml").read_text())["services"]
    assert svc["plan"] == "free" and "disk" not in svc
    env = {e["key"]: e for e in svc["envVars"]}
    for name in keep.ENVS:
        assert env[name].get("sync") is False and "value" not in env[name], name
    assert env[keep.ENV_EPHEMERAL]["value"] == "1" and env[keep.ENV_AWAKE]["value"] == "1"
    sh = (ROOT / "packaging/docker-entrypoint.sh").read_text()
    assert sh.index("bento keep restore") < sh.index("bento remote --on"), \
        "the memory comes back before anything else writes to the home"


def test_nothing_is_kept_on_github_any_more():
    src = (ROOT / "agentos/keep.py").read_text().lower()
    assert "api.github.com" not in src and "github_token" not in src
    assert not (ROOT / "packaging/dev/free-cloud/fake_github.py").exists()
    assert "GITHUB" not in (ROOT / "render.yaml").read_text().upper().replace("GITHUB.COM", "")
