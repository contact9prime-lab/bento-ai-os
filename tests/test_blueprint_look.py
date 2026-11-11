"""A blueprint shows what the thing looks like, says more about each part, and reaches a phone as
a walk through it (agentos/bppicture.py, bpfill, stage.still_views). Asked for as "is it still
going to show the drawings as well, how each thing looks", "the use of the image, building of
the designs should be done further, the content can be made more rich", and "the blueprint
should come in the channels as well". Pinned here:

- a picture is found on Wikimedia Commons under a free licence only, from search words, with its
  credit, licence and page; a model can never hand one in;
- the whole and each part filled get one, and a lookup that fails is quiet;
- a drawing is made only on the person's tap and is marked illustrative;
- parts carry steps (how it works, in order) and a comparison with something everyday;
- a phone gets the blueprint opened for it: the drawing, the parts, how it works, each part.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import bpfill, bppicture, stage  # noqa: E402
from agentos.memory import Store  # noqa: E402

ROOT = Path(__file__).parent.parent
PAINTER = (ROOT / "agentos/ui/src/js/24v-blueprint.js").read_text()


def _page(title, lic, url, index, width=1200, mime="image/png"):
    return {"title": f"File:{title}", "index": index, "imageinfo": [{
        "thumburl": url, "url": url, "width": width, "mime": mime,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:" + title.replace(" ", "_"),
        "extmetadata": {"LicenseShortName": {"value": lic},
                        "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:Ada">Ada</a>'}}}]}


def test_only_a_free_drawing_from_commons_is_taken():
    ans = {"query": {"pages": {
        "1": _page("Turbofan photo.jpg", "CC BY-NC 2.0",
                   "https://upload.wikimedia.org/a/photo.jpg", 1),
        "2": _page("Turbofan engine.png", "Public domain",
                   "https://upload.wikimedia.org/b/engine.png?utm_source=x", 2),
        "3": _page("Simplified turbofan cutaway diagram.svg", "CC BY-SA 4.0",
                   "https://thumb.wikimedia.org/c/cut.svg.png?utm_source=x", 3, 900, "image/svg+xml"),
        "4": _page("Turbofan cutaway evil.png", "CC0", "https://evil.example/cut.png", 0)}}}
    pic = bppicture.pick(ans, "turbofan cutaway")
    assert pic["url"] == "https://thumb.wikimedia.org/c/cut.svg.png"     # no tracking, Commons hosts only
    assert pic["licence"] == "CC BY-SA 4.0" and pic["credit"] == "Ada" and pic["made"] == "found"
    assert pic["page"].startswith("https://commons.wikimedia.org/")
    assert not bppicture.free("CC BY-NC-SA 4.0") and not bppicture.free("CC BY-ND 3.0")
    assert bppicture.free("CC0") and bppicture.free("PD-USGov") and bppicture.free("CC BY 3.0")
    assert bppicture.pick({}, "x") is None


def test_a_model_cannot_hand_in_a_picture_but_gives_search_words():
    sc, dropped = stage.clean({"kind": "blueprint", "title": "Engine", "look_for": "CFM56 cutaway",
                               "picture": {"url": "https://evil.example/x.png"},
                               "parts": [{"name": "Fan", "steps": ["air comes in", "blades push it", {"x": 1}],
                                          "like": "as wide as a car is long", "look_for": "fan blade diagram",
                                          "picture": "https://evil.example/y.png"}, "Core"]})
    assert "picture" not in sc and "picture" in dropped
    assert "parts[0].picture" in dropped and "picture" not in sc["parts"][0]
    assert sc["look_for"] == "CFM56 cutaway"
    fan = sc["parts"][0]
    assert fan["steps"] == ["air comes in", "blades push it"] and fan["like"].startswith("as wide")
    assert bppicture.words_for(sc, fan) == "fan blade diagram"
    assert bppicture.words_for(sc) == "CFM56 cutaway"


def _row(tmp_path):
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "blueprint of a jet engine")
    sc, _ = stage.clean({"kind": "blueprint", "title": "Jet engine", "source": "outline",
                         "parts": [{"name": "Fan", "role": "moves air"}, {"name": "Core", "role": "burns"}],
                         "links": [{"from": "Fan", "to": "Core", "verb": "feeds", "kind": "air"}]})
    return store, stage.add(store, cid, sc)


def _answer(name):
    return {"role": f"the {name}", "how": "it turns", "steps": ["one", "two", "three"],
            "like": "a big desk fan", "look_for": f"{name} diagram",
            "facts": [{"label": "d", "value": 3, "unit": "m"}, {"label": "m", "value": 2, "unit": "t"}],
            "parts": [{"name": f"{name} bit {i}", "how": "x", "steps": ["a"],
                       "parts": [{"name": f"{name} sub {i}"}]} for i in range(6)]}


def test_the_whole_and_each_part_get_a_drawing_and_richer_words(tmp_path):
    store, row = _row(tmp_path)
    bpfill.begin(store, row)
    assert row["scene"]["looking"] > 0
    asked = []

    async def asker(cfg, prompt):
        assert "steps" in prompt and "look_for" in prompt and "like" in prompt
        name = "Fan" if "Fill in this part: Fan" in prompt else "Core"
        return json.dumps(_answer(name)), "claude-code", 1

    async def finder(words):
        asked.append(words)
        if words.startswith("Core"):
            return None                        # nothing free: the part stays without one
        return {"url": "https://upload.wikimedia.org/x/" + words.split()[0] + ".png", "page": "p",
                "title": words, "credit": "Ada", "licence": "CC0", "made": "found"}
    sc = asyncio.run(bpfill.fill(store, {}, row, None, asker=asker, finder=finder))
    assert "Jet engine cutaway diagram" in asked and "Fan diagram" in asked and "Core diagram" in asked
    assert sc["picture"]["url"].endswith("/Jet.png") and "looking" not in sc
    fan, core = sc["parts"]
    assert fan["picture"]["title"] == "Fan diagram" and "picture" not in core
    assert fan["steps"] == ["one", "two", "three"] and fan["like"] == "a big desk fan"
    assert fan["parts"][0]["steps"] == ["a"]
    # the terminal says where each picture came from
    txt = stage.text(sc)
    assert "▣ picture: Jet engine cutaway diagram · Ada · CC0" in txt and "1. one" in txt and "like: a big desk fan" in txt


def test_no_brain_still_looks_for_the_drawing(tmp_path):
    store, row = _row(tmp_path)
    ids = bpfill.begin(store, row, brain=False)
    assert ids == [] and "filling" not in row["scene"] and row["scene"]["looking"]

    async def finder(words):
        raise OSError("offline")
    sc = asyncio.run(bpfill.fill(store, {}, row, None, finder=finder))
    assert "picture" not in sc and "looking" not in sc


def test_a_drawing_is_the_persons_tap_and_says_it_is_illustrative(tmp_path, monkeypatch):
    store, row = _row(tmp_path)
    from agentos import assets as assetmod
    kept = []

    async def put(store_, data, **kw):
        kept.append(kw)
        return {"id": "a1b2"}
    monkeypatch.setattr(assetmod, "put_bytes", put)

    class Box:
        async def _generate_image(self, prompt, w, h):
            assert "blueprint cutaway" in prompt and "Fan of Jet engine" in prompt
            return b"\x89PNG...", "pollinations"
    sent = []

    async def send(ev):
        sent.append(ev)
    pic = asyncio.run(bpfill.draw(store, Box(), row["id"], "fan", send))
    assert pic == {"asset": "a1b2", "url": "/api/assets/a1b2/file", "page": "", "title": "",
                   "credit": "pollinations", "licence": "", "made": "drawn"}
    sc = json.loads(store.db.execute("SELECT scene FROM stage_scenes").fetchone()[0])
    assert sc["parts"][0]["picture"]["made"] == "drawn" and sent[0]["type"] == "stage_fill"
    assert "illustrative" in stage.bp_picture_line(pic)

    class Nothing:
        async def _generate_image(self, prompt, w, h):
            return None, "no image engine answered"
    try:
        asyncio.run(bpfill.draw(store, Nothing(), row["id"], "", None))
        raise AssertionError("should refuse")
    except ValueError as e:
        assert "no image engine" in str(e)


def test_a_phone_gets_the_blueprint_opened_for_it():
    sc, _ = stage.clean({"kind": "blueprint", "title": "Jet engine", "source": "s",
                         "parts": [{"name": "Fan", "parts": [{"name": "Blades"}, {"name": "Hub"}],
                                    "how": "it turns", "steps": ["air in", "pushed back"],
                                    "like": "a giant desk fan", "facts": [{"label": "d", "value": 3, "unit": "m"}]},
                                   {"name": "Core", "parts": [{"name": "Burner"}]}, "Nozzle"],
                         "links": [{"from": "Blades", "to": "Burner", "verb": "feeds", "kind": "air"}]})
    sc["picture"] = {"url": "https://upload.wikimedia.org/x.png", "title": "Cutaway", "credit": "Ada",
                     "licence": "CC0", "page": "https://commons.wikimedia.org/wiki/File:x", "made": "found"}
    views = stage.still_views(sc)
    assert views == [{"mode": "look", "path": []}, {"mode": "parts", "path": []},
                     {"mode": "flows", "path": []}, {"mode": "parts", "path": ["fan"]},
                     {"mode": "parts", "path": ["core"]}]
    items = stage.still_items([sc, {"kind": "numbers", "title": "n"}])
    assert len(items) == 6 and items[-1][1] is None
    caps = [stage.still_caption_for(s, v, i, len(items)) for i, (s, v) in enumerate(items)]
    assert "the drawing" in caps[0] and "CC0" in caps[0] and "Ada" in caps[0]
    assert "Fan feeds Core (air)" in caps[2]
    assert "Jet engine › Fan" in caps[3] and "1. air in" in caps[3] and "≈ a giant desk fan" in caps[3]
    assert "Inside: Blades, Hub" in caps[3] and "d 3 m" in caps[3]
    # both phones use the same views, so a picture and its words never come apart
    for f in ("agentos/telegram.py", "agentos/whatsapp.py"):
        src = (ROOT / f).read_text()
        assert "still_items(scenes)" in src and "still_caption_for(" in src


def test_a_found_drawing_is_kept_here(tmp_path, monkeypatch):
    from agentos import assets as assetmod, netguard
    seen = {}

    async def read(url, cap, **kw):
        seen["url"], seen["ua"] = url, kw["headers"]["User-Agent"]
        return 200, "image/png; x=1", b"\x89PNG"

    async def put(store, data, **kw):
        seen["kw"] = kw
        return {"id": "f00d"}
    monkeypatch.setattr(netguard, "read_capped", read)
    monkeypatch.setattr(assetmod, "put_bytes", put)
    pic = {"url": "https://upload.wikimedia.org/x.png", "page": "https://commons.wikimedia.org/wiki/File:x",
           "title": "x", "credit": "Ada", "licence": "CC0", "made": "found"}
    got = asyncio.run(bppicture.keep(None, pic, "https://example.org/me"))
    assert got["url"] == "/api/assets/f00d/file" and got["remote"] == pic["url"] and got["credit"] == "Ada"
    assert seen["ua"] == "BentoBlueprint/1.0 (https://example.org/me)" and "Ada" in seen["kw"]["source"]

    async def html(url, cap, **kw):
        return 429, "text/html", b"slow down"
    monkeypatch.setattr(netguard, "read_capped", html)
    assert asyncio.run(bppicture.keep(None, pic)) == pic          # refused: the Commons address stays
    assert asyncio.run(bppicture.keep(None, {**pic, "url": "https://evil.example/x.png"}))["url"] \
        == "https://evil.example/x.png"                            # never fetched: not a Commons host
    assert seen["url"] == pic["url"]


def test_the_painter_draws_the_drawing():
    for needle in ("function bpLook(", "function bpPicOf(", "'Original colours'", "'Wikimedia Commons'",
                   "/api/stage/draw", "sc._view", "'bp-steps'", "'bp-like'", "Illustrative drawing by"):
        assert needle in PAINTER, needle
    assert "innerHTML" not in PAINTER
    css = (ROOT / "agentos/ui/src/css/40-blueprint.css").read_text()
    assert ".bp-fig img" in css and "invert(1)" in css
