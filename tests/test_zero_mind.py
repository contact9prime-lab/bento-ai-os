"""A Zero's soul, memory and knowledge graph are kept on its hub, in a section of their own.

Asked for as "in zero mode the souls and memory and kb should be with the hub and
sectioned". A hub and a Zero stand up in this process, linked over real mTLS. What these
defend:

- what a Zero remembers, the facts it adds and its soul are written on the hub, in its
  section, and nothing is written on the Zero;
- a Zero sees ONLY its section: never the hub's own memory, never another Zero's, and it
  cannot forget or correct a row outside it;
- the lead's prompt on a Zero is built from the hub (memories, facts, soul), with the
  Zero's own budget;
- what the Zero kept before it ran on its hub moves there once;
- a machine the hub did not set up to run its work there is refused, and a hub that can't
  be reached is said, with nothing kept locally in its place;
- the hub works a Zero's task inside that Zero's section.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod                                  # noqa: E402
from agentos import executors, provision, teamlink, zeromind          # noqa: E402
from agentos.agent import Agent                                       # noqa: E402
from agentos.memory import Store                                      # noqa: E402
from test_teamlink import _machine                                    # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def hz(tmp_path, monkeypatch):
    """'office' is the hub, 'pi' a Zero it set up to run its work there."""
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": "aria")
    H = _machine(tmp_path / "office", "office")
    Z = _machine(tmp_path / "pi", "pi")
    Z["cfg"]["memory"] = {"inject_user": 10, "inject_facts": 10, "auto_extract": False}
    souls = {}

    def soul_path():
        return souls.get(str(teamlink.home()), tmp_path / "nowhere" / "soul.md")
    monkeypatch.setattr(cfgmod, "soul_path", soul_path)
    souls[str(H["home"])] = H["home"] / "soul.md"
    souls[str(Z["home"])] = Z["home"] / "soul.md"

    async def setup():
        async def on_ask(lk, req):
            with teamlink.at(H["home"]):
                if req.get("op") == "zero_mind":
                    return await zeromind.answer(H["store"], H["cfg"], lk, req)
                return await H["cp"].answer_linked(lk, req)
        with teamlink.at(H["home"]):
            H["lst"] = teamlink.Listener(H["cfg"], on_ask=on_ask)
            port = await H["lst"].start("127.0.0.1", 0)
            inv = teamlink.invite("", "machine", address="127.0.0.1", port=port, cfg=H["cfg"])
        with teamlink.at(Z["home"]):
            Z["lst"] = teamlink.Listener(Z["cfg"])
            await Z["lst"].start("127.0.0.1", 0)
            Z["link"] = await teamlink.join(inv["invite"], "", cfg=Z["cfg"])
    loop = asyncio.new_event_loop()
    loop.run_until_complete(setup())
    with teamlink.at(H["home"]):
        lk = teamlink._load()["links"][0]
        H["zero_lk"] = lk
        d = provision.load()
        d["enabled"][lk["peer_host_fp"]] = {"name": "pi", "label": lk["label"], "execution": "hub", "at": 1}
        provision.save(d)
    with teamlink.at(Z["home"]):
        d = provision.load()
        d["claimed"] = {"leader_fp": Z["link"]["peer_host_fp"], "by": "office", "at": 1}
        provision.save(d)
    Z["cfg"]["zero"] = {"hub": Z["link"]["label"], "execution": "hub", "moved": 1}
    monkeypatch.setattr(cfgmod, "save_config", lambda cfg: None)
    yield H, Z, loop
    for m in (H, Z):
        loop.run_until_complete(m["lst"].stop())
    loop.close()


def _on(m, loop, coro):
    async def go():
        with teamlink.at(m["home"]):
            return await coro()
    return loop.run_until_complete(go())


def _section(H):
    with teamlink.at(H["home"]):
        return zeromind.section(H["store"], H["zero_lk"])


# ---- the rule, in the store ---------------------------------------------------------------------

def test_only_means_that_space_and_nothing_global(tmp_path):
    s = Store(tmp_path / "s.db")
    sid = s.create_space("Zero · pi")
    other = s.create_space("Zero · garage")
    s.add_memory("global fact", space_id="")
    s.add_memory("pi fact", space_id=sid)
    s.add_memory("garage fact", space_id=other)
    s.kg_add("Ada", "likes", "tea", space_id=sid)
    s.kg_add("Ada", "works at", "Accacia", space_id="")
    s.kg_add("Lonely", "is", "orphan")
    s.kg_delete_edges(Store.only(other))      # nothing of garage's: a no-op
    got = [m["content"] for m in s.search_memories("", space=Store.only(sid))]
    assert got == ["pi fact"]
    assert sorted(m["content"] for m in s.search_memories("", space=sid)) == ["global fact", "pi fact"], \
        "the ordinary rule is unchanged"
    assert s.kg_query("", space=Store.only(sid)) == ["Ada —likes→ tea"]
    g = s.kg_graph(Store.only(sid))
    assert {n["name"] for n in g["nodes"]} == {"Ada", "tea"}, "no orphan and no global entity alone"
    assert s.kg_delete_edges(Store.only(sid)) == 1 and s.kg_query("", space=Store.only(sid)) == []
    assert s.kg_query("Accacia"), "a section forgets its own assertions, never the hub's"
    assert s.search_memories("", space=Store.only("")) == [], "an empty section is no section"


# ---- the Zero's mind on the hub ------------------------------------------------------------------

def test_what_a_zero_remembers_is_written_on_the_hub_in_its_section(hz):
    H, Z, loop = hz
    H["store"].add_memory("HUB-PRIVATE: the hub owner's bank is X")
    out = _on(Z, loop, lambda: Z["tb"].remember("The kitchen Pi's user likes green tea"))
    assert out.startswith("remembered") and "on office" in out, out
    assert Z["store"].search_memories("") == [], "nothing is written on the Zero"
    sid = _section(H)
    rows = H["store"].search_memories("", space=Store.only(sid))
    assert [r["content"] for r in rows] == ["The kitchen Pi's user likes green tea"]
    assert rows[0]["source"] == "zero:" + H["zero_lk"]["label"]
    assert H["store"].get_space(sid)["name"].startswith("Zero · ")
    rec = _on(Z, loop, lambda: Z["tb"].recall("tea"))
    assert "green tea" in rec and "HUB-PRIVATE" not in rec
    assert "HUB-PRIVATE" not in _on(Z, loop, lambda: Z["tb"].recall(""))


def test_a_zero_sees_only_its_section_and_can_change_nothing_else(hz):
    H, Z, loop = hz
    other = H["store"].create_space("Zero · garage")
    gid = H["store"].add_memory("garage secret", space_id=other)
    hid = H["store"].add_memory("hub global memory")
    H["store"].kg_add("Hub", "holds", "keys")
    assert "garage" not in _on(Z, loop, lambda: Z["tb"].recall("secret"))
    for mid in (gid, hid):
        assert _on(Z, loop, lambda: Z["tb"].forget(mid)).startswith("[error]")
    assert len(H["store"].search_memories("", limit=50)) == 2, "nothing outside its section was forgotten"
    _on(Z, loop, lambda: Z["tb"].kg_add("Kitchen", "has", "kettle"))
    facts = _on(Z, loop, lambda: Z["tb"].kg_query(""))
    assert "Kitchen —has→ kettle" in facts and "keys" not in facts
    # an after-turn correction can only touch the section's own rows
    r = _on(Z, loop, lambda: zeromind.ask(Z["cfg"], "learn", conversation_id="c1",
                                          retractions=["hub global memory"],
                                          updates=[{"old": "garage secret", "new": "rewritten"}],
                                          user_memories=["likes rooibos too"]))
    assert r["ok"] and r["retracted"] == 0 and r["updated"] == 0 and r["user"] == 1
    assert {m["content"] for m in H["store"].search_memories("", limit=50)} >= {"hub global memory", "garage secret"}


def test_the_soul_lives_on_the_hub_and_the_hubs_own_is_untouched(hz):
    H, Z, loop = hz
    (H["home"] / "soul.md").write_text("I am the hub's own agent." * 3)
    new = "You are Pip, the kitchen's helper. You keep it short and warm, and you love tea."
    out = _on(Z, loop, lambda: Z["tb"].update_soul(new))
    assert out == "soul updated on office", out
    label = H["zero_lk"]["label"]
    with teamlink.at(H["home"]):
        assert zeromind.soul_of(label) == new
        assert zeromind.soul_file(label).parent.name == "zeros"
    assert (H["home"] / "soul.md").read_text().startswith("I am the hub's own agent")
    assert not (Z["home"] / "soul.md").exists(), "the Zero keeps no soul of its own"
    rows = [r["action"] for r in H["store"].audit_list(limit=20)]
    assert "zero.soul" in rows
    got = _on(Z, loop, lambda: zeromind.ask(Z["cfg"], "soul_get"))
    assert got["soul"] == new
    with teamlink.at(Z["home"]):
        assert zeromind.soul_now(Z["cfg"]) == new, "the hub's last word is what the Zero says it is"


def test_the_zero_leads_prompt_is_built_from_the_hub(hz):
    H, Z, loop = hz
    _on(Z, loop, lambda: Z["tb"].remember("The user's name is Ada"))
    _on(Z, loop, lambda: Z["tb"].kg_add("Ada", "drinks", "green tea"))
    _on(Z, loop, lambda: Z["tb"].update_soul("You are Pip, the kitchen's helper, short and warm. " * 2))
    H["store"].add_memory("HUB-PRIVATE never on a Zero")

    async def em(ev):
        pass

    async def ok(*a, **k):
        return True
    agent = Agent(Z["cfg"], Z["tb"], "openai/gpt-4o", em, ok)
    text = _on(Z, loop, lambda: agent._system("what does Ada drink?"))
    assert "kept on office" in text and "The user's name is Ada" in text
    assert "Ada —drinks→ green tea" in text and "You are Pip" in text
    assert "HUB-PRIVATE" not in text


def test_what_it_kept_before_moves_to_the_hub_once(hz):
    H, Z, loop = hz
    Z["cfg"]["zero"].pop("moved")
    Z["store"].add_memory("from before: the fridge is in the corner")
    Z["store"].kg_add("Fridge", "is in", "corner")
    (Z["home"] / "soul.md").write_text("You are the old soul of this Pi, kept before it joined. " * 2)
    _on(Z, loop, lambda: Z["tb"].recall(""))
    assert Z["cfg"]["zero"].get("moved")
    sid = _section(H)
    mems = [m["content"] for m in H["store"].search_memories("", space=Store.only(sid))]
    assert mems == ["from before: the fridge is in the corner"]
    assert H["store"].kg_query("", space=Store.only(sid)) == ["Fridge —is in→ corner"]
    with teamlink.at(H["home"]):
        assert zeromind.soul_of(H["zero_lk"]["label"]).startswith("You are the old soul")
    _on(Z, loop, lambda: Z["tb"].recall(""))
    assert len(H["store"].search_memories("", space=Store.only(sid))) == 1, "moved once"
    assert "zero.moved" in [r["action"] for r in H["store"].audit_list(limit=20)]


def test_a_machine_not_set_up_to_run_here_is_refused(hz):
    H, Z, loop = hz
    with teamlink.at(H["home"]):
        d = provision.load()
        d["enabled"][H["zero_lk"]["peer_host_fp"]]["execution"] = "here"
        provision.save(d)
    out = _on(Z, loop, lambda: Z["tb"].remember("anything"))
    assert out.startswith("[error]") and "did not set you up" in out
    assert H["store"].search_memories("") == [] and Z["store"].search_memories("") == []


def test_a_hub_that_cant_be_reached_is_said_and_nothing_is_kept_locally(hz):
    H, Z, loop = hz
    loop.run_until_complete(H["lst"].stop())
    out = _on(Z, loop, lambda: Z["tb"].remember("while the hub is away"))
    assert out.startswith("[error]") and "could not be reached" in out
    assert Z["store"].search_memories("") == []
    ctx = _on(Z, loop, lambda: zeromind.context(Z["cfg"], Z["store"], "hi"))
    assert not ctx["ok"] and "could not be reached" in zeromind.mem_text(ctx, "office")
    H["lst"] = teamlink.Listener(H["cfg"])            # the fixture stops it again
    loop.run_until_complete(H["lst"].start("127.0.0.1", 0))


def test_an_ordinary_machine_keeps_its_own(tmp_path):
    cfg = {"zero": {"hub": "office", "execution": "here"}}
    with teamlink.at(tmp_path):
        assert not zeromind.on_hub(cfg) and not zeromind.on_hub({})


def test_the_hubs_terminal_shows_each_zeros_section(hz):
    """Found by the live run: the hub's `bento pool mind` opened no database and printed nothing."""
    import subprocess
    H, Z, loop = hz
    _on(Z, loop, lambda: Z["tb"].remember("the user likes green tea"))
    env = {**os.environ, "AGENTOS_HOME": str(H["home"]), "AGENTOS_VAULT_KEYRING": "0"}
    label = H["zero_lk"]["label"]
    every = subprocess.run([sys.executable, "-m", "agentos", "pool", "mind"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=60)
    assert every.returncode == 0, every.stderr
    assert label in every.stdout and "1 memories" in every.stdout
    one = subprocess.run([sys.executable, "-m", "agentos", "pool", "mind", label], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)
    assert "memory    the user likes green tea" in one.stdout, one.stdout + one.stderr


# ---- the faces -------------------------------------------------------------------------------

def test_every_face_reads_the_hub():
    srv = (ROOT / "agentos/server.py").read_text()
    for route in ("api_kg", "api_kg_add", "api_kg_clear", "api_kg_delete_node", "api_soul", "api_put_soul",
                  "api_memories", "api_add_memory", "api_update_memory", "api_delete_memory"):
        body = srv.split(f"async def {route}(", 1)[1].split("\n@app.", 1)[0]
        assert "_zero_mind(" in body, f"{route} reads the hub on a Zero"
    assert '"zero_mind"' in (ROOT / "agentos/teamlink.py").read_text()
    js = (ROOT / "agentos/ui/src/js/17-soul-kg.js").read_text()
    assert "mindKeptOn" in js and "soul-who" in js and "Zero · " in js
    assert "m.zero" in (ROOT / "agentos/ui/src/js/12-memory-profile.js").read_text()
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"mind"' in main and "_zero_mind_cli" in main
    know = (ROOT / "agentos/knowledge.py").read_text()
    assert "_learn_on_hub" in know, "auto-learn on a Zero writes to the hub"
