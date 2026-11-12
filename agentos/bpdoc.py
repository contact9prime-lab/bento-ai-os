"""A blueprint as a document: a set of drawing sheets you can keep, print or send.

Asked for as "you should be able to export the blueprint, like a crazy style document". It is
laid out as an engineering drawing set: landscape sheets with a frame, registration marks and a
title block (sheet n of m, document number, date, who prepared it), in the Stage's own ink. A
cover with the drawing and the key numbers, an overview of the parts, how it works, one sheet per
main part (its steps, comparison, materials, limits, numbers and what's inside it), and a last
sheet of what nobody outside can know, the sources and the picture credits (a CC BY picture must
be credited wherever it's shown).

The figures are drawn by the Stage's own painter (24v-blueprint.js) inside the page, so there is
still one painter; the words are written here, escaped. `pdf` prints the page in a throwaway
headless Chromium (stagestill's browser, over a pipe). Nothing here reaches the network; a picture
kept as an asset travels inside the file.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import html as _h
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from . import stage as stagemod

SHEET_PARTS = 12          # main parts given a sheet of their own
INSIDE_ROWS = 14
PDF_TIMEOUT = 60


def _e(v) -> str:
    return _h.escape(str(v if v is not None else ""))


def doc_number(scene_id: str, sc: dict) -> str:
    base = re.sub(r"[^A-Z0-9]+", "", (sc.get("subject") or sc.get("title") or "BP").upper())[:6] or "BP"
    return f"BP-{base}-{(scene_id or '0000')[:4].upper()}"


def _facts(facts: list) -> str:
    if not facts:
        return ""
    rows = "".join(f"<tr><th>{_e(f.get('label'))}</th><td>{_e(stagemod.bp_value(f))}</td></tr>" for f in facts)
    return f'<table class="spec">{rows}</table>'


def _pic(pic: dict | None, name: str, big: bool = False) -> str:
    if not pic or not pic.get("url"):
        return ""
    cls = "pic" + (" drawn" if pic.get("made") == "drawn" else "") + (" big" if big else "")
    cred = (f"Illustrative drawing by {_e(pic.get('credit') or 'an image model')}" if pic.get("made") == "drawn"
            else f"{_e(pic.get('title'))} · {_e(pic.get('credit'))} · {_e(pic.get('licence'))} · Wikimedia Commons")
    return (f'<figure class="{cls}"><div class="ink"><img src="{_e(pic["url"])}" alt="Drawing of {_e(name)}"></div>'
            f'<figcaption>{cred}</figcaption></figure>')


def _block(label: str, body: str) -> str:
    return f'<div class="blk"><div class="lbl">{_e(label)}</div>{body}</div>' if body else ""


def _part_words(p: dict) -> str:
    out = ""
    if p.get("role"):
        out += f'<p class="role">{_e(p["role"])}</p>'
    if p.get("how"):
        out += _block("How it works", f"<p>{_e(p['how'])}</p>")
    if p.get("steps"):
        out += '<ol class="steps">' + "".join(f"<li>{_e(s)}</li>" for s in p["steps"]) + "</ol>"
    if p.get("like"):
        out += f'<p class="like">≈ {_e(p["like"])}</p>'
    if p.get("made_of"):
        out += _block("Made of", f"<p>{_e(p['made_of'])}</p>")
    if p.get("limits"):
        out += _block("Limits", f"<p>{_e(p['limits'])}</p>")
    if p.get("facts"):
        out += _block("Numbers", _facts(p["facts"]))
    return out


def _inside(p: dict) -> str:
    kids = p.get("parts") or []
    if not kids:
        return ""
    rows = []
    for i, k in enumerate(kids[:INSIDE_ROWS], 1):
        f = "; ".join(f"{x['label']} {stagemod.bp_value(x)}" for x in (k.get("facts") or [])[:3])
        sub = ", ".join(c["name"] for c in (k.get("parts") or [])[:6])
        rows.append(f"<tr><td class='n'>{i}</td><td><b>{_e(k['name'])}</b>"
                    + (f"<div class='r'>{_e(k.get('role'))}</div>" if k.get("role") else "")
                    + (f"<div class='sub'>⊂ {_e(sub)}</div>" if sub else "")
                    + f"</td><td class='f'>{_e(f)}</td></tr>")
    more = f"<p class='more'>and {len(kids) - INSIDE_ROWS} more</p>" if len(kids) > INSIDE_ROWS else ""
    return _block(f"Inside · {len(kids)} parts", "<table class='inside'>" + "".join(rows) + "</table>" + more)


def html(store, scene_id: str, agent: str = "", question: str = "") -> str:
    """The whole document for one blueprint scene, self-contained. Raises KeyError when the
    scene is not here and ValueError when it is not a blueprint."""
    r = store.db.execute("SELECT scene FROM stage_scenes WHERE id=?", (scene_id,)).fetchone()
    if not r:
        raise KeyError(scene_id)
    sc = json.loads(r[0])
    if sc.get("kind") != "blueprint":
        raise ValueError("only a blueprint can be exported as a document")
    sc = stagemod._inline_picture(store, sc)
    subject = sc.get("subject") or sc.get("title") or "Blueprint"
    parts = sc.get("parts") or []
    flows = stagemod.bp_top_links(sc)
    n_all = sum(1 for _ in stagemod.bp_walk(parts))
    depth = max((d for _, d in stagemod.bp_walk(parts)), default=1)
    docno = doc_number(scene_id, sc)
    when = time.strftime("%d %b %Y")
    sheets: list[tuple[str, str]] = []          # (title, inner html)

    # 1. the cover
    lead = _pic(sc.get("picture"), subject, big=True) or '<div class="fig cover" data-mode="parts" data-path=""></div>'
    sheets.append(("Cover", f"""
