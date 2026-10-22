"""A Pi's speech understood by its hub (hearing.py `hub`, wire op `hear`).

Asked for as "with audio transcription, is that done through the hub so it happens quickly, and
if the hub doesn't have it, build it in the hub". It wasn't: a Pi set up from a hub had no voice
keys and no whisper.cpp, so its kiosk could not hear at all. Live run:
packaging/dev/provision-e2e/hub_hear_run.py (real servers, real mTLS, every byte checked)."""
import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import edgecode, hearing, provision                     # noqa: E402
from agentos.memory import Store                                      # noqa: E402
from agentos.policy import PDP                                        # noqa: E402

ROOT = Path(__file__).parent.parent
LK = {"kind": "machine", "label": "kitchen-pi", "peer_host_fp": "f" * 64}


def test_a_machine_with_a_hub_hears_through_it_first(monkeypatch):
    monkeypatch.setattr(hearing, "_hub", lambda cfg: {"label": "big-box"})
    st = hearing.status({})
    assert st["engine"] == "hub" and "your hub, big-box" in st["line"]
    monkeypatch.setattr(hearing, "_hub", lambda cfg: None)
    assert hearing.status({})["engine"] != "hub", "no hub: nothing changes"


def test_if_the_hub_cannot_its_own_engine_still_tries(monkeypatch):
    monkeypatch.setattr(hearing, "_hub", lambda cfg: {"label": "big-box"})

    async def hub_fails(cfg, wav, lang):
        raise hearing.HearError("Your hub can't understand speech yet.")
    monkeypatch.setattr(hearing, "_hub_run", hub_fails)
    monkeypatch.setattr(hearing, "_whisper", lambda cfg: ("/bin/whisper", "/m.bin"))
    monkeypatch.setattr(hearing, "_whisper_run", lambda cfg, wav, lang: "said here")
    assert asyncio.run(hearing.transcribe({}, b"RIFF....", "en")) == "said here"
    monkeypatch.setattr(hearing, "_whisper", lambda cfg: ("", "not installed"))
    try:
        asyncio.run(hearing.transcribe({}, b"RIFF....", "en"))
        raise AssertionError("expected the hub's sentence")
    except hearing.HearError as e:
        assert "hub" in str(e)


def test_too_long_for_the_link_is_said_not_sent(monkeypatch):
    monkeypatch.setattr(hearing, "_hub", lambda cfg: {"label": "big-box"})
    try:
        asyncio.run(hearing._hub_run({}, b"x" * (hearing.HUB_MAX_BYTES + 1), "en"))
        raise AssertionError("expected a refusal")
    except hearing.HearError as e:
        assert "shorter" in str(e)


def _hub(tmp_path, monkeypatch, granted=True, setup=True):
    monkeypatch.setattr(provision, "was_enabled_here", lambda fp: setup and fp == "f" * 64)
    store = Store(tmp_path / "hub.db")
    if granted:
        assert hearing.grant_hub(store, "kitchen-pi") and not hearing.grant_hub(store, "kitchen-pi")
    return store, PDP({}, store)


def test_the_hub_answers_only_machines_it_set_up_and_allowed(tmp_path, monkeypatch):
    req = {"wav": base64.b64encode(b"RIFF").decode(), "lang": "en"}
    store, pdp = _hub(tmp_path, monkeypatch, setup=False)
    assert "set up" in asyncio.run(hearing.answer_hub(store, pdp, {}, LK, req))["error"]
    store, pdp = _hub(tmp_path / "b", monkeypatch, granted=False) if (tmp_path / "b").mkdir() is None else (None, None)
    assert "Permissions" in asyncio.run(hearing.answer_hub(store, pdp, {}, LK, req))["error"]


def test_the_hub_hears_with_its_own_engine_and_never_passes_it_on(tmp_path, monkeypatch):
    store, pdp = _hub(tmp_path, monkeypatch)
    req = {"wav": base64.b64encode(b"RIFFdata").decode(), "lang": "en"}
    monkeypatch.setattr(hearing, "_hub", lambda cfg: {"label": "its-own-hub"})
    monkeypatch.setattr(hearing, "_whisper", lambda cfg: ("", "not installed"))
    out = asyncio.run(hearing.answer_hub(store, pdp, {}, LK, req))
    assert not out["ok"] and "can't understand speech yet" in out["error"], "a hub's hub is never asked"
    monkeypatch.setattr(hearing, "_whisper", lambda cfg: ("/bin/whisper", "/m.bin"))
    monkeypatch.setattr(hearing, "_whisper_run", lambda cfg, wav, lang: f"heard {len(wav)} bytes")
    out = asyncio.run(hearing.answer_hub(store, pdp, {}, LK, req))
    assert out == {"ok": True, "text": "heard 8 bytes", "engine": "whisper.cpp"}


def test_it_is_wired_where_it_has_to_be():
    assert '"edge_run", "hear")' in (ROOT / "agentos/teamlink.py").read_text()
    srv = (ROOT / "agentos/server.py").read_text()
    assert 'req.get("op") == "hear"' in srv and "grant_hub(" in srv
    assert '"speech.hear")' in (ROOT / "agentos/fabric.py").read_text().split("def forget_link_grants")[1][:600]
    assert edgecode.set_up_here is not None
