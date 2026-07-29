/* ================= keyboard / shortcuts system ================= */
// "Command key": Cmd on Mac (metaKey), Ctrl on Linux/Windows — both accepted so it feels native.
const IS_MAC=/Mac/i.test(navigator.platform);
const CMD='⌘/Ctrl';
function cmd(e){return e.metaKey||e.ctrlKey}
function KEYMAP_LIVE(){
  const g=(name)=>((SHORTCUTS[name]||SC_DEFAULTS[name]||{}).keys||'').split('+');
  const row=(name)=>({k:g(name),label:(SHORTCUTS[name]||SC_DEFAULTS[name]||{}).label||name});
  return [
    {group:'General',keys:[row('omnibar.focus'),row('omnibar.focus2'),
      {k:['any key'],label:'Start typing anywhere — it lands in the prompt bar'},
      {k:['Alt','1-9'],label:'Quick launch: a result row, else that dock app'},
      {k:['Shift','Enter'],label:'Ask the agent instead of launching'},
      row('deck'),row('help'),row('settings'),row('fullscreen'),row('voice')]},
    {group:'Windows',keys:[row('switcher'),{k:['Alt','Tab'],label:'Switch window (session mode)'},
      row('expose'),row('windows.arrange'),row('window.close'),row('window.minimize'),row('window.maximize'),
      {k:['drag to edge'],label:'Snap: halves, corners, top to maximize'}]},
    {group:'Desktops',keys:[row('desktop.prev'),row('desktop.next'),
      row('desktop.move.prev'),row('desktop.move.next'),
      {k:['Ctrl','1-9'],label:'Jump straight to a desktop'}]},
    {group:'Apps',keys:[row('chat.new'),row('chat.open'),row('terminal')]},
  ];
}
function activeWin(){let a=null;WM.wins.forEach(w=>{if(w.el.classList.contains('active'))a=w});return a}

// --- Ctrl+Tab window switcher (Cmd+Tab-style) ---
let SW={open:false,list:[],idx:0};
/* The switcher is the machine's window list, not AgentOS's: in session mode the
   external apps are windows on this desktop too, and leaving them out is what
   made Ctrl+Tab feel broken the moment a browser was open. */
function switcherList(){
  const arr=[];WM.wins.forEach(w=>{if(deskVisible(w)&&!w.min)arr.push(w)});
  arr.sort((a,b)=>(+b.el.style.zIndex||0)-(+a.el.style.zIndex||0));
  const nat=(typeof NATWINS!=='undefined'?NATWINS:[]).filter(w=>!w.minimized);
  return arr.concat(nat.map(w=>({native:w,id:w.app,app:{title:(typeof natName==='function'?natName(w):w.app)}})));
}
function switcherOpen(dir){
  SW.list=switcherList();
  if(SW.list.length<2){if(SW.list.length===1){SW.open=true;SW.idx=0;switcherCommit()}return}
  if(!SW.open){SW.open=true;SW.idx=1;$('#switcher').classList.add('show')}
  else{SW.idx=(SW.idx+dir+SW.list.length)%SW.list.length}
  switcherRender();
}
function switcherRender(){
  $('#swbox').innerHTML=SW.list.map((w,i)=>`<div class="swcard${i===SW.idx?' sel':''}">
    ${w.native?natIcon(w.native,48):appIcon(w.id,48)}<span class="sn">${esc(w.app.title)}</span></div>`).join('');
}
function switcherCommit(){
  if(!SW.open)return;SW.open=false;$('#switcher').classList.remove('show');
  const w=SW.list[SW.idx];if(!w)return;
  if(w.native){if(typeof raiseShell==='function')raiseShell(false);natWin('focus',w.native.id)}
  else focusWin(w);
}

