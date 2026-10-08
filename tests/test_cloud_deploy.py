"""Put Bento in the cloud: the deploy files say what the image needs, and a restart keeps you signed in.

Asked for as "deploy it quickly to the cloud … really quick and noob for anyone, so sso
and done". The one-click road is a Render blueprint (render.yaml); Fly.io has fly.toml;
`agentos/clouddeploy.py` is the one list that Settings, `bento cloud` and the docs read.

Two things the container run found, pinned here:
- A host hands the container its PORT and routes only to it. The entrypoint read only
  AGENTOS_PORT, so a Render deploy listened on 8321 while traffic went to 10000.
- The entrypoint sets the passphrase on every start, and `bento remote --passphrase`
  salted it afresh each time. Sessions are signed with that hash, so every restart (each
  redeploy) signed everybody out.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentos import clouddeploy                                    # noqa: E402
from agentos import remote as remotemod                            # noqa: E402


def _image_home():
    for line in (ROOT / "Dockerfile").read_text().splitlines():
        if line.startswith("ENV AGENTOS_HOME="):
            return line.split("=", 1)[1].strip()
    raise AssertionError("the Dockerfile no longer says where the home is")


def _open_paths():
    from agentos import server
    return server.REMOTE_OPEN_PATHS


def test_the_render_blueprint_keeps_the_home_and_asks_for_the_password():
    bp = yaml.safe_load((ROOT / "render.yaml").read_text())
    (svc,) = bp["services"]
    assert svc["type"] == "web" and svc["runtime"] == "docker"
    assert (ROOT / svc["dockerfilePath"]).is_file()
    env = {e["key"]: e for e in svc["envVars"]}
    # The free plan has no disk, so the home must be kept elsewhere (keep.py); a paid
    # plan keeps it on a disk at the image's home.
    if svc["plan"] == "free":
        assert "disk" not in svc and env["BENTO_STORAGE_BUCKET"].get("sync") is False
    else:
        assert svc["disk"]["mountPath"] == _image_home()
    pw = env[clouddeploy.PASSPHRASE_ENV]
    assert pw.get("sync") is False and "value" not in pw, \
        "the password is asked for on the deploy page and never written in the file"
    assert svc["healthCheckPath"] == clouddeploy.HEALTH_PATH
    assert clouddeploy.HEALTH_PATH.startswith(_open_paths()), \
        "the health check must answer without a session"


def test_the_fly_config_keeps_the_home_and_stays_awake():
    # tomllib is 3.11+; on 3.10 (still supported) this one check is skipped rather than
    # stopping the whole file from being collected, which is what failed CI.
    tomllib = pytest.importorskip("tomllib")
    fly = tomllib.loads((ROOT / "fly.toml").read_text())
    assert fly["mounts"]["destination"] == _image_home()
    hs = fly["http_service"]
    assert str(hs["internal_port"]) == fly["env"]["AGENTOS_PORT"]
    assert hs["force_https"] is True
    # missions, schedules and Telegram need it awake; a request-woken machine misses them
    assert hs["auto_stop_machines"] == "off" and hs["min_machines_running"] >= 1
    assert hs["checks"][0]["path"] == clouddeploy.HEALTH_PATH


def test_the_entrypoint_listens_on_the_port_the_host_hands_it():
    sh = (ROOT / "packaging/docker-entrypoint.sh").read_text()
    assert 'PORT="${AGENTOS_PORT:-${PORT:-8321}}"' in sh
    out = subprocess.run(["sh", "-c", 'PORT=10000; PORT="${AGENTOS_PORT:-${PORT:-8321}}"; echo $PORT'],
                         capture_output=True, text=True).stdout.strip()
    assert out == "10000"


def test_the_options_put_the_one_click_road_first_and_all_keep_your_data():
    opts = clouddeploy.options({})
    assert opts[0]["id"] == "render" and opts[0]["recommended"] and opts[0]["free"]
    assert opts[0]["storage"][0]["id"] == "b2", "a free bucket for its memory comes first"
    assert opts[0]["url"] == "https://render.com/deploy?repo=https://github.com/contact9prime-lab/bento-ai-os"
    assert all(o["keeps"] for o in opts), "an option that forgets everything is not offered"
    assert not {o["title"] for o in opts} & set(clouddeploy.NOT_OFFERED)
    assert all(o["how"] and o["steps"] and o["costs"] for o in opts)
    # a fork deploys itself
    fork = clouddeploy.options({"updates": {"repo": "ada/bento-fork"}})
    assert "github.com/ada/bento-fork" in fork[0]["url"]


def test_a_suggested_password_is_good_enough_and_fresh_each_time():
    a, b = clouddeploy.suggest_passphrase(), clouddeploy.suggest_passphrase()
    assert not remotemod.passphrase_problem(a) and a != b


def test_bento_cloud_prints_the_same_list(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path)}
    out = subprocess.run([sys.executable, "-m", "agentos", "cloud"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60).stdout
    assert "render.com/deploy?repo=" in out and "fly deploy" in out
    js = json.loads(subprocess.run([sys.executable, "-m", "agentos", "cloud", "--json"], cwd=ROOT,
                                   env=env, capture_output=True, text=True, timeout=60).stdout)
    assert [o["id"] for o in js["options"]] == [o["id"] for o in clouddeploy.options({})]


def test_the_settings_card_reads_the_route():
    from fastapi.testclient import TestClient
    from agentos import server
    with TestClient(server.app) as cl:
        d = cl.get("/api/cloud/deploy").json()
    assert d["options"][0]["id"] == "render" and d["env"] == "AGENTOS_PASSPHRASE"
    assert not remotemod.passphrase_problem(d["passphrase"])


def test_setting_the_same_passphrase_again_keeps_everyone_signed_in(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path)}

    def remote_on(pw):
        r = subprocess.run([sys.executable, "-m", "agentos", "remote", "--on", "--passphrase", pw],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads((tmp_path / "config.json").read_text())["remote"]

    first = remote_on("indigo-tundra-harbor-saffron-46")
    again = remote_on("indigo-tundra-harbor-saffron-46")
    assert (again["pass_hash"], again["pass_salt"]) == (first["pass_hash"], first["pass_salt"]), \
        "a container restart re-sets the same passphrase; a new salt signed everyone out"
    changed = remote_on("a-brand-new-passphrase-99")
    assert changed["pass_hash"] != first["pass_hash"], "a new passphrase still rotates"
