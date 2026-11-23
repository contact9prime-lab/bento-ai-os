"""Calling people about an alarm nobody acknowledged (alarmcall.py, server._alarms_call). Asked for
after a hotel's chlorine alarm went out by email that nobody read: after the person's minutes an
alarm goes to their own paired phones, then to one chat of theirs they picked, and a phone that was
told can acknowledge it."""
import asyncio
import time
from pathlib import Path

from agentos import alarmcall

ROOT = Path(__file__).parent.parent
COMP = "esp.cold-2.switch.compressor"


def _a(aid="a1", since=None, level="alarm", **kw):
    return {"id": aid, "level": level, "machine": "zone-cold", "text": "Compressor is off",
            "since": since if since is not None else time.time() - 3600, "for": 0, "state": "active", "ack": None, **kw}


# ---- the policy ----------------------------------------------------------------------------

def test_the_policy_is_read_field_by_field_and_says_what_it_corrected():
    p, dropped = alarmcall.clean({})
    assert p == {"on": True, "after_min": 10, "then_min": 15, "levels": ["alarm"], "second": None} and not dropped
    p, dropped = alarmcall.clean({"after_min": 0, "then_min": "x", "levels": ["warning", "loud"], "colour": "red",
                                  "second": {"channel": "email", "to": "a@b.c"}})
    assert p["after_min"] == 1 and p["then_min"] == 15 and p["levels"] == ["warning"] and p["second"] is None
    assert len(dropped) == 5 and any("colour" in d for d in dropped)
    p, _ = alarmcall.clean({"second": {"channel": "telegram", "to": "-1001", "name": "Night shift"}})
    assert p["second"] == {"channel": "telegram", "to": "-1001", "name": "Night shift"}
    assert "then to Night shift 15 min later" in alarmcall.words(p)
    assert "Nobody is called" in alarmcall.words({"on": False, "levels": ["alarm"]})


def test_a_step_is_due_after_its_minutes_and_never_for_an_acknowledged_or_unconfirmed_alarm():
    c, now = alarmcall.Calls(), 10_000.0
    p = alarmcall.clean({"after_min": 10, "then_min": 5, "second": {"channel": "telegram", "to": "2"}})[0]
    young, old = _a("young", since=now - 300), _a("old", since=now - 900)
    seen, unsure, warn = _a("seen", since=0, ack={"by": "x"}), _a("unsure", since=0, state="unconfirmed"), \
        _a("warn", since=0, level="warning")
    assert [(a["id"], s) for a, s in c.due("", [young, old, seen, unsure, warn], p, now)] == [("old", 1)]
    # the rule's own `for` is part of being raised, not of being ignored
    assert not c.due("", [_a("held", since=now - 900, **{"for": 600})], p, now)
    c.told("", "old", 1, ["tg:1"], now)
    assert not c.due("", [old], p, now + 60), "called once, not every judgement"
    assert [s for _a2, s in c.due("", [old], p, now + 301)] == [2]
    c.told("", "old", 2, ["tg:2"], now + 301)
    assert not c.due("", [old], p, now + 9999) and c.told_keys("", "old") == ["tg:1", "tg:2"]
    assert not c.due("", [old], {**p, "second": None}, now + 9999)
    assert not c.due("", [_a("x", since=0)], {**p, "on": False}, now)


def test_only_a_chat_that_was_told_can_acknowledge_and_a_restart_remembers_who_was_told():
    c = alarmcall.Calls()
    c.told("ada", "a1", 1, ["tg:1"])
    code = alarmcall.code_of("ada", "a1")
    assert len(code) == 10 and len(f"al:{code}".encode()) <= 64
    assert c.asked_by("tg:1", code) == [("ada", "a1")] and c.asked_by("tg:1") == [("ada", "a1")]
    assert c.asked_by("tg:9", code) == [] and c.asked_by("wa:1") == []
    assert c.ended("ada", "a1") == ["tg:1"] and c.asked_by("tg:1") == []
    lines = [{"event": "escalated", "owner": "ada", "alarm": "a1", "step": 1, "told": ["tg:1"], "at": 5},
             {"event": "escalated", "owner": "ada", "alarm": "a1", "step": 2, "told": ["wa:7"], "at": 9},
             {"event": "escalated", "owner": "ada", "alarm": "gone", "step": 1, "told": ["tg:1"], "at": 5}]
    r = alarmcall.Calls()
    r.restore(lines, {("ada", "a1")})
    assert r.state[("ada", "a1")]["step"] == 2 and r.told_keys("ada", "a1") == ["tg:1", "wa:7"]
    assert ("ada", "gone") not in r.state, "an alarm that ended while Bento was off is nobody's call"


