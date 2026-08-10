/* ================= logo ================= */
// A refined AgentOS mark: a rounded upward triangle (agency/ascent) with an agent "eye" node.
const LOGO_GLYPH=`<svg viewBox="0 0 24 24" width="64%" height="64%" style="display:block">
  <path d="M12 4.3 L19.6 18.4 Q20.1 19.3 19.1 19.3 L4.9 19.3 Q3.9 19.3 4.4 18.4 Z" fill="#04211c"/>
  <path d="M12 10.2 L15.9 17.6 L8.1 17.6 Z" fill="rgba(255,255,255,.22)"/>
  <circle cx="12" cy="8.6" r="1.5" fill="#04211c"/>
</svg>`;
function paintLogo(){document.querySelectorAll('.mark').forEach(m=>{m.innerHTML=LOGO_GLYPH})}

/* ================= init ================= */
paintLogo();
buildDesktop();
buildPager();
buildDock();
deckLoad();buildDeck();
paintSpaceChip();
/* the tray opens Control Center as a popover (macOS-style), not an app window */
$('#tray-ctl').onclick=e=>{e.stopPropagation();toggleControlCenter()};
$('#tray-voice').onclick=()=>jarvisMode(!JARVIS.on);
$('#tray-voice').innerHTML=svgMic(14);
/* power & session menu — AgentOS as the desktop environment carries real session
   controls in its menu bar (the boot-to-AgentOS direction) */
function powerMenuOpen(force){
  const m=$('#powermenu');if(!m)return false;
  const on=force!==undefined?!!force:!m.classList.contains('show');
  m.classList.toggle('show',on);
  if(on){
    // Ctrl+Alt+Delete is reached for when something is already covering the
    // screen, so the desktop has to come forward with the menu or the menu is
    // behind whatever the problem is.
    if(typeof raiseShell==='function')raiseShell(true);
    popIn(m,{origin:'top right'});
  }
  return true;
}
$('#tray-power').onclick=e=>{e.stopPropagation();powerMenuOpen()};
document.addEventListener('click',e=>{
  if(!e.target.closest('#powermenu')&&!e.target.closest('#tray-power'))$('#powermenu').classList.remove('show');
});
async function powerDo(action,confirmMsg){
  $('#powermenu').classList.remove('show');
  const danger=['logout','restart','poweroff'].includes(action);
  if(confirmMsg&&!await osConfirm(confirmMsg,danger?'Anything unsaved in other apps will be lost.':'',
    {confirmText:{lock:'Lock',suspend:'Suspend',logout:'Log out',restart:'Restart',poweroff:'Power off','agentos-restart':'Restart'}[action]||'OK',danger}))return;
  try{
    const r=await fetch('/api/power',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    const d=await r.json();
    if(!r.ok)return toast(d.error||action+' failed');
    if(action==='agentos-restart')toast('AgentOS is restarting — the desktop reconnects automatically');
    else toast('✓ '+action);
  }catch(e){toast(action+': '+e)}
}
$('#j-mic').innerHTML=svgMic(22);
$('#j-mic').onclick=()=>{if(JARVIS.phase==='listening'){try{JARVIS.rec.stop()}catch(e){}}else jarvisListen()};
$('#j-close').onclick=()=>jarvisMode(false);
$('#tray-bell').onclick=e=>{e.stopPropagation();openNotifPanel()};
document.addEventListener('click',e=>{
  if(!e.target.closest('#notifpanel')&&!e.target.closest('#tray-bell'))$('#notifpanel').classList.remove('show');
});
updateTray();setInterval(updateTray,15000);
// Polling is the fallback; the first compositor 'wm' event switches the
// taskbar to event-driven updates (see the WebSocket handler).
updateNativeWindows();startNativePoll();
tickClock();setInterval(tickClock,5000);
loadWallpaper();
loadThemes();
loadAutomations();   // the palette and the hot-corner picker both read this list
loadToolNames();     // tool + MCP names for automation steps
loadUserApps().then(loadWidgets);
loadNativeApps();
usersBoot();         // who is signed in — nothing at all unless this machine has accounts
APPS_READY=true;
// If this page is the Linux session's desktop, tell the compositor how much
// room our chrome needs so no application window can cover it.
if(typeof suiInit==='function')suiInit();
if(EXPERIENCE==='jarvis')buildJarvisShell();   // APPS now defined — populate the shell if a theme selected it early
connect();
/* the splash leaves when the desktop is actually ready (config + platform +
   setup state loaded), not on a timer; 8s is the give-up cap so a wedged
   endpoint can never trap the user behind the splash */
(async()=>{
  const t0=performance.now();
  try{
    await Promise.race([
      Promise.allSettled([loadPlatform(),loadConfig(),checkSetup()]),
      new Promise(r=>setTimeout(r,8000)),
    ]);
  }catch(e){}
  const wait=Math.max(0,650-(performance.now()-t0));   // let the mark breathe — no sub-frame flash
  setTimeout(()=>{
    const b=$('#boot');if(b){b.classList.add('off');setTimeout(()=>b.remove(),500)}
    if($('#setup-wiz'))return;      // a first run has no desktop to bring back
    // Bring back the desktop this page had before it reloaded. After the splash,
    // so eight windows do not animate in behind it, and never during setup.
    try{if(typeof sessionRestore==='function')sessionRestore()}catch(e){}
    // the prompt bar owns the caret from the first frame — the OS is ready to be told what to do
    const oi=$('#omni-in');if(oi)setTimeout(()=>oi.focus(),60);
  },wait);
})();
