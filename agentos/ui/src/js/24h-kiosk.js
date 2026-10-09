/* ================= the kiosk face =================
   This machine's own screen as the Office, full screen, with the mic on: say the
   agent's name and what you want, and the answer is spoken while the office shows
   the agents doing the work. Asked for as "a kiosk mode as well where mic would be
   on and agents would be working in the office", for a Raspberry Pi with a screen.

   What decides it is agentos/face.py (`face.kiosk`, `face.wake`), read from
   /api/platform. Three rules:
   - Only the screen plugged into the machine gets it (not a remote browser), or a
     page opened with #kiosk. A phone looking at the same box keeps its desktop.
   - Hearing is the SERVER's (agentos/hearing.py): Chromium on a Pi has no key for
     the browser's own recogniser. The page records one utterance at a time (16 kHz
     WAV, cut at the pause) and posts it to /api/speech/hear. When nothing on the
     machine can understand speech, the kiosk says so and shows no live mic.
   - A turn here is an ordinary chat turn in its own thread (origin `kiosk`), so the
     gate, the approvals and the ledger are the ones every other turn gets. An
     approval card still floats over the kiosk.
   TUI: not applicable, a terminal has no office to show; `bento face` sets it.
   SUI: the chrome is hidden, so suiChrome() gives the bands back (00-sui.js). */
var KIOSK={on:false,cid:'',phase:'',line:'',heard:'',reply:'',follow:0,speaking:false,busy:false,
  stream:null,ctx:null,src:null,node:null,rec:null,chunks:[],pre:[],talking:false,quiet:0,started:0,
  floor:0.004,sending:false,muted:false};
var KIOSK_RATE=16000;          // what whisper.cpp and the OpenAI endpoint both want
var KIOSK_FOLLOW_MS=20000;     // after an answer, no name needed for a follow-up
var KIOSK_SILENCE_MS=900;      // a pause this long ends an utterance
var KIOSK_MIN_MS=450;          // shorter is a cough or a door
var KIOSK_MAX_MS=15000;        // longer is cut and sent (hearing.MAX_BYTES holds ~2 min)
var KIOSK_PRE_MS=300;          // kept from before the voice started, so the first word is whole

function kioskFace(){try{return (PLATFORM&&PLATFORM.face)||{}}catch(e){return {}}}
/* Is this the screen the kiosk face is for? */
function kioskWanted(){
  if(location.hash==='#kiosk')return true;
  const f=kioskFace();if(!f.kiosk)return false;
  try{if(sessionStorage.getItem('kiosk.left')==='1')return false}catch(e){}
  return !(typeof remoteClient==='function'&&remoteClient());
}
function kioskApply(){
  const want=kioskWanted();
  if(want&&!KIOSK.on)kioskStart();
  else if(!want&&KIOSK.on)kioskStop();
  else if(KIOSK.on)kioskPaint();
}
function kioskStart(){
  KIOSK.on=true;
  document.body.classList.add('kiosk');
  let hud=document.getElementById('kiosk-hud');
  if(!hud){hud=document.createElement('div');hud.id='kiosk-hud';document.body.appendChild(hud)}
  hud.innerHTML=`<div class="kh-who">${typeof avatarImg==='function'?avatarImg('@agent','kh-face'):''}
      <div class="kh-txt"><b class="kh-name"></b><span class="kh-line"></span></div></div>
    <div class="kh-heard" hidden></div><div class="kh-reply" hidden></div>
    <div class="kh-acts"><button class="kh-mic" aria-label="Microphone"></button>
      <button class="kh-leave" aria-label="Leave the kiosk">Leave</button></div>`;
  hud.querySelector('.kh-mic').onclick=()=>kioskMicTap();
  hud.querySelector('.kh-leave').onclick=()=>kioskLeave();
  // one drawer of the office state at a time (officeSceneAttach): an open Office
  // window would keep the scene empty behind it, and windows are hidden here
  if(typeof OFFICE!=='undefined'&&OFFICE.w&&!OFFICE.w.scene&&typeof closeWin==='function')closeWin(OFFICE.w);
  if(typeof officeSceneStart==='function'){
    if(typeof OFFICE_SCENE!=='undefined'&&OFFICE_SCENE.on)officeSceneResize();else officeSceneStart();
  }
  if(typeof suiSyncStruts==='function')suiSyncStruts();
  kioskPaint();
  kioskListen();
}
function kioskStop(){
  KIOSK.on=false;
  kioskMicOff();
  document.body.classList.remove('kiosk');
  document.body.style.removeProperty('--kiosk-hud');KIOSK.hudH=0;
  const hud=document.getElementById('kiosk-hud');if(hud)hud.remove();
  if(KIOSK.cid&&typeof sinkOff==='function')sinkOff(KIOSK.cid);
  // the office scene stays only if the immersive look asked for it
  if(typeof officeSceneStop==='function'&&!(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&IMMERSIVE.scene==='office'))officeSceneStop();
  else if(typeof officeSceneResize==='function')officeSceneResize();
  if(typeof suiSyncStruts==='function')suiSyncStruts();
}
/* Leave for this session. The setting stays on, so the screen comes back as a kiosk
   after a restart; turning it off for good is Settings → Appearance or `bento face`. */
