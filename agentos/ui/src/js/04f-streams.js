/* ---------------- live windows: a real process, drawn here, steered from here ----------------
   A window on this desktop used to be HTML pretending to be an app. A LIVE window is a
   picture of a real process (the shared Chromium, a native app on this machine) with the
   person's pointer and keys sent back to it, and the agent's hand drawn on top when it
   acts in the same window. `streamView` is that one component; the Browser and the app
   streams (04g) are thin shells round it, so a new kind of stream gets pointer, keyboard,
   touch, resize, the agent's cursor and "needs you" for free.

   The wire: binary messages are JPEG/PNG frames, text messages are JSON (state, the
   agent's hand, notices). Input goes back as JSON ops the server maps to the process
   (cdpbrowser.Browser.person, appstream.Stream.person).

   Faces: GUI and SUI are this. On a phone a tap is a click and the ⌨ button opens the
   keyboard. TUI: a terminal cannot draw pixels; the agent's tools reach the same browser
   and apps (`browser_*`), and `bento browser` says what it shows. */
var STREAM_MODS={Alt:1,Control:2,Meta:4,Shift:8};
var STREAM_KEYS=['Enter','Tab','Escape','Backspace','Delete','ArrowUp','ArrowDown','ArrowLeft','ArrowRight',
  'Home','End','PageUp','PageDown'];

function streamMods(e){return (e.altKey?1:0)|(e.ctrlKey?2:0)|(e.metaKey?4:0)|(e.shiftKey?8:0)}

