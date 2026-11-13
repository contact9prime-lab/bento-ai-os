"""App Studio is an IDE: open an app's file, edit it, check it, run it unsaved, save a version.

Asked for as "for the app studio, can you build an IDE like interface". Before, an app could
only be changed by describing the change to the builder; nobody could open the file. Now:

- the source has one door both faces use (agentos/appsource.py): the Studio's Save and
  `bento studio push|edit`, and a save over a version that moved on is refused;
- the checker runs on the text being edited and says which line each finding is on;
- unsaved code runs in the preview for the account that sent it, and nobody else;
- a change in what the app asks for puts its permissions up for review again.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import appsource                                       # noqa: E402
from agentos.memory import Store                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "agentos/ui/src/js"
CSS = ROOT / "agentos/ui/src/css"


def _app(store, name="Counter"):
    return store.save_app(name, "", "", appsource.blank(name), note="agent build")


# ---- the checker points at lines ---------------------------------------------------------

def test_a_blank_app_is_already_a_bento_app():
    assert appsource.problems(appsource.blank("Counter")) == []


def test_each_finding_says_its_line():
    html = appsource.blank("x").replace("show();\n  appCopilot", "show();\n  if(confirm('x')){}\n  appCopilot")
    line = next(i for i, L in enumerate(html.split("\n"), 1) if "confirm(" in L)
    probs = appsource.problems(html)
    assert [(p["rule"], p["line"]) for p in probs] == [("modal-dialog", line)]
    tool = html.replace("appData.set(state);", "appData.set(state); appTool('no_such_tool');", 1)
    tline = next(i for i, L in enumerate(tool.split("\n"), 1) if "no_such_tool" in L)
    found = {p["rule"]: p["line"] for p in appsource.problems(tool, {"run_command"})}
    assert found["unknown-tool"] == tline


@pytest.mark.skipif(not shutil.which("node"), reason="the syntax rule needs Node")
def test_a_syntax_error_is_on_the_line_node_names():
    html = appsource.blank("x").replace("  show();\n  appCopilot", "  show(;\n  appCopilot")
    line = next(i for i, L in enumerate(html.split("\n"), 1) if "show(;" in L)
    probs = [p for p in appsource.problems(html) if p["rule"] == "js-syntax"]
    assert probs and probs[0]["line"] == line and probs[0]["severity"] == "broken"


def test_a_whole_file_finding_has_no_line_and_the_worst_come_first():
    probs = appsource.problems("<!doctype html><html><body><script>localStorage.x=1</script></body></html>")
    assert probs[0]["severity"] == "contract"
    assert any(p["line"] == 0 for p in probs)          # no widget view: the whole file
    assert next(p for p in probs if p["rule"] == "localstorage-not-appdata")["line"] == 1


# ---- a save is a version, and never silently over another one ---------------------------

def test_save_refuses_a_stale_base_and_force_keeps_mine(tmp_path):
    store = Store(tmp_path / "a.db")
    aid = _app(store)
    src = appsource.load(store, aid)
    assert src["version"] == 1
    store.save_app("Counter", "", "", src["html"] + "<!-- a build -->", note="a build")   # v2 meanwhile
    mine = src["html"].replace("Add one", "Add two")
    with pytest.raises(appsource.Conflict) as e:
        appsource.save(store, aid, mine, base=1)
    assert e.value.current == 2
    res = appsource.save(store, aid, mine, base=1, force=True)
    assert res == {"version": 3, "changed": True, "review": False}
    assert store.get_app(aid)["html"] == mine
    assert store.app_versions(aid)[0]["note"] == appsource.NOTE


def test_saving_the_same_text_makes_no_version(tmp_path):
    store = Store(tmp_path / "a.db")
    aid = _app(store)
    src = appsource.load(store, aid)
    assert appsource.save(store, aid, src["html"], base=1) == {"version": 1, "changed": False, "review": False}


def test_an_empty_or_huge_file_is_not_an_app(tmp_path):
    store = Store(tmp_path / "a.db")
    aid = _app(store)
    for bad in ("", "   ", "x" * (appsource.MAX_BYTES + 1)):
        with pytest.raises(ValueError):
            appsource.save(store, aid, bad)
    with pytest.raises(ValueError):
        appsource.save(store, "nope", "<p>x</p>")


def test_asking_for_something_new_puts_permissions_up_for_review(tmp_path):
    store = Store(tmp_path / "a.db")
    aid = _app(store)
    store.set_app_manifest(aid, json.dumps({"permissions": []}), "approved")
    src = appsource.load(store, aid)
    # a change that asks for nothing new keeps the approval
    res = appsource.save(store, aid, src["html"].replace("Add one", "Add"), base=1)
    assert not res["review"] and store.get_app(aid)["manifest_status"] == "approved"
    # a new tool call is something nobody approved yet; the grants themselves are untouched
    more = store.get_app(aid)["html"].replace("show();\n  appCopilot",
                                              "show();\n  appTool('run_command', {});\n  appCopilot")
    res = appsource.save(store, aid, more, base=2)
    assert res["review"] and store.get_app(aid)["manifest_status"] == "none"


# ---- the routes -----------------------------------------------------------------------------

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    from agentos import users as usersmod
    usersmod.reset_caches()
    with TestClient(servermod.app) as cl:
        yield cl, servermod


def test_the_routes_load_check_save_and_refuse_a_stale_save(client):
    cl, servermod = client
    made = cl.post("/api/apps/new", json={"name": "IDE Route Test"}).json()
    again = cl.post("/api/apps/new", json={"name": "IDE Route Test"}).json()
    assert again["name"] == "IDE Route Test 2" and again["id"] != made["id"]   # never over an existing app
    aid = made["id"]
    try:
        src = cl.get(f"/api/apps/{aid}/source").json()
        assert src["version"] == 1 and "appCopilot.mount" in src["html"]
        chk = cl.post("/api/apps/check", json={"html": src["html"].replace("show();", "show(); prompt('x');", 1)}).json()
        assert [p["rule"] for p in chk["problems"]] == ["modal-dialog"] and chk["problems"][0]["line"] > 0
        r = cl.put(f"/api/apps/{aid}/source", json={"html": src["html"] + "\n", "base": 1})
        assert r.status_code == 200 and r.json()["version"] == 2
        assert r.json()["manifest_status"] == "proposed"      # put to the person, as after a build
        stale = cl.put(f"/api/apps/{aid}/source", json={"html": src["html"] + "\n\n", "base": 1})
        assert stale.status_code == 409 and stale.json()["current"] == 2
        assert cl.put(f"/api/apps/{aid}/source", json={"html": "", "base": 2}).status_code == 400
        assert cl.get("/api/apps/nope/source").status_code == 404
    finally:
        for x in (made["id"], again["id"]):
            cl.delete(f"/api/apps/{x}")


def test_unsaved_code_runs_only_for_whoever_sent_it(client):
    cl, servermod = client
    aid = cl.post("/api/apps/new", json={"name": "IDE Draft Test"}).json()["id"]
    try:
        d = cl.post(f"/api/apps/{aid}/draft", json={"html": "<p>DRAFT-ONLY-TEXT</p>"}).json()["draft"]
        page = cl.get(f"/api/apps/{aid}/page?draft={d}")
        assert page.status_code == 200 and "DRAFT-ONLY-TEXT" in page.text
        assert "DRAFT-ONLY-TEXT" not in cl.get(f"/api/apps/{aid}/page").text      # saved code is unchanged
        assert cl.get(f"/api/apps/{aid}/page?draft=forged").status_code == 404
        servermod.state["app_drafts"][d]["uid"] = "someone-else"
        assert cl.get(f"/api/apps/{aid}/page?draft={d}").status_code == 404
        servermod.state["app_drafts"][d].update(uid="", t=0)                       # expired
        assert cl.get(f"/api/apps/{aid}/page?draft={d}").status_code == 404
        other = cl.post("/api/apps/new", json={"name": "IDE Draft Other"}).json()["id"]
        d2 = cl.post(f"/api/apps/{aid}/draft", json={"html": "<p>x</p>"}).json()["draft"]
        assert cl.get(f"/api/apps/{other}/page?draft={d2}").status_code == 404     # another app's draft
        cl.delete(f"/api/apps/{other}")
    finally:
        cl.delete(f"/api/apps/{aid}")


def test_an_app_frame_cannot_save_source():
    """The new routes are ordinary /api/apps routes: csrf_origin_guard refuses an app's
    Origin: null, so a running app cannot rewrite itself or another app."""
    server = (ROOT / "agentos/server.py").read_text()
    for route in ('@app.put("/api/apps/{aid}/source")', '@app.post("/api/apps/new")',
                  '@app.post("/api/apps/{aid}/draft")'):
        assert route in server
    from agentos import server as servermod
    from fastapi.testclient import TestClient
    with TestClient(servermod.app) as cl:
        r = cl.post("/api/apps/new", json={"name": "x"}, headers={"Origin": "null"})
        assert r.status_code == 403


# ---- the terminal face ---------------------------------------------------------------------

def _bento(home, *args, env_extra=None):
    env = {**os.environ, "AGENTOS_HOME": str(home), "AGENTOS_VAULT_KEYRING": "0", **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "agentos", "studio", *args], env=env,
                          capture_output=True, text=True, cwd=ROOT, timeout=60)


def test_bento_studio_pulls_pushes_and_refuses_a_stale_push(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r = _bento(home, "new", "Counter")
    assert r.returncode == 0 and "started from a blank file" in r.stdout
    f = tmp_path / "c.html"
    assert _bento(home, "pull", "Counter", str(f)).returncode == 0 and "appCopilot" in f.read_text()
    f.write_text(f.read_text().replace("Add one", "Add three"))
    r = _bento(home, "push", "Counter", str(f))
    assert r.returncode == 0 and "saved as v2" in r.stdout and "no problems" in r.stdout
    # pulled at v2, and the app moves on before the push
    _bento(home, "pull", "Counter", str(f))
    store = Store(home / "agentos.db")
    a = store.list_apps()[0]
    store.save_app("Counter", "", "", store.get_app(a["id"])["html"] + "<!-- build -->", note="a build")
    f.write_text(f.read_text() + "<!-- mine -->")
    r = _bento(home, "push", "Counter", str(f))
    assert r.returncode == 1 and "changed since you opened it" in r.stdout and "--force" in r.stdout
    edited = _bento(home, "edit", "Counter", env_extra={"EDITOR": "sed -i s/Add.three/Add.four/"})
    assert edited.returncode == 0 and "saved as v4" in edited.stdout
    chk = _bento(home, "check", "Counter")
    assert chk.returncode == 0 and "no problems" in chk.stdout


# ---- the page --------------------------------------------------------------------------------

@pytest.mark.skipif(not shutil.which("node"), reason="runs the editor's code in Node")
def test_the_highlighter_escapes_everything_and_reads_the_file_back():
    """The highlighted layer sits under the textarea: if it ever dropped or added a
    character, the caret would drift off the letters it is on. And a file's text must
    never become markup."""
    script = r"""
