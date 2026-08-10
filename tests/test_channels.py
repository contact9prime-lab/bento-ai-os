"""Channels — the catalogue of ways in, and the trust ceiling each one carries.

The interesting assertions here are the refusals. A channel panel that cheerfully
accepts a setting it will never enforce is worse than one that has no setting: it
tells you the machine is locked down when it is not.
"""

import asyncio

import pytest

from agentos import channels as ch
from agentos import policy


def base_cfg():
    return {"autonomy": "balanced", "telegram": {"enabled": False, "bot_token": ""},
            "remote": {"enabled": False}}


# --------------------------------------------------------------- the catalogue

def test_every_channel_reports_who_can_use_it():
    """'Who can speak through this' is the whole point — none may be blank."""
    for c in ch.state(base_cfg()):
        assert c["reach"].strip(), f"{c['id']} does not say who can use it"
        assert c["what"].strip(), f"{c['id']} does not say what it is"


def test_the_three_faces_are_all_channels():
    ids = {c["id"] for c in ch.state(base_cfg())}
    assert {"gui", "tui", "sui"} <= ids
    assert {"api", "remote", "task", "telegram"} <= ids


def test_gates_are_real_policy_surfaces():
    """A channel's gate must be one the PDP actually knows, or its posture is fiction."""
    for c in ch.CATALOGUE:
        assert c.gate in policy.SURFACES, f"{c.id} points at unknown gate {c.gate!r}"


def test_every_channel_offered_reaches_this_agent():
    """The rule that replaced the carried tier.

    Channels used to come in two kinds: native ones that brought a conversation to
    this agent, and "carried" ones proxied to another agent's gateway that could
    only deliver OUT. The second kind is gone. A channel is offered here only if
    AgentOS owns it end to end — so "WhatsApp: on" can never again mean a different
    assistant is answering.
    """
    for c in ch.state(base_cfg()):
        assert c["direction"] == "both", f"{c['id']} does not reach this agent"
        assert c["carrier"] == "", f"{c['id']} is proxied to something else"
        assert c["gate"] in policy.SURFACES, f"{c['id']} arrives through no IO gate"


def test_whatsapp_is_a_way_in_with_its_own_gate():
    native = {c["id"]: c for c in ch.state(base_cfg())}
    assert native["whatsapp"]["gate"] == "whatsapp"
    assert native["whatsapp"]["direction"] == "both"
    assert "reaches THIS agent" in native["whatsapp"]["note"]
    # and nothing else is offered: one messenger, the one people actually ask
    # for. A second bridge is a second thing to keep working.
    for pid in ("slack", "signal", "discord", "matrix"):
        assert pid not in native, f"{pid} is not a channel this OS implements"


def test_the_removed_carrier_surface_is_really_gone():
    """A half-removal leaves a module attribute some surface still calls."""
    for gone in ("HERMES_PLATFORMS", "hermes_targets", "carried_state"):
        assert not hasattr(ch, gone), f"channels.{gone} survived the removal"



# ------------------------------------------------------------------- refusals

def test_builtin_channels_cannot_be_switched_off():
    """Switching off the window you are reading this in is a lockout, not a setting."""
    for cid in ("gui", "tui", "task"):
        ok, msg = ch.save(base_cfg(), cid, {"enabled": False})
        assert not ok and "cannot be switched off" in msg


def test_shared_gate_channels_refuse_a_posture_they_could_not_enforce():
    """remote/sui arrive on the 'gui' gate, so their own posture would never be read."""
    for cid in ("remote", "sui"):
        ok, msg = ch.save(base_cfg(), cid, {"posture": "read_only"})
        assert not ok and "same gate" in msg


def test_shared_gate_channels_report_the_posture_actually_in_force():
    cfg = base_cfg()
    assert ch.save(cfg, "gui", {"posture": "read_only"})[0]
    remote = next(c for c in ch.state(cfg) if c["id"] == "remote")
    assert remote["posture"] == "read_only"
    assert remote["posture_from"] == "This window"
    assert not remote["own_gate"]


def test_enabling_an_unconfigured_channel_is_refused_by_name():
    cfg = base_cfg()
    ok, msg = ch.save(cfg, "telegram", {"enabled": True})
    assert not ok and "Bot token" in msg
    assert not cfg["channels"]["telegram"]["enabled"], "must not half-enable"
    assert not cfg["telegram"]["enabled"], "legacy block must not drift out of step"


def test_unknown_channel_and_unknown_posture_are_refused():
    assert not ch.save(base_cfg(), "carrier-pigeon", {"posture": "full"})[0]
    assert not ch.save(base_cfg(), "telegram", {"posture": "whenever"})[0]


# -------------------------------------------------------------------- secrets

