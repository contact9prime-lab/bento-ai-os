"""A story from the Stage as a file: PowerPoint, Word or PDF.

Asked for as "have word documents, pdf and ppt in the stage". A story could be kept, photographed for a
phone and filmed, and a blueprint could be printed, but an answer could not leave as the file people pass
on: a deck, a document. Three rules:

- **One painter.** The pictures in the file are the ones a phone gets (stagestill.py photographing
  stage.report_html), one per `stage.still_items` view, so a file can never show something the Stage did
  not draw. With no browser on this machine the file carries the scenes' words (`stage.text`) and says so.
- **Written here, no library.** A .pptx and a .docx are zip files of XML, and what a story needs of them
  (a title, a picture, some lines) is small. python-pptx and python-docx are fine licences and a megabyte
  of dependency each for that. The PDF is a page printed by the browser, as a blueprint's sheets are.
- **A tall picture is shown in parts, never shrunk.** A phone's picture can be three times as tall as it is
  wide; fitted whole on a slide its words were a few points high. It is cut into overlapping bands with the
  formats' own crop (`a:srcRect`), so nothing is re-encoded and no image library is needed.

Kept free of HTTP. `make` is the one door: the route, the agent's tool and `bento stage export` call it.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import io
import json
import math
import re
import struct
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as _x

FORMATS = {
    "pptx": ("PowerPoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "docx": ("Word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pdf": ("PDF", "application/pdf"),
}
ALIASES = {"ppt": "pptx", "powerpoint": "pptx", "slides": "pptx", "deck": "pptx", "presentation": "pptx",
           "word": "docx", "doc": "docx", "document": "docx"}
MAX_LINES = 14            # lines of words beside one picture
LINE_CHARS = 220
BAND = 1.15               # a band of a tall picture is at most this many times as tall as it is wide
OVERLAP = .06             # and shares this much with the band before, so no row is cut in two unseen
_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")   # not allowed in XML at all


def fmt_of(word: str) -> str:
    """'ppt', 'Word', '.pdf' → the format's own name; a ValueError names the choices."""
    w = str(word or "").strip().lower().lstrip(".")
    w = ALIASES.get(w, w)
    if w not in FORMATS:
        raise ValueError("a story is saved as pptx (PowerPoint), docx (Word) or pdf")
    return w


def e(v) -> str:
    return _x(_BAD.sub("", str(v if v is not None else "")), {'"': "&quot;"})


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height from a PNG's own header; (0, 0) when it is not one."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return 0, 0
    return struct.unpack(">II", data[16:24])


def bands(w: int, h: int, most: float = BAND) -> list[tuple[float, float]]:
    """A picture as (top, bottom) fractions: one band when it fits, overlapping bands when it is tall."""
    if not w or not h or h / w <= most * 1.3:               # a little over is fitted whole, not cut for a sliver
        return [(0.0, 1.0)]
    part = most * w / h                                   # one band, as a fraction of the height
    n = max(2, math.ceil((1 - part * OVERLAP) / (part * (1 - OVERLAP)) - 1e-9))
    step = (1 - part) / (n - 1)
    return [(round(i * step, 5), round(min(1.0, i * step + part), 5)) for i in range(n)]


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "story").lower()).strip("-")[:48] or "story"


def _lines(text: str, *titles: str) -> list[str]:
    """A caption as lines for a page: without the phone's "2/8", the title it already has, or its source."""
    out = []
    for ln in str(text or "").splitlines():
        ln = re.sub(r"^\s*(?:▶\s*)?(?:\d+/\d+ · )?", "", ln).strip()
        if not ln or ln in titles or ln in out or re.match(r"(?i)^(source:|illustrative\b)", ln):
            continue
        out.append(ln[:LINE_CHARS])
    return out[:MAX_LINES]


def _view_name(sc: dict, view) -> str:
    title = sc.get("title") or sc.get("subject") or sc.get("kind") or "Scene"
    if not view or sc.get("kind") != "blueprint":
        return title
    subject = sc.get("subject") or title
    if view["mode"] == "model":
        return f"{subject}: built in 3D"
    if view["mode"] == "look":
        return f"{subject}: the drawing"
    if view["mode"] == "flows":
        return f"{subject}: how it works"
    if view["path"]:
        from . import stage
        name = {p["id"]: p["name"] for p, _ in stage.bp_walk(sc.get("parts") or [])}
        return f"{subject}: {name.get(view['path'][-1], 'a part')}"
    return f"{subject}: the parts"


