"""A Zero's mind is on its hub: its soul, its memory and its knowledge graph live in the
hub's home, in a section of their own, and the Zero reaches them over its link.

Asked for as "in zero mode the souls and memory and kb should be with the hub and
sectioned". A Zero is a small machine that can be lost, wiped or reflashed; what its agent
knows should outlive it, and the hub is where its work already runs (zero.py).

The section is an ordinary space on the hub ("Zero · <label>"), so the hub's own screens,
spaces and the visibility rule already understand it. Two things make it a SECTION rather
than a project:

  * the Zero reads and writes ONLY its own rows (Store.only): never the hub's global
    memory, never another Zero's. The hub's agents working a task for it see the section
    and the hub's global rows, which is the ordinary space rule; they are the hub's team.
  * a Zero cannot write anywhere else: every write is filed under its space whatever it
    asked, and an entity is shared but an assertion is the section's.

One wire op, `zero_mind`, with an `action`, answered by `answer` on the hub only for a
machine it set up to run its work there (zero.ships_to). The Zero's side (`on_hub`, `ask`,
`context`, `tool`) is what the agent loop, the tools and the routes call. When the hub
can't be reached the Zero says so; nothing is written locally in its place.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from . import zero as zeromod

ACTIONS = ("context", "remember", "recall", "forget", "kg_add", "kg_query", "kg_forget",
           "soul_get", "soul_set", "list", "memory_edit", "learn", "import")
TIMEOUT = 20                  # seconds one request to the hub may take
MAX_CONTENT = 2000            # characters in one memory or one soul line set
MAX_SOUL = 20000              # characters in a soul
MAX_IMPORT = 400              # memories, and facts, in one import request
SECTION = "Zero · {label}"


# ---- the hub's side ----------------------------------------------------------------------

def _entry(lk: dict) -> tuple[dict, dict]:
    from . import provision
    d = provision.load()
    return d, d["enabled"].get(str(lk.get("peer_host_fp") or "")) or {}


def section(store, lk: dict) -> str:
    """The space id of this Zero's section on the hub, made the first time. Kept on the
    hub's record of the machine, so renaming the space on screen does not split it."""
    from . import provision
    d, e = _entry(lk)
    sid = str(e.get("space") or "")
    if sid and store.get_space(sid):
        return sid
    label = str(lk.get("label") or "zero")
    sid = store.create_space(SECTION.format(label=label),
                             description=f"What the Zero {label} remembers and knows. It sees only "
                                         f"this section; the hub's agents working for it see this "
                                         f"and what is true everywhere.")
    if e:
        e["space"] = sid
        provision.save(d)
    return sid


def soul_file(label: str) -> Path:
    from . import config as cfgmod
    return Path(cfgmod.soul_path()).parent / "zeros" / f"{zeromod.safe_name(label)}.md"


def soul_of(label: str) -> str:
    from . import config as cfgmod
    p = soul_file(label)
    try:
        return p.read_text() if p.exists() else cfgmod.DEFAULT_SOUL
    except OSError:
        return cfgmod.DEFAULT_SOUL


def sections(store) -> list[dict]:
    """Every Zero this hub keeps a mind for: {label, space}. For the screens."""
    from . import provision
    out = []
    for e in provision.load()["enabled"].values():
        if e.get("execution") == "hub" and e.get("space") and store.get_space(e["space"]):
            out.append({"label": e.get("label") or e.get("name") or "", "space": e["space"]})
    return out


def _text(v, cap=MAX_CONTENT) -> str:
    from . import teamlink
    return teamlink.plain(v, cap, newlines=True).strip()


async def _pick(cfg, rows: list[dict], query: str, n: int) -> list[dict]:
    """Pinned first, then the ones most relevant to the message (or the most recent)."""
    if len(rows) <= n:
        return rows
    pinned = [m for m in rows if m.get("pinned")]
    rest = [m for m in rows if not m.get("pinned")]
    take = max(0, n - len(pinned))
    picked = rest[:take]
    if query and take:
        try:
            from . import knowledge
            ranked = await knowledge.semantic_rank(cfg, rest, query)
            if ranked is not None:
                picked = ranked[:take]
        except Exception:
            pass
    return pinned + picked


def _mem(m: dict) -> dict:
    return {"id": m["id"], "content": m["content"], "scope": m.get("scope") or "user",
            "pinned": int(m.get("pinned") or 0), "source": m.get("source") or "",
            "conversation_id": m.get("conversation_id") or "", "created_at": m.get("created_at"),
            "updated_at": m.get("updated_at")}


