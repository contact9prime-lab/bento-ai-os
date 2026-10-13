/* ---------------- the drama reel: real crew drama as a clip or a strip ----------------
   agentos/drama.py keeps the beats of what the crew actually did (a huddle line, the
   gate refusing an rm -rf, the retry that went through, the work shipped) and
   /api/drama tells the latest episode as four acts. This file turns that story into
   something a person can share:

   - a 15 second CLIP, 9:16 or square, drawn on a canvas and recorded with the browser's
     own MediaRecorder (canvas.captureStream + the agents' voices through a WebAudio
     MediaStreamDestination). Voices are the machine's speech engine saying the agents'
     own words; with the browser's voice there is nothing to record, so the clip has
     sound effects only and the window says so.
   - the scene, RECORDED: 15 seconds of whatever desktop scene is showing (the World,
     Office HQ, the Mind), cropped to the format, with the same footer. The window steps
     aside while it records, because a covered scene stops drawing.
   - the 4-panel STRIP, painted by the server (comic.manga) so the terminal and the
     page share one picture.

   Every clip and strip carries the bento-ai-os footer. Nothing is sent anywhere: the
   person downloads it or keeps it in Files (clips/).
   Faces: GUI and SUI are this window (a browser without MediaRecorder gets the strip
   and a sentence saying why there is no clip). TUI: `bento drama` and
   `bento drama strip FILE.png`; a terminal cannot record a clip, and says so. */
var DRAMA={data:null,fmt:'vertical',voices:true,busy:false,blob:null,url:'',kind:'',seen:'',w:null,note:''};
var DRAMA_DUR=15;
var DRAMA_FMT={vertical:[720,1280],square:[1080,1080]};
var DRAMA_ACT_BG={argue:['#312e81','#1e1b4b'],trouble:['#7f1d1d','#3b0a0a'],fix:['#78350f','#3a1a06'],ship:['#065f46','#022c22']};
var DRAMA_TITLE={argue:'The argument',trouble:'The tantrum',fix:'The fix',ship:'Shipped'};

/* Can this browser make a clip at all? A sentence when not, never a dead button. */
function dramaCan(){
  try{
    if(typeof MediaRecorder==='undefined')return 'This browser cannot record video. The 4-panel strip still works.';
    if(!document.createElement('canvas').captureStream)return 'This browser cannot record a canvas. The 4-panel strip still works.';
  }catch(e){return 'This browser cannot record video.'}
  return '';
}
function dramaMime(){
  const want=['video/mp4;codecs=avc1.42E01E,mp4a.40.2','video/mp4','video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm'];
  for(const t of want){try{if(MediaRecorder.isTypeSupported(t))return t}catch(e){}}
  return '';
}
async function dramaLoad(){
  DRAMA.data=await apiJSON('/api/drama');
  return DRAMA.data;
}

