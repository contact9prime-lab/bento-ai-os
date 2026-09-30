"""Cloud standby (agentos/standby.py): a cloud machine takes over only while yours is away.

Asked for as "run it first on my machine and then jack it to a cloud … it only runs on
the cloud when my local is not available". What these pin, with two homes in one process
and a transport that calls the other side's functions directly:

- pairing is a one-time code (hashed, single use, five tries) and HTTPS off a private
  network;
- copies are sealed with the pair's secret, checked in full on arrival, and the one before
  is kept;
- the standby takes over only after the silence, with a copy, and swaps it in at the next
  start with ITS OWN door (remote access) kept;
- your machine brings the work back when nothing happened here, and keeps its own (the
  cloud's saved beside it) when both worked: the bug found live was a heartbeat stamping
  "last contact" before that check, which made the window empty;
- a side that is not working starts no runners, serves its standing-by page, refuses the
  API and every socket; the peer door wants the token and has a guess ceiling.
"""
import json
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import backup, standby  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(backup, "SCRYPT", {"n": 1 << 10, "r": 8, "p": 1})
    monkeypatch.setenv("AGENTOS_VAULT_KEYRING", "0")
    standby._BAD.clear()
    standby._PASSIVE_CACHE.clear()


def _home(tmp_path, name, remote=None):
    h = tmp_path / name
    (h / "workspace").mkdir(parents=True)
    cfg = {"workspace": str(h / "workspace"), "engine": "aria", "agent_name": name}
    if remote:
        cfg["remote"] = remote
    (h / "config.json").write_text(json.dumps(cfg))
    con = sqlite3.connect(h / "agentos.db")
    con.executescript("""
      create table conversations(id text primary key, title text, created_at real, updated_at real);
      create table messages(id text primary key, conversation_id text, role text, content text,
                            meta text, created_at real);
      create table fabric_runs(id text primary key, started_at real);
      create table task_runs(id text primary key, started_at real);""")
    con.commit()
    con.close()
    return h


def _say(h, title, role="user"):
    con = sqlite3.connect(h / "agentos.db")
    cid = uuid.uuid4().hex
    con.execute("insert into conversations values (?,?,?,?)", (cid, title, time.time(), time.time()))
    con.execute("insert into messages values (?,?,?,?,?,?)",
                (uuid.uuid4().hex, cid, role, title, "{}", time.time()))
    con.commit()
    con.close()


def _titles(h):
    con = sqlite3.connect(h / "agentos.db")
    try:
        return {r[0] for r in con.execute("select title from conversations")}
    finally:
        con.close()


class _Resp:
    def __init__(self, status, data=None, body=b""):
        self.status_code, self._data, self._body = status, data, body

    def json(self):
        return self._data

    def iter_bytes(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]


class _Cloud:
    """The standby's routes, as the server wires them, called in-process."""

    def __init__(self, home):
        self.home, self.up, self.calls = home, True, []

    def handle(self, method, path, headers, js=None, content=None):
        if not self.up:
            import httpx
            raise httpx.ConnectError("down")
        self.calls.append(path)
        if path == "pair":
            try:
                return _Resp(200, standby.accept(js, self.home))
            except standby.StandbyError as e:
                return _Resp(400, {"error": str(e)})
        tok = (headers or {}).get("Authorization", "")[7:]
        if not standby.token_ok(tok, self.home):
            return _Resp(401, {"error": "not paired"})
        try:
            if path == "beat":
                return _Resp(200, standby.heard(js or {}, self.home))
            if path == "state":
                return _Resp(200, standby.answer(self.home))
            if path == "push":
                out = standby.receive(content, self.home)
                return _Resp(200 if out.get("ok") else 409, out)
            if path == "release":
                return _Resp(200, standby.release(self.home))
            if path == "outgoing":
                p = standby.outgoing(self.home)
                return _Resp(200, body=p.read_bytes()) if p else _Resp(404, {"error": "none"})
            if path == "done":
                return _Resp(200, standby.done(js or {}, self.home))
            if path == "takeover":
                return _Resp(200, standby.peer_takeover(js or {}, self.home))
            if path == "unpair":
                standby.forget_peer(self.home)
                return _Resp(200, {"ok": True})
        except standby.StandbyError as e:
            return _Resp(409, {"error": str(e)})
        return _Resp(404, {"error": path})

    def restart(self):
        """What a server start does: apply a staged swap, keep this side's door."""
        rep = backup.apply_pending(home=self.home, echo=None)
        if rep:
            standby.after_swap(rep, home=self.home)
        return rep


