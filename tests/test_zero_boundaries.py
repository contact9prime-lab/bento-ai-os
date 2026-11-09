"""What a Zero can get out of its hub. Anybody at a Zero's screen can steer a turn, so the
turn's answer, the files it carries and what the agents working it can read are all what that
screen can reach. A hub and a Zero stand up in this process, linked over real mTLS."""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agentos import provision, teamlink, zero, zeromind              # noqa: E402
from agentos import users as usersmod                                # noqa: E402
from agentos.agent import Agent                                      # noqa: E402
from agentos.memory import Store                                     # noqa: E402
from test_zero_chat import _brain, _zero_on                          # noqa: E402
from test_zero_mind import _on, _section, hz                         # noqa: E402,F401


def _lk(H):
    with teamlink.at(H["home"]):
        return next(x for x in teamlink._load()["links"] if x["peer_host_fp"] == H["zero_lk"]["peer_host_fp"])


# ---- files going back (S-43) ----------------------------------------------------------------

def _ws(H, tmp_path):
    ws = tmp_path / "hubws"
    ws.mkdir(exist_ok=True)
    H["cfg"]["workspace"] = str(ws)
    return ws


def test_naming_an_old_file_does_not_fetch_it(hz, tmp_path):
    H, Z, loop = hz
    ws = _ws(H, tmp_path)
    old = ws / "salaries.csv"
    old.write_text("everyone's pay")
    os.utime(old, (1000, 1000))
    new = ws / "plan.md"
    new.write_text("made for this")
    with teamlink.at(H["home"]):
        got = H["cp"]._ship_back(_lk(H), f"See `{old}` and `{new}`.", since=time.time() - 5)
    assert [f["name"] for f in got["files"]] == ["plan.md"]
    assert got["kept"] == ["salaries.csv"], "and the answer can say it stayed here"


def test_a_hidden_file_never_goes_back_however_new(hz, tmp_path):
    H, Z, loop = hz
    ws = _ws(H, tmp_path)
    (ws / "finance").mkdir()
    env = ws / "finance" / ".env"
    env.write_text("SECRET=1")
    with teamlink.at(H["home"]):
        got = H["cp"]._ship_back(_lk(H), f"See `{env}`.", since=time.time() - 5)
    assert not got.get("files")


def test_files_going_back_is_a_decision_a_person_can_switch_off(hz, tmp_path):
    from agentos import linkfiles
    H, Z, loop = hz
    ws = _ws(H, tmp_path)
    f = ws / "plan.md"
    f.write_text("x")
    with teamlink.at(H["home"]):
        lk = _lk(H)
        H["store"].db.execute("DELETE FROM audit")
        assert H["cp"]._ship_back(lk, f"`{f}`", since=time.time() - 5)["files"]
        assert H["store"].db.execute("SELECT COUNT(*) FROM audit WHERE action='file.send'").fetchone()[0] >= 1, \
            "the gate decided it, so the ledger has the row"
        linkfiles.set_back(H["store"], lk["label"], False)
        assert H["cp"]._ship_back(lk, f"`{f}`", since=time.time() - 5) == {}


def test_a_non_admins_zero_does_not_reach_the_machines_workspace(hz, tmp_path, monkeypatch):
    H, Z, loop = hz
    ws = _ws(H, tmp_path)
    machine_home = tmp_path / "machine"
    (machine_home / "workspace").mkdir(parents=True)
    other = machine_home / "workspace" / "machine-note.txt"
    other.write_text("the machine's")
    from agentos import config as cfgmod
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", machine_home)
    monkeypatch.setattr(usersmod, "is_admin", lambda uid: False)
    with teamlink.at(H["home"]):
        lk = {**_lk(H), "owner": "bob"}
        got = H["cp"]._ship_back(lk, f"See `{other}`.", since=time.time() - 5)
    assert not got.get("files") and other.name not in (got.get("kept") or [])


def test_the_zero_hears_what_stayed_on_the_hub(hz, monkeypatch):
    H, Z, loop = hz

    async def fake_call(lk, req, **k):
        return {"ok": True, "text": "There you go.", "kept": ["salaries.csv"]}
    monkeypatch.setattr(teamlink, "call", fake_call)

    async def emit(ev):
        pass
    out = _on(Z, loop, lambda: zero.hub_turn(Z["cfg"], "c", "hi", emit))
    assert "salaries.csv" in out["content"] and "stay on" in out["content"]


# ---- what the turn can read (S-46) ----------------------------------------------------------