<div class="cover-grid"><div class="cover-art">{lead}</div>
<div class="cover-words"><div class="kick">Blueprint · {len(parts)} main parts · {n_all} in all · {depth} levels</div>
<h1>{_e(subject)}</h1>{f'<p class="q">“{_e(question)}”</p>' if question else ''}
{f'<p class="role">{_e(sc.get("caption"))}</p>' if sc.get("caption") else ''}
{_block("Key numbers", _facts(sc.get("facts") or []))}
<div class="toc"><div class="lbl">Sheets</div><ol>
<li>Cover</li><li>The parts</li>{'<li>How it works</li>' if flows else ''}
{''.join(f'<li>{_e(p["name"])}</li>' for p in parts[:SHEET_PARTS])}<li>Unknowns, sources and credits</li></ol></div>
</div></div>"""))

    # 2. the parts, drawn, with a numbered legend
    legend = "".join(f"<li><b>{_e(p['name'])}</b>" + (f" <span>{_e(p.get('role'))}</span>" if p.get("role") else "")
                     + "</li>" for p in parts)
    sheets.append(("The parts", f"""<h2 class="sh">The parts</h2><div class="two"><div class="fig" data-mode="parts" data-path=""></div>
<div class="side"><div class="lbl">Main parts</div><ol class="legend">{legend}</ol></div></div>"""))

    # 3. how it works
    if flows:
        name = {p["id"]: p["name"] for p, _ in stagemod.bp_walk(parts)}
        by: dict = {}
        for ln in flows:
            by.setdefault(ln.get("kind") or "other", []).append(ln)
        lists = "".join(f"<div class='blk'><div class='lbl'>{_e(k)}</div><ul class='flows'>"
                        + "".join(f"<li>{_e(name.get(l['from']))} <i>{_e(l.get('verb') or '→')}</i> "
                                  f"{_e(name.get(l['to']))}</li>" for l in ls) + "</ul></div>"
                        for k, ls in by.items())
        sheets.append(("How it works", f"""<h2 class="sh">How it works</h2><div class="two"><div class="fig" data-mode="flows" data-path=""></div>
<div class="side">{lists}</div></div>"""))

    # 4. a sheet per main part
    for p in parts[:SHEET_PARTS]:
        art = (_pic(p.get("picture"), p["name"]) if p.get("picture") else "")
        if p.get("parts"):
            art += f'<div class="fig part" data-mode="parts" data-path="{_e(p["id"])}"></div>'
        cert = "" if p.get("certainty", "known") == "known" else f'<span class="cert">{_e(p["certainty"])}</span>'
        src = f'<p class="src">Source: {_e(p["source"])}</p>' if p.get("source") else ""
        sheets.append((p["name"], f"""<div class="part-head"><h2>{_e(p['name'])}</h2>{cert}</div>
