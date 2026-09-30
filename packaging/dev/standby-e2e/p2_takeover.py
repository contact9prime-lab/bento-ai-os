# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Phase 2: the laptop dies; the cloud takes over and must BE the laptop."""
import json
from h import *
c = Cloud()
say("grace:", c.post("/api/standby/settings", json={"grace": 90}).json().get("grace"))
lpost("/api/standby/copy")                     # the newest state goes over first
before = counts_local(LAG)
json.dump(before, open(E / "counts_laptop_before.json", "w"))
laptop_kill()
t0 = time.time()
_, took = wait_for(lambda: Cloud().get("/api/config").status_code == 200, 400, 3, "takeover")
say(f"cloud is working {time.time()-t0:.0f}s after the laptop died")
c = Cloud()                                   # its own passphrase still opens it
say("signed in with the cloud's passphrase:", c.get("/api/config").status_code == 200)
cfg = c.get("/api/config").json()
say("config carried:", {"agent_name": cfg.get("agent_name"), "default_model": cfg.get("default_model"),
                        "telegram_on": (cfg.get("telegram") or {}).get("enabled"), "remote_on": (cfg.get("remote") or {}).get("enabled"),
                        "workspace": cfg.get("workspace"), "pricing_skip": cfg.get("pricing_skip")})
after = counts_cloud()
json.dump(after, open(E / "counts_cloud_after_takeover.json", "w"))
real, noisy = diff(before, after, "laptop", "cloud")
say("tables that differ (not counting diaries):", real or "none")
say("diary tables that differ:", noisy)
say("vault on the cloud:", cpy("from agentos import vault; print(vault.get('mail.password','e2e'))").strip())
say("workspace on the cloud:", cexec("sh", "-c", "ls /root/AgentOS; cat /root/AgentOS/laptop-deck.md").strip().replace("\n", " | "))
say("mission folder on the cloud:", cpy("import sqlite3;print(sqlite3.connect('file:/data/agentos.db?mode=ro',uri=True).execute(\"select resource from grants where resource like 'fs:%'\").fetchall())").strip())
