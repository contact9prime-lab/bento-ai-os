"""An app built in Chat keeps the chat that built it, and App Studio shows it.

Reported with two screenshots: Claude Code built a "Volume Compression Tracker" in
Chat, and App Studio's Builder pane showed only its intro text. Nothing linked an app
to a conversation: the Studio looked for one titled "build: <name>", which only its
own builds make. The app was also named after the first 60 characters of the message
("Make an application that tracks the stocks that are going th").

Now every version records the conversation that made it, the Studio reads that back,
a follow-up in the same chat edits the same app, and an app names itself from its
<title>.
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors as execmod                           # noqa: E402
from agentos.memory import Store                                   # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
SERVER = (ROOT / "agentos/server.py").read_text()
APP = "<!doctype html><html><head><title>{}</title></head><body>hi</body></html>"


def _ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir(exist_ok=True)
    return str(d)


def test_a_version_records_the_conversation_and_the_app_lists_it(tmp_path):
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("Make an application that tracks volume")
    aid = store.save_app("Volume Tracker", "", "", APP.format("v1"), note="built", conversation_id=cid)
    store.save_app("Volume Tracker", "", "", APP.format("v2"), note="edited")   # a Studio edit, no chat
    convs = store.app_conversations(aid)
    assert [c["id"] for c in convs] == [cid]
    assert convs[0]["title"] == "Make an application that tracks volume" and convs[0]["first_version"] == 1
    assert store.app_for_conversation(cid)["id"] == aid
    assert store.app_for_conversation("") is None and store.app_for_conversation("nope") is None
    assert store.app_versions(aid)[-1]["conversation_id"] == cid


def test_an_old_database_gets_the_column(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE app_versions (id TEXT PRIMARY KEY, app_id TEXT, version INTEGER, "
                "html TEXT, note TEXT DEFAULT '', created_at REAL)")
    con.execute("INSERT INTO app_versions VALUES ('v','a',1,'<h1>x</h1>','old',0)")
    con.commit()
    con.close()
    store = Store(db)
    cols = {r["name"] for r in store.db.execute("PRAGMA table_info(app_versions)").fetchall()}
    assert "conversation_id" in cols
    assert store.app_conversations("a") == [], "a version from before has no chat, and that is fine"


def test_a_chat_build_is_named_from_its_title_and_records_the_chat(tmp_path):
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("Make an application that tracks the stocks that are going th")
    co = execmod.new_app_checkout(_ws(tmp_path), "Tracks The Stocks")
    co["conversation_id"] = cid
    Path(co["path"]).write_text(APP.format("Volume Compression Tracker"))
    saved, why = execmod.commit_app(store, co)
    assert saved and "Volume Compression Tracker" in why
    app = store.app_for_conversation(cid)
    assert app and app["name"] == "Volume Compression Tracker"
    # no title: the name it was checked out with
    co2 = execmod.new_app_checkout(_ws(tmp_path), "Unit Converter")
    Path(co2["path"]).write_text("<!doctype html><html><body>x</body></html>")
    assert execmod.commit_app(store, co2)[0]
    assert any(a["name"] == "Unit Converter" for a in store.list_apps())


def test_a_new_app_never_lands_on_an_existing_one(tmp_path):
    store = Store(tmp_path / "a.db")
    store.save_app("Pomodoro", "", "", APP.format("Pomodoro"))
    co = execmod.new_app_checkout(_ws(tmp_path), "timer")
    Path(co["path"]).write_text(APP.format("Pomodoro"))
    saved, why = execmod.commit_app(store, co)
    assert saved and "Pomodoro 2" in why
    assert sorted(a["name"] for a in store.list_apps()) == ["Pomodoro", "Pomodoro 2"]


def test_a_stopped_turn_installs_a_finished_app_and_not_half_of_one(tmp_path):
    store = Store(tmp_path / "a.db")
    done = execmod.new_app_checkout(_ws(tmp_path), "done")
    Path(done["path"]).write_text(APP.format("Done App"))
    assert execmod.commit_app(store, done, finished=False)[0], \
        "stopped while it wrote a README, after the app worked"
    half = execmod.new_app_checkout(_ws(tmp_path), "half")
    Path(half["path"]).write_text("<!doctype html><html><head><title>Half</title><body><div>")
    saved, why = execmod.commit_app(store, half, finished=False)
    assert not saved and "stopped before the app was finished" in why and half["path"] in why


def test_a_follow_up_edits_the_app_this_chat_built(tmp_path):
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("build me a tracker")
    aid = store.save_app("Tracker", "", "", APP.format("Tracker"), conversation_id=cid)
    co = execmod.checkout_app(store, store.app_for_conversation(cid)["id"], _ws(tmp_path))
    co["conversation_id"] = cid
    note = execmod.chat_app_note(co)
    assert "Earlier in this chat you built" in note and co["path"] in note and "THAT file" in note
    Path(co["path"]).write_text(APP.format("Tracker").replace("hi", "sortable"))
    saved, why = execmod.commit_app(store, co)
    assert saved and "new version" in why
    assert [v["version"] for v in store.app_versions(aid)] == [2, 1]
    assert {v["conversation_id"] for v in store.app_versions(aid)} == {cid}


def test_the_chat_path_wires_all_of_it():
    i = SERVER.index("checkout = execmod.new_app_checkout(env.workspace")
    chat = SERVER[i - 3000:i + 6000]
    assert "_default_app_name(text)" in chat[3000:3200], "not the first 60 characters of the message"
    assert "store.app_for_conversation(cid)" in chat and "execmod.chat_app_note" in chat
    assert '_co["conversation_id"] = cid' in chat
    # committed in `finally`, so a stop after the app was written still installs it
    fin = chat[chat.index("finally:"):chat.index("finally:") + 1500]
    assert "commit_app(store, _co, note=f\"in Chat: {text[:110]}\"" in fin and "finished=turn_done" in fin
    assert '"type": "app_saved"' in chat
    # the Studio's own builds record their build conversation too
    assert "html, _conv=cid)" in SERVER and "note=prompt[:120], conversation_id=cid)" in SERVER
    assert '@app.get("/api/apps/{aid}/conversations")' in SERVER


def test_create_app_files_under_the_agents_conversation_never_the_models(tmp_path):
    agent = (ROOT / "agentos/agent.py").read_text()
    assert '"_conv": self.conversation_id or ""' in agent, "injected after the model's args"
    assert 'k != "_conv"' in agent, "a model-supplied _conv is dropped first"
    from agentos.tools import Toolbox
    store = Store(tmp_path / "t.db")
    tb = Toolbox({"workspace": str(tmp_path), "providers": {}, "port": 8321}, store)
    cid = store.create_conversation("make me a clock")
    out = asyncio.run(tb.execute("create_app", {"name": "Clock", "html": APP.format("Clock"), "_conv": cid}))
    assert "saved" in out, out
    assert store.app_for_conversation(cid)["name"] == "Clock"


def test_app_studio_reads_the_recorded_conversations():
    studio = (JS / "26-studio.js").read_text()
    body = studio[studio.index("async function studioLoadHistory"):studio.index("function studioWireHistory")]
    assert "'/api/apps/'+sel+'/conversations'" in body
    assert "'build: '+app.name" in body, "older builds still fall back to the title"
    assert "Built in Chat" in body and "data-open-chat" in body
    assert "openConv(b.dataset.openChat)" in studio
    # a history-only log is re-read, so a follow-up in Chat shows up
    assert "STUDIO.log.querySelector('.st-src')" in studio
    ws = (JS / "09-websocket.js").read_text()
    assert "case 'app_saved':" in ws and "handoffApp(" in ws
    hand = (JS / "10a-handoff.js").read_text()
    assert "function handoffApp" in hand and "await loadUserApps()" in hand
