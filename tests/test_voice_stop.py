"""The voice can be stopped from wherever it is heard.

Reported as "if I want to stop the voice in the chat I should be able to do that, I have
no idea how to stop the voice". The only way was the chat header's "Voice on" button,
which reads as a setting, is not on the Office's chat panel or the prompt bar, and turns
the voice off for good.

What these defend (the speech code run in Node with a stand-in page):

- while anything is being said there is one Stop pill, and it goes when the speaking ends;
- pressing it, or Esc, stops what is being said and what is queued;
- the rest of a reply still arriving is not said, and the whole reply is not said at the
  end of the turn either;
- the voice is still on for the next reply.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js/08-wallpaper-jarvis-voice.js"
CSS = ROOT / "agentos/ui/src/css/14-omnibar.css"

HARNESS = r"""
const els={};const keys=[];
function mk(){return {id:'',classList:{s:new Set(),add(c){this.s.add(c)},remove(c){this.s.delete(c)},contains(c){return this.s.has(c)}},
  children:[],appendChild(c){this.children.push(c)},setAttribute(){},addEventListener(t,f){this['on_'+t]=f},textContent:''}}
global.document={body:{appendChild(e){els[e.id]=e}},createElement:mk,getElementById:i=>els[i]||null,
  addEventListener(t,f){if(t==='keydown')keys.push(f)}};
global.window={};global.JARVIS={on:false,busy:false};global.VOICE={tts:true,live:true,rate:1};
global.agentName=()=>'Aria';global.voiceClean=t=>String(t||'').trim();global.toast=()=>{};
global.jarvisSetPhase=()=>{};global.agentVoice=()=>({pitch:1});
const said=[];
// the browser engine, with a voice that never finishes on its own
global.SpeechSynthesisUtterance=function(t){this.text=t};
global.speechSynthesis={speak(u){said.push(u.text)},cancel(){said.push('<cancel>')}};
window.speechSynthesis=global.speechSynthesis;
"""

TAIL = r"""
SPEECH.loaded=true;SPEECH.engine='browser';
const out={};
(async()=>{
  speechLiveFeed('c1','The first sentence of the answer is here. ');
  await new Promise(r=>setTimeout(r,5));
  out.pill_on=!!(els.voicestop&&els.voicestop.classList.contains('on'));
  out.speaking=speechSpeaking();
  els.voicestop.on_click({preventDefault(){},stopPropagation(){}});
  out.after_stop={pill:els.voicestop.classList.contains('on'),pending:SPEECH.pending,cancelled:said.includes('<cancel>')};
  const before=said.length;
  speechLiveFeed('c1','The first sentence of the answer is here. And a second one that arrives after the stop. ');
  out.said_after_stop=said.length-before;
  out.end_handled=speechLiveEnd('c1','The first sentence of the answer is here. And a second one that arrives after the stop. Then the end.');
  out.said_at_end=said.length-before;
  // the next reply is spoken: stopping is not switching the voice off
  speechLiveFeed('c1','A new answer to a new question starts here. ');
  await new Promise(r=>setTimeout(r,5));
  out.next_reply_spoken=said[said.length-1];
  out.voice_still_on=VOICE.tts;
  // Esc does the same
  keys.forEach(f=>f({key:'Escape'}));
  out.after_esc=SPEECH.pending;
  // nothing to stop in Jarvis: its own screen is the voice
  JARVIS.on=true;speakAs('@agent','In Jarvis.');
  out.pill_in_jarvis=els.voicestop.classList.contains('on');
  console.log(JSON.stringify(out));
})();
"""


def _body():
    src = JS.read_text()
    a = src.index("var SPEECH={")
    b = src.index("var VOICE_AGENTS=null;")
    return src[a:b]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_voice_stops_where_it_is_heard_and_stays_on():
    r = subprocess.run(["node", "-e", HARNESS + _body() + TAIL], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr[-800:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["pill_on"] and out["speaking"], "something is being said: the pill is there"
    assert out["after_stop"] == {"pill": False, "pending": 0, "cancelled": True}
    assert out["said_after_stop"] == 0, "the rest of the reply still arriving is not said"
    assert out["end_handled"] is True and out["said_at_end"] == 0, "and the whole reply is not said at the end"
    assert out["next_reply_spoken"].startswith("A new answer"), "the next reply is spoken"
    assert out["voice_still_on"] is True
    assert out["after_esc"] == 0, "Esc stops it too"
    assert out["pill_in_jarvis"] is False


def test_the_pill_is_a_real_target_on_every_surface():
    css = CSS.read_text()
    rule = css[css.index("#voicestop{"):]
    assert "min-height:var(--tap,44px)" in rule and "position:fixed" in rule
    js = JS.read_text()
    assert "el.addEventListener('click'" in js and "speechHush()" in js
    # built with text nodes, never markup
    pill = js[js.index("function speechPill()"):js.index("if(typeof document!=='undefined')document.addEventListener('keydown'")]
    assert "innerHTML" not in pill
