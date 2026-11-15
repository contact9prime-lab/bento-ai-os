"""A story from the Stage as a PowerPoint, a Word document or a PDF (agentos/stagedoc.py).

Asked for as "have word documents, pdf and ppt in the stage". Pinned here:

- the pictures in a file are the ones a phone gets, one page per `still_items` view, and with no browser
  the file carries the scenes' words and says so;
- a .pptx and a .docx are well-formed packages: every part parses, every relationship points at a part
  that is there, every part has a content type;
- a tall picture is shown in overlapping bands by the format's own crop, never shrunk whole;
- the chat is the agent's (`_conv`), the file lands only in the workspace's stage folder, never through a
  link, and the tool is safe, in the door, and asked for in paranoid mode;
- the route answers 404, 422 and 503 in words.
"""
import asyncio
import io
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from xml.dom import minidom

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import stage, stagedoc, stagestill  # noqa: E402
from agentos.memory import Store  # noqa: E402

ROOT = Path(__file__).parent.parent


def _png(w: int, h: int) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\x20\x30\x50" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _story(tmp_path):
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "Where is life cheapest & <best>?")
    for sc in ({"kind": "chart", "chart_type": "bar", "title": "Budget by country", "unit": "$", "source": "Numbeo",
                "caption": "Vietnam is cheapest.", "series": [{"name": "", "points": [["Vietnam", 1150], ["UAE", 4250]]}]},
               {"kind": "numbers", "title": "What it means", "illustrative": True,
                "items": [{"label": "Cheapest", "value": "1,150", "unit": "$"}]},
               {"kind": "blueprint", "title": "Jet engine", "subject": "Turbofan", "source": "maker",
                "parts": [{"name": "Fan", "role": "moves air", "parts": [{"name": "Blades"}]}, {"name": "Core"}]}):
        stage.add(store, cid, stage.clean(sc)[0])
    return store, cid, stage.last_question(store, cid)


def _drawn(monkeypatch, sizes):
    async def render(html, cfg=None):
        assert "window.STAGE_STILL=true" in html
        return [_png(*s) for s in sizes]
    monkeypatch.setattr(stagestill, "render", render)


def _check_package(data: bytes, main: str):
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    assert z.testzip() is None and main in names
    for n in names:
        if n.endswith((".xml", ".rels")):
            minidom.parseString(z.read(n))                       # every part is well-formed XML
    types = minidom.parseString(z.read("[Content_Types].xml"))
    exts = {d.getAttribute("Extension") for d in types.getElementsByTagName("Default")}
    over = {o.getAttribute("PartName") for o in types.getElementsByTagName("Override")}
    for n in names - {"[Content_Types].xml"}:
        assert "/" + n in over or n.rsplit(".", 1)[-1] in exts, f"no content type for {n}"
    for n in [x for x in names if x.endswith(".rels")]:
        base = Path(n).parent.parent
        for r in minidom.parseString(z.read(n)).getElementsByTagName("Relationship"):
            if r.getAttribute("TargetMode") == "External":
                continue
            target = (base / r.getAttribute("Target")).as_posix()
            parts = []
            for seg in target.split("/"):
                parts = parts[:-1] if seg == ".." else parts + [seg]
            assert "/".join(p for p in parts if p not in ("", ".")) in names, f"{n} points at a missing {target}"
    return z


def test_the_words_for_a_format_are_read_and_a_wrong_one_names_the_choices():
    assert [stagedoc.fmt_of(w) for w in ("ppt", "PowerPoint", ".PPTX", "word", "doc", "pdf")] == \
        ["pptx", "pptx", "pptx", "docx", "docx", "pdf"]
    with pytest.raises(ValueError, match="pptx .* docx .* pdf"):
        stagedoc.fmt_of("xlsx")


def test_a_tall_picture_is_shown_in_overlapping_bands_and_a_short_one_whole():
    assert stagedoc.bands(1080, 1100) == [(0.0, 1.0)]
    assert stagedoc.bands(1080, 1464) == [(0.0, 1.0)], "a little over is fitted, not cut for a sliver"
    cut = stagedoc.bands(1080, 3200)
    assert len(cut) >= 3 and cut[0][0] == 0 and cut[-1][1] == 1
    for (a, b), (c, d) in zip(cut, cut[1:]):
        assert c < b, "each band shares a strip with the one before"
    assert all((b - a) * 3200 / 1080 <= stagedoc.BAND + 1e-3 for a, b in cut)
    assert stagedoc.png_size(_png(7, 9)) == (7, 9) and stagedoc.png_size(b"not a picture") == (0, 0)


