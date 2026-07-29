/* ================= glass quality =================
   (Numbered 01a so it is initialised before 02-themes applies a theme on load —
   applyTheme re-probes, and a `const` read before its own file has run throws.)

   `backdrop-filter` is the most expensive thing a desktop shell can ask a
   browser for, and the cost is not per-window — it compounds. Every translucent
   surface makes the compositor re-blur everything beneath it, so stacked windows
   multiply: on this machine five open windows in the Liquid Glass theme took the
   desktop from 60fps to 6.5. That is the "it gets slow once several apps are
   loaded" that a native desktop does not have, and no amount of throttling
   JavaScript touches it, because it is not JavaScript.

   The base window rule no longer blurs at all (see 03-windows.css — it was
   blurring behind an opaque background, which cost everything and showed
   nothing). What is left is the themes that genuinely are glass, where the blur
   IS the design. For those, this is the volume knob:

     full     — every surface, as designed
     reduced  — only the focused window; the rest keep the tint, lose the blur.
                Cost stops growing with the number of open windows.
     off      — no blur anywhere, tints become solid. For a Raspberry Pi, a VM,
                or anything drawing in software.

   The default is `auto`: full until the machine says otherwise. It measures real
   frame times with real windows open — no device sniffing, no GPU allowlist,
   because the only honest test of whether this machine can draw this desktop is
   drawing it. */

const GLASS={pref:localStorage.getItem('glass')||'auto', level:'full', timer:null, told:false};

function glassLevel(){return GLASS.pref==='auto'?GLASS.level:GLASS.pref}
function applyGlass(){
  const l=glassLevel();
  document.body.classList.toggle('glass-lite',l==='reduced');
  document.body.classList.toggle('glass-off',l==='off');
}
function setGlass(pref){
  GLASS.pref=pref;localStorage.setItem('glass',pref);
  if(pref!=='auto')GLASS.level=pref;else GLASS.level='full';   // give the machine another chance
  applyGlass();
  if(typeof refreshApp==='function')refreshApp('themes');
  if(pref==='auto')glassProbe(true);
}

/* Measure, don't guess. Sampled a moment after the desktop changes, so we are
   timing the thing the user is actually looking at.

   Sampling is bounded by TIME, not by a frame count: a frame count is a trap
   here, because the slower the machine — the case this exists for — the longer
   it takes to reach it, so the machine that most needs the help waits longest
   for it. ~1s of frames is plenty to tell 60fps from 7. */
function glassProbe(force){
  if(GLASS.pref!=='auto'||GLASS.level==='off')return;   // nothing left to turn off
  if(!force&&GLASS.level!=='full')return;
  clearTimeout(GLASS.timer);
  GLASS.timer=setTimeout(()=>{
    let visible=0;
    if(typeof WM!=='undefined')WM.wins.forEach(w=>{if(typeof winAwake==='function'&&winAwake(w))visible++});
    if(visible<2)return;                              // one window is not a test of anything
    const gaps=[],t0=performance.now();let last=t0;
    const step=t=>{
      gaps.push(t-last);last=t;
      if(t-t0<900||gaps.length<8)return void requestAnimationFrame(step);
      const s=gaps.slice(2).sort((a,b)=>a-b), med=s[(s.length/2)|0]||0;
      if(med<=34)return;                              // ~30fps or better: leave the design alone
      GLASS.level=GLASS.level==='full'?'reduced':'off';
      applyGlass();
      if(typeof toast==='function'&&!GLASS.told){
        GLASS.told=true;
        toast('glass effects turned down to keep the desktop smooth — Themes → Effects');
      }
      glassProbe(true);                               // did that fix it? if not, step down again
    };
    requestAnimationFrame(step);
  },1400);
}
applyGlass();
