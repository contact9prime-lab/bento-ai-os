"""Bring every home on this machine up to the code on disk — the machine's and each account's.

Accounts are isolated by directory (docs/users.md): every person has their own
database and config under ~/.agentos/users/<id>/. A schema change, a new built-in
row (the executor profiles), a character for every agent — each of those has to
reach EVERY one of those homes, not only the one that happened to be opened first.
Left lazy, the first request after an update is what migrates a person's database,
and a person who signs in on a phone an hour later meets a half-migrated home.

So an update runs this once, for everybody, in a FRESH process (`bento migrate`):
the process doing the pull imported the old code, and migrations written in the new
code are not in it. The server also runs it at start, so a machine updated by hand
(`git pull` and a restart) is brought up the same way.

What it does per home, all idempotent:
- opens the database, which runs `Store._migrate` (new tables and columns);
- seeds the built-in executor profiles (`hands.ensure_builtins`);
- generates and stores a character for anybody who has none (`avatars.ensure`).

It reports each home in a sentence, and one home failing never stops the others —
a broken account must not keep everybody else on the old schema.

Stdlib and the store only: no HTTP, no asyncio, like the other modules a terminal
runs with the server down.
"""
from __future__ import annotations


def _one(label: str, cfg: dict, store) -> dict:
    from . import avatars, hands
    hands.ensure_builtins(store)
    people = avatars.ensure(store, cfg)
    return {"home": label, "ok": True, "characters": len(people)}


def everyone(log=None) -> list[dict]:
    """Migrate the machine's home and every account's. Returns one row per home."""
    from . import config as cfgmod
    from . import users as usersmod
    from .memory import Store
    say = log or (lambda m: None)
    out = []
    try:
        cfg = cfgmod.load_config()
        out.append(_one("this machine", cfg, Store(cfgmod.DB_PATH)))
    except Exception as e:
        out.append({"home": "this machine", "ok": False, "error": f"{type(e).__name__}: {e}"})
    try:
        people = usersmod.list_users() if usersmod.enabled() else []
    except Exception:
        people = []
    for u in people:
        label = f"{u.get('name') or u['id']}'s home"
        try:
            with usersmod.as_user(u["id"]):
                out.append(_one(label, usersmod.cfg_for(u["id"]), usersmod.store_for(u["id"])))
        except Exception as e:
            out.append({"home": label, "ok": False, "error": f"{type(e).__name__}: {e}"})
    for r in out:
        say(f"{'✓' if r['ok'] else '✗'} {r['home']}: "
            + (f"up to date ({r['characters']} characters)" if r["ok"] else r["error"]))
    return out
