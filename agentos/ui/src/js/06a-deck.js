/* ================= the deck: app tiles above the prompt bar =================
   The desktop is wallpaper, not a filing cabinet. Every app lives in a bento
   group inside one horizontally scrollable strip that sits directly above the
   omnibar — plus any widget you pin into it. Groups are yours: rename, create,
   move apps between them. Persisted in localStorage; nothing here is on the
   server, so it stays instant. */
const DECK_DEFAULTS=[
  ['Essentials',['chat','apps','browser','files','terminal']],
  ['Create',['store','studio','themes','personalize']],
  ['Intelligence',['models','memory','kg','soul','profile']],
  ['Automation',['fabric','tasks','skills','mcp','telegram']],
  ['System',['taskmgr','control','syssettings','settings','policies','permissions','snapshots','logs','tokens']],
  ['Library',['docs','mission','train','hermes','about']],
];
let DECK=null;
function deckLoad(){
  try{DECK=JSON.parse(localStorage.getItem('deck')||'null')}catch(e){DECK=null}
  if(!DECK||!Array.isArray(DECK.groups))
    DECK={open:true,groups:DECK_DEFAULTS.map(([name,apps],i)=>({id:'g'+i,name,apps:apps.slice()}))};
  if(DECK.open===undefined)DECK.open=true;
  if(DECK.auto===undefined)DECK.auto=true;   // step aside while you're working in a window
  return DECK;
}
function deckSave(){localStorage.setItem('deck',JSON.stringify(DECK))}
function deckGroupOf(id){return DECK.groups.find(g=>g.apps.includes(id))}
/* every launchable app has a home: new built-ins land in More, user apps in Your apps */
function deckReconcile(){
  const ids=(typeof launcherIds==='function'?launcherIds():Object.keys(APPS)).filter(id=>APPS[id]);
  DECK.groups.forEach(g=>g.apps=g.apps.filter(id=>APPS[id]));
  const homeless=ids.filter(id=>!deckGroupOf(id));
  if(homeless.length){
    const ua=homeless.filter(id=>id.startsWith('ua_')), rest=homeless.filter(id=>!id.startsWith('ua_'));
    const into=(name,list)=>{
      if(!list.length)return;
      let g=DECK.groups.find(x=>x.name===name);
      if(!g){g={id:'g'+Date.now().toString(36),name,apps:[]};DECK.groups.push(g)}
      g.apps.push(...list);
    };
    into('Your apps',ua); into('More',rest);
  }
  DECK.groups=DECK.groups.filter(g=>g.apps.length||g.widget);
  deckSave();
}
/* auto mode: the deck shows on a bare desktop and gets out of the way the
   moment a window is in use. Toggling it by hand pins that choice. */
/* Which desktops carry the deck is a per-desktop choice: Desktop 1 is the
   launcher by default, the rest start clear so windows have the whole canvas. */
function deckAllowed(){
  const m=(DECK&&DECK.desks)||{};
  return m[curDesk]!==undefined?!!m[curDesk]:(curDesk===1);
}
function deckVisibleNow(){
  if(!DECK)return false;
  if(!deckAllowed())return false;                        // this space is kept clear
  if(DECK._override!==undefined)return DECK._override;   // the user just toggled it
  if(!DECK.auto)return !!DECK.open;
  let busy=false;WM.wins.forEach(w=>{if(!w.min&&(w.desk||1)===curDesk)busy=true});
  return !busy;
}
/* Window activity recomputes visibility and clears any manual override, so one
   click on ▾ never leaves the deck stuck open over your work. */
function deckAuto(){
  if(!DECK)return;
  DECK._override=undefined;
  const want=deckVisibleNow();
  if(want!==document.body.classList.contains('deck-open'))buildDeck();
}
function deckToggle(){
  if(!DECK)deckLoad();
  DECK.desks=DECK.desks||{};
  const showing=document.body.classList.contains('deck-open');
  DECK.desks[curDesk]=!showing;                 // remembered per desktop
  DECK._override=showing?undefined:true;
  deckSave();buildDeck();
  toast(showing?`Desktop ${curDesk} is clear — Ctrl+Shift+D brings the deck back`
               :`app deck on Desktop ${curDesk}`);
}
function buildDeck(){
  const box=$('#deck');if(!box)return;
  if(!DECK)deckLoad();
  deckReconcile();
  const open=deckVisibleNow();
  document.body.classList.toggle('deck-open',open);
  DECK._shown=open;
  box.innerHTML=`<button id="deck-toggle" title="${open?`Hide the deck on Desktop ${curDesk} (Ctrl+Shift+D)`:`Show the deck on Desktop ${curDesk} (Ctrl+Shift+D)`}">${open?'▾':'▴'}</button>
    <div id="deck-scroll">${DECK.groups.map(g=>deckGroupHTML(g)).join('')}
      ${deckWidgetsHTML()}
      <button class="deck-new" title="New group">＋<span>New group</span></button>
    </div>`;
  $('#deck-toggle').onclick=deckToggle;
  box.querySelector('.deck-new').onclick=deckNewGroup;
  box.querySelectorAll('.deck-tile').forEach(t=>{
    t.onclick=()=>openApp(t.dataset.app);
    t.oncontextmenu=e=>{e.preventDefault();deckTileMenu(e,t.dataset.app)};
  });
  box.querySelectorAll('.deck-gname').forEach(h=>{
    h.oncontextmenu=e=>{e.preventDefault();deckGroupMenu(e,h.dataset.g)};
  });
  deckMeasure(open);
}
/* the deck's real height drives --deckh, so cards, toasts and the start menu
   always sit above it however many rows it wrapped into */
