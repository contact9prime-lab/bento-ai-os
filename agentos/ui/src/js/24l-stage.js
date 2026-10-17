/* ================= the Stage: an answer shown, not only written =================
   agentos/stage.py is the closed set and the record; this file draws it. While the agent
   answers it calls `show_scene`, the server files the scene with the chat and sends a
   `stage` event, and the Stage window plays it: a chart that draws itself, a world map
   that lights its places, numbers that count up, steps that follow each other. Each scene
   is read aloud when voice replies are on. Four rules:

   - Every word is text. Scenes carry other people's words (a page the agent read), so
     labels go in with textContent and SVG text nodes, never markup.
   - A scene opens the Stage only for the chat on THIS screen (Chat's open conversation,
     the Office's, the prompt bar's card), never for a turn somebody started elsewhere,
     and only while "Open by itself" is on (per browser, `stage.auto`).
   - Numbers say where they came from: the source, or "Illustrative, not data", is drawn
     on every scene that carries measurements.
   - The person may give the Stage to an app of their own (`stage.app`): the scene is
     posted into that app's frame as an `appstage` event and the Stage stays closed.

   The map is Natural Earth's 1:110m countries (public domain), fetched the first time a
   map is drawn (/assets/world-110m.json, 107 kB) and never in the bundle. */

var STAGE=window.STAGE||{
  cur:null,           // {cid, answer_to, question}
  scenes:[],          // [{id, seq, scene}]
  at:0,               // the scene on screen
  tab:'now',
  settings:{big:true,app:'',apps:[]},
  world:null, worldP:null,
  playing:false, held:0,     // a person stepping back holds the live scene off for a while
  chips:{},           // cid:answer_to -> chip element in Chat
  lib:null,
};
window.STAGE=STAGE;
var STAGE_PAL=['var(--acc)','#F59E0B','#22D3EE','#F472B6','#34D399','#A78BFA','#F87171','#94A3B8'];

function stageAuto(){try{return localStorage.getItem('stage.auto')!=='0'}catch(e){return true}}
function stageSetAuto(on){try{localStorage.setItem('stage.auto',on?'1':'0')}catch(e){}}

function sEl(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);return e}
var SVGNS='http://www.w3.org/2000/svg';
/* How much a 960x500 drawing is shrunk where it is shown, so its text is drawn that much
   larger: the SVG keeps its shape, so the scale is the tighter of width and height. */
function stageK(svg){
  const b=svg.getBoundingClientRect();
  const s=Math.min((b.width||960)/960,(b.height||500)/500);
  return Math.max(1,Math.min(2.8,1/Math.max(.2,s)));
}
function sSvg(tag,attrs,text){const e=document.createElementNS(SVGNS,tag);
  for(const k in attrs||{})e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=String(text);return e}
function stageReduced(){try{return matchMedia('(prefers-reduced-motion: reduce)').matches}catch(e){return false}}

/* ---------- which screen shows which chat ---------- */
function stageMine(cid){
  if(!cid)return false;
  if(typeof currentConv!=='undefined'&&currentConv===cid&&typeof WM!=='undefined'&&WM.wins.get('chat'))return true;
  if(typeof OFFICE_CHAT!=='undefined'&&OFFICE_CHAT&&OFFICE_CHAT.cid===cid)return true;
  if(typeof OMNI!=='undefined'&&OMNI&&OMNI.cid===cid)return true;
  if(typeof currentConv!=='undefined'&&currentConv===cid)return true;
  return false;
}

/* ---------- the live event ---------- */
function stageEvent(ev){
  const key=ev.conversation_id+':'+(ev.answer_to||'');
  const same=STAGE.cur&&STAGE.cur.cid===ev.conversation_id&&STAGE.cur.answer_to===(ev.answer_to||'');
  if(same){
    if(!STAGE.scenes.some(s=>s.id===ev.id))STAGE.scenes.push({id:ev.id,seq:ev.seq,scene:ev.scene});
    STAGE.scenes.sort((a,b)=>a.seq-b.seq);
  }
  stageChipUpdate(ev.conversation_id,ev.answer_to||'',ev.seq);
  const app=STAGE.settings.app;
  if(app){stageToApp(app,ev);return}
  if(!stageMine(ev.conversation_id)){if(same)stagePaintIfOpen();return}
  if(!same){
    STAGE.cur={cid:ev.conversation_id,answer_to:ev.answer_to||'',question:''};
    STAGE.scenes=[{id:ev.id,seq:ev.seq,scene:ev.scene}];STAGE.at=0;STAGE.tab='now';
    stageQuestion();
  }
  const w=typeof WM!=='undefined'&&WM.wins.get('stage');
  if(!w&&!stageAuto()){return}
  // follow the story as it arrives, unless the person just stepped back to look
  if(Date.now()>STAGE.held)STAGE.at=STAGE.scenes.findIndex(s=>s.id===ev.id);
  if(STAGE.at<0)STAGE.at=STAGE.scenes.length-1;
  if(!w){openApp('stage');}
  else{STAGE.tab='now';stagePaint();}
  if(Date.now()>STAGE.held)stageSay(ev.scene);
}
function stagePaintIfOpen(){const w=typeof WM!=='undefined'&&WM.wins.get('stage');if(w)stagePaint()}
function stageToApp(aid,ev){
  let frames=document.querySelectorAll('iframe[src^="/api/apps/'+aid+'/page"]');
  const post=()=>document.querySelectorAll('iframe[src^="/api/apps/'+aid+'/page"]').forEach(f=>{
    try{f.contentWindow.postMessage({agentos:'stage',scene:ev.scene,seq:ev.seq,story:(ev.conversation_id||'')+':'+(ev.answer_to||'')},'*')}catch(_){}});
  if(!frames.length&&stageMine(ev.conversation_id)&&stageAuto()){
    openApp('ua_'+aid);
    // the frame needs a moment to load its runtime before it can hear anything
    setTimeout(post,1500);return;
  }
  post();
}
async function stageQuestion(){
  const c=STAGE.cur;if(!c||!c.cid)return;
  try{const d=await apiJSON('/api/conversations/'+c.cid);
    const m=(d.messages||[]).find(x=>x.id===c.answer_to);
    if(m&&STAGE.cur===c){c.question=stageStrip(m.content||'');stagePaintIfOpen()}}catch(e){}
}
function stageStrip(t){t=String(t||'').trim();while(t.startsWith('[')){const i=t.indexOf(']');if(i<0)break;t=t.slice(i+1).trim()}return t}