def test_a_section_reads_exactly_and_an_ordinary_space_keeps_the_rule(tmp_path):
    s = Store(tmp_path / "t.db")
    sec, proj = s.create_space("Zero · pi"), s.create_space("A project")
    s.mark_section(sec)
    s.add_memory("the owner's salary", space_id="")
    s.add_memory("the Pi's note", space_id=sec)
    s.add_memory("project note", space_id=proj)
    assert [m["content"] for m in s.search_memories("", space=sec)] == ["the Pi's note"]
    assert sorted(m["content"] for m in s.search_memories("", space=proj)) == ["project note", "the owner's salary"], \
        "every other space still sees what is true everywhere"
    s.kg_add("Owner", "earns", "lots", space_id="")
    s.kg_add("Pi", "watches", "door", space_id=sec)
    assert s.kg_query("", space=sec) == ["Pi —watches→ door"] or len(s.kg_query("", space=sec)) == 1
    assert len(s.kg_graph(space=sec)["nodes"]) == 2
    assert Store(tmp_path / "t.db").is_section(sec), "kept in the database, so a restart keeps it"


def test_the_hubs_global_memory_stays_out_of_a_zeros_chat(hz, monkeypatch):
    seen = []
    _brain(monkeypatch, seen)
    H, Z, loop = _zero_on(hz, monkeypatch)
    H["cfg"]["memory"] = {"inject_user": 10, "inject_facts": 10, "auto_extract": False}
    H["store"].add_memory("the owner's salary is 123", space_id="", scope="user")
    H["store"].kg_add("Owner", "earns", "123", space_id="")
    sid = _section(H)
    H["store"].add_memory("the kitchen light is on the left", space_id=sid, scope="user")

    async def emit(ev):
        pass
    _on(Z, loop, lambda: zero.hub_turn(Z["cfg"], "c-screen", "what do you know?", emit))
    system = next(m["content"] for m in seen[0] if m["role"] == "system")
    assert "kitchen light" in system
    assert "owner's salary" not in system and "—earns→" not in system


def test_the_hubs_soul_stays_out_of_a_zeros_chat(hz, monkeypatch):
    from agentos import config as cfgmod
    seen = []
    _brain(monkeypatch, seen)
    H, Z, loop = _zero_on(hz, monkeypatch)
    with teamlink.at(H["home"]):
        Path(cfgmod.soul_path()).write_text("The owner's divorce is private.")

    async def emit(ev):
        pass
    _on(Z, loop, lambda: zero.hub_turn(Z["cfg"], "c-screen", "hi", emit))
    system = next(m["content"] for m in seen[0] if m["role"] == "system")
    assert "divorce" not in system


def test_a_forwarded_zero_turn_gets_the_zeros_soul_too(hz, monkeypatch):
    from agentos import config as cfgmod, executors
    H, Z, loop = hz
    sid = _section(H)
    with teamlink.at(H["home"]):
        Path(cfgmod.soul_path()).write_text("The owner's divorce is private.")
        note = executors.identity_note(H["cfg"], H["store"], company=False, space_id=sid)
        assert "divorce" not in note
        assert "divorce" in executors.identity_note(H["cfg"], H["store"], company=False)


def test_recall_in_a_section_finds_nothing_of_the_hubs(hz, monkeypatch):
    H, Z, loop = hz
    sid = _section(H)
    H["store"].add_memory("the owner's salary is 123", space_id="", scope="user")
    with teamlink.at(H["home"]):
        out = asyncio.new_event_loop().run_until_complete(H["tb"].recall("salary", space_id=sid))
    assert "salary" not in out


def test_everywhere_does_not_write_past_a_zeros_section(hz):
    H, Z, loop = hz
    sid = _section(H)
    new = asyncio.new_event_loop()
    with teamlink.at(H["home"]):
        new.run_until_complete(H["tb"].remember("from the room", space_id=sid, everywhere=True))
        new.run_until_complete(H["tb"].kg_add("Room", "says", "this", space_id=sid, everywhere=True))
    new.close()
    assert [m["content"] for m in H["store"].search_memories("", space=Store.GLOBAL_ONLY)] == []
    assert H["store"].kg_query("", space=Store.GLOBAL_ONLY) == []


# ---- whose schedule (S-45) ------------------------------------------------------------------

