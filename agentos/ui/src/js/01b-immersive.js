/* ================= immersive experience (beta) =================
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
var IMMERSIVE={on:localStorage.getItem('immersive')==='1',raf:0,tx:0,ty:0,bound:false,mo:null};
function immersiveOn(){return IMMERSIVE.on}
function applyImmersive(){
  document.body.classList.toggle('immersive',IMMERSIVE.on);
  immersiveParallax(IMMERSIVE.on);
  immersiveIcons(IMMERSIVE.on);
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
      ms.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1){if(n.dataset&&n.dataset.ic!==undefined)immersiveIconize({querySelectorAll:()=>[n]});immersiveIconize(n)}}))});
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
  if(typeof toast==='function')toast(on?'Immersive experience on (beta) — Settings → Appearance turns it off':'Back to the standard desktop');
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
