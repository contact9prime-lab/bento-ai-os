/* ================= popovers: one rule for every one of them =================
   The launcher, the notification panel, the power menu, Quick Settings, the
   context menu and the menu-bar menus each owned a document-level click
   listener and a `.show` class, and none of them knew about the others.
   Measured on a fresh desktop: the power menu opened UNDER a still-open
   notification panel with Lock and Restart hidden; the palette opened beside
   Quick Settings; Escape closed none of them; and a menu-bar title's click was
   closed by another popover's listener in the same event, so File · Edit · View
   never opened by clicking at all.

   Three rules, written once:
   - opening one closes the rest (a menu and a panel are never both open);
   - Escape closes the one opened last (see the key handler);
   - a click outside closes whatever is open — decided in the CAPTURE phase,
     before the target's own handler runs, so a title's click can open its menu
     after the previous one has gone rather than being eaten by it.

   `anchor` is the control that toggles a popover: a click on it is left to that
   control's own handler, which is what makes a second click close it.
   TUI: not applicable. SUI: identical — these are page surfaces.
   GUI on a phone: the same elements are bottom sheets; the rules hold. */
var POPS=[];   // open popovers in the order they opened: {el, anchor, close}

function popOpen(el,opts){
  if(!el)return;
  opts=opts||{};
  popCloseAll(el);
  el.classList.add('show');
  POPS=POPS.filter(p=>p.el!==el);
  POPS.push({el,anchor:opts.anchor||null,close:opts.close||null});
}
function popClose(el){
  if(!el)return false;
  const i=POPS.findIndex(p=>p.el===el);
  el.classList.remove('show');
  if(i<0)return false;
  const p=POPS.splice(i,1)[0];
  if(p.close){try{p.close()}catch(e){}}
  return true;
}
function popCloseAll(except){
  POPS.slice().forEach(p=>{if(p.el!==except)popClose(p.el)});
}
function popIsOpen(el){return !!el&&POPS.some(p=>p.el===el)&&el.classList.contains('show')}
/* Escape: the most recently opened popover goes first. Returns whether one was
   there to close, so the caller can stop and not also leave full screen. */
function popCloseTop(){
  const p=POPS[POPS.length-1];
  if(!p)return false;
  popClose(p.el);
  return true;
}
document.addEventListener('click',e=>{
  if(!POPS.length)return;
  POPS.slice().forEach(p=>{
    if(!p.el.isConnected){popClose(p.el);return}
    if(p.el.contains(e.target))return;
    if(p.anchor&&p.anchor.contains&&p.anchor.contains(e.target))return;
    popClose(p.el);
  });
},true);
