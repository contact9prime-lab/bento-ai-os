"""A Zero: a small machine set up by one curl line, run from the hub.

Asked for as "another download to make a zero agent pi using curl on the repo, that would
install the zero agent and Tailscale and connect to the main hub … zero touch … it should
broadcast over Tailscale or the local network, that gets captured … a provisioning profile
which is always standardized … and when the main hub becomes the point of execution, the pi
may need files shipped back to it". What these defend:

- where a machine was heard is read from the address it came FROM, never from its beacon;
- the one line carries the hub's automatic key and addresses, and the Tailscale key goes
  into the line only, never into a file here;
- the standard profile is a closed set read field by field (tools from the company
  allow-list, executors by value), and a key or a person's choice goes over it;
- a claim with `execution: hub` leaves the Zero with no seeded agents and its lead allowed
  to hand tasks to the hub's lead, and nothing else;
- the hub lets ANY of its agents do two things for its own Zero without a person (save a
  report, write in that Zero's folder), only while everything untrusted came from that
  link, and a hand-written row naming every agent is never honoured;
- a task handed by the hub's lead to one of its specialists carries the link's taint (it
  did not, so a linked team's task ran on a specialist that had never seen it came from
  outside), and the answer brings the file it names back into the Zero's workspace, capped.
"""
import asyncio
import base64
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors, fabric, provision, providers, teamlink, zero   # noqa: E402
from agentos.memory import Store                                              # noqa: E402
from agentos.policy import MAIN, PDP, Principal                               # noqa: E402
from agentos.tools import Toolbox                                             # noqa: E402

ROOT = Path(__file__).parent.parent
FP = "ab" * 32


# ---- where it came from --------------------------------------------------------------------

def test_tailscale_or_the_local_network_is_read_from_the_address():
    assert zero.via("100.101.102.103") == "tailscale"
    assert zero.via("100.64.0.1") == "tailscale" and zero.via("100.128.0.1") == "local network"
    assert zero.via("fd7a:115c:a1e0::5") == "tailscale"
    assert zero.via("192.168.1.20") == "local network" and zero.via("not an address") == "local network"
    beacon = {"m": provision.MAGIC, "fp": FP, "name": "pi", "via": "local network"}
    assert provision.clean_beacon(beacon, "100.90.1.2")["via"] == "tailscale", \
        "the beacon's own words about where it is are a stranger's"
    assert provision.clean_beacon(beacon, "10.0.0.7")["via"] == "local network"


def test_hub_addresses_are_names_or_ips_and_at_most_four():
    got = zero.clean_hubs(["100.64.0.9, hub.tail1234.ts.net  big-box.local",
                           "http://evil/x", "a b; rm -rf", "10.0.0.1", "10.0.0.2"])
    assert got == ["100.64.0.9", "hub.tail1234.ts.net", "big-box.local", "a"]
    assert zero.clean_hubs("fd7a:115c:a1e0::1") == ["fd7a:115c:a1e0::1"]
    assert len(zero.clean_hubs([f"10.0.0.{i}" for i in range(9)])) == zero.MAX_HUBS


def test_a_waiting_machine_announces_to_its_hubs_as_well_as_its_network(tmp_path, monkeypatch):
    """Tailscale carries no broadcast: a Zero is heard because it sends to the hub itself."""
    sent = []

    class UDP:
        def sendto(self, raw, addr):
            sent.append(addr[0])
    monkeypatch.setattr(provision, "broadcast_addresses", lambda: ["192.168.1.255"])
    with teamlink.at(tmp_path):
        assert provision.set_hubs("100.64.0.9, http://x/") == ["100.64.0.9"]
        door = provision.Door(lambda: {"provision": {"port": 1}})
        door.udp = UDP()
        door.announce()
    assert sent == ["192.168.1.255", "100.64.0.9"]


# ---- the one line ----------------------------------------------------------------------------