/* ---------- voice: each scene's line, when voice replies are on ---------- */
function stageSay(sc){
  try{if(typeof VOICE==='undefined'||!VOICE.tts||typeof speakAs!=='function')return;
    const line=sc.say||sc.caption||sc.title;if(line)speakAs(typeof agentName==='function'?agentName():'agent',line)}catch(e){}
}

/* ---------- opening a story ---------- */
async function stageOpen(cid,answer_to,at){
  try{const d=await apiJSON('/api/stage/story?conversation='+encodeURIComponent(cid)+'&answer_to='+encodeURIComponent(answer_to||''));
    STAGE.cur={cid,answer_to:answer_to||'',question:''};
    STAGE.scenes=d.scenes||[];STAGE.at=Math.max(0,Math.min(at||0,STAGE.scenes.length-1));
    STAGE.tab='now';STAGE.held=Date.now()+15000;
    stageQuestion();
    const w=WM.wins.get('stage');if(w){focusWin(w);stagePaint()}else openApp('stage');
  }catch(e){toast('could not open that story: '+(e.message||e))}
}

/* ---------- Chat: one chip per answer that has a story ---------- */
function stageChip(cid,answer_to,n){
  const el=sEl('div','handoff stage-chip');
  el.append(sEl('span','ho-what','▶ Shown on the Stage'),sEl('span','ho-note',n+' scene'+(n===1?'':'s')));
  const b=sEl('button','ho-go','Play');b.onclick=()=>stageOpen(cid,answer_to,0);el.append(b);
  el.dataset.key=cid+':'+answer_to;return el;
}
function stageChipUpdate(cid,answer_to,n){
  if(typeof feed==='undefined'||!feed||typeof currentConv==='undefined'||currentConv!==cid)return;
  const key=cid+':'+answer_to;
  let chip=feed.querySelector('.stage-chip[data-key="'+CSS.escape(key)+'"]');
  if(chip){chip.querySelector('.ho-note').textContent=n+' scene'+(n===1?'':'s');return}
  chip=stageChip(cid,answer_to,n);
  if(typeof curBody!=='undefined'&&curBody&&curBody.parentNode)curBody.parentNode.insertBefore(chip,curBody);
  else feed.appendChild(chip);
}
/* A reopened chat: each answer's chip goes after the reply to the message it answers. */
async function stageAttach(cid){
  if(!cid||typeof feed==='undefined'||!feed)return;
  let d;try{d=await apiJSON('/api/stage?conversation='+encodeURIComponent(cid))}catch(e){return}
  if(d.settings)STAGE.settings=d.settings;
  if(currentConv!==cid)return;
  (d.stories||[]).forEach(st=>{
    const key=cid+':'+st.answer_to;
    if(feed.querySelector('.stage-chip[data-key="'+CSS.escape(key)+'"]'))return;
    const u=st.answer_to&&feed.querySelector('.msg.user[data-mid="'+CSS.escape(st.answer_to)+'"]');
    let host=u&&u.nextElementSibling;
    while(host&&!host.classList.contains('assistant')&&!host.classList.contains('user'))host=host.nextElementSibling;
    const chip=stageChip(cid,st.answer_to,st.scenes.length);
    if(host&&host.classList.contains('assistant'))host.appendChild(chip);
    else if(u)u.after(chip);else feed.appendChild(chip);
  });
}

/* ---------- the window ---------- */
async function renderStage(body){
  body.classList.add('stage-body');
  if(!STAGE.lib)stageLoadLib();
  stagePaint(body);
}
async function stageLoadLib(){
  try{const d=await apiJSON('/api/stage/library');STAGE.lib=d;if(d.settings)STAGE.settings=d.settings;
    if(!STAGE.cur&&STAGE.tab==='now'&&(d.stories||[]).length){
      const s=d.stories[0];STAGE.cur={cid:s.conversation_id,answer_to:s.answer_to,question:s.question};
      const x=await apiJSON('/api/stage/story?conversation='+encodeURIComponent(s.conversation_id)+'&answer_to='+encodeURIComponent(s.answer_to));
      STAGE.scenes=x.scenes||[];STAGE.at=0;
    }
    stagePaintIfOpen();
  }catch(e){STAGE.lib={stories:[],boards:[],error:String(e.message||e)};stagePaintIfOpen()}
}
function stageBody(){const w=WM.wins.get('stage');return w&&w.el.querySelector('.wbody')}

function stagePaint(body){
  body=body||stageBody();if(!body)return;
  body.textContent='';
  const top=sEl('div','st-top');
  const seg=sEl('div','seg st-tabs');
  [['now','Now'],['library','Library'],['boards','Boards']].forEach(([id,label])=>{
    const b=sEl('button',STAGE.tab===id?'on':'',label);b.onclick=()=>{STAGE.tab=id;if(id!=='now')stageLoadLib();stagePaint()};seg.append(b)});
  top.append(seg);
  const sw=sEl('label','st-big');const cb=document.createElement('input');cb.type='checkbox';cb.checked=!!STAGE.settings.big;
  cb.onchange=()=>stageSettings({big:cb.checked});
  sw.append(cb,sEl('span','','Answer BIG'));
  sw.title='On: answers with numbers, places or a story are shown here without being asked. Off: only when you ask to see something.';
  top.append(sw);
  body.append(top);
  const main=sEl('div','st-main');body.append(main);
  if(STAGE.tab==='library')stageLibrary(main);
  else if(STAGE.tab==='boards')stageBoards(main);
  else stageNow(main);
}

