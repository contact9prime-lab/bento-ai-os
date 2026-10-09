# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Phase 7: the cloud container restarts while it is the one working; the laptop
starts while the cloud is unreachable (refused, and a black hole)."""
import subprocess
from h import *
lpost("/api/standby/move")
wait_for(lambda: Cloud().get("/api/config").status_code == 200, 90, 1, "cloud working")
c = Cloud()
chat(CURL, "before the container restart", cookies=dict(c.c.cookies))
t = time.time()
subprocess.run(["docker", "restart", CNAME], check=True, capture_output=True)
wait_up(CURL, path="/login")
c = Cloud()
say(f"container restarted in {time.time()-t:.1f}s; working:", c.get("/api/config").status_code == 200,
    "| still has the chat:", "before the container restart" in conv_titles_cloud(),
    "| cloud passphrase still opens it:", c.get("/api/standby").status_code == 200)
say("telegram after restart:", tg_wait_reply(tg_inject("after restart? (7)") and "after restart? (7)"))
r = lpost("/api/standby/back"); wait_for(lambda: lget("/api/config").status_code == 200, 90, 1, "back")
say("back after restart:", "before the container restart" in conv_titles_local())
# the laptop starts with the cloud switched off
subprocess.run(["docker", "stop", CNAME], check=True, capture_output=True)
laptop_kill()
took = laptop_start("laptop3.log")
say(f"laptop start with the cloud off (refused): {took:.1f}s")
laptop_kill()
subprocess.run(["iptables", "-I", "OUTPUT", "-p", "tcp", "-d", HOSTIP, "--dport", str(CPORT), "-j", "DROP"], check=True)
try:
    took = laptop_start("laptop4.log")
    say(f"laptop start with the cloud a black hole: {took:.1f}s")
    say("schedule may act:", time.sleep(2) or lstatus().get("last_error"))
finally:
    subprocess.run(["iptables", "-D", "OUTPUT", "-p", "tcp", "-d", HOSTIP, "--dport", str(CPORT), "-j", "DROP"], check=True)
cloud_start()
v, took = wait_for(lambda: Cloud().get("/api/standby").json().get("last_beat", 0) > time.time() - 40, 90, 3, "beats resume")
say(f"heartbeats resumed {took:.0f}s after the cloud came back")
