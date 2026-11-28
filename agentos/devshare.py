"""Sharing a device with another account on this machine: read-only or read-write.

Asked for as "the devices added to my account are shared across the other accounts … the
user should explicitly share that with other users", then "RO / RW access … getters and
setters done based on that. RO, you may still monitor those devices between the accounts
but not do anything with them; also run agents to collect, to view metrics".

A device is a machine link this hub set up (a Zero), and it belongs to one account: the
link's `owner`. Nobody else sees it unless the owner shares it here. A share is two things,
kept together:

- **`shares` on the link** (`{account id: "ro" | "rw"}`): which boards show it, read by the
  board, the alarm list, the history and the device tools. Shared machines are drawn as
  somebody else's: no Acknowledge, no rules, no switching from the board.
- **Grants in the other account** (source `share`, source_ref `share:<label>`): `device.get`
  for read-only, `device.get` and `device.set` for read-write, on `device:<machine>/*`, for
  that account's own agent. So the gate decides the getters and setters exactly as it does
  for the owner's: the Pi still answers only what it lends, and every set is still asked of
  a person. Ending a share revokes those rows and only those.

A link the MACHINE owns (installed before Bento recorded who installed it) is still shown to
the machine's admins, as before, with "Make it mine" (ties.adopt) offered on it. Sharing is
for a link an account owns: the machine's has nobody to decide.

No agent tool reaches any of this: who may watch or switch a device is a person's decision.
Each change is a `device.share` ledger row in the owner's account.
"""

from __future__ import annotations

LEVELS = ("ro", "rw")
WORDS = {"ro": "can watch it", "rw": "can watch and switch it"}


def _ref(label: str) -> str:
    return f"share:{str(label or '').strip().lower()}"


def level_of(lk: dict, uid: str) -> str:
    """'own', 'rw', 'ro' or '' for this account and this link. The machine's own link is an
    admin's, as it always was; nothing else is anybody's but its owner's and who it is shared with."""
    from . import users as usersmod
    owner = lk.get("owner") or ""
    if owner == (uid or ""):
        return "own"
    if not owner and usersmod.is_admin(uid or ""):
        return "own"
    lv = (lk.get("shares") or {}).get(uid or "")
    return lv if lv in LEVELS else ""


def shares_of(lk: dict) -> list[dict]:
    """Who a link is shared with, by name, for the owner's card."""
    from . import users as usersmod
    out = []
    for uid, lv in sorted((lk.get("shares") or {}).items()):
        if lv not in LEVELS:
            continue
        u = usersmod.get(uid) or {}
        out.append({"uid": uid, "name": u.get("name") or uid, "level": lv, "words": WORDS[lv]})
    return out


def shared_with(uid: str) -> list[tuple[dict, str]]:
    """(link, level) for every device another account shared with this one."""
    from . import teamlink
    from . import zero as zeromod
    out = []
    for lk in teamlink._load()["links"]:
        lv = (lk.get("shares") or {}).get(uid or "")
        if lv in LEVELS and (lk.get("owner") or "") != (uid or "") and zeromod.ships_to(lk):
            out.append((lk, lv))
    return out


def _grants(store, machine: str, label: str, level: str) -> None:
    """The other account's own agent may read (and for rw, switch) this machine's things.
    Only rows this wrote are revoked: a grant the person wrote by hand stays theirs."""
    from . import devio
    ref = _ref(label)
    for g in store.list_grants("user", ""):
        if g.get("source") == "share" and g.get("source_ref") == ref and not g.get("principal_id"):
            store.revoke_grant(g["id"])
    if not level:
        return
    res = devio.resource(machine, "*")
    store.add_grant("user", "", "device.get", res, source="share", source_ref=ref,
                    note=f"{label} is shared with you")
    if level == "rw":
        store.add_grant("user", "", "device.set", res, source="share", source_ref=ref,
                        note=f"{label} is shared with you to switch")


def set_share(label: str, owner: str, who: str, level: str, store_for) -> dict:
    """Share the owner's device `label` with account `who` (an id or a name) at `level`
    ('ro', 'rw'), or end the share ('' or 'off'). `store_for(uid)` opens that account's store."""
    from . import teamlink
    from . import users as usersmod
    from . import zero as zeromod
    level = "" if level in ("", "off", "none") else level
    if level and level not in LEVELS:
        raise ValueError("share as ro (watch it) or rw (watch and switch it)")
    owner = owner or ""
    if not owner:
        raise ValueError("this device belongs to the machine: press Make it mine first, then share it")
    u = usersmod.get(who) or usersmod.by_name(who)
    if u is None:
        raise ValueError(f"there's no account called '{who}' here")
    uid = u["id"]
    if uid == owner:
        raise ValueError("it is already yours")
    if usersmod.tenant_of(uid) != usersmod.tenant_of(owner):
        raise ValueError(f"{u.get('name') or uid} is in another tenant, and nothing crosses tenants")
    d = teamlink._load()
    lk = next((x for x in d["links"] if (x.get("owner") or "") == owner and x.get("label") == label), None)
    if lk is None or not zeromod.ships_to(lk):
        raise LookupError(f"you have no device called '{label}'")
    shares = dict(lk.get("shares") or {})
    if level:
        shares[uid] = level
    else:
        shares.pop(uid, None)
    lk["shares"] = shares
    teamlink._save(d)
    with usersmod.as_user(uid):
        _grants(store_for(uid), label, label, level)
    return {"ok": True, "label": label, "account": u.get("name") or uid, "level": level,
            "shares": shares_of(lk)}


def forget(label: str, owner: str, store_for) -> int:
    """A device that is removed or handed over takes its shares with it: every other account's
    rows for it are revoked. Returns how many accounts lost it."""
    from . import teamlink
    from . import users as usersmod
    d = teamlink._load()
    lk = next((x for x in d["links"] if (x.get("owner") or "") == (owner or "") and x.get("label") == label), None)
    if lk is None:
        return 0
    gone = [uid for uid, lv in (lk.get("shares") or {}).items() if lv in LEVELS]
    for uid in gone:
        with usersmod.as_user(uid):
            _grants(store_for(uid), label, label, "")
    lk["shares"] = {}
    teamlink._save(d)
    return len(gone)
