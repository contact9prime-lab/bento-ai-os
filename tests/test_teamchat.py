"""The lead's identity, and people on linked teams writing to each other.

What these defend:

- your agent is the one in the BLAZER — generated so, migrated so once on a machine
  whose character predates outfits, kept through a reroll, and still a choice a person
  can undo; every outfit paints on every skin;
- an identity from another team is a name and a face, nothing more: cut to size, held
  to the closed set, painted here by the one painter (a recipe it cannot parse is the
  default face, never an error);
- a message is kept first and delivered second: at once over the link's own mTLS when
  the other machine can be reached, with the next exchange when it cannot, and never
  twice (the id is the same on both sides);
- the receiving side can close the door (muted), the sender is told in words, and a
  refused message is not retried every thirty seconds;
- nothing here is readable by an agent: no tool names the table;
- and the terminal says and reads the same rows, between accounts too.
"""
import asyncio
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import avatars as av                                     # noqa: E402
from agentos import teamchat, teamlink                                # noqa: E402
from agentos.memory import Store                                      # noqa: E402

ROOT = Path(__file__).parent.parent


# ---- the lead ----------------------------------------------------------------------------------

def test_your_agent_is_generated_in_the_blazer_and_specialists_are_not():
    assert av.generate(av.AGENT)["outfit"] == "blazer"
    others = {av.generate(f"specialist-{i}")["outfit"] for i in range(40)}
    assert "blazer" not in others and others <= {"shirt", "hoodie"}


def test_a_character_stored_before_outfits_puts_the_agent_in_the_blazer_once(tmp_path):
    s = Store(tmp_path / "a.db")
    old = {k: v for k, v in av.generate(av.AGENT).items() if k != "outfit"}
    s.avatar_put(av.AGENT, old)
    av.ensure(s, {"agent_name": "Aria"})
    assert av.recipe_for(s, av.AGENT)["outfit"] == "blazer", "the lead is migrated into the blazer"
    av.update(s, {"agent_name": "Aria"}, av.AGENT, {"outfit": "shirt"})
    av.ensure(s, {"agent_name": "Aria"})
    assert av.recipe_for(s, av.AGENT)["outfit"] == "shirt", "a person's later choice is never undone"
    av.update(s, {"agent_name": "Aria"}, av.AGENT, {"outfit": "blazer"})
    assert av.reroll(s, {"agent_name": "Aria"}, av.AGENT)["outfit"] == "blazer", "a reroll is never a demotion"


def test_outfit_is_a_closed_choice_and_every_one_paints_on_every_skin():
    with pytest.raises(ValueError, match="shirt, blazer, hoodie"):
        av.validate({"outfit": "cape"})
    assert "blazer over a white shirt and tie" in av.describe({"outfit": "blazer", "hue": 172})
    for outfit in av.OUTFITS:
        for skin in range(len(av.SKINS)):
            buf = av.paint({"skin": skin, "outfit": outfit, "hue": 172})
            assert sum(buf[3::4]) > 0
    shirt = av.paint({"outfit": "shirt", "hue": 172})
    blazer = av.paint({"outfit": "blazer", "hue": 172})
    torso = lambda b: b"".join(bytes(b[(y * av.W + x) * 4:(y * av.W + x) * 4 + 3]) for y in range(13, 19) for x in range(4, 12))
    assert torso(shirt) != torso(blazer), "the blazer is visibly not a shirt"
    assert "outfit" in av.palette() and av.palette()["outfit"] == av.OUTFITS


# ---- an identity from another team -------------------------------------------------------------

def test_an_identity_from_elsewhere_is_a_name_and_a_face_and_nothing_else():
    got = teamlink.clean_identity({"agent_name": "A" * 200, "person": "<b>ada</b>",
                                   "agent": {"hair": "plaid", "outfit": "blazer", "evil": "x"},
                                   "script": "alert(1)"})
    assert len(got["agent_name"]) == 40
    assert set(got) == {"agent_name", "person", "agent"}, "unknown keys are dropped"
    assert set(got["agent"]) == set(av.FIELDS), "the look is held to the closed set"
    assert teamlink.clean_identity("nope") == {"agent_name": "", "person": ""}