<div class="two part"><div class="art">{art or '<div class="none">Nothing inside it was drawn.</div>'}</div>
<div class="side">{_part_words(p)}{_inside(p)}{src}</div></div>"""))

    # 5. what nobody can know, the sources, the credits
    unknowns = list(sc.get("unknowns") or []) + [f"{p['name']}: {u}" for p, _ in stagemod.bp_walk(parts)
                                                for u in p.get("unknowns") or []]
    sources = []
    for s in [sc.get("source")] + [p.get("source") for p, _ in stagemod.bp_walk(parts)]:
        if s and s not in sources:
            sources.append(s)
    credits = []
    for pic in [sc.get("picture")] + [p.get("picture") for p in parts]:
        if pic:
            line = stagemod.bp_picture_line(pic).removeprefix("▣ ")
            if line not in credits:
                credits.append(line)
    sheets.append(("Unknowns, sources and credits", f"""<h2 class="sh">Unknowns, sources and credits</h2><div class="cols3">
{_block("Still unclear", "<ul>" + "".join(f"<li>{_e(u)}</li>" for u in unknowns[:24]) + "</ul>") if unknowns else _block("Still unclear", "<p>Nothing was marked unclear.</p>")}
{_block("Sources", "<ul>" + "".join(f"<li>{_e(s)}</li>" for s in sources[:30]) + "</ul>") if sources else ""}
{_block("Pictures", "<ul>" + "".join(f"<li>{_e(c)}</li>" for c in credits) + "</ul>") if credits else ""}
</div><div class="legend-lines"><span class="k">— known</span><span class="e">- - estimated</span><span class="u">··· unclear</span></div>
<p class="note">Numbers carry their source. A number marked estimated was worked out or remembered loosely.
Prepared by {_e(agent or 'your agent')} with Bento Box AI.</p>"""))

    total = len(sheets)
    body = "".join(f"""<section class="sheet" id="s{i}"><i class="rm tl"></i><i class="rm tr"></i><i class="rm bl"></i><i class="rm br"></i>
<div class="inner">{inner}</div>
<table class="tb"><tr><th>Title</th><td colspan="3">{_e(subject)} · {_e(title)}</td></tr>
<tr><th>Doc</th><td>{_e(docno)}</td><th>Sheet</th><td>{i} of {total}</td></tr>
<tr><th>Date</th><td>{_e(when)}</td><th>By</th><td>{_e(agent or 'Bento')}</td></tr></table></section>"""
                   for i, (title, inner) in enumerate(sheets, 1))
    js = "\n".join((stagemod._UI / f"src/js/{f}").read_text(encoding="utf-8") for f in stagemod.PAINTER_JS)
    css = "\n".join((stagemod._UI / f"src/css/{f}").read_text(encoding="utf-8") for f in stagemod.PAINTER_CSS)
    data = json.dumps(sc).replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(subject)} · Blueprint {_e(docno)}</title>
<style>{stagemod.REPORT_TOKENS}
{css}
{DOC_CSS}</style></head><body class="bpdoc">{body}
<script>window.STAGE_REPORT=true;window.STAGE_STILL=true;
{js}
(function(){{
  var SC={data};
  document.querySelectorAll('.fig').forEach(function(f){{
    var art=document.createElement('div');art.className='stg-art st-art bp-doc-art';f.append(art);
    var path=f.dataset.path?[f.dataset.path]:[];
    try{{stageBlueprint(art,Object.assign({{}},SC,{{_view:{{mode:f.dataset.mode||'parts',path:path}}}}))}}
    catch(e){{art.textContent='This figure could not be drawn.'}}
  }});
  window.BP_DOC_DONE=true;
}})();
</script></body></html>"""


