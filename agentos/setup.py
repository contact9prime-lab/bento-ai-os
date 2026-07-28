"""First-run setup: one shared apply step, driven by the UI wizard, `agentos setup`,
or the TUI's first-launch prompt. Also powers factory reset (Settings → Start fresh)."""

import asyncio

from . import config as cfgmod


#: gradient wallpaper presets the wizard offers in de mode — CSS gradients rendered by
#: the shell's fallback mesh, so choosing one writes config only (never a wallpaper.png)
WALLPAPER_PRESETS = ("aurora", "dusk", "ember", "deep")


def apply_setup(cfg: dict, choices: dict) -> dict:
    """Apply wizard choices to the live config and (optionally) install autostart.
    choices: {agent_name, autonomy, default_model, providers: {anthropic|openai|openrouter:
    {api_key, model?}}, autostart: bool, open_at_login: bool,
    wallpaper_preset?: str (de mode; stored in cfg['desktop'], the shell renders it —
    no file is written), voice?: bool (TTS; the browser shell also mirrors it into its
    client-side VOICE setting)}
    Returns a report of what happened (shown at the wizard's finish step)."""
    report = {"applied": [], "autostart": None, "boot": None}
    if (choices.get("agent_name") or "").strip():
        cfg["agent_name"] = choices["agent_name"].strip()
        report["applied"].append(f"agent name: {cfg['agent_name']}")
    if choices.get("autonomy") in ("paranoid", "balanced", "full"):
        cfg["autonomy"] = choices["autonomy"]
        report["applied"].append(f"autonomy: {cfg['autonomy']}")
    for prov, pconf in (choices.get("providers") or {}).items():
        if prov not in cfg["providers"] or not isinstance(pconf, dict):
            continue
        key = (pconf.get("api_key") or "").strip()
        if key and not key.startswith("•••"):
            cfg["providers"][prov]["api_key"] = key
            cfg["providers"][prov]["enabled"] = True
            report["applied"].append(f"provider: {prov}")
    if (choices.get("default_model") or "").strip():
        cfg["default_model"] = choices["default_model"].strip()
        report["applied"].append(f"model: {cfg['default_model']}")
    if choices.get("wallpaper_preset") in WALLPAPER_PRESETS:
        cfg.setdefault("desktop", {})["wallpaper_preset"] = choices["wallpaper_preset"]
        report["applied"].append(f"wallpaper: {choices['wallpaper_preset']}")
    if isinstance(choices.get("voice"), bool):
        cfg.setdefault("desktop", {})["voice_tts"] = choices["voice"]
        report["applied"].append(f"voice: {'on' if choices['voice'] else 'off'}")

    if choices.get("autostart"):
        # launcher + platform background service (systemd / LaunchAgent / Startup entry)
        from . import desktop
        try:
            desktop.install(autostart=True, open_at_login=bool(choices.get("open_at_login", True)))
            report["autostart"], report["boot"] = desktop.autostart_report()
        except Exception as e:
            report["autostart"] = f"failed: {type(e).__name__}: {e}"

    cfgmod.mark_setup_complete(cfg)
    return report


def factory_reset(cfg: dict, store) -> None:
    """Back to day one: wipe all data, reset config to defaults, delete the soul.
    The next load shows the wizard (setup_complete=false is written explicitly)."""
    store.factory_reset()
    cfgmod.SOUL_PATH.unlink(missing_ok=True)
    # rebuild defaults in place so every live reference (toolbox, scheduler, …) sees them
    import copy
    defaults = copy.deepcopy(cfgmod.DEFAULTS)
    cfg.clear()
    cfg.update(defaults)
    cfg["setup_complete"] = False
    cfgmod.save_config(cfg)
    from . import fabric as fabricmod
    fabricmod.seed_builtins(cfg, store)
    store.log("system", "factory reset — awaiting first-run setup")


# ---------------------------------------------------------------------------
# Terminal wizard (agentos setup / first launch of the TUI)
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    tag = f" [{default}]" if default else ""
    val = input(f"  {prompt}{tag}: ").strip()
    return val or default


def run_cli_wizard() -> None:
    from . import localeinfo
    from . import providers
    cfg = cfgmod.load_config()
    print("\n▲ AgentOS first-time setup — five quick questions.\n")

    name = _ask("1/5  Name your agent", cfg.get("agent_name") or "Aria")

    local = asyncio.run(providers.ollama_models(cfg["providers"]["ollama"]["base_url"]))
    model, prov_choices = "", {}
    if local:
        print("\n  2/5  Pick your agent's brain (local Ollama models found):")
        for i, m in enumerate(local, 1):
            print(f"       {i}. ollama/{m}")
        print("       c. use a cloud model instead (API key)")
        pick = _ask("Choice", "1")
        if pick.lower() != "c" and pick.isdigit() and 1 <= int(pick) <= len(local):
            model = f"ollama/{local[int(pick) - 1]}"
    if not model:
        print("\n  2/5  Cloud model — pick a provider:  1. Anthropic  2. OpenAI  3. OpenRouter")
        prov = {"1": "anthropic", "2": "openai", "3": "openrouter"}.get(_ask("Provider", "1"), "anthropic")
        key = _ask(f"{prov} API key")
        if key:
            prov_choices[prov] = {"api_key": key}
            default_models = {"anthropic": "claude-sonnet-5", "openai": "gpt-4o",
                              "openrouter": "anthropic/claude-sonnet-4.5"}
            model = f"{prov}/{_ask('Model', default_models[prov])}"
        else:
            print("  (no key — you can add one later in Settings)")

    print("\n  3/5  Autonomy — how much can the agent do without asking?")
    print("       1. paranoid (ask for everything)  2. balanced (ask for risky)  3. full (never ask)")
    autonomy = {"1": "paranoid", "2": "balanced", "3": "full"}.get(_ask("Choice", "2"), "balanced")

    auto = _ask("4/5  Start AgentOS automatically at boot/login? (y/n)", "y").lower().startswith("y")

    # voice parity with the UI wizard; the wallpaper question is desktop-only and skipped here
    voice = _ask("5/5  Speak replies aloud in the desktop UI? (y/n)", "n").lower().startswith("y")

    report = apply_setup(cfg, {"agent_name": name, "autonomy": autonomy, "default_model": model,
                               "providers": prov_choices, "autostart": auto,
                               "open_at_login": auto, "voice": voice})
    print("\n✓ Setup complete:")
    for line in report["applied"]:
        print(f"    · {line}")
    if report["autostart"]:
        print(f"    · autostart: {report['autostart']}")
    if report["boot"]:
        print(f"    · boot: {report['boot']}")
    print("\n  Run `agentos` for the desktop UI, `agentos tui` for this terminal UI,")
    print("  or `agentos ask \"...\"` for one-shot tasks. Docs: 📖 Docs app / tab 8 in the TUI.\n")