function streamView(holder,opts){
  holder.classList.add('sv');
  holder.innerHTML=`<canvas class="sv-cv" tabindex="0" aria-label="${esc(opts.label||'live window')}"></canvas>
    <div class="sv-hand" aria-hidden="true"></div><div class="sv-note" hidden></div>
    <input class="sv-kb" autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false" aria-hidden="true">`;
  const cv=holder.querySelector('.sv-cv'),ctx=cv.getContext('2d'),hand=holder.querySelector('.sv-hand'),
        note=holder.querySelector('.sv-note'),kb=holder.querySelector('.sv-kb');
  const S={remote:[0,0],closed:false,frames:0,lastMove:0};
  const proto=location.protocol==='https:'?'wss://':'ws://';
  const ws=new WebSocket(proto+location.host+opts.path);ws.binaryType='blob';
  const send=op=>{if(ws.readyState===1)ws.send(JSON.stringify(op))};
  // the LAYOUT size: a window opening is scaled by a transform, and the box it reports then
  // made the remote page 320x240 for good (a transform never fires the ResizeObserver)
  const size=()=>[Math.max(320,holder.clientWidth|0),Math.max(240,holder.clientHeight|0)];
  ws.onopen=()=>{const [w,h]=size();ws.send(JSON.stringify(Object.assign({type:'hello',w,h},opts.hello||{})))};
  ws.onmessage=async e=>{
    if(typeof e.data!=='string'){
      try{const bm=await createImageBitmap(e.data);
        if(cv.width!==bm.width||cv.height!==bm.height){cv.width=bm.width;cv.height=bm.height}
        S.remote=[bm.width,bm.height];ctx.drawImage(bm,0,0);bm.close&&bm.close();S.frames++;
        holder.classList.add('live')}catch(err){}
      return;
    }
    let m;try{m=JSON.parse(e.data)}catch(err){return}
    if(m.type==='agent')streamHand(hand,cv,S,m);
    else if(m.type==='notice'){note.textContent=m.text;note.hidden=false;clearTimeout(S.nt);S.nt=setTimeout(()=>{note.hidden=true},5000)}
    else if(m.type==='error'){holder.classList.remove('live');opts.onError&&opts.onError(m.text)}
    if(m.size)S.remote=m.size;
    opts.onMessage&&opts.onMessage(m);
  };
  ws.onclose=()=>{S.closed=true;holder.classList.remove('live');opts.onClose&&opts.onClose()};
  // where on the remote page a point on the canvas is
  const at=e=>{const r=cv.getBoundingClientRect(),[W,H]=S.remote[0]?S.remote:[cv.width,cv.height];
    return {x:Math.round((e.clientX-r.left)*W/r.width),y:Math.round((e.clientY-r.top)*H/r.height)}};
  const btn=b=>b===2?'right':b===1?'middle':'left';
  cv.addEventListener('pointerdown',e=>{cv.focus();cv.setPointerCapture&&cv.setPointerCapture(e.pointerId);
    send(Object.assign({type:'mouse',kind:'mousePressed',button:btn(e.button),clicks:e.detail||1,mods:streamMods(e)},at(e)));e.preventDefault()});
  cv.addEventListener('pointerup',e=>{send(Object.assign({type:'mouse',kind:'mouseReleased',button:btn(e.button),clicks:e.detail||1,mods:streamMods(e)},at(e)))});
  cv.addEventListener('pointermove',e=>{const now=performance.now();if(now-S.lastMove<33)return;S.lastMove=now;
    send(Object.assign({type:'mouse',kind:'mouseMoved',buttons:e.buttons,button:e.buttons?'left':'none'},at(e)))});
  cv.addEventListener('wheel',e=>{send(Object.assign({type:'wheel',dx:e.deltaX,dy:e.deltaY},at(e)));e.preventDefault()},{passive:false});
  cv.addEventListener('contextmenu',e=>e.preventDefault());
  const key=e=>{
    if(STREAM_KEYS.includes(e.key)||((e.ctrlKey||e.metaKey)&&e.key.length===1)){send({type:'key',key:e.key,mods:streamMods(e)});e.preventDefault();return}
    if(e.key===' '){send({type:'key',key:' '});e.preventDefault();return}
    if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){send({type:'text',text:e.key});e.preventDefault()}
  };
  cv.addEventListener('keydown',key);
  cv.addEventListener('paste',e=>{const t=(e.clipboardData||window.clipboardData).getData('text');if(t)send({type:'text',text:t});e.preventDefault()});
  // a phone's keyboard opens only for a real input: this one is off-screen and forwards
  kb.addEventListener('input',()=>{if(kb.value){send({type:'text',text:kb.value});kb.value=''}});
  kb.addEventListener('keydown',e=>{if(STREAM_KEYS.includes(e.key)){send({type:'key',key:e.key});e.preventDefault()}});
  let rt=0;const ro=new ResizeObserver(()=>{clearTimeout(rt);rt=setTimeout(()=>{const [w,h]=size();send({type:'resize',w,h})},250)});
  ro.observe(holder);
  return {ws,send,keyboard:()=>{kb.focus()},frames:()=>S.frames,
    destroy(){try{ro.disconnect();ws.close()}catch(e){}}};
}
/* The agent's hand: a ring where it clicked and a line saying what it did, so a page
   that moves on its own is never a surprise. */
function streamHand(hand,cv,S,m){
  const r=cv.getBoundingClientRect(),hr=hand.getBoundingClientRect(),[W,H]=S.remote[0]?S.remote:[cv.width,cv.height];
  const say=m.kind==='click'?`${m.who||'Agent'} clicked${m.label?' “'+m.label+'”':''}`:
            m.kind==='type'?(m.who==='phone'?'Typing the code from your phone':`${m.who||'Agent'} is typing`):`${m.who||'Agent'} pressed ${m.text||'a key'}`;
  const d=document.createElement('div');d.className='sv-tap '+(m.kind||'');
  if(m.x!=null&&m.y!=null){d.style.left=(r.left-hr.left+m.x*r.width/W)+'px';d.style.top=(r.top-hr.top+m.y*r.height/H)+'px'}
  else{d.style.left='50%';d.style.top='18px';d.classList.add('nopos')}
  d.innerHTML=`<i></i><span>${esc(say)}</span>`;
  hand.appendChild(d);setTimeout(()=>d.remove(),2600);
}

