"""Designing a character from a description, with the machine's model.

What these defend: the model is shown the WHOLE closed set and nothing else; whatever it
answers is validated one field at a time, so an invented value costs that field and is
named, never painted; with no model answering, the palette's own words in the
description are matched — and the answer says so, rather than claiming AI did it; the
design applies at once and `previous` is exactly what Undo needs; and every face (the
editor, the route, the CLI) is the same designer.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import avatars as av                                     # noqa: E402

ROOT = Path(__file__).parent.parent


def test_the_model_is_shown_every_option_and_asked_for_json_only():
    system, prompt = av.design_prompt("a calm lead", "Aria")
    pal = av.palette()
    for field in ("skin", "hair", "pants", "shirt"):
        for x in pal[field]:
            assert x["name"] in prompt
    for v in pal["style"] + pal["outfit"]:
        assert v in prompt
    assert "ONLY" in system and "JSON" in system


def test_an_invented_value_costs_that_field_and_is_named():
    patch, dropped, note = av.read_design(
        'Here you go: {"hair":"silver","style":"bun","glasses":true,"outfit":"cape",'
        '"shirt":"purple","skin":"green","note":"a wise lead"}')
    assert patch == {"hair": 5, "style": "bun", "glasses": True, "hue": 264}, patch
    assert dropped == ["skin=green", "outfit=cape"]
    assert note == "a wise lead"
    assert av.read_design("no json at all") == ({}, [], "")


@pytest.mark.parametrize("words,want", [
    ("a calm senior engineer with a grey bun and glasses, in a violet blazer",
     {"hair": 5, "style": "bun", "glasses": True, "outfit": "blazer", "hue": 264}),
    ("deep skin, curly black hair, orange hoodie, jeans",
     {"skin": 4, "hair": 0, "style": "curly", "outfit": "hoodie", "hue": 34, "pants": 0}),
    ("short blonde hair and no glasses", {"hair": 3, "style": "short", "glasses": False}),
])
def test_without_a_model_it_matches_only_what_was_said(words, want):
    assert av.from_words(words) == want


def test_words_that_name_nothing_design_nothing():
    assert av.from_words("make them look cool and friendly") == {}


# ---- the route --------------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        servermod.state["cfg"]["default_model"] = "openai/gpt-4o"
        yield cl, servermod


def test_designed_by_the_model_applied_at_once_and_undone_exactly(client, monkeypatch):
    cl, servermod = client
    seen = {}

    async def fake(cfg, model, prompt, system=""):
        seen["prompt"] = prompt
        return json.dumps({"hair": "grey", "style": "bun", "glasses": True, "outfit": "blazer",
                           "shirt": "violet", "cape": "red", "note": "a calm lead"})
    monkeypatch.setattr(servermod.providers, "complete", fake)
    before = cl.get("/api/avatars").json()
    was = next(a for a in before["avatars"] if a["key"] == "@agent")["recipe"]
    r = cl.post("/api/avatars/@agent/design",
                json={"description": "a calm lead \x1b[2Jwith a grey bun, glasses, violet blazer"}).json()
    assert r["how"] == "model" and r["model"] == "openai/gpt-4o" and r["note"] == "a calm lead"
    assert r["recipe"]["style"] == "bun" and r["recipe"]["outfit"] == "blazer" and r["recipe"]["glasses"]
    assert "\x1b" not in seen["prompt"], "the description is cleaned before it reaches the model"
    assert r["previous"] == was
    p = r["previous"]
    undo = cl.put("/api/avatars/@agent", json={k: p[k] for k in av.FIELDS}).json()
    assert undo["recipe"] == was, "Undo puts back exactly what was there"


def test_with_no_model_answering_it_says_it_matched_words(client, monkeypatch):
    cl, servermod = client

    async def down(*a, **k):
        raise RuntimeError("no key")
    monkeypatch.setattr(servermod.providers, "complete", down)
    r = cl.post("/api/avatars/@me/design", json={"description": "curly auburn hair, green hoodie"}).json()
    assert r["how"] == "words" and "matched the words you used" in r["said"]
    assert r["recipe"]["style"] == "curly" and r["recipe"]["outfit"] == "hoodie"


def test_the_route_refuses_nobody_and_nothing(client, monkeypatch):
    cl, servermod = client

    async def down(*a, **k):
        raise RuntimeError("no key")
    monkeypatch.setattr(servermod.providers, "complete", down)
    assert cl.post("/api/avatars/ghost/design", json={"description": "grey bun"}).status_code == 404
    assert cl.post("/api/avatars/@me/design", json={"description": ""}).status_code == 400
    bad = cl.post("/api/avatars/@me/design", json={"description": "something nice please"})
    assert bad.status_code == 400 and "hair" in bad.json()["error"], "the refusal says what WOULD work"


# ---- the faces ------------------------------------------------------------------------------------

def test_the_terminal_designs_with_the_same_designer(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    r = subprocess.run([sys.executable, "-m", "agentos", "avatar", "design", "agent",
                        "grey", "bun", "and", "glasses,", "in", "a", "violet", "blazer"],
                       env=env, cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "a bun of grey hair, glasses, a violet blazer" in r.stdout
    assert "matched the words" in r.stdout or "designed by" in r.stdout


def test_the_editor_has_the_design_box_and_undo():
    js = (ROOT / "agentos/ui/src/js/00e-avatars.js").read_text()
    assert "ave-design" in js and "/design'" in js and "ave-undo" in js
    assert "r.how==='model'" in js, "the editor says who designed it"
