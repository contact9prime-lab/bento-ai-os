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

import fnmatch

# USD per million tokens, (input, output). Patterns are matched in order, most
# specific first. These are a convenience, not an authority: they were written on
# 2026-08-04 and providers change them without telling us. Override in Settings.
DEFAULT_PRICING: list[tuple[str, tuple[float, float]]] = [
    ("ollama/*", (0.0, 0.0)),          # local: the electricity is not billed per token
    ("lmstudio/*", (0.0, 0.0)),
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


def cost(cfg: dict, model: str, tokens_in: int, tokens_out: int) -> float | None:
    rate = price_of(cfg, model)
    if rate is None:
        return None
    return round((tokens_in or 0) * rate[0] / 1e6 + (tokens_out or 0) * rate[1] / 1e6, 6)


def record(store, cfg: dict, model: str, tokens: dict, *, surface: str = "",
           principal: str = "user", conversation_id: str = "", space_id: str = "",
           kind: str = "chat") -> None:
    """One turn's usage. Called from every path that runs a turn; silent about
    turns that reported nothing, because a provider that does not send usage is
    not the same as a turn that spent nothing."""
    tin, tout = int((tokens or {}).get("input") or 0), int((tokens or {}).get("output") or 0)
    if not (tin or tout):
        return
    try:
        store.usage_add(model=model, tokens_in=tin, tokens_out=tout,
                        cost_usd=cost(cfg, model, tin, tout), surface=surface,
                        principal=principal, conversation_id=conversation_id,
                        space_id=space_id, kind=kind)
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