function kioskLeave(){
  try{sessionStorage.setItem('kiosk.left','1')}catch(e){}
  if(location.hash==='#kiosk')history.replaceState(null,'',location.pathname+location.search);
  kioskStop();
}
function kioskSay(line,phase){KIOSK.line=line||'';if(phase)KIOSK.phase=phase;kioskPaint()}
function kioskPaint(){
  const hud=document.getElementById('kiosk-hud');if(!hud)return;
  const name=agentName(),f=kioskFace(),hear=f.hear||{};
  hud.querySelector('.kh-name').textContent=name;
  const waiting=KIOSK.phase==='listening'?(kioskFollowing()?'Listening. Go ahead.'
      :(f.wake==='always'?'Listening.':`Say “${name}” and what you need.`)):'';
  hud.querySelector('.kh-line').textContent=KIOSK.line||waiting;
  const h=hud.querySelector('.kh-heard'),r=hud.querySelector('.kh-reply');
  h.hidden=!KIOSK.heard;h.textContent=KIOSK.heard?'“'+KIOSK.heard+'”':'';
  r.hidden=!KIOSK.reply;r.textContent=KIOSK.reply.slice(-600);
  const mic=hud.querySelector('.kh-mic');
  const can=!!hear.engine;
  mic.hidden=!can;
  mic.className='kh-mic'+(KIOSK.muted?' off':'')+(KIOSK.talking?' live':'');
  mic.textContent=KIOSK.muted?'Mic off':(KIOSK.talking?'Hearing you':'Mic on');
  hud.dataset.phase=KIOSK.phase||'';
  // the office ends where this band begins: measured, because the answer grows it
  const band=Math.ceil(hud.getBoundingClientRect().height)+24;
  if(KIOSK.hudH!==band){KIOSK.hudH=band;document.body.style.setProperty('--kiosk-hud',band+'px');
    if(typeof officeSceneResize==='function')officeSceneResize()}
}
function kioskFollowing(){return KIOSK.follow&&Date.now()<KIOSK.follow}

/* ---------------- hearing ---------------- */
async function kioskListen(){
  if(!KIOSK.on||KIOSK.muted)return;
  const hear=kioskFace().hear||{};
  if(!hear.engine){kioskSay(hear.line||'Nothing on this machine can understand speech yet.','deaf');return}
  if(hear.engine==='browser')return kioskBrowserListen();
  if(KIOSK.stream){kioskSay('','listening');return}
  if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){
    kioskSay('This browser cannot use a microphone.','deaf');return}
  try{
    KIOSK.stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
  }catch(e){kioskSay('The microphone was not allowed. Allow it for this page, then tap Mic on.','deaf');return}
  const AC=window.AudioContext||window.webkitAudioContext;
  KIOSK.ctx=new AC();
  KIOSK.src=KIOSK.ctx.createMediaStreamSource(KIOSK.stream);
  // ScriptProcessor rather than an AudioWorklet: a worklet is a module file of its own,
  // and the page is one bundle. 4096 frames is ~90 ms at 44.1 kHz, plenty for a pause.
  KIOSK.node=KIOSK.ctx.createScriptProcessor(4096,1,1);
  KIOSK.node.onaudioprocess=e=>kioskFrame(e.inputBuffer.getChannelData(0));
  KIOSK.src.connect(KIOSK.node);KIOSK.node.connect(KIOSK.ctx.destination);
  if(KIOSK.ctx.state==='suspended'){
    // a page may not start audio by itself until somebody touched it
    kioskSay('Tap anywhere to start listening.','asleep');
    const wake=()=>{document.removeEventListener('pointerdown',wake,true);
      KIOSK.ctx&&KIOSK.ctx.resume().then(()=>kioskSay('','listening'))};
    document.addEventListener('pointerdown',wake,true);
    return;
  }
  kioskSay('','listening');
}
function kioskMicOff(){
  try{KIOSK.node&&KIOSK.node.disconnect();KIOSK.src&&KIOSK.src.disconnect()}catch(e){}
  try{KIOSK.stream&&KIOSK.stream.getTracks().forEach(t=>t.stop())}catch(e){}
  try{KIOSK.ctx&&KIOSK.ctx.close()}catch(e){}
  try{KIOSK.rec&&KIOSK.rec.abort()}catch(e){}
  KIOSK.stream=KIOSK.ctx=KIOSK.src=KIOSK.node=KIOSK.rec=null;KIOSK.chunks=[];KIOSK.pre=[];KIOSK.talking=false;
}
function kioskMicTap(){
  KIOSK.muted=!KIOSK.muted;
  if(KIOSK.muted){kioskMicOff();kioskSay('The microphone is off.','muted')}
  else{KIOSK.line='';kioskListen()}
  kioskPaint();
}
/* One frame of audio: a voice starts when the level rises well over the room's own
   noise, and ends after a pause. Nothing is kept while the agent is speaking, so it
   never answers itself. */
