/* ================= keyboard / shortcuts system ================= */
// "Command key": Cmd on Mac (metaKey), Ctrl on Linux/Windows — both accepted so it feels native.
const IS_MAC=/Mac/i.test(navigator.platform);
const CMD='⌘/Ctrl';
function cmd(e){return e.metaKey||e.ctrlKey}
const KEYMAP=[
  {group:'General',keys:[
    {k:['Ctrl','Space'],alt:['Alt','Space'],label:'Command palette / ask AI'},
    {k:[CMD,'K'],label:'Command palette'},
    {k:['Ctrl','/'],alt:['?'],label:'This shortcuts help'},
    {k:[CMD,','],label:'Settings'},
    {k:['F11'],label:'Toggle fullscreen'},
    {k:['Alt','J'],label:'Voice mode'},
  ]},
  {group:'Windows',keys:[
    {k:['Ctrl','Tab'],alt:['Alt','Tab'],label:'Switch window (hold, Tab to cycle)'},
    {k:['Ctrl','Shift','Tab'],label:'Switch window (backwards)'},
    {k:['F3'],alt:['Ctrl','↑'],label:'Exposé — all windows at a glance'},
    {k:[CMD,'W'],label:'Close active window'},
    {k:[CMD,'M'],label:'Minimize active window'},
    {k:[CMD,'F'],label:'Maximize / restore active window'},
    {k:['drag to edge'],label:'Snap: halves, corners, top to maximize'},
  ]},
  {group:'Desktops',keys:[
    {k:['Ctrl','1…6'],label:'Switch virtual desktop'},
  ]},
  {group:'Apps',keys:[
    {k:[CMD,'Enter'],label:'New chat'},
    {k:['Ctrl','Alt','T'],label:'Open terminal'},
  ]},
];
function activeWin(){let a=null;WM.wins.forEach(w=>{if(w.el.classList.contains('active'))a=w});return a}

// --- Ctrl+Tab window switcher (Cmd+Tab-style) ---
let SW={open:false,list:[],idx:0};
function switcherList(){
  const arr=[];WM.wins.forEach(w=>{if(deskVisible(w)&&!w.min)arr.push(w)});
  return arr.sort((a,b)=>(+b.el.style.zIndex||0)-(+a.el.style.zIndex||0));
}
function switcherOpen(dir){
  SW.list=switcherList();
  if(SW.list.length<2){if(SW.list.length===1)focusWin(SW.list[0]);return}
  if(!SW.open){SW.open=true;SW.idx=1;$('#switcher').classList.add('show')}
  else{SW.idx=(SW.idx+dir+SW.list.length)%SW.list.length}
  switcherRender();
}
function switcherRender(){
  $('#swbox').innerHTML=SW.list.map((w,i)=>`<div class="swcard${i===SW.idx?' sel':''}">
    ${appIcon(w.id,48)}<span class="sn">${esc(w.app.title)}</span></div>`).join('');
}
function switcherCommit(){
  if(!SW.open)return;SW.open=false;$('#switcher').classList.remove('show');
  const w=SW.list[SW.idx];if(w)focusWin(w);
}

