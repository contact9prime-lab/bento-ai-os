"""What a turn cost, and whether we are entitled to say.

Token counts were not lost before this module: each turn wrote them into its
`turn` log entry, and `/api/analytics/tokens` re-derives totals by parsing the
JSON meta of the last 1000 of those rows. What that cannot do is answer the
question anyone running a cloud model actually asks — *what did today cost me?* —
or group by anything the log line does not carry. Money was never recorded at
all, the 1000-row ceiling silently truncates history, and "which surface is
expensive" and "what has this space cost" have no answer in that shape.

So spend gets its own table. The old endpoint keeps working and keeps its longer
tail of history; new questions are answered from here.

Two rules shape this module.

**Tokens are a fact; money is an estimate.** Token counts come from the provider.
Prices do not: they live in a table that goes stale the week after it is written,
and a wrong number stated confidently is worse than no number. So an unpriced
model records `cost_usd = NULL` and every report says how many rows were
unpriced, rather than folding them in as zero. A local model genuinely costs
nothing per token, and that is why it is priced at 0 explicitly instead of being
left unpriced — "free" and "unknown" are different answers.

**Prices are the user's to set.** The shipped table is a starting point, editable
in `cfg["pricing"]`, matched by fnmatch so `anthropic/*` can be given one price
without listing every model. Nothing here ranks models or picks one; it only
reports.
"""

from __future__ import annotations

import contextvars
import fnmatch
import time

# USD per million tokens, (input, output). Patterns are matched in order, most
# specific first. These are a convenience, not an authority: refreshed with the model
# catalogue (modelcatalog.CHECKED, 2026-11-15) from the providers' own pricing, and
# providers change them without telling us. Override in Settings.
DEFAULT_PRICING: list[tuple[str, tuple[float, float]]] = [
    ("ollama/*", (0.0, 0.0)),          # local: the electricity is not billed per token
    ("lmstudio/*", (0.0, 0.0)),
    ("*claude-fable-5[-.]2*", (8.0, 40.0)),
    ("*claude-fable*", (10.0, 50.0)),
    ("*claude-opus-5[-.]5*", (4.0, 20.0)),
    ("*claude-opus-5*", (5.0, 25.0)),
    ("*claude-sonnet-5*", (2.0, 10.0)),
    ("*claude-haiku-5*", (0.10, 0.50)),     # "from": its base rate
    ("*gpt-6-astra*", (10.0, 50.0)),
    ("*gpt-6.1-sol*", (2.0, 10.0)),
    ("*gpt-6.1-terra*", (1.0, 5.0)),
    ("*gpt-6-sol*", (2.0, 10.0)),
    ("*gpt-6-luna*", (0.10, 0.50)),
    ("*gpt-5.6-sol*", (5.0, 30.0)),
    ("*gpt-5.6-terra*", (2.5, 15.0)),
    ("*gpt-5.6-luna*", (1.0, 6.0)),
    # DeepSeek bills half of this off-peak; the peak rate is shipped so the estimate is never low
    ("*deepseek*flash*", (0.30, 1.20)),
    ("*deepseek-v4-pro*", (1.32, 3.96)),
    ("*claude-opus*", (15.0, 75.0)),
    ("*claude-sonnet*", (3.0, 15.0)),
    ("*claude-haiku*", (1.0, 5.0)),
    ("*gpt-5*", (1.25, 10.0)),
    ("*gpt-4o-mini*", (0.15, 0.6)),
    ("*gpt-4o*", (2.5, 10.0)),
    ("*gemini*flash-lite*", (0.10, 0.40)),
    ("*gemini*flash*", (0.30, 2.50)),
    ("*gemini*pro*", (1.25, 10.0)),
]


def pricing(cfg: dict) -> list[tuple[str, tuple[float, float]]]:
    """User pricing first, then the shipped table. A user pattern always wins,
    including one that deliberately un-prices a model."""
    user = []
    for pat, v in (cfg.get("pricing") or {}).items():
        try:
            if isinstance(v, dict):
                user.append((str(pat), (float(v.get("in", 0)), float(v.get("out", 0)))))
            elif isinstance(v, (list, tuple)) and len(v) == 2:
                user.append((str(pat), (float(v[0]), float(v[1]))))
        except (TypeError, ValueError):
            continue
    return user + DEFAULT_PRICING


