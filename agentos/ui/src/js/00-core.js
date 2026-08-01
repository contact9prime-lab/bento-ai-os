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
  h=h.replace(/\[([^\]]+)\]\(([\w][\w./-]*\.md(?:#[\w-]*)?)\)/g,'<a href="#" class="doclink" data-doc="$2">$1</a>');
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
function toast(t){
  let box=document.getElementById('toasts');
  if(!box){box=document.createElement('div');box.id='toasts';document.body.appendChild(box)}
  const d=document.createElement('div');d.className='toast';d.textContent=t;
  box.prepend(d);
  while(box.children.length>5)box.lastChild.remove();   // never stack unbounded
  if(typeof Motion!=='undefined')Motion.run(d,[{transform:'translateX(40px)',opacity:0},{transform:'none',opacity:1}],{duration:220,easing:'cubic-bezier(.22,1,.36,1)'});
  setTimeout(()=>{
    if(!d.isConnected)return;
    const done=()=>d.remove();
    if(typeof Motion!=='undefined')Motion.run(d,[{transform:'none',opacity:1},{transform:'translateX(40px)',opacity:0}],{duration:180,easing:'cubic-bezier(.4,0,.7,.2)'}).finished.then(done);
    else done();
  },3500);
}
const fmtBytes=b=>b>=1e12?(b/1e12).toFixed(2)+' TB':b>=1e9?(b/1e9).toFixed(1)+' GB':(b/1e6).toFixed(0)+' MB';

