"""Who a Zero or a linked team talks to, the maps, Chat's tabs, and where the settings went.

Asked for as: "the Zeros or the teams can talk to either Aria, which controls all the departments,
or to each department only … caution the user that Aria will have access to many things, so better
restrict"; "the logical topology is at the company level, the physical topology the devices";
"Teams & Communications: agents' own providers, talk and huddles move to Agents; the rest merges
with Network as Discovery and linkage, Team to agent mapping and Maps"; and "the chat must have
tabs and search: Desktop, Channels, Devices, Huddles, App builder". What these defend:

  * a link talks to the lead or to ONE department that exists and has a desk; anything else is
    refused in a sentence, and a link that says nothing talks to the lead as before;
  * a department link's work runs on that department's desk, marked as from outside, in the right
    company (a parked one too), and never through the lead;
  * the logical map and a link's access are one computation, and talking to the lead says so;
  * a conversation's tab is decided once; a huddle is listed under Huddles and where it happened;
  * Settings has no Team & Communications tab: each piece is in Agents or Network & Teams, and an
    old link to the team tab still lands.
"""
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import chattabs, company, fabric, teamlink, ties, tools, topology   # noqa: E402
from agentos import zero as zeromod                                              # noqa: E402
from agentos import zeromind                                                     # noqa: E402
from agentos.memory import Store                                                 # noqa: E402
from agentos.policy import PDP                                                   # noqa: E402
from agentos.tools import Toolbox                                                # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _hub(tmp_path, keys=("sales", "finance")):
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321,
         "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    plan, _ = company.normalize(company.template_plan(list(keys), "Acme"),
                                [t["name"] for t in tools.TOOL_SCHEMAS])
    company.apply(c, store, plan, {"mail": True, "calendar": True})
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)

    async def broadcast(ev):
        pass
    tb.fabric = fabric.ControlPlane(c, store, tb, broadcast)
    return c, store, tb


def _link(home, **kv):
    with teamlink.at(home):
        d = teamlink._load()
        d["links"] = [{"id": "l1", "kind": "machine", "label": "pi", "owner": "", "url": "192.168.1.20:8622",
                       "peer_host_fp": "f" * 64, "peer_name": "pi", "created": 1, **kv}]
        teamlink._save(d)


def _dept(c, store, i=0):
    return company.departments(c, store)[i]["name"]


def test_a_link_talks_to_the_lead_or_one_department_that_exists(tmp_path):
    c, store, _ = _hub(tmp_path)
    _link(tmp_path)
    sales = _dept(c, store)
    with teamlink.at(tmp_path):
        assert ties.target_of(teamlink.find("", "pi")) == {"to": "lead"}, "a link that says nothing: as before"
        got = ties.set_target("", "pi", {"to": "department", "department": sales.lower()}, c, store)
        assert got == {"to": "department", "company": "", "department": sales}
        assert ties.target_of(teamlink.find("", "pi"))["department"] == sales
        for bad, why in (({"to": "department", "department": "Legal"}, "no department"),
                         ({"to": "department", "company": "deadbeef", "department": sales}, "no company"),
                         ({"to": "everyone"}, "lead agent or to one department")):
            with pytest.raises(ValueError, match=why):
                ties.set_target("", "pi", bad, c, store)
        assert ties.set_target("", "pi", {"to": "lead"}, c, store) == {"to": "lead"}
        assert "talks_to" not in teamlink.find("", "pi")
        assert ties.target_words(c, {"to": "department", "company": "", "department": sales}).startswith(sales)


def test_a_department_link_is_worked_by_that_desk_marked_as_from_outside(tmp_path, monkeypatch):
    c, store, tb = _hub(tmp_path)
    sales = _dept(c, store)
    _link(tmp_path, talks_to={"to": "department", "company": "", "department": sales})
    monkeypatch.setattr(zeromod, "ships_to", lambda lk: True)
    monkeypatch.setattr(zeromind, "section", lambda store_, lk: "")
    asked = []

    async def run_flow(self, flow, text, **kw):
        asked.append({"flow": flow["name"], "text": text, **{k: kw.get(k) for k in ("tainted", "space_id")}})
        return {"content": "Sales says: 12 leads this week.", "status": "done", "fault": ""}
    monkeypatch.setattr(fabric.ControlPlane, "run_flow", run_flow)

    class NoLead:      # the lead's loop must not run for a department link
        def __init__(self, *a, **k):
            raise AssertionError("a department link reached the lead")
    monkeypatch.setattr(fabric, "Agent", NoLead)
    with teamlink.at(tmp_path):
        lk = teamlink.find("", "pi")
        out = asyncio.run(tb.fabric.zero_chat(lk, {"text": "how many leads?", "conversation": "s1"}))
        assert out["ok"] and out["department"] == sales and "12 leads" in out["text"]
        assert asked[-1]["tainted"] is True and asked[-1]["flow"] == company.departments(c, store)[0]["desk"]
        assert "how many leads?" in asked[-1]["text"]
        out = asyncio.run(tb.fabric._lead_for_link(lk, "lead", {"question": "plan next week"}))
        assert out["ok"] and out["department"] == sales and asked[-1]["tainted"] is True
    msgs = [m for cv in store.list_conversations() for m in store.get_messages(cv["id"]) if m["role"] == "assistant"]
    assert all(json.loads(m["meta"] if isinstance(m["meta"], str) else json.dumps(m["meta"])).get("department") == sales
               for m in msgs), "kept here as the department's answer"


