'use strict';
const $=s=>document.querySelector(s);
let ws=null, running=false, currentConv=null, cfg=null;

/* ================= voice / Jarvis mode =================
   (previously mis-placed inside the <style> block, which left JARVIS and these
    functions undefined and threw on every turn — now a live part of the app) */
let JARVIS={on:false,phase:'idle',rec:null,cid:null,busy:false};
let jarvisReply='';
function jarvisSetPhase(p,status){
  JARVIS.phase=p;const ov=$('#jarvis-ov');if(!ov)return;
  ov.classList.remove('listening','thinking','speaking');
  if(p!=='idle')ov.classList.add(p);
  document.body.classList.remove('js-listening','js-thinking','js-speaking');
  if(p!=='idle')document.body.classList.add('js-'+p);       // animate the Jarvis-experience orb too
  if(status){const st=$('#j-status');if(st)st.textContent=status;const jv=$('#js-voice');if(jv)jv.textContent=status}
}
function jarvisMode(on){
  const ov=$('#jarvis-ov');if(!ov)return;
  if(on){
    if(!('webkitSpeechRecognition'in window||'SpeechRecognition'in window))return toast('speech recognition not available in this browser');
    JARVIS.on=true;ov.classList.add('show');
    $('#j-transcript').textContent='';$('#j-reply').textContent='';
    JARVIS.cid=JARVIS.cid||currentConv;
    jarvisListen();
  }else{
    JARVIS.on=false;ov.classList.remove('show');
    try{JARVIS.rec&&JARVIS.rec.stop()}catch(e){}
    try{speechSynthesis.cancel()}catch(e){}
    jarvisSetPhase('idle');
  }
}
function jarvisListen(){
  if(!JARVIS.on)return;
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  try{JARVIS.rec&&JARVIS.rec.abort()}catch(e){}
  const rec=new SR();JARVIS.rec=rec;
  rec.lang=(VOICE&&VOICE.lang)||'en-IN';rec.interimResults=true;rec.continuous=false;
  let finalText='';
  jarvisSetPhase('listening','listening…');
  rec.onresult=e=>{
    let interim='';finalText='';
    for(let i=0;i<e.results.length;i++){const r=e.results[i];if(r.isFinal)finalText+=r[0].transcript;else interim+=r[0].transcript}
    $('#j-transcript').textContent=(finalText||interim).trim();
  };
  rec.onerror=ev=>{if(ev.error==='no-speech'&&JARVIS.on){jarvisListen()}};
  rec.onend=()=>{
    const t=$('#j-transcript').textContent.trim();
    if(!JARVIS.on)return;
    if(t){jarvisAsk(t)}else{jarvisListen()}   // nothing heard → keep listening
  };
  try{rec.start()}catch(e){setTimeout(jarvisListen,400)}
}
function jarvisAsk(text){
  if(!ws||ws.readyState!==1){jarvisSetPhase('idle','not connected');return}
  jarvisSetPhase('thinking',agentName()+' is working…');
  $('#j-reply').textContent='';
  JARVIS.busy=true;jarvisReply='';
  ws.send(JSON.stringify({type:'chat',text,conversation_id:JARVIS.cid,model:''}));
  setRunning(true);
}
function jarvisSpeakAndListen(text){
  jarvisSetPhase('speaking',agentName()+' is speaking…');
  const clean=(text||'').replace(/```[\s\S]*?```/g,' code block. ').replace(/[*_#`>|]/g,'').slice(0,900);
  if(!clean.trim()||!window.speechSynthesis){if(JARVIS.on)jarvisListen();return}
  const u=new SpeechSynthesisUtterance(clean);
  u.rate=(VOICE&&VOICE.rate)||1;
  const v=speechSynthesis.getVoices().find(v=>v.name===(VOICE&&VOICE.voice));if(v)u.voice=v;
  u.onend=()=>{if(JARVIS.on)jarvisListen();else jarvisSetPhase('idle')};
  u.onerror=()=>{if(JARVIS.on)jarvisListen()};
  speechSynthesis.cancel();speechSynthesis.speak(u);
}
const RUNNING=new Set();   // conversation_ids with a live turn (several may run at once)
const STREAMS={};          // conversation_id -> {html, text}: buffered stream for chats not on screen
const QUEUES={};           // conversation_id -> [{id,text,status,reason}]: typed while a turn ran.
                           // The server owns it; this is the mirror the composer renders as "Up next".
let APPS_READY=false;   // APPS (const) is in the temporal dead zone until its definition — gate on this
let curBody=null, curThink=null, curText='';
let feed=null, chatEl=null, input=null, sendBtn=null;   // bound when the Chat window is open

/* ================= helpers ================= */
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function md(src){
  const blocks=[]; src=src.replace(/```(\w*)\n?([\s\S]*?)(```|$)/g,(m,l,c)=>{blocks.push('<pre><code>'+esc(c)+'</code></pre>');return '\x00B'+(blocks.length-1)+'\x00';});
  let h=esc(src);
  h=h.replace(/`([^`\n]+)`/g,'<code>$1</code>');
  h=h.replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
  h=h.replace(/(?<![\w*])\*([^*\n]+)\*(?![\w*])/g,'<em>$1</em>');
  h=h.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  /* Relative .md links navigate inside the Docs app. The leading `\.{0,2}\/?` is
     load-bearing: the old pattern required a word character first, so `../users.md`
     — the normal way a page in docs/design/ points back up — matched nothing and
     rendered as literal text. A dead link in the manual is worse than no link,
     because it reads as the manual being wrong about itself. */
  h=h.replace(/\[([^\]]+)\]\(((?:\.{1,2}\/)*[\w][\w./-]*\.md(?:#[\w-]*)?)\)/g,'<a href="#" class="doclink" data-doc="$2">$1</a>');
  /* Bare URLs, in docs and in every chat reply. The agent writes them constantly
     and a URL you cannot click is the most obviously broken thing on a page.
     Anything that is ALREADY a link — or code — is set aside first, or an href
     ends up with a second href inside it. */
  const links=[];
  h=h.replace(/<a\b[\s\S]*?<\/a>|<code>[\s\S]*?<\/code>/g,m=>{links.push(m);return '\x00A'+(links.length-1)+'\x00'});
  h=h.replace(/(^|[\s(>])((?:https?:\/\/|www\.)[^\s<>()"']+[^\s<>()"'.,;:!?])/g,
    (m,pre,u)=>pre+'<a href="'+(u.startsWith('www.')?'https://'+u:u)+'" target="_blank" rel="noopener">'+u+'</a>');
  h=h.replace(/\x00A(\d+)\x00/g,(m,i)=>links[+i]);
  h=h.replace(/^#### (.+)$/gm,'<h4>$1</h4>').replace(/^### (.+)$/gm,'<h3>$1</h3>').replace(/^## (.+)$/gm,'<h2>$1</h2>').replace(/^# (.+)$/gm,'<h1>$1</h1>');
  h=h.replace(/^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/gm,'<hr>');
  h=h.replace(/((?:^&gt;.*\n?)+)/gm,m=>'<blockquote>'+m.replace(/^&gt; ?/gm,'').trim().replace(/\n/g,'<br>')+'</blockquote>');
  h=h.replace(/((?:^\|.*\|[ \t]*\n?)+)/gm,m=>{
    const rows=m.trim().split(/\n/).map(r=>r.replace(/^\s*\|/,'').replace(/\|\s*$/,'').split('|').map(c=>c.trim()));
    if(rows.length<2||!/^[:\s-]+$/.test(rows[1].join('')))return m;   // not a table
    const cells=(r,tag)=>'<tr>'+r.map(c=>`<${tag}>${c}</${tag}>`).join('')+'</tr>';
    return '<table><thead>'+cells(rows[0],'th')+'</thead><tbody>'+rows.slice(2).map(r=>cells(r,'td')).join('')+'</tbody></table>';
  });
  h=h.replace(/((?:^[ \t]*[-*] .+\n?)+)/gm,m=>'<ul>'+m.trim().split(/\n/).map(l=>'<li>'+l.replace(/^[ \t]*[-*] /,'')+'</li>').join('')+'</ul>');
  h=h.replace(/((?:^[ \t]*\d+\. .+\n?)+)/gm,m=>'<ol>'+m.trim().split(/\n/).map(l=>'<li>'+l.replace(/^[ \t]*\d+\. /,'')+'</li>').join('')+'</ol>');
  h=h.split(/\n{2,}/).map(p=>/^<(h\d|hr|ul|ol|pre|table|blockquote|\x00)/.test(p.trim())?p:'<p>'+p.replace(/\n/g,'<br>')+'</p>').join('');
  return h.replace(/\x00B(\d+)\x00/g,(m,i)=>blocks[+i]);
}
function scrollDown(){if(chatEl)chatEl.scrollTop=chatEl.scrollHeight}
/* What KIND of news a toast is, so it can say so with an icon and a colour rather
   than asking the reader to parse the sentence. `act.kind` decides when a caller
   knows; the ~400 older calls are read by their first words ("could not…" is a
   failure, "saved…" a success). A guess only picks an icon — the words are always
   shown as written, so a wrong guess costs a colour, never the message. */
var TOAST_IC={ok:'M5 12.5l4.5 4.5L19 7.5',err:'M7 7l10 10M17 7L7 17',warn:'M12 6.5v7M12 17v.5',info:'M12 10.5v7M12 6.5v.5'};
function toastKind(t,act){
  if(act&&act.kind&&TOAST_IC[act.kind])return act.kind;
  const s=String(t==null?'':t).trim().toLowerCase();
  if(/^[✗✕✖]|^(could not|couldn.t|can.t |cannot|failed|error|invalid|refused|not allowed|not connected|not a valid|no such |no valid |no link|the server did not answer|install failed)/.test(s))return 'err';
  if(/^[!⚠]|^(warning|careful|glass effects turned down)/.test(s))return 'warn';
  if(/^[✓✔]|^(saved|done|deleted|removed|linked|copied|imported|installed|updated|allowed|granted|stopped|sent|created|applied|revoked|recorded|moved|renamed|promoted|drafted)\b|now works with/.test(s))return 'ok';
  return 'info';
}
/* toast(text) says something happened. toast(text,{label,go,ms,kind}) also offers
   the one tap that deals with it. Hovering holds it (the bar pauses); a failure
   stays twice as long as good news, because it is the one that needs reading. */
function toast(t,act){
  let box=document.getElementById('toasts');
  if(!box){box=document.createElement('div');box.id='toasts';box.setAttribute('role','status');
    box.setAttribute('aria-live','polite');document.body.appendChild(box)}
  const kind=toastKind(t,act);
  const d=document.createElement('div');d.className='toast k-'+kind;
  if(kind==='err')d.setAttribute('role','alert');
  const ms=(act&&act.ms)||(kind==='err'?7000:3800);
  d.style.setProperty('--toast-ms',ms+'ms');
  d.innerHTML=`<i class="toast-ic" aria-hidden="true"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="${TOAST_IC[kind]}"/></svg></i><span class="toast-t"></span>`;
  // the glyph a caller wrote ("✓ saved") is now the icon; the words stay as written
  d.querySelector('.toast-t').textContent=String(t==null?'':t).replace(/^\s*[✓✔✗✕✖⚠]\s*/,'');
  let h=0,left=ms,started=Date.now();
  const leave=()=>{clearTimeout(h);if(!d.isConnected)return;
    const done=()=>d.remove();
    if(typeof Motion!=='undefined')Motion.run(d,[{transform:'none',opacity:1},{transform:'translateX(40px)',opacity:0}],{duration:180,easing:'cubic-bezier(.4,0,.7,.2)'}).finished.then(done);
    else done()};
  if(act&&act.label&&typeof act.go==='function'){
    const b=document.createElement('button');b.className='endbtn toast-act';b.textContent=act.label;
    b.onclick=()=>{d.remove();act.go()};d.classList.add('has-act');d.appendChild(b);
  }
  const x=document.createElement('button');x.className='toast-x';x.setAttribute('aria-label','Dismiss');x.textContent='✕';
  x.onclick=leave;d.appendChild(x);
  const bar=document.createElement('i');bar.className='toast-bar';bar.setAttribute('aria-hidden','true');d.appendChild(bar);
  d.onmouseenter=()=>{clearTimeout(h);left-=Date.now()-started;d.classList.add('held')};
  d.onmouseleave=()=>{started=Date.now();h=setTimeout(leave,Math.max(900,left));d.classList.remove('held')};
  box.prepend(d);
  while(box.children.length>5)box.lastChild.remove();   // never stack unbounded
  if(typeof Motion!=='undefined')Motion.run(d,[{transform:'translateX(40px)',opacity:0},{transform:'none',opacity:1}],{duration:220,easing:'cubic-bezier(.22,1,.36,1)'});
  h=setTimeout(leave,ms);
}
const fmtBytes=b=>b>=1e12?(b/1e12).toFixed(2)+' TB':b>=1e9?(b/1e9).toFixed(1)+' GB':(b/1e6).toFixed(0)+' MB';

