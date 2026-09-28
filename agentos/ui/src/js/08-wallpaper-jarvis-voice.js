/* ================= wallpaper =================
   Four sources, most-specific first:
     1. a wallpaper file the user generated or adopted from the host,
     2. a built-in they picked by hand (remembered per-machine),
     3. the wallpaper the current theme ships with — this is what makes picking
        Claymorphism also dress the desktop for it,
     4. the wizard's preset gradient, or the stylesheet's mesh.
   The built-ins are SVG: a few KB each, sharp from a phone to a 4K panel, and
   cheap to rasterise on slow GPUs (no blur filters — gradients only). */
const BUILTIN_WALLS=['nova','bento','clay','liquid','minimal','spatial','immersive','immersive-dawn','immersive-night','immersive-movement','immersive-crew'];
const builtinWallURL=id=>'/assets/wallpapers/'+encodeURIComponent(id)+'.svg';
function pickedWall(){return localStorage.getItem('wallpaper.builtin')||''}
function themeWall(){
  const t=allThemes()[CURRENT_THEME];
  return (t&&t.wall_img&&BUILTIN_WALLS.includes(t.wall_img))?t.wall_img:'';
}
function applyWallImage(url){
  const w=$('#wall');
  if(!w)return;
  if(url){w.style.backgroundImage='url("'+url+'")';w.classList.add('has')}
  else{w.style.backgroundImage='';w.classList.remove('has')}
}
function loadWallpaper(){
  const url='/api/wallpaper?t='+Date.now();
  const img=new Image();
  img.onload=()=>applyWallImage(url);
  img.onerror=()=>{
    // the immersive look ships a wallpaper too, ranked below a theme's own —
    // the theme designed its scene, the look only dresses whatever is there
    const id=pickedWall()||themeWall()||(typeof immersiveWall==='function'?immersiveWall():'');
    if(id)return applyWallImage(builtinWallURL(id));
    const preset=cfg&&cfg.desktop&&cfg.desktop.wallpaper_preset;
    if(preset&&typeof WIZ_WALLS!=='undefined'&&WIZ_WALLS[preset]){
      const w=$('#wall');w.style.backgroundImage=WIZ_WALLS[preset];w.classList.add('has');
    }else applyWallImage('');
  };
  img.src=url;
}
/* Picking a built-in clears any generated wallpaper file, because a file always
   wins — leaving one behind would make the choice look like it did nothing. */
async function setBuiltinWallpaper(id){
  if(!BUILTIN_WALLS.includes(id))return toast('no built-in wallpaper "'+id+'"');
  localStorage.setItem('wallpaper.builtin',id);
  try{await fetch('/api/wallpaper',{method:'DELETE'})}catch(e){}
  loadWallpaper();
}
function clearBuiltinWallpaper(){localStorage.removeItem('wallpaper.builtin');loadWallpaper()}

/* ================= jarvis thinking animation ================= */
let jrRaf=0,jrPulse=0,jrActive=false,jrTimeout=0;
function jarvisOn(autoOffSecs){
  const c=$('#jarvis');c.classList.add('on');jrActive=true;
  if(!jrRaf)jrRaf=requestAnimationFrame(jarvisDraw);
  clearTimeout(jrTimeout);
  if(autoOffSecs)jrTimeout=setTimeout(()=>{if(!running)jarvisOff()},autoOffSecs*1000);
}
function jarvisOff(){jrActive=false;$('#jarvis').classList.remove('on')}
function jarvisDraw(ts){
  const c=$('#jarvis');
  if(!jrActive&&+getComputedStyle(c).opacity===0){jrRaf=0;return}
  const dpr=devicePixelRatio||1,W=c.clientWidth,H=c.clientHeight;
  if(c.width!==W*dpr){c.width=W*dpr}if(c.height!==H*dpr){c.height=H*dpr}
  const x=c.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);x.clearRect(0,0,W,H);
  const t=ts/1000,cx=W/2,cy=H/2,TAU=Math.PI*2;
  jrPulse*=.96;
  const A=.55+.2*Math.sin(t*2.4)+jrPulse*.3;
  // core glow
  const cr=26+5*Math.sin(t*3)+jrPulse*16;
  const g=x.createRadialGradient(cx,cy,0,cx,cy,cr*3);
  g.addColorStop(0,'rgba(94,234,212,'+(.30*A).toFixed(3)+')');
  g.addColorStop(1,'rgba(34,211,238,0)');
  x.fillStyle=g;x.beginPath();x.arc(cx,cy,cr*3,0,TAU);x.fill();
  x.fillStyle='rgba(94,234,212,'+(.85*A).toFixed(3)+')';x.beginPath();x.arc(cx,cy,4,0,TAU);x.fill();
  // segmented rotating rings
  const rings=[{r:60,s:1.1,n:3,w:2.5},{r:95,s:-.7,n:4,w:1.6},{r:135,s:.45,n:5,w:1.2},{r:185,s:-.28,n:3,w:1}];
  rings.forEach((R,i)=>{
    x.lineWidth=R.w;
    x.strokeStyle='rgba('+(i%2?'34,211,238':'94,234,212')+','+(.5*A).toFixed(3)+')';
    for(let k=0;k<R.n;k++){
      const a0=t*R.s+k*TAU/R.n;
      x.beginPath();x.arc(cx,cy,R.r,a0,a0+TAU/R.n*.62);x.stroke();
    }
  });
  // sweeping ticks on the outer ring
  x.strokeStyle='rgba(94,234,212,'+(.35*A).toFixed(3)+')';x.lineWidth=1;
  const head=Math.floor(t*22);
  for(let k=0;k<72;k++){
    if(((k-head)%72+72)%72>=10)continue;
    const a=k/72*TAU;
    x.beginPath();x.moveTo(cx+Math.cos(a)*205,cy+Math.sin(a)*205);
    x.lineTo(cx+Math.cos(a)*213,cy+Math.sin(a)*213);x.stroke();
  }
  // orbiting dots
  x.fillStyle='rgba(34,211,238,'+(.8*A).toFixed(3)+')';
  for(let k=0;k<3;k++){
    const a=t*(.9+k*.35)+k*2.1,r=60+k*38;
    x.beginPath();x.arc(cx+Math.cos(a)*r,cy+Math.sin(a)*r,2.5,0,TAU);x.fill();
  }
  jrRaf=requestAnimationFrame(jarvisDraw);
}

