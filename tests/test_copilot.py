"""The ever-present agent — server seams for omnibar + copilot panels."""

import inspect
import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import server                     # noqa: E402
from agentos.agent import Agent                # noqa: E402
from agentos.memory import Store               # noqa: E402


def test_run_chat_passes_context_as_extra_system():
    src = inspect.getsource(server.run_chat)
    assert "extra_system=extra" in src
    assert "[:4096]" in src                       # UI-supplied context is capped


def test_agent_extra_system_is_appended():
    assert "extra_system" in inspect.signature(Agent.__init__).parameters


def test_ws_chat_origin_allowlist():
    # only user / omni / copilot:<app> may tag a conversation's origin from the UI
    src = inspect.getsource(server)
    assert 'origin.startswith("copilot:")' in src
    assert '"origin": origin' in src              # the conversation event announces it


def test_conversations_carry_origin(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_conversation("desk", origin="omni")
    store.create_conversation("files thread", origin="copilot:files")
    rows = store.list_conversations()
    origins = {r["title"]: r["origin"] for r in rows}
    assert origins["desk"] == "omni"
    assert origins["files thread"] == "copilot:files"


def test_app_runtime_ships_copilot_widget():
    assert "appCopilot" in server.APP_RUNTIME
    assert "appCopilot.mount" in server.APP_RUNTIME
    # the %-template must render without KeyError/ValueError from stray %
    rendered = server.APP_RUNTIME % ("demo", "tok")
    assert "window.APP_ID = 'demo'" in rendered
    assert "acp-fab" in rendered


def test_builder_persona_mandates_copilot():
    assert "appCopilot.mount" in server.BUILDER_PERSONA
