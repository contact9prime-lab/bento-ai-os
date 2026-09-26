/* ================= immersive experience (the default look) =================
   (Numbered 01b: it has to have put `immersive` on <body> before 02-themes
   applies a theme, or the first paint is the standard look and then jumps.)

   One switch, in Settings → Appearance, kept per browser like the theme —
   `localStorage.immersive` — because it is a choice about the screen in front
   of you, not about the machine: a phone looking at this desktop over the LAN
   may want the plain one. The look itself is entirely 20-immersive.css; this
   file owns the state, the one piece of motion CSS cannot do (a wallpaper that
   follows the pointer), and the things that must be re-done when the material
   changes (re-measure glass, re-send the chrome bands to a session host).

   Faces — GUI: this. SUI: identical, plus suiSyncStruts() because the dock
   grows by 2px. TUI: not applicable — a terminal has no wallpaper or glass; the
   switch's own text says so. */
/* Monday first, as the server counts them (flows.WEEKDAYS). Shared by the flow
   editor, the scheduler and the Missions catalogue. */
var WEEKDAY_NAMES=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
/* ON by default (2026-09): the immersive look is the desktop now, and the standard
   one is what somebody switches to. Only an explicit '0' — this browser switched it
   off — keeps it off; everything it restyles is still scoped to body.immersive, so
   off stays byte-for-byte the standard desktop. A storage that throws (a private
   window) gets the default. */
function immersiveStored(){try{return localStorage.getItem('immersive')}catch(e){return null}}
var IMMERSIVE={on:immersiveStored()!=='0',scene:localStorage.getItem('immersive.scene')||'aurora',raf:0,tx:0,ty:0,bound:false,mo:null,homeT:0};
function immersiveOn(){return IMMERSIVE.on}
function applyImmersive(){
  document.body.classList.toggle('immersive',IMMERSIVE.on);
  document.body.classList.toggle('imm-movement',IMMERSIVE.on&&IMMERSIVE.scene==='movement');
  document.body.classList.toggle('imm-crew',IMMERSIVE.on&&IMMERSIVE.scene==='crew');
  immersiveParallax(IMMERSIVE.on);
  immersiveIcons(IMMERSIVE.on);
  homeRender();
  // the drawn scenes: the watch movement (01c) and the crew (01d). Both load
  // AFTER this file, so at first paint each is still undefined and starts itself;
  // from then on the switch is handled here. Each is tested separately — one
  // early `return` on the first undefined would leave the other permanently
  // unreachable on a first paint, which is the bundle-order trap in a new shape.
  if(typeof MOVEMENT!=='undefined'){if(IMMERSIVE.on&&IMMERSIVE.scene==='movement')movementStart();else movementStop()}
  if(typeof CREW!=='undefined'){if(IMMERSIVE.on&&IMMERSIVE.scene==='crew')crewStart();else crewStop()}
}
/* Which scene: 'aurora' (a sky that follows the day), 'movement' (a watch movement
   that shows what is running) or 'crew' (the roster, drawn, working). Per browser,
   like the look itself. An unknown name falls back to aurora rather than throwing —
   this value comes out of localStorage, which outlives any release that renames a
   scene, and a desktop that fails to paint because of a stale string is not a
   trade worth making. */
var IMMERSIVE_SCENES=['aurora','movement','crew'];
function setImmersiveScene(scene){
  scene=IMMERSIVE_SCENES.indexOf(scene)<0?'aurora':scene;
  IMMERSIVE.scene=scene;localStorage.setItem('immersive.scene',scene);
  applyImmersive();
  if(typeof loadWallpaper==='function')loadWallpaper();
  if(typeof refreshApp==='function')refreshApp('settings');
}
/* A window opened: the prompt bar stands down (CSS), but a caret left in it —
   the wall hands focus back to the bar when it closes — would keep the bar up
   through :focus-within and, worse, swallow the keystrokes meant for the window.
   So the caret leaves the bar unless the bar was deliberately summoned. */
function immersiveWinChange(){
  if(!IMMERSIVE.on)return;
  const inp=document.getElementById('omni-in'),bar=document.getElementById('omnibar');
  if(!inp||!bar)return;
  if(document.body.classList.contains('has-win')&&document.activeElement===inp&&!bar.classList.contains('summoned')&&!bar.classList.contains('pop'))inp.blur();
}
/* The brain chip's text, as words. Its two spans (executor, model) have no
   separator between them in the DOM, so textContent reads "Claude Codedefault". */
function immersiveBrainText(){
  const chip=document.getElementById('fwdchip');
  if(!chip||chip.hidden)return '';
  return [...chip.childNodes].map(n=>n.textContent.replace(/\s+/g,' ').trim().replace(/^[^\p{L}\p{N}]+/u,'')).filter(Boolean).join(' · ');
}
/* The look's wallpaper follows the day: first light until late morning, the
   aurora through the afternoon and evening, the cold sky after dark. The home
   scene's minute tick re-checks the band and reloads only when it changes —
   a wallpaper that swaps under an open window every minute would be a bug. */
