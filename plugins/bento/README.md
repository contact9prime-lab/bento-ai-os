# Bento skills

Bento Box AI's Stage, Blueprint, Brief and Mission as Agent Skills: answers drawn as visual stories, things taken apart into drillable blueprints, work delivered as items to act on, and standing missions with a consent sheet.

- **bento-stage**: Answer with a visual story instead of a wall of text.
- **bento-blueprint**: Take a thing apart into a drillable blueprint, the Bento Box AI way.
- **bento-brief**: Deliver work as a Brief a person acts on, never a wall of text.
- **bento-mission**: Design a standing mission the Bento Box AI way.

They work in Claude Code, Claude.ai, Codex and any agent that reads `SKILL.md`, and inside
Bento (each skill says which Bento tool to use there). The scripts are Python's standard
library only. The pages they draw are single HTML files that open in any browser.

## Install

Claude Code, as a plugin:

```
/plugin marketplace add contact9prime-lab/bento-ai-os
/plugin install bento@bento-box-ai
```

Any agent, one skill: download the zip for that skill from the repository's releases (or
run `bento skills zip`) and unpack it into your skills folder, for Claude Code
`~/.claude/skills/`.

With Bento installed: `bento skills install` copies all four into `~/.claude/skills`.

## Try it

```
python3 skills/bento-stage/scripts/render.py skills/bento-stage/examples/story.json -o story.html
python3 skills/bento-blueprint/scripts/render.py skills/bento-blueprint/examples/blueprint.json -o blueprint.html
python3 skills/bento-brief/scripts/brief.py skills/bento-brief/examples/items.json -o brief.html
python3 skills/bento-mission/scripts/mission.py skills/bento-mission/examples/mission.json
```

These files are generated from the Bento source by `bento skills build`; change them there.
