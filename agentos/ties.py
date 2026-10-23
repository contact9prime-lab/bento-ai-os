"""Every tie this machine has with another one, for the Network tab and the device map:
the Zeros it set up, the teams it linked with, and whether each one is answering.

Asked for as "in network we should not only show the devices that are zero connected but
also the teams connection", "the map should show teams and zero as well, with the
indication and management of both", "a filtered view of KB, memory, sessions and logs for
the Pi and other Zeros and teams", and "what agent it has access to and what executors it
can execute on". Four rules:

  * A tie is a link (teamlink.py), never a second record. Its kind is read: a machine this
    hub set up to run its work here is a Zero (zero.ships_to), another account here is an
    account, anything else a team. A community-only link is plumbing and is left out.
  * Answering is asked, not assumed (`probe`, the link's own `hello` over its pinned
    certificate), at most once every PROBE_TTL per link, all at once, never on a paint.
  * A link a reinstall left behind is named stale: another link to the same machine name
    and address was made after it. Removing it is the person's, one tap.
  * The filtered views (`view`) read only that tie's rows: a Zero's section EXACTLY
    (Store.only), a team's conversations and its principal's ledger rows. Read-only.

Free of HTTP: the server routes and `bento network ties` call into it.
"""
from __future__ import annotations

import asyncio
import json
import time

PROBE_TTL = 30           # seconds an answer to "are you there?" is kept
PROBE_TIMEOUT = 4        # seconds one probe may take
WATCH_TIMEOUT = 50       # the same, from the minute watch: time to look for a machine that moved
VIEWS = ("sessions", "schedules", "memory", "knowledge", "logs")
VIEW_ROWS = 60

_PROBED: dict[str, tuple[float, bool, str]] = {}
_VERSION: dict[str, str] = {}      # what each tie said it runs, at its last hello


def host_of(lk: dict) -> str:
    """The address a machine link reaches: its `host`, else the host part of its `url`."""
    if lk.get("host"):
        return str(lk["host"])
    url = str(lk.get("url") or "")
    if "://" in url:
        url = url.split("://", 1)[1]
    url = url.split("/", 1)[0]
    if url.startswith("["):
        return url[1:].split("]", 1)[0]
    return url.rsplit(":", 1)[0] if url.count(":") == 1 else url


def kind_of(lk: dict) -> str:
    from . import zero as zeromod
    if lk.get("kind") == "account":
        return "account"
    if zeromod.ships_to(lk):
        return "zero"
    return "team"


def _stale(lk: dict, all_links: list[dict]) -> bool:
    """A newer link to the same machine (same name, same address): this one was left by a
    reinstall, and the machine at that address no longer holds its certificate."""
    if lk.get("kind") != "machine":
        return False
    me = (str(lk.get("peer_name") or ""), host_of(lk))
    # by its network card too: a reinstalled Pi that DHCP then gave another address is the same
    # machine, at a new address, holding only the newer link's certificate
    mac = str(lk.get("mac") or "")
    return any(o is not lk and o.get("kind") == "machine"
               and ((str(o.get("peer_name") or ""), host_of(o)) == me
                    or (mac and str(o.get("mac") or "") == mac and str(o.get("peer_name") or "") == me[0]))
               and float(o.get("created") or 0) > float(lk.get("created") or 0)
               for o in all_links)