def test_answer_goes_through_the_boards_own_mark(monkeypatch):
    calls = alarmcall.Calls()
    monkeypatch.setattr(alarmcall, "CALLS", calls)
    seen = []

    async def ack(owner, aid, by, key):
        seen.append((owner, aid, by))
        return {"machine": "zone-cold", "text": "Compressor is off"}
    monkeypatch.setitem(alarmcall._HOOKS, "ack", ack)
    calls.told("", "a1", 1, ["wa:44"])
    assert alarmcall.is_ack("ACK") and alarmcall.is_ack(" ack. ") and not alarmcall.is_ack("ack the door")
    said = asyncio.run(alarmcall.answer("wa:44", "Ada on WhatsApp"))
    assert said.startswith("✓ Acknowledged") and seen == [("", "a1", "Ada on WhatsApp")]
    assert asyncio.run(alarmcall.answer("wa:99", "Eve")) is None, "a chat told nothing gets no say"


# ---- the hub -------------------------------------------------------------------------------

class _Tg:
    def __init__(self, owner_chat):
        self.cfg = {"telegram": {"enabled": True, "bot_token": "t", "owner_chat_id": owner_chat}}
        self.sent = []

    def _t(self):
        return self.cfg["telegram"]

    async def send(self, text, chat_id=None):
        self.sent.append((chat_id, text, None))
        return "sent via Telegram"

    async def send_alarm(self, text, chat_id, code):
        self.sent.append((chat_id, text, code))
        return ""


