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
  if(STAGE.awaiting&&STAGE.awaiting.cid===cid)return true;     // a Go deeper from the Stage itself
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
    const was=STAGE.awaiting&&STAGE.awaiting.cid===ev.conversation_id&&STAGE.cur?{answer_to:STAGE.cur.answer_to,seq:(STAGE.scenes[STAGE.at]||{}).seq||1}:null;
    STAGE.awaiting=null;
    STAGE.cur={cid:ev.conversation_id,answer_to:ev.answer_to||'',question:'',parent:was,deeper:{},versions:[]};
    stageVersions(STAGE.cur);
    STAGE.scenes=[{id:ev.id,seq:ev.seq,scene:ev.scene}];STAGE.at=0;STAGE.tab='now';STAGE.held=0;
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
function stageStrip(t){t=String(t||'').trim();while(t.startsWith('[')){const i=t.indexOf(']');if(i<0)break;t=t.slice(i+1).trim()}
  // a Go deeper question reads as what it went deeper on, not the whole instruction
  const m=t.match(/^Go deeper on "([^"]+)"/);return m?'Deeper: '+m[1]:t}

/* ---------- voice: each scene's line, when voice replies are on ---------- */
function stageSay(sc){
  try{if(typeof VOICE==='undefined'||!VOICE.tts||typeof speakAs!=='function')return;
    const line=sc.say||sc.caption||sc.title;if(line)speakAs(typeof agentName==='function'?agentName():'agent',line)}catch(e){}
}

