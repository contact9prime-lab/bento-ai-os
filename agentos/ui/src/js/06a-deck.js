/* ================= the deck: app tiles above the prompt bar =================
   The desktop is wallpaper, not a filing cabinet. Every app lives in a bento
   group inside one horizontally scrollable strip that sits directly above the
   omnibar — plus any widget you pin into it. Groups are yours: rename, create,
   move apps between them. Persisted in localStorage; nothing here is on the
   server, so it stays instant. */
const DECK_DEFAULTS=[
  ['Essentials',['chat','apps','hostscreen','remotedesk','browser','files','terminal']],
  ['Create',['store','studio','themes','personalize','gallery']],
  ['Intelligence',['models','memory','kg','soul','profile','spaces','timeline']],
  ['Automation',['jobs','automations','fabric','tasks','skills','mcp','telegram']],
  ['System',['taskmgr','control','syssettings','settings','setup','users','policies','permissions','quarantine','audit','snapshots','logs','tokens']],
  ['Library',['docs','mission','train','about']],
];
// folded until used: what these hold is empty on a machine nobody has talked to
const DECK_FOLDED_AT_FIRST=['Intelligence','System','Library'];
let DECK=null;
/* ---- the full app wall ----
   Scrolling up over the tiles (or over bare wallpaper) grows the deck into the
   whole desktop: every group, every system app, bigger tiles, laid out on one
   aligned grid. Scrolling back down, Esc, clicking the wallpaper or opening
   anything puts it back. State is deliberately NOT persisted — an overview you
   log back into is a screen in the way, not a launcher.
   TUI: not applicable, there is no wall to scroll; `agentos apps` already lists
   everything. SUI: the desktop is the BACKGROUND layer, so an overview would
   otherwise open UNDER the native windows — deckFull raises the surface for as
   long as it is up, exactly as the omnibar does.

   The wall has two faces, stacked the way the gesture reads: scroll UP for your
   apps, DOWN for your widgets, and tabs to cross between them without going
   back through the desktop. The apps face opens with the caret already in its
   search box, so the fastest way to an app is still typing its name. */
var DECKFULL=false;         // var, not let: earlier files in the bundle read it
var DECKTAB='apps';         // 'apps' | 'widgets'
var DECKQ='';               // the search box, kept across rebuilds
var DECK_RAISED=false;      // we brought the session surface forward, so we lower it
var DECK_LASTOPEN=false;    // tiles animate in when the deck APPEARS, not on every rebuild
function deckIconPx(){return DECKFULL?54:46}
function deckLoad(){
  try{DECK=JSON.parse(localStorage.getItem('deck')||'null')}catch(e){DECK=null}
  /* Day one is not week four. A fresh desktop showed six groups and 43 tiles —
     Quarantine, Audit, Snapshots and Token Analytics at the same weight as Chat —
     on a machine that could not yet answer a question. The groups that hold
     nothing until the machine has been used start folded to one line with a
     count, and unfold the first time one of their apps is opened, or on a click.
     A stored deck is left exactly as the person arranged it. */
  if(!DECK||!Array.isArray(DECK.groups))
    DECK={open:true,groups:DECK_DEFAULTS.map(([name,apps],i)=>({id:'g'+i,name,apps:apps.slice(),
      collapsed:DECK_FOLDED_AT_FIRST.includes(name)}))};
  if(DECK.open===undefined)DECK.open=true;
  if(DECK.auto===undefined)DECK.auto=true;   // step aside while you're working in a window
  return DECK;
}
function deckSave(){localStorage.setItem('deck',JSON.stringify(DECK))}
function deckGroupOf(id){return DECK.groups.find(g=>g.apps.includes(id))}
/* ---- hiding an app from the desktop ----------------------------------------
   A tile you never use is clutter on the one surface that is meant to be YOURS,
   and the honest answer to "I don't want to see this" is not "delete the app" —
   these are built-ins, and half of them are how the OS explains itself. So the
   deck keeps a hidden list: the tile leaves the shelf, the app stays installed
   and stays reachable from the launcher, the prompt bar and the app wall.
   Hiding is never a one-way door: the wall still draws hidden apps, dimmed and
   marked, and their menu offers them back. A hidden app that could not be found
   again is the dead control this project's honesty rules forbid. */
