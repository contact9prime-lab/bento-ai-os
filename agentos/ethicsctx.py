"""The ethics context: flags a conversation collects, and the score they add up to.

Asked for as "the context has to be built up with ethical flags and scores, and the score is
something that overall in the context would become high". One step is judged on its own by
ethics.py; this module remembers what each step and each request said, so a conversation that
keeps circling harm is treated differently from one that touched it once.

- **A flag is a row** (`ethics_flags`, in the person's own database): when, which conversation or
  root run, who, what kind, its weight, its MIT category, the words that raised it and where the
  rule came from. Rows are kept for the report; the score reads the last `WINDOW_S`.
- **The score is a sum** of the weights in the window, per conversation (or per mission run, which
  has none), and per account. Plain arithmetic over rows, so the same history always gives the
  same number and the ledger shows every part of it.
- **Thresholds act in the gate** (policy.decide): from `WATCH` the independent evaluator reads
  outward and risky steps; from `CAUTION` every risky step is typed to confirm; from `HOLD` no
  risky step runs in that conversation, reading still works. The account's own thresholds are
  `ACCOUNT_X` times higher, so opening a new chat is not a way round.
- **Whose words are the purpose** (`PURPOSE`, a contextvar set by the agent loop): the person's
  message, or a mission's text, from the OUTERMOST turn. A specialist's task is the lead's words,
  so it inherits the person's: a target the lead made up does not become "named" by being handed on.
- **Clearing is a person's act** (`clear`): a typed phrase, a ledger row, and the rows stay in the
  report. It lowers the conversation's score, never the account's.

This file is a SECURITY_MODULE. No model is asked here.
"""
from __future__ import annotations

import contextvars
import hashlib
import ipaddress
import re
import time
from urllib.parse import urlsplit

WATCH, CAUTION, HOLD = 4, 10, 20
ACCOUNT_X = 3
WINDOW_S = 24 * 3600

# What each kind of flag adds. A verdict's rule is its kind; the rest are named here.
WEIGHTS = {"wreck": 6, "attack": 5, "range": 5, "credentials": 4, "leak": 5, "untraced": 3,
           "history": 2, "unread": 2, "own": 1, "again": 3, "secret_read": 1,
           "eval_concern": 4, "eval_harm": 8}
KIND_WORDS = {"wreck": "tried to wipe the machine", "attack": "pointed an attack tool at someone else's machine",
              "range": "tried to scan a range of addresses", "credentials": "tried to dump saved passwords",
              "leak": "sent something out after reading a secret", "untraced": "acted on a target nobody named",
              "history": "tried to rewrite shared history", "unread": "a destructive step Bento couldn't read",
              "own": "deleted a lot of your own files", "again": "tried another way after a refusal",
              "secret_read": "read a secret (a key or a password file)", "mention": "the request mentioned this",
              "eval_concern": "the ethics reviewer had a concern", "eval_harm": "the ethics reviewer saw harm"}
