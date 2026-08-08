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


def test_agentos_does_not_reimplement_a_bridge_hermes_already_has():
    """Slack, Signal, Discord and the rest stay carried by the Hermes gateway. A
    second integration beside a working one is a worse copy of it."""
    native = {c["id"] for c in ch.state(base_cfg())}
    for pid in ("slack", "signal", "discord", "matrix"):
        assert pid not in native, f"{pid} is carried by Hermes, not rebuilt here"
        assert pid in ch.HERMES_PLATFORMS


def test_whatsapp_is_the_one_exception_and_the_two_do_not_pretend_to_be_the_same():
    """The reason is direction, not enthusiasm. Hermes takes messages OUT — a reply
    arriving there is answered by Hermes' own agent with Hermes' memory. The whole
    point of asking for WhatsApp is to reach THIS agent, and delivery-only plumbing
    cannot get there. So both exist, and each says which one it is."""
    native = {c["id"]: c for c in ch.state(base_cfg())}
    assert native["whatsapp"]["gate"] == "whatsapp"          # a way IN, with its own gate
    assert native["whatsapp"]["direction"] == "both"
    assert "reaches THIS agent" in native["whatsapp"]["note"]
    assert "whatsapp" in ch.HERMES_PLATFORMS                  # and still a way OUT


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


# ------------------------------------------------- channels carried by Hermes

def _probe(monkeypatch, result):
    async def fake():
        return result
    monkeypatch.setattr(ch, "hermes_targets", lambda *a, **k: fake())


def test_carried_channels_are_discovered_not_declared(monkeypatch):
    """Configured and working are different things. Hermes' config lists Signal on
    this machine while its gateway has been failing to reach signal-cli every five
    minutes — only the live probe knows the difference."""
    _probe(monkeypatch, {"available": True, "gateway": True, "platforms": {
        "slack": [{"id": "C1", "name": "#ops", "type": "group"}],
        "telegram": [{"id": "PC", "name": "PC", "type": "dm"}]}})
    got = {c["title"]: c for c in asyncio.run(ch.carried_state({}))}
    assert got["Slack"]["status"] == "on" and got["Slack"]["targets"][0]["name"] == "#ops"
    assert got["Signal"]["status"] == "off", "not paired must not read as available"
    assert got["WhatsApp"]["status"] == "off"


def test_carried_channels_say_a_reply_goes_to_hermes_not_this_agent(monkeypatch):
    """Somebody enabling 'WhatsApp' expecting to reach Aria would otherwise be
    quietly talking to a different assistant."""
    _probe(monkeypatch, {"available": True, "platforms": {
        "whatsapp": [{"id": "1", "name": "me", "type": "dm"}]}})
    wa = next(c for c in asyncio.run(ch.carried_state({})) if c["title"] == "WhatsApp")
    assert wa["direction"] == "out"
    assert "Hermes' own agent" in wa["note"]
    assert wa["gate"] == "", "a carried channel has no IO gate here — nothing arrives"


def test_carried_channels_report_why_when_hermes_is_missing(monkeypatch):
    _probe(monkeypatch, {"available": False, "platforms": {},
                         "reason": "Hermes is not installed on this machine"})
    for c in asyncio.run(ch.carried_state({})):
        assert c["status"] == "unavailable"
        assert "not installed" in c["detail"], "never a dead control — say why"


def test_paired_platforms_sort_first(monkeypatch):
    _probe(monkeypatch, {"available": True, "platforms": {
        "whatsapp": [{"id": "1", "name": "me", "type": "dm"}]}})
    titles = [c["title"] for c in asyncio.run(ch.carried_state({}))]
    assert titles[0] == "WhatsApp", "what is actually working belongs at the top"


def test_no_configured_channels_changes_nothing():
    """The feature must be invisible until someone uses it."""
    assert policy.channel_posture({}, "gui") == "inherit"
    assert policy.channel_posture({"channels": {}}, "telegram") == "inherit"
    assert policy.channel_posture({"channels": {"gui": {"posture": "junk"}}}, "gui") == "inherit"
    assert policy.channel_posture({"channels": {"gui": {"posture": "full"}}}, "") == "inherit"
