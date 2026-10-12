"""What an agent builds is held to one bar, wherever it was built.

Asked for as "the apps App Studio or Bento makes don't have a serious jive to them:
more engaging, more intuitive, more reliable". Four gaps were found by reading the
pipeline end to end: an app built in Chat by an agent CLI got no design kit, no
runtime guide and no check at all; nothing caught a script that does not parse; the
sandboxed frame answers confirm() with "no", so "Delete this?" never deleted; and the
starter app on the setup screen saved nothing (appData.set takes one object).
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import appcheck, onboarding                           # noqa: E402
from agentos import executors as execmod                           # noqa: E402
from agentos import server                                         # noqa: E402

ROOT = Path(__file__).parent.parent
NODE = shutil.which("node")


def _rule(html):
    return {i.rule for i in appcheck.check(html, set()).issues}


def test_the_kit_has_the_pieces_an_app_is_told_to_use():
    css = server.APP_UI_CSS
    for cls in (".hero", ".tabs", ".chip", ".toggle", ".progress", ".stat", ".list",
                ".item", ".avatar", ".badge.ok", ".spread", ".skeleton", "button.ghost",
                "button.danger", "prefers-reduced-motion", ":focus-visible"):
        assert cls in css, cls
    persona = server.BUILDER_PERSONA
    for helper in ("appToast", "appConfirm", "appCelebrate", "appIcon", "appShare", "appFmt"):
        assert helper in persona, f"the builder is not told about {helper}"
    assert "NEVER" in persona and "confirm()" in persona


def _runtime():
    rt = server.APP_RUNTIME % ("a1", "tok", "window", "m")
    return rt[rt.index(">") + 1:rt.rindex("</script>")]


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_runtime_parses_and_its_helpers_run(tmp_path):
    js = _runtime()
    # A minimal page for the helpers to run against: enough DOM to append and style.
    stub = """
const el = () => ({style:{setProperty(){}}, classList:{add(){},remove(){}}, children:[],
  appendChild(c){this.children.push(c);return c}, remove(){}, addEventListener(){},
  querySelector(){return null}, setAttribute(){}, focus(){}, set innerHTML(v){this._h=v}, get innerHTML(){return this._h||''},
  set textContent(v){this._t=v}, get textContent(){return this._t||''}});
globalThis.document = {createElement: el, head: el(), body: el(), documentElement: el(),
  addEventListener(){}, getElementById(){return null}, querySelector(){return null},
  readyState:'complete', execCommand(){return true}};
globalThis.window = globalThis; globalThis.parent = {postMessage(){}};
globalThis.addEventListener = () => {}; globalThis.matchMedia = () => ({matches:true});
globalThis.requestAnimationFrame = f => 0; globalThis.navigator = {};
globalThis.fetch = async () => ({ok:true, json: async () => ({}), text: async () => ''});
globalThis.location = {href:'x'}; globalThis.CustomEvent = class {};
"""
    check = """
