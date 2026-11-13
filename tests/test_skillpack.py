"""The downloadable skills (agentos/skillpack): current, self-contained, and held to the
same rules as the Stage and Missions they come from."""
import json
import re
import shutil
import subprocess
import sys

from agentos import flows, skillpack, stage
from agentos.memory import Store


def _copy(tmp_path):
    """The skills as somebody downloads them: no Bento beside them."""
    dest = tmp_path / "skills"
    skillpack.install(dest)
    return dest


def _run(script, *args, cwd):
    # -I: no PYTHONPATH, no user site, so nothing of Bento's can be imported by accident
    return subprocess.run([sys.executable, "-I", str(script), *map(str, args)], cwd=cwd,
                          capture_output=True, text=True, timeout=60)


def test_the_checked_in_plugin_is_current():
    assert skillpack.stale() == [], "run `bento skills build`"


def test_every_skill_names_itself_and_fills_every_blank():
    for rel, data in skillpack.files().items():
        if rel.endswith("SKILL.md"):
            text = data.decode()
            name = rel.split("/")[1]
            assert text.startswith("---\n")
            assert re.search(rf"^name: {name}$", text, re.M)
            desc = re.search(r"^description: (.+)$", text, re.M).group(1)
            assert 40 < len(desc) <= 1024
            assert "{{" not in text and "__" not in text.split("---", 2)[1]
            # every script the text tells an agent to run is in the folder
            for s in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/(scripts/[\w.]+)", text):
                assert f"skills/{name}/{s}" in skillpack.files(), s


def test_the_closed_sets_come_from_the_code():
    md = skillpack.files()["skills/bento-stage/SKILL.md"].decode()
    for k in stage.KINDS:
        assert f"`{k}`" in md
    bp = skillpack.files()["skills/bento-blueprint/SKILL.md"].decode()
    for f in stage.BP_FLOWS + stage.BP_FORMS:
        assert f"`{f}`" in bp
    mission = skillpack.files()["skills/bento-mission/scripts/mission.py"].decode()
    assert repr(tuple(flows.TRIGGER_KINDS)) in mission
    # the painter is the Stage's own, not a copy that can drift
    js, css, _ = stage.painter()
    assert skillpack.files()["skills/bento-stage/assets/painter.js"].decode() == js


def test_outside_bento_the_guidance_names_no_bento_tool():
    for name in ("bento-stage", "bento-blueprint"):
        md = skillpack.files()[f"skills/{name}/SKILL.md"].decode()
        after = md.split("## Anywhere else", 1)[1]
        assert "generate_image" not in after and "fills in every part" not in after


def test_marketplace_points_at_the_plugin():
    m = json.loads(skillpack.marketplace())
    plug = m["plugins"][0]
    assert plug["source"] == "./plugins/bento"
    manifest = json.loads(skillpack.files()[".claude-plugin/plugin.json"])
    assert manifest["name"] == plug["name"] == skillpack.PLUGIN


def test_stage_and_blueprint_render_with_nothing_but_the_folder(tmp_path):
    d = _copy(tmp_path)
    for name, ex in (("bento-stage", "story.json"), ("bento-blueprint", "blueprint.json")):
        out = tmp_path / f"{name}.html"
        r = _run(d / name / "scripts/render.py", d / name / "examples" / ex, "-o", out, cwd=tmp_path)
        assert r.returncode == 0, r.stderr + r.stdout
        page = out.read_text()
        assert "stageDraw" in page and '"kind": "' in page
        assert "note:" not in r.stdout, r.stdout


def test_numbers_without_a_source_are_refused_and_unknown_fields_named(tmp_path):
    d = _copy(tmp_path)
    story = tmp_path / "s.json"
    story.write_text(json.dumps({"scenes": [
        {"kind": "numbers", "title": "made up", "items": [{"label": "x", "value": "3"}]},
        {"kind": "steps", "title": "ok", "colour": "red", "items": [{"title": "a"}]}]}))
    r = _run(d / "bento-stage/scripts/render.py", story, cwd=tmp_path)
    assert r.returncode == 0
    assert "scene 1 refused: say where these numbers came from" in r.stdout
    assert "dropped colour" in r.stdout
    story.write_text(json.dumps([{"kind": "numbers", "items": [{"label": "x", "value": "1"}]}]))
    r = _run(d / "bento-stage/scripts/render.py", story, cwd=tmp_path)
    assert r.returncode != 0 and "nothing to draw" in (r.stdout + r.stderr)


def test_the_brief_page_promises_no_buttons(tmp_path):
    d = _copy(tmp_path)
    out = tmp_path / "brief.html"
    r = _run(d / "bento-brief/scripts/brief.py", d / "bento-brief/examples/items.json",
             "-o", out, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "1 decision" in r.stdout
    data = out.read_text()
    assert "Tap one" not in data and "Tap a card" not in data


def test_the_mission_check_holds_the_lessons(tmp_path):
    d = _copy(tmp_path)
    ex = json.loads((d / "bento-mission/examples/mission.json").read_text())
    f = tmp_path / "m.json"
    f.write_text(json.dumps(ex))
    r = _run(d / "bento-mission/scripts/mission.py", f, cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    assert "nothing until you switch it on" in (tmp_path / "m.md").read_text()
    bad = dict(ex, permissions=dict(ex["permissions"], tools=ex["permissions"]["tools"] + ["remember"]))
    f.write_text(json.dumps(bad))
    r = _run(d / "bento-mission/scripts/mission.py", f, cwd=tmp_path)
    assert r.returncode == 1
    assert "memory: read-write" in r.stdout and "nobody on the roster can call remember" in r.stdout
    f.write_text(json.dumps(dict(ex, triggers=[{"kind": "flow_done", "config": {"flow": ex["name"]}}])))
    assert "cannot follow itself" in _run(d / "bento-mission/scripts/mission.py", f, cwd=tmp_path).stdout


def test_a_mission_file_arrives_in_bento_switched_off(tmp_path):
    store = Store(tmp_path / "t.db")
    ex = json.loads(skillpack.files()["skills/bento-mission/examples/mission.json"])
    flow, report = flows.save_draft(store, ex)
    assert not flow["enabled"] and "filer" in report["agents_created"]


def test_install_keeps_a_copy_somebody_edited(tmp_path):
    d = _copy(tmp_path)
    (d / "bento-stage/SKILL.md").write_text("mine")
    said = skillpack.install(d, ["bento-stage"])
    assert said[0].startswith("kept") and (d / "bento-stage/SKILL.md").read_text() == "mine"
    skillpack.install(d, ["bento-stage"], replace=True)
    assert (d / "bento-stage/SKILL.md").read_text() != "mine"
    shutil.rmtree(d)


def test_zips_unpack_to_one_folder_each(tmp_path):
    import zipfile
    for z in skillpack.zip_all(tmp_path):
        names = zipfile.ZipFile(z).namelist()
        assert names and all(n.startswith(z.stem + "/") for n in names)
        assert f"{z.stem}/SKILL.md" in names
