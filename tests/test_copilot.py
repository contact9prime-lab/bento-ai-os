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
    rendered = server.APP_RUNTIME % ("demo", "tok", "desktop", "m")
    assert "window.APP_ID = 'demo'" in rendered
    assert "acp-fab" in rendered


def test_builder_persona_mandates_copilot():
    assert "appCopilot.mount" in server.BUILDER_PERSONA


# --- widget mode: every app has two surfaces --------------------------------

def test_the_runtime_tells_an_app_which_surface_it_is_on():
    """An app has to know before its own code runs, or it renders the desktop
    view for a frame inside a 260px widget."""
    widget = server.APP_RUNTIME % ("demo", "tok", "widget", "s")
    assert "window.appSurface" in widget
    assert "'widget'" in widget and "'s'" in widget
    assert "agentos-widget-" in widget
    desktop = server.APP_RUNTIME % ("demo", "tok", "desktop", "m")
    assert "'desktop'" in desktop


def test_the_design_system_shows_exactly_one_surface():
    css = server.APP_UI_CSS
    assert 'html[data-surface="desktop"] .widget-only{display:none!important}' in css
    assert 'html[data-surface="widget"] .desktop-only{display:none!important}' in css


def test_the_builder_is_told_to_build_both_surfaces():
    p = server.BUILDER_PERSONA
    assert "widget-only" in p and "desktop-only" in p
    assert "window.appSurface" in p


def test_widget_size_is_a_property_of_the_app(tmp_path):
    """Pinned twice on two desktops, an app must look the same in both — so the
    size belongs to the app, not to the placement."""
    from agentos.memory import Store
    st = Store(tmp_path / "t.db")
    aid = st.save_app("Ticker", "", "stocks", "<p>hi</p>")
    assert st.get_app(aid)["widget_size"] == "m"          # every app has one
    assert st.rename_app(aid, widget_size="l") is None
    assert st.get_app(aid)["widget_size"] == "l"
    st.rename_app(aid, widget_size="enormous")            # nonsense falls back
    assert st.get_app(aid)["widget_size"] == "m"
    assert st.list_apps()[0]["widget_size"] == "m"        # the shell can read it