# Landscape A4 drawing sheets in the Stage's ink: navy paper with a grid, a cyan frame,
# registration marks at the corners and a title block bottom right on every sheet.
DOC_CSS = r"""
@page{size:297mm 210mm;margin:0}
html,body.bpdoc{background:#020a18;margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.bpdoc{--ink:#7dd3fc;--hi:#f0f9ff;--paper:#061a33;--line:rgba(125,211,252,.25);color:#e0f2fe;font:13px/1.5 var(--sans)}
.sheet{position:relative;width:297mm;height:210mm;box-sizing:border-box;margin:0 auto 18px;padding:12mm 12mm 30mm;
  background:var(--paper);overflow:hidden;break-after:page;page-break-after:always;
  background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px),
    linear-gradient(rgba(125,211,252,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(125,211,252,.08) 1px,transparent 1px);
  background-size:40px 40px,40px 40px,8px 8px,8px 8px;
  box-shadow:inset 0 0 0 6mm var(--paper),inset 0 0 0 calc(6mm + 1.5px) var(--ink)}
@media print{.sheet{margin:0}}
.rm{position:absolute;width:9mm;height:9mm;border:0 solid var(--ink)}
.rm.tl{left:3mm;top:3mm;border-left-width:2px;border-top-width:2px}.rm.tr{right:3mm;top:3mm;border-right-width:2px;border-top-width:2px}
.rm.bl{left:3mm;bottom:3mm;border-left-width:2px;border-bottom-width:2px}.rm.br{right:3mm;bottom:3mm;border-right-width:2px;border-bottom-width:2px}
.inner{position:relative;height:100%;overflow:hidden}
.tb{position:absolute;right:9mm;bottom:8mm;border-collapse:collapse;font:600 9.5px ui-monospace,Menlo,monospace;
  background:rgba(2,12,27,.9);color:var(--hi);min-width:110mm}
.tb th,.tb td{border:1px solid var(--ink);padding:3px 7px;text-align:left}
.tb th{color:var(--ink);letter-spacing:.12em;text-transform:uppercase;font-size:8px;width:12mm}
h1{font:800 44px/1.05 var(--sans);margin:4px 0 10px;color:var(--hi);letter-spacing:-.01em}
h2{font:800 28px/1.1 var(--sans);margin:0;color:var(--hi)}
.kick,.lbl{font:700 10px ui-monospace,Menlo,monospace;letter-spacing:.16em;text-transform:uppercase;color:#fcd34d}
.lbl{margin:10px 0 4px;padding-bottom:3px;border-bottom:1px solid var(--line)}
.q{font:italic 15px var(--sans);color:#bae6fd;margin:0 0 8px}
.role{font:600 15px/1.4 var(--sans);color:var(--hi);margin:0 0 6px}
p{margin:0 0 6px}
.cover-grid{display:grid;grid-template-columns:1.35fr 1fr;gap:10mm;height:100%}
.cover-art{display:flex;align-items:center;min-height:0}
.cover-art .fig,.cover-art .pic{width:100%}
.two{display:grid;grid-template-columns:1.5fr 1fr;gap:8mm;height:calc(100% - 14mm);min-height:0}
.sh{margin-bottom:4mm}
.two.part{height:calc(100% - 14mm);grid-template-columns:1.25fr 1fr}
.part-head{display:flex;align-items:center;gap:10px;margin-bottom:4mm}
.cert{font:700 10px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.12em;border:1px dashed var(--ink);padding:2px 7px;border-radius:4px;color:var(--ink)}
.side{min-height:0;overflow:hidden}
.art{display:flex;flex-direction:column;gap:3mm;min-height:0}
.art .pic img{max-height:58mm}
.fig{height:120mm;position:relative}
.fig.part{flex:1;height:auto;min-height:60mm}
.cover .fig,.cover-art .fig{height:150mm}
.bp-doc-art{height:100%;display:flex}
.bp-doc-art .bp{flex:1;display:block;height:100%}
.bp-doc-art .bp-crumbs,.bp-doc-art .bp-spec,.bp-doc-art .bp-peek{display:none!important}
.bp-doc-art .bp-body{display:block;height:100%}
.bp-doc-art .bp-draw{height:100%;background:transparent;box-shadow:inset 0 0 0 1px var(--line)}
.pic{margin:0}
.pic .ink{background:var(--paper);border:1px solid var(--line);border-radius:4px;display:flex;align-items:center;justify-content:center;padding:4mm}
.pic img{max-width:100%;max-height:110mm;object-fit:contain;mix-blend-mode:screen;
  filter:grayscale(1) invert(1) sepia(1) hue-rotate(160deg) saturate(2.4) brightness(1.08) contrast(1.15)}
.pic.big img{max-height:140mm}
.pic.drawn img{mix-blend-mode:normal;filter:none}
.pic figcaption{font:500 9px var(--sans);color:rgba(186,230,253,.7);margin-top:2px}
.spec{border-collapse:collapse;width:100%;font:12px ui-monospace,Menlo,monospace}
.spec th{text-align:left;font-weight:500;color:rgba(186,230,253,.7);text-transform:uppercase;letter-spacing:.06em;font-size:10px;padding:2px 0;border-bottom:1px dotted var(--line)}
.spec td{text-align:right;color:var(--hi);font-weight:700;padding:2px 0;border-bottom:1px dotted var(--line)}
.steps{margin:4px 0 6px;padding-left:0;list-style:none;counter-reset:s}
.steps li{counter-increment:s;position:relative;padding:3px 0 3px 30px;border-left:1px solid var(--line);margin-left:10px}
.steps li::before{content:counter(s);position:absolute;left:-11px;top:2px;width:20px;height:20px;border-radius:50%;
  background:var(--paper);border:1.5px solid var(--ink);color:var(--hi);font:700 11px/18px ui-monospace,monospace;text-align:center}
.like{font:italic 13px var(--sans);color:#bae6fd}
.legend{margin:0;padding-left:20px}.legend li{margin:3px 0}.legend span{color:rgba(224,242,254,.7)}
.inside{border-collapse:collapse;width:100%;font-size:10.5px}
.inside td{border-top:1px solid var(--line);padding:3px 6px;vertical-align:top}
.inside .n{width:16px;color:var(--ink);font:700 11px ui-monospace,monospace}
.inside .r{color:rgba(224,242,254,.75)}.inside .sub{color:rgba(125,211,252,.75);font-size:10.5px}
.inside .f{font:11px ui-monospace,monospace;color:var(--hi);width:38%}
.flows{margin:0;padding-left:16px}.flows i{color:#fcd34d}
.toc ol{margin:0;padding-left:20px;columns:2;font-size:12px}
.cols3{display:grid;grid-template-columns:repeat(3,1fr);gap:8mm}
.cols3 ul{margin:0;padding-left:16px;font-size:11.5px}
.legend-lines{display:flex;gap:16px;margin-top:6mm;font:11px ui-monospace,monospace;color:var(--ink)}
.note{margin-top:4mm;color:rgba(224,242,254,.7);font-size:11px}
.none{color:rgba(186,230,253,.6);font-style:italic}
.more{color:rgba(186,230,253,.6);font-size:11px}
.src{font-size:10.5px;color:rgba(186,230,253,.7)}
"""