/* ---------- opening a story ---------- */
async function stageOpen(cid,answer_to,at){
  try{await stageFetch(cid,answer_to,at);
    STAGE.tab='now';STAGE.held=Date.now()+15000;
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

/* ---------- the window: a theater ---------- */
/* The Now tab is a dark, full-bleed room the story plays in: a moving field of light
   behind each scene (its hue from the kind of scene), one progress segment per scene,
   a big title, the drawing, and the narrator's line arriving word by word, like a
   subtitle. "Go deeper" on any scene asks for its own story, which plays here next and
   keeps a way back. Asked for as "the look and feel is really horrible, it needs a very
   good immersive experience", with background sound, pictures and videos. */
var STAGE_KIND={chart:'Chart',map:'Map',numbers:'Key numbers',timeline:'Timeline',steps:'How it works',
  table:'Table',image:'Picture',video:'Video',film:'Film'};
var STAGE_HUE={chart:255,map:200,numbers:280,timeline:170,steps:320,table:225,image:30,video:350,film:265};
async function renderStage(body,w){
  body.classList.add('stage-body');
  if(w&&w.app&&!w.app.onClose)w.app.onClose=()=>{stageMusic(false,true);STAGE.playing=false};
  if(!STAGE.lib)stageLoadLib();
  stagePaint(body);
}
async function stageLoadLib(){
  try{const d=await apiJSON('/api/stage/library');STAGE.lib=d;if(d.settings)STAGE.settings=d.settings;
    if(!STAGE.cur&&STAGE.tab==='now'&&(d.stories||[]).length){
      const s=d.stories[0];await stageFetch(s.conversation_id,s.answer_to,0);
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
  const mu=sEl('button','st-icon'+(stageMusicOn()?' on':''),stageMusicOn()?'♪ On':'♪ Off');
  mu.title='Background music, made on this screen. Tap to play or pause.';mu.setAttribute('aria-pressed',String(stageMusicOn()));
  mu.onclick=()=>{stageMusic(!stageMusicOn());stagePaint()};
  const fs=sEl('button','st-icon','⛶');fs.title='Full screen';fs.setAttribute('aria-label','Full screen');
  fs.onclick=()=>{const t=body.closest('.win')||body;try{document.fullscreenElement?document.exitFullscreen():t.requestFullscreen()}catch(e){}};
  top.append(mu,fs);
  body.append(top);
  const main=sEl('div','st-main'+(STAGE.tab==='now'?' now':''));body.append(main);
  if(STAGE.tab==='library')stageLibrary(main);
  else if(STAGE.tab==='boards')stageBoards(main);
  else stageNow(main);
}

function stageNow(main){
  const th=sEl('div','stg');main.append(th);
  const bg=sEl('div','stg-bg');th.append(bg);
  if(!STAGE.cur||!STAGE.scenes.length){
    const e=sEl('div','stg-empty');
    e.append(sEl('div','stg-empty-h','Ask something worth seeing.'),
      sEl('p','','"Where are the hottest places on earth?", "how does El Niño work?" or "teach me to make a sourdough starter". The answer plays here as it is written: maps, charts, pictures, videos and the steps in between.'));
    th.append(e);if(STAGE.awaiting)th.append(stageWaiting());return;
  }
  const n=STAGE.scenes.length,cur=STAGE.scenes[STAGE.at],sc=cur.scene;
  th.style.setProperty('--hue',STAGE_HUE[sc.kind]||250);
  // one segment per scene, the current one filling while the story plays
  const prog=sEl('div','stg-prog');
  STAGE.scenes.forEach((s,i)=>{const b=sEl('button',i<STAGE.at?'done':i===STAGE.at?'on'+(STAGE.playing?' run':''):'');
    b.title=(i+1)+'. '+(s.scene.title||STAGE_KIND[s.scene.kind]);b.setAttribute('aria-label','scene '+(i+1));
    b.onclick=()=>stageGo(i);prog.append(b)});
  th.append(prog);
  const head=sEl('div','stg-head');
  if(STAGE.cur.parent){
    const up=sEl('button','stg-crumb','↖ Back to the story this came from');
    up.onclick=()=>stageOpen(STAGE.cur.cid,STAGE.cur.parent.answer_to,(STAGE.cur.parent.seq||1)-1);
    head.append(up);
  }
  if(STAGE.cur.question)head.append(sEl('div','stg-q',STAGE.cur.question));
  const vs=STAGE.cur.versions||[],vi=vs.indexOf(STAGE.cur.answer_to);
  if(vs.length>1&&vi>=0){
    const v=sEl('div','stg-ver');
    const a=sEl('button','','‹');a.title='The version before';a.disabled=vi===0;a.onclick=()=>stageOpen(STAGE.cur.cid,vs[vi-1],0);
    const b=sEl('button','','›');b.title='The version after';b.disabled=vi===vs.length-1;b.onclick=()=>stageOpen(STAGE.cur.cid,vs[vi+1],0);
    v.append(a,sEl('span','',`Version ${vi+1} of ${vs.length}`),b);head.append(v);
  }
  th.append(head);
  const box=sEl('div','stg-scene k-'+sc.kind);
  box.append(sEl('div','stg-kicker',`${STAGE.at+1} of ${n} · ${STAGE_KIND[sc.kind]||sc.kind}`));
  box.append(sEl('div','stg-title',sc.title||STAGE_KIND[sc.kind]));
  const art=sEl('div','stg-art st-art');box.append(art);
  th.append(box);
  // the narrator's line is a subtitle over the bottom of the picture, as in a film
  const foot=sEl('div','stg-foot');
  if(sc.caption){const cap=sEl('div','stg-cap');
    // the narrator's line, word by word: CSS delays, no timers to leak
    sc.caption.split(/\s+/).forEach((w,i)=>{const sp=sEl('span','',w+' ');sp.style.animationDelay=(250+i*55)+'ms';cap.append(sp)});
    foot.append(cap)}
  if(sc.illustrative)foot.append(sEl('div','st-src st-illus','Illustrative, not data'));
  else if(sc.source)foot.append(stageSource(sc.source));
  box.append(foot);
  try{stageDraw(art,sc)}catch(e){art.append(sEl('p','mut','Could not draw this scene: '+(e.message||e)))}
  // the controls: a glass bar along the bottom
  const bar=sEl('div','stg-bar');
  const prev=sEl('button','stg-b','‹');prev.title='Previous scene';prev.disabled=STAGE.at===0;prev.onclick=()=>stageGo(STAGE.at-1);
  const play=sEl('button','stg-b stg-play',STAGE.playing?'❚❚':'▶');play.title=STAGE.playing?'Pause':'Play the story';play.onclick=stagePlay;
  const next=sEl('button','stg-b','›');next.title='Next scene';next.disabled=STAGE.at>=n-1;next.onclick=()=>stageGo(STAGE.at+1);
  bar.append(prev,play,next);
  const deep=sEl('button','stg-b stg-deep','⤵ Go deeper');deep.title='Ask for this scene as its own story';
  deep.onclick=()=>stageDeeper(cur.seq);bar.append(deep);
  const kids=(STAGE.cur.deeper||{})[String(cur.seq)]||[];
  kids.forEach((a,i)=>{const k=sEl('button','stg-b stg-kid',kids.length>1?`Deeper story ${i+1} ›`:'The deeper story ›');
    k.onclick=()=>stageOpen(STAGE.cur.cid,a,0);bar.append(k)});
  const sp=sEl('span','stg-sp');bar.append(sp);
  const keep=sEl('button','stg-b','★ Keep');keep.title='Keep this story as a board, and refresh it if you like';
  keep.onclick=()=>stageKeepMenu(keep);
  const chat=sEl('button','stg-b','Chat');chat.title='Open the conversation';
  chat.onclick=()=>{if(typeof openConv==='function'){openApp('chat');openConv(STAGE.cur.cid)}};
  bar.append(keep,chat);
  th.append(bar);
  if(STAGE.awaiting)th.append(stageWaiting());
  stageMusicMood(sc.kind);
}
/* Every story a chat showed, outside the deeper ones, is a version of its Stage: asking
   "add Japan to the map" in the chat shows the story again with the change, and the one
   before stays one tap away. Asked for as "update the stage or add a new face to the same
   stage with the previous one there as well, like a new version". */
async function stageVersions(c){
  try{const d=await apiJSON('/api/stage?conversation='+encodeURIComponent(c.cid));
    c.versions=(d.stories||[]).filter(s=>!s.parent).map(s=>s.answer_to);
    if(STAGE.cur===c&&c.versions.length>1)stagePaintIfOpen()}catch(e){}
}
function stageWaiting(){
  const w=sEl('div','stg-wait');w.append(sEl('i',''),sEl('span','','Going deeper…'));return w;
}
function stageSource(src){
  const d=sEl('div','st-src');
  if(/^https?:\/\//i.test(src)){const a=document.createElement('a');a.href=src;a.target='_blank';a.rel='noopener noreferrer';
    let host=src;try{host=new URL(src).host}catch(e){}a.textContent='Source: '+host;d.append(a)}
  else d.textContent='Source: '+src;
  return d;
}
async function stageFetch(cid,answer_to,at){
  const d=await apiJSON('/api/stage/story?conversation='+encodeURIComponent(cid)+'&answer_to='+encodeURIComponent(answer_to||''));
  STAGE.cur={cid,answer_to:answer_to||'',question:'',parent:d.parent||null,deeper:d.deeper||{},versions:[]};
  stageVersions(STAGE.cur);
  STAGE.scenes=d.scenes||[];STAGE.at=Math.max(0,Math.min(at||0,STAGE.scenes.length-1));
  stageQuestion();
}
function stageGo(i){if(i<0||i>=STAGE.scenes.length)return;STAGE.at=i;STAGE.held=Date.now()+20000;stagePaint();}
function stagePlay(){
  if(STAGE.playing){STAGE.playing=false;stagePaint();return}
  STAGE.playing=true;if(STAGE.at>=STAGE.scenes.length-1)STAGE.at=0;STAGE.held=Date.now()+600000;stagePaint();
  if(stageMusicOn())stageMusic(true);
  const step=()=>{
    if(!STAGE.playing)return;
    const sc=STAGE.scenes[STAGE.at]&&STAGE.scenes[STAGE.at].scene;if(!sc){STAGE.playing=false;stagePaint();return}
    const line=sc.say||sc.caption||sc.title||'';
    const after=()=>setTimeout(()=>{if(!STAGE.playing)return;
      if(STAGE.at>=STAGE.scenes.length-1){STAGE.playing=false;STAGE.held=0;stagePaint();return}
      STAGE.at++;stagePaint();step()},900);
    // a video plays at its own pace: the story waits on it rather than cutting it off
    const hold=sc.kind==='video'?20000:sc.kind==='film'?stageFilmSeconds(sc)*1000:0;
    if(typeof VOICE!=='undefined'&&VOICE.tts&&typeof speakAs==='function'&&line)speakAs(agentName(),line,()=>setTimeout(after,hold));
    else setTimeout(after,Math.max(4500,line.length*60)+hold);
  };
  step();
}
/* Go deeper: the scene becomes a question in its own chat, sent as the person's message,
   and the story that answers it plays here next with a way back up. */
async function stageDeeper(seq){
  const c=STAGE.cur;if(!c)return;
  let d;
  try{const r=await fetch('/api/stage/deeper',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({conversation_id:c.cid,answer_to:c.answer_to,seq})});
    d=await r.json();if(!r.ok)throw new Error(d.error||r.status)}
  catch(e){toast('could not go deeper: '+(e.message||e));return}
  STAGE.awaiting={cid:c.cid,at:Date.now()};
  const sw=WM.wins.get('stage');
  if(typeof openConv==='function'&&typeof send==='function'){
    if(!WM.wins.get('chat'))openApp('chat');
    if(currentConv!==c.cid)await openConv(c.cid);
    if(typeof input!=='undefined'&&input){input.value=d.text;send()}
  }else if(typeof ws!=='undefined'&&ws&&ws.readyState===1){
    ws.send(JSON.stringify({type:'chat',text:d.text,conversation_id:c.cid,model:''}));
  }
  if(sw)focusWin(sw);
  stagePaint();
}
/* A turn that ended with no new story: say so, and stop waiting. */
function stageTurnEnd(cid){
  const a=STAGE.awaiting;if(!a||a.cid!==cid)return;
  setTimeout(()=>{if(STAGE.awaiting===a){STAGE.awaiting=null;stagePaintIfOpen();
    toast('The answer came back in words, without a new story. It is in the chat.')}},1500);
}
function stageKeepMenu(btn){
  const c=STAGE.cur;if(!c)return;
  const host=btn.closest('.stg')||btn.closest('.st-main');
  const old=host.querySelector('.st-keepbox');if(old){old.remove();return}
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
  host.append(box);
}
async function stageSettings(patch){
  try{const r=await fetch('/api/stage/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
    const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);STAGE.settings=d;
    toast(patch.big!==undefined?('Answer BIG is '+(d.big?'on':'off')):('scenes are shown in '+(d.app?d.app_name:'the Stage')));
    stagePaintIfOpen();if(typeof refreshApp==='function')refreshApp('settings');
  }catch(e){toast('could not save: '+(e.message||e))}
}

/* ---------- the music: a soft score made on this screen ---------- */
/* No files and nothing fetched: a pad of detuned voices through a slowly opening filter
   and a little echo, moving through four chords, with a quiet bell now and then. The
   mood follows the scene (brighter for numbers, darker for a map at night). Off until the
   person turns it on (`stage.music`, per browser); a browser starts sound only after a
   tap, so a scene arriving on its own waits for one. It stops with the window. */
var STAGE_MU={ctx:null,master:null,voices:[],timer:0,chord:0,mood:''};
var STAGE_CHORDS=[[57,64,67,71,72],[53,60,64,67,69],[48,55,59,62,64],[55,62,66,69,71]];
function stageMusicOn(){try{return localStorage.getItem('stage.music')==='1'}catch(e){return false}}
function stageMusic(on,closing){
  try{if(!closing)localStorage.setItem('stage.music',on?'1':'0')}catch(e){}
  const M=STAGE_MU;
  if(!on){if(M.master&&M.ctx){M.master.gain.setTargetAtTime(0,M.ctx.currentTime,.4);
      clearInterval(M.timer);M.timer=0;setTimeout(()=>{if(!stageMusicOn()||closing){try{M.ctx.suspend()}catch(e){}}},1600)}return}
  try{
    if(!M.ctx){
      const C=window.AudioContext||window.webkitAudioContext;if(!C){toast('This browser cannot play sound.');return}
      M.ctx=new C();
      M.master=M.ctx.createGain();M.master.gain.value=0;
      const lp=M.ctx.createBiquadFilter();lp.type='lowpass';lp.frequency.value=900;lp.Q.value=.6;
      const lfo=M.ctx.createOscillator(),lg=M.ctx.createGain();lfo.frequency.value=.05;lg.gain.value=420;lfo.connect(lg);lg.connect(lp.frequency);lfo.start();
      const dl=M.ctx.createDelay(1),fb=M.ctx.createGain(),wet=M.ctx.createGain();dl.delayTime.value=.42;fb.gain.value=.33;wet.gain.value=.35;
      lp.connect(M.master);lp.connect(dl);dl.connect(fb);fb.connect(dl);dl.connect(wet);wet.connect(M.master);
      M.master.connect(M.ctx.destination);M.lp=lp;
      for(let i=0;i<5;i++){
        const g=M.ctx.createGain();g.gain.value=.05;g.connect(lp);
        const a=M.ctx.createOscillator(),b=M.ctx.createOscillator();a.type='sawtooth';b.type='triangle';b.detune.value=7;a.detune.value=-6;
        a.connect(g);b.connect(g);a.start();b.start();M.voices.push({a,b,g});
      }
    }
    M.ctx.resume();
    stageChord(true);
    clearInterval(M.timer);M.timer=setInterval(()=>{stageChord();if(Math.random()<.5)stageBell()},8000);
    M.master.gain.setTargetAtTime(.14,M.ctx.currentTime,1.2);
  }catch(e){}
}
function stageMidi(n){return 440*Math.pow(2,(n-69)/12)}
function stageChord(now){
  const M=STAGE_MU;if(!M.ctx)return;
  if(!now)M.chord=(M.chord+1)%STAGE_CHORDS.length;
  const lift=M.mood==='bright'?12:M.mood==='low'?-12:0;
  STAGE_CHORDS[M.chord].forEach((n,i)=>{const v=M.voices[i];if(!v)return;const f=stageMidi(n+(i===0?-12:0)+(i>2?lift:0));
    v.a.frequency.setTargetAtTime(f,M.ctx.currentTime,now?.01:1.6);v.b.frequency.setTargetAtTime(f,M.ctx.currentTime,now?.01:1.6)});
}
function stageBell(){
  const M=STAGE_MU;if(!M.ctx)return;
  const o=M.ctx.createOscillator(),g=M.ctx.createGain(),t=M.ctx.currentTime;
  const scale=[72,74,76,79,81,84];o.type='sine';o.frequency.value=stageMidi(scale[Math.floor(Math.random()*scale.length)]);
  g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.05,t+.02);g.gain.exponentialRampToValueAtTime(.0001,t+3.2);
  o.connect(g);g.connect(M.lp||M.master);o.start(t);o.stop(t+3.3);
}
function stageMusicMood(kind){
  const M=STAGE_MU;const m=kind==='numbers'||kind==='chart'||kind==='steps'?'bright':kind==='map'||kind==='video'?'low':'';
  if(m===M.mood)return;M.mood=m;if(M.ctx&&stageMusicOn())stageChord(true);
}

/* ---------- the library: every story you were shown ---------- */
function stageLibrary(main){
  const lib=STAGE.lib;
  if(!lib){main.append(sEl('p','mut','Reading…'));return}
  const st=lib.stories||[];
  if(!st.length){main.append(sEl('p','mut st-pad','Nothing yet. Every story an answer shows is kept here, with the chat it came from.'));return}
  const grid=sEl('div','st-grid');
  const KI={chart:'📈',map:'🗺',numbers:'#',timeline:'⟶',steps:'⇢',table:'▦',image:'🖼',video:'▶'};
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
  ({chart:stageChart,map:stageMap,numbers:stageNumbers,timeline:stageTimeline,steps:stageSteps,table:stageTable,
    image:stageImage,video:stageVideo,film:stageFilm}[sc.kind]||(()=>{}))(art,sc);
  if(stageReduced())art.classList.add('still');
}

/* Glow and gradients, shared by every drawing: defined once per SVG, by id. */
var STAGE_UID=0;
function stageDefs(svg,cols){
  const id='sg'+(++STAGE_UID),d=sSvg('defs');
  const f=sSvg('filter',{id:id+'-glow',x:'-50%',y:'-50%',width:'200%',height:'200%'});
  f.append(sSvg('feGaussianBlur',{stdDeviation:'4',result:'b'}));
  const m=sSvg('feMerge');m.append(sSvg('feMergeNode',{in:'b'}),sSvg('feMergeNode',{in:'SourceGraphic'}));f.append(m);d.append(f);
  (cols||[]).forEach((c,i)=>{
    const g=sSvg('linearGradient',{id:id+'-g'+i,x1:'0',y1:'0',x2:'0',y2:'1'});
    const a=sSvg('stop',{offset:'0'});a.style.stopColor=c;a.style.stopOpacity='.55';
    const b=sSvg('stop',{offset:'1'});b.style.stopColor=c;b.style.stopOpacity='0';g.append(a,b);d.append(g);
    const h=sSvg('linearGradient',{id:id+'-b'+i,x1:'0',y1:'0',x2:'0',y2:'1'});
    const p=sSvg('stop',{offset:'0'});p.style.stopColor=c;const q=sSvg('stop',{offset:'1'});q.style.stopColor=c;q.style.stopOpacity='.45';
    h.append(p,q);d.append(h);
  });
  svg.append(d);return id;
}

/* --- a picture, slowly moving (Ken Burns), with its credit --- */
function stageImage(art,sc){
  const fr=sEl('div','stg-pic');
  const img=document.createElement('img');
  img.alt=sc.alt||sc.title||'';img.decoding='async';img.referrerPolicy='no-referrer';
  img.src=sc.asset?'/api/assets/'+encodeURIComponent(sc.asset)+'/file':sc.url;
  // a picture host may refuse a first request (busy, or rate-limited): ask once more first
  let tries=0;
  img.onerror=()=>{if(tries++<1){setTimeout(()=>{img.src=img.src.split('#')[0]+'#retry'},1500);return}
    fr.textContent='';fr.classList.add('broken');
    fr.append(sEl('div','stg-pic-x','This picture could not be loaded.'));
    if(sc.url){const a=document.createElement('a');a.href=sc.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Open it where it lives';fr.append(a)}};
  fr.append(img);
  if(sc.credit)fr.append(sEl('div','stg-credit',sc.credit));
  art.append(fr);
}
/* --- a YouTube video, played from youtube-nocookie.com. In the Telegram page (no
   frames there), its picture links to YouTube instead. --- */
function stageVideo(art,sc){
  const fr=sEl('div','stg-vid');
  if(window.STAGE_REPORT){
    const a=document.createElement('a');a.href='https://www.youtube.com/watch?v='+encodeURIComponent(sc.video)+(sc.start?'&t='+sc.start:'');
    a.target='_blank';a.rel='noopener noreferrer';a.className='stg-vid-link';
    const img=document.createElement('img');img.alt=sc.title||'video';img.referrerPolicy='no-referrer';
    img.src='https://i.ytimg.com/vi/'+encodeURIComponent(sc.video)+'/hqdefault.jpg';
    a.append(img,sEl('span','stg-vid-play','▶'));fr.append(a);art.append(fr);return;
  }
  const f=document.createElement('iframe');
  f.src='https://www.youtube-nocookie.com/embed/'+encodeURIComponent(sc.video)+'?rel=0&modestbranding=1&playsinline=1'+(sc.start?'&start='+sc.start:'');
  f.title=sc.title||'video';f.allow='encrypted-media; picture-in-picture; fullscreen';f.allowFullscreen=true;
  f.referrerPolicy='strict-origin-when-cross-origin';f.loading='lazy';
  fr.append(f);art.append(fr);
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
/* "2015-07" reads as "Jul 15", a day as "3 Jul 15": short enough for its slot. */
function stageDateLabel(x){
  const m=String(x).match(/^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?/);if(!m)return String(x);
  if(!m[2])return m[1];
  const mon=new Date(Date.UTC(2000,+m[2]-1,1)).toLocaleString(undefined,{month:'short',timeZone:'UTC'});
  return (m[3]?(+m[3])+' ':'')+mon+' '+m[1].slice(2);
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
  const T=Math.round(18*K)+8;let B=Math.round((sc.x_label?40:22)*K)+14;
  let L=72;
  const series=sc.series||[];
  if(sc.chart_type==='pie'){stagePie(svg,series[0],sc,W,H);return}
  const all=series.flatMap(s=>s.points);
  const xs=all.map(p=>p[0]);
  const isNum=xs.every(x=>typeof x==='number'), dates=!isNum&&xs.every(x=>stageDate(x)!=null);
  const cats=[];if(!isNum&&!dates)xs.forEach(x=>{if(!cats.includes(x))cats.push(x)});
  const xv=x=>isNum?x:dates?stageDate(x):cats.indexOf(x);
  // a long category name gets a second line rather than an ellipsis (a picture on a phone
  // has no hover to read the rest), and the bottom margin makes room for it
  const twoLines=cats.length>0&&cats.some(c=>String(c).length*7.2*K>(W-72-R)/cats.length-6);
  if(twoLines)B+=Math.round(16*K);
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
  else if(dates){const pts=[...new Set(xs)];const k=Math.ceil(pts.length/8);xl=pts.filter((_,i)=>i%k===0).map(x=>[stageDate(x),stageDateLabel(x)])}
  else{const k=Math.ceil(cats.length/10);xl=cats.map((c,i)=>[i,c]).filter((_,i)=>i%k===0)}
  // each name gets its slot and is cut to it, so neighbours never run into each other
  const room=xl.length>1?Math.abs(X(xl[1][0])-X(xl[0][0]))-6:W-L-R;
  xl.forEach(([v,label])=>{
    const lines=twoLines?stageTwoLines(label,Math.floor(room/(7.2*K))):[fitText(label,room)];
    const t=sSvg('text',{x:X(v),y:H-B+18*K,'text-anchor':'middle'});
    lines.filter(Boolean).forEach((ln,i)=>t.append(sSvg('tspan',{x:X(v),dy:i?16*K:0},ln)));
    if(t.childNodes.length)g.append(t)});
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
  const gid=stageDefs(svg,series.map((_,si)=>STAGE_PAL[si%STAGE_PAL.length]));
  series.forEach((s,si)=>{
    const col=STAGE_PAL[si%STAGE_PAL.length];
    const pts=s.points.map(p=>[xv(p[0]),p[1]]).sort((a,b)=>a[0]-b[0]);
    if(bar){
      const slot=(W-L-R)/((x1-x0)||1),bw=Math.max(2,slot*0.7/n);
      pts.forEach((p,i)=>{const x=X(p[0])-slot*0.35+si*bw,y=Y(Math.max(0,p[1])),h=Math.abs(Y(p[1])-Y(0));
        const r=sSvg('rect',{x,y,width:bw-2,height:Math.max(1,h),rx:Math.min(8,(bw-2)/4),fill:`url(#${gid}-b${si})`,class:'st-bar',style:`animation-delay:${i*40}ms`});
        r.append(sSvg('title',{},`${s.name?s.name+': ':''}${stageFmt(p[1],sc.unit)}`));svg.append(r);
        // the value over its bar only when it fits the bar's slot
        const vt=stageFmt(p[1],tu);
        if(vt.length*7.2*K<=slot*0.95/n)svg.append(sSvg('text',{x:x+(bw-2)/2,y:y-6*K,'text-anchor':'middle',class:'st-val'},vt))});
      return;
    }
    if(sc.chart_type==='scatter'){
      pts.forEach((p,i)=>svg.append(sSvg('circle',{cx:X(p[0]),cy:Y(p[1]),r:5,fill:col,class:'st-dot',style:`animation-delay:${Math.min(i,60)*15}ms`})));return}
    const d=pts.map((p,i)=>(i?'L':'M')+X(p[0]).toFixed(1)+' '+Y(p[1]).toFixed(1)).join('');
    // a line always stands on its own light: the area under it fades to nothing
    if(sc.chart_type==='area'||n<=2){
      const base=Y(Math.max(y0,Math.min(0,y1)));
      const a=d+`L${X(pts[pts.length-1][0]).toFixed(1)} ${base}L${X(pts[0][0]).toFixed(1)} ${base}Z`;
      svg.append(sSvg('path',{d:a,fill:`url(#${gid}-g${si})`,class:'st-area'}))}
    svg.append(sSvg('path',{d,stroke:col,class:'st-line',pathLength:1000,filter:`url(#${gid}-glow)`}));
    const last=pts[pts.length-1];
    svg.append(sSvg('circle',{cx:X(last[0]),cy:Y(last[1]),r:14,fill:col,class:'st-endglow'}));
    svg.append(sSvg('circle',{cx:X(last[0]),cy:Y(last[1]),r:5.5,fill:col,class:'st-end',filter:`url(#${gid}-glow)`}));
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
  const mid=stageDefs(svg,['#F43F5E']);
  // the lines of latitude and longitude, faint, every 30 degrees
  const gr=sSvg('g',{class:'st-grat'});
  for(let lo=-180;lo<=180;lo+=30)gr.append(sSvg('line',{x1:X(lo),x2:X(lo),y1:0,y2:H}));
  for(let la=-60;la<=90;la+=30)gr.append(sSvg('line',{x1:0,x2:W,y1:Y(la),y2:Y(la)}));
  svg.append(gr);
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
  // a few places in order are a journey: arcs join them, drawn one after another
  if(sc.route&&pts.length>=2&&pts.length<=12){
    const arcs=sSvg('g',{class:'st-arcs'});
    for(let i=1;i<pts.length;i++){const a=pts[i-1],b=pts[i],ax=X(a.lon),ay=Y(a.lat),bx=X(b.lon),by=Y(b.lat);
      const mx=(ax+bx)/2,my=(ay+by)/2-Math.hypot(bx-ax,by-ay)*.25;
      arcs.append(sSvg('path',{d:`M${ax} ${ay}Q${mx} ${my} ${bx} ${by}`,pathLength:100,style:`animation-delay:${400+i*250}ms`}))}
    svg.append(arcs);
  }
  const noted=pts.filter(p=>p.note);
  const fits=(lx,ly,lw,th)=>lx>=2&&lx+lw<=W-2&&ly>=2&&ly+th<=H-2
    &&!taken.some(b=>lx<b[2]&&lx+lw>b[0]&&ly<b[3]&&ly+th>b[1]);
  order.forEach(([p],rank)=>{
    const x=X(p.lon),y=Y(p.lat);if(x<-10||x>W+10||y<-10||y>H+10)return;
    const t=p.value!=null&&pv.length>1?(p.value-pmin)/((pmax-pmin)||1):0.5;
    const r=6+t*10,delay=Math.min(rank,30)*120;
    const g=sSvg('g',{class:'st-pin',style:`animation-delay:${delay}ms`});
    g.append(sSvg('circle',{cx:x,cy:y,r:r*1.9,class:'st-pulse'}),sSvg('circle',{cx:x,cy:y,r,class:'st-pt',filter:`url(#${mid}-glow)`}));
    g.append(sSvg('title',{},(p.label||'')+(p.value!=null?': '+stageFmt(p.value,sc.unit):'')+(p.note?' · '+p.note:'')));
    // a place with a note is numbered, and its note is listed under the map: a picture has
    // no hover, and the note is what happened there
    const n=noted.indexOf(p);
    if(n>=0)g.append(sSvg('text',{x,y:y+4*K,'text-anchor':'middle',class:'st-pinno'},String(n+1)));
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
  if(noted.length){const ol=sEl('ol','st-mapnotes');
    noted.forEach((p,i)=>{const li=sEl('li','');li.style.animationDelay=(600+i*160)+'ms';
      li.append(sEl('b','',(i+1)+' · '+(p.label||'')+(p.value!=null?' '+stageFmt(p.value,sc.unit):'')),sEl('span','',p.note));ol.append(li)});
    art.append(ol)}
  if(missing.length)art.append(sEl('p','mut st-note','Not on this map: '+missing.join(', ')));
  if(vals.length>1){const lg=sEl('div','st-scale');lg.append(sEl('span','',stageFmt(vmin,sc.unit)),sEl('i',''),sEl('span','',stageFmt(vmax,sc.unit)));art.append(lg)}
}

/* --- numbers, timeline, steps, table --- */
/* A name on two lines at most, broken at a space, each line cut to n characters. */
function stageTwoLines(text,n){
  const s=String(text);if(n<3)return [];if(s.length<=n)return [s];
  let cut=s.lastIndexOf(' ',n);if(cut<=0)cut=n;
  const a=s.slice(0,cut).trim(),b=s.slice(cut).trim();
  return [a.length>n?a.slice(0,n-1)+'…':a,b.length>n?b.slice(0,n-1)+'…':b];
}
/* A value and its unit as people write them: "$2.6 billion", "10–15 years", "45%". */
function stageWithUnit(value,unit){
  const v=String(value),u=String(unit||'');if(!u)return v;
  const cur=u.match(/^([$€£₹¥])\s*(.*)$/);
  if(cur)return cur[1]+v+(cur[2]?' '+cur[2]:'');
  return /^[A-Za-z]/.test(u)?v+' '+u:v+u;
}
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
        v.textContent=stageWithUnit((target*e).toLocaleString(undefined,{minimumFractionDigits:dec,maximumFractionDigits:dec})+rest,unit);
        if(k<1&&v.isConnected)requestAnimationFrame(tick)};
      requestAnimationFrame(tick);
    }else v.textContent=stageWithUnit(it.value,unit);
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
  // a column of numbers is right-aligned, its heading with it
  const isN=v=>/^[-+]?[\d,.]+%?$/.test(String(v==null?'':v));
  const numCol=sc.columns.map((_,j)=>sc.rows.length>0&&sc.rows.every(r=>r[j]==null||r[j]===''||isN(r[j])));
  const hr=document.createElement('tr');sc.columns.forEach((c,j)=>hr.append(sEl('th',numCol[j]?'n':'',c)));
  const th=document.createElement('thead');th.append(hr);tb.append(th);
  const body=document.createElement('tbody');
  sc.rows.forEach((r,i)=>{const tr=document.createElement('tr');tr.style.animationDelay=Math.min(i,20)*40+'ms';
    sc.columns.forEach((_,j)=>{const td=sEl('td','',r[j]==null?'':r[j]);if(numCol[j]||isN(r[j]))td.className='n';tr.append(td)});body.append(tr)});
  tb.append(body);wrap.append(tb);art.append(wrap);
}

/* --- a film: a short 3D animation played from the agent's shot list ---
   The model picks each shot's subject and camera from a closed set (stage.FILM_*) and this
   builds and moves the scene with three.js (vendored, MIT, imported on first use, as the
   World does). Nothing the model wrote runs here. One small renderer per film, at most 30
   frames a second, none while the window is hidden, stopped the moment the drawing leaves
   the page. With no WebGL, under reduced motion, or on the Telegram page (no server to load
   three.js from), it is a storyboard: the shots as cards, which is also what a phone's
   picture shows. */
var STAGE_FILM_COL=[0x8b5cf6,0xf59e0b,0x22d3ee,0xf472b6,0x34d399,0xa78bfa,0xf87171,0x94a3b8];
var STAGE_FILM_GLYPH={city:'▦',tower:'▮',bars:'▥',rocket:'⬆',factory:'⌂',solar:'▤',road:'⇢',
  conveyor:'⇉',crowd:'⁂',globe:'◍'};
function stageFilmSeconds(sc){return (sc.shots||[]).reduce((t,s)=>t+(s.seconds||4),0)}
function stageFilmBoard(fr,sc){
  fr.classList.add('board');
  const row=sEl('div','film-board');
  (sc.shots||[]).forEach((sh,i)=>{
    const c=sEl('div','film-card');
    c.append(sEl('div','film-glyph',STAGE_FILM_GLYPH[sh.subject]||'◇'),
      sEl('div','film-n',`${i+1} · ${sh.seconds}s · ${sh.camera}`));
    if(sh.value!=null)c.append(sEl('div','film-v',stageWithUnit(stageFmt(sh.value),sh.unit)));
    if(sh.text)c.append(sEl('div','film-t',sh.text));
    row.append(c)});
  fr.append(row);
}
function stageFilmGL(){try{const c=document.createElement('canvas');return !!(c.getContext('webgl2')||c.getContext('webgl'))}catch(e){return false}}
async function stageFilm(art,sc){
  const fr=sEl('div','stg-film');art.append(fr);
  if(window.STAGE_REPORT||stageReduced()||!stageFilmGL()){stageFilmBoard(fr,sc);return}
  let T;
  try{T=(typeof WORLD!=='undefined'&&WORLD.T)||(typeof OF3!=='undefined'&&OF3.T)||await import('/assets/three.module.min.js')}
  catch(e){stageFilmBoard(fr,sc);return}
  if(!fr.isConnected)return;
  const cv=document.createElement('canvas');fr.append(cv);
  const labels=sEl('div','film-labels'),sub=sEl('div','film-sub'),val=sEl('div','film-val'),
        dots=sEl('div','film-dots'),again=sEl('button','film-again','↻ Play again');
  again.hidden=true;fr.append(labels,val,sub,dots,again);
  (sc.shots||[]).forEach(()=>dots.append(sEl('i','')));
  let R;
  try{R=new T.WebGLRenderer({canvas:cv,antialias:true,alpha:false,powerPreference:'low-power'})}
  catch(e){cv.remove();labels.remove();sub.remove();val.remove();dots.remove();again.remove();stageFilmBoard(fr,sc);return}
  R.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));
  const LOOK={day:{sky:0xcfe0f5,ground:0xf4f5f8,sun:1.25,amb:.9,fog:0xcfe0f5},
              dusk:{sky:0x6a4a7e,ground:0xe9d9e4,sun:1.05,amb:.8,fog:0x6a4a7e},
              night:{sky:0x0a1024,ground:0x232a44,sun:.45,amb:.45,fog:0x0a1024}}[sc.look||'day'];
  // the ground runs out past the fog, so no edge of the world is ever on screen
  const S=new T.Scene();S.background=new T.Color(LOOK.sky);S.fog=new T.Fog(LOOK.fog,45,110);
  const cam=new T.PerspectiveCamera(40,1,.1,400);
  S.add(new T.HemisphereLight(0xffffff,LOOK.ground,LOOK.amb));
  const sun=new T.DirectionalLight(0xffffff,LOOK.sun);sun.position.set(30,50,20);S.add(sun);
  const ground=new T.Mesh(new T.CircleGeometry(400,48),new T.MeshLambertMaterial({color:LOOK.ground}));
  ground.rotation.x=-Math.PI/2;S.add(ground);
  const night=sc.look==='night';
  const M=c=>new T.MeshLambertMaterial({color:c,emissive:night?c:0,emissiveIntensity:night?.25:0});
  const box=(w,h,d,c)=>{const m=new T.Mesh(new T.BoxGeometry(w,h,d),M(c));return m};
  const tree=(x,z)=>{const g=new T.Group();const t=new T.Mesh(new T.CylinderGeometry(.15,.15,.8,6),M(0x8d6e63));t.position.y=.4;
    const l=new T.Mesh(new T.ConeGeometry(.7,1.6,8),M(0x4caf50));l.position.y=1.5;g.add(t,l);g.position.set(x,0,z);return g};
  // a seeded random, so a film looks the same every time it is played
  let seed=7;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;
  const H=Math.max(...(sc.shots||[]).flatMap(s=>(s.items||[]).map(i=>Math.abs(i.value))).concat([1]));
  /* each builder makes its subject in `g` and returns {tick(u), r (how far the camera
     stands), y (where it looks), tags: [[Object3D, text]]} — u runs 0→1 over the shot */
  const B={
    city(g){seed=11;const bs=[];for(let i=-3;i<=3;i++)for(let j=-3;j<=3;j++){if(rnd()<.18){g.add(tree(i*3.2,j*3.2));continue}
        const h=1+rnd()*8,b=box(2.2,h,2.2,[0xffffff,0xe8ecf4,0x3949ab][rnd()<.15?2:rnd()<.5?1:0]);b.position.set(i*3.2,h/2,j*3.2);g.add(b);bs.push([b,h])}
      return {r:30,y:2,tick:u=>bs.forEach(([b,h],k)=>{const e=Math.min(1,Math.max(0,u*1.6-k/bs.length*.6));b.scale.y=Math.max(.01,e);b.position.y=h*e/2})}},
    tower(g,sh){const b=box(3,1,3,0x3949ab);g.add(b);for(let i=0;i<8;i++){const a=i/8*Math.PI*2;g.add(tree(Math.cos(a)*7,Math.sin(a)*7))}
      const top=16;return {r:30,y:6,tick:u=>{const e=1-Math.pow(1-u,3);b.scale.y=Math.max(.01,top*e);b.position.y=top*e/2;
        if(sh.value!=null)val.textContent=stageWithUnit(stageFmt(sh.value*e),sh.unit)}}},
    bars(g,sh){const it=sh.items||[],n=it.length,w=2.2,tags=[];
      const bs=it.map((x,i)=>{const b=box(w,1,w,STAGE_FILM_COL[i%8]);b.position.x=(i-(n-1)/2)*(w+1.2);g.add(b);
        const t=new T.Object3D();g.add(t);tags.push([t,x.label+' '+stageWithUnit(stageFmt(x.value),sh.unit)]);return [b,t,Math.abs(x.value)/H*12]});
      return {r:Math.max(32,n*5.5),y:6,tags,tick:u=>bs.forEach(([b,t,h],k)=>{const e=Math.min(1,Math.max(0,u*1.5-k*.08));const v=1-Math.pow(1-e,3);
        b.scale.y=Math.max(.01,h*v);b.position.y=h*v/2;t.position.set(b.position.x,h*v+.8,0)})}},
    rocket(g){const pad=box(6,.6,6,0x9e9e9e);pad.position.y=.3;g.add(pad);
      const tw=box(.6,14,.6,0xd32f2f);tw.position.set(-2.4,7,0);g.add(tw);
      const r=new T.Group(),body=new T.Mesh(new T.CylinderGeometry(.8,.8,7,16),M(0xffffff)),nose=new T.Mesh(new T.ConeGeometry(.8,2,16),M(0x3949ab));
      body.position.y=3.5;nose.position.y=8;r.add(body,nose);
      for(let i=0;i<4;i++){const f=box(.12,1.6,1.2,0x3949ab);const a=i*Math.PI/2;f.position.set(Math.cos(a)*.85,.8,Math.sin(a)*.85);f.rotation.y=-a;r.add(f)}
      r.position.y=.6;g.add(r);const puffs=[];
      for(let i=0;i<26;i++){const p=new T.Mesh(new T.SphereGeometry(.7,8,6),new T.MeshLambertMaterial({color:0xf5f5f5,transparent:true,opacity:.85}));p.visible=false;g.add(p);puffs.push(p)}
      const out={r:30,y:6,tick:u=>{const lift=u<.2?0:Math.pow((u-.2)/.8,2)*26;r.position.y=.6+lift;out.y=6+lift*.8;
        puffs.forEach((p,k)=>{const age=(u*26-k);p.visible=u>.15&&age>0;const s=1+age*.25;p.scale.setScalar(s);
          p.position.set(Math.sin(k*1.7)*age*.4,Math.max(.5,r.position.y-(k%6)*1.2-1),Math.cos(k*2.3)*age*.4);p.material.opacity=Math.max(0,.85-age*.05)})}};
      return out},
    factory(g){const f=box(10,4,6,0xffffff);f.position.y=2;g.add(f);const st=box(10.1,.6,6.1,0x3949ab);st.position.y=3.2;g.add(st);
      const ch=[-3,0,3].map(x=>{const c=new T.Mesh(new T.CylinderGeometry(.5,.6,5,10),M(0xb0bec5));c.position.set(x,6.5,-1.5);g.add(c);return c});
      for(let i=-2;i<=2;i++){const p=box(1.6,.1,1,0x1a237e);p.position.set(i*1.9,4.1,1.5);p.rotation.x=-.3;g.add(p)}
      for(let i=0;i<6;i++)g.add(tree(-9+i*3.6,7));
      const puffs=[];ch.forEach(c=>{for(let i=0;i<6;i++){const p=new T.Mesh(new T.SphereGeometry(.6,8,6),new T.MeshLambertMaterial({color:0xeceff1,transparent:true,opacity:.7}));
        g.add(p);puffs.push([p,c,i/6])}});
      return {r:26,y:3,tick:u=>puffs.forEach(([p,c,o])=>{const k=(u*3+o)%1;p.position.set(c.position.x+k*1.5,9+k*6,c.position.z);p.scale.setScalar(.6+k*1.6);p.material.opacity=.75*(1-k)})}},
    solar(g){const ps=[];for(let r=-3;r<=3;r++)for(let c=-4;c<=4;c++){const p=box(2,.12,1.2,0x1a237e);p.position.set(c*2.4,.8,r*2.2);p.rotation.x=-.45;p.visible=false;g.add(p);ps.push(p)}
      return {r:28,y:0,tick:u=>ps.forEach((p,k)=>{p.visible=k/ps.length<u*1.3})}},
    road(g){const rd=box(60,.05,4,0x424242);rd.position.y=.03;g.add(rd);
      for(let i=-6;i<=6;i++){const m=box(1.5,.06,.15,0xffffff);m.position.set(i*4.5,.06,0);g.add(m)}
      for(let i=0;i<8;i++)g.add(tree(-24+i*7,5));
      const cars=[...Array(7)].map((_,k)=>{const c=box(1.8,.9,1,STAGE_FILM_COL[k%8]);c.position.set(0,.5,k%2?-1:1);g.add(c);return [c,k]});
      return {r:24,y:0,tick:u=>cars.forEach(([c,k])=>{const d=k%2?-1:1;c.position.x=((u*60*d+k*9)%60+60)%60-30})}},
    conveyor(g){const belt=box(30,.5,2.4,0x37474f);belt.position.y=1;g.add(belt);
      const items=[...Array(9)].map((_,k)=>{const b=box(1.2,1.2,1.2,[0xffb74d,0xa1887f,0xffffff][k%3]);b.position.y=1.85;g.add(b);return [b,k]});
      const mk=box(5,4,4,0x3949ab);mk.position.set(-15,2,0);g.add(mk);const tr=box(4,3,3,0xffffff);tr.position.set(15,1.5,0);g.add(tr);
      return {r:22,y:1,tick:u=>items.forEach(([b,k])=>{b.position.x=((u*30+k*3.4)%30)-15})}},
    crowd(g,sh){seed=5;const ppl=[];for(let i=0;i<120;i++){const a=rnd()*Math.PI*2,d=Math.sqrt(rnd())*12;
        const p=new T.Group(),b=new T.Mesh(new T.CylinderGeometry(.28,.34,1.1,8),M(STAGE_FILM_COL[i%8])),h=new T.Mesh(new T.SphereGeometry(.28,10,8),M(0xffcc80));
        b.position.y=.55;h.position.y=1.35;p.add(b,h);p.position.set(Math.cos(a)*d,0,Math.sin(a)*d);p.visible=false;g.add(p);ppl.push(p)}
      return {r:26,y:0,tick:u=>{ppl.forEach((p,k)=>{p.visible=k/ppl.length<u*1.2});
        if(sh.value!=null)val.textContent=stageWithUnit(stageFmt(Math.round(sh.value*Math.min(1,u*1.2))),sh.unit)}}},
    globe(g,sh){const R=7,e=new T.Mesh(new T.SphereGeometry(R,48,32),new T.MeshLambertMaterial({color:0x1e3a8a,emissive:0x0b1a4a,emissiveIntensity:.4}));
      e.position.y=R+1;g.add(e);const ring=new T.Mesh(new T.TorusGeometry(R+.2,.05,6,96),new T.MeshBasicMaterial({color:0x93c5fd}));ring.rotation.x=Math.PI/2;e.add(ring);
      const tags=[];(sh.points||[]).forEach((pt,i)=>{const la=pt.lat*Math.PI/180,lo=pt.lon*Math.PI/180;
        const m=new T.Mesh(new T.SphereGeometry(.28,10,8),new T.MeshBasicMaterial({color:STAGE_FILM_COL[(i+1)%8]}));
        m.position.set(R*Math.cos(la)*Math.sin(lo),R*Math.sin(la),R*Math.cos(la)*Math.cos(lo));e.add(m);if(pt.label)tags.push([m,pt.label])});
      return {r:24,y:R+1,tags,tick:u=>{e.rotation.y=-.6+u*1.6}}},
  };
  const shots=sc.shots||[];let i=-1,t0=0,cur=null,grp=null,stopped=false,last=0;
  const CAM={orbit:(u,r,y)=>[Math.cos(.6+u*1.1)*r,y+r*.45,Math.sin(.6+u*1.1)*r],
    push:(u,r,y)=>{const d=r*(1.35-u*.55);return [d*.62,y+d*.4,d*.78]},
    rise:(u,r,y)=>[r*.7,y+.5+u*r*.9,r*.7],
    fly:(u,r,y)=>[-r*.7+u*r*1.4,y+r*.35,r*.85],
    top:(u,r,y)=>[r*.5*(1-u),y+r*(.6+u*.7),r*.8*(1-u)+.01]};
  const show=k=>{
    if(grp){S.remove(grp);grp.traverse(o=>{if(o.geometry)o.geometry.dispose();if(o.material)o.material.dispose()})}
    i=k;const sh=shots[k];grp=new T.Group();S.add(grp);val.textContent='';labels.textContent='';
    cur=(B[sh.subject]||B.city)(grp,sh)||{r:28,y:2,tick:()=>{}};
    (cur.tags||[]).forEach(t=>{t.el=sEl('span','',t[1]);labels.append(t.el)});
    if(sh.value!=null&&!['tower','crowd'].includes(sh.subject))val.textContent=stageWithUnit(stageFmt(sh.value),sh.unit);
    sub.textContent='';(sh.text||'').split(/\s+/).filter(Boolean).forEach((w,j)=>{const s=sEl('span','',w+' ');s.style.animationDelay=(150+j*60)+'ms';sub.append(s)});
    [...dots.children].forEach((d,j)=>d.className=j<k?'done':j===k?'on':'');
    t0=performance.now();
  };
  const size=()=>{const w=fr.clientWidth||640,h=fr.clientHeight||360;R.setSize(w,h,false);cam.aspect=w/h;cam.updateProjectionMatrix()};
  const v=new T.Vector3();
  const frame=now=>{
    if(stopped)return;
    if(!fr.isConnected){stopped=true;R.dispose();if(grp)grp.traverse(o=>{if(o.geometry)o.geometry.dispose()});return}
    requestAnimationFrame(frame);
    if(document.hidden||now-last<33)return;last=now;
    const sh=shots[i],u=Math.min(1,(now-t0)/(sh.seconds*1000));
    cur.tick(u);
    // a wide, short drawing would leave the subject small in the middle: come closer
    const near=Math.min(1,Math.max(.7,1.5/cam.aspect));
    const p=(CAM[sh.camera]||CAM.orbit)(u,cur.r*near,cur.y);cam.position.set(p[0],p[1],p[2]);cam.lookAt(0,cur.y,0);
    if(cv.width!==Math.round(fr.clientWidth*R.getPixelRatio()))size();
    R.render(S,cam);
    (cur.tags||[]).forEach(t=>{t[0].getWorldPosition(v);v.project(cam);
      t.el.style.left=((v.x+1)/2*100)+'%';t.el.style.top=((1-v.y)/2*100)+'%';t.el.style.opacity=v.z<1?'1':'0'});
    if(u>=1){if(i<shots.length-1)show(i+1);else if(again.hidden){again.hidden=false;[...dots.children].forEach(d=>d.className='done')}}
  };
  again.onclick=()=>{again.hidden=true;show(0)};
  size();show(0);requestAnimationFrame(frame);
}
