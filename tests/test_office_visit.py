"""Visiting a linked team's office — and what a visit may NOT show.

Asked for as: the Crew stage and the Office should show remote agents, be clickable
to start with, and let you see the other team's office. The linked-teams rules decide
the shape (CLAUDE.md → Linked teams): a link grants nothing, not even names, so

- the ANSWERING side shows its look, its lead, and only the agents this link's cells
  let it ask; busy or free, never what the work is; the lead's state not at all;
- the ASKING side cleans the answer where it arrives — the closed sets for style, pet
  and colour, `plain` on every name, `avatars.clean` on every look — and draws it with
  ITS painter, so nothing the other side sends reaches a page as more than a value;
- a person in their office is a door to a chat through one of YOUR agents (ask_agent
  under the matrix), prefilled and never sent.
"""
import asyncio
import os
import struct
import sys
import tempfile
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import avatars as av, fabric, office, teamlink          # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _their_office(tmp_path):
    store = Store(tmp_path / "theirs.db")
    for n in ("analyst", "secret-project-bot"):
        store.save_subagent({"name": n, "soul": n})
    cfg = {"agent_name": "Otto", "office": {"style": "night", "name": "Night Desk", "pet": "dog"}}
    return cfg, store


def test_the_answering_side_shows_only_whom_the_link_may_ask(tmp_path):
    cfg, store = _their_office(tmp_path)
    got = fabric.office_for_link(store, cfg, "home")
    assert [r["key"] for r in got["rows"]] == ["@agent"], "no cell ticked: their lead only, no names"
    fabric.set_link_access(store, "home", theirs_may_ask=["analyst"])
    store.db.execute("INSERT INTO fabric_runs(id,kind,ref,status,input,started_at) VALUES(?,?,?,?,?,strftime('%s','now'))",
                     ("r1", "delegate", "analyst", "running", "Q3 numbers for the board"))
    store.db.commit()
    got = fabric.office_for_link(store, cfg, "home")
    keys = [r["key"] for r in got["rows"]]
    assert keys == ["@agent", "analyst"] and "secret-project-bot" not in str(got)
    an = got["rows"][1]
    assert an["working"] is True and "Q3" not in str(got), "busy, never what the work is"
    assert got["rows"][0]["working"] is None, "the lead's state is the person's, not shared"
    assert got["office"] == {"style": "night", "name": "Night Desk", "pet": "dog"}
    assert an["recipe"] == av.recipe_for(store, "analyst")


def test_what_arrives_is_cleaned_where_it_arrives():
    hostile = {"ok": True,
               "office": {"style": "castle", "name": "\x1b]52;c;cGF5\x07Evil‮ HQ" + "x" * 90, "pet": "dragon",
                          "extra": "<script>"},
               "rows": [{"room": "R\x1b[31m", "color": "#ff0000", "key": "../../etc<b>", "label": "a‮b",
                         "working": "yes", "recipe": {"skin": 99, "hue": "red", "style": "mohawk"}},
                        "not a row"] + [{"key": f"p{i}", "label": "p"} for i in range(100)]}
    v = teamlink.clean_office(hostile)
    assert v["office"]["style"] == office.DEFAULT_STYLE and v["office"]["pet"] == "none"
    assert "\x1b" not in v["office"]["name"] and "‮" not in v["office"]["name"] and len(v["office"]["name"]) <= 24
    assert "extra" not in v["office"]
    r = v["rows"][0]
    assert r["key"] == "....etcb" and r["color"] == "slate" and r["working"] is None
    assert "\x1b" not in r["room"] and "‮" not in r["label"]
    assert r["recipe"] == av.clean({"skin": 99, "hue": "red", "style": "mohawk"}), "held to the closed set"
    assert len(v["rows"]) == teamlink.VISIT_ROWS, "a visit is not a census"
    text = teamlink.visit_text("office", v)
    assert "not shared" in text


def _png_size(b):
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", b[16:24])


