/* ================= gallery — everything the agent made or was handed =================
   Note the `var`, not `let`: the bundle is one concatenated script and anything
   earlier in filename order that calls into this file would hit the temporal dead
   zone. Function declarations hoist across the whole bundle; module state does not. */
var galKind='';
var galQ='';
var galSel=null;
var galCap=null;

async function renderGallery(body,w){
  const qs=new URLSearchParams();
  if(galKind)qs.set('kind',galKind);
  if(galQ)qs.set('q',galQ);
  if(typeof activeSpace==='function'&&activeSpace())qs.set('space',activeSpace());
  const d=await fetch('/api/assets?'+qs).then(r=>r.json()).catch(()=>({assets:[]}));
  galCap=d.capability||{};
  const items=d.assets||[];
  const KINDS=['','image','video','audio','doc'];
  const LABEL={'':'All','image':'Images','video':'Video','audio':'Audio','doc':'Docs'};
  const pb=panelShell(body,{
    title:'Gallery',
    sub:items.length?`${items.length} item${items.length===1?'':'s'}`:'',
    search:{id:'gal-q',placeholder:'Search title, prompt or source…'},
    actions:`<span class="seg" id="gal-kinds">${KINDS.map(k=>
        `<button class="${k===galKind?'on':''}" onclick="galSetKind('${k}')">${LABEL[k]}</button>`).join('')}</span>
      <button class="pghost" onclick="galPick()">Upload</button>`,
  });
  const q=$('#gal-q');
  if(q){q.value=galQ;q.oninput=galSearch}
  pb.innerHTML=(items.length?`<div class="galgrid">${items.map(galTile).join('')}</div>`
      :emptyBox('Nothing here yet',
        'Images, video and audio land here when the agent generates them, when a connected MCP server returns them, or when you upload a file.',
        '','gallery','Generate an image of something and put it in my gallery.'))
    +galCapNote()
    +(galSel?galDetail(items.find(a=>a.id===galSel)):'');
  // a poll, not a bare setInterval: it stops when the window is minimised, on
  // another desktop, or covered
  if(w)winTick(w,()=>refreshApp('gallery'),8000,{key:'gallery',now:false});
}

function galTile(a){
  const badge=a.kind==='video'?'▶':a.kind==='audio'?'♪':a.kind==='doc'?'▤':'';
  // no thumbnail is a real answer, not a broken tile: images fall back to the
  // original scaled by CSS, everything else to its kind mark
  const art=a.thumb_url
    ? `<img loading="lazy" src="${a.thumb_url}" alt="">`
    : (a.kind==='image'?`<img loading="lazy" src="${a.url}" alt="">`
       :`<span class="galmark">${badge||'●'}</span>`);
  const meta=[a.duration?galDur(a.duration):'',a.width?a.width+'×'+a.height:'',
              Math.round((a.bytes||0)/1024)+' KB'].filter(Boolean).join(' · ');
  return `<button class="galtile ${galSel===a.id?'on':''}" onclick="galOpen('${a.id}')" title="${esc(a.title||'')}">
    <span class="galart">${art}${badge?`<span class="galbadge">${badge}</span>`:''}</span>
    <span class="galcap"><span class="galname">${esc(a.title||a.kind)}</span><span class="galmeta">${esc(meta)}</span></span>
  </button>`;
}

function galDur(s){s=Math.round(s);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')}

function galCapNote(){
  if(!galCap||galCap.ffmpeg)return '';
  // an honest sentence naming the component that would fix it — never a dead control
  return `<div class="galnote"><b>Previews and measurements are limited.</b> ${esc(galCap.why||'')}
    ${galCap.component?`<button class="pghost" style="margin-left:8px" onclick="openApp('syssettings')">Install ${esc(galCap.component)}${galCap.licence?' ('+esc(galCap.licence)+')':''}</button>`:''}
    <div class="mut" style="margin-top:4px">Media a service generated still arrives, is kept, and plays.</div></div>`;
}

function galDetail(a){
  if(!a)return '';
  const player=a.kind==='video'?`<video class="galplayer" src="${a.url}" controls preload="metadata"></video>`
    :a.kind==='audio'?`<audio class="galplayer" src="${a.url}" controls preload="metadata"></audio>`
    :a.kind==='image'?`<img class="galplayer" src="${a.url}" alt="">`
    :`<div class="mut" style="padding:18px">No inline preview for ${esc(a.mime||a.kind)}.</div>`;
  const row=(k,v)=>v?`<div class="galrow"><span>${k}</span><span>${esc(String(v))}</span></div>`:'';
  const when=a.created_at?new Date(a.created_at*1000).toLocaleString():'';
  return `<div class="galdetail">
    ${player}
    <div class="galinfo">
      <div class="ptitle" style="margin:0 0 6px">${esc(a.title||a.kind)}</div>
      ${row('Kind',a.kind+(a.mime?' · '+a.mime:''))}
      ${row('Size',Math.round((a.bytes||0)/1024)+' KB')}
      ${row('Dimensions',a.width?a.width+'×'+a.height:'')}
      ${row('Duration',a.duration?galDur(a.duration):'')}
      ${row('Made by',a.source)}
      ${row('From prompt',a.prompt)}
      ${row('When',when)}
      <div class="row" style="margin-top:10px">
        <button class="endbtn" onclick="window.open('${a.url}','_blank')">Open</button>
        <a class="endbtn" href="${a.url}" download style="text-decoration:none;text-align:center">Download</a>
        <button class="endbtn" onclick="galDelete('${a.id}')">Delete</button>
      </div>
    </div></div>`;
}

function galSetKind(k){galKind=k;galSel=null;refreshApp('gallery')}
function galOpen(id){galSel=(galSel===id?null:id);refreshApp('gallery')}
var _galT=null;
function galSearch(e){clearTimeout(_galT);const v=e.target.value;_galT=setTimeout(()=>{galQ=v;refreshApp('gallery')},220)}
async function galDelete(id){
  if(!await osConfirm('Delete this asset?','Its file is removed from disk too.',
                      {confirmText:'Delete',danger:true}))return;
  await fetch('/api/assets/'+id,{method:'DELETE'});
  galSel=null;toast('deleted');refreshApp('gallery');
}

/* Upload: a raw-body PUT, not multipart. A 200 MB video should never be
   base64-inflated into a JSON body, and multipart would mean a new dependency. */
function galPick(){
  const inp=document.createElement('input');
  inp.type='file';inp.multiple=true;
  inp.onchange=async()=>{
    for(const f of inp.files){
      try{
        const sp=(typeof activeSpace==='function'&&activeSpace())?activeSpace():'';
        const r=await fetch('/api/assets/raw?name='+encodeURIComponent(f.name),{
          method:'PUT',
          headers:Object.assign({'Content-Type':f.type||'application/octet-stream'},
                                sp?{'X-AgentOS-Space':sp}:{}),
          body:f});
        if(!r.ok){const e=await r.json().catch(()=>({}));toast(e.error||('upload failed: '+f.name))}
      }catch(err){toast('upload failed: '+f.name)}
    }
    refreshApp('gallery');
  };
  inp.click();
}