def test_the_hub_calls_your_phone_then_the_second_chat_and_a_tap_acknowledges_it(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import phoneforward, server
    with TestClient(server.app) as c:
        here = server._here_name()
        machines = [{"machine": here, "key": "here", "here": True, "up": True, "live": True, "things": [
            {"id": COMP, "name": "Compressor", "unit": "", "kind": "switch", "onoff": True,
             "group": "esp.cold-2", "group_name": "Cold room B"}]}]
        monkeypatch.setattr(server, "_board_machines", lambda owner: [dict(m, things=[dict(t) for t in m["things"]])
                                                                         for m in machines] if owner == "" else [])
        said, ledger = [], []

        async def event(owner, ev, label, text, **meta):
            said.append((ev, text, meta))

        async def tell(ev, owner):
            pass
        tg = _Tg(111)
        monkeypatch.setattr(server, "_device_event", event)
        monkeypatch.setattr(server, "_tie_tell", tell)
        monkeypatch.setattr(server, "_demo_shows", lambda me: False)
        monkeypatch.setattr(server, "_alarm_bridges", lambda owner: [("telegram", tg)])
        monkeypatch.setattr(server, "_alarm_ledger", lambda *a: ledger.append(a))
        monkeypatch.setattr(phoneforward, "targets", lambda t, w: [
            {"channel": "telegram", "to": "222", "name": "Night shift", "kind": "person", "ready": True, "why": ""}])
        monkeypatch.setattr(alarmcall, "CALLS", alarmcall.Calls())
        server._ALARMS = None
        assert c.put("/api/devices/escalation", json={"second": {"channel": "telegram", "to": "999"}}).status_code == 400
        r = c.put("/api/devices/escalation", json={"after_min": 1, "then_min": 1,
                                                   "second": {"channel": "telegram", "to": "222"}})
        assert r.status_code == 200 and r.json()["policy"]["second"]["name"] == "Night shift"
        g = c.get("/api/devices/escalation").json()
        assert g["own"] == [{"channel": "telegram", "name": "your Telegram"}] and g["choices"][0]["name"] == "Night shift"
        c.put("/api/devices/alarms", json={"alarms": [{"machine": here, "item": COMP, "when": "off"}]})
        comp = {"item": COMP, "domain": "switch", "name": "Compressor", "at": time.time()}
        loop = asyncio.new_event_loop()
        try:
            run = loop.run_until_complete
            run(server._device_observe("", here, [{**comp, "value": 0.0, "first": True}], live=True))
            assert not tg.sent, "nobody is called the moment it is raised"
            al = server._alarms()
            aid = next(iter(al.active[""]))
            al.since[("", aid)] -= 70
            run(server._alarms_judge(""))
            assert [(x[0], x[2] is not None) for x in tg.sent] == [(111, True)]
            assert "Open 1 min and nobody has acknowledged it" in tg.sent[0][1]
            run(server._alarms_judge(""))
            assert len(tg.sent) == 1, "called once"
            alarmcall.CALLS.state[("", aid)]["at"] -= 70
            run(server._alarms_judge(""))
            assert [x[0] for x in tg.sent] == [111, 222, 111], "the second chat, and you are told it went on"
            assert "it went to Night shift" in tg.sent[2][1]
            steps = [m for e, _t, m in said if e == "escalated"]
            assert [s["step"] for s in steps] == [1, 2] and steps[1]["told"] == ["tg:222"]
            assert [a[1] for a in ledger] == ["device.escalate", "device.escalate"]
            # the second chat taps Acknowledge: the board's mark, and the others hear who took it
            reply = run(alarmcall.answer("tg:222", "Sam on Telegram", code=tg.sent[1][2]))
            assert reply.startswith("✓ Acknowledged")
            assert c.get("/api/devices/board").json()["alarms"][0]["ack"]["by"] == "Sam on Telegram"
            assert tg.sent[-1][0] == 111 and "Sam on Telegram acknowledged" in tg.sent[-1][1]
            assert run(alarmcall.answer("tg:222", "Sam", code=tg.sent[1][2])).startswith("That alarm is already")
        finally:
            loop.close()
        c.put("/api/devices/alarms", json={"alarms": []})
        c.put("/api/devices/escalation", json={})
        for k in [k for k in server._DEV_LAST if k[2] == COMP]:
            server._DEV_LAST.pop(k, None)
        server._ALARMS = None


def test_nobody_paired_is_said_and_a_cleared_alarm_is_told_to_whoever_heard_of_it(monkeypatch):
    from agentos import server
    tg, said = _Tg(111), []

    async def event(owner, ev, label, text, **meta):
        said.append((ev, text))
    monkeypatch.setattr(server, "_device_event", event)
    monkeypatch.setattr(server, "_alarm_ledger", lambda *a: None)
    monkeypatch.setattr(alarmcall, "CALLS", alarmcall.Calls())
    alarmcall.CALLS.restored = True
    monkeypatch.setattr(server, "_alarm_bridges", lambda owner: [])
    a = _a("a1", since=time.time() - 3600)
    asyncio.run(server._alarms_call("", [a], []))
    assert said[-1][0] == "escalated" and "nobody could be told" in said[-1][1] and "no Telegram" in said[-1][1]
    monkeypatch.setattr(server, "_alarm_bridges", lambda owner: [("telegram", tg)])
    alarmcall.CALLS.told("", "a1", 1, ["tg:111"])
    asyncio.run(server._alarms_call("", [], [a]))
    assert tg.sent[-1][0] == 111 and tg.sent[-1][1].startswith("✓ Cleared on zone-cold")
    assert alarmcall.CALLS.told_keys("", "a1") == []


# ---- the faces -----------------------------------------------------------------------------

def test_the_bridges_take_ack_before_the_agent_and_the_card_writes_names_as_text():
    tg = (ROOT / "agentos/telegram.py").read_text()
    assert tg.index('startswith("al:")') < tg.index('if cq.get("from", {}).get("id") != (self._t().get("owner_chat_id")')
    assert tg.index("alarmcall.is_ack(text)") < tg.index("chat = self.store.tg_upsert_chat(chat_id, title")
    wa = (ROOT / "agentos/whatsapp.py").read_text()
    assert wa.index("alarmcall.is_ack(text)") < wa.index("chat = self.store.wa_upsert_chat(wa_id, name)")
    js = (ROOT / "agentos/ui/src/js/01h-devscene.js").read_text()
    card = js[js.index("function devCallDraw"):js.index("// first paint")]
    assert "innerHTML" not in card and "textContent" in card
    assert "[data-dvcall]" in js and "/api/devices/escalation" in js
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert 'rest[0] == "call"' in cli and "bento network alarms call" in cli


def test_no_agent_can_change_who_is_called():
    from agentos import tools
    names = {s["name"] for s in tools.TOOL_SCHEMAS} if hasattr(tools, "TOOL_SCHEMAS") else set()
    assert not any("escalat" in n or "alarm" in n for n in names)
    from agentos import tools as t
    assert "device_escalation" not in getattr(t, "CONFIG_SAFE_KEYS", ())