def _source(sc: dict) -> str:
    if sc.get("source"):
        return f"Source: {sc['source']}"
    return "Illustrative: these numbers were not measured" if sc.get("illustrative") else ""


async def gather(store, cfg: dict, conversation_id: str, answer_to: str, agent: str = "") -> dict:
    """The story as pages: a title, the picture a phone would get, its words and its source."""
    from . import stage, stagestill
    rows = stage.story(store, conversation_id, answer_to)
    scenes = [r["scene"] for r in rows]
    if not scenes:
        raise KeyError("no story")
    question = stage.question_of(store, answer_to) if answer_to else ""
    items = stage.still_items(scenes)
    pngs = []
    try:
        pngs = await stagestill.render(
            stage.report_html(store, conversation_id, answer_to, agent=agent, still=True), cfg)
    except Exception:
        pngs = []
    drawn = len(pngs) == len(items)
    pages = []
    for i, (sc, view) in enumerate(items):
        title = _view_name(sc, view)
        if drawn:
            words = _lines(stage.still_caption_for(sc, view, i, len(items)), title, sc.get('title') or '', sc.get('subject') or '')
            if sc.get("say") and sc["say"] not in words:
                words.append(str(sc["say"])[:LINE_CHARS])
        else:
            words = _lines(stage.text(sc), title, sc.get('title') or '') if not view or not view.get("path") else []
            if view and view.get("path"):
                continue                                   # with no picture, a part's sheet says nothing new
        png = pngs[i] if drawn else b""
        w, h = png_size(png)
        pages.append({"title": title, "png": png if w else b"", "w": w, "h": h, "words": words,
                      "source": _source(sc), "kind": sc.get("kind") or ""})
        if sc.get("kind") == "video" and sc.get("video"):
            pages[-1]["words"].append(f"https://www.youtube.com/watch?v={sc['video']}")
    title = scenes[0].get("subject") or scenes[0].get("title") or "Story"
    if len(scenes) > 1 and question:
        title = question
    return {"title": str(title)[:160], "question": str(question or "")[:400], "agent": agent or "",
            "date": datetime.date.today().isoformat(), "pages": pages, "drawn": drawn}


# ---------------------------------------------------------------- the zip both formats are

