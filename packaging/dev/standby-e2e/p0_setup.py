# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Phase 0: a laptop with a life (provider, vault secret, Telegram, schedule, mission,
memories, facts, a skill, an agent, a chat, a workspace file) and a fresh cloud container."""
import json, subprocess, time, shutil
from h import *

shutil.rmtree(LHOME, ignore_errors=True)
LAG.mkdir(parents=True)
(LHOME / "AgentOS").mkdir()
(LHOME / "AgentOS" / "laptop-deck.md").write_text("# made on the laptop\n")
cfg = {"setup_complete": True, "agent_name": "Aria", "engine": "aria", "default_model": "custom/fake-1",
       "providers": {"custom": {"enabled": True, "base_url": f"http://{HOSTIP}:9301/v1", "api_key": "", "models": ["fake-1"]}},
       "telegram": {"enabled": True, "bot_token": "123456:TESTTOKEN", "owner_chat_id": 777},
       "autonomy": "balanced", "pricing_skip": ["custom/fake-1"]}
(LAG / "config.json").write_text(json.dumps(cfg))
laptop_kill()
laptop_start()
# a secret in the vault, the way a mail password is kept
r = subprocess.run([f"{REPO}/.venv/bin/python", "-c", "from agentos import vault; print(vault.put('mail.password','s3cret-mail-pw'))"],
                   cwd=REPO, env=lenv(), capture_output=True, text=True)
say("vault put:", r.stdout.strip() or r.stderr[-300:])
for m in ("Piyush prefers short answers", "The launch is on the 14th", "Board meeting every Monday"):
    lpost("/api/memories", json={"content": m})
for s, rel, o in (("Accacia", "builds", "Bento"), ("Bento", "runs on", "Raspberry Pi"), ("Piyush", "founded", "Accacia")):
    lpost("/api/kg", json={"subject": s, "relation": rel, "object": o})
say("skill:", lpost("/api/skills", json={"name": "weekly-summary", "description": "Summarise the week", "content": "List what happened."}).json())
say("agent:", lpost("/api/subagents", json={"name": "scout", "description": "Looks things up", "persona": "You look things up.", "tools": ["fetch_url"]}).text[:120])
say("schedule:", lpost("/api/tasks", json={"prompt": "Say the time in one line", "schedule_type": "interval", "interval_minutes": 1}).json())
(LHOME / "AgentOS" / "inbox").mkdir()
r = subprocess.run([f"{REPO}/.venv/bin/python", "-m", "agentos", "job", "add", "folder-watch", "--folder", str(LHOME / "AgentOS" / "inbox")],
                   cwd=REPO, env=lenv(), capture_output=True, text=True)
say("mission:", (r.stdout + r.stderr).strip().splitlines()[-1:])
cid, ans = chat(LURL, "hello from the laptop desk")
say("chat:", cid, ans[:80])
u = tg_inject("hi from my phone (laptop era)")
say("telegram:", tg_wait_reply("hi from my phone (laptop era)"))
cloud_start(fresh=True)
say("counts laptop:", json.dumps(counts_local(LAG))[:300])