function stageNow(main){
  if(!STAGE.cur||!STAGE.scenes.length){
    const e=sEl('div','st-empty');
    e.append(sEl('div','st-empty-h','Ask something worth seeing.'),
      sEl('p','mut','"Where are the hottest places on earth?" or "how does low implied volatility affect the market?". The answer is shown here as it is written: maps, charts, numbers and the steps in between.'));
    main.append(e);return;
  }
  const sc=STAGE.scenes[STAGE.at].scene;
  if(STAGE.cur.question)main.append(sEl('div','st-q','» '+STAGE.cur.question));
  const card=sEl('div','st-card k-'+sc.kind);
  card.append(sEl('div','st-title',sc.title||''));
  const art=sEl('div','st-art');card.append(art);
  if(sc.caption)card.append(sEl('div','st-cap',sc.caption));
  if(sc.illustrative)card.append(sEl('div','st-src st-illus','Illustrative, not data'));
  else if(sc.source)card.append(stageSource(sc.source));
  main.append(card);
  try{stageDraw(art,sc)}catch(e){art.append(sEl('p','mut','Could not draw this scene: '+(e.message||e)))}
  // the story's controls
  const nav=sEl('div','st-nav');
  const prev=sEl('button','endbtn','‹');prev.disabled=STAGE.at===0;prev.onclick=()=>stageGo(STAGE.at-1);
  const next=sEl('button','endbtn','›');next.disabled=STAGE.at>=STAGE.scenes.length-1;next.onclick=()=>stageGo(STAGE.at+1);
  const dots=sEl('div','st-dots');
  STAGE.scenes.forEach((s,i)=>{const d=sEl('button',i===STAGE.at?'on':'');d.title=s.scene.title||s.scene.kind;
    d.setAttribute('aria-label','scene '+(i+1));d.onclick=()=>stageGo(i);dots.append(d)});
  const play=sEl('button','endbtn',STAGE.playing?'❚❚':'▶');play.title='Play the story';play.onclick=stagePlay;
  const keep=sEl('button','endbtn st-keep','★ Keep');keep.title='Keep this story as a board, and refresh it if you like';
  keep.onclick=()=>stageKeepMenu(keep);
  const chat=sEl('button','endbtn','Open the chat');chat.onclick=()=>{if(typeof openConv==='function'){openApp('chat');openConv(STAGE.cur.cid)}};
  nav.append(prev,dots,next,play,keep,chat);
  main.append(nav);
}
function stageSource(src){
  const d=sEl('div','st-src');
  if(/^https?:\/\//i.test(src)){const a=document.createElement('a');a.href=src;a.target='_blank';a.rel='noopener noreferrer';
    let host=src;try{host=new URL(src).host}catch(e){}a.textContent='Source: '+host;d.append(a)}
  else d.textContent='Source: '+src;
  return d;
}
function stageGo(i){if(i<0||i>=STAGE.scenes.length)return;STAGE.at=i;STAGE.held=Date.now()+20000;stagePaint();}
function stagePlay(){
  if(STAGE.playing){STAGE.playing=false;stagePaint();return}
  STAGE.playing=true;STAGE.at=0;STAGE.held=Date.now()+600000;stagePaint();
  const step=()=>{
    if(!STAGE.playing)return;
    const sc=STAGE.scenes[STAGE.at]&&STAGE.scenes[STAGE.at].scene;if(!sc){STAGE.playing=false;stagePaint();return}
    const line=sc.say||sc.caption||sc.title||'';
    const after=()=>setTimeout(()=>{if(!STAGE.playing)return;
      if(STAGE.at>=STAGE.scenes.length-1){STAGE.playing=false;STAGE.held=0;stagePaint();return}
      STAGE.at++;stagePaint();step()},900);
    if(typeof VOICE!=='undefined'&&VOICE.tts&&typeof speakAs==='function'&&line)speakAs(agentName(),line,after);
    else setTimeout(after,Math.max(3500,line.length*55));
  };
  step();
}
function stageKeepMenu(btn){
  const c=STAGE.cur;if(!c)return;
  const box=sEl('div','st-keepbox');
  box.append(sEl('div','st-keep-h','Keep this story'));
  const sel=document.createElement('select');
  [['','As it is'],['hour','Ask again every hour'],['day','Ask again every day'],['week','Ask again every week']]
    .forEach(([v,l])=>{const o=document.createElement('option');o.value=v;o.textContent=l;sel.append(o)});
  sel.value='day';
  const ok=sEl('button','endbtn pri','Keep');
  ok.onclick=async()=>{
    try{const r=await fetch('/api/stage/boards',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({conversation_id:c.cid,answer_to:c.answer_to,every:sel.value})});
      const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);
      toast('kept: '+d.title+' · '+d.when);box.remove();STAGE.lib=null;
    }catch(e){toast('could not keep it: '+(e.message||e))}};
  const no=sEl('button','endbtn','Cancel');no.onclick=()=>box.remove();
  box.append(sel,sEl('p','mut','A refresh asks the same question again, looks the facts up afresh and shows the new story here.'),ok,no);
  btn.closest('.st-main').append(box);
}
async function stageSettings(patch){
  try{const r=await fetch('/api/stage/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
    const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);STAGE.settings=d;
    toast(patch.big!==undefined?('Answer BIG is '+(d.big?'on':'off')):('scenes are shown in '+(d.app?d.app_name:'the Stage')));
    stagePaintIfOpen();if(typeof refreshApp==='function')refreshApp('settings');
  }catch(e){toast('could not save: '+(e.message||e))}
}

