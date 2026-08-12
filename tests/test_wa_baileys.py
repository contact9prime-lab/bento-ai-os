"""The WhatsApp Web (Baileys) transport.

Offline by design: none of this starts Node, talks to WhatsApp, or scans anything.
What is worth testing is the seam — that a linked-device message becomes exactly the
shape the Cloud API webhook produces, so `WhatsAppBridge._one` cannot tell the two
transports apart. If that reshaping drifts, pairing, the allow-list, commands, flow
triggers and approvals silently stop applying on one of the two paths.
"""

import asyncio

import pytest

from agentos import components, wa_baileys, whatsapp as wamod


def base_cfg(**over):
    cfg = {"channels": {"whatsapp": {}}, "whatsapp": {}}
    cfg["channels"]["whatsapp"].update(over)
    return cfg


# ---- which transport, and what each one needs -----------------------------------

def test_cloud_is_the_default_so_a_working_install_keeps_working():
    assert wamod.mode({}) == "cloud"
    assert wamod.mode(base_cfg(mode="baileys")) == "baileys"


def test_configured_asks_the_right_question_per_transport(monkeypatch):
    """A QR-paired link has no phone_number_id, and demanding one would report
    'not set up' on a channel that is working."""
    cloud = base_cfg(phone_number_id="1", access_token="t", verify_token="v")
    assert wamod.configured(cloud)
    monkeypatch.setattr(wa_baileys, "installed", lambda: True)
    monkeypatch.setattr(wa_baileys, "paired", lambda: True)
    assert wamod.configured(base_cfg(mode="baileys"))
    monkeypatch.setattr(wa_baileys, "paired", lambda: False)
    assert not wamod.configured(base_cfg(mode="baileys"))


def test_a_linked_device_needs_nothing_public():
    """The Cloud API needs Meta to reach this machine. A linked device dials out,
    so reporting 'turn on a tunnel' there would be a fix for a problem it has not
    got."""
    reach = asyncio.run(wamod.reachability(base_cfg(mode="baileys")))
    assert reach["reachable"] is True and reach["why"] == ""
    assert reach["webhook"] == ""      # nothing to paste into Meta's console


def test_why_not_names_the_missing_piece(monkeypatch):
    monkeypatch.setattr(wa_baileys, "node_path", lambda: "")
    assert "Node.js" in wa_baileys.why_not()
    monkeypatch.setattr(wa_baileys, "node_path", lambda: "/usr/bin/node")
    monkeypatch.setattr(wa_baileys, "NODE_MODULES", wa_baileys.BRIDGE_DIR / "nope")
    assert "not been downloaded" in wa_baileys.why_not()


# ---- the seam: a Baileys message must look like a Meta webhook message ----------

def _transport(seen):
    async def on_message(msg, val):
        seen.append((msg, val))
    return wa_baileys.BaileysTransport(on_message=on_message)


def test_a_text_message_arrives_in_the_cloud_api_shape():
    seen = []
    t = _transport(seen)
    asyncio.run(t._inbound({"from": "919812345678", "text": "  hello  ",
                            "name": "Piyush", "id": "AAA", "kind": "text"}))
    (msg, val), = seen
    assert msg["from"] == "919812345678"
    assert msg["type"] == "text"
    assert msg["text"]["body"] == "hello"          # trimmed, like the webhook path
    assert val["contacts"][0]["profile"]["name"] == "Piyush"


def test_a_numbered_reply_becomes_the_button_tap_answer_expects():
    """No interactive buttons on a linked device, so approvals fall back to 1/2/3.
    They must arrive as the `ap:<aid>:<value>` ids `_answer` parses — an earlier
    version invented ids like "deny", which `_answer` silently ignored, so every
    approval on this transport would have hung until it timed out."""
    for reply, value in (("1", "0"), ("2", "1"), ("3", "2")):
        seen = []
        t = _transport(seen)
        t.pending_button = lambda v: f"ap:abc123:{v}"
        asyncio.run(t._inbound({"from": "91", "text": reply}))
        (msg, _), = seen
        assert msg["type"] == "interactive"
        assert msg["interactive"]["button_reply"]["id"] == f"ap:abc123:{value}"


def test_a_digit_with_nothing_pending_is_just_a_message():
    """Texting "2" to your own agent must reach it as a sentence, not vanish into
    an approval slot that nobody opened."""
    seen = []
    t = _transport(seen)          # default pending_button returns "" — nothing waiting
    asyncio.run(t._inbound({"from": "91", "text": "2"}))
    (msg, _), = seen
    assert msg["type"] == "text" and msg["text"]["body"] == "2"


