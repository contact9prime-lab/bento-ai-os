"""An app reports in the person's chats, and the phone reaches the apps.

Asked for as "the channels such as Telegram or WhatsApp have no hook into the apps: apps should
report on these channels too, Telegram's / buttons can ask the apps, and a schedule should give
its data to the channels or their groups".
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import appchannels, appjobs, appphone, approvalcard, runlog    # noqa: E402
from agentos import telegram_admin                                          # noqa: E402
from agentos.agent import APP_SPEAKS, Agent                                 # noqa: E402
from agentos.memory import Store                                            # noqa: E402
from agentos.policy import MAIN, PDP, Principal, action_of                  # noqa: E402
from agentos.scheduler import Scheduler                                     # noqa: E402
from agentos.tools import APP_BOUND_TOOLS, SAFE_TOOLS, Toolbox               # noqa: E402

ROOT = Path(__file__).parent.parent
OWNER, GROUP, STRANGER = 111, -100222, 333


class FakeBridge:
    def __init__(self):
        self.sent = []

    async def send(self, text, chat=None):
        self.sent.append((chat, text))
        return "sent via Telegram"


def _world(tmp_path, autonomy="balanced"):
    c = {"agent_name": "Aria", "autonomy": autonomy, "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path / "ws"), "providers": {}, "port": 8321,
         "sandbox": {"enabled": False}, "memory": {"inject_facts": 0, "inject_user": 0},
         "telegram": {"bot_token": "x", "owner_chat_id": OWNER}}
    os.makedirs(c["workspace"], exist_ok=True)
    store = Store(tmp_path / "t.db")
    for cid, title, kind, ok in ((OWNER, "Piyush", "private", 1), (GROUP, "Traders", "supergroup", 1),
                                 (STRANGER, "Someone", "private", 0)):
        store.tg_upsert_chat(cid, title, "", kind)
        store.tg_set_allowed(cid, ok, "test")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    tb.telegram = FakeBridge()

    async def bc(_ev):
        pass
    tb.broadcast = bc
    sched = Scheduler(c, store, tb, bc)
    tb.scheduler = sched
    aid = store.save_app("Signal Desk", "", "", "<html><title>Signal Desk</title></html>")
    return c, store, tb, sched, aid


def _call(tb, c, aid, args, principal=None, approve=False):
    seen = []

    async def emit(_ev):
        pass

    async def approver(name, a, reason, offer=None):
        seen.append((name, a, offer))
        return approve
    agent = Agent({**c, "max_steps": 1}, tb, "", emit, approver, tool_filter=["send_to_channel"],
                  principal=principal or Principal("app", aid), surface="task")
    agent.app_id = aid
    out, *_ = asyncio.run(agent.call_tool("send_to_channel", args))
    return out, seen


def test_only_chats_the_person_let_in_are_destinations(tmp_path):
    c, store, tb, _, _ = _world(tmp_path)
    ids = [d["id"] for d in appchannels.destinations(store, c)]
    assert ids == [f"telegram:{OWNER}", f"telegram:{GROUP}"], "the stranger never let in is not one"
    labels = [d["label"] for d in appchannels.destinations(store, c)]
    assert labels == ["you on Telegram", "the group Traders on Telegram"]
    assert appchannels.resolve(store, c, "telegram")[0]["id"] == f"telegram:{OWNER}"
    assert appchannels.resolve(store, c, "Traders")[0]["id"] == f"telegram:{GROUP}"
    dest, err = appchannels.resolve(store, c, f"telegram:{STRANGER}")
    assert dest is None and "not a chat this app may send to" in err


def test_the_gate_decides_the_exact_chat_and_a_message_is_the_apps(tmp_path):
    assert "send_to_channel" in APP_BOUND_TOOLS and "send_to_channel" in APP_SPEAKS
    assert "send_to_channel" not in SAFE_TOOLS and "channel_destinations" in SAFE_TOOLS
    assert action_of("send_to_channel", {"_dest": f"telegram:{GROUP}"}) == ("channel.send", f"channel:telegram/{GROUP}")
    assert action_of("send_to_channel", {"to": "telegram:1"}) == ("channel.send", "channel:none"), \
        "a caller's own words never name the resource"
    c, store, tb, _, aid = _world(tmp_path)
    out, seen = _call(tb, c, aid, {"text": "BTC crossed 100k", "to": "Traders"})
    assert seen and seen[0][0] == "send_to_channel", "the first send to a chat asks"
    assert str(out).startswith(("[denied]", "not approved", "[error]")), out
    assert tb.telegram.sent == [], "nobody said yes: nothing went out"
    card = approvalcard.card("send_to_channel", seen[0][1], who='The app "Signal Desk"')
    assert card["body"].startswith("To: the group Traders on Telegram")
    # Always, on that card: the app's grant for that one chat
    offer = seen[0][2]
    assert offer and offer["principal_kind"] == "app" and offer["resource"] == f"channel:telegram/{GROUP}"
    store.add_grant("app", aid, "channel.send", f"channel:telegram/{GROUP}", source="user")
    out, seen = _call(tb, c, aid, {"text": "BTC crossed 100k", "to": "Traders"})
    assert out == "sent to the group Traders on Telegram" and not seen
    assert tb.telegram.sent == [(GROUP, "▦ Signal Desk\nBTC crossed 100k")], "the app's name goes first"
    # the grant is for that group only
    out, seen = _call(tb, c, aid, {"text": "hi", "to": "telegram"})
    assert seen, "your own chat is another chat, and asks for itself"


def test_a_schedule_working_for_the_app_sends_as_the_app(tmp_path):
    """The agent of a schedule runs as the person with the app beside it; the message is still
    the app's, so the app's grant decides it, and the person's would not."""
    c, store, tb, _, aid = _world(tmp_path)
    store.add_grant("app", aid, "channel.send", f"channel:telegram/{OWNER}", source="user")
    out, seen = _call(tb, c, aid, {"text": "daily summary", "to": "telegram"}, principal=MAIN)
    assert out == "sent to you on Telegram" and not seen
    led = store.db.execute("SELECT principal_kind, action, effect FROM audit WHERE action='channel.send' "
                           "ORDER BY rowid DESC LIMIT 1").fetchone()
    assert (led["principal_kind"], led["effect"]) == ("app", "allow")


