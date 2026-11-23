"""Is a copy of this machine kept anywhere else (offsite.py)? Asked for after a reel of incidents:
a backup on the same disk is lost with the disk. One answer for Settings, setup and the doctor."""
import json
import time
from pathlib import Path

from agentos import backup, offsite

ROOT = Path(__file__).parent.parent


def test_nothing_kept_elsewhere_is_said_with_the_three_doors(tmp_path):
    s = offsite.state(tmp_path)
    assert s["kind"] == "none" and s["level"] == "bad" and "lost" in s["line"]
    assert [d["id"] for d in s["doors"]] == ["standby", "cloud", "backup"]
    assert offsite.done(tmp_path) == (False, "")


def test_a_downloaded_backup_counts_for_a_month_and_is_never_called_safe(tmp_path):
    offsite.note_made(1234, "download", home=tmp_path)
    assert oct((tmp_path / offsite.FILE).stat().st_mode & 0o777) == "0o600"
    s = offsite.state(tmp_path)
    assert s["kind"] == "file" and s["level"] == "warn" and "another disk" in s["line"]
    assert offsite.done(tmp_path)[0]
    later = time.time() + offsite.STALE_S + 60
    s = offsite.state(tmp_path, now=later)
    assert "Make a new one" in s["line"] and not offsite.done(tmp_path, now=later)[0]
    assert any(offsite.FILE.startswith(p) for p in backup.PRIVATE), "a fact about this computer, never carried"


def test_a_standby_counts_once_it_holds_a_copy_and_warns_when_it_goes_stale(tmp_path, monkeypatch):
    from agentos import standby
    st = {"role": "primary", "peer_host": "cloud-1", "last_push": 0, "last_error": ""}
    monkeypatch.setattr(standby, "status", lambda home=None: dict(st))
    s = offsite.state(tmp_path)
    assert s["kind"] == "standby" and s["level"] == "warn" and "hasn't had a copy yet" in s["line"]
    st["last_push"] = time.time() - 600
    s = offsite.state(tmp_path)
    assert s["level"] == "ok" and "cloud-1" in s["line"] and offsite.done(tmp_path) == (True, "cloud standby")
    st["last_error"] = "the standby refused the copy"
    assert offsite.state(tmp_path)["level"] == "warn"
    monkeypatch.setattr(standby, "status", lambda home=None: {"role": "standby", "peer_host": "laptop"})
    assert offsite.state(tmp_path)["kind"] == "copy"


def test_a_bucket_counts_once_a_save_worked(tmp_path, monkeypatch):
    from agentos import keep
    ks = {"enabled": True, "saved_at": 0, "line": "Your memory will be kept in B2.", "kind": "ok"}
    monkeypatch.setattr(keep, "status", lambda home=None: dict(ks))
    assert offsite.state(tmp_path)["level"] == "warn"
    ks["saved_at"] = time.time()
    assert offsite.state(tmp_path)["level"] == "ok" and offsite.done(tmp_path) == (True, "storage bucket")


def test_every_face_reads_it():
    src = {f: (ROOT / f).read_text() for f in ("agentos/server.py", "agentos/__main__.py", "agentos/onboarding.py",
                                              "agentos/setup_tui.py", "agentos/ui/src/js/11g-backup.js",
                                              "agentos/ui/src/js/14b-onboarding.js")}
    assert src["agentos/server.py"].count("offsite.") >= 2, "the route says it and a download is recorded"
    assert "offsite.note_made" in src["agentos/__main__.py"] and "copy elsewhere:" in src["agentos/__main__.py"]
    assert '"copy"' in src["agentos/onboarding.py"] and "_step_copy" in src["agentos/setup_tui.py"]
    assert "backupOffsite" in src["agentos/ui/src/js/11g-backup.js"] and "copy(s)" in src["agentos/ui/src/js/14b-onboarding.js"]


def test_the_setup_step_is_in_both_plans_and_can_be_skipped():
    from agentos import onboarding as ob
    assert "copy" in ob.PLANS["one"] and ob.PLANS["company"].index("copy") < ob.PLANS["company"].index("account")
    assert ob.BY_ID["copy"].optional
