"""The Stage: an answer shown, not only written (agentos/stage.py, 24l-stage.js).

Asked for as "if I ask what are the hottest places on earth it shows them on the map in
front of me … every answer becomes a story", then "a toggle that answers BIG and saves the
stage … the Stage is the default app unless someone uses their own … auto refreshed as the
requirement persists". Pinned here:

- a scene is a closed set, read field by field, and what is dropped is named;
- numbers say where they came from, or are marked illustrative;
- the chat is the agent's (`_conv`), and a scene is filed under the question it answers;
- show_scene is safe, offered to the lead and to a forwarded lead through the team door;
- a board keeps a story and can ask its question again; a refresh that shows nothing
  keeps the old story and says why;
- the page builds every label as text, and the map is a lazy asset, never the bundle.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import stage  # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js/24l-stage.js"


def test_a_scene_is_a_closed_set():
    sc, dropped = stage.clean({"kind": "chart", "title": "IV", "source": "NSE",
                               "series": [{"name": "IV", "points": [["2024-01", 18], ["2024-02", "15.5%"],
                                                                    ["2024-03", "x"]]}],
                               "chart_type": "radar", "script": "<b>", "marks": [{"y": 13, "text": "low"}]})
    assert "script" in dropped and "chart_type 'radar'" in dropped
    assert sc["chart_type"] == "line"
    assert sc["series"][0]["points"] == [["2024-01", 18.0], ["2024-02", 15.5]]
    with pytest.raises(ValueError, match="kind must be"):
        stage.clean({"kind": "hologram"})
    with pytest.raises(ValueError, match="series"):
        stage.clean({"kind": "chart", "series": [], "source": "x"})
    # controls a web page could carry never reach a terminal or the page
    sc, _ = stage.clean({"kind": "steps", "title": "a\x1b]0;pwned\x07b‮", "items": ["x"]})
    assert "\x1b" not in sc["title"] and "‮" not in sc["title"]


def test_numbers_say_where_they_came_from():
    with pytest.raises(ValueError, match="came from"):
        stage.clean({"kind": "numbers", "items": [{"label": "VIX", "value": "12.4"}]})
    sc, _ = stage.clean({"kind": "numbers", "illustrative": True, "items": [{"label": "a", "value": 1}]})
    assert sc["illustrative"]
    # places with no values need no source; a map that measures does
    stage.clean({"kind": "map", "points": [{"lat": 36.5, "lon": -116.9, "label": "Death Valley"}]})
    with pytest.raises(ValueError, match="came from"):
        stage.clean({"kind": "map", "regions": [{"country": "India", "value": 48}]})
    # a timeline and steps are a story, not measurements
    stage.clean({"kind": "steps", "items": [{"title": "IV falls"}, {"title": "premiums shrink"}]})
    assert "Illustrative" in JS.read_text() and "Source: " in JS.read_text()


def test_every_kind_has_a_terminal_face():
    for spec in ({"kind": "chart", "source": "s", "series": [{"points": [[1, 2], [2, 3]]}]},
                 {"kind": "chart", "chart_type": "bar", "source": "s", "series": [{"points": [["a", 2], ["b", 3]]}]},
                 {"kind": "map", "points": [{"lat": 1, "lon": 2, "label": "p", "value": 3}], "source": "s"},
                 {"kind": "numbers", "source": "s", "items": [{"label": "l", "value": "1"}]},
                 {"kind": "timeline", "events": [{"when": "1990", "label": "x"}]},
                 {"kind": "steps", "items": ["a", "b"]},
                 {"kind": "table", "source": "s", "columns": ["a", "b"], "rows": [[1, 2]]}):
        sc, _ = stage.clean(spec)
        assert stage.text(sc).startswith("▶"), spec["kind"]


def test_a_scene_is_filed_under_the_question_it_answers(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    with pytest.raises(ValueError, match="no chat"):
        stage.add(store, "", {"kind": "steps"})
    q1 = store.add_message(cid, "user", "hottest places?")
    sc, _ = stage.clean({"kind": "steps", "items": ["a"]})
    r1 = stage.add(store, cid, sc)
    stage.add(store, cid, sc)
    q2 = store.add_message(cid, "user", "and the coldest?")
    r3 = stage.add(store, cid, sc)
    assert (r1["answer_to"], r1["seq"]) == (q1, 1) and (r3["answer_to"], r3["seq"]) == (q2, 1)
    st = stage.stories(store, cid)
    assert [len(s["scenes"]) for s in st] == [2, 1]
    lib = stage.library(store)
    assert lib[0]["question"] == "and the coldest?" and lib[1]["scenes"] == 2
    for _ in range(stage.MAX_PER_ANSWER - 1):
        stage.add(store, cid, sc)
    with pytest.raises(ValueError, match="say the rest"):
        stage.add(store, cid, sc)
    store.delete_conversation(cid)
    assert stage.stories(store, cid) == []


def test_a_board_keeps_a_story_and_asks_again(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    q = store.add_message(cid, "user", "[Scheduled] VIX this week?")
    sc, _ = stage.clean({"kind": "steps", "items": ["a"]})
    stage.add(store, cid, sc)
    with pytest.raises(ValueError, match="every"):
        stage.save_board(store, cid, q, every="minute")
    b = stage.save_board(store, cid, q, every="day")
    assert b["question"] == "VIX this week?" and b["when"] == "refreshed every day"
    assert stage.save_board(store, cid, q, every="hour")["id"] == b["id"], "one board per story"
    assert not stage.due_boards(store)
    assert [x["id"] for x in stage.due_boards(store, now=b["created_at"] + 4000)] == [b["id"]]
    stage.claim(store, b["id"])
    assert not stage.due_boards(store, now=b["created_at"] + 4000), "claimed, so not started twice"
    # a refresh that showed nothing keeps the old story, and says so
    cid2 = store.create_conversation("r")
    q2 = store.add_message(cid2, "user", "again")
    nb = stage.refreshed(store, b["id"], cid2, q2, ok=True)
    assert nb["conversation_id"] == cid and "last story stays" in nb["last_status"]
    stage.add(store, cid2, sc)
    nb = stage.refreshed(store, b["id"], cid2, q2, ok=True)
    assert (nb["conversation_id"], nb["answer_to"], nb["last_status"]) == (cid2, q2, "ok")
    assert stage.drop_board(store, b["id"]) and not stage.boards(store)


def test_the_tool_is_the_agents_and_safe():
    from agentos import tools, policy, toolscope, executors, hands
    assert "show_scene" in tools.SAFE_TOOLS and "show_scene" in policy.PARANOID_FREE
    assert "show_scene" in toolscope.CORE and "show_scene" in executors.DOOR_TOOLS
    assert any("show_scene" in v for v in hands.GROUPS.values()) and "show_scene" in hands.READ_ONLY_TOOLS
    schema = next(t for t in tools.TOOL_SCHEMAS if t["name"] == "show_scene")
    assert "_conv" not in schema["parameters"]["properties"], "the chat is never the model's"
    src = (ROOT / "agentos/agent.py").read_text()
    inj = src[src.index('if name == "show_scene":'):][:300]
    assert '"_conv": self.conversation_id' in inj
    # the forwarded lead hears it, in its own tool's name, only with a chat to show it in
    door = (ROOT / "agentos/executors.py").read_text()
    assert 'tool="mcp__bento__show_scene"' in door


def test_the_tool_files_and_broadcasts(tmp_path):
    from agentos.memory import Store
    from agentos.tools import Toolbox
    store = Store(tmp_path / "a.db")
    tb = Toolbox.__new__(Toolbox)
    tb.store = store
    tb.broadcast = None
    sent = []

    async def bu(ev, uid):
        sent.append(ev)
    tb.broadcast_user = bu
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "where is it hot?")

    async def go():
        out = await tb.show_scene(kind="map", title="Hot", _conv=cid,
                                  points=[{"lat": 36.5, "lon": -116.9, "label": "Death Valley"}], junk=1)
        bad = await tb.show_scene(kind="numbers", items=[{"label": "a", "value": 1}], _conv=cid)
        none = await tb.show_scene(kind="steps", items=["a"], _conv="")
        await asyncio.sleep(0)
        return out, bad, none
    out, bad, none = asyncio.run(go())
    assert out.startswith("[on the Stage · scene 1 · map") and "junk" in out
    assert bad.startswith("[error]") and "came from" in bad
    assert none.startswith("[error]") and "no chat" in none
    assert sent and sent[0]["type"] == "stage" and sent[0]["conversation_id"] == cid


def test_answer_big_is_a_persons_setting():
    from agentos import users, config
    assert "stage" in users.USER_KEYS and config.DEFAULTS["stage"]["big"] is True
    assert stage.note({}).startswith("THE STAGE. Answer BIG")
    assert "when they ask" in stage.note({"stage": {"big": False}})
    assert "mcp__bento__show_scene" in stage.note({}, tool="mcp__bento__show_scene")


def test_a_refresh_has_a_stage_only_door():
    src = (ROOT / "agentos/executors.py").read_text()
    door = src[src.index("def open_app_door("):][:1600]
    assert "set(tools) <= set(STAGE_DOOR_TOOLS)" in door
    srv = (ROOT / "agentos/server.py").read_text()
    rf = srv[srv.index("async def _stage_refresh("):][:3200]
    assert '"tools": execmod.STAGE_DOOR_TOOLS' in rf and "task_run_start" in rf
    assert "needs_person()" in rf, "a refresh with nobody there never answers for a person"
    assert "asyncio.create_task(_stage_loop())" in srv


def test_the_page_draws_words_as_text():
    js = JS.read_text()
    assert "innerHTML" not in js, "scene words are often a web page's"
    assert "var STAGE=" in js and "\nlet " not in js and "\nconst " not in js
    assert "fetch('/assets/world-110m.json')" in js
    world = json.loads((ROOT / "agentos/ui/assets/world-110m.json").read_text())
    assert "public domain" in world["source"] and len(world["countries"]) > 150
    html = (ROOT / "agentos/ui/index.html").read_text()
    assert '"countries"' not in html, "the map is a lazy asset, never the bundle"
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'stage': if(typeof stageEvent==='function')stageEvent(ev)" in ws
    chat = (ROOT / "agentos/ui/src/js/10-chat.js").read_text()
    assert "m.dataset.mid=msg.id" in chat and "stageAttach(cid)" in chat


def test_an_app_can_draw_the_stage():
    srv = (ROOT / "agentos/server.py").read_text()
    assert "e.data.agentos !== 'stage'" in srv and "new CustomEvent('appstage'" in srv
    js = JS.read_text()
    assert "agentos:'stage'" in js and "openApp('ua_'+aid)" in js


def test_telegram_gets_the_story_as_one_page(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    q = store.add_message(cid, "user", "hottest places </script><b>?")
    sc, _ = stage.clean({"kind": "map", "title": "Hot </script>", "source": "WMO",
                         "points": [{"lat": 36.5, "lon": -116.9, "label": "Death Valley", "value": 56.7}]})
    stage.add(store, cid, sc)
    page = stage.report_html(store, cid, q, answer="<i>the answer</i>", agent="Aria")
    # one painter: the Stage's own drawing code and styles, and the map inline
    assert "function stageMap(" in page and ".st-pin" in page and '"countries"' in page
    # nothing a page or a model wrote can close the script or add markup
    assert page.count("</script>") == 1 and "<b>?" not in page and "<i>the answer" not in page
    assert stage.write_report(store, tmp_path, cid, "nope") is None
    p = stage.write_report(store, tmp_path, cid, q, answer="a")
    assert p.exists() and p.parent.name == "stage"
    tg = (ROOT / "agentos/telegram.py").read_text()
    assert "await self.send_stage(cid, reply, chat_id)" in tg


def test_pictures_and_videos():
    """Asked for as "the Stage doesn't have images … I should see YouTube videos for each of
    the tutorials". A picture is an https address or one of the person's assets; a video is
    only ever a YouTube id, played from youtube-nocookie.com."""
    sc, _ = stage.clean({"kind": "image", "title": "Starter", "url": "https://upload.wikimedia.org/a.jpg"})
    assert sc["url"].startswith("https://") and sc["alt"] == "Starter"
    with pytest.raises(ValueError, match="https"):
        stage.clean({"kind": "image", "url": "http://x/a.jpg"})
    with pytest.raises(ValueError, match="asset"):
        stage.clean({"kind": "image", "asset": "../../etc/passwd"})
    assert stage.youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1") == "dQw4w9WgXcQ"
    assert stage.youtube_id("youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert stage.youtube_id("https://evil.example/?u=youtube.com/watch?v=dQw4w9WgXcQ") == ""
    v, _ = stage.clean({"kind": "video", "title": "How", "url": "https://youtu.be/dQw4w9WgXcQ", "start": 42})
    assert (v["video"], v["start"]) == ("dQw4w9WgXcQ", 42)
    js = JS.read_text()
    assert "https://www.youtube-nocookie.com/embed/" in js and "img.referrerPolicy='no-referrer'" in js
    assert "STAGE.awaiting" in js and "window.STAGE_REPORT" in js


def test_going_deeper_links_the_new_story_to_its_scene(tmp_path):
    """Asked for as "click a stage and ask it to go deeper, so it builds further stages and
    the application evolves". The link is made on the Stage's side when the next story's
    first scene arrives, whichever brain answered."""
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    q1 = store.add_message(cid, "user", "el nino?")
    sc, _ = stage.clean({"kind": "steps", "title": "Warm water moves east", "items": ["a"]})
    stage.add(store, cid, sc)
    with pytest.raises(ValueError):
        stage.ask_deeper(store, cid, q1, 9)
    text = stage.ask_deeper(store, cid, q1, 1)
    assert text.startswith('Go deeper on "Warm water moves east"')
    q2 = store.add_message(cid, "user", text)
    stage.add(store, cid, sc)
    q3 = store.add_message(cid, "user", "now add Japan")     # not a Go deeper: a new version
    stage.add(store, cid, sc)
    by = {s["answer_to"]: s for s in stage.stories(store, cid)}
    assert by[q2]["parent"] == {"answer_to": q1, "seq": 1} and by[q1]["deeper"] == {"1": [q2]}
    assert by[q3]["parent"] is None, "only the next story after a Go deeper is its child"
    srv = (ROOT / "agentos/server.py").read_text()
    assert '@app.post("/api/stage/deeper")' in srv and '"parent": st.get("parent")' in srv


def test_versions_and_a_story_that_holds_its_own():
    """"When I ask in the chat to update the stage it should update it or add a new face
    with the previous one there as well": every top-level story of a chat is a version."""
    js = JS.read_text()
    assert "c.versions=(d.stories||[]).filter(s=>!s.parent)" in js and "Version ${vi+1} of ${vs.length}" in js
    assert "kept as a new version" in stage.note({})