@pytest.fixture()
def linked(tmp_path):
    """Another Bento on its own loop: its listener answers `office` with the REAL
    office_for_link over its own store, as the server's router does."""
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    home = tmp_path / "office"
    cfg, ostore = _their_office(tmp_path)
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    async def on_ask(lk, req):
        if req.get("op") == "office":
            return fabric.office_for_link(ostore, cfg, lk["label"])
        return {"ok": False, "error": "unknown request"}

    async def start():
        with teamlink.at(home):
            lst = teamlink.Listener({"team": {"machine_name": "office"}}, on_ask=on_ask,
                                    identity=lambda o: {"agent_name": "Otto", "agent": av.generate(av.AGENT)})
            port = await lst.start("127.0.0.1", 0)
            inv = teamlink.invite("", "machine", address="127.0.0.1", port=port)
        return lst, inv
    lst, inv = asyncio.run_coroutine_threadsafe(start(), loop).result(15)
    teamlink.remove("", "office")
    with TestClient(servermod.app) as cl:
        lk = asyncio.run(teamlink.join(inv["invite"], "", label="office", cfg=servermod.state["cfg"],
                                       identity=servermod._team_identity("")))
        servermod._VISITS.clear()
        yield cl, servermod, lk, ostore
    teamlink.remove("", "office")


def test_a_visit_over_a_real_link(linked):
    cl, servermod, lk, ostore = linked
    # the link on THEIR side is labelled by them; tick analyst for every label they hold
    for l in {x["label"] for x in [lk]} | {"home", "office"}:
        fabric.set_link_access(ostore, l, theirs_may_ask=["analyst"])
    servermod._VISITS.clear()
    r = cl.get("/api/team/links/office/office")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["office"]["name"] == "Night Desk" and d["office"]["style"] == "night"
    names = [x["label"] for x in d["rows"]]
    assert "secret-project-bot" not in names and "Night Desk" in d["text"]
    png = cl.get("/api/team/links/office/office.png")
    assert png.status_code == 200 and _png_size(png.content)[0] > 0
    vis = cl.get("/api/team/visitors").json()["teams"]
    assert vis and vis[0]["label"] == "office" and vis[0]["ok"]
    assert cl.get("/api/team/links/nobody/office").status_code == 404
    # cached per user and link: a second visit within the TTL is not a second call
    calls = []
    real = teamlink.call

    async def counting(*a, **k):
        calls.append(1)
        return await real(*a, **k)
    teamlink.call = counting
    try:
        cl.get("/api/team/links/office/office")
        assert calls == [], "the stage and the home row must not call another machine per paint"
        cl.get("/api/team/links/office/office?fresh=1")
        assert calls == [1]
    finally:
        teamlink.call = real


def test_the_visit_has_a_door_on_every_face():
    of = (JS / "24d-office.js").read_text()
    assert "function officeVisit(" in of and "function linkedAsk(" in of
    assert "/api/team/links/'+encodeURIComponent(label)+'/office" in of
    ask = of.split("async function linkedAsk(")[1].split("\n}")[0]
    assert "i.value=" in ask and "Enter" not in ask and "send" not in ask.replace("sent", ""), "prefilled, never sent"
    assert "avatarRecipeImg(" in of, "their faces through the one door"
    crew = (JS / "01d-crew.js").read_text()
    assert "/api/team/visitors" in crew and "avatarRecipeSrc(g.rec,{sheet:1})" in crew
    assert "CREW_GUEST_MS=300000" in crew, "their roster is a call to another machine"
    home = (JS / "01b-immersive.js").read_text()
    assert "officeVisit(b.dataset.l)" in home
    assert '"chat_pull", "office")' in (ROOT / "agentos/teamlink.py").read_text(), "the listener allows the op"
    assert '"visit"' in (ROOT / "agentos/__main__.py").read_text()
    assert "/api/team/visitors" in (ROOT / "agentos/tui_app.py").read_text()
    # a visit is keyed on the user as well as the link (CLAUDE.md: caches keyed on the user)
    assert "_VISITS.get((owner, label))" in (ROOT / "agentos/server.py").read_text()
