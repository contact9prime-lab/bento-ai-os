"""New machines on the network: heard, asked about, and set up from the one that leads.

Asked for as "the system should be able to provision multiple pi agents … more like POAP:
identify and discover pi(s) and ask for it to be enabled with agent", and "whenever a new
machine is turned on and discovered on the network, we should be able to check if we need
to provision it". A leader and stand-in Raspberry Pis stand up in this process, each with
its own home; discovery is real UDP broadcast on loopback and the claim is real TLS.
"""
import asyncio
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import executors, pool, provision, teamlink              # noqa: E402
from agentos.memory import Store                                    # noqa: E402
from agentos.policy import PDP                                      # noqa: E402


def _free(kind=socket.SOCK_STREAM) -> int:
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _machine(home: Path, name: str, brain=True, pi=False):
    home.mkdir(parents=True, exist_ok=True)
    cfg = {"agent_name": "Aria", "default_model": "openai/gpt-4o" if brain else "",
           "providers": {"openai": {"enabled": True, "api_key": "k" if brain else ""}},
           "team": {"machine_name": name}, "provision": {"port": _free()}}
    store = Store(home / "agentos.db")
    pdp = PDP(cfg, store)
    p = pool.Pool(cfg=lambda: cfg, store=lambda: store, pdp=lambda: pdp)
    return {"home": home, "name": name, "cfg": cfg, "store": store, "pool": p, "pi": pi}


def _at(m):
    return teamlink.at(m["home"])


@pytest.fixture()
def lan(tmp_path, monkeypatch):
    """A leader and two waiting Pis. Broadcasts go to 127.255.255.255, which every socket
    on this host bound to the discovery port receives, as a LAN's broadcast would."""
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    monkeypatch.setenv("AGENTOS_DISCOVER_UDP", str(_free(socket.SOCK_DGRAM)))
    monkeypatch.setenv("AGENTOS_DISCOVER_TARGETS", "127.255.255.255")
    monkeypatch.setenv("AGENTOS_PI_MODEL", "Raspberry Pi 5 Model B Rev 1.0")
    L = _machine(tmp_path / "lead", "big-box")
    A = _machine(tmp_path / "pi-a", "pi-kitchen", brain=False, pi=True)
    B = _machine(tmp_path / "pi-b", "pi-garage", brain=False, pi=True)
    loop = asyncio.new_event_loop()
    heard = []

    async def setup():
        async def on_pool(lk, req):
            with _at(L):
                return await L["pool"].on_op(lk, req)
        with _at(L):
            L["lst"] = teamlink.Listener(L["cfg"], on_pool=on_pool)
            L["port"] = await L["lst"].start("127.0.0.1", 0)
            L["cfg"]["team"]["link_port"] = L["port"]
            pool.create(L["cfg"], "Home")

            async def on_new(b):
                heard.append(b)
            L["watch"] = await provision.Watch(on_new=on_new).start()
        for m in (A, B):
            with _at(m):
                m["door"] = await provision.Door(lambda m=m: m["cfg"]).start()
    loop.run_until_complete(setup())
    yield L, A, B, loop, heard
    for m in (L, A, B):
        for k in ("door", "watch", "lst"):
            if m.get(k):
                loop.run_until_complete(m[k].stop())
    loop.close()


def _scan(L, loop):
    async def go():
        with _at(L):
            return await provision.scan(0.6)
    return {b["name"]: b for b in loop.run_until_complete(go())}


def _enable(L, target, loop, code="", profile=None, raw=False):
    async def go():
        with _at(L):
            t = target if raw else provision.find_seen(target["fp"])
            return await provision.enable(L["cfg"], t, profile or {},
                                          code=code, pool_info={"id": "x", "name": "Home"})
    return loop.run_until_complete(go())


def _code(m):
    with _at(m):
        return provision.pin()


# ---- who waits ------------------------------------------------------------------------------

def test_a_fresh_pi_waits_and_a_set_up_or_ordinary_machine_does_not(tmp_path, monkeypatch):
    with teamlink.at(tmp_path):
        monkeypatch.setenv("AGENTOS_PI_MODEL", "Raspberry Pi 4 Model B")
        assert provision.waiting({})[0]
        assert not provision.waiting({"setup_complete": True})[0], "a Pi somebody set up is left alone"
        monkeypatch.setenv("AGENTOS_PI_MODEL", "")
        assert not provision.waiting({})[0], "a laptop never opens the door by itself"
        provision.set_wait(True)
        assert provision.waiting({"setup_complete": True}) == (True, "asked to wait")
        provision.set_wait(False)
        assert not provision.waiting({})[0]


