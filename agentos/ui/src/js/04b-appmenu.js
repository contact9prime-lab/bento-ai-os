/* ================= application menus =================
   Every window gets File · Edit · View · Window · Help in the menu bar, the way
   a desktop application is expected to. The set is generated for the focused
   window, so it is never stale and no app has to opt in; an app can add its own
   entries by declaring APPS[id].menus(w) — those are merged, not replacing the
   basics. Edit acts on whatever has the caret, which is what makes Copy/Paste
   behave like the rest of the system. */

function menuStd(w){
  const app=w&&w.app, id=w&&w.id;
  const has=sel=>!!(w&&w.el.querySelector(sel));
  const file=[];
  if(app&&app.multi)file.push({label:'New window',keys:'',fn:()=>openAppNew(id)});
  file.push({label:'New chat',fn:()=>{openApp('chat');newChat()}});
  if(has('.psearch input'))file.push({label:'Find in this app',keys:'',fn:()=>{
    const i=w.el.querySelector('.psearch input');if(i)i.focus()}});
  file.push(null,
    {label:'Take a screenshot',fn:()=>takeScreenshot('full')},
    {label:'Close window',keys:(SHORTCUTS['window.close']||{}).keys,fn:()=>closeWin(w)});

  const edit=[
    {label:'Undo',keys:'Ctrl+Z',fn:()=>document.execCommand('undo')},
    {label:'Redo',keys:'Ctrl+Shift+Z',fn:()=>document.execCommand('redo')},
    null,
    {label:'Cut',keys:'Ctrl+X',fn:()=>editDo('cut')},
    {label:'Copy',keys:'Ctrl+C',fn:()=>editDo('copy')},
    {label:'Paste',keys:'Ctrl+V',fn:()=>editPaste()},
    {label:'Select all',keys:'Ctrl+A',fn:()=>document.execCommand('selectAll')},
  ];

  const view=[
    {label:'Reload this app',fn:()=>refreshApp(id)},
    {label:w&&w.fs?'Leave full screen':'Full screen',keys:'',fn:()=>toggleFullWin(w)},
    {label:w&&w.max?'Restore size':'Maximize',keys:(SHORTCUTS['window.maximize']||{}).keys,fn:()=>toggleMax(w)},
    null,
    {label:(w&&w.el.querySelector('.copanel.open'))?'Hide the agent panel':'Ask the agent about this app',
     keys:(SHORTCUTS['copilot']||{}).keys,fn:()=>toggleCopilot(w)},
    {label:'Spaces overview',keys:(SHORTCUTS['expose']||{}).keys,fn:()=>exposeToggle(true)},
  ];

  const win=[
    {label:'Minimize',keys:(SHORTCUTS['window.minimize']||{}).keys,fn:()=>minimizeWin(w)},
    {label:'Tile left',fn:()=>tileWin(w,'left')},
    {label:'Tile right',fn:()=>tileWin(w,'right')},
    {label:'Centre',fn:()=>tileWin(w,'centre')},
    {label:'Organise all windows',keys:(SHORTCUTS['windows.arrange']||{}).keys,fn:()=>arrangeWindows()},
  ];
  if(DESKS>1){
    win.push(null);
    for(let n=1;n<=DESKS;n++)if(n!==w.desk)
      win.push({label:'Move to Desktop '+n,fn:()=>{w.desk=n;applyDeskVisibility();buildPager();toast('moved to Desktop '+n)}});
  }
  const openWins=[];WM.wins.forEach(o=>{if(o!==w&&!o.min)openWins.push(o)});
  if(openWins.length){
    win.push(null);
    openWins.slice(0,8).forEach(o=>win.push({label:o.app.title,fn:()=>focusWin(o)}));
  }

  const help=[
    {label:'Keyboard shortcuts',keys:(SHORTCUTS['help']||{}).keys,fn:()=>keysHelp(true)},
    {label:'Bento Box AI manual',fn:()=>openApp('docs')},
    {label:`Ask ${agentName()} about ${app?app.title:'this app'}`,fn:()=>copilotAsk(id,'')},
    null,
    {label:'About Bento Box AI',fn:()=>openApp('about')},
  ];

  const menus=[['File',file],['Edit',edit],['View',view],['Window',win],['Help',help]];
  // an app's own menus merge into the standard ones (or add a new menu)
  let extra=[];
  try{extra=(app&&app.menus)?app.menus(w)||[]:[]}catch(e){}
  extra.forEach(([title,items])=>{
    const hit=menus.find(m=>m[0].toLowerCase()===String(title).toLowerCase());
    if(hit)hit[1]=items.concat([null],hit[1]);
    else menus.splice(menus.length-1,0,[title,items]);
  });
  return menus;
}
function editDo(cmd){
  const el=document.activeElement;
  if(el&&/^(input|textarea)$/i.test(el.tagName||''))el.focus();
  if(!document.execCommand(cmd))toast('nothing selected');
}
async function editPaste(){
  const el=document.activeElement;
  if(!el||!/^(input|textarea)$/i.test(el.tagName||''))return toast('click into a text field first');
  try{
    const t=await navigator.clipboard.readText();
    const s=el.selectionStart??el.value.length, e=el.selectionEnd??s;
    el.value=el.value.slice(0,s)+t+el.value.slice(e);
    el.selectionStart=el.selectionEnd=s+t.length;
    el.dispatchEvent(new Event('input',{bubbles:true}));
  }catch(err){toast('press Ctrl+V — the browser kept the clipboard private')}
}
/* ---- native (external) windows get menus too -------------------------------
   We cannot reach inside someone else's app for its File and Edit, and
   pretending otherwise would be worse than useless. What we CAN offer is every
   verb the window manager owns — and saying so plainly, under the app's real
   name, is what makes an external app feel like part of the machine rather than
   a rectangle floating on top of it. */
