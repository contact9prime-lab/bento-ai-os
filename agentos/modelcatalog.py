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
CHECKED = "2026-09-27"
#: `bento version bump` warns when the catalogue is older than this.
STALE_DAYS = 45

CATALOGUE: dict[str, dict] = {
    "anthropic": {
        "default": "claude-sonnet-5",
        "models": ["claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5-1"],
        "source": "https://platform.claude.com/docs/en/about-claude/models/overview",
    },
    "openai": {
        "default": "gpt-6-sol",
        "models": ["gpt-6-sol", "gpt-6-luna", "gpt-5.6-terra"],
        "source": "https://techcrunch.com/2026/09/22/openai-launches-gpt-6-sol-and-luna/",
    },
    "google": {
        "default": "gemini-3.8-flash",
        "models": ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"],
        "source": "https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash",
    },
    "openrouter": {
        "default": "google/gemini-3.8-flash",
        "models": ["anthropic/claude-opus-5.5", "google/gemini-3.8-flash", "openai/gpt-6-luna"],
        "source": "https://openrouter.ai/anthropic/claude-opus-5.5",
    },
    "deepseek": {
        "default": "deepseek-flash",
        "models": ["deepseek-flash"],
        "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    },
    "moonshot": {
        "default": "kimi-k3",
        "models": ["kimi-k3"],
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