// --- Spaces: every desktop as a card, every window a tile you can throw between them ---
let EXPO={on:false,wins:[]};
function deskWins(n){const a=[];WM.wins.forEach(w=>{if((w.desk||1)===n&&!w.min)a.push(w)});return a}
function exposeToggle(force){
  const on=force!==undefined?force:!EXPO.on;
  if(on===EXPO.on)return;
  let ov=$('#expose');
  // inside #desktop, like the deck: #desktop is position:fixed and therefore its
  // own stacking context — an overlay outside it would sit ABOVE the windows and
  // blur the very thumbnails it is meant to show.
  if(!ov){ov=document.createElement('div');ov.id='expose';$('#desktop').appendChild(ov);
    ov.addEventListener('mousedown',e=>{if(e.target===ov||e.target.id==='expose-grid')exposeToggle(false)})}
  if(on){
    EXPO.on=true;
    document.body.classList.add('exposing');
    ov.classList.add('show');
    ov.innerHTML=`<div id="expose-spaces"></div><div id="expose-grid"></div>
      <div id="expose-hint">click a space to switch · drag a window onto a space to move it · double-click a window to open it</div>`;
    exposeSpaces();exposeGrid();
  }else{
    EXPO.on=false;
    ov.classList.remove('show');ov.innerHTML='';
    EXPO.wins.forEach(w=>{w.el.style.transform='';
      setTimeout(()=>{w.el.classList.remove('exp-win');w.el.style.transformOrigin=''},300)});
    setTimeout(()=>document.body.classList.remove('exposing'),320);
    EXPO.wins=[];
  }
}
/* the spaces strip: a live mini-map of every desktop, and a drop target */
function exposeSpaces(){
  const box=$('#expose-spaces');if(!box)return;
  const cards=[];
  for(let n=1;n<=DESKS;n++){
    const wins=deskWins(n);
    const W=innerWidth,H=innerHeight;
    const mini=wins.map(w=>{
      const r=w.el.getBoundingClientRect();
      return `<i style="left:${(r.left/W*100).toFixed(1)}%;top:${(r.top/H*100).toFixed(1)}%;
        width:${(r.width/W*100).toFixed(1)}%;height:${(r.height/H*100).toFixed(1)}%"></i>`;
    }).join('');
    cards.push(`<div class="space${n===curDesk?' on':''}" data-n="${n}" title="Desktop ${n} — ${wins.length} window(s)">
      <div class="sp-map">${mini}</div>
      <div class="sp-lbl">Desktop ${n}${wins.length?` · ${wins.length}`:''}
        ${DESKS>1?`<button class="sp-x" title="Remove this desktop">✕</button>`:''}</div></div>`);
  }
  if(DESKS<9)cards.push(`<div class="space add" id="sp-add" title="Add a desktop">＋<div class="sp-lbl">New desktop</div></div>`);
  box.innerHTML=cards.join('');
  box.querySelectorAll('.space[data-n]').forEach(c=>{
    const n=+c.dataset.n;
    c.onclick=e=>{
      if(e.target.closest('.sp-x')){e.stopPropagation();removeDesk(n);return}
      if(n!==curDesk){switchDesk(n);setTimeout(()=>{exposeSpaces();exposeGrid()},260)}
    };
    c.ondragover=e=>{e.preventDefault();c.classList.add('drop')};
    c.ondragleave=()=>c.classList.remove('drop');
    c.ondrop=e=>{
      e.preventDefault();c.classList.remove('drop');
      const key=e.dataTransfer.getData('text/agentos-window');
      const w=WM.wins.get(key);if(!w||w.desk===n)return;
      w.desk=n;applyDeskVisibility();
      toast(`moved "${w.app.title}" to Desktop ${n}`);
      exposeSpaces();exposeGrid();
    };
  });
  const add=$('#sp-add');
  if(add)add.onclick=()=>{DESKS++;localStorage.setItem('desks',DESKS);buildPager();exposeSpaces()};
}
function removeDesk(n){
  if(DESKS<=1)return;
  deskWins(n).forEach(w=>{w.desk=Math.max(1,n-1)});     // never orphan a window
  DESKS--;localStorage.setItem('desks',DESKS);
  if(curDesk>DESKS)switchDesk(DESKS);
  applyDeskVisibility();buildPager();exposeSpaces();exposeGrid();
  toast('desktop removed');
}
/* the grid: the CURRENT desktop's real windows, scaled down and draggable */
function exposeGrid(){
  const ov=$('#expose'),grid=$('#expose-grid');if(!grid)return;
  EXPO.wins.forEach(w=>{w.el.style.transform='';w.el.classList.remove('exp-win')});
  grid.innerHTML='';
  const wins=deskWins(curDesk).sort((a,b)=>(+b.el.style.zIndex||0)-(+a.el.style.zIndex||0));
  EXPO.wins=wins;
  if(!wins.length){grid.innerHTML='<div class="exp-empty">No windows on this desktop</div>';return}
  const dr=$('#desktop').getBoundingClientRect();
  const top=dr.top+150, W=dr.width, H=dr.height-150-110, pad=30, gap=26;
  const n=wins.length, cols=Math.ceil(Math.sqrt(n)), rows=Math.ceil(n/cols);
  const cw=(W-pad*2-gap*(cols-1))/cols, ch=(H-gap*(rows-1))/rows;
  wins.forEach((w,i)=>{
    const r=w.el.getBoundingClientRect();
    const col=i%cols,row=Math.floor(i/cols);
    const s=Math.min(cw/r.width,ch/r.height,0.92);
    const cx=pad+col*(cw+gap)+(cw-r.width*s)/2, cy=top+row*(ch+gap)+(ch-r.height*s)/2;
    const lx=cx-dr.left, ly=cy-dr.top;                    // overlay coords are desktop-relative
    w.el.classList.add('exp-win');
    w.el.style.transformOrigin='top left';
    w.el.style.transform=`translate(${cx-r.left}px,${cy-r.top}px) scale(${s})`;
    const c=document.createElement('div');c.className='exp-catch';c.draggable=true;
    c.style.left=lx+'px';c.style.top=ly+'px';c.style.width=r.width*s+'px';c.style.height=r.height*s+'px';
    c.innerHTML=`<button class="exp-x" title="Close">✕</button>
      <span class="exp-lbl">${appIcon(w.id,15)} ${esc(w.app.title)}</span>`;
    c.ondragstart=e=>{e.dataTransfer.setData('text/agentos-window',w.key);e.dataTransfer.effectAllowed='move';
      c.classList.add('dragging')};
    c.ondragend=()=>c.classList.remove('dragging');
    c.onclick=e=>{if(e.target.closest('.exp-x')){e.stopPropagation();closeWin(w);setTimeout(()=>{exposeSpaces();exposeGrid()},260);return}
      exposeToggle(false);focusWin(w)};
    grid.appendChild(c);
  });
}