def ties(owner: str | None = None) -> list[dict]:
    """Every tie, newest first: what the screens draw. `owner` None is every account's
    (an admin's view of the machine); a uid is that account's own."""
    from . import provision, teamlink
    links = [lk for lk in teamlink.links(owner) if lk.get("kind") in ("machine", "account")]
    enabled = provision.load().get("enabled") or {}
    out = []
    for lk in links:
        e = enabled.get(str(lk.get("peer_host_fp") or "")) or {}
        pr = _PROBED.get(lk.get("id") or "")
        brain = lk.get("brain") if isinstance(lk.get("brain"), dict) else {}
        out.append({
            "label": lk.get("label") or "", "id": lk.get("id") or "", "kind": kind_of(lk),
            "peer": lk.get("peer_name") or lk.get("label") or "", "owner": lk.get("owner") or "",
            "addr": host_of(lk) if lk.get("kind") == "machine" else "",
            "fp": lk.get("peer_host_fp") or "", "created": lk.get("created") or 0,
            "stale": _stale(lk, links), "pass": bool(lk.get("pass")),
            "answering": pr[1] if pr else None, "checked": pr[0] if pr else 0,
            "why": pr[2] if pr else "", "space": e.get("space") or "",
            "brain": {"executor": str(brain.get("executor") or ""), "model": str(brain.get("model") or "")},
            "version": _VERSION.get(lk.get("id") or "", ""),
            "behind": behind(_VERSION.get(lk.get("id") or "", "")),
            "moved": (lk.get("moved") or [])[-1] if lk.get("moved") else None,
            "talks_to": target_of(lk),
        })
    out.sort(key=lambda t: (t["stale"], -float(t["created"] or 0)))
    return out


async def probe(lks: list[dict], force: bool = False, wait: float = PROBE_TIMEOUT) -> None:
    """Ask each machine link whether it is there, all at once. An account link is always
    there (same machine). Kept PROBE_TTL seconds. A screen waits PROBE_TIMEOUT; the minute
    watch waits WATCH_TIMEOUT, because a machine that moved is looked for inside the call
    (teamlink.relocate) and cut off at five seconds it was never found by looking."""
    from . import teamlink
    now = time.time()

    async def one(lk):
        key = lk.get("id") or ""
        if not force and key in _PROBED and now - _PROBED[key][0] < PROBE_TTL:
            return
        if lk.get("kind") != "machine":
            _PROBED[key] = (now, True, "")
            return
        try:
            got = await asyncio.wait_for(teamlink.call(lk, {"op": "hello"}, timeout=PROBE_TIMEOUT),
                                         wait + 1)
            ok = bool(got.get("ok"))
            why = "" if ok else teamlink.plain(got.get("error") or "no answer", 120, newlines=False)
            if ok:
                # a hello with no version is a Bento from before versions were said: behind, and
                # never the value an earlier answer left here
                _VERSION[key] = teamlink.plain(got.get("version") or OLDER, 20, newlines=False).strip()
        except Exception as e:      # an answer is a sentence, never a traceback
            ok, why = False, _why(e)
        _PROBED[key] = (time.time(), ok, why)
    await asyncio.gather(*(one(lk) for lk in lks))


def _why(e: Exception) -> str:
    s = f"{type(e).__name__}: {e}".lower()
    if "certificate" in s or "ssl" in s:
        return "it answers with another certificate (reinstalled, so this link is old)"
    if "refused" in s:
        return "nothing is listening there"
    if "timeout" in s or "timed out" in s:
        return "no answer in time"
    return str(e)[:120] or type(e).__name__


# ---- keeping the Zeros current ------------------------------------------------------------
#
# Asked for as "if Bento is updated, ask the hub to update the Pi, or the Pi checks and asks".
# A Zero this hub set up updates ITSELF when its hub asks over the link (wire op zero_update,
# answered only for its own hub): no SSH, no password. What happens after the hub itself updates
# is `provision.zero_updates`: "ask" (the default: a toast with Update), "auto", or "off".

UPDATE_MODES = ("ask", "auto", "off")
OLDER = "< 0.6.88"               # what a Zero that says no version runs


def _vt(v: str) -> tuple:
    out = []
    for p in str(v or "").split("."):
        try:
            out.append(int("".join(ch for ch in p if ch.isdigit()) or 0))
        except ValueError:
            out.append(0)
    return tuple(out)


def behind(version: str) -> bool:
    """Is a machine on `version` behind this one? Unknown is not behind."""
    from . import __version__
    if version == OLDER:
        return True
    return bool(version) and _vt(version) < _vt(__version__)


def update_mode(cfg: dict) -> str:
    m = str(((cfg or {}).get("provision") or {}).get("zero_updates") or "ask")
    return m if m in UPDATE_MODES else "ask"


