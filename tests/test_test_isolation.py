"""A canary for the guard in conftest.py.

`agentos.config` resolves CONFIG_PATH at import time from the real environment,
and `save_config()` writes it. Any test that reaches a code path calling it will
overwrite the developer's own `~/.agentos/config.json` — which has happened, and
cost a live config with provider keys and a paired Telegram owner in it.

If the autouse fixture is ever removed or renamed, this fails immediately and
says why, instead of the suite quietly going back to writing real files.
"""

from pathlib import Path


def test_config_writes_are_redirected_away_from_the_real_home():
    from agentos import config as cfgmod

    real = Path.home() / ".agentos" / "config.json"
    assert cfgmod.CONFIG_PATH != real, (
        "conftest's _never_touch_the_real_config guard is not active — "
        "a test that saves config will overwrite the developer's own")
    assert Path.home() not in cfgmod.AGENTOS_HOME.parents or "agentos-home" in str(cfgmod.AGENTOS_HOME)


def test_saving_config_lands_in_the_throwaway_home():
    from agentos import config as cfgmod

    cfgmod.save_config({"canary": True})
    assert cfgmod.CONFIG_PATH.exists()
    assert '"canary"' in cfgmod.CONFIG_PATH.read_text()
    assert not (Path.home() / ".agentos" / "config.json").read_text().startswith('{\n  "canary"')