// --- shortcuts help overlay ---
function keysHelp(on){
  const ov=$('#keyshelp');const show=on!==undefined?on:!ov.classList.contains('show');
  if(show){
    $('#keysbox').innerHTML=`<div class="kh"><span>Keyboard shortcuts</span><button class="mclose" style="font-size:var(--fs-xs);width:auto;padding:0 8px" onclick="keysHelp(false);openApp(&quot;settings&quot;)">Edit</button><button class="mclose" onclick="keysHelp(false)">✕</button></div>
      <div class="kbody">${KEYMAP_LIVE().map(g=>`<div class="kgrp"><h4>${esc(g.group)}</h4>${g.keys.map(r=>`<div class="krow"><span>${esc(r.label)}</span><span class="kk">${(r.k).map(x=>`<kbd>${esc(x)}</kbd>`).join('')}</span></div>`).join('')}</div>`).join('')}</div>`;
  }
  ov.classList.toggle('show',show);
}
$('#keyshelp').addEventListener('mousedown',e=>{if(e.target.id==='keyshelp')keysHelp(false)});

/* ================= launcher sources (rendered BY the omnibar) =================
   The omnibar is the command palette — there is no second overlay. These stay
   here as the sources it draws from: app/action rows, fuzzy scoring, and the
   intent grammar that turns language into direct actions. */