function deckHidden(){return (DECK&&DECK.hidden)||[]}
function deckIsHidden(id){return deckHidden().includes(id)}
function deckSetHidden(id,on){
  if(!DECK)return;
  const h=new Set(deckHidden());
  on?h.add(id):h.delete(id);
  DECK.hidden=[...h];
  deckSave();buildDeck();
  const name=(APPS[id]&&APPS[id].title)||id;
  toast(on?`${name} hidden — still in the launcher, and on the app wall (scroll up)`
          :`${name} is back on the desktop`);
}
/* the apps of a group that actually belong on the shelf right now */
function deckShown(g){return g.apps.filter(id=>APPS[id]&&(DECKFULL||!deckIsHidden(id)))}
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
  if(DECKFULL)return true;                               // the wall overrides every other rule
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
function buildDeck(fresh){
  const box=$('#deck');if(!box)return;
  if(!DECK)deckLoad();
  deckReconcile();
  const open=deckVisibleNow();
  document.body.classList.toggle('deck-open',open);
  DECK._shown=open;
  const board=DECKFULL&&DECKTAB==='widgets';
  box.innerHTML=`${DECKFULL?deckHeadHTML()
      :`<button id="deck-toggle" title="${open?`Hide the deck on Desktop ${curDesk} (Ctrl+Shift+D) — scroll up here for all apps`:`Show the deck on Desktop ${curDesk} (Ctrl+Shift+D)`}">${open?'▾':'▴'}</button>`}
    <div id="deck-scroll">${board?deckBoardHTML()
      :`${DECKFULL?deckNoneHTML():''}
      ${DECK.groups.map(g=>deckGroupHTML(g)).join('')}
      ${deckNativeHTML()}
      ${deckWidgetsHTML()}
      <button class="deck-new" title="New group">＋<span>New group</span></button>`}
    </div>`;
  $('#deck-toggle').onclick=DECKFULL?(()=>deckFull(false)):deckToggle;
  if(DECKFULL)deckHeadWire();
  const nw=box.querySelector('.deck-new');
  if(nw)nw.onclick=deckNewGroup;
  const ask=box.querySelector('.dn-ask');
  if(ask)ask.onclick=()=>{const q=DECKQ;deckFull(false);omniSummon(true);
    const i=$('#omni-in');if(i){i.value=q;omniPop(true)}};
  box.querySelectorAll('.deck-board').forEach(c=>{
    const id=c.dataset.w;
    c.querySelector('.db-open').onclick=()=>{deckFull(false);openApp('ua_'+id)};
    c.querySelector('.deck-gname').oncontextmenu=e=>{e.preventDefault();deckBoardMenu(e,id)};
  });
  const st=box.querySelector('.de-studio'), so=box.querySelector('.de-store');
  if(st)st.onclick=()=>{deckFull(false);openApp('studio')};
  if(so)so.onclick=()=>{deckFull(false);openApp('store')};
  box.querySelectorAll('.deck-tile[data-app]').forEach(t=>{
    // a drag is not a click: `_moved` is set by the drag and read here, the same
    // rule the desktop icons have always used
    t.onclick=()=>{if(t._moved)return;deckFull(false);openApp(t.dataset.app)};
    t.oncontextmenu=e=>{e.preventDefault();deckTileMenu(e,t.dataset.app)};
    deckDragWire(t,'tile');
  });
  box.querySelectorAll('.deck-nat').forEach(t=>{
    t.onclick=()=>{deckFull(false);launchNative(t.dataset.nat,t.dataset.natname)};
    t.oncontextmenu=e=>{e.preventDefault();showCtxItems(e,[
      {label:'Open',fn:()=>launchNative(t.dataset.nat,t.dataset.natname)},
      {label:'Show all applications',fn:()=>openApp('apps')},
      null,
      {label:'Hide system apps from the deck',fn:deckToggleNative},
    ])};
  });
  const more=box.querySelector('.deck-natmore');
  if(more)more.onclick=()=>deckFull(true);   // "+N more" is the wall, one click instead of a scroll
  box.querySelectorAll('.deck-gname[data-native]').forEach(h=>{
    h.oncontextmenu=e=>{e.preventDefault();showCtxItems(e,[
      {label:'Show all applications',fn:()=>openApp('apps')},
      {label:'Hide system apps from the deck',fn:deckToggleNative},
    ])};
  });
  box.querySelectorAll('.deck-gname[data-g]').forEach(h=>{
    h.oncontextmenu=e=>{e.preventDefault();deckGroupMenu(e,h.dataset.g)};
    // the group's NAME is its handle — dragging from the tiles moves a tile
    const g=h.closest('.deck-group[data-g]');
    if(g&&!h.classList.contains('deck-unfold'))deckDragWire(g,'group',h);
  });
  box.querySelectorAll('.deck-unfold,.deck-fold').forEach(b=>{
    b.onclick=e=>{e.stopPropagation();deckFold(b.dataset.g,b.classList.contains('deck-fold'))};
  });
  // on the wall, the space around the tiles is a way out, like any overview
  box.onclick=e=>{if(DECKFULL&&(e.target===box||e.target.id==='deck-scroll'))deckFull(false)};
  deckMeasure(open);
  if(DECKFULL&&!board)deckFilter(DECKQ,true);   // a rebuild must not drop the query
  if(open&&(fresh||!DECK_LASTOPEN))deckStagger();
  DECK_LASTOPEN=open;
}
/* ---- the wall's header: two tabs, a search box, and the way out ----
   The count is on the tab rather than beside a title because the tabs are what
   you are choosing between; a heading that says "All apps" above a Widgets tab
   is a heading that lies half the time. */