def test_the_one_line_carries_the_key_and_never_stores_the_tailscale_key(tmp_path):
    home = tmp_path / "hub"
    home.mkdir()
    cfg = {"updates": {"repo": "someone/bento-ai-os"}}
    secret = "tskey-auth-kQ3abcDEFghij-ZYX987"
    with teamlink.at(home):
        k = provision.zero_key()
        assert k["auto"] and provision.zero_key()["id"] == k["id"], "one Zero key, made once"
        line = zero.one_line(cfg, k["text"], ["100.64.0.9", "192.168.1.4"], secret)
        with pytest.raises(ValueError, match="tskey-"):
            zero.one_line(cfg, k["text"], [], "my-password")
    assert line.startswith("curl -fsSL https://raw.githubusercontent.com/someone/bento-ai-os/master/install.sh | sh -s -- ")
    assert "--zero" in line and f"--enroll={k['text']}" in line and "--hub=100.64.0.9,192.168.1.4" in line
    assert f"--tailscale-key={secret}" in line
    for f in home.rglob("*"):
        if f.is_file():
            assert secret not in f.read_text(errors="ignore"), f"the Tailscale key ended up in {f}"
    assert "--tailscale-key" not in zero.one_line(cfg, k["text"], [])


def test_install_sh_takes_the_zero_flags_and_asks_nothing():
    sh = (ROOT / "install.sh").read_text()
    for flag in ("--zero)", "--hub=*)", "--tailscale-key=*)"):
        assert flag in sh, flag
    assert re.search(r'\[ -n "\$ZERO" \] && INTERACTIVE=""', sh), "a Zero is zero touch"
    assert "tailscale up" in sh and "--authkey" in sh
    assert "bento pool hub" in sh, "the hub's addresses are written before the machine waits"
    assert not re.search(r'echo[^\n]*\$TS_KEY', sh), "the Tailscale key is never printed"


# ---- the standard profile --------------------------------------------------------------------

def test_the_standard_profile_is_a_closed_set_and_layers_under_keys(tmp_path):
    with teamlink.at(tmp_path):
        assert provision.standard() == {"lite": True, "execution": "hub", "agents": [], "hands": []}
        prof, dropped = provision.set_standard({
            "kiosk": True, "execution": "anywhere", "shell": "yes",
            "hands": [{"name": "web-only", "spec": {"tools": ["fetch_url"]}},
                      {"name": "default", "spec": {}}],
            "agents": [{"name": "scout", "tools": ["fetch_url", "run_command"], "hands": "web-only"},
                       {"name": "Scout"}, {"name": "x" * 40},
                       {"name": "helper", "hands": "nowhere"}]})
        assert "execution" not in prof and "shell" not in prof and prof["kiosk"] is True
        assert [h["name"] for h in prof["hands"]] == ["web-only"]
        assert [a["name"] for a in prof["agents"]] == ["scout", "helper"]
        assert prof["agents"][0]["tools"] == ["fetch_url"] and prof["agents"][1]["hands"] == ""
        said = " ".join(dropped)
        assert "run_command" in said and "'default'" in said and "named twice" in said and "nowhere" in said
        got = provision.profile_for({"profile": {"kiosk": False, "agent_name": "Pip"}}, {"name": "kitchen"})
        assert got["kiosk"] is False and got["agent_name"] == "Pip" and got["name"] == "kitchen"
        assert got["agents"][0]["name"] == "scout", "the standard is under what a key adds"


def test_an_agent_of_the_hub_goes_into_the_standard_with_its_executor(tmp_path):
    from agentos import hands
    store = Store(tmp_path / "h.db")
    hands.save(store, "readers", {"tools": ["fetch_url", "recall"]}, "reads only")
    store.save_subagent({"name": "analyst", "soul": "You read numbers.",
                         "tools": ["fetch_url", "run_command"], "profile": "readers"})
    with teamlink.at(tmp_path):
        prof, dropped = provision.add_agent_from(store, "analyst")
        assert prof["agents"][0]["tools"] == ["fetch_url"] and "run_command" in " ".join(dropped)
        assert prof["hands"][0]["name"] == "readers", "the executor travels by value"
        assert provision.drop_agent("analyst")["hands"] == [], "an unused executor goes with it"
        with pytest.raises(ValueError):
            provision.add_agent_from(store, "nobody")


# ---- the Zero's side --------------------------------------------------------------------------

