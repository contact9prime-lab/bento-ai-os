# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Phase 8: a laptop with two accounts (isolated by directory) moves to a fresh cloud.
Accounts are the lock on the cloud too; each person sees only their own work."""
import json, re, shutil, subprocess
from pathlib import Path
import h
from h import *
h.LHOME = E / "family-user"; h.LAG = h.LHOME / ".agentos"; h.LPORT = 8981; h.LURL = "http://127.0.0.1:8981"
h.CNAME = "bento-cloud2"; h.CPORT = 8982; h.CURL = f"http://{HOSTIP}:8982"
LURL, CURL = h.LURL, h.CURL
subprocess.run(["docker", "stop", "bento-cloud"], capture_output=True)
shutil.rmtree(h.LHOME, ignore_errors=True); h.LAG.mkdir(parents=True)
cfg = {"setup_complete": True, "agent_name": "Aria", "engine": "aria", "default_model": "custom/fake-1",
       "providers": {"custom": {"enabled": True, "base_url": f"http://{HOSTIP}:9301/v1", "api_key": "", "models": ["fake-1"]}},
       "pricing_skip": ["custom/fake-1"]}
(h.LAG / "config.json").write_text(json.dumps(cfg))
for name, role in (("ada", "admin"), ("bob", "executor")):
    r = subprocess.run([f"{REPO}/.venv/bin/python", "-m", "agentos", "user", "add", name, "--role", role, "--password", f"{name}-password-1"],
                       cwd=REPO, env=h.lenv(), capture_output=True, text=True)
    say("user add", name, (r.stdout + r.stderr).strip().splitlines()[-1:])
for ucfg in h.LAG.glob("users/*/config.json"):
    d = json.loads(ucfg.read_text()); d["pricing_skip"] = ["custom/fake-1"]; d["default_model"] = "custom/fake-1"; ucfg.write_text(json.dumps(d))
for udir in h.LAG.glob("users/*"):
    if not (udir / "config.json").exists():
        (udir / "config.json").write_text(json.dumps({"pricing_skip": ["custom/fake-1"], "default_model": "custom/fake-1"}))
h.laptop_start("family.log")

def signin(base, user):
    c = httpx.Client(base_url=base, timeout=60)
    r = c.post("/api/users/login", json={"name": user, "password": f"{user}-password-1"})
    return c, r.status_code

ada, s1 = signin(LURL, "ada"); bob, s2 = signin(LURL, "bob")
say("laptop sign-ins:", s1, s2)
say("ada chat:", h.chat(LURL, "ada's private question", cookies=dict(ada.cookies))[1][:40])
say("bob chat:", h.chat(LURL, "bob's private question", cookies=dict(bob.cookies))[1][:40])
ada.post("/api/memories", json={"content": "ada's secret plan"})
h.cloud_start(fresh=True)
out = h.cexec("/opt/agentos/.venv/bin/python", "-m", "agentos", "standby", "wait")
code = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}", out).group(0)
say("bob may not pair:", bob.post("/api/standby/pair", json={"url": CURL, "code": code}).status_code)
say("ada pairs:", ada.post("/api/standby/pair", json={"url": CURL, "code": code}).status_code)
wait_for(lambda: Cloud(CURL).get("/api/standby").json().get("copy_at"), 60, 2, "first copy")
say("bob may not move:", bob.post("/api/standby/move").status_code)
r = ada.post("/api/standby/move"); say("ada moves:", r.status_code, r.json().get("message"))
wait_for(lambda: httpx.post(CURL + "/api/users/login", json={"name": "ada", "password": "ada-password-1"}).status_code == 200, 120, 2, "cloud working")
cada, s = signin(CURL, "ada"); cbob, s2 = signin(CURL, "bob")
say("cloud sign-ins with the laptop's accounts:", s, s2)
say("cloud passphrase alone opens nothing now:", httpx.post(CURL + "/api/remote/login", json={"passphrase": CPASS}).status_code)
def titles(c):
    d = c.get("/api/conversations").json()
    d = d.get("conversations", d) if isinstance(d, dict) else d
    return [x["title"] for x in d]
say("ada sees on the cloud:", titles(cada))
say("bob sees on the cloud:", titles(cbob))
say("ada's memory on the cloud:", any("secret plan" in (m.get("content") or "") for m in (cada.get("/api/memories").json().get("memories") or [])))
say("ada chats on the cloud:", h.chat(CURL, "ada from the cloud", cookies=dict(cada.cookies))[1][:40])
say("bob may not bring it back:", bob.post("/api/standby/back").status_code)
r = ada.post("/api/standby/back"); say("ada brings it back:", r.status_code)
wait_for(lambda: httpx.post(LURL + "/api/users/login", json={"name": "ada", "password": "ada-password-1"}).status_code == 200
         and httpx.get(LURL + "/api/standby").status_code in (200, 401), 120, 2, "laptop back")
time.sleep(3)
ada, _ = signin(LURL, "ada"); bob, _ = signin(LURL, "bob")
say("ada on the laptop:", titles(ada)); say("bob on the laptop:", titles(bob))
h.laptop_kill()
subprocess.run(["docker", "rm", "-f", "bento-cloud2"], capture_output=True)
