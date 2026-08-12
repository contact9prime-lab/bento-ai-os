"""The cloud providers the setup step offers — in all three faces, from one list.

The model step exists in a browser (`OB_CLOUD` in 14b-onboarding.js) and in a
terminal (`setup.CLOUD_PROVIDERS`, used by `bento setup` over SSH). Two copies of a
menu drift, and the half that drifts is whichever nobody is demoing — which is the
terminal, on the headless box where a standing job actually earns its keep.

So these assert the two lists are the same list, and that every id in them is a real
provider: an id that is not a key of `cfg["providers"]` saves a `default_model` that
`providers.chat()` then refuses to dispatch, and the failure lands on the user's
first message rather than on the step that caused it.
"""

import asyncio
import copy
import re
from pathlib import Path

import pytest

from agentos import config as cfgmod
from agentos import providers, setup as setupmod

UI = Path(__file__).resolve().parent.parent / "agentos" / "ui" / "src" / "js" / "14b-onboarding.js"


def _ui_providers() -> list[str]:
    """The ids in OB_CLOUD, in order, read out of the source the bundle is built from."""
    src = UI.read_text()
    block = re.search(r"var OB_CLOUD=\[(.*?)\n\];", src, re.S)
    assert block, "OB_CLOUD not found in 14b-onboarding.js — has it been renamed?"
    return re.findall(r"\{id:'([^']+)'", block.group(1))


def test_the_terminal_offers_exactly_what_the_browser_offers():
    assert _ui_providers() == [p for p, _, _ in setupmod.CLOUD_PROVIDERS]


@pytest.mark.parametrize("pid,label,model", setupmod.CLOUD_PROVIDERS,
                         ids=[p for p, _, _ in setupmod.CLOUD_PROVIDERS])
def test_every_offered_provider_is_real_and_answerable(pid, label, model):
    assert pid in cfgmod.DEFAULTS["providers"], f"{pid} is offered but not a configured provider"
    assert label and model, f"{pid} needs a label and a default model to be pickable"


@pytest.mark.parametrize("pid", [p for p, _, _ in setupmod.CLOUD_PROVIDERS])
def test_a_keyless_provider_says_which_one_rather_than_dispatching(pid):
    """The step's whole output is `provider/model` + a key. If the key is missing the
    error has to name the provider the user picked — a message naming the wrong one
    sends them to the wrong Settings row."""
    if pid == "ollama":
        return
    cfg = copy.deepcopy(cfgmod.DEFAULTS)
    cfg["providers"][pid]["api_key"] = ""

    async def drain():
        async for _ in providers.chat(cfg, f"{pid}/some-model", [], []):
            pass

    with pytest.raises(providers.ProviderError) as e:
        asyncio.run(drain())
    assert "key" in str(e.value).lower()
