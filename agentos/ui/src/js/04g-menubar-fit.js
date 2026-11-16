/* ================= the menu bar fits its screen =================
   Reported with a 1366x768 screenshot: the space chip sat on top of Window and Help,
   "Bento Box AI" wrapped onto two lines and the clock onto three. Every part of the bar
   was a flex item that could shrink, so the menus shrank under their neighbours instead
   of anything giving way.

   Now nothing in the bar shrinks or wraps (44-menubar-fit.css), and when it does not fit
   it lets go of things in ONE order, least useful first, each step a class on #menubar:
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
var MBFIT={n:0,max:11,raf:0};
function menubarFit(){
  MBFIT.raf=0;
  const mb=document.getElementById('menubar');if(!mb)return;
  const set=n=>{for(let i=1;i<=MBFIT.max;i++)mb.classList.toggle('f'+i,i<=n)};
  let n=0;set(0);
  while(n<MBFIT.max&&mb.scrollWidth>mb.clientWidth+1){n++;set(n)}
  MBFIT.n=n;
}
function menubarFitSoon(){if(!MBFIT.raf)MBFIT.raf=requestAnimationFrame(menubarFit)}
(function(){
  const mb=document.getElementById('menubar');if(!mb)return;
  try{new ResizeObserver(menubarFitSoon).observe(mb)}catch(e){addEventListener('resize',menubarFitSoon)}
  try{new MutationObserver(menubarFitSoon).observe(mb,{childList:true,subtree:true,characterData:true,
    attributes:true,attributeFilter:['hidden'],attributeOldValue:false})}catch(e){}
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(menubarFitSoon);
  menubarFitSoon();
})();