def price_of(cfg: dict, model: str) -> tuple[float, float] | None:
    """(input, output) USD per million tokens, or None if this model is unpriced."""
    m = (model or "").lower()
    if not m:
        return None
    for pat, rate in pricing(cfg):
        if fnmatch.fnmatchcase(m, pat.lower()):
            return rate
    return None


# ---------------------------------------------------------------------------
# A price is established BEFORE a new cloud model is used
# ---------------------------------------------------------------------------
#
# The shipped table cannot know about a model released after it was written, and
# the failure mode of not knowing is the expensive one: the model runs, the
# tokens are recorded as unpriced, and the first anyone learns of the rate is the
# provider's invoice. So an unknown *cloud* model is not run until its price has
# been established — looked up where a provider publishes one, and confirmed by
# the user either way, because a fetched number is still a number about to be
# attributed to their money.
#
# Local models are exempt: their per-token cost really is zero and prompting for
# it would be noise.

LOCAL_PREFIXES = ("ollama/", "lmstudio/", "llamacpp/", "local/")


def is_local(model: str) -> bool:
    return (model or "").lower().startswith(LOCAL_PREFIXES)


def is_executor(model: str) -> bool:
    """Executors are exempt too — for a different reason than local models.

    `claude-code` and its siblings are ENGINE ids, not model ids. A delegated run
    bills against the subscription that CLI is signed in to, it reports its own
    spend on its `result` event, and AgentOS never counts tokens for it — so
    "what does claude-code cost per million tokens" is a question with no answer,
    and asking it is not a safeguard, it is a stall.

    It stalled for exactly five minutes. `needs_price` said "unknown" for the
    engine id, so every delegated turn went to the price card first — and at the
    time no surface drew that card, so no answer could arrive and the turn waited
    out the whole timeout. To the user that was five minutes of "working" with no
    step, no tool, no word, before the CLI was even spawned.
    """
    from .executors import ENGINES     # local: executors imports config, config imports us
    return (model or "") in ENGINES


def price_state(cfg: dict, model: str) -> str:
    """`priced` | `local` | `executor` | `skipped` | `unknown`.

    `skipped` is a deliberate "run it without pricing" the user chose once; it is
    remembered so the question is asked once per model, not once per turn.
    `executor` is its own answer rather than `local` because a delegated run is
    not free — it is billed somewhere this machine does not meter, which is a
    different thing from costing nothing.
    """
    if not model:
        return "priced"
    if is_local(model):
        return "local"
    if is_executor(model):
        return "executor"
    if (model or "").startswith("pool/"):
        # the community's leader runs it and records it as its own usage (pool.py);
        # this machine pays nothing for it, so asking it a price would only stall
        return "pool"
    if model in (cfg.get("pricing_skip") or []):
        return "skipped"
    return "priced" if price_of(cfg, model) is not None else "unknown"


def needs_price(cfg: dict, model: str) -> bool:
    return price_state(cfg, model) == "unknown"