def _png_size(b):
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", b[16:24])


# ---- messages: the shape -----------------------------------------------------------------------

def test_a_message_is_held_to_its_shape():
    m = teamchat.new_message("  hello  ", {"person": "ada", "me": av.generate("@me")})
    assert m["text"] == "hello" and m["sender"] == "ada" and len(m["id"]) == 16
    with pytest.raises(ValueError):
        teamchat.new_message("   ", {})
    with pytest.raises(ValueError, match="4000"):
        teamchat.new_message("x" * 4001, {})
    c = teamchat.clean_message({"id": "abcdef0123456789", "text": "hi", "sender": "x" * 90,
                                "look": {"skin": 99}, "ts": 9e12, "html": "<script>"})
    assert set(c) == {"id", "text", "ts", "sender", "look"} and len(c["sender"]) == 40
    assert c["ts"] < 9e12, "a sender cannot date a message into the future"
    with pytest.raises(ValueError):
        teamchat.clean_message({"id": "../../etc", "text": "hi"})


def test_receiving_dedupes_counts_and_honours_the_mute(tmp_path):
    s = Store(tmp_path / "a.db")
    lk = {"label": "office", "owner": ""}
    m = {"id": "abcdef0123456789", "text": "hi", "sender": "ada"}
    got, why = teamchat.receive(s, "", lk, m)
    assert got and not why
    assert teamchat.receive(s, "", lk, m) == (None, ""), "a retried delivery is one row"
    assert len(s.team_msgs("office")) == 1
    assert teamchat.receive(s, "", {**lk, "chat_muted": True}, {**m, "id": "b" * 16})[1].startswith("they are not taking")
    teamchat._meter.clear()
    for i in range(teamchat.RATE):
        teamchat.overflowing("", "flood")
    assert teamchat.overflowing("", "flood")
    teamchat._meter.clear()


def test_no_agent_can_read_a_message():
    from agentos.tools import TOOL_SCHEMAS
    text = json.dumps(TOOL_SCHEMAS)
    assert "team_message" not in text and "team_msgs" not in text
    for f in (ROOT / "agentos").glob("*.py"):
        if f.name in ("memory.py", "teamchat.py", "server.py", "__main__.py"):
            continue
        assert "team_msg" not in f.read_text(), f"{f.name} reaches the people's messages"


# ---- messages: over a real link -----------------------------------------------------------------