function deckHeadHTML(){
  const own=DECK.groups.reduce((n,g)=>n+g.apps.filter(id=>APPS[id]).length,0);
  const nat=(typeof NATIVEAPPS!=='undefined'&&!deckNativeHidden())?NATIVEAPPS.length:0;
  const apps={};(typeof USERAPPS!=='undefined'?USERAPPS:[]).forEach(a=>apps[a.id]=a);
  const wn=(typeof WIDGETS!=='undefined'?WIDGETS:[]).filter(w=>apps[w.app_id]).length;
  const tab=(id,label,n)=>`<button class="dh-tab${DECKTAB===id?' on':''}" data-tab="${id}"
    role="tab" aria-selected="${DECKTAB===id}">${label}<span class="dh-n">${n}</span></button>`;
  return `<div id="deck-head">
    <div class="dh-tabs" role="tablist">${tab('apps','All apps',own+nat)}${tab('widgets','Widgets',wn)}</div>
    ${DECKTAB==='apps'?`<input id="deck-q" type="search" autocomplete="off" spellcheck="false"
      placeholder="Search apps and system apps…" value="${esc(DECKQ)}"
      aria-label="Search apps">`:''}
    <span class="dh-hint">${DECKTAB==='apps'?'scroll down or press Esc to go back'
                                            :'scroll up for your apps · Esc to go back'}</span>
    <button id="deck-toggle" title="Back to the desktop (Esc)">✕</button></div>`;
}
function deckHeadWire(){
  const box=$('#deck');
  box.querySelectorAll('.dh-tab').forEach(b=>b.onclick=()=>deckTab(b.dataset.tab));
  const q=$('#deck-q');
  if(!q)return;
  q.oninput=()=>deckFilter(q.value);
  q.onkeydown=e=>{
    if(e.key==='Enter'){e.preventDefault();deckOpenSelected();return}
    if(e.key==='ArrowRight'||e.key==='ArrowLeft'||e.key==='ArrowDown'||e.key==='ArrowUp'){
      // the caret stays put: on a wall of tiles the arrows are for the tiles
      e.preventDefault();deckMoveSel(e.key==='ArrowLeft'||e.key==='ArrowUp'?-1:1);
    }
  };
  // the wall is a launcher, so the caret belongs in the box the moment it opens
  q.focus();
  const n=q.value.length;try{q.setSelectionRange(n,n)}catch(e){}
}
/* switch faces without leaving the wall */
function deckTab(tab){
  if(!DECKFULL||tab===DECKTAB)return;
  DECKTAB=tab;
  if(tab==='widgets')DECKQ='';
  buildDeck(true);
}
/* ---- search ----
   palScore is the omnibar's own ranking (3 prefix · 2 substring · 1 scattered),
   so a name typed here and the same name typed in the prompt bar cannot
   disagree about what it matches. Tiles are hidden in place rather than
   re-rendered: re-rendering would take the caret out of the box on every
   keystroke. */
function deckFilter(q,quiet){
  const box=$('#deck');if(!box)return;
  DECKQ=q||'';
  const s=DECKQ.trim();
  box.classList.toggle('filtering',!!s);
  const tiles=[...box.querySelectorAll('.deck-tile')];
  const scored=tiles.map(t=>({t,s:s?deckTileScore(s,t):3}));
  const best=scored.reduce((m,x)=>Math.max(m,x.s),0);
  const floor=best>=2?2:1;                  // drop the scattered tail once there is a real hit
  scored.forEach(x=>x.t.classList.toggle('nomatch',s?x.s<floor:false));
  box.querySelectorAll('.deck-group').forEach(g=>{
    const any=[...g.querySelectorAll('.deck-tile')].some(t=>!t.classList.contains('nomatch'));
    g.classList.toggle('nomatch',!!s&&!any);
  });
  const hits=scored.filter(x=>!x.t.classList.contains('nomatch'));
  if(s)hits.sort((a,b)=>b.s-a.s);
  // no query, no selection: a ring on the first tile of an unfiltered wall reads
  // as "this is where you are", which is not true and Enter would prove it
  deckSelect(s&&hits.length?hits[0].t:null);
  box.classList.toggle('noresults',!!s&&!hits.length);
}
function deckTileScore(q,t){
  const label=(t.querySelector('span')||{}).textContent||'';
  return Math.max(palScore(q,label),
                  t.dataset.app?palScore(q,t.dataset.app):0,
                  t.title?(String(t.title).toLowerCase().includes(q.toLowerCase())?1.5:0):0);
}
/* "nothing matches" is a sentence with a way forward, not an empty screen: the
   thing you typed goes to the agent, which is the one search that can't miss. */
function deckNoneHTML(){
  return `<div class="deck-none"><b>Nothing here matches that.</b>
    <button class="dn-ask">Ask the agent instead</button></div>`;
}
function deckSelect(t){
  const box=$('#deck');if(!box)return;
  box.querySelectorAll('.deck-tile.sel').forEach(e=>e.classList.remove('sel'));
  if(t){t.classList.add('sel');if(t.scrollIntoView)t.scrollIntoView({block:'nearest'})}
}
function deckMoveSel(step){
  const box=$('#deck');if(!box)return;
  const vis=[...box.querySelectorAll('.deck-tile')].filter(t=>!t.classList.contains('nomatch'));
  if(!vis.length)return;
  const cur=vis.findIndex(t=>t.classList.contains('sel'));
  deckSelect(vis[Math.max(0,Math.min(vis.length-1,(cur<0?0:cur+step)))]);
}
function deckOpenSelected(){
  const t=$('#deck .deck-tile.sel');
  if(t)t.click();
}
/* Tiles arrive rather than appear: one sweep left-to-right, capped so a machine
   with two hundred apps does not spend a second and a half drawing them. Under
   prefers-reduced-motion Motion.run resolves without animating, so this whole
   function costs nothing rather than being branched around. */
function deckStagger(){
  const box=$('#deck');if(!box||Motion.reduced)return;
  box.querySelectorAll('.deck-group').forEach((g,i)=>Motion.run(g,
    [{opacity:0,transform:'translateY(14px) scale(.985)'},{opacity:1,transform:'none'}],
    {duration:280,delay:Math.min(i*26,190),easing:EASE.out,fill:'backwards'}));
  box.querySelectorAll('.deck-tile').forEach((t,i)=>Motion.run(t,
    [{opacity:0,transform:'translateY(10px) scale(.88)'},{opacity:1,transform:'none'}],
    {duration:260,delay:Math.min(70+i*9,430),easing:EASE.spring,fill:'backwards'}));
}
/* ---- open / close the wall ----
   Opening is a rebuild (bigger icons, every system app) plus a scrim fade;
   closing fades the scrim out FIRST, so the compact deck is never seen wearing
   the wall's layout for a frame. */