@pytest.fixture
def pair(tmp_path, monkeypatch):
    laptop = _home(tmp_path, "laptop")
    cloud_home = _home(tmp_path, "cloud", remote={"enabled": True, "pass_hash": "cloudlock"})
    cloud = _Cloud(cloud_home)

    class _Client:
        def __init__(self, timeout=0):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def _path(self, url):
            return url.split("/api/standby/peer/", 1)[1]

        def post(self, url, json=None, content=None, headers=None):
            if content is not None and not isinstance(content, (bytes, bytearray)):
                content = list(content)
            return cloud.handle("POST", self._path(url), headers, json, content)

        def request(self, method, url, headers=None, json=None, **kw):
            return cloud.handle(method, self._path(url), headers, json)

        @contextmanager
        def stream(self, method, url, headers=None):
            yield cloud.handle(method, self._path(url), headers)

    monkeypatch.setattr(standby, "_client", _Client)
    monkeypatch.setattr(standby.time, "sleep", lambda s: None)
    code = standby.offer(cloud_home)["code"]
    standby.pair("https://cloud.example", code, laptop)
    return laptop, cloud


def test_pairing_is_a_one_time_code_and_https_off_a_private_network(tmp_path, monkeypatch):
    h = _home(tmp_path, "c")
    o = standby.offer(h)
    assert len(standby._norm_code(o["code"])) == 8
    off = json.loads((h / ".standby" / "offer.json").read_text())
    assert o["code"] not in json.dumps(off), "the code is stored hashed"
    body = {"code": "WRONG-CODE", "token": "t" * 40, "secret": "s" * 40}
    for _ in range(standby.CODE_TRIES - 1):
        with pytest.raises(standby.StandbyError, match="not right"):
            standby.accept(body, h)
    with pytest.raises(standby.StandbyError, match="Too many"):
        standby.accept(body, h)
    with pytest.raises(standby.StandbyError, match="not waiting"):
        standby.accept({**body, "code": o["code"]}, h)
    o = standby.offer(h)
    assert standby.accept({**body, "code": o["code"].lower()}, h)["ok"]
    st = standby.load(h)
    assert st["role"] == "standby" and not st["active"] and st["token_hash"] != "t" * 40
    assert standby.token_ok("t" * 40, h) and not standby.token_ok("t" * 39, h)
    with pytest.raises(standby.StandbyError, match="already standing by"):
        standby.offer(h)
    assert standby.url_problem("http://bento.example.com")
    for ok in ("https://bento.example.com", "http://192.168.1.4:8321", "http://100.101.1.2:8321",
               "http://box.tail1234.ts.net", "http://127.0.0.1:8962"):
        assert standby.url_problem(ok) == "", ok
    # a copy and its state are this machine's own: never in a backup, never moved by one
    assert backup._private(".standby")