def test_a_claim_to_run_on_the_hub_leaves_no_seeded_agents_and_one_cell(tmp_path):
    cfg = {"zero": {"hub": "big-box", "execution": "hub"}, "autonomy": "full",
           "workspace": str(tmp_path), "team": {"talk": "matrix"}}
    store = Store(tmp_path / "z.db")
    fabric.seed_builtins(cfg, store)
    assert store.list_subagents() == [], "a Zero keeps no agents of its own"
    fabric.seed_builtins({}, store)
    seeded = [a["name"] for a in store.list_subagents()]
    assert seeded, "an ordinary machine still gets its starting team"
    store.save_subagent({"name": "mine", "soul": "a person's own"})
    prof = provision.clean_profile({"execution": "hub", "hands": [{"name": "web-only", "spec": {"tools": ["fetch_url"]}}],
                                    "agents": [{"name": "scout", "tools": ["fetch_url"], "hands": "web-only"}]})
    r = provision.apply_people(store, cfg, prof, hub="big-box")
    names = {a["name"] for a in store.list_subagents()}
    assert names == {"mine", "scout"}, "the seeded ones go, a person's own stays"
    assert set(r["removed"]) == set(seeded) and "scout" in r["made"]
    assert store.get_subagent("scout")["profile"] == "web-only"
    # the hand-over to the hub's lead is decided, nobody is asked on a machine nobody sits at
    pdp = PDP(cfg, store)
    d = pdp.decide(MAIN, "agent.message", "agent:subagent/lead@big-box", {"risk": "safe", "tool": "delegate"})
    assert d.effect == "allow", d.reason
    assert pdp.decide(MAIN, "agent.message", "agent:subagent/lead@elsewhere",
                      {"risk": "safe", "tool": "delegate"}).effect != "allow"
    provision.apply_people(store, cfg, prof, hub="big-box")
    assert len([g for g in store.list_grants(principal_kind="user") if g["source"] == "provision"]) == 1


def test_the_zero_lead_is_told_where_its_work_runs():
    assert zero.note({}) == ""
    n = zero.note({"zero": {"hub": "big-box", "execution": "hub"}}, prefix="")
    assert 'delegate {"subagent": "lead@big-box"' in n and "from-big-box/" in n
    assert zero.note({"zero": {"hub": "big-box", "execution": "here"}}) == ""
    agent_src = (ROOT / "agentos/agent.py").read_text()
    assert "_zero.note(self.cfg" in agent_src, "the built-in lead hears it as well as a forwarded one"


# ---- the hub's side ---------------------------------------------------------------------------

LINKED = [{"tool": "linked team", "source": "pi-kitchen"}]


def _hub(tmp_path):
    cfg = {"autonomy": "full", "workspace": str(tmp_path / "ws"), "security": {"taint": "ask"}}
    (tmp_path / "ws").mkdir()
    store = Store(tmp_path / "hub.db")
    store.save_subagent({"name": "writer", "soul": "SOUL-writer", "tools": ["write_file"]})
    return cfg, store


def test_the_hub_lets_its_agents_make_files_for_its_own_zero_and_nothing_else(tmp_path):
    cfg, store = _hub(tmp_path)
    w = Principal("subagent", "writer")
    folder = zero.folder_for(cfg, "pi-kitchen")
    pdp = PDP(cfg, store)

    def write(path, taint=LINKED, who=w):
        return pdp.decide(who, "fs.write", f"fs:{path}", {"risk": "risky", "taint": taint, "reason": "writes"}).effect

    assert write(folder / "plan.md") == "ask", "nothing standing yet: a person is needed"
    made = zero.zero_standing(store, cfg, "pi-kitchen")
    assert folder.is_dir() and len(made) == 1
    assert zero.zero_standing(store, cfg, "pi-kitchen") == [], "written once"
    pdp = PDP(cfg, store)
    assert write(folder / "plan.md") == "allow"
    assert write(folder / "sub" / "deep.csv") == "allow"
    assert write(folder / "x.md", who=Principal("subagent", "other")) == "allow", "any agent of the hub"
    assert write(tmp_path / "ws" / "elsewhere.md") == "ask", "only that Zero's folder"
    assert write(folder / ".." / "escape.md") == "ask", "matched on the real path"
    assert write(folder / ".bashrc") == "ask", "never a hidden file"
    assert write(folder / "p.md", taint=LINKED + [{"tool": "fetch_url", "source": "x.com"}]) == "ask", \
        "a page read too puts the person back"
    assert write(folder / "p.md", taint=[{"tool": "linked team", "source": "office"}]) == "ask", \
        "another link's task gets nothing from this"
    rep = pdp.decide(w, "tool.use", "tool:save_report", {"risk": "safe", "tool": "save_report", "taint": LINKED, "reason": "saves"})
    assert rep.effect == "allow", "a report is safe already: nothing standing is needed for it"
    # the lead itself is not a subagent: standing permissions never widen it
    assert pdp.decide(MAIN, "fs.write", f"fs:{folder}/a.md",
                      {"risk": "risky", "taint": LINKED, "reason": "w"}).effect == "ask"
    # a row naming every agent that provisioning did not write is never honoured
    from agentos.policy import standing_resource
    other = tmp_path / "ws" / "shared"
    other.mkdir()
    store.add_grant("team", "pi-kitchen/*", "team.act", standing_resource("*", "fs.write", f"fs:{other}/*"),
                    source="user")
    assert PDP(cfg, store).decide(w, "fs.write", f"fs:{other}/a.md",
                                  {"risk": "risky", "taint": LINKED, "reason": "w"}).effect == "ask"