/* ---- the window ---- */
function renderDrama(body,w){
  DRAMA.w=w;
  const pb=panelShell(body,{title:'Drama reel',sub:'',actions:
    `<button class="endbtn" id="dr-reload" title="Read the latest episode">Refresh</button>`});
  pb.innerHTML='<div class="mut" style="padding:14px">reading what your crew did…</div>';
  body.querySelector('#dr-reload').onclick=()=>renderDrama(body,w);
  dramaLoad().then(()=>dramaPaint(pb)).catch(e=>{pb.innerHTML=emptyBox('Could not read the drama',esc(e.message))});
}
function dramaPanelHTML(p){
  const face=(typeof avatarImg==='function'&&avatarImg(p.who,'dr-av'))||'';
  const body=p.says?`<div class="dr-says">“${esc(p.says)}”</div>`
    :p.command?`<div class="dr-cmd"><code>${p.shell?'$ ':''}${esc(p.command)}</code>${p.stamp?`<b class="dr-stamp ${p.kind}">${esc(p.stamp)}</b>`:''}
      ${p.reason?`<div class="dr-why">${esc(p.reason)}</div>`:''}</div>`:'';
  return `<div class="dr-act ${esc(p.act)}"><div class="dr-cap">${esc(p.title)}</div>
    <div class="dr-who">${face}<b>${esc(p.name)}</b>${p.to_name?` <span class="mut">to ${esc(p.to_name)}</span>`:''}</div>${body}</div>`;
}
function dramaPaint(pb){
  const d=DRAMA.data||{},st=d.story||{panels:[]};
  const sub=DRAMA.w&&DRAMA.w.el.querySelector('.ps');if(sub)sub.textContent=st.title||'';
  if(!st.panels.length){
    pb.innerHTML=emptyBox('No drama yet',
      'Start a huddle with two agents (<code>@a @b what should we do?</code>) or give your crew real work. '
      +'When the gate refuses something and they try again, the story writes itself.')
      +dramaSceneRow();
    dramaWire(pb);return;
  }
  const can=dramaCan(),voiceNote=d.speech==='browser'
    ?'Voices need a voice engine under Settings → Voice. With the browser’s voice the clip has sound effects only.':'';
  const missing=(st.missing||[]).map(a=>DRAMA_TITLE[a].toLowerCase());
  pb.innerHTML=`<div class="dr-wrap">
    <div class="dr-title">${esc(st.title)}${pInfoSafe('Made from what really happened: each panel is one event your crew went through, in their own words. Nothing is shared until you share it.')}</div>
    <div class="dr-acts">${st.panels.map(dramaPanelHTML).join('')}</div>
    ${missing.length?`<div class="mut dr-missing">Not yet: ${esc(missing.join(', '))}. The story fills in as it happens.</div>`:''}
    <div class="dr-ctl">
      <span class="seg" id="dr-fmt">${[['vertical','9:16 clip'],['square','Square clip'],['strip','4-panel strip']].map(([k,l])=>
        `<button data-f="${k}" class="${DRAMA.fmt===k?'on':''}">${l}</button>`).join('')}</span>
      <label class="dr-voice"><input type="checkbox" id="dr-voices"${DRAMA.voices?' checked':''}> Voices</label>
    </div>
    ${voiceNote&&DRAMA.fmt!=='strip'?`<div class="mut dr-note">${esc(voiceNote)}</div>`:''}
    <div class="dr-go">
      ${DRAMA.fmt==='strip'
        ?`<button class="endbtn primary" id="dr-strip">Make the strip</button>`
        :`<button class="endbtn primary" id="dr-rec"${can?' disabled':''}>● Record the clip (15 s)</button>`}
    </div>
    ${can&&DRAMA.fmt!=='strip'?`<div class="mut dr-note">${esc(can)}</div>`:''}
    <div class="dr-out" id="dr-out">${dramaOutHTML()}</div>
    ${dramaSceneRow()}
  </div>`;
  dramaWire(pb);
}
function dramaSceneRow(){
  const can=dramaCan(),cv=dramaSceneCanvas();
  const why=can||(cv?'':'Switch the desktop to a scene first (the World, Office HQ or the Mind) and close the windows over it.');
  return `<div class="dr-scene"><div><b>Record the scene</b><div class="mut">15 seconds of the desktop scene as it plays, with the footer. This window steps aside while it records.</div></div>
    <button class="endbtn" id="dr-scene"${why?' disabled':''}>Record the scene</button>${why?`<div class="mut dr-note">${esc(why)}</div>`:''}</div>`;
}
function dramaOutHTML(){
  if(!DRAMA.url)return DRAMA.note?`<div class="mut">${esc(DRAMA.note)}</div>`:'';
  const media=DRAMA.kind==='image'
    ?`<img src="${DRAMA.url}" alt="the strip">`
    :`<video src="${DRAMA.url}" controls playsinline loop></video>`;
  return `${media}<div class="dr-acts-row">
    <a class="endbtn" id="dr-dl" href="${DRAMA.url}" download="${dramaFileName()}">Download</a>
    <button class="endbtn" id="dr-keep">Keep in Files</button></div>
    ${DRAMA.note?`<div class="mut dr-note">${esc(DRAMA.note)}</div>`:''}`;
}
function dramaFileName(){
  const ext=DRAMA.kind==='image'?'png':((DRAMA.blob&&DRAMA.blob.type)||'').indexOf('mp4')>=0?'mp4':'webm';
  return 'bento-drama.'+ext;
}
function dramaWire(pb){
  const q=s=>pb.querySelector(s);
  pb.querySelectorAll('#dr-fmt [data-f]').forEach(b=>b.onclick=()=>{DRAMA.fmt=b.dataset.f;dramaPaint(pb)});
  if(q('#dr-voices'))q('#dr-voices').onchange=e=>DRAMA.voices=e.target.checked;
  if(q('#dr-rec'))q('#dr-rec').onclick=()=>dramaRecord(pb);
  if(q('#dr-strip'))q('#dr-strip').onclick=()=>dramaStrip(pb);
  if(q('#dr-scene'))q('#dr-scene').onclick=()=>dramaSceneRecord(pb);
  if(q('#dr-keep'))q('#dr-keep').onclick=()=>dramaKeep(q('#dr-keep'));
}
function dramaSet(blob,kind,note){
  if(DRAMA.url)URL.revokeObjectURL(DRAMA.url);
  DRAMA.blob=blob;DRAMA.kind=kind;DRAMA.note=note||'';
  DRAMA.url=blob?URL.createObjectURL(blob):'';
}
async function dramaKeep(btn){
  if(!DRAMA.blob)return;
  btn.disabled=true;
  try{
    const d=await apiJSON('/api/drama/clip',{method:'POST',headers:{'Content-Type':DRAMA.blob.type.split(';')[0]||'video/webm'},body:DRAMA.blob});
    toast('Kept in Files as '+d.name,{kind:'ok'});btn.textContent='Kept ✓';
  }catch(e){toast('Could not keep it: '+e.message,{kind:'err'});btn.disabled=false}
}
async function dramaStrip(pb){
  try{
    const r=await fetch('/api/drama/strip.png',{cache:'no-store'});
    if(!r.ok)throw new Error('the server could not paint the strip');
    dramaSet(await r.blob(),'image');
  }catch(e){dramaSet(null,'',e.message)}
  const o=pb.querySelector('#dr-out');if(o){o.innerHTML=dramaOutHTML();dramaWire(pb)}
}