def test_the_cloud_takes_over_after_the_silence_and_hands_the_work_back(pair):
    laptop, cloud = pair
    (laptop / "workspace" / "deck.md").write_text("laptop deck")
    _say(laptop, "written on the laptop")
    assert standby.beat(laptop)["active"] is False
    assert standby.push(laptop)["sent"]
    assert standby.push(laptop) == {"sent": False, "why": "nothing changed"}
    assert standby.passive(cloud.home) and not standby.passive(laptop)
    # not yet: the laptop was heard just now
    assert standby.due_takeover(cloud.home) == ""
    st = standby.load(cloud.home)
    st["last_beat"] = time.time() - standby.GRACE_S - 5
    standby.save(st, cloud.home)
    why = standby.due_takeover(cloud.home)
    assert "has not been heard from for 5 minutes" in why
    standby.takeover(why, cloud.home)
    assert not standby.passive(cloud.home)
    cloud.restart()
    assert "written on the laptop" in _titles(cloud.home)
    assert (cloud.home / "workspace" / "deck.md").read_text() == "laptop deck"
    cfg = json.loads((cloud.home / "config.json").read_text())
    assert cfg["remote"]["pass_hash"] == "cloudlock", "the cloud keeps its own lock"
    assert cfg["agent_name"] == "laptop" and cfg["workspace"] == str(cloud.home / "workspace")
    # the cloud works; the laptop comes back and nothing happened on it meanwhile
    _say(cloud.home, "made in the cloud")
    assert standby.beat(laptop)["active"]
    r = standby.come_back(laptop)
    assert r["restart"] and not r["split"]
    rep = backup.apply_pending(home=laptop, echo=None)
    standby.after_swap(rep, laptop)
    assert {"written on the laptop", "made in the cloud"} <= _titles(laptop)
    assert "remote" not in json.loads((laptop / "config.json").read_text()), \
        "the laptop's door stays the laptop's (it had none)"
    c = standby.load(cloud.home)
    assert not c["active"] and not c["holds_work"] and not standby.outgoing(cloud.home)
    assert standby.due_takeover(cloud.home) == "", "heard from just now: no second takeover"
    assert standby.load(laptop)["epoch"] == c["epoch"] == 2


def test_a_heartbeat_that_finds_the_cloud_working_keeps_the_window_open(pair):
    """Found live: the beat that saw the cloud working stamped last_contact, so the
    work check looked back over nothing and the cloud's copy replaced ours."""
    laptop, cloud = pair
    standby.push(laptop)
    before = standby.load(laptop)["last_contact"]
    st = standby.load(cloud.home)
    st["last_beat"] = 1
    standby.save(st, cloud.home)
    standby.takeover("quiet", cloud.home)
    time.sleep(0.01)
    assert standby.beat(laptop)["active"]
    assert standby.load(laptop)["last_contact"] == before


def test_when_both_worked_ours_stays_and_the_clouds_is_one_step_away(pair):
    laptop, cloud = pair
    standby.push(laptop)
    st = standby.load(cloud.home)
    st["last_beat"] = 1
    standby.save(st, cloud.home)
    standby.takeover("quiet", cloud.home)
    cloud.restart()
    _say(cloud.home, "cloud during the split")
    _say(laptop, "laptop during the split")
    r = standby.come_back(laptop)
    assert r["split"] and not r["restart"] and "kept its own" in r["message"]
    assert "laptop during the split" in _titles(laptop)
    assert not backup.pending(laptop), "nothing is swapped in on a split"
    sp = standby.load(laptop)["split"]
    assert Path(sp["path"]).exists() and sp["worked"] == 1
    assert not standby.load(cloud.home)["active"]
    standby.adopt(laptop)
    backup.apply_pending(home=laptop, echo=None)
    assert "cloud during the split" in _titles(laptop)
    assert "split" not in standby.load(laptop)


def test_moving_on_purpose_and_back(pair):
    laptop, cloud = pair
    _say(laptop, "before the move")
    r = standby.move(laptop)
    assert r["restart"] and standby.passive(laptop)
    assert standby.load(laptop)["moved"]
    assert not standby.may_act(laptop), "a machine that handed over fires nothing"
    cloud.restart()
    assert "before the move" in _titles(cloud.home)
    _say(cloud.home, "after the move")
    r = standby.back(laptop)
    assert r["restart"] and not r["split"]
    backup.apply_pending(home=laptop, echo=None)
    assert "after the move" in _titles(laptop) and not standby.passive(laptop)