def test_the_theater_and_its_music():
    js, css = JS.read_text(), (ROOT / "agentos/ui/src/css/31-stage.css").read_text()
    assert "STAGE_CHORDS" in js and "localStorage.getItem('stage.music')==='1'" in js, "off until turned on"
    assert "w.app.onClose=()=>{stageMusic(false,true)" in js, "the music stops with the window"
    # nothing inside a drawing animates forever: Chrome on Wayland painted the map twice
    import re
    for rule in re.findall(r"\.st-[a-z-]+\{[^}]*animation:[^}]*infinite[^}]*\}", css):
        raise AssertionError(f"an SVG part animates forever: {rule[:80]}")
    assert ".stg>.stg-bar{grid-row:4}" in css, "each part keeps its row in a short window"


def test_the_how_to_gets_a_picture_and_a_video_and_the_note_comes_first():
    """Measured with the owner's Claude Code: told at the end of the door's context, a how-to
    came back as one timeline; told first and by kind, it searched YouTube and Wikimedia and
    showed steps, a picture, a video and a table."""
    assert "YouTube video (search the web" in stage.BIG_LINE
    door = (ROOT / "agentos/executors.py").read_text()
    seg = door[door.index("stage_note = \"\""):][:900]
    assert "+ stage_note + dept_note" in seg