async def discover_price(cfg: dict, model: str) -> dict:
    """Look up a published price. Returns {found, input, output, source, note}.

    OpenRouter publishes per-model rates for hundreds of models on an unauthenticated
    endpoint, and it is the only provider in this codebase that does. Anthropic,
    OpenAI and Google do not, so for those this returns a *reference* match if
    OpenRouter happens to carry the same model, clearly labelled as such — never
    silently written. Everything here is a suggestion for the user to confirm.
    """
    import httpx

    name = (model or "").split("/", 1)[-1].lower()
    out = {"found": False, "input": None, "output": None, "source": "", "note": ""}
    if not name:
        return out
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://openrouter.ai/api/v1/models")
            r.raise_for_status()
            data = r.json().get("data") or []
    except Exception as e:                                    # noqa: BLE001
        out["note"] = f"could not reach the OpenRouter price list ({type(e).__name__})"
        return out

    def rate(entry):
        p = entry.get("pricing") or {}
        try:  # OpenRouter quotes USD per token; this module works per million
            return float(p.get("prompt", 0)) * 1e6, float(p.get("completion", 0)) * 1e6
        except (TypeError, ValueError):
            return None

    exact = next((e for e in data if str(e.get("id", "")).lower() == (model or "").lower()), None)
    loose = exact or next(
        (e for e in data if str(e.get("id", "")).lower().split("/", 1)[-1] == name), None)
    if not loose:
        out["note"] = "no published price found for this model"
        return out
    got = rate(loose)
    if not got or (got[0] == 0 and got[1] == 0):
        out["note"] = f"{loose.get('id')} is listed as free — confirm that is right for you"
    out.update({"found": True, "input": (got or (0.0, 0.0))[0], "output": (got or (0.0, 0.0))[1],
                "source": f"openrouter:{loose.get('id')}"})
    if not exact:
        out["note"] = (f"this is OpenRouter's rate for {loose.get('id')}, used as a reference — "
                       f"your provider may charge differently")
    return out


def set_price(cfg: dict, model: str, price_in: float, price_out: float) -> None:
    """Record a confirmed price. Exact model id, not a glob: the user answered
    about THIS model, and widening that to a pattern on their behalf would price
    models they were never asked about."""
    cfg.setdefault("pricing", {})[model] = {"in": float(price_in), "out": float(price_out)}
    skip = cfg.get("pricing_skip") or []
    if model in skip:
        cfg["pricing_skip"] = [m for m in skip if m != model]


def skip_price(cfg: dict, model: str) -> None:
    """'Run it without pricing.' Remembered, so the question is asked once."""
    skip = list(cfg.get("pricing_skip") or [])
    if model not in skip:
        skip.append(model)
    cfg["pricing_skip"] = skip


#: What a cached input token costs, as a share of the input rate. Anthropic bills a cache read
#: at a tenth and a cache write at 1.25x; OpenAI's cached input is a tenth on its current models.
#: Still an estimate, and every report says so.
CACHE_READ, CACHE_WRITE = 0.10, 1.25


def cost(cfg: dict, model: str, tokens_in: int, tokens_out: int,
         cache_read: int = 0, cache_write: int = 0) -> float | None:
    rate = price_of(cfg, model)
    if rate is None:
        return None
    cr, cw = int(cache_read or 0), int(cache_write or 0)
    plain = max(0, int(tokens_in or 0) - cr - cw)
    inp = plain + cr * CACHE_READ + cw * CACHE_WRITE
    return round(inp * rate[0] / 1e6 + (tokens_out or 0) * rate[1] / 1e6, 6)


def record(store, cfg: dict, model: str, tokens: dict, *, surface: str = "",
           principal: str = "user", conversation_id: str = "", space_id: str = "",
           kind: str = "chat", cost_usd: float | None = None, estimated: bool = False) -> None:
    """One turn's usage. Called from every path that runs a turn; silent about
    turns that reported nothing, because a provider that does not send usage is
    not the same as a turn that spent nothing.

    `cost_usd`: what an agent CLI said the turn cost (Claude Code reports it on its last
    line). It is the bill, so it is recorded as given; this OS has no price list for a
    CLI's models and never works one out. `estimated`: a cost worked out here from a price
    list (a video's seconds), so it isn't the provider's bill."""
    tin, tout = int((tokens or {}).get("input") or 0), int((tokens or {}).get("output") or 0)
    if cost_usd is None and isinstance((tokens or {}).get("cost"), (int, float)):
        cost_usd = float(tokens["cost"])        # the provider stated it (OpenRouter's `cost`)
    if not (tin or tout or cost_usd):
        return
    src = ("estimated" if estimated else "reported") if cost_usd is not None else ""
    if cost_usd is None:
        cost_usd = cost(cfg, model, tin, tout, (tokens or {}).get("cache_read") or 0,
                        (tokens or {}).get("cache_write") or 0)
        src = "estimated" if cost_usd is not None else ""
    try:
        store.usage_add(model=model, tokens_in=tin, tokens_out=tout,
                        cost_usd=cost_usd, surface=surface,
                        principal=principal, conversation_id=conversation_id,
                        space_id=space_id, kind=kind, cost_src=src)
    except Exception:
        # Bookkeeping never costs the user the answer they were waiting for. This
        # sits on the turn's own exit path, so an exception here would surface as
        # "your chat turn failed" for a row nobody was reading yet.
        pass


