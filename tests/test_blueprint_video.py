"""Every blueprint reaches a phone as a video, on Telegram and on WhatsApp.

Reported as "Telegram is not giving the blueprint in form of video or interaction, it is just
coming as PDF. Same thing should be implemented in WhatsApp too". Read from the owner's record:
the black hole blueprint came from the agent with no 3D form, the video step only knew scenes
built in 3D, so the pictures and the PDF went and nothing else; asked why, the agent said "the
Stage has no way yet to turn a blueprint into a video". WhatsApp had no video path at all.
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import bpfill, stage, stageclip, whatsapp  # noqa: E402
from agentos.memory import Store  # noqa: E402

ROOT = Path(__file__).parent.parent
HOLE = {"kind": "blueprint", "title": "A black hole, taken apart", "source": "general relativity",
        "form": "exploded", "subject": "A black hole",
        "parts": [{"name": "Event horizon", "role": "The one-way boundary.", "how": "Space falls in faster than light.",
                   "parts": [{"name": "Outer horizon"}]},
                  {"name": "Accretion disk", "role": "Hot gas spiralling in.", "parts": [{"name": "Inner edge"}]}],
        "links": [{"from": "Accretion disk", "to": "Event horizon", "verb": "falls through", "kind": "material"}]}
FLOW = {"kind": "blueprint", "title": "How an outage happened", "source": "the report", "form": "flow",
        "parts": [{"name": "Upgrade", "parts": [{"name": "Wiring"}]}, {"name": "Failure", "parts": [{"name": "Switch"}]}]}
SOLIDS = {"ground": "space", "solids": [
    {"shape": "sphere", "at": [0, 8, 0], "size": [3, 3, 3], "color": "black", "label": "Event horizon",
     "note": "Nothing comes back out.", "part": "Event horizon", "look_for": "black hole", "mesh": {"x": 1}},
    {"shape": "ring", "at": [0, 9, 0], "size": [12, .3, 12], "color": "orange", "part": "Accretion disk", "move": "spin"},
    {"shape": "ring", "at": [0, 9, 0], "size": [16, .3, 16], "color": "red", "part": "Nowhere"},
    {"shape": "teapot", "at": [0, 0, 0]}]}


def test_a_thing_with_no_3d_form_is_given_one_and_a_process_is_not():
    hole, flow = stage.clean(HOLE)[0], stage.clean(FLOW)[0]
    assert stage.wants_shape(hole) and not stage.builds_3d(hole)
    assert not stage.wants_shape(flow)                                  # a process has no shape to build
    with_model = stage.clean(dict(HOLE, model=SOLIDS["solids"][:2]))[0]
    assert not stage.wants_shape(with_model) and stage.builds_3d(with_model)
    # the answer goes through the model's own cleaner: a shape that is not one and a part that
    # is not there are dropped, and an address or a mesh never comes from a brain
    dropped = stage.shape_into(hole, SOLIDS)
    assert len(hole["model"]) == 3 and hole["ground"] == "space" and stage.builds_3d(hole)
    assert all("look_for" not in so and "mesh" not in so for so in hole["model"])
    assert any("teapot" in d for d in dropped) and any("part" in d for d in dropped)
    assert hole["model"][0]["part"] == "event-horizon"
    try:
        stage.shape_into(stage.clean(HOLE)[0], {"solids": [{"shape": "sphere"}]})
    except ValueError:
        pass
    else:
        raise AssertionError("two solids are not a form")
    # a ground only for a blueprint that has a form, and only from the closed set
    assert "ground" not in stage.clean(dict(HOLE, ground="space"))[0]
    assert stage.clean(dict(HOLE, model=SOLIDS["solids"][:2], ground="space"))[0]["ground"] == "space"
    assert "ground" not in stage.clean(dict(HOLE, model=SOLIDS["solids"][:2], ground="lava"))[0]


def test_the_fill_stage_asks_for_the_form_once_and_a_failure_is_named(tmp_path):
    import json
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "blueprint of a black hole")
    row = stage.add(store, cid, stage.clean(HOLE)[0])
    asked = []

    async def asker(cfg, prompt):
        asked.append(prompt)
        if "no 3D form yet" in prompt:
            return json.dumps(SOLIDS), "test", 0
        return json.dumps({"name": "x", "role": "r", "how": "h"}), "test", 0

    async def nofind(words):
        return None
    bpfill.begin(store, row)
    assert "shaping" in row["scene"]
    sc = asyncio.run(bpfill.fill(store, {}, row, None, asker=asker, finder=nofind))
    assert sum("no 3D form yet" in p for p in asked) == 1
    assert len(sc["model"]) == 3 and sc["ground"] == "space" and "shaping" not in sc and stage.builds_3d(sc)
    # the phone's album now opens on it built in 3D
    assert stage.still_views(sc)[0] == {"mode": "model", "path": []}
    # nothing usable back: the blueprint is as it was, and says why
    row2 = stage.add(store, cid, stage.clean(dict(HOLE, title="Another"))[0])

    async def bad(cfg, prompt):
        return "sorry, no", "test", 0
    bpfill.begin(store, row2)
    sc2 = asyncio.run(bpfill.fill(store, {}, row2, None, asker=bad, finder=nofind))
    assert "model" not in sc2 and sc2.get("shape_failed") and "shaping" not in sc2
    # a blueprint the agent gave a form is not asked about, and neither is a process
    for spec in (dict(HOLE, model=SOLIDS["solids"][:2]), FLOW):
        r = stage.add(store, cid, stage.clean(spec)[0])
        bpfill.begin(store, r, brain=True)
        assert "shaping" not in r["scene"]


def test_one_plan_for_both_channels_3d_when_it_has_a_form_a_walk_through_when_not():
    hole, flow = stage.clean(dict(HOLE, model=SOLIDS["solids"][:2]))[0], stage.clean(FLOW)[0]
    nums = stage.clean({"kind": "numbers", "title": "n", "source": "s", "items": [{"label": "a", "value": 1}]})[0]
    scenes = [nums, flow, hole]
    items = stage.still_items(scenes)
    pngs = [b"png%d" % i for i in range(len(items))]
    jobs = stageclip.plan(scenes, items, pngs)
    assert [j["how"] for j in jobs] == ["walk", "3d"]
    walk = jobs[0]
    assert walk["scene"] is flow and len(walk["slides"]) == len(stage.still_views(flow))
    assert [png for _v, png in walk["slides"]] == [png for (sc, _v), png in zip(items, pngs) if sc is flow]
    assert stageclip.caption(walk) == "▶ How an outage happened: the walk-through"
    assert stageclip.caption(jobs[1]) == "▶ A black hole, taken apart"
    # no pictures in hand: nothing to walk through, and the 3D one still goes
    assert [j["how"] for j in stageclip.plan(scenes)] == ["3d"]
    assert len(stageclip.plan([hole, hole, hole])) == stageclip.CLIPS


def test_the_words_under_a_picture_are_whole_sentences_and_the_ones_read_aloud():
    sc = stage.clean(HOLE)[0]
    seen = [stage.walk_text(sc, v) for v in stage.still_views(sc)]
    heads = [h for h, _ in seen]
    assert heads[0] == "The parts" and "How it works" in heads and "Event horizon" in heads
    for _h, text in seen:
        assert len(text) <= stage.WALK_SAY + 1 and "→" not in text and "Source:" not in text and "(material)" not in text
    flows = dict(seen)["How it works"]
    assert flows == "Accretion disk falls through Event horizon."
    said = []

    async def walk(title, slides, cfg=None):
        said.extend(slides)
        return b"v" * 4000, "video/mp4", 30.0
    old = stageclip.walk
    stageclip.walk = walk
    try:
        items = stage.still_items([sc])
        job = stageclip.plan([sc], items, [b"p"] * len(items))[0]
        got = asyncio.run(stageclip.make(job, {"speech": {"engine": "browser"}}))
    finally:
        stageclip.walk = old
    assert got[1] == "video/mp4" and [s["head"] for s in said] == heads
    assert all(s["narration"] is None for s in said)          # no server voice here: shown, not said


def test_the_page_records_a_walk_through_and_carries_no_three_for_it():
    js = (ROOT / "agentos/ui/src/js/24x-model.js").read_text()
    assert "async function mdlWalk(" in js and "function stageWalk(" in js and "function stageClipLeave(" in js
    page = stage.walk_html("T", [{"img": "data:image/png;base64,AA", "head": "h", "text": "</script>", "narr": ""}])
    assert "stageWalk(" in page and 'id="three"' not in page and "<\\/script>" in page
    assert "whole:true" in js and "ground:mdl.ground" in js    # a blueprint's form stands where it was put, seen from outside


def _tg(clips=True):
    sent, acts = [], []
    me = types.SimpleNamespace(cfg={"speech": {"engine": "browser"}, "agent_name": "Aria"},
                               store=types.SimpleNamespace(log=lambda *a, **k: acts.append(("log", a))))
    me._t = lambda: {"clips": clips}

    async def _api(method, **kw):
        acts.append((method, kw))
    me._api = _api

    async def send_video(data, mime, caption="", chat_id=None, seconds=0):
        sent.append((mime, caption, chat_id))
        return "sent"
    me.send_video = send_video
    return me, sent, acts


def test_telegram_sends_a_blueprint_with_no_form_as_a_walk_through(monkeypatch):
    from agentos.telegram import TelegramBridge
    made = []

    async def walk(title, slides, cfg=None):
        made.append((title, len(slides)))
        return b"v" * 4000, "video/mp4", 40.0
    monkeypatch.setattr(stageclip, "walk", walk)
    monkeypatch.setattr(stageclip, "available", lambda cfg=None: True)
    flow = stage.clean(FLOW)[0]
    items = stage.still_items([flow])
    me, sent, acts = _tg()
    assert asyncio.run(TelegramBridge.send_clips(me, [flow], 7, items, [b"p"] * len(items))) == 1
    assert made == [("How an outage happened", len(items))]
    assert sent == [("video/mp4", "▶ How an outage happened: the walk-through", 7)]
    assert any(a[0] == "log" and "sent a video" in a[1][1] for a in acts)
    me, sent, _ = _tg(clips=False)
    assert asyncio.run(TelegramBridge.send_clips(me, [flow], 7, items, [b"p"] * len(items))) == 0 and sent == []
    src = (ROOT / "agentos/telegram.py").read_text()
    assert "self.send_clips(scenes, chat_id, items, pngs)" in src


class _Link:
    def __init__(self):
        self.sent = []

    async def send_photo(self, png, cap, wa_id):
        self.sent.append(("photo", cap))
        return "sent via WhatsApp"

    async def send_document(self, path, cap, wa_id):
        self.sent.append(("doc", Path(path).name))
        return "sent via WhatsApp"

    async def send_video(self, mp4, cap, wa_id):
        self.sent.append(("video", len(mp4), cap, wa_id))
        return "sent via WhatsApp"


def _wa(tmp_path, **extra):
    store = Store(tmp_path / "a.db")
    cfg = {"agent_name": "Aria", "speech": {"engine": "browser"},
           "whatsapp": {"mode": "baileys", "enabled": True, "owner_wa_id": "44", **extra}}

    async def bc(ev):
        pass
    b = whatsapp.WhatsAppBridge(cfg, store, None, bc)
    b.link = _Link()
    return b


def test_whatsapp_sends_the_same_videos_after_the_pictures(tmp_path, monkeypatch):
    from agentos import bpdoc, stagestill
    b = _wa(tmp_path)
    cid = b.store.create_conversation("WhatsApp · me", origin="whatsapp")
    b.store.add_message(cid, "user", "how did the outage happen")
    stage.add(b.store, cid, stage.clean(FLOW)[0])
    n = len(stage.still_views(stage.clean(FLOW)[0]))

    async def stills(html, cfg=None):
        return [b"png"] * n

    async def walk(title, slides, cfg=None):
        return b"v" * 4000, "video/mp4", 40.0

    async def nodoc(*a, **k):
        return None
    monkeypatch.setattr(stagestill, "render", stills)
    monkeypatch.setattr(stageclip, "walk", walk)
    monkeypatch.setattr(stageclip, "available", lambda cfg=None: True)
    monkeypatch.setattr(bpdoc, "to_file", nodoc)
    asyncio.run(b.send_stage(cid, "reply", "44"))
    kinds = [s[0] for s in b.link.sent]
    assert kinds == ["photo"] * n + ["video"]
    assert b.link.sent[-1] == ("video", 4000, "▶ How an outage happened: the walk-through", "44")
    # the owner's switch
    b2 = _wa(tmp_path / "b", clips=False) if (tmp_path / "b").mkdir() is None else None
    assert asyncio.run(b2.send_clips([stage.clean(FLOW)[0]], "44", [], [])) == 0


def test_whatsapp_plays_only_mp4_and_a_video_too_big_is_made_smaller_or_said(tmp_path, monkeypatch):
    b = _wa(tmp_path)
    out = asyncio.run(b.send_video(b"x" * 3000, "video/webm", "c", "44"))
    assert out.startswith("[error]") and "mp4" in out and b.link.sent == []
    big = b"x" * (whatsapp.WA_VIDEO_LIMIT + 10)

    async def cannot(data, tmp, crf=23, src_name="in.webm"):
        return None
    monkeypatch.setattr(stageclip, "_to_mp4", cannot)
    out = asyncio.run(b.send_video(big, "video/mp4", "c", "44"))
    assert out.startswith("[error]") and "MB" in out and b.link.sent == []

    async def smaller(data, tmp, crf=23, src_name="in.webm"):
        assert crf > 23 and src_name == "in.mp4"
        return b"s" * 5000
    monkeypatch.setattr(stageclip, "_to_mp4", smaller)
    assert asyncio.run(b.send_video(big, "video/mp4", "c", "44")) == "sent via WhatsApp"
    assert b.link.sent == [("video", 5000, "c", "44")]
    # both transports: the linked device's sidecar plays it in the chat, the Cloud API sends it as a video
    assert "cmd.type === 'video'" in (ROOT / "agentos/wa_bridge/bridge.js").read_text()
    assert '"type": "video"' in (ROOT / "agentos/whatsapp.py").read_text()
    assert "async def send_video" in (ROOT / "agentos/wa_baileys.py").read_text()


def test_the_agent_is_never_told_a_blueprint_cannot_be_a_video():
    line = stage.note({"stage": {"big": True}}, surface="telegram")
    assert "as a video with sound" in line and "never tell them a blueprint cannot be a video" in line
    assert "as a video with sound" in stage.note({}, surface="whatsapp")
    assert "as a video with sound" not in stage.note({}, surface="")
