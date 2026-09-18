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
var IMMERSIVE={on:localStorage.getItem('immersive')==='1',raf:0,tx:0,ty:0,bound:false};
function immersiveOn(){return IMMERSIVE.on}
function applyImmersive(){
  document.body.classList.toggle('immersive',IMMERSIVE.on);
  immersiveParallax(IMMERSIVE.on);
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