function immersiveWallBand(){const h=new Date().getHours();return h>=5&&h<11?'immersive-dawn':h>=11&&h<19?'immersive':'immersive-night'}
function immersiveWall(){return !IMMERSIVE.on?'':IMMERSIVE.scene==='movement'?'immersive-movement':IMMERSIVE.scene==='crew'?'immersive-crew':immersiveWallBand()}
/* ---- the home scene ----
   With no window open the desktop is a place, not a tile board: a greeting by
   the hour (and by name on a machine with accounts), the date, the prompt bar
   in the upper third, three things to try, and one line of what the agent is
   doing. It re-renders once a minute — the greeting and the date are the only
   things that move — and whenever the look is switched. Chips fill the prompt
   bar rather than sending, so the first message is still the person's. */
var HOME_CHIPS=['How is this machine doing? Check CPU, memory and disk.',
  'What is taking up the most space in my home folder?',
  'Every morning at 9, check disk space and tell me if it is low.',
  'Fetch the top Hacker News stories and summarise them.',
  'Create a project folder with a starter README in my workspace.',
  'Remember that I prefer concise answers.',
  'Watch my Downloads folder and tell me what lands there.',
  'Draft a flow that briefs me every morning.'];
/* The same three chips, but for the person who said who they are: a founder's
   first message should not be about disk space. Keyed on cfg.persona (a USER_KEY
   the Missions catalogue sets); the neutral list is the fallback. */
var HOME_CHIPS_BY={
  founder:['Watch my competitors\' pricing pages and tell me when they change.',
    'Draft my investor update every Friday from my notes folder.',
    'Tell me when my company or my competitors are in the news.',
    'What is the one thing I should do today, from what you know about me?',
    'Every morning at 8, brief me on my market.',
    'Remember that our runway ends in March.'],
  coder:['Write my standup from the repos in ~/code.',
    'Review what I pushed today and tell me what looks risky.',
    'Run the tests in my project every morning and tell me if they are red.',
    'Tell me when fastapi or pydantic ship a new release.',
    'What changed in this repo this week?',
    'Remember that I prefer small commits with tests.'],
  consultant:['Read what lands in my client\'s folder and tell me what they want.',
    'Draft the weekly status report for Acme every Friday.',
    'Tell me when my clients are in the news.',
    'What did I work on this week, by client?',
    'Every morning at 8, brief me on my clients\' industries.',
    'Remember that Acme\'s invoice terms are net 30.']};