function deckMeasure(open){
  const box=$('#deck');if(!box)return;
  requestAnimationFrame(()=>{
    const h=open?Math.ceil(box.getBoundingClientRect().height)+8:0;
    document.documentElement.style.setProperty('--deckh',h+'px');
  });
}
addEventListener('resize',()=>{if(DECK)deckMeasure(document.body.classList.contains('deck-open'))});
function deckGroupHTML(g){
  return `<div class="deck-group" data-g="${esc(g.id)}">
    <div class="deck-gname" data-g="${esc(g.id)}">${esc(g.name)}</div>
    <div class="deck-tiles">${g.apps.map(id=>APPS[id]?`
      <button class="deck-tile" data-app="${esc(id)}" title="${esc(APPS[id].desc||APPS[id].title)}">
        ${appIcon(id,46)}<span>${esc(APPS[id].title)}</span></button>`:'').join('')}</div>
  </div>`;
}
function deckWidgetsHTML(){
  const apps={};(USERAPPS||[]).forEach(a=>apps[a.id]=a);
  const here=(WIDGETS||[]).filter(w=>w.place==='deck'&&apps[w.app_id]);
  return here.map(w=>`<div class="deck-group deck-wgroup" data-w="${esc(w.app_id)}">
    <div class="deck-gname">${esc(apps[w.app_id].name)}
      <button class="deck-wx" title="Unpin" onclick="setWidgetPlace('${esc(w.app_id)}','')">✕</button></div>
    <div class="deck-wframe"><iframe src="/api/apps/${esc(w.app_id)}/page?surface=widget" sandbox="allow-scripts allow-same-origin allow-forms"></iframe></div>
  </div>`).join('');
}
async function deckNewGroup(){
  const name=await osPrompt('Name the new group',{placeholder:'e.g. Work',confirmText:'Create'});
  if(!name||!name.trim())return;
  DECK.groups.push({id:'g'+Date.now().toString(36),name:name.trim(),apps:[]});
  deckSave();buildDeck();
  toast('group "'+name.trim()+'" added — right-click any app to move it here');
}
function deckTileMenu(e,id){
  const cur=deckGroupOf(id);
  const items=[{label:'Open',fn:()=>openApp(id)}];
  if(APPS[id]&&APPS[id].multi)items.push({label:'New window',fn:()=>openAppNew(id)});
  items.push({label:'✦ Ask about this app',fn:()=>copilotAsk(id,'')});
  items.push(null);
  DECK.groups.filter(g=>g!==cur).forEach(g=>items.push({label:'Move to '+g.name,fn:()=>{
    if(cur)cur.apps=cur.apps.filter(x=>x!==id);
    g.apps.push(id);deckSave();buildDeck();
  }}));
  items.push(null,{label:'Pin to dock',fn:()=>pinToDock(id)});
  if(id.startsWith('ua_'))items.push({label:'Pin as widget (deck)',fn:()=>setWidgetPlace(id.slice(3),'deck')});
  showCtxItems(e,items);
}
function deckGroupMenu(e,gid){
  const g=DECK.groups.find(x=>x.id===gid);if(!g)return;
  showCtxItems(e,[
    {label:'Rename group…',fn:async()=>{
      const v=await osPrompt('Rename group',{value:g.name,confirmText:'Rename'});
      if(v&&v.trim()){g.name=v.trim();deckSave();buildDeck()}}},
    {label:'Move group left',fn:()=>{const i=DECK.groups.indexOf(g);if(i>0){DECK.groups.splice(i,1);DECK.groups.splice(i-1,0,g);deckSave();buildDeck()}}},
    {label:'Move group right',fn:()=>{const i=DECK.groups.indexOf(g);if(i<DECK.groups.length-1){DECK.groups.splice(i,1);DECK.groups.splice(i+1,0,g);deckSave();buildDeck()}}},
    null,
    {label:(DECK.auto?'Always show the deck':'Hide the deck while working'),fn:()=>{
      DECK.auto=!DECK.auto;DECK.open=true;DECK._override=undefined;deckSave();buildDeck();
      toast(DECK.auto?'the deck steps aside while you work':'the deck always shows')}},
    {label:'Delete group',danger:true,fn:async()=>{
      if(!await osConfirm(`Delete "${g.name}"?`,'Its apps move back into More — nothing is uninstalled.',{confirmText:'Delete',danger:true}))return;
      DECK.groups=DECK.groups.filter(x=>x!==g);
      deckSave();buildDeck();
    }},
  ]);
}
