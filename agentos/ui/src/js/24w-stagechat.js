/* The Stage with its chat beside it. Asked for as "load the stage inside the chat and keep the
   chat window on the right to go further, like blueprint + chat, because you can ask more and
   chat on it". The panel is the copilot panel pinned to the story's own conversation
   (initCopilot with data-cid), so a question asked here is a turn in that chat, its answer is
   in Chat too, and a scene it shows lands on this Stage as the next version of the story.

   Three things keep it right:
   - ONE panel element per conversation, moved into each repaint: stagePaint rebuilds the body
     on every scene, and rebuilding the panel would drop a reply that is streaming into it.
   - Every turn says what the person is looking at (`_context`): the scene, and in a blueprint
     the level, the view and the part selected, so "what is it made of?" means that part.
   - It's the person's to hide (`stage.chat`, per browser). On a phone it opens over the scene.

   The chat is a TREE that follows the blueprint (asked for as "dig deeper into something and come
   out of it … resume the chat from the top of the tree but the context of everything is known").
   Each level of a blueprint has its own thread: a question is filed with where it was asked
   (`stage_at` on the message, server._stage_at), the panel shows the thread of the level on
   screen, and opening a part or going Up moves the chat with it. A reply belongs to the question
   before it. The agent's conversation stays ONE: everything said on any branch is in its history,
   and each turn says where in the tree it is asked and which branches exist. A story the agent
   shows from inside a part is that part gone deeper (stage._asked_inside), and Back opens the
   parent blueprint at that part, where its thread resumes. */
var STAGE_CHAT={el:null,cid:'',open:null,key:'',want:null,counts:{},names:{},lastAt:null};