def test_a_new_machine_is_heard_once_and_scanned_with_its_board(lan):
    L, A, B, loop, heard = lan

    async def announce():
        for m in (A, B):
            with _at(m):
                m["door"].announce()
        await asyncio.sleep(0.4)
        with _at(A):
            A["door"].announce()           # heard again: not new again
        await asyncio.sleep(0.4)
    loop.run_until_complete(announce())
    assert sorted(b["name"] for b in heard) == ["pi-garage", "pi-kitchen"]
    got = _scan(L, loop)
    assert set(got) == {"pi-kitchen", "pi-garage"}
    assert got["pi-kitchen"]["hw"]["board"].startswith("Raspberry Pi 5")
    assert got["pi-kitchen"]["id"] == provision.id_code(got["pi-kitchen"]["fp"])
    with _at(L):
        names = [e["name"] for e in provision.seen_list()]
    assert set(names) == {"pi-kitchen", "pi-garage"}


def test_enabling_with_the_code_sets_the_pi_up_and_it_joins_at_once(lan):
    L, A, B, loop, heard = lan
    t = _scan(L, loop)["pi-kitchen"]
    with pytest.raises(ValueError, match="six-digit code"):
        _enable(L, t, loop)
    with pytest.raises(ValueError, match="not the one on this machine's screen"):
        _enable(L, t, loop, code="000000" if _code(A) != "000000" else "111111")
    r = _enable(L, t, loop, code=_code(A),
                profile={"name": "kitchen", "agent_name": "Pip", "kiosk": True, "buddy": "on",
                         "lite": True, "shell": "rm -rf /"})
    assert r["ok"] and r["how"] == "code" and "shell" not in r["profile"]
    c = A["cfg"]
    assert c["setup_complete"] and c["agent_name"] == "Pip" and c["profile"] == "lite"
    assert c["face"]["kiosk"] is True and c["face"]["buddy"] == "on"
    assert c["team"]["listen"] and c["team"]["machine_name"] == "kitchen"
    with _at(A):
        assert not provision.waiting(c)[0], "a claim closes the door for good"
        lk = next(x for x in teamlink._load()["links"] if x["kind"] == "machine")
        assert lk["url"].endswith(f":{L['port']}")
    # a second claim is refused: the door answers nothing once it was set up
    with pytest.raises(ValueError, match="not waiting"):
        _enable(L, t, loop, code="123456")

    # the Pi joins over the link the claim wrote, and is let in without asking anybody
    async def join():
        with _at(A):
            return await pool.join(c, lk["label"])
    v = loop.run_until_complete(join())
    assert v["role"] == "member"
    grants = [g for g in L["store"].list_grants() if g["principal_kind"] == "pool"]
    assert len(grants) == 1 and grants[0]["action"] == "model.use"
    actions = [r["action"] for r in L["store"].audit_list(limit=50)]
    assert "pool.approve" in actions


def test_wrong_codes_change_the_code_and_then_shut_the_door(lan):
    L, A, B, loop, heard = lan
    t = _scan(L, loop)["pi-garage"]
    first = _code(B)
    wrong = "999999" if first != "999999" else "888888"
    for _ in range(provision.PIN_TRIES):
        with pytest.raises(ValueError):
            _enable(L, t, loop, code=wrong)
    assert _code(B) != first, "five wrong codes and the code changes"
    with _at(B):
        d = provision.load()
        d["pin_rounds"] = provision.PIN_ROUNDS - 1
        provision.save(d)
    for _ in range(provision.PIN_TRIES):
        with pytest.raises(ValueError):
            _enable(L, t, loop, code=wrong)
    with pytest.raises(ValueError, match="too many wrong codes"):
        _enable(L, t, loop, code=_code(B))


def test_an_enrolment_key_sets_a_pi_up_with_no_code(lan):
    L, A, B, loop, heard = lan
    with _at(L):
        k = provision.make_key("kitchen Pis", auto=True, profile={"kiosk": True})
    assert k["text"].startswith("bento-enroll-1.") and "secret" not in k
    with _at(A):
        provision.adopt_key(k["text"])
        assert provision.status(A["cfg"])["pin"] == "", "a keyed machine shows no code"
    t = _scan(L, loop)["pi-kitchen"]
    assert t["key_id"] == k["id"]
    with _at(L):
        assert provision.seen_list()[0]["our_key"] or any(e["our_key"] for e in provision.seen_list())
    r = _enable(L, t, loop)
    assert r["how"] == "key" and A["cfg"]["face"]["kiosk"] is True