def test_a_department_of_a_parked_company_runs_on_its_own_desk(tmp_path, monkeypatch):
    c, store, tb = _hub(tmp_path)
    first = company.companies(c)
    company.create(c, store, "Forge", "metal parts")          # Acme is parked now
    acme = next(x for x in company.companies(c) if x["name"] != "Forge")
    assert first and acme["id"], "the first company got an id when the second was made"
    depts = company.departments_of(c, store, acme["id"])
    assert depts and company.departments(c, store) == [], "Forge (open) has none; Acme's are read parked"
    ran = []

    async def run_flow(self, flow, text, **kw):
        ran.append(flow["name"])
        return {"content": "ok", "status": "done", "fault": ""}
    monkeypatch.setattr(fabric.ControlPlane, "run_flow", run_flow)
    got = asyncio.run(tb.fabric.department_task(depts[0]["name"], "x", company=acme["id"], tainted=True))
    assert ran == [depts[0]["desk"]] and got["department"] == depts[0]["name"]
    with pytest.raises(ValueError, match="no longer kept"):
        asyncio.run(tb.fabric.department_task(depts[0]["name"], "x", company="deadbeef"))


def test_the_logical_map_and_a_links_access_are_one_reading(tmp_path, monkeypatch):
    c, store, _ = _hub(tmp_path)
    store.save_subagent({"name": "loner", "soul": "s", "tools": ["recall"]})
    sales = _dept(c, store)
    monkeypatch.setattr(zeromod, "ships_to", lambda lk: True)
    tree = topology.logical(c, store, [{"label": "pi", "kind": "zero", "talks_to": {"to": "department", "company": "",
                                                                                    "department": sales}},
                                       {"label": "studio", "kind": "team", "talks_to": {"to": "lead"}}])
    assert tree["lead"]["name"] == "Aria" and [t["label"] for t in tree["lead"]["ties"]] == ["studio"]
    acme = tree["companies"][0]
    d = next(x for x in acme["departments"] if x["name"] == sales)
    assert [t["label"] for t in d["ties"]] == ["pi"], "a tie hangs from what it talks to"
    assert d["people"] and all("tools" in p and "hands" in p and "allow" in p for p in d["people"])
    default = tree["companies"][-1]
    assert default.get("default") and [p["name"] for p in default["people"]] == ["loner"]
    assert "pi" in topology.text(tree) and "Default company" in topology.text(tree)

    _link(tmp_path)
    with teamlink.at(tmp_path):
        lk = teamlink.find("", "pi")
        wide = topology.access(c, store, lk)
        assert wide["talks_to"] == {"to": "lead"} and "every one of your" in wide["caution"]
        assert "delegate" in wide["tools"] and "loner" in [p["name"] for p in wide["reach"]]
        ties.set_target("", "pi", {"to": "department", "department": sales}, c, store)
        narrow = topology.access(c, store, teamlink.find("", "pi"))
        assert not narrow["caution"] and "loner" not in [p["name"] for p in narrow["reach"]]
        assert {p["name"] for p in narrow["reach"]} == set(d and [p["name"] for p in d["people"]])


def test_a_conversation_has_one_home_tab_and_a_huddle_is_also_under_huddles(tmp_path):
    st = Store(tmp_path / "c.db")
    ids = {k: st.create_conversation(t, origin=o) for k, (t, o) in {
        "desk": ("New chat", "user"), "tg": ("Telegram · Ana", "telegram"), "pi": ("◫ pi: hi", "zero"),
        "team": ("↔ studio: plan", "team"), "studio": ("build: notes", "studio"),
        "talk": ("Free talk", "freetalk"), "omni": ("What's on today", "omni")}.items()}
    st.add_message(ids["desk"], "assistant", "@a (m): x", {"huddle": {"names": ["a", "b"]}})
    st.add_message(ids["tg"], "user", "where is the invoice for Northwind?")
    tagged = {c["id"]: c for c in chattabs.tag(st, st.list_conversations())}
    want = {"desk": "desktop", "tg": "channels", "pi": "devices", "team": "devices", "studio": "apps",
            "talk": "huddles", "omni": "desktop"}
    assert {k: tagged[v]["tab"] for k, v in ids.items()} == want
    assert tagged[ids["desk"]]["tabs"] == ["desktop", "huddles"], "a huddle is found under Huddles and where it was"
    assert chattabs.search(st, "Northwind") == {ids["tg"]}
    assert set(chattabs.TABS) == {"desktop", "channels", "devices", "huddles", "apps"}


