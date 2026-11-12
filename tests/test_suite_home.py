"""The suite runs on a home of its own (tests/conftest.py).

A run once left five test rows in the developer's real machine ledger, because the in-process
server opened `config.DB_PATH` at import and that was ~/.agentos/agentos.db. The chain stopped
verifying and the machine's Telegram warned about it every twenty minutes.
"""
import os
from pathlib import Path


def test_the_suite_never_opens_the_real_home():
    from agentos import config as cfgmod
    real = (Path.home() / ".agentos").resolve()
    assert Path(os.environ["AGENTOS_HOME"]).resolve() != real
    assert cfgmod.DB_PATH.parent.resolve() != real
