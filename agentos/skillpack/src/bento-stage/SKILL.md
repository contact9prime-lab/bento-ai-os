---
name: bento-stage
description: Answer with a visual story instead of a wall of text. Draws charts, world maps with notes on each place, key numbers, timelines, steps, tables, pictures, YouTube videos and short 3D films as one self-contained HTML page, using Bento Box AI's Stage painter. Use when the user asks to show, visualise, map, chart or compare something, asks for a story or briefing, or when an answer has numbers, places or a sequence worth seeing.
license: See LICENSE in the Bento Box AI repository
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/render.py *)
---

# Bento Stage

An answer shown, not only written. You pick three to six scenes, in story order, write
them as JSON, and the render script draws them with the same painter Bento's Stage uses.

## Inside Bento

If you have a `show_scene` tool, you are inside Bento: call it once per scene with the
same fields described below, before you write your reply. Skip the script.

## Anywhere else

1. Find the facts first. Real figures you looked up, with where they came from.
2. Write `story.json`:

   ```json
   {"question": "What the person asked",
    "answer": "Your written answer, plain text, paragraphs split by a blank line",
    "scenes": [ {"kind": "numbers", ...}, {"kind": "map", ...} ]}
   ```

3. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/render.py story.json -o story.html`.
4. Read every `note:` line it prints. A refused scene says why; fix it and run again.
5. Hand the person the page (open it, or give its path).

## How to tell the story

{{BIG}}

## The rules the script holds you to

- A scene is a closed set. Fields it does not know are dropped and named in a `note:`.
- **Numbers say where they came from.** A chart, a map with values, key numbers and a
  table need `source` (a site, a dataset or a URL), or `"illustrative": true` when they
  are an example. The page prints "Illustrative, not data" on those. Never invent figures.
- At most {{MAX_PER_ANSWER}} scenes. Every scene can carry `title`, `caption` (the
  takeaway as a sentence with a verb), `say` (a line to read aloud) and `source`.
- Pictures are `https` addresses you found (Wikipedia, the maker's site). Videos are a
  youtube.com or youtu.be address. Nothing else is fetched.

## Scene kinds

{{FIELDS}}

Shapes, field by field:

- **chart**: `chart_type` one of {{CHART_TYPES}}; `series`: `[{"name": "Price", "points": [["2024", 12.5], ["2025", 14]]}]`
  (up to {{MAX_SERIES}} series); `x_label`, `y_label`, `unit`; `marks`: `[{"y": 15, "text": "target"}]`.
- **map**: `points`: `[{"lat": 25.3, "lon": 51.5, "label": "Doha", "value": 46, "note": "what happened here"}]`;
  `regions`: `[{"country": "India", "value": 12, "label": "..."}]`; `view` one of {{VIEWS}};
  `unit`; `route: true` only when the places are a journey.
- **numbers**: `items`: `[{"label": "Revenue", "value": "2.6", "unit": "$bn", "delta": "+12%", "note": "..."}]`
  (up to {{MAX_ITEMS}}). A rise or fall is read from the sign of `delta`.
- **timeline**: `events`: `[{"when": "1969", "label": "Apollo 11", "note": "..."}]` (up to {{MAX_EVENTS}}).
- **steps**: `items`: `[{"title": "...", "text": "...", "note": "..."}]`; `ordered: false` for a list.
- **table**: `columns`: `["City", "Temp"]`; `rows`: `[["Doha", "46"]]` (up to {{MAX_COLS}} columns, {{MAX_ROWS}} rows).
- **image**: `url`, `alt`, `credit`.
- **video**: `url` (YouTube), `start` in seconds.
- **film**: `look` one of {{FILM_LOOKS}}; `shots`: up to {{MAX_SHOTS}} of
  `{"subject": one of {{FILM_SUBJECTS}}, "camera": one of {{FILM_CAMERAS}}, "seconds": 4, "text": "the line said over it"}`.
  Outside Bento a film is drawn as its storyboard.
- **blueprint**: a thing taken apart. Use the `bento-blueprint` skill for it.

An example is in [examples/story.json](examples/story.json).
