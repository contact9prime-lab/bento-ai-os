/* ================= themes ================= */
// A theme is not just colors — it can carry a web font and extra CSS that restyles the whole
// desktop (taskbar, windows, icons, widgets). Built-in themes:
const THEMES={
  agentos:{label:'AgentOS (teal)',mode:'dark',v:{bg:'#0b0d10',bg2:'#111419',bg3:'#171b22',bg4:'#1e242e',line:'#232a35',txt:'#e6ebf2',dim:'#8a94a6',dim2:'#5c6577',acc:'#5eead4',acc2:'#22d3ee',warn:'#fbbf24',err:'#f87171',ok:'#4ade80',glass:'rgba(17,20,25,.82)'}},
  ubuntu:{label:'Ember (dark)',mode:'dark',v:{bg:'#1c1a1b',bg2:'#242021',bg3:'#2c2727',bg4:'#383231',line:'#3a3433',txt:'#ffffff',dim:'#c7c2bf',dim2:'#8f8987',acc:'#E95420',acc2:'#F29879',warn:'#f9c74f',err:'#f87171',ok:'#26a269',glass:'rgba(36,32,33,.86)'}},
  'ubuntu-light':{label:'Ember (light)',mode:'light',v:{bg:'#faf9f8',bg2:'#f2f0ee',bg3:'#ecebe9',bg4:'#e0ddda',line:'#d3cfcb',txt:'#1d1b19',dim:'#5e5b58',dim2:'#8f8b87',acc:'#E95420',acc2:'#c7451d',warn:'#b98900',err:'#c01c28',ok:'#26a269',glass:'rgba(245,243,241,.92)'}},
  dracula:{label:'Dracula',mode:'dark',v:{bg:'#191a21',bg2:'#21222c',bg3:'#282a36',bg4:'#343746',line:'#3b3d4d',txt:'#f8f8f2',dim:'#b8bcc8',dim2:'#6272a4',acc:'#bd93f9',acc2:'#ff79c6',warn:'#f1fa8c',err:'#ff5555',ok:'#50fa7b',glass:'rgba(33,34,44,.86)'}},
  nord:{label:'Nord',mode:'dark',v:{bg:'#242933',bg2:'#2e3440',bg3:'#3b4252',bg4:'#434c5e',line:'#4c566a',txt:'#eceff4',dim:'#d8dee9',dim2:'#7b88a1',acc:'#88c0d0',acc2:'#81a1c1',warn:'#ebcb8b',err:'#bf616a',ok:'#a3be8c',glass:'rgba(46,52,64,.86)'}},
  aero:{label:'Frost (glass)',mode:'dark',font:{url:'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600&display=swap',family:'Space Grotesk'},
    v:{bg:'#141628',bg2:'#1b2036',bg3:'#222844',bg4:'#2b3352',line:'#3a4470',txt:'#eef1f8',dim:'#aab2c8',dim2:'#6b7699',acc:'#7aa2f7',acc2:'#b892f6',warn:'#f6c177',err:'#f26d6d',ok:'#7bd88f',glass:'rgba(28,32,52,.62)'},
    css:`#desktop{background:radial-gradient(1200px 700px at 70% 110%,rgba(150,90,220,.42),transparent 60%),radial-gradient(900px 600px at 15% -10%,rgba(70,120,230,.42),transparent 55%),linear-gradient(170deg,#181c30,#141628 45%,#201a33)}
#taskbar{background:rgba(20,24,40,.5);backdrop-filter:blur(24px)}
.win{background:rgba(28,32,52,.66)!important;backdrop-filter:blur(26px);border:1px solid rgba(255,255,255,.12)}
.win .ttl{background:rgba(255,255,255,.05)}
.dicon .aicon{box-shadow:0 10px 26px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.28)}
.widget{border:1px solid rgba(255,255,255,.12)}`},
  field:{label:'Field (warm light)',mode:'light',
    v:{bg:'#f6f2e9',bg2:'#fffdf7',bg3:'#f1ece0',bg4:'#e9e2d2',line:'#e4dcc9',txt:'#2b2620',dim:'#6f6656',dim2:'#8a8172',acc:'#b0693a',acc2:'#c98a4a',warn:'#b98900',err:'#c0492c',ok:'#5a8a3c',glass:'rgba(255,253,247,.92)'},
    css:`#desktop{background:linear-gradient(180deg,#f6f2e9,#f1ece0)}
#taskbar{background:#fffdf7;border-top:1px solid #e4dcc9}
.win{background:#fffdf7!important;border:1px solid #e4dcc9}
.win .ttl{background:#f7f2e6}
.dicon .aicon{box-shadow:0 3px 10px rgba(60,50,30,.14),inset 0 1px 0 rgba(255,255,255,.5)}`},
  shell:{label:'Shell (terminal)',mode:'dark',font:{url:'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap',family:'JetBrains Mono'},
    v:{bg:'#0a0e0b',bg2:'#0d130f',bg3:'#111a13',bg4:'#16231a',line:'#1e3323',txt:'#a7c4ad',dim:'#6f9578',dim2:'#46614d',acc:'#86efac',acc2:'#4ade80',warn:'#e3d34d',err:'#f87171',ok:'#4ade80',glass:'rgba(13,19,15,.9)'},
    css:`#desktop{background:#070a08}
#taskbar{background:#0a0e0b;border-top:1px solid #1e3323}
.win{background:#0a0e0b!important;border:1px solid #1e3323}
.win .ttl{background:#0d130f}
.dicon .aicon{border-radius:7px}
*{letter-spacing:.1px}`},
  jarvis:{label:'Aura (Voice OS)',mode:'dark',exp:'jarvis',font:{url:'https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=IBM+Plex+Mono:wght@400;500&display=swap',family:'IBM Plex Mono'},
    v:{bg:'#03060c',bg2:'#061019',bg3:'#0a1722',bg4:'#10222e',line:'#15353c',txt:'#c8e6f2',dim:'#6fa8b8',dim2:'#3d6a75',acc:'#5eead4',acc2:'#22d3ee',warn:'#f6c177',err:'#f87171',ok:'#4ade80',glass:'rgba(4,14,20,.78)'},
    css:`#desktop{background:radial-gradient(900px 600px at 72% 55%,rgba(30,74,94,.5),transparent 60%),linear-gradient(160deg,#040810,#03060c 60%,#051018)}
#taskbar{background:rgba(4,12,18,.72);backdrop-filter:blur(14px);border-top:1px solid rgba(94,234,212,.16)}
.win{background:rgba(6,16,24,.82)!important;backdrop-filter:blur(10px);border:1px solid rgba(94,234,212,.18);box-shadow:0 0 40px rgba(94,234,212,.07)}
.win.active{box-shadow:0 0 50px rgba(94,234,212,.14)}
.win .ttl{background:rgba(94,234,212,.04);border-bottom:1px solid rgba(94,234,212,.14)}
.win .tname{font-family:'Orbitron',sans-serif;letter-spacing:.12em;font-size:11px;text-transform:uppercase}
#welcome h1,#startbtn{font-family:'Orbitron',sans-serif;letter-spacing:.12em}
.widget{border:1px solid rgba(94,234,212,.18);box-shadow:0 0 26px rgba(94,234,212,.07)}
.dicon .aicon{border:1px solid rgba(94,234,212,.2);box-shadow:0 0 18px rgba(94,234,212,.16),inset 0 1px 0 rgba(255,255,255,.14)}
.dicon .dlbl{letter-spacing:.04em}
.tbwin.on{box-shadow:inset 0 -2px 0 var(--acc),0 0 14px rgba(94,234,212,.25)}`},
};
const CUSTOM_THEMES={};   // name -> theme object, loaded from the server
function allThemes(){const m={};for(const k in THEMES)m[k]={...THEMES[k],id:k};for(const n in CUSTOM_THEMES)m[n]={...CUSTOM_THEMES[n],id:n};return m}
let CURRENT_THEME=localStorage.getItem('theme')||'agentos';
function applyThemeObj(t){
  // crossfade the whole desktop through the theme change instead of hard-cutting
  if(document.startViewTransition&&!matchMedia('(prefers-reduced-motion: reduce)').matches&&document.body.dataset.themed){
    const apply=()=>_applyThemeObj(t);
    try{document.startViewTransition(apply);return}catch(e){}
  }
  document.body.dataset.themed='1';
  _applyThemeObj(t);
}
function _applyThemeObj(t){
  const r=document.documentElement,v=t.v||t.vars||{};
  Object.entries(v).forEach(([k,val])=>r.style.setProperty('--'+k,val));
  r.dataset.theme=(t.mode==='light')?'light':'dark';
  let fl=document.getElementById('theme-font');
  if(t.font&&t.font.url){
    if(!fl){fl=document.createElement('link');fl.id='theme-font';fl.rel='stylesheet';document.head.appendChild(fl)}
    fl.href=t.font.url;
    if(t.font.family)r.style.setProperty('--sans',"'"+t.font.family+"',system-ui,sans-serif");
  }else{if(fl)fl.remove();r.style.removeProperty('--sans')}
  let st=document.getElementById('theme-extra');
  if(!st){st=document.createElement('style');st.id='theme-extra';document.head.appendChild(st)}
  st.textContent=t.css||'';
  setExperience(t.shell?'custom':(t.exp||'standard'),t.shell);
}

