/* ================= task desktops: one desktop per running task =================
   Asked for as "use desktops for different chats, and scroll between them, given we can
   give different tasks at the same time to the same or different company; as tasks get
   completed the desktop can close, asking the user".

   The moment it happens: you leave a conversation in Chat while its turn is still running
   (you open another chat, or start a new one, to give a second task). That running task
   moves to a desktop of its own, in a Task window pinned to it (initCopilot with
   data-cid): its progress keeps streaming there and you can keep talking to it, while
   Chat is free for the next task. The pager names each task desktop and shows a dot while
   it works; the wheel over the pager scrolls the desktops. When the task finishes you are
   asked whether to close its desktop; nothing is closed without a yes.

   Per browser and on by default (`taskdesk.auto`); a desktop of its own is a change to
   what is on your screen, so it is said in a toast with a way to go there. The TUI and
   Telegram have no desktops: there the backend runs tasks side by side (telegram.py runs
   each chat's turn on its own). */

var TASKDESK=window.TASKDESK||{map:{},next:null};
window.TASKDESK=TASKDESK;
var TASKDESK_MAX=9;

function taskDeskAuto(){try{return localStorage.getItem('taskdesk.auto')!=='0'}catch(e){return true}}

function renderTaskWin(body,w){
  if(!w._cid&&TASKDESK.next){w._cid=TASKDESK.next.cid;w._title=TASKDESK.next.title;TASKDESK.next=null}
  const t=w.el.querySelector('.tname');if(t&&w._title)t.textContent='▸ '+w._title;
  if(!w._cid){body.innerHTML=emptyBox('No task here','A running chat moves to its own desktop when you start another task.');return}
  if(body.querySelector('.task-chat'))return;
  body.innerHTML='<div class="task-chat"></div>';
  const p=body.firstChild;p.dataset.cid=w._cid;p.dataset.title=w._title||'';
  initCopilot(w,p);
}

/* The title Chat shows for a conversation, read from its own list. */
function taskDeskTitle(cid){
  const row=document.querySelector('#convs .conv.active .t');
  const t=(row&&currentConv===cid?row.textContent:'')||'';
  return t.replace(/^● /,'').trim()||'a task';
}

/* A running conversation gets a desktop of its own, with its task window. */
function taskDeskOpen(cid,title){
  if(!cid||TASKDESK.map[cid])return;
  if(DESKS>=TASKDESK_MAX){toast('There is no room for another desktop. Close a finished one first.');return}
  DESKS++;try{localStorage.setItem('desks',DESKS)}catch(e){}
  const n=DESKS;
  TASKDESK.next={cid,title};
  const w=openApp('task',{fresh:true});
  if(!w)return;
  w.desk=n;
  TASKDESK.map[cid]={desk:n,title,w,done:false};
  applyDeskVisibility();buildPager();
  toast(`“${title}” keeps working on Desktop ${n}`,{label:'Go there',go:()=>switchDesk(n)});
}

/* Leaving a running conversation in Chat: it gets its own desktop. */
function taskDeskLeaving(nextCid){
  if(!taskDeskAuto())return;
  const cid=typeof currentConv!=='undefined'?currentConv:null;
  if(!cid||cid===nextCid||!RUNNING.has(cid)||TASKDESK.map[cid])return;
  taskDeskOpen(cid,taskDeskTitle(cid));
}

/* A task finished: ask, never close by ourselves. */
function taskDeskDone(cid){
  const d=TASKDESK.map[cid];if(!d||d.done)return;
  d.done=true;buildPager();
  toast(`“${d.title}” is done. Close its desktop?`,{kind:'ok',ms:120000,label:'Close',go:()=>taskDeskClose(cid)});
}

/* Close a task's desktop: its window goes, the desktops after it move down one. */
function taskDeskClose(cid){
  const d=TASKDESK.map[cid];if(!d)return;
  delete TASKDESK.map[cid];
  try{if(d.w&&WM.wins.get(d.w.key))closeWin(d.w)}catch(e){}
  const n=d.desk;
  WM.wins.forEach(w=>{if((w.desk||1)>n)w.desk=(w.desk||1)-1});
  Object.values(TASKDESK.map).forEach(o=>{if(o.desk>n)o.desk--});
  DESKS=Math.max(1,DESKS-1);try{localStorage.setItem('desks',DESKS)}catch(e){}
  if(curDesk>DESKS||curDesk===n){curDesk=Math.min(curDesk>n?curDesk-1:curDesk,DESKS)||1;
    try{localStorage.setItem('curDesk',curDesk)}catch(e){}}
  else if(curDesk>n){curDesk--;try{localStorage.setItem('curDesk',curDesk)}catch(e){}}
  applyDeskVisibility();buildPager();
}

/* What the pager draws for desktop i: a task's name and whether it is still working. */
function taskDeskOf(i){
  for(const cid in TASKDESK.map){const d=TASKDESK.map[cid];if(d.desk===i)return {cid,...d}}
  return null;
}