@pytest.fixture()
def office(tmp_path):
    """Another Bento on its own loop and thread — 'office' — with a mini chat door that
    does what the server's does, and the server under test linked to it."""
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    home = tmp_path / "office"
    ostore = Store(home / "agentos.db")
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    muted = {"on": False}

    async def on_ask(lk, req):
        lk = {**lk, "chat_muted": muted["on"]}
        if req.get("op") == "chat":
            msg, why = teamchat.receive(ostore, "", lk, req.get("message"))
            if why:
                return {"ok": False, "error": why, "refused": True}
        waiting = ostore.team_msg_pending(lk["label"])
        ostore.team_msg_delivered([m["id"] for m in waiting])
        return {"ok": True, "messages": [{k: m[k] for k in ("id", "text", "ts", "sender", "look")} for m in waiting]}

    async def start():
        with teamlink.at(home):
            lst = teamlink.Listener({"team": {"machine_name": "office"}}, on_ask=on_ask,
                                    identity=lambda o: {"agent_name": "Otto", "person": "olu",
                                                        "agent": av.generate(av.AGENT)})
            port = await lst.start("127.0.0.1", 0)
            inv = teamlink.invite("", "machine", address="127.0.0.1", port=port)
        return lst, inv
    lst, inv = asyncio.run_coroutine_threadsafe(start(), loop).result(15)
    teamlink.remove("", "office")
    with TestClient(servermod.app) as cl:
        lk = asyncio.run(teamlink.join(inv["invite"], "", label="office", cfg=servermod.state["cfg"],
                                       identity=servermod._team_identity("")))
        yield cl, servermod, lk, ostore, muted, loop
    asyncio.run_coroutine_threadsafe(lst.stop(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)
    teamlink.remove("", "office")


def test_a_link_carries_who_the_other_team_is(office):
    cl, servermod, lk, ostore, muted, loop = office
    assert lk["peer_identity"]["agent_name"] == "Otto" and lk["peer_identity"]["agent"]["outfit"] == "blazer"
    d = cl.get("/api/team/links").json()
    card = next(x for x in d["links"] if x["label"] == "office")
    assert card["peer_identity"]["person"] == "olu"
    face = cl.get("/api/avatar.png", params={"recipe": json.dumps(card["peer_identity"]["agent"]), "crop": "face"})
    assert face.headers["content-type"] == "image/png" and _png_size(face.content) == (14, 14)
    junk = cl.get("/api/avatar.png", params={"recipe": "{not json", "crop": "face"})
    assert junk.status_code == 200, "a recipe it cannot read is the default face, never an error"


def test_write_deliver_answer_and_read(office):
    cl, servermod, lk, ostore, muted, loop = office
    r = cl.post("/api/team/chat/office", json={"text": "Is the Q3 deck ready?"}).json()
    assert r["ok"] and r["delivered"], r
    got = ostore.team_msgs("office")[0] if ostore.team_msgs("office") else ostore.team_msgs(
        next(iter(ostore.team_threads())))[0]
    assert got["text"] == "Is the Q3 deck ready?" and got["dir"] == "in"
    assert got["look"], "the sender's face travelled with it"

    # office answers: its reply waits there and comes back with the next exchange
    reply = teamchat.new_message("Friday.", {"person": "olu", "me": av.generate("olu")})
    label_there = next(iter(ostore.team_threads()))
    ostore.team_msg_add(label_there, reply, "out")
    th = cl.get("/api/team/chat/office").json()          # opening the thread pulls
    texts = [(m["dir"], m["text"]) for m in th["messages"]]
    assert texts == [("out", "Is the Q3 deck ready?"), ("in", "Friday.")], texts
    assert th["identity"]["agent_name"] == "Otto"
    assert ostore.team_msg_pending(label_there) == [], "collected once"
    threads = cl.get("/api/team/chat").json()["threads"]
    assert next(t for t in threads if t["label"] == "office")["unread"] == 0, "reading marks it read"


def test_the_other_side_can_close_the_door_and_is_not_knocked_on(office):
    cl, servermod, lk, ostore, muted, loop = office
    muted["on"] = True
    r = cl.post("/api/team/chat/office", json={"text": "hello?"}).json()
    assert r["ok"] and not r["delivered"] and "not taking messages" in r["note"]
    row = [m for m in servermod.state["store"].team_msgs("office") if m["text"] == "hello?"][0]
    assert row["delivered"] == -1, "refused, and not retried every thirty seconds"
    assert servermod.state["store"].team_msg_pending("office") == []


def test_muting_here_refuses_theirs_in_words_and_is_audited(office):
    cl, servermod, lk, ostore, muted, loop = office
    assert cl.put("/api/team/chat/office", json={"muted": True}).json()["muted"]
    here = teamlink.find("", "office")
    m = teamchat.new_message("hi", {"person": "olu"})
    got = asyncio.run(servermod._team_chat_in(here, {"op": "chat", "message": m}))
    assert not got["ok"] and got["refused"] and "not taking messages" in got["error"]
    rows = servermod.state["store"].audit_list(limit=20) if hasattr(servermod.state["store"], "audit_list") else []
    assert any(r.get("action") == "link.chat" for r in rows)
    cl.put("/api/team/chat/office", json={"muted": False})


def test_a_machine_that_cannot_be_reached_keeps_the_message_for_the_next_exchange(office):
    cl, servermod, lk, ostore, muted, loop = office
    d = teamlink._load()
    for x in d["links"]:
        if x["label"] == "office" and (x.get("owner") or "") == "":
            x["url"] = ""
    teamlink._save(d)
    r = cl.post("/api/team/chat/office", json={"text": "for later"}).json()
    assert not r["delivered"] and r["note"].startswith("kept"), r
    # office talks to us (a pull): what was waiting goes with the answer
    here = teamlink.find("", "office")
    got = asyncio.run(servermod._team_chat_in(here, {"op": "chat_pull"}))
    assert [m["text"] for m in got["messages"]] == ["for later"]
    assert servermod.state["store"].team_msg_pending("office") == []


# ---- the terminal, between accounts --------------------------------------------------------------

def test_two_accounts_write_to_each_other_from_a_terminal(tmp_path):
    home = tmp_path / "home"
    env = {**os.environ, "AGENTOS_HOME": str(home), "AGENTOS_VAULT_KEYRING": "0"}
    setup = ("from agentos import users, teamlink\n"
             "a=users.create('ada','hunter2hunter')['id'];b=users.create('bob','hunter2hunter',role='executor')['id']\n"
             "r=teamlink.request_account(a,b,{a:'ada',b:'bob'});teamlink.approve(r['id'],b,names={a:'ada',b:'bob'})\n")
    subprocess.run([sys.executable, "-c", setup], env=env, cwd=ROOT, check=True, timeout=60)
    say = subprocess.run([sys.executable, "-m", "agentos", "link", "say", "bob", "lunch", "at", "one?", "--user", "ada"],
                         env=env, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert "sent to bob ✓" in say.stdout, say.stdout + say.stderr
    read = subprocess.run([sys.executable, "-m", "agentos", "link", "chat", "ada", "--user", "bob"],
                          env=env, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert "ada: lunch at one?" in read.stdout, read.stdout + read.stderr


def test_team_chat_has_every_face():
    reg = (ROOT / "agentos/ui/src/js/05-apps-registry.js").read_text()
    assert "teamchat:{id:'teamchat'" in reg
    assert "teamchat:[" in (ROOT / "agentos/ui/src/js/01-app-icons.js").read_text()
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'team_message'" in ws and "case 'team_message_delivered'" in ws
    assert "team_message" in (ROOT / "agentos/tui_app.py").read_text()
    js = (ROOT / "agentos/ui/src/js/24c-teamchat.js").read_text()
    assert "tc.phone" in (ROOT / "agentos/ui/src/css/22-avatars.css").read_text(), "a phone gets one pane at a time"
    assert "avatarRecipeImg" in js and "/api/avatar.png" not in js, "faces go through the one door"


def test_two_installs_do_not_share_one_agent(tmp_path):
    # Unsalted, '@agent' hashed to the same person on every machine: two linked teams
    # whose leads were identical twins. Each install now draws its own.
    looks = []
    for n in range(4):
        s = Store(tmp_path / f"{n}.db")
        av.ensure(s, {"agent_name": "Aria"})
        r = av.recipe_for(s, av.AGENT)
        assert r["hue"] == av.AGENT_HUE and r["outfit"] == "blazer", "still teal, still the lead"
        looks.append(tuple(r[k] for k in av._LOOK))
    assert len(set(looks)) > 1


def test_an_untouched_default_is_redrawn_once_and_an_edited_one_is_kept(tmp_path):
    s = Store(tmp_path / "a.db")
    s.avatar_put(av.AGENT, {k: v for k, v in av.generate(av.AGENT).items() if k != "outfit"})
    s.avatar_put(av.ME, {**av.generate(av.ME), "hair": 7})            # somebody chose pink
    av.ensure(s, {"agent_name": "Aria"})
    once = av.recipe_for(s, av.AGENT)
    assert once["outfit"] == "blazer" and once["hue"] == av.AGENT_HUE
    # (a redraw can land on the default again by chance — 1 in the size of the palette
    # space — so what is pinned is that it is then STORED, not that it differs)
    av.ensure(s, {"agent_name": "Aria"})
    assert av.recipe_for(s, av.AGENT) == once, "redrawn once, then stored like any other"
    assert av.recipe_for(s, av.ME)["hair"] == 7, "an edited look is never redrawn"