def test_a_story_is_a_page_per_picture_a_phone_gets_with_its_words_and_source(tmp_path, monkeypatch):
    store, cid, ans = _story(tmp_path)
    scenes = [r["scene"] for r in stage.story(store, cid, ans)]
    n = len(stage.still_items(scenes))
    _drawn(monkeypatch, [(1080, 1100)] * n)
    doc = asyncio.run(stagedoc.gather(store, {}, cid, ans, "Aria"))
    assert doc["drawn"] and len(doc["pages"]) == n and n >= 4          # the blueprint opens into its sheets
    assert doc["question"] == "Where is life cheapest & <best>?" and doc["title"] == doc["question"]
    first = doc["pages"][0]
    assert first["title"] == "Budget by country" and (first["w"], first["h"]) == (1080, 1100)
    assert "Vietnam is cheapest." in first["words"] and first["source"] == "Source: Numbeo"
    assert not any(w.startswith(("Source:", "1/")) for p in doc["pages"] for w in p["words"])
    assert doc["pages"][1]["source"].startswith("Illustrative")
    assert any(p["title"] == "Turbofan: the parts" for p in doc["pages"]) and any(p["title"] == "Turbofan: Fan" for p in doc["pages"])


def test_the_deck_and_the_document_are_whole_packages(tmp_path, monkeypatch):
    store, cid, ans = _story(tmp_path)
    n = len(stage.still_items([r["scene"] for r in stage.story(store, cid, ans)]))
    _drawn(monkeypatch, [(1080, 1100), (1080, 3000)] + [(1080, 1300)] * (n - 2))
    deck, name, doc = asyncio.run(stagedoc.make(store, {}, cid, ans, "ppt", "Aria"))
    assert name == "where-is-life-cheapest-best.pptx"
    z = _check_package(deck, "ppt/presentation.xml")
    slides = sorted(x for x in z.namelist() if x.startswith("ppt/slides/slide"))
    tall = len(stagedoc.bands(1080, 3000))
    assert len(slides) == 1 + (n - 1) + tall, "a title slide, a slide a picture, the tall one over several"
    assert len([x for x in z.namelist() if x.startswith("ppt/media/")]) == n, "a picture is stored once however many bands"
    two = z.read("ppt/slides/slide2.xml").decode()
    assert "Budget by country" in two and "Vietnam is cheapest." in two and "Source: Numbeo" in two
    assert z.read("ppt/slides/slide1.xml").decode().count("&amp; &lt;best&gt;") >= 1, "the question is escaped"
    assert "<a:srcRect" in z.read("ppt/slides/slide3.xml").decode() and "(1 of " in z.read("ppt/slides/slide3.xml").decode()
    word, wname, _ = asyncio.run(stagedoc.make(store, {}, cid, ans, "word", "Aria"))
    assert wname.endswith(".docx")
    w = _check_package(word, "word/document.xml")
    body = w.read("word/document.xml").decode()
    assert body.count("<w:drawing>") == (n - 1) + len(stagedoc.bands(1080, 3000, 1.25))
    assert "Budget by country" in body and 'w:val="Heading1"' in body and "<a:srcRect" in body


def test_with_no_browser_the_file_carries_the_words_and_says_so(tmp_path, monkeypatch):
    store, cid, ans = _story(tmp_path)

    async def none(html, cfg=None):
        return []
    monkeypatch.setattr(stagestill, "render", none)
    deck, _n, doc = asyncio.run(stagedoc.make(store, {}, cid, ans, "pptx"))
    assert not doc["drawn"] and all(not p["png"] for p in doc["pages"])
    z = _check_package(deck, "ppt/presentation.xml")
    assert not [x for x in z.namelist() if x.startswith("ppt/media/")]
    text = "".join(z.read(x).decode() for x in z.namelist() if x.startswith("ppt/slides/slide"))
    assert "no browser to draw the pictures" in text and "Vietnam" in text and "Fan" in text
    assert "in words only" in stagedoc.describe(doc, "pptx")
    from agentos import bpdoc

    async def no_pdf(page, cfg=None):
        assert "window.BP_DOC_DONE=true" in page and "<h1>" in page
        return b""
    monkeypatch.setattr(bpdoc, "pdf", no_pdf)
    with pytest.raises(RuntimeError, match="no browser to print a PDF"):
        asyncio.run(stagedoc.make(store, {}, cid, ans, "pdf"))