function togglePalette(force){force===false?omniPop(false):omniFocus()}   // legacy name, one surface
function paletteOpen(){return omniOpen()}
function palActions(){
  const items=Object.keys(APPS).map(id=>({id,icon:APPS[id].icon,label:APPS[id].title,hint:APPS[id].desc,run:()=>openApp(id)}));
  const g=inner=>`<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="display:block">${inner}</svg>`;
  items.push(
    {icon:'＋',label:'New chat',hint:'start a fresh conversation',run:()=>{openApp('chat');newChat()}},
    {icon:g('<path d="M4.5 7h15M9.5 7V5.2h5V7M7 7l.9 12.3h8.2L17 7"/>'),label:'Clear session',hint:'wipe the current conversation',run:()=>{openApp('chat');clearSession()}},
    {icon:svgSpeaker(false),label:'Toggle voice',hint:'speak replies on/off',run:()=>{VOICE.tts=!VOICE.tts;saveVoice();toast(VOICE.tts?'voice on':'voice off')}},
    {icon:g('<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4.4 16.4l4.3-3.8 3.4 2.9 3-2.5 4.5 3.6"/>'),label:'Reset wallpaper',hint:'back to the default background',run:()=>fetch('/api/wallpaper',{method:'DELETE'})},
  );
  // saved automations are first-class palette entries — typing their name is the
  // ad-hoc way to fire one, alongside a hot corner or the Automations app
  (typeof AUTOMATIONS!=='undefined'?AUTOMATIONS:[]).forEach(a=>items.push({
    icon:a.icon||'▶',label:a.name,
    hint:a.steps.map(automationStepLabel).join(' → ').slice(0,90)||'automation',
    run:()=>runAutomation(a),
  }));
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
  // an automation's whole promise is that typing its name runs it, so it beats
  // the fuzzy app match ("start work" must not become "open Web")
  {
    const qq=q.toLowerCase().trim().replace(/^run\s+/,'');
    const a=(typeof AUTOMATIONS!=='undefined'?AUTOMATIONS:[])
      .find(x=>x.name.toLowerCase()===qq)||
      (qq.length>=3?(typeof AUTOMATIONS!=='undefined'?AUTOMATIONS:[]).find(x=>x.name.toLowerCase().startsWith(qq)):null);
    if(a)act(a.icon||'▶',`Run "${a.name}"`,a.steps.map(automationStepLabel).join(' → ').slice(0,90),()=>runAutomation(a));
  }
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
      if(seq!==palIntentSeq||!omniOpen()||$('#omni-in').value.trim()!==q)return;   // stale
      if(!d||!d.action||d.action==='chat'||d.action==='ask')return;
      const row={icon:'✦',label:d.label||`Do it: ${q}`,hint:d.hint||'suggested action',intent:true,
        run:()=>{shellCmd({id:'',action:d.action,args:{target:d.target}});}};
      OMNI.matches.splice(Math.max(0,OMNI.matches.length-1),0,row);
      omniPaint();
    }catch(e){}
  },350);
}
function palAsk(q){
  // quick asks flow through the omnibar's Desktop thread (an answer card),
  // not a full Chat window — escalation is one click on the card
  if(typeof omniAsk==='function'){omniAsk(q);return}
  openApp('chat');
  if(input){input.value=q;input.dispatchEvent(new Event('input'));send()}
}
/* ================= shortcuts: one editable table =================
   Every binding lives in cfg.shortcuts (Settings → Shortcuts) with these
   defaults. Actions are named so the SAME table drives the browser shell and,
   in session mode, sway keybindings that reach the shell over HTTP — which is
   how they keep working while a native window has the keyboard. */