function kioskFrame(data){
  if(!KIOSK.on||KIOSK.muted||KIOSK.speaking||KIOSK.sending)return;
  let sum=0;for(let i=0;i<data.length;i++)sum+=data[i]*data[i];
  const rms=Math.sqrt(sum/data.length),now=performance.now();
  const frame=new Float32Array(data);
  const on=rms>Math.max(0.012,KIOSK.floor*3.2);
  if(!KIOSK.talking){
    KIOSK.floor=KIOSK.floor*0.95+rms*0.05;
    KIOSK.pre.push(frame);
    const keep=Math.ceil(KIOSK_PRE_MS/1000*KIOSK.ctx.sampleRate/data.length);
    while(KIOSK.pre.length>keep)KIOSK.pre.shift();
    if(on){KIOSK.talking=true;KIOSK.started=now;KIOSK.quiet=0;KIOSK.chunks=KIOSK.pre.slice();KIOSK.pre=[];kioskPaint()}
    return;
  }
  KIOSK.chunks.push(frame);
  KIOSK.quiet=on?0:(KIOSK.quiet||now);
  const long=now-KIOSK.started;
  if((KIOSK.quiet&&now-KIOSK.quiet>KIOSK_SILENCE_MS)||long>KIOSK_MAX_MS){
    const chunks=KIOSK.chunks;KIOSK.chunks=[];KIOSK.talking=false;kioskPaint();
    if(long-(KIOSK.quiet?now-KIOSK.quiet:0)<KIOSK_MIN_MS)return;
    kioskSend(kioskWav(chunks,KIOSK.ctx.sampleRate));
  }
}
/* Float frames at the device's rate → 16 kHz mono 16-bit WAV. */
function kioskWav(chunks,rate){
  let n=0;chunks.forEach(c=>n+=c.length);
  const all=new Float32Array(n);let o=0;chunks.forEach(c=>{all.set(c,o);o+=c.length});
  const step=rate/KIOSK_RATE,len=Math.floor(n/step),pcm=new Int16Array(len);
  for(let i=0;i<len;i++){
    const a=Math.floor(i*step),b=Math.min(n,Math.floor((i+1)*step));
    let s=0;for(let j=a;j<b;j++)s+=all[j];
    const v=Math.max(-1,Math.min(1,s/Math.max(1,b-a)));pcm[i]=v<0?v*0x8000:v*0x7fff;
  }
  const buf=new ArrayBuffer(44+pcm.length*2),dv=new DataView(buf);
  const str=(p,s)=>{for(let i=0;i<s.length;i++)dv.setUint8(p+i,s.charCodeAt(i))};
  str(0,'RIFF');dv.setUint32(4,36+pcm.length*2,true);str(8,'WAVE');str(12,'fmt ');
  dv.setUint32(16,16,true);dv.setUint16(20,1,true);dv.setUint16(22,1,true);
  dv.setUint32(24,KIOSK_RATE,true);dv.setUint32(28,KIOSK_RATE*2,true);dv.setUint16(32,2,true);dv.setUint16(34,16,true);
  str(36,'data');dv.setUint32(40,pcm.length*2,true);
  new Int16Array(buf,44).set(pcm);
  return new Blob([buf],{type:'audio/wav'});
}
async function kioskSend(wav){
  KIOSK.sending=true;kioskSay('Understanding…','hearing');
  let text='';
  try{
    const lang=String((typeof VOICE!=='undefined'&&VOICE.lang)||'').slice(0,5);
    const r=await fetch('/api/speech/hear?lang='+encodeURIComponent(lang),
      {method:'POST',headers:{'Content-Type':'audio/wav'},body:wav});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){KIOSK.sending=false;kioskSay(d.error||('could not understand that ('+r.status+')'),'listening');return}
    text=String(d.text||'').trim();
  }catch(e){KIOSK.sending=false;kioskSay('The machine could not be reached.','listening');return}
  KIOSK.sending=false;
  kioskHeard(text);
}
/* The browser's own recogniser, for a machine whose browser has one that works. */
function kioskBrowserListen(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){kioskSay('This browser has no speech recogniser. Choose whisper.cpp or OpenAI in Settings.','deaf');return}
  const rec=new SR();KIOSK.rec=rec;
  rec.lang=(typeof VOICE!=='undefined'&&VOICE.lang)||'en-IN';rec.continuous=false;rec.interimResults=false;
  rec.onresult=e=>{const t=[...e.results].map(r=>r[0].transcript).join(' ');kioskHeard(t)};
  rec.onerror=e=>{if(e.error==='network'||e.error==='not-allowed')
    kioskSay(e.error==='network'?'This browser cannot reach its speech service. Choose whisper.cpp or OpenAI in Settings.'
      :'The microphone was not allowed.','deaf')};
  rec.onend=()=>{KIOSK.rec=null;if(KIOSK.on&&!KIOSK.muted&&!KIOSK.speaking&&KIOSK.phase!=='deaf')setTimeout(kioskListen,400)};
  try{rec.start();kioskSay('','listening')}catch(e){}
}

