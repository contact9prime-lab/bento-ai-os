"""If the lead's brain isn't available, the next one answers.

Asked for from Settings → AI providers, with Claude Code as the brain: "we can also give a pool
of models it can take from based on availability; if one is not available, point to the other".
`brain_fallbacks` (a USER_KEY, beside `default_model`) is an ordered list of brains, each the
same {executor, model} pair the brain picker writes. A chat turn that produced no answer and
failed because its brain was unavailable is asked again of the next one, once each, in order,
and the chat says so. Three rules:

  * Only UNAVAILABLE is a reason. A usage limit, a sign-in that lapsed, an overloaded or
    unreachable service, a CLI that isn't installed: the next brain may well answer. A turn the
    person stopped, or one the gate refused, is never retried on another brain; that would be
    a way around the stop or the refusal.
  * A brain this machine can't run right now is skipped, never tried (`usable`).
  * The list is validated at the write (`clean`), like the picker: an engine this machine
    doesn't know, or a provider model with no provider, is refused in a sentence.

Free of HTTP and asyncio: the chat runner, the route and `bento brain fallbacks` call it.
"""
from __future__ import annotations

import re

MAX = 4                     # brains after the first: each is a turn the person waits through

# what an unavailable brain says, across Claude Code, Gemini CLI, Codex and the providers
_UNAVAILABLE = re.compile(
    r"usage limit|rate.?limit|limit (?:reached|exceeded)|hit your limit|quota|credit|billing|"
    r"overloaded|capacity|too many requests|\b429\b|\b529\b|\b503\b|\b502\b|service unavailable|"
    r"not logged in|log ?in|sign ?in|unauthori[sz]ed|\b401\b|authenticat|api key|invalid.{0,20}key|"
    r"connect(?:ion)? (?:error|refused|failed)|could not connect|all connection attempts failed|"
    r"timed? ?out|unreachable|not installed|no such file|command not found|not available|"
    r"model .{0,40}not found|does not exist|no brain|no model", re.I)
# never a reason to try another brain
_NOT_A_REASON = re.compile(r"turn stopped|cancel|denied|not allowed|refused by|blocked by", re.I)


def unavailable(errors: list[str]) -> bool:
    """Did these errors say the brain could not answer at all (rather than refused)?"""
    text = " ".join(str(e or "") for e in errors)
    return bool(text.strip()) and not _NOT_A_REASON.search(text) and bool(_UNAVAILABLE.search(text))


def key(executor: str, model: str = "") -> str:
    """What a brain is called in `_tried`: the model for a provider, the CLI otherwise."""
    return model if (executor or "aria") == "aria" else executor


def clean(items, cfg: dict | None = None) -> list[dict]:
    """The stored shape, refused in a sentence when a brain isn't one this machine knows."""
    from . import executors as execmod
    out, seen = [], set()
    for it in list(items or [])[:MAX]:
        if not isinstance(it, dict):
            raise ValueError("each fallback is an executor and a model")
        ex = str(it.get("executor") or "aria").strip()
        model = str(it.get("model") or "").strip()[:160]
        if ex not in execmod.ENGINES and ex not in (cfg or {}).get("providers", {}):
            raise ValueError(f"'{ex}' is not a brain this machine knows")
        if ex in (cfg or {}).get("providers", {}):     # a provider named as the executor
            model = model if "/" in model else f"{ex}/{model}" if model else ""
            ex = "aria"
        if ex == "aria" and "/" not in model:
            raise ValueError("choose one of the provider's models for a fallback")
        k = key(ex, model)
        if k in seen:
            continue
        seen.add(k)
        out.append({"executor": ex, "model": model})
    return out


def chain(cfg: dict) -> list[dict]:
    try:
        return clean((cfg or {}).get("brain_fallbacks") or [], cfg)
    except ValueError:
        return []


def usable(cfg: dict, fb: dict) -> bool:
    """Can this machine run that brain right now? A CLI must be installed; a provider must be
    switched on and, for a cloud one, have its key."""
    from . import executors as execmod
    ex, model = fb.get("executor") or "aria", fb.get("model") or ""
    if ex != "aria":
        return execmod.drives(ex) and bool(execmod.probe(ex).get("installed"))
    prov = model.split("/", 1)[0]
    p = ((cfg or {}).get("providers") or {}).get(prov)
    if p is None:
        return False
    if p.get("enabled") is False:
        return False
    return prov in ("ollama", "custom", "pool") or bool(p.get("api_key"))


def next_for(cfg: dict, tried: list[str]) -> dict | None:
    """The first fallback not yet tried this turn that can run here."""
    for fb in chain(cfg):
        if key(fb["executor"], fb["model"]) in tried:
            continue
        if usable(cfg, fb):
            return fb
    return None


def request(fb: dict) -> str:
    """What the chat runner is handed as the turn's model: a CLI by its id, a provider's model
    by its full id (resolve_engine reads both)."""
    return fb["executor"] if fb["executor"] != "aria" else fb["model"]


def words(fb: dict) -> str:
    from . import executors as execmod
    if fb["executor"] == "aria":
        return fb["model"]
    title = execmod.EXECUTORS_BY_ID.get(fb["executor"], {}).get("title", fb["executor"])
    return title + (f" ({fb['model']})" if fb.get("model") else "")