/* ---------- the library: every story you were shown ---------- */
function stageLibrary(main){
  const lib=STAGE.lib;
  if(!lib){main.append(sEl('p','mut','Reading…'));return}
  const st=lib.stories||[];
  if(!st.length){main.append(sEl('p','mut st-pad','Nothing yet. Every story an answer shows is kept here, with the chat it came from.'));return}
  const grid=sEl('div','st-grid');
  const KI={chart:'📈',map:'🗺',numbers:'#',timeline:'⟶',steps:'⇢',table:'▦'};
  st.forEach(s=>{
    const c=sEl('button','st-tile');
    c.append(sEl('div','st-tile-k',(s.kinds||[]).map(k=>KI[k]||'·').join(' ')),
      sEl('div','st-tile-q',s.question||s.chat||'(a story)'),
      sEl('div','st-tile-t',(s.titles||[]).slice(0,3).join(' · ')),
      sEl('div','st-tile-m',s.scenes+' scene'+(s.scenes===1?'':'s')+' · '+new Date(s.last_at*1000).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})));
    c.onclick=()=>stageOpen(s.conversation_id,s.answer_to,0);
    grid.append(c)});
  main.append(grid);
}

/* ---------- boards: stories kept, some asking again on their own ---------- */
function stageBoards(main){
  const lib=STAGE.lib;
  if(!lib){main.append(sEl('p','mut','Reading…'));return}
  const bs=lib.boards||[];
  // where scenes are drawn: the Stage, or one of the person's own apps
  const where=sEl('div','st-where');
  where.append(sEl('span','','Show answers in'));
  const sel=document.createElement('select');
  const o0=document.createElement('option');o0.value='';o0.textContent='the Stage';sel.append(o0);
  (STAGE.settings.apps||[]).forEach(a=>{const o=document.createElement('option');o.value=a.id;o.textContent=a.name;sel.append(o)});
  sel.value=STAGE.settings.app||'';sel.onchange=()=>stageSettings({app:sel.value});
  const auto=sEl('label','');const ab=document.createElement('input');ab.type='checkbox';ab.checked=stageAuto();
  ab.onchange=()=>stageSetAuto(ab.checked);auto.append(ab,sEl('span','',' Open by itself on this screen'));
  where.append(sel,auto);
  main.append(where);
  if(STAGE.settings.app)main.append(sEl('p','mut st-pad','Your app receives each scene as an appstage event. App Studio can build one: ask it for "an app that draws my Stage".'));
  if(!bs.length){main.append(sEl('p','mut st-pad','No boards yet. ★ Keep a story on the Now tab to make one; it can ask its question again every hour, day or week.'));return}
  const list=sEl('div','st-boards');
  bs.forEach(b=>{
    const row=sEl('div','st-board');
    const info=sEl('div','st-board-i');
    info.append(sEl('div','st-board-t',b.title),
      sEl('div','mut',b.when+' · '+(b.last_run?'last '+new Date(b.last_run*1000).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'not refreshed yet')
        +(b.last_status&&b.last_status!=='ok'?' · '+b.last_status:'')));
    info.onclick=()=>stageOpen(b.conversation_id,b.answer_to,0);
    const ev=document.createElement('select');
    [['','As it is'],['hour','Every hour'],['day','Every day'],['week','Every week']].forEach(([v,l])=>{const o=document.createElement('option');o.value=v;o.textContent=l;ev.append(o)});
    ev.value=b.every||'';
    ev.onchange=async()=>{try{const r=await fetch('/api/stage/boards',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({conversation_id:b.conversation_id,answer_to:b.answer_to,title:b.title,every:ev.value})});
      const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);toast(d.title+': '+d.when);STAGE.lib=null;stageLoadLib()}catch(e){toast('could not save: '+(e.message||e))}};
    const now=sEl('button','endbtn',b.last_status==='refreshing'?'Refreshing…':'↻ Now');now.disabled=b.last_status==='refreshing'||!b.question;
    now.onclick=async()=>{now.disabled=true;now.textContent='Refreshing…';
      try{const r=await fetch('/api/stage/boards/'+b.id+'/refresh',{method:'POST'});const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);
        toast('asking it again: the new story arrives here')}catch(e){toast('could not refresh: '+(e.message||e));now.disabled=false;now.textContent='↻ Now'}};
    const del=sEl('button','endbtn','Remove');del.onclick=async()=>{
      try{await fetch('/api/stage/boards/'+b.id,{method:'DELETE'});STAGE.lib=null;stageLoadLib()}catch(e){}};
    row.append(info,ev,now,del);list.append(row)});
  main.append(list);
}

/* ================= drawing ================= */
function stageDraw(art,sc){
  ({chart:stageChart,map:stageMap,numbers:stageNumbers,timeline:stageTimeline,steps:stageSteps,table:stageTable}[sc.kind]||(()=>{}))(art,sc);
  if(stageReduced())art.classList.add('still');
}