def _ship_here(fp=FP):
    d = provision.load()
    d["enabled"][fp] = {"at": 1, "name": "pi-kitchen", "execution": "hub", "via": "tailscale"}
    provision.save(d)


def test_files_go_back_only_to_a_machine_this_hub_set_up_to_run_here(tmp_path):
    lk = {"kind": "machine", "label": "pi-kitchen", "peer_host_fp": FP}
    with teamlink.at(tmp_path):
        assert not zero.ships_to(lk)
        _ship_here()
        assert zero.ships_to(lk)
        assert not zero.ships_to({**lk, "kind": "account"}), "an account link gets words"
        assert not zero.ships_to({**lk, "peer_host_fp": "cd" * 32}), "another machine gets words"
        assert "for-pi-kitchen" in zero.hub_note({"workspace": str(tmp_path)}, lk)
        assert zero.hub_note({}, {**lk, "peer_host_fp": "cd" * 32}) == ""
        d = provision.load()
        d["claimed"] = {"leader_fp": FP}
        provision.save(d)
        assert zero.is_my_hub({}, lk) and not zero.is_my_hub({}, {**lk, "peer_host_fp": "cd" * 32})


def test_files_travel_capped_and_arrive_as_plain_names(tmp_path, monkeypatch):
    ws = tmp_path / "hubws"
    (ws / "out").mkdir(parents=True)
    (ws / "out" / "plan.md").write_text("# plan")
    (ws / "out" / "big.bin").write_bytes(b"x" * 300)
    (tmp_path / "secret.txt").write_text("not yours")
    monkeypatch.setattr(zero, "SHIP_FILE_CAP", 200)
    text = (f"Done. See `{ws}/out/plan.md` and `{ws}/out/big.bin`, and `{tmp_path}/secret.txt`.")
    files, left = zero.pack(text, [ws])
    assert [f["name"] for f in files] == ["plan.md"], "only files under this machine's own roots"
    assert left and left[0].startswith("big.bin")
    zws = tmp_path / "zero"
    files.append({"name": "../../etc/passwd", "data": base64.b64encode(b"root").decode()})
    files.append({"name": "plan.md", "data": base64.b64encode(b"again").decode()})
    files.append({"name": "bad", "data": "not base64!!"})
    files.append({"name": "huge", "data": base64.b64encode(b"y" * 500).decode()})
    got = zero.unpack(files, zws, "big-box")
    assert [p.name for p in got] == ["plan.md", "passwd", "plan-2.md"]
    assert all(p.parent == zws / "from-big-box" for p in got), "nothing lands outside from-<hub>/"
    assert (zws / "from-big-box" / "plan.md").read_text() == "# plan"
    line = zero.files_line(got, "big-box", left)
    assert str(got[0]) in line and "too big" in line
    assert zero.unpack("not a list", zws, "big-box") == []


# ---- a task from a Zero, answered on the hub --------------------------------------------------

def _provider(folder):
    """The hub's lead hands the task to the writer; the writer writes the plan into the
    Zero's folder (the lead was told where by zero.hub_note); the lead answers naming it."""
    def chat(cfg, model, messages, tools, options=None):
        async def gen():
            sys_txt = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = next((m["content"] for m in messages if m["role"] == "user"), "")
            done = [m["content"] for m in messages if m["role"] == "tool"]
            if "SOUL-writer" in sys_txt:
                if not done:
                    yield {"type": "tool_call", "id": "w1", "name": "write_file",
                           "args": {"path": f"{folder}/kitchen-plan.md", "content": "eggs, milk"}}
                    yield {"type": "finish", "reason": "tool_calls"}
                    return
                yield {"type": "text", "text": "WRITER: " + done[-1]}
            else:
                assert str(folder) in user, "the hub's lead is told where a Zero's files go"
                if not done:
                    yield {"type": "tool_call", "id": "l1", "name": "delegate",
                           "args": {"subagent": "writer", "task": "write the kitchen plan"}}
                    yield {"type": "finish", "reason": "tool_calls"}
                    return
                yield {"type": "text", "text": f"Here it is: `{folder}/kitchen-plan.md`"}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat


