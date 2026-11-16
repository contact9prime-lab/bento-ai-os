/* ================= the menu bar fits its screen =================
   Reported with a 1366x768 screenshot: the space chip sat on top of Window and Help,
   "Bento Box AI" wrapped onto two lines and the clock onto three. Every part of the bar
   was a flex item that could shrink, so the menus shrank under their neighbours instead
   of anything giving way.

   Now nothing in the bar shrinks or wraps (44-menubar-fit.css). When it does not fit, the
   icon controls move to a rail on the right edge first (below), and only if the bar still
   does not fit does it let go of things in ONE order, least useful first, each step a class on #menubar:
     f1 the date beside the clock          f5 battery percent, your name (initial stays)
     f2 the words "Bento Box AI"            f6 the space name shortened further
     f3 the ADMIN tag and the model name    f7 the focused app's name (its menus stay)
     f4 the space name, to 150px            f8 the app's menus folded into one ☰ list
   and on a phone-sized bar: f9 the brain chip as its dot, f10 the space chip, f11 your chip.
   Every one is still a tooltip or a click away; nothing is removed from the machine.

   Measured, never guessed: each pass starts from nothing hidden and adds a step while
   the bar is wider than the screen. It runs on resize and when anything in the bar
   changes (a window takes focus, the clock ticks, a chip appears); it only changes
   classes on #menubar itself, which the observer does not watch, so it cannot loop.

   SUI: the bar's height is reported to the compositor (00-sui.js); nowrap keeps it one
   line, which is the same height on every screen. TUI: not applicable, a terminal has
   no menu bar. A phone keeps its own layout (15-responsive.css); this only ever hides. */
/* The right edge first (asked for as "use the right part of the screen, like the tool bar
   extending to the right on the edge"): before anything is hidden, the bar's icon controls
   (mic, network, sound and battery, notifications, your account, the brain) move into a rail
   down the right edge of the screen, and the top bar keeps the menus, the space and the
   brand. The desktop gives the rail its width (body.mb-rail #desktop), so a window, a
   maximised one too, stops at the rail instead of lying under it. The elements are MOVED,
   not copied: same ids, same handlers, one of each.
   Only where the page owns the screen's edges: not in SUI (the compositor reserves the top
   and bottom bands only, so native windows would cover a rail; there the bar hides instead),
   not on a phone (its own layout, 15-responsive.css) and not in the kiosk. */
/* Two stages: the plain icons go first; your chip and the brain chip keep their words in the
   top bar and move only if the bar still does not fit (the first cut moved all six at once,
   and a 1366 screen showed a P and a dot beside 330px of empty bar). */
var MBRAIL_STAGES=[['tray-voice','tray-net','tray-ctl','tray-bell'],['mb-user','fwdchip']];
var MBRAIL_IDS=MBRAIL_STAGES[0].concat(MBRAIL_STAGES[1]);
var MBFIT={n:0,max:11,raf:0,rail:0,obs:null};
function menubarRailAllowed(){
  const b=document.body.classList;
  if(b.contains('dev-mobile')||b.contains('kiosk'))return false;
  try{if(typeof suiActive==='function'&&suiActive())return false}catch(e){}
  try{if(localStorage.getItem('menubar.rail')==='0')return false}catch(e){}
  return !!document.getElementById('mbrail');
}
function menubarRail(stage){
  const on=stage>0,ids=on?MBRAIL_STAGES.slice(0,stage).flat():[];
  const rail=document.getElementById('mbrail'),tray=document.getElementById('tray');
  if(!rail||!tray)return;
  ids.forEach(id=>{const e=document.getElementById(id);if(e&&e.parentNode!==rail)rail.appendChild(e)});
  {
    const spin=document.getElementById('spin'),dot=document.getElementById('statdot');
    MBRAIL_IDS.filter(id=>!ids.includes(id)).forEach(id=>{const e=document.getElementById(id);if(!e||e.parentNode===tray)return;
      const before=(id==='mb-user'||id==='fwdchip')?dot:spin;
      tray.insertBefore(e,before&&before.parentNode===tray?before:null)});
  }
  rail.hidden=!on;
  document.body.classList.toggle('mb-rail',on);
  MBFIT.rail=stage;
}
function menubarFit(){
  MBFIT.raf=0;
  const mb=document.getElementById('menubar');if(!mb)return;
  const set=n=>{for(let i=1;i<=MBFIT.max;i++)mb.classList.toggle('f'+i,i<=n)};
  const over=()=>mb.scrollWidth>mb.clientWidth+1;
  let n=0;set(0);
  menubarRail(0);
  // the icons to the edge, then the date, then the two chips, then the steps above
  const rail=menubarRailAllowed();
  if(rail&&over())menubarRail(1);
  if(over()){n=1;set(1)}
  if(rail&&over())menubarRail(2);
  while(n<MBFIT.max&&over()){n++;set(n)}
  MBFIT.n=n;
  // what this pass moved is not news: drop it, or the observer would run the fit again
  if(MBFIT.obs)MBFIT.obs.takeRecords();
}
function menubarFitSoon(){if(!MBFIT.raf)MBFIT.raf=requestAnimationFrame(menubarFit)}
(function(){
  const mb=document.getElementById('menubar');if(!mb)return;
  try{new ResizeObserver(menubarFitSoon).observe(mb)}catch(e){addEventListener('resize',menubarFitSoon)}
  const opts={childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden']};
  try{MBFIT.obs=new MutationObserver(menubarFitSoon);MBFIT.obs.observe(mb,opts);
    const rail=document.getElementById('mbrail');if(rail)MBFIT.obs.observe(rail,opts)}catch(e){}
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(menubarFitSoon);
  menubarFitSoon();
})();
