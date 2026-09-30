# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Phase 3: the laptop comes back and takes the work back before anything starts."""
import json
from h import *
c = Cloud()
c.get("/api/config")
cloud_before = counts_cloud()
cloud_titles = conv_titles_cloud()
cexec("sh", "-c", "echo 'made in the cloud' > /root/AgentOS/cloud-note.md")
took = laptop_start(f"laptop-back-{int(time.time())}.log")
say("laptop start (incl. bringing the work back):", f"{took:.1f}s")
lg = sorted(E.glob("laptop-back-*.log"))[-1].read_text()
say("laptop said:", [l.strip() for l in lg.splitlines() if "▲" in l and ("working" in l or "back" in l)][:3])
after = counts_local(LAG)
real, noisy = diff(cloud_before, after, "cloud", "laptop")
say("tables that differ cloud→laptop (not diaries):", real or "none")
missing = [t for t in cloud_titles if t not in conv_titles_local()]
say("conversations from the cloud missing on the laptop:", missing or "none")
say("cloud file on laptop:", (LHOME / "AgentOS" / "cloud-note.md").read_text().strip() if (LHOME / "AgentOS" / "cloud-note.md").exists() else "MISSING",
    "| laptop-deck:", (LHOME / "AgentOS" / "laptop-deck.md").exists(),
    "| nested:", (LHOME / "AgentOS" / "workspace").exists())
r = subprocess.run([f"{REPO}/.venv/bin/python", "-c", "from agentos import vault; print(vault.get('mail.password','e2e'))"], cwd=REPO, env=lenv(), capture_output=True, text=True)
say("vault on laptop:", r.stdout.strip() or r.stderr[-200:])
say("laptop config workspace:", lget("/api/config").json().get("workspace"))
say("laptop remote door:", (lget("/api/config").json().get("remote") or {}).get("enabled"))
time.sleep(6)
c = Cloud()
say("cloud now:", c.get("/api/config").status_code, {k: v for k, v in c.get("/api/standby").json().items() if k in ("active", "holds_work", "epoch")})
say("telegram polls last 6s:", polls_since(6))
say("telegram:", tg_wait_reply(tg_inject("back home? (3)") and "back home? (3)"))
say("chat on laptop:", chat(LURL, "am I home?"))
say("laptop standby:", {k: v for k, v in lstatus().items() if k in ("active", "epoch", "last_swap", "last_error")})