async def answer(store, cfg: dict, lk: dict, req: dict) -> dict:
    """One request from a Zero, answered inside its section. Refused for any machine this
    hub did not set up to run its work here."""
    from .memory import Store
    from . import fabric as fabricmod
    if not zeromod.ships_to(lk):
        return {"ok": False, "error": "this machine did not set you up to keep your memory here"}
    action = str(req.get("action") or "")
    if action not in ACTIONS:
        return {"ok": False, "error": f"unknown request '{action}'"}
    label = str(lk.get("label") or "zero")
    sid = section(store, lk)
    only = Store.only(sid)
    src = f"zero:{label}"
    mc = cfg.get("memory") or {}

    def num(key, default, hi):
        try:
            return max(0, min(int(req.get(key, default)), hi))
        except (TypeError, ValueError):
            return default

    if action == "context":
        q = _text(req.get("query"))
        conv = str(req.get("conversation_id") or "")[:80]
        users = await _pick(cfg, store.search_memories("", limit=500, scope="user", space=only), q,
                            num("n_user", int(mc.get("inject_user", 15)), 60))
        sess = store.search_memories("", limit=num("n_session", int(mc.get("inject_session", 10)), 40),
                                     scope="session", conversation_id=conv, space=only) if conv else []
        facts = store.kg_query("", limit=num("n_facts", int(mc.get("inject_facts", 12)), 60), space=only)
        return {"ok": True, "section": SECTION.format(label=label), "soul": soul_of(label),
                "memories": [_mem(m) for m in users], "session": [_mem(m) for m in sess], "facts": facts}
    if action == "remember":
        content = _text(req.get("content"))
        if not content:
            return {"ok": False, "error": "nothing to remember"}
        scope = "session" if req.get("scope") == "session" and req.get("conversation_id") else "user"
        mid = store.add_memory(content, scope=scope, conversation_id=str(req.get("conversation_id") or "")[:80] or None,
                               source=src, pinned=1 if req.get("pinned") else 0, space_id=sid)
        return {"ok": True, "id": mid, "scope": scope}
    if action == "recall":
        q = _text(req.get("query"))
        rows = store.search_memories(q, limit=15, space=only)
        if q:
            try:
                from . import knowledge
                ranked = await knowledge.semantic_rank(cfg, store.search_memories("", limit=500, space=only), q)
                if ranked:
                    seen = {m["id"] for m in rows}
                    rows = (rows + [m for m in ranked[:10] if m["id"] not in seen])[:15]
            except Exception:
                pass
        return {"ok": True, "memories": [_mem(m) for m in rows]}
    if action in ("forget", "memory_edit"):
        mid = str(req.get("id") or "")
        mine = {m["id"] for m in store.search_memories("", limit=10**6, space=only)}
        if mid not in mine:
            return {"ok": False, "error": f"no memory with id {mid} in this machine's section"}
        if action == "forget":
            store.delete_memory(mid)
        else:
            store.update_memory(mid, content=_text(req["content"]) if "content" in req else None,
                                pinned=req.get("pinned") if "pinned" in req else None,
                                scope=req.get("scope") if req.get("scope") in ("user", "session") else None)
        return {"ok": True}
    if action == "kg_add":
        s, r, o = (_text(req.get(k), 200) for k in ("subject", "relation", "object"))
        if not (s and r and o):
            return {"ok": False, "error": "a fact needs a subject, a relation and an object"}
        eid = store.kg_add(s, r, o, _text(req.get("subject_type"), 40), _text(req.get("object_type"), 40),
                           space_id=sid)
        return {"ok": True, "id": eid}
    if action == "kg_query":
        return {"ok": True, "facts": store.kg_query(_text(req.get("query")), limit=40, space=only)}
    if action == "kg_forget":
        n = store.kg_delete_edges(only, node_id=str(req.get("node") or ""))
        return {"ok": True, "removed": n}
    if action == "soul_get":
        return {"ok": True, "soul": soul_of(label), "section": SECTION.format(label=label)}
    if action == "soul_set":
        text = str(req.get("content") or "")[:MAX_SOUL]
        if len(text.strip()) < 40:
            return {"ok": False, "error": "refusing to overwrite the soul with something that short"}
        set_soul(store, label, text, by=f"the Zero {label}")
        return {"ok": True}
    if action == "list":
        return {"ok": True, "section": SECTION.format(label=label),
                "memories": [_mem(m) for m in store.search_memories("", limit=2000, space=only)],
                "graph": store.kg_graph(only), "soul": soul_of(label)}
    if action == "learn":
        # what the Zero's after-turn pass learned (knowledge.extract_from_turn), applied in
        # its section: corrections and retractions only ever touch the section's own rows
        added = {"user": 0, "session": 0, "facts": 0, "updated": 0, "retracted": 0}
        mine = {m["content"].strip().lower(): m for m in store.search_memories("", limit=10**6, space=only)}
        conv = str(req.get("conversation_id") or "")[:80]
        for u in (req.get("updates") or [])[:5]:
            if isinstance(u, dict):
                hit = mine.get(str(u.get("old") or "").strip().lower())
                if hit and _text(u.get("new")):
                    store.update_memory(hit["id"], content=_text(u.get("new")))
                    added["updated"] += 1
        for old in (req.get("retractions") or [])[:5]:
            hit = mine.get(str(old or "").strip().lower()) if isinstance(old, str) else None
            if hit and not hit.get("pinned"):
                store.delete_memory(hit["id"])
                added["retracted"] += 1
        for c in (req.get("user_memories") or [])[:10]:
            if isinstance(c, str) and _text(c) and store.add_memory(_text(c), scope="user", source=src, space_id=sid):
                added["user"] += 1
        for c in (req.get("session_memories") or [])[:5]:
            if isinstance(c, str) and _text(c) and conv and store.add_memory(
                    _text(c), scope="session", conversation_id=conv, source=src, space_id=sid):
                added["session"] += 1
        for f in (req.get("facts") or [])[:10]:
            if isinstance(f, dict):
                s_, r_, o_ = (_text(f.get(k), 200) for k in ("subject", "relation", "object"))
                if s_ and r_ and o_:
                    store.kg_add(s_, r_, o_, _text(f.get("subject_type"), 40), _text(f.get("object_type"), 40),
                                 space_id=sid)
                    added["facts"] += 1
        return {"ok": True, **added}
    # import: what a Zero kept before it was set up to run here, moved once
    mems = req.get("memories") if isinstance(req.get("memories"), list) else []
    facts = req.get("facts") if isinstance(req.get("facts"), list) else []
    n_m = n_f = 0
    for m in mems[:MAX_IMPORT]:
        if isinstance(m, dict) and _text(m.get("content")):
            store.add_memory(_text(m.get("content")), scope="user", source=src,
                             pinned=1 if m.get("pinned") else 0, space_id=sid)
            n_m += 1
    for f in facts[:MAX_IMPORT]:
        if isinstance(f, (list, tuple)) and len(f) == 3 and all(_text(x, 200) for x in f):
            store.kg_add(*(_text(x, 200) for x in f), space_id=sid)
            n_f += 1
    soul = str(req.get("soul") or "")[:MAX_SOUL]
    if len(soul.strip()) >= 40 and not soul_file(label).exists():
        set_soul(store, label, soul, by=f"the Zero {label}, moving it here", audit=False)
    fabricmod.audit_team(store, "zero.moved", f"link:{label}",
                         f"took {n_m} memories, {n_f} facts" + (" and its soul" if soul.strip() else "")
                         + f" from the Zero {label} into its section")
    return {"ok": True, "memories": n_m, "facts": n_f}