/* ---------------- what was said ---------------- */
/* The words after the agent's name, or '' when the name was not said. "Hey Aria,
   what's on today" → "what's on today". Whole words, so "Ariadne" is not "Aria". */
function kioskAddressed(text,name){
  const norm=s=>String(s).toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g,'');
  const t=norm(text),n=norm(name).trim();if(!n)return null;
  const re=new RegExp('(^|[^\\p{L}\\p{N}])'+n.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(?=$|[^\\p{L}\\p{N}])','u');
  const m=re.exec(t);if(!m)return null;
  return String(text).slice(m.index+m[0].length).replace(/^[\s,.:;!?-]+/,'').trim();
}
function kioskHeard(text){
  text=String(text||'').trim();
  if(!text){kioskSay('','listening');return}
  const f=kioskFace(),name=agentName();
  let ask=text;
  if(f.wake!=='always'&&!kioskFollowing()){
    const after=kioskAddressed(text,name);
    if(after===null){kioskSay('','listening');return}         // not for us: nothing is kept
    if(!after){KIOSK.heard=text;KIOSK.follow=Date.now()+KIOSK_FOLLOW_MS;
      kioskSpeak('Yes?');return}
    ask=after;
  }
  KIOSK.heard=text;KIOSK.reply='';
  kioskAsk(ask);
}
async function kioskThread(){
  if(KIOSK.cid)return KIOSK.cid;
  const day=new Date().toISOString().slice(0,10);
  try{const s=JSON.parse(localStorage.getItem('kiosk.thread')||'{}');if(s.day===day&&s.cid)KIOSK.cid=s.cid}catch(e){}
  if(!KIOSK.cid){
    try{
      const d=await (await fetch('/api/conversations',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({origin:'kiosk',title:'At the screen · '+day,surface:'gui'})})).json();
      KIOSK.cid=d.id||'';
      try{localStorage.setItem('kiosk.thread',JSON.stringify({day,cid:KIOSK.cid}))}catch(e){}
    }catch(e){}
  }
  return KIOSK.cid;
}
async function kioskAsk(text){
  if(typeof ws==='undefined'||!ws||ws.readyState!==1){kioskSay('Not connected to the machine.','listening');return}
  const cid=await kioskThread();
  if(!cid){kioskSay('Could not start a conversation.','listening');return}
  KIOSK.busy=true;kioskSay(agentName()+' is working…','working');
  sinkOn(cid,{
    delta:(t,all)=>{KIOSK.reply=all||((KIOSK.reply||'')+t);kioskPaint()},
    error:ev=>{KIOSK.busy=false;KIOSK.reply='';kioskSay(String(ev.message||'something went wrong'),'listening')},
    end:()=>{KIOSK.busy=false;const said=KIOSK.reply;
      if(said.trim())kioskSpeak(said);else kioskSay('','listening')},
  });
  if(typeof voiceAddress==='function')text=voiceAddress(text);
  ws.send(JSON.stringify({type:'chat',text,conversation_id:cid,model:''}));
  if(typeof setRunning==='function')setRunning(true);
}
/* Spoken through the one door every voice uses (speakAs), with the mic deaf until it
   is finished, then a short window where no name is needed. */
