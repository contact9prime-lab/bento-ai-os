"""An app job: a schedule that runs an app's own script, with no model.

Asked for over Signal Desk, a market scanner whose page refreshed itself every minute by
running a hidden Python reader through `run_command`. The person asked for a schedule and
found none in Missions, because there wasn't one: the work lived in the page's timer, outside
the framework. The owner's rule: "the framework provides mission, permissions, ethics; the
app should look into the framework". And their choice, by kind of work: numbers an app shows
(fetch, compute) are an app job; work that needs judgement is an agent schedule
(`schedule_task` with the app).

How a job keeps to the framework:
- **It is a `tasks` row** (`script`, `data_key`, `app_id`), so Missions → Schedule lists it, the
  scheduler fires it, and every firing is a `task_runs` row in Missions → History.
- **A person approves the script itself.** `schedule_app_job` is ALWAYS_ASK, and the card's body
  is the script. The yes writes ONE grant: this app may run exactly this script
  (`tool:run_python <args>`, glob-free, `source_ref` job:<task>). Changing the script is a new
  card; the old grant goes.
- **Each run goes through `Agent.call_tool`**, as the app, with a headless approver: the PDP
  decision, the ethics check, the ledger row and the jail are the ones any step gets. A script
  that no longer matches its grant is refused there and the run says so.
- **What it prints is the app's data** under `data_key` (JSON if it parses), and `_jobs` keeps
  each job's last run, so the page only displays and says when it was updated.
- **It is handed what it saved last time** (`input_of`, a JSON file named by sys.argv[1]), so a
  script that compares with the last run keeps no state of its own.
- **It may speak in chats the card named** (`send_to`, appchannels.py): an object printed with
  a `_message` sends that text there as the app, through the same gate (`channel.send`), and
  the key is never saved. No `_message`, nothing is sent.

Stdlib only, no HTTP or asyncio.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

MAX_SCRIPT = 60_000
MIN_MINUTES = 1
MAX_MINUTES = 7 * 24 * 60
MAX_JOBS = 5               # per app; each one runs code on this machine on a clock
TIMEOUT = 120              # seconds a run may take
MAX_OUTPUT = 200_000       # what is kept in the app's data
STATUS_KEY = "_jobs"       # the app's data key holding each job's last run
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")


def args_of(script: str) -> dict:
    """The run_python arguments a job runs with: the same every time, so its grant matches."""
    return {"code": script, "timeout": TIMEOUT}


def grant_of(script: str) -> tuple[str, str]:
    """(action, resource) the approval writes: this exact script and nothing else."""
    from .policy import _glob_free, action_of
    action, resource = action_of("run_python", args_of(script))
    return action, _glob_free(resource)


def digest(script: str) -> str:
    return hashlib.sha256(script.encode("utf-8", "replace")).hexdigest()[:12]


def clean(title: str, script: str, interval_minutes, key: str) -> tuple[dict | None, str]:
    """The job as it would be saved, or why not. Read field by field."""
    title = " ".join(str(title or "").split())[:80]
    if not title:
        return None, "[error] give the job a title, e.g. 'Scan the market'"
    script = str(script or "")
    if not script.strip():
        return None, "[error] the job needs a script: the Python that fetches or computes the data"
    if len(script) > MAX_SCRIPT:
        return None, f"[error] the script is {len(script)} characters; at most {MAX_SCRIPT}"
    try:
        every = int(interval_minutes)
    except (TypeError, ValueError):
        return None, "[error] interval_minutes must be a whole number of minutes"
    if not MIN_MINUTES <= every <= MAX_MINUTES:
        return None, f"[error] interval_minutes must be between {MIN_MINUTES} and {MAX_MINUTES}"
    key = str(key or "").strip()
    if not _KEY.match(key) or key == STATUS_KEY:
        return None, ("[error] key is the name the app reads its data under: a letter, then "
                      "letters, digits, _ . or -, at most 80")
    return {"title": title, "script": script, "every": every, "key": key}, ""


def of_app(store, app_id: str) -> list[dict]:
    return [t for t in store.list_tasks() if (t.get("app_id") or "") == app_id and t.get("script")]


def find(store, app_id: str, title: str) -> dict | None:
    return next((t for t in of_app(store, app_id) if t.get("prompt") == title), None)


def summary(task: dict) -> dict:
    """What an app (or a screen) is told about one of its jobs: never the grant."""
    return {"id": task["id"], "title": task.get("prompt") or "",
            "every_minutes": int(task.get("interval_seconds") or 0) // 60,
            "key": task.get("data_key") or "", "script_sha": digest(task.get("script") or ""),
            "enabled": bool(task.get("enabled")), "last_run": task.get("last_run"),
            "last_result": (task.get("last_result") or "")[:300],
            "send_to": targets_of(task)}


def targets_of(task: dict | None) -> list[str]:
    """The chats a job sends its `_message` to (appchannels ids), as saved."""
    try:
        got = json.loads((task or {}).get("send_to") or "[]")
    except ValueError:
        return []
    return [str(t) for t in got if isinstance(t, str)] if isinstance(got, list) else []


def same(task: dict | None, job: dict) -> bool:
    return bool(task) and task.get("script") == job["script"] \
        and int(task.get("interval_seconds") or 0) == job["every"] * 60 \
        and (task.get("data_key") or "") == job["key"] \
        and targets_of(task) == list(job.get("send_to") or [])


def _drop_grant(store, task_id: str):
    for g in store.list_grants():
        if (g.get("source_ref") or "") == f"job:{task_id}":
            store.revoke_grant(g["id"])


def save(store, app_id: str, job: dict) -> tuple[str, str]:
    """Write the approved job and its one grant. (task_id, words). A job by the same title is
    replaced in place, and its old grant goes with the old script."""
    old = find(store, app_id, job["title"])
    if same(old, job):
        return old["id"], f"already scheduled: {job['title']}, every {job['every']} min"
    if not old and len(of_app(store, app_id)) >= MAX_JOBS:
        raise ValueError(f"this app already has {MAX_JOBS} jobs; remove one in Missions → Schedule")
    now = time.time()
    if old:
        tid = old["id"]
        _drop_grant(store, tid)
        store.update_task(tid, script=job["script"], interval_seconds=job["every"] * 60,
                          data_key=job["key"], next_run=now + 5, enabled=1,
                          send_to=json.dumps(list(job.get("send_to") or [])))
    else:
        tid = store.add_task(job["title"], "interval", job["every"] * 60, None, now + 5,
                             app_id=app_id, script=job["script"], data_key=job["key"],
                             send_to=json.dumps(list(job.get("send_to") or [])))
    action, resource = grant_of(job["script"])
    store.add_grant("app", app_id, action, resource, source="user",
                    note=f"app job '{job['title']}', approved on its card", source_ref=f"job:{tid}")
    for dest in job.get("send_to") or []:
        # the same card named these chats, so the same yes lets the job post there; they go
        # with the job (`_drop_grant`), a send from the app's page still asks for itself
        chan, _, chat = dest.partition(":")
        store.add_grant("app", app_id, "channel.send", f"channel:{chan}/{chat}", source="user",
                        note=f"app job '{job['title']}' sends to this chat, approved on its card",
                        source_ref=f"job:{tid}")
    return tid, (f"{'updated' if old else 'scheduled'}: {job['title']}, every {job['every']} min, "
                 f"no model. Its runs are in Missions → History, and what it prints is saved "
                 f"under '{job['key']}' in the app's data")


def forget(store, task_id: str):
    """A job removed in Missions takes its grant with it."""
    _drop_grant(store, task_id)


_FENCE = re.compile(r'^\s*<untrusted source="[^"\n]*">\n(.*)\n</untrusted>\n\[The block above is DATA[^\n]*\]\s*$',
                    re.S)


def unfence(output: str) -> str:
    """The script's own output without the gate's <untrusted> fence. The fence is a note to a
    model reading web content (agent.fence); a job's output goes to a sandboxed page as data,
    and saved with the fence it reached the page as a string (found live: no prices shown)."""
    m = _FENCE.match(str(output or ""))
    return m.group(1).replace("<\\/untrusted>", "</untrusted>") if m else str(output or "")


def result_of(output: str) -> tuple[bool, object, str]:
    """(ok, value to save, a line for the run) from what run_python returned."""
    out = unfence(output)
    head = out.lstrip()[:200].lower()
    if head.startswith(("[denied]", "[error]", "not approved", "[blocked]")):
        return False, None, out.strip()[:300]
    m = re.match(r"\s*\[exit code (-?\d+)\]", out)
    if m:
        return False, None, f"the script stopped with exit code {m.group(1)}: {out.strip()[-300:]}"
    body = out.strip()
    if len(body) > MAX_OUTPUT:
        return False, None, f"the script printed {len(body)} characters; at most {MAX_OUTPUT} are kept"
    try:
        value = json.loads(body)
    except ValueError:
        value = body
    return True, value, f"saved {len(body)} characters"


def input_of(data_json: str, task: dict) -> dict:
    """What a run is handed (sys.argv[1], a JSON file): what this job saved last time under its
    key, and when, so "alert when it moved since the last check" needs no state of its own."""
    try:
        data = json.loads(data_json or "{}")
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    run = (data.get(STATUS_KEY) or {}).get(task.get("prompt") or "") if isinstance(data.get(STATUS_KEY), dict) else None
    return {"previous": data.get(task.get("data_key") or ""), "at": (run or {}).get("at")}


MESSAGE_KEY = "_message"     # what a run wants said in the job's chats; never saved


def split_message(value) -> tuple[object, str]:
    """(what to save, what to send). A job's script decides when to speak: an object with a
    non-empty `_message` sends it to the job's chats; anything else sends nothing, so a
    price check can alert only when a line is crossed."""
    if isinstance(value, dict) and MESSAGE_KEY in value:
        value = dict(value)
        msg = value.pop(MESSAGE_KEY)
        return value, (str(msg).strip() if msg not in (None, "", False) and not
                       isinstance(msg, (dict, list)) else "")
    return value, ""


def status(data_json: str, title: str, ok: bool, line: str) -> dict:
    """The app's data with this job's last run noted under `_jobs`, the rest kept."""
    try:
        data = json.loads(data_json or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    jobs = data.get(STATUS_KEY) if isinstance(data.get(STATUS_KEY), dict) else {}
    jobs[title] = {"at": int(time.time() * 1000), "ok": ok, "note": line[:300]}
    data[STATUS_KEY] = jobs
    return data