def test_a_phone_gives_the_story_the_room():
    """Measured at 390x844 with touch emulation: two rows of chrome left the map a 200px strip,
    the subtitle covered the last number card's note, and a third number fell out of the frame."""
    css = (ROOT / "agentos/ui/src/css/31-stage.css").read_text()
    js = JS.read_text()
    # the subtitle goes over a picture, never over words
    assert ".stg-scene:not(.k-map):not(.k-image):not(.k-video) .stg-foot{margin-top:0}" in css
    # one row each on a phone, with short labels, and two numbers a row
    for rule in ("body.dev-mobile .st-top{flex-wrap:nowrap", "body.dev-mobile .stg-bar{flex-wrap:nowrap",
                 "body.dev-mobile .stg-long{display:none}", "body.dev-mobile .st-nums{grid-template-columns"):
        assert rule in css, rule
    # full screen is offered only where the browser has it (an iPhone does not)
    assert "if(document.fullscreenEnabled){" in js
    # the map takes the frame's shape, and an upright frame keeps the places' longitudes
    i = js.index("async function stageMap(")
    body = js[i:i + 2600]
    assert "W*fh/fw" in body and "stageK(svg,W,H)" in body and "aspect<1.6&&lons.length" in body
    # measured after the scene laid out, and after the places' notes took their row
    assert body.index("await stageWorld()") < body.index("art.clientHeight")
    assert body.index("st-mapnotes") < body.index("art.clientHeight") and "art.insertBefore(svg,ol)" in body
    # the notes are one scrolling row on the Stage, so the map keeps its half
    assert ".stg .st-mapnotes{display:flex;overflow-x:auto;scroll-snap-type:x mandatory" in css
    assert ".stg-scene.k-map:has(.st-mapnotes) .stg-foot{margin-top:0}" in css