function kioskSpeak(text){
  const clean=String(text||'').replace(/```[\s\S]*?```/g,' code block. ').replace(/[*_#`>|]/g,'').slice(0,900);
  KIOSK.speaking=true;KIOSK.chunks=[];KIOSK.talking=false;
  kioskSay(agentName()+' is speaking…','speaking');
  const done=()=>{KIOSK.speaking=false;KIOSK.follow=Date.now()+KIOSK_FOLLOW_MS;kioskSay('','listening');
    if(kioskFace().hear&&kioskFace().hear.engine==='browser'&&!KIOSK.rec)kioskListen()};
  if(typeof speakAs==='function')speakAs('@agent',clean,done);else done();
}

/* ---------------- Settings → Appearance → On this screen ---------------- */
/* One agent, the kiosk, what it listens for, and what understands speech, from
   /api/face (admin only on a machine with accounts: a screen is the machine's). */
async function faceSettingsPaint(){
  const box=document.getElementById('s-face');if(!box)return;
  let d;try{d=await apiJSON('/api/face')}catch(e){box.innerHTML=`<div class="prow"><div class="pl"><small>${esc(String(e.message||e))}</small></div></div>`;return}
  const hear=d.hear||{};
  box.innerHTML=[
    pRow('One agent on screen',pSelect('s-face-buddy',[['auto','Auto: in Light mode'],['on','On'],['off','Off']],d.buddy_setting||'auto'),
      {desc:'Draws only your agent in the Office and on the desktop.',
       more:'Specialists still work. Their work lights your agent instead. Auto turns it on in Light mode, which a Raspberry Pi gets by itself.',
       f:'buddy one agent single light mode raspberry pi office crew'}),
    pRow('Kiosk',pSwitch('s-face-kiosk',!!d.kiosk),
      {desc:'This machine’s own screen shows the Office and listens.',
       more:'Only the screen plugged into this machine. A phone or another browser keeps the desktop. Add #kiosk to the address to try it anywhere.',
       f:'kiosk mic microphone always listening screen office raspberry pi wake word'}),
    pRow('The kiosk listens for',pSelect('s-face-wake',[['name','Your agent’s name'],['always','Everything it hears']],d.wake||'name'),
      {desc:'With a name, anything else said in the room is ignored.',f:'wake word name always listening'}),
    pRow('Understanding speech',pSelect('s-face-hear',[['auto','Auto'],['whisper.cpp','whisper.cpp on this machine'],['openai','OpenAI'],['browser','This browser']],hear.setting||'auto'),
      {desc:esc(hear.line||''),
       more:'whisper.cpp keeps your voice on this machine. Install it and a model yourself; Bento uses it when it finds it.',
       f:'speech to text whisper openai transcribe hearing stt'}),
  ].join('');
  const put=async body=>{
    const r=await fetch('/api/face',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json().catch(()=>({}));
    if(!r.ok||j.error){toast(j.error||'could not save that');faceSettingsPaint();return}
    toast('✓ '+(j.description||'saved'));
    try{sessionStorage.removeItem('kiosk.left')}catch(e){}
    if(typeof loadPlatform==='function')await loadPlatform();
    faceSettingsPaint();
  };
  box.querySelector('#s-face-buddy').onchange=e=>put({buddy:e.target.value});
  box.querySelector('#s-face-kiosk').onchange=e=>put({kiosk:e.target.checked});
  box.querySelector('#s-face-wake').onchange=e=>put({wake:e.target.value});
  box.querySelector('#s-face-hear').onchange=e=>put({hear:e.target.value});
}
addEventListener('hashchange',()=>{if(location.hash==='#kiosk')try{sessionStorage.removeItem('kiosk.left')}catch(e){}
  if(typeof kioskApply==='function')kioskApply()});
