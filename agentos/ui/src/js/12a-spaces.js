/* ================= spaces & timeline =================
   A space is a thing the user is working on. Everything it groups — conversations,
   memory, facts, assets, runs — is visible from inside it ALONGSIDE what is true
   everywhere; never instead of it. That is why the global scope is labelled
   "Everywhere" rather than "None": it is a real scope, not a missing value.

   `var`, not `let` — see the note at the top of 25a-gallery.js. */
var SPACES={list:[],active:{},loaded:false};
var tlKind='';
var tlSince=168;

function activeSpace(){return (SPACES.active||{}).gui||''}
function spaceById(id){return (SPACES.list||[]).find(s=>s.id===id)||null}
function spaceName(id){const s=spaceById(id);return s?s.name:'Everywhere'}

async function loadSpaces(force){
  if(SPACES.loaded&&!force)return SPACES;
  try{
    const d=await fetch('/api/spaces').then(r=>r.json());
    SPACES.list=d.spaces||[];SPACES.active=d.active||{};SPACES.loaded=true;
  }catch(e){}
  return SPACES;
}

/* ---- the menu-bar chip ---------------------------------------------------
   In SUI the menu bar is a layer-shell exclusive zone whose height the page
   MEASURES and reports to the host (00-sui.js). The chip is an inline element
   inside the existing band for exactly that reason: it must not change the
   band's height, and nothing here may hardcode one. */
function spaceChipHTML(){
  const id=activeSpace(),s=spaceById(id);
  const dot=s&&s.colour?`<span class="spdot" style="background:${esc(s.colour)}"></span>`:'';
  return `<button class="spchip" onclick="spaceMenu(event)" title="Which project you are working in. Memory and facts you save belong to it; what is true everywhere stays shared.">
    ${dot}${esc(s?((s.icon?s.icon+' ':'')+s.name):'Everywhere')}</button>`;
}

async function paintSpaceChip(){
  const el=$('#mbspace');
  if(!el)return;
  await loadSpaces();
  // Only worth a chip once there is a choice to make — until the user has a
  // space, "Everywhere" is the only scope and the control would be decoration.
  el.innerHTML=(SPACES.list||[]).length?spaceChipHTML():'';
}

async function spaceMenu(ev){
  ev.stopPropagation();
  await loadSpaces(true);
  const cur=activeSpace();
  const tick=id=>(id===cur?'● ':'   ');
  const items=[{label:tick('')+'Everywhere',fn:()=>switchSpace('')}]
    .concat(SPACES.list.map(s=>({
      label:tick(s.id)+esc((s.icon?s.icon+' ':'')+s.name),
      fn:()=>switchSpace(s.id)})))
    .concat([null,
      {label:'New space…',fn:newSpace},
      {label:'Manage spaces',fn:()=>openApp('spaces')},
      {label:'Timeline',fn:()=>openApp('timeline')}]);
  showCtxItems(ev,items);
}

async function switchSpace(id){
  const r=await fetch('/api/spaces/activate',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({space_id:id,surface:'gui'})});
  if(!r.ok){toast('could not switch space');return}
  const d=await r.json();
  SPACES.active=Object.assign({},SPACES.active,{gui:id});
  toast(id?('working in '+d.name):'working everywhere');
  // everything that reads scoped data redraws; a new chat starts in the new space
  ['memory','profile','kg','gallery','timeline','logs','audit','spaces'].forEach(a=>refreshApp(a));
  paintSpaceChip();
}

async function newSpace(){
  const name=await osPrompt('Name the space',{placeholder:'e.g. Q3 launch',confirmText:'Create'});
  if(name===null||!name.trim())return;
  const description=await osPrompt('What is this space about?',
    {placeholder:'One line — the memory subsystem reads this to decide what belongs here',
     confirmText:'Create'});
  const r=await fetch('/api/spaces',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name.trim(),description:(description||'').trim()})});
  if(!r.ok){toast('could not create the space');return}
  const d=await r.json();
  await loadSpaces(true);
  await switchSpace(d.id);
  refreshApp('spaces');
}

/* ---- the Spaces app ----------------------------------------------------- */
async function renderSpaces(body){
  await loadSpaces(true);
  const cur=activeSpace();
  const card=s=>`<div class="item">
    <div class="grow"><b>${s.icon?esc(s.icon)+' ':''}${esc(s.name)}</b>
      ${s.id===cur?'<span class="badge" style="margin-left:6px">active</span>':''}
      <div class="sub">${esc(s.description||'no description — the agent uses this to decide what belongs here')}</div></div>
    <button onclick="switchSpace('${s.id}')" ${s.id===cur?'disabled':''}>Work here</button>
    <button title="stop offering this space; nothing is deleted" onclick="spaceDispose('${s.id}','archive')">Archive</button>
    <button title="move everything in it to the shared scope" onclick="spaceDispose('${s.id}','global')">Make shared</button>
    <button title="delete the space and everything scoped to it" onclick="spaceDispose('${s.id}','delete')">✕</button></div>`;
  const pb=panelShell(body,{title:'Spaces',sub:'the things you are working on',
    actions:`<button class="pact" onclick="newSpace()">New space</button>`});
  pb.innerHTML=`
    <div class="item"><div class="grow"><b>Everywhere</b>
      ${cur===''?'<span class="badge" style="margin-left:6px">active</span>':''}
      <div class="sub">Shared context: what is true about you no matter what you are working on. Always visible from inside every space.</div></div>
      <button onclick="switchSpace('')" ${cur===''?'disabled':''}>Work here</button></div>
    ${SPACES.list.map(card).join('')}
    ${SPACES.list.length?'':emptyBox('No spaces yet','Everything is shared. Make a space when a project starts accumulating its own people, decisions and files — its memory then stops competing with the rest.','','spaces','Create a space for the project I am starting and explain what will go in it.')}`;
}