/* ================= voice: TTS + mic ================= */
let VOICE=JSON.parse(localStorage.getItem('voice')||'{"tts":false,"voice":"","rate":1,"lang":"en-IN"}');
function saveVoice(){localStorage.setItem('voice',JSON.stringify(VOICE))}
/* A reply read aloud: your lead, in the engine chosen in Settings → Voice. A new
   reply replaces one still being read. */
function speak(text){
  if(!VOICE.tts||!text)return;
  speechStop();speakAs('@agent',text);
}
let rec=null,recOn=false;
function micToggle(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR)return toast('speech recognition is not available in this browser');
  if(recOn){rec.stop();return}
  rec=new SR();rec.lang=VOICE.lang||'en-IN';rec.interimResults=true;rec.continuous=true;
  const base=input?input.value:'';
  rec.onresult=e=>{
    if(!input)return;
    let fin=base,inter='';
    for(let i=0;i<e.results.length;i++){const r=e.results[i];
      if(r.isFinal)fin=(fin+' '+r[0].transcript).trim();else inter+=r[0].transcript}
    input.value=(fin+' '+inter).trim();input.dispatchEvent(new Event('input'));
  };
  rec.onend=()=>{recOn=false;$('#mic')?.classList.remove('rec')};
  rec.onerror=e=>toast('mic: '+e.error);
  rec.start();recOn=true;$('#mic')?.classList.add('rec');
}
function agentName(){return (cfg&&cfg.agent_name)||'Aria'}

/* ================= a voice per agent =================
   With voice on, or in Jarvis mode, a huddle, a free talk and one agent asking another
   are heard as well as read, and each agent speaks in its own voice: a system voice
   picked from the name (so it stays the same every time), and a pitch of its own for
   the machines that only have one or two voices. Your lead keeps the voice chosen in
   Settings → Voice. Lines are queued by speechSynthesis itself, never cancelled, so a
   room of agents is heard in order and your lead's reply comes after them.
   Faces: GUI and SUI speak through the browser. TUI has no speaker on purpose; the
   same lines are text in `bento team log` and the chat. */
