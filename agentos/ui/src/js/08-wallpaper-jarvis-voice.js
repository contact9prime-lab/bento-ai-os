/* ================= wallpaper ================= */
function loadWallpaper(){
  const w=$('#wall'),url='/api/wallpaper?t='+Date.now();
  const img=new Image();
  img.onload=()=>{w.style.backgroundImage='url("'+url+'")';w.classList.add('has')};
  img.onerror=()=>{
    // no wallpaper file: the wizard's preset gradient (config-only) if one was
    // chosen, else the built-in mesh fallback from the stylesheet
    const preset=cfg&&cfg.desktop&&cfg.desktop.wallpaper_preset;
    if(preset&&typeof WIZ_WALLS!=='undefined'&&WIZ_WALLS[preset]){
      w.style.backgroundImage=WIZ_WALLS[preset];w.classList.add('has');
    }else{w.style.backgroundImage='';w.classList.remove('has')}
  };
  img.src=url;
}

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
function speak(text){
  if(!VOICE.tts||!text||!window.speechSynthesis)return;
  const clean=text.replace(/```[\s\S]*?```/g,' code block. ').replace(/[*_#`>|]/g,'').slice(0,800);
  const u=new SpeechSynthesisUtterance(clean);
  u.rate=VOICE.rate||1;
  const v=speechSynthesis.getVoices().find(v=>v.name===VOICE.voice);
  if(v)u.voice=v;
  speechSynthesis.cancel();speechSynthesis.speak(u);
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