/* --- numbers that read as numbers --- */
function stageFmt(n,unit){
  if(n==null||!isFinite(n))return '';
  const a=Math.abs(n);
  const s=a>=1e9?(n/1e9).toFixed(1)+'B':a>=1e6?(n/1e6).toFixed(1)+'M':a>=1e4?(n/1e3).toFixed(0)+'k'
    :a>=100?Math.round(n).toLocaleString():a>=1?(+n.toFixed(2)).toString():(+n.toPrecision(2)).toString();
  // a word is a word apart ("8 billion"); a symbol sits on the number ("56.7°C", "12%")
  return s+(unit?(/^[A-Za-z]{2}/.test(unit)?' ':'')+unit:'');
}
function stageTicks(lo,hi,n){
  if(lo===hi){lo-=1;hi+=1}
  const span=hi-lo,raw=span/Math.max(1,n),mag=Math.pow(10,Math.floor(Math.log10(raw)));
  const step=[1,2,2.5,5,10].map(f=>f*mag).find(s=>s>=raw)||raw;
  const t0=Math.floor(lo/step)*step,out=[];
  for(let t=t0;t<=hi+step*0.001;t+=step)out.push(+t.toFixed(10));
  return out;
}
function stageDate(x){
  if(typeof x!=='string')return null;
  const m=x.match(/^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?(?:[T ](\d{1,2}):(\d{2}))?/);
  if(!m||x.length>25)return null;
  return Date.UTC(+m[1],(+m[2]||1)-1,+m[3]||1,+m[4]||0,+m[5]||0);
}

/* --- charts --- */
function stageChart(art,sc){
  const W=960,H=500,R=24;
  const svg=sSvg('svg',{viewBox:`0 0 ${W} ${H}`,class:'st-svg',role:'img','aria-label':sc.title||'chart'});
  art.append(svg);const K=stageK(svg);svg.style.setProperty('--k',K);
  // the margins make room for the text at the size it is drawn
  const T=Math.round(18*K)+8,B=Math.round((sc.x_label?40:22)*K)+14;
  let L=72;
  const series=sc.series||[];
  if(sc.chart_type==='pie'){stagePie(svg,series[0],sc,W,H);return}
  const all=series.flatMap(s=>s.points);
  const xs=all.map(p=>p[0]);
  const isNum=xs.every(x=>typeof x==='number'), dates=!isNum&&xs.every(x=>stageDate(x)!=null);
  const cats=[];if(!isNum&&!dates)xs.forEach(x=>{if(!cats.includes(x))cats.push(x)});
  const xv=x=>isNum?x:dates?stageDate(x):cats.indexOf(x);
  const bar=sc.chart_type==='bar';
  let x0=Math.min(...all.map(p=>xv(p[0]))),x1=Math.max(...all.map(p=>xv(p[0])));
  if(bar||(!isNum&&!dates)){x0-=0.5;x1+=0.5}
  if(x0===x1){x0-=1;x1+=1}
  let ys=all.map(p=>p[1]).concat((sc.marks||[]).filter(m=>m.y!=null).map(m=>m.y));
  let y0=Math.min(...ys),y1=Math.max(...ys);
  if(bar||sc.chart_type==='area')y0=Math.min(0,y0);
  const pad=(y1-y0)*0.08||1;if(!(bar&&y0===0))y0-=pad;y1+=pad;
  const yt=stageTicks(y0,y1,5);y0=Math.min(y0,yt[0]);y1=Math.max(y1,yt[yt.length-1]);
  // a unit that is a word ("million") is said once, by the axis, not on every tick
  const wordUnit=/^[A-Za-z]{2}/.test(sc.unit||''),tu=wordUnit?'':sc.unit,ylab=sc.y_label||(wordUnit?sc.unit:'');
  L=Math.round(Math.max(...yt.map(t=>stageFmt(t,tu).length))*7.4*K+(ylab?24*K:0)+18);
  const fitText=(text,room)=>{const n=Math.floor(room/(7.2*K));return n>=String(text).length?String(text):n>=3?String(text).slice(0,n-1)+'…':''};
  const X=v=>L+(v-x0)/(x1-x0)*(W-L-R),Y=v=>T+(1-(v-y0)/(y1-y0))*(H-T-B);
  const g=sSvg('g',{class:'st-axis'});svg.append(g);
  yt.forEach(t=>{g.append(sSvg('line',{x1:L,x2:W-R,y1:Y(t),y2:Y(t),class:'st-grid'}));
    g.append(sSvg('text',{x:L-10,y:Y(t)+4*K,'text-anchor':'end'},stageFmt(t,tu)))});
  // x labels: at most eight, evenly picked
  let xl=[];
  if(isNum)xl=stageTicks(x0,x1,7).filter(t=>t>=x0&&t<=x1).map(t=>[t,stageFmt(t)]);
  else if(dates){const pts=[...new Set(xs)];const k=Math.ceil(pts.length/8);xl=pts.filter((_,i)=>i%k===0).map(x=>[stageDate(x),x])}
  else{const k=Math.ceil(cats.length/10);xl=cats.map((c,i)=>[i,c]).filter((_,i)=>i%k===0)}
  // each name gets its slot and is cut to it, so neighbours never run into each other
  const room=xl.length>1?Math.abs(X(xl[1][0])-X(xl[0][0]))-6:W-L-R;
  xl.forEach(([v,label])=>{const t=fitText(label,room);if(t)g.append(sSvg('text',{x:X(v),y:H-B+18*K,'text-anchor':'middle'},t))});
  if(sc.x_label)g.append(sSvg('text',{x:(L+W-R)/2,y:H-6*K,'text-anchor':'middle',class:'st-axlabel'},sc.x_label));
  if(ylab)g.append(sSvg('text',{x:14*K,y:(T+H-B)/2,'text-anchor':'middle',class:'st-axlabel',transform:`rotate(-90 ${14*K} ${(T+H-B)/2})`},ylab));
  // marks: the lines the answer is about ("low IV under 12")
  (sc.marks||[]).forEach(m=>{
    if(m.y!=null){svg.append(sSvg('line',{x1:L,x2:W-R,y1:Y(m.y),y2:Y(m.y),class:'st-mark'}));
      svg.append(sSvg('text',{x:W-R-6,y:Y(m.y)-6,'text-anchor':'end',class:'st-marktext'},m.text||stageFmt(m.y,sc.unit)))}
    else if(m.x!=null){const v=xv(m.x);if(v==null||v<0&&!isNum)return;
      svg.append(sSvg('line',{x1:X(v),x2:X(v),y1:T,y2:H-B,class:'st-mark'}));
      svg.append(sSvg('text',{x:X(v)+6,y:T+14,class:'st-marktext'},m.text||''))}
  });
  const n=series.length;
  series.forEach((s,si)=>{
    const col=STAGE_PAL[si%STAGE_PAL.length];
    const pts=s.points.map(p=>[xv(p[0]),p[1]]).sort((a,b)=>a[0]-b[0]);
    if(bar){
      const slot=(W-L-R)/((x1-x0)||1),bw=Math.max(2,slot*0.7/n);
      pts.forEach((p,i)=>{const x=X(p[0])-slot*0.35+si*bw,y=Y(Math.max(0,p[1])),h=Math.abs(Y(p[1])-Y(0));
        const r=sSvg('rect',{x,y,width:bw-2,height:Math.max(1,h),fill:col,class:'st-bar',style:`animation-delay:${i*40}ms`});
        r.append(sSvg('title',{},`${s.name?s.name+': ':''}${stageFmt(p[1],sc.unit)}`));svg.append(r);
        // the value over its bar only when it fits the bar's slot
        const vt=stageFmt(p[1],tu);
        if(vt.length*7.2*K<=slot*0.95/n)svg.append(sSvg('text',{x:x+(bw-2)/2,y:y-6*K,'text-anchor':'middle',class:'st-val'},vt))});
      return;
    }
    if(sc.chart_type==='scatter'){
      pts.forEach((p,i)=>svg.append(sSvg('circle',{cx:X(p[0]),cy:Y(p[1]),r:5,fill:col,class:'st-dot',style:`animation-delay:${Math.min(i,60)*15}ms`})));return}
    const d=pts.map((p,i)=>(i?'L':'M')+X(p[0]).toFixed(1)+' '+Y(p[1]).toFixed(1)).join('');
    if(sc.chart_type==='area'){
      const a=d+`L${X(pts[pts.length-1][0]).toFixed(1)} ${Y(Math.max(y0,0))}L${X(pts[0][0]).toFixed(1)} ${Y(Math.max(y0,0))}Z`;
      svg.append(sSvg('path',{d:a,fill:col,class:'st-area'}))}
    svg.append(sSvg('path',{d,stroke:col,class:'st-line',pathLength:1000}));
    const last=pts[pts.length-1];
    svg.append(sSvg('circle',{cx:X(last[0]),cy:Y(last[1]),r:5,fill:col,class:'st-end'}));
    svg.append(sSvg('text',{x:Math.min(X(last[0])+8,W-R-4),y:Y(last[1])-8,'text-anchor':X(last[0])>W-140?'end':'start',class:'st-val'},stageFmt(last[1],sc.unit)));
  });
  if(n>1||series[0]&&series[0].name){
    const lg=sEl('div','st-legend');
    series.forEach((s,si)=>{const it=sEl('span','');const sw=sEl('i','');sw.style.background=STAGE_PAL[si%STAGE_PAL.length];it.append(sw,document.createTextNode(s.name||('series '+(si+1))));lg.append(it)});
    art.append(lg);
  }
}
function stagePie(svg,s,sc,W,H){
  const pts=(s&&s.points)||[];const tot=pts.reduce((a,p)=>a+p[1],0)||1;
  const cx=W/2-120,cy=H/2,r=190,ri=110;let a0=-Math.PI/2;
  pts.forEach((p,i)=>{
    const a1=a0+p[1]/tot*Math.PI*2,large=a1-a0>Math.PI?1:0,col=STAGE_PAL[i%STAGE_PAL.length];
    const pt=(a,rr)=>[cx+Math.cos(a)*rr,cy+Math.sin(a)*rr];
    const [ax,ay]=pt(a0,r),[bx,by]=pt(a1,r),[cx2,cy2]=pt(a1,ri),[dx,dy]=pt(a0,ri);
    const path=sSvg('path',{d:`M${ax} ${ay}A${r} ${r} 0 ${large} 1 ${bx} ${by}L${cx2} ${cy2}A${ri} ${ri} 0 ${large} 0 ${dx} ${dy}Z`,fill:col,class:'st-slice',style:`animation-delay:${i*90}ms`});
    path.append(sSvg('title',{},`${p[0]}: ${stageFmt(p[1],sc.unit)}`));svg.append(path);
    const ly=60+i*38;svg.append(sSvg('rect',{x:W/2+130,y:ly-14,width:18,height:18,rx:4,fill:col}));
    svg.append(sSvg('text',{x:W/2+158,y:ly,class:'st-pie-l'},`${String(p[0]).slice(0,26)}  ${stageFmt(p[1],sc.unit)} · ${Math.round(p[1]/tot*100)}%`));
    a0=a1;
  });
}