/* ---- the clip: four acts on a virtual clock ---- */
function dramaPlan(st){
  const ps=(st.clip||st.panels).slice(0,5),a=1.0,b=DRAMA_DUR-1.2,len=(b-a)/Math.max(1,ps.length);
  return ps.map((p,i)=>({p,a:a+i*len,b:a+(i+1)*len}));
}
function dramaFaces(st){
  const keys=[...new Set((st.clip||st.panels).flatMap(p=>[p.who,p.to].filter(Boolean)))];
  return Promise.all(keys.map(k=>new Promise(res=>{
    const im=new Image();im.onload=()=>res([k,im]);im.onerror=()=>res([k,null]);
    im.src=avatarSrc(k,{sheet:1});
  }))).then(rows=>Object.fromEntries(rows));
}
function dramaWrap(ctx,text,maxW){
  const words=String(text||'').split(/\s+/),lines=[];let cur='';
  for(const w of words){const t=cur?cur+' '+w:w;if(ctx.measureText(t).width>maxW&&cur){lines.push(cur);cur=w}else cur=t}
  if(cur)lines.push(cur);
  return lines;
}
function dramaRound(ctx,x,y,w,h,r){
  ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);
  ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();
}
/* One frame of the clip at time t (seconds). Pure drawing: the same t always gives the
   same picture, which is what lets the reel be checked frame by frame. */