const SC_DEFAULTS={
  'omnibar.focus':   {keys:'Ctrl+Space',  label:'Focus the prompt bar',        session:true},
  'omnibar.focus2':  {keys:'Alt+Space',   label:'Focus the prompt bar (alt)',  session:true},
  'palette':         {keys:'Ctrl+K',      label:'Focus the prompt bar (alt)'},
  'expose':          {keys:'Ctrl+Up',     label:'Spaces — desktops & windows',  session:true,typing:false},
  'expose.f3':       {keys:'F3',          label:'Spaces (alternate)',           session:true},
  'windows.arrange': {keys:'Ctrl+Down',   label:'Organise windows: tile → cascade → restore',typing:false},
  'desktop.prev':    {keys:'Ctrl+Left',   label:'Previous desktop',             typing:false},
  'desktop.next':    {keys:'Ctrl+Right',  label:'Next desktop',                 typing:false},
  'desktop.move.prev':{keys:'Ctrl+Shift+Left', label:'Send window to the previous desktop',typing:false},
  'desktop.move.next':{keys:'Ctrl+Shift+Right',label:'Send window to the next desktop',typing:false},
  'switcher':        {keys:'Ctrl+Tab',    label:'Switch window'},
  'window.close':    {keys:'Ctrl+W',      label:'Close active window'},
  'window.minimize': {keys:'Ctrl+M',      label:'Minimize active window'},
  'window.maximize': {keys:'Ctrl+F',      label:'Maximize / restore window'},
  'chat.new':        {keys:'Ctrl+Enter',  label:'New chat'},
  'chat.open':       {keys:'Ctrl+Shift+A',label:'Open Agent Chat',             session:true},
  'copilot':         {keys:'Ctrl+Shift+Space',label:'Ask the agent about this window',session:true},
  'agent.stop':      {keys:'Ctrl+.',    label:'Stop the agent — everywhere, now',session:true},
  'terminal':        {keys:'Ctrl+Alt+T',  label:'Open Terminal',               session:true},
  'settings':        {keys:'Ctrl+,',      label:'Settings'},
  'voice':           {keys:'Alt+J',       label:'Voice mode',                  session:true},
  'fullscreen':      {keys:'F11',         label:'Toggle fullscreen'},
  'help':            {keys:'Ctrl+/',      label:'Keyboard shortcuts'},
  'deck':            {keys:'Ctrl+Shift+D',label:'Show / hide the app deck'},
};
let SHORTCUTS=JSON.parse(JSON.stringify(SC_DEFAULTS));
function scLoad(){
  const saved=(cfg&&cfg.shortcuts)||{};
  Object.keys(SC_DEFAULTS).forEach(k=>{
    SHORTCUTS[k]={...SC_DEFAULTS[k],...(saved[k]?{keys:saved[k]}:{})};
  });
}
function scParse(keys){
  const p={ctrl:false,alt:false,shift:false,meta:false,key:''};
  String(keys||'').split('+').map(s=>s.trim()).filter(Boolean).forEach(part=>{
    const l=part.toLowerCase();
    if(l==='ctrl'||l==='control')p.ctrl=true;
    else if(l==='alt'||l==='option')p.alt=true;
    else if(l==='shift')p.shift=true;
    else if(l==='meta'||l==='cmd'||l==='super'||l==='win')p.meta=true;
    else p.key=part;
  });
  return p;
}
/* "Left" in a binding and "ArrowLeft" from the browser are the same key — one
   normaliser so the table can be written the way a person would say it. */
const SC_ALIAS={left:'arrowleft',right:'arrowright',up:'arrowup',down:'arrowdown',
  esc:'escape',ret:'enter',return:'enter',del:'delete',ins:'insert',
  pgup:'pageup',pgdn:'pagedown','↑':'arrowup','↓':'arrowdown','←':'arrowleft','→':'arrowright'};
function scKeyName(k){k=String(k||'').toLowerCase();return SC_ALIAS[k]||k}
function scMatch(e,keys){
  const p=scParse(keys);if(!p.key)return false;
  // Cmd and Ctrl are interchangeable so the same table feels native on a Mac
  const modOk=(p.ctrl?(e.ctrlKey||e.metaKey):(p.meta?e.metaKey:!e.ctrlKey&&!e.metaKey))
    &&(!!p.alt===!!e.altKey)&&(!!p.shift===!!e.shiftKey);
  if(!modOk)return false;
  const want=scKeyName(p.key);
  if(want==='space')return e.code==='Space';
  return scKeyName(e.key)===want||(e.code||'').toLowerCase()==='key'+want;
}
const SC_ACTIONS={
  'omnibar.focus':()=>omniFocus(),
  'omnibar.focus2':()=>omniFocus(),
  'palette':()=>omniFocus(),
  'expose':()=>exposeToggle(),
  'expose.f3':()=>exposeToggle(),
  'windows.arrange':()=>arrangeWindows(),
  'desktop.prev':()=>switchDeskBy(-1),
  'desktop.next':()=>switchDeskBy(1),
  'desktop.move.prev':()=>moveActiveDeskBy(-1),
  'desktop.move.next':()=>moveActiveDeskBy(1),
  'switcher':e=>switcherOpen(e&&e.shiftKey?-1:1),
  'window.close':()=>{const a=activeWin();if(a)closeWin(a)},
  'window.minimize':()=>{const a=activeWin();if(a)minimizeWin(a)},
  'window.maximize':()=>{const a=activeWin();if(a)toggleMax(a)},
  'chat.new':()=>{openApp('chat');newChat()},
  'chat.open':()=>openApp('chat'),
  'agent.stop':()=>stopAllAgents(),   // works while typing, in any app, in any window
  'copilot':()=>{                     // works in full screen too — the panel is inside the window
    const a=activeWin();
    if(a)toggleCopilot(a);else omniFocus();
  },
  'terminal':()=>{omniPop(false);openApp('terminal')},
  'settings':()=>openApp('settings'),
  'voice':()=>jarvisMode(!JARVIS.on),
  'fullscreen':()=>toggleFullscreen(),
  'help':()=>keysHelp(),
  'deck':()=>deckToggle(),
  // named so hot corners and automation steps reach exactly the same behaviours
  // the keyboard does — one vocabulary, three ways to trigger it
  'showdesktop':()=>toggleShowDesktop(),
  'launcher':()=>toggleStart(),
  'control':()=>toggleControlCenter(),
  'notifications':()=>openNotifPanel(),
};
function scRun(name,e){const f=SC_ACTIONS[name];if(f){f(e);return true}return false}

