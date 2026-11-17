/* ================= the App Hub scene: your apps and your widgets, as the desktop =================
   Asked for as "every desktop I add, I can change the scene: Town, Device, App Hub (with widgets)".
   The wall (06a-deck.js) already has both faces, but it is an overlay you open and leave. This is
   the same two things at rest: every widget you have, live, laid out as a board, then the groups
   of your deck, with the chat docked on the right ("App hub should be organizing widgets with the
   Chat on the right side"). A desktop set to it is a glance board, a launcher and a place to ask.

   Nothing here is a second list. The groups are DECK.groups (deckShown hides what you hid), the
   widgets are deckBoardHTML's cards, a tile opens with openApp and its menu is the deck's.
   Widget frames are the deck's own sandboxed frames, built by deckBoardHTML, mounted only while the
   desktop is bare: a hidden frame left running is a timer nobody can see. No frame loop and no
   blur of its own. It is not in LITE_SCENES: what its widgets cost on a Pi's own screen has not
   been measured, so that screen shows Aurora and a phone or laptop looking at it shows the hub.

   TUI: not applicable, a terminal has no desktop; `bento apps` lists the apps. SUI: words and
   frames in the desktop layer, like the Devices scene; nothing touches the compositor. */
var APPHUB={on:false,el:null,live:false,sig:''};
function appHubStart(){
  if(APPHUB.on)return;
  APPHUB.on=true;
  const desk=document.getElementById('desktop'),home=document.getElementById('home');
  if(!desk)return;
  let el=document.getElementById('apphub');
  if(!el){el=document.createElement('div');el.id='apphub';el.setAttribute('role','region');
    el.setAttribute('aria-label','Your apps and widgets');desk.insertBefore(el,home?home.nextSibling:null)}
  APPHUB.el=el;el.hidden=false;
  // the chat on the right is the Devices scene's panel (01h devChat*), open here unless folded
  if(typeof devChatMount==='function')devChatMount();
  appHubPaint();
}
function appHubStop(){
  if(!APPHUB.on)return;
  APPHUB.on=false;APPHUB.live=false;APPHUB.sig='';
  const el=document.getElementById('apphub');if(el){el.hidden=true;el.textContent=''}
  // leaving gives the bar back: answers kept for the panel have nowhere to stay
  const wrap=document.getElementById('omnicards');
  if(wrap)[...wrap.children].forEach(c=>{if(c.dataset.done&&c._close)c._close()});
  const bar=document.getElementById('omnibar');if(bar)bar.classList.remove('dvc-news');
  // the Devices scene may be the one starting: it reads its own choice for the panel
  if(typeof DEVSCENE!=='undefined'&&DEVSCENE.on&&typeof devChatMount==='function')devChatMount();
}
function appHubBare(){
  const b=document.body.classList;
  return !document.hidden&&!b.contains('has-win')&&!b.contains('deck-full')&&!b.contains('exposing');
}
/* A window opened or closed, or the wall did: the widgets run only while they can be seen. */
function appHubSync(){
  if(!APPHUB.on)return;
  if(appHubBare()!==APPHUB.live)appHubPaint();
}
function appHubPaint(){
  const el=APPHUB.el;if(!APPHUB.on||!el)return;
  // the deck and the app table are `let`s in later files: until they exist there is nothing to draw
  let ready=false;try{ready=!!(DECK&&APPS)}catch(e){}
  if(!ready)return;
  if(!appHubBare()){if(APPHUB.live){el.textContent='';APPHUB.live=false;APPHUB.sig=''}return}
  const groups=DECK.groups.map(g=>({g,ids:deckShown(g)})).filter(x=>x.ids.length);
  const apps={};(typeof USERAPPS!=='undefined'?USERAPPS:[]).forEach(a=>apps[a.id]=a);
  const wid=(typeof WIDGETS!=='undefined'?WIDGETS:[]).filter(w=>apps[w.app_id]);
  // the deck rebuilds often (a fold, a window): only a real change redraws, or every frame reloads
  const sig=JSON.stringify([groups.map(x=>[x.g.name,x.ids]),wid.map(w=>[w.app_id,w.place||'',apps[w.app_id].widget_size||'m'])]);
  if(APPHUB.live&&sig===APPHUB.sig)return;
  APPHUB.live=true;APPHUB.sig=sig;
  el.innerHTML=`<section class="ah-wid" aria-label="Widgets">
      <header><h2>Widgets</h2><span class="mut">${wid.length?wid.length+' live':''}</span></header>
      <div class="ah-board">${deckBoardHTML()}</div></section>
    <section class="ah-apps" aria-label="Apps">
      <header><h2>Apps</h2><button type="button" class="endbtn ah-all">All apps</button></header>
      <div class="ah-groups">${groups.map(({g,ids})=>`<div class="deck-group ah-g">
        <div class="deck-gname">${esc(g.name)}</div>
        <div class="deck-tiles">${ids.map(id=>`<button type="button" class="deck-tile" data-app="${esc(id)}"
          title="${esc(APPS[id].desc||APPS[id].title)}">${appIcon(id,46)}<span>${esc(APPS[id].title)}</span></button>`).join('')}</div>
      </div>`).join('')}</div></section>`;
  el.querySelector('.ah-all').onclick=()=>deckFull(true,'apps');
  el.querySelectorAll('.deck-tile[data-app]').forEach(t=>{
    t.onclick=()=>openApp(t.dataset.app);
    t.oncontextmenu=e=>{e.preventDefault();deckTileMenu(e,t.dataset.app)};
  });
  el.querySelectorAll('.deck-board').forEach(c=>{
    const id=c.dataset.w;
    c.querySelector('.db-open').onclick=()=>openApp('ua_'+id);
    c.querySelector('.deck-gname').oncontextmenu=e=>{e.preventDefault();deckBoardMenu(e,id)};
  });
  const st=el.querySelector('.de-studio'),so=el.querySelector('.de-store');
  if(st)st.onclick=()=>openApp('studio');
  if(so)so.onclick=()=>openApp('store');
}
document.addEventListener('visibilitychange',()=>appHubSync());
// the first paint runs before this file exists (01b applyImmersive), so the scene starts itself
if(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&immersiveSceneNow()==='apps')setTimeout(appHubStart,0);
