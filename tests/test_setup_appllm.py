"""Agent-led onboarding + appLLM v2 — config application and runtime surface."""

import inspect
import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import server, setup              # noqa: E402


def _base_cfg():
    return {"agent_name": "Aria", "autonomy": "balanced", "default_model": "",
            "providers": {"anthropic": {}, "openai": {}, "openrouter": {},
                          "ollama": {"base_url": "http://127.0.0.1:11434"}}}


def test_apply_setup_new_fields():
    cfg = _base_cfg()
    rep = setup.apply_setup(cfg, {"agent_name": "Nova", "autonomy": "balanced",
                                  "wallpaper_preset": "aurora", "voice": True})
    assert cfg["agent_name"] == "Nova"
    assert cfg["desktop"]["wallpaper_preset"] == "aurora"
    assert cfg["desktop"]["voice_tts"] is True
    assert any("wallpaper: aurora" in a for a in rep["applied"])


def test_apply_setup_rejects_unknown_preset():
    cfg = _base_cfg()
    setup.apply_setup(cfg, {"wallpaper_preset": "not-a-preset"})
    assert "wallpaper_preset" not in cfg.get("desktop", {})


def test_say_fallback_covers_every_wizard_step():
    # the JS drives these step ids; a missing key would show the 'done' line mid-flow
    for step in ("autonomy", "autostart", "de_here", "wallpaper", "voice", "done"):
        assert step in server.SAY_FALLBACK, step
        assert "{name}" in server.SAY_FALLBACK["autonomy"]


def test_app_runtime_exposes_v2_helpers():
    src = inspect.getsource(server)
    for marker in ("appLLM.stream", "window.appChat", "window.appAgent",
                   "window.appContext"):
        assert marker in src, f"injected app runtime lost {marker}"


def test_builder_persona_teaches_v2_patterns():
    p = server.BUILDER_PERSONA
    assert "appLLM.stream" in p
    assert "appChat" in p
    assert "appAgent" in p
    assert "FLOOR" in p          # "textarea + ✨ button" is the floor, not the ceiling


def test_setup_state_shape():
    # the wizard's first fetch — keys the new JS depends on
    sig = inspect.getsource(server.api_setup_state)
    for key in ("first_run", "agent_name", "ollama_models", "providers"):
        assert key in sig