def test_two_peoples_zeros_with_one_name_stay_apart(hz, monkeypatch):
    H, Z, loop = hz
    with teamlink.at(H["home"]):
        d = teamlink._load()
        d["links"][0]["owner"] = "ada"
        d["links"][0]["label"] = "raspberrypi"
        twin = "9" * 64
        d["links"].append({**d["links"][0], "id": "twin", "owner": "bob", "peer_host_fp": twin})
        teamlink._save(d)
        pd = provision.load()
        fp = H["zero_lk"]["peer_host_fp"]
        pd["enabled"][fp].update(space="s-ada", execution="hub", label="raspberrypi")
        pd["enabled"][twin] = {"name": "raspberrypi", "label": "raspberrypi", "execution": "hub", "space": "s-bob"}
        provision.save(pd)
        assert zeromind.link_of_section("s-bob", "bob")["owner"] == "bob"
        assert zeromind.link_of_section("s-ada", "ada")["owner"] == "ada"
        assert zeromind.link_of_section("s-bob", "ada") is None, "another account's section is not found"


def test_a_schedule_runs_as_the_account_it_belongs_to(hz, monkeypatch):
    from agentos import server
    H, Z, loop = hz
    with teamlink.at(H["home"]):
        d = teamlink._load()
        d["links"][0]["owner"] = "ada"
        d["links"][0]["label"] = "raspberrypi"
        twin = "9" * 64
        d["links"].append({**d["links"][0], "id": "twin", "owner": "bob", "peer_host_fp": twin})
        teamlink._save(d)
        pd = provision.load()
        fp = H["zero_lk"]["peer_host_fp"]
        pd["enabled"][fp].update(space="s-ada", execution="hub", label="raspberrypi")
        pd["enabled"][twin] = {"name": "raspberrypi", "label": "raspberrypi", "execution": "hub", "space": "s-bob"}
        provision.save(pd)
        ran = {}

        class Fabric:
            async def zero_chat(self, lk, req, say=None):
                ran["owner"], ran["as"] = lk["owner"], usersmod.current()
                return {"ok": True, "text": "done", "conversation": "c"}

        async def call(lk, req, **k):
            ran["sent_to"] = lk["peer_host_fp"]
            return {"ok": True}
        monkeypatch.setattr(teamlink, "call", call)
        monkeypatch.setattr(server, "state", {"fabric": Fabric()})

        async def go():
            with usersmod.as_user("bob"):
                return await server._zero_job({"id": "t1", "space_id": "s-bob", "prompt": "tea"})
        got = asyncio.new_event_loop().run_until_complete(go())
    assert ran["owner"] == "bob" and ran["as"] == "bob" and ran["sent_to"] == twin
    assert got[1] == "done"


def test_the_inventory_row_is_found_by_certificate_and_not_by_label(monkeypatch):
    from agentos import inventory, ties
    rows = [{"key": "ada", "links": [{"label": "raspberrypi", "owner": "ada", "fp": "a" * 64}]},
            {"key": "bob", "links": [{"label": "raspberrypi", "owner": "bob", "fp": "b" * 64}]}]
    monkeypatch.setattr(inventory, "rows", lambda: rows)
    assert ties.inventory_row({"label": "raspberrypi", "owner": "bob", "peer_host_fp": "b" * 64})["key"] == "bob"
    assert ties.machine_of({"label": "raspberrypi", "owner": "ada", "peer_host_fp": "a" * 64}) == "ada"


# ---- how much a Zero may ask for (S-78, schedules) -------------------------------------------

def test_a_zeros_schedules_are_capped(hz, monkeypatch):
    from agentos import tools
    H, Z, loop = hz
    sid = _section(H)
    with teamlink.at(H["home"]):
        d = provision.load()
        d["enabled"][H["zero_lk"]["peer_host_fp"]]["space"] = sid
        provision.save(d)
        monkeypatch.setattr(tools, "ZERO_MAX_SCHEDULES", 3)
        new = asyncio.new_event_loop()
        tb = H["tb"]

        class Sch:
            def create_task(self, prompt, *a, space_id="", **k):
                H["store"].add_task(prompt, "daily", None, "09:00", 0, space_id=space_id)
                return "scheduled"
        tb.scheduler = Sch()
        tb._schedule_app = lambda a, b: ("", "")
        said = [new.run_until_complete(tb.schedule_task(f"job {i}", "daily", at_time="09:00", space_id=sid)) for i in range(5)]
        assert said[:3] == ["scheduled"] * 3 and all("already has 3" in s for s in said[3:])
        out = new.run_until_complete(tb.schedule_task("spin", "interval", interval_minutes=1, space_id=sid))
        assert "at most every" in out
        new.close()
