/* ================= who may talk to the agent, as tables =================
   Telegram's people and groups and WhatsApp's people, drawn by one helper: who,
   whether they are answered, when that was decided and by whom, and for a group
   the people who wrote in it, each with their own allow or block. Asked for as "the
   groups list and the people list should come in form of a table that we can see
   when it was validated and who all … in the group also you can restrict".
   Every name here is somebody else's words, so every cell goes through esc(). On a
   narrow window the rows become cards (43b-chantables.css), each value labelled.
   GUI and SUI draw this; the phone's /people, /groups and /members say the same. */
function chanWhen(ts){
  if(!ts)return '';
  const d=new Date(ts*1000);
  return d.toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'})+', '
    +d.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});
}
function chanDecided(r){
  if(!r.decided_at)return '<span class="mut">not recorded</span>';
  return esc(chanWhen(r.decided_at))+(r.decided_by?`<small>${esc(r.decided_by)}</small>`:'');
}
function chanBadge(ok,word){return `<span class="badge ${ok?'ok':'err'}">${esc(word)}</span>`}
function chanTable(heads,rows,empty){
  if(!rows.length)return `<p class="mut ct-empty">${esc(empty)}</p>`;
  return `<div class="whotw"><table class="whotab"><thead><tr>${heads.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${rows.join('')}</tbody></table></div>`;
}
function chanCells(heads,cells){
  return cells.map((c,i)=>`<td data-l="${esc(heads[i]||'')}">${c}</td>`).join('');
}

/* ---- Telegram ---- */
var TG_PEOPLE_H=['Who','Status','Decided','Messages','Last wrote',''];
var TG_GROUP_H=['Group','Status','Who may talk','Decided','Wrote',''];
var TG_MEMBER_H=['Person','Answered','Decided','Messages','Last wrote',''];
function tgPeopleTable(d){
  const rows=(d.people||[]).map(c=>`<tr>${chanCells(TG_PEOPLE_H,[
    `<b>${esc(c.title||c.chat_id)}</b>${c.username?` <span class="mut">@${esc(c.username)}</span>`:''}${c.owner?' <span class="badge ok">owner</span>':''}<small>${esc(c.chat_id)}</small>`,
    chanBadge(c.allowed,c.allowed?'let in':'blocked'),
    chanDecided(c),
    esc(c.msg_count||0),
    esc(chanWhen(c.last_seen)),
    c.owner?'':`<span class="ct-act"><button class="endbtn" onclick="tgAllow(${+c.chat_id},${c.allowed?0:1})">${c.allowed?'Block':'Allow'}</button>
      <button class="endbtn" title="Forget this chat" onclick="tgDelChat(${+c.chat_id})">Forget</button></span>`])}</tr>`);
  return chanTable(TG_PEOPLE_H,rows,'Nobody has written yet.');
}
function tgGroupsTable(d){
  const on=!!d.groups_on;
  const rows=(d.group_rows||[]).map(g=>{
    const ms=g.members||[],picked=ms.filter(m=>m.state==='allowed').length;
    const status=!g.allowed?chanBadge(false,'blocked'):on?chanBadge(true,'answered'):chanBadge(false,'groups are off');
    const who=`<select class="ct-sel" aria-label="Who may talk in ${esc(g.title||g.chat_id)}" onchange="tgMembersOnly(${+g.chat_id},this.value==='1')">
        <option value="0"${g.members_only?'':' selected'}>Everybody in it</option>
        <option value="1"${g.members_only?' selected':''}>Only people I pick${g.members_only?' ('+picked+')':''}</option></select>`;
    const head=`<tr>${chanCells(TG_GROUP_H,[
      `<b>${esc(g.title||g.chat_id)}</b><small>${esc(g.type)} · ${esc(g.chat_id)}</small>`,
      status,who,chanDecided(g),esc(ms.length)+(ms.length===1?' person':' people'),
      `<span class="ct-act"><button class="endbtn" onclick="tgAllow(${+g.chat_id},${g.allowed?0:1})">${g.allowed?'Stop':'Allow'}</button>
        <button class="endbtn" title="Forget this group" onclick="tgDelChat(${+g.chat_id})">Forget</button></span>`])}</tr>`;
    const mrows=ms.map(m=>`<tr>${chanCells(TG_MEMBER_H,[
      `<b>${esc(m.name||m.member_id)}</b>${m.username?` <span class="mut">@${esc(m.username)}</span>`:''}${m.owner?' <span class="badge ok">owner</span>':''}`,
      chanBadge(m.talks,m.talks?'yes':(m.state==='blocked'?'blocked':'not picked')),
      m.state?chanDecided(m):'<span class="mut">the group’s rule</span>',
      esc(m.msg_count||0),esc(chanWhen(m.last_seen)),
      m.owner?'':`<span class="ct-act"><button class="endbtn" onclick="tgMember(${+g.chat_id},'${jsq(m.member_id)}','${jsq(m.talks?'blocked':'allowed')}')">${m.talks?'Block':'Allow'}</button>
        ${m.state?`<button class="endbtn" title="Back to the group’s rule" onclick="tgMember(${+g.chat_id},'${jsq(m.member_id)}','')">Reset</button>`:''}</span>`])}</tr>`);
    const inner=ms.length?chanTable(TG_MEMBER_H,mrows,''):'<p class="mut ct-empty">Nobody has written to the agent in this group yet.</p>';
    return head+`<tr class="ct-sub"><td colspan="${TG_GROUP_H.length}"><details${g.allowed&&ms.length?' open':''}>
      <summary>Who wrote in ${esc(g.title||g.chat_id)}</summary>${inner}</details></td></tr>`;
  });
  return chanTable(TG_GROUP_H,rows,'No group has written yet. Add the bot to a group and write to it there.');
}
async function tgMembersOnly(id,on){
  await fetch('/api/telegram/chats/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({members_only:!!on})});
  toast(on?'Only the people you pick are answered there.':'Everybody in that group is answered.');refreshApp('telegram');
}
async function tgMember(id,member,state){
  const r=await fetch('/api/telegram/chats/'+id+'/members/'+encodeURIComponent(member),
    {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({state})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok||d.ok===false)toast('Could not change that: '+(d.message||d.error||r.status));
  refreshApp('telegram');
}

/* ---- WhatsApp ---- */
var WA_PEOPLE_H=['Who','Status','Decided','Messages','Last wrote',''];
function waPeopleTable(d){
  const rows=(d.chats||[]).map(c=>{
    const own=c.wa_id===d.owner_wa_id;
    return `<tr>${chanCells(WA_PEOPLE_H,[
      `<b>${esc(c.name||'+'+c.wa_id)}</b>${own?' <span class="badge ok">owner</span>':''}<small>+${esc(c.wa_id)}</small>`,
      chanBadge(c.allowed,c.allowed?'let in':'blocked'),
      chanDecided(c),esc(c.msg_count||0),esc(chanWhen(c.last_seen)),
      own?'':`<span class="ct-act"><button class="endbtn" onclick="waAllow('${jsq(c.wa_id)}',${c.allowed?0:1})">${c.allowed?'Block':'Allow'}</button></span>`])}</tr>`;
  });
  return `<div class="wa-line"><b>Who may talk to the agent here</b> ${pInfo('Everybody who wrote in. A new number is blocked until you allow it, here or from your phone.')}</div>`
    +chanTable(WA_PEOPLE_H,rows,'Nobody has written yet.');
}