function deckFull(on,tab){
  on=!!on;
  const box=$('#deck');
  if(!box)return;
  if(on&&DECKFULL)return tab?deckTab(tab):undefined;   // already up: the gesture just picks a face
  if(on===DECKFULL)return;
  if(on){
    DECKFULL=true;DECKTAB=tab||'apps';DECKQ='';
    document.body.classList.add('deck-full');
    // SUI/DE: come in front of the native windows for as long as the wall is up
    if(!(typeof OMNI!=='undefined'&&OMNI.pop)&&typeof raiseShell==='function'){
      DECK_RAISED=true;raiseShell(true);
    }
    buildDeck(true);
    Motion.run(box,[{opacity:0},{opacity:1}],{duration:180,easing:EASE.out});
    return;
  }
  const a=Motion.run(box,[{opacity:1},{opacity:0}],{duration:130,easing:EASE.in,fill:'forwards'});
  (a.finished||Promise.resolve()).then(()=>{
    a.cancel();                       // drop the held opacity in the same task as the rebuild
    DECKFULL=false;DECKQ='';DECKTAB='apps';
    document.body.classList.remove('deck-full');
    box.classList.remove('filtering','noresults');
    buildDeck();
    // the caret goes back where the desktop keeps it, without popping the launcher
    const i=$('#omni-in');if(i&&!(typeof OMNI!=='undefined'&&OMNI.pop))i.focus();
    if(DECK_RAISED){DECK_RAISED=false;if(typeof raiseShell==='function')raiseShell(false)}
  });
}
/* ---- the widgets face ----
   Every widget you have, wherever it is pinned and whichever desktop it is on,
   as live cards. The iframes are mounted on open and thrown away on close: a
   glance surface that shows what it showed ten minutes ago is worse than one
   that takes a moment to load, and a hidden iframe left running is a timer
   nobody can see. */
function deckBoardHTML(){
  const apps={};(typeof USERAPPS!=='undefined'?USERAPPS:[]).forEach(a=>apps[a.id]=a);
  const list=(typeof WIDGETS!=='undefined'?WIDGETS:[]).filter(w=>apps[w.app_id]);
  if(!list.length)return `<div class="deck-empty">
    <b>No widgets pinned yet</b>
    <span>Every app you build has a second face — one glanceable card. Right-click
      one of your own apps on the apps tab to pin it, or make one in App Studio.
      The built-in apps are windows only; they have no widget to pin.</span>
    <div class="row"><button class="de-studio">Open App Studio</button>
      <button class="de-store">Browse the Store</button></div></div>`;
  const where=w=>((typeof WIDGET_PLACES!=='undefined'
    ?(WIDGET_PLACES.find(p=>p[0]===(w.place||''))||[])[1]:'')||'Desktop')
    +(w.place?'':' '+(w.desk||1));
  return list.map(w=>{
    const a=apps[w.app_id], size=esc(a.widget_size||'m');
    return `<div class="deck-group deck-board" data-w="${esc(w.app_id)}">
      <div class="deck-gname">${esc(a.name)}<span class="mut">${esc(where(w))}</span>
        <button class="db-open" title="Open the whole app">⤢</button></div>
      <div class="deck-wframe db-${size}"><iframe loading="lazy" title="${esc(a.name)}"
        src="/api/apps/${esc(w.app_id)}/page?surface=widget&size=${size}"
        sandbox="allow-scripts allow-forms"></iframe></div>
    </div>`;
  }).join('');
}
/* the deck's real height drives --deckh, so cards, toasts and the start menu
   always sit above it however many rows it wrapped into */
function deckMeasure(open){
  const box=$('#deck');if(!box)return;
  // the wall is a transient overlay, not chrome: measuring it would push toasts,
  // cards and the start menu off the bottom of the screen
  if(DECKFULL)return;
  requestAnimationFrame(()=>{
    const h=open?Math.ceil(box.getBoundingClientRect().height)+8:0;
    document.documentElement.style.setProperty('--deckh',h+'px');
  });
}
addEventListener('resize',()=>{if(DECK)deckMeasure(document.body.classList.contains('deck-open'))});
function deckGroupHTML(g){
  // the wall shows everything: folding is a property of the shelf, not of the overview
  const folded=!!g.collapsed&&!DECKFULL;
  const shown=deckShown(g);
  const n=shown.length;
  if(folded)return `<div class="deck-group folded" data-g="${esc(g.id)}">
    <button class="deck-gname deck-unfold" data-g="${esc(g.id)}" title="Show the ${n} apps in ${esc(g.name)}">
      ${esc(g.name)} <span class="mut">${n}</span><span class="deck-caret">▸</span></button>
    <div class="deck-peek">${shown.slice(0,5).map(id=>appIcon(id,18)).join('')}</div>
  </div>`;
  const hid=g.apps.filter(id=>APPS[id]&&deckIsHidden(id)).length;
  return `<div class="deck-group" data-g="${esc(g.id)}">
    <div class="deck-gname" data-g="${esc(g.id)}" title="Drag to move this group">${esc(g.name)}${
      hid&&!DECKFULL?`<span class="deck-hidn" title="${hid} app${hid>1?'s':''} hidden from the desktop — right-click to show ${hid>1?'them':'it'}">${hid} hidden</span>`:''}${
      g.collapsed!==undefined?`<button class="deck-fold" data-g="${esc(g.id)}" title="Fold ${esc(g.name)} to one line">▾</button>`:''}</div>
    <div class="deck-tiles">${shown.map(id=>`
      <button class="deck-tile${deckIsHidden(id)?' hidden-app':''}" data-app="${esc(id)}"
        title="${esc(APPS[id].desc||APPS[id].title)}${deckIsHidden(id)?' · hidden from the desktop':''}">
        ${appIcon(id,deckIconPx())}<span>${esc(APPS[id].title)}</span></button>`).join('')}</div>
  </div>`;
}
/* ---- system apps ----
   The machine's own applications belong on the same shelf as AgentOS's. This is
   a SYNTHESIZED group rather than a stored one: the host's app list changes
   whenever something is installed, so it is read from /api/native/apps every
   time instead of being frozen into localStorage like the user's own groups.
   It shows in every run mode — AgentOS being the session or a window inside
   someone else's is not a reason to hide the machine's apps. */