const fs=require('fs');global.esc=s=>String(s);
eval(fs.readFileSync(process.argv[1],'utf8')+';global.H=ideHighlight;global.O=ideOutline;global.D=ideDiff');
const src=fs.readFileSync(0,'utf8');
const r=H(src);
const back=r.html.replace(/<span class="[^"]*">/g,'').replace(/<\/span>/g,'').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
const tags=r.html.replace(/<span class="[^"]*">|<\/span>/g,'');
console.log(JSON.stringify({same:back===src,modes:r.modes.length,lines:src.split('\n').length,
  raw:/<(?!\/?span)/.test(tags),outline:O(src).map(o=>o.kind),diff:(d=>[d.head,d.tail,...d.rows.map(x=>x.k+x.t)])(D('a\nb\nc','a\nB\nc'))}));
"""
    src = appsource.blank("Counter") + ("<script>const re=/[<'\"]/g; let s='</div>'; const t=`a ${1}`; // x\n</script>"
                                        "<style>@media (max-width:4px){ .a:hover{color:#fff} }</style>"
                                        "<img src=x onerror=alert(1)><!-- c -->")
    out = subprocess.run(["node", "-e", script, str(JS / "26b-studio-ide.js")], input=src,
                         capture_output=True, text=True, timeout=30)
    r = json.loads(out.stdout)
    assert r["same"] and r["modes"] == r["lines"] and not r["raw"]
    assert {"css", "js", "fn", "id", "surface", "ai"} <= set(r["outline"])
    assert r["diff"] == [1, 1, "-b", "+B"]      # the unchanged head and tail are counted, not listed


def test_the_studio_keeps_edits_across_repaints_and_asks_before_losing_them():
    studio = (JS / "26-studio.js").read_text()
    # an `apps` broadcast (every save sends one) repaints the list, not the editor
    assert "const soft=!STUDIO._hard&&body._ideSel===STUDIO.sel" in studio
    assert "docs:{}" in studio and "STUDIO.docs[aid]={text:src.html,saved:src.html,base:src.version" in studio
    # a save names its base, and a refusal is a choice, never an overwrite
    assert "body:JSON.stringify({html:text,base:doc.base,force:!!force})" in studio
    assert "Keep mine and save" in studio and "Load v${+doc.stale}" in studio
    # closing a tab with edits asks; a build first offers to save the edits
    assert "Close without saving?" in studio and "Save and build" in studio
    # the editor saves once per Ctrl+S: the window's handler skips what the editor took
    assert "!e.defaultPrevented&&(e.metaKey||e.ctrlKey)" in studio


def test_the_phone_layout_queries_a_wrapper_and_panes_respect_hidden():
    css = (CSS / "41-studio-ide.css").read_text()
    # a container query cannot restyle its own container: the first cut put both on .stide
    assert ".stide-wrap{height:100%;min-height:0;container-type:inline-size;container-name:stide}" in css
    assert "container-type" not in css.split(".stide{", 1)[1].split("}", 1)[0]
    # display:flex on the builder pane out-ranked [hidden], so Problems showed under Builder
    assert ".ide-pane[data-for=builder]:not([hidden])" in css
    # an implicit grid column takes the tab row's full width, which pushed Fix it off a phone
    assert ".ide-center{display:grid;grid-template-columns:minmax(0,1fr);" in css
    # the old phone rule hid the explorer for good; it is a pane of its own now
    assert "body.dev-mobile .stside" not in (CSS / "15-responsive.css").read_text()
