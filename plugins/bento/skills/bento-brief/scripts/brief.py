#!/usr/bin/env python3
"""Turn Brief items into one page a person acts on.

    python3 brief.py items.json [-o brief.html] [--agent NAME] [--summary "two sentences"]

items.json is a list of items (or {"items": [...]}), each:
    {"kind": "needs_you|decide|fyi|done", "title": "...", "body": "...",
     "who": "...", "due": "...", "mission": "...", "options": ["...", "..."]}

The page is the Brief as Bento tells it (bento_brief.story) drawn by the Stage's painter.
Prints the same Brief as text, so a terminal or a chat gets it too.

Standard library only. Generated from the Bento Box AI repository; do not edit by hand.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bento_brief as brief  # noqa: E402
import render  # noqa: E402


def items_of(raw) -> tuple[list, list]:
    if isinstance(raw, dict):
        raw = raw.get("items")
    if not isinstance(raw, list):
        raise SystemExit("items.json is a list of items, or {\"items\": [...]}")
    out, notes, now = [], [], time.time()
    for n, it in enumerate(raw, 1):
        if not isinstance(it, dict) or not str(it.get("title") or "").strip():
            notes.append(f"item {n}: needs a title")
            continue
        kind = str(it.get("kind") or "fyi").strip().lower()
        if kind not in brief.KINDS:
            notes.append(f"item {n}: kind {kind!r} is not one of {', '.join(brief.KINDS)}; filed as fyi")
            kind = "fyi"
        opts = [brief._short(str(o)) for o in (it.get("options") or []) if str(o).strip()][:4]
        if kind == "decide" and len(opts) < 2:
            notes.append(f"item {n}: a decision needs two choices or more")
        out.append({"id": "", "kind": kind, "state": "open", "title": str(it["title"]).strip(),
                    "body": str(it.get("body") or ""), "who": str(it.get("who") or ""),
                    "due": str(it.get("due") or ""), "mission": brief.slug(str(it.get("mission") or "")),
                    "options": opts, "created_at": now, "updated_at": now - n})
    return out, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("items", help="items.json, or - for stdin")
    ap.add_argument("-o", "--out", default="", help="the page to write (default: brief.html)")
    ap.add_argument("--agent", default="", help="who filed it, said on the page")
    ap.add_argument("--summary", default="", help="two sentences to open on")
    a = ap.parse_args(argv)
    raw = json.loads(sys.stdin.read() if a.items == "-" else Path(a.items).read_text(encoding="utf-8"))
    items, notes = items_of(raw)
    live = brief.fold(items)
    scenes = brief.story(live, time.time(), agent=a.agent, summary=a.summary)
    for sc in scenes:
        # a file has no buttons: Bento's "tap one to choose" would be a promise this page breaks
        for k in ("caption", "say"):
            sc[k] = re.sub(r"\s*(This is what your missions filed for you\.\s*)?Tap [^.]*\.", "", sc.get(k) or "").strip()
    page, more = render.build({"question": brief.headline(brief.counts_of(live)) or "Your Brief",
                               "agent": a.agent, "scenes": scenes},
                              footer="Made with the Bento Brief skill. Counts are of the items above.")
    out = Path(a.out or "brief.html")
    out.write_text(page, encoding="utf-8")
    for n in notes + more:
        print("note:", n)
    print(brief.digest(live) or "Nothing is waiting for you.")
    print(f"wrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