const DECK_NATIVE_MAX=14;
function deckNativeHidden(){return !!(DECK&&DECK.hide_native)}
function deckNativeHTML(){
  const apps=(typeof NATIVEAPPS!=='undefined'?NATIVEAPPS:[]);
  if(!apps.length||deckNativeHidden())return '';
  // the wall is where "all apps" has to mean all of them — the shelf is capped
  // only while it is sharing the desktop with your work
  const show=DECKFULL?apps:apps.slice(0,DECK_NATIVE_MAX), rest=apps.length-show.length;
  const px=deckIconPx();
  return `<div class="deck-group deck-native">
    <div class="deck-gname" data-native="1">System apps <span class="mut">${apps.length}</span></div>
    <div class="deck-tiles">${show.map(a=>`
      <button class="deck-tile deck-nat" data-nat="${esc(a.id)}" data-natname="${esc(a.name)}"
              title="${esc(a.comment||a.name)}">${nativeIcon(a,px)}<span>${esc(a.name)}</span></button>`).join('')}
      ${rest>0?`<button class="deck-tile deck-natmore" title="Every installed application">
        ${appIcon('apps',px)}<span>+${rest} more</span></button>`:''}</div>
  </div>`;
}
function deckWidgetsHTML(){
  const apps={};(USERAPPS||[]).forEach(a=>apps[a.id]=a);
  const here=(WIDGETS||[]).filter(w=>w.place==='deck'&&apps[w.app_id]);
  return here.map(w=>`<div class="deck-group deck-wgroup" data-w="${esc(w.app_id)}">
    <div class="deck-gname">${esc(apps[w.app_id].name)}
      <button class="deck-wx" title="Unpin" onclick="setWidgetPlace('${esc(w.app_id)}','')">✕</button></div>
    <div class="deck-wframe"><iframe src="/api/apps/${esc(w.app_id)}/page?surface=widget" sandbox="allow-scripts allow-forms"></iframe></div>
  </div>`).join('');
}
function deckToggleNative(){
  DECK.hide_native=!deckNativeHidden();deckSave();buildDeck();
  toast(DECK.hide_native?'system apps hidden — right-click any group header to bring them back'
                        :'system apps back on the deck');
}
async function deckNewGroup(){
  const name=await osPrompt('Name the new group',{placeholder:'e.g. Work',confirmText:'Create'});
  if(!name||!name.trim())return;
  DECK.groups.push({id:'g'+Date.now().toString(36),name:name.trim(),apps:[]});
  deckSave();buildDeck();
  toast('group "'+name.trim()+'" added — right-click any app to move it here');
}
/* the board's own right-click: size, where it lives, unpin — the same verbs the
   widget has on the desktop, reached from the one place that lists them all */
function deckBoardMenu(e,id){
  const items=[{label:'Open the app',fn:()=>{deckFull(false);openApp('ua_'+id)}},null];
  if(typeof WIDGET_SIZES!=='undefined')
    Object.entries(WIDGET_SIZES).forEach(([k,d])=>items.push({label:d.label+' widget',
      fn:()=>{setWidgetSize(id,k);if(DECKFULL)buildDeck(true)}}));
  items.push(null);
  if(typeof WIDGET_PLACES!=='undefined')
    WIDGET_PLACES.forEach(([p,label])=>items.push({label:'Move to '+label,
      fn:()=>{setWidgetPlace(id,p);if(DECKFULL)buildDeck(true)}}));
  items.push(null,{label:'Unpin',danger:true,fn:()=>{unpinWidget(id);if(DECKFULL)buildDeck(true)}});
  showCtxItems(e,items);
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
  items.push(null);
  // Rearranging without a pointer, and the one thing a menu can do that a drag
  // cannot: say what it will do before you commit to it.
  if(cur){
    const i=cur.apps.indexOf(id);
    const prev=cur.apps.slice(0,i).reverse().find(x=>APPS[x]&&(DECKFULL||!deckIsHidden(x)));
    const next=cur.apps.slice(i+1).find(x=>APPS[x]&&(DECKFULL||!deckIsHidden(x)));
    if(prev)items.push({label:'Move earlier',fn:()=>deckMoveTile(id,-1)});
    if(next)items.push({label:'Move later',fn:()=>deckMoveTile(id,1)});
  }
  items.push({label:'Pin to dock',fn:()=>pinToDock(id)});
  items.push(deckIsHidden(id)
    ?{label:'Show on the desktop',fn:()=>deckSetHidden(id,false)}
    :{label:'Hide from the desktop',fn:()=>deckSetHidden(id,true)});
  if(id.startsWith('ua_')){
    items.push({label:'Pin as widget',fn:()=>{setWidgetPlace(id.slice(3),'');if(DECKFULL)deckTab('widgets')}});
    items.push({label:'Pin as widget (deck)',fn:()=>setWidgetPlace(id.slice(3),'deck')});
  }
  showCtxItems(e,items);
}
/* fold/unfold one group; `deckUsed(id)` unfolds the group an app was just opened
   from any other door (launcher, prompt bar, dock) — a group you have been into
   is not one that holds nothing */
