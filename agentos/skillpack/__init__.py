"""Bento's best features as Agent Skills anyone can download.

Asked for as "build bento stage and blueprint mission and some of the cool features as
skills … easy to download". Each skill is a folder with a SKILL.md, the scripts it runs and
the files they read, so it works in Claude Code, Claude.ai, Codex or any agent that reads
SKILL.md, and inside Bento too (each SKILL.md says which Bento tool to call instead).

Three rules keep it honest, pinned by tests/test_skillpack.py:

- **One painter.** A story drawn by a skill is drawn by `stage.page_html` with the Stage's
  own 24l-stage.js / 24v-blueprint.js and CSS, copied in at build time, and every scene is
  checked by `stage.clean`, the module itself copied in (it is stdlib only). The skills
  never carry a second idea of what a scene is.
- **The closed sets are read, never retyped.** Every list a SKILL.md names (kinds, forms,
  flows, trigger kinds…) is filled in here from the module that owns it, so a new kind in
  stage.py reaches the skill on the next build.
- **Generated, then checked in, and checked current.** `bento skills build` writes
  `plugins/bento/` (a Claude Code plugin inside the repository's marketplace,
  `.claude-plugin/marketplace.json`), and the test fails when that tree is stale, the
  ui/build argument: a skill that drifted from the code is a skill that lies.

Kept free of HTTP and asyncio. Building, zipping and installing a copy are file work.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

from .. import brief, flows, stage

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
REPO = HERE.parent.parent
OUT = REPO / "plugins" / "bento"
MARKET = "bento-box-ai"
PLUGIN = "bento"
REPO_SLUG = "contact9prime-lab/bento-ai-os"

#: name -> (scripts, assets). Scripts and assets are (source, file name in the skill).
SKILLS = {
    "bento-stage": {"scripts": ["render.py", "bento_stage.py"],
                    "assets": ["painter.js", "painter.css", "world-110m.json", "three.module.min.js"]},
    "bento-blueprint": {"scripts": ["render.py", "bento_stage.py"],
                        "assets": ["painter.js", "painter.css", "three.module.min.js"]},
    "bento-brief": {"scripts": ["brief.py", "render.py", "bento_stage.py", "bento_brief.py"],
                    "assets": ["painter.js", "painter.css"]},
    "bento-mission": {"scripts": ["mission.py"], "assets": []},
}

PLUGIN_DESC = ("Bento Box AI's Stage, Blueprint, Brief and Mission as Agent Skills: answers "
               "drawn as visual stories, things taken apart into drillable blueprints, work "
               "delivered as items to act on, and standing missions with a consent sheet.")


def _words(seq) -> str:
    return ", ".join(f"`{x}`" for x in seq)


def _cut(text: str, old: str, new: str = "") -> str:
    """Replace a phrase the outside world has no use for, loudly: a guidance line that
    changed in stage.py must fail the build rather than ship half-edited."""
    if old not in text:
        raise RuntimeError(f"skillpack: stage guidance changed, cannot find {old[:60]!r}")
    return text.replace(old, new)


def story_line() -> str:
    """BIG_LINE as advice to an agent with no Stage: no tool names, no Bento-only steps."""
    t = _cut(stage.BIG_LINE, " " + stage.BP_LINE + " ", " ")
    t = _cut(t, "Answer BIG: the person watches your answers on the Stage, so anything worth "
                "seeing is SHOWN with show_scene before you write the text: ",
             "Anything worth seeing is shown: ")
    t = _cut(t, " or one you made with generate_image")
    t = t[:t.index("When the person asks to change")].rstrip() if "When the person asks to change" in t else t
    return t + " A blueprint (a thing taken apart) is its own skill, bento-blueprint."


def blueprint_line() -> str:
    t = _cut(stage.BP_LINE, "show ONE blueprint scene, and make it the main scene: ",
             "make ONE blueprint scene the main scene: ")
    t = re.sub(r" The Stage then fills in every part on its own.*?while it fills\.", "", t)
    t = re.sub(r" Give look_for:.*?the Stage finds a free drawing with them\.", "", t)
    if "Stage" in t:
        raise RuntimeError("skillpack: BP_LINE names the Stage in a sentence the skill cannot keep")
    return t


def fills() -> dict:
    return {
        "BIG": story_line(), "BP": blueprint_line(),
        "FIELDS": "\n".join(f"- `{k}`: {_words(f) if f else '(the common fields only)'}"
                            for k, f in stage.FIELDS.items()),
        "CHART_TYPES": _words(stage.CHART_TYPES), "VIEWS": _words(stage.VIEWS),
        "FILM_SUBJECTS": _words(stage.FILM_SUBJECTS), "FILM_CAMERAS": _words(stage.FILM_CAMERAS),
        "FILM_LOOKS": _words(stage.FILM_LOOKS),
        "BP_FORMS": _words(stage.BP_FORMS), "BP_PART": _words(stage.BP_PART),
        "BP_CERTAINTY": _words(stage.BP_CERTAINTY), "BP_STATUS": _words(stage.BP_STATUS),
        "BP_FLOWS": _words(stage.BP_FLOWS),
        "MODEL_PRIMS": _words(stage.MODEL_PRIMS), "MODEL_PROPS": _words(stage.MODEL_PROPS),
        "MODEL_STYLES": _words(stage.MODEL_STYLES), "MODEL_COLORS": _words(stage.MODEL_COLORS),
        "MODEL_MOVES": _words(stage.MODEL_MOVES), "MODEL_WEATHER": _words(stage.MODEL_WEATHER[1:]),
        "MODEL_GROUND": _words(stage.MODEL_GROUND[1:]),
        "TRIGGER_KINDS": _words(flows.TRIGGER_KINDS), "SINK_KINDS": _words(flows.SINK_KINDS),
        "MEMORY_SCOPES": _words(flows.MEMORY_SCOPES), "BRIEF_KINDS": _words(brief.KINDS),
        **{k: str(getattr(stage, k)) for k in (
            "MAX_PER_ANSWER", "MAX_SERIES", "MAX_ITEMS", "MAX_EVENTS", "MAX_COLS", "MAX_ROWS",
            "MAX_SHOTS", "BP_FACTS", "BP_HEADLINE", "BP_STEPS", "BP_DEPTH", "BP_CHILDREN",
            "BP_NODES")},
    }


def _fill(text: str, values: dict) -> str:
    out = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)], text)
    left = re.findall(r"\{\{[^}]*\}\}", out)
    if left:
        raise RuntimeError(f"skillpack: unfilled {left}")
    return out


GENERATED = "<!-- generated by `bento skills build` from agentos/skillpack; edit there -->\n"


def files() -> dict[str, bytes]:
    """Every file of the plugin, path relative to plugins/bento -> bytes. Pure: the build
    writes this and the test compares it with what is checked in."""
    js, css, world = stage.painter()
    script_src = {
        "render.py": (SRC / "shared/render.py").read_text(encoding="utf-8"),
        "bento_stage.py": (HERE.parent / "stage.py").read_text(encoding="utf-8"),
        "bento_brief.py": (HERE.parent / "brief.py").read_text(encoding="utf-8"),
        "brief.py": (SRC / "bento-brief/brief.py").read_text(encoding="utf-8"),
        "mission.py": (SRC / "bento-mission/mission.py").read_text(encoding="utf-8")
        .replace("__TRIGGER_KINDS__", repr(tuple(flows.TRIGGER_KINDS)))
        .replace("__SINK_KINDS__", repr(tuple(flows.SINK_KINDS)))
        .replace("__MEMORY_SCOPES__", repr(tuple(flows.MEMORY_SCOPES)))
        .replace("__BRIEF_KINDS__", repr(tuple(brief.KINDS))),
    }
    assets = {"painter.js": js, "painter.css": css, "world-110m.json": world,
              # three.js (MIT, its licence in its own header): a page that carries it builds in 3D live
              "three.module.min.js": (HERE.parent / "ui/assets/three.module.min.js").read_text(encoding="utf-8")}
    values = fills()
    out: dict[str, bytes] = {}
    for name, spec in SKILLS.items():
        md = _fill((SRC / name / "SKILL.md").read_text(encoding="utf-8"), values)
        head, _, body = md.partition("\n---\n")
        out[f"skills/{name}/SKILL.md"] = (head + "\n---\n" + GENERATED + body).encode()
        for s in spec["scripts"]:
            out[f"skills/{name}/scripts/{s}"] = script_src[s].encode()
        for a in spec["assets"]:
            out[f"skills/{name}/assets/{a}"] = assets[a].encode()
        for ex in sorted((SRC / name / "examples").glob("*.json")):
            out[f"skills/{name}/examples/{ex.name}"] = ex.read_bytes()
    out[".claude-plugin/plugin.json"] = (json.dumps({
        "name": PLUGIN, "description": PLUGIN_DESC,
        "author": {"name": "Bento Box AI"}, "license": "See LICENSE",
        "keywords": ["stage", "blueprint", "brief", "mission", "visualisation"]}, indent=2) + "\n").encode()
    out["README.md"] = readme().encode()
    return out


def marketplace() -> bytes:
    return (json.dumps({
        "name": MARKET, "description": "Agent Skills from Bento Box AI",
        "owner": {"name": "Bento Box AI"},
        "plugins": [{"name": PLUGIN, "source": "./plugins/bento", "description": PLUGIN_DESC,
                     "category": "productivity"}]}, indent=2) + "\n").encode()


def readme(repo: str = REPO_SLUG) -> str:
    rows = []
    for name in SKILLS:
        md = (SRC / name / "SKILL.md").read_text(encoding="utf-8")
        desc = re.search(r"^description: (.+)$", md, re.M).group(1)
        rows.append(f"- **{name}**: {desc.split('. ')[0]}.")
    return f"""# Bento skills