def _zip(parts: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name.endswith(".png") else zipfile.ZIP_DEFLATED
            z.writestr(info, data if isinstance(data, bytes) else data.encode("utf-8"))
    return buf.getvalue()


HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _rels(rows: list[tuple[str, str, str]]) -> str:
    return (HEAD + f'<Relationships xmlns="{PKG_REL}">'
            + "".join(f'<Relationship Id="{i}" Type="{REL}/{t}" Target="{e(tg)}"'
                      + (' TargetMode="External"' if t == "hyperlink" else "") + "/>" for i, t, tg in rows)
            + "</Relationships>")


def _core(doc: dict) -> str:
    stamp = doc["date"] + "T00:00:00Z"
    return (HEAD + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
            'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{e(doc["title"])}</dc:title><dc:creator>{e(doc["agent"] or "Bento Box AI")}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified></cp:coreProperties>')


def _crop(top: float, bottom: float) -> str:
    if top <= 0 and bottom >= 1:
        return ""
    return f'<a:srcRect t="{round(top * 100000)}" b="{round((1 - bottom) * 100000)}"/>'


def _byline(doc: dict) -> str:
    return " · ".join(x for x in (doc["agent"], doc["date"], "Bento Box AI") if x)


# ---------------------------------------------------------------- PowerPoint

EMU = 914400
SLIDE_W, SLIDE_H = 12192000, 6858000            # 13.333 x 7.5 in, 16:9
INK, PALE, GOLD, NIGHT = "F4EAD6", "A9B8CC", "FFD98A", "0F1724"

_THEME = (HEAD + f'<a:theme xmlns:a="{A_NS}" name="Bento"><a:themeElements><a:clrScheme name="Bento">'
          '<a:dk1><a:srgbClr val="0F1724"/></a:dk1><a:lt1><a:srgbClr val="F4EAD6"/></a:lt1>'
          '<a:dk2><a:srgbClr val="1C2A40"/></a:dk2><a:lt2><a:srgbClr val="A9B8CC"/></a:lt2>'
          '<a:accent1><a:srgbClr val="FFD98A"/></a:accent1><a:accent2><a:srgbClr val="6FB7E9"/></a:accent2>'
          '<a:accent3><a:srgbClr val="8FD19E"/></a:accent3><a:accent4><a:srgbClr val="E9886F"/></a:accent4>'
          '<a:accent5><a:srgbClr val="B79CE9"/></a:accent5><a:accent6><a:srgbClr val="E9C46F"/></a:accent6>'
          '<a:hlink><a:srgbClr val="6FB7E9"/></a:hlink><a:folHlink><a:srgbClr val="B79CE9"/></a:folHlink>'
          '</a:clrScheme><a:fontScheme name="Bento"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/>'
          '<a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/>'
          '<a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Bento"><a:fillStyleLst>'
          + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3 + '</a:fillStyleLst><a:lnStyleLst>'
          + '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3
          + '</a:lnStyleLst><a:effectStyleLst>' + '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3
          + '</a:effectStyleLst><a:bgFillStyleLst>' + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
          + '</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')

_P_NS = (f'xmlns:a="{A_NS}" xmlns:r="{REL}" '
         'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
_TREE = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm>'
         '<a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')
_CLR = ('<p:clrMap bg1="dk1" tx1="lt1" bg2="dk2" tx2="lt2" accent1="accent1" accent2="accent2" accent3="accent3" '
        'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>')
_BG = (f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{NIGHT}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>')


def _box(n: int, x: int, y: int, w: int, h: int, paras: list[tuple[str, int, str, bool]], anchor: str = "t") -> str:
    """A text box: paras are (text, size in points, colour, bold)."""
    body = "".join(
        f'<a:p><a:pPr><a:spcAft><a:spcPts val="{round(sz * 45)}"/></a:spcAft></a:pPr><a:r>'
        f'<a:rPr lang="en-US" sz="{sz * 100}" b="{1 if bold else 0}" dirty="0"><a:solidFill><a:srgbClr val="{col}"/>'
        f'</a:solidFill></a:rPr><a:t>{e(text)}</a:t></a:r></a:p>' for text, sz, col, bold in paras) or "<a:p/>"
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{n}" name="Text {n}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>'
            f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
            f'</a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" '
            f'anchor="{anchor}"><a:normAutofit/></a:bodyPr><a:lstStyle/>{body}</p:txBody></p:sp>')


def _pic(n: int, rid: str, x: int, y: int, w: int, h: int, top: float, bottom: float, name: str) -> str:
    return (f'<p:pic><p:nvPicPr><p:cNvPr id="{n}" name="Picture {n}" descr="{e(name)}"/><p:cNvPicPr>'
            '<a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill>'
            f'<a:blip r:embed="{rid}"/>{_crop(top, bottom)}<a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr>'
            f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
            '</a:prstGeom></p:spPr></p:pic>')


def _slide(shapes: str) -> str:
    return (HEAD + f'<p:sld {_P_NS}><p:cSld>{_BG}<p:spTree>{_TREE}{shapes}</p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def pptx(doc: dict) -> bytes:
    """The story as a deck: a title slide, then a slide per picture (a tall one over several)."""
    m = EMU // 2                                             # half an inch of margin
    slides, media = [], {}
    title = [_box(2, m, round(2.1 * EMU), SLIDE_W - 2 * m, round(1.9 * EMU), [(doc["title"], 40, INK, True)], "b"),
             _box(3, m, round(4.2 * EMU), SLIDE_W - 2 * m, round(1.6 * EMU),
                  ([(doc["question"], 20, PALE, False)] if doc["question"] and doc["question"] != doc["title"] else [])
                  + [(_byline(doc), 14, GOLD, False)])]
    slides.append(("".join(title), ""))
    if not doc["drawn"]:
        slides[0] = (slides[0][0] + _box(4, m, round(6.4 * EMU), SLIDE_W - 2 * m, round(.6 * EMU), [(
            "This machine had no browser to draw the pictures with, so the scenes are given in words.", 12, PALE, False)]), "")
    top, hgt = round(1.35 * EMU), SLIDE_H - round(1.35 * EMU) - round(.75 * EMU)
    for pi, pg in enumerate(doc["pages"]):
        img = ""
        if pg["png"]:
            img = f"image{len(media) + 1}.png"
            media[img] = pg["png"]
        cuts = bands(pg["w"], pg["h"]) if img else [(0.0, 1.0)]
        for ci, (a, b) in enumerate(cuts):
            head = pg["title"] + (f" ({ci + 1} of {len(cuts)})" if len(cuts) > 1 else "")
            sh = [_box(2, m, round(.42 * EMU), SLIDE_W - 2 * m, round(.8 * EMU), [(head, 26, INK, True)], "ctr")]
            words = pg["words"] if ci == 0 else []
            if img:
                ratio = pg["w"] / (pg["h"] * (b - a))            # width over height of what is shown
                boxw = round((6.0 if words else 12.3) * EMU)
                w = min(boxw, round(hgt * ratio))
                h = round(w / ratio)
                x = m + (boxw - w) // 2 if words else (SLIDE_W - w) // 2
                sh.append(_pic(3, "rId2", x, top + (hgt - h) // 2, w, h, a, b, head))
            if words:
                tx = m + round(6.4 * EMU) if img else m
                size = 18 if len(words) <= 7 else 15 if len(words) <= 10 else 13
                sh.append(_box(4, tx, top, SLIDE_W - m - tx, hgt, [(w_, size, INK, False) for w_ in words],
                               "ctr" if img else "t"))
            foot = " · ".join(x for x in (pg["source"], f"{len(slides) + 1}") if x)
            sh.append(_box(5, m, SLIDE_H - round(.55 * EMU), SLIDE_W - 2 * m, round(.3 * EMU), [(foot, 11, PALE, False)]))
            slides.append(("".join(sh), img))
    parts = {
        "[Content_Types].xml": HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'presentationml.presentation.main+xml"/><Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/><Override PartName='
        '"/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'presentationml.slideLayout+xml"/><Override PartName="/ppt/theme/theme1.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.theme+xml"/><Override PartName="/docProps/core.xml" ContentType='
        '"application/vnd.openxmlformats-package.core-properties+xml"/>'
        + "".join(f'<Override PartName="/ppt/slides/slide{i + 1}.xml" ContentType="application/vnd.openxmlformats-'
                  'officedocument.presentationml.slide+xml"/>' for i in range(len(slides))) + "</Types>",
        "_rels/.rels": HEAD + f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{REL}/officeDocument" '
        'Target="ppt/presentation.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
        'relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>',
        "docProps/core.xml": _core(doc),
        "ppt/presentation.xml": HEAD + f'<p:presentation {_P_NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" '
        'r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
        + "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 2}"/>' for i in range(len(slides)))
        + f'</p:sldIdLst><p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>',
        "ppt/_rels/presentation.xml.rels": _rels(
            [("rId1", "slideMaster", "slideMasters/slideMaster1.xml")]
            + [(f"rId{i + 2}", "slide", f"slides/slide{i + 1}.xml") for i in range(len(slides))]
            + [(f"rId{len(slides) + 2}", "theme", "theme/theme1.xml")]),
        "ppt/theme/theme1.xml": _THEME,
        "ppt/slideMasters/slideMaster1.xml": HEAD + f'<p:sldMaster {_P_NS}><p:cSld>{_BG}<p:spTree>{_TREE}</p:spTree>'
        f'</p:cSld>{_CLR}<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        '<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>',
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _rels(
            [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"), ("rId2", "theme", "../theme/theme1.xml")]),
        "ppt/slideLayouts/slideLayout1.xml": HEAD + f'<p:sldLayout {_P_NS} type="blank" preserve="1"><p:cSld name="Blank">'
        f'<p:spTree>{_TREE}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>',
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")]),
    }
    for i, (shapes, img) in enumerate(slides):
        parts[f"ppt/slides/slide{i + 1}.xml"] = _slide(shapes)
        parts[f"ppt/slides/_rels/slide{i + 1}.xml.rels"] = _rels(
            [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")]
            + ([("rId2", "image", f"../media/{img}")] if img else []))
    for name, data in media.items():
        parts[f"ppt/media/{name}"] = data
    return _zip(parts)


# ---------------------------------------------------------------- Word

_W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
         f'xmlns:r="{REL}" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
         f'xmlns:a="{A_NS}" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
PAGE_W = round(6.5 * EMU)                       # Letter and A4 both leave at least this between inch margins


def _para(text: str, style: str = "", brk: bool = False) -> str:
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + ("<w:pageBreakBefore/>" if brk else "")
    return (f'<w:p>{"<w:pPr>" + ppr + "</w:pPr>" if ppr else ""}<w:r><w:t xml:space="preserve">{e(text)}</w:t></w:r></w:p>')


def _wpic(n: int, rid: str, w: int, h: int, top: float, bottom: float, name: str) -> str:
    return ('<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{w}" cy="{h}"/><wp:docPr id="{n}" name="Picture {n}" descr="{e(name)}"/><a:graphic>'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr>'
            f'<pic:cNvPr id="{n}" name="Picture {n}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/>'
            f'{_crop(top, bottom)}<a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def _wstyle(sid: str, name: str, size: int, bold: bool, colour: str, after: int, base: str = "Normal") -> str:
    return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="{base}"/>'
            f'<w:pPr><w:keepNext/><w:spacing w:before="{after}" w:after="{after}"/></w:pPr><w:rPr>'
            + ("<w:b/>" if bold else "") + f'<w:color w:val="{colour}"/><w:sz w:val="{size * 2}"/></w:rPr></w:style>')


def docx(doc: dict) -> bytes:
    """The story as a document: its title and question, then each picture under its heading with its words."""
    body = [_para(doc["title"], "Title")]
    if doc["question"] and doc["question"] != doc["title"]:
        body.append(_para(doc["question"], "Subtitle"))
    body.append(_para(_byline(doc), "Byline"))
    if not doc["drawn"]:
        body.append(_para("This machine had no browser to draw the pictures with, so the scenes are given in words.", "Source"))
    rels, media, n = [], {}, 0
    for pi, pg in enumerate(doc["pages"]):
        body.append(_para(pg["title"], "Heading1", brk=pi > 0 and bool(pg["png"])))
        if pg["png"]:
            name = f"image{len(media) + 1}.png"
            media[name] = pg["png"]
            rid = f"rId{len(media) + 1}"
            rels.append((rid, "image", f"media/{name}"))
            for a, b in bands(pg["w"], pg["h"], 1.25):
                ratio = pg["w"] / (pg["h"] * (b - a))
                w = min(round(4.6 * EMU), round(6.2 * EMU * ratio))
                n += 1
                body.append(_wpic(n, rid, w, round(w / ratio), a, b, pg["title"]))
        body += [_para(w_) for w_ in pg["words"]]
        if pg["source"]:
            body.append(_para(pg["source"], "Source"))
    styles = (HEAD + f'<w:styles {_W_NS}><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" '
              'w:cs="Calibri"/><w:sz w:val="22"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
              '<w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              + _wstyle("Title", "Title", 28, True, "0F1724", 120)
              + _wstyle("Subtitle", "Subtitle", 14, False, "44546A", 80)
              + _wstyle("Byline", "Byline", 10, False, "7A6A3A", 240)
              + _wstyle("Heading1", "heading 1", 16, True, "1C2A40", 160)
              + _wstyle("Source", "Source", 9, False, "6B7280", 60) + "</w:styles>")
    document = (HEAD + f'<w:document {_W_NS}><w:body>{"".join(body)}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" '
                'w:gutter="0"/></w:sectPr></w:body></w:document>')
    parts = {
        "[Content_Types].xml": HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>',
        "_rels/.rels": HEAD + f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{REL}/officeDocument" '
        'Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
        'relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>',
        "docProps/core.xml": _core(doc),
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/_rels/document.xml.rels": _rels([("rId1", "styles", "styles.xml")] + rels),
    }
    for name, data in media.items():
        parts[f"word/media/{name}"] = data
    return _zip(parts)


# ---------------------------------------------------------------- PDF (a page, printed)

_CSS = """@page{size:A4;margin:14mm}*{box-sizing:border-box}
body{margin:0;font:11pt/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#141a26}
h1{font-size:24pt;line-height:1.15;margin:0 0 4mm}.q{font-size:13pt;color:#44546a;margin:0 0 3mm}
.by{font-size:9.5pt;color:#7a6a3a;margin:0 0 8mm}section{break-before:page}section.first{break-before:auto}
h2{font-size:15pt;margin:0 0 4mm;color:#1c2a40;break-after:avoid}
.band{width:100mm;margin:0 auto 3mm;overflow:hidden;border-radius:2mm;break-inside:avoid;position:relative}
.band img{display:block;width:100%;position:absolute;left:0}
p{margin:0 0 2mm}.src{font-size:8.5pt;color:#6b7280;margin-top:3mm}"""


def html(doc: dict) -> str:
    """The page the PDF is printed from. Self-contained: every picture is in it."""
    out = [f'<h1>{e(doc["title"])}</h1>']
    if doc["question"] and doc["question"] != doc["title"]:
        out.append(f'<p class="q">{e(doc["question"])}</p>')
    out.append(f'<p class="by">{e(_byline(doc))}</p>')
    if not doc["drawn"]:
        out.append('<p class="src">This machine had no browser to draw the pictures with, so the scenes are given in words.</p>')
    for pi, pg in enumerate(doc["pages"]):
        sec = [f'<h2>{e(pg["title"])}</h2>']
        if pg["png"]:
            uri = "data:image/png;base64," + base64.b64encode(pg["png"]).decode()
            for a, b in bands(pg["w"], pg["h"], 1.6):
                # the band's own height, and the picture moved up inside it by the part already shown
                sec.append(f'<div class="band" style="aspect-ratio:{pg["w"]}/{round(pg["h"] * (b - a), 2)}">'
                           f'<img src="{uri}" alt="{e(pg["title"])}" style="top:-{round(a / (b - a) * 100, 3)}%"></div>')
        sec += [f"<p>{e(w_)}</p>" for w_ in pg["words"]]
        if pg["source"]:
            sec.append(f'<p class="src">{e(pg["source"])}</p>')
        out.append(f'<section class="{"first" if pi == 0 or not pg["png"] else ""}">{"".join(sec)}</section>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(doc["title"])}</title>'
            f'<style>{_CSS}</style></head><body>{"".join(out)}<script>window.BP_DOC_DONE=true</script></body></html>')


# ---------------------------------------------------------------- the one door

async def make(store, cfg: dict, conversation_id: str, answer_to: str, fmt: str, agent: str = "") -> tuple[bytes, str, dict]:
    """(the file's bytes, its name, the story it was made from). KeyError when there is no story;
    RuntimeError, in a sentence, when a PDF was asked for and this machine has no browser to print it."""
    fmt = fmt_of(fmt)
    doc = await gather(store, cfg, conversation_id, answer_to, agent)
    name = f"{slug(doc['title'])}.{fmt}"
    if fmt == "pptx":
        return await asyncio.to_thread(pptx, doc), name, doc
    if fmt == "docx":
        return await asyncio.to_thread(docx, doc), name, doc
    from . import bpdoc
    data = await bpdoc.pdf(html(doc), cfg)
    if not data:
        raise RuntimeError("this machine has no browser to print a PDF with; save it as Word or PowerPoint instead")
    return data, name, doc


async def to_file(store, cfg: dict, conversation_id: str, answer_to: str, fmt: str, folder, agent: str = "") -> Path:
    """The file written under `folder`/stage, where the chat's file chips and a phone's send_files find it."""
    data, name, _doc = await make(store, cfg, conversation_id, answer_to, fmt, agent)
    d = Path(folder) / "stage"
    if d.is_symlink():                       # save_report's lesson: a planted link wrote into another folder
        raise RuntimeError("the stage folder is a link, so nothing was saved there")
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def newest(store, conversation_id: str) -> str:
    """The question (message id) of the newest story a chat showed; KeyError when it showed none. Asked "send
    it as a deck", the person's last message is that request, which has no scenes of its own."""
    from . import stage
    told = [st for st in stage.stories(store, conversation_id) if st.get("scenes")]
    if not told:
        raise KeyError("no story")
    return max(told, key=lambda st: max(r["created_at"] for r in st["scenes"]))["answer_to"]


def describe(doc: dict, fmt: str) -> str:
    n = len(doc["pages"])
    return (f"{FORMATS[fmt][0]}, {n} scene{'s' if n != 1 else ''}"
            + ("" if doc["drawn"] else ", in words only (no browser here to draw the pictures)"))


__all__ = ["FORMATS", "fmt_of", "gather", "pptx", "docx", "html", "make", "to_file", "bands", "png_size", "describe"]
_ = json   # kept for callers that read a scene row beside this module