/* --- the map --- */
/* The map's lookup by every name a country goes by, built once. The Telegram report
   (stage.report_html) calls it on the copy it carries inline. */
function stageWorldIndex(d){
  const idx={};
  const al={usa:'USA',us:'USA',america:'USA','united states':'USA',uk:'GBR',britain:'GBR','great britain':'GBR',england:'GBR',
    russia:'RUS','south korea':'KOR',korea:'KOR','north korea':'PRK',uae:'ARE',iran:'IRN',syria:'SYR',vietnam:'VNM',
    laos:'LAO',bolivia:'BOL',venezuela:'VEN',tanzania:'TZA',congo:'COG',drc:'COD','dr congo':'COD','czech republic':'CZE',
    'ivory coast':'CIV',burma:'MMR',taiwan:'TWN',palestine:'PSE',holland:'NLD'};
  d.countries.forEach(c=>{[c.n,...(c.alt||[]),c.a3,c.a2].filter(Boolean).forEach(k=>idx[String(k).toLowerCase()]=c)});
  Object.entries(al).forEach(([k,a3])=>{const c=d.countries.find(x=>x.a3===a3);if(c&&!idx[k])idx[k]=c});
  d.idx=idx;STAGE.world=d;return d;
}
async function stageWorld(){
  if(STAGE.world)return STAGE.world;
  if(!STAGE.worldP)STAGE.worldP=fetch('/assets/world-110m.json').then(r=>{if(!r.ok)throw new Error('the world map did not load ('+r.status+')');return r.json()})
    .then(d=>stageWorldIndex(d));
  return STAGE.worldP;
}
var STAGE_VIEW={world:[-180,-58,180,84],africa:[-20,-36,53,38],asia:[25,-12,150,60],europe:[-25,34,45,72],
  'north america':[-170,7,-50,75],'south america':[-85,-57,-32,14],oceania:[110,-50,180,5],'middle east':[25,10,65,42],india:[66,5,98,37]};