def test_an_app_never_sends_for_another_app(tmp_path):
    c, store, tb, _, aid = _world(tmp_path)
    other = store.save_app("Notes", "", "", "<html></html>")
    store.add_grant("app", other, "channel.send", f"channel:telegram/{OWNER}", source="user")
    out, seen = _call(tb, c, aid, {"text": "x", "to": "telegram", "app": "Notes"})
    assert seen, "the grant is Notes', and the caller is Signal Desk"


def test_a_job_reports_its_message_in_the_chats_its_card_named(tmp_path):
    c, store, tb, sched, aid = _world(tmp_path)
    script = ("import json\nprint(json.dumps({'btc': 101000, "
              "'_message': 'BTC is above 100k: 101,000'}))\n")
    out = asyncio.run(tb.schedule_app_job(title="Watch BTC", script=script, interval_minutes=5,
                                          key="prices", _app=aid, send_to=["telegram", "Traders"]))
    assert out.startswith("scheduled: Watch BTC"), out
    task = appjobs.find(store, aid, "Watch BTC")
    assert appjobs.targets_of(task) == [f"telegram:{OWNER}", f"telegram:{GROUP}"]
    refs = {g["resource"] for g in store.list_grants() if g.get("source_ref") == f"job:{task['id']}"}
    assert {f"channel:telegram/{OWNER}", f"channel:telegram/{GROUP}"} <= refs
    asyncio.run(sched._run_task(task))
    data = json.loads(store.get_app_data(aid))
    assert data["prices"] == {"btc": 101000}, "the message is sent, not saved"
    assert [chat for chat, _ in tb.telegram.sent] == [OWNER, GROUP]
    assert all(t.endswith("BTC is above 100k: 101,000") for _, t in tb.telegram.sent)
    assert "sent to you on Telegram" in data["_jobs"]["Watch BTC"]["note"]
    rows = runlog.schedules(store)
    assert rows[0]["sends_to"] == "Piyush on Telegram, Traders on Telegram"
    # a run with nothing to say says nothing
    tb.telegram.sent.clear()
    quiet = "import json\nprint(json.dumps({'btc': 99000, '_message': ''}))\n"
    asyncio.run(tb.schedule_app_job(title="Watch BTC", script=quiet, interval_minutes=5,
                                    key="prices", _app=aid, send_to=["telegram", "Traders"]))
    asyncio.run(sched._run_task(appjobs.find(store, aid, "Watch BTC")))
    assert tb.telegram.sent == []
    # removing the job takes its chats' grants with it
    store.delete_task(task["id"])
    assert not [g for g in store.list_grants() if g.get("source_ref") == f"job:{task['id']}"]