/* ================= experience shells ================= */
let EXPERIENCE='standard';
function setExperience(exp,shellHtml){
  const cs=$('#custom-shell');
  if(exp==='custom'&&cs){
    // An AI-designed shell fully replaces the desktop. It runs in a same-origin iframe:
    // its scripts get their own global scope (no collisions with the desktop's globals)
    // while keeping full access to the REST API and the /ws websocket.
    try{
      cs.innerHTML='';
      const f=document.createElement('iframe');
      f.style.cssText='flex:1;width:100%;height:100%;border:none;background:var(--bg)';
      cs.appendChild(f);
      f.contentDocument.open();
      f.contentDocument.write(shellHtml||'');
      f.contentDocument.close();
    }catch(e){cs.innerHTML='';toast('shell failed to load: '+e.message);exp='standard'}
  }else if(cs){cs.innerHTML=''}
  if(exp===EXPERIENCE&&exp!=='custom')return;
  EXPERIENCE=exp;
  document.body.classList.toggle('exp-jarvis',exp==='jarvis');
  document.body.classList.toggle('exp-custom',exp==='custom');
  if(exp==='jarvis')buildJarvisShell();
  else{const sh=$('#jarvis-shell');if(sh){clearInterval(sh._t);sh.innerHTML=''}}
}
const JS_RING=['chat','models','scheduler','kg','memory','files','logs','terminal'];
function buildJarvisShell(){
  const sh=$('#jarvis-shell');if(!sh||!APPS_READY)return;   // APPS loads later; init re-builds
  sh.innerHTML=`
    <button id="js-exit" onclick="applyTheme('agentos')">⊞ Standard desktop</button>
    <div id="js-top">
      <div style="display:flex;align-items:center"><span class="brand">AGENTOS</span><span class="tag">VOICE CORE</span></div>
      <div class="stats"><span>MCP <b id="js-mcp">–</b></span><span>MODEL <b id="js-model">–</b></span><span id="js-clock">–</span></div>
    </div>
    <div id="js-mid">
      <div id="js-side">
        <div class="js-panel"><div class="h">VOICE LINK</div><div id="js-voice" style="font-size:13px;color:var(--acc)">tap the orb to speak</div></div>
        <div class="js-panel" style="flex:1;display:flex;flex-direction:column;min-height:0"><div class="h">ACTIVITY STREAM</div><div id="js-stream"></div></div>
      </div>
      <div id="js-stage">
        <div id="js-ring"></div>
        <div id="js-orb"><span class="rg a"></span><span class="rg b"></span><span class="rg c"></span><span class="core"></span><span class="lbl">TAP TO SPEAK</span></div>
      </div>
    </div>
    <div id="js-bottom"><div id="js-ask">
      <span style="color:var(--acc);font-size:15px">⌕</span>
      <input id="js-input" placeholder="Ask ${esc(agentName())} or search apps… (Enter)">
      <span class="mic" onclick="jarvisMode(true)">${svgMic(16)}</span>
    </div></div>`;
  // ring of app nodes
  const ring=$('#js-ring');
  JS_RING.forEach((id,i)=>{
    const a=APPS[id];if(!a)return;
    const ang=(i/JS_RING.length)*2*Math.PI - Math.PI/2;
    const rx=50+Math.cos(ang)*34, ry=50+Math.sin(ang)*40;   // % of stage
    const n=document.createElement('div');n.className='js-node';
    n.style.left=rx+'%';n.style.top=ry+'%';
    n.innerHTML=`${appIcon(id,36)}<span class="n">${esc(a.title)}</span>`;
    n.onclick=()=>openApp(id);
    ring.appendChild(n);
  });
  $('#js-orb').onclick=()=>jarvisMode(true);
  const inp=$('#js-input');
  inp.addEventListener('keydown',e=>{if(e.key==='Enter'){const q=inp.value.trim();if(!q)return;
    const app=Object.keys(APPS).find(k=>APPS[k].title.toLowerCase()===q.toLowerCase());
    if(app){openApp(app)}else{openApp('chat');if(input){input.value=q;input.dispatchEvent(new Event('input'));send()}}
    inp.value='';}});
  jarvisShellRefresh();
  clearInterval(sh._t);sh._t=setInterval(jarvisShellRefresh,4000);
}
async function jarvisShellRefresh(){
  if(EXPERIENCE!=='jarvis')return;
  const cl=$('#js-clock');if(cl)cl.textContent=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  const mo=$('#js-model');if(mo&&$('#modelsel'))mo.textContent=(($('#modelsel').value||'').split('/').pop()||'–').slice(0,14);
  try{const m=await (await fetch('/api/mcp')).json();const c=$('#js-mcp');if(c)c.textContent=(m.servers||[]).filter(s=>s.status==='connected').length}catch(e){}
  try{const d=await (await fetch('/api/logs?limit=8')).json();const s=$('#js-stream');
    if(s)s.innerHTML=(d.logs||[]).slice(0,8).map(l=>`<div class="ln"><span class="t">${new Date(l.created_at*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span><span>${esc((l.kind+' · '+l.message).slice(0,60))}</span></div>`).join('');
  }catch(e){}
}
function applyTheme(name){
  const t=allThemes()[name];if(!t)return;
  applyThemeObj(t);CURRENT_THEME=name;localStorage.setItem('theme',name);
}
async function loadThemes(){
  try{const d=await (await fetch('/api/themes')).json();
    for(const k in CUSTOM_THEMES)delete CUSTOM_THEMES[k];
    (d.themes||[]).forEach(t=>{CUSTOM_THEMES[t.name]=t});
  }catch(e){}
  if(allThemes()[CURRENT_THEME])applyTheme(CURRENT_THEME);   // re-apply if it's a custom theme
}
applyTheme(THEMES[CURRENT_THEME]?CURRENT_THEME:'agentos');

/* ================= fullscreen ================= */
function toggleFullscreen(){
  if(document.fullscreenElement)document.exitFullscreen();
  else document.documentElement.requestFullscreen?.().catch(()=>toast('fullscreen blocked by the browser'));
}

