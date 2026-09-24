"""Linking by request — the OAuth device flow between two Bentos, and between accounts.

The invite string was a thing a person had to carry from one screen to another. A
request is: type an address, press Ask; the other side gets an Approve / Deny card; both
screens show the same six digits. These tests defend the parts that make that safe:

- the digits are computed on EACH side from the certificates that side saw — so a
  machine in the middle, which must show each side its own certificate, makes them
  DISAGREE (a real relay stands in the middle below);
- approving writes both halves of the link together, or neither: an asker that never
  collects its answer leaves nothing behind, and can simply ask again;
- a deny, a withdrawal and an expiry each end the request on both screens;
- asking is metered per address (a request puts a card on somebody's screen), and a
  certificate that does not chain to the CA it came with is refused at the door;
- between accounts, only the person asked can approve, signed in as themselves.
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod                                  # noqa: E402
from agentos import executors, teamlink                               # noqa: E402
from agentos import users as usersmod                                 # noqa: E402
from test_teamlink import _machine                                    # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def two(tmp_path, monkeypatch):
    """'office' listening (it will be asked) and 'home' (it asks). Not linked yet."""
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    A = _machine(tmp_path / "office", "office")
    B = _machine(tmp_path / "home", "home")
    loop = asyncio.new_event_loop()
    seen = []

    async def on_event(kind, x):
        seen.append((kind, x))

    async def setup():
        with teamlink.at(A["home"]):
            A["lst"] = teamlink.Listener(A["cfg"], on_event=on_event)
            A["port"] = await A["lst"].start("127.0.0.1", 0)
        with teamlink.at(B["home"]):
            B["lst"] = teamlink.Listener(B["cfg"])
            B["port"] = await B["lst"].start("127.0.0.1", 0)
    loop.run_until_complete(setup())
    A["seen"] = seen
    yield A, B, loop
    for m in (A, B):
        loop.run_until_complete(m["lst"].stop())
    loop.close()


def _ask(B, A, loop, **kw):
    async def go():
        with teamlink.at(B["home"]):
            return await teamlink.request_link(f"127.0.0.1:{A['port']}", "", cfg=B["cfg"],
                                               my_port=B["port"], **kw)
    return loop.run_until_complete(go())


def _poll(B, p, loop):
    async def go():
        with teamlink.at(B["home"]):
            return await teamlink.poll_link(p)
    return loop.run_until_complete(go())


def _waiting(A):
    with teamlink.at(A["home"]):
        return teamlink.requests("")["incoming"]


def _links(m):
    with teamlink.at(m["home"]):
        return teamlink.links("")


# ---- the flow ------------------------------------------------------------------------------

def test_ask_approve_and_both_sides_are_linked_with_the_same_six_digits(two):
    A, B, loop = two
    p = _ask(B, A, loop)
    assert p["name"] == "office" and len(p["sas"]) == 7, p   # "482 913"
    card = _waiting(A)
    assert [c["name"] for c in card] == ["home"]
    assert card[0]["sas"] == p["sas"], "both screens show the same digits"
    assert "token_hash" not in card[0] and "peer_ca" not in card[0], "a card carries no secrets"
    assert [k for k, _ in A["seen"]] == ["request"], "the asked side is told at once"

    assert _poll(B, p, loop)["state"] == "pending"
    assert _links(A) == [] and _links(B) == [], "asking links nothing"

    with teamlink.at(A["home"]):
        got = teamlink.approve(card[0]["id"], "")
    assert got["pending"]["state"] == "approved"
    assert _links(A) == [], "approving waits for the asker to collect — both halves or neither"

    res = _poll(B, p, loop)
    assert res["state"] == "approved" and res["link"]["label"] == "office"
    assert [lk["label"] for lk in _links(A)] == ["home"], "collected: now the asked side has it too"
    assert _links(A)[0]["direction"] == "they asked" and _links(B)[0]["direction"] == "you asked"
    assert ("approved" in [k for k, _ in A["seen"]])

    async def hello():
        with teamlink.at(B["home"]):
            b = await teamlink.call(teamlink.find("", "office"), {"op": "hello"})
        with teamlink.at(A["home"]):
            a = await teamlink.call(teamlink.find("", "home"), {"op": "hello"})
        return a, b
    a, b = loop.run_until_complete(hello())
    assert a["ok"] and b["ok"], "and from then on it is mutual TLS, both ways"
    assert _waiting(A) == [], "an answered request leaves no card"


def test_a_deny_is_heard_and_nothing_is_linked(two):
    A, B, loop = two
    p = _ask(B, A, loop)
    with teamlink.at(A["home"]):
        teamlink.deny(_waiting(A)[0]["id"], "")
    assert _poll(B, p, loop)["state"] == "denied"
    assert _links(A) == [] and _links(B) == []
    assert _poll(B, p, loop)["state"] == "expired", "an answer is collected once"


def test_an_asker_that_never_collects_leaves_nothing_and_may_ask_again(two):
    A, B, loop = two
    p = _ask(B, A, loop)
    with teamlink.at(A["home"]):
        teamlink.approve(_waiting(A)[0]["id"], "")
    # the asker went away; the approved request expires unread
    with teamlink.at(A["home"]):
        d = teamlink._load()
        for r in d["requests"]:
            r["expires"] = 0
        teamlink._save(d)
    assert _links(A) == [], "no half-link"
    p2 = _ask(B, A, loop)
    assert p2["sas"] == p["sas"], "same two machines, same digits"
    assert len(_waiting(A)) == 1


def test_asking_again_replaces_the_card_and_withdrawing_removes_it(two):
    A, B, loop = two
    _ask(B, A, loop)
    p = _ask(B, A, loop)
    assert len(_waiting(A)) == 1, "one card per machine, never a stack"

    async def cancel():
        with teamlink.at(B["home"]):
            await teamlink.cancel_link(p)
    loop.run_until_complete(cancel())
    assert _waiting(A) == []


def test_the_wait_loop_ends_on_the_answer(two):
    A, B, loop = two
    p = _ask(B, A, loop)

    async def both():
        async def approve_soon():
            await asyncio.sleep(0.3)
            with teamlink.at(A["home"]):
                teamlink.approve(teamlink.requests("")["incoming"][0]["id"], "")
        with teamlink.at(B["home"]):
            _, got = await asyncio.gather(approve_soon(), teamlink.wait_link(p, every=0.1))
        return got
    assert loop.run_until_complete(both())["state"] == "approved"


# ---- what keeps it safe ---------------------------------------------------------------------

def test_a_machine_in_the_middle_makes_the_six_digits_disagree(two, tmp_path):
    # M terminates the TLS from home with ITS OWN certificate (it has no other choice:
    # it does not hold office's key) and relays the request to office unchanged.
    A, B, loop = two
    M = _machine(tmp_path / "mallory", "mallory")

    async def relay(reader, writer):
        line = await reader.readline()
        with teamlink.at(M["home"]):
            import json
            got, _, _ = await teamlink._once("127.0.0.1", A["port"], json.loads(line))
        writer.write((json.dumps(got) + "\n").encode())
        await writer.drain()
        writer.close()

    async def start():
        with teamlink.at(M["home"]):
            ctx = teamlink._server_ctx(teamlink.ensure_pki())
            srv = await asyncio.start_server(relay, "127.0.0.1", 0, ssl=ctx)
        return srv, srv.sockets[0].getsockname()[1]
    srv, mport = loop.run_until_complete(start())
    try:
        async def ask():
            with teamlink.at(B["home"]):
                return await teamlink.request_link(f"127.0.0.1:{mport}", "", cfg=B["cfg"])
        p = loop.run_until_complete(ask())
    finally:
        srv.close()
    office_sees = _waiting(A)[0]["sas"]
    assert p["sas"] != office_sees, "the two screens disagree — a person comparing them denies it"
    with teamlink.at(A["home"]):
        office_fp = teamlink.ensure_pki()["host_fp"]
    assert p["fp"] != office_fp, "home pinned the relay's certificate, not office's"


def test_asking_is_metered_per_address(two):
    A, B, loop = two
    for _ in range(teamlink.REQUEST_LIMIT):
        _ask(B, A, loop)
    with pytest.raises(ValueError, match="too many link requests"):
        _ask(B, A, loop)


def test_a_certificate_that_is_not_its_own_cas_is_refused_at_the_door(two, tmp_path):
    A, B, loop = two
    O = _machine(tmp_path / "other", "other")
    with teamlink.at(O["home"]):
        other_ca = teamlink.ensure_pki()["ca"]
    with teamlink.at(B["home"]):
        ident = teamlink.ensure_pki()

    async def forged():
        with teamlink.at(B["home"]):
            got, _, _ = await teamlink._once("127.0.0.1", A["port"], {
                "op": "request", "name": "home", "ca": other_ca, "host": ident["host"]})
        return got
    got = loop.run_until_complete(forged())
    assert not got["ok"] and "not signed by its own CA" in got["error"]
    assert _waiting(A) == []


def test_a_poll_with_a_made_up_token_learns_nothing_and_counts_as_a_guess(two):
    A, B, loop = two
    p = _ask(B, A, loop)
    fake = {**p, "token": "x" * 32}
    assert _poll(B, fake, loop)["state"] == "expired"
    assert A["lst"]._guess, "counted"
    assert _waiting(A), "the real request is untouched"


def test_an_address_is_typed_the_way_people_type_them():
    assert teamlink.parse_address("office.local") == ("office.local", 8322)
    assert teamlink.parse_address("192.168.1.20:9000") == ("192.168.1.20", 9000)
    assert teamlink.parse_address("http://office.local:8321/") == ("office.local", 8322)
    assert teamlink.parse_address("[fe80::1]:8322") == ("fe80::1", 8322)
    with pytest.raises(ValueError, match="office.local"):
        teamlink.parse_address("not an address!")
    assert teamlink.sas("a" * 64, "b" * 64) == teamlink.sas("b" * 64, "a" * 64), "order-free"


# ---- between accounts ---------------------------------------------------------------------------

@pytest.fixture()
def people(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    ada = usersmod.create("ada", "hunter2hunter")["id"]
    bob = usersmod.create("bob", "hunter2hunter", role="executor")["id"]
    names = {ada: "ada", bob: "bob"}
    return ada, bob, names


def test_an_account_asks_another_and_only_that_person_can_say_yes(people):
    ada, bob, names = people
    r = teamlink.request_account(ada, bob, names)
    assert teamlink.requests(bob)["incoming"][0]["name"] == "ada"
    assert teamlink.requests(ada)["outgoing"][0]["to_name"] == "bob"
    assert teamlink.requests(ada)["incoming"] == [], "ada cannot answer her own request"
    with pytest.raises(ValueError):
        teamlink.approve(r["id"], ada, names=names)
    got = teamlink.approve(r["id"], bob, names=names)
    assert got["mine"]["label"] == "ada" and got["theirs"]["label"] == "bob"
    assert got["mine"]["pair_id"] == got["theirs"]["pair_id"], "one agreement, two halves"
    with pytest.raises(ValueError, match="already linked"):
        teamlink.request_account(ada, bob, names)


def test_an_account_request_can_be_refused_or_withdrawn(people):
    ada, bob, names = people
    r = teamlink.request_account(ada, bob, names)
    teamlink.deny(r["id"], bob)
    assert teamlink.requests(bob)["incoming"] == [] and teamlink.links(ada) == []
    r = teamlink.request_account(ada, bob, names)
    assert not teamlink.withdraw(r["id"], bob), "only the asker withdraws"
    assert teamlink.withdraw(r["id"], ada)
    with pytest.raises(ValueError, match="that is you"):
        teamlink.request_account(ada, ada, names)


# ---- the faces ---------------------------------------------------------------------------------

def test_asking_is_the_first_thing_on_every_face():
    js = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    body = js[js.index("async function paintTeamLinks"):js.index("async function teamApi")]
    assert body.index("Ask to link") < body.index("Use an invite code instead"), \
        "the request is the way in; the invite is folded away for headless machines"
    assert "tlk-sas" in js and "Approve" in js and "Deny" in js
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'team_link_request'" in ws and "case 'team_links'" in ws, \
        "the server broadcast team_links before and nothing listened"
    assert "team_link_request" in (ROOT / "agentos/tui_app.py").read_text()
    env = {**os.environ, "AGENTOS_HOME": tempfile.mkdtemp(prefix="agentos-cli-")}
    r = subprocess.run([sys.executable, "-m", "agentos", "link", "requests"], env=env,
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0 and "no link requests waiting" in r.stdout, r.stdout + r.stderr
    r = subprocess.run([sys.executable, "-m", "agentos", "link", "request"], env=env,
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 2 and "bento link request ADDRESS" in r.stdout
