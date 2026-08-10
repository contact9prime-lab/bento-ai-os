"""WhatsApp as a native channel: the webhook, the pairing, and the 24-hour window.

Most of this file is about refusals. The webhook is one of two routes in the OS
meant to be reachable from the open internet, so its signature check is asserted
here rather than assumed — including the specific mistake that gets the check
deleted instead of fixed, which is verifying a re-serialised body.

The other half is the 24-hour customer-service window. It is the one thing about
WhatsApp that a port of the Telegram bridge gets wrong for free, and it is the one
that produces a silent 08:00 failure rather than a visible one.
"""

import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import whatsapp as wa                                 # noqa: E402
from agentos.memory import Store                                   # noqa: E402

SECRET = "s3cr3t-app-secret"
# Everything above the link-transport section is about the CLOUD transport, so it
# says so rather than relying on a default. `link` is what a fresh machine gets.
CFG = {"channels": {"whatsapp": {
    "mode": "cloud", "enabled": True, "phone_number_id": "111", "access_token": "tok",
    "app_secret": SECRET, "verify_token": "let-me-in"}}}
CLOUD = {"channels": {"whatsapp": {"mode": "cloud"}}}


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def envelope(text: str, frm: str = "919812345678", mid: str = "wamid.1") -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": frm, "profile": {"name": "Piyush"}}],
        "messages": [{"from": frm, "id": mid, "type": "text",
                      "text": {"body": text}}]}}]}]}


# ---------------------------------------------------------------------------
# The signature, over the raw bytes
# ---------------------------------------------------------------------------

def test_a_correct_signature_passes():
    raw = json.dumps(envelope("hello")).encode()
    assert wa.verify_signature(SECRET, raw, sign(raw))


def test_a_signature_from_the_wrong_secret_is_refused():
    raw = b'{"a":1}'
    assert not wa.verify_signature(SECRET, raw, sign(raw, "not-the-secret"))


def test_no_signature_header_is_refused():
    assert not wa.verify_signature(SECRET, b"{}", "")


def test_no_app_secret_means_no_trust_rather_than_no_check():
    """An unverifiable public endpoint is refused, not waved through. This is the
    one route a stranger can POST to."""
    assert not wa.verify_signature("", b"{}", sign(b"{}"))


def test_the_signature_is_over_the_bytes_as_received_not_the_reparsed_json():
    """Re-serialising changes key order and whitespace, so a check written against
    the parsed body fails on every real delivery — and then gets removed rather
    than fixed. This test is the reason the route reads request.body()."""
    raw = b'{"b":2,  "a":1}'
    header = sign(raw)
    assert wa.verify_signature(SECRET, raw, header)
    reserialised = json.dumps(json.loads(raw)).encode()
    assert reserialised != raw
    assert not wa.verify_signature(SECRET, reserialised, header)


def test_the_sha256_prefix_is_optional_because_meta_sends_it():
    raw = b"{}"
    bare = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert wa.verify_signature(SECRET, raw, bare)
    assert wa.verify_signature(SECRET, raw, "sha256=" + bare)


# ---------------------------------------------------------------------------
# The verify handshake
# ---------------------------------------------------------------------------

@pytest.fixture()
def bridge(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    store = Store(tmp_path / "wa.db")
    sent: list = []

    class _TB:
        fabric = None

    b = wa.WhatsAppBridge(cfg, store, _TB(), lambda ev: asyncio.sleep(0))

    async def fake_send(text, wa_id=None):
        sent.append((wa_id, text))
        return "sent via WhatsApp"
    b.send = fake_send                       # no network in tests
    return b, store, cfg, sent


def test_the_handshake_echoes_the_challenge_for_the_right_token(bridge):
    b, *_ = bridge
    assert b.verify_challenge("subscribe", "let-me-in", "1234") == "1234"


@pytest.mark.parametrize("mode,token", [
    ("subscribe", "wrong"), ("unsubscribe", "let-me-in"), ("subscribe", ""),
])
def test_the_handshake_refuses_anything_else(bridge, mode, token):
    b, *_ = bridge
    assert b.verify_challenge(mode, token, "1234") is None


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------

def test_the_first_number_to_write_becomes_the_owner(bridge, monkeypatch):
    b, store, cfg, sent = bridge
    monkeypatch.setattr(wa.cfgmod, "save_config", lambda _c: None)
    asyncio.run(b.handle(envelope("hi")))
    assert cfg["whatsapp"]["owner_wa_id"] == "919812345678"
    assert store.wa_get_chat("919812345678")["allowed"] == 1
    assert "Linked" in sent[0][1]


def test_a_second_number_is_told_this_machine_is_not_theirs(bridge, monkeypatch):
    b, store, cfg, sent = bridge
    monkeypatch.setattr(wa.cfgmod, "save_config", lambda _c: None)
    asyncio.run(b.handle(envelope("hi")))
    sent.clear()
    asyncio.run(b.handle(envelope("hello?", frm="447700900000", mid="wamid.2")))
    assert store.wa_get_chat("447700900000")["allowed"] == 0
    assert "not enabled" in sent[0][1]


def test_a_redelivered_message_does_not_start_a_second_turn(bridge, monkeypatch):
    """Meta retries. Without the id check, one sentence becomes several agent runs
    — and the user is billed for each of them."""
    b, store, cfg, sent = bridge
    monkeypatch.setattr(wa.cfgmod, "save_config", lambda _c: None)
    asyncio.run(b.handle(envelope("hi", mid="wamid.same")))
    n = len(sent)
    asyncio.run(b.handle(envelope("hi", mid="wamid.same")))
    assert len(sent) == n


def test_a_photo_is_answered_rather_than_swallowed(bridge, monkeypatch):
    """An assistant that never replies to a photo reads as broken, not as limited."""
    b, store, cfg, sent = bridge
    monkeypatch.setattr(wa.cfgmod, "save_config", lambda _c: None)
    env = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "919812345678", "id": "wamid.img", "type": "image",
         "image": {"id": "abc"}}]}}]}]}
    asyncio.run(b.handle(env))
    assert "only read text" in sent[0][1]