def _answer(tmp_path, monkeypatch, hub_side: bool, own_zero: bool = True):
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    cfg, store = _hub(tmp_path)
    # balanced, the default: handing work to a specialist asks a person below full, and
    # the live run found nobody at the hub to answer (the unit test at full had passed)
    cfg.update({"agent_name": "Aria", "autonomy": "balanced", "default_model": "openai/gpt-4o", "max_steps": 6,
                "memory": {"inject_facts": 0, "inject_user": 0},
                "providers": {"openai": {"enabled": True, "api_key": "k"}}})
    monkeypatch.setattr(providers, "chat", _provider(zero.folder_for(cfg, "pi-kitchen")))
    tb = Toolbox(cfg, store)
    tb.pdp = PDP(cfg, store)

    async def broadcast(ev):
        pass
    tb.broadcast = broadcast
    cp = fabric.ControlPlane(cfg, store, tb, broadcast)
    tb.fabric = cp
    seen = {}
    real = cp.run_subagent

    async def spy(defn, task, **kw):
        seen["taint"] = kw.get("taint")
        seen["space"] = kw.get("space_id")
        return await real(defn, task, **kw)
    cp.run_subagent = spy
    lk = {"id": "l1", "kind": "machine", "label": "pi-kitchen", "peer_host_fp": FP}
    with teamlink.at(tmp_path / "home"):
        if own_zero:
            _ship_here()
        if hub_side:
            zero.zero_standing(store, cfg, "pi-kitchen")
            tb.pdp = PDP(cfg, store)
        res = asyncio.run(cp._lead_for_link(lk, "Pip", {"question": "plan my kitchen"}))
    return res, seen, store


def test_a_task_from_a_zero_runs_on_the_hub_and_its_file_comes_back(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    res, seen, store = _answer(tmp_path, monkeypatch, hub_side=True)
    assert seen["taint"] == LINKED, "the specialist knows the task came from outside"
    sid = next(c["space_id"] for c in store.list_conversations(limit=10) if c["title"].startswith("↔ pi-kitchen"))
    assert sid and seen["space"] == sid, "the task is worked inside that Zero's section (zeromind.py)"
    assert store.get_space(sid)["name"] == "Zero · pi-kitchen"
    assert res["ok"] and "Here it is" in res["text"], res["text"]
    assert [f["name"] for f in res.get("files") or []] == ["kitchen-plan.md"]
    assert b"eggs, milk" in base64.b64decode(res["files"][0]["data"])
    rows = [r["action"] for r in store.audit_list(limit=80)]
    assert "link.files" in rows
    # and on the Zero, it lands in from-<hub>/
    got = zero.unpack(res["files"], tmp_path / "zero-ws", "big-box")
    assert got and got[0].parent.name == "from-big-box"


def test_without_the_hub_side_a_tainted_specialist_is_refused(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    res, seen, store = _answer(tmp_path, monkeypatch, hub_side=False)
    assert seen["taint"] == LINKED
    assert not res.get("files"), "nobody said yes, so nothing was made to send"
    assert not list((tmp_path / "ws").rglob("kitchen-plan.md"))


def test_another_linked_teams_task_is_not_handed_on_without_a_person(tmp_path, monkeypatch):
    """The hub answers the hand-over itself only for a Zero it set up to run here."""
    (tmp_path / "home").mkdir()
    res, seen, store = _answer(tmp_path, monkeypatch, hub_side=True, own_zero=False)
    assert "taint" not in seen, "the writer never ran: nobody here said yes"
    assert not res.get("files")


# ---- the faces --------------------------------------------------------------------------------

def test_every_face_has_it():
    js = (ROOT / "agentos/ui/src/js/24j-provision.js").read_text()
    for needle in ("provZeroHTML", "zeroline", "zerocopy", "std-exec", "std-add", "/api/provision/zero",
                   "/api/provision/standard"):
        assert needle in js, needle
    main = (ROOT / "agentos/__main__.py").read_text()
    for verb in ('"zero"', '"standard"', '"hub"', "--tailscale-key"):
        assert verb in main, verb
    srv = (ROOT / "agentos/server.py").read_text()
    for route in ('"/api/provision/zero"', '"/api/provision/standard"', '"/api/provision/standard/agent"'):
        assert route in srv, route
    assert "_zero().hub_side(" in srv and "_z.hub_side(" in main, "one hub side for the desktop and the terminal"
