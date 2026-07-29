/* ================= window lifecycle: sleep and wake =================

   Why this exists.

   On a native desktop every app is its own process, and a window you cannot see
   costs you nothing: it is not drawn, its animations do not run, and a polite app
   stops working when it is minimised. Ten open apps feel like one.

   AgentOS apps are all live DOM in a single Chromium renderer. Nothing about
   being minimised, on another desktop, or buried under a maximized window stops
   an app's `setInterval` from firing — so ten open apps meant ten pollers, ten
   `fetch`es, ten re-renders and ten sets of layout work competing for one main
   thread. That is exactly the "it gets slow once several apps are loaded" that a
   native desktop does not have, and it is a lifecycle problem, not a speed one.

   So windows get the lifecycle they were missing. A window is AWAKE when you can
   actually see it, and ASLEEP otherwise; asleep windows keep their state and
   their DOM (reopening is instant) but stop doing periodic work.

   Two rules make this safe to use everywhere:

     1. Waking runs the work immediately, so a window is never revealed showing a
        stale frame from ten minutes ago. There is no "refreshing…" gap.
     2. Ticks belong to the window, so closing it stops them — the old
        `clearInterval(w.timer)`-in-onClose pattern leaked any second timer an app
        added, and leaked everything if onClose was forgotten.

   Apps opt in by using `winTick(w, fn, ms)` instead of `setInterval(fn, ms)`.
   Anything animating with requestAnimationFrame should bail on `!winAwake(w)`. */

const LIFE={asleep:0, awake:0, stopped:0};   // stopped = timers currently not running (Task Manager shows it)

/* Is this window worth spending time on? */
function winAwake(w){
  if(!w||!w.el||!w.el.isConnected)return false;
  if(w.min)return false;                                   // minimised
  if(typeof deskVisible==='function'&&!deskVisible(w))return false;   // another desktop
  if(document.hidden)return false;                         // the whole page is in the background
  return !winOccluded(w);
}
/* Fully covered by a maximized or full-screen window above it. Overlapping
   windows do NOT count — only a window that owns the whole desktop, because
   that is the case we can be certain about without hit-testing every pixel.
   During Spaces everything is on show, so nothing is occluded. */
function winOccluded(w){
  if(w.max||w.fs)return false;
  if(document.body.classList.contains('exposing'))return false;
  const z=+w.el.style.zIndex||0;
  let covered=false;
  WM.wins.forEach(o=>{
    if(covered||o===w||o.min||(typeof deskVisible==='function'&&!deskVisible(o)))return;
    if((o.max||o.fs)&&(+o.el.style.zIndex||0)>z)covered=true;
  });
  return covered;
}

/* A repeating job that belongs to a window. Runs once now (so the first paint is
   not an empty box), then every `ms` for as long as the window is awake.
   ms:0             — run on WAKE only, never on a schedule. For work that has
                      nothing to poll (a canvas repaint) but must not be left
                      showing whatever was on screen when the window went away.
   opts.key         — replaces any tick this window already has under that name.
                      Renders re-run (refreshApp, a websocket event, the user
                      pressing ↻) and two of them can overlap, so "register" has
                      to mean "replace" or a busy app quietly grows pollers.
   opts.now:false   — do not run immediately on creation
   opts.eager:false — do not run immediately on WAKE either (for jobs whose result
                      cannot go stale, or that are expensive enough to wait a tick) */
function winTick(w,fn,ms,opts){
  opts=opts||{};
  if(opts.key)(w._ticks||[]).filter(t=>t.key===opts.key).forEach(stopTick);
  const t={fn,ms,id:null,key:opts.key||null,eager:opts.eager!==false,alive:true,w};
  (w._ticks||(w._ticks=[])).push(t);
  if(opts.now!==false&&winAwake(w))fn();
  applyWindowActivity();
  return t;
}
/* Stop one tick early (its window stays alive) */
function stopTick(t){if(!t)return;t.alive=false;clearInterval(t.id);t.id=null;
  const a=t.w&&t.w._ticks;if(a){const i=a.indexOf(t);if(i>=0)a.splice(i,1)}}
/* Stop every tick a window owns. closeWin does this for you. */
function stopWinTicks(w){(w._ticks||[]).forEach(t=>{t.alive=false;clearInterval(t.id);t.id=null});w._ticks=[]}

/* The single pass that puts every window in the right state. Cheap and
   idempotent — call it from anything that changes what is visible. */
function applyWindowActivity(){
  let asleep=0,awake=0,stopped=0;
  WM.wins.forEach(w=>{
    const on=winAwake(w), was=w._awake!==false;      // first pass counts as "was awake"
    w._awake=on;
    on?awake++:asleep++;
    w.el.classList.toggle('asleep',!on);
    (w._ticks||[]).forEach(t=>{
      if(!t.alive)return;
      if(on){
        if(!was&&t.eager)t.fn();                     // waking: refresh now, never show a stale frame
        if(t.ms&&!t.id)t.id=setInterval(t.fn,t.ms);
      }else if(t.id){
        clearInterval(t.id);t.id=null;
      }
      if(t.ms&&!t.id)stopped++;
    });
  });
  LIFE.asleep=asleep;LIFE.awake=awake;LIFE.stopped=stopped;
}

/* The page itself going to the background is the same thing as every window
   being hidden — and on a phone, switching apps is the common case. */
document.addEventListener('visibilitychange',()=>applyWindowActivity());