CATEGORY_OF = {"wreck": "5.1", "attack": "4.2", "range": "4.2", "credentials": "2.1", "leak": "2.1",
               "untraced": "7.1", "history": "5.1", "unread": "5.1", "own": "5.1", "again": "7.1",
               "secret_read": "2.1"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ethics_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    ctx TEXT DEFAULT '',            -- the conversation, or the root run of a mission
    principal TEXT DEFAULT '',
    kind TEXT DEFAULT '',
    weight INTEGER DEFAULT 0,
    category TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    source TEXT DEFAULT '',         -- attack | atlas | bento | gate | evaluator
    ref TEXT DEFAULT '',
    cleared_at REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ethics_flags_ctx ON ethics_flags(ctx, ts);
CREATE INDEX IF NOT EXISTS ethics_flags_ts ON ethics_flags(ts);
"""

PURPOSE: contextvars.ContextVar = contextvars.ContextVar("ethics_purpose", default=None)


# --- the purpose of a turn ----------------------------------------------------------------

_HOST = re.compile(r"(?<![\w.@-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62})(?![\w-])", re.I)
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", re.I)
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def named(text: str) -> set[str]:
    """Every host, domain, address and email domain a piece of text names, lower case."""
    t = str(text or "")
    out = set()
    for m in re.finditer(r"https?://[^\s'\"<>]+", t):
        h = urlsplit(m.group(0)).hostname
        if h:
            out.add(h.lower())
    out |= {m.group(1).lower() for m in _HOST.finditer(t)}
    out |= {m.group(1).lower() for m in _EMAIL.finditer(t)}
    out |= {m.group(0) for m in _IP.finditer(t)}
    return out


def enter(person: str, conv: str = "", root: str = "") -> contextvars.Token | None:
    """Open a turn's purpose unless an outer turn already has one (the outermost words count)."""
    if PURPOSE.get() is not None:
        return None
    text = str(person or "")[:8000]
    return PURPOSE.set({"person": text, "named": named(text), "ctx": conv or root or "",
                        "conv": conv or "", "root": root or ""})


def leave(tok) -> None:
    if tok is not None:
        PURPOSE.reset(tok)


def purpose() -> dict | None:
    return PURPOSE.get()


def traced(host: str) -> bool:
    """Did the person's words name this host (or a domain it is under)?"""
    p = PURPOSE.get()
    if not p:
        return True              # nothing to trace against (an app's call, a test): not judged here
    h = str(host or "").lower().strip("[]").rstrip(".")
    if not h:
        return True
    for n in p.get("named") or ():
        if h == n or h.endswith("." + n):
            return True
    try:
        ipaddress.ip_address(h)
        return h in (p.get("named") or ())
    except ValueError:
        return False


def key_of(ctx: dict | None = None) -> str:
    p = PURPOSE.get()
    if p and p.get("ctx"):
        return p["ctx"]
    ctx = ctx or {}
    return str(ctx.get("conversation_id") or ctx.get("run_id") or "")


# --- flags and the score ----------------------------------------------------------------

def _db(store):
    db = getattr(store, "db", None)
    if db is None:
        return None
    try:
        db.executescript(SCHEMA) if not getattr(store, "_ethics_ready", False) else None
        store._ethics_ready = True
    except Exception:
        return None
    return db


def flag(store, ctx: str, kind: str, detail: str = "", weight: int | None = None,
         category: str = "", source: str = "gate", ref: str = "", principal: str = "") -> None:
    db = _db(store)
    if db is None:
        return
    w = WEIGHTS.get(kind, 0) if weight is None else int(weight)
    try:
        db.execute("INSERT INTO ethics_flags (ts, ctx, principal, kind, weight, category, detail, source, ref)"
                   " VALUES (?,?,?,?,?,?,?,?,?)",
                   (time.time(), ctx or "", principal[:80], kind[:40], w,
                    category or CATEGORY_OF.get(kind, ""), str(detail)[:400], source[:20], str(ref)[:40]))
        db.commit()
    except Exception:
        pass


def note_request(store, ctx: str, text: str, principal: str = "") -> list[dict]:
    """Flag what the library recognises in a person's (or a task's) words, once per phrase per
    conversation in the window. Returns what was new."""
    from . import ethicslib
    found = ethicslib.mentions(text)
    db = _db(store)
    if not found or db is None:
        return []
    new = []
    since = time.time() - WINDOW_S
    for m in found:
        ref = hashlib.sha1(m["phrase"].encode()).hexdigest()[:12]
        try:
            seen = db.execute("SELECT 1 FROM ethics_flags WHERE ctx=? AND kind='mention' AND ref=? AND ts>?",
                              (ctx or "", ref, since)).fetchone()
        except Exception:
            seen = None
        if seen:
            continue
        title = m.get("title") or ""
        said = f"“{m['phrase']}”" + (f" ({title})" if title and title.lower() != m["phrase"].lower() else "")
        flag(store, ctx, "mention", said, weight=m["weight"],
             category=m["category"], source=m["source"], ref=ref, principal=principal)
        new.append(m)
    return new


def score(store, ctx: str = "", account: bool = False) -> int:
    db = _db(store)
    if db is None:
        return 0
    since = time.time() - WINDOW_S
    try:
        if account:
            row = db.execute("SELECT COALESCE(SUM(weight),0) FROM ethics_flags WHERE ts>?", (since,)).fetchone()
        else:
            if not ctx:
                return 0
            row = db.execute("SELECT COALESCE(SUM(weight),0) FROM ethics_flags WHERE ctx=? AND ts>? AND cleared_at=0",
                             (ctx, since)).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


def level(sc: int, account: bool = False) -> str:
    x = ACCOUNT_X if account else 1
    return "hold" if sc >= HOLD * x else "caution" if sc >= CAUTION * x else "watch" if sc >= WATCH * x else "ok"


_ORDER = {"ok": 0, "watch": 1, "caution": 2, "hold": 3}


def state(store, ctx: str = "", flags: bool = False) -> dict:
    """The conversation's score and level, the account's, and which one decides."""
    sc, acc = score(store, ctx), score(store, account=True)
    lc, la = level(sc), level(acc, account=True)
    lv = lc if _ORDER[lc] >= _ORDER[la] else la
    return {"score": sc, "level": lv, "conversation_level": lc, "account": acc, "account_level": la,
            "by": "account" if lv != lc else "conversation",
            "flags": recent(store, ctx=ctx, limit=8) if (flags and ctx) else [],
            "thresholds": {"watch": WATCH, "caution": CAUTION, "hold": HOLD, "account_x": ACCOUNT_X}}


def has_recent(store, ctx: str, kind: str, within: float = 3600) -> bool:
    db = _db(store)
    if db is None or not ctx:
        return False
    try:
        return bool(db.execute("SELECT 1 FROM ethics_flags WHERE ctx=? AND kind=? AND ts>? AND cleared_at=0",
                               (ctx, kind, time.time() - within)).fetchone())
    except Exception:
        return False


def recent(store, ctx: str = "", limit: int = 30, days: float = 7) -> list[dict]:
    db = _db(store)
    if db is None:
        return []
    q = ("SELECT id, ts, ctx, principal, kind, weight, category, detail, source, ref, cleared_at FROM ethics_flags"
         " WHERE ts>?" + (" AND ctx=?" if ctx else "") + " ORDER BY id DESC LIMIT ?")
    args = [time.time() - days * 86400] + ([ctx] if ctx else []) + [int(limit)]
    try:
        rows = db.execute(q, args).fetchall()
    except Exception:
        return []
    from . import ethicslib
    cats = ethicslib.CATEGORIES
    out = []
    for r in rows:
        d = dict(zip(("id", "ts", "ctx", "principal", "kind", "weight", "category", "detail", "source",
                      "ref", "cleared_at"), r))
        d["words"] = KIND_WORDS.get(d["kind"], d["kind"])
        d["category_words"] = cats.get(d["category"], "")
        out.append(d)
    return out


def clear(store, ctx: str) -> int:
    """A person reviewed the flags: they stop counting for the conversation (never the account)."""
    db = _db(store)
    if db is None or not ctx:
        return 0
    try:
        n = db.execute("UPDATE ethics_flags SET cleared_at=? WHERE ctx=? AND cleared_at=0",
                       (time.time(), ctx)).rowcount
        db.commit()
        return n
    except Exception:
        return 0


def report(store, days: float = 7) -> dict:
    """What the week looked like: counts by kind and category, and the conversations that rose."""
    rows = recent(store, limit=5000, days=days)
    by_kind: dict = {}
    by_cat: dict = {}
    by_ctx: dict = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        if r["category"]:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["weight"]
        c = by_ctx.setdefault(r["ctx"] or "(no conversation)", {"ctx": r["ctx"], "score": 0, "flags": 0,
                                                                  "last": 0, "cleared": False})
        c["score"] += r["weight"]
        c["flags"] += 1
        c["last"] = max(c["last"], r["ts"])
        c["cleared"] = c["cleared"] or bool(r["cleared_at"])
    from . import ethicslib
    top = sorted(by_ctx.values(), key=lambda c: -c["score"])[:10]
    for c in top:
        c["level"] = level(c["score"])
    return {"days": days, "flags": len(rows), "by_kind": by_kind,
            "by_category": [{"id": k, "words": ethicslib.CATEGORIES.get(k, k), "weight": v}
                            for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
            "conversations": top, "account": score(store, account=True),
            "account_level": level(score(store, account=True), account=True)}


def hold_words(st: dict) -> str:
    acct = st.get("by") == "account"
    n = st.get("account") if acct else st.get("score")
    return (f"Bento's ethics check: this {'account' if acct else 'conversation'} has an ethics score of {n}, "
            f"past the hold line, so no risky step runs. Reading still works. A person can review the "
            f"flags in Settings → Permissions → Ethics.")