def _tab(name: str) -> str:
    src = (JS / "11-settings.js").read_text()
    a = src.index(f"  if(want('{name}')){{")
    b = src.index("\n  if(want(", a + 10)
    return src[a:b]


def test_team_and_communications_is_split_between_agents_and_network():
    src = (JS / "11-settings.js").read_text()
    assert "['team'," not in src and "want('team')" not in src
    assert "SETTAB_ALIAS={team:'network'}" in src, "an old link to the team tab still lands"
    agent = _tab("agent")
    for piece in ("s-team-own", "s-team-list", "s-team-talk", "s-team-matrix", "s-team-limits",
                  "s-team-freetalk", "s-team-talklog", "Start a huddle"):
        assert piece in agent, piece
    net = _tab("network")
    for piece in ("Discovery and linkage", "s-net", "s-prov", "s-team-links", "s-pool", "openApp(\\'teamchat\\')",
                  "Team to agent mapping", "s-net-mapping", "Maps", "s-net-maps"):
        assert piece in net, piece
    assert "Network &amp; Teams" in net
    for f in JS.glob("*.js"):
        t = f.read_text()
        assert "placeSettings('team')" not in t and 'data-t="team"' not in t, f.name


def test_the_pages_read_the_one_answer():
    topo = (JS / "24r-topology.js").read_text()
    for route in ("/api/network/logical", "/api/network/targets", "/access?owner=", "/target"):
        assert route in topo, route
    assert "confirm(" not in topo, "no browser dialog: the caution is on the row"
    chat = (JS / "10-chat.js").read_text()
    assert "c.tabs||[c.tab]" in chat and "chatNewHuddle" in chat and "conv-q" in chat
    assert re.search(r"devViewSet\('?\w", (JS / "24o-devices.js").read_text())


def test_a_pi_on_a_department_link_gets_the_desks_real_run(tmp_path, monkeypatch):
    """No run_flow stand-in: the desk's master hands the piece to the head, who answers, and the
    master finishes. The run is marked tainted (it came from a screen nobody signed in at), it is
    the desk's flow, and the Pi gets the desk's words back."""
    from agentos import flows, office, providers
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 8, "default_model": "ollama/x",
         "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0},
         "company": {"review": "off", "audit": False}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)

    async def broadcast(ev):
        pass
    cp = fabric.ControlPlane(c, store, tb, broadcast)
    tb.fabric = cp
    store.save_subagent({"name": "finance-lead", "soul": "does the books", "tools": ["recall"]})
    flows.save(store, {"name": "finance-desk", "mission": "You run the Finance department.",
                       "roster": ["finance-lead"], "permissions": {"tools": [], "memory": "read-space"}, "sinks": []})
    office.save(c, store, {"departments": [{"name": "Finance", "color": "amber", "members": ["finance-lead"],
                                            "lead": "finance-lead", "desk": "finance-desk"}]})
    turns = [[{"type": "tool_call", "id": "c1", "name": "delegate",
               "args": {"subagent": "finance-lead", "task": "what did we spend in March"}}],
             [{"type": "text", "text": "March spend was 4,210 EUR."}],
             [{"type": "tool_call", "id": "c2", "name": "finish", "args": {"summary": "Spend in March was 4,210 EUR."}}],
             [{"type": "text", "text": "Spend in March was 4,210 EUR."}]]
    st = {"i": 0}

    def chat(cfg_, model, messages, tools_, options=None):
        async def gen():
            i = min(st["i"], len(turns) - 1)
            st["i"] += 1
            for ev in turns[i]:
                yield ev
            yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", chat)
    monkeypatch.setattr(zeromod, "ships_to", lambda lk: True)
    monkeypatch.setattr(zeromind, "section", lambda store_, lk: "")
    _link(tmp_path, talks_to={"to": "department", "company": "", "department": "Finance"})
    with teamlink.at(tmp_path):
        out = asyncio.run(cp.zero_chat(teamlink.find("", "pi"), {"text": "what did we spend in March?",
                                                                  "conversation": "s1"}))
    assert out["ok"] and out["department"] == "Finance" and "4,210" in out["text"], out
    run = dict(next(r for r in store.db.execute("SELECT * FROM fabric_runs WHERE kind='flow'").fetchall()))
    assert run["ref"] == "finance-desk", "the desk's flow, never the lead"
    assert (store.artifact_get(run["id"], "in1") or {}).get("tainted") == 1, "the question is marked from outside"
    assert not store.db.execute("SELECT 1 FROM fabric_runs WHERE kind='chat'").fetchall()