async def ask_update(lk: dict) -> dict:
    """Ask a Zero this hub set up to update itself. It answers at once and works after."""
    from . import teamlink
    from . import zero as zeromod
    if not zeromod.ships_to(lk):
        return {"ok": False, "error": "only a machine this hub set up updates when it asks"}
    # Ask what it runs first. Already on this hub's version, there is nothing to install: it used
    # to be asked anyway, found nothing, did not restart, and the button said "updating" for good.
    await probe([lk], force=True, wait=PROBE_TIMEOUT)
    have = _VERSION.get(lk.get("id") or "", "")
    if have and have != OLDER and not behind(have):
        return {"ok": True, "current": True, "version": have,
                "said": f"{lk.get('label')} is already on {have}, the same as this hub"}
    try:
        got = await teamlink.call(lk, {"op": "zero_update"}, timeout=30)
    except Exception as e:
        got = {"ok": False, "error": _why(e)}
    if not got.get("ok") and "unknown request" in str(got.get("error") or ""):
        got["error"] = ("it runs a Bento older than 0.6.88, which can't be asked over the link: "
                        "update it once with Controls → Update (or bento network update)")
    return got


async def faces_remote(lk: dict, change: dict) -> dict:
    """Read (no change) or change a Zero's screen faces, over its link (wire op zero_face)."""
    from . import teamlink
    from . import zero as zeromod
    if not zeromod.ships_to(lk):
        return {"ok": False, "error": "only a machine this hub set up takes its screen from here"}
    try:
        got = await teamlink.call(lk, {"op": "zero_face", **change}, timeout=20)
    except Exception as e:
        got = {"ok": False, "error": _why(e)}
    if not got.get("ok") and "unknown request" in str(got.get("error") or ""):
        got["error"] = "it runs a Bento older than 0.6.90: update it first, then its screen can be changed from here"
    return got


# ---- what it runs on here -------------------------------------------------------------

def brain_for(cfg: dict, lk: dict) -> tuple[str, str, dict]:
    """(engine, model, cfg) a tie's work runs on here. A link may name one of this
    machine's brains (Network → the tie → Runs on); one that is no longer installed or
    enabled falls back to the machine's, as resolve_engine does for the machine itself."""
    from . import executors as execmod
    b = lk.get("brain") if isinstance(lk.get("brain"), dict) else {}
    ex, model = str(b.get("executor") or ""), str(b.get("model") or "")
    if ex and ex != "aria" and ex in execmod.ENGINES and execmod.drives(ex) \
            and execmod.probe(ex).get("installed"):
        c = dict(cfg)
        if model:
            key = ex.replace("-", "_")
            c["executors"] = {**(cfg.get("executors") or {}),
                              key: {**((cfg.get("executors") or {}).get(key) or {}), "model": model}}
        return ex, model, c
    if ex == "aria" and model and "/" in model:
        prov = model.split("/", 1)[0]
        p = (cfg.get("providers") or {}).get(prov) or {}
        if prov == "ollama" or p.get("enabled", True):
            return "aria", model, {**cfg, "engine": "aria", "default_model": model}
    eng = execmod.resolve_engine(cfg)
    return eng, cfg.get("default_model") or "", cfg


def set_brain(owner: str, label: str, executor: str, model: str) -> dict:
    """Write which brain a tie's work runs on here ('' = the machine's own)."""
    from . import teamlink
    from . import executors as execmod
    executor, model = str(executor or "").strip(), str(model or "").strip()[:120]
    if executor and executor != "aria" and executor not in execmod.ENGINES:
        raise ValueError(f"'{executor}' is not a brain this machine knows")
    if executor == "aria" and model and "/" not in model:
        raise ValueError("choose a model from the list")
    d = teamlink._load()
    lk = next((x for x in d["links"] if (x.get("owner") or "") == (owner or "")
               and x.get("label") == label), None)
    if not lk:
        raise LookupError(f"no link called '{label}'")
    if executor:
        lk["brain"] = {"executor": executor, "model": model}
    else:
        lk.pop("brain", None)
    teamlink._save(d)
    return lk.get("brain") or {"executor": "", "model": ""}