def report(store, cfg: dict, days: float = 1.0, group: str = "model",
           space: str = "") -> dict:
    import time
    since = time.time() - days * 86400
    rows = store.usage_summary(since=since, group=group, space=space)
    total_cost = sum(r["cost"] or 0 for r in rows)
    unpriced = sum(r["unpriced"] for r in rows)
    return {"days": days, "group": group, "rows": rows,
            "tokens_in": sum(r["tin"] or 0 for r in rows),
            "tokens_out": sum(r["tout"] or 0 for r in rows),
            "cost_usd": round(total_cost, 4),
            "unpriced_turns": unpriced,
            # the sentence the UI shows, so the caveat travels with the number
            "note": (f"{unpriced} turn(s) ran on a model with no price configured and are "
                     f"counted in tokens only" if unpriced else "")}


def turn(store, cfg: dict, model: str, tokens: dict, **kw) -> None:
    """A turn's own bookkeeping after it ends. Every call to a provider was counted at the door
    already (`meter`), so only a turn whose calls never passed it is recorded here: an agent
    CLI's, with the bill it stated."""
    if kw.get("cost_usd") is None and at_door(model):
        return
    record(store, cfg, model, tokens, **kw)


def format_report(rep: dict) -> str:
    lines = [f"last {rep['days']:g} day(s), by {rep['group']}:", ""]
    lines.append(f"  {'':<34}{'turns':>7}{'in':>12}{'out':>10}{'USD':>10}")
    for r in rep["rows"]:
        cost_txt = "—" if r["priced"] == 0 else f"{r['cost']:.4f}"
        lines.append(f"  {str(r['bucket'] or '(none)')[:34]:<34}{r['n']:>7}"
                     f"{r['tin'] or 0:>12,}{r['tout'] or 0:>10,}{cost_txt:>10}")
    lines.append("")
    lines.append(f"  total: {rep['tokens_in']:,} in / {rep['tokens_out']:,} out"
                 f"  ·  ${rep['cost_usd']:.4f}")
    if rep["note"]:
        lines.append(f"  note: {rep['note']}")
    return "\n".join(lines)



# ---- every call, counted once, at the door -----------------------------------------------
#
# Asked for as "usage available for all the LLMs and all the accounts, money and tokens in, out and
# total". Every call to a provider passes ONE door, `providers.chat`, and `meter` records it there,
# in the account that made it: a chat's rounds, a specialist's, a mission master's, a summary, an
# extraction, an app's AI, a draft. Before, only some turns were recorded, after they ended, and a
# specialist or a mission master's calls reached no Usage row at all. Who a call is for comes from
# `CALLER`, set by the Agent around its run (`Agent._usage_caller`) and by a route that calls a
# model itself. A turn's own bookkeeping after it ends (`turn`) skips those calls (`at_door`), so
# nothing is counted twice; an agent CLI's turn never passes the door, and its bill is still
# recorded by the turn, as the CLI stated it.

CALLER: contextvars.ContextVar = contextvars.ContextVar("bento_usage_caller", default=None)


def at_door(model: str) -> bool:
    """Is this model's every call counted at the door? Everything but an agent CLI's turn."""
    from .executors import ENGINES
    head = llm_of(model)
    return bool(head) and not (head in ENGINES and head != "aria")


