# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""Phase 5: the lid closes (process frozen), the cloud takes over, the lid opens."""
import signal
from h import *
lpost("/api/standby/copy")
laptop_signal(signal.SIGSTOP)
t = time.time()
say("laptop frozen")
wait_for(lambda: Cloud().get("/api/config").status_code == 200, 400, 3, "takeover")
say(f"cloud took over {time.time()-t:.0f}s after the lid closed")
c = Cloud()
chat(CURL, "while the lid was closed", cookies=dict(c.c.cookies))
say("telegram during sleep:", tg_wait_reply(tg_inject("lid closed? (5)") and "lid closed? (5)"))
laptop_signal(signal.SIGCONT)
t = time.time()
say("laptop woken")
v, took = wait_for(lambda: "while the lid was closed" in conv_titles_local() and lget("/api/config").status_code == 200, 120, 1, "work back after wake")
say(f"laptop had the cloud's work {time.time()-t:.1f}s after waking")
st = lstatus()
say("split?", bool(st.get("split")), "| laptop active:", st.get("active"))
time.sleep(6)
say("cloud API:", Cloud().get("/api/config").status_code, "| telegram polls last 6s:", polls_since(6))