# ---- who it talks to ------------------------------------------------------------------
#
# Asked for as "the Zeros or the teams can talk to either Aria, which controls all the
# departments, or they can talk to each department only … better restrict". A link says who
# answers it here: the lead (everything the lead can reach: every company, department and
# specialist), or ONE department of one company, whose desk does the work with its own people,
# the company's persona and its sign-offs. Stored on the link (`talks_to`), like its brain.
# A link that says nothing talks to the lead, as every link did before, and every screen that
# shows it says what that hands over (topology.access).

def target_of(lk: dict) -> dict:
    t = lk.get("talks_to") if isinstance(lk.get("talks_to"), dict) else {}
    if t.get("to") == "department" and t.get("department"):
        return {"to": "department", "company": str(t.get("company") or ""),
                "department": str(t["department"])}
    return {"to": "lead"}


def set_target(owner: str, label: str, target: dict, cfg: dict, store) -> dict:
    """Write who a tie talks to. A department must exist in that company now, and have a desk:
    a link pointed at nothing would refuse every question with no way to see why."""
    from . import company as companymod
    from . import teamlink
    t = target if isinstance(target, dict) else {}
    want = {"to": "lead"}
    if t.get("to") == "department":
        cid, dname = str(t.get("company") or "").strip().lower(), str(t.get("department") or "").strip()
        if companymod.cfg_of(cfg, cid) is None:
            raise ValueError("you keep no company by that id")
        d = next((x for x in companymod.departments_of(cfg, store, cid)
                  if x["name"].lower() == dname.lower()), None)
        if not d:
            raise ValueError(f"no department called '{dname}' in that company")
        if not d.get("desk"):
            raise ValueError(f"{d['name']} has no desk yet: set the company up again from the Company panel")
        want = {"to": "department", "company": cid, "department": d["name"]}
    elif t.get("to") not in (None, "", "lead"):
        raise ValueError("a link talks to your lead agent or to one department")
    d_ = teamlink._load()
    lk = next((x for x in d_["links"] if (x.get("owner") or "") == (owner or "")
               and x.get("label") == label), None)
    if not lk:
        raise LookupError(f"no link called '{label}'")
    if want["to"] == "lead":
        lk.pop("talks_to", None)
    else:
        lk["talks_to"] = want
    teamlink._save(d_)
    return target_of(lk)


def target_words(cfg: dict, t: dict) -> str:
    from . import company as companymod
    if t.get("to") != "department":
        return (cfg or {}).get("agent_name") or "Aria"
    c = companymod.cfg_of(cfg, t.get("company") or "")
    name = companymod.profile(c).get("name") if c is not None else ""
    return f"{t['department']}" + (f" at {name}" if name else "")


# ---- whose it is -----------------------------------------------------------------------

def adopt(label: str, uid: str) -> dict:
    """Move a tie the MACHINE owns (made from a terminal, no account named) to an account.
    Its agents, memory and the conversations held for it here then belong to that person;
    what was kept for it under the machine stays there and the answer says so."""
    from . import provision, teamlink
    d = teamlink._load()
    lk = next((x for x in d["links"] if not (x.get("owner") or "") and x.get("label") == label), None)
    if not lk:
        raise LookupError(f"no link called '{label}' belongs to the machine")
    if any((x.get("owner") or "") == uid and x.get("label") == label for x in d["links"]):
        raise ValueError(f"you already have a link called '{label}'")
    lk["owner"] = uid
    teamlink._save(d)
    pd = provision.load()
    e = (pd.get("enabled") or {}).get(str(lk.get("peer_host_fp") or ""))
    moved_space = ""
    if e is not None:
        e["owner"] = uid
        moved_space = e.pop("space", "") or ""
        provision.save(pd)
    return {"ok": True, "label": label, "owner": uid, "left_behind": bool(moved_space)}


