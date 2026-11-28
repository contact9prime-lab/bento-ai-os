"""Sharing a device with another account: read-only or read-write (agentos/devshare.py).

Reported with two screenshots: the owner's three Pis showed on every admin's Devices board,
because they belonged to the machine and the machine's devices are every admin's. Asked for as
"the user should explicitly share that with other users", then "RO / RW access … getters and
setters done based on that; RO may still monitor those devices but not do anything with them,
and run agents to collect, to view metrics".
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import config as cfgmod                                # noqa: E402
from agentos import devshare, teamlink                              # noqa: E402
from agentos import users as usersmod                               # noqa: E402
from agentos import vault                                           # noqa: E402
from agentos import zero as zeromod                                 # noqa: E402
from agentos.memory import Store                                    # noqa: E402

PW = "correct horse 1"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    usersmod.reset_caches()
    usersmod.set_current("")
    vault.forget_held()
    links = {"links": []}
    monkeypatch.setattr(teamlink, "_load", lambda: links)
    monkeypatch.setattr(teamlink, "_save", lambda d: None)
    monkeypatch.setattr(zeromod, "ships_to", lambda lk: lk.get("kind") == "machine")
    yield tmp_path, links
    vault.forget_held()
    usersmod.reset_caches()
    usersmod.set_current("")


def _stores():
    opened = {}

    def store_for(uid):
        if uid not in opened:
            opened[uid] = Store(str(usersmod.home_for(uid) / "agentos.db"))
        return opened[uid]
    return store_for


def _rows(store, ref):
    return sorted((g["action"], g["resource"]) for g in store.list_grants("user", "")
                  if g.get("source") == "share" and g.get("source_ref") == ref)


def test_a_device_is_its_owners_until_shared_and_the_share_is_its_grants(home):
    _, links = home
    ada = usersmod.create("ada", PW, role="admin")
    bob = usersmod.create("bob", PW)
    links["links"] += [{"id": "L1", "label": "raspberrypi-2", "kind": "machine", "owner": ada["id"]}]
    lk = links["links"][0]
    store_for = _stores()
    assert devshare.level_of(lk, ada["id"]) == "own"
    assert devshare.level_of(lk, bob["id"]) == "", "nobody else sees it until it is shared"
    assert devshare.shared_with(bob["id"]) == []

    got = devshare.set_share("raspberrypi-2", ada["id"], "bob", "ro", store_for)
    assert got["level"] == "ro" and devshare.level_of(lk, bob["id"]) == "ro"
    assert [x["name"] for x in got["shares"]] == ["bob"]
    assert _rows(store_for(bob["id"]), "share:raspberrypi-2") == [("device.get", "device:raspberrypi-2/*")], \
        "watching is a read grant only"

    devshare.set_share("raspberrypi-2", ada["id"], bob["id"], "rw", store_for)
    assert _rows(store_for(bob["id"]), "share:raspberrypi-2") == [
        ("device.get", "device:raspberrypi-2/*"), ("device.set", "device:raspberrypi-2/*")]

    # a grant bob wrote himself is his, and survives the share ending
    store_for(bob["id"]).add_grant("user", "", "device.get", "device:raspberrypi-2/temp", source="person")
    devshare.set_share("raspberrypi-2", ada["id"], "bob", "off", store_for)
    assert devshare.level_of(lk, bob["id"]) == "" and _rows(store_for(bob["id"]), "share:raspberrypi-2") == []
    assert any(g["resource"] == "device:raspberrypi-2/temp" for g in store_for(bob["id"]).list_grants("user", ""))


def test_what_cannot_be_shared_is_refused_in_words(home):
    _, links = home
    ada = usersmod.create("ada", PW, role="admin")
    usersmod.create("bob", PW)
    links["links"] += [{"id": "L1", "label": "pi", "kind": "machine", "owner": ""},
                       {"id": "L2", "label": "mine", "kind": "machine", "owner": ada["id"]}]
    store_for = _stores()
    with pytest.raises(ValueError, match="Make it mine"):
        devshare.set_share("pi", "", "bob", "ro", store_for)
    with pytest.raises(ValueError, match="no account called"):
        devshare.set_share("mine", ada["id"], "carol", "ro", store_for)
    with pytest.raises(ValueError, match="already yours"):
        devshare.set_share("mine", ada["id"], "ada", "ro", store_for)
    with pytest.raises(ValueError, match="ro .* or rw"):
        devshare.set_share("mine", ada["id"], "bob", "admin", store_for)
    with pytest.raises(LookupError):
        devshare.set_share("pi", ada["id"], "bob", "ro", store_for)   # not hers, so not hers to share


def test_the_machines_own_device_is_still_every_admins_and_says_so(home):
    _, links = home
    ada = usersmod.create("ada", PW, role="admin")
    bob = usersmod.create("bob", PW)
    lk = {"id": "L1", "label": "pi", "kind": "machine", "owner": ""}
    links["links"].append(lk)
    assert devshare.level_of(lk, ada["id"]) == "own" and devshare.level_of(lk, bob["id"]) == ""


def test_removing_a_device_takes_its_shares_with_it(home):
    _, links = home
    ada = usersmod.create("ada", PW, role="admin")
    bob = usersmod.create("bob", PW)
    links["links"].append({"id": "L1", "label": "pi", "kind": "machine", "owner": ada["id"]})
    store_for = _stores()
    devshare.set_share("pi", ada["id"], "bob", "rw", store_for)
    assert devshare.forget("pi", ada["id"], store_for) == 1
    assert _rows(store_for(bob["id"]), "share:pi") == [] and devshare.shared_with(bob["id"]) == []


def test_read_only_never_switches_and_the_owner_diary_names_who():
    src = (Path(__file__).parent.parent / "agentos" / "server.py").read_text()
    tool = src[src.index("async def _device_tool"):src.index("async def _device_tool") + 4000]
    assert 'lk.get("_access") == "ro"' in tool and "to watch only" in tool
    assert "'s)\"" in tool or "'s)" in tool, "the owner's diary says whose agent it was"
    board = src[src.index("async def api_device_board"):src.index("async def api_device_board") + 3500]
    assert "_shared_machines(me)" in board and "Never judged from here" in board
    js = (Path(__file__).parent.parent / "agentos/ui/src/js/01h-devscene.js").read_text()
    assert "!a.shared" in js, "somebody else's alarm has no Acknowledge"
    assert "Make it mine" in js and "/api/devices/share" in js