function stageChatWanted(){
  if(STAGE_CHAT.open!==null)return STAGE_CHAT.open;
  let v=null;try{v=localStorage.getItem('stage.chat')}catch(e){}
  // a phone keeps the scene to itself until asked; a desk has the room
  STAGE_CHAT.open=v===null?!(typeof document!=='undefined'&&document.body.classList.contains('dev-mobile')):v==='1';
  return STAGE_CHAT.open;
}
function stageChatSet(on,focus){
  STAGE_CHAT.open=!!on;try{localStorage.setItem('stage.chat',on?'1':'0')}catch(e){}
  stagePaint();
  if(on&&focus)setTimeout(()=>{const i=STAGE_CHAT.el&&STAGE_CHAT.el.querySelector('.cp-in');if(i)i.focus()},60);
}
function stageChatPanel(){
  const w=typeof WM!=='undefined'&&WM.wins.get('stage');
  const cid=(STAGE.cur&&STAGE.cur.cid)||'';
  if(!w||!cid||typeof initCopilot!=='function')return null;
  if(!STAGE_CHAT.el||STAGE_CHAT.cid!==cid){
    const p=sEl('div','task-chat st-chat');
    p.dataset.cid=cid;p.dataset.title=(STAGE.cur.question||'this story').slice(0,60);
    p._context=stageChatContext;p._filter=stageChatFilter;
    // where the last question was asked: a story it brings is a branch under that part
    p._at=()=>{const a=stageChatAt();const cur=STAGE.scenes[STAGE.at];
      STAGE_CHAT.lastAt=a?{...a,answer_to:STAGE.cur.answer_to,seq:(cur&&cur.seq)||1}:null;return a};
    STAGE_CHAT.el=p;STAGE_CHAT.cid=cid;STAGE_CHAT.key=stageChatKey(stageChatAt());
    initCopilot(w,p);
    const tree=sEl('div','st-tree');tree.setAttribute('aria-label','Where this chat is in the blueprint');
    const head=p.querySelector('.cp-head');if(head)head.after(tree);
  }
  const t=STAGE_CHAT.el.querySelector('.cp-in');
  if(t&&!t.value)t.placeholder=stageChatHint();
  return STAGE_CHAT.el;
}
function stageChatHint(){
  const at=stageChatAt();
  if(at)return 'Ask about the '+at.names[at.names.length-1]+'…';
  return 'Ask more about this…';
}
/* where the person is in the tree: the blueprint on screen and the level opened */
function stageChatBp(){const art=document.querySelector('.st-main .bp-art');const st=art&&art._bp;return st&&st.live&&st.sid?st:null}
function stageChatAt(){
  const st=stageChatBp();if(!st)return null;
  const names=[st.sc.subject||st.sc.title||'Blueprint'];let n={parts:st.sc.parts};
  for(const id of st.path){n=bpKids(n).find(p=>p.id===id);if(!n)break;names.push(n.name)}
  return {scene:st.sid,path:st.path.slice(),names};
}
function stageChatKey(at){return at?at.scene+'#'+at.path.join('/'):''}
/* the branch on screen, out of the whole conversation; and how much was said on every branch */
function stageChatFilter(msgs){
  const at=stageChatAt();
  STAGE_CHAT.counts={};STAGE_CHAT.names={};
  if(!at){stageChatTree();return msgs}
  const key=stageChatKey(at),top=!at.path.length,out=[];let cur='';
  msgs.forEach(m=>{
    if(m.role==='user'){const t=(m.meta||{}).stage_at;
      cur=t&&t.scene?t.scene+'#'+(t.path||[]).join('/'):'';
      if(t&&t.scene){STAGE_CHAT.counts[cur]=(STAGE_CHAT.counts[cur]||0)+1;STAGE_CHAT.names[cur]=t.names||[]}}
    // a message asked in Chat itself (no place in the tree) is the top of the first story,
    // never of a story that went deeper from it
    if(cur===key||(!cur&&top&&!(STAGE.cur&&STAGE.cur.parent)))out.push(m);
  });
  stageChatTree();
  return out;
}
/* the strip over the thread: where you are, the threads above you, the ones inside */
function stageChatTree(){
  const p=STAGE_CHAT.el,box=p&&p.querySelector('.st-tree');if(!box)return;
  box.textContent='';
  const st=stageChatBp(),at=stageChatAt();
  if(!st||!at){box.hidden=true;return}
  box.hidden=false;
  const crumbs=sEl('div','st-tree-at');crumbs.append(sEl('span','st-tree-k','Talking about'));
  at.names.forEach((nm,i)=>{
    if(i)crumbs.append(sEl('span','st-tree-sep','›'));
    const k=at.scene+'#'+at.path.slice(0,i).join('/'),c=STAGE_CHAT.counts[k]||0;
    const here=i===at.names.length-1;
    const b=sEl('button','st-tree-b'+(here?' on':''),nm+(c&&!here?' · '+c:''));
    b.title=here?'This level\'s thread':'Back up to '+nm+(c?' ('+c+' question'+(c===1?'':'s')+' there)':'');
    if(!here)b.onclick=()=>bpGo(st,at.path.slice(0,i),'back');
    crumbs.append(b)});
  box.append(crumbs);
  // threads inside this level, one level down or deeper, that this blueprint still has
  const pre=at.scene+'#'+at.path.join('/'),kids=[];
  Object.keys(STAGE_CHAT.counts).forEach(k=>{
    if(k===pre||!k.startsWith(at.scene+'#'))return;
    const path=k.slice(at.scene.length+1).split('/').filter(Boolean);
    if(path.length<=at.path.length||at.path.some((id,i)=>path[i]!==id))return;
    kids.push([path,STAGE_CHAT.names[k]||[],STAGE_CHAT.counts[k]])});
  if(kids.length){const row=sEl('div','st-tree-in');row.append(sEl('span','st-tree-k','Threads inside'));
    kids.sort((a,b)=>a[0].length-b[0].length).slice(0,8).forEach(([path,names,c])=>{
      const nm=names.slice(at.path.length+1).join(' › ')||path[path.length-1];
      const b=sEl('button','st-tree-b','↳ '+nm+' · '+c);b.title='Go into '+nm+' and pick its thread up';
      b.onclick=()=>bpGo(st,path,'in');row.append(b)});
    box.append(row)}
  // stories that went deeper from this level or a part inside it: the way back down
  const br=((STAGE.cur&&STAGE.cur.branches)||[]).filter(b=>b.scene===at.scene&&b.path.length>=at.path.length
    &&at.path.every((id,i)=>b.path[i]===id));
  if(br.length){const row=sEl('div','st-tree-in');row.append(sEl('span','st-tree-k','Went deeper'));
    br.slice(0,6).forEach(b=>{const x=sEl('button','st-tree-b','⤵ '+(b.title||'its own blueprint'));
      x.title='Open the blueprint this went deeper into, and its thread';
      x.onclick=()=>stageOpen(STAGE.cur.cid,b.answer_to,0);row.append(x)});
    box.append(row)}
  // a deeper story: the way back up the tree to the part it came from
  const pa=STAGE.cur&&STAGE.cur.parent;
  if(pa&&(pa.path||[]).length){const b=sEl('button','st-tree-b st-tree-up','↑ Back up the tree');
    b.title='Open the blueprint this came from, at the part it went deeper on';
    b.onclick=()=>{STAGE_CHAT.want={scene:pa.scene,path:pa.path,until:Date.now()+5000};stageOpen(STAGE.cur.cid,pa.answer_to,(pa.seq||1)-1)};
    box.append(b)}
}
/* the blueprint moved (a part opened, Up, another scene): the chat moves to that branch */
function stageChatFollow(st){
  const p=STAGE_CHAT.el;if(!p||!p.isConnected||STAGE_CHAT.cid!==(STAGE.cur&&STAGE.cur.cid))return;
  const key=stageChatKey(stageChatAt());
  const t=p.querySelector('.cp-in');if(t)t.placeholder=stageChatHint();
  if(key===STAGE_CHAT.key){stageChatTree();return}
  STAGE_CHAT.key=key;
  if(p._replay)p._replay();
}
function stageChatScene(){const c=STAGE.scenes&&STAGE.scenes[STAGE.at];return c&&c.scene}
/* what the person is looking at, said with every turn from the panel */
function stageChatContext(){
  const sc=stageChatScene();if(!sc)return '';
  const out=['The person is asking from the Stage, looking at scene '+(STAGE.at+1)+' of '+STAGE.scenes.length+': '
    +(STAGE_KIND[sc.kind]||sc.kind)+(sc.title?' "'+sc.title+'"':'')+'.'];
  const art=document.querySelector('.bp-art');const st=art&&art._bp;
  if(sc.kind==='blueprint'&&st&&st.sc===sc){
    const names=[];let n={parts:sc.parts};
    st.path.forEach(id=>{n=bpKids(n).find(p=>p.id===id);if(n)names.push(n.name)});
    out.push('Blueprint of '+(sc.subject||sc.title)+(names.length?', opened at '+names.join(' › '):', at the top level')
      +', in the '+({parts:'Parts',flows:'How it works',look:'Drawing'}[st.mode||'parts'])+' view.');
    const p=st.sel?bpFind(sc.parts,st.sel):null;
    if(p)out.push('The part selected is "'+p.name+'"'+(p.role?' ('+p.role+')':'')+'. "It" or "this" means that part.');
    // the tree: where this is asked, and the branches already talked about
    const br=Object.keys(STAGE_CHAT.counts).map(k=>(STAGE_CHAT.names[k]||[]).join(' › ')+' ('+STAGE_CHAT.counts[k]+')').filter(x=>x.length>4);
    out.push('This chat follows the blueprint as a tree: the person moves into parts and back up, and each level has its own '
      +'thread. This question is asked at '+(['the top'].concat(names).slice(-1)[0])+'; answer about that level. Everything said on '
      +'other branches is earlier in this conversation and still counts'+(br.length?' (threads so far: '+br.slice(0,12).join('; ')+')':'')+'.');
    out.push('To go deeper than this blueprint, show a new scene: a blueprint of one part, a specification as a table, a '
      +'chart. It appears on their Stage as a branch under this part, and they can come back up to it.');
  }
  return out.join(' ');
}
/* "Ask about this part": the chat opens with the part named, ready to finish the sentence */
function stageAskAbout(name){
  if(!stageChatWanted())stageChatSet(true);
  const p=stageChatPanel();if(!p)return;
  const i=p.querySelector('.cp-in');if(!i)return;
  i.value='About the '+name+': ';i.focus();try{i.setSelectionRange(i.value.length,i.value.length)}catch(e){}
}
/* the window's ✦ is this chat on the Stage: one panel, not two threads */
function stageChatButton(w){
  const cb=w&&w.el.querySelector('.cp-btn');if(!cb||cb._stage)return;
  cb._stage=true;cb.title='Chat about this story';
  // the app copilot's own thread would be a second chat about the same story
  const cp=w.el.querySelector('.copanel');if(cp&&cp.classList.contains('open')){cp.classList.remove('open');cb.classList.remove('on')}
  cb.onclick=e=>{e.stopPropagation();stageChatSet(!stageChatWanted(),true)};
}
