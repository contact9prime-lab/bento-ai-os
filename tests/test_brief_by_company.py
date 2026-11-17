"""The Brief on a phone says whose each item is and what is expected, and a department's
card in a chat keeps following its task.

Two reports from one morning:

- The 08:00 Brief on Telegram: "it is very unclear what is expected to be done by the user
  in the brief, which company, what is it saying". It was 45 lines of a bullet and a title
  ("• The auditor failed Tech's task — auditor") from three companies in one list.
- A screenshot of the Office: `department_task … running · 10m 20s` with nothing under it,
  while the log named who had got which piece. Replayed in a browser: the card follows its
  desk's run through a link made when the run starts, and a panel that left the chat and
  came back redrew the card from a snapshot without it.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

import pytest                                                        # noqa: E402

from agentos import brief, company, tools                           # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
CO = {"growth-launches-desk": "Bento Growth", "bhav-tech-desk": "Bhav Capital",
      "bhav-research-desk": "Bhav Capital"}


def _brief(tmp_path):
    s = Store(tmp_path / "b.db")
    brief.add(s, "growth-launches-desk", "r1", "needs_you",
              "The auditor has concerns about Launches & Content's task",
              body="The README says a passphrase is needed; the docs say no login.\nMore.",
              who="auditor", key="audit-r1")
    brief.add(s, "bhav-tech-desk", "r2", "needs_you", "Give the engineer a shell", who="Tech desk",
              body="Without it the backtest cannot run.")
    brief.add(s, "bhav-research-desk", "r3", "decide", "Aria needs you to decide on Research's task",
              who="Aria", options=["Approve", "Send back"], key="review-r3")
    brief.add(s, "inbox", "r4", "needs_you", "Sign the SOW", who="Jane", due="Thu")
    brief.add(s, "inbox", "r4", "fyi", "Invoice paid")
    brief.add(s, "inbox", "r4", "done", "Filed the receipts")
    return s, brief.page(s)["items"]


def test_the_brief_is_read_company_by_company_and_says_what_is_asked(tmp_path):
    _, items = _brief(tmp_path)
    text = brief.digest(items, company_of=lambda m: CO.get(m, ""))
    lines = text.splitlines()
    assert lines[0] == "▲ 3 need you · 1 decision · 1 FYI · 1 done for you"
    assert lines[1].startswith("These wait for you. Answer with a button below")
    heads = [ln for ln in lines if ln.startswith("▦ ")]
    assert heads == ["▦ Bhav Capital · 1 to do · 1 to decide", "▦ Bento Growth · 1 to do",
                     "▦ Not in a company · 1 to do"], "the company with most waiting first, no company last"
    assert "1. Do: Give the engineer a shell" in text
    assert "   Asked by Tech desk · Without it the backtest cannot run." in text
    assert "2. Decide: Aria needs you to decide on Research's task" in text and "   Choices: Approve / Send back" in text
    # an item this OS files says what to do about it, not only what happened
    at = lines.index("3. Do: The auditor has concerns about Launches & Content's task")
    assert lines[at + 1] == "   Read what the auditor found, then accept the work or have it redone."
    assert lines[at + 2] == "   Asked by auditor · The README says a passphrase is needed; the docs say no login."
    assert "   A boss did not sign this off. Read why, then accept it or send it back." in text
    # FYI and finished work are counted, never listed: nothing is expected for them
    assert "Invoice paid" not in text and "Filed the receipts" not in text
    assert lines[-1] == "Also, nothing to do for these: 1 FYI, 1 done for you."


def test_the_buttons_carry_the_numbers_the_text_gives(tmp_path):
    _, items = _brief(tmp_path)
    whose = lambda m: CO.get(m, "")                                   # noqa: E731
    text = brief.digest(items, company_of=whose)
    rows = brief.telegram_rows(items, company_of=whose)
    by_n = {r[0]["text"].split(":")[0].replace("✓ ", "").split()[0]: r for r in rows}
    order = brief.actionable(items, whose)
    for n, i in enumerate(order, 1):
        assert f"{n}. {brief.ASKS[i['kind']]}: {i['title']}" in text
        assert i["id"] in by_n[str(n)][0]["callback_data"], "the same item under the same number"
    assert [b["text"] for b in by_n["2"]] == ["2: Approve", "2: Send back"]


def test_a_long_brief_says_how_many_more_wait_and_nothing_waiting_says_so(tmp_path):
    s = Store(tmp_path / "c.db")
    for n in range(12):
        brief.add(s, "m", "r", "needs_you", f"Thing number {n}")
    text = brief.digest(brief.page(s)["items"], limit=8)
    assert text.count("Do: Thing number") == 8 and "… and 4 more to do or decide in the Brief." in text
    assert "▦" not in text, "no company named: no headings"
    s2 = Store(tmp_path / "d.db")
    brief.add(s2, "m", "r", "fyi", "Worth knowing")
    assert brief.digest(brief.page(s2)["items"]).splitlines()[-1] == "Nothing waits for you. 1 FYI."


def test_a_missions_company_is_read_from_the_mission(tmp_path):
    cfg = {"agent_name": "Aria"}
    store = Store(tmp_path / "e.db")
    plan, _ = company.normalize(company.template_plan(["sales"], "Brightdesk"),
                                [t["name"] for t in tools.TOOL_SCHEMAS])
    company.apply(cfg, store, plan, {"mail": True, "calendar": True}, talk=False)
    whose = company.of_mission(cfg, store)
    assert whose("sales-desk") == "Brightdesk" and whose("no-such-mission") == "" and whose("") == ""
    from agentos import server
    import inspect
    src = inspect.getsource(server._brief_deliver)
    assert src.count("company_of=whose") == 3, "the chat's copy, the phone's text and its buttons"


# ---- a department's card keeps following its task ---------------------------------------------

def _desk_run(store, cid="c1"):
    top = store.fabric_run_start("flow", "tech-desk", "Run the backtest", flow="tech-desk",
                                 conversation_id=cid, origin_surface="chat")
    store.fabric_event(top, "flow_start", {"flow": "tech-desk", "conversation_id": cid,
                                           "department": "Tech", "head": "tech-lead"})
    store.fabric_event(top, "node_add", {"node_id": "d1", "agent": "engineer",
                                         "task": "Write and run   the backtest script"})
    kid = store.fabric_run_start("delegate", "engineer", "x", parent_run=top, flow="tech-desk",
                                 conversation_id=cid)
    store.fabric_event(kid, "status", {"status": "running", "ref": "engineer", "parent_run": top})
    store.fabric_event(kid, "step", {"tool": "run_python", "status": "start", "detail": "backtest.py"})
    store.fabric_event(kid, "step", {"tool": "run_python", "status": "end", "ok": True})
    return top, kid


def test_what_a_desk_has_done_is_read_back_for_a_card_drawn_late(tmp_path):
    store = Store(tmp_path / "f.db")
    top, kid = _desk_run(store)
    got = company.live(store, "c1")
    assert len(got) == 1 and got[0]["run_id"] == top and got[0]["department"] == "Tech"
    assert got[0]["children"] == [{"run_id": kid, "who": "engineer"}]
    assert got[0]["lines"] == ["Tech has it, led by tech-lead",
                               "→ engineer: Write and run the backtest script",
                               "engineer is working", "  engineer · run_python · backtest.py"], \
        "the words the card writes as it happens (deptCardLive)"
    assert company.live(store, "another-chat") == [] and company.live(store, "") == []
    # a finished task is not open any more, and a mission started from a chat is not a desk
    store.fabric_run_finish(top, "ok", "done")
    assert company.live(store, "c1") == []
    other = store.fabric_run_start("flow", "daily", "x", flow="daily", conversation_id="c1")
    store.fabric_event(other, "flow_start", {"flow": "daily", "conversation_id": "c1"})
    assert company.live(store, "c1") == []


def test_the_page_puts_a_redrawn_card_back_on_its_run():
    src = (JS / "10a-handoff.js").read_text()
    for fn in ("function deptCardRestore(", "async function deptCardCatchUp(", "function deptCardPaint("):
        assert fn in src
    # a run is followed even when no card is on screen yet, with its chat and department kept
    live = src[src.index("function deptCardLive("):]
    assert "if(!cards.length)return" not in live
    assert "cid:ev.conversation_id,department:ev.department" in live
    assert "/api/company/live?conversation_id=" in src
    # a card made here is built from text nodes: a department's name is somebody's words
    made = src[src.index("async function deptCardCatchUp("):src.index("function deptCardLive(")]
    assert "innerHTML" not in made
    # both places that redraw a running chat call it
    panel = (JS / "04a-copilot.js").read_text()
    chat = (JS / "10-chat.js").read_text()
    assert "deptCardRestore(feedEl)" in panel and "deptCardCatchUp(cid,feedEl" in panel
    assert "deptCardRestore(feed)" in chat and "deptCardCatchUp(cid,curBody.parentNode,curBody)" in chat


def test_the_brief_greets_the_person_by_the_hour_and_by_name():
    import datetime as dt
    at = lambda h: dt.datetime(2026, 11, 17, h, 0).timestamp()        # noqa: E731
    assert brief.greeting(at(8), "piyush chitkara") == "Good morning, Piyush"
    assert brief.greeting(at(14), "Ada") == "Good afternoon, Ada"
    assert brief.greeting(at(21), "") == "Good evening", "no name known: no name said"
    s = Store(tempfile.mkdtemp() + "/g.db")
    brief.add(s, "m", "r", "needs_you", "Sign the SOW")
    scenes = brief.story(brief.page(s)["items"], at(8), name="Piyush")
    assert scenes[0]["caption"].startswith("Good morning, Piyush. 1 needs you.")
    assert scenes[0]["say"].startswith("Good morning, Piyush."), "and it is the first thing heard"
    # over an AI summary the greeting is still said
    scenes = brief.story(brief.page(s)["items"], at(8), name="Piyush", summary="One thing waits.")
    assert scenes[0]["say"].startswith("Good morning, Piyush. One thing waits.")


def test_a_phone_is_told_once_when_the_machine_has_no_voice():
    import inspect
    from agentos import server
    src = inspect.getsource(server._brief_deliver)
    assert 'in ("", "browser") and not b.get("voice_told")' in src and "Settings → Voice" in src
    assert "briefmod.greeting(scheduled_at or now, person)" in src
    assert "owner_name" in inspect.getsource(server._brief_person)


# ---- the Brief is the account's to switch, and each company's -------------------------------------

def test_an_accounts_brief_is_switched_off_and_keeps_its_times():
    import datetime as dt
    cfg = {}
    brief.set_schedule(cfg, times=["08:00"])
    at = dt.datetime(2026, 11, 17, 9, 0).timestamp()
    assert brief.schedule(cfg)["on"] is True and brief.due_at(brief.schedule(cfg), at)
    brief.set_schedule(cfg, on=False)
    s = brief.schedule(cfg)
    assert s["on"] is False and s["times"] == ["08:00"], "off keeps the times"
    assert brief.due_at(s, at) == 0 and brief.next_at(s, at) == 0, "and nothing is due"
    brief.set_schedule(cfg, on=True)
    assert brief.due_at(brief.schedule(cfg), at)
    from agentos import users
    assert "brief" in users.USER_KEYS and "company" in users.USER_KEYS and "companies" in users.USER_KEYS, \
        "one person's switch is their own"


def test_a_company_is_left_out_of_the_brief_and_comes_back(tmp_path):
    cfg = {"agent_name": "Aria"}
    store = Store(tmp_path / "h.db")
    names = [t["name"] for t in tools.TOOL_SCHEMAS]
    plan, _ = company.normalize(company.template_plan(["sales"], "Brightdesk"), names)
    company.apply(cfg, store, plan, {"mail": True, "calendar": True}, talk=False)
    company.create(cfg, store, "Kidstube")
    plan, _ = company.normalize(company.template_plan(["support"], "Kidstube"), names)
    company.apply(cfg, store, plan, {"mail": True, "calendar": True}, talk=False)
    assert [(c["name"], c["on"]) for c in company.brief_list(cfg)] == [("Kidstube", True), ("Brightdesk", True)]
    assert company.set_brief(cfg, "brightdesk", False) == {"name": "Brightdesk", "on": False}
    assert company.brief_off(cfg) == {"Brightdesk"}
    brief.add(store, "sales-desk", "r1", "needs_you", "Call the clinic")
    brief.add(store, "kidstube-support-desk", "r2", "needs_you", "Answer the parent")
    whose = company.of_mission(cfg, store)
    items = brief.kept(brief.page(store)["items"], whose, company.brief_off(cfg))
    assert [i["title"] for i in items] == ["Answer the parent"]
    assert len(brief.page(store)["items"]) == 2, "its items stay in the Brief app"
    # the switch is the company's own, so it parks and comes back with it
    bright = next(c for c in company.companies(cfg) if c["name"] == "Brightdesk")
    company.switch(cfg, store, bright["id"])
    assert company.brief_off(cfg) == {"Brightdesk"}
    company.set_brief(cfg, "Brightdesk", True)
    assert company.brief_off(cfg) == set()
    with pytest.raises(ValueError, match="no company called"):
        company.set_brief(cfg, "Nobody Ltd", False)


def test_every_face_has_the_two_switches():
    import inspect
    from agentos import __main__ as cli, server
    route = inspect.getsource(server.api_brief_schedule)
    assert 'on=body.get("on")' in route and "set_brief(cfg, str(name), bool(on))" in route
    assert "brief_off(cfg)" in inspect.getsource(server._brief_deliver), "the delivered Brief leaves them out"
    assert 'pg["companies"]' in inspect.getsource(server.api_brief)
    page = (JS / "24b-brief.js").read_text()
    assert "function briefSwitch(" in page and "function briefCompanyTicks(" in page
    assert "Your Brief is switched off" in page and "Turn my Brief off" in page
    src = inspect.getsource(cli)
    assert 'act == "company"' in src and 'args.id in ("on", "off")' in src