function menuNative(w){
  const name=(typeof natName==='function'&&natName(w))||w.app||'Application';
  const app=[
    {label:'Show the desktop',keys:'Super+D',fn:showDesktop},
    {label:'Switch window',keys:'Alt+Tab',fn:()=>fetch('/api/windows/cycle',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({direction:'next'})})},
    null,
    {label:'Close '+name,keys:'Super+Q',danger:true,fn:()=>natWin('close',w.id)},
  ];
  const win=natWinItems(w).filter(it=>!it||it.label!=='Close window');
  const help=[
    {label:'Keyboard shortcuts',keys:(SHORTCUTS['help']||{}).keys,fn:()=>{
      raiseShell(true);keysHelp(true)}},
    {label:`Ask ${agentName()} about ${name}`,fn:()=>{raiseShell(true);
      omniFocus&&omniFocus();const i=$('#omni-in');if(i){i.value='About the '+name+' window: ';omniPop(true)}}},
    null,
    {label:'Bento Box AI desktop',keys:(SHORTCUTS['omnibar.focus']||{}).keys,fn:()=>raiseShell(true)},
  ];
  return [[name,app],['Window',win],['Help',help]];
}
/* Bring the AgentOS desktop in front of the native windows (or send it back).

   In the session UI this is a one-call layer change on our own surface — the
   desktop lives on the BACKGROUND layer, coming forward means OVERLAY, and
   nothing else on the screen is touched.

   The HTTP path below is for the older Chromium-rendered session, where the
   desktop is a WINDOW and "in front" has to be faked by floating it at the size
   of the output and lowering it again. That is the trade the layer-shell host
   exists to remove; it stays for machines without WebKitGTK. */
function raiseShell(on){
  if(typeof suiRaise==='function'&&suiRaise(on))return Promise.resolve();
  if(PLATFORM.mode!=='de')return Promise.resolve();
  return fetch('/api/shell/raise',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({on:on!==false})}).catch(()=>{});
}
/* ---- the menu bar renders the focused window's menus ---- */
function buildAppMenus(){
  const box=$('#mbmenus');if(!box)return;
  // The COMPOSITOR's focus is the truth, not the shell's idea of it. A focused
  // external window owns the bar even while an AgentOS window is still marked
  // active inside the page — otherwise the bar says "Task Manager" while you are
  // typing in VS Code.
  const nat=(typeof natFocused==='function')?natFocused():null;
  const w=nat?null:((typeof activeWin==='function')&&activeWin());
  const label=$('#mbapp');
  if(label&&label.dataset.native){label.textContent='';delete label.dataset.native}
  if(!w&&!nat){box.innerHTML='';box.classList.remove('on');return}
  if(nat){
    if(label){label.textContent=natName(nat);label.dataset.native='1'}
    box.classList.add('on');
    paintMenuBar(box,menuNative(nat),()=>menuNative(natFocused()||nat));
    return;
  }
  const menus=menuStd(w);
  box.classList.add('on');
  // recomputed on open, not on focus: an app that renders asynchronously (or has
  // since changed folder / tab) gets menus that describe it as it is now
  paintMenuBar(box,menus,()=>(activeWin()===w?menuStd(w):menus));
}
function paintMenuBar(box,menus,live){
  box.innerHTML=menus.map(([title],i)=>`<button data-i="${i}">${esc(title)}</button>`).join('');
  box.querySelectorAll('button').forEach(b=>{
    const open=()=>{
      const r=b.getBoundingClientRect();
      box.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
      let set=menus;
      try{set=live()||menus}catch(e){}
      const items=(set[+b.dataset.i]||menus[+b.dataset.i])[1];
      showCtxItems({clientX:r.left,clientY:r.bottom+2,preventDefault(){}},
        items.map(it=>it&&({...it,
          label:it.keys?`${it.label}<span class="mk">${esc(it.keys)}</span>`:it.label})));
      const clear=()=>{b.classList.remove('on');document.removeEventListener('click',clear,true)};
      setTimeout(()=>document.addEventListener('click',clear,true),0);
    };
    b.onclick=open;
    b.onmouseenter=()=>{if(box.querySelector('button.on'))open()};   // slide across like a real menu bar
  });
}
