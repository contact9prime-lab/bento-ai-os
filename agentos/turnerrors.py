"""A failed turn, as a sentence with a door.

The first message ever sent on a fresh install used to be answered with
``ConnectError: All connection attempts failed`` — in red, from the agent, with
a toast saying it had replied. No model was set, the provider layer fell through
to an Ollama that was not running, and the exception's class name was the whole
explanation. The honesty rule this OS applies to capabilities ("say why, and
name what would fix it") was not applied to turns, and a turn is the first thing
anybody does.

This module is the vocabulary for that. It is pure — no HTTP, no asyncio — so
the TUI, the Telegram bridge and the tests can use the same sentences, and so
the server's exception handler stays one line. Every answer carries:

- ``message``  a sentence a person can act on;
- ``kind``     a short machine word (``no_brain``, ``unreachable``, ``auth``…);
- ``action``   the door the UI offers, or ``''`` when there is nothing to open
               (``brain`` opens the setup step, ``providers`` the AI providers
               pane, ``models`` the Model Manager).

The exception's name and text still go to Logs, where somebody debugging wants
them. They do not go in the reply.
"""

from __future__ import annotations

import asyncio


def no_brain() -> dict:
    """Nothing is set to answer. Said BEFORE the turn runs, so nothing is billed
    or logged as a failure — the machine is not broken, it is not set up."""
    return {
        "message": "Nothing can answer yet — this machine has no brain. "
                   "Give it one: a model on this machine, a cloud key, or another agent.",
        "kind": "no_brain",
        "action": "brain",
    }


def _provider_name(provider: str) -> str:
    return {
        "ollama": "Ollama", "anthropic": "Anthropic", "openai": "OpenAI",
        "google": "Google", "openrouter": "OpenRouter", "deepseek": "DeepSeek",
        "moonshot": "Kimi", "custom": "the custom endpoint",
    }.get(provider, provider or "the provider")


def explain(exc: BaseException, model: str, cfg: dict | None = None) -> dict:
    """Turn an exception from a turn into ``{message, kind, action}``.

    ``model`` is the model id the turn ran on (``ollama/qwen3``,
    ``anthropic/claude-sonnet-5``, or a bare Ollama name). ``cfg`` is only read
    for the Ollama base URL, so the sentence can name the address that did not
    answer.
    """
    from .providers import ProviderError, parse_model_id

    name = type(exc).__name__
    text = str(exc) or ""
    low = f"{name} {text}".lower()
    provider, short = parse_model_id(model) if model else ("", "")
    who = _provider_name(provider)

    if not model:
        return no_brain()

    # A ProviderError is already a sentence written for a person ("Anthropic API
    # key not set — add it in Settings."). Keep it; just point at the door.
    if isinstance(exc, ProviderError):
        kind = "auth" if "key" in low else "provider"
        return {"message": text, "kind": kind, "action": "providers"}

    if isinstance(exc, asyncio.TimeoutError) or "timed out" in low or "timeout" in low:
        return {"message": f"{who} did not answer in time. Try again, or choose another model.",
                "kind": "timeout", "action": ""}

    unreachable = ("connecterror" in low or "connection refused" in low
                   or "all connection attempts failed" in low or "name or service not known" in low
                   or "nodename nor servname" in low or "connection reset" in low
                   or isinstance(exc, ConnectionError))
    if unreachable:
        if provider == "ollama":
            url = ""
            try:
                url = ((cfg or {}).get("providers", {}).get("ollama", {}) or {}).get("base_url", "")
            except Exception:
                url = ""
            where = f" at {url}" if url else ""
            return {"message": f"Could not reach Ollama{where}. Start it (`ollama serve`), "
                               f"or choose a cloud model.",
                    "kind": "unreachable", "action": "models"}
        return {"message": f"Could not reach {who}. Check the network, or the base URL "
                           f"in AI providers.",
                "kind": "unreachable", "action": "providers"}

    if ("401" in low or "403" in low or "unauthorized" in low or "authentication" in low
            or "invalid api key" in low or "invalid x-api-key" in low or "incorrect api key" in low):
        return {"message": f"{who} refused the API key. Check it in Settings → AI providers.",
                "kind": "auth", "action": "providers"}

    if "429" in low or "rate limit" in low or "rate_limit" in low or "quota" in low:
        return {"message": f"{who} is rate-limiting this machine. Wait a minute and try again, "
                           f"or choose another model.",
                "kind": "rate", "action": ""}

    if provider == "ollama" and ("404" in low or "not found" in low):
        return {"message": f"{short or model} is not on this machine yet — pull it in Model Manager.",
                "kind": "missing", "action": "models"}

    if "402" in low or "insufficient" in low or "credit" in low or "billing" in low:
        return {"message": f"{who} says this account has no credit left. Top it up, "
                           f"or choose another model.",
                "kind": "billing", "action": "providers"}

    detail = text.strip().replace("\n", " ")[:160]
    return {"message": f"{short or model} did not answer"
                       + (f": {detail}" if detail else "")
                       + ". Details are in Logs.",
            "kind": "failed", "action": ""}