def test_copies_are_checked_on_arrival_and_the_one_before_is_kept(pair, tmp_path):
    laptop, cloud = pair
    standby.push(laptop, force=True)
    _say(laptop, "second")
    standby.push(laptop)
    d = cloud.home / ".standby"
    assert (d / "latest.bento").exists() and (d / "previous.bento").exists()
    good = (d / "latest.bento").read_bytes()
    bad = bytearray(good)
    bad[len(bad) // 2] ^= 1
    with pytest.raises(standby.StandbyError, match="did not check out"):
        standby.receive([bytes(bad)], cloud.home)
    assert (d / "latest.bento").read_bytes() == good, "a bad copy never replaces a good one"
    # the newest will not open: the takeover falls back to the one before
    (d / "latest.bento").write_bytes(bytes(bad))
    st = standby.load(cloud.home)
    st["last_beat"] = 1
    standby.save(st, cloud.home)
    assert standby.takeover("quiet", cloud.home)["ok"]


def test_the_scheduler_waits_for_a_heartbeat_after_a_long_sleep(pair):
    laptop, _ = pair
    assert standby.may_act(laptop)
    st = standby.load(laptop)
    st["last_attempt"] = time.time() - 10 * standby.BEAT_S
    standby.save(st, laptop)
    assert not standby.may_act(laptop)
    sched = (ROOT / "agentos/scheduler.py").read_text()
    assert "_sb.may_act()" in sched.split("def run_forever", 1)[1].split("def stop", 1)[0]


def test_a_quiet_side_serves_its_page_and_refuses_the_rest(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import config as cfgmod
    from agentos import desktop as desktopmod
    from agentos import server as servermod
    restarts = []
    monkeypatch.setattr(desktopmod, "restart_service", lambda: restarts.append(1) or "test")
    home = Path(cfgmod.AGENTOS_HOME)
    standby.save({"role": "standby", "active": False, "epoch": 0, "token_hash": standby._hash("k" * 43),
                  "secret": "s" * 43, "peer_host": "laptop", "last_beat": time.time(),
                  "grace": 300, "auto": True}, home)
    with TestClient(servermod.app) as cl:
        page = cl.get("/")
        assert page.status_code == 200 and "Standing by for laptop" in page.text
        r = cl.get("/api/config")
        assert r.status_code == 503 and "standing by for laptop" in r.json()["error"]
        assert cl.get("/api/standby").json()["role"] == "standby"
        # the peer door wants the token, and counts wrong ones
        assert cl.post("/api/standby/peer/beat", json={}).status_code == 401
        ok = cl.post("/api/standby/peer/beat", json={"version": "x"},
                     headers={"Authorization": "Bearer " + "k" * 43})
        assert ok.status_code == 200 and ok.json()["active"] is False
        for _ in range(standby.BAD_LIMIT):
            cl.post("/api/standby/peer/beat", json={}, headers={"Authorization": "Bearer nope"})
        assert cl.post("/api/standby/peer/beat", json={},
                       headers={"Authorization": "Bearer " + "k" * 43}).status_code == 429
        with pytest.raises(Exception):
            with cl.websocket_connect("/ws") as ws:
                ws.receive_text()
    srv = (ROOT / "agentos/server.py").read_text()
    start = srv.split("async def startup(", 1)[1].split("\n@app.", 1)[0]
    lines = start.splitlines()
    for runner in ("scheduler.run_forever()", "telegram.run_forever()", "_parked_loop(",
                   "_resume_whatsapp_link())", "_team_chat_sweep()", "attention.attention_loop("):
        i = next(n for n, ln in enumerate(lines) if runner in ln and "create_task" in ln)
        while not lines[i].startswith("    ") or lines[i].startswith("     "):
            i -= 1               # up to the enclosing statement at the function's own depth
        assert lines[i].strip() == "if not idle:", runner
    assert '"/api/standby/peer/")' in srv.split("REMOTE_OPEN_PATHS = (", 1)[1].split("\n\n", 1)[0]
    # the gate is registered before the remote gate, so it runs after it
    assert srv.index("async def standby_gate(") < srv.index("async def remote_access_gate(")


def test_the_start_brings_the_work_back_before_anything_opens():
    main = (ROOT / "agentos/__main__.py").read_text()
    serve = main.split("def serve(", 1)[1].split("\ndef ", 1)[0]
    assert serve.index("_sb.boot(") < serve.index("apply_pending()") < serve.index("_sb.after_swap(")
    assert 'verb("standby"' in main
    js = (ROOT / "agentos/ui/src/js/11h-standby.js").read_text()
    for route in ("/api/standby/pair", "/api/standby/offer", "/api/standby/move",
                  "/api/standby/adopt", "/api/standby/keep", "/api/standby/settings"):
        assert route in js, route