def _priced_by_admin(cfg: dict) -> dict:
    """The prices a call is counted at. `/api/pricing` writes into whoever asked's view, so an
    account that isn't an admin could set its own price to $0 and slip under a dollar quota. For
    such an account the machine's prices win, and its own count only for a model the machine has
    no price for (the price card on a new model still has to be answerable)."""
    from . import users as usersmod
    uid = usersmod.current() or "" if usersmod.enabled() else ""
    if not uid or usersmod.is_tenant_admin(uid):
        return cfg
    machine = dict(((usersmod._machine[0] or {}).get("pricing")) or {})
    known = {"pricing": machine}
    own = {k: v for k, v in (cfg.get("pricing") or {}).items() if price_of(known, k) is None}
    return {**cfg, "pricing": {**own, **machine}}


def meter(cfg: dict, model_id: str, ev: dict) -> None:
    who = CALLER.get() or {}
    try:
        from . import users as usersmod
        store = usersmod.store_for(usersmod.current() or "")
        cfg = _priced_by_admin(cfg)
    except Exception:
        return
    record(store, cfg, model_id, ev, kind=who.get("kind") or "background",
           principal=who.get("principal") or "user", surface=who.get("surface") or "",
           conversation_id=who.get("conversation_id") or "", space_id=who.get("space_id") or "")


class caller:
    """`with usage.caller(kind="app", principal="app:<id>", surface=…, conversation_id=…):` names
    who the calls made inside are for."""

    def __init__(self, **who):
        self.who = who

    def __enter__(self):
        self._tok = CALLER.set(self.who)
        return self

    def __exit__(self, *a):
        CALLER.reset(self._tok)
        return False


# ---- by LLM, by account, and the daily quotas ----------------------------------------------
#
# Asked for as "per account limits for the amount or tokens per day per LLM shared, like a quota:
# decide which LLMs are shared and the quota per user, by tokens or cost or both; by default it's
# unlimited". `cfg["llm_sharing"]` is the machine's (and an Isolated Tenant's own, users.TENANT_KEYS):
#   off:   providers NOT shared with the accounts (their admins still use them)
#   quota: {"*": {llm: {tokens, usd}}, "<uid>": {llm: {tokens, usd}}}, llm a provider id or a model
#          id; 0 or absent is unlimited. "*" is everyone's who has none of their own, admins aside.
# A day is the machine's local day. Checked at the door (`providers.chat` → `quota_refusal`).

LOCAL = ("ollama", "lmstudio", "llamacpp", "local")


def llm_of(model_id: str) -> str:
    return str(model_id or "").split("/", 1)[0]


def day_start(now: float | None = None) -> float:
    t = time.localtime(now or time.time())
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _admin_here(uid: str) -> bool:
    from . import users as usersmod
    return usersmod.is_tenant_admin(uid)


def sharing(cfg: dict) -> dict:
    s = (cfg or {}).get("llm_sharing")
    return s if isinstance(s, dict) else {}


def quota_for(cfg: dict, uid: str, model_id: str) -> dict:
    """This account's daily quota for this LLM: {tokens, usd}, 0 meaning no limit on that one."""
    q = sharing(cfg).get("quota") or {}
    mine = q.get(uid) if isinstance(q.get(uid), dict) else None
    if mine is None and not _admin_here(uid):
        mine = q.get("*") if isinstance(q.get("*"), dict) else None
    mine = mine or {}
    got = mine.get(model_id) or mine.get(llm_of(model_id)) or {}
    out = {}
    for k in ("tokens", "usd"):
        try:
            v = float(got.get(k) or 0)
        except (TypeError, ValueError):
            v = 0
        out[k] = v if v > 0 else 0
    return out


def spent_today(store, model_id: str, now: float | None = None) -> dict:
    """What this account spent today on this LLM: tokens in, out, total and dollars."""
    llm = llm_of(model_id)
    rows = store.db.execute(
        "SELECT model, SUM(tokens_in) tin, SUM(tokens_out) tout, SUM(COALESCE(cost_usd,0)) usd "
        "FROM usage WHERE ts >= ? GROUP BY model", (day_start(now),)).fetchall()
    tin = tout = 0
    usd = 0.0
    for r in rows:
        m = r["model"] or ""
        if m == model_id or llm_of(m) == llm:
            tin += int(r["tin"] or 0)
            tout += int(r["tout"] or 0)
            usd += float(r["usd"] or 0)
    return {"in": tin, "out": tout, "total": tin + tout, "usd": round(usd, 6)}