def set_soul(store, label: str, text: str, by: str, audit: bool = True) -> None:
    p = soul_file(label)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    if audit:
        from . import fabric as fabricmod
        fabricmod.audit_team(store, "zero.soul", f"link:{label}", f"{by} changed the soul of {label}")


# ---- the Zero's side -----------------------------------------------------------------------

_SOUL: dict[str, str] = {}          # the last soul the hub sent, per home: said while it is away


def hub_link(cfg: dict) -> dict | None:
    from . import teamlink
    return next((lk for lk in teamlink._load()["links"] if zeromod.is_my_hub(cfg, lk)), None)


def on_hub(cfg: dict) -> bool:
    """Is this machine a Zero whose mind is on its hub?"""
    return zeromod.runs_on_hub(cfg) and hub_link(cfg) is not None


def _key() -> str:
    from . import teamlink
    return str(teamlink.home())


async def ask(cfg: dict, action: str, **kw) -> dict:
    from . import teamlink
    lk = hub_link(cfg)
    if not lk:
        return {"ok": False, "error": "this machine has no hub to keep its memory"}
    try:
        out = await teamlink.call(lk, {"op": "zero_mind", "action": action, **kw},
                                  timeout=TIMEOUT, limit=teamlink.POOL_LINE)
    except Exception as e:      # an answer is always a sentence, never a traceback
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not isinstance(out, dict):
        out = {"ok": False, "error": "the hub sent nothing usable"}
    if not out.get("ok"):
        out["error"] = (f"{lk['label']} could not be reached for this machine's memory "
                        f"({out.get('error') or 'no answer'})")
    elif out.get("soul"):
        _SOUL[_key()] = out["soul"]
    return out


def soul_now(cfg: dict) -> str:
    """The soul to use without waiting: the hub's last word, else the local file."""
    from . import config as cfgmod
    return _SOUL.get(_key()) or cfgmod.load_soul()