{PLUGIN_DESC}

{chr(10).join(rows)}

They work in Claude Code, Claude.ai, Codex and any agent that reads `SKILL.md`, and inside
Bento (each skill says which Bento tool to use there). The scripts are Python's standard
library only. The pages they draw are single HTML files that open in any browser.

## Install

Claude Code, as a plugin:

```
/plugin marketplace add {repo}
/plugin install {PLUGIN}@{MARKET}
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
"""


def build(out: Path = OUT, root: Path = REPO) -> list[str]:
    """Write the plugin and the marketplace file. Returns what changed."""
    want = files()
    changed = []
    if out.exists():
        for p in out.rglob("*"):
            if p.is_file() and str(p.relative_to(out)) not in want:
                p.unlink()
                changed.append(f"removed {p.relative_to(out)}")
    for rel, data in want.items():
        p = out / rel
        if not p.exists() or p.read_bytes() != data:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            if rel.startswith("skills/") and "/scripts/" in rel:
                p.chmod(0o755)
            changed.append(rel)
    m = root / ".claude-plugin" / "marketplace.json"
    if not m.exists() or m.read_bytes() != marketplace():
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_bytes(marketplace())
        changed.append(".claude-plugin/marketplace.json")
    return changed


def stale(out: Path = OUT, root: Path = REPO) -> list[str]:
    """What differs between the checked-in plugin and a fresh build."""
    want = files()
    bad = [rel for rel, data in want.items()
           if not (out / rel).exists() or (out / rel).read_bytes() != data]
    if out.exists():
        bad += [str(p.relative_to(out)) for p in out.rglob("*")
                if p.is_file() and str(p.relative_to(out)) not in want]
    m = root / ".claude-plugin" / "marketplace.json"
    if not m.exists() or m.read_bytes() != marketplace():
        bad.append(".claude-plugin/marketplace.json")
    return bad


def zip_all(dest: Path) -> list[Path]:
    """One zip per skill, each unpacking to a folder of the skill's name."""
    dest.mkdir(parents=True, exist_ok=True)
    made = []
    for name in SKILLS:
        z = dest / f"{name}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, data in sorted(files().items()):
                if rel.startswith(f"skills/{name}/"):
                    info = zipfile.ZipInfo(rel[len("skills/"):], date_time=(2026, 1, 1, 0, 0, 0))
                    info.external_attr = (0o755 if "/scripts/" in rel else 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(info, data)
        made.append(z)
    return made


def install(dest: Path, names: list[str] | None = None, replace: bool = False) -> list[str]:
    """Copy skills into an agent's skills folder (Claude Code: ~/.claude/skills). A folder
    that exists is kept unless `replace`, because somebody may have edited their copy."""
    said = []
    want = files()
    for name in names or list(SKILLS):
        if name not in SKILLS:
            raise ValueError(f"no skill called {name!r}; one of {', '.join(SKILLS)}")
        target = dest / name
        if target.exists():
            if not replace:
                said.append(f"kept {target} (it exists; --replace to overwrite)")
                continue
            shutil.rmtree(target)
        for rel, data in want.items():
            if rel.startswith(f"skills/{name}/"):
                p = dest / rel[len("skills/"):]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                if "/scripts/" in rel:
                    p.chmod(0o755)
        said.append(f"installed {target}")
    return said
