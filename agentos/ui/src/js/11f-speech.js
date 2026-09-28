/* ================= Settings → Voice → Voice engine =================
   Which engine reads your agents aloud (agentos/speech.py). The browser's own voices
   stay the default; "This computer" is the machine's own speech (say, piper,
   espeak-ng, Windows speech); ElevenLabs, OpenAI and Google Cloud need a key, which is
   sent once and never shown again (the page learns only that one is set). Every agent
   keeps its own voice on every engine; the lead's is chosen here.
   Faces: GUI and SUI draw this. TUI: `bento voice` shows, sets and tries the same thing.
   `var`/function declarations only. */
var SPEECH_UI={d:null,voices:{},busy:false};
async function speechPaint(){
  const box=document.getElementById('v-engine-box');if(!box)return;
  let d;
  try{d=await apiJSON('/api/speech')}catch(e){box.innerHTML=`<p class="mut">${esc(e.message)}</p>`;return}
  SPEECH_UI.d=d;box.classList.remove('mut');
  const c=d.config||{},eng=d.engines||{},t=d.titles||{},cur=c.engine||'browser';
  const opts=Object.keys(t).map(k=>`<option value="${esc(k)}" ${k===cur?'selected':''}>${esc(t[k])}${eng[k]&&!eng[k].ok?' · not ready':''}</option>`).join('');
  const cloud=['elevenlabs','openai','google'].includes(cur);
  const st=eng[cur]||{};
  box.innerHTML=`<div class="sp-row"><select id="v-engine" onchange="speechSet({engine:this.value})">${opts}</select>
      <button class="endbtn" onclick="speechTry(this)">Try it</button></div>
    ${st.ok?'':`<p class="sp-why">${esc(st.why||'')}</p>`}
    ${cloud?`<div class="sp-row">${secretField('v-key',(c.keys||{})[cur]?(c.openai_from_provider&&cur==='openai'?'using your OpenAI provider key':'a key is saved'):'paste your '+t[cur]+' API key')}
      <button class="endbtn" onclick="speechKey()">Save key</button>${(c.keys||{})[cur]&&!(c.openai_from_provider&&cur==='openai')?`<button class="endbtn" onclick="speechSet({keys:{${cur}:''}})">Remove</button>`:''}</div>`:''}
    ${cur==='browser'?'':`<div class="sp-row"><label class="sp-lab">Your lead’s voice</label><select id="v-srv-voice" onchange="speechSet({voice:this.value})"><option value="">loading…</option></select></div>
      <p class="mut sp-note">Every other agent gets a different voice from this engine, the same one each time.</p>`}`;
  // the browser's own voice picker below is this engine's twin; with another engine on,
  // two "your lead's voice" rows would each look like the one that counts
  const bv=document.getElementById('v-voice'),bvRow=bv&&bv.closest('.prow');
  if(bvRow)bvRow.style.display=cur==='browser'?'':'none';
  if(cur!=='browser'&&st.ok)speechVoices(cur,c.voice||'');
  else{const v=document.getElementById('v-srv-voice');if(v)v.innerHTML='<option value="">not ready yet</option>'}
}
async function speechVoices(engine,chosen){
  const sel=document.getElementById('v-srv-voice');if(!sel)return;
  try{
    const d=await apiJSON('/api/speech/voices?engine='+encodeURIComponent(engine));
    const vs=d.voices||[];SPEECH_UI.voices[engine]=vs;
    sel.innerHTML=`<option value="">${vs.length?'Pick one for me':'no voices found'}</option>`+vs.map(v=>
      `<option value="${esc(v.id)}" ${v.id===chosen?'selected':''}>${esc(v.name)}${v.lang?' · '+esc(v.lang):''}</option>`).join('');
  }catch(e){sel.innerHTML=`<option value="">${esc(e.message)}</option>`}
}
async function speechSet(patch){
  try{
    await apiJSON('/api/speech',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
    if(typeof SPEECH!=='undefined'){SPEECH.loaded=false;SPEECH.warned=false}
    if(patch.engine)toast('Voice engine: '+((SPEECH_UI.d&&SPEECH_UI.d.titles||{})[patch.engine]||patch.engine));
    speechPaint();
  }catch(e){toast(e.message)}
}
function speechKey(){
  const k=document.getElementById('v-key'),cur=((SPEECH_UI.d||{}).config||{}).engine;
  if(!k||!k.value.trim())return toast('paste the key first');
  speechSet({keys:{[cur]:k.value.trim()}});
}
/* Your lead, then two of your agents, each in its own voice: what a huddle sounds like. */
async function speechTry(btn){
  btn.disabled=true;
  if(typeof speechStop==='function')speechStop();
  // Try it always says why when the engine refuses, even if a toast already did once
  if(typeof SPEECH!=='undefined'){SPEECH.loaded=false;SPEECH.warned=false}
  let names=[];
  try{names=((await (await fetch('/api/subagents')).json()).subagents||[]).map(s=>s.name).slice(0,2)}catch(e){}
  speakAs('@agent','Hi, I’m '+agentName()+'. This is how I sound.');
  names.forEach(n=>speakAs(n,'And I’m '+n+'. This is my voice.'));
  setTimeout(()=>{btn.disabled=false},1500);
}
