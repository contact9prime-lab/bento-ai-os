"""The Stage with its chat beside it, the chat as a tree, and a blueprint as a document.

Asked for as "keep the chat window on the right … blueprint + chat, because you can ask more",
"dig deeper into something and come out of it … resume the chat from the top of the tree but the
context of everything is known", and "export the blueprint, like a crazy style document".
Pinned here:

- a message asked from the Stage's chat carries where in the tree (`stage_at`), read field by
  field, and the brain is told the place in front of the question (measured: told only in the
  system context, "these blades" inside the Fan was answered about the turbine blades);
- a story the agent shows from inside a part is that part gone deeper, and Back knows the part;
- the document is drawing sheets with every word escaped and the pictures credited;
- the page keeps one chat panel per conversation, filters it by branch, and counts a story asked
  from the Stage's own chat as the person's.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import bpdoc, stage  # noqa: E402
from agentos.memory import Store  # noqa: E402

ROOT = Path(__file__).parent.parent
CHAT = (ROOT / "agentos/ui/src/js/24w-stagechat.js").read_text()


def _engine():
    sc, _ = stage.clean({"kind": "blueprint", "title": "Jet engine", "source": "maker",
                         "facts": [{"label": "thrust", "value": "121", "unit": "kN"}],
                         "parts": [{"name": "Fan <script>x</script>", "id": "fan", "role": "moves air",
                                    "steps": ["air in", "pushed back"], "like": "a desk fan",
                                    "parts": [{"name": "Blades"}, {"name": "Hub"}]},
                                   {"name": "Core", "parts": [{"name": "Burner"}]}],
                         "links": [{"from": "Blades", "to": "Burner", "verb": "feeds", "kind": "air"}],
                         "unknowns": ["exact blade alloy"]})
    sc["picture"] = {"url": "https://upload.wikimedia.org/x.png", "title": "Cutaway", "credit": "Ada",
                     "licence": "CC BY 3.0", "page": "https://commons.wikimedia.org/wiki/File:x", "made": "found"}
    return sc


def test_where_a_question_was_asked_is_read_and_said_first():
    from agentos import server
    at = server._stage_at({"stage_at": {"scene": "s1", "path": ["fan", 3, "x" * 99], "names": ["Engine", "Fan"],
                                        "evil": True}})
    assert at == {"scene": "s1", "path": ["fan", "x" * 40], "names": ["Engine", "Fan"]}
    assert server._stage_at({"stage_at": {"path": ["fan"]}}) is None
    assert server._stage_at({}) is None
    words = server._stage_words({"stage_at": {"scene": "s1", "path": ["fan"], "names": ["Engine", "Fan"]}})
    assert words.startswith("[Asked on the Stage inside Engine › Fan.") and "mean the Fan" in words
    assert "top of the Engine blueprint" in server._stage_words({"stage_at": {"scene": "s", "path": [],
                                                                              "names": ["Engine"]}})
    src = (ROOT / "agentos/server.py").read_text()
    # the brain hears the place, the kept message stays the person's words
    assert '"content": _stage_words(data) + text' in src and "run_task(_stage_words(data) + text" in src
    assert '{"stage_at": _stage_at(data)}' in src and '"stage_at": item.get("stage_at")' in src


def test_a_story_shown_from_inside_a_part_is_a_branch_of_the_tree(tmp_path):
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "blueprint of a jet engine")
    top = stage.add(store, cid, _engine())
    # asked at the top: a new story there is a version, not a branch
    store.add_message(cid, "user", "redo it", {"stage_at": {"scene": top["id"], "path": [], "names": ["Jet engine"]}})
    v2 = stage.add(store, cid, _engine())
    assert v2["answer_to"] not in stage.links(store, cid)
    # asked inside the Fan: the story that answers is the Fan gone deeper
    store.add_message(cid, "user", "show the blade root", {"stage_at": {"scene": top["id"], "path": ["fan"],
                                                                         "names": ["Jet engine", "Fan"]}})
    deep, _ = stage.clean({"kind": "blueprint", "title": "Blade root", "parts": ["Dovetail", "Slot"]})
    child = stage.add(store, cid, deep)
    ln = stage.links(store, cid)[child["answer_to"]]
    assert ln == {"answer_to": top["answer_to"], "seq": 1, "path": ["fan"], "scene": top["id"]}
    parent = next(s for s in stage.stories(store, cid) if s["answer_to"] == top["answer_to"])
    assert parent["branches"] == [{"answer_to": child["answer_to"], "scene": top["id"], "path": ["fan"],
                                   "title": "Blade root"}]
    assert stage.stage_at_of(store, "nope") is None


def test_the_blueprint_as_drawing_sheets(tmp_path):
    store = Store(tmp_path / "a.db")
    cid = store.create_conversation("t")
    store.add_message(cid, "user", "blueprint of a jet engine")
    row = stage.add(store, cid, _engine())
    page = bpdoc.html(store, row["id"], agent="Aria", question="blueprint of a jet engine")
    # cover, the parts, how it works, one per main part, unknowns and credits
    assert page.count('class="sheet"') == 6 and "Sheet</th><td>6 of 6" in page
    assert "<script>x</script>" not in page.split("<script>window.STAGE_REPORT")[0]
    assert "Fan &lt;script&gt;x&lt;/script&gt;" in page
    assert "Cutaway · Ada · CC BY 3.0 · Wikimedia Commons" in page          # a CC BY picture is credited
    assert "exact blade alloy" in page and "air in" in page and "≈ a desk fan" in page
    assert 'data-mode="flows"' in page and 'data-path="fan"' in page and "@page{size:297mm 210mm" in page
    assert bpdoc.doc_number(row["id"], {"subject": "Jet engine"}).startswith("BP-JETENG-")
    assert bpdoc.filename("Jet engine / CFM", "pdf") == "jet-engine-cfm-blueprint.pdf"
    numbers, _ = stage.clean({"kind": "numbers", "title": "n", "source": "s",
                              "items": [{"label": "a", "value": 1}]})
    other = stage.add(store, cid, numbers)
    try:
        bpdoc.html(store, other["id"])
        raise AssertionError("only a blueprint")
    except ValueError:
        pass
    try:
        bpdoc.html(store, "missing")
        raise AssertionError("not here")
    except KeyError:
        pass


def test_every_face_can_export_it():
    src = (ROOT / "agentos/server.py").read_text()
    assert '@app.get("/api/stage/scene/{sid}/export")' in src
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert '"contact", "export"])' in cli and "bpdoc.html(store, r[0]" in cli
    painter = (ROOT / "agentos/ui/src/js/24v-blueprint.js").read_text()
    assert "'/export?format='" in painter and "'Document (PDF)'" in painter
    for f in ("agentos/telegram.py", "agentos/whatsapp.py"):
        assert "send_blueprint_docs(" in (ROOT / f).read_text()


def test_the_stage_chat_is_a_tree():
    for needle in ("function stageChatFilter(", "function stageChatTree(", "function stageChatFollow(",
                   "p._filter=stageChatFilter", "STAGE_CHAT.lastAt", "'Threads inside'", "'Went deeper'",
                   "'↑ Back up the tree'", "!(STAGE.cur&&STAGE.cur.parent)"):
        assert needle in CHAT, needle
    assert "innerHTML" not in CHAT
    cp = (ROOT / "agentos/ui/src/js/04a-copilot.js").read_text()
    assert "stage_at:o.stageAt" in cp and "panel._filter" in cp and "panel._replay=" in cp
    stg = (ROOT / "agentos/ui/src/js/24l-stage.js").read_text()
    assert "STAGE_CHAT.cid===cid&&STAGE_CHAT.el&&STAGE_CHAT.el.isConnected" in stg     # its stories are yours
    bp = (ROOT / "agentos/ui/src/js/24v-blueprint.js").read_text()
    assert "stageChatFollow(st)" in bp and "Date.now()<(STAGE_CHAT.want.until||0)" in bp
    # one fake turn's context, as the Stage would say it, never empty for a blueprint
    assert "This chat follows the blueprint as a tree" in CHAT