async function stageMap(art,sc){
  const W=960,H=500;
  const svg=sSvg('svg',{viewBox:`0 0 ${W} ${H}`,class:'st-svg st-mapsvg',role:'img','aria-label':sc.title||'map'});
  art.append(svg);const K=stageK(svg);svg.style.setProperty('--k',K);
  let world;
  try{world=await stageWorld()}catch(e){art.textContent='';art.append(sEl('p','mut',String(e.message||e)));return}
  // the box: the view named, else the places and countries shown, padded, else the world
  let box=STAGE_VIEW[sc.view]||null;
  const hits=(sc.regions||[]).map(r=>({r,c:world.idx[String(r.country).toLowerCase()]}));
  if(!box){
    const lons=[],lats=[];
    (sc.points||[]).forEach(p=>{lons.push(p.lon);lats.push(p.lat)});
    hits.forEach(h=>{if(h.c)h.c.r.forEach(ring=>{for(let i=0;i<ring.length;i+=2){lons.push(ring[i]/10);lats.push(ring[i+1]/10)}})});
    if(lons.length){
      let a=Math.min(...lons),b=Math.max(...lons),c=Math.min(...lats),d=Math.max(...lats);
      const pw=Math.max(12,(b-a)*0.15),ph=Math.max(8,(d-c)*0.15);
      box=[Math.max(-180,a-pw),Math.max(-60,c-ph),Math.min(180,b+pw),Math.min(85,d+ph)];
      if(box[2]-box[0]>230)box=STAGE_VIEW.world;
    }else box=STAGE_VIEW.world;
  }
  // keep the shape: widen the shorter side to the frame's aspect
  let [lo0,la0,lo1,la1]=box;const aspect=W/H;
  const midLat=(la0+la1)/2,kx=Math.cos(midLat*Math.PI/180)||1;
  let bw=(lo1-lo0)*kx,bh=la1-la0;
  if(bw/bh>aspect){const nh=bw/aspect;la0=midLat-nh/2;la1=midLat+nh/2}
  else{const nw=bh*aspect/kx,mid=(lo0+lo1)/2;lo0=mid-nw/2;lo1=mid+nw/2}
  const X=lon=>(lon-lo0)/(lo1-lo0)*W,Y=lat=>(la1-lat)/(la1-la0)*H;
  svg.append(sSvg('rect',{x:0,y:0,width:W,height:H,class:'st-sea'}));
  // shaded countries by value
  const vals=hits.map(h=>h.r.value).filter(v=>v!=null);
  const vmin=Math.min(...vals),vmax=Math.max(...vals);
  const shade=new Map();hits.forEach(h=>{if(h.c)shade.set(h.c.a3,h.r)});
  const land=sSvg('g',{class:'st-land'});svg.append(land);
  world.countries.forEach(c=>{
    const d=c.r.map(ring=>{let s='';for(let i=0;i<ring.length;i+=2)s+=(i?'L':'M')+X(ring[i]/10).toFixed(1)+' '+Y(ring[i+1]/10).toFixed(1);return s+'Z'}).join('');
    const p=sSvg('path',{d,class:'st-country'});
    const r=shade.get(c.a3);
    if(r){p.classList.add('on');
      const t=vals.length>1&&r.value!=null?(r.value-vmin)/((vmax-vmin)||1):1;
      p.style.setProperty('--t',(0.35+0.65*t).toFixed(2));
      p.append(sSvg('title',{},c.n+(r.value!=null?': '+stageFmt(r.value,sc.unit):'')+(r.label?' · '+r.label:'')))}
    else p.append(sSvg('title',{},c.n));
    land.append(p)});
  const missing=hits.filter(h=>!h.c).map(h=>h.r.country);
  // places: sized by value, labelled where the label fits
  const pts=(sc.points||[]).slice();
  const pv=pts.map(p=>p.value).filter(v=>v!=null),pmin=Math.min(...pv),pmax=Math.max(...pv);
  const taken=[];
  // every pin's dot is kept clear of labels, so a label never hides a place
  pts.forEach(p=>{const x=X(p.lon),y=Y(p.lat);taken.push([x-9,y-9,x+9,y+9])});
  const order=pts.map((p,i)=>[p,i]).sort((a,b)=>(b[0].value||0)-(a[0].value||0));
  const fits=(lx,ly,lw,th)=>lx>=2&&lx+lw<=W-2&&ly>=2&&ly+th<=H-2
    &&!taken.some(b=>lx<b[2]&&lx+lw>b[0]&&ly<b[3]&&ly+th>b[1]);
  order.forEach(([p],rank)=>{
    const x=X(p.lon),y=Y(p.lat);if(x<-10||x>W+10||y<-10||y>H+10)return;
    const t=p.value!=null&&pv.length>1?(p.value-pmin)/((pmax-pmin)||1):0.5;
    const r=6+t*10,delay=Math.min(rank,30)*120;
    const g=sSvg('g',{class:'st-pin',style:`animation-delay:${delay}ms`});
    g.append(sSvg('circle',{cx:x,cy:y,r:r*1.9,class:'st-pulse'}),sSvg('circle',{cx:x,cy:y,r,class:'st-pt'}));
    g.append(sSvg('title',{},(p.label||'')+(p.value!=null?': '+stageFmt(p.value,sc.unit):'')+(p.note?' · '+p.note:'')));
    svg.append(g);
    // the full name, then its first part ("Furnace Creek"), placed where it touches no
    // other label: right, left, above, below. A place with no room keeps its dot and title.
    const val=p.value!=null?' '+stageFmt(p.value,sc.unit):'';
    const names=[(p.label||'')+val];
    const short=String(p.label||'').split(',')[0].trim();
    if(short&&short!==p.label)names.push(short+val);
    const th=20*K;
    for(const label of names){
      if(!label.trim())continue;
      const tx=sSvg('text',{x:0,y:0,class:'st-tagtext',style:`animation-delay:${delay+200}ms`},label);
      svg.append(tx);
      let lw=label.length*7.4*K+10*K;try{const bb=tx.getBBox();if(bb.width)lw=bb.width+12*K}catch(e){}
      const cx=Math.max(2,Math.min(W-lw-2,x-lw/2));   // above and below slide to stay in the frame
      const spot=[[x+r+6,y-th/2],[x-r-6-lw,y-th/2],[cx,y-r-th-6],[cx,y+r+6]].find(([lx,ly])=>fits(lx,ly,lw,th));
      if(!spot){tx.remove();continue}
      const [lx,ly]=spot;taken.push([lx,ly,lx+lw,ly+th]);
      tx.setAttribute('x',lx+6*K);tx.setAttribute('y',ly+th*0.7);
      svg.insertBefore(sSvg('rect',{x:lx,y:ly,width:lw,height:th,rx:6*K,class:'st-tag',style:`animation-delay:${delay+200}ms`}),tx);
      break;
    }
  });
  if(missing.length)art.append(sEl('p','mut st-note','Not on this map: '+missing.join(', ')));
  if(vals.length>1){const lg=sEl('div','st-scale');lg.append(sEl('span','',stageFmt(vmin,sc.unit)),sEl('i',''),sEl('span','',stageFmt(vmax,sc.unit)));art.append(lg)}
}