function deckFold(gid,on){
  const g=DECK.groups.find(x=>x.id===gid);if(!g)return;
  g.collapsed=!!on;deckSave();buildDeck();
}
function deckUsed(id){
  if(!DECK)return;
  const g=deckGroupOf(id);
  if(g&&g.collapsed){g.collapsed=false;deckSave();if(DECK._shown)buildDeck()}
}
function deckGroupMenu(e,gid){
  const g=DECK.groups.find(x=>x.id===gid);if(!g)return;
  const hidden=g.apps.filter(id=>APPS[id]&&deckIsHidden(id));
  showCtxItems(e,[
    {label:g.collapsed?'Unfold group':'Fold group to one line',fn:()=>deckFold(gid,!g.collapsed)},
    ...(hidden.length?[{label:`Show ${hidden.length} hidden app${hidden.length>1?'s':''}`,fn:()=>{
      DECK.hidden=deckHidden().filter(id=>!hidden.includes(id));deckSave();buildDeck();
      toast(`${hidden.length} app${hidden.length>1?'s are':' is'} back on the desktop`)}}]:[]),
    {label:'Rename group…',fn:async()=>{
      const v=await osPrompt('Rename group',{value:g.name,confirmText:'Rename'});
      if(v&&v.trim()){g.name=v.trim();deckSave();buildDeck()}}},
    {label:'Move group left',fn:()=>{const i=DECK.groups.indexOf(g);if(i>0){DECK.groups.splice(i,1);DECK.groups.splice(i-1,0,g);deckSave();buildDeck()}}},
    {label:'Move group right',fn:()=>{const i=DECK.groups.indexOf(g);if(i<DECK.groups.length-1){DECK.groups.splice(i,1);DECK.groups.splice(i+1,0,g);deckSave();buildDeck()}}},
    null,
    {label:(deckNativeHidden()?'Show system apps':'Hide system apps'),fn:deckToggleNative},
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

/* ================= the gesture: scroll the tiles to open everything ==========
   Three surfaces in a vertical stack, which is what makes one gesture enough:

            All apps        ← push up
            the desktop
            Widgets         ← push down

   From the desktop (or the deck) a wheel, two fingers or a swipe up opens the
   apps face and down opens the widgets face; from either face, a push past the
   end you are already at drops you back on the desktop. Two rules keep it from
   fighting the ordinary scrollbar: the strip scrolls itself first and only
   fires the gesture once it is AT the end it is being pushed past, and a
   gesture has to add up to a real push rather than one stray notch.

   GUI: plain DOM events, so it works in any browser tab. SUI: identical — the
   desktop is a layer surface, and a wheel over it is still a wheel. */
const DECK_GESTURE=90;     // px of accumulated scroll before the wall moves
const DECK_WINDOW=420;     // ms after which a stalled gesture is forgotten
var DGEST={acc:0,at:0,cool:0};
/* Where the pointer is, in the only three terms this gesture cares about. The
   chrome and any window are somebody else's scroll and are left alone. */
function deckWheelZone(t){
  if(!t||!t.closest)return '';
  if(t.closest('#deck'))return 'deck';
  if(t.closest('.win,#taskbar,#menubar,#omnibar,#omnicards,#omnilist,#startmenu,#notifpanel,#widgets,#ccpop,#expose,.dlg-scrim,#switcher,#keyshelp'))return '';
  return t.closest('#desktop')?'wall':'';
}
function deckWheelPx(e){
  return e.deltaMode===1?e.deltaY*16:e.deltaMode===2?e.deltaY*innerHeight:e.deltaY;
}
/* true when the deck's own scroller has nothing left to give in this direction */
function deckAtEdge(up){
  const sc=$('#deck-scroll');
  if(!sc)return true;
  return up?sc.scrollTop<=0:sc.scrollTop+sc.clientHeight>=sc.scrollHeight-1;
}
function deckGesture(dy,now){
  if(now-DGEST.at>DECK_WINDOW||(dy<0)!==(DGEST.acc<0))DGEST.acc=0;
  DGEST.at=now;
  DGEST.acc+=dy;
  const up=DGEST.acc<0;
  if(Math.abs(DGEST.acc)<DECK_GESTURE)return false;
  DGEST.acc=0;
  DGEST.cool=now+420;                 // one gesture, one change of state
  // open: this push is already past the end, so it goes back to the desktop
  if(DECKFULL){deckFull(false);return true}
  deckFull(true,up?'apps':'widgets');
  return true;
}
addEventListener('wheel',e=>{
  if(e.ctrlKey||e.metaKey||e.altKey)return;                 // zoom, not a scroll
  const zone=deckWheelZone(e.target);
  if(!zone)return;
  const now=performance.now();
  if(now<DGEST.cool)return;
  const dy=deckWheelPx(e);
  if(!dy)return;
  // let the strip scroll itself while it still can
  if(zone==='deck'&&!deckAtEdge(dy<0))return;
  if(deckGesture(dy,now))e.preventDefault();
},{passive:false});

/* Touch: the same three-surface stack under a finger — swipe up for apps, down
   for widgets, and either way out of a face that is already at its end. Only
   vertical drags count, so a horizontal flick through a group's tiles stays a
   flick. Note the inverted edge test: a finger moving UP scrolls a list DOWN,
   so the edge a swipe has to be past is the opposite one from the wheel's. */
var DTOUCH=null;
addEventListener('touchstart',e=>{
  if(e.touches.length!==1)return DTOUCH=null;
  const zone=deckWheelZone(e.target);
  DTOUCH=zone?{zone,x:e.touches[0].clientX,y:e.touches[0].clientY,fired:false}:null;
},{passive:true});
addEventListener('touchmove',e=>{
  if(!DTOUCH||DTOUCH.fired||e.touches.length!==1)return;
  const dx=e.touches[0].clientX-DTOUCH.x, dy=e.touches[0].clientY-DTOUCH.y;
  if(Math.abs(dx)>Math.abs(dy))return;
  const up=dy<0;                                   // finger travelling up the screen
  if(DTOUCH.zone==='deck'&&!deckAtEdge(!up))return;
  if(Math.abs(dy)<70)return;
  DTOUCH.fired=true;
  if(DECKFULL)deckFull(false);
  else deckFull(true,up?'apps':'widgets');
},{passive:true});
addEventListener('touchend',()=>{DTOUCH=null},{passive:true});

/* ================= rearranging the bento: drag a tile, drag a group ==========
   The deck is the desktop's one arrangeable surface, and until now the only way
   to move anything was a context menu ("Move to Automation"), which is a way to
   RELOCATE a tile and no way at all to ORDER one. So tiles and groups drag.

   Pointer events, not HTML5 drag-and-drop: DnD has no touch story at all, and
   the phone is a first-class face here. One code path therefore serves a mouse,
   a trackpad and a finger.

   The DOM is the model while a drag is in flight — the dragged element itself is
   moved between siblings, so what you see IS the arrangement — and the order is
   read back out of it and committed on drop. That is what keeps the preview and
   the result the same computation instead of two that can disagree.

   Two rules that are easy to get wrong and expensive to debug:
   - A FOLDED group has no `.deck-tiles` in the DOM, and a hidden app has no tile.
     Reading a group's order back from the DOM must therefore never be a wholesale
     replacement: the ids that were not rendered are still that person's
     arrangement, and dropping them silently deletes apps from the deck.
   - On touch the drag must not start on contact. The deck scrolls, and a finger
     that moves is scrolling; only a finger that STAYS is rearranging. Hence the
     long press, and hence pointercancel (the browser taking the gesture for a
     scroll) abandons the drag rather than fighting it.

   TUI: not applicable — no pointer, and `bento apps` lists everything.
   SUI: identical, this is all inside the page.  */
var DRAG=null;
const DRAG_HOLD_MS=320;      // touch: hold this long, still, to pick a tile up
const DRAG_SLOP=5;           // mouse: move this far before it is a drag, not a click

/* Which way a container lays its children out, measured rather than assumed —
   the shelf flows in columns, the wall in rows, and a phone in one column. */
function deckAxis(box){
  const kids=[...box.children].filter(el=>el.offsetParent!==null);
  if(kids.length<2)return 'x';
  const a=kids[0].getBoundingClientRect(),b=kids[1].getBoundingClientRect();
  return Math.abs(b.left-a.left)>=Math.abs(b.top-a.top)?'x':'y';
}
function deckDragWire(el,kind,handle){
  (handle||el).addEventListener('pointerdown',e=>{
    if(e.button!==undefined&&e.button!==0)return;
    if(e.target.closest('.deck-fold,.deck-wx,.deck-unfold'))return;   // a button is a button
    deckDragArm(el,kind,e);
  });
}
function deckDragArm(el,kind,e){
  const touch=e.pointerType==='touch';
  const sx=e.clientX,sy=e.clientY;
  let started=false,hold=null;
  el._moved=false;
  /* WINDOW, not the element, and deliberately no setPointerCapture: this drag
     MOVES the dragged element between siblings, and a DOM move is a remove plus
     an insert, which releases pointer capture. Measured: the tile reordered on
     screen and then the drop never committed, because `pointerup` had stopped
     arriving at the element the listener was on. Listening on the window is
     immune to whatever happens to the node. */
  const begin=()=>{if(!started){started=true;deckDragStart(el,kind,{clientX:sx,clientY:sy})}};
  const move=ev=>{
    const far=Math.hypot(ev.clientX-sx,ev.clientY-sy);
    if(!started){
      if(touch){if(far>10){clearTimeout(hold);done()}return}   // a finger that moves is scrolling
      if(far<DRAG_SLOP)return;
      begin();
    }
    el._moved=true;
    deckDragMove(ev.clientX,ev.clientY);
  };
  const up=()=>{done();if(started)deckDragDrop()};
  const cancel=()=>{done();if(started)deckDragDrop(true)};
  // Touch scrolling is stopped by a non-passive touchmove, not by preventing a
  // pointer event: by the time the browser is scrolling, the pointer stream is
  // already lost. The long press means it has not started scrolling yet.
  const noscroll=ev=>{if(started)ev.preventDefault()};
  function done(){
    clearTimeout(hold);
    window.removeEventListener('pointermove',move);
    window.removeEventListener('pointerup',up);
    window.removeEventListener('pointercancel',cancel);
    window.removeEventListener('touchmove',noscroll);
  }
  window.addEventListener('pointermove',move);
  window.addEventListener('pointerup',up);
  window.addEventListener('pointercancel',cancel);
  window.addEventListener('touchmove',noscroll,{passive:false});
  if(touch)hold=setTimeout(begin,DRAG_HOLD_MS);
}
function deckDragStart(el,kind,e){
  const r=el.getBoundingClientRect();
  const ghost=el.cloneNode(true);
  ghost.classList.add('deck-ghost');
  ghost.style.width=r.width+'px';ghost.style.height=r.height+'px';
  document.body.appendChild(ghost);
  el.classList.add('dragging');
  document.body.classList.add('deck-dragging');
  DRAG={el,kind,ghost,dx:e.clientX-r.left,dy:e.clientY-r.top,into:null,
        home:{parent:el.parentNode,next:el.nextSibling}};
  deckDragMove(e.clientX,e.clientY);
  if(navigator.vibrate)try{navigator.vibrate(8)}catch(err){}
}
function deckDragMove(x,y){
  if(!DRAG)return;
  DRAG.ghost.style.left=(x-DRAG.dx)+'px';
  DRAG.ghost.style.top=(y-DRAG.dy)+'px';
  deckDragAutoScroll(x,y);
  const under=document.elementFromPoint(x,y);
  if(!under)return;
  if(DRAG.kind==='group'){
    const g=under.closest('.deck-group[data-g]');
    if(!g||g===DRAG.el)return;
    return deckDragPlace(DRAG.el,g,x,y);
  }
  // a tile: onto another tile, into an open group, or onto a folded one
  const folded=under.closest('.deck-group.folded[data-g]');
  deckDropInto(folded?folded.dataset.g:null);
  if(folded)return;
  const tile=under.closest('.deck-tile[data-app]');
  if(tile&&tile!==DRAG.el)return deckDragPlace(DRAG.el,tile,x,y);
  const grp=under.closest('.deck-group[data-g] .deck-tiles');
  if(grp&&!grp.contains(DRAG.el))grp.appendChild(DRAG.el);
}
/* put the dragged element before or after the thing under the pointer, along
   whichever axis that container actually runs in */
function deckDragPlace(el,target,x,y){
  const box=target.parentNode;
  if(!box)return;
  const r=target.getBoundingClientRect();
  const before=deckAxis(box)==='x'?x<r.left+r.width/2:y<r.top+r.height/2;
  const ref=before?target:target.nextSibling;
  if(ref!==el)box.insertBefore(el,ref===el?el.nextSibling:ref);
}
function deckDropInto(gid){
  if(DRAG.into===gid)return;
  const old=DRAG.into&&document.querySelector(`.deck-group[data-g="${CSS.escape(DRAG.into)}"]`);
  if(old)old.classList.remove('dropinto');
  DRAG.into=gid;
  const now=gid&&document.querySelector(`.deck-group[data-g="${CSS.escape(gid)}"]`);
  if(now)now.classList.add('dropinto');
}
/* the wall can be taller than the screen — a drag that cannot reach the bottom
   of it is a drag that cannot do the one thing it is for */
function deckDragAutoScroll(x,y){
  const sc=$('#deck-scroll');if(!sc)return;
  const r=sc.getBoundingClientRect(),edge=48;
  if(sc.scrollHeight>sc.clientHeight+2){
    if(y<r.top+edge)sc.scrollTop-=14; else if(y>r.bottom-edge)sc.scrollTop+=14;
  }
  if(sc.scrollWidth>sc.clientWidth+2){
    if(x<r.left+edge)sc.scrollLeft-=14; else if(x>r.right-edge)sc.scrollLeft+=14;
  }
}
function deckDragDrop(abandon){
  if(!DRAG)return;
  const {el,kind,ghost,into,home}=DRAG;
  const drag=DRAG;DRAG=null;
  ghost.remove();
  el.classList.remove('dragging');
  document.body.classList.remove('deck-dragging');
  document.querySelectorAll('.deck-group.dropinto').forEach(g=>g.classList.remove('dropinto'));
  if(abandon){                                   // the browser took the gesture: put it back
    if(home.parent)home.parent.insertBefore(el,home.next);
    return;
  }
  if(kind==='tile'&&into)return deckDropIntoGroup(el.dataset.app,into);
  deckCommitOrder();
  buildDeck();
}
/* Commit what the DOM now says. Only groups that are actually SHOWING their
   tiles are re-read; a folded group's apps are not on screen and must be left
   alone, and every id that is hidden (or otherwise unrendered) keeps its place
   rather than being dropped on the floor. */
function deckCommitOrder(){
  const sc=$('#deck-scroll');if(!sc||!DECK)return;
  const order=[];
  sc.querySelectorAll('.deck-group[data-g]').forEach(gel=>{
    const g=DECK.groups.find(x=>x.id===gel.dataset.g);
    if(!g)return;
    order.push(g);
    const tiles=gel.querySelector('.deck-tiles');
    if(!tiles)return;                                   // folded: nothing was shown, nothing moves
    const shown=[...tiles.querySelectorAll('.deck-tile[data-app]')].map(t=>t.dataset.app);
    const rest=g.apps.filter(id=>!shown.includes(id));   // hidden, or not rendered here
    g.apps=[...shown,...rest];
  });
  // a tile that moved between groups leaves the group it came from
  const claimed=new Set();
  order.forEach(g=>g.apps=g.apps.filter(id=>{
    if(claimed.has(id))return false;
    claimed.add(id);return true;
  }));
  DECK.groups.filter(g=>!order.includes(g)).forEach(g=>order.push(g));
  DECK.groups=order;
  deckSave();
}
/* dropped onto a group that is folded shut: it takes the app and opens */
function deckDropIntoGroup(id,gid){
  const g=DECK.groups.find(x=>x.id===gid);if(!g)return buildDeck();
  DECK.groups.forEach(x=>{if(x!==g)x.apps=x.apps.filter(a=>a!==id)});
  if(!g.apps.includes(id))g.apps.push(id);
  g.collapsed=false;
  deckSave();buildDeck();
  toast(`moved to ${g.name}`);
}
/* the menu's way to reorder, for anyone not using a pointer */
function deckMoveTile(id,dir){
  const g=deckGroupOf(id);if(!g)return;
  const i=g.apps.indexOf(id);
  const vis=x=>APPS[x]&&(DECKFULL||!deckIsHidden(x));
  const j=dir<0?g.apps.slice(0,i).reduce((p,x,k)=>vis(x)?k:p,-1)
               :(()=>{const k=g.apps.slice(i+1).findIndex(vis);return k<0?-1:i+1+k})();
  if(j<0)return;
  g.apps.splice(i,1);g.apps.splice(j,0,id);
  deckSave();buildDeck();
}
