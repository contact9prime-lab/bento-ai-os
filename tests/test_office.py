"""The Office playground: a comic office where the crew is seen at work.

What these defend:

- the office is a CLOSED set (style, colour, decor, pet) validated in one place, and a
  refusal names the choices — the editor, the agent's `set_office` and `bento office`
  all go through it;
- the cast is the real one: a department member who is nobody here is dropped and
  NAMED, a specialist nobody placed sits on the open floor, one desk each, and a deleted
  specialist leaves no empty chair with a name on it;
- it is personal (a USER_KEY) and every change a person makes is a ledger row; the
  agent's change is its own action (`office.write`), so it can be granted and refused
  apart from real work;
- the terminal has the plan and the same editor, and says what it cannot show;
- the page: registered and reachable, fed by the ONE event seam, asleep when unseen,
  and it paints rooms, never people.
"""
import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import office, policy                                   # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _world(tmp_path, names=("researcher", "analyst", "writer")):
    store = Store(tmp_path / "a.db")
    for n in names:
        store.save_subagent({"name": n, "soul": n})
    return {"agent_name": "Aria"}, store


def test_the_office_is_a_closed_set_and_a_refusal_names_the_choices(tmp_path):
    cfg, store = _world(tmp_path)
    for bad, what in [({"style": "castle"}, "loft"), ({"pet": "dragon"}, "robot"),
                      ({"decor": ["plants", "hot tub"]}, "arcade"),
                      ({"departments": [{"name": "R", "color": "plaid"}]}, "violet")]:
        with pytest.raises(ValueError) as e:
            office.save(cfg, store, bad)
        assert what in str(e.value), (bad, e.value)
    # the picker's own words are accepted, not only the ids
    got, _ = office.save(cfg, store, {"style": "Space station"})
    assert got["style"] == "space"
    got, _ = office.save(cfg, store, {"name": "HQ‮\x1b[31mevil\n", "meeting": "no"})
    assert got["name"] == "HQ[31mevil" and got["meeting"] is False, "no control or bidi characters reach a label"


def test_the_cast_is_the_real_one(tmp_path):
    cfg, store = _world(tmp_path)
    got, dropped = office.save(cfg, store, {"departments": [
        {"name": "Research", "color": "sky", "members": ["researcher", "Analyst", "ghost"]},
        {"name": "Writing", "members": ["writer", "researcher"]},        # one desk each
        {"name": "research", "members": []},                            # a duplicate name
    ]})
    assert dropped == ["ghost"], "a name that is nobody here is dropped and named"
    assert [d["name"] for d in got["departments"]] == ["Research", "Writing"]
    assert got["departments"][0]["members"] == ["researcher", "analyst"]
    assert got["departments"][1]["members"] == ["writer"]
    store.save_subagent({"name": "validator", "soul": "checks"})
    v = office.view(cfg, store)
    kinds = [(r["kind"], r["name"], r["members"]) for r in v["rooms"]]
    assert kinds[0] == ("lead", "Aria's office", ["@agent"])
    assert ("floor", office.FLOOR, ["validator"]) in kinds, "a specialist nobody placed sits on the open floor"
    assert [k for k, *_ in kinds][-2:] == ["meeting", "lounge"]
    # deleted: its name leaves the room, and nothing is drawn for it
    store.db.execute("DELETE FROM subagents WHERE name='writer'")
    store.db.commit()
    v = office.view(cfg, store)
    assert next(r for r in v["rooms"] if r["name"] == "Writing")["members"] == []
    with pytest.raises(ValueError):
        office.save(cfg, store, {"departments": [{"name": f"D{i}"} for i in range(office.MAX_DEPTS + 1)]})


def test_moving_one_person_and_the_empty_office(tmp_path):
    cfg, store = _world(tmp_path)
    office.place(cfg, store, "analyst", "Numbers", "amber")
    office.place(cfg, store, "@researcher", "numbers")
    d = office.current(cfg)["departments"]
    assert d == [{"name": "Numbers", "color": "amber", "members": ["analyst", "researcher"]}]
    office.place(cfg, store, "analyst", "")
    assert office.current(cfg)["departments"][0]["members"] == ["researcher"]
    with pytest.raises(ValueError, match="no specialist called"):
        office.place(cfg, store, "nobody", "Numbers")
    cfg2, store2 = _world(tmp_path / "e", names=())
    (tmp_path / "e").mkdir(exist_ok=True)
    v = office.view(cfg2, Store(tmp_path / "e" / "b.db"))
    assert v["agents"] == [] and "No specialists yet" in office.text(v)


def test_it_is_personal_and_a_persons_change_is_in_the_ledger(tmp_path):
    from agentos import config as cfgmod, users
    assert "office" in users.USER_KEYS and "office" in cfgmod.DEFAULTS
    cfg, store = _world(tmp_path)
    office.record(store, "style set to space")
    rows = store.db.execute("SELECT action, resource, rule FROM audit WHERE action='office.write'").fetchall()
    assert rows and tuple(rows[0]) == ("office.write", "office", "person")


