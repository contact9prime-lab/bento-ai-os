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
var STAGE_DOWN='#F43F5E',STAGE_UP='#34D399';
var STAGE_PAL=['var(--acc)','#F59E0B','#22D3EE','#F472B6','#34D399','#A78BFA','#F87171','#94A3B8'];

function stageAuto(){try{return localStorage.getItem('stage.auto')!=='0'}catch(e){return true}}
function stageSetAuto(on){try{localStorage.setItem('stage.auto',on?'1':'0')}catch(e){}}

function sEl(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);return e}
var SVGNS='http://www.w3.org/2000/svg';
/* How much a 960x500 drawing (or the map's own w x h) is shrunk where it is shown, so its
   text is drawn that much larger: the SVG keeps its shape, so the scale is the tighter of
   width and height. */
function stageK(svg,w,h){
  w=w||960;h=h||500;
  const b=svg.getBoundingClientRect();
  const s=Math.min((b.width||w)/w,(b.height||h)/h);
  return Math.max(1,Math.min(2.8,1/Math.max(.2,s)));
}
function sSvg(tag,attrs,text){const e=document.createElementNS(SVGNS,tag);
  for(const k in attrs||{})e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=String(text);return e}
function stageReduced(){try{return matchMedia('(prefers-reduced-motion: reduce)').matches}catch(e){return false}}

/* ---------- which screen shows which chat ---------- */
function stageMine(cid){
  if(!cid)return false;
  if(STAGE.awaiting&&STAGE.awaiting.cid===cid)return true;     // a Go deeper from the Stage itself
  if(typeof STAGE_CHAT!=='undefined'&&STAGE_CHAT.cid===cid&&STAGE_CHAT.el&&STAGE_CHAT.el.isConnected)return true;   // asked in the Stage's chat
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
    let was=STAGE.awaiting&&STAGE.awaiting.cid===ev.conversation_id&&STAGE.cur?{answer_to:STAGE.cur.answer_to,seq:(STAGE.scenes[STAGE.at]||{}).seq||1}:null;
    // asked in the Stage's chat from inside a part: the new story is that part gone deeper (stage._asked_inside)
    const la=typeof STAGE_CHAT!=='undefined'&&STAGE_CHAT.cid===ev.conversation_id&&STAGE_CHAT.lastAt;
    if(!was&&la&&la.path.length&&la.answer_to!==(ev.answer_to||''))was={answer_to:la.answer_to,seq:la.seq,path:la.path,scene:la.scene};
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
/* A blueprint filling itself in (bpfill.py): the part that landed is redrawn where you are. */
function stageFill(ev){
  const hit=(STAGE.scenes||[]).find(s=>s.id===ev.id);
  if(!hit)return;
  const old=hit.scene;hit.scene=ev.scene;
  document.querySelectorAll('.bp-art').forEach(art=>{if(art._bp&&art._bp.sc===old)bpRefill(art._bp,ev.scene)});
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
  table:'Table',image:'Picture',video:'Video',film:'Film',blueprint:'Blueprint'};
var STAGE_HUE={chart:255,map:200,numbers:280,timeline:170,steps:320,table:225,image:30,video:350,film:265,blueprint:205};
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
  // on a phone the label is one word, so the whole bar fits one row
  sw.append(cb,sEl('span','stg-long','Answer BIG'),sEl('span','stg-short','BIG'));
  sw.title='On: answers with numbers, places or a story are shown here without being asked. Off: only when you ask to see something.';
  top.append(sw);
  const mu=sEl('button','st-icon'+(stageMusicOn()?' on':''),'♪');mu.append(sEl('span','stg-long',stageMusicOn()?' On':' Off'));
  mu.title='Background music, made on this screen. Tap to play or pause.';mu.setAttribute('aria-label','Background music');mu.setAttribute('aria-pressed',String(stageMusicOn()));
  mu.onclick=()=>{stageMusic(!stageMusicOn());stagePaint()};
  top.append(mu);
  // offered only where the browser can do it: an iPhone has no full screen for a page, and a
  // button that does nothing there reads as the Stage being broken
  if(document.fullscreenEnabled){
    const fs=sEl('button','st-icon','⛶');fs.title='Full screen';fs.setAttribute('aria-label','Full screen');
    fs.onclick=()=>{const t=body.closest('.win')||body;try{document.fullscreenElement?document.exitFullscreen():t.requestFullscreen()}catch(e){}};
    top.append(fs);
  }
  // the story's chat on the right (24w-stagechat.js), to ask more about what is on screen
  const talk=STAGE.tab==='now'&&STAGE.cur&&STAGE.cur.cid&&typeof stageChatPanel==='function';
  if(talk){
    const on=stageChatWanted();
    const cb=sEl('button','st-icon st-chat-b'+(on?' on':''),'✦');cb.append(sEl('span','stg-long',' Chat'));
    cb.title=on?'Hide the chat':'Chat about this story';cb.setAttribute('aria-pressed',String(on));
    cb.onclick=()=>stageChatSet(!on,true);top.append(cb);
  }
  body.append(top);
  const w=WM.wins.get('stage');if(w&&typeof stageChatButton==='function')stageChatButton(w);
  const main=sEl('div','st-main'+(STAGE.tab==='now'?' now':''));body.append(main);
  if(STAGE.tab==='library')stageLibrary(main);
  else if(STAGE.tab==='boards')stageBoards(main);
  else{
    stageNow(main);
    const p=talk&&stageChatWanted()?stageChatPanel():null;
    if(p){main.classList.add('with-chat');main.append(p)}
  }
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
    const pa=STAGE.cur.parent;
    // back up the tree: the parent blueprint opens at the part this went deeper on (24w-stagechat.js)
    if((pa.path||[]).length){up.textContent='↖ Back up to the part this came from'}
    up.onclick=()=>{if(typeof STAGE_CHAT!=='undefined'&&(pa.path||[]).length)STAGE_CHAT.want={scene:pa.scene,path:pa.path,until:Date.now()+5000};
      stageOpen(STAGE.cur.cid,pa.answer_to,(pa.seq||1)-1)};
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
  box.append(sEl('div','stg-kicker',`${STAGE.at+1} of ${n} · ${sc.kind==='steps'&&sc.ordered===false?'List':STAGE_KIND[sc.kind]||sc.kind}`));
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
  if(!STAGE.cur.xray){
    const deep=sEl('button','stg-b stg-deep','⤵ ');deep.append(sEl('span','stg-long','Go deeper'),sEl('span','stg-short','Deeper'));
    deep.title='Ask for this scene as its own story';
    deep.onclick=()=>stageDeeper(cur.seq);bar.append(deep);
  }else{
    // an X-ray is read from the records, so it can be read again while a run is still going
    const re=sEl('button','stg-b','↻ ');re.append(sEl('span','stg-long','Read again'));re.title='Read the records again';
    re.onclick=()=>stageXray(STAGE.cur.xray,STAGE.cur.question);bar.append(re);
    if(STAGE.cur.xray.conversation||STAGE.cur.xray.run){const j=document.createElement('a');j.className='stg-b';
      j.textContent='⤓ JSON';j.title='Everything it did, as one file to read or hand to an AI';j.setAttribute('download','');
      j.href=STAGE.cur.xray.run?'/api/trace/run/'+encodeURIComponent(STAGE.cur.xray.run)
        :'/api/trace/conversation/'+encodeURIComponent(STAGE.cur.xray.conversation);bar.append(j)}
  }
  const kids=(STAGE.cur.deeper||{})[String(cur.seq)]||[];
  kids.forEach((a,i)=>{const k=sEl('button','stg-b stg-kid',kids.length>1?`Deeper story ${i+1} ›`:'The deeper story ›');
    k.onclick=()=>stageOpen(STAGE.cur.cid,a,0);bar.append(k)});
  const sp=sEl('span','stg-sp');bar.append(sp);
  if(!STAGE.cur.xray){const keep=sEl('button','stg-b','★');keep.append(sEl('span','stg-long',' Keep'));
    keep.title='Keep this story as a board, and refresh it if you like';keep.setAttribute('aria-label','Keep');
    keep.onclick=()=>stageKeepMenu(keep);bar.append(keep)}
  if(STAGE.cur.cid){const chat=sEl('button','stg-b','Chat');chat.title='Open the conversation';
    chat.onclick=()=>{if(typeof openConv==='function'){openApp('chat');openConv(STAGE.cur.cid)}};
    bar.append(chat)}
  th.append(bar);
  if(STAGE.awaiting)th.append(stageWaiting());
  stageMusicMood(sc.kind);
}
/* Every story a chat showed, outside the deeper ones, is a version of its Stage: asking
   "add Japan to the map" in the chat shows the story again with the change, and the one
   before stays one tap away. Asked for as "update the stage or add a new face to the same
   stage with the previous one there as well, like a new version". */
async function stageVersions(c){
  if(c.xray)return;
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
  STAGE.cur={cid,answer_to:answer_to||'',question:'',parent:d.parent||null,deeper:d.deeper||{},branches:d.branches||[],versions:[]};
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
    const hold=sc.kind==='video'?20000:sc.kind==='film'?stageFilmSeconds(sc)*1000:sc.kind==='blueprint'?bpTourMs(sc):0;
    if(typeof VOICE!=='undefined'&&VOICE.tts&&typeof speakAs==='function'&&line)speakAs(agentName(),line,()=>setTimeout(after,hold));
    else setTimeout(after,Math.max(4500,line.length*60)+hold);
  };
  step();
}
/* Go deeper: the scene becomes a question in its own chat, sent as the person's message,
   and the story that answers it plays here next with a way back up. */