function dramaFrame(ctx,W,H,t,st,plan,faces){
  const u=Math.min(W,H)/720,cur=plan.find(x=>t>=x.a&&t<x.b);
  const act=cur?cur.p.act:(t<1?'argue':'ship');
  const bg=DRAMA_ACT_BG[act]||DRAMA_ACT_BG.argue;
  const g=ctx.createLinearGradient(0,0,0,H);g.addColorStop(0,bg[0]);g.addColorStop(1,bg[1]);
  ctx.fillStyle=g;ctx.fillRect(0,0,W,H);
  // halftone, the comic printer's dot
  ctx.fillStyle='rgba(255,255,255,.06)';
  for(let y=0,j=0;y<H;y+=18*u,j++)for(let x=(j%2)*9*u;x<W;x+=18*u){ctx.beginPath();ctx.arc(x,y,2.2*u,0,6.283);ctx.fill()}
  const foot=86*u;
  if(t<1.0||!cur){dramaCard(ctx,W,H,u,t,st,foot);dramaFooter(ctx,W,H,u,foot);return}
  const p=cur.p,k=(t-cur.a)/(cur.b-cur.a);
  // the narrator's caption: words nobody in the picture said
  ctx.font=`800 ${34*u}px Geist,Inter,system-ui,sans-serif`;
  const cap=(p.title||DRAMA_TITLE[p.act]).toUpperCase(),cw=ctx.measureText(cap).width+36*u;
  ctx.fillStyle='#fde68a';ctx.fillRect(28*u,40*u,cw,58*u);
  ctx.strokeStyle='#111';ctx.lineWidth=4*u;ctx.strokeRect(28*u,40*u,cw,58*u);
  ctx.fillStyle='#111';ctx.fillText(cap,46*u,81*u);
  // the person, from the one painter's sheet (four frames of 16x26)
  const im=faces[p.who],s=Math.round((H>W?13:10)*u),pw=16*s,ph=26*s;
  let px=W*0.5-pw/2,py=H-foot-ph-40*u,frame=0;
  if(p.mood==='tantrum'){px+=Math.sin(t*48)*10*u;frame=Math.floor(t*8)%2?2:0}
  else if(p.mood==='cheer'){py-=Math.abs(Math.sin(t*7))*40*u;frame=2+Math.floor(t*6)%2}
  else if(p.mood==='pace'){px+=Math.sin(t*2.2)*60*u;frame=Math.floor(t*3)%2?2:0}
  else frame=(Math.floor(t*10)%23===0)?1:0;
  if(p.to){px-=W*0.18}
  if(im){ctx.imageSmoothingEnabled=false;ctx.drawImage(im,frame*16,0,16,26,px,py,pw,ph)}
  dramaTag(ctx,px+pw/2,py+ph+30*u,p.name,u);
  if(p.to&&faces[p.to]){
    const qx=W*0.5+W*0.16;ctx.drawImage(faces[p.to],0,0,16,26,qx,py,pw,ph);dramaTag(ctx,qx+pw/2,py+ph+30*u,p.to_name||p.to,u);
  }
  if(p.mood==='tantrum'){                         // the marks over a head, drawn, never words
    ctx.strokeStyle='#ff4d4d';ctx.lineWidth=6*u;
    for(let i=0;i<3;i++){const bx=px+pw*0.15+i*pw*0.3,by=py-30*u-Math.sin(t*20+i)*6*u;
      ctx.beginPath();ctx.moveTo(bx,by);for(let z=1;z<5;z++)ctx.lineTo(bx+z*8*u,by+(z%2?-10:0)*u);ctx.stroke()}
  }
  const top=128*u,maxW=W-80*u;
  if(p.says){
    ctx.font=`600 ${(W>H?34:38)*u}px Geist,Inter,system-ui,sans-serif`;
    const full=`“${p.says}”`,shown=full.slice(0,Math.ceil(full.length*Math.min(1,k/0.55)));
    const lines=dramaWrap(ctx,shown,maxW-48*u).slice(0,6),lh=48*u,bh=lines.length*lh+40*u;
    ctx.fillStyle='#fff';dramaRound(ctx,40*u,top,maxW,bh,26*u);ctx.fill();
    ctx.strokeStyle='#111';ctx.lineWidth=4*u;ctx.stroke();
    ctx.beginPath();ctx.moveTo(px+pw*0.5-18*u,top+bh-2*u);ctx.lineTo(px+pw*0.5,Math.min(py-14*u,top+bh+60*u));
    ctx.lineTo(px+pw*0.5+20*u,top+bh-2*u);ctx.closePath();ctx.fillStyle='#fff';ctx.fill();ctx.stroke();
    ctx.fillStyle='#fff';ctx.fillRect(px+pw*0.5-16*u,top+bh-6*u,34*u,6*u);
    ctx.fillStyle='#111';lines.forEach((ln,i)=>ctx.fillText(ln,64*u,top+44*u+i*lh));
    if(p.model){ctx.font=`500 ${20*u}px Geist,Inter,system-ui,sans-serif`;ctx.fillStyle='rgba(255,255,255,.75)';
      ctx.fillText(p.name+' · '+p.model,44*u,top+bh+30*u)}
  }else if(p.command){
    ctx.font=`600 ${30*u}px ui-monospace,Menlo,monospace`;
    const lines=dramaWrap(ctx,(p.shell?'$ ':'')+p.command,maxW-48*u).slice(0,3),lh=42*u,bh=lines.length*lh+36*u;
    ctx.fillStyle='rgba(10,12,20,.92)';dramaRound(ctx,40*u,top,maxW,bh,18*u);ctx.fill();
    ctx.strokeStyle='rgba(255,255,255,.25)';ctx.lineWidth=2*u;ctx.stroke();
    ctx.fillStyle='#86efac';lines.forEach((ln,i)=>ctx.fillText(ln,62*u,top+46*u+i*lh));
    if(p.stamp&&k>0.3){                            // the stamp slams in
      const sk=Math.min(1,(k-0.3)/0.08),sc=1+(1-sk)*1.4;
      ctx.save();ctx.translate(W/2,top+bh+80*u);ctx.rotate(-0.12);ctx.scale(sc,sc);ctx.globalAlpha=sk;
      ctx.font=`900 ${64*u}px Geist,Inter,system-ui,sans-serif`;
      const sw=ctx.measureText(p.stamp).width+40*u;
      ctx.fillStyle=p.kind==='declined'?'#475569':'#dc2626';ctx.fillRect(-sw/2,-50*u,sw,84*u);
      ctx.strokeStyle='#fff';ctx.lineWidth=5*u;ctx.strokeRect(-sw/2+8*u,-42*u,sw-16*u,68*u);
      ctx.fillStyle='#fff';ctx.fillText(p.stamp,-sw/2+20*u,14*u);ctx.restore();
      if(p.reason&&k>0.45){ctx.font=`500 ${24*u}px Geist,Inter,system-ui,sans-serif`;ctx.fillStyle='rgba(255,255,255,.9)';
        dramaWrap(ctx,p.reason,maxW).slice(0,2).forEach((ln,i)=>ctx.fillText(ln,44*u,top+bh+170*u+i*32*u))}
    }
  }
  if(p.act==='ship'){                              // confetti, from a fixed seed
    for(let i=0;i<60;i++){const r=(i*9301+49297)%233280/233280,x=(r*W+t*40*(i%3+1))%W,y=((i*37)%H+t*(160+i*3)*u)%(H-foot);
      ctx.fillStyle=['#fde047','#34d399','#60a5fa','#f472b6'][i%4];ctx.fillRect(x,y,10*u,16*u)}
  }
  dramaFooter(ctx,W,H,u,foot);
}
function dramaTag(ctx,cx,y,name,u){
  ctx.font=`700 ${26*u}px Geist,Inter,system-ui,sans-serif`;
  const w=ctx.measureText(name).width+28*u;
  ctx.fillStyle='#fff';dramaRound(ctx,cx-w/2,y-28*u,w,40*u,20*u);ctx.fill();
  ctx.fillStyle='#111';ctx.fillText(name,cx-w/2+14*u,y+2*u);
}
function dramaCard(ctx,W,H,u,t,st,foot){
  const a=Math.min(1,t/0.35);
  ctx.globalAlpha=a;ctx.fillStyle='#fff';
  ctx.font=`900 ${58*u}px Geist,Inter,system-ui,sans-serif`;
  dramaWrap(ctx,st.title||'',W-90*u).slice(0,3).forEach((ln,i)=>ctx.fillText(ln,46*u,H*0.42+i*66*u));
  ctx.font=`500 ${28*u}px Geist,Inter,system-ui,sans-serif`;ctx.fillStyle='rgba(255,255,255,.8)';
  ctx.fillText(t<1?'a true story from my AI crew':'recorded on my own machine',46*u,H*0.42-60*u);
  ctx.globalAlpha=1;
}
function dramaFooter(ctx,W,H,u,foot){
  ctx.fillStyle='rgba(8,8,16,.92)';ctx.fillRect(0,H-foot,W,foot);
  ctx.fillStyle='#fff';ctx.font=`800 ${34*u}px Geist,Inter,system-ui,sans-serif`;
  const wm='bento-ai-os',ww=ctx.measureText(wm).width;
  ctx.fillText(wm,W-ww-30*u,H-foot/2+12*u);
  ctx.font=`500 ${20*u}px Geist,Inter,system-ui,sans-serif`;ctx.fillStyle='rgba(255,255,255,.6)';
  ctx.fillText('real agents · real events',30*u,H-foot/2+8*u);
}

