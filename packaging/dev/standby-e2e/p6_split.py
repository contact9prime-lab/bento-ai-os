# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Phase 6: the network splits, BOTH sides work, then it heals."""
import subprocess
from h import *
ip = cip()
direct = f"http://{ip}:8321"
lpost("/api/standby/copy")
subprocess.run(["iptables", "-I", "OUTPUT", "-p", "tcp", "-m", "conntrack", "--ctorigdst", HOSTIP, "--ctorigdstport", str(CPORT), "-j", "REJECT"], check=True)
say("laptop cut off from the cloud; harness reaches the cloud at", direct)
try:
    t = time.time()
    wait_for(lambda: Cloud(direct).get("/api/config").status_code == 200, 400, 3, "takeover")
    say(f"cloud took over {time.time()-t:.0f}s after the split")
    c = Cloud(direct)
    chat(direct, "cloud during the split", cookies=dict(c.c.cookies))
    chat(LURL, "laptop during the split")
    say("both worked")
finally:
    subprocess.run(["iptables", "-D", "OUTPUT", "-p", "tcp", "-m", "conntrack", "--ctorigdst", HOSTIP, "--ctorigdstport", str(CPORT), "-j", "REJECT"], check=True)
    say("healed")
v, took = wait_for(lambda: lstatus().get("split"), 120, 2, "split noticed")
say(f"split noticed {took:.0f}s after healing:", {k: v.get(k) for k in ("worked", "bytes")})
say("laptop kept its own:", "laptop during the split" in conv_titles_local(), "| cloud's not merged in:", "cloud during the split" not in conv_titles_local())
import sqlite3
b = sqlite3.connect(f"file:{LAG/'agentos.db'}?mode=ro", uri=True).execute("select title from brief_items where mission='standby'").fetchall()
say("brief item:", b)
time.sleep(4)
say("cloud API:", Cloud().get("/api/config").status_code)
t = time.time()
say("adopt:", lpost("/api/standby/adopt").json())
time.sleep(3)
wait_for(lambda: lget("/api/config").status_code == 200, 90, 1, "laptop back")
say(f"adopted in {time.time()-t:.1f}s:", "cloud during the split" in conv_titles_local())