def test_a_key_from_another_community_is_refused(lan, tmp_path):
    L, A, B, loop, heard = lan
    with teamlink.at(tmp_path / "other"):
        other = provision.make_key("theirs")
    with _at(L):
        mine = provision.make_key("mine")
    with _at(A):
        provision.adopt_key(other["text"])
    t = _scan(L, loop)["pi-kitchen"]
    assert t["key_id"] == other["id"] != mine["id"]
    with pytest.raises(ValueError, match="six-digit code"):
        _enable(L, t, loop)            # not our key, so it is a code machine to this leader


def test_a_device_that_only_copied_a_key_id_is_not_enabled(lan, monkeypatch):
    L, A, B, loop, heard = lan
    with _at(L):
        k = provision.make_key("auto", auto=True)
    with _at(A):
        provision.adopt_key(k["text"])
    t = _scan(L, loop)["pi-kitchen"]
    # a device that says yes to any claim, without holding the secret
    monkeypatch.setattr(provision, "check_claim", lambda req, nonce: (True, "", "not-the-secret"))
    with pytest.raises(ValueError, match="does not really hold the enrolment key"):
        _enable(L, t, loop)
    with _at(L):
        assert not provision.was_enabled_here(t["fp"]), "nothing is recorded for it"


def test_a_different_machine_at_that_address_is_refused(lan):
    L, A, B, loop, heard = lan
    got = _scan(L, loop)
    t = dict(got["pi-kitchen"])
    t["port"] = got["pi-garage"]["port"]           # B answers where A was heard
    with pytest.raises(ValueError, match="different machine answered"):
        _enable(L, t, loop, code=_code(A), raw=True)


# ---- what a stranger's beacon may carry ---------------------------------------------------

def test_a_beacon_is_cleaned_and_a_bad_one_dropped():
    assert provision.clean_beacon({"m": "nope"}) is None
    assert provision.clean_beacon({"m": provision.MAGIC, "fp": "short"}) is None
    b = provision.clean_beacon({"m": provision.MAGIC, "fp": "a" * 64, "name": "Pi\x1b]52;evil",
                                "hw": {"board": "Raspberry‮Pi", "ram_mb": "9" * 30},
                                "key_id": "not-hex", "port": 99999, "extra": "x"}, "10.0.0.5")
    assert b["name"] == "pi-52-evil" and "‮" not in b["hw"]["board"]
    assert b["hw"]["ram_mb"] <= 1 << 22 and b["key_id"] == "" and b["port"] == 0 and "extra" not in b


def test_the_profile_is_a_closed_set():
    p = provision.clean_profile({"name": "Kitchen Pi!", "agent_name": "x" * 99, "kiosk": 1,
                                 "buddy": "sometimes", "wake_word": "1234", "default_model": "evil/x"})
    assert p == {"name": "kitchen-pi", "agent_name": "x" * 32, "kiosk": True}


def test_keys_parse_strictly():
    assert provision.parse_key("bento-enroll-1.0a1b2c3d." + "s" * 32 + "." + "f" * 16)
    for bad in ("", "bento-enroll-1.zz.s.f", "bento-enroll-2.0a1b2c3d." + "s" * 32 + "." + "f" * 16):
        assert provision.parse_key(bad) is None


def test_there_is_no_agent_tool_for_enabling_a_machine():
    from agentos import tools
    names = {t["function"]["name"] if "function" in t else t.get("name") for t in tools.TOOL_SCHEMAS}
    assert not any("provision" in (n or "") for n in names), \
        "enabling a machine spends this machine's budget on it: a person's act"


def test_a_machine_heard_again_unchanged_is_not_written_again(tmp_path, monkeypatch):
    """An SD card wears out: a Pi left waiting announces every minute, and the leader's
    file of heard machines is not rewritten for each of those."""
    b = provision.clean_beacon({"m": provision.MAGIC, "fp": "b" * 64, "name": "pi", "waiting": True,
                                "port": 8620, "hw": {}}, "10.0.0.9")
    with teamlink.at(tmp_path):
        assert provision.note_seen(b) is True
        mtime = provision.path().stat().st_mtime_ns
        assert provision.note_seen(b) is False
        assert provision.path().stat().st_mtime_ns == mtime, "nothing changed, nothing written"
        moved = dict(b, addr="10.0.0.10")
        provision.note_seen(moved)
        assert provision.find_seen("pi")["addr"] == "10.0.0.10", "a machine that moved is written down"