# ---- the filtered views ---------------------------------------------------------------

def _q(store, sql: str, args: tuple) -> list[dict]:
    return [dict(r) for r in store.db.execute(sql, args).fetchall()]


def view(store, tie: dict, what: str, limit: int = VIEW_ROWS) -> dict:
    """One tie's own rows, read-only. A Zero is its section here, exactly; a team is the
    conversations its questions made and its agents' ledger rows."""
    if what not in VIEWS:
        raise ValueError(f"choose one of: {', '.join(VIEWS)}")
    label, sid, kind = tie["label"], tie.get("space") or "", tie["kind"]
    if what == "sessions":
        if sid:
            rows = _q(store, "SELECT id,title,origin,updated_at FROM conversations WHERE space_id=? "
                             "ORDER BY updated_at DESC LIMIT ?", (sid, limit))
        else:
            rows = _q(store, "SELECT id,title,origin,updated_at FROM conversations WHERE origin='team' "
                             "AND title LIKE ? ORDER BY updated_at DESC LIMIT ?", (f"↔ {label}:%", limit))
        for r in rows:
            n = store.db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (r["id"],)).fetchone()
            r["messages"] = n[0] if n else 0
        return {"what": what, "rows": rows}
    if what == "schedules":
        # what a Zero asked for at its screen, run here as its chat runs (scheduler.zero_job)
        if not sid:
            return {"what": what, "rows": [], "note": "A linked team keeps its schedules on its own machine."}
        rows = _q(store, "SELECT id, prompt, schedule_type, at_time, interval_seconds, weekday, next_run, last_run, "
                         "last_result, enabled FROM tasks WHERE space_id=? ORDER BY created_at DESC LIMIT ?", (sid, limit))
        return {"what": what, "rows": rows, "note": "" if rows else
                "Nothing scheduled yet. Ask at its screen, like “every morning at 8, tell me the weather”."}
    if what in ("memory", "knowledge") and not sid:
        return {"what": what, "rows": [], "note": (
            "A linked team keeps its own memory on its own machine. Only a Zero this machine set up "
            "keeps its memory here." if kind != "zero" else
            "This Zero hasn't kept anything here yet.")}
    if what == "memory":
        rows = store.search_memories("", limit=limit, space=store.only(sid))
        return {"what": what, "rows": [{"id": m.get("id"), "content": m.get("content"),
                                        "scope": m.get("scope"), "pinned": m.get("pinned"),
                                        "created_at": m.get("created_at")} for m in rows]}
    if what == "knowledge":
        g = store.kg_graph(space=store.only(sid))
        names = {n["id"]: n.get("name") for n in g["nodes"]}
        return {"what": what, "rows": [{"subject": names.get(e["src"], "?"), "relation": e.get("relation") or e.get("rel") or "",
                                        "object": names.get(e["dst"], "?")} for e in g["edges"][:limit]]}
    # logs: the diary's lines for its conversations or section, and its principal's ledger rows
    logs = _q(store, "SELECT kind,message,created_at FROM logs WHERE "
                     + ("COALESCE(space_id,'')=? OR " if sid else "")
                     + "meta LIKE ? ORDER BY created_at DESC LIMIT ?",
              ((sid,) if sid else ()) + (f'%"zero": {json.dumps(label)}%', limit))
    led = _q(store, "SELECT ts AS created_at, action, resource, effect, reason FROM audit WHERE "
                    "principal_kind IN ('team','pool') AND principal_id LIKE ? ORDER BY ts DESC LIMIT ?",
             (f"{label}/%", limit))
    rows = [{"kind": r["kind"], "text": r["message"], "at": r["created_at"]} for r in logs] + \
           [{"kind": "ledger", "text": f"{r['action']} {r['resource']}: {r['effect']}"
             + (f" ({r['reason']})" if r.get("reason") else ""), "at": r["created_at"]} for r in led]
    rows.sort(key=lambda r: -float(r["at"] or 0))
    return {"what": what, "rows": rows[:limit]}