document.addEventListener('keyup',e=>{if(e.key==='Control'||e.key==='Meta'||e.key==='Alt')switcherCommit()});
document.addEventListener('keydown',e=>{
  const inTerm=e.target.closest&&e.target.closest('.xterm');
  // "Typing" means a field with something in it. The prompt bar holds the caret
  // by default, so treating an EMPTY bar as typing would mute every desktop
  // shortcut on a fresh desktop — which is where you need them most.
  const el=document.activeElement;
  const inField=/^(input|textarea|select)$/i.test((el&&el.tagName)||'')||!!(el&&el.isContentEditable);
  const idleBar=el&&el.id==='omni-in'&&!el.value&&!(typeof OMNI!=='undefined'&&OMNI.pop);
  const typing=inField&&!idleBar;
  if(SC_REC)return;                       // a Settings row is recording a new binding
  // window switcher first: Alt+Tab is also accepted (sway forwards it in session mode)
  if((cmd(e)||e.altKey)&&e.key==='Tab'){e.preventDefault();switcherOpen(e.shiftKey?-1:1);return}
  const fsw=[...WM.wins.values()].find(w=>w.fs);
  if((e.key==='Escape'||(e.key.toLowerCase()==='f'&&!typing&&!inTerm))&&fsw){e.preventDefault();toggleFullWin(fsw);return}
  if(e.key==='Escape'){if(EXPO.on){exposeToggle(false);return}if(SW.open){switcherCommit();return}
    if($('#keyshelp').classList.contains('show')){keysHelp(false);return}}
  if(e.key==='?'&&!typing){e.preventDefault();keysHelp();return}
  if(cmd(e)&&!e.altKey&&e.key.toLowerCase()==='a'&&!typing&&!inTerm&&!activeWin()){
    e.preventDefault();launcherIds().forEach(id=>setSel(id,true));return}
  // everything else comes from the (editable) table
  for(const name in SHORTCUTS){
    const sc=SHORTCUTS[name];
    if(!scMatch(e,sc.keys))continue;
    // window actions need a window; typing surfaces keep their own text editing keys
    if(name.startsWith('window.')&&!activeWin())continue;
    // Ctrl+←/→ is word-jump inside text; these bindings stand aside while typing
    if(sc.typing===false&&(typing||inTerm))continue;
    if(name==='agent.stop'){e.preventDefault();scRun(name,e);return}   // never blocked
    if(inTerm&&!['omnibar.focus','omnibar.focus2','palette','chat.open','expose','fullscreen','help'].includes(name))continue;
    e.preventDefault();scRun(name,e);return;
  }
  if(e.ctrlKey&&!e.shiftKey&&!e.altKey&&/^[1-9]$/.test(e.key)&&!inTerm){
    const n=+e.key;if(n<=DESKS){e.preventDefault();switchDesk(n)}}
});


/* ---- the session's Alt-Tab overlay -------------------------------------
   In session mode the compositor owns Alt-Tab, so the shell cannot see the key
   at all — it is told what to draw. Same overlay as the in-shell switcher, fed
   from the server's ring (the AgentOS desktop, then every native window). */
function sessionSwitcher(ev){
  const box=$('#switcher');if(!box)return;
  if(!ev.open){box.classList.remove('show');return}
  const ring=ev.ring||[];
  $('#swbox').innerHTML=ring.map((w,i)=>{
    const icon=w.shell?appIcon('chat',48)
      :(typeof natIcon==='function'?natIcon(w,48):emojiIcon('▭',48));
    const name=w.shell?'Desktop'
      :((typeof natName==='function'?natName(w):w.app)||w.title||'window');
    return `<div class="swcard${i===ev.idx?' sel':''}">${icon}<span class="sn">${esc(name)}</span></div>`;
  }).join('');
  box.classList.add('show');
}
