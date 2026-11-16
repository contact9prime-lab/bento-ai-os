/* Send to your phone (phoneforward.py): carry a chat on in Telegram or WhatsApp, or send one
   answer or one story there. Asked for as "a chat response to continue in the Telegram, send the
   stage to Telegram or WhatsApp … the user can decide which chat".
   The list is this account's own chats, from the server; the page never names a chat itself.
   Names are other people's words, so everything here is text nodes.
   GUI and SUI: this dialog (a page, nothing native). TUI: nothing here; the phone's own
   /sessions and /resume reach a carried-on chat, and sending from a terminal is not built. */
var PHONE_SEND={what:'',to:''};
function psEl(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);return e}
async function phoneSend(o){
  o=o||{};
  const cid=o.cid||(typeof currentConv!=='undefined'?currentConv:'');
  if(!cid){toast('Open a chat first.');return}
  let d;
  try{d=await apiJSON('/api/phone/options?conversation='+encodeURIComponent(cid))}
  catch(e){toast('Could not load your phone chats: '+(e.message||e));return}
  document.querySelectorAll('.dlg-scrim.psend-scrim').forEach(x=>x.remove());
  const scr=psEl('div','dlg-scrim psend-scrim'),dlg=psEl('div','dlg psend');
  dlg.setAttribute('role','dialog');dlg.setAttribute('aria-modal','true');dlg.setAttribute('aria-label','Send to your phone');
  dlg.append(psEl('div','dlg-t','Send to your phone'));
  dlg.append(psEl('div','dlg-m',d.title?('From “'+d.title+'”'):'From this chat'));
  const stories=d.stories||[];
  const story=o.answer_to?stories.find(s=>s.answer_to===o.answer_to):stories[stories.length-1];
  const whats=[
    ['continue','Carry the chat on there','The phone picks up here, with everything said so far.',true],
    ['reply','The last answer',d.reply||'No answer in this chat yet.',!!d.reply],
    ['stage','The story',story?((story.scenes+' scene'+(story.scenes===1?'':'s'))+(story.question?' · '+story.question:'')):'This chat has shown no story.',!!story]];
  let what=o.what||PHONE_SEND.what||'continue';
  if(!(whats.find(w=>w[0]===what)||[])[3])what='continue';
  try{const last=JSON.parse(localStorage.getItem('phone.send')||'{}');if(!PHONE_SEND.to&&last.to)PHONE_SEND.to=last.channel+':'+last.to}catch(e){}
  const ts=d.targets||[];
  let to=(ts.find(t=>t.ready&&t.channel+':'+t.to===PHONE_SEND.to)||ts.find(t=>t.ready)||{});
  to=to.channel?to.channel+':'+to.to:'';
  dlg.append(psEl('div','psend-h','What'));
  const wbox=psEl('div','psend-list');wbox.setAttribute('role','radiogroup');wbox.setAttribute('aria-label','What to send');
  whats.forEach(w=>{const b=psEl('button','psend-row');b.type='button';b.dataset.w=w[0];b.setAttribute('role','radio');
    b.append(psEl('b','',w[1]),psEl('span','',w[2]));if(!w[3])b.disabled=true;wbox.append(b)});
  dlg.append(wbox);
  dlg.append(psEl('div','psend-h','Where'));
  const tbox=psEl('div','psend-list');tbox.setAttribute('role','radiogroup');tbox.setAttribute('aria-label','Which chat');
  if(!ts.length){const p=psEl('p','psend-none','Telegram and WhatsApp are not set up for your account yet. ');
    const a=psEl('button','psend-link','Open Channels');a.type='button';
    a.onclick=()=>{scr.remove();if(typeof placeSettings==='function')placeSettings('channels')()};p.append(a);tbox.append(p)}
  ts.forEach(t=>{const b=psEl('button','psend-row');b.type='button';b.dataset.t=t.channel+':'+t.to;b.setAttribute('role','radio');
    const kind=t.kind==='you'?'you':t.kind==='group'?'group, everyone in it sees it':'someone you let in';
    b.append(psEl('b','',(t.channel==='telegram'?'Telegram':'WhatsApp')+' · '+t.name),psEl('span','',t.ready?kind:(t.why||'cannot be reached right now')));
    if(!t.ready)b.disabled=true;tbox.append(b)});
  dlg.append(tbox);
  const said=psEl('div','psend-said');said.setAttribute('aria-live','polite');dlg.append(said);
  const bar=psEl('div','dlg-b'),no=psEl('button','','Cancel'),ok=psEl('button','dlg-ok','Send');
  no.type=ok.type='button';bar.append(no,ok);dlg.append(bar);scr.append(dlg);document.body.append(scr);
  const paint=()=>{
    wbox.querySelectorAll('.psend-row').forEach(b=>{const on=b.dataset.w===what;b.classList.toggle('on',on);b.setAttribute('aria-checked',on)});
    tbox.querySelectorAll('.psend-row').forEach(b=>{const on=b.dataset.t===to;b.classList.toggle('on',on);b.setAttribute('aria-checked',on)});
    ok.disabled=!to;ok.textContent=what==='continue'?'Carry on there':'Send'};
  wbox.querySelectorAll('.psend-row').forEach(b=>b.onclick=()=>{what=b.dataset.w;paint()});
  tbox.querySelectorAll('.psend-row').forEach(b=>b.onclick=()=>{to=b.dataset.t;paint()});
  const close=()=>{scr.remove();document.removeEventListener('keydown',key)};
  const key=e=>{if(e.key==='Escape')close()};
  document.addEventListener('keydown',key);
  no.onclick=close;scr.onclick=e=>{if(e.target===scr)close()};
  ok.onclick=async()=>{
    if(!to)return;
    const i=to.indexOf(':'),channel=to.slice(0,i),chat=to.slice(i+1);
    ok.disabled=true;said.className='psend-said';
    said.textContent=what==='stage'?'Drawing the story and sending it… this can take a minute.':'Sending…';
    let r;
    try{r=await apiJSON('/api/phone/send',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({channel,to:chat,what,conversation_id:cid,answer_to:what==='stage'&&story?story.answer_to:''})})}
    catch(e){r={ok:false,message:e.message||String(e)}}
    if(!r.ok){said.className='psend-said err';said.textContent=r.message||'It could not be sent.';ok.disabled=false;return}
    PHONE_SEND.what=what;PHONE_SEND.to=to;
    try{localStorage.setItem('phone.send',JSON.stringify({channel,to:chat}))}catch(e){}
    close();toast(r.message||'Sent.',{kind:'ok'});
    if(typeof loadConvs==='function')loadConvs();
  };
  paint();(ok.disabled?no:ok).focus();
}
/* A new session for one phone chat, started here. The phone stays where it is. */
async function phoneNewSession(channel,to){
  let r;
  try{r=await apiJSON('/api/phone/session',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({channel,to})})}
  catch(e){toast('Could not start a session: '+(e.message||e));return}
  if(!r.ok){toast(r.message||'Could not start a session.');return}
  if(typeof loadConvs==='function')await loadConvs();
  if(typeof openConv==='function')openConv(r.id);
}