/* Three dispositions, each its own button, each confirmed with what is actually
   in the space. A space must never be removed without saying what happens to
   its contents — silently orphaning a project's memory is unrecoverable. */
async function spaceDispose(id,contents){
  const s=spaceById(id);if(!s)return;
  const st=await fetch('/api/spaces/'+id+'/stats').then(r=>r.json()).catch(()=>({stats:{}}));
  const held=Object.entries(st.stats||{}).filter(([k,v])=>v>0)
    .map(([k,v])=>v+' '+k.replace(/_/g,' ')).join(', ')||'nothing';
  const WORDS={
    archive:['Archive "'+s.name+'"?','It holds '+held+'. Nothing is deleted or moved — the space just stops being offered, and you can bring it back.','Archive',false],
    global:['Move "'+s.name+'" into the shared scope?','Its '+held+' become true everywhere, mixed in with the rest. The space itself is removed. This cannot be undone.','Make shared',false],
    delete:['Delete "'+s.name+'" and everything in it?','This permanently removes '+held+'. This cannot be undone.','Delete everything',true],
  };
  const [title,message,confirmText,danger]=WORDS[contents]||WORDS.archive;
  if(!await osConfirm(title,message,{confirmText,danger}))return;
  const r=await fetch('/api/spaces/'+id+'?contents='+contents,{method:'DELETE'});
  if(!r.ok){toast('could not update the space');return}
  const d=await r.json().catch(()=>({}));
  if(activeSpace()===id&&contents!=='archive')await switchSpace('');
  await loadSpaces(true);
  toast(contents==='archive'?'archived — nothing was deleted'
       :contents==='global'?'moved to the shared scope':'deleted');
  refreshApp('spaces');
}

/* ---- the Timeline app ---------------------------------------------------
   Milestones, not messages. A timeline containing every message IS the message
   list, and there is already one of those. */
async function renderTimeline(body,w){
  const qs=new URLSearchParams();
  if(activeSpace())qs.set('space',activeSpace());
  if(tlKind)qs.set('kind',tlKind);
  if(tlSince)qs.set('since',String(Math.floor(Date.now()/1000-tlSince*3600)));
  const d=await fetch('/api/timeline?'+qs).then(r=>r.json()).catch(()=>({events:[]}));
  const KINDS=['','run','asset','memory','app_version','conversation','task','space'];
  const MARK={run:'▸',asset:'◧',memory:'◈',app_version:'⌾',conversation:'❯',task:'⏱',space:'▣'};
  const RANGE=[[24,'Today'],[168,'Week'],[720,'Month'],[0,'All']];
  const pb=panelShell(body,{
    title:'Timeline',
    sub:activeSpace()?esc(spaceName(activeSpace())):'everywhere',
    actions:`<span class="seg">${RANGE.map(([h,l])=>
        `<button class="${tlSince===h?'on':''}" onclick="tlRange(${h})">${l}</button>`).join('')}</span>
      <select onchange="tlSetKind(this.value)" style="flex:0 0 auto">
        ${KINDS.map(k=>`<option value="${k}" ${k===tlKind?'selected':''}>${k?k.replace(/_/g,' '):'everything'}</option>`).join('')}
      </select>`,
  });
  const ev=d.events||[];
  let day='',out='';
  ev.forEach(e=>{
    const dt=new Date(e.ts*1000),dd=dt.toLocaleDateString();
    if(dd!==day){day=dd;out+=`<div class="ptitle" style="margin-top:12px">${esc(dd)}</div>`}
    out+=`<div class="item"><span class="tlmark">${MARK[e.kind]||'•'}</span>
      <div class="grow">${esc(e.title||e.kind)}
        <div class="sub">${dt.toLocaleTimeString()} · ${esc(e.kind.replace(/_/g,' '))}</div></div></div>`;
  });
  pb.innerHTML=out||emptyBox('Nothing yet in this period',
    'The timeline records milestones — runs that finished, assets produced, memory learned, apps changed — not every message.');
  if(w)winTick(w,()=>refreshApp('timeline'),15000,{key:'timeline',now:false});
}
function tlSetKind(k){tlKind=k;refreshApp('timeline')}
function tlRange(h){tlSince=h;refreshApp('timeline')}