def test_the_agents_tool_is_its_own_action_and_the_same_closed_set(tmp_path):
    from agentos.tools import TOOL_SCHEMAS, Toolbox
    from agentos import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["workspace"] = str(tmp_path)
    store = Store(tmp_path / "t.db")
    store.save_subagent({"name": "researcher", "soul": "r"})
    tb = Toolbox(cfg, store)
    assert any(t["name"] == "set_office" for t in TOOL_SCHEMAS)
    assert policy.action_of("set_office", {"style": "space"}) == ("office.write", "office:*")
    out = asyncio.run(tb.set_office())
    assert "style (pop, loft" in out and "researcher" in out, "with nothing, it describes and lists the options"
    out = asyncio.run(tb.set_office(style="garden", agent="researcher", department="Research", pet="dog"))
    assert out.startswith("Done") and "greenhouse" in out and "Research (researcher)" in out
    assert asyncio.run(tb.set_office(style="castle")).startswith("[error]")
    assert "no department called" in asyncio.run(tb.set_office(remove_department="Nope"))
    out = asyncio.run(tb.set_office(departments=[{"name": "Lab", "members": ["researcher", "ghost"]}]))
    assert "nobody here is called: ghost" in out


def test_the_routes(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        v = cl.get("/api/office").json()
        assert v["rooms"][0]["kind"] == "lead" and "pop" in v["styles"] and "teal" in v["colors"]
        r = cl.put("/api/office", json={"style": "night", "decor": ["arcade"]})
        assert r.status_code == 200 and r.json()["office"]["style"] == "night"
        assert cl.put("/api/office", json={"pet": "dragon"}).status_code == 400
        assert cl.put("/api/office/place", json={"agent": "nobody", "department": "X"}).status_code == 400
        audit = cl.get("/api/audit", params={"action": "office.write"})
        if audit.status_code == 200:
            assert "office" in audit.text


def test_the_terminal_has_the_plan_and_the_same_editor(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "office", *a], cwd=ROOT, env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=60)
    r = run()
    assert r.returncode == 0 and "Pop comic" in r.stdout and "A terminal shows the plan, not the play" in r.stdout
    r = run("style", "space")
    assert r.returncode == 0 and "Space station" in r.stdout
    r = run("pet", "dragon")
    assert r.returncode == 2 and "choose one of: none, cat, dog, robot" in r.stderr
    assert "Space station" in run("styles").stdout


# ---- the page ----

def _js(name):
    return (JS / name).read_text()


def test_the_app_is_registered_and_reachable():
    reg = _js("05-apps-registry.js")
    assert re.search(r"office:\{id:'office'.*render:renderOffice,onClose:officeClose", reg, re.S)
    assert "'office'" in reg.split("const DESKTOP_APPS=")[1].split("]")[0]
    assert "'office'" in _js("06a-deck.js").split("const DECK_DEFAULTS=")[1].split("\n];")[0]
    assert "office:()=>officeContext()" in reg, "the chat on the right knows what the office shows"
    ws = _js("09-websocket.js")
    assert "case 'office': refreshApp('office')" in ws and "officeReload()" in ws


def test_one_seam_feeds_every_scene():
    mv = _js("01c-movement.js")
    assert "function scenePulse(" in mv and "officePulse(kind,label,ev)" in mv and "crewPulse(kind,label,ev)" in mv
    body = mv.split("function movementPulse(")[1][:900]
    assert "scenePulse(kind,label,ev)" in body
    hud = _js("10b-huddle.js")
    assert "scenePulse('say'" in hud and "scenePulse('msg'" in hud
    for f in JS.glob("*.js"):
        if f.name not in ("01c-movement.js", "24d-office.js"):
            assert "officePulse(" not in f.read_text(), f"{f.name} calls the office directly — use scenePulse"
    ws = _js("09-websocket.js")
    assert "movementPulse('tool',ev.name,ev)" in ws and "movementPulse('turn',ev.conversation_id,ev)" in ws


def test_the_page_sleeps_paints_rooms_not_people_and_moves_only_on_events():
    of = _js("24d-office.js")
    assert "setInterval" not in of, "a window's periodic work is winTick, and a canvas is rAF"
    assert "winAwake(O.w)" in of and "winTick(w,officeKick,0" in of
    assert "1/30" in of and "1/6" in of, "the frame budget: 30 while something moves, 6 at rest"
    assert "prefers-reduced-motion" in of
    assert ".filter=" not in of and "shadowBlur" not in of, "no blur, no canvas shadow"
    assert "avatarSrc(key,{sheet:1})" in of, "faces are the server's sheet — no second painter"
    # the people do not wander: nothing picks a random walk target except the pet
    walks = re.findall(r"officeWalk\([^;]*Math\.random", of)
    assert not walks
    assert "function officePetStep" in of and "Math.random" in of.split("function officePetStep")[1].split("function officePetDraw")[0]
    # an answer that arrives mid-walk is heard after the question, never before it
    assert "visit.reply" in of and "!asker.visit.asked" in of
    # the chat is the window's own agent panel, moved into the layout — not a second chat
    assert "initCopilot(w,chat)" in of and "cp-btn" in of


def test_a_phone_gets_the_chat_as_a_sheet_and_the_tap_floor():
    css = (ROOT / "agentos/ui/src/css/23-office.css").read_text()
    assert "@container (max-width:760px)" in css and "body.dev-mobile .of-chat" in css
    assert ".of-empty[hidden]{display:none}" in css
    assert "body.dev-touch .of-chip" in css and "min-height:var(--tap)" in css
