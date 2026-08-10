"""Test-suite guards.

The one here is not a convenience. `agentos.config` resolves `AGENTOS_HOME` and
`CONFIG_PATH` at import time from the real environment, and `save_config()` reads
those module globals — so ANY test that reaches a code path calling it writes the
developer's own `~/.agentos/config.json`. That is not hypothetical: a test for the
Telegram admin console did exactly that, replacing a live 7KB config (provider
keys, the paired Telegram owner, every setting) with a four-key stub built for the
test. It was recoverable only because the running server still held the real one
in memory.

Nothing about the test looked wrong. It built its own `cfg` dict and passed it in
— the write happened three calls deeper, in code whose whole job is to persist
configuration. Which is the point: this cannot be left to each test author
remembering, so it is enforced here for every test, automatically.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _never_touch_the_real_config(tmp_path, monkeypatch):
    """Point every config write at a throwaway directory, for every test."""
    from agentos import config as cfgmod

    home = tmp_path / "agentos-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", home)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", home / "config.json")
    yield