async def context(cfg: dict, store, query: str = "", conversation_id: str = "") -> dict:
    """What the lead is told about itself this turn, from the hub. Moves what this
    machine kept before, once, first."""
    await move_local(cfg, store)
    mc = cfg.get("memory") or {}       # this machine's settings decide its prompt's budget
    return await ask(cfg, "context", query=query[:2000], conversation_id=conversation_id,
                     n_user=int(mc.get("inject_user", 15)), n_session=int(mc.get("inject_session", 10)),
                     n_facts=int(mc.get("inject_facts", 12)))


def mem_text(ctx: dict, hub: str) -> str:
    """The memory part of the lead's prompt, from a context answer (the same shape the
    built-in loop writes for a local one)."""
    if not ctx.get("ok"):
        return (f"\n=== Memory ===\n{ctx.get('error')}. Say so if the person asks what you "
                f"remember, and don't pretend to.\n=== end memory ===\n")
    out = (f"\n=== Your memory is kept on {hub}, in its section '{ctx.get('section')}' ===\n"
           "remember, recall, kg_add and kg_query read and write it there.\n")
    if ctx.get("memories"):
        out += "\n=== User memory (durable facts about your user & machine) ===\n" + "\n".join(
            f"- {'📌 ' if m.get('pinned') else ''}{m['content']}" for m in ctx["memories"]) + \
            "\n=== end user memory ===\n"
    if ctx.get("session"):
        out += "\n=== Session memory (context of THIS conversation) ===\n" + "\n".join(
            f"- {m['content']}" for m in ctx["session"]) + "\n=== end session memory ===\n"
    if ctx.get("facts"):
        out += ("\n=== Knowledge graph highlights (query more with kg_query) ===\n"
                + "\n".join(f"- {f}" for f in ctx["facts"]) + "\n=== end knowledge graph ===\n")
    return out


async def tool(cfg: dict, store, name: str, **kw) -> str:
    """remember / recall / forget / kg_add / kg_query / update_soul on a Zero: the same
    words a local call answers with, the work done on the hub."""
    await move_local(cfg, store)
    hub = (hub_link(cfg) or {}).get("label") or "the hub"
    if name == "update_soul":
        r = await ask(cfg, "soul_set", content=kw.get("content") or "")
        return f"[error] {r['error']}" if not r.get("ok") else f"soul updated on {hub}"
    r = await ask(cfg, name, **kw)
    if not r.get("ok"):
        return f"[error] {r['error']}"
    if name == "remember":
        return f"remembered ({r.get('scope', 'user')} memory, on {hub}, id {r['id']})"
    if name == "recall":
        rows = r.get("memories") or []
        return "\n".join(
            f"- [{m['id']}|{m.get('scope', 'user')}] "
            f"{time.strftime('%Y-%m-%d', time.localtime(m.get('created_at') or 0))}: {m['content']}"
            for m in rows) or "(no memories found)"
    if name == "forget":
        return f"forgotten (id {kw.get('id')}, on {hub})"
    if name == "kg_add":
        return (f"added to knowledge graph on {hub}: {kw.get('subject')} —{kw.get('relation')}→ "
                f"{kw.get('object')} (edge {r['id']})")
    return "\n".join(r.get("facts") or []) or "(knowledge graph has no matching facts)"


async def move_local(cfg: dict, store) -> dict | None:
    """What this machine knew before it was set up to run on its hub goes to its section,
    once: its memories, its facts and its soul. The local rows are left where they are
    and not read again. Returns the hub's answer the time it happens."""
    z = cfg.get("zero") if isinstance(cfg.get("zero"), dict) else {}
    if not z or z.get("moved") or not on_hub(cfg):
        return None
    async with _move_lock():
        if z.get("moved"):
            return None
        from . import config as cfgmod
        mems = [{"content": m["content"], "pinned": m.get("pinned")}
                for m in store.search_memories("", limit=MAX_IMPORT, scope="user")]
        facts = [tuple(x.strip() for x in _split_fact(f)) for f in store.kg_query("", limit=MAX_IMPORT)]
        facts = [f for f in facts if len(f) == 3]
        sp = Path(cfgmod.soul_path())
        soul = sp.read_text() if sp.exists() else ""
        r = await ask(cfg, "import", memories=mems, facts=facts, soul=soul)
        if r.get("ok"):
            z["moved"] = time.time()
            cfg["zero"] = z
            try:
                cfgmod.save_config(cfg)
            except Exception:
                pass
            return r
        return None


def _split_fact(line: str) -> list[str]:
    s, _, rest = line.partition(" —")
    r, _, o = rest.partition("→ ")
    return [s, r, o] if s and r and o else []


_LOCKS: dict[str, asyncio.Lock] = {}


def _move_lock() -> asyncio.Lock:
    k = _key()
    if k not in _LOCKS:
        _LOCKS[k] = asyncio.Lock()
    return _LOCKS[k]
