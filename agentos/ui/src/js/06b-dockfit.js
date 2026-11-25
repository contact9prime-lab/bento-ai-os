/* ================= the phone dock shows whole icons =================
   Reported as "the dock and bar, there are issues in ui", and before that as "the bar below
   looks broken". On a phone the dock is a row that scrolls, and a row that scrolls rested with
   half an icon at its edge: scroll-snap keeps ONE edge whole, and the row's width was whatever
   the screen left over (318px for 44px icons, so 7.2 of them). Half an icon is a tap target
   whose centre is outside its own row.

   So the two rows are sized here, in whole icons: the running apps that are not pinned get up
   to a third of the bar, the pinned ones the rest. Measured from the bar as it is, on resize
   and whenever an icon comes or goes. Only on a phone: everywhere else the dock is as wide as
   its icons and nothing is set.

   GUI: this. TUI: not applicable, a terminal has no dock. SUI: the dock there is never a
   phone's (the session owns a real screen), so nothing is set. */
var DOCKFIT={raf:0,obs:null};
function dockFit(){
  DOCKFIT.raf=0;
  const tb=document.getElementById('taskbar'),dock=document.getElementById('dock'),wins=document.getElementById('tbwins');
  if(!tb||!dock)return;
  [dock,wins].forEach(e=>{if(e){e.style.flex='';e.style.width='';e.style.maxWidth=''}});
  if(!document.body.classList.contains('dev-mobile')){if(DOCKFIT.obs)DOCKFIT.obs.takeRecords();return}
  const shown=el=>[...el.children].filter(c=>c.offsetWidth>0);
  const whole=(el,avail)=>{
    const k=shown(el);if(!k.length)return 0;
    const gap=parseFloat(getComputedStyle(el).columnGap)||0,pitch=k[0].offsetWidth+gap;
    return Math.max(1,Math.min(k.length,Math.floor((avail+gap)/pitch)))*pitch-gap;
  };
  const cs=getComputedStyle(tb),gap=parseFloat(cs.columnGap)||0;
  const inner=tb.clientWidth-(parseFloat(cs.paddingLeft)||0)-(parseFloat(cs.paddingRight)||0);
  let avail=inner-[...tb.children].filter(c=>c!==dock&&c!==wins&&c.offsetWidth>0).reduce((s,c)=>s+c.offsetWidth+gap,0);
  if(wins&&shown(wins).length){
    const w=whole(wins,inner*.36);
    wins.style.flex='none';wins.style.maxWidth='none';wins.style.width=w+'px';
    avail-=w+gap;
  }
  dock.style.flex='none';dock.style.width=whole(dock,avail)+'px';
  // what this pass set is not news
  if(DOCKFIT.obs)DOCKFIT.obs.takeRecords();
}
function dockFitSoon(){if(!DOCKFIT.raf)DOCKFIT.raf=requestAnimationFrame(dockFit)}
(function(){
  const tb=document.getElementById('taskbar');if(!tb)return;
  try{new ResizeObserver(dockFitSoon).observe(tb)}catch(e){addEventListener('resize',dockFitSoon)}
  // icons come and go, and a running app's tile hides when its app is pinned (class indock)
  try{DOCKFIT.obs=new MutationObserver(dockFitSoon);
    DOCKFIT.obs.observe(tb,{childList:true,subtree:true,attributes:true,attributeFilter:['class','hidden']})}catch(e){}
  // the body learns it is a phone after the first paint
  try{new MutationObserver(dockFitSoon).observe(document.body,{attributes:true,attributeFilter:['class']})}catch(e){}
  dockFitSoon();
})();