/* ---------------- the shared browser window ---------------- */
var BROWSER_STATE={status:null};
async function renderBrowser(body,w){
  let st=BROWSER_STATE.status;
  if(!st){try{st=BROWSER_STATE.status=await apiJSON('/api/browser')}catch(e){st={ok:false,why:e.message}}}
  if(!st.ok)return renderWebLauncher(body,w,st.why);
  body.innerHTML=`<div class="bw">
    <div class="bw-bar">
      <button class="bw-b" data-op="back" title="Back" aria-label="Back">‹</button>
      <button class="bw-b" data-op="forward" title="Forward" aria-label="Forward">›</button>
      <button class="bw-b" data-op="reload" title="Reload" aria-label="Reload">⟳</button>
      <input class="bw-url" placeholder="Search or type an address" aria-label="Address" autocapitalize="off" spellcheck="false">
      <button class="bw-b bw-kb" title="Keyboard" aria-label="Open the keyboard">⌨</button>
      <button class="bw-b bw-ext" title="Open this page in your own browser" aria-label="Open in your own browser">↗</button>
    </div>
    <div class="bw-tabs" role="tablist"></div>
    <div class="bw-ask" hidden></div>
    <div class="bw-view"></div>
    <div class="bw-foot mut"><span class="bw-who"></span></div>
  </div>`;
  const q=s=>body.querySelector(s),view=q('.bw-view'),url=q('.bw-url'),ask=q('.bw-ask');
  const start=w._pending||'';w._pending=null;
  const sv=streamView(view,{path:'/ws/browser',label:'the shared browser',hello:start?{url:start}:{},
    onMessage:m=>{if(m.type==='state')browserPaint(w,m)},
    onError:t=>{view.innerHTML=emptyBox('The browser could not start',esc(t))}});
  w.sv=sv;
  body.querySelectorAll('[data-op]').forEach(b=>b.onclick=()=>sv.send({type:b.dataset.op}));
  url.addEventListener('keydown',e=>{if(e.key==='Enter'){sv.send({type:'navigate',url:url.value});view.querySelector('.sv-cv')?.focus()}});
  q('.bw-kb').onclick=()=>sv.keyboard();
  q('.bw-ext').onclick=()=>{const u=w._url||'';if(/^https?:/.test(u))openHost({url:u});else toast('Nothing to open yet')};
  ask.addEventListener('click',e=>{if(e.target.closest('.bw-done')){sv.send({type:'resume'})}});
}
function browserPaint(w,m){
  const body=w.el.querySelector('.wbody');if(!body)return;
  const q=s=>body.querySelector(s);
  w._url=m.url||'';
  const url=q('.bw-url');if(url&&document.activeElement!==url)url.value=m.url&&m.url!=='about:blank'?m.url:'';
  const tabs=q('.bw-tabs');
  if(tabs)tabs.innerHTML=(m.tabs||[]).map(t=>`<button class="bw-tab${t.active?' on':''}" role="tab" aria-selected="${t.active}" data-id="${esc(t.id)}" title="${esc(t.url)}">
      <span>${esc(t.title||'New tab')}</span>${(m.tabs||[]).length>1?`<i data-close="${esc(t.id)}" aria-label="Close tab">✕</i>`:''}</button>`).join('')
    +`<button class="bw-tab bw-new" aria-label="New tab">＋</button>`;
  tabs&&tabs.querySelectorAll('.bw-tab').forEach(b=>b.onclick=e=>{
    const c=e.target.closest('[data-close]');
    if(c)w.sv.send({type:'tab_close',id:c.dataset.close});
    else if(b.classList.contains('bw-new'))w.sv.send({type:'tab_new'});
    else w.sv.send({type:'tab_switch',id:b.dataset.id})});
  const ask=q('.bw-ask'),a=m.attention;
  if(ask){
    ask.hidden=!a;
    if(a)ask.innerHTML=`<span class="bw-ask-ic">${a.kind==='captcha'?'🧩':a.kind==='code'?'🔢':a.kind==='login'?'🔐':'✋'}</span>
      <div><b>${esc((typeof agentName==='function'&&agentName())||'Your agent')} needs you here</b>
      <span>${esc(a.reason||('This page wants '+(a.why||'a person')+'.'))} Do it in the page below, then press Done.</span></div>
      <button class="pact bw-done">Done, carry on</button>`;
  }
  winNeedsYou('browser',!!a,a&&(a.site||''));
  const who=q('.bw-who');if(who)who.textContent=m.title?m.title:'';
}
/* The browser needs the person and its window may not be open: open it, or offer to. */
function browserAttention(ev){
  const open=winsOf('browser').length>0;
  winNeedsYou('browser',true,ev.site||'');
  // the same wall is announced when the agent meets it and again when it starts waiting:
  // one toast, not a stack of the same sentence
  const key=(ev.kind||'')+'|'+(ev.site||''),now=Date.now();
  if(BROWSER_STATE.asked===key&&now-(BROWSER_STATE.askedAt||0)<60000)return;
  BROWSER_STATE.asked=key;BROWSER_STATE.askedAt=now;
  const what=ev.kind==='captcha'?'a CAPTCHA':ev.kind==='code'?'a sign-in code':ev.kind==='login'?'a sign-in':'your help';
  toast(`${(typeof agentName==='function'&&agentName())||'Your agent'} needs ${what} in the browser${ev.site?' on '+ev.site:''}`,
    {kind:'warn',label:open?'Show':'Open',go:()=>openApp('browser')});
  if(typeof suiAttention==='function')suiAttention();
}