# ---------------------------------------------------------------------------
# The 24-hour window
# ---------------------------------------------------------------------------

def test_the_window_opens_on_an_inbound_message_only(tmp_path):
    """A message WE sent does not reopen it — that is precisely what Meta's rule
    says, and getting it wrong means promising a delivery that will be refused."""
    store = Store(tmp_path / "w.db")
    store.wa_upsert_chat("911", "P")
    chat = store.wa_get_chat("911")
    assert time.time() - chat["last_inbound"] < 5
    store.wa_set_conversation("911", "c1")          # any other write
    assert store.wa_get_chat("911")["last_inbound"] == chat["last_inbound"]


def test_a_silent_chat_is_refused_with_the_reason_and_the_fix(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    cfg["whatsapp"] = {"owner_wa_id": "911"}
    store = Store(tmp_path / "w.db")
    store.wa_upsert_chat("911", "P")
    store.db.execute("UPDATE whatsapp_chats SET last_inbound=? WHERE wa_id=?",
                     (time.time() - wa.WINDOW_SECS - 60, "911"))
    store.db.commit()

    class _TB:
        fabric = None
    b = wa.WhatsAppBridge(cfg, store, _TB(), lambda ev: asyncio.sleep(0))
    assert not b.window_open("911")
    out = asyncio.run(b.send("the morning brief"))
    assert out.startswith("[error]")
    assert "24 hours" in out and "reopen" in out


def test_an_unconfigured_channel_says_what_is_missing_not_a_stack_trace(tmp_path):
    store = Store(tmp_path / "w.db")

    class _TB:
        fabric = None
    b = wa.WhatsAppBridge(json.loads(json.dumps(CLOUD)), store, _TB(),
                          lambda ev: asyncio.sleep(0))
    assert "not set up" in asyncio.run(b.send("hello"))


def test_configured_but_unpaired_says_to_message_the_number(tmp_path):
    store = Store(tmp_path / "w.db")

    class _TB:
        fabric = None
    b = wa.WhatsAppBridge(json.loads(json.dumps(CFG)), store, _TB(),
                          lambda ev: asyncio.sleep(0))
    assert "Not paired" in asyncio.run(b.send("hello"))


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

def test_reply_button_titles_fit_whatsapps_limit():
    """Twenty characters, hard. Over it, Meta truncates server-side and the user is
    asked to approve something whose label was cut off."""
    for t in wa._TITLES.values():
        assert len(t) <= 20, t


def test_only_the_owners_tap_answers_an_approval(bridge, monkeypatch):
    b, store, cfg, sent = bridge
    monkeypatch.setattr(wa.cfgmod, "save_config", lambda _c: None)
    asyncio.run(b.handle(envelope("hi")))

    async def go():
        fut = asyncio.get_event_loop().create_future()
        b._pending["aa"] = fut
        b._answer("447700900000", "ap:aa:1")       # a stranger
        assert not fut.done()
        b._answer("919812345678", "ap:aa:1")       # the owner
        assert await asyncio.wait_for(fut, 1) == "1"
    asyncio.run(go())


# ---------------------------------------------------------------------------
# Where it appears in the rest of the OS
# ---------------------------------------------------------------------------

def test_whatsapp_is_a_real_io_gate():
    """Not a label: a grant has to be scopeable to it, or "may act from WhatsApp"
    cannot be expressed."""
    from agentos import policy
    assert "whatsapp" in policy.SURFACES
    assert policy.surface_allows("whatsapp", "whatsapp")
    assert not policy.surface_allows("telegram", "whatsapp")


def test_it_is_a_channel_that_needs_all_four_values():
    from agentos import channels
    st = {c["id"]: c for c in channels.state(json.loads(json.dumps(CLOUD)))}
    assert st["whatsapp"]["status"] == "needs"
    assert st["whatsapp"]["gate"] == "whatsapp" and st["whatsapp"]["own_gate"]
    missing = st["whatsapp"]["detail"]
    for label in ("Phone number ID", "Access token", "App secret", "Verify token"):
        assert label in missing


def test_saving_a_blank_secret_does_not_erase_the_saved_one():
    from agentos import channels
    cfg: dict = {}
    channels.save(cfg, "whatsapp", {"access_token": "real-token"})
    channels.save(cfg, "whatsapp", {"access_token": "", "phone_number_id": "222"})
    assert wa.conf(cfg)["access_token"] == "real-token"


def test_switching_it_on_half_configured_is_refused():
    from agentos import channels
    cfg: dict = json.loads(json.dumps(CLOUD))
    ok, msg = channels.save(cfg, "whatsapp", {"enabled": True, "phone_number_id": "1"})
    assert not ok and "still needs" in msg
    assert not wa.conf(cfg).get("enabled")


def test_it_is_a_flow_delivery_sink():
    from agentos import flows
    assert "whatsapp" in flows.SINK_KINDS


def test_a_job_offers_whatsapp_only_when_paired_and_says_why_not():
    from agentos import jobs
    off = {d["id"]: d for d in jobs.deliveries(json.loads(json.dumps(CLOUD)))}
    assert off["whatsapp"]["ready"] is False
    assert "Settings → Channels → WhatsApp" in off["whatsapp"]["detail"]
    paired = json.loads(json.dumps(CFG))
    paired["channels"]["whatsapp"]["owner_wa_id"] = "911"
    on = {d["id"]: d for d in jobs.deliveries(paired)}
    assert on["whatsapp"]["ready"] is True
    # and the constraint is stated before it is chosen, not discovered at 08:00
    assert "24 hours" in on["whatsapp"]["detail"]


def test_a_whatsapp_job_also_saves_a_report_because_the_send_can_be_refused(tmp_path):
    from agentos import fabric, jobs
    store = Store(tmp_path / "j.db")
    fabric.seed_builtins({}, store)
    paired = json.loads(json.dumps(CFG))
    paired["channels"]["whatsapp"]["owner_wa_id"] = "911"
    body = jobs.build(paired, store, "morning-brief",
                      {"topics": "rust", "deliver": "whatsapp"})
    assert {"whatsapp_send", "save_report"} <= set(body["permissions"]["tools"])
    assert "save_report" in body["mission"] and "FIRST" in body["mission"]


# ---------------------------------------------------------------------------
# The link transport over HTTP
# ---------------------------------------------------------------------------

@pytest.fixture()
def api():
    from fastapi.testclient import TestClient

    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        yield c, servermod.state


def test_the_card_is_told_which_transport_is_live(api):
    c, st = api
    d = c.get("/api/whatsapp").json()
    assert d["mode"] in ("baileys", "cloud")
    assert "link" in d and "installed" in d["link"]


def test_linking_without_the_bridge_refuses_with_the_reason(api, monkeypatch):
    """Never a dead control: the refusal names what is missing and which
    component would fix it, which is what the card turns into an install offer."""
    c, st = api
    from agentos import wa_baileys as wab
    monkeypatch.setattr(wab, "node_path", lambda: "")
    r = c.post("/api/whatsapp/link")
    assert r.status_code == 428
    assert "Node" in r.json()["error"]
    assert r.json()["component"] == "whatsapp-bridge"


def test_unlinking_is_idempotent_and_forgets_the_credentials(api):
    """Unlink on a machine that was never linked must succeed quietly — and it
    clears the owner, or the next person to scan inherits somebody else's chat."""
    c, st = api
    assert c.request("DELETE", "/api/whatsapp/link").json()["ok"]
    assert c.request("DELETE", "/api/whatsapp/link").json()["ok"]
    from agentos import wa_baileys as wab
    assert not wab.paired()
    assert not st["whatsapp"]._c().get("owner_wa_id")


def test_switching_transport_over_http_sticks(api):
    c, st = api
    assert c.put("/api/whatsapp", json={"mode": "cloud"}).json()["mode"] == "cloud"
    assert c.get("/api/whatsapp").json()["mode"] == "cloud"
    c.put("/api/whatsapp", json={"mode": "baileys"})


def test_installing_a_component_has_a_route_at_all(api):
    """Both the first-run 'install Ollama for me' button and the WhatsApp bridge
    card have always POSTed here. There was no such route, so both 404'd silently
    while reporting 'could not install'."""
    c, st = api
    r = c.post("/api/components/install", json={"id": "definitely-not-a-component"})
    assert r.status_code == 200
    assert r.json()["ok"] is False and "unknown component" in r.json()["message"]