/* --- numbers, timeline, steps, table --- */
function stageNumbers(art,sc){
  const g=sEl('div','st-nums');
  sc.items.forEach((it,i)=>{
    const c=sEl('div','st-num');c.style.animationDelay=(i*120)+'ms';
    const v=sEl('div','st-num-v');c.append(v);
    const unit=it.unit||'';
    const m=String(it.value).match(/^(-?[\d,]*\.?\d+)(.*)$/);
    if(m&&!stageReduced()){
      const target=parseFloat(m[1].replace(/,/g,'')),rest=m[2],dec=(m[1].split('.')[1]||'').length,t0=performance.now()+i*120;
      const tick=now=>{const k=Math.min(1,Math.max(0,(now-t0)/900)),e=1-Math.pow(1-k,3);
        v.textContent=(target*e).toLocaleString(undefined,{minimumFractionDigits:dec,maximumFractionDigits:dec})+rest+unit;
        if(k<1&&v.isConnected)requestAnimationFrame(tick)};
      requestAnimationFrame(tick);
    }else v.textContent=it.value+unit;
    c.append(sEl('div','st-num-l',it.label));
    if(it.delta){const d=sEl('div','st-num-d',it.delta);if(/^[-−▼↓]/.test(it.delta))d.classList.add('down');c.append(d)}
    if(it.note)c.append(sEl('div','st-num-n',it.note));
    g.append(c)});
  art.append(g);
}
function stageTimeline(art,sc){
  const t=sEl('div','st-tl'+(sc.events.length>7?' tall':''));
  sc.events.forEach((e,i)=>{const r=sEl('div','st-tl-e');r.style.animationDelay=(i*140)+'ms';
    r.append(sEl('div','st-tl-w',e.when),sEl('div','st-tl-dot'),sEl('div','st-tl-l',e.label));
    if(e.note)r.append(sEl('div','st-tl-n',e.note));t.append(r)});
  art.append(t);
}
function stageSteps(art,sc){
  const s=sEl('div','st-steps'+(sc.items.length>4?' tall':''));
  sc.items.forEach((it,i)=>{
    if(i){const a=sEl('div','st-arrow','→');a.style.animationDelay=(i*260-130)+'ms';s.append(a)}
    const c=sEl('div','st-step');c.style.animationDelay=(i*260)+'ms';
    c.append(sEl('div','st-step-n',String(i+1)),sEl('div','st-step-t',it.title));
    if(it.text)c.append(sEl('div','st-step-x',it.text));s.append(c)});
  art.append(s);
}
function stageTable(art,sc){
  const wrap=sEl('div','st-tablewrap'),tb=document.createElement('table');tb.className='st-table';
  const hr=document.createElement('tr');sc.columns.forEach(c=>hr.append(sEl('th','',c)));
  const th=document.createElement('thead');th.append(hr);tb.append(th);
  const body=document.createElement('tbody');
  sc.rows.forEach((r,i)=>{const tr=document.createElement('tr');tr.style.animationDelay=Math.min(i,20)*40+'ms';
    sc.columns.forEach((_,j)=>{const td=sEl('td','',r[j]==null?'':r[j]);if(/^[-+]?[\d,.]+%?$/.test(String(r[j]||'')))td.className='n';tr.append(td)});body.append(tr)});
  tb.append(body);wrap.append(tb);art.append(wrap);
}