/* ---------------- a native app in a window (agentos/appstream.py) ---------------- */
var APPWIN={next:null,status:null};
async function appStreamStatus(){
  if(APPWIN.status)return APPWIN.status;
  try{APPWIN.status=await apiJSON('/api/appstreams')}catch(e){APPWIN.status={ok:false,why:e.message}}
  return APPWIN.status;
}
/* Open an installed app in a Bento window: started in its own display on this machine,
   drawn here. The way a phone or a laptop in another room sees a native app at all. */
async function openAppWindow(app,title){
  const st=await appStreamStatus();
  if(!st.ok){toast(st.why||'Apps cannot be shown in windows here',{kind:'warn'});return null}
  const box=document.getElementById('desktop')||document.body,r=box.getBoundingClientRect();
  try{
    const d=await apiJSON('/api/appstreams',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({app,w:Math.min(1280,Math.round(r.width*.7)),h:Math.min(800,Math.round(r.height*.7))})});
    return showAppWindow(d.id,d.title||title||app);
  }catch(e){toast('Could not open it: '+e.message,{kind:'err'});return null}
}
function showAppWindow(id,title){
  const have=winsOf('appwindow').find(w=>w._sid===id);
  if(have){focusWin(have);return have}
  APPWIN.next={id,title};
  return openApp('appwindow',{fresh:true});
}
function renderAppWindow(body,w){
  if(!w._sid&&APPWIN.next){w._sid=APPWIN.next.id;w._title=APPWIN.next.title;APPWIN.next=null}
  const t=w.el.querySelector('.tname');if(t&&w._title)t.textContent=w._title;
  if(!w._sid){body.innerHTML=emptyBox('No app here','Open one from the Apps launcher with “In a window”.');return}
  body.innerHTML='<div class="aw"><div class="aw-view"></div></div>';
  w.sv=streamView(body.querySelector('.aw-view'),{path:'/ws/appstream?id='+encodeURIComponent(w._sid),label:w._title||'app',
    onMessage:m=>{if(m.type==='ended'){body.innerHTML=emptyBox('This app has closed','Open it again from the Apps launcher.')}},
    onError:t=>{body.innerHTML=emptyBox('This app is not open any more',esc(t))}});
}