def test_a_saved_secret_is_never_handed_back():
    cfg = base_cfg()
    ch.save(cfg, "telegram", {"bot_token": "123456:REAL-SECRET"})
    tg = next(c for c in ch.state(cfg) if c["id"] == "telegram")
    assert tg["set"]["bot_token"] is True
    assert tg["values"]["bot_token"] == ""
    assert "REAL-SECRET" not in str(tg)


def test_a_blank_secret_means_leave_it_alone_not_erase_it():
    """The UI shows a saved secret as a chip with no input, so '' is the normal
    state of a configured channel — treating it as 'clear' would wipe the token
    every time someone saved an unrelated change on the same card."""
    cfg = base_cfg()
    ch.save(cfg, "telegram", {"bot_token": "123456:KEEP"})
    ch.save(cfg, "telegram", {"bot_token": ""})
    assert cfg["channels"]["telegram"]["bot_token"] == "123456:KEEP"


def test_telegram_writes_through_to_the_block_the_poller_reads():
    cfg = base_cfg()
    ch.save(cfg, "telegram", {"bot_token": "123456:ABC"})
    ok, _ = ch.save(cfg, "telegram", {"enabled": True})
    assert ok
    assert cfg["telegram"]["enabled"] is True
    assert cfg["telegram"]["bot_token"] == "123456:ABC"


# ------------------------------------------------------- the posture is real

class _Store:
    """Grants that say 'allow everything, everywhere'."""
    grants_version = 1

    def grants_live(self):
        return [{"id": "g1", "principal_kind": "*", "principal_id": "*",
                 "action": "tool.use", "resource": "*", "effect": "allow",
                 "surfaces": "*", "note": "allow everywhere"}]


@pytest.mark.parametrize("posture,risk,expect", [
    ("read_only", "risky", "deny"),    # refused, not queued: nobody may be watching
    ("read_only", "safe", "allow"),    # reading is exactly what read-only is for
    ("ask", "risky", "ask"),
    ("full", "risky", "allow"),
    ("inherit", "risky", "ask"),       # falls back to the machine's autonomy
])
def test_posture_decides_what_a_channel_may_do(posture, risk, expect):
    cfg = {"autonomy": "balanced", "channels": {"telegram": {"posture": posture}}}
    pdp = policy.PDP(cfg, _Store())
    dec = pdp.decide_tool(policy.MAIN, "write_file", {"path": "/x"}, risk,
                          "writes a file", surface="telegram")
    assert dec.effect == expect


def test_read_only_outranks_a_grant_that_allows_everything_everywhere():
    """A ceiling that a broad grant could punch through would not be a ceiling.
    Narrowing a way in must not be silently undone by consent given at the desk."""
    cfg = {"autonomy": "full", "channels": {"telegram": {"posture": "read_only"}}}
    pdp = policy.PDP(cfg, _Store())
    dec = pdp.decide_tool(policy.MAIN, "write_file", {"path": "/x"}, "risky",
                          "writes", surface="telegram")
    assert dec.effect == "deny"
    assert dec.rule == "channel-read-only"
    assert "read-only" in dec.reason and "Channels" in dec.reason


def test_a_posture_on_one_channel_does_not_leak_to_another():
    cfg = {"autonomy": "balanced", "channels": {"telegram": {"posture": "read_only"}}}
    pdp = policy.PDP(cfg, _Store())
    for surface in ("gui", "tui", "api", "task"):
        dec = pdp.decide_tool(policy.MAIN, "write_file", {"path": "/x"}, "risky",
                              "writes", surface=surface)
        assert dec.effect != "deny", f"{surface} was caught by telegram's ceiling"


def test_no_configured_channels_changes_nothing():
    """The feature must be invisible until someone uses it."""
    assert policy.channel_posture({}, "gui") == "inherit"
    assert policy.channel_posture({"channels": {}}, "telegram") == "inherit"
    assert policy.channel_posture({"channels": {"gui": {"posture": "junk"}}}, "gui") == "inherit"
    assert policy.channel_posture({"channels": {"gui": {"posture": "full"}}}, "") == "inherit"


# ------------------------------------------------- removal migration

def test_a_config_pinned_to_a_removed_engine_still_answers(tmp_path, monkeypatch):
    """A machine set to forward to Hermes must not be left answering with nothing."""
    import json
    from agentos import config as cfgmod
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"engine": "hermes",
                             "hermes": {"repo": "x", "engine_enabled": True}}))
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", p)
    cfg = cfgmod.load_config()
    assert cfg["engine"] == "aria"
    assert "hermes" not in cfg, "a setting for a removed feature reads as 'switched off'"


def test_the_migration_leaves_a_real_engine_alone():
    from agentos import config as cfgmod
    assert cfgmod.load_config().get("engine") in ("", None, "aria", "claude-code")
