/* ---------------- Watch me once: the desktop notices a routine ----------------
   When the person does the same few steps twice (open Logs filtered to errors, then
   the Brief, then WhatsApp), a card offers to make it one click: a Routine (the
   desktop's own replayable sequence, 15a-automations.js) pinned to the desktop as a
   card, and if they like, played every day at nine.

   What is noted is the DOOR, never the content: which app, which tab, which place,
   which Logs filter. Not a word typed, not a file, not a message. It is kept in this
   page's memory only (a reload forgets it), only steps a person's own tap caused are
   noted (navigator.userActivation), nothing a Routine itself replays, and a sequence
   turned down is never offered again in this browser. Off is one switch in Settings →
   Appearance, remembered per account.
   Faces: GUI and SUI. A terminal has no desktop to watch; a Routine made here plays from
   the prompt bar and Missions → Routines, and `run_automation` reaches it from any chat. */
var WATCH={steps:[],quiet:0,offered:{},card:null};
var WATCH_KEEP=60,WATCH_WINDOW=45*60*1000,WATCH_MIN=3,WATCH_MAX=6;

function watchKey(){return 'watch.off'+((typeof AVATARS!=='undefined'&&AVATARS.uid)?':'+AVATARS.uid:'')}
function watchOn(){try{return localStorage.getItem(watchKey())!=='1'}catch(e){return true}}
function setWatchOn(on){try{localStorage.setItem(watchKey(),on?'0':'1')}catch(e){};if(!on)WATCH.steps=[]}
function watchSeen(){try{return JSON.parse(localStorage.getItem('watch.declined')||'{}')}catch(e){return {}}}
function watchDecline(sig){const d=watchSeen();d[sig]=Date.now();try{localStorage.setItem('watch.declined',JSON.stringify(d))}catch(e){}}

/* One step. kind 'app' (a = app id), 'view' (a = app id, v = the tab or filter) or
   'place' (a = a place's label, 05b-places.js). */
function watchNote(kind,a,v){
  try{
    if(!watchOn()||!a)return;
    if(typeof AUTO_RUNNING!=='undefined'&&AUTO_RUNNING)return;           // a routine replaying is not you
    if(navigator.userActivation&&!navigator.userActivation.isActive)return;  // code opening things is not you
    const now=Date.now();
    if(kind!=='place'&&now<WATCH.quiet)return;     // a place opens its app; the place is the step
    const last=WATCH.steps[WATCH.steps.length-1];
    if(kind==='view'){
      // a tab chosen right after its app opened is that same step, made precise
      if(last&&last.app===a&&now-last.at<4000){last.view=String(v||'');last.key=watchStepKey(last);last.at=now}
      else watchPush({app:a,view:String(v||''),at:now});
    }else if(kind==='place'){
      WATCH.quiet=now+1500;
      watchPush({place:a,at:now});
    }else{
      if(last&&last.app===a&&!last.view&&now-last.at<1500)return;
      watchPush({app:a,at:now});
    }
  }catch(e){}
}
function watchStepKey(s){return s.place?'place:'+s.place:'app:'+s.app+(s.view?'#'+s.view:'')}
function watchPush(s){
  s.key=watchStepKey(s);
  const last=WATCH.steps[WATCH.steps.length-1];
  if(last&&last.key===s.key)return;                // the same door twice in a row is one step
  WATCH.steps.push(s);
  if(WATCH.steps.length>WATCH_KEEP)WATCH.steps.shift();
  const hit=watchFind(WATCH.steps,Date.now());
  if(hit)watchOffer(hit);
}
/* The newest steps, if the same sequence of them happened earlier too. Longest first,
   at least two different doors, both times within the last WATCH_WINDOW. Pure, so the
   rule can be checked on its own. */
function watchFind(steps,now){
  const n=steps.length;
  for(let L=Math.min(WATCH_MAX,Math.floor(n/2));L>=WATCH_MIN;L--){
    const tail=steps.slice(n-L),keys=tail.map(s=>s.key);
    if(new Set(keys).size<2)continue;
    for(let j=n-2*L;j>=0;j--){
      const prev=steps.slice(j,j+L);
      if(prev[0].at<now-WATCH_WINDOW)break;
      if(prev.every((s,i)=>s.key===keys[i]))return {steps:tail,sig:keys.join('>')};
    }
  }
  return null;
}
function watchLabel(s){
  if(s.place)return s.place;
  const t=(APPS[s.app]&&APPS[s.app].title)||s.app;
  return s.view?t+' · '+s.view:t;
}
function watchRoutineSteps(steps){
  return steps.map(s=>s.place?{kind:'place',place:s.place}:(s.view?{kind:'app',app:s.app,view:s.view}:{kind:'app',app:s.app}));
}
function watchOffer(hit){
  if(WATCH.offered[hit.sig]||watchSeen()[hit.sig])return;
  WATCH.offered[hit.sig]=Date.now();
  const words=hit.steps.map(watchLabel);
  const old=document.getElementById('watchcard');if(old)old.remove();
  const c=document.createElement('div');c.id='watchcard';c.className='procard watchcard';
  c.innerHTML=`<div class="pc-head"><span data-ic="sparkles">✦</span> I just watched you do that twice</div>
    <div class="pc-text">${words.map(w=>`<span class="wt-step">${esc(w)}</span>`).join('<span class="wt-arr">→</span>')}</div>
    <div class="pc-text mut">Make it one click? It becomes a Routine with a card on your desktop.</div>
    <label class="wt-daily"><input type="checkbox" id="wt-daily"> Also play it every day at 9:00 ${pInfoSafe('Played on this desktop by your agent when the desktop is open. Change or stop it in Missions → Schedule.')}</label>
    <div class="pc-actions"><button class="pc-go" id="wt-yes">Make it one click</button><button class="pc-x" id="wt-no">Not this one</button></div>`;
  ($('#desktop')||document.body).appendChild(c);
  if(typeof popIn==='function')popIn(c,{origin:'bottom right'});
  c.querySelector('#wt-yes').onclick=()=>watchMake(hit,words,c.querySelector('#wt-daily').checked,c);
  c.querySelector('#wt-no').onclick=()=>{watchDecline(hit.sig);c.remove()};
  setTimeout(()=>{if(c.isConnected)c.remove()},60000);
}
async function watchMake(hit,words,daily,card){
  const name=watchName(words);
  const btn=card.querySelector('#wt-yes');btn.disabled=true;
  try{
    const d=await saveAutomation(name,watchRoutineSteps(hit.steps));
    if(!d||!d.id)throw new Error('the routine was not saved');
    pinRoutine(d.id);
    if(daily){
      const r=await apiJSON('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({prompt:`Run my desktop routine "${name}" with run_automation.`,schedule_type:'daily',at_time:'09:00'})});
      if(r&&r.ok===false)throw new Error(r.message||'the schedule was not saved');
      toast('It plays every day at 9:00 on this desktop. Change it in Missions → Schedule.',{kind:'ok'});
    }
    watchDecline(hit.sig);            // made: never offered again
    card.remove();
  }catch(e){btn.disabled=false;toast('Could not make it: '+e.message,{kind:'err'})}
}
function watchName(words){
  let s=words.join(' → ');
  if(s.length>60)s=words[0]+' → … → '+words[words.length-1];
  return s.slice(0,80);
}