def test_a_normal_message_is_not_mistaken_for_an_approval():
    seen = []
    asyncio.run(_transport(seen)._inbound({"from": "91", "text": "12"}))
    (msg, _), = seen
    assert msg["type"] == "text" and msg["text"]["body"] == "12"


def test_pending_button_targets_the_approval_that_is_waiting():
    import asyncio as _a
    async def go():
        async def bc(_):
            pass
        b = wamod.WhatsAppBridge(base_cfg(mode="baileys"), _Store(), None, bc)
        assert b.pending_button("1") == ""            # nothing asked yet
        fut = _a.get_event_loop().create_future()
        b._pending["dead"] = _a.get_event_loop().create_future()
        b._pending["dead"].set_result("0")            # already answered
        b._pending["live"] = fut
        assert b.pending_button("1") == "ap:live:1"
        fut.cancel()
    _a.run(go())


def test_non_text_keeps_its_kind_so_the_bridge_can_say_so():
    """`_one` answers 'I can only read text' for these — it needs the kind."""
    seen = []
    asyncio.run(_transport(seen)._inbound({"from": "91", "text": "",
                                           "kind": "audioMessage"}))
    (msg, _), = seen
    assert msg["type"] == "audioMessage" and msg["text"]["body"] == ""


def test_a_message_with_no_sender_is_dropped():
    seen = []
    asyncio.run(_transport(seen)._inbound({"text": "hi"}))
    assert seen == []


def test_inbound_failures_do_not_kill_the_link():
    """One bad turn must not take down the transport that would report it."""
    async def boom(msg, val):
        raise RuntimeError("turn blew up")
    t = wa_baileys.BaileysTransport(on_message=boom)
    asyncio.run(t._inbound({"from": "91", "text": "hi"}))   # must not raise


# ---- the 24-hour window belongs to the Business API only ------------------------

class _Store:
    def wa_get_chat(self, wa_id):
        return {"last_inbound": 0}          # ancient: closed on the Cloud API
    def log(self, *a, **k):
        pass


def test_the_24_hour_window_is_not_invented_for_a_linked_device():
    async def bc(_):
        pass
    cloud = wamod.WhatsAppBridge(base_cfg(owner_wa_id="91"), _Store(), None, bc)
    assert cloud.window_open("91") is False
    link = wamod.WhatsAppBridge(base_cfg(mode="baileys", owner_wa_id="91"),
                                _Store(), None, bc)
    assert link.window_open("91") is True


# ---- the component is offered, with the warning in view -------------------------

def test_the_bridge_is_offered_not_shipped():
    comp = components.CATALOG["whatsapp-bridge"]
    assert comp["group"] == "optional"          # never required, never recommended
    assert "MIT" in comp["licence"]


def test_the_consent_text_states_the_ban_risk():
    """An unofficial bridge that can get somebody's account banned has to say so
    before it installs, not in a doc they will not read."""
    unlocks = components.CATALOG["whatsapp-bridge"]["unlocks"].lower()
    assert "unofficial" in unlocks
    assert "ban" in unlocks


def test_a_machine_without_node_is_told_that_and_not_something_useless(monkeypatch):
    monkeypatch.setattr(wa_baileys, "npm_path", lambda: "")
    comp = components.CATALOG["whatsapp-bridge"]
    assert components.install_argv(comp) == []
    assert "Node.js" in components.unavailable_reason(comp)


def test_the_install_never_touches_anything_global(monkeypatch):
    monkeypatch.setattr(wa_baileys, "npm_path", lambda: "/usr/bin/npm")
    argv = components.install_argv(components.CATALOG["whatsapp-bridge"])
    assert "--prefix" in argv and str(wa_baileys.BRIDGE_DIR) in argv
    assert "-g" not in argv and "--global" not in argv


# ---- credentials -----------------------------------------------------------------

def test_forget_session_removes_the_device_credentials(tmp_path, monkeypatch):
    d = tmp_path / "session"
    d.mkdir()
    (d / "creds.json").write_text("{}")
    # `session_dir()` and not a constant: the credentials follow the ACCOUNT now,
    # so where they live is a question with an answer that depends on who is asking.
    monkeypatch.setattr(wa_baileys, "session_dir", lambda: d)
    assert wa_baileys.paired() is True
    assert wa_baileys.forget_session() is True
    assert wa_baileys.paired() is False
    assert wa_baileys.forget_session() is False


def test_the_approval_prompt_says_how_to_answer_it():
    p = wa_baileys.approval_prompt("run_command", "it wants to run rm")
    for token in ("1", "2", "3", "run_command"):
        assert token in p
