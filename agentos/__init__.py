"""AgentOS — a local-first agentic OS."""

from pathlib import Path

# ONE place the version is written: `agentos/VERSION`, next to this file.
#
# It lives inside the package rather than at the repo root so a wheel carries it
# too, and it is a plain file rather than a constant here because the update
# checker has to read the SAME number from a remote checkout without importing
# it. `tests/test_version.py` asserts pyproject.toml agrees, so a release bumps
# one line and drift is a test failure rather than a support question.
try:
    __version__ = (Path(__file__).parent / "VERSION").read_text().strip()
except OSError:                      # pragma: no cover — a broken install
    __version__ = "0.0.0"
