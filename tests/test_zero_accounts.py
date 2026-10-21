"""A Zero belongs to an account on its hub.

Asked for as "can you confirm the hub integrations are per user, so whatever we authorise is
only for that user, as MCP would be activated there; a system may have multiple users with
their own integrations, and their own Zeros attached". Integrations already were per account
(MCP servers, channels, mail, calendar and sign-ins are users.USER_KEYS), but every Zero's link
was written with owner '', so the hub answered every Zero as the machine, with nobody's
integrations. What these defend:

- the automatic key in a Zero's one line is one per account, and a machine set up with it
  belongs to that account (its link's owner, which is who the hub answers it as);
- an admin can set a machine up for a named account, and without one it stays the machine's;
- the list of machines says whose each is.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import provision, teamlink                                     # noqa: E402
from test_provision import _at, _code, _enable, _scan, lan                  # noqa: E402,F401

ROOT = Path(__file__).parent.parent


def test_a_zero_key_is_one_per_account(lan):
    L, A, B, loop, heard = lan
    with _at(L):
        ada, bob, machine = provision.zero_key("ada"), provision.zero_key("bob"), provision.zero_key()
        assert len({ada["id"], bob["id"], machine["id"]}) == 3, "each account's Zeros have their own key"
        assert provision.zero_key("ada")["id"] == ada["id"], "asked again, the same key"
        assert {k["id"]: k["owner"] for k in provision.keys()} == {
            ada["id"]: "ada", bob["id"]: "bob", machine["id"]: ""}


def _link(L, fp):
    with _at(L):
        return next(lk for lk in teamlink._load()["links"] if lk.get("peer_host_fp") == fp)


def test_a_machine_set_up_with_an_accounts_line_belongs_to_that_account(lan):
    L, A, B, loop, heard = lan
    with _at(L):
        k = provision.zero_key("bob")
    with _at(A):
        provision.adopt_key(k["text"])
    t = _scan(L, loop)["pi-kitchen"]
    r = _enable(L, t, loop)
    assert r["how"] == "key" and r["owner"] == "bob"
    assert _link(L, t["fp"])["owner"] == "bob", "the hub answers it as bob, with bob's integrations"
    with _at(L):
        assert provision.load()["enabled"][t["fp"]]["owner"] == "bob"
        assert next(m for m in provision.seen_list() if m["fp"] == t["fp"])["owner"] == "bob"


def test_a_machine_set_up_by_code_is_the_machines_unless_an_account_is_named(lan):
    L, A, B, loop, heard = lan
    seen = _scan(L, loop)
    r = _enable(L, seen["pi-kitchen"], loop, code=_code(A))
    assert r["owner"] == "" and _link(L, seen["pi-kitchen"]["fp"])["owner"] == ""

    async def go():
        with _at(L):
            t = provision.find_seen(seen["pi-garage"]["fp"])
            return await provision.enable(L["cfg"], t, {}, code=_code(B),
                                          pool_info={"id": "x", "name": "Home"}, owner="ada")
    r = loop.run_until_complete(go())
    assert r["owner"] == "ada" and _link(L, seen["pi-garage"]["fp"])["owner"] == "ada"


def test_every_face_can_say_whose_a_zero_is():
    srv = (ROOT / "agentos/server.py").read_text()
    assert "def _zero_for(" in srv and 'provmod.zero_key(owner)' in srv
    assert '"owner_name"' in srv and '"accounts"' in srv, "the list says whose; an admin can choose"
    assert 'with usersmod.as_user(r.get("owner") or "")' in srv, \
        "the hub's half of a Zero (its cells, its folder) is written in the owner's account"
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"--for", dest="for_account"' in main and "prov.zero_key(owner)" in main
    js = (ROOT / "agentos/ui/src/js/24j-provision.js").read_text()
    assert "zero-for" in js and "owner_name" in js


def test_a_zeros_office_says_its_brain_is_on_the_hub():
    """Its memory is its section on the hub; this machine's empty tables are not its brain."""
    off = (ROOT / "agentos/office.py").read_text()
    assert '"brain": _brain_here(cfg, store)' in off and 'return {"on":' in off
    js = (ROOT / "agentos/ui/src/js/24k-office3d.js").read_text()
    assert "br.on?'on '+esc(br.on)" in js