/* The agents' own words in their own voices, plus a few sound effects, mixed into one
   track the recorder can take. The words are asked of the machine's speech engine
   (/api/speech/say), decoded, and scheduled at their act; the browser's voice cannot be
   recorded, so with it the clip keeps only the effects. */
async function dramaVoices(st,plan){
  const AC=window.AudioContext||window.webkitAudioContext;
  if(!AC)return null;
  const ctx=new AC(),dest=ctx.createMediaStreamDestination(),mix=ctx.createGain();
  mix.gain.value=0.9;mix.connect(dest);mix.connect(ctx.destination);
  const lines=[];
  if(DRAMA.voices&&(DRAMA.data||{}).speech!=='browser'){
    await Promise.all(plan.map(async x=>{
      const words=(x.p.says||'').split(/(?<=[.!?])\s/)[0].slice(0,160);
      if(!words)return;
      try{
        const lead=x.p.who==='@agent';
        const r=await fetch('/api/speech/say',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({text:words,agent:lead?'':x.p.who,lead})});
        if(!r.ok)return;
        lines.push({at:x.a+0.25,buf:await ctx.decodeAudioData(await r.arrayBuffer())});
      }catch(e){}
    }));
  }
  const fx=(at,kind)=>({at,kind});
  const effects=[fx(0.05,'whoosh')].concat(plan.map(x=>x.p.act==='trouble'?fx(x.a+(x.b-x.a)*0.3,'buzz')
    :x.p.act==='fix'?fx(x.a+0.2,'keys'):x.p.act==='ship'?fx(x.a+0.15,'chime'):fx(x.a,'whoosh')));
  return {dest,ctx,voiced:lines.length,start(){
    const t0=ctx.currentTime+0.05;
    lines.forEach(l=>{const s=ctx.createBufferSource();s.buffer=l.buf;s.connect(mix);s.start(t0+l.at)});
    effects.forEach(e=>dramaFx(ctx,mix,t0+e.at,e.kind));
  },close(){try{ctx.close()}catch(e){}}};
}
function dramaFx(ctx,out,at,kind){
  const tone=(f,type,a,d,vol)=>{const o=ctx.createOscillator(),g=ctx.createGain();o.type=type;o.frequency.value=f;
    g.gain.setValueAtTime(0,a);g.gain.linearRampToValueAtTime(vol,a+0.01);g.gain.exponentialRampToValueAtTime(0.0001,a+d);
    o.connect(g);g.connect(out);o.start(a);o.stop(a+d+0.05)};
  if(kind==='buzz'){tone(110,'square',at,0.45,0.18);tone(116,'square',at,0.45,0.12)}
  else if(kind==='chime'){[880,1109,1319,1760].forEach((f,i)=>tone(f,'sine',at+i*0.09,0.7,0.14))}
  else if(kind==='keys'){for(let i=0;i<10;i++)tone(2400+(i%3)*300,'square',at+i*0.07,0.03,0.04)}
  else{const n=ctx.createBufferSource(),b=ctx.createBuffer(1,ctx.sampleRate*0.5,ctx.sampleRate),d=b.getChannelData(0);
    for(let i=0;i<d.length;i++)d[i]=(Math.random()*2-1)*Math.sin(Math.PI*i/d.length)*0.12;
    const f=ctx.createBiquadFilter();f.type='lowpass';f.frequency.setValueAtTime(400,at);f.frequency.linearRampToValueAtTime(3000,at+0.5);
    n.buffer=b;n.connect(f);f.connect(out);n.start(at)}
}
function dramaProgress(pb,t,label){
  const b=pb.querySelector('#dr-rec,#dr-scene');
  const el=pb.querySelector('#dr-out');
  if(el)el.innerHTML=`<div class="dr-bar"><i style="width:${Math.min(100,t/DRAMA_DUR*100).toFixed(1)}%"></i></div><div class="mut">${esc(label)} ${Math.max(0,Math.ceil(DRAMA_DUR-t))} s</div>`;
  if(b)b.disabled=true;
}
async function dramaRecord(pb){
  const why=dramaCan();if(why){toast(why,{kind:'warn'});return}
  const st=(DRAMA.data||{}).story;if(!st||!st.panels.length||DRAMA.busy)return;
  DRAMA.busy=true;
  const [W,H]=DRAMA_FMT[DRAMA.fmt]||DRAMA_FMT.vertical;
  const cv=document.createElement('canvas');cv.width=W;cv.height=H;
  const ctx=cv.getContext('2d'),plan=dramaPlan(st);
  let audio=null;
  try{
    dramaProgress(pb,0,'getting the voices ready…');
    const faces=await dramaFaces(st);
    audio=await dramaVoices(st,plan);
    const stream=cv.captureStream(30);
    if(audio)audio.dest.stream.getAudioTracks().forEach(t=>stream.addTrack(t));
    const mime=dramaMime(),chunks=[];
    const rec=new MediaRecorder(stream,mime?{mimeType:mime,videoBitsPerSecond:5e6}:{});
    rec.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data)};
    const stopped=new Promise(r=>rec.onstop=r);
    dramaFrame(ctx,W,H,0,st,plan,faces);
    rec.start(250);if(audio)audio.start();
    const t0=performance.now();
    await new Promise(res=>{const step=()=>{const t=(performance.now()-t0)/1000;
      dramaFrame(ctx,W,H,Math.min(t,DRAMA_DUR-0.01),st,plan,faces);dramaProgress(pb,t,'recording');
      if(t<DRAMA_DUR)requestAnimationFrame(step);else res()};requestAnimationFrame(step)});
    rec.stop();await stopped;
    const note=audio&&!audio.voiced&&DRAMA.voices?'No voices in this one: '
      +((DRAMA.data||{}).speech==='browser'?'the browser’s voice cannot be recorded.':'the voice engine did not answer.'):'';
    dramaSet(new Blob(chunks,{type:(mime||'video/webm').split(';')[0]}),'video',note);
  }catch(e){dramaSet(null,'','Could not record: '+(e.message||e))}
  finally{if(audio)audio.close();DRAMA.busy=false}
  dramaPaint(pb);
}

