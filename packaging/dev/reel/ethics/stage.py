"""Start the ethics reel's world: a throwaway home, the stand-in brain and a real `bento serve`.

Imported by film.py. Nothing here touches ~/.agentos: the home is REEL_HOME (a temp folder).
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PY = str(ROOT / ".venv" / "bin" / "python")
HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("REEL_PORT", 8631))
BRAIN = int(os.environ.get("REEL_BRAIN", 9431))


def up(home: Path):
    shutil.rmtree(home, ignore_errors=True)
    work = home / "work"
    (work / "photos").mkdir(parents=True)
    for i in range(1, 641):
        (work / "photos" / f"IMG_{i:04d}.jpg").write_bytes(b"\xff\xd8" + os.urandom(2400))
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True,
        "default_model": "custom/fake-1", "workspace": str(work), "autonomy": "full",
        "pricing": {"custom/fake-1": {"in": 0, "out": 0}},
        "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1",
                                 "api_key": "", "models": ["fake-1"]}}}))
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost")
    logs = home / "logs"
    logs.mkdir()
    brain = subprocess.Popen([PY, str(HERE / "brain.py"), str(BRAIN)], env=env,
                             stdout=open(logs / "brain.log", "w"), stderr=subprocess.STDOUT)
    srv = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser",
                            "--if-running", "fail"], env=env, cwd=ROOT,
                           stdout=open(logs / "server.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/platform", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    return [brain, srv], f"http://127.0.0.1:{PORT}"


def down(procs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
