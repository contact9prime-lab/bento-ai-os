#!/usr/bin/env python3
"""Draw a Bento Stage story as one self-contained HTML page.

    python3 render.py story.json [-o story.html]

story.json is {"question": "...", "answer": "...", "scenes": [ {...}, ... ]} or just a
list of scenes. Every scene is checked by Bento's own closed set (bento_stage.clean):
what the page cannot draw is dropped and named, and a scene with numbers but no source
(and no "illustrative": true) is refused with the reason. The page is drawn by Bento's
own painter (assets/painter.js and painter.css), so it looks as it does on the Stage.

Standard library only. Generated from the Bento Box AI repository; do not edit by hand.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bento_stage as stage  # noqa: E402

ASSETS = HERE.parent / "assets"


def _read(name: str) -> str:
    p = ASSETS / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _answer_html(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in paras)


def load(path: str) -> dict:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, list):
        data = {"scenes": data}
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        raise SystemExit("story.json needs a list of scenes, or {\"scenes\": [...]}")
    return data


def build(data: dict, footer: str = "") -> tuple[str, list[str]]:
    """(the page, notes about what was dropped or refused)."""
    notes, scenes = [], []
    raw = data["scenes"]
    if len(raw) > stage.MAX_PER_ANSWER:
        notes.append(f"kept the first {stage.MAX_PER_ANSWER} scenes of {len(raw)}: a story, not a slideshow")
    for i, spec in enumerate(raw[:stage.MAX_PER_ANSWER], 1):
        try:
            sc, dropped = stage.clean(spec)
        except ValueError as e:
            notes.append(f"scene {i} refused: {e}")
            continue
        if sc["kind"] == "image" and sc.get("asset"):
            notes.append(f"scene {i}: an asset id only works inside Bento; give an https url")
        if dropped:
            notes.append(f"scene {i} ({sc['kind']}): dropped {', '.join(dropped)}")
        scenes.append(sc)
    if not scenes:
        raise SystemExit("nothing to draw:\n  " + "\n  ".join(notes))
    paint = (_read("painter.js"), _read("painter.css"), _read("world-110m.json"))
    if any(s["kind"] == "map" for s in scenes) and not paint[2]:
        notes.append("this skill has no world map file; map scenes draw without countries")
    page = stage.page_html(scenes, str(data.get("question") or ""),
                           _answer_html(str(data.get("answer") or "")),
                           str(data.get("agent") or ""), paint=paint, footer=footer)
    return page, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("story", help="story.json, or - for stdin")
    ap.add_argument("-o", "--out", default="", help="the page to write (default: next to story.json)")
    a = ap.parse_args(argv)
    data = load(a.story)
    page, notes = build(data)
    out = Path(a.out) if a.out else (Path("story.html") if a.story == "-"
                                     else Path(a.story).with_suffix(".html"))
    out.write_text(page, encoding="utf-8")
    for n in notes:
        print("note:", n)
    print(f"wrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