// --- exposé: every window on this desktop, live, in a grid (F3 / Ctrl+↑) ---
let EXPO={on:false,wins:[]};
function exposeToggle(force){
  const on=force!==undefined?force:!EXPO.on;
  if(on===EXPO.on)return;
  let ov=$('#expose');
  if(!ov){ov=document.createElement('div');ov.id='expose';document.body.appendChild(ov);
    ov.addEventListener('mousedown',e=>{if(e.target.id==='expose')exposeToggle(false)})}
  if(on){
    const wins=switcherList();
    if(!wins.length)return;
    EXPO.on=true;EXPO.wins=wins;
    document.body.classList.add('exposing');
    ov.classList.add('show');ov.innerHTML='';
    const mbh=parseInt(getComputedStyle(document.documentElement).getPropertyValue('--mbh'))||30;
    const W=innerWidth, H=innerHeight-mbh, pad=36, gap=26;
    const n=wins.length, cols=Math.ceil(Math.sqrt(n)), rows=Math.ceil(n/cols);
    const cw=(W-pad*2-gap*(cols-1))/cols, ch=(H-pad*2-64-gap*(rows-1))/rows;
    wins.forEach((w,i)=>{
      const r=w.el.getBoundingClientRect();
      const col=i%cols,row=Math.floor(i/cols);
      const s=Math.min(cw/r.width,ch/r.height,0.94);
      const cx=pad+col*(cw+gap)+(cw-r.width*s)/2, cy=mbh+pad+row*(ch+gap)+(ch-r.height*s)/2;
      w.el.classList.add('exp-win');
      w.el.style.transformOrigin='top left';
      w.el.style.transform=`translate(${cx-r.left}px,${cy-r.top}px) scale(${s})`;
      const c=document.createElement('div');c.className='exp-catch';
      c.style.left=cx+'px';c.style.top=(cy-mbh)+'px';c.style.width=r.width*s+'px';c.style.height=r.height*s+'px';
      c.innerHTML=`<span class="exp-lbl">${appIcon(w.id,15)} ${esc(w.app.title)}</span>`;
      c.onclick=()=>{exposeToggle(false);focusWin(w)};
      ov.appendChild(c);
    });
  }else{
    EXPO.on=false;
    ov.classList.remove('show');ov.innerHTML='';
    EXPO.wins.forEach(w=>{w.el.style.transform='';
      setTimeout(()=>{w.el.classList.remove('exp-win');w.el.style.transformOrigin=''},300)});
    setTimeout(()=>document.body.classList.remove('exposing'),320);
    EXPO.wins=[];
  }
}

// --- shortcuts help overlay ---
function keysHelp(on){
  const ov=$('#keyshelp');const show=on!==undefined?on:!ov.classList.contains('show');
  if(show){
    $('#keysbox').innerHTML=`<div class="kh"><span>Keyboard shortcuts</span><button class="mclose" onclick="keysHelp(false)">✕</button></div>
      <div class="kbody">${KEYMAP.map(g=>`<div class="kgrp"><h4>${esc(g.group)}</h4>${g.keys.map(r=>`<div class="krow"><span>${esc(r.label)}</span><span class="kk">${(r.k).map(x=>`<kbd>${esc(x)}</kbd>`).join('')}</span></div>`).join('')}</div>`).join('')}</div>`;
  }
  ov.classList.toggle('show',show);
}
$('#keyshelp').addEventListener('mousedown',e=>{if(e.target.id==='keyshelp')keysHelp(false)});

/* ================= command palette (quicksilver) ================= */
let palIdx=0,palMatches=[];
function paletteOpen(){return $('#palette').classList.contains('show')}
function togglePalette(force){
  const on=force!==undefined?force:!paletteOpen();
  $('#palette').classList.toggle('show',on);
  if(on){$('#palin').value='';palRender('');setTimeout(()=>$('#palin').focus(),10)}
}
function palActions(){
  const items=Object.keys(APPS).map(id=>({id,icon:APPS[id].icon,label:APPS[id].title,hint:APPS[id].desc,run:()=>openApp(id)}));
  const g=inner=>`<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="display:block">${inner}</svg>`;
  items.push(
    {icon:'＋',label:'New chat',hint:'start a fresh conversation',run:()=>{openApp('chat');newChat()}},
    {icon:g('<path d="M4.5 7h15M9.5 7V5.2h5V7M7 7l.9 12.3h8.2L17 7"/>'),label:'Clear session',hint:'wipe the current conversation',run:()=>{openApp('chat');clearSession()}},
    {icon:svgSpeaker(false),label:'Toggle voice',hint:'speak replies on/off',run:()=>{VOICE.tts=!VOICE.tts;saveVoice();toast(VOICE.tts?'voice on':'voice off')}},
    {icon:g('<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4.4 16.4l4.3-3.8 3.4 2.9 3-2.5 4.5 3.6"/>'),label:'Reset wallpaper',hint:'back to the default background',run:()=>fetch('/api/wallpaper',{method:'DELETE'})},
  );
  NATIVEAPPS.forEach(a=>items.push({nat:a,label:a.name,hint:(a.comment||'')+(a.comment?' · ':'')+'system app',run:()=>launchNative(a.id,a.name)}));
  return items;
}
function palScore(q,text){
  q=q.toLowerCase();text=text.toLowerCase();
  if(text.startsWith(q))return 3;
  if(text.includes(q))return 2;
  let i=0;for(const ch of text){if(ch===q[i])i++}
  return i>=q.length?1:0;
}