LLM_NAMES = {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google Gemini",
             "openrouter": "OpenRouter", "deepseek": "DeepSeek", "moonshot": "Moonshot (Kimi)",
             "custom": "your custom provider", "pool": "your community's leader",
             "claude-code": "Claude Code", "gemini-cli": "Gemini CLI", "codex": "Codex",
             "ollama": "Ollama (this machine)"}


def llm_name(llm: str) -> str:
    return LLM_NAMES.get(llm, llm)


def quota_refusal(cfg: dict, model_id: str) -> str:
    """Why this account may not call this LLM now, or ''. Asked before every call."""
    try:
        from . import users as usersmod
        if not usersmod.enabled():
            return ""
        uid = usersmod.current() or ""
        if not uid:
            return ""
        llm = llm_of(model_id)
        if llm in LOCAL:
            return ""
        s = sharing(cfg)
        if llm in (s.get("off") or []) and not _admin_here(uid):
            return (f"{llm_name(llm)} isn't shared with your account on this machine. Ask its admin, "
                    "or pick another brain.")
        q = quota_for(cfg, uid, model_id)
        if not (q["tokens"] or q["usd"]):
            return ""
        got = spent_today(usersmod.store_for(uid), model_id)
        if q["tokens"] and got["total"] >= q["tokens"]:
            return (f"Your daily quota for {llm_name(llm)} is used up: {got['total']:,} of "
                    f"{int(q['tokens']):,} tokens today. It starts again at midnight.")
        if q["usd"] and got["usd"] >= q["usd"]:
            return (f"Your daily quota for {llm_name(llm)} is used up: ${got['usd']:.2f} of "
                    f"${q['usd']:.2f} today. It starts again at midnight.")
    except Exception:
        return ""
    return ""


def by_llm(store, cfg: dict, days: float = 1.0, uid: str = "") -> list[dict]:
    """One account's spend per LLM (provider) and per model: tokens in, out, total, dollars, and
    how much of the dollars is the provider's own figure against our estimate."""
    since = day_start() if days <= 1 else time.time() - days * 86400
    rows = store.db.execute(
        "SELECT model, COUNT(*) n, SUM(tokens_in) tin, SUM(tokens_out) tout, "
        "SUM(CASE WHEN cost_src='reported' THEN cost_usd ELSE 0 END) exact, "
        "SUM(CASE WHEN cost_src='reported' THEN 0 ELSE COALESCE(cost_usd,0) END) est, "
        "SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) unpriced "
        "FROM usage WHERE ts >= ? GROUP BY model", (since,)).fetchall()
    out: dict = {}
    for r in rows:
        llm = llm_of(r["model"]) or "(unknown)"
        d = out.setdefault(llm, {"llm": llm, "name": llm_name(llm), "calls": 0, "in": 0, "out": 0,
                                 "usd_exact": 0.0, "usd_estimated": 0.0, "unpriced": 0, "models": []})
        d["calls"] += int(r["n"] or 0)
        d["in"] += int(r["tin"] or 0)
        d["out"] += int(r["tout"] or 0)
        d["usd_exact"] += float(r["exact"] or 0)
        d["usd_estimated"] += float(r["est"] or 0)
        d["unpriced"] += int(r["unpriced"] or 0)
        d["models"].append({"model": r["model"], "calls": int(r["n"] or 0), "in": int(r["tin"] or 0),
                            "out": int(r["tout"] or 0)})
    res = []
    for d in out.values():
        d["total"] = d["in"] + d["out"]
        d["usd"] = round(d["usd_exact"] + d["usd_estimated"], 6)
        d["usd_exact"], d["usd_estimated"] = round(d["usd_exact"], 6), round(d["usd_estimated"], 6)
        if uid:
            q = quota_for(cfg, uid, d["llm"])
            if q["tokens"] or q["usd"]:
                today = spent_today(store, d["llm"])
                d["quota"] = {**q, "left_tokens": max(0, q["tokens"] - today["total"]) if q["tokens"] else None,
                              "left_usd": round(max(0.0, q["usd"] - today["usd"]), 4) if q["usd"] else None}
        res.append(d)
    return sorted(res, key=lambda d: (-d["usd"], -d["total"]))


