---
name: bento-blueprint
description: Take a thing apart into a drillable blueprint, the Bento Box AI way. A building, a machine, an engine, a body, a company or a process becomes a scale drawing whose parts open level by level, with how each part works, what it is made of, its limits, real numbers with their certainty, how parts connect (load, power, fluid, data, money and more) and what nobody outside can know. Renders one self-contained HTML page. Use when the user asks for a blueprint, a cutaway, what is inside something, how something is built or works, or to drill into a system.
license: See LICENSE in the Bento Box AI repository
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/render.py *)
---

# Bento Blueprint

A blueprint gets to the bottom of a thing rather than presenting a chart about it. The
parts nest, so the person drills in on the page without waiting on you.

## Inside Bento

If you have a `show_scene` tool, call it with `kind: "blueprint"` and the fields below.
Bento fills in thin parts on its own afterwards, so show the outline once.

## Anywhere else

Outside Bento nothing fills the parts in later, so do the depth yourself:

1. Research the thing. Look up real dimensions, materials, figures, and name sources.
2. Write `blueprint.json` as a story with one blueprint scene (add a chart or timeline
   after it only if it helps):

   ```json
   {"question": "Give me a blueprint of the Burj Khalifa",
    "scenes": [{"kind": "blueprint", "title": "Burj Khalifa, taken apart",
                "subject": "Burj Khalifa", "form": "tower", "unit": "m",
                "source": "CTBUH; SOM", "parts": [...], "links": [...],
                "facts": [...], "unknowns": [...]}]}
   ```

3. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/render.py blueprint.json -o blueprint.html`.
4. Read every `note:` line. Dropped fields are named by their path (`parts[2].parts[0].colour`).

## What to give

{{BP}}

Outside Bento, go further than the outline: give each of the six to ten top parts its own
`parts` (three to eight each), and the most interesting of those their own, so the drawing
holds two or three levels. Every part should have `role`, `how`, two or three `facts` and,
where it matters, `made_of`, `limits` and `certainty`.

## The closed set

- `form`: {{BP_FORMS}}. A tower's parts go bottom first, with `from` and `to` as heights in
  `unit`, and `width` as the real width in the same unit (0 to 1 only when you cannot know it).
- A part: {{BP_PART}}.
- `certainty`: {{BP_CERTAINTY}}. It is drawn as the line (solid, dashed, dotted), never colour alone.
- `status` (for a system's parts): {{BP_STATUS}}.
- `facts`: `[{"label": "Height", "value": "828", "unit": "m"}]`, up to {{BP_FACTS}} a part and
  {{BP_HEADLINE}} for the whole.
- `links`: `[{"from": "core", "to": "foundation", "verb": "carries load to", "kind": "load"}]`,
  `kind` one of {{BP_FLOWS}}. `from` and `to` are part ids (or names).
- `steps` on a part: how it works, in order, up to {{BP_STEPS}}.
- Limits: {{BP_DEPTH}} levels, {{BP_CHILDREN}} parts at one level, {{BP_NODES}} parts in all.
- Facts with numbers need `source` on the scene, or `"illustrative": true`.
- `model`: what it looks like, in 3D. A tower is stacked from its parts by the page. Anything
  else carries `model`: solids `{"shape", "at": [x, y, z], "size": [w, h, d], "color", "part": "<part id>"}`
  from {{MODEL_PRIMS}} and {{MODEL_PROPS}}, each naming the part it draws, so a tap on it opens
  that part. `style` one of {{MODEL_STYLES}}.

The page carries its own 3D engine: the blueprint opens on the model, inked on paper, raised and
then lit like a real object; drag turns it, Tour goes round its parts, Pull apart separates them,
and Clip saves a video of the build with sound.

An example is in [examples/blueprint.json](examples/blueprint.json).
