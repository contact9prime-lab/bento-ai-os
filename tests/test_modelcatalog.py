"""The model catalogue: what this release suggests, never what anybody chose.

Reported as "in AI providers the models are really old": the suggested lists still
offered gpt-4o, gemini-2.0-flash (shut down June 2026) and kimi-k2-0711-preview. They
live in agentos/modelcatalog.py now, dated, refreshed every release — and an update must
not rewrite anybody's saved models while doing it.
"""

import asyncio
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import config as cfgmod                               # noqa: E402
from agentos import modelcatalog as mc                             # noqa: E402
from agentos import providers                                      # noqa: E402
from agentos import setup as setupmod                              # noqa: E402

ROOT = Path(__file__).parent.parent


def test_every_provider_has_a_dated_sourced_default_among_its_models():
    dt.date.fromisoformat(mc.CHECKED)
    for prov, entry in mc.CATALOGUE.items():
        assert entry["models"] and entry["default"] in entry["models"], prov
        assert entry["source"].startswith("https://"), prov
        assert len(set(entry["models"])) == len(entry["models"]), prov


def test_retired_names_are_not_suggested():
    every = [m for e in mc.CATALOGUE.values() for m in e["models"]]
    for gone in ("gemini-2.0-flash", "kimi-k2-0711-preview", "deepseek-chat", "gpt-4o"):
        assert not any(m.endswith(gone) for m in every), gone


def test_new_installs_start_from_the_catalogue():
    d = cfgmod.DEFAULTS["providers"]
    for prov in mc.CATALOGUE:
        assert d[prov]["models"] == mc.suggested(prov), prov


def test_a_saved_list_is_never_rewritten(tmp_path, monkeypatch):
    """Somebody who pinned gpt-4o in 2025 keeps gpt-4o: the catalogue is a selection
    list, not a migration."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"providers": {"openai": {"models": ["gpt-4o"]}},
                             "default_model": "openai/gpt-4o"}))
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", p)
    cfg = cfgmod.load_config()
    assert cfg["providers"]["openai"]["models"] == ["gpt-4o"]
    assert cfg["default_model"] == "openai/gpt-4o"


def test_the_picker_offers_suggestions_after_your_own_only_when_the_provider_cannot_list(monkeypatch):
    async def none(*a, **k):
        return []

    async def listed(*a, **k):
        return ["gpt-live-model"]
    providers.forget_models()
    monkeypatch.setattr(providers, "ollama_models", none)
    cfg = {"providers": {"ollama": {"enabled": False, "base_url": ""},
                         "anthropic": {"enabled": True, "api_key": "k", "models": ["claude-opus-4-8"]},
                         "openai": {"enabled": True, "api_key": "k", "models": ["gpt-4o"]}}}
    monkeypatch.setattr(providers, "openai_models", listed)
    ids = [m["id"] for m in asyncio.run(providers.available_models(cfg))]
    # Anthropic cannot list: the person's pin first, then this release's suggestions
    ant = [i for i in ids if i.startswith("anthropic/")]
    assert ant[0] == "anthropic/claude-opus-4-8"
    assert "anthropic/claude-sonnet-5" in ant
    # OpenAI listed its models: that list is the truth, no suggestions are invented
    oai = [i for i in ids if i.startswith("openai/")]
    assert oai == ["openai/gpt-4o", "openai/gpt-live-model"]
    providers.forget_models()


def test_setup_offers_the_catalogue_default_on_every_face():
    for pid, _label, model in setupmod.CLOUD_PROVIDERS:
        assert model == mc.default(pid), pid
    js = (ROOT / "agentos/ui/src/js/14b-onboarding.js").read_text()
    block = js[js.index("var OB_CLOUD=["):js.index("];", js.index("var OB_CLOUD=["))]
    for pid, model in re.findall(r"\{id:'([a-z]+)',label:'[^']*',\s*model:'([^']*)'", block, re.S):
        assert model == mc.default(pid), (pid, model)


def test_the_release_step_says_when_the_catalogue_is_old():
    checked = dt.date.fromisoformat(mc.CHECKED)
    assert mc.stale_note(checked) == ""
    note = mc.stale_note(checked + dt.timedelta(days=mc.STALE_DAYS + 1))
    assert "modelcatalog.py" in note and mc.CHECKED in note