def test_the_pdfs_page_carries_every_picture_and_moves_a_band_by_what_was_shown(tmp_path, monkeypatch):
    store, cid, ans = _story(tmp_path)
    n = len(stage.still_items([r["scene"] for r in stage.story(store, cid, ans)]))
    _drawn(monkeypatch, [(1080, 4000)] + [(1080, 1000)] * (n - 1))
    page = stagedoc.html(asyncio.run(stagedoc.gather(store, {}, cid, ans)))
    assert page.count("data:image/png;base64,") == (n - 1) + len(stagedoc.bands(1080, 4000, 1.6))
    assert 'style="top:-0.0%"' in page and "aspect-ratio:1080/" in page and "&lt;best&gt;" in page
    assert "<script>window.BP_DOC_DONE=true</script>" in page and page.count("<script") == 1


def test_the_tool_saves_the_newest_story_into_the_stage_folder_and_never_through_a_link(tmp_path, monkeypatch):
    from agentos import bpfill, tools
    store, cid, ans = _story(tmp_path)
    store.add_message(cid, "user", "send it as a deck")              # the request itself shows nothing
    assert stagedoc.newest(store, cid) == ans
    _drawn(monkeypatch, [(1080, 1000)] * len(stage.still_items([r["scene"] for r in stage.story(store, cid, ans)])))

    async def settle(ids, wait):
        return None
    monkeypatch.setattr(bpfill, "settle", settle)
    ws = tmp_path / "ws"
    ws.mkdir()
    tb = tools.Toolbox({"workspace": str(ws), "agent_name": "Aria"}, store)
    out = asyncio.run(tb.stage_file(format="ppt", _conv=cid))
    path = ws / "stage" / "where-is-life-cheapest-best.pptx"
    assert out.startswith("[saved · PowerPoint] " + str(path)) and "Name this path in your reply" in out
    assert zipfile.is_zipfile(path)
    assert "pptx" in asyncio.run(tb.stage_file(format="xls", _conv=cid)) and "[error]" in asyncio.run(tb.stage_file(format="pdf", _conv=""))
    empty = store.create_conversation("e")
    assert "shown nothing on the Stage yet" in asyncio.run(tb.stage_file(format="docx", _conv=empty))
    # a planted link is refused, as save_report's is
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (ws2 / "stage").symlink_to(tmp_path / "elsewhere")
    tb2 = tools.Toolbox({"workspace": str(ws2)}, store)
    assert "is a link" in asyncio.run(tb2.stage_file(format="docx", _conv=cid)) and not list((tmp_path / "elsewhere").iterdir())


def test_the_tool_is_the_agents_safe_in_the_door_and_asked_for_when_paranoid():
    from agentos import executors, hands, policy, tools, toolscope
    assert "stage_file" in tools.SAFE_TOOLS and "stage_file" not in policy.PARANOID_FREE
    assert "stage_file" in toolscope.CORE and "stage_file" in executors.DOOR_TOOLS
    assert "stage_file" not in executors.STAGE_DOOR_TOOLS, "a board's own refresh has nobody to hand a file to"
    assert any("stage_file" in v for v in hands.GROUPS.values()) and "stage_file" not in hands.READ_ONLY_TOOLS
    schema = next(t for t in tools.TOOL_SCHEMAS if t["name"] == "stage_file")
    assert set(schema["parameters"]["properties"]) == {"format"}, "the chat is never the model's"
    src = (ROOT / "agentos/agent.py").read_text()
    assert '"_conv": self.conversation_id' in src[src.index('if name == "stage_file":'):][:300]
    note = stage.note({"stage": {"big": True}}, tool="mcp__bento__show_scene")
    assert "mcp__bento__stage_file" in note and "name the path it gives" in note and "straight away" in note
    assert "stage_file" in stage.note({"stage": {"big": False}}) and "stage_file" not in stage.BIG_LINE   # the skills never hear it


def test_the_page_offers_the_three_files_as_plain_downloads():
    js = (ROOT / "agentos/ui/src/js/24l-stage.js").read_text()
    assert "function stageSaveMenu(which,cls)" in js and "/api/stage/story/file?format=" in js
    assert "var STAGE_FILES=[['pptx','PowerPoint'" in js and "a.setAttribute('download','')" in js
    assert "innerHTML" not in js
    bp = (ROOT / "agentos/ui/src/js/24v-blueprint.js").read_text()
    assert "'/api/stage/story/file?format='+f[0]+'&sid='" in bp
    css = (ROOT / "agentos/ui/src/css/31-stage.css").read_text()
    assert ".stg-save-a{" in css and "min-height:var(--tap)" in css[css.index(".stg-save-a{"):][:200]
