# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
import json
from h import *
c = Cloud()
say("chat on the cloud:", chat(CURL, "hello cloud, are you me?", cookies=dict(c.c.cookies)))
say("telegram:", tg_wait_reply(tg_inject("where are you now? (2)") and "where are you now? (2)"))
say("telegram polls last 10s:", (time.sleep(10), polls_since(10))[1])
st = c.get("/api/standby").json()
say("cloud standby:", {k: st.get(k) for k in ("role", "active", "reason", "epoch", "last_swap")})
print(cpy(r'''
import sqlite3,json
c=sqlite3.connect("file:/data/agentos.db?mode=ro",uri=True)
cols=[r[1] for r in c.execute("pragma table_info(tasks)")]
print("task cols",cols)
for r in c.execute("select * from tasks"): print("TASK",str(r)[:300])
for r in c.execute("select name,enabled,job from flows"): print("FLOW",r)
for r in c.execute("select resource,effect,source_ref from grants where resource like 'fs:%'"): print("GRANT",r)
'''))
n0 = int(cpy("import sqlite3;print(sqlite3.connect('file:/data/agentos.db?mode=ro',uri=True).execute('select count(*) from task_runs').fetchone()[0])"))
time.sleep(70)
n1 = int(cpy("import sqlite3;print(sqlite3.connect('file:/data/agentos.db?mode=ro',uri=True).execute('select count(*) from task_runs').fetchone()[0])"))
say(f"schedule runs on the cloud in 70s: {n1-n0}")
