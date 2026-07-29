/* ================= device classes =================
   One desktop, three form factors. The CSS in 15-responsive.css does the layout
   work off `body.dev-*`; this file owns the classification and the handful of
   behaviours CSS cannot express (windows become sheets on a phone, the dock
   rebuilds at a new size, panels close when the shape changes under them).

   Breakpoints are on the *viewport*, not on the user agent: a narrow browser
   window on a laptop gets the phone layout, which is exactly what you want when
   AgentOS is docked beside an editor. Touch is tracked separately, because a
   tablet and a touchscreen laptop want the same hit targets at different widths. */
const DEV_BP={mobile:720, tablet:1180};   // < mobile → phone, < tablet → tablet, else desktop
let DEVICE='desktop', DEVICE_TOUCH=false;
function deviceClassFor(w){return w<DEV_BP.mobile?'mobile':w<DEV_BP.tablet?'tablet':'desktop'}
function isMobile(){return DEVICE==='mobile'}
function isTablet(){return DEVICE==='tablet'}
function isHandheld(){return DEVICE!=='desktop'}
function isTouch(){return DEVICE_TOUCH}

function applyDevice(){
  const b=document.body, prev=DEVICE;
  DEVICE=deviceClassFor(innerWidth);
  DEVICE_TOUCH=matchMedia('(pointer:coarse)').matches||navigator.maxTouchPoints>0;
  b.classList.toggle('dev-mobile',DEVICE==='mobile');
  b.classList.toggle('dev-tablet',DEVICE==='tablet');
  b.classList.toggle('dev-desktop',DEVICE==='desktop');
  b.classList.toggle('dev-handheld',DEVICE!=='desktop');
  b.classList.toggle('dev-touch',DEVICE_TOUCH);
  b.classList.toggle('dev-portrait',innerHeight>=innerWidth);
  document.documentElement.dataset.device=DEVICE;
  return DEVICE!==prev;
}
applyDevice();

/* A phone has no room for overlapping windows: every window is a full-bleed
   sheet, and the WM's maximize state is what already means "fill the screen",
   so reuse it rather than inventing a second mode. `wasMax` remembers the
   window's own choice so going back to a desktop width restores it. */
function fitWindowsToDevice(){
  if(typeof WM==='undefined')return;
  WM.wins.forEach(w=>{
    if(isMobile()){
      if(!w.max){w.wasMax=false;if(typeof toggleMax==='function')toggleMax(w)}
    }else if(w.wasMax===false&&w.max){
      w.wasMax=undefined;if(typeof toggleMax==='function')toggleMax(w);
    }
  });
}
/* Popovers are anchored to chrome that just moved — close them rather than
   leave them pointing at nothing. */
function closeTransientSurfaces(){
  ['#powermenu','#notifpanel','#startmenu','#ctxmenu','#ccpop'].forEach(s=>{
    const el=document.querySelector(s);if(el)el.classList.remove('show');
  });
  document.body.classList.remove('sheet-open');
}
let _devT=null;
addEventListener('resize',()=>{
  clearTimeout(_devT);
  _devT=setTimeout(()=>{
    if(!applyDevice())return;                 // same class → CSS already handled it
    closeTransientSurfaces();
    fitWindowsToDevice();
    if(typeof buildDock==='function')buildDock();
    if(typeof buildDeck==='function')buildDeck();
    if(typeof buildDesktop==='function')buildDesktop();
  },140);
});
addEventListener('orientationchange',()=>setTimeout(()=>{applyDevice();fitWindowsToDevice()},220));

/* iOS/Android address bars change the visual viewport without firing resize on
   `window`; --vh keeps full-height surfaces honest when they do. */
function trackViewportHeight(){
  const vv=window.visualViewport;
  const set=()=>document.documentElement.style.setProperty('--vh',((vv?vv.height:innerHeight)/100)+'px');
  set();
  if(vv){vv.addEventListener('resize',set);vv.addEventListener('scroll',set)}
  else addEventListener('resize',set);
}
trackViewportHeight();