function agentVoice(name){
  const lead=!name||name==='@agent'||name===agentName();
  const lang=String(VOICE.lang||'en').slice(0,2).toLowerCase();
  const all=(window.speechSynthesis&&speechSynthesis.getVoices())||[];
  const vs=all.filter(v=>String(v.lang||'').slice(0,2).toLowerCase()===lang);
  const mine=all.find(v=>v.name===VOICE.voice);
  if(lead)return {voice:mine||null,pitch:1};
  let h=0;for(const c of String(name))h=(h*31+c.charCodeAt(0))>>>0;
  const pool=vs.filter(v=>v!==mine);
  return {voice:pool.length?pool[h%pool.length]:(vs[h%(vs.length||1)]||null),pitch:[.85,1.15,.95,1.25,.75,1.05][h%6]};
}
function voiceClean(text,n){
  return String(text||'').replace(/```[\s\S]*?```/g,' code block. ').replace(/[*_#`>|]/g,'')
    .replace(/(^|\s)@([\w-]+)/g,'$1$2').slice(0,n||600).trim();
}
/* Which engine speaks is the machine's choice (agentos/speech.py): this browser's
   voices, this computer's, or ElevenLabs, OpenAI or Google Cloud. Anything but the
   browser is audio from /api/speech/say, fetched as soon as a line is queued so the
   next one is ready when this one ends, and played strictly in order. A line the
   server cannot say is said by the browser instead, and the reason is said once. */
var SPEECH={engine:'browser',loaded:false,warned:false,gen:0,audio:null,chain:Promise.resolve()};
async function speechLoad(){
  try{const d=await (await fetch('/api/speech')).json();SPEECH.engine=(d.config||{}).engine||'browser'}catch(e){}
  SPEECH.loaded=true;
}
function speechStop(){
  SPEECH.gen++;SPEECH.chain=Promise.resolve();
  try{SPEECH.audio&&SPEECH.audio.pause()}catch(e){}
  try{window.speechSynthesis&&speechSynthesis.cancel()}catch(e){}
}
function speechWho(name){return name&&name!=='@agent'?name:agentName()}
function browserSay(name,clean){
  return new Promise(res=>{
    if(!window.speechSynthesis)return res();
    const u=new SpeechSynthesisUtterance(clean),a=agentVoice(name);
    if(a.voice)u.voice=a.voice;u.pitch=a.pitch;u.rate=VOICE.rate||1;
    u.onstart=()=>{if(JARVIS.on)jarvisSetPhase('speaking',speechWho(name)+' is speaking…')};
    u.onend=u.onerror=()=>res();
    speechSynthesis.speak(u);
  });
}
/* One agent's line, spoken in its voice. `done` runs when it has been said. */
function speakAs(name,text,done){
  const clean=voiceClean(text);
  if(!clean){if(done)done();return}
  if(!SPEECH.loaded){speechLoad().then(()=>speakAs(name,text,done));return}
  if(SPEECH.engine==='browser'){browserSay(name,clean).then(()=>{if(done)done()});return}
  const gen=SPEECH.gen,lead=!name||name==='@agent'||name===agentName();
  const got=fetch('/api/speech/say',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:clean,agent:lead?'':name,lead})})
    .then(async r=>{if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||'the voice engine did not answer');
      return URL.createObjectURL(await r.blob())});
  got.catch(()=>{});
  SPEECH.chain=SPEECH.chain.then(()=>gen!==SPEECH.gen?null:got.then(url=>new Promise(res=>{
      if(gen!==SPEECH.gen){URL.revokeObjectURL(url);return res()}
      const a=new Audio(url);SPEECH.audio=a;a.playbackRate=VOICE.rate||1;
      a.onplay=()=>{if(JARVIS.on)jarvisSetPhase('speaking',speechWho(name)+' is speaking…')};
      a.onended=a.onerror=a.onpause=()=>{URL.revokeObjectURL(url);res()};
      a.play().catch(()=>res());
    })).catch(e=>{
      if(!SPEECH.warned){SPEECH.warned=true;toast('Voice: '+e.message+' Using this browser’s voice instead.')}
      return browserSay(name,clean);
    })).then(()=>{if(done&&gen===SPEECH.gen)done()});
}
/* Speech has no "@". Said out loud, "at researcher, at writer, should we…" comes back as
   words, so the names a spoken request OPENS with become the addresses the chat reads
   ("@researcher @writer should we…", a huddle; "ask writer to…", that agent). Only the
   opening words and only names of agents here, so "look at writer's draft" is left alone. */
var VOICE_AGENTS=null;
async function voiceAgentsLoad(){
  try{const d=await (await fetch('/api/subagents')).json();VOICE_AGENTS=(d.subagents||[]).map(s=>s.name)}
  catch(e){VOICE_AGENTS=VOICE_AGENTS||[]}
}
function voiceAddress(text){
  const names=VOICE_AGENTS||[];if(!names.length)return text;
  let rest=String(text||''),out=[];
  for(;;){
    const m=rest.match(/^\s*(?:at|hey|ask|and|@)?\s*([A-Za-z][\w-]*)[\s,:.]+/i);
    const hit=m&&names.find(n=>n.toLowerCase()===m[1].toLowerCase());
    if(!hit)break;
    out.push('@'+hit);rest=rest.slice(m[0].length);
  }
  return out.length?out.join(' ')+' '+rest.replace(/^\s*to\s+/i,''):text;
}
/* Called by every surface that shows agents talking to each other. Silent unless you
   asked to hear it: voice on, or Jarvis mode, and each agent's own voice switched on. */
function voiceAgentLine(name,text){
  if(!(VOICE.tts||JARVIS.on)||VOICE.agents===false||!name)return;
  speakAs(name,text);
}

