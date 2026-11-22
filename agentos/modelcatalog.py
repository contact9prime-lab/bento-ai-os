"""The models this release SUGGESTS for each cloud provider — and when that was checked.

Model names go stale faster than anything else in this OS: a list written in 2025 still
offered `gpt-4o` and `gemini-2.0-flash` (shut down June 2026) in 2026's picker. So the
suggestions live here, in one place, with the date they were checked and where from,
and refreshing them is a release step like the docs (CLAUDE.md, "Every release";
`bento version bump` says when this is older than `STALE_DAYS`).

What this is NOT: anybody's choice. A person's saved models (`providers.<p>.models`,
`default_model`, an agent's pin) are theirs and are never rewritten by an update.
The catalogue reaches three places only:
- the config DEFAULTS, which fill a provider's list on a NEW install;
- the picker, where a provider cannot list its own models (Anthropic has no listing
  endpoint) or its listing failed — added after the person's own, never replacing them;
- the defaults offered by setup (the desktop wizard, `bento setup`, the TUI).

Only IDs that were confirmed as the exact API string go in: a wrong ID in a picker is
a dead choice. Stdlib only; config.py imports it at start.
"""
from __future__ import annotations

import datetime as _dt

#: When these lists were last checked against the providers' own pages.
CHECKED = "2026-11-21"
#: `bento version bump` warns when the catalogue is older than this.
STALE_DAYS = 45

CATALOGUE: dict[str, dict] = {
    "anthropic": {
        "default": "claude-sonnet-5-5",
        "models": ["claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
        "source": "https://platform.claude.com/docs/en/about-claude/models/overview",
    },
    "openai": {
        "default": "gpt-6.1-sol",
        "models": ["gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna"],
        "source": "https://developers.openai.com/api/docs/models",
    },
    "google": {
        # Gemini 4 is listed with its ids but the page does not say who may use it yet, so only
        # the one described as "for everyone" is offered; carbon and argon wait for the next check
        "default": "gemini-3.8-flash",
        "models": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-4-hydrogen"],
        "source": "https://aistudio.google.com/docs/models",
    },
    "openrouter": {
        "default": "google/gemini-3.8-flash",
        "models": ["anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5", "google/gemini-3.8-flash",
                   "openai/gpt-6.1-sol", "openai/gpt-6-luna"],
        "source": "https://openrouter.ai/api/v1/models",
    },
    "deepseek": {
        # 2026-11-21: DeepSeek's own V4 notes name the fast model `deepseek-v4-flash` (read through
        # search, the docs host was not reachable from where this was checked); `deepseek-flash`
        # appeared nowhere and would have been a dead choice
        "default": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    },
    "moonshot": {
        "default": "kimi-k3.1-pro",
        "models": ["kimi-k3.1-pro", "kimi-k3.1-pro-highspeed", "kimi-k3"],
        "source": "https://platform.kimi.ai/docs/models",
    },
}


def suggested(provider: str) -> list[str]:
    """This release's suggestions for one provider (a copy; [] for one it has none for)."""
    return list((CATALOGUE.get(provider) or {}).get("models") or [])


def default(provider: str) -> str:
    """The model setup offers first for this provider ("" when there is none)."""
    return str((CATALOGUE.get(provider) or {}).get("default") or "")


def age_days(today: _dt.date | None = None) -> int:
    """How many days since the catalogue was checked."""
    today = today or _dt.date.today()
    return (today - _dt.date.fromisoformat(CHECKED)).days


def stale_note(today: _dt.date | None = None) -> str:
    """A sentence for the release step when the catalogue is old, else ""."""
    days = age_days(today)
    if days <= STALE_DAYS:
        return ""
    return (f"the model catalogue (agentos/modelcatalog.py) was last checked {days} days "
            f"ago, on {CHECKED} — refresh the suggested models from the providers' own "
            f"pages before this release")