async def pdf(page_html: str, cfg: dict | None = None) -> bytes:
    """The document printed to PDF by a throwaway headless Chromium; b'' when there is none."""
    from . import cdpbrowser
    binary = cdpbrowser.binary(cfg)
    if not binary:
        return b""
    tmp = Path(tempfile.mkdtemp(prefix="bento-doc-"))
    proc = None
    try:
        page = tmp / "doc.html"
        page.write_text(page_html, encoding="utf-8")
        args = [binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={tmp / 'p'}",
                "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                "--disable-sync", "--mute-audio", "--hide-scrollbars", "--force-color-profile=srgb",
                "--window-size=1123,794", "about:blank"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(2, "--no-sandbox")
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", 'exec "$0" "$@" 3<&0 4>&1 0</dev/null 1>/dev/null', *args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=256 * 1024 * 1024)
        cdp = cdpbrowser.CDP(proc)
        return await asyncio.wait_for(_print(cdp, page.as_uri()), PDF_TIMEOUT)
    except Exception:
        return b""
    finally:
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.kill()
                await proc.wait()
        shutil.rmtree(tmp, ignore_errors=True)


async def _print(cdp, url: str) -> bytes:
    tgt = (await cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
    s = (await cdp.send("Target.attachToTarget", {"targetId": tgt, "flatten": True}))["sessionId"]
    await cdp.send("Page.enable", session=s)
    await cdp.send("Emulation.setEmulatedMedia", {"media": "print", "features": [
        {"name": "prefers-reduced-motion", "value": "reduce"}]}, session=s)
    await cdp.send("Page.navigate", {"url": url}, session=s)

    async def ev(expr):
        r = await cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                "awaitPromise": True}, session=s)
        return (r.get("result") or {}).get("value")
    for _ in range(80):
        if await ev("window.BP_DOC_DONE===true"):
            break
        await asyncio.sleep(0.15)
    await ev("Promise.race([Promise.all([document.fonts.ready].concat(Array.from(document.images)"
             ".filter(i=>!i.complete).map(i=>new Promise(r=>{i.onload=i.onerror=r})))),"
             "new Promise(r=>setTimeout(r,6000))]).then(()=>1)")
    await asyncio.sleep(0.4)
    out = await cdp.send("Page.printToPDF", {"printBackground": True, "preferCSSPageSize": True,
                                             "marginTop": 0, "marginBottom": 0, "marginLeft": 0,
                                             "marginRight": 0}, session=s)
    return base64.b64decode(out["data"])


def filename(sc_subject: str, ext: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (sc_subject or "blueprint").lower()).strip("-")[:48] or "blueprint"
    return f"{slug}-blueprint.{ext}"


async def to_file(store, cfg: dict, scene_id: str, folder, agent: str = "", question: str = ""):
    """The PDF under `folder`/stage, for a channel to send after the album. None without a browser."""
    page = await asyncio.to_thread(html, store, scene_id, agent, question)
    data = await pdf(page, cfg)
    if not data:
        return None
    r = store.db.execute("SELECT scene FROM stage_scenes WHERE id=?", (scene_id,)).fetchone()
    subject = json.loads(r[0]).get("subject") if r else "blueprint"
    d = Path(folder) / "stage"
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename(subject or "blueprint", "pdf")
    p.write_bytes(data)
    return p