async function stageDeeper(seq,part){
  const c=STAGE.cur;if(!c||c.xray)return;
  let d;
  try{const r=await fetch('/api/stage/deeper',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({conversation_id:c.cid,answer_to:c.answer_to,seq,part:part||''})});
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
    image:stageImage,video:stageVideo,film:stageFilm,blueprint:stageBlueprint}[sc.kind]||(()=>{}))(art,sc);
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
/* A move is read by its sign: when a set of values has both, a rise says "+" as a fall says "-". */
function stageSigned(vals){const v=(vals||[]).filter(x=>x!=null&&isFinite(x));return v.some(x=>x>0)&&v.some(x=>x<0)}
function stageFmtS(n,unit,signed){const s=stageFmt(n,unit);return signed&&n>0?'+'+s:s}
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
  // A name whose one word cannot fit its slot is drawn at an angle instead: cut, "Nasdaq"
  // became "Nasda q" (found with a market's ten indexes on a phone).
  const slotW=(W-72-R)/Math.max(1,cats.length)-6;
  const tilt=cats.length>0&&cats.some(c=>String(c).split(/\s+/).some(w=>w.length*7.2*K>slotW));
  const twoLines=!tilt&&cats.length>0&&cats.some(c=>String(c).length*7.2*K>slotW);
  if(twoLines)B+=Math.round(16*K);
  if(tilt)B+=Math.round(Math.min(18,Math.max(...cats.map(c=>String(c).length)))*7.2*K*0.62+8*K);
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
    if(tilt){const s=String(label),ln=s.length>18?s.slice(0,17)+'…':s,ty=H-B+16*K;
      g.append(sSvg('text',{x:X(v),y:ty,'text-anchor':'end',transform:`rotate(-35 ${X(v)} ${ty})`},ln));return}
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
  const signed=stageSigned(all.map(p=>p[1]));
  // one series that rises and falls (a market's day): rises green, falls red, as the map
  const tones=bar&&signed&&n===1;
  const gid=stageDefs(svg,series.map((_,si)=>STAGE_PAL[si%STAGE_PAL.length]).concat([STAGE_DOWN,STAGE_UP]));
  // one size for every value on the bars, the size the tightest one needs
  const barSlot=bar?(W-L-R)/((x1-x0)||1)*0.95/n:0;
  const valFs=bar?Math.min(...all.map(p=>{const need=stageFmtS(p[1],tu,signed).length*7.2*K;return need<=barSlot?1:need*0.75<=barSlot?0.75:0})):1;
  series.forEach((s,si)=>{
    const col=STAGE_PAL[si%STAGE_PAL.length];
    const pts=s.points.map(p=>[xv(p[0]),p[1]]).sort((a,b)=>a[0]-b[0]);
    if(bar){
      const slot=(W-L-R)/((x1-x0)||1),bw=Math.max(2,slot*0.7/n);
      pts.forEach((p,i)=>{const x=X(p[0])-slot*0.35+si*bw,y=Y(Math.max(0,p[1])),h=Math.abs(Y(p[1])-Y(0));
        const tone=tones?(p[1]<0?n:p[1]>0?n+1:si):si;
        const r=sSvg('rect',{x,y,width:bw-2,height:Math.max(1,h),rx:Math.min(8,(bw-2)/4),fill:`url(#${gid}-b${tone})`,class:'st-bar',style:`animation-delay:${i*40}ms`});
        r.append(sSvg('title',{},`${s.name?s.name+': ':''}${stageFmt(p[1],sc.unit)}`));svg.append(r);
        // the value over its bar only when it fits the bar's slot
        // every value is shown, smaller when its slot is tight, and a fall's under its bar
        const vt=stageFmtS(p[1],tu,signed),fs=valFs;
        if(fs){const vy=p[1]<0?Y(p[1])+15*K*fs:y-6*K;
          const t=sSvg('text',{x:x+(bw-2)/2,y:vy,'text-anchor':'middle',class:'st-val'},vt);
          if(fs<1)t.style.fontSize=`calc(${13*fs}px * var(--k,1))`;svg.append(t)}});
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
  // a rising-and-falling single series is coloured by sign, so one swatch would mislead
  if(n>1||series[0]&&series[0].name&&!tones){
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
  // the world first: awaiting it lets the scene finish laying out (the controls bar is added
  // after this returns), so the room measured below is the room the map really gets
  let world;
  try{world=await stageWorld()}catch(e){art.textContent='';art.append(sEl('p','mut',String(e.message||e)));return}
  // The drawing takes the shape of the room it really gets: the places' notes go in first and
  // the map has what they leave. A fixed 960x500 left the world a thin strip on a phone held
  // upright, and sized before the notes it came out a quarter of its box.
  let ol=null;const notes=(sc.points||[]).filter(p=>p.note);
  const nsigned=stageSigned((sc.points||[]).map(p=>p.value));
  if(notes.length){ol=sEl('ol','st-mapnotes');
    notes.forEach((p,i)=>{const li=sEl('li','');li.style.animationDelay=(600+i*160)+'ms';
      li.append(sEl('b','',(i+1)+' · '+(p.label||'')+(p.value!=null?' '+stageFmtS(p.value,sc.unit,nsigned):'')),sEl('span','',p.note));
      if(nsigned&&p.value)li.classList.add(p.value<0?'down':'up');ol.append(li)});
    art.append(ol)}
  const W=960,fw=art.clientWidth,fh=art.clientHeight-(ol?ol.offsetHeight+10:0);
  const H=fw>40&&fh>40?Math.round(Math.min(1400,Math.max(320,W*fh/fw))):500;
  const svg=sSvg('svg',{viewBox:`0 0 ${W} ${H}`,class:'st-svg st-mapsvg',role:'img','aria-label':sc.title||'map'});
  art.insertBefore(svg,ol);const K=stageK(svg,W,H);svg.style.setProperty('--k',K);
  // the box: the view named, else the places and countries shown, padded, else the world
  let box=STAGE_VIEW[sc.view]||null;
  const hits=(sc.regions||[]).map(r=>({r,c:world.idx[String(r.country).toLowerCase()]}));
  const lons=[],lats=[];
  (sc.points||[]).forEach(p=>{lons.push(p.lon);lats.push(p.lat)});
  hits.forEach(h=>{if(h.c)h.c.r.forEach(ring=>{for(let i=0;i<ring.length;i+=2){lons.push(ring[i]/10);lats.push(ring[i+1]/10)}})});
  if(!box){
    if(lons.length){
      let a=Math.min(...lons),b=Math.max(...lons),c=Math.min(...lats),d=Math.max(...lats);
      const pw=Math.max(12,(b-a)*0.15),ph=Math.max(8,(d-c)*0.15);
      box=[Math.max(-180,a-pw),Math.max(-60,c-ph),Math.min(180,b+pw),Math.min(85,d+ph)];
      if(box[2]-box[0]>230)box=STAGE_VIEW.world;
    }else box=STAGE_VIEW.world;
  }
  let [lo0,la0,lo1,la1]=box;const aspect=W/H;
  // an upright frame cannot show every longitude at a size anybody can read, so it keeps
  // the longitudes the places are in (never wider than the view asked for)
  if(aspect<1.6&&lons.length){
    const pw=Math.max(12,(Math.max(...lons)-Math.min(...lons))*0.12);
    const a=Math.max(lo0,Math.min(...lons)-pw),b=Math.min(lo1,Math.max(...lons)+pw);
    if(b-a>=20){lo0=a;lo1=b}
  }
  // keep the shape: widen the shorter side to the frame's aspect
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
  const pv0=pts.map(p=>p.value).filter(v=>v!=null),signed=stageSigned(pv0);
  // with rises and falls, a pin is as big as the move: by raw value the biggest fall was the
  // smallest pin on the map
  const mag=v=>signed?Math.abs(v):v;
  const pv=pv0.map(mag),pmin=Math.min(...pv),pmax=Math.max(...pv);
  const taken=[];
  // every pin's dot is kept clear of labels, so a label never hides a place
  pts.forEach(p=>{const x=X(p.lon),y=Y(p.lat);taken.push([x-9,y-9,x+9,y+9])});
  const order=pts.map((p,i)=>[p,i]).sort((a,b)=>mag(b[0].value||0)-mag(a[0].value||0));
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
    const t=p.value!=null&&pv.length>1?(mag(p.value)-pmin)/((pmax-pmin)||1):0.5;
    const tone=signed&&p.value!=null?(p.value<0?' down':p.value>0?' up':''):'';
    const r=6+t*10,delay=Math.min(rank,30)*120;
    const g=sSvg('g',{class:'st-pin',style:`animation-delay:${delay}ms`});
    g.append(sSvg('circle',{cx:x,cy:y,r:r*1.9,class:'st-pulse'+tone}),sSvg('circle',{cx:x,cy:y,r,class:'st-pt'+tone,filter:`url(#${mid}-glow)`}));
    g.append(sSvg('title',{},(p.label||'')+(p.value!=null?': '+stageFmtS(p.value,sc.unit,signed):'')+(p.note?' · '+p.note:'')));
    // a place with a note is numbered, and its note is listed under the map: a picture has
    // no hover, and the note is what happened there
    const n=noted.indexOf(p);
    if(n>=0)g.append(sSvg('text',{x,y:y+4*K,'text-anchor':'middle',class:'st-pinno'},String(n+1)));
    svg.append(g);
    // the full name, then its first part ("Furnace Creek"), placed where it touches no
    // other label: right, left, above, below. A place with no room keeps its dot and title.
    const val=p.value!=null?' '+stageFmtS(p.value,sc.unit,signed):'';
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
    const c=stageCard(it.open,'st-num');c.style.animationDelay=(i*120)+'ms';
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
  const list=sc.ordered===false;   // things waiting, not a sequence: no numbers, no arrows
  const s=sEl('div','st-steps'+(list?' list':'')+(sc.items.length>4?' tall':''));
  sc.items.forEach((it,i)=>{
    if(i&&!list){const a=sEl('div','st-arrow','→');a.style.animationDelay=(i*260-130)+'ms';s.append(a)}
    const c=stageCard(it.open,'st-step');c.style.animationDelay=(i*260)+'ms';
    if(!list)c.append(sEl('div','st-step-n',String(i+1)));
    c.append(sEl('div','st-step-t',it.title));
    if(it.text)c.append(sEl('div','st-step-x',it.text));
    if(it.note)c.append(sEl('div','st-step-m',it.note));
    s.append(c)});
  art.append(s);
}
/* A card with a door (stage._OPEN: a Brief item or group) is a button that opens it; on
   the Telegram page, where there is no desktop to open, it stays a card. */
function stageCard(open,cls){
  if(!open||typeof openApp!=='function')return sEl('div',cls);
  const b=sEl('button',cls+' st-go');b.type='button';b.title='Open it in the Brief';
  b.onclick=()=>stageOpenRef(open);return b;
}
async function stageOpenRef(ref){
  const m=/^brief:(.+)$/.exec(ref||'');if(!m)return;
  if(typeof STAGE!=='undefined'&&STAGE.playing){STAGE.playing=false;if(typeof speechStop==='function')speechStop();stagePaintIfOpen()}
  openApp('brief');
  // the Brief paints after a fetch: wait for it, then show the item or the group
  for(let n=0;n<40;n++){
    const app=document.querySelector('.br-app');
    if(app){
      if(/^(needs_you|decide|fyi|done)$/.test(m[1])){if(typeof briefJump==='function')briefJump(m[1]);return}
      let el=[...app.querySelectorAll('.br-item')].find(x=>x.dataset.id===m[1]);
      // a phone shows one item at a time: turn the stack to this one
      const live=((typeof BRIEF==='object'&&BRIEF&&BRIEF.page&&BRIEF.page.items)||[])
        .filter(i=>i.state==='open'||i.state==='later'||i.state==='decided');
      const at=live.findIndex(i=>i.id===m[1]);
      if(!el&&at>=0&&app.querySelector('.br-stack')){BRIEF.i=at;await renderBrief(app.parentElement);
        el=document.querySelector('.br-app .br-item[data-id="'+m[1]+'"]')}
      if(el){el.scrollIntoView({behavior:'smooth',block:'center'});el.classList.add('br-flash');
        setTimeout(()=>el.classList.remove('br-flash'),2400)}
      else toast('That one is already handled.');
      return}
    await new Promise(r=>setTimeout(r,100))}
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

/* ================= the Stage's blueprint: a thing taken apart, level by level =================
   stage.py's `blueprint` kind is the closed set; this draws it. Asked for as "give me a fine
   blueprint of Burj Khalifa … it opens the building inside out and I can drill into anything",
   and as a Jarvis-style look that gets to the bottom of things rather than presenting a chart.
   The X-ray (agentos/xray.py) is the same scene built from this machine's own records.

   Five rules:
   - Every word is text (textContent, SVG text nodes), the Stage's rule: a part's words are a
     model's, often copied off a page.
   - The parts nest, so drilling is drawn here at once with no model call. Past the last level,
     "Take this apart" asks the agent (stageDeeper with the part's id), and the answer plays
     next on the Stage with the way back.
   - A state is never colour alone: each status is an icon AND a word, and certainty is the
     line itself (solid known, dashed estimated, dotted unclear), with a legend.
   - Sized from the drawing's LAYOUT box (clientWidth), never getBoundingClientRect: a window
     opening under a scale transform made the remote page 320x240 once. A ResizeObserver
     redraws it, and is dropped when the drawing leaves the page.
   - Nothing moves forever: the parts draw in once, the scan line crosses once, the tour (while
     the story plays) stops at the first touch. Reduced motion draws it still.

   Three faces: the GUI is this file; the TUI and the terminal chat print a blueprint as an
   indented tree (stage.text) and `bento stage xray` prints an X-ray the same way; in SUI it is a
   page like any other, and nothing here touches the compositor.

   Loaded after 24l-stage.js, whose sEl/sSvg/stageTicks/stageReduced it uses; function
   declarations hoist across the bundle, and the Telegram page embeds both files. */

var BP_INK='#7dd3fc', BP_HI='#f8fafc', BP_DIM='rgba(125,211,252,.42)';
var BP_STATUS={ok:['✓','done','#34d399'],refused:['✕','refused','#f87171'],asked:['?','asked you','#fbbf24'],
  waiting:['⏸','waiting','#fbbf24'],failed:['⚠','failed','#f87171'],stopped:['■','stopped','#94a3b8'],
  running:['●','running','#7dd3fc']};
var BP_DASH={known:'',estimated:'7 5',unclear:'1.5 4.5'};
var BP_CERT_WORD={known:'known',estimated:'estimated',unclear:'unclear'};

function bpKids(n){return (n&&n.parts)||[]}
function bpNode(st){   // the level on screen: the subject, or the part at the end of the path
  let n={name:st.sc.subject||st.sc.title,parts:st.sc.parts,form:st.sc.form,role:'',root:true,facts:st.sc.facts||[]};
  for(const id of st.path){const k=bpKids(n).find(p=>p.id===id);if(!k)break;n=k}
  return n;
}
function bpFind(parts,id){for(const p of parts||[]){if(p.id===id)return p;const k=bpFind(p.parts,id);if(k)return k}return null}
function bpCount(parts){return (parts||[]).reduce((t,p)=>t+1+bpCount(p.parts),0)}
function bpDepth(parts){return (parts||[]).reduce((d,p)=>Math.max(d,1+bpDepth(p.parts)),0)}
function bpVal(f){const v=String(f.value==null?'':f.value),u=String(f.unit||'');
  if(!u||v.indexOf(u)>=0)return v;return /^[A-Za-z]/.test(u)?v+' '+u:v+u}
function bpFmt(n){if(n==null||!isFinite(n))return '';const a=Math.abs(n);
  return a>=1000?Math.round(n).toLocaleString():a>=10?String(Math.round(n)):String(Math.round(n*10)/10)}
/* a part that names a thing and says almost nothing about it (stage.bp_thin) */
function bpThin(p){return (p.facts||[]).length<2&&!p.how&&!p.detail}
/* the parts bpfill.py is filling in right now; a server stopped mid-fill leaves `until` behind */
function bpFillingIds(sc){const f=sc&&sc.filling;return f&&Date.now()/1000<(f.until||0)?(f.ids||[]):[]}
function bpIsFilling(st,p){return bpFillingIds(st.sc).indexOf(p.id)>=0}
function bpFailed(st,p){return ((st.sc.fill&&st.sc.fill.failed)||[]).find(f=>f.id===p.id)}
/* what to call the parts inside, in a line: "Mast, Antenna and 4 more" */
function bpInside(p,max){const k=bpKids(p).map(x=>x.name);if(!k.length)return '';
  max=max||4;return k.length<=max?k.join(' · '):k.slice(0,max).join(' · ')+' +'+(k.length-max)}
function bpHover(){try{return matchMedia('(hover:hover)').matches}catch(e){return false}}

/* ---------- the scene ---------- */
function stageBlueprint(art,sc){
  art.classList.add('bp-art');
  const st={sc,path:[],sel:null,peek:null,tour:null,art,
    live:!window.STAGE_REPORT&&typeof STAGE!=='undefined'&&STAGE.cur&&!STAGE.cur.xray,
    seq:(typeof STAGE!=='undefined'&&STAGE.scenes&&STAGE.scenes[STAGE.at]&&STAGE.scenes[STAGE.at].scene===sc)?STAGE.scenes[STAGE.at].seq:0};
  st.sid=st.seq?STAGE.scenes[STAGE.at].id:'';
  // a phone's album opens it for the person: one view per picture (stage.still_views)
  // a repaint of the Stage (the chat shown or hidden, the question loading) keeps your place
  const kept=st.sid&&!sc._view&&BP_KEEP[st.sid];
  if(kept){let n={parts:sc.parts};const ok=[];
    for(const id of kept.path){const k=bpKids(n).find(p=>p.id===id);if(!k||!bpKids(k).length)break;ok.push(id);n=k}
    st.path=ok;st.mode=kept.mode}
  // back up the tree from a deeper story: open at the part it went deeper on
  // (kept a few seconds, not used up: the Stage paints again when the story's question loads)
  if(typeof STAGE_CHAT!=='undefined'&&STAGE_CHAT.want&&STAGE_CHAT.want.scene===st.sid&&Date.now()<(STAGE_CHAT.want.until||0)){
    let n={parts:sc.parts};const ok=[];
    for(const id of STAGE_CHAT.want.path){const k=bpKids(n).find(p=>p.id===id);if(!k)break;ok.push(id);n=k}
    st.path=bpKids(n).length?ok:ok.slice(0,-1)}
  if(sc._view){art.classList.add('bp-v-'+sc._view.mode);st.mode=sc._view.mode;st.path=(sc._view.path||[]).filter(id=>(sc.parts||[]).some(p=>p.id===id))}
  art._bp=st;
  const wrap=sEl('div','bp');
  const crumbs=sEl('div','bp-crumbs');
  const body=sEl('div','bp-body');
  const draw=sEl('div','bp-draw');
  const svg=sSvg('svg',{class:'bp-svg',role:'group','aria-label':'Blueprint of '+(sc.subject||sc.title||'it')});
  draw.append(svg);
  const spec=sEl('aside','bp-spec');spec.setAttribute('aria-live','polite');
  const loc=sEl('div','bp-loc');loc.setAttribute('aria-hidden','true');
  body.append(draw,spec);wrap.append(crumbs,body);art.append(wrap);
  const info=sEl('div','bp-info');
  // a phone reads the part under its finger here, over the drawing; the panel is below it
  const peek=sEl('div','bp-peek');peek.hidden=true;draw.append(peek);
  st.el={wrap,crumbs,draw,svg,loc,spec,info,peek};
  art.tabIndex=-1;
  art.addEventListener('keydown',e=>bpKey(st,e));
  if(typeof ResizeObserver!=='undefined'){
    let last='';st.ro=new ResizeObserver(()=>{
      if(!art.isConnected){st.ro.disconnect();return}
      const k=draw.clientWidth+'x'+draw.clientHeight;if(k!==last){last=k;bpRender(st,'')}});
    st.ro.observe(draw);
  }
  bpRender(st,'in');
  if(typeof STAGE!=='undefined'&&STAGE.playing&&!window.STAGE_REPORT)bpTour(st);
}

/* bpfill.py landed a part: the same place, the new words */
function bpRefill(st,sc){
  st.sc=sc;
  let n={parts:sc.parts},ok=[];
  for(const id of st.path){const k=bpKids(n).find(p=>p.id===id);if(!k)break;ok.push(id);n=k}
  st.path=ok;
  if(st.sel&&!bpKids(bpNode(st)).some(k=>k.id===st.sel))st.sel=null;
  st.peek=null;bpRender(st,'');
}
function bpNarrow(st){return st.art.clientWidth<700}
function bpRender(st,how){
  const {svg,draw}=st.el;
  // a narrow Stage scrolls: the drawing takes the room you can see, the panel waits below
  const lvl=st.path.join('/');if(st.wantFor!==lvl){st.wantFor=lvl;st.wantH=0}
  if(bpNarrow(st)&&!window.STAGE_REPORT){
    const h=Math.max(300,st.art.clientHeight-st.el.crumbs.offsetHeight-12,st.wantH||0);
    if(Math.abs((parseFloat(draw.style.height)||0)-h)>2)draw.style.height=h+'px';
  }else if(draw.style.height)draw.style.height='';
  const W=Math.max(280,draw.clientWidth||900),H=Math.max(260,draw.clientHeight||520);
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width',W);svg.setAttribute('height',H);
  svg.style.setProperty('--bp-h',H+'px');
  svg.textContent='';
  svg.classList.toggle('bp-still',stageReduced()||!!window.STAGE_STILL);
  svg.classList.remove('bp-in','bp-back');void svg.getBoundingClientRect();
  if(how&&!stageReduced())svg.classList.add('bp-'+how);
  bpGrid(svg,W,H);
  const node=bpNode(st),kids=bpKids(node);
  const world=sSvg('g',{class:'bp-world'});svg.append(world);
  const form=node.form||(node.root?st.sc.form:'')||'exploded';
  st.needH=0;
  const look=st.el.draw.querySelector('.bp-look');if(look)look.remove();
  svg.style.display='';
  if(st.mode==='look'){bpLook(st);st.items=[];st.form=form;bpCrumbs(st);bpSpec(st);bpMark(st);
    if(st.live&&typeof stageChatFollow==='function')stageChatFollow(st);
    if(st.sid)BP_KEEP[st.sid]={path:st.path.slice(),mode:'look'};return}
  const flows=st.mode==='flows'&&bpFlowEdges(st,kids).length;
  const L=flows?bpFlows(world,node,kids,W,H,st):(form==='tower'?bpTower:form==='flow'?bpFlow:bpExploded)(world,node,kids,W,H,st);
  if(st.needH>H+2&&bpNarrow(st)&&!st.grown){st.grown=true;st.wantH=st.needH;const r=bpRender(st,how);st.grown=false;return r}
  st.items=L;
  // links over the cards cut their words: How it works draws them, the panel lists them
  if(!stageReduced()&&!window.STAGE_STILL&&how){
    const scan=sSvg('rect',{class:'bp-scan',x:0,y:0,width:W,height:3});svg.append(scan)}
  st.form=form;
  bpCrumbs(st);
  bpSpec(st);
  bpMark(st);
  // the Stage's chat follows the tree: each level has its own thread (24w-stagechat.js)
  if(st.live&&typeof stageChatFollow==='function')stageChatFollow(st);
  if(st.sid)BP_KEEP[st.sid]={path:st.path.slice(),mode:st.mode||'parts'};
}
var BP_KEEP={};   // where you were in each blueprint, for a repaint of the Stage

/* ---------- the drafting sheet ---------- */
var BP_UID=0;
function bpGrid(svg,W,H){
  const id='bp'+(++BP_UID),d=sSvg('defs');
  const p1=sSvg('pattern',{id:id+'-g',width:16,height:16,patternUnits:'userSpaceOnUse'});
  p1.append(sSvg('path',{d:'M16 0H0V16',fill:'none',stroke:'rgba(125,211,252,.07)','stroke-width':1}));
  const p2=sSvg('pattern',{id:id+'-G',width:80,height:80,patternUnits:'userSpaceOnUse'});
  p2.append(sSvg('rect',{width:80,height:80,fill:'url(#'+id+'-g)'}),
    sSvg('path',{d:'M80 0H0V80',fill:'none',stroke:'rgba(125,211,252,.14)','stroke-width':1}));
  const hatch=sSvg('pattern',{id:id+'-h',width:8,height:8,patternUnits:'userSpaceOnUse',patternTransform:'rotate(45)'});
  hatch.append(sSvg('line',{x1:0,y1:0,x2:0,y2:8,stroke:'rgba(125,211,252,.28)','stroke-width':1.2}));
  const glow=sSvg('filter',{id:id+'-glow',x:'-30%',y:'-30%',width:'160%',height:'160%'});
  glow.append(sSvg('feGaussianBlur',{stdDeviation:'2.4',result:'b'}));
  const m=sSvg('feMerge');m.append(sSvg('feMergeNode',{in:'b'}),sSvg('feMergeNode',{in:'SourceGraphic'}));glow.append(m);
  const ah=sSvg('marker',{id:id+'-a',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});
  ah.append(sSvg('path',{d:'M0 1L10 5L0 9z',fill:BP_INK}));
  d.append(p1,p2,hatch,glow,ah);svg.append(d);
  svg.append(sSvg('rect',{class:'bp-sheet',x:0,y:0,width:W,height:H,fill:'url(#'+id+'-G)'}));
  // registration marks in the corners, as on a drawing
  [[10,10,1,1],[W-10,10,-1,1],[10,H-10,1,-1],[W-10,H-10,-1,-1]].forEach(([x,y,a,b])=>
    svg.append(sSvg('path',{d:`M${x} ${y+14*b}V${y}H${x+14*a}`,class:'bp-reg'})));
  svg.dataset.uid=id;
}
function bpId(svg,k){return 'url(#'+svg.dataset.uid+'-'+k+')'}
function bpSvgOf(g){return g.ownerSVGElement||g}

/* ---------- a part on the sheet ---------- */
function bpPartG(world,p,i,st){
  const g=sSvg('g',{class:'bp-p c-'+(p.certainty||'known')+(p.status?' s-'+p.status:''),tabindex:0,role:'button',
    'data-id':p.id,'aria-label':p.name+(p.role?': '+p.role:'')+(bpKids(p).length?'. '+bpKids(p).length+' parts inside':'')});
  g.style.setProperty('--i',i);
  g.addEventListener('click',e=>{e.stopPropagation();bpTap(st,p,e)});
  g.addEventListener('pointerenter',e=>{if(e.pointerType==='mouse'){st.peek=p.id;bpSpec(st);bpMark(st)}});
  g.addEventListener('pointerleave',e=>{if(e.pointerType==='mouse'&&st.peek===p.id){st.peek=null;bpSpec(st);bpMark(st)}});
  g.addEventListener('focus',()=>{st.peek=p.id;bpSpec(st);bpMark(st)});
  g.addEventListener('blur',()=>{if(st.peek===p.id){st.peek=null;bpSpec(st);bpMark(st)}});
  world.append(g);return g;
}
function bpShape(g,tag,attrs,p){
  const e=sSvg(tag,Object.assign({class:'bp-edge'},attrs));
  const d=BP_DASH[p.certainty||'known'];if(d)e.setAttribute('stroke-dasharray',d);
  g.append(e);return e;
}
function bpBadge(g,p,x,y){
  if(!p.status||!BP_STATUS[p.status])return;
  const [ic,,col]=BP_STATUS[p.status];
  const b=sSvg('g',{class:'bp-badge'});
  b.append(sSvg('circle',{cx:x,cy:y,r:8,fill:'#061a33',stroke:col,'stroke-width':1.4}),
    sSvg('text',{x,y:y+3.6,'text-anchor':'middle',fill:col,'font-size':10,'font-weight':700},ic));
  g.append(b);
}
/* one line of text that fits `w` px, cut at a word */
function bpText(parent,x,y,str,w,cls,anchor){
  const t=sSvg('text',{x,y,class:cls||'','text-anchor':anchor||'start'},str);parent.append(t);
  if(w&&t.getComputedTextLength&&t.getComputedTextLength()>w){
    let s=String(str);while(s.length>3&&t.getComputedTextLength()>w){s=s.replace(/\s*\S+$/,'');if(!/\s/.test(s)){s=s.slice(0,-2)}t.textContent=s+'…'}
  }
  return t;
}
/* up to `lines` lines that fit `w` px, words kept whole, the last cut with an ellipsis */
function bpWrap(parent,x,y,str,w,lines,cls,lh,anchor){
  const words=String(str||'').split(/\s+/).filter(Boolean);let line='',n=0,i=0;lh=lh||14;
  while(i<words.length&&n<lines){
    const t=sSvg('text',{x,y:y+n*lh,class:cls||'','text-anchor':anchor||'start'},'');parent.append(t);line='';
    while(i<words.length){const nxt=line?line+' '+words[i]:words[i];t.textContent=nxt;
      if(t.getComputedTextLength&&t.getComputedTextLength()>w){
        if(line){t.textContent=line;break}
        // one word wider than the line (a path, a URL): keep its end, which is the part that names it
        let wd=words[i];while(wd.length>4&&t.getComputedTextLength()>w){wd=wd.slice(2);t.textContent='…'+wd}
        line=t.textContent;i++;break}
      line=nxt;i++}
    if(n===lines-1&&i<words.length){bpText(parent,x,y+n*lh,t.textContent+' '+words.slice(i).join(' '),w,cls,anchor);t.remove()}
    n++;
  }
  return n;
}
function bpSub(p){   // the second line under a part's name: its first two facts, else its role
  const fs=(p.facts||[]).filter(f=>f.value!==''&&f.value!=null).slice(0,2);
  return fs.length?fs.map(f=>(f.label?f.label+' ':'')+bpVal(f)).join(' · '):(p.role||'')}

/* ---------- tower: built in layers along a height, bottom first ---------- */
function bpTower(world,node,kids,W,H,st){
  const out=[],unit=node.root?(st.sc.unit||''):(st.sc.unit||'');
  const have=kids.every(p=>p.from!=null&&p.to!=null);
  const spans=kids.map((p,i)=>have?[p.from,p.to]:[i,i+1]);
  let lo=Math.min(0,...spans.map(s=>s[0])),hi=Math.max(...spans.map(s=>s[1]));if(hi<=lo)hi=lo+1;
  // a part that runs most of the height beside others is inside the tower (a core, a lift
  // shaft): drawn as a shaft, not stacked as a floor
  const range=hi-lo;
  const shaft=kids.map((p,i)=>have&&(spans[i][1]-spans[i][0])>=range*.55&&
    spans.some((s,j)=>j!==i&&s[0]<spans[i][1]&&s[1]>spans[i][0]));
  const narrow=W<560,two=!narrow&&kids.length>7;
  const top=30,bot=narrow?34:44,left=narrow?54:64;
  const cx=narrow?Math.max(left+56,W*.3):two?W*.5:W*.38;
  const plotH=H-top-bot,k=plotH/(hi-lo);
  // a width over 1 is the real width in the drawing's unit, drawn to the same scale as the
  // height: the Burj Khalifa comes out as slender as it is. 0 to 1 is a share of the widest.
  const real=kids.some(p=>p.width!=null&&p.width>1);
  const cap=narrow?W*.3:two?W*.2:W*.26;
  const maxW=real?Math.min(cap,Math.max(...kids.map(p=>(p.width||0)))*k):Math.min(cap,240,plotH*.62);
  const wScale=real?Math.min(k,cap/Math.max(1,...kids.map(p=>p.width||0))):0;
  const y=v=>top+(hi-v)*k;
  const svg=bpSvgOf(world);
  // ground and what is under it
  if(lo<0){
    const gy=y(0);
    world.append(sSvg('rect',{x:16,y:gy,width:W-32,height:Math.max(0,y(lo)-gy+10),fill:bpId(svg,'h'),class:'bp-earth'}));
    world.append(sSvg('line',{x1:16,y1:gy,x2:W-16,y2:gy,class:'bp-ground'}));
    // the axis marks 0 already; on a narrow sheet this word would sit on a label
    if(!narrow)bpText(world,W-20,gy-6,'ground · 0'+(unit?' '+unit:''),0,'bp-tiny','end');
  }else world.append(sSvg('line',{x1:16,y1:y(lo),x2:W-16,y2:y(lo),class:'bp-ground'}));
  // the height axis
  world.append(sSvg('line',{x1:left-14,y1:y(hi),x2:left-14,y2:y(lo),class:'bp-axis'}));
  (typeof stageTicks==='function'?stageTicks(lo,hi,narrow?4:6):[lo,hi]).forEach(t=>{
    const ty=y(t);world.append(sSvg('line',{x1:left-19,y1:ty,x2:left-9,y2:ty,class:'bp-axis'}));
    bpText(world,left-22,ty+3.5,(t>0?'+':'')+bpFmt(t),0,'bp-tiny','end')});
  if(unit)bpText(world,left-14,top-12,unit,0,'bp-tiny','middle');
  // the centreline, dash-dot, as on a drawing
  world.append(sSvg('line',{x1:cx,y1:y(hi)-10,x2:cx,y2:y(lo)+6,class:'bp-cl'}));
  const stacked=kids.map((p,i)=>i).filter(i=>!shaft[i]);
  const wOf=i=>{const p=kids[i];if(p.width!=null)return p.width;
    const j=stacked.indexOf(i),n=Math.max(1,stacked.length-1);return j<0?.08:.92-.7*(j/n)};
  const pxW=i=>real?(kids[i].width!=null?(kids[i].width>1?kids[i].width*wScale:kids[i].width*maxW):maxW*.5):maxW*wOf(i);
  // the outline of the whole, drawn once behind the parts with a glow: the silhouette
  const sil=stacked.map(i=>[spans[i][0],spans[i][1],Math.max(4,pxW(i))]).sort((a,b)=>a[0]-b[0]);
  if(sil.length>1){let r='',l='';sil.forEach(([a,b,w])=>{r+=`L${cx+w/2} ${y(a)}L${cx+w/2} ${y(b)}`;l=`L${cx-w/2} ${y(b)}L${cx-w/2} ${y(a)}`+l});
    world.append(sSvg('path',{d:'M'+cx+' '+y(sil[0][0])+r+'L'+cx+' '+y(sil[sil.length-1][1])+l+'Z',class:'bp-sil',filter:bpId(svg,'glow')}))}
  stacked.forEach((i,j)=>{
    const p=kids[i],[a,b]=spans[i];const w=Math.max(4,pxW(i));
    const y0=y(b),y1=y(a),h=Math.max(3,y1-y0);
    const g=bpPartG(world,p,j,st);
    g.append(sSvg('rect',{x:cx-Math.max(w,24)/2,y:y0-Math.max(0,(14-h)/2),width:Math.max(w,24),height:Math.max(h,14),class:'bp-hit'}));
    g.append(sSvg('rect',{x:cx-w/2,y:y0,width:w,height:h,class:'bp-fill'}));
    // floor lines inside a section
    if(h>14){const fl=sSvg('g',{class:'bp-floors'});const step=Math.max(5,Math.min(9,h/10));
      for(let fy=y0+step;fy<y1-2;fy+=step)fl.append(sSvg('line',{x1:cx-w/2+2,y1:fy,x2:cx+w/2-2,y2:fy}));g.append(fl)}
    bpShape(g,'rect',{x:cx-w/2,y:y0,width:w,height:h},p);
    if(bpKids(p).length&&h>16)g.append(sSvg('text',{x:cx,y:y0+h/2+4,'text-anchor':'middle',class:'bp-plus'},'⊕'));
    bpBadge(g,p,cx+w/2,y0);
    // an elevation mark at the top of each section
    world.append(sSvg('path',{d:`M${cx-w/2-9} ${y0-5}l4 5l4 -5z`,class:'bp-elev'}));
    // what is inside a section, where it sits: a line at each inner part's boundary
    const ks=bpKids(p).filter(c=>c.from!=null&&c.to!=null);
    if(ks.length>1&&h>20){const sub=sSvg('g',{class:'bp-subs'});
      ks.forEach(c=>[c.from,c.to].forEach(v=>{if(v>a&&v<b){const ly=y(v);sub.append(sSvg('line',{x1:cx-w/2,y1:ly,x2:cx+w/2,y2:ly}))}}));
      g.append(sub)}
    if(bpIsFilling(st,p))g.classList.add('bp-filling');
    out.push({p,g,st,box:[cx-w/2,y0,w,h],anchor:[cx+w/2,y0+h/2],left:[cx-w/2,y0+h/2]});
  });
  // a part as wide as the tower that runs its height wraps it (a facade, a skin): drawn as an
  // envelope round the outline, not as a line down the middle
  const widestW=Math.max(1,...stacked.map(i=>kids[i].width||0));
  const wraps=i=>shaft[i]&&kids[i].width!=null&&kids[i].width>=(real?widestW*.9:.9);
  kids.forEach((p,i)=>{if(!wraps(i))return;
    const [a,b]=spans[i],secs=sil.filter(([s0,s1])=>s1>a&&s0<b);if(!secs.length)return;
    const pad=6;let r='',l='';
    secs.forEach(([s0,s1,w])=>{const y0=y(Math.min(s1,b)),y1=y(Math.max(s0,a));r+=`L${cx+w/2+pad} ${y1}L${cx+w/2+pad} ${y0}`;l=`L${cx-w/2-pad} ${y0}L${cx-w/2-pad} ${y1}`+l});
    const g=bpPartG(world,p,stacked.length,st);g.classList.add('bp-wrap');
    const d='M'+cx+' '+y(Math.max(secs[0][0],a))+r+'L'+cx+' '+y(Math.min(secs[secs.length-1][1],b))+l+'Z';
    g.append(sSvg('path',{d,class:'bp-hitline'}));
    bpShape(g,'path',{d},p);
    const hy=y(Math.max(secs[0][0],a))-(y(Math.max(secs[0][0],a))-y(Math.min(secs[secs.length-1][1],b)))*.62;
    const hw=(secs.find(([s0,s1])=>y(s0)>=hy&&y(s1)<=hy)||secs[0])[2];
    out.push({p,g,st,box:[cx-hw/2-pad,hy-6,hw+pad*2,12],anchor:[cx+hw/2+pad,hy],left:[cx-hw/2-pad,hy]});
    shaft[i]=false;
  });
  // the shafts inside, side by side on the centreline
  const sh=kids.map((p,i)=>i).filter(i=>shaft[i]&&!wraps(i));
  sh.forEach((i,k)=>{
    const p=kids[i],[a,b]=spans[i],w=Math.max(4,Math.min(maxW*.12,10));
    const x=cx-(sh.length*w*1.6)/2+k*w*1.6+w*.3,y0=y(b),h=Math.max(3,y(a)-y0);
    const g=bpPartG(world,p,stacked.length+k,st);g.classList.add('bp-shaft');
    bpShape(g,'rect',{x,y:y0,width:w,height:h},p);
    g.append(sSvg('rect',{x:x-6,y:y0,width:w+12,height:h,class:'bp-hit'}));
    out.push({p,g,st,box:[x,y0,w,h],anchor:[x+w,y0+h*.3],left:[x,y0+h*.3]});
  });
  // the overall height, as a dimension line beside the tower
  const above=Math.max(...spans.map(s=>s[1]));
  const widest=Math.max(8,...stacked.map(pxW));
  if(!narrow){const dx=cx-widest/2-34;
    world.append(sSvg('line',{x1:dx,y1:y(above),x2:dx,y2:y(Math.max(0,lo)),class:'bp-dim',
      'marker-start':bpId(svg,'a'),'marker-end':bpId(svg,'a')}));
    const ty=(y(above)+y(Math.max(0,lo)))/2;
    const t=sSvg('text',{x:dx-6,y:ty,class:'bp-dimt','text-anchor':'middle',transform:`rotate(-90 ${dx-6} ${ty})`},
      bpFmt(above-Math.max(0,lo))+(unit?' '+unit:''));world.append(t)}
  bpLabels(world,out,W,H,top,bot,cx,widest,two,narrow);
  return out;
}
/* Leader lines to labels in a column, spread so no two touch, the shortest way. */
function bpLabels(world,items,W,H,top,bot,cx,maxW,two,narrow){
  const cols=two?[[],[]]:[[]];
  items.slice().sort((a,b)=>a.anchor[1]-b.anchor[1]).forEach((it,i)=>cols[two?(i%2):0].push(it));
  cols.forEach((col,c)=>{
    const right=c===0;
    const lx=right?cx+maxW/2+(narrow?22:44):cx-maxW/2-60;
    const tw=right?W-lx-14:lx-74;
    const lo=top+8,hi=H-bot-6,avail=hi-lo,n=col.length;
    // three lines a label while they fit (name, numbers, what is inside), then two, then one;
    // never on top of each other
    let gap=narrow?44:48,lines=3;
    if(n*gap>avail){gap=narrow?30:34;lines=2}
    if(n*gap>avail){gap=Math.max(15,Math.min(20,avail/Math.max(1,n)));lines=1}
    const one=lines===1;
    const yy=col.map(it=>it.anchor[1]);
    for(let k=0;k<n;k++)yy[k]=Math.max(yy[k],k?yy[k-1]+gap:lo);
    for(let k=n-1;k>=0;k--)yy[k]=Math.min(yy[k],k===n-1?hi:yy[k+1]-gap);
    if(n&&yy[0]<lo)for(let k=0;k<n;k++)yy[k]=lo+k*gap;
    col.forEach((it,k)=>{
      const [ax,ay]=right?it.anchor:it.left,ty=yy[k],ex=right?lx-6:lx+6;
      it.g.append(sSvg('path',{d:`M${ax} ${ay}H${(ax+ex)/2}L${ex} ${ty-4}`,class:'bp-lead'}));
      it.g.append(sSvg('circle',{cx:ax,cy:ay,r:2,class:'bp-dot'}));
      const lab=sSvg('g',{class:'bp-label'});it.g.append(lab);
      lab.append(sSvg('rect',{x:right?lx-4:lx-tw-4,y:ty-16,width:tw+8,height:one?gap:gap-2,class:'bp-hit'}));
      // a backing in the paper's colour: the ground line or a leader passing under a label
      // once read "Floors=Concourse=8"
      const bg=sSvg('rect',{class:'bp-lbg',rx:3});lab.append(bg);
      const ts=[bpText(lab,lx,ty,it.p.name,tw,'bp-name',right?'start':'end')];
      const sub=!one&&bpSub(it.p);if(sub)ts.push(bpText(lab,lx,ty+14,sub,tw,'bp-subt',right?'start':'end'));
      const fil=bpIsFilling(it.st||{sc:{}},it.p);
      const in3=lines===3&&(fil?'◌ filling in…':bpInside(it.p,4));
      if(in3)ts.push(bpText(lab,lx,ty+28,(fil?'':'⊂ ')+in3,tw,fil?'bp-insidet bp-fillt':'bp-insidet',right?'start':'end'));
      try{const ws=ts.map(t=>t.getComputedTextLength());const mw=Math.max(...ws);
        bg.setAttribute('x',right?lx-3:lx-mw-3);bg.setAttribute('y',ty-12);
        bg.setAttribute('width',mw+6);bg.setAttribute('height',14*ts.length+2)}catch(e){bg.remove()}
      it.label=[lx,ty];
    });
  });
}
/* ---------- exploded: a thing made of parts round a core ---------- */
function bpExploded(world,node,kids,W,H,st){
  const out=[],n=kids.length,narrow=W<560;
  const svg=bpSvgOf(world);
  if(narrow){   // a phone: the whole on top and the parts in two columns under it, scrolled
    const cols=n>3?2:1,cw=(W-36)/cols,bh=cols===2?150:128,cy=40;
    const core=sSvg('g',{class:'bp-core'});world.append(core);
    core.append(sSvg('rect',{x:18,y:cy-22,width:W-36,height:44,rx:22,class:'bp-hub'}));
    bpWrap(core,W/2,cy+5,node.name,W-70,1,'bp-corename',15,'middle');
    const y0=cy+48,rows=Math.ceil(n/cols);
    world.append(sSvg('line',{x1:W/2,y1:cy+22,x2:W/2,y2:y0+(rows-1)*(bh+14)+bh/2,class:'bp-ex'}));
    kids.forEach((p,i)=>{const c=i%cols,r=Math.floor(i/cols);
      const x=18+c*cw+(cols>1?4:0),y=y0+r*(bh+14),w=cw-(cols>1?8:0);
      if(cols>1)world.append(sSvg('line',{x1:W/2,y1:y+bh/2,x2:c?x:x+w,y2:y+bh/2,class:'bp-ex'}));
      out.push(bpBox(world,p,i,st,x,y,w,bh))});
    st.needH=y0+rows*(bh+14)+20;
    return out;
  }
  if(n<=4){   // a few big parts pulled out round the hub
    const bw=Math.min(300,W*.3),bh=Math.min(176,H*.4);
    const cx=W/2,cy=H/2-6,cr=Math.min(62,H*.12);
    const core=sSvg('g',{class:'bp-core'});world.append(core);
    core.append(sSvg('circle',{cx,cy,r:cr*1.9,class:'bp-ring'}),sSvg('circle',{cx,cy,r:cr*1.35,class:'bp-ring2'}),
      sSvg('circle',{cx,cy,r:cr,class:'bp-hub'}));
    const probe=sSvg('text',{class:'bp-corename'},node.name||'');core.append(probe);
    const two=probe.getComputedTextLength&&probe.getComputedTextLength()>cr*1.7;probe.remove();
    bpWrap(core,cx,cy+(two?-3:4),node.name,cr*1.7,two?2:1,'bp-corename',15,'middle');
    const rx=(W-bw)/2-18,ry=(H-bh)/2-14;
    kids.forEach((p,i)=>{
      const a=-Math.PI*3/4+i*Math.PI/2,px=cx+Math.cos(a)*rx,py=cy+Math.sin(a)*ry;
      const sx=cx+Math.cos(a)*cr*1.35,sy=cy+Math.sin(a)*cr*1.35;
      const ex=px+(px<cx?bw/2:-bw/2),ey=py+(py<cy?bh/2:-bh/2);
      world.append(sSvg('line',{x1:sx,y1:sy,x2:ex,y2:ey,class:'bp-ex','marker-end':bpId(svg,'a')}));
      out.push(bpBox(world,p,i,st,px-bw/2,py-bh/2,bw,bh))});
    return out;
  }
  // the whole, assembled, as a band across the middle; its parts pulled out above and below,
  // each on a dimension line from the place it fits. Two levels at once: every card shows
  // what is inside it, so the first screen is the thing taken apart, not a list of names.
  const per=Math.ceil(n/2),gap=14,pad=16;
  const bw=(W-pad*2-gap*(per-1))/per,band=40,lane=26;
  const bh=Math.max(96,Math.min(210,(H-pad*2-band-lane*2)/2));
  const by=pad+bh+lane,cx=W/2;
  const core=sSvg('g',{class:'bp-core'});world.append(core);
  core.append(sSvg('rect',{x:pad,y:by,width:W-pad*2,height:band,rx:band/2,class:'bp-hub'}));
  bpText(core,cx,by+band/2+5,node.name,W*.5,'bp-corename','middle');
  const rowOf=i=>i<per?0:1;
  kids.forEach((p,i)=>{
    const r=rowOf(i),c=r?i-per:i,inRow=r?n-per:per;
    const off=(per-inRow)*(bw+gap)/2;
    const x=pad+off+c*(bw+gap),y=r?by+band+lane:pad;
    const mx=x+bw/2,y1=r?by+band:by,y2=r?y:y+bh;
    world.append(sSvg('line',{x1:mx,y1,x2:mx,y2:r?y2-2:y2+2,class:'bp-ex','marker-end':bpId(svg,'a')}));
    world.append(sSvg('path',{d:`M${mx-4} ${y1}h8`,class:'bp-reg'}));
    out.push(bpBox(world,p,i,st,x,y,bw,bh));
  });
  return out;
}
function bpBox(world,p,i,st,x,y,w,h){
  const g=bpPartG(world,p,i,st);
  const filling=bpIsFilling(st,p),thin=!filling&&bpThin(p);
  if(filling)g.classList.add('bp-filling');
  if(thin)g.classList.add('bp-thinp');
  g.append(sSvg('rect',{x,y,width:w,height:h,rx:3,class:'bp-fill'}));
  bpShape(g,'rect',{x,y,width:w,height:h,rx:3},p);
  // corner ticks, as a drawing frames a detail
  [[x,y,1,1],[x+w,y,-1,1],[x,y+h,1,-1],[x+w,y+h,-1,-1]].forEach(([a,b,s,t])=>
    g.append(sSvg('path',{d:`M${a+7*s} ${b-3*t}H${a-3*s}V${b+7*t}`,class:'bp-tick'})));
  const iw=w-20,L=x+10,R=x+w-10;
  bpText(g,L,y+19,p.name,iw-(p.status?14:0),'bp-name');
  // a card is read top down: what it is for, its numbers, then what is inside it. The lines
  // the box has are shared out with numbers first, because a number is what a name lacks.
  const facts=(p.facts||[]).filter(f=>f.value!==''&&f.value!=null);
  const inside=bpInside(p,w>220?5:3);
  let lines=Math.max(0,Math.floor((h-22-36)/13.5)+1);
  const insN=inside&&lines>1?1:0;lines-=insN;
  const roleN=p.role?(lines>=6?2:lines>=1?1:0):0;lines-=roleN;
  const fN=Math.min(facts.length,w>200?5:3,lines);
  let cy=y+36;const foot=y+h-9;
  if(roleN)cy+=bpWrap(g,L,cy,p.role,iw,roleN,'bp-rolet',13)*13.5+2;
  facts.slice(0,fN).forEach(f=>{
    const v=bpText(g,R,cy,bpVal(f),iw*.5,'bp-fv','end');
    const vw=v.getComputedTextLength?v.getComputedTextLength():iw*.4;
    bpText(g,L,cy,f.label||'·',Math.max(20,iw-vw-10),'bp-fl');
    g.append(sSvg('line',{x1:L,y1:cy+4,x2:R,y2:cy+4,class:'bp-rule'}));
    cy+=13.5});
  // room left over goes to how it works, which is what a tall card was missing
  const left=lines-fN;
  if(p.how&&left>=2){cy+=3;cy+=bpWrap(g,L,cy,p.how,iw,Math.min(5,left),'bp-howt',13)*13}
  if(insN)bpText(g,L,cy+1,'⊂ '+inside,iw,'bp-insidet');
  const k=bpKids(p).length,deep=bpCount(p.parts);
  const ft=filling?'◌ filling in…':k?'⊕ '+k+' inside'+(deep>k?' · '+deep+' in all':''):thin?'· little known yet':(p.evidence?'⌖ record':'');
  bpText(g,L,foot,ft,iw,'bp-more'+(filling?' bp-fillt':thin?' bp-thint':''));
  bpBadge(g,p,x+w-12,y+12);
  return {p,g,box:[x,y,w,h],anchor:[x+w,y+h/2],left:[x,y+h/2]};
}
/* ---------- flow: a process, in order ---------- */
function bpFlow(world,node,kids,W,H,st){
  const out=[],n=kids.length;
  const few=n<=4;
  const gap=W<560?16:34,bw=W<560?W-56:Math.max(150,Math.min(few?270:240,(W-48-gap*(few?n-1:3))/(few?Math.max(n,3):4)));
  const rowsGuess=Math.ceil(n/Math.max(1,Math.floor((W-40+gap)/(bw+gap))));
  const bh=W<560?132:Math.max(96,Math.min(few?170:150,(H-60)/Math.max(1,rowsGuess)-44));
  const per=Math.max(1,Math.min(n,Math.floor((W-40+gap)/(bw+gap))));
  const rows=Math.ceil(n/per),rowH=bh+(per===1?20:44);
  const total=rows*rowH-(rowH-bh),y0=Math.max(46,(H-total)/2-6);
  st.needH=total+70;      // a narrow sheet scrolls, so a long flow asks for the height it needs
  const svg=bpSvgOf(world);
  const x0=(W-(per*bw+(per-1)*gap))/2;
  const pos=[];
  kids.forEach((p,i)=>{const r=Math.floor(i/per);let c=i%per;if(r%2)c=per-1-c;   // a snake: the next row comes back
    pos.push([x0+c*(bw+gap),y0+r*rowH])});
  kids.forEach((p,i)=>{if(!i)return;
    const [ax,ay]=pos[i-1],[bx,by]=pos[i];let d;
    if(ay===by){const fwd=bx>ax;d=fwd?`M${ax+bw} ${ay+bh/2}H${bx}`:`M${ax} ${ay+bh/2}H${bx+bw}`}
    else d=`M${ax+bw/2} ${ay+bh}V${by}`;
    world.append(sSvg('path',{d,class:'bp-flow','marker-end':bpId(svg,'a')}))});
  kids.forEach((p,i)=>out.push(bpBox(world,p,i,st,pos[i][0],pos[i][1],bw,bh)));
  return out;
}

/* ---------- how it works: what flows between the parts of this level ----------
   A link between two parts deeper down counts for the parts of THIS level that hold them, so
   the top of a jet engine shows air and power moving between its sections even though the
   links were written between blades and shafts. Each kind is its own line and its own word. */
var BP_FLOW_STYLE={load:['',2.6],power:['10 4',1.8],fluid:['6 3 1.5 3',1.8],heat:['2 3',1.8],air:['1 5',2.2],
  data:['8 3 2 3',1.6],signal:['3 3',1.6],control:['12 3 3 3',1.6],material:['',1.6],money:['5 5',1.6],people:['1.5 3',2]};
function bpFlowEdges(st,kids){
  const own={};kids.forEach(k=>{own[k.id]=k.id;for(const [d] of bpWalkJs(k.parts))own[d.id]=k.id});
  const seen={},out=[];
  (st.sc.links||[]).forEach(l=>{const a=own[l.from],b=own[l.to];if(!a||!b||a===b)return;
    const key=a+'>'+b+'>'+(l.kind||'');if(seen[key]){seen[key].n++;return}
    const e={from:a,to:b,verb:l.verb||'',kind:l.kind||'',n:1};seen[key]=e;out.push(e)});
  return out.slice(0,24);
}
function bpWalkJs(parts,acc){acc=acc||[];(parts||[]).forEach(p=>{acc.push([p]);bpWalkJs(p.parts,acc)});return acc}
function bpFlows(world,node,kids,W,H,st){
  const edges=bpFlowEdges(st,kids),svg=bpSvgOf(world),out=[];
  const used=kids.filter(k=>edges.some(e=>e.from===k.id||e.to===k.id));
  // layers by the longest path from a part nothing flows into; a loop is cut where it closes
  const state={},back=new Set();
  const dfs=u=>{state[u]=1;edges.forEach((e,i)=>{if(e.from!==u)return;
    if(state[e.to]===1)back.add(i);else if(!state[e.to])dfs(e.to)});state[u]=2};
  used.forEach(k=>{if(!state[k.id])dfs(k.id)});
  const layer={};used.forEach(k=>layer[k.id]=0);
  for(let pass=0;pass<used.length;pass++){let moved=false;
    edges.forEach((e,i)=>{if(!back.has(i)&&layer[e.to]<layer[e.from]+1){layer[e.to]=layer[e.from]+1;moved=true}});
    if(!moved)break}
  const cols=[];used.forEach(k=>{(cols[layer[k.id]]=cols[layer[k.id]]||[]).push(k)});
  const live=cols.filter(Boolean),narrow=W<560;
  // the layers run left to right and wrap into rows, the next row coming back (a snake), so
  // a long chain stays readable instead of shrinking ten boxes into one line
  const gx=narrow?0:64,minW=narrow?W-60:170;
  const per=narrow?1:Math.max(1,Math.min(live.length,Math.floor((W-40+gx)/(minW+gx))));
  const bw=narrow?W-60:Math.min(230,(W-40-gx*(per-1))/per),bh=56,gy=12,rowGap=narrow?30:46;
  const rows=[];live.forEach((col,i)=>{(rows[Math.floor(i/per)]=rows[Math.floor(i/per)]||[]).push(col)});
  const rowH=rows.map(r=>Math.max(...r.map(c=>c.length))*(bh+gy)-gy);
  const total=rowH.reduce((a,b)=>a+b,0)+rowGap*(rows.length-1);
  const pos={};let ry=Math.max(18,(H-34-total)/2);
  rows.forEach((r,ri)=>{
    const x0=(W-(r.length*bw+(r.length-1)*gx))/2;
    r.forEach((col,ci)=>{const c=ri%2?r.length-1-ci:ci;
      const top=ry+(rowH[ri]-(col.length*(bh+gy)-gy))/2;
      col.forEach((k,ki)=>{pos[k.id]=[x0+c*(bw+gx),top+ki*(bh+gy)]})});
    ry+=rowH[ri]+rowGap});
  st.needH=ry+40;
  const words=edges.length<=6;
  edges.forEach((e,i)=>{
    const [ax,ay]=pos[e.from],[bx,by]=pos[e.to];const sty=BP_FLOW_STYLE[e.kind]||['4 4',1.4];
    const acx=ax+bw/2,acy=ay+bh/2,bcx=bx+bw/2,bcy=by+bh/2,dx=bcx-acx,dy=bcy-acy;
    let s1,s2,n1,n2;
    if(Math.abs(dx)>=Math.abs(dy)*1.4&&Math.abs(dx)>bw*.6){const r=dx>0?1:-1;
      s1=[acx+r*bw/2,acy];s2=[bcx-r*bw/2,bcy];n1=[r,0];n2=[-r,0]}
    else if(Math.abs(dy)>bh*.6){const r=dy>0?1:-1;
      s1=[acx,acy+r*bh/2];s2=[bcx,bcy-r*bh/2];n1=[0,r];n2=[0,-r]}
    else{s1=[acx+bw/2,acy];s2=[bcx+bw/2,bcy];n1=[1,0];n2=[1,0]}   // side by side: out and back round
    const k=Math.max(30,Math.min(90,Math.hypot(dx,dy)/2.5))+(i%3)*6;
    const c1=[s1[0]+n1[0]*k,s1[1]+n1[1]*k],c2=[s2[0]+n2[0]*k,s2[1]+n2[1]*k];
    const d=`M${s1[0]} ${s1[1]}C${c1[0]} ${c1[1]} ${c2[0]} ${c2[1]} ${s2[0]} ${s2[1]}`;
    const path=sSvg('path',{d,class:'bp-fl-line k-'+(e.kind||'none'),'marker-end':bpId(svg,'a'),'data-from':e.from,'data-to':e.to});
    if(sty[0])path.setAttribute('stroke-dasharray',sty[0]);path.setAttribute('stroke-width',sty[1]);
    world.append(path);
    const word=(e.kind?e.kind+(e.verb?' · ':''):'')+(e.verb||'')+(e.n>1?' ×'+e.n:'');
    // the midpoint of the curve; crowded, a word shows with the part you point at
    const mx=(s1[0]+3*c1[0]+3*c2[0]+s2[0])/8,my=(s1[1]+3*c1[1]+3*c2[1]+s2[1])/8;
    if(word)world.append(sSvg('text',{x:mx,y:my-5,'text-anchor':'middle','class':'bp-fl-word'+(words?' on always':''),'data-from':e.from,'data-to':e.to},word));
  });
  used.forEach((k,i)=>{const [x,y]=pos[k.id];
    const g=bpPartG(world,k,i,st);g.append(sSvg('rect',{x,y,width:bw,height:bh,rx:6,class:'bp-fill'}));
    bpShape(g,'rect',{x,y,width:bw,height:bh,rx:6},k);
    bpText(g,x+10,y+21,k.name,bw-20,'bp-name');
    bpText(g,x+10,y+39,bpSub(k)||k.role||'',bw-20,'bp-subt');
    out.push({p:k,g,box:[x,y,bw,bh],anchor:[x+bw,y+bh/2],left:[x,y+bh/2]})});
  // the key: each kind on the sheet, with its own line
  const kinds=[...new Set(edges.map(e=>e.kind).filter(Boolean))];
  const left=kids.length-used.length;
  let kx=18;const ky=H-14;
  kinds.forEach(kd=>{const sty=BP_FLOW_STYLE[kd];
    const ln=sSvg('line',{x1:kx,y1:ky-4,x2:kx+22,y2:ky-4,class:'bp-fl-line k-'+kd});
    if(sty[0])ln.setAttribute('stroke-dasharray',sty[0]);ln.setAttribute('stroke-width',sty[1]);world.append(ln);
    const t=bpText(world,kx+27,ky,kd,0,'bp-tiny');kx+=27+(t.getComputedTextLength?t.getComputedTextLength():40)+14});
  const tail=[edges.length>6?(bpHover()?'point at a part to read its flows':'tap a part to read its flows'):'',
    left>0?left+' part'+(left===1?'':'s')+' with no known flow':''].filter(Boolean).join(' · ');
  if(tail)bpText(world,W-16,ky,tail,0,'bp-tiny','end');
  return out;
}

/* ---------- the title block, as on a drawing: at the foot of the panel ---------- */
function bpTitleBlock(st){
  const el=st.el.info;el.textContent='';
  const node=bpNode(st),n=bpCount(st.sc.parts),dp=bpDepth(st.sc.parts);
  [['Subject',st.sc.subject||st.sc.title||''],['Level',(st.path.length+1)+' of '+dp+' · '+(st.form||'')],
   ['Parts',bpKids(node).length+' here · '+n+' in all'],
   ['Source',st.sc.illustrative?'illustrative, not data':(st.sc.source||'—')]].forEach(([k,v])=>{
    el.append(sEl('span','bp-tbk',k),sEl('span','bp-tbv',v))});
  return el;
}
/* ---------- where you are ---------- */
function bpCrumbs(st){
  const c=st.el.crumbs;c.textContent='';
  const home=sEl('button','bp-crumb'+(st.path.length?'':' on'),st.sc.subject||st.sc.title||'Blueprint');
  home.onclick=()=>bpGo(st,[]);c.append(home);
  let n={parts:st.sc.parts};
  st.path.forEach((id,i)=>{n=bpKids(n).find(p=>p.id===id);if(!n)return;
    c.append(sEl('span','bp-sep','›'));
    const b=sEl('button','bp-crumb'+(i===st.path.length-1?' on':''),n.name);
    const to=st.path.slice(0,i+1);b.onclick=()=>bpGo(st,to);c.append(b)});
  c.append(sEl('span','bp-sp'));
  // two ways to read a level: what it is made of, and what flows between its parts
  const ne=bpFlowEdges(st,bpKids(bpNode(st))).length;
  const pic=bpPicOf(st),canLook=!!pic||bpLooking(st)||(st.live&&!!st.sid);
  if(ne||canLook){const seg=sEl('span','bp-modes');seg.setAttribute('role','group');
    [['parts','Parts']].concat(ne?[['flows','How it works · '+ne]]:[]).concat(canLook?[['look',pic?'Drawing':'◌ Drawing']]:[]).forEach(([m,w])=>{
      const b=sEl('button','bp-mode'+((st.mode||'parts')===m?' on':''),w);b.setAttribute('aria-pressed',String((st.mode||'parts')===m));
      b.onclick=()=>{st.mode=m;st.sel=null;st.peek=null;bpRender(st,'in')};seg.append(b)});
    c.append(seg)}
  // the blueprint as a document of drawing sheets (bpdoc.py): a PDF, or the page itself
  if(st.sid&&!window.STAGE_REPORT){const d=document.createElement('details');d.className='bp-exp';
    const sm=sEl('summary','bp-up','⤓ Export');sm.title='Keep it as a document: a set of drawing sheets';d.append(sm);
    const m=sEl('div','bp-exp-m');
    [['pdf','Document (PDF)','Drawing sheets, ready to print or send'],['html','Web page','The same sheets as one page you can open anywhere']].forEach(([f,w,t])=>{
      const a=document.createElement('a');a.className='bp-exp-a';a.href='/api/stage/scene/'+encodeURIComponent(st.sid)+'/export?format='+f;
      a.setAttribute('download','');a.title=t;a.append(sEl('b','',w),sEl('span','',t));
      a.onclick=()=>{d.open=false;if(typeof toast==='function')toast(f==='pdf'?'Printing the blueprint… it downloads in a moment':'Downloading the blueprint')};m.append(a)});
    d.append(m);c.append(d)}
  if(st.path.length){const up=sEl('button','bp-up','↥ Up');up.title='Back up one level (Esc)';up.onclick=()=>bpGo(st,st.path.slice(0,-1),'back');c.append(up)}
  // the legend: what a dashed or dotted line means
  const lg=sEl('span','bp-legend');
  [['known','known'],['estimated','estimated'],['unclear','unclear']].forEach(([k,w])=>{
    const s=sEl('span','bp-lg c-'+k);s.append(sEl('i',''),document.createTextNode(w));lg.append(s)});
  c.append(lg);
}
function bpLocator(st){
  const box=st.el.loc;box.textContent='';
  if(!st.path.length)return null;
  const W=150,H=110,svg=sSvg('svg',{viewBox:`0 0 ${W} ${H}`,width:W,height:H});box.append(svg);
  // the top level, small, with the branch you are in lit: you are here
  const root={name:'',parts:st.sc.parts,form:st.sc.form,root:true};
  svg.dataset.uid='bpl';
  const g=sSvg('g',{class:'bp-world bp-mini'});svg.append(g);
  const fake={sc:st.sc,path:[],sel:null};
  try{const L=(st.sc.form==='tower'?bpTower:st.sc.form==='flow'?bpFlow:bpExploded)(g,root,bpKids(root),W*4,H*4,fake);
    g.setAttribute('transform','scale(.25)');
    L.forEach(it=>{if(it.p.id===st.path[0])it.g.classList.add('here')});
  }catch(e){}
  box.append(sEl('div','bp-loc-t','You are here: '+st.path.length+' level'+(st.path.length===1?'':'s')+' in'));
  return box;
}
/* ---------- the drawing: a picture of the real thing, in blueprint ink (bppicture.py) ---------- */
function bpPicOf(st){   // the level's own picture, else the nearest one above it
  let n={parts:st.sc.parts},pic=st.sc.picture||null;
  for(const id of st.path){n=bpKids(n).find(p=>p.id===id);if(!n)break;if(n.picture)pic=n.picture}
  return pic}
function bpLooking(st){return !!st.sc.looking&&Date.now()/1000<st.sc.looking}
function bpCredit(pic){
  const cap=sEl('figcaption','bp-cred');
  if(pic.made==='drawn'){cap.textContent='Illustrative drawing by '+(pic.credit||'an image model')+'. It may not match the real thing.';return cap}
  cap.append(document.createTextNode([pic.title,pic.credit,pic.licence].filter(Boolean).join(' · ')+' · '));
  if(pic.page&&!window.STAGE_STILL){const a=document.createElement('a');a.href=pic.page;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Wikimedia Commons';cap.append(a)}
  else cap.append(document.createTextNode('Wikimedia Commons'));
  return cap}
function bpImg(pic,name){const img=document.createElement('img');img.src=pic.url||'';img.alt='Drawing of '+(name||'it');
  img.decoding='async';img.referrerPolicy='no-referrer';return img}
function bpThumb(pic,name){const b=sEl('button','bp-thumb'+(pic.made==='drawn'?' drawn':''));b.title='See the drawing';
  b.append(bpImg(pic,name),sEl('span','bp-thumb-t','▣ Drawing ›'));return b}
function bpLook(st){
  const {draw,svg}=st.el;svg.style.display='none';
  const box=sEl('div','bp-look');draw.append(box);
  const node=bpNode(st),pic=bpPicOf(st),kids=bpKids(node);
  if(!pic){
    box.append(sEl('div','bp-look-none',bpLooking(st)?'◌ Looking for a free drawing of it…':'No free drawing of this was found.'));
    if(!bpLooking(st)&&st.live&&st.sid)box.append(bpDrawBtn(st,'✎ Draw one'));
    return}
  const fig=sEl('figure','bp-fig'+(pic.made==='drawn'?' drawn':'')+(st.orig?' orig':''));
  const img=bpImg(pic,node.name||st.sc.subject);
  img.onerror=()=>{fig.replaceWith(sEl('div','bp-look-none bp-fail','The drawing could not be loaded.'))};
  fig.append(img,bpCredit(pic));box.append(fig);
  // the parts of this level beside it, numbered: the picture cannot be pointed at reliably
  if(kids.length){const ol=sEl('ol','bp-look-parts');
    kids.forEach(k=>{const li=sEl('li','');const b=sEl('button','bp-in-b',k.name);
      b.onclick=()=>{st.sel=k.id;bpSpec(st)};li.append(b);ol.append(li)});box.append(ol)}
  if(!window.STAGE_REPORT){const acts=sEl('div','bp-look-acts');
    if(pic.made!=='drawn'){const o=sEl('button','bp-mode',st.orig?'Blueprint ink':'Original colours');
      o.onclick=()=>{st.orig=!st.orig;bpRender(st,'')};acts.append(o)}
    if(st.live&&st.sid)acts.append(bpDrawBtn(st,pic.made==='drawn'?'✎ Draw again':'✎ Draw one instead'));
    box.append(acts)}
}
/* a drawing made on the person's tap with this machine's image engine; the scene comes back on stage_fill */
function bpDrawBtn(st,w){
  const b=sEl('button','bp-open',w);b.title='Draw it with this machine\'s image engine. It is illustrative.';
  b.onclick=async()=>{b.disabled=true;b.textContent='✎ Drawing…';
    try{const r=await fetch('/api/stage/draw',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id:st.sid,part:st.path.length?st.path[0]:''})});
      const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||('HTTP '+r.status))}
    catch(e){b.disabled=false;b.textContent=w;if(typeof toast==='function')toast('Could not draw it: '+e.message)}};
  return b}
/* ---------- the spec panel: what the part under your finger is ---------- */
function bpSpec(st){
  const el=st.el.spec;el.textContent='';
  const node=bpNode(st),kids=bpKids(node);
  const id=st.peek||st.sel,p=id?kids.find(k=>k.id===id):null;
  if(!p){
    el.append(sEl('div','bp-k',(st.path.length?'Inside ':'Blueprint · ')+(st.path.length?'':'')+kids.length+' parts'+(st.path.length?'':' · '+bpDepth(st.sc.parts)+' levels deep')));
    el.append(sEl('div','bp-h',node.name||st.sc.subject));
    if(node.root&&st.sc.caption)el.append(sEl('p','bp-role',st.sc.caption));
    if(node.role)el.append(sEl('p','bp-role',node.role));
    if(node.root)bpFillNote(st,el);
    bpAbout(el,node);
    if((node.facts||[]).length){el.append(sEl('div','bp-k2 bp-k2b',node.root?'Key numbers':'Numbers'));bpFacts(el,node.facts)}
    const un=(node.root?st.sc.unknowns:node.unknowns)||[];
    if(un.length){el.append(sEl('div','bp-k2','Still unclear'));const u=sEl('ul','bp-unk');un.forEach(x=>u.append(sEl('li','',x)));el.append(u)}
    const hint=sEl('p','bp-hint',bpHover()?'Point at a part to read it. Click to open it.':'Tap a part to read it. Tap again to open it.');
    el.append(hint);
    if(!node.root&&node.evidence)el.append(sEl('div','bp-ev',node.evidence));
    bpPanelFoot(st,el);
    return;
  }
  const i=kids.indexOf(p);
  const k=sEl('div','bp-k','Part '+(i+1)+' of '+kids.length+' · ');
  const c=sEl('span','bp-cert c-'+(p.certainty||'known'),BP_CERT_WORD[p.certainty||'known']);k.append(c);el.append(k);
  el.append(sEl('div','bp-h',p.name));
  if(p.status&&BP_STATUS[p.status]){const [ic,w,col]=BP_STATUS[p.status];
    const s=sEl('span','bp-status',ic+' '+w);s.style.color=col;s.style.borderColor=col;el.append(s)}
  if(p.role)el.append(sEl('p','bp-role',p.role));
  if(p.picture&&bpKids(p).length){const t=bpThumb(p.picture,p.name);
    t.onclick=()=>{st.mode='look';bpOpen(st,p)};el.append(t)}
  if(bpIsFilling(st,p))el.append(sEl('p','bp-note bp-fillt','◌ Filling this part in. It updates here when it lands.'));
  else{const f=bpFailed(st,p);
    if(f)el.append(sEl('p','bp-note','Couldn\'t fill this part in: '+f.why));
    else if(bpThin(p))el.append(sEl('p','bp-note','Only a little is known about this part.'))}
  bpAbout(el,p);
  if(p.from!=null||p.to!=null){
    const u=st.sc.unit?' '+st.sc.unit:'';
    bpFacts(el,[{label:'from',value:bpFmt(p.from),unit:u.trim()},{label:'to',value:bpFmt(p.to),unit:u.trim()}].concat(p.facts||[]));
  }else bpFacts(el,p.facts);
  if((p.unknowns||[]).length){el.append(sEl('div','bp-k2','Still unclear'));const u=sEl('ul','bp-unk');p.unknowns.forEach(x=>u.append(sEl('li','',x)));el.append(u)}
  if(bpKids(p).length){el.append(sEl('div','bp-k2 bp-k2b','Inside'));const u=sEl('ul','bp-in-list');
    bpKids(p).forEach(c=>{const li=sEl('li','');const b=sEl('button','bp-in-b',c.name);
      b.onclick=()=>{bpOpen(st,p);setTimeout(()=>{st.sel=c.id;bpSpec(st);bpMark(st)},460)};
      li.append(b);if(c.role)li.append(sEl('span','bp-in-r',c.role));u.append(li)});el.append(u)}
  if(p.evidence)el.append(sEl('div','bp-ev',p.evidence));
  if(p.source)el.append(typeof stageSource==='function'?stageSource(p.source):sEl('div','st-src','Source: '+p.source));
  const n=bpKids(p).length;
  const acts=sEl('div','bp-acts');
  if(n){const b=sEl('button','bp-open','Open inside · '+n+' part'+(n===1?'':'s')+' ›');b.onclick=()=>bpOpen(st,p);acts.append(b)}
  else if(st.live&&st.seq&&typeof stageDeeper==='function'){
    const b=sEl('button','bp-open','⤵ Take this apart');b.title='Ask for this part as its own blueprint';
    b.onclick=()=>stageDeeper(st.seq,p.id);acts.append(b)}
  else if(p.evidence)acts.append(sEl('span','bp-bottom','This is a record: the bottom of it.'));
  // the story's chat beside the Stage: ask about this part in words (24w-stagechat.js)
  if(st.live&&typeof stageAskAbout==='function'){const a=sEl('button','bp-more-b','✦ Ask about this');
    a.title='Ask your agent about '+p.name+' in the chat beside the Stage';a.onclick=()=>stageAskAbout(p.name);acts.append(a)}
  el.append(acts);
  bpPanelFoot(st,el,p);
}
/* What the panel ends on: how this part depends on others, where you are, the title block. */
function bpPanelFoot(st,el,p){
  const name=id=>{const x=bpFind(st.sc.parts,id);return x?x.name:id};
  const here=new Set(bpKids(bpNode(st)).map(k=>k.id));
  const ls=(st.sc.links||[]).filter(l=>p?(l.from===p.id||l.to===p.id):(here.has(l.from)||here.has(l.to)));
  if(ls.length){el.append(sEl('div','bp-k2 bp-k2b','How it connects'));const u=sEl('ul','bp-conn');
    ls.slice(0,8).forEach(l=>u.append(sEl('li','',name(l.from)+' '+(l.verb||'→')+' '+name(l.to))));el.append(u)}
  const loc=bpLocator(st);if(loc)el.append(loc);
  el.append(bpTitleBlock(st));
}
/* how it works, what it is made of, its limits: the three things a name never says */
function bpAbout(el,p){
  if(p.how){el.append(sEl('div','bp-k2 bp-k2b','How it works'));el.append(sEl('p','bp-detail',p.how))}
  if((p.steps||[]).length){if(!p.how)el.append(sEl('div','bp-k2 bp-k2b','How it works'));
    const ol=sEl('ol','bp-steps');p.steps.forEach(x=>ol.append(sEl('li','',x)));el.append(ol)}
  if(p.like)el.append(sEl('p','bp-like','≈ '+p.like));
  if(p.detail)el.append(sEl('p','bp-detail',p.detail));
  if(p.made_of){el.append(sEl('div','bp-k2 bp-k2b','Made of'));el.append(sEl('p','bp-detail',p.made_of))}
  if(p.limits){el.append(sEl('div','bp-k2','Limits'));el.append(sEl('p','bp-detail',p.limits))}
}
/* where the filling in is: how many parts landed, looked up or not, and which could not */
function bpFillNote(st,el){
  const f=st.sc.fill;if(!f)return;
  const going=bpFillingIds(st.sc).length,done=(f.done||[]).length,bad=(f.failed||[]).length;
  const all=done+bad+going;
  let w=going?'◌ Filling in '+(done+bad)+' of '+all+' parts…':'Filled in '+done+' of '+all+' parts';
  if(f.looked_up)w+=' · '+f.looked_up+' look-up'+(f.looked_up===1?'':'s');
  else if(done&&!going)w+=' · from what the model knew, nothing looked up';
  el.append(sEl('p','bp-note'+(going?' bp-fillt':''),w));
}
function bpFacts(el,facts){
  if(!(facts||[]).length)return;
  const dl=sEl('dl','bp-facts');
  facts.forEach(f=>{if(f.value===''||f.value==null)return;dl.append(sEl('dt','',f.label||'·'),sEl('dd','',bpVal(f)))});
  el.append(dl);
}
function bpPeek(st){
  const el=st.el.peek;el.textContent='';
  const p=st.sel&&bpNarrow(st)?bpKids(bpNode(st)).find(k=>k.id===st.sel):null;
  el.hidden=!p;if(!p)return;
  // never over the part it is about: low on the drawing, the sheet sits at the top
  const it=(st.items||[]).find(x=>x.p.id===p.id),H=st.el.draw.clientHeight||1;
  el.classList.toggle('up',!!it&&(it.box[1]+it.box[3]/2)>H*.55);
  const top=sEl('div','bp-peek-h');top.append(sEl('b','',p.name));
  if(p.status&&BP_STATUS[p.status]){const [ic,w,col]=BP_STATUS[p.status];const s=sEl('span','bp-status',ic+' '+w);s.style.color=col;s.style.borderColor=col;top.append(s)}
  el.append(top);
  const f=(p.facts||[])[0];
  el.append(sEl('div','bp-peek-r',p.role||(f?(f.label+' '+bpVal(f)):'')));
  const acts=sEl('div','bp-acts');
  const n=bpKids(p).length;
  if(n){const b=sEl('button','bp-open','Open inside · '+n+' ›');b.onclick=()=>bpOpen(st,p);acts.append(b)}
  // only the scene scrolls: scrollIntoView would scroll the Stage's own room too
  const more=sEl('button','bp-more-b','Details ↓');more.onclick=()=>st.art.scrollTo({top:st.el.spec.offsetTop-8,behavior:stageReduced()?'auto':'smooth'});
  acts.append(more);
  const x=sEl('button','bp-x','✕');x.setAttribute('aria-label','Close');x.onclick=()=>{st.sel=null;bpSpec(st);bpMark(st)};acts.append(x);
  el.append(acts);
}
function bpMark(st){
  bpPeek(st);
  const id=st.peek||st.sel;
  st.el.svg.classList.toggle('bp-focus',!!id);
  (st.items||[]).forEach(it=>it.g.classList.toggle('on',it.p.id===id));
  st.el.svg.querySelectorAll('.bp-link,.bp-verb,.bp-fl-line[data-from],.bp-fl-word').forEach(l=>l.classList.toggle('on',l.classList.contains('always')||(!!id&&(l.dataset.from===id||l.dataset.to===id))));
}

/* ---------- moving through it ---------- */
function bpTap(st,p,e){
  bpTourStop(st);
  const kids=bpKids(p).length;
  // a mouse reads by pointing, so a click opens; a finger reads by the first tap
  if(kids&&(st.sel===p.id||(e&&e.pointerType==='mouse')||bpHover())){bpOpen(st,p);return}
  st.sel=st.sel===p.id&&!kids?null:p.id;st.peek=null;bpSpec(st);bpMark(st);
}
function bpOpen(st,p){
  if(!bpKids(p).length)return;
  const it=(st.items||[]).find(x=>x.p.id===p.id),world=st.el.svg.querySelector('.bp-world');
  const go=()=>{st.path=st.path.concat(p.id);st.sel=null;st.peek=null;bpRender(st,'in');bpFocusFirst(st)};
  if(!it||!world||stageReduced()){go();return}
  // the drawing flies into the part, then the part's own drawing comes up
  const W=+st.el.svg.getAttribute('width'),H=+st.el.svg.getAttribute('height');
  const [x,y,w,h]=it.box,s=Math.min(6,Math.max(1.6,Math.min(W/Math.max(w,30),H/Math.max(h,30))*.7));
  world.style.transformOrigin=(x+w/2)+'px '+(y+h/2)+'px';
  world.style.transform=`translate(${W/2-(x+w/2)}px,${H/2-(y+h/2)}px) scale(${s})`;
  world.classList.add('bp-dive');
  setTimeout(go,420);
}
function bpGo(st,path,how){bpTourStop(st);const was=st.path.length;st.path=path;st.sel=null;st.peek=null;
  bpRender(st,how||(path.length<was?'back':'in'));bpFocusFirst(st)}
function bpFocusFirst(st){try{if(st.art.contains(document.activeElement)){const g=st.el.svg.querySelector('.bp-p');if(g)g.focus({preventScroll:true})}}catch(e){}}
function bpKey(st,e){
  if(e.key==='Escape'&&st.path.length){e.preventDefault();e.stopPropagation();bpGo(st,st.path.slice(0,-1),'back');return}
  const gs=[...st.el.svg.querySelectorAll('.bp-p')];const i=gs.indexOf(document.activeElement);
  if(i<0)return;
  if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();
    const p=bpKids(bpNode(st)).find(k=>k.id===gs[i].dataset.id);if(p){if(bpKids(p).length)bpOpen(st,p);else{st.sel=p.id;bpSpec(st);bpMark(st)}}return}
  const d={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[e.key];
  if(d){e.preventDefault();e.stopPropagation();gs[(i+d+gs.length)%gs.length].focus()}
}

/* ---------- the tour: while the story plays, each part is pointed out in turn ---------- */
function bpTourMs(sc){return Math.min(14000,(sc.parts||[]).length*1700+1200)}
function bpTour(st){
  const kids=bpKids(bpNode(st));let i=0;
  const step=()=>{if(!st.art.isConnected||typeof STAGE==='undefined'||!STAGE.playing){bpTourStop(st);return}
    if(i>=kids.length){st.peek=null;bpSpec(st);bpMark(st);return}
    st.peek=kids[i++].id;bpSpec(st);bpMark(st);st.tour=setTimeout(step,1700)};
  st.tour=setTimeout(step,900);
}
function bpTourStop(st){if(st.tour){clearTimeout(st.tour);st.tour=null}}

/* ---------- X-ray: this machine's own record of an answer or a run, as a blueprint ---------- */
async function stageXray(q,label){
  let d;
  try{d=await apiJSON('/api/stage/xray?'+new URLSearchParams(q).toString())}
  catch(e){toast('could not X-ray it: '+(e.message||e));return}
  if(!d||!d.scene){toast('could not X-ray it: '+((d&&d.error)||'no record'));return}
  STAGE.cur={cid:q.conversation||d.conversation_id||'',answer_to:'xray:'+(q.answer_to||q.run||''),
    question:label||d.scene.subject||'',parent:null,deeper:{},versions:[],xray:q};
  STAGE.scenes=[{id:'xray',seq:1,scene:d.scene}];STAGE.at=0;STAGE.tab='now';STAGE.held=Date.now()+600000;
  const w=typeof WM!=='undefined'&&WM.wins.get('stage');
  if(w){focusWin(w);stagePaint()}else openApp('stage');
}
function xrayButton(q,label){
  const b=sEl('button','xray-btn','⌖ X-ray');
  b.title='Take this apart: who did what, every decision the gate made, what it cost';
  b.onclick=e=>{e.stopPropagation();stageXray(q,label)};return b;
}
/* Chat: an X-ray under each answer, for the question it answers. */
function xrayAttach(cid){
  if(!cid||typeof feed==='undefined'||!feed)return;
  feed.querySelectorAll('.msg.user[data-mid]').forEach(u=>{
    let a=u.nextElementSibling;
    while(a&&!a.classList.contains('assistant')&&!a.classList.contains('user'))a=a.nextElementSibling;
    if(!a||!a.classList.contains('assistant')||a.querySelector(':scope > .xray-btn'))return;
    a.append(xrayButton({conversation:cid,answer_to:u.dataset.mid},'X-ray · '+(u.textContent||'').trim().slice(0,80)));
  });
}
/* A turn that just ended has no message id on the page yet: its X-ray asks for the last one. */
async function xrayLive(cid,msgEl){
  if(!cid||!msgEl||msgEl.querySelector(':scope > .xray-btn'))return;
  // pinned to this question now, so a later turn in the chat never changes what it opens
  let mid='';try{const d=await apiJSON('/api/conversations/'+encodeURIComponent(cid));
    const us=(d.messages||[]).filter(m=>m.role==='user');mid=us.length?us[us.length-1].id:''}catch(e){}
  if(!msgEl.isConnected||msgEl.querySelector(':scope > .xray-btn'))return;
  msgEl.append(xrayButton(mid?{conversation:cid,answer_to:mid}:{conversation:cid},'X-ray of this answer'));
}