def test_a_job_naming_a_stranger_is_refused_at_the_save(tmp_path):
    c, store, tb, _, aid = _world(tmp_path)
    out = asyncio.run(tb.schedule_app_job(title="Spam", script="print(1)", interval_minutes=5,
                                          key="x", _app=aid, send_to=[f"telegram:{STRANGER}"]))
    assert out.startswith("[error]") and not appjobs.find(store, aid, "Spam")


def test_the_job_card_says_where_it_reports():
    args = {"title": "Watch", "script": "print(1)", "interval_minutes": 5, "key": "p",
            "_send_labels": "you on Telegram and the group Traders on Telegram"}
    c = approvalcard.card("schedule_app_job", args, who='The app "Signal Desk"')
    assert "send it to you on Telegram and the group Traders on Telegram" in c["body"]
    assert any("also sends it to" in m for m in c["means"])
    # one yes starts a job: Allow must not read as "asks you every time"
    assert c["choices"]["allow"].startswith("The job starts and runs every 5 minutes without asking again")


def test_the_phone_glances_at_an_app_and_asks_it(tmp_path):
    c, store, tb, sched, aid = _world(tmp_path)
    asyncio.run(tb.schedule_app_job(title="Scan", script="import json\nprint(json.dumps({'signals': 4}))\n",
                                    interval_minutes=5, key="scan", _app=aid))
    asyncio.run(sched._run_task(appjobs.find(store, aid, "Scan")))
    app, rest = appphone.find(store, "signal desk what moved today")
    assert app["id"] == aid and rest == "what moved today"
    text = appphone.glance(store, app)
    assert "Scan · every 5 min · just now" in text and "signals: 4" in text
    assert "/app Signal Desk <your question>" in text
    said = asyncio.run(appphone.answer(store, "Nope", "telegram", None))
    assert "Which app?" in said and "Signal Desk" in said
    names = [c_ for c_, _, _ in telegram_admin.COMMANDS]
    assert "/apps" in names and "/app" in names
    menu = [m["command"] for m in telegram_admin.menu(True)]
    assert "apps" in menu and "apps" not in [m["command"] for m in telegram_admin.menu(False)], \
        "the owner's console, like /flows"


def test_the_phone_question_is_the_apps_own_assistant():
    src = (ROOT / "agentos/server.py").read_text()
    body = src[src.index("async def app_ask_from_phone("):]
    body = body[:body.index("\n\n\n")]
    assert 'Principal("app", app_id)' in body and '"agent.invoke", "agent:main"' in body
    assert "suspended_at" in body and "about=True" in body
    wa = (ROOT / "agentos/whatsapp.py").read_text()
    assert '("/apps", "/app")' in wa and "appphone.answer" in wa


def test_the_builder_is_told_to_report_through_appchannel():
    src = (ROOT / "agentos/server.py").read_text()
    assert "window.appChannel = {" in src and "appChannel.send(text, {to:'telegram'})" in src
    assert "send_to:['telegram']" in src and '"_message"' in src