function homeChips(){
  const p=(typeof cfg!=='undefined'&&cfg&&cfg.persona)||'';
  return HOME_CHIPS_BY[p]||HOME_CHIPS;
}
function homeRender(){
  const h=document.getElementById('home');if(!h)return;
  if(!IMMERSIVE.on){h.hidden=true;clearInterval(IMMERSIVE.homeT);IMMERSIVE.homeT=0;return}
  const now=new Date(),hr=now.getHours();
  const part=hr<5?'Good night':hr<12?'Good morning':hr<17?'Good afternoon':hr<22?'Good evening':'Good night';
  const me=(typeof USERS!=='undefined'&&USERS.me&&USERS.me.multiuser)?String(USERS.me.display||USERS.me.name||'').trim().split(/\s+/)[0]:'';
  h.querySelector('.hm-hi').textContent=part+(me?', '+me:'');
  let date='';try{date=now.toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long'})}catch(e){date=now.toDateString()}
  h.querySelector('.hm-date').textContent=date;
  const day=Math.floor(now/864e5);
  const pool=homeChips();
  const chips=[0,1,2].map(i=>pool[(day*3+i)%pool.length]);
  const box=h.querySelector('.hm-chips');
  const key=String(day)+':'+((typeof cfg!=='undefined'&&cfg&&cfg.persona)||'');
  if(box.dataset.day!==key){box.dataset.day=key;
    box.innerHTML=chips.map(c=>`<button class="hm-chip">${esc(c)}</button>`).join('');
    box.querySelectorAll('.hm-chip').forEach((b,i)=>b.onclick=()=>{const inp=document.getElementById('omni-in');if(!inp)return;
      inp.value=chips[i];inp.dispatchEvent(new Event('input'));inp.focus();
      const n=inp.value.length;try{inp.setSelectionRange(n,n)}catch(e){}});}
  const n=(typeof RUNNING!=='undefined')?RUNNING.size:0;
  const who=(typeof agentName==='function')?agentName():'Aria';
  const brain=immersiveBrainText();
  const line=h.querySelector('.hm-now');
  const br=(typeof BRIEF!=='undefined'&&BRIEF.page&&BRIEF.page.open)?BRIEF.page.headline:'';
  // the agent's face on its own line: the one on the stage and beside every reply.
  // Rewritten only when the words change, so the image is not refetched every minute.
  const said=n?`${who} is working on ${n} ${n===1?'turn':'turns'}`:(br?`Your Brief: ${br}`:(brain?`${who} · ${brain}`:`${who} is ready`));
  const html=(typeof avatarImg==='function'?avatarImg('@agent','av-home'):'')+esc(said);
  if(line.dataset.said!==html){line.dataset.said=html;line.innerHTML=html}
  line.classList.toggle('br-open',!n&&!!br);
  line.onclick=(!n&&br)?()=>openApp('brief'):null;
  h.hidden=false;
  const band=immersiveWallBand();
  if(IMMERSIVE.scene==='aurora'&&IMMERSIVE.band&&IMMERSIVE.band!==band&&typeof loadWallpaper==='function')loadWallpaper();
  IMMERSIVE.band=band;
  if(!IMMERSIVE.homeT){IMMERSIVE.homeT=setInterval(homeRender,60000);
    if(typeof briefLoad==='function')briefLoad().then(()=>homeRender());}
}
/* Glyph → icon. Any element with data-ic="name" is a unicode glyph in the
   standard desktop and the matching SVG (00d-icons.js) in this look. The glyph
   is kept on the element so switching back restores it byte for byte. Apps
   render their own markup whenever they open, so a MutationObserver swaps
   what arrives later — one query per added subtree, nothing per frame. */
function immersiveIconize(root){
  const els=root.querySelectorAll?root.querySelectorAll('[data-ic]'):[];
  els.forEach(el=>{
    if(IMMERSIVE.on){
      if(el.dataset.gl===undefined)el.dataset.gl=el.innerHTML;
      const svg=typeof uiIcon==='function'?uiIcon(el.dataset.ic,el.dataset.icpx?+el.dataset.icpx:15):'';
      if(svg&&!el.querySelector('svg.ic'))el.innerHTML=svg;
    }else if(el.dataset.gl!==undefined){el.innerHTML=el.dataset.gl;delete el.dataset.gl}
  });
}
function immersiveIcons(on){
  immersiveIconize(document);
  if(on&&!IMMERSIVE.mo&&window.MutationObserver){
    IMMERSIVE.mo=new MutationObserver(ms=>{if(!IMMERSIVE.on)return;
      ms.forEach(m=>{
        // a button whose glyph was (re)written in place — #omni-shot is set by
        // the omnibar after this file ran — is the parent of the mutation
        const t=m.target;
        if(t&&t.nodeType===1&&t.dataset&&t.dataset.ic!==undefined&&!t.querySelector('svg.ic')){delete t.dataset.gl;immersiveIconize({querySelectorAll:()=>[t]})}
        m.addedNodes.forEach(n=>{if(n.nodeType===1){if(n.dataset&&n.dataset.ic!==undefined)immersiveIconize({querySelectorAll:()=>[n]});immersiveIconize(n)}});
      })});
    IMMERSIVE.mo.observe(document.body,{childList:true,subtree:true});
  }
  if(!on&&IMMERSIVE.mo){IMMERSIVE.mo.disconnect();IMMERSIVE.mo=null}
}
function setImmersive(on){
  on=!!on;
  const changed=on!==IMMERSIVE.on;
  IMMERSIVE.on=on;localStorage.setItem('immersive',on?'1':'0');
  // crossfade, as a theme change does, instead of hard-cutting every surface at once
  if(changed&&document.startViewTransition&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
    try{document.startViewTransition(applyImmersive)}catch(e){applyImmersive()}
  }else applyImmersive();
  if(!changed)return;
  if(typeof loadWallpaper==='function')loadWallpaper();     // the look ships a wallpaper; theme and file still outrank it
  if(typeof glassProbe==='function')glassProbe(true);       // one more blurred surface — can this machine still draw it?
  if(typeof suiSyncStruts==='function')suiSyncStruts();     // the dock's band changed height
  if(typeof refreshApp==='function'){refreshApp('settings');refreshApp('themes')}
  if(typeof toast==='function')toast(on?'Immersive experience on — Settings → Appearance turns it off':'Back to the standard desktop');
}
/* The wallpaper drifts a few pixels against the pointer, so the desktop reads as
   a scene with depth instead of a picture. It is a transform on one composited
   layer, throttled to a frame, and it is NOT offered where it would be wrong:
   a touch screen has no pointer to follow, and reduced-motion means it. */
function immersiveParallax(on){
  const w=document.getElementById('wall');if(!w)return;
  const ok=on&&!(typeof isTouch==='function'&&isTouch())&&!matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(ok&&!IMMERSIVE.bound){IMMERSIVE.bound=true;addEventListener('pointermove',immersivePointer,{passive:true})}
  if(!ok&&IMMERSIVE.bound){IMMERSIVE.bound=false;removeEventListener('pointermove',immersivePointer)}
  if(!ok){w.style.transform=''}
}
function immersivePointer(e){
  IMMERSIVE.tx=e.clientX/innerWidth-.5;IMMERSIVE.ty=e.clientY/innerHeight-.5;
  if(IMMERSIVE.raf)return;
  IMMERSIVE.raf=requestAnimationFrame(()=>{
    IMMERSIVE.raf=0;
    const w=document.getElementById('wall');if(!w||!IMMERSIVE.on)return;
    w.style.transform=`translate3d(${(-IMMERSIVE.tx*16).toFixed(1)}px,${(-IMMERSIVE.ty*12).toFixed(1)}px,0) scale(1.04)`;
  });
}
applyImmersive();