/* ---- intent grammar: language goes straight to action, not into a chat box.
   Each rule returns {icon,label,hint,run} rows placed ABOVE fuzzy app matches. ---- */
function palFindApp(name){
  name=name.toLowerCase().trim();
  let best=null,bs=0;
  for(const id in APPS){const s=palScore(name,APPS[id].title)||palScore(name,id);if(s>bs){bs=s;best={id}}}
  NATIVEAPPS.forEach(a=>{const s=palScore(name,a.name);if(s>bs){bs=s;best={nat:a}}});
  return bs>=2?best:null;
}
function palIntent(q){
  const out=[];
  const P=(re)=>{const m=q.match(re);return m};
  let m;
  const act=(icon,label,hint,run)=>out.push({icon,label,hint,run,intent:true});
  if(m=P(/^(?:open|launch|start|show)\s+(.+)$/i)){
    const hit=palFindApp(m[1]);
    if(hit&&hit.id)act('▸',`Open ${APPS[hit.id].title}`,'AgentOS app',()=>openApp(hit.id));
    if(hit&&hit.nat)act('▸',`Open ${hit.nat.name}`,'system app',()=>launchNative(hit.nat.id,hit.nat.name));
  }
  if(m=P(/^close\s+(.+)$/i)){
    const hit=palFindApp(m[1]);
    if(hit&&hit.id&&winsOf(hit.id).length)act('✕',`Close ${APPS[hit.id].title}`,`${winsOf(hit.id).length} window(s)`,()=>winsOf(hit.id).forEach(w=>closeWin(w)));
  }
  if(m=P(/^(?:make it |go |switch to |theme )?(dark|light)(?:\s*mode)?$/i)){
    const dark=m[1].toLowerCase()==='dark';
    const name=dark?'agentos':'field';
    act(dark?'◐':'◑',`Switch to ${dark?'dark':'light'} mode`,`theme: ${name}`,()=>{applyTheme(name);toast((dark?'dark':'light')+' mode')});
  }
  if(m=P(/^theme\s+(.+)$/i)){
    const all=allThemes(),qq=m[1].toLowerCase().trim();
    const id=Object.keys(all).find(k=>k.toLowerCase()===qq)||Object.keys(all).find(k=>k.toLowerCase().includes(qq));
    if(id)act('◧',`Apply theme "${id}"`,'switch the whole desktop',()=>{applyTheme(id);toast('theme: '+id)});
  }
  if(m=P(/^(?:set\s+)?vol(?:ume)?\s+(?:to\s+)?(\d{1,3})%?$/i)){
    const v=Math.min(100,+m[1]);
    act('◈',`Volume ${v}%`,'set the output volume',()=>{ctlSet({volume:v});toast('volume '+v+'%')});
  }
  if(P(/^mute$/i))act('◈','Mute','silence the output',()=>{ctlSet({mute:true});toast('muted')});
  if(P(/^unmute$/i))act('◈','Unmute','sound back on',()=>{ctlSet({mute:false});toast('unmuted')});
  if(m=P(/^(?:set\s+)?brightness\s+(?:to\s+)?(\d{1,3})%?$/i)){
    const v=Math.min(100,+m[1]);
    if(cap('display.brightness').available)act('☼',`Brightness ${v}%`,'set the display brightness',
      async()=>{await fetch('/api/brightness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({percent:v})});toast('brightness '+v+'%')});
  }
  if(m=P(/^(?:connect(?:\s+to)?\s+)?wi-?fi(?:\s+(.+))?$/i)){
    act('⌁',m[1]?`Join Wi-Fi "${m[1].trim()}"`:'Wi-Fi settings','open Network settings',()=>{openApp('syssettings')});
  }
  if(P(/^lock(?:\s+(?:the\s+)?screen)?$/i))act('⌗','Lock screen','',()=>powerDo('lock','Lock the screen?'));
  if(P(/^(?:suspend|sleep)$/i))act('☾','Suspend','put the machine to sleep',()=>powerDo('suspend','Suspend the machine?'));
  if(P(/^(?:restart|reboot)(?:\s+(?:the\s+)?(?:machine|computer|pc))?$/i))act('↻','Restart the machine','',()=>powerDo('restart','Restart the machine?'));
  if(P(/^(?:power\s*off|shut\s*down)$/i))act('⏻','Power off','',()=>powerDo('poweroff','Power off the machine?'));
  if(P(/^log\s*out$/i))act('⇥','Log out','end this session',()=>powerDo('logout','Log out of this session? Unsaved work in other apps will be lost.'));
  if(P(/^(?:take\s+a\s+)?screenshot$/i)&&cap('screen.capture').available)
    act('▣','Take a screenshot','saved to your workspace',()=>takeScreenshot('full'));
  if(m=P(/^wallpaper\s+(?:of\s+)?(.{3,})$/i)){
    const p=m[1];
    act('❋',`Generate wallpaper: “${p}”`,`${agentName()} paints it in the background`,
      async()=>{toast('generating wallpaper…');const r=await fetch('/api/wallpaper/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:p})});const d=await r.json().catch(()=>({}));if(!r.ok)toast(d.error||'generation failed')});
  }
  if(m=P(/^desktop\s+([1-9])$/i)){const n=+m[1];if(n<=DESKS)act('▦',`Go to desktop ${n}`,'',()=>switchDesk(n))}
  if(P(/^(?:dnd|do not disturb)(?:\s+on)?$/i))act('◌','Do not disturb on','silence notifications',()=>{toggleDnd(true);toast('do not disturb on')});
  if(P(/^(?:dnd|do not disturb)\s+off$/i))act('◌','Do not disturb off','',()=>{toggleDnd(false);toast('do not disturb off')});
  // arithmetic: the answer inline, Enter copies it
  if(/^[\d\s+\-*/().^%]+$/.test(q)&&/\d/.test(q)&&/[+\-*/^%]/.test(q)){
    try{
      const v=Function('"use strict";return ('+q.replace(/\^/g,'**')+')')();
      if(typeof v==='number'&&isFinite(v)){
        const r=Math.round(v*1e10)/1e10;
        act('=',`${q} = ${r}`,'Enter copies the result',()=>{try{navigator.clipboard.writeText(String(r))}catch(e){}toast('copied '+r)});
      }
    }catch(e){}
  }
  return out;
}
/* model fallback: when the grammar misses, ask the server to classify the intent
   (debounced; appends a suggested action row when it answers) */
let palIntentT=0,palIntentSeq=0;
function palIntentAsync(q){
  clearTimeout(palIntentT);
  if(!q||q.length<8||q.split(/\s+/).length<2)return;
  const seq=++palIntentSeq;
  palIntentT=setTimeout(async()=>{
    try{
      const r=await fetch('/api/intent',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})});
      if(!r.ok)return;
      const d=await r.json();
      if(seq!==palIntentSeq||!paletteOpen()||$('#palin').value.trim()!==q)return;   // stale
      if(!d||!d.action||d.action==='chat')return;
      const row={icon:'✦',label:d.label||`Do it: ${q}`,hint:d.hint||'suggested action',intent:true,
        run:()=>{shellCmd({id:'',action:d.action,args:{target:d.target}});}};
      if(d.action==='ask')return;
      palMatches.splice(Math.max(0,palMatches.length-1),0,row);
      palRenderList();
    }catch(e){}
  },350);
}
function palRender(q){
  q=q.trim();
  const items=palActions();
  const direct=q?palIntent(q):[];              // grammar first: language → action
  const fuzzy=q?items.map(it=>({it,s:palScore(q,it.label+' '+(it.hint||''))})).filter(x=>x.s>0)
      .sort((a,b)=>b.s-a.s).map(x=>x.it).slice(0,Math.max(3,8-direct.length)):items.slice(0,9);
  palMatches=[...direct,...fuzzy];
  if(q)palMatches.push({icon:'▲',label:`Ask ${agentName()}: “${q}”`,hint:'send to the agent',run:()=>palAsk(q)});
  palIdx=Math.min(palIdx,palMatches.length-1)||0;
  palRenderList();
  if(q&&!direct.length)palIntentAsync(q);      // grammar missed → model classifies in the background
}
function palRenderList(){
  $('#pallist').innerHTML=palMatches.map((it,i)=>`<div class="palitem${i===palIdx?' sel':''}${it.intent?' act':''}" data-i="${i}">
    ${it.id?appIcon(it.id,32):it.nat?nativeIcon(it.nat,32):`<span class="pi">${it.icon}</span>`}<span><div class="pl">${esc(it.label)}</div><div class="ph">${esc(it.hint||'')}</div></span></div>`).join('');
  $('#pallist').querySelectorAll('.palitem').forEach(el=>{
    el.onclick=()=>{palRun(+el.dataset.i)};
    el.onmousemove=()=>{palIdx=+el.dataset.i;palHighlight()};
  });
}
function palHighlight(){$('#pallist').querySelectorAll('.palitem').forEach((el,i)=>el.classList.toggle('sel',i===palIdx))}
function palRun(i){
  const it=palMatches[i];if(!it)return;
  togglePalette(false);
  it.run();
}
function palAsk(q){
  openApp('chat');
  if(input){input.value=q;input.dispatchEvent(new Event('input'));send()}
}
$('#palin').addEventListener('input',e=>{palIdx=0;palRender(e.target.value)});
$('#palin').addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'){e.preventDefault();palIdx=Math.min(palIdx+1,palMatches.length-1);palHighlight()}
  else if(e.key==='ArrowUp'){e.preventDefault();palIdx=Math.max(palIdx-1,0);palHighlight()}
  else if(e.key==='Enter'){e.preventDefault();palRun(palIdx)}
  else if(e.key==='Escape'){togglePalette(false)}
});
$('#palette').addEventListener('mousedown',e=>{if(e.target.id==='palette')togglePalette(false)});
document.addEventListener('keyup',e=>{if(e.key==='Control'||e.key==='Meta'||e.key==='Alt')switcherCommit()});
document.addEventListener('keydown',e=>{
  const inTerm=e.target.closest&&e.target.closest('.xterm');
  const k=e.key.toLowerCase();
  const typing=/^(input|textarea|select)$/i.test((e.target.tagName||''));
  // window switcher — Ctrl/Cmd+Tab (reliable), Alt+Tab (best-effort; the OS may grab it)
  if((cmd(e)||e.altKey)&&e.key==='Tab'){e.preventDefault();switcherOpen(e.shiftKey?-1:1);return}
  // Command-key window controls (Cmd on Mac, Ctrl elsewhere)
  if(cmd(e)&&!e.altKey){
    const a=activeWin();
    if(k==='a'&&!typing&&!inTerm&&!a){e.preventDefault();launcherIds().forEach(id=>setSel(id,true));return}
    if(k==='w'&&a){e.preventDefault();closeWin(a);return}
    if(k==='m'&&a){e.preventDefault();minimizeWin(a);return}
    if(k==='f'&&a){e.preventDefault();toggleMax(a);return}
    if(k===','){e.preventDefault();openApp('settings');return}
    if(e.key==='Enter'){e.preventDefault();openApp('chat');newChat();return}
    if(k==='/'){e.preventDefault();keysHelp();return}
  }
  if(e.key==='?'&&!typing){e.preventDefault();keysHelp();return}
  if(e.key==='Escape'){if(EXPO.on){exposeToggle(false);return}if(SW.open){switcherCommit();return}if($('#keyshelp').classList.contains('show')){keysHelp(false);return}}
  if(e.key==='F3'||(e.ctrlKey&&!e.shiftKey&&!e.altKey&&e.key==='ArrowUp'&&!typing&&!inTerm)){e.preventDefault();exposeToggle();return}
  if(e.ctrlKey&&e.shiftKey&&k==='p'){e.preventDefault();togglePalette()}          // works everywhere, incl. terminal
  else if(e.key==='F11'){e.preventDefault();toggleFullscreen()}
  else if((e.altKey&&e.code==='Space')&&!inTerm){e.preventDefault();togglePalette()}   // Alt+Space quick launch / ask AI
  else if(!inTerm&&((e.ctrlKey&&e.code==='Space')||(e.ctrlKey&&!e.shiftKey&&!e.altKey&&k==='k'))){e.preventDefault();togglePalette()}
  else if(e.ctrlKey&&e.altKey&&k==='t'){e.preventDefault();togglePalette(false);openApp('terminal')}
  else if(e.altKey&&!e.ctrlKey&&!e.shiftKey&&k==='j'){e.preventDefault();jarvisMode(!JARVIS.on)}
  else if(e.ctrlKey&&!e.shiftKey&&!e.altKey&&/^[1-9]$/.test(e.key)&&!inTerm){
    const n=+e.key;if(n<=DESKS){e.preventDefault();switchDesk(n)}}
});

