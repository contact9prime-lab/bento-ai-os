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
    {label:'AgentOS manual',fn:()=>openApp('docs')},
    {label:`Ask ${agentName()} about ${app?app.title:'this app'}`,fn:()=>copilotAsk(id,'')},
    null,
    {label:'About AgentOS',fn:()=>openApp('about')},
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
/* ---- the menu bar renders the focused window's menus ---- */
function buildAppMenus(){
  const box=$('#mbmenus');if(!box)return;
  const w=(typeof activeWin==='function')&&activeWin();
  if(!w){box.innerHTML='';box.classList.remove('on');return}
  const menus=menuStd(w);
  box.classList.add('on');
  box.innerHTML=menus.map(([title],i)=>`<button data-i="${i}">${esc(title)}</button>`).join('');
  box.querySelectorAll('button').forEach(b=>{
    const open=()=>{
      const r=b.getBoundingClientRect();
      box.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
      // recomputed on open, not on focus: an app that renders asynchronously (or
      // has since changed folder / tab) gets menus that describe it as it is now
      const live=(activeWin()===w?menuStd(w):menus)[+b.dataset.i][1];
      showCtxItems({clientX:r.left,clientY:r.bottom+2,preventDefault(){}},
        live.map(it=>it&&({...it,
          label:it.keys?`${it.label}<span class="mk">${esc(it.keys)}</span>`:it.label})));
      const m=$('#ctxmenu');
      const clear=()=>{b.classList.remove('on');document.removeEventListener('click',clear,true)};
      setTimeout(()=>document.addEventListener('click',clear,true),0);
    };
    b.onclick=open;
    b.onmouseenter=()=>{if(box.querySelector('button.on'))open()};   // slide across like a real menu bar
  });
}