/* ---- recording the scene that is playing ---- */
function dramaSceneCanvas(){
  // the largest visible canvas of the desktop scene, never one inside a window
  let best=null,area=0;
  document.querySelectorAll('#wall canvas,#desktop canvas,#world-scene canvas,#office-scene canvas').forEach(c=>{
    if(c.closest('.win'))return;
    const r=c.getBoundingClientRect(),a=r.width*r.height;
    if(r.width<200||r.height<200||getComputedStyle(c).visibility==='hidden'||!c.checkVisibility||!c.checkVisibility())return;
    if(a>area){area=a;best=c}
  });
  return best;
}
async function dramaSceneRecord(pb){
  const why=dramaCan();if(why){toast(why,{kind:'warn'});return}
  if(DRAMA.busy)return;
  const w=DRAMA.w;
  if(w&&typeof minimizeWin==='function')minimizeWin(w);
  await new Promise(r=>setTimeout(r,450));       // the scene wakes once nothing covers it
  const src=dramaSceneCanvas();
  if(!src){if(w)restoreWin(w);toast('There is no scene showing to record.',{kind:'warn'});return}
  DRAMA.busy=true;
  const [W,H]=DRAMA_FMT[DRAMA.fmt==='square'?'square':'vertical'];
  const cv=document.createElement('canvas');cv.width=W;cv.height=H;
  const ctx=cv.getContext('2d'),u=Math.min(W,H)/720,foot=86*u;
  const vid=document.createElement('video');vid.muted=true;vid.playsInline=true;
  const pill=document.createElement('div');pill.className='dr-recpill';document.body.appendChild(pill);
  try{
    vid.srcObject=src.captureStream(30);await vid.play();
    const out=cv.captureStream(30),mime=dramaMime(),chunks=[];
    const rec=new MediaRecorder(out,mime?{mimeType:mime,videoBitsPerSecond:5e6}:{});
    rec.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data)};
    const stopped=new Promise(r=>rec.onstop=r);
    rec.start(250);
    const t0=performance.now();
    await new Promise(res=>{const step=()=>{const t=(performance.now()-t0)/1000;
      const vw=vid.videoWidth||src.width,vh=vid.videoHeight||src.height;
      // cover: crop the middle of the scene to the format
      const s=Math.max(W/vw,(H-foot)/vh),dw=vw*s,dh=vh*s;
      ctx.fillStyle='#000';ctx.fillRect(0,0,W,H);
      try{ctx.drawImage(vid,(W-dw)/2,(H-foot-dh)/2,dw,dh)}catch(e){}
      dramaFooter(ctx,W,H,u,foot);
      pill.textContent='● REC '+Math.max(0,Math.ceil(DRAMA_DUR-t))+' s';
      if(t<DRAMA_DUR)requestAnimationFrame(step);else res()};requestAnimationFrame(step)});
    rec.stop();await stopped;
    dramaSet(new Blob(chunks,{type:(mime||'video/webm').split(';')[0]}),'video','Scene recordings are silent.');
  }catch(e){dramaSet(null,'','Could not record the scene: '+(e.message||e))}
  finally{
    DRAMA.busy=false;pill.remove();
    try{(vid.srcObject&&vid.srcObject.getTracks()||[]).forEach(t=>t.stop())}catch(e){}
    if(w&&typeof restoreWin==='function')restoreWin(w);
  }
  dramaPaint(pb);
}

/* An episode just finished (the server says so once): offer the clip, never record it. */
function dramaOffer(ev){
  if(!ev||!ev.episode||ev.episode===DRAMA.seen)return;
  DRAMA.seen=ev.episode;
  toast('Your crew just had a moment: trouble, a fix, and it shipped.',{label:'Make a clip',go:()=>openApp('drama'),ms:9000,kind:'info'});
}