const out = {
  num: appFmt.num(12345.678), pct: appFmt.pct(.42), dur: appFmt.dur(125),
  ago: appFmt.ago(Date.now() - 120000), icons: appIcon.names.length,
  svg: appIcon('plus').startsWith('<svg'), confirm: typeof appConfirm, toast: typeof appToast,
  celebrate: typeof appCelebrate, share: typeof appShare,
};
appToast('hi'); alert('still a toast');
console.log(JSON.stringify(out));
"""
    f = tmp_path / "rt.js"
    f.write_text(stub + js + check)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[-800:]
    import json
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["pct"] == "42%" and out["dur"] == "2:05" and out["ago"] == "2 min ago"
    assert out["icons"] >= 20 and out["svg"]
    assert {out["confirm"], out["toast"], out["celebrate"], out["share"]} == {"function"}


def test_the_theme_travels_only_as_colours_and_only_to_a_frame_we_drew():
    rt = _runtime()
    assert "e.source !== parent" in rt and "^--[a-z0-9-]+$" in rt
    wm = (ROOT / "agentos/ui/src/js/05-apps-registry.js").read_text()
    body = wm[wm.index("agentos!=='theme?'"):]
    assert "f.contentWindow===e.source" in body, "only a frame this page drew is answered"
    assert "['--acc','--acc2','--on-acc']" in body


@pytest.mark.parametrize("src", [
    "<button onclick=\"if(confirm('Delete?'))del()\">x</button>",
    "<script>async function go(){ if (window.confirm('sure')) wipe() }</script>",
    "<script>const name = prompt('Your name?')</script>",
])
def test_a_modal_the_sandbox_refuses_is_broken(src):
    assert "modal-dialog" in _rule(src)


@pytest.mark.parametrize("src", [
    "<script>async function go(){ if (await appConfirm('Delete?', {danger:true})) wipe() }</script>",
    "<script>const t = 'please confirm(it)'; dialog.confirm(); // confirm()\n</script>",
])
def test_the_runtimes_own_confirm_is_not_flagged(src):
    assert "modal-dialog" not in _rule(src)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_script_that_does_not_parse_is_broken_with_the_parsers_words():
    rep = appcheck.check("<div id=a></div><script>function f( { return 1 }</script>", set())
    issue = next(i for i in rep.issues if i.rule == "js-syntax")
    assert issue.severity == appcheck.BROKEN and "script 1" in issue.message
    ok = "<script>const x = 1; console.log(x)</script><script type=module>await 1</script>"
    assert "js-syntax" not in _rule(ok) and "top-level-await" not in _rule(ok)


def test_a_chat_build_gets_the_same_brief_as_a_studio_build(tmp_path):
    p = server.write_app_brief(tmp_path)
    text = Path(p).read_text()
    assert "BUILD QUALITY" in text and "MAKE IT A JOY TO USE" in text and "appConfirm" in text
    assert "PROCESS — work like" not in text, "the create_app mechanics stay with the Studio"
    co = {"path": str(tmp_path / "app.html"), "brief": p}
    assert p in execmod.new_app_note(co)
    assert p in execmod.chat_app_note({**co, "name": "Clock", "app_id": 3})
    assert "APP_BRIEF" not in execmod.new_app_note({"path": "x"})
    assert 'checkout["brief"] = write_app_brief(' in (ROOT / "agentos/server.py").read_text()


def test_create_app_answers_with_what_the_check_found(tmp_path):
    from agentos.memory import Store
    from agentos.tools import Toolbox
    tb = Toolbox({"workspace": str(tmp_path), "providers": {}, "port": 8321}, Store(tmp_path / "t.db"))
    bad = "<!doctype html><title>Bin</title><button onclick=\"if(confirm('x'))go()\">Empty</button>"
    out = asyncio.run(tb.execute("create_app", {"name": "Bin", "html": bad}))
    assert "saved" in out and "AUTOMATED CHECK" in out and "confirm" in out
    good = "<!doctype html><title>Hi</title><div class=card><h2>Hi</h2></div>"
    out = asyncio.run(tb.execute("create_app", {"name": "Hi", "html": good}))
    assert "saved" in out


def _fix_setup(monkeypatch, tmp_path, html):
    path = tmp_path / "app.html"
    path.write_text(html)
    calls = []

    async def fake_run_task(task, env, sink, run):
        calls.append((task, env.session_id))
        path.write_text(html.replace("confirm(", "await appConfirm("))
        run.session_id = "s2"
        run.cost_usd = .01

    monkeypatch.setattr(execmod, "run_task", fake_run_task)
    env = execmod.Envelope(workspace=str(tmp_path))
    run = execmod.Run(engine="claude-code")
    run.session_id = "s1"
    statuses = []

    async def evsend(ev):
        statuses.append(ev)

    async def relay(ev):
        pass
    co = {"path": str(path), "before": "", "brief": "/x/APP_BRIEF.md"}
    return co, env, run, calls, statuses, evsend, relay


def test_a_broken_chat_build_gets_one_fix_turn_in_its_own_session(monkeypatch, tmp_path):
    co, env, run, calls, statuses, evsend, relay = _fix_setup(
        monkeypatch, tmp_path, "<script>function go(){ if(confirm('x')) wipe() }</script>")
    asyncio.run(server._chat_app_fix("claude-code", env, run, (co, None), None, evsend, relay))
    assert len(calls) == 1 and calls[0][1] == "s1", "resumes the session that wrote it"
    assert "confirm()" in calls[0][0] and "/x/APP_BRIEF.md" in calls[0][0]
    assert run.session_id == "s2" and run.cost_usd == pytest.approx(.01)
    assert any("fixing 1 problem" in e.get("message", "") for e in statuses)


def test_a_clean_build_or_a_cli_without_resume_is_left_alone(monkeypatch, tmp_path):
    co, env, run, calls, _s, evsend, relay = _fix_setup(
        monkeypatch, tmp_path, "<div class=card>fine</div>")
    asyncio.run(server._chat_app_fix("claude-code", env, run, (co,), None, evsend, relay))
    assert calls == []
    co, env, run, calls, _s, evsend, relay = _fix_setup(
        monkeypatch, tmp_path, "<script>if(confirm('x'))y()</script>")
    asyncio.run(server._chat_app_fix("gemini-cli", env, run, (co,), None, evsend, relay))
    assert calls == [], "a CLI that cannot resume would not know the file"
    run.stopped = True
    asyncio.run(server._chat_app_fix("claude-code", env, run, (co,), None, evsend, relay))
    assert calls == [], "a stopped turn is not resumed"


def test_the_starter_app_saves_and_passes_the_check():
    html = onboarding.STARTER_APP["html"]
    assert "appData.set({text:" in html and "appData.get()" in html
    assert "appData.set('" not in html and "appData.get('" not in html
    rep = appcheck.check(html, set())
    assert not [i for i in rep.issues if i.severity == appcheck.BROKEN], rep.brief()
    assert "#12161d" not in html, "the kit's colours, so it follows the theme"