def everyone(cfg: dict, days: float = 1.0, viewer: str = "") -> list[dict]:
    """Every account's spend per LLM, for an admin: the machine's admin sees all accounts, an
    Isolated Tenant's admin its own tenant's. Each account's rows come from its own database."""
    from . import users as usersmod
    if not usersmod.enabled():
        return [{"uid": "", "name": "this machine", "llms": by_llm(usersmod.store_for(""), cfg, days)}]
    t = usersmod.tenant_of(viewer) if viewer else ""
    rows = []
    for u in usersmod.list_users():
        if not usersmod.is_admin(viewer) and str(u.get("tenant") or "") != t:
            continue
        try:
            st = usersmod.store_for(u["id"])
        except Exception:
            continue
        rows.append({"uid": u["id"], "name": u.get("name") or u["id"],
                     "tenant": u.get("tenant") or "", "llms": by_llm(st, usersmod.cfg_for(u["id"]), days, u["id"])})
    return rows


def words(llms: list[dict], days: float = 1.0) -> str:
    """The same numbers as sentences, for an agent to answer with and for `bento usage`."""
    when = "today" if days <= 1 else f"in the last {days:g} days"
    if not llms:
        return f"No model calls {when}."
    lines = [f"Usage {when}, by LLM:"]
    for d in llms:
        money = f"${d['usd']:.4f}"
        if d["usd_exact"] and d["usd_estimated"]:
            money += f" (${d['usd_exact']:.4f} as the provider stated it, ${d['usd_estimated']:.4f} estimated)"
        elif d["usd_estimated"]:
            money += " (estimated from the price list)"
        elif d["usd_exact"]:
            money += " (as the provider stated it)"
        if d["unpriced"]:
            money += f"; {d['unpriced']} call(s) had no price"
        line = (f"- {d['name']}: {d['calls']} calls, {d['in']:,} tokens in, {d['out']:,} out, "
                f"{d['total']:,} in all, {money}")
        q = d.get("quota")
        if q:
            bits = []
            if q.get("left_tokens") is not None:
                bits.append(f"{int(q['left_tokens']):,} of {int(q['tokens']):,} tokens left today")
            if q.get("left_usd") is not None:
                bits.append(f"${q['left_usd']:.2f} of ${q['usd']:.2f} left today")
            line += "; quota: " + ", ".join(bits)
        lines.append(line)
    return "\n".join(lines)


def clean_sharing(raw: dict, providers: dict, uids: set) -> tuple[dict, list[str]]:
    """The sharing settings, read field by field: `off` names providers this machine has, a quota's
    account is "*" or one of `uids`, an LLM is a provider id or "provider/model", and each limit is
    a number of tokens or dollars a day (0 is unlimited). What is dropped is named."""
    raw = raw if isinstance(raw, dict) else {}
    dropped: list[str] = []
    off = []
    for p in raw.get("off") or []:
        if p in providers and p not in LOCAL and p not in off:
            off.append(p)
        else:
            dropped.append(f"off: {str(p)[:40]}")
    quota: dict = {}
    for who, per in (raw.get("quota") or {}).items():
        if who != "*" and who not in uids:
            dropped.append(f"quota for an unknown account {str(who)[:20]}")
            continue
        if not isinstance(per, dict):
            continue
        for llm, lim in per.items():
            llm = str(llm or "")[:120]
            if llm_of(llm) not in providers or llm_of(llm) in LOCAL:
                dropped.append(f"quota for {llm[:40]}")
                continue
            got = {}
            for k in ("tokens", "usd"):
                try:
                    v = float((lim or {}).get(k) or 0)
                except (TypeError, ValueError, AttributeError):
                    v = 0
                if v > 0:
                    got[k] = int(v) if k == "tokens" else round(v, 4)
            if got:
                quota.setdefault(who, {})[llm] = got
    return {"off": off, "quota": quota}, dropped
